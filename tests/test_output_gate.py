# -*- coding: utf-8 -*-
"""GOLDEN: 出力ゲート ルールA(非日本語スクリプト混入=ハングル)  2026-07-30

正本= 00_AI-HQ/設計_出力ゲート_呼称スラッグ非日本語スクリプト_2026-07-30.md §2/§4/§5。
裁定= Chami(2026-07-30「推奨どおりでいい」)。

★これは**ルールAのみ**のテスト。B(スラッグ露出)・C(呼称違反)は未実装(設計書§5)。
検査対象は純関数 detect_hangul / hangul_gate(送信・Discord・queueには一切触れない)。

実行: python tests/test_output_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "llm"))
import dept_daemon as d  # noqa: E402


_fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        _fails.append(name)


# --- detect_hangul(設計書§4のA最小ケース) ---------------------------------
# 発火: オタコンの実例『左右각약9%』(각약=U+AC01/U+C57D、正は『各約』)
check("detect: 左右각약9% は発火", d.detect_hangul("左右각약9%") is not None)
# 通過: 正しい日本語『各約9%』はハングルを含まない
check("detect: 各約9% は None", d.detect_hangul("各約9%") is None)
# 発火(=仕様): 正当な引用『ORG-45: 판と判』でも鳴る=誤検出ではない(§4)
check("detect: ORG-45: 판と判 は発火(仕様)", d.detect_hangul("ORG-45: 판と判") is not None)
# 補助: 純日本語・空文字・None で落ちない/鳴らない
check("detect: 通常の日本語は None", d.detect_hangul("各約9%を薄く覆う") is None)
check("detect: 空文字は None", d.detect_hangul("") is None)
check("detect: None は None", d.detect_hangul(None) is None)


# --- hangul_gate(再生成ループの3ケース・§2) ------------------------------
# strip_marker は本番と同じ split_wip_marker を渡す((本文, bool)を返す)。
STRIP = d.split_wip_marker

# 1) 1回目にハングルが無い通常返信 → 何もしない(本文不変・警告なし)
out, info = d.hangul_gate("各約9%を薄く覆う", regen=lambda: "使われない", strip_marker=STRIP)
check("gate: 通常返信は本文不変", out == "各約9%を薄く覆う")
check("gate: 通常返信は hit1=False", info["hit1"] is False and info["warned"] is False)

# 2) 1回目ハングル → 再生成で消える → きれいな本文へ差し替え(警告なし)
calls = {"n": 0}
def regen_clean():
    calls["n"] += 1
    return "各約9%(再生成でクリーン)"
out, info = d.hangul_gate("左右각약9%", regen=regen_clean, strip_marker=STRIP)
check("gate: 1回で消えたら差し替え", out == "各約9%(再生成でクリーン)")
check("gate: 1回で消えたら警告なし", info["warned"] is False and info["hit2"] is False)
check("gate: 1回で消えたら hit1/regenerated=True", info["hit1"] and info["regenerated"])
check("gate: 再生成は1回だけ呼ぶ", calls["n"] == 1)

# 3) 1回目ハングル → 再生成後も混入 → 元文に警告付き(沈黙にしない)
out, info = d.hangul_gate("左右각약9%", regen=lambda: "まだ각약が残る", strip_marker=STRIP)
check("gate: 2回目も混入なら元文を保持", out.startswith("左右각약9%"))
check("gate: 2回目も混入なら警告付与", d.HANGUL_WARN in out and info["warned"] and info["hit2"])

# 4) regen=None(session_relay/失敗告知/test経路) → 再生成せず警告付き(fail-open)
out, info = d.hangul_gate("左右각약9%", regen=None, strip_marker=STRIP)
check("gate: regen=None は再生成せず警告付き",
      d.HANGUL_WARN in out and info["warned"] and info["regenerated"] is False)

# 5) fail-open: 再生成が例外を投げても落ちず、元文に警告付きで返す
def regen_boom():
    raise RuntimeError("regen failed")
out, info = d.hangul_gate("左右각약9%", regen=regen_boom, strip_marker=STRIP)
check("gate: 再生成例外は握り潰し警告付き", d.HANGUL_WARN in out and info["warned"])

# 6) fail-open: 再生成が空を返したら元文に警告付き(沈黙にしない)
out, info = d.hangul_gate("左右각약9%", regen=lambda: "", strip_marker=STRIP)
check("gate: 再生成が空なら警告付き", d.HANGUL_WARN in out and info["warned"])

# 7) 再生成本文に <<WIP>> が付いていても strip_marker で剥がして判定する
out, info = d.hangul_gate("左右각약9%", regen=lambda: "各約9%<<WIP>>", strip_marker=STRIP)
check("gate: 再生成の<<WIP>>を剥がして判定", out == "各約9%" and info["warned"] is False)

# 8) 警告行は二重に付けない(冪等)
warned_once = d._append_hangul_warn("本文")
check("gate: 警告は二重付与しない", d._append_hangul_warn(warned_once) == warned_once)


print("-" * 40)
if _fails:
    print("FAILED:", len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ALL PASS")
