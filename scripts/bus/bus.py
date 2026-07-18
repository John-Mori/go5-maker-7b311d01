#!/usr/bin/env python3
"""SQLiteメッセージバス — 検証用プロトタイプ (Phase 0 / 2026-07-18)。

★★正本は scripts/queue/leasequeue.py(研究室裁定2026-07-18でバスは一本化)★★
  本日バスが3系統並行実装されたため leasequeue.py に統一。本ファイルはPhase 0の
  「独立検証プロトタイプ」として役目完了(第三者検証=データ整理部門で 5/5 + 4/4 PASS、
  設計も他2系統と独立に一致)。本番運用はleasequeueを使うこと。以下は検証の証跡として残置。

★これは独立した新規モジュールで、本番の配線には一切つながっていない★
  現行の鳩(inbox_poller)・sweep・JSONL箱・processed台帳には手を触れない。
  ここで「並行クレームで二重取得しない/重複msg_idが弾かれる/リース失効で再配達される」を
  実測で証明し、本番統合(Phase 1=鳩の書き込み先変更・各セッションのドレイン手順変更)は
  改修部門+Chami承認で行う。人事はここまで(独立プロトタイプの検証)。

設計の出典 = docs/設計・調査/調査_エージェント運用の恒久改善_世界のOSSサーベイ_2026-07-18.md §3提案A
  litequeue方式の1文アトミッククレーム / SQSのvisibility timeout(リース) /
  outboxパターン(状態変更と結果記録を同一トランザクション) / msg_id主キーによる冪等化。

これ1つが将来置換するもの:
  - mvドレイン窓での喪失(INC-76/100)  → クレームは単一UPDATEで隙間が無い
  - 共有processed台帳への並行追記による記録消失(2026-07-16実測) → 1行1トランザクション
  - sweepのdept名ヒューリスティック誤爆(INC-86)                 → statusカラムで判定・推測しない
  - 処理済みの人力確認による二重処理(INC-87)                   → status + msg_id主キーで自動dedup
  - waiterの再武装忘れがハングになる問題                        → リース失効で自動再配達

使い方(ライブラリ):
  from bus import Bus
  bus = Bus("local/bus/bus.db")
  bus.enqueue("msgid-1", dept="hr-room", channel="...", author="chami", body="...")
  claimed = bus.claim(dept="hr-room", worker="hr-session-A", lease_sec=900)  # or None
  if claimed: bus.complete(claimed["msg_id"], result="ok")
  bus.sweep_expired()   # リース切れをpendingへ戻す(=再配達)

CLI(点検用): python scripts/bus/bus.py --db local/bus/bus.db --stats
"""
import argparse
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
    msg_id           TEXT PRIMARY KEY,          -- Discord message id 等。冪等キー(重複INSERTは弾く)
    dept             TEXT NOT NULL,
    channel          TEXT,
    author           TEXT,
    body             TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending / claimed / done / failed
    created_at       REAL NOT NULL,
    claimed_by       TEXT,
    claimed_at       REAL,
    lease_expires_at REAL,
    attempts         INTEGER NOT NULL DEFAULT 0,
    result           TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_dept_status ON messages(dept, status);
"""


def _now():
    return time.time()


class Bus:
    def __init__(self, db_path, busy_timeout_ms=5000):
        self.db_path = db_path
        d = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(d, exist_ok=True)
        self._init_db(busy_timeout_ms)

    def _connect(self):
        # 各呼び出し/スレッドで独立接続を開く(SQLite接続はスレッド跨ぎ共有不可)。
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")       # 並行read/単一writeの両立(huey #445の教訓)
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")      # 'database is locked' の緩和(必須)
        return conn

    def _init_db(self, busy_timeout_ms):
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def enqueue(self, msg_id, dept, channel="", author="", body=""):
        """1メッセージ投入。msg_idが既にあれば黙って無視(=冪等・二重投入で増えない)。
        戻り値: 新規に入ったらTrue / 既存で弾かれたらFalse。"""
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO messages(msg_id,dept,channel,author,body,status,created_at)"
                " VALUES(?,?,?,?,?, 'pending', ?)",
                (msg_id, dept, channel, author, body, _now()))
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()

    def claim(self, dept, worker, lease_sec=900):
        """その部門のpending(またはリース切れのclaimed)を1件、アトミックに取得する。
        litequeue方式の単一UPDATE…RETURNING。取れなければNone。
        取得した瞬間にstatus=claimed・lease_expires_atがセットされるので、
        同時に別ワーカーが呼んでも同じ行は二重に取れない。"""
        now = _now()
        conn = self._connect()
        try:
            row = conn.execute(
                "UPDATE messages"
                "   SET status='claimed', claimed_by=?, claimed_at=?, lease_expires_at=?,"
                "       attempts=attempts+1"
                " WHERE msg_id=("
                "     SELECT msg_id FROM messages"
                "      WHERE dept=? AND (status='pending'"
                "            OR (status='claimed' AND lease_expires_at < ?))"
                "      ORDER BY created_at LIMIT 1)"
                " RETURNING *",
                (worker, now, now + lease_sec, dept, now)).fetchone()
            conn.commit()
            return dict(row) if row else None
        finally:
            conn.close()

    def complete(self, msg_id, result="ok"):
        """処理完了。状態変更と結果記録を同一トランザクションで(=outboxパターン)。
        「返信は送ったが記録が飛ぶ」不整合が原理的に起きない。"""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE messages SET status='done', result=? WHERE msg_id=? AND status='claimed'",
                (result, msg_id))
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()

    def fail(self, msg_id, err=""):
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE messages SET status='failed', result=? WHERE msg_id=?",
                (err, msg_id))
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()

    def sweep_expired(self):
        """リース切れのclaimedをpendingへ戻す(=再配達)。処理中に死んだワーカーの分が甦る。
        戻り値: 戻した件数。"""
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE messages SET status='pending', claimed_by=NULL, lease_expires_at=NULL"
                " WHERE status='claimed' AND lease_expires_at < ?", (_now(),))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def stats(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT dept, status, COUNT(*) n FROM messages GROUP BY dept, status"
                " ORDER BY dept, status").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def main():
    ap = argparse.ArgumentParser(description="SQLiteメッセージバス(検証用プロトタイプ)")
    ap.add_argument("--db", default="local/bus/bus.db")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()
    bus = Bus(args.db)
    if args.sweep:
        print(f"sweep: {bus.sweep_expired()}件をpendingへ戻した")
    if args.stats or not args.sweep:
        for r in bus.stats():
            print(f"  {r['dept']:20} {r['status']:8} {r['n']}")


if __name__ == "__main__":
    main()
