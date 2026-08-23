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

2026-08-06 追加 (Chami「1番困る部類の出来事。反応がない」msg 1534698574837714984):
  7. ★**人の便が機械の便に追い越されない**。claim は prio(Chami本人=0 / それ以外=5)→id の
     順で選ぶ。毎朝8時の自動巡回が全部門へ一斉投入された直後にChamiが喋ると、旧FIFOでは
     必ず自動便の後ろに並んだ (実測=下の PRIO_CHAMI のコメント)。判定できない便は
     PRIO_NORMAL へ倒す=優先度は門ではないので、誤判定で便が止まることはない。
"""
import json
import os
import sqlite3
import time

# 状態: pending(未処理) → (claim) → 見えない期間はlease_untilで表現 → ack で status='done'。
# dead は毒メッセージの隔離。done行は台帳として残す (削除は purge_done のみ)。
DEFAULT_LEASE_SEC = 900          # 既定リース (処理猶予)。INC-94の実測(処理は数分〜十数分)より長く
DEFAULT_MAX_DELIVERIES = 5       # これを超えたら dead-letter

# ★2026-08-14 追加 (研究室HQ DISPATCH-aegis-gl-1786643264450 / 実測 01:04〜02:44 JST)。
#   何が起きたか= Claude CLI の**セッション上限**(You've hit your session limit)に当たると
#   relay が rc=1 で即座に返る。今の作りは「相手が一時的に受けられない」と「この便自体が
#   毒」を**同じ deliveries カウンタ**で数えていたため、外部要因の数十分で正常な便が
#   max_deliveries に達して dead へ落ちた。実害= Chamiの便 msg 1537508993923154042 が
#   deliveries=6 / status=dead。**dead は二度と拾われない=黙って消える。**
#   → 外部要因と分かっている失敗は `nack(refund=True)` で回数を**返金**し、
#     `retry_after` でリセット時刻まで寝かせる (共通規律§3「可用性は fail-open」)。
#   ★返金にも打ち止めが要る= 「外部要因」の名を借りた無限ループを作らないため。
#     60回 = 上限の窓が数時間続いても足りる幅で、かつ永久には回らない。
DEFAULT_MAX_REFUNDS = 60

# --- 優先度 (2026-08-06 追加・小さいほど先に処理される) ---------------------------
#   なぜ要るか= claim は厳密FIFO(ORDER BY id)だった。毎朝8時に自動便(絵文字巡回・日次
#   振り返り)が全部門へ一斉投入され、部門デーモンは1件ずつしか処理しないので、その直後に
#   Chamiが喋ると**必ず自動便の後ろに並ぶ**。実測 2026-08-06: プラットフォームSEの箱で
#   08:00:33 に絵文字巡回便(id=2154)がclaimされ、08:03:06 のChamiの便(id=2158)は未claimの
#   まま置かれた → 08:04:12 に「反応がない」。人の便を機械の便が追い越す構造だった。
#   直し方= Chami本人の便だけを先頭へ寄せる。判定できない便は従来どおり(fail-open)。
PRIO_CHAMI = 0                   # Chami本人の発言 = 常に最優先
PRIO_NORMAL = 5                  # それ以外 (部門間のdispatch・自動巡回・機械の便)
CHAMI_AUTHORS = ("chami_fusoh",)
CHAMI_AUTHOR_ID = "490925528367497227"


def prio_of(body):
    """便の本文(JSON文字列 or dict)から優先度を決める。純粋関数=テストできる。

    ★判定できない形(JSONでない・authorが無い)は **PRIO_NORMAL** に倒す。優先度は
    「速く出す」ための仕掛けであって門ではない。誤判定で便が止まる方が事故だ。
    """
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return PRIO_NORMAL
    if not isinstance(body, dict):
        return PRIO_NORMAL
    author = (body.get("author") or "").strip()
    if author in CHAMI_AUTHORS:
        return PRIO_CHAMI
    if str(body.get("author_id") or "") == CHAMI_AUTHOR_ID:
        return PRIO_CHAMI
    return PRIO_NORMAL


class LeaseQueue:
    def __init__(self, path, lease_sec=DEFAULT_LEASE_SEC, max_deliveries=DEFAULT_MAX_DELIVERIES,
                 max_refunds=DEFAULT_MAX_REFUNDS):
        self.path = path
        self.lease_sec = lease_sec
        self.max_deliveries = max_deliveries
        self.max_refunds = max_refunds
        # ★dead へ落ちる瞬間に呼ばれるフック(既定 None=誰も設定しなければ従来と1バイト差なし)。
        #   呼び側(dept_daemon)が「Chamiが読む場所へ1行出す」ために使う。
        #   フックが例外を投げてもキューは止めない(通知の失敗で配送機構を殺さない)。
        self.on_dead = None
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
                result       TEXT NOT NULL DEFAULT '',
                prio         INTEGER NOT NULL DEFAULT 5   -- 小さいほど先。Chami本人=0
            );
            CREATE INDEX IF NOT EXISTS idx_ready ON queue(status, lease_until);
            CREATE TABLE IF NOT EXISTS counters (
                name TEXT PRIMARY KEY,
                n    INTEGER NOT NULL
            );
            """
        )
        # --- 既存DBへの追加 (2026-08-06)。ALTERは「列が無い時だけ」通る=冪等。
        #     既に走っている本番の inbox.db を壊さずに prio を足すための経路。
        cols = [r[1] for r in self._db.execute("PRAGMA table_info(queue)").fetchall()]
        if "prio" not in cols:
            self._db.execute("ALTER TABLE queue ADD COLUMN prio INTEGER NOT NULL DEFAULT 5")
            # 移行の瞬間に既に並んでいる未処理便へも効かせる (待たされている本人の便を救う)。
            # done/dead は触らない=台帳としての過去は書き換えない。
            for qid, body in self._db.execute(
                    "SELECT id, body FROM queue WHERE status='pending'").fetchall():
                p = prio_of(body)
                if p != PRIO_NORMAL:
                    self._db.execute("UPDATE queue SET prio=? WHERE id=?", (p, qid))
        # --- 既存DBへの追加 (2026-08-14)。返金した回数=「外部要因で数えなかった」回数。
        #     ALTERは列が無い時だけ通る=冪等。既存行は0で始まる(過去は書き換えない)。
        if "refunds" not in cols:
            self._db.execute("ALTER TABLE queue ADD COLUMN refunds INTEGER NOT NULL DEFAULT 0")
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ready_prio ON queue(status, lease_until, prio, id)")

    # --- 書き込み ---
    def enqueue(self, body, msg_id=None, dept=None, not_before=0.0):
        """1件投入。msg_id が既存なら二重投入を無視 (冪等)。投入できたら True。

        not_before(2026-08-24 イージス研究室・C-059 の止血): **その時刻まで claim させない**
          epoch秒。0 なら従来どおり即時に取れる(既存の呼び出しは1文字も変わらない)。
          ★新しい仕組みを足していない= claim は既に `lease_until < now` で絞っている
            (上の claim を参照)。だから lease_until を未来に置けば、便は**キューの中に
            見える形で座ったまま**その時刻に自然と配れるようになる。
          ★これは**捨てるのではなく遅らせる**ための口だ(C-048=喪失禁止)。行は最初から
            status='pending' で存在するので、`SELECT ... WHERE lease_until > now` で
            「今どれだけ待たされているか」を外から数えられる。
        """
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False)
        try:
            cur = self._db.execute(
                "INSERT INTO queue(msg_id, dept, body, enqueued_at, prio, lease_until)"
                " VALUES(?,?,?,?,?,?)",
                (msg_id, dept, body, time.time(), prio_of(body), float(not_before or 0.0)),
            )
            return cur.rowcount == 1
        except sqlite3.IntegrityError:
            return False  # msg_id 重複 = 既に入っている

    # --- 優先度の自己修復 (2026-08-06) ---
    #   実測で分かったこと= prio は enqueue した**プロセス**が書く。ところが投函側
    #   (scripts/queue/discord_gateway.py) は 07-29 19:00 起動の常駐で、古い leasequeue を
    #   メモリに抱えたまま走っていた。結果、claim側だけ新しくなり、08:05〜08:39 の
    #   Chami便 5件が**全部 prio=5 のまま**入った(id=2160/2163/2169/2170/2172)。
    #   ★「入れる側と出す側の版が揃っている」という前提に優先度を乗せていたのが誤り。
    #   → **prio は body から導ける**ので、claim の直前に未処理行を見て食い違いを直す。
    #     これで投函側が古かろうが順番は正しくなる(常駐の再起動に依存しない)。
    #     書き込むのは食い違った行だけ=通常は読むだけで終わる。
    def _repair_prio(self):
        rows = self._db.execute(
            "SELECT id, body FROM queue WHERE status='pending' AND prio=? LIMIT 500",
            (PRIO_NORMAL,)).fetchall()
        fix = []
        for qid, body in rows:
            p = prio_of(body)
            if p != PRIO_NORMAL:
                fix.append((p, qid))
        if not fix:
            return 0
        try:
            with self._db:
                self._db.executemany("UPDATE queue SET prio=? WHERE id=?", fix)
        except sqlite3.OperationalError:
            return 0   # 競合したら次のclaimで直せばよい (可用性を止めない)
        return len(fix)

    # --- クレーム (原子的占有) ---
    def claim(self, dept=None, who=""):
        """処理可能な1件を占有して返す。無ければ None。who=処理者名 (台帳に残る)。

        「未処理 or リース切れ」の1件を、**優先度→投入順**で選び lease_until を延ばして掴む。
        BEGIN IMMEDIATE で書き込みロックを取ってから RETURNING するため、同時claimでも
        同一行は1者にしか渡らない。
        ★prio が同じ便どうしは従来どおり厳密FIFO(id昇順)=順序の保証は壊れていない。
        """
        self._repair_prio()   # 投函側が古くても順番が狂わないようにする (上のコメント参照)
        now = time.time()
        where_dept = "AND dept = ?" if dept else ""
        # SQLite は UPDATE ... LIMIT を既定ビルドで許さないので、対象idを副問い合わせで1件に絞る。
        sql = f"""
            UPDATE queue
               SET lease_until = ?, deliveries = deliveries + 1, claimed_by = ?
             WHERE id = (
                 SELECT id FROM queue
                  WHERE status='pending' AND lease_until < ? {where_dept}
                  ORDER BY prio, id LIMIT 1
             )
         RETURNING id, msg_id, dept, body, deliveries, prio
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
        qid, msg_id, dept_v, body, deliveries, prio = row
        # max_deliveries 超過は毒メッセージ → dead-letter へ隔離し、次を返さない (呼び側は再claim)
        if deliveries > self.max_deliveries:
            self._db.execute("UPDATE queue SET status='dead' WHERE id=?", (qid,))
            self._announce_dead(qid, msg_id, dept_v, body, deliveries)
            return None
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {"_raw": body}
        return {"id": qid, "msg_id": msg_id, "dept": dept_v,
                "deliveries": deliveries, "prio": prio, "body": parsed}

    # --- 完了・失敗 ---
    def ack(self, qid, result=""):
        """処理完了。行は消さず done に変える=これが処理済み台帳になる (INC-103)。
        消すと再投入時の冪等照合 (msg_id UNIQUE) の相手も消え、二重処理が復活するため。"""
        cur = self._db.execute(
            "UPDATE queue SET status='done', acked_at=?, result=? WHERE id=? AND status='pending'",
            (time.time(), str(result)[:2000], qid))
        return cur.rowcount == 1

    def nack(self, qid, retry_after=None, refund=False):
        """処理失敗・手放す。lease を即時解放して他ワーカーが拾えるようにする (再配布は次のclaimで)。

        ★2026-08-14 追加の2引数(既定は従来と完全に同じ挙動)=
          retry_after: この**エポック秒まで**再配達しない(lease_until をそこまで伸ばす)。
                       Claude CLIの上限エラーは `resets 2:40am` と復帰時刻を教えてくれるので、
                       それまで叩かない=無駄な試行で回数を溶かさない。
          refund:      この試行を**無かったことにする**(deliveries を1つ戻す)。
                       「相手が一時的に受けられない」を毒メッセージと同じ数え方にしないため。
                       ★返金は max_refunds 回まで。使い切ったら普通の失敗として数える
                         (外部要因を名乗る無限ループを作らない)。
        戻り値= {"refunded": bool, "retry_after": float, "refunds": int}
        """
        until = float(retry_after or 0)
        if not refund:
            self._db.execute("UPDATE queue SET lease_until=? WHERE id=? AND status='pending'",
                             (until, qid))
            return {"refunded": False, "retry_after": until, "refunds": None}
        row = self._db.execute(
            "SELECT deliveries, refunds FROM queue WHERE id=? AND status='pending'", (qid,)).fetchone()
        if not row:
            return {"refunded": False, "retry_after": until, "refunds": None}
        deliveries, refunds = row[0], row[1] or 0
        if refunds >= self.max_refunds:
            # ★打ち止め。ここから先は普通に数える=いつかは dead になり、通知が出る(黙らない)。
            self._db.execute("UPDATE queue SET lease_until=? WHERE id=? AND status='pending'",
                             (until, qid))
            return {"refunded": False, "retry_after": until, "refunds": refunds}
        self._db.execute(
            "UPDATE queue SET lease_until=?, deliveries=MAX(deliveries-1,0), refunds=refunds+1"
            " WHERE id=? AND status='pending'", (until, qid))
        return {"refunded": True, "retry_after": until, "refunds": refunds + 1}

    def _announce_dead(self, qid, msg_id, dept, body, deliveries):
        """★dead へ落ちた瞬間に「落ちた」を残す(2026-08-14)。

        なぜ要るか= 今までは dead になっても**どこにも出なかった**。Chamiから見ると
        「返事が来ない」だけで、消えたことすら分からない(共通規律§4「警報は受け手が読む
        場所へ出す」)。ここでは2つやる:
          ① DBの隣に `dead_letters.jsonl` を1行(**通知が失敗しても消えない記録**)。
          ② on_dead フックがあれば呼ぶ(呼び側が部屋へ出す)。
        ★どちらが失敗してもキューは止めない= 通知の不調で配送機構を殺さない。
        """
        try:
            rec = json.loads(body) if isinstance(body, str) else (body or {})
        except Exception:
            rec = {"_raw": str(body)[:500]}
        info = {"ts": time.time(), "id": qid, "msg_id": msg_id, "dept": dept,
                "deliveries": deliveries, "body": rec}
        try:
            d = os.path.dirname(self.path)
            with open(os.path.join(d, "dead_letters.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(info, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if self.on_dead:
            try:
                self.on_dead(info)
            except Exception:
                pass

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

    def peek_ready(self, dept=None, limit=50):
        """★claim/ackせずに、いま取れる便を覗くだけ(2026-08-08 イージス研究室)。

        claim() と**同じ並び**(prio→id)で、同じ条件(pending かつ リース失効)の行を返す。
        リースも deliveries も**1ミリも触らない**ので、覗いただけで便が消えたり
        再配達の回数を減らしたりしない=「掴む前に、掴むかどうかを決める」ための道具。
        用途= 受信側の集約窓(連投が落ち着いたか判定する。dept_daemon._coalesce_hold)。
        body は claim() と揃えて**dictへ復元して返す**(呼び側で分岐を増やさない)。
        """
        now = time.time()
        sql = ("SELECT id, msg_id, dept, body, enqueued_at, prio FROM queue"
               " WHERE status='pending' AND lease_until < ?")
        args = [now]
        if dept:
            sql += " AND dept=?"
            args.append(dept)
        sql += " ORDER BY prio, id LIMIT ?"
        args.append(int(limit))
        out = []
        for r in self._db.execute(sql, args):
            body = r[3]
            try:
                body = json.loads(body) if isinstance(body, str) else body
            except Exception:
                pass
            out.append({"id": r[0], "msg_id": r[1], "dept": r[2], "body": body,
                        "enqueued_at": r[4], "prio": r[5]})
        return out

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

    def abandoned(self, older_sec, dept=None):
        """リースが切れたまま放置の未処理行 (claim経験の有無を問わない・2026-07-18 QA追加)。

        stale_pending()はdeliveries=0限定のため、一度claimされnackされた行 (例: 代打が
        機微をリース返却した行) が検出外に落ちる (研究室指摘)。エスカレート判定はこちらを使う:
        「pending かつ リース失効 かつ enqueueからolder_sec経過」= いま誰も働いていない放置全部。
        処理中 (リース有効) の行は含まない。"""
        now = time.time()
        sql = ("SELECT id, msg_id, dept, body, enqueued_at, deliveries FROM queue"
               " WHERE status='pending' AND lease_until < ? AND enqueued_at < ?")
        args = [now, now - older_sec]
        if dept:
            sql += " AND dept=?"
            args.append(dept)
        sql += " ORDER BY id"
        return [{"id": r[0], "msg_id": r[1], "dept": r[2], "body": r[3],
                 "enqueued_at": r[4], "deliveries": r[5]}
                for r in self._db.execute(sql, args)]

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
