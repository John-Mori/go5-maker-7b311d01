#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""output_gates.apply_gates(案B配線)の回帰テスト。

なぜ要るか(2026-08-15 platform-se・一ノ瀬怜):
  案B(ミラー経路へゲートC/Dを相乗り)は 9b53e9a でコミット済だが、
  本番の tone_audit/naming_audit に source="mirror" 行が0件=**一度も本番発火していない**。
  「ソース文字列一致だけで固めるな。入力を差し替えて経路を実行で通せ」(HQ裁定2026-08-14)。
  fail-open は可用性の砦なので、経路を実行で固定しておく。

実行= python scripts/llm/test_output_gates.py (全PASSで exit 0)。
  隔離tempへ監査を書くので本番の audit を汚さない。ネイティブPythonで走る(Git Bashの/tmp非依存)。
"""
import os
import sys
import json
import tempfile
import shutil
import importlib

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_PASS = 0
_FAIL = 0


def _check(name, cond):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("PASS", name)
    else:
        _FAIL += 1
        print("FAIL", name)


def _rows(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def main():
    tmp = tempfile.mkdtemp(prefix="og_test_")
    os.environ["GO5_LOCAL_DIR"] = tmp
    os.environ.pop("GO5_MIRROR_GATE_FIX", None)   # 既定=警告のみ
    import output_gates
    importlib.reload(output_gates)                 # LOCAL/AUDIT を tmp で解決

    ta = os.path.join(tmp, "llm", "tone_audit.jsonl")

    # 1) 陽性対照: 謙譲体フレーズを含む本文で口調ゲートが発火し、source=mirror で記録される
    probe = "承知しました。確認させていただきました。ご確認ください。以下です。"
    fixed, summ = output_gates.apply_gates("hq", "シャビ・アロンソ", probe, source="mirror")
    tr = _rows(ta)
    _check("謙譲体で口調警告が出る", summ["tone_warn"] >= 1)
    _check("source=mirror が全行に付く", tr and all(r.get("source") == "mirror" for r in tr))
    _check("既定は警告のみ=本文を書き換えない", fixed == probe)

    # 2) fail-open: ルール取得が例外でも本文を殺さない
    save = output_gates._rules
    output_gates._rules = lambda kind: (_ for _ in ()).throw(RuntimeError("boom"))
    f2, _ = output_gates.apply_gates("hq", "シャビ・アロンソ", probe, source="mirror")
    output_gates._rules = save
    _check("例外時も本文が返る(fail-open)", f2 == probe)

    # 3) 空persona / 空本文 は素通し(判定材料が無い時に黙って壊さない)
    _check("空personaは素通し", output_gates.apply_gates("hq", "", probe)[0] == probe)
    _check("空本文は素通し", output_gates.apply_gates("hq", "シャビ・アロンソ", "")[0] == "")

    # 4) fix=True で置換が一意な時だけ本文が変わる(常駐と同じ純関数任せ・沈黙ゼロ)
    f4, _ = output_gates.apply_gates("hq", "シャビ・アロンソ", probe, source="mirror", fix=True)
    _check("fix=Trueでも空文字は返さない", str(f4 or "").strip() != "")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
