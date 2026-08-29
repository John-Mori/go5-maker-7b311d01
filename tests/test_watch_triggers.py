#!/usr/bin/env python3
"""引き金置き場(`scripts/llm/watch_triggers.py`)の検査。

★何のための検査か(2026-08-29 イージス研究室 / 発注= 研究室HQ HQ-0220・HQ-0218)
  HQが2回「**人の記憶に置くな。仕組みに載せろ**」と言った条件を、機械が本当に見て本当に
  発火するか。ここで守りたい性質:
    ① 線を**超えた時だけ**発火する(超えていないのに鳴らない・超えたのに黙らない)
    ② T2 は超えたら **_model_override.json から実際に外す**(便を出すだけで終わらない)
    ③ 母数が足りないうちは判定しない(fail-quality= 迷ったら高い方=Opusのまま)
    ④ 本番の local/ を1バイトも触らない

★空PASS禁止(共通規律§3・skills/test-must-fail)。
  最後の E 節で **引き金の線を外して(=旧仕様「人が覚えている」相当)同じ検体が鳴らなくなる**
  ことを見せる。鳴らないなら、A〜D で見たのは本当に線の効き目だ。
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import watch_triggers as w            # noqa: E402

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


TMPD = tempfile.mkdtemp(prefix="go5_watch_")
PROD = {"state": w.STATE, "watch": w.WATCH, "override": w.OVERRIDE,
        "audit": w.AUDIT, "cold": w.COLD_LOG}
PROD_MTIME = {k: (os.path.getmtime(v) if os.path.exists(v) else None) for k, v in PROD.items()}

w.STATE = os.path.join(TMPD, "state.json")
w.WATCH = os.path.join(TMPD, "watch.json")
w.OVERRIDE = os.path.join(TMPD, "override.json")
w.AUDIT = os.path.join(TMPD, "audit.jsonl")
w.COLD_LOG = os.path.join(TMPD, "cold.jsonl")

SENT = []
w.send = lambda title, text, dry: (SENT.append(title), True)[1]   # 外へ出る手だけ偽物
NOW = datetime.now(w.JST)


def put(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


print("A. T1= 1日の投函数の線(HQ-0220「200を超えた日が来たら、その日のうちに測り直す」)")
w.posts_today = lambda now: 150
check("150件(線200の下)は鳴らない", w.t1_cold_gap(NOW, {}, False), False)
w.posts_today = lambda now: 201
w.cold_gap_summary_calls = 0


class _FakeCG:                                     # 測る本体は別で検査済み(重いので差し替え)
    @staticmethod
    def summary(hours):
        return "本文", {"cold": 1}


sys.modules["cold_gap_report"] = _FakeCG
st = {}
check("201件(線を超えた)は鳴る", w.t1_cold_gap(NOW, st, False), True)
check("鳴った日は台帳に日付が入る", st.get("t1_last_date") == NOW.strftime("%Y-%m-%d"), True)
check("同じ日に二度は鳴らない", w.t1_cold_gap(NOW, st, False), False)
check("測った数字は履歴へ1行残る", os.path.exists(w.COLD_LOG), True)

print("\nB. T2= 格下げの見張り(HQ-0218「基準+50%を超えたら即戻す」)")
put(w.OVERRIDE, {"enabled": True, "work": {"kaizen-analyst": "sonnet", "hq": "sonnet"}})
now = time.time()
put(w.WATCH, {"kaizen-analyst": {"start_ts": now - 86400, "judge_at": now + 86400,
                                 "baseline_pct": 40.0, "rollback_mult": 1.5,
                                 "rollback_pct": 60.0, "min_n": 5}})
import reround_check as rr                                      # noqa: E402
rr.measure = lambda dept, t0, t1, window=3600.0: (100, 80, 80.0)  # 基準の2倍= 線を超えた
SENT[:] = []
check("線を超えたら発火する", w.t2_downgrade(NOW, {}, False), True)
work = json.load(open(w.OVERRIDE, encoding="utf-8-sig"))["work"]
check("★_model_override.json から外れている", "kaizen-analyst" not in work, True)
check("巻き添えで他の部屋を消さない", work.get("hq"), "sonnet")
check("見張りは閉じる(二度鳴らさない)",
      bool(json.load(open(w.WATCH, encoding="utf-8-sig"))["kaizen-analyst"].get("closed")), True)

put(w.OVERRIDE, {"enabled": True, "work": {"kaizen-analyst": "sonnet"}})
put(w.WATCH, {"kaizen-analyst": {"start_ts": now - 8 * 86400, "judge_at": now - 1,
                                 "baseline_pct": 40.0, "rollback_mult": 1.5,
                                 "rollback_pct": 60.0, "min_n": 5}})
rr.measure = lambda dept, t0, t1, window=3600.0: (100, 40, 40.0)  # 基準どおり
SENT[:] = []
check("判定日に線の下なら続行の便が出る", w.t2_downgrade(NOW, {}, False), True)
check("★続行の時は外さない",
      "kaizen-analyst" in json.load(open(w.OVERRIDE, encoding="utf-8-sig"))["work"], True)

put(w.WATCH, {"kaizen-analyst": {"start_ts": now - 8 * 86400, "judge_at": now - 1,
                                 "baseline_pct": 40.0, "rollback_mult": 1.5,
                                 "rollback_pct": 60.0, "min_n": 20}})
rr.measure = lambda dept, t0, t1, window=3600.0: (3, 3, 100.0)    # 母数3本だけ
check("母数が足りなければ判定しない(fail-quality)", w.t2_downgrade(NOW, {}, False), False)

print("\nC. T3= frontend の月100便(HQ-0218 ①の再検討条件)")
with open(w.AUDIT, "w", encoding="utf-8") as f:
    for i in range(50):
        f.write(json.dumps({"dept": "frontend", "ts": NOW.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
check("50便(線100の下)は鳴らない", w.t3_frontend(NOW, {}, False), False)
with open(w.AUDIT, "a", encoding="utf-8") as f:
    for i in range(60):
        f.write(json.dumps({"dept": "frontend", "ts": NOW.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    for i in range(999):                          # 他の部屋は数に入れない
        f.write(json.dumps({"dept": "hq", "ts": NOW.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
st = {}
check("110便(線を超えた)は鳴る", w.t3_frontend(NOW, st, False), True)
check("同じ月に二度は鳴らない", w.t3_frontend(NOW, st, False), False)

print("\nD. 本番の local/ を触っていないこと")
for k, v in PROD.items():
    m = os.path.getmtime(v) if os.path.exists(v) else None
    check("本番 %s を触っていない" % k, m == PROD_MTIME[k], True)

print("\nE. ★空PASS禁止= 線を無くしたら A と C は鳴らなくなるか")
save1, save3 = w.POST_PER_DAY, w.FRONTEND_PER_MONTH
w.POST_PER_DAY = 10 ** 9        # 「人が覚えている」= 機械の線が無い状態と同じ
w.FRONTEND_PER_MONTH = 10 ** 9
w.posts_today = lambda now: 201
check("線が無ければ T1 は鳴らない", w.t1_cold_gap(NOW, {}, False), False)
check("線が無ければ T3 は鳴らない", w.t3_frontend(NOW, {}, False), False)
w.POST_PER_DAY, w.FRONTEND_PER_MONTH = save1, save3

print("\nPASS %d / FAIL %d" % (ok, ng))
sys.exit(1 if ng else 0)
