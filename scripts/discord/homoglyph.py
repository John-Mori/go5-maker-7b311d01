#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人格名の同形異字(ホモグリフ)を正名へ寄せる正本(2026-09-04・依頼=人事部門ククール)。

**なぜ1本にまとめるか**: 表を2か所に持つと必ず片方が腐る(ORG-11)。
炎上ゲート(`enjoh.py`)と同じ置き方で、OUT口の両方(persona_send / bot_send)と
名義解決(resolve_persona)から **この1本だけ** を import する。

直す対象は2つ:
  (1) **名義**  … `[ККール]` / `[KKール]` のようにタグが化けた時、送信名を「ククール」へ寄せる。
  (2) **本文中の人格名** … 「オレ(ККール)の持ち場だ」のように地の文で化けた自称・言及。
      実物= Discord msg 1545137710820360214(キリルК U+041A)。Chamiの画面には
      「(KKール)」と映り、本人が詫びる羽目になった。

**誤爆させない掛け金**(ここが肝心。地の文の1字置換は絶対にやらない):
  - 置換は **既知の人格名の全体一致** でだけ起きる。「力」単独や「口」単独は動かない。
  - 3字以上の名前だけを見る。
  - 化けた字は最大 len-2 字まで(=正しい字が2字以上残っている時だけ寄せる)。
  - 候補が2人以上に当たる時は **直さない**(取り違えるくらいなら化けたまま出す)。
  - どこで失敗しても素通し(fail-open)。送信を止める権利はこのゲートに無い。
"""
import json
import os
import re
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
AVATARS_FILE = os.path.join(LOCAL, "persona_avatars.json")
AUDIT_FILE = os.path.join(LOCAL, "llm", "naming_audit.jsonl")

# ── 同形異字表(正本) ────────────────────────────────────────────────
# 左= 正しい字 / 右= 見た目が同じで化けやすい字。**足すならここ1か所**。
# 実測で出たもの(★)と、日本語で古典的に取り違えられる組を入れてある。
CONFUSABLES = {
    "ク": "КкΚκKkＫｋｸ",  # ★実測 U+041A(キリルК)/ U+004B(ラテンK)
    "カ": "力Ｋ",            # 力=漢字ちから
    "ロ": "口ОоOoＯ０0",   # 口=漢字くち
    "エ": "工",
    "ニ": "二",
    "ト": "卜",
    "タ": "夕",
    "オ": "才",
    "ハ": "八",
    "ヘ": "へ",              # ひらがな へ
    "リ": "り刂",
    "ミ": "彡",
    "ナ": "十",
    "ヒ": "匕",
    "ム": "厶",
    "セ": "世",
    "イ": "ィ",
    "ア": "ァ",
    "ー": "-‐‑–—―─−－ｰ_",  # 長音とハイフン類
    "・": "･·•‧",
    "ス": "ｽ",
    "ル": "ﾙ",
}

# 変異表を引きやすい形へ畳んだもの: 化けた字 -> 正しい字
_FOLD = {}
for _base, _vars in CONFUSABLES.items():
    for _v in _vars:
        _FOLD.setdefault(_v, _base)

MIN_NAME_LEN = 3        # 2字の名前は取り違えが怖いので触らない
_CACHE = {"names": None, "at": 0.0}
_CACHE_TTL = 60.0


def fold(s):
    """字ごとに正しい字へ倒した文字列を返す(比較用。表示には使わない)。"""
    return "".join(_FOLD.get(c, c) for c in s)


def _nfkc(s):
    try:
        return unicodedata.normalize("NFKC", s)
    except Exception:
        return s


def known_names(extra=None):
    """既知の人格名(avatars.json のキー = 名義の正本)。60秒だけ覚える。"""
    now = time.time()
    if _CACHE["names"] is None or now - _CACHE["at"] > _CACHE_TTL:
        names = set()
        try:
            with open(AVATARS_FILE, encoding="utf-8") as f:
                names = set(json.load(f).keys())
        except Exception:
            names = set()
        _CACHE["names"], _CACHE["at"] = names, now
    names = set(_CACHE["names"])
    for n in (extra or []):
        if n:
            names.add(n)
    return names


def _diff_count(a, b):
    """同じ長さの2文字列で、字が違う箇所の数。"""
    return sum(1 for x, y in zip(a, b) if x != y)


def _match_name(cand, name):
    """cand が name の同形異字ゆらぎか。掛け金を全部通った時だけ True。"""
    if len(cand) != len(name) or len(name) < MIN_NAME_LEN:
        return False
    if cand == name:
        return False                      # もう正しい= 触らない
    for x, y in zip(cand, name):
        if x != y and _FOLD.get(x) != y:  # 表に無い違いが1つでもあれば別語
            return False
    d = _diff_count(cand, name)
    return 1 <= d <= max(1, len(name) - 2)


def canonical_name(name, names=None):
    """化けた人格名を正名へ寄せる。→ (正名 or "", 理由)。

    一意に決まらない時は ("", 理由) を返す= **直さない**。
    """
    try:
        name = (name or "").strip()
        if not name:
            return "", "empty"
        pool = names if names is not None else known_names()
        if name in pool:
            return "", "already-known"
        if _nfkc(name) in pool:           # 半角カナ等はNFKCで正名に戻る
            return _nfkc(name), "nfkc"
        hits = set()
        for cand in (name, _nfkc(name)):
            for n in pool:
                if _match_name(cand, n):
                    hits.add(n)
        if len(hits) == 1:
            return hits.pop(), "homoglyph"
        if len(hits) > 1:
            return "", "ambiguous:" + "/".join(sorted(hits))
        return "", "no-match"
    except Exception as e:      # fail-open
        return "", "error:%s" % e


def _pattern_for(name):
    """name の各字に「その字 or その同形異字」を許す正規表現。"""
    out = []
    for ch in name:
        vs = CONFUSABLES.get(ch, "")
        out.append("[" + re.escape(ch + vs) + "]" if vs else re.escape(ch))
    return re.compile("".join(out))


def fix_text(text, names=None):
    """本文中の化けた人格名を正名へ直す。→ (直した本文, 変更リスト)。"""
    changes = []
    try:
        if not text:
            return text, changes
        pool = names if names is not None else known_names()
        # 化けうる字を1つ以上持つ名前だけが対象(=大半の名前はそもそも動かない)
        targets = [n for n in pool
                   if len(n) >= MIN_NAME_LEN and any(c in CONFUSABLES for c in n)]
        for n in sorted(targets, key=len, reverse=True):
            def _sub(m, _n=n):
                got = m.group(0)
                if got == _n:
                    return got
                # 一意判定はここでも通す(2人に当たる字面は化けたまま出す)
                canon, _why = canonical_name(got, pool)
                if canon != _n:
                    return got
                changes.append({"from": got, "to": _n})
                return _n
            text = _pattern_for(n).sub(_sub, text)
        return text, changes
    except Exception:           # fail-open
        return text, changes


def _audit(rec):
    try:
        os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def homoglyph_backstop(body, persona=None, dept=None, tag="", channel=None):
    """OUT口の合流点ゲート。本文中の化けた人格名を直して返す(C-064)。"""
    try:
        fixed, changes = fix_text(body, known_names([persona] if persona else None))
        if changes:
            _audit({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "event": "homoglyph_body_fix", "dept": dept, "persona": persona,
                    "channel": channel, "via": tag or "persona_send",
                    "fixed": changes[:10], "n": len(changes)})
            for c in changes[:5]:
                print("[homoglyph] 本文の人格名を正名へ: %r -> %r" % (c["from"], c["to"]),
                      file=sys.stderr)
        return fixed
    except Exception:
        return body


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--name":
        for a in args[1:]:
            print(a, "->", canonical_name(a))
    else:
        src = " ".join(args) or sys.stdin.read()
        out, ch = fix_text(src)
        print(out)
        print("changes:", ch, file=sys.stderr)
