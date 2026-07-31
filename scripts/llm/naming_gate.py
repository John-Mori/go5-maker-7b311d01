#!/usr/bin/env python3
"""出力ゲート ルールC(呼称違反チェック)=純関数(LLM不要・テスト可)  2026-07-30.

設計書= 00_AI-HQ/設計_出力ゲート_呼称スラッグ非日本語スクリプト_2026-07-30.md §1-C/§2-C/§3/§6。
裁定= Chami承認(§6 裁定②)=**Cはまず「警告のみ」**。ここでは
  「違反候補(verdicts)を返すだけ」。送信抑止・本文改変・自動補完は**しない**
  (呼び出し側 dept_daemon.py が naming_audit.jsonl へ1行残すだけ)。

唯一の写像= 00_AI-HQ/departments/hr/personas/呼称ルール.json(散文INDEX.mdはパースしない)。
判定は (話者=persona名, 部屋=dept, 本文) の三つ組。ここでは話者×対象×本文で見る
(部屋依存の分岐は現時点のルールJSONに無いので dept は監査記録用に受け取るだけ)。

fail-open: 例外・ルール未ロードは**空リスト**を返す=ゲート自身が配送を殺さない
  (呼び出し側の fail-safe と二重の守り。既存 audit_hangul と同じ思想)。

★ORG-11(判定を2本持たない): 呼称判定はこの1本に集約する。
  dept_daemon.py も tests/test_naming_gate.py も**この関数**を引く。

取りこぼし(警告のみなので実害小・設計§6の許容):
  - `__男性キャラ__` グループ(target=一ノ瀬怜)は下の MALE_CHARACTERS 固定集合で近似する。
    集合外の男性話者は取りこぼす(False negative=鳴らないだけ・本文は壊さない)。
  - `otacon_address` / `chami_address` / `no_honorific_entities` は
    honorific_required_targets / speaker_target_overrides の外にある別表なので、
    今回のCゲート(実害の核=「アロンソさん」「デブライネさん/デブライネ」)では未使用。
    必要になったら同じ写像へ足す(2本に割れさせない)。
"""
import json
import re


def _norm(s):
    """話者/対象名の表記ゆれを吸収して突き合わせる。

    ★config は「ケヴィン・デ・ブライネ」、呼称ルール.json は「ケヴィン・デブライネ」と
      中黒(・)の有無が違う。中黒・空白を落として比較する
      (「ルカ・モドリッチ」等の他キーは両側同じ変換なので影響なし)。
    """
    return re.sub(r"[・\s]", "", str(s or "")).lower()


# ★「__男性キャラ__」グループの近似集合(取りこぼし前提・警告のみなので実害小)。
#   一ノ瀬怜への呼び捨て(『怜』)を許す男性話者。集合外は取りこぼす。
MALE_CHARACTERS = {
    _norm(x) for x in (
        "ソリッド・スネーク", "オタコン", "メタルギアMk.II",
        "ケヴィン・デブライネ", "ケヴィン・デ・ブライネ",
        "三笘薫", "ルカ・モドリッチ", "シャビ・アロンソ",
        "ククール", "一ノ瀬怜",
    )
}


def load_naming_rules(path):
    """呼称ルール.json を読み込む。読めなければ None(呼び出し側で fail-open)。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _speaker_matches(rule_speaker, persona):
    """override の speaker フィールドが今の話者に当たるか。

    - "*"            = 全話者(アロンソ本人の yobisute_ok 等)。
    - "__男性キャラ__" = MALE_CHARACTERS 集合(近似)。
    - それ以外       = 中黒無視の完全一致。
    """
    rs = str(rule_speaker or "")
    if rs == "*":
        return True
    if rs == "__男性キャラ__":
        return _norm(persona) in MALE_CHARACTERS
    return _norm(rs) == _norm(persona)


def _find_forms(text, forms):
    """text 中に forms(候補文字列)のいずれかが出た最初の位置と形を返す。無ければ None。"""
    s = str(text or "")
    best = None
    for f in forms:
        f = str(f or "")
        if not f:
            continue
        i = s.find(f)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, f)
    return best


# 裸の姓の直後に付きうる敬称/接尾(この並びが「実際に使われた形」を決める)。
#   長い順に試す(「ちゃん」→「ちゃ」等の食い違い防止)。
_HONORIFICS = ("さん", "さま", "ちゃん", "くん", "君", "様",
               "コーチ", "監督", "先輩", "氏")


def _appears_as_allowed(text, bare, allowed):
    """本文中の bare(裸の姓)の**各出現**が、許容形として使われているか。

    判定の芯= 各出現位置 i で「実際に使われた形」を組み立て、それが allowed に入るか。
      「実際に使われた形」=
        (a) i から始まる allowed 形のうち最長のもの(例=「アロンソコーチ」)。
            → 役職名など bare を含む長い許容形をそのまま拾える。
        (b) それが無ければ bare + 直後の敬称/接尾(例=「デブライネさん」)。
            → ★呼び捨てが正(allowed=["デブライネ"])の話者で「デブライネさん」は
              実際の形が「デブライネさん」となり allowed に無い=違反として拾える
              (allowed「デブライネ」が prefix でも許容にしない=INDEX特例の要)。
    全出現が allowed に入れば True。1つでも外れれば False(=違反候補)。
    """
    s = str(text or "")
    bare = str(bare or "")
    if not bare:
        return True
    allowed = [str(a or "") for a in (allowed or []) if str(a or "")]
    allowed_set = set(allowed)
    start = 0
    while True:
        i = s.find(bare, start)
        if i < 0:
            break
        # (a) i から始まる最長の allowed 形。
        #     ただしその allowed 形の**直後にさらに敬称が続く**なら、それは
        #     「その allowed 形そのもの」ではなく敬称付きの別形なので採らない
        #     (例=allowed「デブライネ」+「さん」→実際は「デブライネさん」)。
        best_allowed = ""
        for a in allowed:
            if not s.startswith(a, i) or len(a) <= len(best_allowed):
                continue
            after = s[i + len(a):]
            if any(after.startswith(h) for h in _HONORIFICS):
                continue        # 直後に敬称=この allowed 形では言い切っていない
            best_allowed = a
        if best_allowed:
            actual = best_allowed
        else:
            # (b) bare + 直後の敬称/接尾
            tail = s[i + len(bare):]
            suf = ""
            for h in _HONORIFICS:
                if tail.startswith(h):
                    suf = h
                    break
            actual = bare + suf
        if actual not in allowed_set:
            return False        # この出現は許容形ではない=違反候補
        start = i + len(bare)
    return True


def _target_key_forms(rules, target_key):
    """対象キーの bare_forms(裸の姓)を honorific_required_targets から引く。無ければ空。"""
    hrt = (rules or {}).get("honorific_required_targets") or {}
    ent = hrt.get(target_key)
    if not isinstance(ent, dict):
        ent = {}                # ★_note 等のメタ文字列キーを弾く
    forms = list(ent.get("bare_forms") or [])
    # bare_forms が無い対象(override 専用対象)はキー名そのものを候補にする
    if not forms:
        forms = [target_key]
    return forms


def naming_verdicts(persona, dept, text, rules):
    """呼称違反の候補一覧を返す(純関数)。

    引数:
      persona : 話者(解決済みの正式名。split_persona_blocks の resolve 結果 or 既定名)。
      dept    : 部屋(監査記録用。判定には現状未使用=ルールに部屋依存が無いため)。
      text    : ブロック本文。
      rules   : load_naming_rules() の戻り(dict) or None。

    返り値: list[dict]。各要素=
      {"target": 対象キー, "found": 本文に出た形, "expected": [許容形...], "reason": 理由}
    違反が無ければ空リスト。ルール未ロード/例外は空リスト(fail-open)。
    """
    out = []
    try:
        if not rules:
            return out
        s = str(text or "")
        if not s:
            return out

        hrt = rules.get("honorific_required_targets") or {}
        overrides = rules.get("speaker_target_overrides") or []

        # 対象キーの集合= honorific_required_targets のキー ∪ override が触る target。
        #   ★"_note"/"_meta" 等のメタキー(値が dict でない)は対象ではない=除外。
        target_keys = [k for k, v in hrt.items()
                       if isinstance(v, dict) and not str(k).startswith("_")]
        for ov in overrides:
            tk = ov.get("target")
            if tk and tk != "*" and tk not in target_keys:
                target_keys.append(tk)

        for tk in target_keys:
            forms = _target_key_forms(rules, tk)
            hit = _find_forms(s, forms)
            if hit is None:
                continue        # この対象は本文に出ていない

            # --- この話者×対象に効く override を最優先で探す(specific > "*") ---
            ov_specific = None
            ov_wild = None
            for ov in overrides:
                if ov.get("target") not in (tk, "*"):
                    continue
                if ov.get("target") == "*":
                    if _speaker_matches(ov.get("speaker"), persona):
                        ov_wild = ov
                    continue
                if _speaker_matches(ov.get("speaker"), persona):
                    # 話者が "__男性キャラ__" や実名で当たった特例
                    ov_specific = ov
            ov = ov_specific or ov_wild

            ent = hrt.get(tk) or {}
            forbidden = list(ent.get("forbidden") or [])

            # forbidden は override より前に(話者非依存で)チェック=常に違反
            fb = _find_forms(s, forbidden)
            if fb is not None:
                out.append({
                    "target": tk, "found": fb[1],
                    "expected": list(ent.get("allowed") or []),
                    "reason": "forbidden",
                })
                continue

            if ov is not None:
                # 話者本人がトップ等で「呼び捨てOK」→この対象は不問
                if ov.get("yobisute_ok"):
                    continue
                allowed = list(ov.get("allowed") or [])
                if not allowed:
                    continue    # 許容形の指定が無い override は判定材料に乏しい=不問
                if _appears_as_allowed(s, hit[1], allowed):
                    continue    # 許容形として出ている
                out.append({
                    "target": tk, "found": hit[1],
                    "expected": allowed,
                    "reason": "override_allowed",
                })
                continue

            # --- override 無し=既定(honorific_required_targets の allowed) ---
            allowed = list(ent.get("allowed") or [])
            if not allowed:
                # honorific_required に載っていない対象で override も無い=判定不能=不問
                continue
            if _appears_as_allowed(s, hit[1], allowed):
                continue        # さん付け等の許容形で出ている
            out.append({
                "target": tk, "found": hit[1],
                "expected": allowed,
                "reason": "honorific_required",
            })
        return out
    except Exception:
        return []               # fail-open=ゲートは配送を殺さない


# ==== 自動修正(高信頼のみ・2026-07-31 Chami「いいよ」でGo)========================
#   設計§2-C「高信頼だけ自動付与、他は警告＋fail-open」を実装する。
#   ★自動修正するのは次の2型だけ(Chamiへ提案し承認された範囲):
#     ① override_allowed で「アロンソさん/裸アロンソ」→ allowed[0]=「アロンソコーチ」
#     ② honorific_required で「裸の姓」→「姓+さん」(=allowed[0])
#   ★安全弁(誤修正=事故を防ぐ):
#     - target_form(=allowed[0])が **裸の姓で始まる時だけ**置換する
#       (別名・愛称への丸ごと置換はしない=「同じ姓に敬称/役職を足す/直す」に限定)。
#     - 各違反出現の**直後が安全境界**(文末/句読点/助詞)の時だけ置換する
#       → 「三笘薫」のような姓+名(直後が漢字)は置換せず**警告のみ**へ落とす
#         (「三笘さん薫」に壊すのを防ぐ=設計が警告したCの false-positive の核)。
#     - forbidden(シャビさん等)・愛称ゆれ・敬称ゆれは自動修正しない=警告のみ。
#   fail-open: 例外時は元文をそのまま返す(applied=[])。

# 違反出現の直後に来てよい「境界」文字(この後ろなら姓が言い切られている)。
_SAFE_AFTER_CHARS = set(
    " \t\r\n　"
    "、。，．・！？…‥「」『』（）()【】〈〉《》"
    "\"'“”‘’~〜:：;；/／\\|,.!?＝=＋+＊*＿_-–—「」"
)
# 姓の直後に来てよい助詞/接尾(この並びで姓が終わっていると判る)。長い順。
_SAFE_AFTER_PARTICLES = (
    "って", "では", "にも", "へも", "との", "への", "から", "まで", "より",
    "です", "だっ",
    "は", "が", "を", "に", "へ", "と", "も", "の", "や", "で",
    "だ", "さ", "ね", "よ", "な",
)


def _safe_after(s, end_idx):
    """s[end_idx:] が『姓が言い切られた』境界で始まるか(=そこで置換して安全か)。"""
    after = s[end_idx:]
    if after == "":
        return True
    if after[0] in _SAFE_AFTER_CHARS:
        return True
    return any(after.startswith(p) for p in _SAFE_AFTER_PARTICLES)


def _iter_occurrences(s, bare, allowed):
    """本文中の bare の各出現について (開始位置, 実際に使われた形, 許容か) を返す。

    「実際に使われた形」の求め方は _appears_as_allowed と同じ(2本に割れさせない):
      (a) その位置から始まる最長の allowed 形(直後にさらに敬称が続くなら不採用)、
      (b) 無ければ bare + 直後の敬称/接尾。
    """
    allowed = [str(a or "") for a in (allowed or []) if str(a or "")]
    allowed_set = set(allowed)
    start = 0
    while True:
        i = s.find(bare, start)
        if i < 0:
            break
        best_allowed = ""
        for a in allowed:
            if not s.startswith(a, i) or len(a) <= len(best_allowed):
                continue
            after = s[i + len(a):]
            if any(after.startswith(h) for h in _HONORIFICS):
                continue
            best_allowed = a
        if best_allowed:
            actual = best_allowed
        else:
            tail = s[i + len(bare):]
            suf = ""
            for h in _HONORIFICS:
                if tail.startswith(h):
                    suf = h
                    break
            actual = bare + suf
        yield i, actual, (actual in allowed_set)
        start = i + len(bare)


def naming_corrections(persona, dept, text, rules):
    """高信頼の呼称違反だけ自動修正した本文を返す(純関数)。

    返り値: {"fixed": str, "applied": [ {target,to,reason,count} ], "remaining": [verdict...] }
      - applied  : 自動修正した違反(本文は fixed に反映済み)。
      - remaining : 自動修正しなかった違反(=警告のみ・呼び出し側で naming_audit へ残す)。
    fail-open: 例外時は元文と applied=[] を返す。
    """
    result = {"fixed": str(text or ""), "applied": [], "remaining": []}
    try:
        s = str(text or "")
        verdicts = naming_verdicts(persona, dept, s, rules)
        if not verdicts:
            return result
        repls = []  # (start, end, new)
        for v in verdicts:
            reason = v.get("reason")
            bare = str(v.get("found") or "")
            allowed = [str(a or "") for a in (v.get("expected") or []) if str(a or "")]
            # 自動修正の対象は2型だけ(forbidden・愛称ゆれ等は警告のみ)
            if reason not in ("override_allowed", "honorific_required") or not bare or not allowed:
                result["remaining"].append(v)
                continue
            target_form = allowed[0]
            # 「同じ姓に敬称/役職を足す/直す」= target_form が裸の姓で始まる時だけ
            if not target_form.startswith(bare):
                result["remaining"].append(v)
                continue
            fixed_n = 0
            unsafe = False
            for i, actual, ok in _iter_occurrences(s, bare, allowed):
                if ok:
                    continue
                end = i + len(actual)
                if not _safe_after(s, end):
                    unsafe = True          # 姓+名(直後が漢字)等=置換すると壊れる
                    continue
                repls.append((i, end, target_form))
                fixed_n += 1
            if fixed_n:
                result["applied"].append({
                    "target": v.get("target"), "to": target_form,
                    "reason": reason, "count": fixed_n,
                })
            if unsafe or not fixed_n:
                # 危険な出現が残った/1つも直せなかった=警告として残す(沈黙にしない)
                result["remaining"].append(v)
        if repls:
            repls.sort(key=lambda r: r[0])
            filtered, last_end = [], -1
            for a, b, new in repls:
                if a >= last_end:           # 重なりは最初の1つだけ採る
                    filtered.append((a, b, new))
                    last_end = b
            out, prev = [], 0
            for a, b, new in filtered:
                out.append(s[prev:a])
                out.append(new)
                prev = b
            out.append(s[prev:])
            result["fixed"] = "".join(out)
        return result
    except Exception:
        return {"fixed": str(text or ""), "applied": [], "remaining": []}
