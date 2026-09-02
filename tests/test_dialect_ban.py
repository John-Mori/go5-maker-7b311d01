# -*- coding: utf-8 -*-
"""GOLDEN: 出力ゲートA'(関西弁の一律禁止)  2026-09-03

裁定= **Chami直接指示**(§3.7=どの裁定より上)。2便で1つの指示:
  1)「てか関西弁使うキャラっていないから一律禁止にしといてもろて」(msg 1544754070487568555)
  2)「ただし、俺の発言の引用として使うのはOKだからね」(msg 1544754298372624434)
発注= 改善提案部門トトリ経由・研究室HQ(msg 1544754417796911204 / 1544754298372624434)。

壊れている実物= 軍議 msg 1544752273253728276。下の KANSAI_REAL は**その便の本文**を
local/llm/tone_audit.jsonl の excerpt から引いた実物(自作の偽物では測らない)。

検査対象は純関数 dialect_gate / dialect_detector / tone_gate.dialect_hits
(送信・Discord・queueには一切触れない)。

実行: PYTHONIOENCODING=utf-8 python tests/test_dialect_ban.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "llm"))
import dept_daemon as d          # noqa: E402
import tone_gate as TG           # noqa: E402


_fails = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        _fails.append(name)


STRIP = d.split_wip_marker
RULES = d._tone_rules()
DET = d.dialect_detector("gunji", ["三笘薫"])

# --- 実物のフィクスチャ ------------------------------------------------------
# ★軍議 msg 1544752273253728276 の本文(tone_audit.jsonl の excerpt そのまま)。
#   地の文に「ほんまや」「なんよ」「や(断定)」が在り、**同じ文中に「表には流しません」の
#   引用符も在る**= must-fail③(引用符が在っても地の文の方言は止まる)がそのまま測れる。
KANSAI_REAL = (
    "ははっ、ほんまや。ジェンティルドンナが「表には流しません」って表にデカデカ書いてたら"
    "世話ないわな。\n\n種を明かすと、あの横断共有はAI便で流してて、仕様上"
    "「要点だけは表に出る＋残りは裏の便」なんよ。"
)
# ★Chami本人の関西弁ツッコミ(msg 1544752273253728276 の発端)を**引用しただけ**の便。
CHAMI_QUOTE = "Chamiの「流しとるやないかい」はもっともだ。仕様を確認して直す。"
# ★同じ言い回しを**地の文で**言った便(引用の保全が「方言の隠れ蓑」になっていないか測る対)。
CHAMI_BARE = "流しとるやないかい、と俺も思う。"
# ★標準語の正常便(巻き込み事故を測る側)。
PLAIN = "この構成、表に出す分と裏に置く分の線引きを整理しておいてください。"


# ============================================================================
# 0) 前提= 判定の正本(tone_gate.dialect_hits)が引けている
# ============================================================================
check("前提: 口調ルール.json が読める", bool(RULES))
check("前提: 部屋の判定 thunk が作れる", DET is not None)


# ============================================================================
# 1) 判定(dialect_hits)= 地の文だけ数える
# ============================================================================
check("判定: 実物の軍議便は当たる", bool(DET(KANSAI_REAL)))
check("判定: 標準語の正常便は当たらない", DET(PLAIN) == [])
check("判定: 地の文の『やないかい』は当たる", bool(DET(CHAMI_BARE)))
check("判定: 同じ形もChamiの引用の中なら当たらない", DET(CHAMI_QUOTE) == [])
check("判定: 空文字で落ちない", DET("") == [])
check("判定: 未登録の人格でも一律に当たる(登録の有無を穴にしない)",
      bool([h.get("marker") for h in (TG.dialect_hits(KANSAI_REAL, RULES) or [])]))


# ============================================================================
# 2) must-fail ①= 関西弁が**残ったまま送信されたら赤**
#    再生成しても方言が消えない最悪ケースで、素の本文がそのまま出て行かないこと。
# ============================================================================
calls = {"n": 0}


def regen_still_kansai():
    calls["n"] += 1
    return "せやな、ほんまにその通りや。"


out, info = d.dialect_gate(KANSAI_REAL, regen=regen_still_kansai,
                           strip_marker=STRIP, detect=DET)
check("must-fail①: 検知している", info["hit1"] is True)
check("must-fail①: 再生成を1回だけ試す", calls["n"] == 1 and info["regenerated"] is True)
check("must-fail①: 2回目も方言なら警告が付く(素通ししない)",
      info["hit2"] is True and info["warned"] is True and d.DIALECT_WARN in out)
check("must-fail①: 沈黙にはしない(本文は残す)", KANSAI_REAL[:12] in out)

# 再生成で消えた場合= きれいな本文へ差し替わり、警告は付かない
calls2 = {"n": 0}


def regen_clean():
    calls2["n"] += 1
    return "そのとおりだ。仕様上、要点だけが表に出る形になっている。"


out2, info2 = d.dialect_gate(KANSAI_REAL, regen=regen_clean,
                             strip_marker=STRIP, detect=DET)
check("must-fail①: 再生成で消えたら差し替え",
      out2 == "そのとおりだ。仕様上、要点だけが表に出る形になっている。")
check("must-fail①: 再生成で消えたら警告なし",
      info2["warned"] is False and info2["hit2"] is False)
check("must-fail①: 再生成は1回だけ", calls2["n"] == 1)
check("must-fail①: 方言の載った版は出さない", not DET(out2))


# ============================================================================
# 3) must-fail ②= 標準語の正常便を**再生成に巻き込んだら赤**
# ============================================================================
calls3 = {"n": 0}


def regen_never():
    calls3["n"] += 1
    return "呼ばれてはいけない"


out3, info3 = d.dialect_gate(PLAIN, regen=regen_never, strip_marker=STRIP, detect=DET)
check("must-fail②: 正常便は本文不変", out3 == PLAIN)
check("must-fail②: 正常便で再生成を呼ばない", calls3["n"] == 0)
check("must-fail②: 正常便は hit1/warned とも False",
      info3["hit1"] is False and info3["warned"] is False)
check("must-fail②: 正常便に警告を足さない", d.DIALECT_WARN not in out3)


# ============================================================================
# 4) must-fail ③= 引用符が文中に在っても、**地の文の方言は必ず止める**
#    (「引用が1つでも在れば素通し」では駄目、というトトリの指定そのもの)
# ============================================================================
check("must-fail③: 引用符を含む実物でも検知する(素通ししない)",
      bool(DET(KANSAI_REAL)) and "「表には流しません」" in KANSAI_REAL)
out4, info4 = d.dialect_gate(KANSAI_REAL, regen=None, strip_marker=STRIP, detect=DET)
check("must-fail③: 再生成の手が無い経路でも警告は付く(=届く前に印が付く)",
      info4["hit1"] is True and info4["warned"] is True and d.DIALECT_WARN in out4)


# ============================================================================
# 5) must-fail ④= Chamiの関西弁を**引用しただけ**の便を巻き込まない
# ============================================================================
calls5 = {"n": 0}


def regen_never5():
    calls5["n"] += 1
    return "呼ばれてはいけない"


out5, info5 = d.dialect_gate(CHAMI_QUOTE, regen=regen_never5,
                             strip_marker=STRIP, detect=DET)
check("must-fail④: 引用の便は本文不変", out5 == CHAMI_QUOTE)
check("must-fail④: 引用の便で再生成を呼ばない", calls5["n"] == 0)
check("must-fail④: 引用の便に警告を足さない", d.DIALECT_WARN not in out5)
# ★対= 同じ言い回しでも地の文なら止まる(引用の保全が抜け道になっていない)
out5b, info5b = d.dialect_gate(CHAMI_BARE, regen=None, strip_marker=STRIP, detect=DET)
check("must-fail④の対: 地の文の同形は止まる", info5b["hit1"] is True)


# ============================================================================
# 6) fail-open= ゲートが配送を殺さない
# ============================================================================
out6, info6 = d.dialect_gate(KANSAI_REAL, regen=None, strip_marker=STRIP, detect=None)
check("fail-open: detect が無ければ素通し(黙って止めない)",
      out6 == KANSAI_REAL and info6["hit1"] is False)


def regen_boom():
    raise RuntimeError("再生成が壊れた")


out7, info7 = d.dialect_gate(KANSAI_REAL, regen=regen_boom, strip_marker=STRIP, detect=DET)
check("fail-open: 再生成が例外でも本文は返る(警告付き)",
      d.DIALECT_WARN in out7 and KANSAI_REAL[:12] in out7)


def det_boom(_s):
    raise RuntimeError("判定が壊れた")


out8, _ = d.dialect_gate(KANSAI_REAL, regen=None, strip_marker=STRIP, detect=det_boom)
check("fail-open: 判定が例外でも元文が返る", out8 == KANSAI_REAL)
check("fail-open: 空文字で落ちない", d.dialect_gate("", detect=DET)[0] == "")


# ============================================================================
# 7) 逃げ道は写像側に1つだけ= 部屋の人格が**全員** dialect_ok なら掛けない
#    ★コードに人格名は書かない(ORG-11)。今この条件に当たる人格は0。
# ============================================================================
_saved = dict(d._TONE_RULES_CACHE)
try:
    fake = {"personas": {"方言の人": {"dialect_ok": True}}}
    d._TONE_RULES_CACHE.update({"loaded": True,
                                "mtime": d._TONE_RULES_CACHE.get("mtime"),
                                "rules": fake})
    check("例外: 全員 dialect_ok の部屋はゲートを掛けない",
          d.dialect_detector("x", ["方言の人"]) is None)
    check("例外: 1人でも標準語なら掛ける",
          d.dialect_detector("x", ["方言の人", "三笘薫"]) is not None)
finally:
    d._TONE_RULES_CACHE.clear()
    d._TONE_RULES_CACHE.update(_saved)
check("例外: 実データでは0人格=全部屋に掛かる",
      d.dialect_detector("gunji", ["三笘薫"]) is not None)


# ============================================================================
# 8) C-053= 「壊した側」を**動く別の実装**へ戻すと、上の must-fail が実際に落ちる
#    空実装ではなく、**今日までの本番の挙動**(=ゲートD: 検知して台帳に書くが本文は触らない)
#    を書き下ろして当てる。これが赤くならないなら、上の検査は何も守っていない。
# ============================================================================
def _detect_only(text, detect=None):
    """2026-09-02までの実際の挙動= 検知して記録するだけ。本文はそのまま送る。"""
    hits = (detect(text) if detect else []) or []
    return text, {"hit1": bool(hits), "markers": list(hits),
                  "regenerated": False, "hit2": False, "warned": False}


old_out, old_info = _detect_only(KANSAI_REAL, detect=DET)
check("C-053: 旧挙動は検知だけはできていた(穴は検知ではない)", old_info["hit1"] is True)
check("C-053: 旧挙動なら関西弁が**そのまま**Chamiへ届く=must-fail①が赤になる",
      bool(DET(old_out)) and d.DIALECT_WARN not in old_out)
check("C-053: 旧挙動は正常便を巻き込まない(=②だけでは差が出ない)",
      _detect_only(PLAIN, detect=DET)[0] == PLAIN)


print()
print("FAILS:", len(_fails))
for n in _fails:
    print(" -", n)
sys.exit(1 if _fails else 0)
