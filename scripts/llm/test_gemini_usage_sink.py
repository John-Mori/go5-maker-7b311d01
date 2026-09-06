#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""検査プロセスが書いた使用量の行が、本番の課金台帳へ入らないことの回帰検査。

実行:            python scripts/llm/test_gemini_usage_sink.py
変異(must-fail): python scripts/llm/test_gemini_usage_sink.py --mutate

★なぜ在るか(2026-09-06 イージス研究室・実測):
  `scripts/teian/test_body_bytes_regression.py` は urlopen だけを偽物にして本物の
  call_vision を走らせる正しい検査だが、本物の経路には gemini_usage.log() が入っている
  = 検査1回につき "HTTP 429" の行が4本、**本番の課金台帳へ**入っていた(09-06 の3回で12行)。
  台帳は「429の段数」で課金の是非を決める脈だ= C-054「見張っている脈を、見張り以外の手で
  更新するな」。逸らす機構(gemini_usage._under_test)を入れたので、その機構を検査で縛る。

検査の作り(organization-test-gate):
  外へ出る手だけ偽物にする=**書き込み先のディレクトリだけ**一時領域へ振り替え(GO5_LOCAL_DIR)、
  判定(_under_test)と分岐は本物のまま子プロセスで実行する。
  ★実行体の名前で判定するので、子プロセスを **test_ で始まる名前 / 始まらない名前** の
  2通りで走らせて、書き込み先が実際に分かれることを**ファイルの中身で**確かめる。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))

CHILD = '''# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"{here}")
import gemini_usage
gemini_usage.log("homin", "sink_probe", "model-probe", 1, 0, 0, False, "HTTP 429", 0.0)
'''


def _lines(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [ln for ln in f.read().splitlines() if ln.strip()]


def _run_child(tmp, child_name):
    """child_name の名前で子プロセスを1回走らせ、(本番行, 退避行) を返す。"""
    local = os.path.join(tmp, child_name.replace(".py", ""))
    os.makedirs(os.path.join(local, "llm"), exist_ok=True)
    path = os.path.join(tmp, child_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(CHILD.format(here=HERE))
    env = dict(os.environ)
    env["GO5_LOCAL_DIR"] = local
    env.pop("GEMINI_USAGE_SINK_TEST", None)
    r = subprocess.run([sys.executable, path], env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"{child_name}: 子プロセスが異常終了 rc={r.returncode} {r.stderr[:300]}")
    return (_lines(os.path.join(local, "llm", "gemini_usage.jsonl")),
            _lines(os.path.join(local, "llm", "gemini_usage_test.jsonl")))


def run(label=""):
    print(f"=== test_gemini_usage_sink{label} ===")
    ok = True
    tmp = tempfile.mkdtemp(prefix="usage_sink_")
    try:
        # (1) 検査プロセス(test_ で始まる実行体)= 本番台帳は0行・退避先に1行 + "test": true
        prod, sink = _run_child(tmp, "test_child_probe.py")
        if prod:
            ok = False
            print(f"  FAIL 検査プロセスの行が本番台帳へ入った({len(prod)}行): {prod[0][:160]}")
        elif len(sink) != 1:
            ok = False
            print(f"  FAIL 退避先の行数={len(sink)}(期待1)")
        elif json.loads(sink[0]).get("test") is not True:
            ok = False
            print(f"  FAIL 退避行に \"test\": true が無い: {sink[0][:160]}")
        else:
            print("  PASS 検査プロセス: 本番0行 / 退避1行(test=true)")

        # (2) 本番プロセス(test_ で始まらない実行体)= 逸らさない(fail-open の向きを確認)
        prod2, sink2 = _run_child(tmp, "teian_child_probe.py")
        if len(prod2) != 1:
            ok = False
            print(f"  FAIL 本番プロセスの行数={len(prod2)}(期待1)。"
                  f"判定が広すぎて本番の記録を取りこぼしている。")
        elif sink2:
            ok = False
            print(f"  FAIL 本番プロセスの行が退避先へ逸れた({len(sink2)}行)")
        else:
            print("  PASS 本番プロセス: 本番1行 / 退避0行")
    except AssertionError as e:
        ok = False
        print(f"  FAIL {e}")
    except Exception as e:
        ok = False
        print(f"  FAIL (想定外の例外) {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def _mutate(path):
    """判定を殺して(常にFalse)、検査が本当に赤くなるか確かめる。★CRLFのまま置換する。"""
    src = path.read_bytes()
    old = b'    return argv0.startswith("test_") or argv0.endswith("_test.py") or argv0 == "pytest"'
    new = b'    return False  # MUTATED'
    if old not in src:
        raise AssertionError(f"{path}: 変異対象の断片が見つからない(実装が変わった?)")
    path.write_bytes(src.replace(old, new, 1))


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        import pathlib
        target = pathlib.Path(HERE) / "gemini_usage.py"
        backup = target.with_suffix(".py.mutate_tmp")
        shutil.copyfile(target, backup)
        try:
            _mutate(target)
            pyc = os.path.join(HERE, "__pycache__")
            if os.path.isdir(pyc):
                for f in os.listdir(pyc):
                    if f.startswith("gemini_usage."):
                        os.remove(os.path.join(pyc, f))
            if run(" --mutate(逸らしを殺す)"):
                print("\n✗ 変異させたのに検査が全部PASSした(検査が壊れている)")
                sys.exit(1)
            print("\n✓ 変異(逸らしを殺す)で狙いどおり赤になった")
            sys.exit(0)
        finally:
            shutil.copyfile(backup, target)
            os.remove(backup)
    else:
        sys.exit(0 if run() else 1)
