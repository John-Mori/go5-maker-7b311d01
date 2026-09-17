#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discordへ出す人格本文の最終安全網。

判定の正本は既存の ``lang_gate`` に置いたまま、ここでは次の2点だけを束ねる。

* 表示名が別に付く人格便の、冒頭の自己紹介を落とす。
* 英語前置き/英語段落を既存関数で剥ぎ、英語ダンプは保留する。

純関数だけを置く。監査と送信可否の記録は各OUT口が持つ。
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import lang_gate as _lang_gate
except Exception:
    _lang_gate = None


def _names(persona, aliases=()):
    out = []
    for raw in (persona,) + tuple(aliases or ()):
        name = str(raw or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def strip_opening_self_intro(text, persona, aliases=()):
    """冒頭の自己名だけを落とす。戻り値は ``(本文, info)``。

    対象は、その便の話者名と完全一致する次の形だけだ。
    ``[名前]`` / ``**[名前]**`` / ``名前。`` / ``名前です。``。
    本文中の名前、引用、別人格のタグは触らない。
    """
    info = {"stripped": False, "kind": "", "removed": ""}
    s = str(text or "")
    names = _names(persona, aliases)
    if not s or not names:
        return s, info

    lines = s.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return s, info
    line = lines[first]
    # 引用・コードの中にある名前は説明材料であって自己紹介とは限らない。
    if line.lstrip().startswith((">", "```")):
        return s, info

    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    deco = r"(?:\*\*|__|`)?"
    lead = r"^\s*(?:#{1,6}\s*)?"
    patterns = (
        ("bracket", re.compile(
            lead + deco + r"[\[［]\s*(?:" + alt + r")\s*[\]］]" + deco
            + r"\s*(?:(?:[:：\-—])\s*)?(?P<rest>.*)$")),
        # モデルが開き括弧だけ落とした ``アメス] body`` も、話者が一致する時だけ救う。
        ("broken_bracket", re.compile(
            lead + deco + r"(?:" + alt + r")\s*[\]］]" + deco
            + r"\s*(?:(?:[:：\-—])\s*)?(?P<rest>.*)$")),
        ("bare", re.compile(
            lead + deco + r"(?:" + alt + r")" + deco
            + r"\s*(?:(?:です|だ)\s*)?(?:[。.!！:：]\s*|$)(?P<rest>.*)$")),
    )
    hit = None
    kind = ""
    for kind, pat in patterns:
        hit = pat.match(line)
        if hit:
            break
    if not hit:
        return s, info

    rest = (hit.groupdict().get("rest") or "").strip()
    rebuilt = lines[:first]
    if rest:
        rebuilt.append(rest)
    rebuilt.extend(lines[first + 1:])
    # 名札の直後にできる先頭空行だけを除く。本文内の段落構造は保つ。
    while rebuilt and not rebuilt[0].strip():
        rebuilt.pop(0)
    out = "\n".join(rebuilt).strip()
    info.update({"stripped": True, "kind": kind, "removed": line.strip()[:160]})
    return out, info


def apply(text, persona, aliases=()):
    """自己紹介と不要な英語を除く。英語ダンプなら本文は ``None``。

    英語の判定条件は ``lang_gate`` の既存関数だけを使う。ここに閾値の写しは持たない。
    """
    body = str(text or "")
    info = {
        "intro": [], "preamble": {"stripped": False, "removed_latin": 0},
        "paragraphs": {"stripped": 0, "removed_latin": 0}, "blocked": None,
    }

    # ``英語の作業メモ → [自己名] → 短い日本語本文`` は、既存の前置き剥ぎが
    # 「残る日本語20字以上」の安全弁で意図的に触らない。だが自己名が境界として一致する時は
    # 切る位置が一意だ。英語判定そのものは既存 detect_english_paragraph に任せる。
    if _lang_gate is not None:
        try:
            lines = body.splitlines()
            for i in range(1, min(len(lines), 7)):
                candidate = "\n".join(lines[i:])
                cand_out, cand_intro = strip_opening_self_intro(candidate, persona, aliases)
                if not cand_intro.get("stripped"):
                    continue
                prefix = "\n".join(lines[:i]).strip()
                hit = _lang_gate.detect_english_paragraph(prefix)
                if hit is not None:
                    body = cand_out
                    info["intro"].append(cand_intro)
                    info["preamble"] = {
                        "stripped": True, "removed_latin": hit.get("latin", 0),
                        "by": hit.get("by", ""), "via": "self_intro_boundary",
                    }
                    break
        except Exception:
            pass

    body, intro = strip_opening_self_intro(body, persona, aliases)
    if intro.get("stripped"):
        info["intro"].append(intro)

    if _lang_gate is None:
        return body, info
    try:
        body, pre = _lang_gate.strip_english_preamble(body)
        info["preamble"] = pre
        # 英語前置きを剥いだ後に現れた名札も落とす。
        body, intro = strip_opening_self_intro(body, persona, aliases)
        if intro.get("stripped"):
            info["intro"].append(intro)

        body, para = _lang_gate.strip_english_paragraphs(body)
        info["paragraphs"] = para
        body, intro = strip_opening_self_intro(body, persona, aliases)
        if intro.get("stripped"):
            info["intro"].append(intro)

        hit = _lang_gate.detect_english_dump(body)
        if hit is not None:
            info["blocked"] = hit
            return None, info
        return body, info
    except Exception:
        return body, info                         # fail-open: 判定不能で送信を殺さない
