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
try:
    import kana_choice_gate as _kana_choice   # ゲートH(かな括弧の選択肢ラベル)
except Exception:
    _kana_choice = None                       # import 失敗でもミラーは動く(fail-open)
try:
    import dept_ref_gate as _dept_ref         # ゲートI(部門を人格名で呼ぶ崩れ)
except Exception:
    _dept_ref = None
try:
    import struct_drift_gate as _struct_drift  # ゲートJ(Claude既定のレポート骨格)
except Exception:
    _struct_drift = None

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


def apply_naming_gate_only(dept, persona, text, source="dispatch", msg_id="",
                           vocative_only=True):
    """★投函経路(dispatch)用= **ゲートC(呼称)だけ**を当てる。返り値 (text, summary)。

    経路③ 投函 dispatch.py → キュー(inbox.db)/相手部屋への表投稿 は、経路①(常駐)にも
    経路②(ミラー)にも通らない= **どのゲートも通っていなかった**(2026-09-02 実測)。
    ここが3本目の合流点なので、同じ純関数(naming_corrections)を同じ台帳
    (naming_audit.jsonl・source="dispatch")へ当てる=記録先を2つ持たない(§4)。

    ★当てるのは呼称だけ。口調D・メタ剥ぎEは当てない=
      便は表とちがって**書式そのものが情報**(表・引用・設定値)で、書き換えの誤爆が高くつく。
      必要になったらここへ1本足せる(合流点は既にこの1箇所に寄せてある)。
    ★vocative_only=True 既定= 呼びかけ位置だけ直す。根拠は naming_corrections の docstring
      (ククール実便8本の実測: 地の文まで直すと6本書き換わり大半が化ける / 呼びかけ位置だけなら
       書き換え1本=事故便そのもの・誤爆0)。
    ★何が起きても例外を外へ出さない(fail-open)= 便を止めない。
    """
    summary = {"naming_fix": 0, "naming_warn": 0}
    s = str(text or "")
    if not s.strip() or not str(persona or "").strip():
        return text, summary
    try:
        rules = _rules("naming")
        if _naming_gate is None or not rules:
            return text, summary
        res = _naming_gate.naming_corrections(persona, dept, s, rules,
                                              vocative_only=vocative_only) or {}
        applied = res.get("applied") or []
        remaining = res.get("remaining") or []
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        excerpt_before = s[:200]
        rows = []
        for a in applied:
            rows.append({"ts": ts, "dept": dept, "event": "naming_fix",
                         "persona": str(persona or ""), "source": source,
                         "target": a.get("target", ""), "to": a.get("to", ""),
                         "count": a.get("count", 0), "reason": a.get("reason", ""),
                         "msg_id": str(msg_id or ""), "excerpt": excerpt_before})
        for v in remaining:
            rows.append({"ts": ts, "dept": dept, "event": "naming",
                         "persona": str(persona or ""), "source": source,
                         "target": v.get("target", ""), "found": v.get("found", ""),
                         "expected": v.get("expected", []), "reason": v.get("reason", ""),
                         "near": v.get("near", ""), "hits": v.get("hits", 0),
                         "msg_id": str(msg_id or ""), "excerpt": excerpt_before})
        _append(NAMING_AUDIT, rows)
        summary["naming_fix"] = len(applied)
        summary["naming_warn"] = len(remaining)
        return (res.get("fixed", s) or s), summary
    except Exception:
        return text, summary


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
               "meta_strip": 0, "meta_emptied": False, "narration_leak": 0,
               "kana_choice_fix": 0, "kana_choice_warn": 0,
               "dept_ref_fix": 0, "dept_ref_warn": 0}
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

    # --- 実況漏れ(名乗りも声も無い生ログ)= **警告のみ** ------------------
    # ★2026-09-01 イージス研究室。常駐(経路①)と**同じ検知器**(meta_strip.detect_narration_leak)。
    # ★ここでは突き返さない= この経路に**再生成の手が無い**(セッションは既に喋り終えている)。
    #   突き返し=送らないことになり、沈黙が最悪の事故という原則に反する。だから台帳に残すだけ。
    #   常駐側だけが「1回だけ再生成」へ格上げしている(手が有るから)。
    # ★格上げの是非は、この台帳(event=narration_leak / source=mirror)の数字で後から決める。
    try:
        if _meta_strip is not None:
            _leak = _meta_strip.detect_narration_leak(s)
            if _leak:
                summary["narration_leak"] = 1
                _append(META_AUDIT, [{
                    "ts": ts, "dept": dept, "event": "narration_leak", "source": source,
                    "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                    "machine": _leak.get("machine") or [],
                    "warned": False, "before": excerpt_before}])
    except Exception:
        pass            # 検知で転んでも本文は素通し

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
                # ★near/hits= 当たった**現場**の抜粋と出現数(2026-09-02)。excerpt は便の頭
                #   (text[:200])なので、当たった場所が200字より後だと台帳に証拠が残らず、
                #   後から use/mention を読み分けられなかった(実測= 5ペア41行中22行)。
                rows.append({"ts": ts, "dept": dept, "event": "naming",
                             "persona": str(persona or ""), "source": source,
                             "target": v.get("target", ""), "found": v.get("found", ""),
                             "expected": v.get("expected", []), "reason": v.get("reason", ""),
                             "near": v.get("near", ""), "hits": v.get("hits", 0),
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

    # --- ゲートH(かな括弧の選択肢ラベル)= **話者非依存** ---------------------
    # ★2026-09-02 HQ-0232。Chamiが3回目の指摘(炎上+再発)を押した実物= (あ)(い) の選択肢。
    #   ★今回のカスミは**この経路(対話セッション=ミラー)**で出た。だから経路①だけでは塞がらない。
    #   ★C/Dと違い写像(口調ルール.json)を見ない= 話者別の器に入れると人格を足すたび穴が開く。
    #   ★ここは**警告のみにしない**= 判定材料は本文だけで、置換は「(あ)→(1)」の1対1。
    #     ゲートDが警告のみへ倒れた理由(話者別の写像を引用文へ誤爆させた)はここには無い。
    #     引用行(>)とコードは正本 kana_choice_gate 側で除外済み=規律を論じる本文は壊れない。
    try:
        if _kana_choice is not None:
            s2, _kfix, _kwarn = _kana_choice.apply_and_audit(
                s, dept=dept, persona=str(persona or ""), source=source,
                msg_id=str(msg_id or ""), audit_path=TONE_AUDIT)
            summary["kana_choice_fix"] = len(_kfix)
            summary["kana_choice_warn"] = len(_kwarn)
            s = s2
    except Exception:
        pass            # 素通し=送信は殺さない

    # --- ゲートI(部門を人格名で呼ぶ崩れ)= **話者非依存** ---------------------
    # ★2026-09-02 DEF-kaizen-analyst-9d9bd45e55。人事部門の裁定(呼称ルール.json
    #   department_reference_rule)の基盤側。部門を指す位置に人格名が単独で置かれた時だけ直す。
    #   ★呼称ルール.json の表は speaker×target=**人格ペア**で、『部門』という target クラスが
    #     無い(=schema拡張が要る)。だからC(naming_gate)に足さず別口にした。naming_gate L82 が
    #     漢字名を構造的に外している所へ足すと、そちらの誤爆側に落ちる。
    #   ★写像は org_registry.yml の display_ja(正本・ORG-11)。ここに部門名を書かない。
    #   ★書き換えるのは実測で誤爆0だった rule(A_route)だけ。B_own は検知のみ=台帳に残す。
    try:
        if _dept_ref is not None:
            s2, _dhits = _dept_ref.apply(s)
            rows = []
            for h in _dhits:
                fixed = h.get("rule") in _dept_ref.FIX_RULES
                rows.append({"ts": ts, "dept": dept,
                             "event": "dept_ref_fix" if fixed else "dept_ref",
                             "persona": str(persona or ""), "source": source,
                             "target": h.get("dept", ""), "found": h.get("name", ""),
                             "expected": [h.get("display_ja", "")], "rule": h.get("rule", ""),
                             "near": h.get("line", "")[:200],
                             "msg_id": str(msg_id or ""), "excerpt": excerpt_before})
                if fixed:
                    summary["dept_ref_fix"] += 1
                else:
                    summary["dept_ref_warn"] += 1
            _append(NAMING_AUDIT, rows)
            s = s2
    except Exception:
        pass            # 素通し=送信は殺さない

    # --- ゲートJ(Claude既定のレポート骨格へ倒れた=構造ドリフト)= **検知のみ** ----
    # ★2026-09-02 657/f98d721938 の残り。人事部門ククールからの発注(この経路へ建てろ)。
    #   実物= DISPATCH-aegis-gl-1788315302529(アロンソ・敬語16+一人称ゼロ+■節見出し)。
    #   ★ゲートDが素通しするのは、崩れが**語尾域内**に収まるから。崩れているのは骨格だ。
    #   ★書き直さない= 骨格の置換に一意な写像が無い(Dが方言を直さないのと同じ理由)。
    #     代わりに台帳へ event="tone" で書く=session_relay の突き返しがそのまま拾い、
    #     次の封筒で生成側の目の前に出る。**新しい配線は1本も足していない。**
    #   ★一人称の写像は tone_gate._persona_entry を再利用(ORG-11)=ここに人格名を書かない。
    try:
        if _struct_drift is not None:
            _jhits = _struct_drift.audit(
                s, dept=dept, persona=str(persona or ""), rules=_rules("tone"),
                source=source, msg_id=str(msg_id or ""), audit_path=TONE_AUDIT)
            summary["struct_drift_warn"] = len(_jhits)
    except Exception:
        pass            # 素通し=送信は殺さない

    # ★最後の砦= 本文が空になったら**元の本文で送る**(沈黙ゼロ・受け入れ条件②)。
    if not str(s or "").strip():
        return text, summary
    return s, summary
