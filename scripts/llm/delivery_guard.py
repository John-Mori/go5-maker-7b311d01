#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discordへ出す人格本文の最終安全網。

表示名はDiscord側が付けるため、本文冒頭の自己名は二重表示になる。
正式名だけでなく、モデルが短縮した姓/名や全角括弧も、実際の話者名との対応が
一意な時だけ落とす。本文中の言及・引用・別人格のタグは触らない。

英語の判定は既存の ``lang_gate`` を正本として使う。ここに閾値は写さない。
"""
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    import lang_gate as _lang_gate
except Exception:
    _lang_gate = None


_TAG_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<deco>`{1,2}|\*{1,2}|_{1,2})?\s*"
    r"(?P<open>[\[［【])\s*(?P<label>[^\]］】\n]{1,24}?)\s*(?P<close>[\]］】])"
    r"\s*(?(deco)(?P=deco))\s*"
    r"(?:(?:[:：\-—])\s*)?(?P<rest>.*)$")
_BROKEN_TAG_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<deco>`{1,2}|\*{1,2}|_{1,2})?\s*"
    r"(?P<label>[^\]］】\n]{1,24}?)\s*(?P<close>[\]］】])"
    r"\s*(?(deco)(?P=deco))\s*"
    r"(?:(?:[:：\-—])\s*)?(?P<rest>.*)$")
_BARE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<deco>`{1,2}|\*{1,2}|_{1,2})?\s*"
    r"(?P<label>[^。.!！:：\n]{1,24}?)\s*(?:です|だ)?\s*"
    r"(?(deco)(?P=deco))\s*(?:[。.!！:：]\s*|$)(?P<rest>.*)$")
_HONORIFICS = ("さん", "様", "さま", "ちゃん", "くん", "君")


def _norm(value):
    try:
        return unicodedata.normalize("NFKC", str(value or "")).strip()
    except Exception:
        return str(value or "").strip()


def _names(persona, aliases=()):
    out = []
    for raw in (persona,) + tuple(aliases or ()):
        name = _norm(raw)
        if name and name not in out:
            out.append(name)
    return out


def _without_honorific(label):
    value = _norm(label)
    for suffix in _HONORIFICS:
        if len(value) > len(suffix) and value.endswith(suffix):
            return value[:-len(suffix)].strip()
    return value


def _is_self_label(label, names):
    """冒頭ラベルが話者自身かを見る。

    完全一致に加え、2文字以上の前方/後方短縮だけを認める。
    ``一ノ瀬怜``→``一ノ瀬``、``シャビ・アロンソ``→``アロンソ``の形だ。
    中間部分一致は認めず、1文字短縮も認めない。短い一般見出しを消さないためだ。
    明示されたaliasesは短くても完全一致なら受ける。
    """
    raw = _norm(label)
    base = _without_honorific(raw)
    if not base:
        return False
    for name in names:
        if base == name:
            return True
    if len(base) < 2:
        return False
    formal = names[0] if names else ""
    return bool(formal and (formal.startswith(base) or formal.endswith(base)))


def _opening_match(line, names):
    for kind, pattern in (("bracket", _TAG_RE),
                          ("broken_bracket", _BROKEN_TAG_RE),
                          ("bare", _BARE_RE)):
        hit = pattern.match(str(line or ""))
        if hit and _is_self_label(hit.group("label"), names):
            return kind, hit
    return "", None


def strip_opening_self_intro(text, persona, aliases=()):
    """冒頭の自己名だけを落とす。戻り値は ``(本文, info)``。"""
    info = {"stripped": False, "kind": "", "removed": "", "label": ""}
    source = str(text or "")
    names = _names(persona, aliases)
    if not source or not names:
        return source, info

    lines = source.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return source, info
    line = lines[first]
    # 引用・コード内は説明材料であり、話者の自己紹介とは限らない。
    if line.lstrip().startswith((">", "```")):
        return source, info

    kind, hit = _opening_match(line, names)
    if hit is None:
        return source, info
    rest = (hit.groupdict().get("rest") or "").strip()
    rebuilt = lines[:first]
    if rest:
        rebuilt.append(rest)
    rebuilt.extend(lines[first + 1:])
    while rebuilt and not rebuilt[0].strip():
        rebuilt.pop(0)
    out = "\n".join(rebuilt).strip()
    if not out:
        return source, info                  # 名札しか無い便を空投稿へ変えない(fail-open)
    info.update({
        "stripped": True,
        "kind": kind,
        "removed": line.strip()[:160],
        "label": hit.group("label").strip(),
    })
    return out, info


def apply(text, persona, aliases=()):
    """自己紹介と不要な英語を除く。英語ダンプなら本文は ``None``。"""
    body = str(text or "")
    info = {
        "intro": [],
        "preamble": {"stripped": False, "removed_latin": 0},
        "paragraphs": {"stripped": 0, "removed_latin": 0},
        "blocked": None,
    }

    # 英語作業メモ→自己名→短い日本語、の形。自己名が境界になる時だけ前を落とす。
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
                        "stripped": True,
                        "removed_latin": hit.get("latin", 0),
                        "by": hit.get("by", ""),
                        "via": "self_intro_boundary",
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
        return body, info                       # 判定不能なら喋る側へ倒す(fail-open)
