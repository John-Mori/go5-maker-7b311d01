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


# ==== 名乗りタグ `[名前]` は「日本語の本文」ではない(2026-08-23)====================
#   ★実測で入れた(改善提案部門トトリの提案 msg DISPATCH-aegis-gl-1787458670363 を
#     こちらで数え直した結果)。naming_audit.jsonl の違反候補165件のうち
#     **64件(39%)が、返信の1行目の名乗り `[ケヴィン・デブライネ]` を本文と見なして
#     「デブライネさん と書け」と鳴らしていた**。名乗りは Discord へ出る前に
#     dept_daemon が取り除く**機械の構文**で、日本語の呼びかけではない。
#   ★★これは騒音であると同時に**地雷**だった= もし `]` を _SAFE_AFTER_CHARS へ足すと、
#     自動修正が `[ケヴィン・デブライネ]` → `[ケヴィン・デブライネさん]` に書き換え、
#     **名義の解決が壊れる**(共通規律§4.8・付録A-6)。今それを止めていたのは
#     「`]` がたまたま安全境界の一覧に無い」ことだけ=**静かに壊れる推定**(§3)。
#   直し方= 判定の前にタグの範囲を**同じ長さのNULで覆う**(削らない=位置がずれると
#     naming_corrections の位置指定の置換が壊れるため)。覆うのは
#     **中身が実在の人格名と完全一致する行頭の角括弧だけ**=「[三笘の96h]」のような
#     普通の括弧書きは今までどおり judged のまま(取りこぼしを作らない)。
_NAME_TAG_RE = re.compile(r"(?m)^[ \t　]*\[([^\[\]\n]{1,24})\]")
_MASK_CH = chr(0)  # 本文に出ない=どの名前にも一致せず、安全境界(_SAFE_AFTER_CHARS)にもならない


def _known_name_norms(persona, rules):
    """名乗りタグの中身が『人格名』かを見分けるための正規化済み名前集合。

    集めるのは**判定に使う名前だけ**= 話者本人 + 呼称ルールの対象キーとその検出形。
    それ以外の名前は、そもそもこのゲートが違反を出さない=覆う必要がない。
    """
    names = set()
    if persona:
        names.add(_norm(persona))
    rules = rules or {}
    hrt = rules.get("honorific_required_targets") or {}
    for k, v in hrt.items():
        if str(k).startswith("_") or not isinstance(v, dict):
            continue
        names.add(_norm(k))
        for f in list(v.get("bare_forms") or []) + list(v.get("allowed") or []):
            if f:
                names.add(_norm(f))
    detect = rules.get("target_detect_forms") or {}
    if isinstance(detect, dict):
        for k, arr in detect.items():
            if str(k).startswith("_"):
                continue
            names.add(_norm(k))
            for f in (arr or []) if isinstance(arr, (list, tuple)) else []:
                if f:
                    names.add(_norm(f))
    for ov in rules.get("speaker_target_overrides") or []:
        tk = ov.get("target")
        if tk and tk != "*":
            names.add(_norm(tk))
    names.discard("")
    return names


def _is_self(persona, target_key):
    """話者と対象が同じ人か(中黒・空白のゆれを吸収して見る)。

    ★1つの述語として名前を付けてある理由は2つ(2026-08-23):
      ①同じ問いを2か所に書かない(ORG-11)。
      ②検査で**この述語だけを旧仕様(常にFalse)へ戻して**、同じ検体が鳴ることを
        見せられるようにする=must-fail(共通規律§3「入力を差し替えて経路を実行で通せ」)。
    """
    return _norm(persona) == _norm(target_key)


def _mask_name_tags(text, persona, rules):
    """行頭の名乗りタグ `[人格名]` を**同じ長さの覆い**に差し替えた文字列を返す。

    長さを変えないのが要点= naming_corrections は元文の**位置**で置換するので、
    ここでずらすと置換先が1文字ずつ狂う(判定用と置換用で2本の文字列を持たない)。
    fail-open: 例外は元文をそのまま返す(覆えなくても配送は殺さない)。
    """
    try:
        s = str(text or "")
        if "[" not in s:
            return s
        known = _known_name_norms(persona, rules)
        if not known:
            return s
        out = list(s)
        for m in _NAME_TAG_RE.finditer(s):
            if _norm(m.group(1)) not in known:
                continue        # 人格名ではない普通の括弧書き=判定に残す
            for i in range(m.start(), m.end()):
                out[i] = _MASK_CH
        return "".join(out)
    except Exception:
        return str(text or "")


# ==== 引用の中の名前は「呼びかけ」ではない(2026-08-23)==========================
#   ★改善提案部門トトリの訂正便(DISPATCH-aegis-gl-1787459099442)の P1③
#     「名前の直後が話題助詞(の/は/が/を/に)なら除外」は**こちらの実測で不採用**にした。
#     その形だと本物の呼び捨てが道連れで黙る:
#       「アロンソが全部喋っちゃってただけ」「デブライネは言い訳しないで」
#       「アロンソの一人称は原典から採るの」(いずれもアメスの地の文=本物の違反)
#     助詞は"言及か呼びかけか"を分けない。分けるのは**引用符**だ。
#   実測(local/llm/naming_audit.jsonl 403行の excerpt を現行コードへ通した284判定):
#       引用符の中で鳴っていた 54件(19%)。例=
#         ククール「アロンソさん」でゲートを走らせたら…  ← ゲートの動作説明
#         人事部門の解説文『三笘くん』を…                ← 呼称の解説
#         **アメス→一ノ瀬怜=呼び捨て「怜」** を刻んだ    ← 台帳の値
#     どれも「その文字列そのものの話」であって、誰かをそう呼んだのではない。
#   ★境界の決め方(推定を置かない):
#     - 開き/閉じが**同じ行**に在るものだけ覆う。改行を跨ぐ対は誤対応
#       (実測: バッククォートが段落を跨いで対になり 66〜89字を巻き込んでいた=
#        それを覆うと本物の呼び捨てまで黙る)。
#     - 併せて長さ上限 60 字。これは意味の線ではなく**誤対応よけ**
#       (実測で正しい引用の最長は36字)。
_QUOTE_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'), ("`", "`"))
_QUOTE_MAX = 60


def _mask_quoted_mentions(text):
    """引用符の**中身**を同じ長さの覆いに差し替えた文字列を返す。

    `_mask_name_tags` と同じ約束= **長さを変えない**(naming_corrections は元文の
    位置で置換するため。判定用と置換用で2本の文字列を持たない)。
    fail-open: 例外は元文をそのまま返す(覆えなくても配送は殺さない)。
    ★1つの述語として名前を付けてあるのは、検査でここだけを旧仕様(恒等関数)へ
      戻して同じ検体が鳴るのを見せるため(共通規律§3)。
    """
    try:
        s = str(text or "")
        if not s:
            return s
        out = None
        for op, cl in _QUOTE_PAIRS:
            i = 0
            while True:
                b = s.find(op, i)
                if b < 0:
                    break
                e = s.find(cl, b + 1)
                if e < 0:
                    break
                inner = s[b + 1:e]
                i = e + 1
                if not inner or len(inner) > _QUOTE_MAX or "\n" in inner:
                    continue
                if out is None:
                    out = list(s)
                for k in range(b + 1, e):
                    out[k] = _MASK_CH
        return s if out is None else "".join(out)
    except Exception:
        return str(text or "")


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
    """対象キーの「本文中でその人を指す形」を集める。無ければキー名そのもの。

    材料は2つ(どちらも同じ写像=呼称ルール.json の中・ORG-11):
      ① honorific_required_targets[key].bare_forms  … **さん付け必須**の対象の裸の姓
      ② target_detect_forms[key]                    … ★検出専用(2026-08-15 追加)

    ★②が要る理由(2026-08-15・人事部門ククールが実測して回してきた発注):
      検出formsを①に相乗りさせると「さん付け必須」の意味まで付いてくる。
      一ノ瀬怜は override を持つ話者だけが呼び方を決められる対象(男連中は『怜』呼び捨て・
      芽衣は『怜ちゃん』・ヴィルシーナは『怜さん』)で、**既定でさん付け必須ではない**。
      なのに①へ入れると override を持たない話者が裸の『怜』を出した瞬間に
      honorific_required で誤爆する。だから **検出だけの表** を別に持つ。
      それまでは怜の検出候補がキー名「一ノ瀬怜」だけ=誰もフル表記では呼ばないので、
      怜宛ての override(ククール/デブライネ/ヴィルシーナ/芽衣)が**全部空振り**していた。

    ★②は判定を増やさない。②だけを持つ対象は honorific_required_targets に居ない=
      allowed が無い= override を持たない話者は「判定不能=不問」で必ず素通りする
      (下の naming_verdicts 末尾の分岐)。効くのは **override を書いたペアだけ**(C-035)。
    """
    rules = rules or {}
    hrt = rules.get("honorific_required_targets") or {}
    ent = hrt.get(target_key)
    if not isinstance(ent, dict):
        ent = {}                # ★_note 等のメタ文字列キーを弾く
    detect = rules.get("target_detect_forms") or {}
    extra = detect.get(target_key) if isinstance(detect, dict) else None
    if not isinstance(extra, (list, tuple)):
        extra = []
    forms = []
    for f in list(ent.get("bare_forms") or []) + list(extra):
        f = str(f or "")
        if f and f not in forms:
            forms.append(f)
    # どちらも無い対象(override 専用対象)はキー名そのものを候補にする
    if not forms:
        forms = [target_key]
    return forms


def _is_katakana(ch):
    """1文字がカタカナ(長音符ーを含む)か。半角カタカナも見る。"""
    if not ch:
        return False
    o = ord(ch)
    return (0x30A0 <= o <= 0x30FF) or (0xFF66 <= o <= 0xFF9F)


def _abbrev_verdicts(text, rules):
    """人格名の一字/短縮略称(C-021)を単語境界で捕まえる(警告のみ)。

    データ(hrが用意)= rules["abbreviation_forbidden"]:
        "<正式名>": ["ク", ...]                                # 略称形の配列、または
        "<正式名>": {"forbidden_forms": ["ク"], "expected": ["ククール"]}
    判定(基盤)= 略称形が本文に出て、その出現の**前後どちらもカタカナでない**時だけ違反。
      → 「ククール」自体や「リンク」等のカタカナ連なりの一部では発火しない
        (単独トークンとしての略称だけを拾う)。s.find の部分一致では捕まえられない
        C-021(ククール→ク)を、境界(=前後の非カタカナ)で切り分ける。
    reason="abbreviation"=Cゲートは警告のみ(naming_corrections は自動修正しない=
      「ク」が必ずしもククールを指すとは限らず、full名への丸ごと置換は事故になりうるため)。
    fail-open: データが無い/形が違う時は空リスト(=既定は無変更)。
    """
    out = []
    ab = (rules or {}).get("abbreviation_forbidden") or {}
    if not isinstance(ab, dict):
        return out
    s = str(text or "")
    for full, spec in ab.items():
        if str(full).startswith("_"):
            continue                      # _note 等のメタキーを弾く
        if isinstance(spec, dict):
            forms = list(spec.get("forbidden_forms") or [])
            expected = list(spec.get("expected") or [full])
        elif isinstance(spec, (list, tuple)):
            forms = list(spec)
            expected = [full]
        else:
            continue
        for form in forms:
            form = str(form or "")
            if not form:
                continue
            start = 0
            while True:
                i = s.find(form, start)
                if i < 0:
                    break
                end = i + len(form)
                before = s[i - 1] if i > 0 else ""
                after = s[end] if end < len(s) else ""
                if (not _is_katakana(before)) and (not _is_katakana(after)):
                    out.append({
                        "target": full, "found": form,
                        "expected": expected, "reason": "abbreviation",
                    })
                    break                 # この形は便あたり1警告で十分
                start = i + 1
    return out


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
        # ★名乗りタグ `[人格名]` は機械の構文=判定から外す(2026-08-23・上の★参照)。
        #   長さは変えない=位置は元文と1文字もずれない。
        s = _mask_name_tags(s, persona, rules)
        # ★引用符の中身は「その文字列そのものの話」=呼びかけではない(上の★参照)。
        s = _mask_quoted_mentions(s)

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
                # ★話者×対象の override が持つ forbidden も消費する(2026-08-15・人事部門依頼 案E)。
                #   それまでは honorific_required_targets.forbidden しか読んでおらず、
                #   写像に書かれた override 側の forbidden は**静かに無視**されていた
                #   (実在例= 三笘薫→三笘薫 の自称 forbidden:["三笘さん"])。
                #   reason="forbidden" = 警告のみ(naming_corrections は自動修正しない)。
                #   abbreviation_forbidden と同じ扱い= 置換先が一意に決まらないものは直さない。
                #   ★yobisute_ok より先に見る= 呼び捨て可の話者でも禁止形は禁止。
                ov_fb = _find_forms(s, [str(x) for x in (ov.get("forbidden") or []) if str(x)])
                if ov_fb is not None:
                    out.append({
                        "target": tk, "found": ov_fb[1],
                        "expected": list(ov.get("allowed") or ent.get("allowed") or []),
                        "reason": "forbidden",
                    })
                    continue
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
            # ★自分で自分を呼ぶ形に敬称を要求しない(2026-08-23)。
            #   実測= 違反候補165件のうち **69件(42%)が「話者==対象」**、つまり
            #   デブライネの便に出る「デブライネ」へ『デブライネさん と書け』と鳴っていた。
            #   日本語で自称に「さん」は付かない=**この警告は原理的に常に誤り**で、
            #   常に誤発火する安全網は無視される(共通規律§3)。
            #   ★消すのは**既定の敬称要求だけ**= 話者×対象の override(三笘薫→三笘薫の
            #     forbidden:["三笘さん"] のような**わざと書かれた自称の禁止形**)は
            #     この行より上で処理済み=そのまま生きる。forbidden / abbreviation も無傷。
            if _is_self(persona, tk):
                continue
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
        # ★人格名の一字略(C-021・ククール→ク)を単語境界で捕まえる(警告のみ)。
        out.extend(_abbrev_verdicts(s, rules))
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


# ★自動修正を「呼びかけ位置だけ」に絞る部屋(2026-08-24・A案の後継)===============
#   人事部門(hr-room)は このAI組織の呼称ルールそのものを本文で論じる部屋だ。
#   ここでは人格名が**呼びかけではなくデータ**として出る=①名簿の列挙
#   (`デブライネ/モドリッチ/ククール/オタコン/三笘/星南/…`) ②設定オブジェクトの持ち主
#   (「三笘のforbiddenへ1語追加した」) ③判定対象の識別子(「同じ文をアロンソで判定しても空」)。
#   これらを話者の許容形へ自動置換すると、本文が化ける。
#
#   ★2026-08-24 実測(イージス研究室): naming_audit の hr-room 漏れ90本へ自動修正を
#     当て直したら **46箇所が書き換わり、うち30箇所が化け**た。最悪例は
#       「呼称ルール.json にも三笘→三笘の自己言及ルール(allowed=俺・三笘 / forbidden=三笘さん)」
#       → 「… (allowed=俺・三笘さん / forbidden=三笘さん)」= **記述しているルールを反転させる**。
#     引用マスク(_mask_quoted_mentions)では防げない=列挙も「Xの<設定語>」も引用符が付かない。
#   ★2026-08-03 のA案(部屋ごと全部オフ)は結論として正しかったが、当時の説明
#     「autofixが『三笘くん』→『三笘さん』へ化けさせた」の**向きは裏が取れていない**
#     (msg 1533593872004022292 の生成原文はもう残っていない。人事部門ククールは
#      2026-08-24 に「あれは自分の生成ドリフトだ」と述べている=どちらか**不明**)。
#     向きに関わらず、上の実測により**この部屋で地の文を自動置換してはいけない**。
#
#   そのうえで安全に直せる場所が1つだけある= **呼びかけ位置**。
#   ①出現が行頭から始まり ②直後が読点、の2条件が揃う所は「相手に呼びかけている」以外の
#   読みが無い(列挙・設定キー・識別子はこの形にならない)。実測で7箇所・化け0。
#   → この部屋は呼びかけ位置だけ直し、残りは remaining(警告のみ)として監査に残す。
#   ★naming_verdicts(監査記録)は不変=見え方は落とさず、本文破壊だけを止める。
VOCATIVE_ONLY_DEPTS = {"hr-room"}


def _vocative_only(dept):
    """この部屋の自動修正を「呼びかけ位置だけ」に絞るか。"""
    return str(dept or "").strip().lower() in VOCATIVE_ONLY_DEPTS


def _is_vocative(s, i, end):
    """s[i:end] の出現が『呼びかけ』位置か= 行頭から始まり、直後が読点。"""
    if i != 0 and s[i - 1:i] != "\n":
        return False
    return s[end:end + 1] in ("、", ",")


def naming_corrections(persona, dept, text, rules):
    """高信頼の呼称違反だけ自動修正した本文を返す(純関数)。

    返り値: {"fixed": str, "applied": [ {target,to,reason,count} ], "remaining": [verdict...] }
      - applied  : 自動修正した違反(本文は fixed に反映済み)。
      - remaining : 自動修正しなかった違反(=警告のみ・呼び出し側で naming_audit へ残す)。
    ★VOCATIVE_ONLY_DEPTS の部屋(人事部門)は**呼びかけ位置だけ**直し、地の文の出現は
      全部 remaining へ回す(呼称ルールを本文で論じる部屋で本文が化けるのを防ぐ)。
    fail-open: 例外時は元文と applied=[] を返す。
    """
    result = {"fixed": str(text or ""), "applied": [], "remaining": []}
    try:
        s = str(text or "")
        verdicts = naming_verdicts(persona, dept, s, rules)
        if not verdicts:
            return result
        # ★探すのは覆った文字列・書くのは元文(2026-08-23)。長さが同じなので位置は共通。
        #   これで**名乗りタグの中は絶対に書き換わらない**(`[ケヴィン・デブライネさん]`
        #   に化けて名義の解決が壊れる事故を、境界文字の運任せでなく機構で止める)。
        masked = _mask_quoted_mentions(_mask_name_tags(s, persona, rules))
        # ★呼称ルールを本文で論じる部屋は、呼びかけ位置だけ直す(地の文は警告のみ)。
        voc_only = _vocative_only(dept)
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
            for i, actual, ok in _iter_occurrences(masked, bare, allowed):
                if ok:
                    continue
                end = i + len(actual)
                if not _safe_after(masked, end):
                    unsafe = True          # 姓+名(直後が漢字)等=置換すると壊れる
                    continue
                if voc_only and not _is_vocative(masked, i, end):
                    unsafe = True          # 人事部門の地の文=名簿/設定キー/識別子=直さない
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
