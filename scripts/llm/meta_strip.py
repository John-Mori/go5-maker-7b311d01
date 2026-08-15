#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""送信直前ゲートE= 本文の末尾に混じった**内部の手続きメタ**を剥ぐ純関数。

なぜ要るか(2026-08-15 Chami指示③ msg 1538151871464865813 / 人事部門経由で基盤へ):
  Chami原文=「**画像のように不要な文字列を出さないように対策。**」
  壊れた実物(コピー部門・早坂芽衣の便 / local/llm/recent_copy-director.jsonl の
  msg_id=DISPATCH-copy-director-1786794044539 の reply)= **本文がこれ1行だけ**だった:

    No response requested — this is a backchannel HQ→部門 answer to my own §3.9 上申,
    with no Chami手番 and nothing left on my side (...)。§4.7に従い部屋への「了解」返信はしない。

  = セッションが**自分の規律遵守の判断**(返す必要があるか / §4.7に従うか)を本文に書き出し、
    それがそのままDiscordへ出た。§4.8(実況を書くな)違反が出力へ抜けた形だ。
  ★特定の人格の癖ではない= **どのセッションでも起きる**(口調ゲートDの話者別forbiddenでは拾えない)。
    剥ぐべきは「人格の声」ではなく「本文へ混じった手続きメタ」=構造。だから人事部門ではなくここ。

置き場所(2経路とも通す。ゲートC/Dが2経路に散っているのと同じ形):
  経路① 常駐    : dept_daemon の合流点(`split_wip_marker` の直後)
  経路② ミラー  : output_gates.apply_gates(mirror_to_discord.gate_body から呼ばれる)

設計(依頼の条件をそのまま実装する):
  ★**保守的に倒す**= 誤爆は「本文が欠ける」という取り返しのつかない事故になる。
    だから**高確度マーカーだけ**・**末尾の連続ブロックだけ**を剥ぐ。真ん中は触らない。
  ★**引用は剥がない**= 「」『』"" の中・行頭 `>` の引用・``` コードブロックの中は対象外。
    この事故そのものを部屋で論じる時(今この便がそうだ)に本文が消えるのを防ぐ。
  ★**判定不能・例外は素通し**(fail-open)。この関数は**どんな入力でも例外を投げない**。
  ★全部剥いで空になった時に「何を送るか」は**呼び出し側が決める**。ここは判断しない
    = 経路①は既存の「生成失敗」へ落ちる(=便が閉じずに残る)。経路②も同じ向きへ倒す。
  ★マーカーを足す時は**実物の specimen を1つ添えること**(推測で足すと誤爆が増える)。

検査= python scripts/llm/test_meta_strip.py
"""
import re

# ★高確度マーカー(名前, 正規表現, 実物の出所)。
#   条件= **日本語話者の人格が本文として書くことがあり得ない、ハーネス側の言い回し**であること。
#   ここに「§4.7」「上申」「手番」のような**日本語の規律語**を単独で入れてはいけない=
#   部門間の便では正当な本文に頻出する(この依頼の便自体がそうだ)。
_MARKERS = (
    # 実物: recent_copy-director.jsonl msg=DISPATCH-copy-director-1786794044539 の reply 冒頭。
    #   ハーネスが「返事は要らない便」に対して吐く定型。人格の台詞では絶対に出ない。
    ("no_response_requested", re.compile(r"^\s*no response requested\b", re.IGNORECASE)),
    # 実物: 同上。「これは裏の便だ」という**自分の経路の説明**=本文ではない。
    ("backchannel", re.compile(r"\bthis is a backchannel\b", re.IGNORECASE)),
    # 実物: 同系統(ハーネスの定型)。行頭に来た時だけ拾う。
    ("no_further_action",
     re.compile(r"^\s*\(?no (?:further )?action (?:is )?(?:required|needed)\b", re.IGNORECASE)),
    ("nothing_to_report",
     re.compile(r"^\s*\(?nothing (?:to report|further)\b", re.IGNORECASE)),
)

# 行頭の飾り(強調・箇条書き・引用の記号)。剥ぐ前にここだけ落として判定する。
_DECOR = "*_`~-—–•·  \t"
# 引用の開き。マーカーがこれらの**後ろ**に居る行は「引用している」と見て剥がない。
_QUOTE_OPEN = "「『“\"'（(【〔"


def is_meta_line(line):
    """1行が内部の手続きメタなら マーカー名 を返す(違えば None)。例外は投げない。"""
    try:
        s = str(line or "")
        body = s.lstrip(_DECOR)
        if body.lstrip().startswith(">"):        # 引用ブロックは人の言葉の写し=触らない
            return None
        for name, rx in _MARKERS:
            m = rx.search(body)
            if not m:
                continue
            # ★引用ガード= マーカーより前に開き括弧があるなら、それは「引用して論じている」行。
            if any(q in body[:m.start()] for q in _QUOTE_OPEN):
                return None
            return name
    except Exception:                            # noqa: BLE001
        return None
    return None


def strip_meta_tail(text):
    """本文の**末尾の連続したメタ行**を落として (本文, 剥いだ行) を返す。

    - 1件も当たらなければ **元の文字列をそのまま**返す(前後の空白の整形すらしない)。
    - 空行は末尾ブロックの一部として一緒に落とす(メタ行に挟まれた空行を残さないため)。
    - ``` の中(コードブロック)は対象外= 事故の再現手順を貼っている時に消さない。
    - ★全行がメタだった時は本文が空文字になる。**その扱いは呼び出し側の責任**。
    """
    try:
        s = str(text or "")
        if not s.strip():
            return s, []
        lines = s.splitlines()
        # 各行が ``` の内側かどうかを先に確定させる(後ろから走査するので前計算する)。
        inside, fence = [], False
        for ln in lines:
            if ln.lstrip().startswith("```"):
                inside.append(True)              # フェンス行自体も「中」扱い=触らない
                fence = not fence
            else:
                inside.append(fence)
        cut, hits = len(lines), []
        i = len(lines) - 1
        while i >= 0:
            ln = lines[i]
            if inside[i]:
                break
            if not ln.strip():                   # 空行は透過(ブロックの一部として落とす)
                i -= 1
                continue
            name = is_meta_line(ln)
            if not name:
                break
            hits.append({"marker": name, "line": ln.strip()[:300]})
            cut = i
            i -= 1
        if not hits:
            return s, []
        return "\n".join(lines[:cut]).rstrip(), list(reversed(hits))
    except Exception:                            # noqa: BLE001
        return text, []                          # 何が起きても素通し(沈黙ゼロ)
