# -*- coding: utf-8 -*-
"""閉じた描画室で絵が出なかった時、**誰へ行くか**の検査(2026-09-22 イージス研究室)。

依頼= Chami直令 msg 1551691197020508272(🛡️イージス研究室 05:26:50)=
  「その時はローカル研究室に対応させて。ローカル内のことだから。」
  直前の流れ= Claude常駐を閉じた4室(rooms.NO_CLAUDE_DEPTS)は、不具合が起きても中に応答者が
  居ない、と当室が答えた。その「その時」の受け先をChamiが指名した。

★塞いだ穴= local_responder.handle_image_request の失敗経路は、最後に FOR_CLAUDE(main箱)へ
  積んでいた。閉室の目的(msg 1551680397103071355)は「この部屋のことでClaudeを起こして
  課金しない」なのに、失敗のたび main箱経由でClaudeが起きる=閉めた意味が裏口から抜ける。

★ソースの文字列一致では見ない(C-053)。**入力(local_chain の結果と dispatch の呼び出し)だけ
  偽物に差し替え、判定と分岐は本物のまま実行で通す**。外へ出る手(subprocess / 投稿 / 箱への追記)
  は全部握って、どこへ何が出たかを数える。

    python scripts/imagegen/test_trouble_routing.py
"""
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import rooms                       # noqa: E402
import local_responder as lr       # noqa: E402

CLOSED = sorted(rooms.NO_CLAUDE_DEPTS)[0]      # Claudeを閉じた部屋(実在)
OPEN_DEPT = "imagegen-open-test"               # Claudeが聞いている描画室(架空)


class Fake(object):
    """外へ出る手を全部ここで受け止める。何も送らない・何も書かない。"""

    def __init__(self, chain_rc=1, dispatch_rc=0):
        self.chain_rc = chain_rc
        self.dispatch_rc = dispatch_rc
        self.runs = []          # subprocess.run に渡った argv
        self.sent = []          # 部屋へ出た本文
        self.sent_as = []       # 別名義で部屋へ出た本文
        self.appended = []      # (箱のpath, 行)
        self.logs = []          # responder_log へ落ちた行

    # --- 外部プロセス(local_chain と dispatch)
    def run(self, argv, **kw):
        self.runs.append(list(argv))
        rc = self.dispatch_rc if any("dispatch.py" in str(a) for a in argv) else self.chain_rc
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": "boom"})()

    def send(self, channel, text):
        self.sent.append((channel, text))

    def send_as(self, channel, text, persona, suffix=""):
        self.sent_as.append((channel, text, persona))
        return True

    def append_line(self, path, line):
        self.appended.append((path, line))

    def log(self, rec):
        self.logs.append(rec)

    # --- 読み取り
    def dispatches(self):
        return [a for a in self.runs if any("dispatch.py" in str(x) for x in a)]

    def dispatch_dept(self):
        a = self.dispatches()[0]
        return a[a.index("--dept") + 1]

    def to_claude_box(self):
        return [p for p, _ln in self.appended if p == lr.FOR_CLAUDE]


class Routing(unittest.TestCase):

    def setUp(self):
        self.fake = Fake()
        self._orig = (lr.subprocess.run, lr.send, lr.send_as, lr.append_line, lr.log,
                      lr.TROUBLE_STATE)
        lr.subprocess.run = self.fake.run
        lr.send = self.fake.send
        lr.send_as = self.fake.send_as
        lr.append_line = self.fake.append_line
        lr.log = self.fake.log
        fd, self.state = tempfile.mkstemp(prefix="trouble_state_", suffix=".json")
        os.close(fd)
        os.remove(self.state)                  # 印はまだ1つも無い状態から始める
        lr.TROUBLE_STATE = self.state

    def tearDown(self):
        (lr.subprocess.run, lr.send, lr.send_as, lr.append_line, lr.log,
         lr.TROUBLE_STATE) = self._orig
        rooms.ROOMS.pop(OPEN_DEPT, None)
        if os.path.exists(self.state):
            os.remove(self.state)

    def _fail_a_draw(self, dept, content="銀髪ロング 制服 桜"):
        """その部屋で1件、生成を失敗させて通す(local_chain は必ず rc!=0 を返す)。"""
        rec = {"content": content, "attachments_local": []}
        raw = json.dumps(rec, ensure_ascii=False)
        return lr.handle_image_request(rec, raw, content, rooms.channel_name(dept) or dept,
                                       dept=dept, cue=None)

    # ------------------------------------------------------------------ 閉じた部屋
    def test_a_closed_room_hands_the_failure_to_the_local_lab(self):
        """★Chamiが指名した受け先へ実際に1本出ているか(部門名は rooms.trouble_dept が正本)。"""
        self._fail_a_draw(CLOSED)
        self.assertEqual(len(self.fake.dispatches()), 1, "直せる部門へ1本も出ていない")
        self.assertEqual(self.fake.dispatch_dept(), rooms.trouble_dept(CLOSED))
        self.assertEqual(rooms.trouble_dept(CLOSED), "local-lab")

    def test_a_closed_room_does_not_wake_claude(self):
        """★閉室の目的そのもの= 失敗が main箱へ積まれてClaudeが起きる裏口を残さない。"""
        self._fail_a_draw(CLOSED)
        self.assertEqual(self.fake.to_claude_box(), [], "閉じた部屋の失敗をmain箱へ積んでいる")

    def test_the_room_is_told_where_it_went(self):
        """部屋のChamiには黙らない= 誰が見に行くかを1本返す(沈黙の事故を作らない)。"""
        self._fail_a_draw(CLOSED)
        said = " ".join(t for _c, t in self.fake.sent)
        self.assertIn("ローカル研究室", said)
        self.assertNotIn("Claude側に引き取って", said)

    def test_the_relay_is_a_work_handoff_not_a_whisper(self):
        """--work 付き= 相手に手番が有る実依頼(C-023)。--also-post は付けない(口を増やさない)。"""
        self._fail_a_draw(CLOSED)
        argv = self.fake.dispatches()[0]
        self.assertIn("--work", argv)
        self.assertIn("--audience", argv)
        self.assertEqual(argv[argv.index("--audience") + 1], "ai")
        self.assertNotIn("--also-post", argv)
        self.assertNotIn("--quiet-ack-ok", argv, "手番の有る便を黙らせている")

    def test_the_body_carries_the_room_and_the_reason(self):
        """本文に部屋と理由が乗っているか= 受けた側が現場を探さずに動ける。"""
        self._fail_a_draw(CLOSED)
        argv = self.fake.dispatches()[0]
        path = argv[argv.index("--body-file") + 1]
        with open(path, encoding="utf-8") as f:
            body = f.read()
        self.assertIn(CLOSED, body)
        self.assertIn("1551691197020508272", body, "何の指示で回しているかが本文に無い")
        self.assertIn("boom", body, "local_chain が吐いた理由が落ちている")

    def test_the_same_trouble_does_not_flood_the_lab(self):
        """★同じ部屋の同じ型は30分に1本。★ただし2件目を**Claudeへ流し直さない**
        (「直近に出した」は届いていないことではない)。"""
        self._fail_a_draw(CLOSED)
        self._fail_a_draw(CLOSED)
        self.assertEqual(len(self.fake.dispatches()), 1, "同じ不具合を連投している")
        self.assertEqual(self.fake.to_claude_box(), [], "2件目がmain箱へ落ちている")

    def test_if_the_relay_fails_the_request_is_not_lost(self):
        """★回送そのものが失敗した時だけ、従来の受け皿(main箱)へ落として便を守る。"""
        self.fake.dispatch_rc = 1
        self._fail_a_draw(CLOSED)
        self.assertEqual(len(self.fake.dispatches()), 1)
        self.assertEqual(len(self.fake.to_claude_box()), 1, "回送に失敗した便が消えている")

    # ------------------------------------------------------------------ 開いている部屋
    def test_a_room_where_claude_listens_keeps_the_old_path(self):
        """★巻き添えを出さない= 開いている部屋の失敗は今までどおりClaudeへ。"""
        rooms.ROOMS[OPEN_DEPT] = {"lora_hint": None, "persona": "優依",
                                  "ckpt": rooms.ROOMS["imagegen"]["ckpt"],
                                  "label": "検査用(架空・開いている部屋)"}
        self._fail_a_draw(OPEN_DEPT)
        self.assertEqual(self.fake.dispatches(), [], "開いている部屋の失敗まで回送している")
        self.assertEqual(len(self.fake.to_claude_box()), 1)
        said = " ".join(t for _c, t in self.fake.sent)
        self.assertIn("Claude側に引き取って", said)

    # ------------------------------------------------------------------ 台帳の形
    def test_the_destination_lives_in_the_room_table(self):
        """★受け先の正本は1か所(ORG-11)= 閉室の名簿をその場で読む形になっているか。

        部屋を1つ閉じ足しただけで受け先が継がれること(=名簿を二重に持たない)を、
        架空室を NO_CLAUDE_DEPTS へ足して実行で見る。
        """
        orig = rooms.NO_CLAUDE_DEPTS
        try:
            rooms.NO_CLAUDE_DEPTS = tuple(orig) + (OPEN_DEPT,)
            self.assertEqual(rooms.trouble_dept(OPEN_DEPT), rooms.TROUBLE_DEPT)
        finally:
            rooms.NO_CLAUDE_DEPTS = orig
        self.assertIsNone(rooms.trouble_dept(OPEN_DEPT))
        self.assertIsNone(rooms.trouble_dept("hq"), "描画室でない部屋まで引き取らせている")


if __name__ == "__main__":
    unittest.main(verbosity=2)
