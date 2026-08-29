#!/usr/bin/env python3
"""引き継ぎブロックの痩身(HQ-0220③)と、その見張り T4 の検査。

★何のための検査か(2026-08-29 イージス研究室 / 発注= 研究室HQ HQ-0220 ③裁定)
  HQの裁定=「承認する。ただし『ID+件数だけ』への全面除去はしない。
             **ID+件数+一行要旨** まで残す」。守りたい性質はこれだけだ:
    ① 痩身ONで **ID は残る・一行要旨は残る・件数は残る**(=裁定の下限を割らない)
    ② 痩身ONで **詳細(壊れた実物の在りか/気づいた/出所)は起動文から消える**(=節約が本当に起きる)
    ③ 🔥(炎上)の印と**先頭固定の並び**は痩身しても壊れない(C-040 の執行を巻き添えにしない)
    ④ **全文は台帳に残っている**= close_item.py --show で同じ物が引ける(実行条件1「移動しない」)
    ⑤ 既定(スイッチ無し)は**旧版と1文字も変わらない**
    ⑥ T4= 投入後の close_item 実行が戻す線を下回ったら、便を出すだけでなく**実際に off にする**
    ⑦ 母数が足りない窓では**戻しも続行も宣言しない**(0件と0件を比べて「落ちていない」と言わない)
    ⑧ 本番の local/ を1バイトも触らない

★空PASS禁止(共通規律§3・skills/test-must-fail)。
  E節で **痩身を off にした版(=今動いている本番の実装。空の骨組みではない)** に差し替え、
  A〜C で見た性質が**赤くなる**ことを見せる。赤くなるなら、見ていたのは本当に痩身の効き目だ。
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import session_relay as SR          # noqa: E402
import watch_triggers as W          # noqa: E402

ok = 0
ng = 0


def check(label, got, want):
    global ok, ng
    if got == want:
        ok += 1
        print("  PASS %-58s = %s" % (label, got))
    else:
        ng += 1
        print("  FAIL %-58s = %r (期待 %r)" % (label, got, want))


TMPD = tempfile.mkdtemp(prefix="go5_slim_")
PROD = {"defects": SR.DEFECTS_FILE, "slim": SR.LEDGER_SLIM_FILE,
        "watch_slim": W.SLIM, "access": W.ACCESS_LOG}
PROD_MTIME = {k: (os.path.getmtime(v) if os.path.exists(v) else None) for k, v in PROD.items()}

SR.DEFECTS_FILE = os.path.join(TMPD, "open_defects.jsonl")
SR.LEDGER_SLIM_FILE = os.path.join(TMPD, "handoff_slim.json")
W.DEFECTS = SR.DEFECTS_FILE
W.SLIM = SR.LEDGER_SLIM_FILE
W.ACCESS_LOG = os.path.join(TMPD, "ledger_access.jsonl")

SENT = []
W.send = lambda title, text, dry: (SENT.append(title), True)[1]   # 外へ出る手だけ偽物
NOW = datetime.now(W.JST)
DEPT = "testroom"


def rows(*items):
    with open(SR.DEFECTS_FILE, "w", encoding="utf-8") as f:
        for d in items:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def switch(doc):
    if doc is None:
        if os.path.exists(SR.LEDGER_SLIM_FILE):
            os.remove(SR.LEDGER_SLIM_FILE)
        return
    with open(SR.LEDGER_SLIM_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


# 検体= 症状が長い不具合1件(詳細つき)+ 🔥の依頼1件(催促つき)。
LONG = "投稿履歴の画像は保存しても反映されるが、カテゴリのチェックはリロードすると戻る。" * 3
D1 = {"op": "open", "kind": "defect", "id": "DEF-testroom-aaa", "dept": DEPT,
      "ts": "2026-08-01T00:00:00", "symptom": LONG,
      "broken": "msg_id=1500000000000000001 / 部屋=検体", "noticed_at": "2026-08-01 00:00:00",
      "source": "reaction_watch(再発スタンプ)"}
R1 = {"op": "open", "kind": "request", "id": "REQ-testroom-bbb", "dept": DEPT,
      "ts": "2026-08-02T00:00:00", "symptom": "途中の実装を再開してほしい",
      "broken": "msg_id=1500000000000000002 / 部屋=検体", "noticed_at": "2026-08-02 00:00:00",
      "source": "dept_daemon", "close_when": "実物をその場面で確認できた時"}
R2 = {"op": "open", "kind": "request", "id": "REQ-testroom-ccc", "dept": DEPT,
      "ts": "2026-08-03T00:00:00", "symptom": "こっちが🔥の方だ",
      "broken": "msg_id=1500000000000000003 / 部屋=検体", "noticed_at": "2026-08-03 00:00:00",
      "source": "reaction_watch"}
# ★🔥は行の項目ではなく **note行(note_kind=enjo)** で立つ= 本番と同じ立て方で検体を作る。
E2 = {"op": "note", "kind": "request", "id": "REQ-testroom-ccc", "dept": DEPT,
      "ts": "2026-08-03T01:00:00", "note_kind": "enjo", "where": "msg_id=1500000000000000004"}
# ★実部屋なみの厚み(不具合8件)。1〜3件だと「掟の定型文」が塊の大半を占めて
#   痩身の比率が実態とかけ離れる= 検体が薄いだけの数字を採らない。
BULK = [dict(D1, id="DEF-testroom-b%02d" % i, ts="2026-08-0%dT00:00:00" % (i % 9 + 1),
             symptom=LONG[:80] + "その%d" % i,
             broken="msg_id=15000000000000001%02d / 部屋=検体" % i) for i in range(7)]


def ledger(on):
    switch({"on": on} if on is not None else None)
    return "\n".join(SR._ledger_lines(DEPT))


print("A. 痩身ONで**裁定の下限**(ID+件数+一行要旨)を割らないか")
rows(D1, R1, R2, E2, *BULK)
on = ledger(True)
check("IDが残る(不具合)", "DEF-testroom-aaa" in on, True)
check("IDが残る(依頼)", "REQ-testroom-bbb" in on, True)
check("件数が残る", "が8件ある" in on, True)
check("一行要旨が残る(先頭%d字)" % 20, LONG[:20] in on, True)
check("要旨は一行に切られている(%d字上限)" % SR.DEFECT_SYMPTOM_SLIM,
      LONG[:SR.DEFECT_SYMPTOM_SLIM + 1] in on, False)

print("\nB. 痩身ONで**詳細が起動文から消える**か(=節約が本当に起きる)")
check("『壊れた実物の在りか=』が消える", "壊れた実物の在りか=" in on, False)
check("『依頼の便の在りか=』が消える", "依頼の便の在りか=" in on, False)
check("『★閉じる条件=』が消える", "★閉じる条件=" in on, False)
check("台帳を開く手(--show)が案内される", "close_item.py --show" in on, True)
off = ledger(False)
check("痩身OFFより短い", len(on) < len(off), True)
check("削減が3割以上ある", (len(off) - len(on)) / len(off) > 0.30, True)

print("\nC. 🔥(C-040)を巻き添えにしていないか")
check("🔥の印が残る", "🔥【炎上=恒久対策まで行け】" in on, True)
check("🔥が先頭(REQ-cccがbbbより前)",
      on.index("REQ-testroom-ccc") < on.index("REQ-testroom-bbb"), True)
check("🔥の件数の注記が残る", "🔥(炎上)の 1件を先頭に置いた" in on, True)

print("\nD. 実行条件1= 全文は**移動していない**(台帳に在る)")
raw = open(SR.DEFECTS_FILE, encoding="utf-8").read()
check("台帳に長文がそのまま在る", LONG in raw, True)
check("台帳に在りかがそのまま在る", "msg_id=1500000000000000001" in raw, True)
item = {x["id"]: x for x in SR.fold_defects(None)}["DEF-testroom-aaa"]
check("台帳から全文が引ける", item["symptom"] == LONG, True)
check("台帳から在りかが引ける", item["broken"].startswith("msg_id=1500000000000000001"), True)

print("\nE. 既定(スイッチ無し)は旧版と1文字も変わらないか")
check("スイッチ無し == 痩身OFF", ledger(None) == off, True)
switch({"on": True, "こわれた": True})
check("読めない/欠けた値でも fail-open(全文へ倒れる)", SR.ledger_slim_on(), True)
with open(SR.LEDGER_SLIM_FILE, "w", encoding="utf-8") as f:
    f.write("{壊れたJSON")
check("壊れたスイッチは全文へ倒れる", SR.ledger_slim_on(), False)


def confirms(n, t0, days):
    """confirm行を n本、t0 から days 日ぶんに散らして足す。"""
    base = datetime.strptime(t0, "%Y-%m-%dT%H:%M:%S")
    with open(SR.DEFECTS_FILE, "a", encoding="utf-8") as f:
        for i in range(n):
            ts = (base + timedelta(seconds=int(days * 86400 * (i + 0.5) / n)))
            f.write(json.dumps({"op": "confirm", "id": "DEF-testroom-aaa", "dept": DEPT,
                                "ts": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                                "fixed": "x", "scene": "y", "by": "z"},
                               ensure_ascii=False) + "\n")


def t4(since_days, judge_days, before_n, after_n, base_days=14, min_n=10, frac=0.5):
    """投入前 before_n件 / 投入後 after_n件 の台帳を作って T4 を1回回す。"""
    del SENT[:]
    since = (NOW - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows(D1, R1, R2, E2, *BULK)
    confirms(before_n, (NOW - timedelta(days=since_days + base_days))
             .strftime("%Y-%m-%dT%H:%M:%S"), base_days)
    confirms(after_n, since, since_days)
    _, brate = W._confirm_rate((NOW - timedelta(days=since_days + base_days))
                               .strftime("%Y-%m-%dT%H:%M:%S"), since)
    W.write_json(W.SLIM, {"on": True, "since": since, "baseline_days": base_days,
                          "baseline_n": before_n, "baseline_rate": brate,
                          "rollback_frac": frac, "rollback_rate": brate * frac, "min_n": min_n,
                          "judge_at": (NOW + timedelta(days=judge_days))
                          .strftime("%Y-%m-%dT%H:%M:%S")})
    fired = W.t4_handoff_slim(NOW, {}, False)
    return fired, (W.read_json(W.SLIM) or {})


print("\nF. T4= 判定日まで鳴らない / 落ちたら**実際に off にする**")
fired, doc = t4(since_days=7, judge_days=7, before_n=42, after_n=21)
check("判定日前は鳴らない", (fired, len(SENT)), (False, 0))
check("判定日前は痩身が入ったまま", doc["on"], True)

fired, doc = t4(since_days=14, judge_days=-1, before_n=42, after_n=5)
check("落ちた→発火", fired, True)
check("落ちた→**off にした**(便を出すだけで終わらない)", doc["on"], False)
check("落ちた→戻した便を出した", "戻した" in (SENT[0] if SENT else ""), True)
check("落ちた→判定を閉じた", bool(doc.get("closed")), True)

fired, doc = t4(since_days=14, judge_days=-1, before_n=42, after_n=42)
check("落ちていない→発火(判定日だから)", fired, True)
check("落ちていない→痩身は残る", doc["on"], True)
check("落ちていない→続行の便", "続行" in (SENT[0] if SENT else ""), True)

print("\nG. 母数が足りない窓では**戻しも続行も宣言しない**(fail-quality)")
fired, doc = t4(since_days=14, judge_days=-1, before_n=3, after_n=0)
check("判定不能でも黙らない(便は出す)", fired, True)
check("判定不能では off にしない", doc["on"], True)
check("判定不能と書く", "判定不能" in (SENT[0] if SENT else ""), True)
fired, doc = t4(since_days=14, judge_days=-1, before_n=3, after_n=0)
check("★『0件と0件』を『落ちていない』と言っていない",
      "続行" in (SENT[0] if SENT else ""), False)

print("\nH. ★空PASS禁止= 痩身を off にした版(=いま動いている本番の実装)なら赤くなるか")
_MUST_FAIL = []


def must_fail(label, cond):
    """痩身OFF(旧仕様=本番でいま動いている形)で**成り立たなくなる**ことを見せる。"""
    _MUST_FAIL.append((label, cond))
    print("  %s %-56s" % ("赤(期待どおり)" if not cond else "★緑のまま(検査が空)", label))


rows(D1, R1, R2, E2, *BULK)
o = ledger(False)                       # ← 差し替える「動く別実装」= 旧レンダラ
must_fail("A『要旨が一行に切られている』", LONG[:SR.DEFECT_SYMPTOM_SLIM + 1] not in o)
must_fail("B『壊れた実物の在りか= が消える』", "壊れた実物の在りか=" not in o)
must_fail("B『--show が案内される』", "close_item.py --show" in o)
must_fail("B『削減が3割以上』", (len(off) - len(o)) / len(off) > 0.30)
_still_green = [lab for lab, c in _MUST_FAIL if c]
check("旧実装では A/B の4項目すべてが赤くなる", _still_green, [])
check("ただし C(🔥)と D(全文)は旧実装でも緑= 痩身は🔥も台帳も壊していない",
      ("🔥【炎上=恒久対策まで行け】" in o and LONG in open(SR.DEFECTS_FILE,
                                                          encoding="utf-8").read()), True)

print("\nI. 本番の local/ を1バイトも触っていないか")
for k, v in PROD.items():
    now_m = os.path.getmtime(v) if os.path.exists(v) else None
    check("本番 %s は無傷" % k, now_m, PROD_MTIME[k])

print("\n== %d PASS / %d FAIL ==" % (ok, ng))
sys.exit(1 if ng else 0)
