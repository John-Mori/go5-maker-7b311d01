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
"""
import json
import os
import sqlite3
import time

# 状態: pending(未処理) → (claim) → 見えない期間はlease_untilで表現 → ack でdone行削除。
# dead は毒メッセージの隔離。done は行削除で表現 (テーブルを小さく保つ)。
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
                status       TEXT NOT NULL DEFAULT 'pending'  -- pending | dead
            );
            CREATE INDEX IF NOT EXISTS idx_ready ON queue(status, lease_until);
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
    def claim(self, dept=None):
        """処理可能な1件を占有して返す。無ければ None。

        「未処理 or リース切れ」の最古を1件、lease_until を延ばして掴む。BEGIN IMMEDIATE で
        書き込みロックを取ってから RETURNING するため、同時claimでも同一行は1者にしか渡らない。
        """
        now = time.time()
        where_dept = "AND dept = ?" if dept else ""
        params = [now]
        if dept:
            params.append(dept)
        params += [now + self.lease_sec, now]
        # SQLite は UPDATE ... LIMIT を既定ビルドで許さないので、対象idを副問い合わせで1件に絞る。
        sql = f"""
            UPDATE queue
               SET lease_until = ?, deliveries = deliveries + 1
             WHERE id = (
                 SELECT id FROM queue
                  WHERE status='pending' AND lease_until < ? {where_dept}
                  ORDER BY id LIMIT 1
             )
         RETURNING id, msg_id, dept, body, deliveries
        """
        # params順: SET lease_until(now+lease) は先頭に来る → 並べ直す
        ordered = [now + self.lease_sec, now]
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
    def ack(self, qid):
        """処理完了。行を消す (これで初めて『処理済』になる)。"""
        self._db.execute("DELETE FROM queue WHERE id=?", (qid,))

    def nack(self, qid):
        """処理失敗・手放す。lease を即時解放して他ワーカーが拾えるようにする (再配布は次のclaimで)。"""
        self._db.execute("UPDATE queue SET lease_until=0 WHERE id=? AND status='pending'", (qid,))

    # --- 観測 ---
    def stats(self):
        now = time.time()
        row = self._db.execute(
            """SELECT
                 SUM(CASE WHEN status='pending' AND lease_until < ? THEN 1 ELSE 0 END) AS ready,
                 SUM(CASE WHEN status='pending' AND lease_until >= ? THEN 1 ELSE 0 END) AS leased,
                 SUM(CASE WHEN status='dead' THEN 1 ELSE 0 END) AS dead,
                 COUNT(*) AS total
               FROM queue""",
            (now, now),
        ).fetchone()
        return {"ready": row[0] or 0, "leased": row[1] or 0,
                "dead": row[2] or 0, "total": row[3] or 0}

    def dead_letters(self):
        cur = self._db.execute("SELECT msg_id, dept, body FROM queue WHERE status='dead' ORDER BY id")
        return [{"msg_id": m, "dept": d, "body": b} for m, d, b in cur.fetchall()]

    def close(self):
        try:
            self._db.close()
        except sqlite3.Error:
            pass
