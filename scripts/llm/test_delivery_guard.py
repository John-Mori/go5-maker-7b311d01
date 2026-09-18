#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discord本文の冒頭名乗りを、実際の出口経路で落とす回帰検査。

引き金(2026-09-18・Chami):
  「最初の［一ノ瀬］などの名乗りがなかなか消えない」

実物の形は、正式名 ``一ノ瀬怜`` ではなく短縮した ``［一ノ瀬］``。
正式名完全一致だけの網では拾えないため、短縮形・全角括弧・装飾を同じ検体に固定する。
外へ出るHTTPだけを偽物にし、Codex専用Botは ``dc_send`` まで本物の経路を通す。
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, os.path.join(ROOT, "scripts", "discord"),
                os.path.join(ROOT, "scripts", "codex")]

try:
    import delivery_guard as dg
except Exception:
    dg = None
import persona_send as ps
import codex_run as cr

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name, extra)


def guarded(text, persona, aliases=()):
    if dg is None:
        return text, {"intro": []}
    return dg.apply(text, persona, aliases)


MUTATE = "--mutate" in sys.argv
if MUTATE and dg is not None:
    # C-053: 実装を壊さず、動く別実装へ差し替えて同じ出口経路を赤にする。
    dg.apply = lambda text, persona, aliases=(): (
        str(text or ""), {"intro": [], "preamble": {"stripped": False},
                           "paragraphs": {"stripped": 0}, "blocked": None})
    dg.strip_opening_self_intro = lambda text, persona, aliases=(): (
        str(text or ""), {"stripped": False, "kind": "", "removed": ""})


print("== 純関数: 正式名と短縮名 ==")
cases = (
    ("全角短縮", "［一ノ瀬］\n原因を特定した。", "原因を特定した。"),
    ("半角正式名", "[一ノ瀬怜]\n原因を特定した。", "原因を特定した。"),
    ("隅付き短縮", "【一ノ瀬】 原因を特定した。", "原因を特定した。"),
    ("装飾短縮", "**［一ノ瀬］** 原因を特定した。", "原因を特定した。"),
    ("裸の短縮", "一ノ瀬。原因を特定した。", "原因を特定した。"),
)
for label, src, want in cases:
    out, info = guarded(src, "一ノ瀬怜")
    check(label, out == want and bool(info.get("intro")), repr((out, info)))

out, _ = guarded("本文中の［一ノ瀬］は引用だ。", "一ノ瀬怜")
check("本文中の名前は不変", out == "本文中の［一ノ瀬］は引用だ。", repr(out))
out, _ = guarded("> ［一ノ瀬］\n引用だ。", "一ノ瀬怜")
check("引用行の名前は不変", out == "> ［一ノ瀬］\n引用だ。", repr(out))
out, _ = guarded("［アメス］\n別人格の引用だ。", "一ノ瀬怜")
check("別人格のタグは不変", out == "［アメス］\n別人格の引用だ。", repr(out))

print("== persona_send最終合流点 ==")
try:
    out = ps.apply_text_gates("［一ノ瀬］\n原因を特定した。", persona="一ノ瀬怜",
                              dept="platform-se", audit=False)
except Exception as exc:
    out = "EXC:" + type(exc).__name__
check("直送/無人代打でも短縮名が残らない", out == "原因を特定した。", repr(out))

print("== Codex専用Botの実出口 ==")
check("Codexの短い別名も落ちる",
      "".join(cr.prepare_discord_chunks("ボス。\n原因を特定した。")) == "原因を特定した。")

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
finally:
    sys.stdout = old_stdout
    cr.urllib.request.urlopen = real
check("HTTP直前の実値にCodex名乗りが無い", sent == ["原因を特定した。"], sent)

print("\n%d PASS / %d FAIL" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
