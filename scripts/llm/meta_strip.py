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


# ============================================================================
# 実況漏れ(名乗り無しの生ログ露出)の検知  2026-09-01 / イージス研究室
# ----------------------------------------------------------------------------
# 発端= Chami 2026-09-01「アイが謎の機械口調」。
# 型doc= docs/departments/kaizen-analyst/型_実況漏れ_名乗り無し生ログ露出_2026-09-01.md
#        (改善提案部門・トトリ / 5SecMovieMaker 2f7cceb)。
# 壊れた実物(検体)= 00_AI-HQ/departments/hr/memory/shorts-analyst.jsonl
#   ts=2026-09-01T03:00:09 / msg_id=1544041139580178502 / from=三笘薫(軍議)。本文は**全部で2文**:
#     「リトライ中はPythonのstdoutバッファで出力が末尾までflushされない。完了通知を待つ。」
#   = 名乗りも一人称も相手も無く、機械のログがそのまま部屋へ出た。
#
# なぜ strip_meta_tail では拾えないか:
#   あちらは**末尾の連続ブロック**を剥ぐ。この事故は**本文が丸ごとメタ**なので剥ぐ先が無い
#   (剥げば空=沈黙になる)。だから剥がずに**検知だけ**して、呼び出し側が再生成へ回す。
#
# なぜ口調ゲートDでは拾えないか:
#   Dは話者ごとの禁止語(俺/お前/です。等)を見る。この本文には**禁止語が1つも無い**。
#   壊れているのは語彙ではなく「話者が本文の中に居ない」という構造だ。だから人事部門ではなくここ。
#   ★ここに人格名・人格固有の語尾を書かない(ORG-11=判定材料は写像2本のまま)。
#     下の _VOICE は「誰でもいい、話者が居る痕跡」であって特定人格の規則ではない。
#
# 3条件を**全部**満たした時だけ鳴らす(トトリの受け入れ条件1・2をそのまま実装):
#   ① 本文のどこにも `[名前]` ブロックが無い
#   ② 機械ログ語を1つ以上含む
#   ③ 話者が居る痕跡(一人称/呼びかけ/情動)が**1つも**無い
#   → ③が無いと、機械語を**本人の声で**語る正常便(07-29型)を巻き込む。
#
# 実測(2026-09-01・イージス研究室):
#   HQ hr/memory 32部屋 4,285便 → ①のみ=1,645便 / ①∧②=61便 / ①∧②∧③=**3便**(0.070%)。
#   61→3へ落としているのが③= 落ちた58便は全部「わね/オレ/ちゃみ、」等の声が在る正常便。
#   残った3便= 検体(09-01) / llm-edu 07-29「…をDL中。…落ちたら差し替えて生成する。」/
#              research-room 08-18(略号だけの羅列)。**声の無い状態報告**という同じ形で、
#              人の目で見て「これは人格の台詞だ」と言える便は1つも無い=明白な誤発火0。
#   local/llm/recent_* 132便 → 1便(同じ検体の 02:48:13 版)。検体は1回きりではなく2回出ている。
_MACHINE_WORDS = (
    "DL中", "バッチ", "flush", "stdout", "投函済", "msg=",
    "pending", "リトライ", "quota", "HTTP 5", "完了通知", "回送済",
)

# 「話者が居る」痕跡。どれか1つでも在れば**素通し**(=保守的に倒す)。
_VOICE_WORDS = (
    # 一人称(人格を問わない。どの人格も必ずどれかを使う)
    "俺", "オレ", "おれ", "僕", "ぼく", "私", "わたし", "あたし", "自分", "こっち", "うち",
    # 相手が居る=会話である痕跡
    "ちゃみ", "Chami", "さん", "君", "お前", "アンタ", "あんた", "コーチ", "監督", "くん", "ちゃん",
    # 情動・対人の語尾(機械ログには出ない)
    "わね", "わよ", "のよ", "だぜ", "ぜ。", "ぜ、", "だな", "かな", "だろ",
    "よ。", "ね。", "ね、", "わ。", "な。", "ます", "です", "——", "!", "！", "?", "？",
)
# 行頭の呼びかけ「アロンソ、受けた。」= 名前を知らなくても会話だと分かる形。
_ADDRESS_RE = re.compile(r"^[^\s、。」』\n]{2,12}[、][^\n]", re.M)
_TAG_RE = re.compile(r"^[ \t　]*[\[［][^\]］\n]{1,24}[\]］]", re.M)
_FENCE_RE = re.compile(r"```.*?```", re.S)


def detect_narration_leak(text):
    """実況漏れ(名乗り無しの生ログ露出)なら情報dictを返す(違えば None)。例外は投げない。

    返り値: {"machine": [当たった機械語], "reason": "narration_leak"} / None
    ★**判定だけ**する。本文は1文字も変えない(機械置換は事故を増やすだけ)。
    ★どんな入力でも例外を投げない= 判定不能は None(=素通し・fail-open)。
    """
    try:
        s = str(text or "")
        if not s.strip():
            return None
        if _TAG_RE.search(s):                    # ① 名乗りが在る=人格の便
            return None
        # コードブロックは「機械語が出て当たり前」の場所=判定から外す(貼り付けを巻き込まない)
        body = _FENCE_RE.sub(" ", s)
        machine = [w for w in _MACHINE_WORDS if w in body]
        if not machine:                          # ② 機械ログ語が無い
            return None
        if any(w in s for w in _VOICE_WORDS):    # ③ 話者が居る=素通し
            return None
        if _ADDRESS_RE.search(s):                # ③ 行頭の呼びかけ=会話=素通し
            return None
        return {"machine": machine, "reason": "narration_leak"}
    except Exception:                            # noqa: BLE001
        return None                              # 判定で転んだら素通し(沈黙ゼロ)
