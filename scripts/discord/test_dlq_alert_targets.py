#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""デッドレター警報の宛先が incident + hq の2室だけであることの検査(2026-08-14 イージス研究室)。

裁定= 研究室HQ DISPATCH-aegis-gl-1786644517490。
出典= Chami msg 1537520749349310605(2026-08-14 02:58 JST)「これ送られる部屋が多すぎて邪魔かな」。
  引用元= メタルギアMk.II の `⚠デッドレターが新たに発生(現在計7件)`(msg 1537515526375346247)。

壊れていた形= `check_dead_letters`(増分速報) と `check_stale_dead`(滞留警報) の両方が
  `targets = [SUMMARY_DEPT, "hq"] + [d for d in by ...]` = **当該部門にも同じ長文を配っていた**。
  02:37:45 の実発火では by が5部門 → incident + hq + 5部門 = **7室**に同一の長文が出た。

★2026-08-14 追記(HQ 2度目の指摘 DISPATCH-aegis-gl-1786646041745 への対応)=
  旧版は12項目中8項目がソースの文字列一致だった。**滞留(stale)側は滞留0件で発火しない**ため、
  宛先の2室固定をソース検査で代用していた= 本番の初発火が実質の初検証になる形だ。
  → `absence_watchdog.queue_db_path()` を差し替え点にして、**滞留が在る状態の偽DBを渡し**、
    判定・本文・宛先を**実行で**通す(§3「入力が無いなら、その状態を作って渡す」)。
  偽DBは tempfile 上の本物の sqlite= 本番の `local/queue/inbox.db` には触れず、
  bot_send も dry-run のスパイに差し替えるのでDiscordへは1通も出ない。

実行: python scripts/discord/test_dlq_alert_targets.py
"""
import os
import sqlite3
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import absence_watchdog as aw  # noqa: E402

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def fire(fn, state, db=None):
    """1回だけ発火させ、実際に出た宛先と本文を返す(送信はしない)。

    db を渡すと、その周回だけ警報が読むキューDBを偽物へ向ける(本番DBは読まない)。
    """
    sent_to = []
    orig_send, orig_db = aw.bot_send, aw.queue_db_path

    def spy(channel, body, dry_run, by_dept=False):
        sent_to.append((channel, body))
        return True

    aw.bot_send = spy
    if db:
        aw.queue_db_path = lambda: db
    try:
        fn(state, True)
    finally:
        aw.bot_send, aw.queue_db_path = orig_send, orig_db
    return sent_to


def with_db(db, fn, *a):
    """その呼び出しの間だけ、警報が読むキューDBを偽物へ向ける。"""
    orig = aw.queue_db_path
    aw.queue_db_path = lambda: db
    try:
        return fn(*a)
    finally:
        aw.queue_db_path = orig


def make_db(rows):
    """本番と同じ形の queue テーブルを持つ**偽のキューDB**を作る。

    rows= (dept, status, 何秒前に積まれたか, result, body) のタプル列。
    ★列定義は scripts/queue/leasequeue.py の CREATE TABLE と同じ形にしてある
      (検査だけ通って本番で落ちる、を避けるため)。
    """
    path = os.path.join(tempfile.mkdtemp(prefix="dlqtest_"), "inbox.db")
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE queue (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id       TEXT UNIQUE,
            dept         TEXT,
            body         TEXT NOT NULL,
            enqueued_at  REAL NOT NULL,
            lease_until  REAL NOT NULL DEFAULT 0,
            deliveries   INTEGER NOT NULL DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'pending',
            claimed_by   TEXT NOT NULL DEFAULT '',
            acked_at     REAL,
            result       TEXT NOT NULL DEFAULT '',
            prio         INTEGER NOT NULL DEFAULT 5
        );
        """
    )
    now = time.time()
    for i, row in enumerate(rows):
        # ★6つ目に id を書くと、その id で入る(=**投函順と死ぬ順がずれた状態**を作れる)。
        dept, status, age_sec, result, body = row[:5]
        rid = row[5] if len(row) > 5 else None
        if rid is None:
            con.execute(
                "INSERT INTO queue (msg_id, dept, body, enqueued_at, deliveries, status, result) "
                "VALUES (?,?,?,?,?,?,?)",
                (f"M-{i}", dept, body, now - age_sec, 5, status, result),
            )
        else:
            con.execute(
                "INSERT INTO queue (id, msg_id, dept, body, enqueued_at, deliveries, status, result) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (rid, f"M-{i}", dept, body, now - age_sec, 5, status, result),
            )
    con.commit()
    con.close()
    return path


def main():
    # =====================================================================
    # A) 偽DBを差し込んで**実行で**通す(滞留0件でも経路を通せる= HQ指摘への対応)
    # =====================================================================
    H = 3600
    print("A) 偽のキューDBで警報を実際に発火させる(本番DBには触らない)")

    # --- A-1 滞留警報= 6時間超・手当ての印が無いdeadが3部門に在る状態を作って発火させる ---
    db = make_db([
        ("aegis-gl", "dead", 7 * H, "", '{"author": "someone"}'),
        ("llm-qa", "dead", 30 * H, "", '{"author": "someone"}'),
        ("llm-qa", "dead", 9 * H, "", '{"author": "someone"}'),
        ("platform-se", "dead", 8 * H, "", '{"author": "someone"}'),
        # ↓鳴ってはいけない行(混ぜておく=判定が生きていることを同時に押さえる)
        ("router", "dead", 1 * H, "", '{"author": "someone"}'),          # 6時間未満
        ("system-engineer", "dead", 20 * H, "ack済", '{"author": "x"}'),  # 手当ての印あり
        ("hr-room", "pending", 40 * H, "", '{"author": "someone"}'),      # deadではない
    ])
    total, by, oldest, chami = with_db(db, aw.stale_dead_summary)
    print(f"  偽DBの実測(滞留): 計{total}件 / 内訳 {by} / 最古 {int(oldest//3600)}時間前 / Chami発 {chami}件")
    check("★滞留の判定が実行で効く= 6時間未満・ack済・pending は数えない(4件だけ)",
          total == 4 and set(by) == {"aegis-gl", "llm-qa", "platform-se"})

    st = {"last_stale_dead_alert": 0}
    sent = fire(aw.check_stale_dead, st, db=db)
    depts = [c for c, _ in sent]
    body = sent[0][1] if sent else ""
    print(f"  → 滞留警報の宛先(実発火): {depts}")
    check("★★滞留警報が**実行で**2室(incident・hq)だけへ出る",
          depts == [aw.SUMMARY_DEPT, "hq"])
    check("★★滞留の当該部門へは出ない(3部門詰まっていても増えない)",
          all(d not in depts for d in by))
    check("本文に部門の内訳が残る= 2室で詰まり先が読める",
          "aegis-gl" in body and "llm-qa" in body and "platform-se" in body)
    check("本文の最古が実データどおり(30時間前)", "30時間前" in body)
    check("Chami発が無いので見出しは🔥ではない", body.startswith("🕳"))
    check("1日1回の上限が効く= 直後の2回目は鳴らない",
          fire(aw.check_stale_dead, st, db=db) == [])

    # --- A-2 Chami本人の便が沈んでいる時だけ 🔥 に上がる(重大度の分岐も実行で見る) ---
    db2 = make_db([
        ("aegis-gl", "dead", 7 * H, "", '{"author": "chami", "content": "この部屋、応答できる?"}'),
        ("llm-qa", "dead", 8 * H, "", '{"author": "someone"}'),
    ])
    sent2 = fire(aw.check_stale_dead, {"last_stale_dead_alert": 0}, db=db2)
    body2 = sent2[0][1] if sent2 else ""
    check("★Chamiの便が沈んでいたら見出しが🔥に上がる(2026-08-12の13日間沈黙の再発防止)",
          body2.startswith("🔥") and "1件" in body2)
    check("🔥でも宛先は2室のまま(重大度で宛先を増やさない)",
          [c for c, _ in sent2] == [aw.SUMMARY_DEPT, "hq"])

    # --- A-3 増分速報も同じ偽DBで通す(基準id・前進判定・宛先) ---
    st3 = {}
    check("★新コードの初回は既存deadを基準として黙って取り込む(過去分で鳴らない)",
          fire(aw.check_dead_letters, st3, db=db) == [] and st3.get("last_dead_max_id", 0) > 0)
    st4 = {"last_dead_max_id": 0, "last_dead_alert": 0}
    sent4 = fire(aw.check_dead_letters, st4, db=db)
    depts4 = [c for c, _ in sent4]
    print(f"  → 増分速報の宛先(実発火): {depts4}")
    check("★★増分速報が**実行で**2室(incident・hq)だけへ出る",
          depts4 == [aw.SUMMARY_DEPT, "hq"])
    check("★増分速報の当該部門へは出ない(9325c04のon_deadが個別に出す側の仕事)",
          all(d not in depts4 for d in ["aegis-gl", "llm-qa", "platform-se"]))
    check("基準idが前進していなければ鳴らない(二度鳴りしない)",
          fire(aw.check_dead_letters, dict(st4, last_dead_alert=0), db=db) == [])
    check("告知した id が集合として残る(次の周回の判定材料)",
          sorted(st4.get("dead_announced_ids") or []) == sorted(with_db(db, aw.dead_ids)))

    # --- A-3b ★順序の穴(HQ発注 msg 1537539162083823732)。
    #     id は**投函順**に振られ、dead は**5回失敗した後**に落ちる= 先に入った便が
    #     後から入った便より遅れて死ぬと、その id は基準より小さく、高水位1本では永久に黙る。
    db3 = make_db([
        ("aegis-gl", "dead", 2 * H, "", '{"author": "someone"}', 10),   # 既に告知済みの古いdead
        ("llm-qa", "dead", 2 * H, "", '{"author": "someone"}', 50),     # ★後から死んだ**小さいid**
        ("router", "pending", 1 * H, "", '{"author": "someone"}', 120),  # 基準を押し上げた新しい便
    ])
    print(f"  偽DBの実測(順序の穴): dead id= {sorted(with_db(db3, aw.dead_ids))} / 基準は100")
    st5 = {"dead_announced_ids": [10], "last_dead_max_id": 100, "last_dead_alert": 0}
    sent5 = fire(aw.check_dead_letters, st5, db=db3)
    body5 = sent5[0][1] if sent5 else ""
    check("★★基準(100)より小さい id=50 の dead でも鳴る(順序の穴が塞がっている)",
          [c for c, _ in sent5] == [aw.SUMMARY_DEPT, "hq"])
    check("本文に新規idが出る(どの便が死んだかを2室で読める)", "新規id 50" in body5)
    check("鳴った後は id=50 も告知済みに入る(二度鳴りしない)",
          50 in (st5.get("dead_announced_ids") or [])
          and fire(aw.check_dead_letters, dict(st5, last_dead_alert=0), db=db3) == [])
    check("★基準idは下げない(purgeで二度鳴りしない従来の性質を保つ)",
          int(st5.get("last_dead_max_id") or 0) == 100)
    check("既に告知済みの古い dead(id=10)だけなら鳴らない",
          fire(aw.check_dead_letters,
               {"dead_announced_ids": [10, 50], "last_dead_max_id": 100, "last_dead_alert": 0},
               db=db3) == [])
    # ★移行(1回だけ)= 集合がまだ無い本番の state を、旧い高水位から**翻訳**して引き継ぐ。
    st6 = {"last_dead_max_id": 100, "last_dead_alert": 0}
    check("移行= 集合が無くても、基準以下の現deadは告知済みとして黙る(過去分で鳴らない)",
          fire(aw.check_dead_letters, st6, db=db3) == []
          and sorted(st6.get("dead_announced_ids") or []) == [10, 50])

    # --- A-4 DB不在は fail-open で黙る(監視自体が落ちない) ---
    check("キューDBが無くても例外を投げず黙る(fail-open)",
          fire(aw.check_stale_dead, {"last_stale_dead_alert": 0},
               db=os.path.join(tempfile.mkdtemp(), "nope.db")) == [])

    # =====================================================================
    # B) 本番のキューDBをそのまま読んで発火させる(実データでの確認は残す)
    # =====================================================================
    print("B) 本番のキューDBでの実測(state は保存しない=クールダウンを食い潰さない)")
    total, by, max_id = aw.dead_letter_summary()
    print(f"  本番キューの実測: dead 計{total}件 / 内訳 {by} / 最大id {max_id}")
    stB = {"last_dead_max_id": 0, "last_dead_alert": 0}
    sentB = fire(aw.check_dead_letters, stB)
    if total == 0:
        check("本番dead 0件なら鳴らない(空振りしない)", sentB == [])
    else:
        deptsB = [c for c, _ in sentB]
        print(f"  → 増分速報の宛先: {deptsB}")
        check("★本番データでも増分速報は incident と hq の2室だけへ出る",
              deptsB == [aw.SUMMARY_DEPT, "hq"])
        check("★本番データでも当該部門へは出ない", all(d not in deptsB for d in by))

    s_total, s_by, s_oldest, _ = aw.stale_dead_summary()
    print(f"  本番キューの実測(滞留): 計{s_total}件 / 内訳 {s_by} / 最古 {int(s_oldest//3600)}時間前")
    sentB2 = fire(aw.check_stale_dead, {"last_stale_dead_alert": 0})
    if s_total == 0:
        check("本番の滞留0件なら鳴らない(空振りしない)", sentB2 == [])
    else:
        deptsB2 = [c for c, _ in sentB2]
        print(f"  → 滞留警報の宛先: {deptsB2}")
        check("★本番データでも滞留警報は2室だけへ出る",
              deptsB2 == [aw.SUMMARY_DEPT, "hq"])

    # =====================================================================
    # C) 源流(コード)の検査= 上のAで経路は実行で押さえた。ここは「枝が消えていない」
    #    ことの安い保険として**残す**(C-003= 消さずに残す)。判定の主役ではない。
    # =====================================================================
    src = open(os.path.join(HERE, "absence_watchdog.py"), encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    check("宛先に部門を足し込む式がコードから消えている",
          'targets = [SUMMARY_DEPT, "hq"] + [d for d in by' not in code)
    check("2室固定の式が2箇所(増分・滞留)に在る",
          code.count('targets = [SUMMARY_DEPT, "hq"]') == 2)
    check("頻度は変えていない= 増分のクールダウン定数がそのまま",
          "DEAD_ALERT_COOLDOWN_SEC" in code)
    check("他の警報の宛先には触っていない(窓の死活は incident のまま)",
          "def check_dead_windows" in code)

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
