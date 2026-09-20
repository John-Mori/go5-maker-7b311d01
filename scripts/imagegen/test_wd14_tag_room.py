# -*- coding: utf-8 -*-
"""部屋「プロンプト変換と学習」(dept=imagetag)の検査。

依頼= Chami直令(研究室HQ DISPATCH-aegis-gl-1789535197199)。
  「ここの部屋に画像を貼ったらコードブロックでその画像を表現するためのプロンプト変換をする部屋に」
受入条件(HQ)= 「画像を1枚貼ると、数秒でコードブロックのタグ列が返ってくる」。

★判定と分岐は**本物のまま**通す。偽物にするのは外へ出る手だけ=
  Discordへの送信(bot_send=lr.subprocess.run)・台帳追記(append_line/log)・
  タガー本体の起動(wd14_tag.subprocess.run)。
  ★タガーの出力の**読み方と組み立て方**(prompt_of / format_reply)は本物が通る=
    「コードブロックで返る」かどうかを、文字列一致の保険ではなく実際の組み立てで測る。

    python scripts/imagegen/test_wd14_tag_room.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import rooms                      # noqa: E402
import wd14_tag                   # noqa: E402
import local_responder as lr      # noqa: E402

# 実物のタガーが返した形(2026-09-16 local/attachments/1549517543079804996_0.png・実測)
REAL_OUTPUT = {
    "ok": True,
    "items": [{
        "path": "x.png",
        "general": ["fake_screenshot", "multiple_girls", "brown_hair", "^_^"],
        "character": ["hakurei_reimu"],
        "rating": "sensitive",
        "scores": {},
    }],
}


class _Proc(object):
    def __init__(self, stdout="", rc=0):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = ""


class Harness(object):
    """外へ出る手だけを受け止める。何をタグにするか・返すかは本物が決める。

    ★`lr.subprocess` と `wd14_tag.subprocess` は**同じモジュール実体**だ=
      片方ずつ差し替えると後勝ちで、タガーの返事が送信の返事として返る
      (最初に書いた版はこれで「送っていないのに sent=True」になった)。
      だから差し替えは1枚にして、**argvを見て行き先を分ける**。
      どちらの手が呼ばれたかは、ここが唯一の記録になる。
    """

    def __init__(self, tagger_stdout=None, tagger_rc=0, persona_rc=0, persona_stdout=""):
        self.tagger_stdout = json.dumps(REAL_OUTPUT, ensure_ascii=False) \
            if tagger_stdout is None else tagger_stdout
        self.tagger_rc = tagger_rc
        # 人格の口(persona_send)が落ちた時の退避を測るための細工。
        #   persona_stdout に "送信OK" が在る=1通は出た後の失敗= 退避してはいけない形。
        self.persona_rc = persona_rc
        self.persona_stdout = persona_stdout
        self.sent = []          # bot_send へ渡した argv
        self.tagged = []        # タガーへ渡した argv
        self.other = []         # どちらでもない外部起動(在ってはいけない)
        self.logged = []
        self.appended = []
        self.queued = []        # 使い捨てキューへ積まれた行(msg_id, dept, body)
        self._orig = {}

    def __enter__(self):
        self._orig = {"run": subprocess.run, "log": lr.log, "append_line": lr.append_line,
                      "qdb": lr.QDB}
        subprocess.run = self._run
        lr.log = lambda d: self.logged.append(d)
        lr.append_line = lambda p, l: self.appended.append((p, l))
        # ★キューは**使い捨てのDB**へ向ける(2026-09-20)。
        #   ここを本物(local/queue/inbox.db)のままにしていたら、字だけの便の検体
        #   「このプロンプトどう思う?」が本番のキューへ入り、カスミの常駐が拾って
        #   **実際に部屋へ投稿した**(17:45:12 msg 1551152242030288935)。
        #   検査は本番の部屋を鳴らしてはいけない(共通規律「本番でテストしない」)。
        #   ★積む手そのものは本物のまま(LeaseQueue を実際に呼ぶ)= 行き先だけを移す。
        self._qdir = tempfile.mkdtemp(prefix="tagroom_q_")
        lr.QDB = os.path.join(self._qdir, "inbox.db")
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        LeaseQueue(lr.QDB).close()          # 空の台帳を作る(handoff_to_talk は在ることを確かめてから積む)
        return self

    def __exit__(self, *a):
        subprocess.run = self._orig["run"]
        lr.log = self._orig["log"]
        lr.append_line = self._orig["append_line"]
        try:                                # 捨てる前に積まれた行を手元へ写す
            import sqlite3
            con = sqlite3.connect(lr.QDB)
            self.queued = list(con.execute("SELECT msg_id, dept, body FROM queue"))
            con.close()
        except Exception:
            self.queued = []
        lr.QDB = self._orig["qdb"]
        shutil.rmtree(self._qdir, ignore_errors=True)
        return False

    def _run(self, argv, **kw):
        argv = list(argv)
        joined = " ".join(str(a) for a in argv)
        if "_wd14_runner.py" in joined:
            self.tagged.append(argv)
            return _Proc(self.tagger_stdout, self.tagger_rc)
        if "persona_send.py" in joined:
            self.sent.append(argv)
            return _Proc(self.persona_stdout, self.persona_rc)
        if "bot_send.py" in joined:
            self.sent.append(argv)
            return _Proc()
        self.other.append(argv)
        return _Proc()

    def body(self):
        if not self.sent:
            raise AssertionError("部屋へ1本も出していない")
        return self.sent[0][-1]

    def modes(self):
        return [d.get("mode") for d in self.logged]


def deliver(content="", images=0, h=None):
    """本物の handle_tag_request() をそのまま通す。images>0 なら実在する画像ファイルを添える。"""
    tmp = []
    for i in range(images):
        fd, p = tempfile.mkstemp(suffix=".png")
        os.write(fd, b"\x89PNG\r\n\x1a\n")
        os.close(fd)
        tmp.append(p)
    rec = {"content": content, "channel": "プロンプト変換と学習", "dept": "imagetag",
           "msg_id": "test-tag-0001", "author": "chami_fusoh",
           "attachments": [], "attachments_local": tmp}
    h = h or Harness()
    try:
        with h:
            lr.handle_tag_request(rec, json.dumps(rec, ensure_ascii=False))
    finally:
        for p in tmp:
            try:
                os.remove(p)
            except OSError:
                pass
    return h


class TestPromptBuilding(unittest.TestCase):
    """タガーの生の出力 → そのまま貼れる1行のプロンプト。"""

    def test_character_tags_come_first(self):
        line = wd14_tag.prompt_of(REAL_OUTPUT["items"][0])
        self.assertTrue(line.startswith("hakurei reimu"), line)

    def test_underscores_open_into_spaces(self):
        line = wd14_tag.prompt_of(REAL_OUTPUT["items"][0])
        self.assertIn("fake screenshot", line)
        self.assertIn("multiple girls", line)

    def test_emoticon_tags_are_left_alone(self):
        # `^_^` の `_` まで開くとタグが壊れる。英数字だけのタグにしか触らない。
        self.assertIn("^_^", wd14_tag.prompt_of(REAL_OUTPUT["items"][0]))

    def test_rating_is_not_a_prompt_word(self):
        # rating(sensitive/general…)は分類であってプロンプトではない。
        self.assertNotIn("sensitive", wd14_tag.prompt_of(REAL_OUTPUT["items"][0]))


class TestTagRoomAnswers(unittest.TestCase):
    """画像を貼った時=コードブロックのタグ列が**この部屋へ**返る。"""

    def test_an_image_gets_a_code_block(self):
        h = deliver(images=1)
        body = h.body()
        self.assertIn("```", body)
        self.assertIn("hakurei reimu", body)
        self.assertIn("fake screenshot", body)

    def test_the_code_block_holds_only_the_prompt(self):
        # 囲みの中身は貼って使う物= 見出しや rating を混ぜない。
        inner = h_inner(deliver(images=1).body())
        self.assertNotIn("rating", inner)
        self.assertNotIn("**", inner)
        self.assertEqual(inner, wd14_tag.prompt_of(REAL_OUTPUT["items"][0]))

    def test_the_reply_goes_to_the_tag_room_by_dept(self):
        argv = deliver(images=1).sent[0]
        self.assertIn("--dept", argv)
        self.assertEqual(argv[argv.index("--dept") + 1], lr.TAG_DEPT)

    def test_it_is_logged_as_tagged(self):
        self.assertIn("tagged", deliver(images=1).modes())

    def test_the_reply_wears_the_yui_name(self):
        # ★2026-09-20 Chami直令 msg 1551158137002795042「あとマルチエージェントじゃなくて
        #   優依が出してください」= 生のBot名義で出さない。
        #   素のBot APIは投稿者名を上書きできない(Discordの仕様)ので、名義を替える口は
        #   webhook=persona_send だけだ。旧検査(bot_send を使うこと)はこの直令で失効した。
        #   ★乗り換えの前提「口調ゲートは英語のタグ列を削らない」は実測で確かめてある
        #     (local/_work/_tagreply_gate_probe.py・4形とも本文は1文字も変わらない)。
        argv = deliver(images=1).sent[0]
        self.assertTrue(any(a.endswith("persona_send.py") for a in argv), argv)
        self.assertFalse(any(a.endswith("bot_send.py") for a in argv), argv)
        self.assertEqual(argv[argv.index("--persona") + 1], lr.PERSONA)
        self.assertEqual(argv[argv.index("--suffix") + 1], lr.PERSONA_SUFFIX)

    def test_the_tag_list_reaches_the_mouth_untouched(self):
        # 名義を替えても本文は痩せない= 柵の中身は組み立てたプロンプトそのままで口へ渡る。
        argv = deliver(images=1).sent[0]
        self.assertEqual(h_inner(argv[-1]), wd14_tag.prompt_of(REAL_OUTPUT["items"][0]))

    def test_a_dead_persona_mouth_falls_back_to_the_bot_mouth(self):
        # 人格の口が落ちた時に黙るとタグ列そのものが消える。出し直す先は素のBotの口。
        h = deliver(images=1, h=Harness(persona_rc=4))
        self.assertEqual(len(h.sent), 2, h.sent)
        self.assertTrue(any(a.endswith("bot_send.py") for a in h.sent[1]), h.sent[1])
        self.assertEqual(h.sent[1][-1], h.sent[0][-1])          # 同じ本文を出し直す

    def test_a_half_sent_persona_mouth_does_not_double_post(self):
        # 分割連投の途中で落ちた(=1通は部屋に出ている)形で退避すると二重投稿になる。
        h = deliver(images=1, h=Harness(persona_rc=3, persona_stdout="送信OK → プロンプト変換と学習"))
        self.assertEqual(len(h.sent), 1, h.sent)


class TestTheTriggerIsTheAttachment(unittest.TestCase):
    """引き金は「画像の添付そのもの」= 合図語を実装側で発明しない(研究室HQ裁定)。"""

    def test_text_without_an_image_is_not_answered_by_yui(self):
        # 優依が喋るのは画像便だけ= この線は動かさない。
        # ★2026-09-20 Chami直令(DISPATCH-aegis-gl-1789845665234)で、字の便は黙殺ではなく
        #   同じ部屋のカスミ(TALK_DEPT)へ積み直す形になった= 旧 mode=tag_no_image は
        #   「本文も添付も空の便」だけに残る。
        h = deliver(content="このプロンプトどう思う?", images=0)
        self.assertEqual(h.sent, [])
        self.assertIn("tag_talk_handoff", h.modes())
        self.assertEqual([d for _, d, _ in h.queued], [lr.TALK_DEPT])

    def test_an_empty_envelope_wakes_nobody(self):
        # 本文も添付も無い便(スタンプだけ等)は誰も起こさない=積み直しもしない。
        h = deliver(content="", images=0)
        self.assertEqual(h.sent, [])
        self.assertEqual(h.queued, [])
        self.assertIn("tag_no_image", h.modes())

    def test_the_cue_word_alone_does_not_trigger(self):
        h = deliver(content="生成依頼 銀髪ロング", images=0)
        self.assertEqual(h.sent, [])

    def test_an_image_with_no_text_still_triggers(self):
        self.assertIn("```", deliver(content="", images=1).body())


class TestFailuresAreSpoken(unittest.TestCase):
    """失敗した時に**黙らない**(この部屋の失敗は「無言」ではなく「理由」であるべき)。"""

    def test_a_broken_tagger_is_reported_not_swallowed(self):
        h = deliver(images=1, h=Harness(tagger_stdout="", tagger_rc=9))
        self.assertIn("うまくいかなかった", h.body())
        self.assertNotIn("```", h.body())
        self.assertIn("tag_failed", h.modes())


class TestTheImageRoomsAreUntouched(unittest.TestCase):
    """C-035= 名指しの部屋の話を他の部屋へ広げない。"""

    def test_the_tag_room_is_not_an_imagegen_room(self):
        # ROOMS に入れると gateway の画像ファンアウトと合図規律が巻き込む。
        self.assertNotIn("imagetag", rooms.ROOMS)

    def test_the_tag_room_is_outside_the_cue_rule(self):
        self.assertFalse(rooms.cue_required("imagetag"))
        self.assertNotIn("imagetag", rooms.CUE_REQUIRED_DEPTS)

    def test_the_lora_rooms_still_require_their_cue(self):
        self.assertTrue(rooms.cue_required("imagegen-fusoh-v0"))
        self.assertTrue(rooms.cue_required("imagegen-fusoh-v2"))


class TestTheQueueRowIsFolded(unittest.TestCase):
    """優依がこの部屋のキュー行を畳む= 45秒の受領スタンプ/30分のエスカレを起こさない。"""

    class _Q(object):
        def __init__(self, rows):
            self.rows = list(rows)
            self.acked = []
            self.closed = False

        def claim(self, dept, who=""):
            for i, r in enumerate(self.rows):
                if r["dept"] == dept:
                    return self.rows.pop(i)
            return None

        def ack(self, _id, result=""):
            self.acked.append((_id, result))

        def close(self):
            self.closed = True

    def test_both_rooms_are_drained(self):
        q = self._Q([
            {"id": 1, "dept": "llm-growth", "msg_id": "m1",
             "body": {"content": "やあ", "channel": "ローカルllm成長進捗",
                      "dept": "llm-growth", "msg_id": "m1"}},
            {"id": 2, "dept": "imagetag", "msg_id": "m2",
             "body": {"content": "", "channel": "プロンプト変換と学習",
                      "dept": "imagetag", "msg_id": "m2",
                      "attachments": [], "attachments_local": []}},
        ])
        seen = []
        orig = (lr.QDB, lr.handle, lr.handle_tag_request, lr._processed_msg_ids)
        try:
            lr.QDB = __file__                       # 「DBが在る」だけ満たす
            lr.handle = lambda rec, raw, **kw: seen.append(("growth", rec["msg_id"]))
            lr.handle_tag_request = lambda rec, raw: seen.append(("tag", rec["msg_id"]))
            lr._processed_msg_ids = lambda: set()
            sys.modules.setdefault("leasequeue", _FakeLeaseQueueModule(q))
            sys.modules["leasequeue"] = _FakeLeaseQueueModule(q)
            n = lr.drain_queue()
        finally:
            lr.QDB, lr.handle, lr.handle_tag_request, lr._processed_msg_ids = orig
            sys.modules.pop("leasequeue", None)
        self.assertEqual(seen, [("growth", "m1"), ("tag", "m2")])
        self.assertEqual(n, 2)
        self.assertEqual([r for _i, r in q.acked], ["qwen応答", "タグ列"])


class _FakeLeaseQueueModule(object):
    def __init__(self, q):
        self._q = q

    def LeaseQueue(self, _path):
        return self._q


def h_inner(body):
    """コードブロックの中身だけ取り出す。"""
    parts = body.split("```")
    if len(parts) < 3:
        raise AssertionError("コードブロックが無い: " + body[:120])
    return parts[1].strip()


if __name__ == "__main__":
    unittest.main(verbosity=2)
