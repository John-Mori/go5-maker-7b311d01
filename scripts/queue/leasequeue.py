#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LeaseQueue — SQLite1ファイルの「リース式」メッセージキュー (恒久解 案A・基盤部品)。

なぜ作るか (OSS調査 2026-07-18 の結論):
  現行の「JSONLファイル+mv+ディレクトリ走査」は、トランザクションもack概念も無いため
  INC-85(働く窓から箱を強奪)/INC-86(退避ファイルの黙食い)/INC-94(通知前に奪う)/
  INC-103(箱空≠処理済)を構造的に生む。これらは「クレーム→リース→ack、リース切れで
  自動再配布」を備えたキューでは**起こり得ない**。フル装備の既製SQLite品は世界に無い
  (litequeue 228★は半分まで)ので、WALモード+RETURNINGで最小自作する。

不変条件 (これがインシデント族の絶滅を保証する):
  1. claim は「未クレーム or リース期限切れ」の1件を**原子的に**占有し lease_until を延ばす。
     2つのワーカーが同時にclaimしても、同じ行は片方にしか渡らない (BEGIN IMMEDIATE + RETURNING)。
  2. 処理中にワーカーが死ぬ → lease_until を過ぎる → 次のclaimで自動的に再配布される
     (メッセージは消えない = INC-86/94)。
  3. ack で初めて done。ack しない限り「処理済」にならない (箱空≠処理済の消滅 = INC-103)。
  4. enqueue は msg_id UNIQUE で冪等 (鳩が同じDiscordメッセージを二度入れても二重処理しない)。
  5. deliveries が max_deliveries を超えたら dead-letter (毒メッセージで無限ループしない)。

依存ゼロ (標準ライブラリのみ)。1ファイル=既存のバックアップ機構にそのまま乗る。
本モジュールは「部品」であり、まだ本番の受信経路には配線しない (strangler移行はPoC後)。

2026-07-18 研究室統合 (Chami実装Go・並行実装だったgo5busを本モジュールへ一本化):
  6. ★ackは行を**消さずdoneに変える** (旧実装は削除だった)。行を消すと、鳩の再起動などで
     同じmsg_idが再投入された時にUNIQUEの照合相手が消えており二重処理が復活する。
     「台帳だけが記憶を持つ」(INC-103) を守るにも処理済み行=台帳そのもの。肥大化は
     purge_done() で古いdoneだけ掃除する (既定30日・監査猶予)。
  追加API: claim(who=)=誰が借りたか記録 / extend()=長い処理のリース延長 /
  stale_pending()=一度もclaimされない放置の検出 (部門が死んでいる時の救済・sweep相当) /
  next_counter()=INC-等の表示用連番の原子的採番 (採番衝突INC-99/100型の根治)。
"""
import json
import os
import sqlite3
import time

# 状態: pending(未処理) → (claim) → 見えない期間はlease_untilで表現 → ack で status='done'。
# dead は毒メッセージの隔離。done行は台帳として残す (削除は purge_done のみ)。
DEFAULT_LEASE_SEC = 900          # 既定リース (処理猶予)。INC-94の実測(処理は数分〜十数分)より長く
DEFAULT_MAX_DELIVERIES = 5       # これを超えたら dead-letter


class LeaseQueue:
    def __init__(self, path, lease_sec=DEFAULT_LEASE_SEC, max_deliveries=DEFAULT_MAX_DELIVERIES):
        self.path = path
        self.lease_sec = lease_sec
        self.max_deliveries = max_deliveries
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self):
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS queue (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id       TEXT UNIQUE,          -- 冪等キー (Discord message id 等)
                dept         TEXT,
                body         TEXT NOT NULL,        -- JSON文字列 (レコード全体)
                enqueued_at  REAL NOT NULL,
                lease_until  REAL NOT NULL DEFAULT 0,  -- これを過ぎたら再配布可
                deliveries   INTEGER NOT NULL DEFAULT 0,
                status       TEXT NOT NULL DEFAULT 'pending',  -- pending | done | dead
                claimed_by   TEXT NOT NULL DEFAULT '',
                acked_at     REAL,
                result       TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_ready ON queue(status, lease_until);
            CREATE TABLE IF NOT EXISTS counters (
                name TEXT PRIMARY KEY,
                n    INTEGER NOT NULL
            );
            """
        )

    # --- 書き込み ---
    def enqueue(self, body, msg_id=None, dept=None):
        """1件投入。msg_id が既存なら二重投入を無視 (冪等)。投入できたら True。"""
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False)
        try:
            cur = self._db.execute(
                "INSERT INTO queue(msg_id, dept, body, enqueued_at) VALUES(?,?,?,?)",
                (msg_id, dept, body, time.time()),
            )
            return cur.rowcount == 1
        except sqlite3.IntegrityError:
            return False  # msg_id 重複 = 既に入っている

    # --- クレーム (原子的占有) ---
    def claim(self, dept=None, who=""):
        """処理可能な1件を占有して返す。無ければ None。who=処理者名 (台帳に残る)。

        「未処理 or リース切れ」の最古を1件、lease_until を延ばして掴む。BEGIN IMMEDIATE で
        書き込みロックを取ってから RETURNING するため、同時claimでも同一行は1者にしか渡らない。
        """
        now = time.time()
        where_dept = "AND dept = ?" if dept else ""
        # SQLite は UPDATE ... LIMIT を既定ビルドで許さないので、対象idを副問い合わせで1件に絞る。
        sql = f"""
            UPDATE queue
               SET lease_until = ?, deliveries = deliveries + 1, claimed_by = ?
             WHERE id = (
                 SELECT id FROM queue
                  WHERE status='pending' AND lease_until < ? {where_dept}
                  ORDER BY id LIMIT 1
             )
         RETURNING id, msg_id, dept, body, deliveries
        """
        ordered = [now + self.lease_sec, who, now]
        if dept:
            ordered.append(dept)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute(sql, ordered).fetchone()
            self._db.execute("COMMIT")
        except sqlite3.OperationalError:
            self._db.execute("ROLLBACK")
            return None
        if not row:
            return None
        qid, msg_id, dept_v, body, deliveries = row
        # max_deliveries 超過は毒メッセージ → dead-letter へ隔離し、次を返さない (呼び側は再claim)
        if deliveries > self.max_deliveries:
            self._db.execute("UPDATE queue SET status='dead' WHERE id=?", (qid,))
            return None
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {"_raw": body}
        return {"id": qid, "msg_id": msg_id, "dept": dept_v,
                "deliveries": deliveries, "body": parsed}

    # --- 完了・失敗 ---
    def ack(self, qid, result=""):
        """処理完了。行は消さず done に変える=これが処理済み台帳になる (INC-103)。
        消すと再投入時の冪等照合 (msg_id UNIQUE) の相手も消え、二重処理が復活するため。"""
        cur = self._db.execute(
            "UPDATE queue SET status='done', acked_at=?, result=? WHERE id=? AND status='pending'",
            (time.time(), str(result)[:2000], qid))
        return cur.rowcount == 1

    def nack(self, qid):
        """処理失敗・手放す。lease を即時解放して他ワーカーが拾えるようにする (再配布は次のclaimで)。"""
        self._db.execute("UPDATE queue SET lease_until=0 WHERE id=? AND status='pending'", (qid,))

    def extend(self, qid, lease_sec=None):
        """長い処理のリース延長 (SQSのハートビート相当)。処理中の行のみ有効。"""
        cur = self._db.execute(
            "UPDATE queue SET lease_until=? WHERE id=? AND status='pending'",
            (time.time() + (lease_sec or self.lease_sec), qid))
        return cur.rowcount == 1

    def purge_done(self, older_sec=30 * 24 * 3600):
        """古いdone行の掃除 (テーブル肥大化対策・既定30日)。台帳の監査猶予を残して消す。"""
        cur = self._db.execute(
            "DELETE FROM queue WHERE status='done' AND acked_at < ?",
            (time.time() - older_sec,))
        return cur.rowcount

    # --- 救済・採番 ---
    def stale_pending(self, older_sec, dept=None):
        """一度もclaimされずに放置されている行 (=その部門が起きていない)。
        リース失効の自動再配布はclaim済みしか救えないため、未claim放置はこの一覧を
        研究室/sweepが定期的に見てエスカレートする (現行sweepの「mainへ回収」相当)。"""
        q = ("SELECT id, msg_id, dept, body, enqueued_at FROM queue"
             " WHERE status='pending' AND deliveries=0 AND enqueued_at < ?")
        args = [time.time() - older_sec]
        if dept:
            q += " AND dept=?"
            args.append(dept)
        q += " ORDER BY id"
        return [{"id": r[0], "msg_id": r[1], "dept": r[2], "body": r[3],
                 "enqueued_at": r[4]} for r in self._db.execute(q, args)]

    def reroute(self, qid, new_dept):
        """未処理行の宛先部門を付け替える (sweep相当のエスカレート用・2026-07-18 QA追加)。
        用途: stale_pending (誰もclaimしない放置) を 'router'(=研究室) へ回す。
        リースも解放するので、付け替え先のconsumerが即claimできる。処理済み行には効かない。"""
        cur = self._db.execute(
            "UPDATE queue SET dept=?, lease_until=0 WHERE id=? AND status='pending'",
            (new_dept, qid))
        return cur.rowcount == 1

    def next_counter(self, name):
        """表示用連番 (INC- 等) の原子的採番。共有カウンタの衝突 (INC-99/100二重) を根治。"""
        try:
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute("INSERT OR IGNORE INTO counters(name, n) VALUES(?, 0)", (name,))
            n = self._db.execute(
                "UPDATE counters SET n=n+1 WHERE name=? RETURNING n", (name,)).fetchone()[0]
            self._db.execute("COMMIT")
            return n
        except sqlite3.OperationalError:
            self._db.execute("ROLLBACK")
            raise

    # --- 観測 ---
    def stats(self):
        now = time.time()
        row = self._db.execute(
            """SELECT
                 SUM(CASE WHEN status='pending' AND lease_until < ? THEN 1 ELSE 0 END) AS ready,
                 SUM(CASE WHEN status='pending' AND lease_until >= ? THEN 1 ELSE 0 END) AS leased,
                 SUM(CASE WHEN status='dead' THEN 1 ELSE 0 END) AS dead,
                 SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done,
                 COUNT(*) AS total
               FROM queue""",
            (now, now),
        ).fetchone()
        return {"ready": row[0] or 0, "leased": row[1] or 0,
                "dead": row[2] or 0, "done": row[3] or 0, "total": row[4] or 0}

    def dead_letters(self):
        cur = self._db.execute("SELECT msg_id, dept, body FROM queue WHERE status='dead' ORDER BY id")
        return [{"msg_id": m, "dept": d, "body": b} for m, d, b in cur.fetchall()]

    def close(self):
        try:
            self._db.close()
        except sqlite3.Error:
            pass
