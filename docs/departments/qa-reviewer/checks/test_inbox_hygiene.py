#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_inbox_hygiene.py の回帰ガード(★.session箱の誤検出を二度と出さない)。

★偽物にするのは**入力(inboxの中身と台帳)だけ**= 検査の判定・分岐は本物が通る。
  ソースの文字列一致では測らない= 実際に main() を走らせ、**戻り値と印字**で測る。
  (main() は モジュール変数 ROOT を見るので、そこだけ一時ディレクトリへ差し替える)

    python docs/departments/qa-reviewer/checks/test_inbox_hygiene.py
    python docs/departments/qa-reviewer/checks/test_inbox_hygiene.py --mustfail
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from importlib.machinery import SourceFileLoader

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(path, name):
    """拡張子が .bak_… でも読めるように loader を明に渡す(既定では None が返る)。"""
    spec = importlib.util.spec_from_file_location(
        name, path, loader=SourceFileLoader(name, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_against(mod, boxes, depts=("aegis-gl", "hq", "keiei-kikaku", "research-room")):
    """偽のinboxを1つ作って検査を**実行**し、(戻り値, 印字) を返す。"""
    tmp = tempfile.mkdtemp(prefix="inbox_hygiene_")
    try:
        os.makedirs(os.path.join(tmp, "local", "inbox"))
        with open(os.path.join(tmp, "local", "discord_channels.json"), "w",
                  encoding="utf-8") as f:
            json.dump([{"name": d, "id": "0", "dept": d} for d in depts], f)
        for b in boxes:
            open(os.path.join(tmp, "local", "inbox", b), "w", encoding="utf-8").close()
        old, mod.ROOT = mod.ROOT, tmp
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = mod.main()
        finally:
            mod.ROOT = old
        return rc, buf.getvalue()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HYGIENE = _load(os.path.join(_HERE, "check_inbox_hygiene.py"), "check_inbox_hygiene")

# 2026-09-16 実測の現物の名前。hq.session.jsonl は同日16:01に書かれていた現役の箱。
LIVE = ["aegis-gl.jsonl", "aegis-gl.session.jsonl", "hq.session.jsonl",
        "keiei-kikaku.session.jsonl", "research-room.session.jsonl"]


class TestTheLiveBoxesAreNotAccused(unittest.TestCase):
    """★本命= 生きている `<dept>.session.jsonl` を「台帳外」と言わない。"""

    def test_the_real_shape_passes(self):
        rc, out = run_against(HYGIENE, LIVE)
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)

    def test_it_does_not_tell_anyone_to_move_a_live_box(self):
        rc, out = run_against(HYGIENE, LIVE)
        self.assertNotIn("退避", out)


class TestItStillCatchesTheRealTrap(unittest.TestCase):
    """★黙らせていない= 台帳に無い名前は今までどおり赤。"""

    def test_a_foreign_dept_is_still_red(self):
        rc, out = run_against(HYGIENE, ["aegis-gl.jsonl", "shiranai-heya.jsonl"])
        self.assertEqual(rc, 1)
        self.assertIn("shiranai-heya.jsonl", out)

    def test_a_foreign_dept_wearing_session_is_still_red(self):
        # `.session` を付ければ何でも通る、にはしない。
        rc, out = run_against(HYGIENE, ["shiranai-heya.session.jsonl"])
        self.assertEqual(rc, 1)
        self.assertIn("shiranai-heya.session.jsonl", out)

    def test_an_unknown_suffix_is_still_red(self):
        # 剥がすのは `.session` の1語だけ。`.tmp` や `.bak` は名前の一部として扱う。
        rc, out = run_against(HYGIENE, ["aegis-gl.tmp.jsonl"])
        self.assertEqual(rc, 1)
        self.assertIn("aegis-gl.tmp.jsonl", out)

    def test_the_bare_word_session_is_not_a_dept(self):
        rc, out = run_against(HYGIENE, ["session.jsonl"])
        self.assertEqual(rc, 1)

    def test_non_jsonl_files_are_ignored(self):
        rc, out = run_against(HYGIENE, ["aegis-gl.session.jsonl", "README.md"])
        self.assertEqual(rc, 0, out)


def mustfail():
    """直す前の版(.bak)に同じ入力を渡して、**判定で**赤くなることを確かめる。

    ★import で落ちる赤は検査ではない= 古い main() を実際に走らせ、
      「生きている箱4つを退避しろと言う」ところを現物で見る。
    """
    bak = os.path.join(_HERE, "check_inbox_hygiene.py.bak_20260916_sessionbox")
    if not os.path.exists(bak):
        print("控えが無い: " + bak)
        return 1
    old = _load(bak, "check_inbox_hygiene_old")
    print("直す前の版に、実測どおりの箱の並びを渡す…")
    rc, out = run_against(old, LIVE)
    if rc == 0:
        print("  ✗ 赤くならなかった(この検査は意味を成していない)")
        return 1
    print("  ✓ 判定FAIL(期待どおりの赤):")
    for ln in out.strip().splitlines():
        print("    " + ln)
    if "退避" not in out:
        print("  ✗ 退避を指示していない= 再現できていない")
        return 1
    print("直した版に同じ入力を渡す…")
    rc2, out2 = run_against(HYGIENE, LIVE)
    print("  " + out2.strip())
    return 0 if rc2 == 0 else 1


if __name__ == "__main__":
    if "--mustfail" in sys.argv:
        sys.exit(mustfail())
    unittest.main(verbosity=2)
