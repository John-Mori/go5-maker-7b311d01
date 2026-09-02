# -*- coding: utf-8 -*-
"""出力ゲートJ= **構造ドリフト(Claude既定のレポート骨格)の検知**。 2026-09-02

★0歩目に見た壊れた実物(検知でなく、実際に出た便):
  - `DISPATCH-aegis-gl-1788315302529`(シャビ・アロンソ 11:15)= 敬語16・一人称ゼロ・■節見出し。
  - `DISPATCH-hq-1788317734354`(ケヴィン・デブライネ 11:56)= 同型。**この機構を書いた本人の便**だ。
  発注= 人事部門ククール(657/f98d721938 の残り・msg DISPATCH-aegis-gl-1788318083311)。
  Chami原文(657)=「アロンソの口調がClaude標準、色んな人の口調がバグる」。

★なぜ口調ゲートD(tone_gate)で獲れないか= Dが見るのは**語尾・方言・一人称の取り違え**で、
  どれも「語尾域内」に収まると素通しになる。崩れているのは**文の骨格**の方だ
  (■節見出しの連発+太字の多用+一人称の消失)。語の写像では表現できない=別の因子が要る。

★判定は3因子の**同時成立**だけ(1つでも欠けたら黙る):
  ①■/## の節見出しが HEAD_MIN 本以上  ②**太字**が BOLD_MIN 個以上
  ③その人格の一人称(口調ルール.json の first_person)が本文に**1つも無い**
  ★③が無いと、ただの技術メモまで叩く。実測= 全部門の実便 `local/discord_processed.jsonl`
    4,858本のうち ①②だけなら481本が当たるが、③まで足すと **58本**へ落ちる。
    ★分母は「口調ルールに一人称が登録されている人格の便」= 556本 → 発火率 **10.4%**。
    内訳= デブライネ 37/126=29%(表記2形の合算)/ アロンソ 13/85=15% /
    モドリッチ2・トトリ2・怜1・星南1・ククール1・オタコン1。★最悪の常習犯は**この機構を書いた本人**だ。
    ★この数字は下の first_person() 経由=つまり**本番と同じ引き当て**で数えた。
      自前の dict 参照で数えた時は 48/511 だった=別名(中黒あり)を取りこぼしていた。
      写像を2本持つと計測まで狂う、の実例(ORG-11)。

★ここは**書き直さない**(警告のみ)。理由は2つ:
  1. 骨格の書き直しは置換で決まらない=一意な写像が無い(ゲートDが方言を直せないのと同じ理由)。
  2. だが**警告のみは素通りする**——それは session_relay の設計コメントが実測で証明済みだ。
  → だから台帳は `tone_audit.jsonl` へ **event="tone" / reason="structure_drift"** で書く。
    session_relay の既存の突き返し(次の封筒へ「前の便で口調が崩れた」を出す機構)が
    event="tone" を拾う=**新しい配線を1本も足さずに、生成側の目の前へ出る**。
    ★新方式を作る前に、既に効いている型へ合流する(共通規律§3)。

★fail-open= 何が起きても本文は素通しする。この段が配送を殺さない。
"""
import json
import os
import re
import time

try:
    import tone_gate as _tone
except Exception:                                     # 単体で読み込まれた時
    try:
        from . import tone_gate as _tone              # type: ignore
    except Exception:
        _tone = None

# 節見出し= 「■」始まり と markdown の `## 〜`。
# ★「【」は入れない= 【AD研究室 → イージス研究室】のような**宛名行**が全部当たるからだ
#   (実測で数え直して外した)。★「#」1本は本文の強調に使われることがあるので `##` 以上。
_HEAD = re.compile(r"^\s*(?:■|#{2,6}\s)")
_BOLD = re.compile(r"\*\*[^*\n]+\*\*")
_FENCE = re.compile(r"```.*?```", re.S)
_TAG = re.compile(r"^\[[^\]\n]{1,20}\]\s*")

HEAD_MIN = 3
BOLD_MIN = 6


def _body(text):
    """引用行(>)とコードフェンスを落とした本文。引用の中の骨格は本人の骨格ではない。"""
    s = _FENCE.sub("", str(text or ""))
    s = _TAG.sub("", s)                               # 1行目の名乗り `[名前]` は数えない
    return "\n".join(l for l in s.splitlines() if not l.lstrip().startswith(">"))


def features(text):
    """(見出しの本数, 太字の個数, 判定に使った本文の字数)。★数えるだけ・判定はしない。"""
    b = _body(text)
    return (sum(1 for l in b.splitlines() if _HEAD.match(l)),
            len(_BOLD.findall(b)),
            len(b))


def first_person(persona, rules):
    """この人格の正規の一人称。写像は口調ルール.json 1本だけ(ORG-11)=ここに名前を書かない。"""
    try:
        if not rules or _tone is None:
            return []
        ent = _tone._persona_entry(rules, persona) or {}
        return [str(x) for x in (ent.get("first_person") or []) if str(x)]
    except Exception:
        return []


def scan(persona, text, rules):
    """当たったら1件ぶんのdict、当たらなければ None。★3因子が揃った時だけ。"""
    try:
        own = first_person(persona, rules)
        if not own:
            return None                               # 一人称が登録されていない人格は判定しない
        head, bold, _n = features(text)
        if head < HEAD_MIN or bold < BOLD_MIN:
            return None
        body = _body(text)
        if any(x in body for x in own):
            return None                               # 声が残っている=骨格が硬いだけ
        return {"persona": str(persona or ""), "reason": "structure_drift",
                "marker": "節見出し%d本+太字%d個+一人称ゼロ" % (head, bold),
                "head": head, "bold": bold, "own_first_person": own}
    except Exception:
        return None                                   # 判定で転んでも本文は通す


def audit(text, dept="", persona="", rules=None, source="", msg_id="", audit_path=None):
    """検知して台帳へ1行。★本文は返さない=**書き直さないゲート**だから。

    返り値: 当たった時 [hit] / 当たらない時 []。
    ★event は "tone"= session_relay の突き返しへ相乗りするため(この選択が本機構の要)。
    """
    hit = scan(persona, text, rules)
    if not hit:
        return []
    try:
        if audit_path:
            os.makedirs(os.path.dirname(audit_path), exist_ok=True)
            with open(audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "dept": str(dept or ""), "event": "tone",
                    "reason": "structure_drift",
                    "persona": hit["persona"], "source": str(source or ""),
                    "marker": hit["marker"],
                    "own_first_person": hit["own_first_person"],
                    "head": hit["head"], "bold": hit["bold"],
                    "msg_id": str(msg_id or ""),
                    "excerpt": str(text or "")[:200],
                }, ensure_ascii=False) + "\n")
    except Exception:
        pass                                          # 監査の失敗で配送を巻き添えにしない
    return [hit]
