#!/usr/bin/env python3
"""出力ゲートH(かな括弧の選択肢ラベル)= 純関数の正本。2026-09-02 イージス研究室。

依頼= 研究室HQ msg 1544509917568831569(台帳 HQ-0232)。Chamiが炎上+再発を同時に押した実物=
  msg 1544451166887350322「(あ)、(い)で選択肢やめてって前も言ったでしょ〜」(3回目)。
  1回目= 共通規律への明文化 / 2回目= msg 1540768838533259315「1,2,3〜やA,B,C〜でお願い」。

なぜ口調ゲートD(tone_gate)ではないか:
  Dの写像は **話者別**(口調ルール.json の persona ごとの forbidden)だ。かな括弧は
  **誰が書いても駄目**= 話者非依存。話者別の器に入れると、人格を1つ足すたびに穴が開く。
  だから話者を見ない純関数として独立させ、両方の合流点から**同じ1本**を呼ぶ。

★かける面= Discordへ出る本文(経路①常駐 dept_daemon / 経路②ミラー output_gates)。
  片方だけに置いた実装は必ず割れる(2026-08-15 口調ドリフトの再来を作らない)。
★検出= 1行の中にかな1文字の丸括弧ラベルが**2個以上**。加えて、**行頭ラベルが2行以上**
  連なる箇条書き((あ) …\n(い) …)も同じ選択肢の形なので拾う。
  ★単発の (あ) は相槌= 対象外(「(あ)、そうか」を壊さない)。
★置換= 同じラベルは1つの本文の中で**同じ数字**へ。ラベルが9個を超えるなど一意に決まらない時は
  **素通し**(記録だけ残す)。コードブロック/インラインコード/引用行(>)は触らない
  = 規律やこの穴そのものを本文で論じる部屋が壊れないようにする(ゲートDが実測で踏んだ穴)。
★fail-open: 例外が何処で起きても**元の本文を返す**。ゲートが送信を殺すことは絶対に無い。
"""
import json
import os
import re
import time

# かな1文字を丸括弧で囲んだラベル。半角 () と全角 () の両方。
#   ひらがな(ぁ-ん)・カタカナ(ァ-ヶ)の1文字だけ= 「(笑)」「(1)」「(注)」は当たらない。
KANA_LABEL_RE = re.compile(r"([((])([ぁ-んァ-ヶ])([))])")

# 行頭の飾り(箇条書き記号・番号なし)。ここまでを「行頭」と見なす。
_HEAD_RE = re.compile(r"^[\s　]*(?:[-*・‣]\s*)?")

# コードは触らない(奇数要素=コード)。enjoh.py と同じ考え方。
_CODE_SPLIT_RE = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)
_MASK = "\x00"


def _masked(text):
    """コードと引用行を伏せた**同じ長さ**の写しを返す(位置がそのまま使える)。"""
    parts = _CODE_SPLIT_RE.split(text)
    buf = []
    for i, p in enumerate(parts):
        buf.append(p if i % 2 == 0 else _MASK * len(p))
    s = "".join(buf)
    out = []
    for ln in s.split("\n"):
        out.append(_MASK * len(ln) if ln.lstrip().startswith(">") else ln)
    return "\n".join(out)


def find_choice_labels(text):
    """選択肢として使われている かな括弧ラベルの出現位置を返す。

    返り値: [{"start":int, "end":int, "label":"(あ)", "kana":"あ", "line":int, "shape":str}, …]
      shape = "inline"(1行に2個以上) / "list"(行頭ラベルが2行以上連なる箇条書き)
    ★単発(1本文に1個だけ・行頭でもない)は空リスト= 相槌を壊さない。
    """
    s = str(text or "")
    if "(" not in s and "(" not in s:
        return []
    m = _masked(s)
    hits = []
    head_lines = []          # (line_no, [span…]) 行頭にラベルが立っている行
    pos = 0
    for ln_no, line in enumerate(m.split("\n")):
        spans = [(pos + x.start(), pos + x.end(), x.group(0), x.group(2))
                 for x in KANA_LABEL_RE.finditer(line)]
        if len(spans) >= 2:
            for st, en, lab, kana in spans:
                hits.append({"start": st, "end": en, "label": lab, "kana": kana,
                             "line": ln_no, "shape": "inline"})
        elif len(spans) == 1:
            head = len(_HEAD_RE.match(line).group(0))
            if spans[0][0] - pos == head:
                head_lines.append((ln_no, spans[0]))
        pos += len(line) + 1
    # 箇条書き形= 行頭ラベルが**2行以上**あり、少なくとも2種類のかなが並んでいる時だけ。
    if len({sp[3] for _, sp in head_lines}) >= 2:
        for ln_no, (st, en, lab, kana) in head_lines:
            hits.append({"start": st, "end": en, "label": lab, "kana": kana,
                         "line": ln_no, "shape": "list"})
    hits.sort(key=lambda h: h["start"])
    return hits


def kana_choice_corrections(text):
    """かな括弧ラベルを 1,2,3 へ直す。直せない時は本文を1ミリも変えずに記録材料だけ返す。

    返り値: {"fixed": str, "applied": [...], "remaining": [...], "hits": n}
      applied  = [{"label":"(あ)", "to":"(1)", "count":n, "shape":str}] 直した分
      remaining= [{"labels":[…], "reason":str}]                        直さず記録だけの分
    ★同じラベルは本文の中で同じ数字(初出順に 1,2,3…)。
    ★例外は外へ出さない= 呼び手は必ず本文を受け取れる(fail-open)。
    """
    out = {"fixed": text, "applied": [], "remaining": [], "hits": 0}
    try:
        s = str(text or "")
        hits = find_choice_labels(s)
        if not hits:
            return out
        out["hits"] = len(hits)
        order = []
        for h in hits:
            if h["kana"] not in order:
                order.append(h["kana"])
        if len(order) > 9:
            # 一意に決まらない(1桁の数字に収まらない)= 素通し。記録だけ残す。
            out["remaining"] = [{"labels": ["(" + k + ")" for k in order],
                                 "reason": "ラベルが9個を超える=数字への対応が一意に決まらない"}]
            return out
        num = {k: str(i + 1) for i, k in enumerate(order)}
        buf = []
        last = 0
        count = {}
        for h in hits:
            buf.append(s[last:h["start"]])
            op, cl = h["label"][0], h["label"][-1]
            buf.append(op + num[h["kana"]] + cl)
            last = h["end"]
            key = (h["label"], op + num[h["kana"]] + cl, h["shape"])
            count[key] = count.get(key, 0) + 1
        buf.append(s[last:])
        out["fixed"] = "".join(buf)
        out["applied"] = [{"label": k[0], "to": k[1], "shape": k[2], "count": v}
                          for k, v in count.items()]
        return out
    except Exception as e:
        # 何が起きても元の本文。沈黙・破損より素通しを選ぶ。
        return {"fixed": text, "applied": [], "remaining": [],
                "hits": 0, "error": type(e).__name__}


def apply_and_audit(text, dept="", persona="", source="", msg_id="", audit_path=None):
    """★両方の経路から呼ばれる唯一の入口。本文を直し、既存の tone_audit.jsonl へ相乗りする。

    記録先を2つ持たない(受け入れ条件5)= 呼び手が自分の TONE_AUDIT を渡す。
    どちらの経路かは `"source"` で分ける(daemon / mirror)。
    返り値: (本文, applied, remaining)。例外時は (元の本文, [], [])。
    """
    try:
        res = kana_choice_corrections(text)
        applied = res.get("applied") or []
        remaining = res.get("remaining") or []
        if (applied or remaining) and audit_path:
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")     # JST(この端末はJSTで動く)
            rows = []
            for a in applied:
                rows.append({"ts": ts, "dept": dept, "event": "kana_choice_fix",
                             "persona": str(persona or ""), "source": source,
                             "label": a.get("label", ""), "to": a.get("to", ""),
                             "shape": a.get("shape", ""), "count": a.get("count", 0),
                             "msg_id": str(msg_id or ""),
                             "excerpt": str(text or "")[:200]})
            for v in remaining:
                rows.append({"ts": ts, "dept": dept, "event": "kana_choice",
                             "persona": str(persona or ""), "source": source,
                             "labels": v.get("labels", []), "reason": v.get("reason", ""),
                             "msg_id": str(msg_id or ""),
                             "excerpt": str(text or "")[:200]})
            try:
                os.makedirs(os.path.dirname(audit_path), exist_ok=True)
                with open(audit_path, "a", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            except Exception:
                pass            # 監査の失敗で送信を巻き添えにしない
        fixed = res.get("fixed", text)
        if not str(fixed or "").strip():
            return text, applied, remaining     # 空になったら元を通す(沈黙ゼロ)
        return fixed, applied, remaining
    except Exception:
        return text, [], []
