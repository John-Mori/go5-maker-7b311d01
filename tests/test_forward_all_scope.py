# -*- coding: utf-8 -*-
"""forward_all が部門間便を二重回送しないことの回帰テスト。"""
import os
import sys


ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import dept_daemon as D  # noqa: E402


def check(got, want, label):
    if got != want:
        raise AssertionError(f"{label}: got={got!r} want={want!r}")


# forward_all の本来の安全網= Chami便は、作業キーワードを拾えなくても残す。
check(D.forward_after_reply({"author": "chami_fusoh"}, False, True), True,
      "Chami便はforward_allで回送")
check(D.forward_after_reply({"author": "Chami"}, False, True), True,
      "Chami判定は大小文字に依存しない")

# 今回の本丸= AIが返答済みの便を、forward_allだけで再投入しない。
check(D.forward_after_reply({"author": "ルカ・モドリッチ", "audience": "ai"}, False, True),
      False, "AI間便はforward_allだけで二重回送しない")
check(D.forward_after_reply({"author": "完遂通知(自動)", "audience": "ai"}, False, True),
      False, "完遂通知をforward_allで再投入しない")

# 必要な上申は残す= 返答が範囲外作業を明示した時は、AI便でも上げる。
check(D.forward_after_reply({"author": "ルカ・モドリッチ", "audience": "ai"}, True, True),
      True, "<<WORK>>の上申は従来どおり残す")
check(D.forward_after_reply({}, True, False), True,
      "送り主不明でも明示的な範囲外作業は落とさない")

check(D.forward_after_reply({"author": "chami_fusoh"}, False, False), False,
      "forward_allでない部屋は新たに回送しない")
check(D.forward_after_reply(None, False, True), False,
      "不正レコードで例外を出さない")

print("PASS forward_allの範囲(Chami便は残す/AI間の二重回送は止める/<<WORK>>は残す)")
