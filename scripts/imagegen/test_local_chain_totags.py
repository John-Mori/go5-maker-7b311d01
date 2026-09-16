# -*- coding: utf-8 -*-
"""local_chain.to_tags() の検査(欠陥 local_chain_rc1 = タグ列が空で返る)。

症状の実物= responder_log.jsonl 2026-09-16T14:17:22 / 画像生成ローカル-fusoh_v0手描き風
  reason=local_chain_rc1 / local_chain.py line 165 main() → line 88 to_tags() → RuntimeError

★偽物にするのは**外へ出る手だけ**= `_post`(LM Studioへのhttp)。
  空か否かの判定・拾うか諦めるか・引き直すか・例外にするかの**分岐は本物**が通る。
  ソースの文字列一致では測らない= 実際に to_tags() を走らせて戻り値で測る。

    python scripts/imagegen/test_local_chain_totags.py
    python scripts/imagegen/test_local_chain_totags.py --mustfail   # 直す前の版で赤を確認
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import local_chain as lc            # noqa: E402

# 2026-09-16 実測。gemma-4-12b-it が同じ注文文に対して実際に書いた思考の末尾。
# ★作り物ではない= `Final Tag List:` の直後に**完成した1行**が既に在る、という形が要点。
REAL_REASONING = """    Wait, looking at Illustrious/SDXL style:
    `1girl, mature female, long hair, waist-length hair, half updo, black hair, red hair, sailor suit, school uniform, masterpiece, best quality, highres`

    *Refining for "Onee-san":* `mature female` is the standard tag.

    6. black hair, red hair (I'll include both as requested)

    Final Tag List:
    1girl, mature female, long hair, waist-length hair, half updo, black hair, red hair, sailor suit, school uniform, masterpiece, best quality, highres

    *Wait*, let's look at "Red" again. Maybe they meant "reddish"? I'll just put both.
"""

EXPECT = ("1girl, mature female, long hair, waist-length hair, half updo, "
          "black hair, red hair, sailor suit, school uniform, "
          "masterpiece, best quality, highres")

ORDER = "黒髪ロング ハーフアップ 腰まである髪 赤い髪 お姉さん セーラー服"


class Mouth(object):
    """LM Studioの口だけ差し替える。返す中身は1回ごとに指定する。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.budgets = []          # 実際に投げた max_tokens(引き直しをここで測る)
        self._orig = None

    def __enter__(self):
        self._orig = lc._post
        lc._post = self._post
        return self

    def __exit__(self, *a):
        lc._post = self._orig
        return False

    def _post(self, url, payload, timeout=900):
        self.budgets.append(payload["max_tokens"])
        content, reasoning, rtok = self.replies[min(len(self.budgets) - 1,
                                                    len(self.replies) - 1)]
        return {"choices": [{"message": {"content": content,
                                         "reasoning_content": reasoning}}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": rtok}}}


def reply(content="", reasoning="", rtok=0):
    return (content, reasoning, rtok)


class TestTheNormalCase(unittest.TestCase):
    """普通に content が返る時は、今までどおり1文字も変わらない。"""

    def test_content_comes_back_as_is(self):
        with Mouth([reply(content=EXPECT, rtok=1027)]):
            self.assertEqual(lc.to_tags(ORDER), EXPECT)

    def test_quotes_and_newlines_are_stripped(self):
        with Mouth([reply(content='"1girl, long hair,\nblack hair, highres"')]):
            self.assertEqual(lc.to_tags(ORDER), "1girl, long hair, black hair, highres")

    def test_it_does_not_ask_twice_when_the_first_answer_is_good(self):
        m = Mouth([reply(content=EXPECT)])
        with m:
            lc.to_tags(ORDER)
        self.assertEqual(len(m.budgets), 1)


class TestTheAnswerIsSalvagedFromTheThinking(unittest.TestCase):
    """★本命= content が空でも、思考の中に既に書かれている最終案を拾う。

    これが無い版では、同じ入力がそのまま RuntimeError になる(= 絵が出ない)。
    """

    def test_an_empty_content_still_yields_the_tags(self):
        with Mouth([reply(content="", reasoning=REAL_REASONING, rtok=1497)]):
            self.assertEqual(lc.to_tags(ORDER), EXPECT)

    def test_it_does_not_ask_twice_when_the_thinking_had_the_answer(self):
        m = Mouth([reply(content="", reasoning=REAL_REASONING, rtok=1497)])
        with m:
            lc.to_tags(ORDER)
        self.assertEqual(len(m.budgets), 1)

    def test_without_a_heading_it_takes_the_last_tag_line(self):
        # 見出しが無ければ末尾から= 推敲後の新しい方を採る。
        r = "first, second, third, fourth\nthinking out loud\nalpha, beta, gamma, delta"
        with Mouth([reply(content="", reasoning=r)]):
            self.assertEqual(lc.to_tags(ORDER), "alpha, beta, gamma, delta")


class TestItDoesNotInventTags(unittest.TestCase):
    """拾えない物を拾ったことにしない(でっち上げ防止)。"""

    def test_japanese_lines_are_not_tags(self):
        self.assertEqual(lc.salvage_tags("ええと、黒髪、ロング、セーラー服、どうしよう"), "")

    def test_too_few_commas_is_not_a_tag_line(self):
        self.assertEqual(lc.salvage_tags("long hair, black hair"), "")

    def test_a_line_without_words_is_not_a_tag_line(self):
        self.assertEqual(lc.salvage_tags("1, 2, 3, 4, 5"), "")

    def test_no_thinking_at_all_salvages_nothing(self):
        self.assertEqual(lc.salvage_tags(""), "")
        self.assertEqual(lc.salvage_tags(None), "")


class TestItDrawsAgainBeforeGivingUp(unittest.TestCase):
    """拾えなかった時は、諦める前に予算を倍にして1回だけ引き直す。"""

    def test_the_second_ask_has_double_the_budget(self):
        m = Mouth([reply(content="", reasoning="もう一声"),
                   reply(content=EXPECT)])
        with m:
            self.assertEqual(lc.to_tags(ORDER, max_tokens=4000), EXPECT)
        self.assertEqual(m.budgets, [4000, 8000])

    def test_it_stops_at_two(self):
        m = Mouth([reply(content="", reasoning="だめ")])
        with m:
            self.assertRaises(RuntimeError, lc.to_tags, ORDER)
        self.assertEqual(len(m.budgets), 2)


class TestTheGivingUpIsSpokenNotSilent(unittest.TestCase):
    """最後まで外れた時に、空文字を黙って返さない。"""

    def test_it_raises_instead_of_returning_empty(self):
        with Mouth([reply(content="", reasoning="だめ", rtok=3999)]):
            self.assertRaises(RuntimeError, lc.to_tags, ORDER)

    def test_the_message_carries_the_numbers_that_explain_it(self):
        with Mouth([reply(content="", reasoning="だめ", rtok=3999)]):
            try:
                lc.to_tags(ORDER, max_tokens=4000)
                self.fail("空なのに例外が出ていない")
            except RuntimeError as e:
                msg = str(e)
        self.assertIn("3999", msg)          # 思考がどれだけ食ったか
        self.assertIn("4000", msg)          # 予算はいくらだったか
        self.assertIn("8000", msg)          # 引き直した予算も残す
        self.assertIn(lc.CHAT_MODEL, msg)   # どのモデルの話か


class TestTheDefaultBudgetClearsWhatWasMeasured(unittest.TestCase):
    """既定値そのものが直っているか= 実測の思考量を超えているか。"""

    def test_the_default_is_above_the_measured_worst_case(self):
        import inspect
        d = inspect.signature(lc.to_tags).parameters["max_tokens"].default
        # 2026-09-16 実測の最大 reasoning_tokens = 1890。旧既定1500はこれを下回っていた。
        self.assertGreater(d, 1890 * 2, "実測の最悪値(1890)に余裕が無い既定値だ")


def mustfail():
    """直す前の版(.bak)を読み込んで、**判定で**赤くなることを確かめる。

    ★import で落ちる赤は検査ではない= ここでは古い to_tags を実際に呼び、
      「同じ入力が RuntimeError になる(= 絵が出ない)」ことを現物で見る。
    """
    import importlib.util
    from importlib.machinery import SourceFileLoader
    bak = os.path.join(_HERE, "local_chain.py.bak_20260916_totags")
    if not os.path.exists(bak):
        print("控えが無い: " + bak)
        return 1
    # ★拡張子が .bak_… なので loader を明に渡す(既定では None が返る)。
    spec = importlib.util.spec_from_file_location(
        "local_chain_old", bak, loader=SourceFileLoader("local_chain_old", bak))
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    calls = []

    def fake_post(url, payload, timeout=900):
        calls.append(payload["max_tokens"])
        return {"choices": [{"message": {"content": "",
                                         "reasoning_content": REAL_REASONING}}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 1497}}}

    old._post = fake_post
    print("直す前の版に、実測どおりの返事(content空 + 思考に最終案あり)を渡す…")
    try:
        got = old.to_tags(ORDER)
        print("  ✗ 落ちなかった: " + repr(got))
        return 1
    except RuntimeError as e:
        print("  ✓ 判定FAIL(期待どおりの赤): RuntimeError " + str(e)[:80])
    print("  投げた max_tokens = %s (引き直しをしていない)" % calls)
    print("直した版に同じ返事を渡す…")
    with Mouth([reply(content="", reasoning=REAL_REASONING, rtok=1497)]):
        got = lc.to_tags(ORDER)
    print("  ✓ 拾えた: " + got)
    return 0 if got == EXPECT else 1


if __name__ == "__main__":
    if "--mustfail" in sys.argv:
        sys.exit(mustfail())
    unittest.main(verbosity=2)
