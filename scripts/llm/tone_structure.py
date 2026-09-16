#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""口調の崩れを**構造**で数えるだけの一段(閾値を置かない・誰も落とさない)。

なぜ要るか(2026-09-16 aegis-gl・ケヴィン・デブライネ):
  口調の崩れには少なくとも3つの軸が在る、というのがAD研究室の corpus 実測だ。
    軸① 語尾・トーン    → 送信直前の語尾ゲート(tone_backstop)が既に見ている
    軸② 構造(レポート体) → **どのゲートも見ていない**。区切り線+太字の節見出し+
                            番号ラベルで手順を割る形。語尾は人格域内なので語尾ゲートを
                            素通りする= 構造でしか見えない(オタコン 9/01・花海咲季 9/15)
    軸③ 他人格からの引っ張り → 自分の原典に負例を書いても**原理的に止まらない**
                            (9/05 に一ノ瀬怜とヴィルシーナへ同日2件
                             「ジェンティルドンナに口調引っ張られてるよ」)
  ★ここで閾値を置くと、正当な技術説明を殴る。実測(AD研究室)= 崩れた便の bold は 3、
    平時の中央値 1・最大 5 で**分離しない**。だから今は**数えて書くだけ**にする。
    分布が溜まってから閾値を決める= 軸②が通った道(検知先行・剥ぐ手は後)と同じ順番。

使う側= `persona_send.apply_text_gates()`(外へ出る本文の唯一の合流点・ORG-11/C-064)。
読む側= `python scripts/llm/tone_structure_report.py`。
この関数は**何も書き換えない・何も落とさない**。副作用を足すな。
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 口調ルールの正本=研究室HQ(ORG-11)。persona_send の TONE_RULES_PATH と**同じ1本**を見る=
# GO5_HQ_DIR の上書きも同じに扱う(置き場を2つ持たない)。
_HQ_ROOT = os.environ.get("GO5_HQ_DIR") or os.path.normpath(
    os.path.join(os.path.dirname(ROOT), "00_AI-HQ"))
TONE_RULES = os.path.join(_HQ_ROOT, "departments", "hr", "personas", "口調ルール.json")

_RULES_CACHE = {"mtime": None, "data": None}

# 一人称は短く、地の文へ普通に現れる語も混ざる(「私」「僕」)。★軸③の材料として数えるのは
# **識別力のある一人称だけ**= 口調ルール側の方針(distinctive)と揃える。
_WEAK_FIRST_PERSON = {"私", "僕", "わたし", "自分", "こちら"}

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_HR = re.compile(r"^\s*(-{3,}|─{3,}|={3,})\s*$")
_HEADING = re.compile(r"^\s*#{1,6}\s+\S")
# ★`・` は日本語では**空白を置かずに**続けるのが普通(「・中黒」)。`\s+` を必須にすると
#   実物の箇条書きを取りこぼす(2026-09-16 実測で踏んだ)。行頭の `・` は箇条書きと見る=
#   「ケヴィン・デブライネ」のような語中の中黒は行頭に来ないので誤検知しない。
_BULLET = re.compile(r"^(\s*)(?:[-*]\s+\S|[・①-⑳]\s*\S|\d+[.)]\s+\S)")
# 「**① 最初の1回だけ**」のように**太字の番号ラベル**で手順を割る形。崩れ便の骨格。
# ★番号が太字の中で**単独**とは限らない(実物は `**① 最初の1回だけ**`)= 先頭一致で見る
#   (2026-09-16 実測。単独前提の式では実便の3本を1本も拾えなかった)。
_NUMLABEL_HEAD = re.compile(r"^\s*(?:[①-⑳]|[0-9]{1,2}[.)]|[A-Z][.)])")
_TABLE = re.compile(r"^\s*\|.*\|\s*$")
# 行頭が太字ラベルで始まる節見出し(「**■ 見た実物**」「**結論**=」)
_BOLD_HEAD = re.compile(r"^\s*(?:[■□◆●▼★]\s*)?\*\*[^*]{1,40}\*\*\s*[=:：]?")


def _load_rules():
    """口調ルール.json を mtime 都度読みで拾う(人事部門が足した人格が即日効くように)。"""
    try:
        m = os.path.getmtime(TONE_RULES)
    except OSError:
        return {}
    if _RULES_CACHE["mtime"] == m and _RULES_CACHE["data"] is not None:
        return _RULES_CACHE["data"]
    try:
        with open(TONE_RULES, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:                                # noqa: BLE001
        return _RULES_CACHE["data"] or {}
    _RULES_CACHE["mtime"] = m
    _RULES_CACHE["data"] = data
    return data


def _persona_entry(personas, name):
    """名前の前後空白・肩書き付き表記のゆれを吸って人格エントリを引く(無ければ None)。"""
    n = str(name or "").strip()
    if not n:
        return None
    if n in personas:
        return personas[n]
    for k in personas:
        if n.startswith(k) or k.startswith(n):
            return personas[k]
    return None


def other_persona_material(persona):
    """★軸③の材料。**自分以外の**人格の名前と識別力のある一人称を返す。

    自分のものは必ず除く= 自分の一人称を数えて「混ざっている」と言ったら偽の赤になる。
    """
    data = _load_rules()
    personas = data.get("personas") or {}
    me = None
    n = str(persona or "").strip()
    for k in personas:
        if n and (n.startswith(k) or k.startswith(n)):
            me = k
            break
    mine = set()
    if me:
        mine.add(me)
        for fp in (personas.get(me, {}).get("first_person") or []):
            mine.add(fp)
    names, fps = [], []
    for k, v in personas.items():
        if k == me:
            continue
        names.append(k)
        for fp in (v.get("first_person") or []):
            if fp in mine or fp in _WEAK_FIRST_PERSON:
                continue
            fps.append(fp)
    return {"me": me or "", "names": names, "first_persons": sorted(set(fps))}


def count_structure(body, persona=None):
    """本文の構造指標を数える。**判定しない**(閾値も真偽も返さない)。

    戻り値= 数だけの dict。ここに「崩れている/いない」を入れるな——
    入れた瞬間に閾値を置いたことになり、正当な技術説明を殴る側へ回る。
    """
    text = str(body or "")
    lines = text.splitlines()
    bolds = _BOLD.findall(text)
    depths = []
    bullets = hrs = heads = tables = bold_heads = 0
    for ln in lines:
        if _HR.match(ln):
            hrs += 1
        if _HEADING.match(ln):
            heads += 1
        if _TABLE.match(ln):
            tables += 1
        if _BOLD_HEAD.match(ln):
            bold_heads += 1
        m = _BULLET.match(ln)
        if m:
            bullets += 1
            depths.append(len(m.group(1).replace("\t", "  ")) // 2)

    mat = other_persona_material(persona)
    others_name = {}
    for k in mat["names"]:
        c = text.count(k)
        if c:
            others_name[k] = c
    others_fp = {}
    for fp in mat["first_persons"]:
        c = text.count(fp)
        if c:
            others_fp[fp] = c

    return {
        "chars": len(text),
        "lines": len(lines),
        "bold": len(bolds),
        "bold_head": bold_heads,
        "hr": hrs,
        "heading": heads,
        "bullet": bullets,
        "bullet_depth": max(depths) if depths else 0,
        "numlabel": sum(1 for s in bolds if _NUMLABEL_HEAD.match(s)),
        "table": tables,
        # ★軸③= 他人格の固有名詞・一人称が何個混ざったか(AD研究室 msg 1549597333283676171 の注文)。
        #   ★数えるだけ= 部門間の報告では他人格の名前が正当に出る。ここで赤くしない。
        "other_names": others_name,
        "other_names_total": sum(others_name.values()),
        "other_first_person": others_fp,
        "other_first_person_total": sum(others_fp.values()),
    }
