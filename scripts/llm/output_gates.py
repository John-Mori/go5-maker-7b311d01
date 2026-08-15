#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""出力ゲート(呼称C・口調D)を **常駐以外の送信経路** にも相乗りさせる薄い配線。

なぜ要るか(2026-08-15 人事部門→基盤への依頼・設計_口調ドリフト恒久策_2026-08-14.md 案B):
  ゲートC/Dは `dept_daemon.py` の中にだけ実装されている。だが Discord へ出る道は2本ある。

    経路① 常駐デーモン   : dept_daemon.generate() → audit_naming/audit_tone → persona_send
    経路② セッションのミラー: mirror_to_discord.py → persona_render → persona_send
                              ★この経路には**ゲートが1つも無い**(実測 grep 0件)

  研究室HQ(シャビ・アロンソ)の発言は経路②で出る。だから characterfile をどれだけ磨いても、
  口調ルール.json に指紋(Claude標準体の署名句)を足しても、**機械が一度も見ていなかった**。
  Chami「アロンソの口調がClaude標準体」はこの穴の症状だ。

設計(依頼の受け入れ条件をそのまま実装する):
  ① 判定材料は 呼称ルール.json / 口調ルール.json の2本のまま(ORG-11)。ここに規則を書かない。
  ② 置換は `naming_corrections` / `tone_corrections`(常駐が使っているのと**同じ純関数**)に任せる。
     置換先が一意に決まらない時に素通しする安全弁も、そちらが既に持っている。
  ③ fail-open 厳守。import 失敗・ルール未ロード・例外の**どれが起きても元の本文を返す**。
     ゲートが送信を殺すことは絶対に無い(沈黙が最悪の事故・AegisConciel)。
  ④ 記録先を2つ持たない(§4)= 常駐と**同じ** naming_audit.jsonl / tone_audit.jsonl へ書く。
     どの経路から来たかは `"source"` で分ける(常駐の行にはこのキーが無い=既存の行は不変)。

★このモジュールは dept_daemon から呼ばれない。経路①の挙動は1バイトも変わらない。
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
HQ = os.path.join(os.path.dirname(ROOT), "00_AI-HQ")

NAMING_AUDIT = os.path.join(LOCAL, "llm", "naming_audit.jsonl")
TONE_AUDIT = os.path.join(LOCAL, "llm", "tone_audit.jsonl")
# ★ゲートE(内部メタ剥ぎ)の監査。常駐側(dept_daemon.META_AUDIT)と**同じ1本**へ書く
#   (§4「記録先を2つ持たない」)。どちらの経路かは "source" で分ける。
META_AUDIT = os.path.join(LOCAL, "llm", "meta_strip_audit.jsonl")
NAMING_RULES_PATH = os.path.join(HQ, "departments", "hr", "personas", "呼称ルール.json")
TONE_RULES_PATH = os.path.join(HQ, "departments", "hr", "personas", "口調ルール.json")

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import naming_gate as _naming_gate
except Exception:
    _naming_gate = None
try:
    import tone_gate as _tone_gate
except Exception:
    _tone_gate = None
try:
    import meta_strip as _meta_strip
except Exception:
    _meta_strip = None

# ルールは **mtime が変わったら読み直す**(常駐の _tone_rules と同じ思想)。
#   人事部門が写像へ1行足した時に、ミラー側だけ古い規則で動くのを防ぐ。
_CACHE = {}


def _rules(kind):
    if kind == "naming":
        mod, path = _naming_gate, NAMING_RULES_PATH
        loader = "load_naming_rules"
    else:
        mod, path = _tone_gate, TONE_RULES_PATH
        loader = "load_tone_rules"
    if mod is None:
        return None
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = None
    c = _CACHE.get(kind)
    if not c or c.get("mtime") != mt:
        c = {"mtime": mt, "rules": None}
        try:
            c["rules"] = getattr(mod, loader)(path)
        except Exception:
            c["rules"] = None
        _CACHE[kind] = c
    return c["rules"]


def _append(path, rows):
    try:
        if not rows:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        pass            # 監査の失敗で送信を巻き添えにしない


# ★既定は「警告のみ」= 本文を書き換えない(2026-08-15 実測で決めた。下の数字が根拠)。
#
#   研究室HQ(シャビ・アロンソ)の実便 1,407件へこの経路を通して測った結果:
#     本文が書き換わる便 = **1件**  / 警告だけ出る便 = 9件
#   そしてその1件は**誤りだった**:
#     前) 「三笘=俺固定・五月=俺僕禁止と原典に明記なのに未登録」
#     後) 「三笘=俺固定・五月=俺俺禁止と原典に明記なのに未登録」
#   研究室HQは**口調ルールそのものを本文で論じる部屋**なので、地の文に出る「僕」は
#   他人格の一人称ではなく**引用**だ。呼称ゲートCが人事部門の部屋で同じ壊れ方をして
#   NO_AUTOFIX_DEPTS を持つに至ったのと、完全に同じ形(実物 msg 1533593872004022292)。
#
#   → 実測での真陽性ゼロ・偽陽性1。**この経路で本文を書き換える理由が数字に無い**。
#     ゲートC/Dが辿った道(警告のみ→実測→格上げ)をここでも踏む。
#     格上げしたくなったら `GO5_MIRROR_GATE_FIX=1` を立てる(コード変更不要)。
#   ★指紋(Claude標準体の署名10句)は**そもそも警告のみ**なので、この既定でも案Aは効く。
def _fix_enabled():
    return os.environ.get("GO5_MIRROR_GATE_FIX") == "1"


def apply_gates(dept, persona, text, source="mirror", msg_id="", fix=None):
    """本文にゲートC(呼称)→D(口調)を当て、監査へ残す。既定は**警告のみ**(本文を変えない)。

    返り値: (text, summary)
      summary = {"naming_fix":n, "naming_warn":n, "tone_fix":n, "tone_warn":n}
      ★警告のみモードでは naming_fix/tone_fix は「直せたはずの件数」= 実際には直していない。
        監査の event も `*_fix_skipped` で分けて残す(後から格上げの是非を数字で決められる)。
    ★何が起きても例外を外へ出さない。壊れたら元の text をそのまま返す。
    """
    do_fix = _fix_enabled() if fix is None else bool(fix)
    summary = {"naming_fix": 0, "naming_warn": 0, "tone_fix": 0, "tone_warn": 0,
               "meta_strip": 0, "meta_emptied": False}
    s = str(text or "")
    if not s.strip() or not str(persona or "").strip():
        return text, summary
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")       # JST(この端末はJSTで動く)
    excerpt_before = s[:200]

    # --- ゲートE(内部の手続きメタ剥ぎ) ----------------------------------
    # ★2026-08-15 Chami指示③。常駐経路(dept_daemon)と**同じ純関数**を当てる。
    #   ここだけは「警告のみ」にしない= 実測(jsonl 198本・本文8,890件)で
    #   剥ぎが起きたのは**壊れた実物1件のみ・誤爆0**。判定材料は本文だけで話者に依存しない。
    # ★全部メタで空になったら **空を返す**(下の「最後の砦」の対象外にする)=
    #   呼び出し側(mirror)が「送らない」を選べるようにする。中身ゼロの便を出す方が事故だ。
    try:
        if _meta_strip is not None:
            stripped, hits = _meta_strip.strip_meta_tail(s)
            if hits:
                summary["meta_strip"] = len(hits)
                summary["meta_emptied"] = not str(stripped or "").strip()
                _append(META_AUDIT, [{
                    "ts": ts, "dept": dept, "event": "meta_strip", "source": source,
                    "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                    "markers": [h.get("marker") for h in hits],
                    "stripped": [h.get("line") for h in hits],
                    "emptied": summary["meta_emptied"], "before": excerpt_before}])
                if summary["meta_emptied"]:
                    return "", summary
                s = stripped
    except Exception:
        pass            # 剥ぎで転んでも以降のゲートは当てる(本文は直前の状態のまま)

    # --- ゲートC(呼称) --------------------------------------------------
    try:
        rules = _rules("naming")
        if _naming_gate is not None and rules:
            res = _naming_gate.naming_corrections(persona, dept, s, rules) or {}
            applied = res.get("applied") or []
            remaining = res.get("remaining") or []
            rows = []
            for a in applied:
                rows.append({"ts": ts, "dept": dept,
                             "event": "naming_fix" if do_fix else "naming_fix_skipped",
                             "persona": str(persona or ""), "source": source,
                             "target": a.get("target", ""), "to": a.get("to", ""),
                             "count": a.get("count", 0), "reason": a.get("reason", ""),
                             "msg_id": str(msg_id or ""), "excerpt": excerpt_before})
            for v in remaining:
                rows.append({"ts": ts, "dept": dept, "event": "naming",
                             "persona": str(persona or ""), "source": source,
                             "target": v.get("target", ""), "found": v.get("found", ""),
                             "expected": v.get("expected", []), "reason": v.get("reason", ""),
                             "msg_id": str(msg_id or ""), "excerpt": excerpt_before})
            _append(NAMING_AUDIT, rows)
            summary["naming_fix"] = len(applied)
            summary["naming_warn"] = len(remaining)
            if do_fix:
                s = res.get("fixed", s) or s
    except Exception:
        pass            # 呼称で転んでも口調は当てる。本文は直前の状態を持ち越す

    # --- ゲートD(口調) --------------------------------------------------
    try:
        rules = _rules("tone")
        if _tone_gate is not None and rules:
            res = _tone_gate.tone_corrections(persona, dept, s, rules) or {}
            applied = res.get("applied") or []
            remaining = res.get("remaining") or []
            rows = []
            for a in applied:
                rows.append({"ts": ts, "dept": dept,
                             "event": "tone_fix" if do_fix else "tone_fix_skipped",
                             "persona": str(persona or ""), "source": source,
                             "marker": a.get("marker", ""), "to": a.get("to", ""),
                             "count": a.get("count", 0), "reason": a.get("reason", ""),
                             "msg_id": str(msg_id or ""), "excerpt": excerpt_before})
            for v in remaining:
                rows.append({"ts": ts, "dept": dept, "event": "tone",
                             "persona": str(persona or ""), "source": source,
                             "marker": v.get("marker", ""),
                             "own_first_person": v.get("own_first_person", []),
                             "index": v.get("index", -1), "reason": v.get("reason", ""),
                             "msg_id": str(msg_id or ""), "excerpt": excerpt_before})
            _append(TONE_AUDIT, rows)
            summary["tone_fix"] = len(applied)
            summary["tone_warn"] = len(remaining)
            if do_fix:
                s = res.get("fixed", s) or s
    except Exception:
        pass

    # ★最後の砦= 本文が空になったら**元の本文で送る**(沈黙ゼロ・受け入れ条件②)。
    if not str(s or "").strip():
        return text, summary
    return s, summary
