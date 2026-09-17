#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒頭の自己名と不要な英語を、実際のDiscord出口で止める回帰検査。"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SANDBOX = tempfile.mkdtemp(prefix="delivery_guard_test_")
os.environ["GO5_LOCAL_DIR"] = SANDBOX
sys.path[:0] = [HERE, os.path.join(ROOT, "scripts", "discord"),
                os.path.join(ROOT, "scripts", "codex")]

import delivery_guard as dg  # noqa: E402
import persona_send as ps     # noqa: E402
import codex_run as cr        # noqa: E402

# C-053の変異口。判定を消した状態でこの同じ経路を走らせ、赤になることを先に確認する。
if os.environ.get("GO5_MUTATE_DELIVERY_GUARD") == "1":
    dg.apply = lambda text, persona, aliases=(): (
        str(text or ""), {"intro": [], "preamble": {"stripped": False},
                          "paragraphs": {"stripped": 0}, "blocked": None})
    dg.strip_opening_self_intro = lambda text, persona, aliases=(): (
        str(text or ""), {"stripped": False, "kind": "", "removed": ""})

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name, extra)


def codex_body(text):
    return "".join(cr.prepare_discord_chunks(text))


print("== 純関数 ==")
out, info = dg.apply("[一ノ瀬怜]\n原因を特定した。", "一ノ瀬怜")
check("実物型の角括弧名乗りを落とす", out == "原因を特定した。", repr(out))
check("名乗り除去を記録できる", len(info["intro"]) == 1, info)
out, _ = dg.apply("**[一ノ瀬怜]** 対応を終えた。", "一ノ瀬怜")
check("装飾名乗りの後ろの本文は残す", out == "対応を終えた。", repr(out))
out, _ = dg.apply("本文中の [一ノ瀬怜] は引用だ。", "一ノ瀬怜")
check("本文中の名前は触らない", out == "本文中の [一ノ瀬怜] は引用だ。", repr(out))
out, _ = dg.apply("> [一ノ瀬怜]\n引用だ。", "一ノ瀬怜")
check("引用の名札は触らない", out == "> [一ノ瀬怜]\n引用だ。", repr(out))

mixed = "Let me inspect the delivery path and verify the final output.\n\n[一ノ瀬怜]\n原因を特定した。再発を止める。"
out, _ = dg.apply(mixed, "一ノ瀬怜")
check("英語前置きと、その後に現れた名乗りを両方落とす",
      out == "原因を特定した。再発を止める。", repr(out))
whole = "I'll inspect the output path and report once the verification is complete."
out, info = dg.apply(whole, "一ノ瀬怜")
check("全文英語は保留", out is None and info["blocked"], info)
normal = "HTTP 200を確認した。入口は scripts/discord/persona_send.py だ。"
out, _ = dg.apply(normal, "一ノ瀬怜")
check("日本語と識別子の通常文は不変", out == normal, repr(out))

print("== persona_sendの最終合流点 ==")
out = ps.apply_text_gates("[一ノ瀬怜]\n原因を特定した。", persona="一ノ瀬怜",
                          dept="platform-se", audit=False)
check("直送経路でも名乗りが残らない", out == "原因を特定した。", repr(out))
check("直送経路でも全文英語を止める", ps.english_backstop(whole, "一ノ瀬怜", "x") is None)

print("== Codex専用Botの実出口 ==")
check("素の自己紹介を落とす",
      codex_body("ネイキッド・スネーク。\n原因を特定した。") == "原因を特定した。")
check("表示名での自己紹介も落とす",
      codex_body("Snake🐍Codex: 原因を特定した。") == "原因を特定した。")
check("Codex全文英語は1通も作らない", cr.prepare_discord_chunks(whole) == [])

# 外へ出る手だけ偽物にし、dc_sendを本物のまま通す。
sent = []


class FakeResp:
    def read(self):
        return json.dumps({"id": "999"}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


real = cr.urllib.request.urlopen
cr.urllib.request.urlopen = lambda req, timeout=None: (
    sent.append(json.loads(req.data.decode("utf-8"))["content"]) or FakeResp())
stdout, old_stdout = io.StringIO(), sys.stdout
sys.stdout = stdout
try:
    cr.dc_send("dummy", "1", "ネイキッド・スネーク。\n原因を特定した。")
    cr.dc_send("dummy", "1", whole)
finally:
    sys.stdout = old_stdout
    cr.urllib.request.urlopen = real
check("HTTP直前の実値に名乗りが無い", sent == ["原因を特定した。"], sent)

print("\n%d PASS / %d FAIL" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
