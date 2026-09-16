# -*- coding: utf-8 -*-
"""合図ゲート(雑談と画像注文の線引き)の検査。

依頼= アメス便 1549468992396329025(依頼元 imagegen-fusoh-v0)。
★2026-09-16 03:0x 合図を**「生成依頼」で始まる時だけ**の1本に絞った(Chami直
  msg 1549476416641572937 / 1549477000807194637「1。でも印はいらんかな」)。
  `!描`系の印と「〜の絵を描いて」の曖昧マッチは、この2室では引き金にしない。
★この検査は**判定と分岐を本物のまま**通す。偽物にするのは外へ出る手だけ=
  Discordへの送信(send)・ファイル追記(append_line/log)・ComfyUIの起動(subprocess.run)。
★旧コード(scripts/llm/local_responder.py.bak_20260916_cue)に当てると
  test_chitchat_is_not_drawn が落ちる=直る前に落ちる検査になっている。

    python scripts/imagegen/test_image_cue.py
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import rooms                      # noqa: E402
import local_responder as lr      # noqa: E402

# 実害そのものの文(アメス便の実例)
CHITCHAT = "これデーモン?デーモンの返信いらんよ"


class _Proc(object):
    returncode = 0
    stdout = ""
    stderr = ""


class Harness(object):
    """外へ出る手だけを受け止める。分岐は本物が決める。"""

    def __init__(self):
        self.sent = []          # (channel, text)
        self.sent_as = []       # (channel, text, persona)
        self.logged = []        # log() の辞書
        self.appended = []      # (path, line)
        self.spawned = []       # local_chain へ渡した argv
        self._orig = {}

    def __enter__(self):
        self._orig = {
            "send": lr.send, "send_as": lr.send_as, "log": lr.log,
            "append_line": lr.append_line, "run": lr.subprocess.run,
        }
        lr.send = lambda ch, text, **kw: (self.sent.append((ch, text)), True)[1]
        lr.send_as = lambda ch, text, persona, suffix="": (
            self.sent_as.append((ch, text, persona)), True)[1]
        lr.log = lambda d: self.logged.append(d)
        lr.append_line = lambda p, l: self.appended.append((p, l))
        lr.subprocess.run = self._run
        return self

    def _run(self, argv, **kw):
        self.spawned.append(list(argv))
        return _Proc()

    def __exit__(self, *a):
        lr.send = self._orig["send"]
        lr.send_as = self._orig["send_as"]
        lr.log = self._orig["log"]
        lr.append_line = self._orig["append_line"]
        lr.subprocess.run = self._orig["run"]
        return False

    def modes(self):
        return [d.get("mode") for d in self.logged]

    def prompt(self):
        """local_chain へ実際に渡した本文(=絵になる文)。"""
        self.assertish()
        return self.spawned[0][2]

    def assertish(self):
        if not self.spawned:
            raise AssertionError("local_chain が起動されていない")


def deliver(text, dept, channel=None):
    """本物の handle() をそのまま通す。

    ★channel を省いたら**その部屋の実名**(台帳から引く)を使う= 本番と同じ「同じ部屋に出す」形。
      別の部屋へ貼る形(優依の自室で頼んで画像生成ルームへ出す)は channel を明示して作る。
    """
    if channel is None:
        channel = rooms.channel_name(dept) or "ローカルllm-画像生成ルーム-優依"
    rec = {"content": text, "channel": channel, "dept": dept,
           "msg_id": "test-0001", "author": "chami_fusoh"}
    h = Harness()
    with h:
        lr.handle(rec, '{"test": true}')
    return h


class TestCueTable(unittest.TestCase):
    """正本(rooms.py)の合図表そのもの。"""

    def test_only_the_two_named_rooms_require_a_cue(self):
        self.assertTrue(rooms.cue_required("imagegen-fusoh-v0"))
        self.assertTrue(rooms.cue_required("imagegen-fusoh-v2"))
        self.assertFalse(rooms.cue_required("imagegen"))   # 既存室は変えない(C-035)

    def test_the_table_is_derived_from_the_lora_rooms(self):
        """★2026-09-16 13:25 Chami「今後も1LoRAにつき1部屋を立てる。ルールは統一。」
        合図の要る部屋= LoRAを持つ部屋。名簿を別に持たない(=二重管理を作らない)。
        今日の値は直書き時代と同じ2件であることも、ここで固定しておく。"""
        self.assertEqual(rooms.CUE_REQUIRED_DEPTS, rooms.lora_depts())
        self.assertEqual(set(rooms.CUE_REQUIRED_DEPTS),
                         {"imagegen-fusoh-v0", "imagegen-fusoh-v2"})

    def test_the_cue_is_exactly_one_word(self):
        """★2026-09-16 Chami直「1。でも印はいらんかな」= 引き金は「生成依頼」1本だけ。"""
        self.assertEqual(rooms.CUE_PREFIXES, ("生成依頼",))

    def test_cue_is_stripped_from_the_prompt(self):
        ok, body = rooms.order_of("imagegen-fusoh-v0", "生成依頼 銀髪ロング 制服 桜", None)
        self.assertTrue(ok)
        self.assertEqual(body, "銀髪ロング 制服 桜")

    def test_old_marks_are_now_chitchat(self):
        """★外した印(!描系・絵:系)は、もう引き金にならない=雑談として読むだけ。"""
        for head in ("!描 猫", "!draw cat", "!絵 猫", "絵:猫", "画:猫", "描いて:猫"):
            ok, _ = rooms.order_of("imagegen-fusoh-v0", head, lr.wants_image)
            self.assertFalse(ok, head)

    def test_natural_japanese_is_no_longer_a_trigger(self):
        """★「〜の絵を描いて」の曖昧マッチも外した(Chami「印はいらんかな」の前提=1本化)。"""
        ok, _ = rooms.order_of("imagegen-fusoh-v0", "女の子の絵を描いて", lr.wants_image)
        self.assertFalse(ok)

    def test_chitchat_is_rejected(self):
        ok, _ = rooms.order_of("imagegen-fusoh-v0", CHITCHAT, lr.wants_image)
        self.assertFalse(ok)

    def test_cue_only_returns_empty_body(self):
        ok, body = rooms.order_of("imagegen-fusoh-v0", "生成依頼", None)
        self.assertTrue(ok)
        self.assertEqual(body, "")

    def test_chami_trigger_word_works_with_a_newline(self):
        """★Chami本人が決めた語(2026-09-16 02:32 原文「生成依頼」)。改行を挟んだ書き方で来る。"""
        ok, body = rooms.order_of("imagegen-fusoh-v0", "生成依頼\n\n銀髪ロング 制服 桜", None)
        self.assertTrue(ok)
        self.assertEqual(body, "銀髪ロング 制服 桜")

    def test_chamis_own_typo_probe_does_not_fire(self):
        """★Chamiが**わざと**間に ‘ を入れて試した文(msg 1549476416641572937)。

        原文=「生成’依頼  で始まるチャットじゃないと生成が始まらない仕組みにして。
               間違えて生成が走らないようにこのチャットで間に ‘をあえて入れた。」
        → 頭の完全一致だから当たらない。これが「完全一致で足りるか」への実物の答え。
        """
        ok, _ = rooms.order_of("imagegen-fusoh-v0", "生成’依頼  で始まるチャットじゃないと", None)
        self.assertFalse(ok)

    def test_the_cue_must_be_at_the_head(self):
        """途中に出てきても引き金にしない=「さっきの生成依頼どうなった?」で描かない。"""
        ok, _ = rooms.order_of("imagegen-fusoh-v0", "さっきの生成依頼どうなった?", None)
        self.assertFalse(ok)

    def test_known_cost_a_sentence_starting_with_the_cue_is_an_order(self):
        """★頭一致1本にした代償(隠さず固定しておく)。

        「生成依頼のやり方教えて」は**注文として通る**(本文=「のやり方教えて」)。
        頭に置いた語で始める限り注文、というChamiの決めたとおりの挙動。
        直すならChamiの言葉を待つ(勝手に助詞を弾く判定を足さない)。
        """
        ok, body = rooms.order_of("imagegen-fusoh-v0", "生成依頼のやり方教えて", lr.wants_image)
        self.assertTrue(ok)
        self.assertEqual(body, "のやり方教えて")

    def test_help_line_is_built_from_the_table(self):
        self.assertIn(rooms.CUE_PREFIXES[0], rooms.cue_help())
        self.assertNotIn("!描", rooms.cue_help())


class TestRoomV0(unittest.TestCase):
    """fusoh_v0(手描き風・カスミ)。実害が起きた部屋。"""

    DEPT = "imagegen-fusoh-v0"

    def test_chitchat_is_not_drawn(self):
        """★これが直る前に落ちる本体。雑談でComfyUIを起こさない・部屋へ喋らない。"""
        h = deliver(CHITCHAT, self.DEPT)
        self.assertEqual(h.spawned, [], "雑談で local_chain を起動した")
        self.assertEqual(h.sent, [], "雑談に返事をした(Chami「デーモンの返信いらんよ」)")
        self.assertIn("image_no_cue", h.modes())

    def test_chitchat_is_still_counted(self):
        """黙って捨てない=台帳に残り、二度読みしないよう済にする。"""
        h = deliver(CHITCHAT, self.DEPT)
        self.assertEqual(len(h.logged), 1)
        self.assertEqual(h.logged[0].get("dept"), self.DEPT)
        self.assertTrue(h.appended, "PROCESSED に積んでいない(同じ便を何度も読む)")

    def test_cue_order_is_drawn_without_the_cue_word(self):
        h = deliver("生成依頼 銀髪ロング 制服 桜", self.DEPT)
        self.assertTrue(h.spawned, "合図付きの注文を描かなかった")
        self.assertIn("銀髪ロング 制服 桜", h.spawned[0])
        self.assertNotIn("生成依頼", " ".join(h.spawned[0]))

    def test_cue_order_is_drawn_exactly_once(self):
        """★中野五月便の完了条件=「トリガー有り=**1回だけ**生成」。"""
        h = deliver("生成依頼\n\n銀髪ロング 制服 桜", self.DEPT)
        self.assertEqual(len(h.spawned), 1, "1便で複数回走った: %r" % (h.spawned,))

    def test_natural_order_is_not_drawn_anymore(self):
        """★「〜の絵を描いて」だけでは描かない(2026-09-16 合図1本化)。"""
        h = deliver("探偵っぽい女の子の絵を描いて", self.DEPT)
        self.assertEqual(h.spawned, [], "合図無しで描いた")
        self.assertEqual(h.sent, [], "合図無しの便に返事をした")
        self.assertIn("image_no_cue", h.modes())

    def test_cue_only_asks_back_and_does_not_draw(self):
        h = deliver("生成依頼", self.DEPT)
        self.assertEqual(h.spawned, [])
        self.assertEqual(len(h.sent), 1)
        self.assertIn("image_cue_only", h.modes())

    def test_room_persona_is_kasumi(self):
        self.assertEqual(rooms.ROOMS[self.DEPT]["persona"], "カスミ")


class TestRoomV2(TestRoomV0):
    """★姉妹室にも同じ配線を効かせる(アメス便「両室に効かせてほしい」)。"""

    DEPT = "imagegen-fusoh-v2"

    def test_room_persona_is_kasumi(self):
        self.assertEqual(rooms.ROOMS[self.DEPT]["persona"], "中野五月")


class TestLoraLookup(unittest.TestCase):
    """★LoRAはフォルダ名で分けてよい(2026-09-16 Chami質問への答えを実物で固定する)。"""

    def setUp(self):
        import tempfile
        self._orig = rooms.LORA_DIR
        self.tmp = tempfile.mkdtemp(prefix="loras_")
        rooms.LORA_DIR = self.tmp

    def tearDown(self):
        import shutil
        rooms.LORA_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _put(self, *parts):
        path = os.path.join(self.tmp, *parts)
        d = os.path.dirname(path)
        if not os.path.isdir(d):
            os.makedirs(d)
        io_open = open(path, "wb")
        io_open.write(b"x")
        io_open.close()
        return path

    def test_folder_name_is_enough(self):
        """置き場/fusoh_v0/なんでもいい名前.safetensors → 拾う。"""
        self._put("fusoh_v0", "model.safetensors")
        name, why = rooms.find_lora("imagegen-fusoh-v0")
        self.assertEqual(name, "fusoh_v0/model.safetensors", why)

    def test_file_name_still_works(self):
        """直置きのファイル名で入っている従来の形も変わらず拾う。"""
        self._put("fusoh_v2_style.safetensors")
        name, _ = rooms.find_lora("imagegen-fusoh-v2")
        self.assertEqual(name, "fusoh_v2_style.safetensors")

    def test_the_other_rooms_lora_is_not_picked_up(self):
        """★隣の部屋のLoRAを間違って着せない(v0のフォルダしか無い時にv2は拾わない)。"""
        self._put("fusoh_v0", "model.safetensors")
        name, why = rooms.find_lora("imagegen-fusoh-v2")
        self.assertIsNone(name, why)
        self.assertIn("フォルダ", why)


class TestNoNarration(unittest.TestCase):
    """★優依は画像室で実況を喋らない(2026-09-16 Chami直=「デーモンが話す配線は恒久的にいらん」)。

    2026-07-27にChamiが確定させた設計= 「打ったら本人に届く/普段は黙る/問題だけ上がる」。
    絵が同じ部屋に出るなら**絵そのものが返事**だ。言葉が要るのは別の部屋へ出した時だけ。
    """

    def test_order_in_the_room_produces_no_words(self):
        h = deliver("生成依頼 銀髪ロング 制服 桜", "imagegen-fusoh-v0")
        self.assertTrue(h.spawned, "注文を描かなかった")
        self.assertEqual(h.sent, [], "絵と一緒に実況を喋った: %r" % (h.sent,))
        self.assertEqual(h.sent_as, [], "別名義で実況を喋った: %r" % (h.sent_as,))

    def test_order_in_v2_room_produces_no_words(self):
        h = deliver("生成依頼 制服 教室", "imagegen-fusoh-v2")
        self.assertTrue(h.spawned)
        self.assertEqual(h.sent, [])

    def test_cross_room_still_says_where_it_went(self):
        """★別の部屋へ貼る時だけは言う=黙るとどこへ出たか分からない(沈黙の事故)。"""
        h = deliver("女の子の絵を描いて", "imagegen", channel="ローカルllm成長進捗")
        self.assertTrue(h.spawned)
        self.assertTrue(h.sent, "別部屋へ貼ったのに、行き先を誰にも言わなかった")
        self.assertIn("ローカルllm-画像生成ルーム-優依", " ".join(t for _, t in h.sent))


class TestReplayOfRealChamiMessages(unittest.TestCase):
    """★実物の再生。2026-09-16 深夜にChamiがfusoh_v0室へ実際に打った4便を、
    台帳(local/discord_processed.jsonl / responder_log.jsonl)から起こしてそのまま通す。
    「登録だけで完了にしない」(中野五月便の条件)の、机の上で出来る側の証拠。
    """

    DEPT = "imagegen-fusoh-v0"

    # (実文, 描くか)
    REAL = [
        ("生成依頼\n\nこれがひとまずトリガーワードの一つとして設定しといて", True),
        ("生成’依頼  で始まるチャットじゃないと生成が始まらない仕組みにして。"
         "間違えて生成が走らないようにこのチャットで間に ‘をあえて入れた。", False),
        ("1。でも印はいらんかな", False),
        ("これデーモン?デーモンの返信いらんよ", False),
    ]

    def test_replay(self):
        for text, should_draw in self.REAL:
            h = deliver(text, self.DEPT)
            if should_draw:
                self.assertTrue(h.spawned, "描くはずが描かなかった: %r" % (text[:24],))
            else:
                self.assertEqual(h.spawned, [], "描かないはずが描いた: %r" % (text[:24],))
                self.assertEqual(h.sent, [], "黙るはずが喋った: %r" % (text[:24],))
                self.assertIn("image_no_cue", h.modes(), text[:24])


class TestNewLoraRoomInheritsTheCue(unittest.TestCase):
    """★3つ目のLoRA部屋を建てた時、**誰も手を動かさずに**合図ルールが継がれるか。

    依頼= カスミ便 DISPATCH-aegis-gl-1789532909454(依頼元 imagegen-fusoh-v0)。
    Chami原文=「今後も1LoRAにつき1部屋を立てる。」「ルールは統一。」
      (msg 1549637220883759176 / 1549637278559895655・2026-09-16 13:25 JST)

    ★この検査は**判定と分岐を本物のまま**通す。偽物にするのは外へ出る手だけ(Harness)。
    ★旧コード(scripts/imagegen/rooms.py.bak_20260916_cue_auto=直書きの名簿)に当てると
      test_a_brand_new_lora_room_requires_the_cue が落ちる=直る前に落ちる検査だ。
      (旧 cue_required は `dept in CUE_REQUIRED_DEPTS` の名簿一致なので、
       ROOMSへ足しただけの新室は合図なしで素通し=雑談で絵が走る側へ倒れる)
    """

    DEPT = "imagegen-fusoh-v9"      # ★架空の3室目。テストの中だけで建てて、必ず畳む。

    def setUp(self):
        rooms.ROOMS[self.DEPT] = {
            "channel_id": "000000000000000000",
            "lora_hint": "fusoh_v9",
            "lora_strength": 0.8,
            "ckpt": rooms.ROOMS["imagegen-fusoh-v0"]["ckpt"],
            "persona": "優依",
            "label": "fusoh_v9(検査用の架空室)",
        }

    def tearDown(self):
        rooms.ROOMS.pop(self.DEPT, None)

    def test_a_brand_new_lora_room_requires_the_cue(self):
        """ROOMSへ1件足しただけ。合図の名簿には**何も書いていない**。"""
        self.assertTrue(rooms.cue_required(self.DEPT),
                        "新しいLoRA部屋が合図ルールを継がなかった(手で足す必要が残っている)")
        self.assertIn(self.DEPT, rooms.lora_depts())

    def test_chitchat_in_the_new_room_is_not_drawn(self):
        """統一の中身=雑談で絵が走らない。実害の文(アメス便の実例)をそのまま通す。"""
        h = deliver(CHITCHAT, self.DEPT, channel="検査用-架空のLoRA部屋")
        self.assertEqual(h.spawned, [], "新室で雑談を描いた")
        self.assertEqual(h.sent, [], "新室で雑談に返事をした")
        self.assertIn("image_no_cue", h.modes())

    def test_cue_order_in_the_new_room_is_drawn_once(self):
        h = deliver("生成依頼 銀髪ロング 制服 桜", self.DEPT, channel="検査用-架空のLoRA部屋")
        self.assertEqual(len(h.spawned), 1, "新室で合図付きの注文が走らなかった: %r" % (h.spawned,))
        self.assertNotIn("生成依頼", " ".join(h.spawned[0]))

    def test_a_new_room_without_a_lora_is_still_untouched(self):
        """★LoRA無しの部屋を建てた場合は従来どおり素通し(C-035の線はそのまま)。"""
        rooms.ROOMS["imagegen-plain-test"] = {"lora_hint": None, "persona": "優依",
                                              "ckpt": rooms.ROOMS["imagegen"]["ckpt"],
                                              "label": "検査用(LoRA無し)"}
        try:
            self.assertFalse(rooms.cue_required("imagegen-plain-test"))
        finally:
            rooms.ROOMS.pop("imagegen-plain-test", None)


class TestExistingRoomUnchanged(unittest.TestCase):
    """既存の imagegen 室= Chamiは名指ししていない。挙動を1文字も変えない(C-035)。"""

    def test_chitchat_is_still_drawn_there(self):
        h = deliver(CHITCHAT, "imagegen")
        self.assertTrue(h.spawned, "既存室の挙動を勝手に変えた")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    unittest.main(verbosity=2)
