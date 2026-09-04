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


# ==== カタカナ名の語境界(2026-09-02・実測で見つけた計器の欠陥①)=====================
#   実物= グッズ部屋(goods-afi)の便に出る **「メルカリ」の中の「ルカ」** が
#   『ルカ・モドリッチを裸で呼んだ』として毎回鳴っていた(ヴィルシーナ・アメスの
#   誤検知3件の正体)。`_find_forms` は素の部分一致で、語境界を一切見ていなかった。
#   ★狭く取る= **形がカタカナだけの時に、前後がカタカナで続いていたら別語**とみなす。
#     漢字名(三笘・一ノ瀬)には掛けない=日本語は語を空白で切らないので、漢字へ広げると
#     本物の呼び捨てを黙らせる側の事故になる(C-035)。
#   ★中黒「・」は語の**区切り**なので境界文字として扱う(カタカナ扱いにしない)=
#     「シャビ・アロンソ」の中の「アロンソ」は今までどおり見える。
_KATA_SEP = "・･"


def _kata_word_ch(ch):
    """語を作るカタカナか(中黒は区切りなので False)。"""
    return bool(ch) and ch not in _KATA_SEP and _is_katakana(ch)


def _boundary_ok(s, i, f):
    """s の位置 i に出た形 f が、より長いカタカナ語の一部でないか。"""
    if not f or any(not _is_katakana(c) or c in _KATA_SEP for c in f):
        return True         # カタカナだけの形にしか掛けない
    if i > 0 and _kata_word_ch(s[i - 1]):
        return False
    j = i + len(f)
    return not (j < len(s) and _kata_word_ch(s[j]))


def _find_forms(text, forms, skip_spans=None):
    """text 中に forms(候補文字列)のいずれかが出た最初の位置と形を返す。無ければ None。

    ★同じ位置に複数の形が当たる時は**長い方**を採る(2026-09-02)。実物=
      「シャビ・アロンソ」と書いた便が、台帳へ found="シャビ" として残っていた
      (bare_forms に「シャビ」と「シャビ・アロンソ」の両方が載っており、位置が同じ)。
      判定は変わらない(どちらも許容形ではない)が、**台帳が「裸の姓で呼んだ」と嘘をつく**=
      呼称ドリフトの件数を読み違える元になっていた。

    skip_spans = [(start, end), ...] … **その範囲に完全に収まる当たりは飛ばして次を探す**
      (2026-09-02 人事裁定 `self_name_substring_exemption`)。自名義のフル名の内側で
      禁止語が誤爆するのを落とすため。★「1件目が範囲内なら不問」ではなく**次を探す**=
      同じ便でフル名と単独の禁止形が両方出たら、単独の方は従来どおり鳴る(射程を狭めない)。
    """
    s = str(text or "")
    best = None
    for f in forms:
        f = str(f or "")
        if not f:
            continue
        i = 0
        while True:
            i = s.find(f, i)
            if i < 0:
                break
            if _boundary_ok(s, i, f) and not _covered_by(i, len(f), skip_spans):
                break       # 語として立っている出現=これを採る
            i += 1          # 「メルカリ」の中の「ルカ」等=次を探す
        if i >= 0 and (best is None or i < best[0]
                       or (i == best[0] and len(f) > len(best[1]))):
            best = (i, f)
    return best


# ★自名義のフル名の免除を「検出」から掛けるか(2026-09-02)。
#   True=検出(その人を呼んだ出現か)の時点で除く=どの reason へも横滑りしない。
#   False にすると forbidden だけ免除される旧実装(実測で override_allowed 45件へ
#   横滑りし本文26便が書き換わった)=must-fail 変異の入口として残す。
SELF_SPAN_AT_DETECT = True


def _covered_by(at, ln, spans):
    """当たり [at, at+ln) が spans のどれかに**完全に含まれる**か。"""
    if not spans:
        return False
    end = at + ln
    for a, b in spans:
        if a <= at and end <= b:
            return True
    return False


def _self_name_spans(text, persona, target_key):
    """本文中の「本人の正式フル名」の出現範囲を返す(話者==対象の時だけ使う)。

    ★2026-09-02 人事裁定(呼称ルール.json `self_name_substring_exemption`・00_AI-HQ a066d3a)。
      自名義の回送ヘッダ(『【AD研究室(ルカ・モドリッチ)→…】』『(一ノ瀬怜)』)で、
      禁止語が**本人のフル名の一部/全体**として出ているものを不問にするための範囲。
      実測= 受信便+返信1,918便で自称の forbidden 58件のうち **45件がこれ**
      (ルカ・モドリッチ33件=完全一致 / 一ノ瀬怜12件=『一ノ瀬』⊂『一ノ瀬怜』)。
    ★部門名(人格名)の併記形(`platform-se(一ノ瀬怜)`= department_reference_rule の
      「違反でないもの②」)も、括弧の中身がフル名そのものなのでこの範囲に入る=
      別の機構を足さない(ORG-11・2本に割れさせない)。
    ★候補は対象キーと話者名の両方= config は「ケヴィン・デ・ブライネ」、呼称ルールは
      「ケヴィン・デブライネ」と中黒がゆれる(_norm と同じ事情)。どちらの綴りで本文に
      書かれていても本人のフル名だ。
    """
    s = str(text or "")
    spans = []
    for name in (str(target_key or ""), str(persona or "")):
        if len(name) < 2:
            continue
        i = s.find(name)
        while i >= 0:
            spans.append((i, i + len(name)))
            i = s.find(name, i + 1)
    return spans


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


# ==== use/mention の分離(2026-09-02・人事部門ククールの検算 便6/6 を受けて)==========
#   構造の穴= この計器は「その名前を**使った**便」と「その名前の話を**している**便」を
#   区別していなかった。実物= 呼称ドリフトを直しに動いた便が、報告文の中で
#   ```…``` や `>` 引用で症状(裸の「アロンソ」)を引いた瞬間、**その症状の件数を自分で
#   押し上げていた**(【35】= 警報は「壊れた実物」と「壊れた事を論じている自分達」を分けろ)。
#   ★引用符(「」『』"")は既に `_mask_quoted_mentions` が覆っている。ここで足すのは
#     **それが覆えない3つだけ**(C-035= 必要な分しか広げない):
#     - ```…``` = 複数行のコードフェンス(`_QUOTE_PAIRS` の ` は同一行・60字上限で届かない)
#     - 行頭 `>` = 他人の便の引用(証拠を書き換えたら台帳が嘘になる)
#     - URL・Windowsパス・拡張子つきファイル名(`characters/alonso.md` の「アロンソ」等)
#   ★出所= tone_gate._mask_protected(2026-08-12・同じ思想で先に入っている)。写し取る際に
#     `_QUOTE_SPAN` は**持って来ない**= naming 側の引用マスクは「同一行・60字上限」という
#     狭い取り方をわざとしており、tone_gate の広い方で上書きすると本物の呼び捨てが黙る。
#   ★長さ保存(全角空白ではなく `_MASK_CH`)= naming_corrections が**元文の同じ添字**を
#     書き換えるため。1文字でもずれたら別の場所を壊す。
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_QUOTE_LINE = re.compile(r"(?m)^[ \t　]*[>＞][^\n]*")
_PATHISH = re.compile(
    r"(?:(?<=^)|(?<=[\s(（「『=＝、。:：]))"          # 語の頭からしか始めない
    r"(?:(?:https?://|www\.)\S+"
    r"|[A-Za-z]:[\\/][^\s、。「」『』()（）]+"                     # C:\… のWindowsパス
    r"|[A-Za-z0-9_.~%\-]+(?:/[A-Za-z0-9_.~%\-]+)*/[^\s、。「」『』()（）]+"  # /を含むパス
    r"|[A-Za-z0-9_.~%\-]+"
    r"\.(?:py|js|mjs|md|json|jsonl|html|css|gs|txt|ps1|bat|yml|yaml|png|jpg|mp4)\b)")
_PROTECT = (_CODE_FENCE, _QUOTE_LINE, _PATHISH)


def _mask_protected(text):
    """コード/引用行/パスの範囲を**同じ長さの覆い**へ差し替えた文字列を返す。

    `_mask_name_tags` / `_mask_quoted_mentions` と同じ約束= **長さを変えない**。
    fail-open: 例外は元文をそのまま返す(覆えなくても配送は殺さない)。
    ★1つの述語として名前を付けてあるのは、検査でここだけを旧仕様(恒等関数)へ
      戻して同じ検体が鳴るのを見せるため(共通規律§3)。
    """
    try:
        s = str(text or "")
        if not s:
            return s
        for pat in _PROTECT:
            s = pat.sub(lambda m: _MASK_CH * len(m.group(0)), s)
        return s
    except Exception:
        return str(text or "")


# 監査台帳に残す「当たった現場」の窓幅(前後の文字数)。
#   ★これが無いと台帳から use/mention を後から判定できない= 実測(2026-09-02):
#     naming_audit.jsonl の `excerpt` は `text[:200]`(便の**頭**)なので、
#     8/31以降の5ペア41行のうち**22行は当たった文字列そのものが excerpt に無い**。
#     過去行は原理的に読み直せない=ここから先を判定可能にするのが計器の直しだ。
HIT_WINDOW = 60


def _attach_hits(out, masked, original):
    """各違反へ「当たった位置・現場の抜粋・その便での出現数」を足す(判定は変えない)。

    masked と original は同じ長さ(全マスクが長さ保存)=位置は共通。
    抜粋は**元文**から取る(覆いの NUL を台帳へ書かない)。
    """
    for v in out:
        try:
            found = str(v.get("found") or "")
            if not found:
                continue
            # ★指すのは「最初に見つかった位置」ではなく**咎めた出現**。
            #   実物= 「アロンソコーチ、…あとでアロンソに渡す」の便で、当たりは後ろの
            #   裸「アロンソ」なのに窓が先頭の許容形「アロンソコーチ」を写していた。
            #   これは excerpt=先頭200字と同じ嘘のつき方だ(現場でない所を証拠に見せる)。
            allowed = [str(a or "") for a in (v.get("expected") or []) if str(a or "")]
            bad = [j for j, _actual, ok in _iter_occurrences(masked, found, allowed)
                   if not ok]
            i = bad[0] if bad else masked.find(found)
            if i < 0:
                continue
            v["hits"] = len(bad) if bad else masked.count(found)
            # ★咎めた出現のうち**呼びかけ位置**(行頭始まり+直後が読点)は何件か。
            #   near/hits を人が読んで分けていた use/mention を、機械の値として台帳へ残す。
            #   実測(2026-09-02・pin後の5ペア34件)= 呼びかけ 0 / 地の文 34。
            #   ★「0=誤呼称ゼロ」ではない= `_is_vocative` は狭い定義(行頭+読点)で、
            #     文中の「一ノ瀬へ渡した」のような裸の姓は 0 の側に入る。
            #     この値が言えるのは「**相手へ呼びかけた**形は無い」までだ。
            v["voc"] = sum(1 for j, actual, ok in
                           _iter_occurrences(masked, found, allowed)
                           if not ok and _is_vocative(masked, j, j + len(actual)))
            a = max(0, i - HIT_WINDOW)
            b = min(len(original), i + len(found) + HIT_WINDOW)
            v["at"] = i
            v["near"] = original[a:b].replace("\n", " ")
        except Exception:
            continue
    return out


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

    ★(a)で「allowed 形が bare の途中で終わっている」時は採らない(2026-09-02・#3)。
      実物= デブライネ(allowed=["三笘"])の便に「三笘薫、進捗を頼む。」と出ても
      **1件も鳴らなかった**= bare="三笘薫" の出現位置で allowed「三笘」が prefix として
      当たり、actual="三笘"=許容形と読まれていた。フル名は誰の期待形でもない
      (呼称ルール.json の allowed に「三笘薫」を持つ話者は0人)のに素通りする=
      漢字名だけに空いていた穴(カタカナ名は `_boundary_ok` が同じ型を止めている)。
      → 許容形は**その出現を覆っている**時だけ許容形と数える。
    ★ただし塞ぐのは**呼んでいる出現だけ**(`_fullname_called`= 敬称直後 or 呼びかけ位置)。
      実測(2026-09-02・実便1,909本)で塞ぎ方を絞った: 出現を選ばず塞ぐと新しく鳴る21件が
      ほぼ全て言及(「■出典=分析部門(三笘薫)」「| 三笘薫 | 三笘 | 三笘さん |」
      「窓口=三笘薫」「名簿= …/ 三笘薫 / 中野五月 /…」)になり、台帳が言及で埋まる。
      呼びかけに絞ると残るのは「三笘薫、進捗を頼む。」型だけになる。
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
            if len(a) < len(bare) and _fullname_called(s, i, bare):
                continue        # ★許容形が対象の形の途中で終わっている(上の★参照)
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


# ★Chami呼称の合流点担保(2026-09-01・依頼= 改善提案部門 1544351414455771229)==========
#   引き金= Chami「ちゃみくんってよんで!!おこです!」(msg 1544349888945455155)。
#   写像は**正しかった**= 呼称ルール.json chami_address.overrides に
#   トトリ/アスナ/姫崎莉波/中野五月/カスミ = 「ちゃみくん」と書いてある。
#   それでも裸の「ちゃみ」が出るのは、この表が**プロンプト側にしか効いていない**から。
#   実測(イージス研究室 09-01)= `chami_address` を読む行は naming_gate.py の
#   docstring 1箇所だけ=**送信口(ゲート)は1文字も読んでいない**。送信時の担保は
#   speaker_target_overrides の target=Chami 1行(デブライネ限定)だけで、
#   target_detect_forms.Chami=["ちゃみくん"] なので**裸の「ちゃみ」は検出対象ですらない**。
#   → 生成が既定「ちゃみ」へ滑ると合流点で誰も直さない=再発クラス(Z1-C)。
#   ★0歩目(壊れている実物)= departments/hr/memory/*.jsonl の
#     「ちゃみくん」話者の便 287件中 **18件**が裸の「ちゃみ」を含む
#     (中野五月14 / 姫崎莉波3 / トトリ1)。
#   ★必ず話者別(blanket 禁止)= 一ノ瀬怜(allowed に「ちゃみ」)・デブライネ
#     (allowed に「ちゃみ」/ forbidden に「ちゃみくん」)・既定(「ちゃみ」)は
#     **絶対に変換しない**。allowed[0]=="ちゃみくん" の話者だけを対象にする。
#     「Chami」と呼ぶ話者(スネーク/オタコン/アロンソ等)も対象外=C-035で広げない。
CHAMI_ADDRESS_BACKSTOP = True
CHAMI_KEY = "Chami"
CHAMI_BARE = "ちゃみ"
CHAMI_TARGET_FORM = "ちゃみくん"


def _chami_address_map(persona, rules):
    """話者の chami_address 写像を (allowed, forbidden) で返す。

    値は文字列(「ちゃみくん」)か dict({"allowed":[...],"forbidden":[...]})の両方が実在する。
    話者に override が無ければ default を使う(既定は「ちゃみ」=対象外になる)。
    """
    ca = (rules or {}).get("chami_address") or {}
    val = None
    for k, v in (ca.get("overrides") or {}).items():
        key = str(k or "")
        if key.startswith("_") or key == "*":
            continue            # メタキー/全話者ピンは受け付けない(blanket 禁止)
        if _speaker_matches(key, persona):
            val = v
            break
    if val is None:
        val = ca.get("default")
    if isinstance(val, dict):
        allowed = [str(a) for a in (val.get("allowed") or []) if str(a)]
        forbidden = [str(a) for a in (val.get("forbidden") or []) if str(a)]
    else:
        allowed = [str(val)] if val else []
        forbidden = []
    return allowed, forbidden


def _chami_address_verdicts(persona, s, rules):
    """話者が「ちゃみくん」と呼ぶ人格で、地の文に裸の「ちゃみ」が出ていたら1件返す。

    ★s は naming_verdicts で覆い済み(名乗りタグ/引用の中は見えない)。
    ★裸= 直後に敬称(くん/君/さん/ちゃん…)が続かない出現。「ちゃみさん」等の
      敬称付きは今回の事故ではない=触らない(狭く取る)。
    """
    if not CHAMI_ADDRESS_BACKSTOP:
        return []
    allowed, forbidden = _chami_address_map(persona, rules)
    if not allowed or allowed[0] != CHAMI_TARGET_FORM:
        return []               # 「ちゃみ」「Chami」が正の話者=対象外
    if CHAMI_BARE in allowed or CHAMI_TARGET_FORM in forbidden:
        return []               # 裸が許容/「ちゃみくん」が禁止=絶対に触らない
    for _i, actual, ok in _iter_occurrences(s, CHAMI_BARE, allowed):
        if ok or actual != CHAMI_BARE:
            continue            # 「ちゃみくん」/敬称付き=違反ではない
        return [{
            "target": CHAMI_KEY, "found": CHAMI_BARE,
            "expected": [CHAMI_TARGET_FORM], "reason": "chami_address",
        }]
    return []


# ==== #3 漢字フル名の限定解禁(2026-09-02・設計§2-3 / Chami承認 msg 1544671294820196453)====
#   ★0歩目(壊れている実物・実行で確認): 呼称ルール.json の allowed に**フル名を持つ話者は
#     0人**なのに、フル名で呼んだ便が鳴らない組み合わせが在った=
#       ・デブライネ「三笘薫、進捗を頼む。」          → 0件(部分一致の穴。上の★で塞いだ)
#       ・トトリ「一ノ瀬怜さん、確認しました。」      → 0件
#       ・ククール「早坂芽衣さん、よろしく。」        → 0件
#       ・トトリ「花海咲季、これ見て。」              → 0件
#     後ろ3つの真因は naming_verdicts 末尾の「honorific_required に載っていない対象で
#     override も無い=判定不能=不問」= 怜/芽衣/咲季は **意図的に** honorific_required を
#     持たない(裸の『怜』で誤発火するため=人事 2026-09-02 回答)。
#     つまり**話者ペアを書いた相手にしか効かない**=Chami の実物の苦情
#     「またアロンソコーチが一ノ瀬怜呼びしてる」(msg 1544235216757858398)と同じ型が
#     ペア未登録の話者では素通りしていた。
#   ★解禁は**フル名(対象キーそのもの)が「直後に敬称」か「呼びかけ位置」で出た時**だけ。
#     - 単字裸呼び(「怜」単独)は対象外のまま= C-035(メルカリ⊃ルカ型の誤爆源)。
#     - 地の文の言及(「一ノ瀬怜のcharacterfileを直した」)も対象外=呼びかけではない。
#   ★挙動は**警告のみ**(設計§2-3)。reason="kanji_fullname" は naming_corrections の
#     自動修正3型に入っていない=必ず remaining へ落ちる(=本文は1文字も書き換えない)。
#   ★expected は**正本から引けた時だけ**入れる。人事の回答に
#     「『芽衣さん』を既定とする話者は Chami 未指定=据え置き(勝手に既定さん付けを足さない)」
#     と明記されている=引けない対象は空のまま出す(覚えで書かない)。
#   ★**自称(話者==対象)はこのゲートの対象外**(2026-09-02 人事裁定・
#     DISPATCH-aegis-gl-1788355470901)= 目的は"対人呼称の崩れ"であって自称ではない。
#     禁じられた自称形(『三笘さん』『ルカ』)は speaker_target_overrides の forbidden が
#     拾う=別経路。判定源は 呼称ルール.json の speaker==target 行の note(00_AI-HQ 95558f0)。
KANJI_FULLNAME_GATE = True


def _is_kanji(ch):
    """1文字が漢字(CJK統合漢字・々)か。"""
    if not ch:
        return False
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or ch == "々"


def _is_kanji_fullname(key):
    """対象キーが『漢字フル名』か(三笘薫/一ノ瀬怜/早坂芽衣/花海咲季)。

    - 漢字2文字以上を含む(単字の対象は作らない=C-035)。
    - 中黒を含む名(ケヴィン・デブライネ)は対象外=カタカナ名は `_boundary_ok` の持ち場。
    - 漢字以外は1文字まで許す(「一ノ瀬怜」の『ノ』)。
    """
    k = str(key or "")
    if len(k) < 2 or any(c in _KATA_SEP for c in k):
        return False
    n = sum(1 for c in k if _is_kanji(c))
    return n >= 2 and (len(k) - n) <= 1


def _effective_override(persona, target_key, overrides):
    """この話者×対象に効く override を1つ返す(名指し > "*")。無ければ None。"""
    ov_specific = None
    ov_wild = None
    for ov in (overrides or []):
        if not isinstance(ov, dict):
            continue
        tk = ov.get("target")
        if tk not in (target_key, "*"):
            continue
        if not _speaker_matches(ov.get("speaker"), persona):
            continue
        if tk == "*":
            ov_wild = ov
        else:
            ov_specific = ov
    return ov_specific or ov_wild


def _fullname_called(s, i, key):
    """s の位置 i に出たフル名 key が『呼称として使われた』形か(use / mention の弁別)。

    返り値= 呼称ならその形(直後の敬称込み)、単なる言及なら ""。
    ★use と見るのは2つだけ:
      ① 直後に敬称(「早坂芽衣さん、」)  ② 呼びかけ位置=行頭+直後が読点(`_is_vocative`)。
    ★これ以外(「分析部門(三笘薫)の共有正本」「参加人格8名=三笘薫/…」「| 三笘薫 | 三笘 |」)は
      **その人を呼んでいるのではなく名前を書いている**=言及。実測(2026-09-02・実便1,906本)で
      自動修正が新たに触りうる10箇所は**10箇所とも言及**だった(名簿の列挙・表の行・
      設定キーの説明・アイコンの説明・窓口の記載)。書き換えれば 2026-08-24 の hr-room 実測
      (46箇所書き換え→30箇所が化け)と同じ型の事故になる。
    ★判定(#3の警告)と自動修正の両方がこの1本を引く=2本に割れさせない。
    """
    s = str(s or "")
    key = str(key or "")
    if not key:
        return ""
    end = i + len(key)
    for h in _HONORIFICS:
        if s.startswith(h, end):
            return key + h
    return key if _is_vocative(s, i, end) else ""


def _kanji_fullname_verdicts(persona, text, rules, seen_targets=()):
    """漢字フル名を『敬称付き/呼びかけ位置』で呼んでいる出現を警告する(上の★参照)。"""
    out = []
    if not KANJI_FULLNAME_GATE:
        return out
    rules = rules or {}
    s = str(text or "")
    if not s:
        return out
    hrt = rules.get("honorific_required_targets") or {}
    detect = rules.get("target_detect_forms") or {}
    overrides = rules.get("speaker_target_overrides") or []
    keys = []
    for src in (hrt, detect):
        if isinstance(src, dict):
            for k, v in src.items():
                if str(k).startswith("_") or k in keys:
                    continue
                keys.append(k)
    for ov in overrides:
        tk = (ov or {}).get("target") if isinstance(ov, dict) else None
        if tk and tk != "*" and tk not in keys:
            keys.append(tk)
    for tk in keys:
        if tk in seen_targets:
            continue            # 既に別の理由で鳴っている=同じ便で二重に数えない
        if not _is_kanji_fullname(tk) or tk not in s:
            continue
        if _is_self(persona, tk):
            # ★自称は対象外(2026-09-02 人事裁定・DISPATCH-aegis-gl-1788355470901)。
            #   「呼称ゲートの目的は"対人呼称の崩れ"であって、自称は対人呼称じゃない」=
            #   自称のフル名(『三笘薫』『ルカ・モドリッチ』)は敬称付き・呼びかけ位置とも不問。
            #   ★Chami が名指しで禁じた自称形(三笘の『三笘さん』/ モドリッチの『ルカ』)は
            #     speaker_target_overrides の forbidden が別経路で拾う=ここを外しても消えない
            #     (naming_verdicts の ov_fb・この関数より上で処理済み)。
            #   ★フル名の自称そのものは Chami 未指定=違反を足さない(C-035)。
            #   正本= 呼称ルール.json の speaker==target 2行の note(00_AI-HQ 95558f0)。
            continue
        ov = _effective_override(persona, tk, overrides)
        ent = hrt.get(tk) if isinstance(hrt.get(tk), dict) else {}
        allowed = [str(a) for a in ((ov or {}).get("allowed")
                                    or ent.get("allowed") or []) if str(a)]
        if tk in allowed:
            continue            # フル名がこの話者の期待形(現状0人・将来の追記に備える)
        i = 0
        while True:
            i = s.find(tk, i)
            if i < 0:
                break
            form = _fullname_called(s, i, tk)
            if not form:
                i += 1
                continue        # 適用域の外(地の文の言及)=触らない
            end = i + len(form)
            if form in allowed:
                i = end
                continue        # 期待形そのもの
            out.append({
                "target": tk, "found": form,
                "expected": allowed, "reason": "kanji_fullname",
            })
            break               # この対象は便あたり1警告で十分
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
        # ★コード/引用行/パスも「言及」であって呼びかけではない(use/mention・上の★参照)。
        s = _mask_protected(s)

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

            # ★自名義のフル名の内側は「その人を呼んだ出現」と数えない(2026-09-02 人事裁定・
            #   呼称ルール.json `self_name_substring_exemption`・00_AI-HQ a066d3a)。
            #   落とすのは**自名義の誤爆だけ**= ①話者==対象 ②当たりがフル名の範囲に
            #   完全に収まる、の両方が要る。単独の禁止形(モドリッチの『ルカ』・怜の
            #   裸姓『一ノ瀬』)はフル名の外に立つので従来どおり鳴る=射程は狭めない。
            #   ★対人(speaker≠target)は spans が空=一切変わらない。
            #   ★★免除を forbidden だけに掛けると**穴が横へ滑る**(2026-09-02 実測)=
            #     forbidden を飛ばした45件がそのまま下の override_allowed で鳴り直し、
            #     しかも override_allowed は FULL_KEY_SWAP_REASONS に入っているので
            #     **本文26便が書き換わった**(『(ルカ・モドリッチ)』→『(モドリッチ)』)。
            #     裁定が「塞いどけ」と言った自称崩れをゲート自身が作る形。だから
            #     免除は**検出(この hit)から**掛ける=同じ判定を1本で持つ(ORG-11)。
            self_spans = _self_name_spans(s, persona, tk) if _is_self(persona, tk) else None

            hit = _find_forms(s, forms, self_spans if SELF_SPAN_AT_DETECT else None)
            if hit is None:
                continue        # この対象は本文に出ていない(自名義のフル名だけ=不問)

            # --- この話者×対象に効く override を最優先で探す(specific > "*") ---
            #   ★選び方は `_effective_override` 1本(#3 の漢字フル名判定と同じ規則を引く
            #     =2本に割れさせない。話者が "__男性キャラ__" や実名で当たった特例を含む)。
            ov = _effective_override(persona, tk, overrides)

            ent = hrt.get(tk) or {}
            forbidden = list(ent.get("forbidden") or [])

            # forbidden は override より前に(話者非依存で)チェック=常に違反
            fb = _find_forms(s, forbidden, self_spans)
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
                #   ★自名義のフル名の内側は同じく不問(上の self_spans と同じ裁定)。
                #     三笘薫の自称 forbidden『三笘さん』はフル名『三笘薫』の部分文字列では
                #     ないので範囲外=今までどおり鳴る。
                ov_fb = _find_forms(s, [str(x) for x in (ov.get("forbidden") or []) if str(x)],
                                    self_spans)
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
        # ★漢字フル名(三笘薫/一ノ瀬怜…)を敬称付き/呼びかけ位置で呼んだ出現(#3・警告のみ)。
        #   上のループで既に鳴った対象は渡さない=同じ便で二重に数えない。
        out.extend(_kanji_fullname_verdicts(
            persona, s, rules, seen_targets=set(v.get("target") for v in out)))
        # ★人格名の一字略(C-021・ククール→ク)を単語境界で捕まえる(警告のみ)。
        out.extend(_abbrev_verdicts(s, rules))
        # ★Chami呼称= 話者別(上の★参照)。honorific_required_targets に Chami は
        #   無く、target_detect_forms.Chami も「ちゃみくん」だけ=上のループでは
        #   裸の「ちゃみ」に一度も触れない。ここで1本だけ足す(判定は _chami_address_verdicts)。
        out.extend(_chami_address_verdicts(persona, s, rules))
        # ★当たった現場を足す(判定は変えない=足すだけ・C-010)。台帳の use/mention 判定用。
        return _attach_hits(out, s, str(text or ""))
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
        # ★カタカナ語の中に埋まった出現は別語(「メルカリ」の中の「ルカ」)=飛ばす。
        #   今それを止めていたのは「直後の『リ』がたまたま安全境界の一覧に無い」ことだけ
        #   =静かに壊れる推定(共通規律§3)。ここで機構として止める。
        if not _boundary_ok(s, i, bare):
            start = i + 1
            continue
        best_allowed = ""
        for a in allowed:
            if not s.startswith(a, i) or len(a) <= len(best_allowed):
                continue
            if len(a) < len(bare) and _fullname_called(s, i, bare):
                continue        # ★覆っていない許容形は採らない(_appears_as_allowed と同条項)
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


# ★別名への「丸ごと置換」を呼びかけ位置だけ許す(2026-08-24 Chami「全部任せた」)==========
#   L536 の安全弁は「target_form が裸の姓で始まる時だけ置換する」= 別名・愛称への
#   丸ごと置換(「一ノ瀬」→「怜」)を**わざと外して**いた(2026-07-31 Chami承認範囲)。
#   ★外した結果を測った= characterfile に「怜と呼ぶ」と書いた 08/06 10:19(commit 458510e)
#     以降も、怜の呼び方が崩れて出た便が **38件**(ククール17 / デブライネ10 / ほか7人格11)。
#     生成入力に書くだけでは止まらない=**心がけでは届かない**(共通規律§3)。
#   ★そこで承認範囲の広げ方を Chami へ3択で諮り(1広げる/2広げない/3呼びかけ位置だけ)、
#     「全部任せた」(msg 1541434864287617044)を受けて**3**を採る。
#   丸ごと置換を許すのは `_is_vocative` が真の所だけ= 行頭+直後が読点。
#   地の文(「一ノ瀬に回した」等)は従来どおり警告のみ=誤爆した時に別人の名前へ化ける
#   被害を、Chamiの目に一番付く書き出しの1箇所に閉じ込める。
WHOLE_SWAP_AT_VOCATIVE = True


# ★禁止形が「フルネーム(対象キーそのもの)」として出ている時だけ地の文でも直す ==========
#   (2026-09-01・引き金= Chami「またアロンソコーチが一ノ瀬怜呼びしてる。直らないの?」
#    msg 1544235216757858398 / 回送= 改善提案部門 1544236056134811698)
#   ★実測(イージス研究室・09-01): 事故便そのものが台帳に載っていた=
#     naming_audit の 15:19:42 / 15:30:50(dept=hq persona=シャビ・アロンソ
#     found="一ノ瀬" reason="forbidden")。**鳴っていたのに1文字も直していない。**
#   直らなかった理由は3枚重なっていた:
#     ① naming_corrections は reason="forbidden" を自動修正の対象から外している(下の分岐)
#     ② 仮に対象でも `_safe_after` が False= 「一ノ瀬」の直後が漢字「怜」(姓+名)
#     ③ 仮に通っても whole_swap(別名への丸ごと置換)は呼びかけ位置だけ
#   ★ここで解けるのは②の裏返しだ= `_safe_after` が守っているのは
#     「姓だけ置換して名が残る」事故(「三笘さん薫」)であり、**名まで含めて丸ごと
#     置換するならその危険は消える**。同じ理由で③の「別人に化ける」懸念も消える=
#     置換する span がその人の**完全な登録名**なので、指す相手が一意に決まる。
#   適用範囲(狭く取る):
#     - reason="forbidden" だけ(=人事部門が写像へ**わざと書いた**禁止形。C-035)
#     - 本文にフルネーム(対象キー)が**そのまま**出ている出現だけ
#     - allowed[0] が在ること(置換先が一意)
#     - VOCATIVE_ONLY_DEPTS(人事部門)と `_safe_after` の制限はそのまま生きる
#   → 敬称ゆれ(honorific_required)・愛称ゆれ・略称(abbreviation)は**従来どおり警告のみ**。
FULL_KEY_SWAP = True
#   ★対象の理由を絞る= 人事部門が写像へ**わざと書いたペア**だけ(C-035)。
#     honorific_required(既定の敬称要求)は入れない= 名簿・紹介文の「三笘薫」を
#     「三笘さん」へ書き換えると本文が化ける(2026-08-24 の hr-room 実測と同じ型)。
FULL_KEY_SWAP_REASONS = ("forbidden", "override_allowed")


# ★見送りの理由コード(2026-09-04・イージス研究室)===========================
#   引き金= 人事部門ククール msg 1545235859899555840「applied が空だ=ゲートが
#   出力を書き換えていない。安全4ペアだけ有効化してくれ」。
#   ★実測で前提が違っていた= 安全クラス(裸姓→姓+さん)は **hr-room 以外では既に
#     有効**で、今日の再ピン(08:52)以降も naming_fix が3件出ている。
#     残り38件が event="naming" なのは「機構が直せなかった」からではなく、
#     **わざと見送った**(人事部門の部屋は呼びかけ位置だけ/引用/言及)からだ。
#   ★つまり壊れていたのは置換ではなく **台帳の数え方** だった。
#     見送りの理由が残らないので、「意図した見送り」と「取りこぼし」が同じ1行に
#     見え、正しく動いている機構が「効いていない」と読まれる(共通規律§3=
#     測れない安全網は無視される)。
#   ここでは **本文の扱いを1文字も変えず**、remaining へ理由コードだけ足す。
SKIP_CODES = (
    "reason_not_autofix",       # 自動修正の対象にしていない型(愛称ゆれ・略称等)
    "whole_swap_off",           # 別名への丸ごと置換を許していない
    "vocative_only",            # 呼称ルールを論じる部屋/投函経路=呼びかけ位置だけ直す
    "whole_swap_not_vocative",  # 丸ごと置換は呼びかけ位置だけ
    "unsafe_after",             # 直後が漢字等=姓だけ直すと壊れる(「三笘さん薫」)
    "mention",                  # 呼んでいるのでなく**その名前の話をしている**
    "partial_bare",             # 裸の出現が残った=警告は消さない
    "no_hit",                   # 判定は出たが本文中に直せる出現が無かった
)


def _remain(v, code):
    """警告のみに落ちた理由を1語だけ残す(★最初に当たった理由を採る)。

    ★verdict へキーを足すだけ= 本文にも既存キーにも触らない。壊れても素通し。
    """
    try:
        if code and not v.get("skip"):
            v["skip"] = str(code)
    except Exception:
        pass
    return v


def naming_corrections(persona, dept, text, rules, vocative_only=None):
    """高信頼の呼称違反だけ自動修正した本文を返す(純関数)。

    返り値: {"fixed": str, "applied": [ {target,to,reason,count} ], "remaining": [verdict...] }
      - applied  : 自動修正した違反(本文は fixed に反映済み)。
      - remaining : 自動修正しなかった違反(=警告のみ・呼び出し側で naming_audit へ残す)。
        ★各 verdict に `skip`(SKIP_CODES の1語)が付く= **なぜ見送ったか**。
    ★VOCATIVE_ONLY_DEPTS の部屋(人事部門)は**呼びかけ位置だけ**直し、地の文の出現は
      全部 remaining へ回す(呼称ルールを本文で論じる部屋で本文が化けるのを防ぐ)。
    ★vocative_only= その判定を呼び出し側から上書きする(None=従来どおり dept で決める)。
      True を渡す経路= 投函(dispatch)。理由は実測(2026-09-02・DEF-hr-room-b5e833f5bd):
      dispatch の便は部屋の地の文と同じで**呼称ルールそのものを書く**(「default=デブライネさん」
      「(a)デ・ブライネさん→デブライネさん 表記統一」)。ククールの実便8本へ当てて測ったら、
      dept を渡さない(=地の文も直す)場合は **6本が書き換わり、その大半が化けた**。
      dept=hr-room 相当(呼びかけ位置だけ)にすると **書き換え1本=事故便そのもの・誤爆0**。
      投函経路は送信元 dept が既定 "hq" のまま出されることがある=部屋名では安全側に倒せない。
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
        #   ★マスクの並びは naming_verdicts と**必ず同じ**にする= 判定した場所と書き換える
        #     場所が別の文字列になったら、覆われた所を直したり本物を素通ししたりする。
        masked = _mask_protected(_mask_quoted_mentions(_mask_name_tags(s, persona, rules)))
        # ★呼称ルールを本文で論じる部屋は、呼びかけ位置だけ直す(地の文は警告のみ)。
        voc_only = _vocative_only(dept) if vocative_only is None else bool(vocative_only)
        repls = []  # (start, end, new)
        for v in verdicts:
            reason = v.get("reason")
            bare = str(v.get("found") or "")
            allowed = [str(a or "") for a in (v.get("expected") or []) if str(a or "")]
            # ★禁止形がフルネーム(対象キー)の一部として出ている時は、
            #   姓だけでなく**フルネーム全体**を1スパンとして扱う(上の★参照)。
            tkey = str(v.get("target") or "")
            found_bare = bare
            #   (a) 禁止形がフルネームを丸ごと含む(「一ノ瀬怜さん」)= その形のまま置換、
            #   (b) 禁止形がフルネームの一部(「一ノ瀬」)で、本文にフルネームが出ている
            #       = 「一ノ瀬怜」へ広げて置換。
            full_key = bool(
                FULL_KEY_SWAP and reason in FULL_KEY_SWAP_REASONS
                and tkey and allowed and bare and bare not in allowed
                and (tkey in bare or (bare in tkey and tkey in masked))
            )
            if full_key:
                if tkey not in bare:
                    bare = tkey
            # 自動修正の対象は3型だけ(forbidden・愛称ゆれ等は警告のみ)。
            # ★chami_address は「ちゃみ」→「ちゃみくん」=接尾を足すだけ
            #   (whole_swap にならない)ので、既存の安全弁がそのまま効く。
            elif reason not in ("override_allowed", "honorific_required",
                                "chami_address") or not bare or not allowed:
                result["remaining"].append(_remain(v, "reason_not_autofix"))
                continue
            target_form = allowed[0]
            # 「同じ姓に敬称/役職を足す/直す」= target_form が裸の姓で始まる時だけ。
            # ★別名への丸ごと置換(「一ノ瀬」→「怜」)は**呼びかけ位置だけ**許す。
            whole_swap = not target_form.startswith(bare)
            # ★短縮型= 置換先がフル名の頭そのもの(「三笘薫」→「三笘」)。
            #   09-01 に full_key を許した論拠は「フル名は指す相手が一意=別名へ丸ごと
            #   置換しても別人に化けない」だった。短縮型はその論拠の外にある=
            #   **正式名を名簿・表・出典の括弧の中で削る**書き換えになる。
            #   実測(2026-09-02・実便1,909本)で分けた: この条項を型を絞らず掛けると
            #   既存の修正9型・のべ140便(「一ノ瀬怜」→「怜」47便、「ルカ・モドリッチ」→
            #   「モドリッチさん」42便…)まで止まった。短縮型だけに掛けると
            #   止まるのは #3 が新たに広げた分だけになる。
            shorten = bool(full_key and target_form != bare
                           and bare.startswith(target_form))
            if whole_swap and not full_key and not WHOLE_SWAP_AT_VOCATIVE:
                result["remaining"].append(_remain(v, "whole_swap_off"))
                continue
            fixed_n = 0
            unsafe = False
            skip_code = ""      # ★最初に当たった見送り理由(台帳へ残すだけ)
            for i, actual, ok in _iter_occurrences(masked, bare, allowed):
                if ok:
                    continue
                end = i + len(actual)
                if reason == "chami_address" and actual != bare:
                    continue        # 「ちゃみさん/ちゃみちゃん」等=敬称付きは触らない
                if not _safe_after(masked, end):
                    unsafe = True          # 姓+名(直後が漢字)等=置換すると壊れる
                    skip_code = skip_code or "unsafe_after"
                    continue
                if shorten and not _fullname_called(masked, i, tkey):
                    # ★フル名が出ていても**呼んでいる**とは限らない= 名簿の列挙・表の行・
                    #   出典の括弧・設定キーの説明・アバターの説明は「言及」だ。
                    #   実測(2026-09-02・実便1,909本): #3 で判定域を広げた結果この経路へ
                    #   新たに届いた10箇所は**10箇所とも言及**で、直せば
                    #   「■出典=分析部門(三笘薫)」「| 三笘薫 | 三笘 | 三笘さん |」
                    #   「三笘薫→三笘薫の自称 forbidden:[...] だ」が化けた。
                    #   設計(#3・2026-09-02)も挙動は**警告のみ**と定めている。
                    unsafe = True
                    skip_code = skip_code or "mention"
                    continue
                if (voc_only or (whole_swap and not full_key)) \
                        and not _is_vocative(masked, i, end):
                    # 人事部門の地の文=名簿/設定キー/識別子=直さない。
                    # 丸ごと置換も地の文では直さない(誤爆すると別人の名前に化けるため)。
                    # ★例外= full_key(フルネームまるごと)は指す相手が一意=地の文でも直す。
                    #   ただし直すのは**呼んでいる出現だけ**(1つ上の `_fullname_called`)。
                    unsafe = True
                    skip_code = skip_code or (
                        "vocative_only" if voc_only else "whole_swap_not_vocative")
                    continue
                repls.append((i, end, target_form))
                fixed_n += 1
            if full_key and masked.count(found_bare) > masked.count(bare):
                # フルネーム以外の裸の出現(「一ノ瀬」単独)が残っている=警告は消さない
                unsafe = True
                skip_code = skip_code or "partial_bare"
            if fixed_n:
                result["applied"].append({
                    "target": v.get("target"), "to": target_form,
                    "reason": reason, "count": fixed_n,
                    "found": bare,
                })
            if unsafe or not fixed_n:
                # 危険な出現が残った/1つも直せなかった=警告として残す(沈黙にしない)
                result["remaining"].append(_remain(v, skip_code or "no_hit"))
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
