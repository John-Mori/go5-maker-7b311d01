#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受信テキストの不可視Unicodeを見張る正本(2026-09-04・依頼=研究室HQ msg 1545233909699051611)。

**なぜ要るか**: U+E0000-E007F(Unicode Tags)は人間の目に一切映らないが、AIには読める。
プロンプトインジェクションの手口が、スパムフィルタ回避へ転用され始めている
(Microsoft Security Blog 2026-09-03 "ASCII Smuggling crosses over from AI prompt
injection to phishing evasion"・Chami共有 msg 1545228542122655758)。
**読むのはAIなので、人の目視レビューでは止まらない。**

HQ実測(2026-09-04・117ファイル/47,938,737バイト):
  - U+E0000-E007F = 0件(密輸帯の現物はまだ来ていない)
  - だが**同じ形は既に入っている** … ZWSP 6 / WJ 6 / FSI 3 / BOM 12 / SOFT HYPHEN 12 / ZWJ 36
    実物= msg 1543275691204943962(2026-08-29 Chamiの貼り付け)に `Cyber<U+200B><U+200B>duck`
    = **単語の内側にZWSPが2つ**。記事の `fun + U+E0020 + ding` と同じ形。
  → Web由来のテキストは既に不可視文字を連れてきている。

**方針(HQ指示)**:
  - U+E0000-E007F(密輸帯)= **除去する**。人に見えない以上、残す理由が1つも無い。
  - ZW系/bidi系(200B-200F・202A-202E・2060-2069・FEFF・00AD)= **残して警告だけ**。
    絵文字連結のZWJや正規のbidi制御を消すと本文の意味が壊れる(ZWJ 36件の大半は絵文字)。

**置き方**: 表を2か所に持つと必ず片方が腐る(ORG-11)。`homoglyph.py`(OUT口の正本)と
同じ置き方で、**受信の合流点1か所**だけがこのモジュールを import する。
★homoglyph.py は**出て行く手**(persona_send / bot_send)の持ち場、こちらは**入って来る手**。
  向きが逆なので二重ではない(C-052の確認済み)。

**fail-open**: どこで失敗しても素の本文をそのまま返す。受信を止める権利はこのゲートに無い
(共通規律§3= 可用性に関わる所は fail-open。最悪の事故は沈黙)。
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
AUDIT_FILE = os.path.join(ROOT, "local", "llm", "invisible_audit.jsonl")

# ── 密輸帯(除去する) ──────────────────────────────────────────────
TAG_LO, TAG_HI = 0xE0000, 0xE007F

# ── 見張るが消さない帯(残して警告) ──────────────────────────────
#   ★足すならここ1か所。HQの走査スクリプト local/_work/invisible_scan.py と同じ表。
WATCH = {
    0x00AD: "SOFT HYPHEN",
    0x200B: "ZWSP", 0x200C: "ZWNJ", 0x200D: "ZWJ",
    0x200E: "LRM", 0x200F: "RLM",
    0x202A: "LRE", 0x202B: "RLE", 0x202C: "PDF", 0x202D: "LRO", 0x202E: "RLO",
    0x2060: "WJ", 0x2061: "FA", 0x2062: "IT", 0x2063: "IS", 0x2064: "IP",
    0x2066: "LRI", 0x2067: "RLI", 0x2068: "FSI", 0x2069: "PDI",
    0xFEFF: "BOM/ZWNBSP",
}

# 絵文字の連結(ZWJ)は日常的に出る= それ単独では警告に数えない。
#   ★常に誤発火する安全網は無視される(共通規律§3)。
NOISY = {0x200D}


def decode_tags(text):
    """密輸帯に隠された中身をASCIIへ戻す= **何を隠していたか**の証拠。

    U+E0020-U+E007E は ASCII 0x20-0x7E に1対1で対応する(0xE0000 を引くだけ)。
    見つからなければ空文字。
    """
    try:
        out = []
        for ch in text:
            cp = ord(ch)
            if 0xE0020 <= cp <= 0xE007E:
                out.append(chr(cp - 0xE0000))
        return "".join(out)
    except Exception:
        return ""


def scan(text):
    """本文を数えるだけ(1文字も変えない)。読み取り専用なので誰が呼んでもよい。

    返り値= {"tags": 密輸帯の文字数, "watch": {名前: 件数}, "hidden": 復号したASCII}
    """
    result = {"tags": 0, "watch": {}, "hidden": ""}
    try:
        for ch in text or "":
            cp = ord(ch)
            if TAG_LO <= cp <= TAG_HI:
                result["tags"] += 1
            elif cp in WATCH and cp not in NOISY:
                name = WATCH[cp]
                result["watch"][name] = result["watch"].get(name, 0) + 1
        if result["tags"]:
            result["hidden"] = decode_tags(text)
    except Exception:
        return {"tags": 0, "watch": {}, "hidden": ""}
    return result


def sanitize(text):
    """入口ゲート本体。**密輸帯だけ消す。他は1文字も触らない。**

    返り値= (きれいにした本文, 報告dict)。
    報告dict は scan() と同じ形 + "stripped"(消した文字数)。
    ★失敗したら素の本文を返す(fail-open)。
    """
    if not text:
        return text, {"tags": 0, "watch": {}, "hidden": "", "stripped": 0}
    try:
        report = scan(text)
        report["stripped"] = report["tags"]
        if not report["tags"]:
            return text, report
        clean = "".join(ch for ch in text
                        if not (TAG_LO <= ord(ch) <= TAG_HI))
        return clean, report
    except Exception:
        return text, {"tags": 0, "watch": {}, "hidden": "", "stripped": 0}


def audit(report, where, msg_id=None, dept=None):
    """警告を台帳へ1行。★書けなくても呼び出し元を巻き込まない(fail-open)。

    ★鳴っている≠届いている(共通規律§4)= ここは記録。人が読む面へは
      absence_watchdog 側から拾わせる想定で、まずは実物を貯める。
    """
    try:
        if not report or (not report.get("tags") and not report.get("watch")):
            return False
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "where": where,
            "msg_id": str(msg_id) if msg_id is not None else None,
            "dept": dept,
            "tags": report.get("tags", 0),
            "stripped": report.get("stripped", 0),
            "watch": report.get("watch", {}),
            "hidden": (report.get("hidden") or "")[:200],
        }
        os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def gate(text, where, msg_id=None, dept=None):
    """合流点から呼ぶ1本= 消す・記録する・きれいな本文を返す、をまとめただけ。"""
    clean, report = sanitize(text)
    audit(report, where, msg_id=msg_id, dept=dept)
    return clean, report
