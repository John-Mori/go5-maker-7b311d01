# -*- coding: utf-8 -*-
"""C-049 §7-B の気づかせ線(2026-08-29 イージス研究室 / 発注= 研究室HQ
`DISPATCH-aegis-gl-1787949604668`)の検査。

見るもの:
  A 出る条件   : 作業便 かつ テスト/バグチェックの語があるときだけ1行出る
  B 出ない条件 : 会話便 / 語が無い便 / **持ち物が載っている便**では1文字も足さない
  C 封筒の作法 : 本文を1文字も書き換えない・work_note の後ろに置く
  D T5         : 判定日まで鳴らない / ①が動けば「効いた」/ 0のままなら「効かなかった」
                 ★どちらでも `on` を false にしない(戻す引き金ではない)
  E must-fail  : 気づかせ線を**外した実装**に差し替えると A が赤くなる
                 (★C-053= 空PASSを禁じる。緑のまま通る検査は検査ではない)

  python tests/test_fcc_hint.py
"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import session_relay as SR                                        # noqa: E402
import watch_triggers as WT                                       # noqa: E402

OK = [0]
NG = [0]


def check(name, cond, detail=""):
    (OK if cond else NG)[0] += 1
    print("%s %s%s" % ("PASS" if cond else "**FAIL**", name,
                       ("  | " + detail) if (detail and not cond) else ""))


def rec(content, msg_id="1"):
    return {"author": "Chami", "msg_id": msg_id, "channel": "イージス研究室",
            "ts": "2026-08-29T05:00:00", "content": content}


MARK = "C-049 §7-B で既定はFCC"

# ---------------------------------------------------------------- A 出る条件
print("== A 出る条件 ==")
A_YES = [
    ("Chamiの実文言1", "問題ないかテスト、バグチェックした?"),
    ("Chamiの実文言2", "テストとかシステムのバグチェックとかどんどんそっちで。"),
    ("Chamiの実文言3", "できる限りFCCなどトークン節約をして実装やデバッグをして"),
    ("動作確認",       "投稿履歴の表示、動作確認までやっといて"),
    ("pytest",         "pytest が2本落ちてる。直して"),
]
for name, txt in A_YES:
    h = SR._fcc_hint(rec(txt), True)
    check("A 出る= " + name, MARK in h, repr(h[:40]))
check("A 1行の中に1コマンドが載っている",
      "fcc_task.py --dept" in SR._fcc_hint(rec("テストして"), True))
check("A 持ち物は載らないと断ってある",
      "素通り" in SR._fcc_hint(rec("テストして"), True))

# ---------------------------------------------------------------- B 出ない条件
print("\n== B 出ない条件 ==")
check("B 会話便には出ない", SR._fcc_hint(rec("テストどうだった?"), False) == "")
check("B 語が無ければ出ない", SR._fcc_hint(rec("候補一覧の並び順を直して"), True) == "")
B_MOCHIMONO = [
    ("00_AI-HQ",        "00_AI-HQ/裁定カタログ.md を見てテストを直して"),
    ("open_defects",    "local/llm/open_defects.jsonl のバグを見て"),
    ("characterfile",   "characterfile の口調がバグってる。テストを足して"),
    ("トークン",        "ANTHROPIC_API_KEY を使うテストを書いて"),
]
for name, txt in B_MOCHIMONO:
    check("B 持ち物で抑止= " + name, SR._fcc_hint(rec(txt), True) == "",
          repr(SR._fcc_hint(rec(txt), True)[:40]))
check("B recが壊れていても落ちない(fail-open)", SR._fcc_hint(None, True) == "")
check("B contentが無くても落ちない", SR._fcc_hint({}, True) == "")

# ---------------------------------------------------------------- C 封筒の作法
print("\n== C 封筒の作法 ==")
body = "月詠みだけドラフトの挙動がバグる。テストして"
env_work = SR.build_envelope(rec(body), is_work=True, dept="system-engineer")
env_talk = SR.build_envelope(rec(body), is_work=False, dept="system-engineer")
check("C 作業便の封筒に線が入る", MARK in env_work)
check("C 会話便の封筒には入らない", MARK not in env_talk)
check("C 本文は1文字も変わっていない", body in env_work)
check("C 線は本文の**後ろ**", env_work.index(body) < env_work.index(MARK))
check("C 線は work_note の後ろ",
      env_work.index("実作業の依頼") < env_work.index(MARK))
_no = SR.build_envelope(rec("並び順を直して"), is_work=True, dept="system-engineer")
check("C 当たらない便の封筒は今までと同じ(線の分だけ長くならない)",
      MARK not in _no and len(_no) < len(env_work))

# ---------------------------------------------------------------- D T5
print("\n== D T5(判定を人の記憶に置かない) ==")
from datetime import datetime                                     # noqa: E402


def t5(doc, n_tasks, nowiso, dry=False):
    """T5 を仮のスイッチ・仮の①件数で回す。★本番の local/ は触らない。"""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "fcc_hint.json")
    io.open(path, "w", encoding="utf-8").write(json.dumps(doc, ensure_ascii=False))
    import fcc_usage as FU
    old_f, old_tasks, old_send = WT.FCC_HINT, FU.tasks, WT.send
    sent = []
    WT.FCC_HINT = path
    FU.tasks = lambda since=None: [None] * n_tasks
    WT.send = lambda title, text, d: (sent.append(title + "\n" + text), True)[1]
    try:
        fired = WT.t5_fcc_hint(datetime.strptime(nowiso, "%Y-%m-%dT%H:%M:%S"), {}, dry)
    finally:
        WT.FCC_HINT, FU.tasks, WT.send = old_f, old_tasks, old_send
    after = json.loads(io.open(path, encoding="utf-8-sig").read())
    return fired, "\n".join(sent), after


DOC = {"on": True, "since": "2026-08-29T05:44:38", "baseline_tasks": 0,
       "window_days": 7, "threshold": 1, "judge_at": "2026-09-05T00:00:00"}

f, s, a = t5(dict(DOC), 0, "2026-09-04T23:59:59")
check("D 判定日の前は鳴らない", f is False and s == "")
check("D 判定日の前は台帳を閉じない", not a.get("closed"))

f, s, a = t5(dict(DOC), 0, "2026-09-05T00:00:00")
check("D 判定日・①が0= 『効かなかった』と言う", f and "効かなかった" in s, s[:80])
check("D 効かなくても on は落とさない(戻す引き金ではない)", a.get("on") is True)
check("D 次の手をHQへ返す話だと書いてある", "次の手" in s)
check("D 但し書き(0.81%・床が主戦場)を落としていない", "0.81%" in s and "床" in s)
check("D 判定したら閉じる", a.get("closed") and a.get("final_tasks") == 0)

f, s, a = t5(dict(DOC), 3, "2026-09-06T00:00:00")
check("D 判定日・①が動いた= 『効いた』と言う", f and "効いた" in s, s[:80])
check("D ★『載った』と『節約が出た』を混ぜない", "節約が出た" in s or "ではない" in s)
check("D 効いた側も on は落とさない", a.get("on") is True)

f, s, a = t5({"on": False}, 9, "2026-09-09T00:00:00")
check("D 入っていなければ何もしない", f is False and s == "")
f, s, a = t5(dict(DOC, closed="2026-09-05T00:00:00"), 9, "2026-09-09T00:00:00")
check("D 判定済なら二度鳴らない", f is False and s == "")

check("D run() の名簿に t5 が居る",
      any(n == "t5" for n, _ in (("t1", 1), ("t2", 1), ("t3", 1), ("t4", 1), ("t5", 1)))
      and "t5_fcc_hint" in io.open(os.path.join(ROOT, "scripts", "llm", "watch_triggers.py"),
                                   encoding="utf-8").read().split("def run(")[1])

# ---------------------------------------------------------------- E must-fail
print("\n== E must-fail(気づかせ線を外すと赤くなるか) ==")
_real = SR._fcc_hint
SR._fcc_hint = lambda rec, is_work: ""          # ★= 投入前の実装(線が無い状態)
try:
    red = 0
    for _, txt in A_YES:
        if MARK not in SR._fcc_hint(rec(txt), True):
            red += 1
    env_off = SR.build_envelope(rec(body), is_work=True, dept="system-engineer")
    if MARK not in env_off:
        red += 1
finally:
    SR._fcc_hint = _real
check("E 線を外すと A の %d項目 + 封筒 が赤くなる" % len(A_YES), red == len(A_YES) + 1,
      "赤くなったのは %d件" % red)
check("E 戻したら緑に戻る", MARK in SR._fcc_hint(rec("テストして"), True))

# ---------------------------------------------------------------- F 本番のlocal/
print("\n== F 本番のlocal/を触っていない ==")
real = os.path.join(ROOT, "local", "llm", "fcc_hint.json")
check("F 本番のスイッチは on のまま",
      json.loads(io.open(real, encoding="utf-8-sig").read()).get("on") is True)

print("\n==== %d PASS / %d FAIL ====" % (OK[0], NG[0]))
sys.exit(1 if NG[0] else 0)
