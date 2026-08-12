#!/usr/bin/env python3
"""jsonl_store のテスト。python scripts/lib/test_jsonl_store.py"""
import io
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jsonl_store import validate, append_jsonl, read_jsonl, SCHEMAS  # noqa: E402

ok_count = 0
fail = []


def check(name, cond):
    global ok_count
    if cond:
        ok_count += 1
        print(f"  PASS  {name}")
    else:
        fail.append(name)
        print(f"  FAIL  {name}")


# T1: 正しいcorpus行は通る
good = {"ts": "2026-07-17T08:00:00+00:00", "msg_id": "1", "content": "こんにちは", "sensitive": False}
ok, errs = validate(good, SCHEMAS["corpus"])
check("T1 正常なcorpus行は通る", ok and not errs)

# T2: ts='t'(実在した壊れ値)は弾かれる
bad_ts = dict(good, ts="t")
ok, errs = validate(bad_ts, SCHEMAS["corpus"])
check("T2 ts='t' は弾かれる", (not ok) and any("ISO" in e for e in errs))

# T3: 必須欠落は弾かれる
no_content = {"ts": good["ts"], "msg_id": "2"}
ok, errs = validate(no_content, SCHEMAS["corpus"])
check("T3 content欠落は弾かれる", not ok)

# T4: 型違いは弾かれる
bad_type = dict(good, sensitive="yes")
ok, errs = validate(bad_type, SCHEMAS["corpus"])
check("T4 sensitiveが文字列なら弾かれる", not ok)

# T5: 未知フィールドは許容(スキーマ進化に強い)
extra = dict(good, new_field="x")
ok, errs = validate(extra, SCHEMAS["corpus"])
check("T5 未知フィールドは許容", ok)

# T6: append_jsonl は違反を書かずValueError
tmp = os.path.join(tempfile.gettempdir(), "go5_test_jsonl_store.jsonl")
if os.path.exists(tmp):
    os.remove(tmp)
raised = False
try:
    append_jsonl(tmp, bad_ts, SCHEMAS["corpus"])
except ValueError:
    raised = True
wrote_nothing = not os.path.exists(tmp) or os.path.getsize(tmp) == 0
check("T6 違反行はValueErrorで書かれない", raised and wrote_nothing)

# T7: 正常行は書ける
append_jsonl(tmp, good, SCHEMAS["corpus"])
check("T7 正常行は追記できる", os.path.exists(tmp) and os.path.getsize(tmp) > 0)

# T8: read_jsonl は壊れ行をskipしてbadに記録
with io.open(tmp, "a", encoding="utf-8") as f:
    f.write(json.dumps({"ts": "t", "msg_id": "3", "content": "x"}, ensure_ascii=False) + "\n")
    f.write("{ broken json\n")
rows, bad = read_jsonl(tmp, SCHEMAS["corpus"], on_bad="skip")
check("T8 read_jsonlは正常1行/壊れ2件を分離", len(rows) == 1 and len(bad) == 2)

os.remove(tmp)

# ---- T9〜: ts_epoch(帯の有無で9時間ずれる穴・2026-08-13 イージス研究室) ----
from jsonl_store import ts_epoch                                        # noqa: E402

JST_NOON = ts_epoch("2026-08-13T12:00:00+09:00")
check("T9 帯つき(+09:00)を読む", JST_NOON is not None)
check("T10 帯なしはJSTとみなす= 帯つきと同じ値",
      ts_epoch("2026-08-13T12:00:00") == JST_NOON)
check("T11 ★Zは UTC として扱う= JST正午とは9時間ずれる",
      ts_epoch("2026-08-13T03:00:00Z") == JST_NOON)
check("T12 空白区切りも受ける", ts_epoch("2026-08-13 12:00:00") == JST_NOON)
check("T13 秒が無くても読める", ts_epoch("2026-08-13T12:00") == JST_NOON)
check("T14 ミリ秒つきも読める",
      abs(ts_epoch("2026-08-13T12:00:00.500000") - JST_NOON) < 1.0)
check("T15 ★読めない値は0ではなくNone(1970年で集計に混ざるのを防ぐ)",
      ts_epoch("t") is None and ts_epoch("") is None and ts_epoch(None) is None)
check("T16 日付だけは読めない扱い", ts_epoch("2026-08-13") is None)
check("T17 defaultを指定できる", ts_epoch("こわれ", default=-1) == -1)
check("T18 数値はそのまま通す", ts_epoch(1234.5) == 1234.5)

# ---- T19〜: BOM付き行(実測= change_log.jsonl 1行目・2026-08-13 イージス研究室) ----
tmp2 = os.path.join(tempfile.gettempdir(), "go5_test_jsonl_bom.jsonl")
with io.open(tmp2, "w", encoding="utf-8") as f:
    f.write("﻿" + json.dumps(good, ensure_ascii=False) + "\n")   # 1行目にBOM
    f.write(json.dumps(dict(good, msg_id="9"), ensure_ascii=False) + "\n")
rows, bad = read_jsonl(tmp2, SCHEMAS["corpus"], on_bad="skip")
check("T19 ★1行目のBOMを落として読める(壊れ扱いにしない)", len(rows) == 2 and not bad)

with io.open(tmp2, "w", encoding="utf-8") as f:                      # 途中の行にBOM
    f.write(json.dumps(good, ensure_ascii=False) + "\n")
    f.write("﻿" + json.dumps(dict(good, msg_id="9"), ensure_ascii=False) + "\n")
rows, bad = read_jsonl(tmp2, SCHEMAS["corpus"], on_bad="skip")
check("T20 追記で途中に混ざったBOMも落とせる", len(rows) == 2 and not bad)
os.remove(tmp2)

print(f"\n{ok_count}/{ok_count + len(fail)} passed")
sys.exit(1 if fail else 0)
