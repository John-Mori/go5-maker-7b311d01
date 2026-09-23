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
try:
    import tone_rewrite as _tone_rewrite       # ゲートD-2(案F・LLM1往復の書き直し)
except Exception:
    _tone_rewrite = None                       # 読めなくてもD以降は動く(fail-open)
# ★同形異字(ホモグリフ)の正本= scripts/discord/homoglyph.py。表を2か所に持たない(ORG-11)。
try:
    _DISCORD_DIR = os.path.join(ROOT, "scripts", "discord")
    if _DISCORD_DIR not in sys.path:
        sys.path.insert(0, _DISCORD_DIR)
    import homoglyph as _homoglyph
except Exception:
    _homoglyph = None                         # 読めなくてもゲートは動く(fail-open)

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


def canon_persona(persona):
    """話し手の名前が同形異字で化けていたら正名へ寄せる。→ (使う名前, 化けていた元 or "")。

    ★なぜ要るか(2026-09-06 実測・イージス研究室):
      naming_audit.jsonl に `persona="ККール"`(キリル К U+041A ×2)の判定行が **9行**
      在った(2026-09-04T09:55:36・dept=hr-room・source=dispatch)。呼称ルール.json の
      `speaker_target_overrides` は話し手名の**文字列一致**で引くので、化けた名前では
      ククールの例外が1つも当たらない= **別人として裁かれた**便が台帳に残る。
      同じ便の1秒後(09:55:37)に `homoglyph_body_fix` が出ている= 既存の修復は
      **本文だけ**を直し、しかも**このゲートより後**に走る。話し手名は誰も直していなかった。
    ★寄せるのは `homoglyph.canonical_name` が**一意に決めた時だけ**。候補が2人以上なら
      化けたまま通す(取り違えるくらいなら直さない)。
    ★どこで転んでも元の名前を返す(fail-open)= 名前の正規化で便を止めない。
    """
    p = str(persona or "").strip()
    if not p or _homoglyph is None:
        return p, ""
    try:
        canon, _why = _homoglyph.canonical_name(p)
        if canon and canon != p:
            return canon, p
    except Exception:
        pass
    return p, ""


def apply_naming_gate_only(dept, persona, text, source="dispatch", msg_id="",
                           vocative_only=True):
    """★投函経路(dispatch)用= **ゲートC(呼称)だけ**を当てる。返り値 (text, summary)。

    経路③ 投函 dispatch.py → キュー(inbox.db)/相手部屋への表投稿 は、経路①(常駐)にも
    経路②(ミラー)にも通らない= **どのゲートも通っていなかった**(2026-09-02 実測)。
    ここが3本目の合流点なので、同じ純関数(naming_corrections)を同じ台帳
    (naming_audit.jsonl・source="dispatch")へ当てる=記録先を2つ持たない(§4)。

    ★2026-09-03 封筒エコー(E-2)だけ**記録のみ**で足した(切らない)。理由は本体の注記。
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
    # ★話し手名の同形異字を**規則を引く前に**正名へ寄せる(理由= canon_persona の説明)。
    #   化けていた事実は消さない= 台帳へ persona_raw / persona_homoglyph で残す。
    persona, persona_raw = canon_persona(persona)
    if persona_raw:
        summary["persona_homoglyph"] = persona_raw
    # ★★2026-09-03(イージス研究室)**封筒エコーを投函経路でも見る。ただし記録だけ・切らない。**
    #   研究室HQから所有権を引き継いだ時の実測(このファイルの呼び出し元を全部数えた):
    #     経路① 常駐 dept_daemon.strip_meta       = **生きている**(E-2配線あり)
    #     経路② ミラー output_gates.apply_gates   = **呼び出し元が1つも無い**。
    #        唯一の非テスト呼び元 scripts/hooks/mirror_to_discord.py は 2026-08-15 に退役し
    #        (absence_watchdog.py:680)、.claude/settings.json の hooks にも載っていない=
    #        あちらへ入れたE-2は**本番では一度も発火しない**。入っていることを根拠にしない。
    #     経路③ 投函 dispatch.py → ここ            = **E-2が無かった**= 生きた穴はこちらだった。
    #   便の封筒エコーは表より高くつく= 実在しないChamiの便が**相手の部屋の文脈へ**入る
    #   (事故の実物 msg_id 1544753080036790319 は GET が404=最初から存在しない)。
    #   ★それでも今は切らない。理由はこの関数の設計(便は書式そのものが情報・誤爆が高くつく)と、
    #     「発火しない安全網は検証されない」の裏返しで**まず本番で1回鳴らす**のが順序だから。
    #     event=envelope_echo_warn が実物で出たら、その実物を見て切りへ上げる(§4.55)。
    try:
        if _meta_strip is not None:
            _cut, _eh = _meta_strip.strip_envelope_echo(s)
            if _eh:
                summary["envelope_echo_warn"] = len(_eh)
                _append(META_AUDIT, [{
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "dept": dept,
                    "event": "envelope_echo_warn", "source": source,
                    "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                    "markers": [h.get("marker") for h in _eh],
                    "would_cut_chars": len(s) - len(str(_cut or "")),
                    "cut": False, "before": s[:200]}])
    except Exception:
        pass            # 記録で転んでも便は止めない(fail-open)
    # ★2026-09-23(プラットフォームSE)自己申告メモ(DEF-platform-se-8f7599cc3c)も投函経路で**見る**。
    #   常駐(経路①)とミラー(経路②)は空にして止めるが、投函経路のこの関数は呼称ゲートCだけでE系は
    #   切らない設計(便は書式が情報)。ここでは**記録だけ**残し、投函便でこの形が出るかを実測する。
    #   event=selfdeclared_memo_warn / source=dispatch が実物で出たら、その実物を見て切りへ上げる。
    try:
        if _meta_strip is not None and hasattr(_meta_strip, "strip_selfdeclared_memo"):
            _mcut, _mh = _meta_strip.strip_selfdeclared_memo(s)
            if _mh:
                summary["selfdeclared_memo_warn"] = len(_mh)
                _append(META_AUDIT, [{
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "dept": dept,
                    "event": "selfdeclared_memo_warn", "source": source,
                    "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                    "markers": [h.get("marker") for h in _mh],
                    "line": _mh[0].get("line") or "",
                    "cut": False, "before": s[:200]}])
    except Exception:
        pass            # 記録で転んでも便は止めない(fail-open)
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
                         # ★skip= なぜ直さなかったか(2026-09-04・常駐経路と同じ列)
                         "skip": v.get("skip", ""),
                         # ★voc= 咎めた出現のうち**呼びかけ位置**(行頭+読点)の件数
                         #   (2026-09-06)。naming_gate._attach_hits が前から計算して
                         #   verdict に載せていたのに、書き手2箇所がどちらも写して
                         #   いなかった= 台帳858行に voc キーが**0件**。
                         #   その結果 naming_drift_check._all_mention()
                         #   (judgeable>=5 かつ voc==0 で地の文だけの組を落とす枝)が
                         #   作られてから一度も発火していない。共通規律§3
                         #   「機械が自動で載せられない値を機構の前提にするな」の実例。
                         #   ★near からは後付けできない= near は改行を潰して保存する
                         #     (naming_gate.py L423 `.replace("\n"," ")`)ので行頭が
                         #     消え、既存475行では _is_vocative が常に偽になる。
                         "voc": v.get("voc", 0),
                         "msg_id": str(msg_id or ""), "excerpt": excerpt_before})
        # ★化けた名前で来たことを**必ず1行残す**。判定が0件の便でも残す=
        #   「寄せたから何も無かった」に見せない(直した側だけを数えると穴が消える)。
        #   event が "naming"/"naming_fix" ではないので、ドリフト判定の件数には入らない。
        if persona_raw:
            rows.append({"ts": ts, "dept": dept, "event": "persona_homoglyph",
                         "persona": persona, "persona_raw": persona_raw,
                         "source": source, "msg_id": str(msg_id or ""),
                         "excerpt": excerpt_before})
            for r in rows:
                r.setdefault("persona_raw", persona_raw)
        _append(NAMING_AUDIT, rows)
        summary["naming_fix"] = len(applied)
        summary["naming_warn"] = len(remaining)
        return (res.get("fixed", s) or s), summary
    except Exception:
        return text, summary


def apply_tone_gate_only(dept, persona, text, source="dispatch", msg_id="",
                         fix=False, body_key="", write=True):
    """★投函経路(dispatch)用= **ゲートD(口調)だけ**を、既定で**警告のみ**当てる。

    なぜ足したか(2026-09-16 AD研究室 msg 1549614905580068977 の実証):
      オタコンの「俺→僕」は3層とも揃っていて(otacon.md:16 / 口調ルール.json:250 /
      tone_gate.py:24)、機構も同じ日に2回発火している。それでも 10:22 の実便
      `DISPATCH-research-room-1789521766461` は監査にヒット0行だった=
      **直せなかったのではない。呼ばれていなかった。**投函経路はゲートDを通っていない。
      → 原典を何行足しても、ゲートを呼ばない口から出れば素通しだ(層(c)の実証)。

    ★既定 fix=False= **本文を書き換えない。**便は表とちがって書式そのものが情報で、
      封筒には**他部屋の本文がそのまま引用**される。そこで一人称を機械置換すると
      引用が化ける= 証拠を壊す方が事故として重い(apply_naming_gate_only と同じ理由)。
      まず**数えられる状態**にする。実物が溜まってから切りへ上げるかを決める(§4.55)。
    ★msg_id= dispatch は enqueue 前に合成id(`DISPATCH-<部門>-<ミリ秒>`)を持っている=
      ここで渡せば台帳の行が**後から実便へ突き合わせられる**(監査の13.9%が照合不能
      だった件の裏返し。記録が在ることと検証できることは別だ)。
    ★write=False= **数えるが台帳へ書かない。**--dry-run 用だ= 出ない便の行を台帳へ残すと
      「いつ送られたか」が混ざって分布が読めなくなる(tone_structure_report の live/backfill を
      分けている理由と同じ)。確認したい人が数字を見られる状態は保つ。
    ★何が起きても例外を外へ出さない(fail-open)= 便を止めない。
    """
    summary = {"tone_fix": 0, "tone_warn": 0}
    s = str(text or "")
    if not s.strip() or not str(persona or "").strip():
        return text, summary
    persona, persona_raw = canon_persona(persona)
    try:
        rules = _rules("tone")
        if _tone_gate is None or not rules:
            return text, summary
        res = _tone_gate.tone_corrections(persona, dept, s, rules) or {}
        applied = res.get("applied") or []
        remaining = res.get("remaining") or []
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        excerpt_before = s[:200]
        rows = []
        for a in applied:
            rows.append({"ts": ts, "dept": dept,
                         "event": "tone_fix" if fix else "tone_fix_skipped",
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
        # ★body_key= 同報(1本の本文を N部門へ)で**同じ違反が部門数ぶん並ぶ**のを、
        #   読む側が潰せるようにする鍵(本文のsha1先頭12桁)。行は便ごとに残す=
        #   便ごとに msg_id が違い、突き合わせに要るから。数える時は body_key で畳め。
        for r in rows:
            if body_key:
                r.setdefault("body_sha1", str(body_key))
            if persona_raw:
                r.setdefault("persona_raw", persona_raw)
        if write:
            _append(TONE_AUDIT, rows)
        summary["tone_fix"] = len(applied)
        summary["tone_warn"] = len(remaining)
        return ((res.get("fixed", s) or s) if fix else text), summary
    except Exception:
        return text, summary


def apply_gates(dept, persona, text, source="mirror", msg_id="", fix=None, ask=None):
    """本文にゲートC(呼称)→D(口調)→D-2(書き直し)を当て、監査へ残す。既定は**警告のみ**。

    返り値: (text, summary)
      summary = {"naming_fix":n, "naming_warn":n, "tone_fix":n, "tone_warn":n}
      ★警告のみモードでは naming_fix/tone_fix は「直せたはずの件数」= 実際には直していない。
        監査の event も `*_fix_skipped` で分けて残す(後から格上げの是非を数字で決められる)。
    ★何が起きても例外を外へ出さない。壊れたら元の text をそのまま返す。
    ★`ask`= ゲートD-2が外へ出す手(LLM)を差し替える口。must-fail検査が**判定と分岐は本物のまま**
      経路を通すために使う(§3「ソース文字列一致で固めない」)。本番では None= ask_cascade。
    """
    do_fix = _fix_enabled() if fix is None else bool(fix)
    tone_remaining, tone_rules = [], None      # ★ゲートD-2へ渡す(D側が転んでもNameErrorにしない)
    summary = {"naming_fix": 0, "naming_warn": 0, "tone_fix": 0, "tone_warn": 0,
               "tone_rewrite": 0,
               "meta_strip": 0, "meta_emptied": False, "narration_leak": 0,
               "envelope_echo": 0, "orphan_fence": 0,
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
    # ★ゲートE-2(封筒エコー切り落とし)= 2026-09-03 研究室HQの止血。常駐(経路①)と同じ純関数。
    #   実物= 軍議 msg 1544752527507984384 / 1544752530511106295。検査= test_envelope_echo.py。
    try:
        if _meta_strip is not None:
            cut, ehits = _meta_strip.strip_envelope_echo(s)
            if ehits:
                summary["envelope_echo"] = len(ehits)
                summary["meta_emptied"] = not str(cut or "").strip()
                _append(META_AUDIT, [{
                    "ts": ts, "dept": dept, "event": "envelope_echo", "source": source,
                    "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                    "markers": [h.get("marker") for h in ehits],
                    "cut_chars": len(s) - len(str(cut or "")),
                    "emptied": summary["meta_emptied"], "before": excerpt_before}])
                if summary["meta_emptied"]:
                    return "", summary
                s = cut
    except Exception:
        pass            # 切り落としで転んでも以降のゲートは当てる

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

    # --- ゲートE-3(孤立コードフェンス切り)= 2026-09-17 プラットフォームSE -----
    #   実物= imagegen-fusoh-v0/カスミ msg 1549651824397778945。常駐(経路①)と同じ純関数。
    #   開始の無い末尾 ``` を落とす。OUT口は常駐とミラーの2つ=同時に塞ぐ(C-064)。
    try:
        if _meta_strip is not None:
            fcut, fhits = _meta_strip.strip_orphan_fence(s)
            if fhits:
                summary["orphan_fence"] = len(fhits)
                _append(META_AUDIT, [{
                    "ts": ts, "dept": dept, "event": "orphan_fence", "source": source,
                    "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                    "stripped": [h.get("line") for h in fhits],
                    "before": excerpt_before}])
                s = fcut
    except Exception:
        pass            # 切り落としで転んでも以降のゲートは当てる

    # --- ゲートE-4(名乗り前の英語作業前置き切り)= 2026-09-21 イージス研究室 -----
    #   発注= 改善提案部門(トトリ) msg 1551430845766836227 / 出所= Chami msg 1551429691251101828
    #   実物= トトリのPDCA報告便 msg 1551390481165058160 の1行目が英語の作業ノート。
    #   ★detect_narration_leak では当たらない(3条件ANDの③=声の痕跡で必ず素通しする)。
    #     見るのは語彙ではなく**位置**= 名乗りより前に英語の作業ノートが在るか。
    #   OUT口は常駐とミラーの2つ=同時に塞ぐ(C-064)。
    try:
        if _meta_strip is not None:
            pcut, phits = _meta_strip.strip_preamble_leak(s)
            if phits:
                summary["preamble_leak"] = len(phits)
                _append(META_AUDIT, [{
                    "ts": ts, "dept": dept, "event": "preamble_leak", "source": source,
                    "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                    "stripped": [h.get("line") for h in phits],
                    "before": excerpt_before}])
                s = pcut
            else:
                # 本文がまるごと前置き= 切ると沈黙になるので**切らない**。台帳に残すだけ
                #   (この経路に再生成の手が無い。常駐側だけが作り直しへ格上げする)。
                _only = _meta_strip.detect_preamble_only(s)
                if _only:
                    summary["preamble_only"] = 1
                    _append(META_AUDIT, [{
                        "ts": ts, "dept": dept, "event": "preamble_only", "source": source,
                        "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                        "line": _only.get("line") or "",
                        "warned": False, "before": excerpt_before}])
    except Exception:
        pass            # 切り落としで転んでも以降のゲートは当てる

    # --- ゲートE-5(自己申告メモの丸ごと抑止)= 2026-09-23 プラットフォームSE ---
    #   炎上 DEF-platform-se-8f7599cc3c / C-038。常駐(経路①)と**同じ純関数**(C-064)。
    #   実物= send_audit msg 1551880577232277526「(これは作業メモで、部屋への投稿ではありません…)」。
    #   本文自身が「投稿ではない」と宣言していたら本文まるごと空にして送らない(便は書式が情報だが、
    #   これは書式ではなく**本人が投稿ではないと言っている**ので、envelope_echo と同じく空を返す)。
    try:
        if _meta_strip is not None:
            mcut, mhits = _meta_strip.strip_selfdeclared_memo(s)
            if mhits:
                summary["selfdeclared_memo"] = len(mhits)
                summary["meta_emptied"] = True
                _append(META_AUDIT, [{
                    "ts": ts, "dept": dept, "event": "selfdeclared_memo", "source": source,
                    "persona": str(persona or ""), "msg_id": str(msg_id or ""),
                    "markers": [h.get("marker") for h in mhits],
                    "stripped": [h.get("line") for h in mhits],
                    "emptied": True, "before": excerpt_before}])
                return "", summary
    except Exception:
        pass            # 抑止で転んでも以降のゲートは当てる

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
            tone_remaining, tone_rules = remaining, rules      # ★D-2へ引き継ぐ
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

    # --- ゲートD-2(案F= 機械で直せなかった崩れをLLM1往復で書き直す)-------------
    # ★2026-09-11(Chami「寝る前Go」msg 1547688457051177000)。D-2は2026-08-16に**常駐にだけ**
    #   置かれた。外へ撃つ口は3つ(C-064)= dept_daemon:4794 / persona_send:527 / ここ。
    #   ゲートDが `remaining` へ落とした指紋語尾・方言・敬体を、この経路も捨てていた。
    # ★**do_fix に従う**= この経路の既定は「警告のみ」(GO5_MIRROR_GATE_FIX=1 で格上げ)。
    #   Dが本文を直さない設定でD-2だけが本文を書き換えたら建て付けが割れるし、
    #   直しもしないのにLLMの往復だけ毎便焼く(Gemini無料枠は20/日/モデル)。
    #   ★台帳(event=tone_rewrite)は書く= 回った/弾かれたを後から数えられるようにする。
    # ★fail-open: 例外・鍵なし・写像に人格が無い= 直前の本文 `s` をそのまま持ち越す。
    try:
        if _tone_rewrite is not None and do_fix and tone_remaining and tone_rules \
                and str(os.environ.get("GO5_TONE_REWRITE", "1")).strip().lower() \
                not in ("0", "off", "false"):
            _before = s
            _rw = _tone_rewrite.rewrite_once(persona, dept, s, tone_remaining, tone_rules,
                                             ask=ask, timeout=20) or {}
            if _rw.get("attempted"):
                _append(TONE_AUDIT, [{
                    "ts": ts, "dept": dept, "event": "tone_rewrite",
                    "persona": str(persona or ""), "source": source,
                    "ok": bool(_rw.get("ok")),
                    "targets": _rw.get("targets") or [],
                    "after": _rw.get("after") or [],
                    "why": _rw.get("why") or "",
                    "elapsed_ms": _rw.get("elapsed_ms", 0),
                    "engine": _rw.get("engine") or "",
                    "msg_id": str(msg_id or ""),
                    "excerpt": str(_before or "")[:200],       # ★書き直し**前**
                    "excerpt_after": str(_rw.get("text") or "")[:200],
                }])
                summary["tone_rewrite"] = 1 if _rw.get("ok") else 0
                if _rw.get("ok"):
                    s = _rw.get("text") or s
    except Exception:
        pass            # この段が送信を殺さない(沈黙が最悪の事故)

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
