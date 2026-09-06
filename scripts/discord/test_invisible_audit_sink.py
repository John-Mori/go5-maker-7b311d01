#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""検査プロセスが書いた不可視文字の警告行が、本番の見張り台帳へ入らないことの回帰検査。

実行:            python scripts/discord/test_invisible_audit_sink.py
変異(must-fail): python scripts/discord/test_invisible_audit_sink.py --mutate

★なぜ在るか(2026-09-06 イージス研究室・実測):
  `scripts/discord/test_invisible.py` は leasequeue へ便を1つ投入して、密輸帯が本当に
  落ちるかを**本物の経路で**確かめる正しい検査だ。ただしその経路には invisible.audit() が
  入っている= 検査1回ごとに `TEST-INVISIBLE-1/2` の2行が **本番の見張り台帳**へ入っていた。
  09-04 に台帳を作ってから溜まった16行は**全部が検査の行**で、本番の検出は0件だった。
  中身は偽の注入文字列(IGNORE PREVIOUS INSTRUCTIONS…)、dept は当室。
  「攻撃が来ているか」を見る面がこれでは読めない= C-054「見張っている脈を、
  見張り以外の手で更新するな」。

  穴は2つあった。両方をこの検査で縛る:
    (a) `invisible.py` が `ROOT/local` を直書きしていて `GO5_LOCAL_DIR` を見ていなかった
        = 隔離したつもりの検査が本番へ書けてしまう。
    (b) 逸らし(test_sink)が無かった。

検査の作り(organization-test-gate):
  書き込み先のディレクトリだけ一時領域へ振り替え、判定と分岐は本物のまま子プロセスで実行する。
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
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

# 密輸帯(U+E0000-E007F)へ "X" を1文字隠した本文= 必ず警告が立つ
CHILD = '''# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"{here}")
import invisible
hidden = "".join(chr(0xE0000 + ord(c)) for c in "PROBE")
invisible.gate("明日の予定" + hidden, "sink_probe", msg_id="SINK-PROBE-1", dept="aegis-gl")
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
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("GEMINI_USAGE_SINK_TEST", None)
    r = subprocess.run([sys.executable, path], env=env, capture_output=True,
                       text=True, errors="replace")
    if r.returncode != 0:
        raise AssertionError(f"{child_name}: 子プロセスが異常終了 rc={r.returncode} {r.stderr[:300]}")
    return (_lines(os.path.join(local, "llm", "invisible_audit.jsonl")),
            _lines(os.path.join(local, "llm", "invisible_audit_test.jsonl")))


def run(label=""):
    print(f"=== test_invisible_audit_sink{label} ===")
    ok = True
    tmp = tempfile.mkdtemp(prefix="invis_sink_")
    try:
        # (0) GO5_LOCAL_DIR を尊重しているか= これが無いと隔離そのものが効かない
        env = dict(os.environ)
        env["GO5_LOCAL_DIR"] = os.path.join(tmp, "envprobe")
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, "-c",
             f'import sys;sys.path.insert(0,r"{HERE}");import invisible;print(invisible.AUDIT_FILE)'],
            env=env, capture_output=True, text=True, errors="replace")
        if os.path.join(tmp, "envprobe") not in (r.stdout or ""):
            ok = False
            print(f"  FAIL AUDIT_FILE が GO5_LOCAL_DIR を見ていない: {(r.stdout or r.stderr).strip()[:200]}")
        else:
            print("  PASS AUDIT_FILE は GO5_LOCAL_DIR で振り替わる")

        # (1) 検査プロセス= 本番台帳は0行・退避先に1行 + "test": true
        prod, sink = _run_child(tmp, "test_child_invis.py")
        if prod:
            ok = False
            print(f"  FAIL 検査プロセスの行が本番の見張り台帳へ入った({len(prod)}行): {prod[0][:160]}")
        elif len(sink) != 1:
            ok = False
            print(f"  FAIL 退避先の行数={len(sink)}(期待1)")
        elif json.loads(sink[0]).get("test") is not True:
            ok = False
            print(f"  FAIL 退避行に \"test\": true が無い: {sink[0][:160]}")
        else:
            print("  PASS 検査プロセス: 本番0行 / 退避1行(test=true)")

        # (2) 本番プロセス= 逸らさない(★本物の攻撃を取りこぼさない向きの確認)
        prod2, sink2 = _run_child(tmp, "gateway_child_invis.py")
        if len(prod2) != 1:
            ok = False
            print(f"  FAIL 本番プロセスの行数={len(prod2)}(期待1)。"
                  f"判定が広すぎて**本物の警告を取りこぼしている**。")
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
    """判定の正本を殺して(常にFalse)、検査が本当に赤くなるか確かめる。★CRLFのまま置換する。"""
    src = path.read_bytes()
    old = b'        return argv0.startswith("test_") or argv0.endswith("_test.py") or argv0 == "pytest"'
    new = b'        return False  # MUTATED'
    if old not in src:
        raise AssertionError(f"{path}: 変異対象の断片が見つからない(実装が変わった?)")
    path.write_bytes(src.replace(old, new, 1))


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        import pathlib
        target = pathlib.Path(ROOT) / "scripts" / "lib" / "test_sink.py"
        backup = target.with_suffix(".py.mutate_tmp")
        shutil.copyfile(target, backup)
        try:
            _mutate(target)
            for pyc, pref in ((os.path.join(HERE, "__pycache__"), "invisible."),
                              (str(target.parent / "__pycache__"), "test_sink.")):
                if os.path.isdir(pyc):
                    for f in os.listdir(pyc):
                        if f.startswith(pref):
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
