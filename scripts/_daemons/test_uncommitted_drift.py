#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uncommitted_drift.py の検査(C-079)。

見ているのは4つ=
  ① 持ち主を **後ろから** 引いている(同じファイルを複数部門が触っていたら最後の部門が勝つ)
  ② 1行が **件数だけ** になっていない(age と 持ち主 と ファイル名が必ず載る / C-079の★)
  ③ 並びが **age 降順**(増分ではなく age を見ろ)
  ④ git へ **書く** 動詞を1つも持っていない(読むだけ)
実物でも1回走らせて、常駐の名指しが空でない事だけ確かめる(数は日々動くので固定しない)。
"""
import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import uncommitted_drift as ud                             # noqa: E402


class TestOwner(unittest.TestCase):
    def rows(self):
        return [
            {"ts": "2026-09-01T10:00:00", "dept": "hq", "触った": "scripts/llm/a.py を直した"},
            {"ts": "2026-09-05T10:00:00", "dept": "aegis-gl", "触った": "scripts\\llm\\a.py と b"},
            {"ts": "2026-09-06T10:00:00", "dept": "platform-se", "触った所": "scripts/llm/c.py"},
            {"ts": "2026-09-07T10:00:00", "dept": "kaizen-analyst", "何": "a.py の話をしただけ"},
        ]

    def test_last_writer_wins(self):
        """後ろから引く= 9/1のhqではなく9/5のaegis-glが持ち主。"""
        dept, how, ts = ud.owner_of("scripts/llm/a.py", self.rows())
        self.assertEqual((dept, how), ("aegis-gl", "path"))
        self.assertEqual(ts, "2026-09-05T10:00:00")

    def test_windows_separator_hits(self):
        self.assertEqual(ud.owner_of("scripts/llm/a.py", self.rows()[1:2])[1], "path")

    def test_basename_fallback_is_marked(self):
        """フルパスが無く basename でしか当たらない時は 'name' と区別して返す(誤掴み注意)。"""
        rows = [{"ts": "t", "dept": "hq", "触った": "z.py を直した"}]
        self.assertEqual(ud.owner_of("scripts/llm/z.py", rows), ("hq", "name", "t"))

    def test_unknown_owner(self):
        self.assertEqual(ud.owner_of("bat/foo.bat", self.rows())[0], None)

    def test_touch_fields_only(self):
        """`何`(作業の説明文)は持ち主の根拠にしない= 触った欄だけを引く。"""
        rows = [{"ts": "t", "dept": "kaizen-analyst", "何": "scripts/llm/a.py"}]
        self.assertIsNone(ud.owner_of("scripts/llm/a.py", rows)[0])


class TestOneLine(unittest.TestCase):
    def report(self):
        return {"ts": "2026-09-16T04:00:00", "tracked_files": 121, "added": 4618,
                "deleted": 542, "pyc_files": 5, "resident_files": 2,
                "resident": [
                    {"file": "scripts/llm/dept_daemon.py", "daemons": ["local_responder"],
                     "add": 838, "del": 105, "age_max_days": 10.9, "age_min_days": 0.2,
                     "owner": "aegis-gl", "owner_by": "path", "owner_ts": "x"},
                    {"file": "bat/old.py", "daemons": ["office_daily"], "add": 3, "del": 0,
                     "age_max_days": 2.0, "age_min_days": 0.1, "owner": None,
                     "owner_by": None, "owner_ts": ""}],
                "owner_unknown": ["bat/old.py"], "closed": False}

    def test_line_is_not_a_bare_count(self):
        """★件数だけの通知は作るな= 1行に ファイル名・age・持ち主 が入っている事。"""
        line = ud.one_line(self.report())
        self.assertIn("121本", line)
        self.assertIn("+4618/-542", line)
        self.assertIn("dept_daemon.py", line)          # ②名指し
        self.assertIn("10.9d", line)                   # ③age
        self.assertIn("aegis-gl", line)                # ④持ち主
        self.assertIn("持ち主不明", line)

    def test_zero_resident_line_says_close_condition(self):
        """閉じ条件= 名指しした常駐ファイルの未コミットが0件になった日。その日は1行で判る事。"""
        r = self.report()
        r.update(resident=[], resident_files=0, owner_unknown=[], closed=True)
        self.assertIn("0件", ud.one_line(r))

    def test_sorted_by_age_not_by_size(self):
        """並びは age 降順(行数の多寡では並べない)。"""
        now = time.time()
        r = ud.scan(now=now)
        ages = [h["age_max_days"] or 0.0 for h in r["resident"]]
        self.assertEqual(ages, sorted(ages, reverse=True))


class TestReadOnly(unittest.TestCase):
    # 文字列で "add" 等を探すと JSON のキー名まで拾って嘘の赤になるので、**ast で
    # `_git([...])` の第1語だけ**を見る= 実際に git へ渡す副詞令だけを検査する。
    READ_ONLY = {"diff", "log", "status", "show", "rev-parse", "ls-files"}

    def _git_subcommands(self):
        import ast
        src = self._src()
        subs = []
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_git" and node.args):
                arg = node.args[0]
                self.assertIsInstance(arg, ast.List, "_git の引数がリテラルでない")
                first = arg.elts[0]
                self.assertIsInstance(first, ast.Constant, "git の第1語がリテラルでない")
                subs.append(first.value)
        return subs

    def _src(self):
        with open(os.path.join(HERE, "uncommitted_drift.py"), encoding="utf-8") as f:
            return f.read()

    def test_no_git_write_verbs(self):
        """読むだけ= git へ渡す第1語が読み取り系しか無い(C-079)。"""
        subs = self._git_subcommands()
        self.assertTrue(subs, "_git の呼び出しが1つも見つからない")
        for s in subs:
            self.assertIn(s, self.READ_ONLY, "git へ書く副詞令が入っている: %s" % s)

    def test_no_subprocess_git_write_elsewhere(self):
        """_git を通さない生の git 書き込みも無い事。"""
        src = self._src()
        for bad in ("git add", "git commit", "git push", '"commit",', '"push",'):
            self.assertNotIn(bad, src, "書き込みの痕跡: %s" % bad)

    def test_history_is_append_only(self):
        """履歴は追記のみ(上書きモードで開いていない)。"""
        src = self._src()
        self.assertIn('open(HISTORY, "a"', src)
        self.assertNotIn('open(HISTORY, "w"', src)


class TestAgainstRealRepo(unittest.TestCase):
    def test_scan_shape(self):
        r = ud.scan()
        for k in ("tracked_files", "added", "deleted", "resident", "owner_unknown", "closed"):
            self.assertIn(k, r)
        self.assertEqual(r["closed"], len(r["resident"]) == 0)
        for h in r["resident"]:
            self.assertTrue(h["daemons"], "常駐名が空の行がある: %s" % h["file"])
            self.assertIn("/", h["file"])

    def test_resident_map_covers_dept_daemon(self):
        """手書きリストではなく閉包で引けている事の実物確認(dept_daemon は SUPERVISED に
        名前が無いが、responder の閉包に必ず入る)。"""
        self.assertIn("scripts/llm/dept_daemon.py", ud.resident_map())

    def test_uncommitted_matches_git_numstat(self):
        """件数が git の実測と一致する事(自前で数え直さない)。"""
        import subprocess
        out = subprocess.run(["git", "-C", ud.ROOT, "diff", "--numstat", "HEAD"],
                             capture_output=True, encoding="utf-8", errors="replace").stdout
        n = len([l for l in out.splitlines() if l.count("\t") >= 2])
        self.assertEqual(len(ud.uncommitted()), n)

    def test_history_line_is_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "h.jsonl")
            real, ud.HISTORY = ud.HISTORY, path
            try:
                sys.argv = ["x", "--quiet"]
                ud.main()
            finally:
                ud.HISTORY = real
            with open(path, encoding="utf-8") as f:
                self.assertIn("tracked_files", json.loads(f.readline()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
