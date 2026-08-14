#!/usr/bin/env python3
"""出力ゲート ルールD(口調ドリフト検知)=純関数(LLM不要・テスト可・警告のみ)  2026-08-03.

設計書= 00_AI-HQ/設計_口調ゲート_送信直前_名乗りと本文の食い違い_2026-08-03.md。
裁定= 研究室HQ(msg 1533789472783863899)「①警告のみ段階=投入Go / ②LLM審級はinlineにしない」。

判定は (話者=persona名, 部屋=dept, 本文) の三つ組。呼称ゲート(ルールC=naming_gate)と
**同じ送信直前地点**(dept_daemon.audit_naming と同じブロック)へ相乗りする兄弟チェック。

一次(このモジュール)=純関数で「名乗り[名前]と本文の一人称の露骨な食い違い」だけを拾う。
  例: アメス(一人称=あたし)のブロックに「オレ」= 別人格ククール/デブライネの一人称=食い違い。
意味的ドリフト(一人称も語尾も踏まずに距離感だけ別人格へ寄る=DEF-hq-6999e18608「アロンソ口調」型)は
  純関数では拾えない=**このゲートの対象外**(HQ裁定②=inline LLMは却下・二次で別途)。

★fail-open(HQ裁定①で厳守指示): 例外・ルール未ロードは**空リスト**を返す=ゲート自身が配送を殺さない。
★ORG-11(判定を2本持たない): 口調判定はこの1本に集約する。写像1本=口調ルール.json。

== 2026-08-12 格上げ: 警告のみ → **違反した便だけ書き直す** ==
Chami「寝る前Goのやつ、Goで」(2026-08-12 05:50 JST)→ 研究室HQが2番(本命)に確定
(msg 1536843049408270336)→ 人事部門(ククール)から発注(msg 1536843250646646854)。
理由= 警告のみでは素通りする。実測で「俺」が 8/9・8/10・8/11・8/12 と4日連続そのまま送信された。

書き直しは `tone_corrections()`(naming_gate.naming_corrections の兄弟)。**再生成しない**=
**一人称/二人称トークンの機械的置換**だけ。往復ゼロ(遅延を1ミリも足さない)で、
**数字・バージョン・ファイル名には構造上触りようがない**(発注条件4)。
★書き直しは1回まで= 置換後にもう一度判定して**まだ違反が残るなら元の本文をそのまま通す**
  (発注条件2・共通規律§3「可用性に関わる所は fail-open」= 口調のゲートで沈黙を作らない)。
★語尾は対象外= 機械的置換では文が壊れる(「〜だぜ」→「〜です」は文法が変わる)。一人称・二人称だけ。

== 2026-08-12 追加: 方言(関西弁)の**検知**(書き直しはしない) ==
Chamiが🔥(重大炎上・恒久対策しろ)を貼った実物= msg 1536785938829549718「ちょ、こいつらヤバイ /
関西弁使い出した」。崩れた実物= msg 1536784731872698439(改修部門α)=
  花海咲季「縦積みになってるやん、これは完全に悪化。**ほんま**ごめんな。」
  オタコン「今までのもコレが**元凶や**。…ぜんぶ同じ穴**や**。」
★構造の穴= このゲートは一人称/二人称しか見ていなかった。だから「オレ↔俺」は機械が直すのに、
  「やん・ほんま・元凶や」には**見張りが一人も居ない**。characterfileのNGは"お願い"で、
  熱が入ると素通りする(実際に人事部門が db8d9eb でNGを足した後に再発している)。
★ここで**書き直しはしない**= 語尾の置換は文法が変わる(「元凶や」→「元凶だ」は語尾、
  「〜してるやん」→「〜してるよな」は形が変わる)。**検知して次便へ突き返す**のが担当。
  突き返し= dept_daemon が tone_audit の直近を読んで、次の封筒へ是正行を1本入れる。
"""
import json
import re

# 判定に使う「distinctive(識別力のある)一人称」だけを対象にする。
#   私 / わたし / うち / 自分 は中立・多義(私立・私的…)で誤検知が高いので**対象外**
#   (警告のみMVP=まず誤検知率を低く保って実測する。HQ裁定①「誤検知率を実測できる形」)。
DISTINCTIVE_MARKERS = (
    "オレ", "俺", "僕", "ぼく", "あたし", "あたい",
    "わし", "わっち", "拙者", "小生", "あちき",
)

# ------------------------------------------------------------------
# 方言(関西弁)マーカー = (表示名, 正規表現)。★**誤検知を作らない側へ寄せる**=
#   標準語と読みが被る形は入れない(拾い漏れは次の便でまた出るが、誤って
#   「関西弁を使った」と突き返すと**その人格の正しい声まで疑わせる**)。
#   入れなかったもの= 「めっちゃ」(全国区の口語)・「ちゃう」(「〜しちゃう」と衝突)・
#   「とる」(「取る」と衝突)・「ええ」(「ええと」と衝突)。
_DIALECT_KANSAI = (
    ("ほんま", r"ほんま"),
    # 「やん」= 文末のみ。「やんわり」「やんちゃ」は後続が わ/ち なので当たらない。
    ("やん", r"やん(?=[。、，,！!？?…\s]|$)|やん[かなねで]"),
    ("せや", r"せや(?:な|で|から|けど)"),
    # ★2026-08-15 カタカナ表記を許容。実物「一番アカン事故や」(msg 1537849548896993352)が
    #   ひらがな限定の r"あかん" を素通りしていた。**強調で書く時ほどカタカナになる**=
    #   熱が入った時に崩れる、というこのゲートが狙う場面そのものを取りこぼしていた。
    #   後続カタカナを除くのは「アカンサス」(植物)よけ=一人称側の _scan_marker と同じ考え方。
    ("あかん", r"あかん|アカン(?![ァ-ヴー])"),
    ("やで", r"やで(?=[。、，,！!？?…\s]|$)"),
    ("やねん", r"やねん"),
    ("なんぼ", r"なんぼ"),
    ("おおきに", r"おおきに"),
    # 断定の「や」= **漢字/カタカナの直後で文が終わる時だけ**。
    #   実物「元凶や。」「同じ穴や。」を拾い、「いや。」(前がひらがな)・
    #   「AやB」(文末でない)・「そりゃ」は拾わない。
    ("や(断定)", r"(?<=[一-龥ァ-ヴー])や(?=[。！!？?]|$)"),
    # ★2026-08-15 断定「や」の**連結形**。上の「や(断定)」は文末限定なので、文の途中に
    #   立つ「事故やと思う」「はずやから」が丸ごと漏れていた(実物 msg 1537849548896993352)。
    #   ★誤検知を増やさないための絞り込み(発注条件):
    #     ・「やと」は後続を 思/言/聞/見/考 に限る → 「はやとちり」「隼(はやと)が」を拾わない。
    #     ・直前の「い」を外す → 「いやと言った」(嫌だと)・「いやからかうな」を拾わない。
    #     ・「やから」は素で足りる → 標準語で ひらがな や+から が続く語がほぼ無い
    #       (部屋から=屋・タイヤから=ヤ・おもちゃから=ゃ で、どれも当たらない)。
    #   ★入れなかった連結形= 「やけど」(火傷と衝突)・「やし」(林/椰子)・「やな」(嫌な/柳)・
    #     「やって」(やってみる)。どれも標準語の実物と当たるので、拾い漏れる側に倒す。
    ("や(連結)", r"(?<!い)や(?:と(?=[思言聞見考])|から)"),
    ("やろ", r"やろ(?![うっ])(?=[。、，,！!？?…\s]|$)"),
)

_KATAKANA = re.compile(r"[ァ-ヴ]")
# 「…」『…』で囲まれた span=他人格のセリフ引用でありうる=一人称判定から外す(FP抑制)。
# ★2026-08-12 追加: **二重引用符**(" / “” / ＂ / 〝〟)も同じ扱いにする。
#   実物= 2026-08-11 16:59 copy-director・早坂芽衣(正=私/芽衣)の便
#     『題名も1にすると"実は女の子も"と"俺だけじゃない"がぴったり…』
#   で「俺」が発火していた。これは**話者の一人称ではなくコピー案の引用**=誤検知。
#   警告のみの段階では雑音で済むが、**書き直しへ格上げすると案文そのものを壊す**
#   (「"俺だけじゃない"」→「"私だけじゃない"」は訴求の意味が別物になる)ので先に潰す。
# ★シングルクォート(' / ’)は**入れない**= don't / it's のアポストロフィで
#   無関係な範囲を丸ごと引用と誤認し、本物の違反を隠す(検知漏れ)方向に効くため。
# ★どのパターンも改行をまたがない([^\n])= 閉じ忘れの1個で本文全体が消えるのを防ぐ。
_QUOTE_SPAN = re.compile(
    r"「[^「」]*」|『[^『』]*』"
    r"|\"[^\"\n]*\"|“[^”\n]*”|＂[^＂\n]*＂|〝[^〟\n]*〟")

# ★2026-08-12(書き直し格上げと同時): 引用に加えて **コード・引用行・パス/URL** も判定から外す。
#   警告のみなら雑音で済んだが、**本文を書き換える**なら誤爆1件が中身の破壊になる。
#   - ```…``` / `…` = コード。閉じ忘れの時は**マッチしない**=本文を飲み込まない(非貪欲)。
#   - 行頭 `>` = 他人の便の引用(証拠を書き換えたら台帳が嘘になる)。
#   - URL・Windowsパス・拡張子つきファイル名 = 発注条件4「ファイル名には触らせない」を構造で担保。
#     ★広げすぎない= `A/B` のような1スラッシュの略記は**パス扱いしない**(検知漏れを作らないため)。
_CODE_SPAN = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_QUOTE_LINE = re.compile(r"^[ \t]*[>＞][^\n]*", re.M)
#     ★スラッシュの汎用パターンは **ASCII のみ**にする= 日本語は空白で区切らないので
#       `\S*/\S+/\S*` だと「俺は改修α/基盤/両方をやる」の**文ごと**保護されて検知漏れになる。
#     ★★パス/ファイル名の判定は**必ずASCIIから始める**。実測で分かった事故=
#       `\S*\.md` のような左側自由の形だと、日本語は空白で切れないので
#       「差し戻し無しの素通しなので、俺の側の手番は…(selection-rules.md)」の**一文まるごと**が
#       ファイル名扱いになり、**本物の違反(アメスの「俺」)を隠していた**(2026-08-06 の実物)。
#       日本語のファイル名は `docs/口調ルール.json` のように**スラッシュの後ろ**でだけ許す。
_PATHISH = re.compile(
    r"(?:(?<=^)|(?<=[\s(（「『=＝、。:：]))"          # 語の頭からしか始めない
    r"(?:(?:https?://|www\.)\S+"
    r"|[A-Za-z]:[\\/][^\s、。「」『』()（）]+"                     # C:\… のWindowsパス
    r"|[A-Za-z0-9_.~%\-]+(?:/[A-Za-z0-9_.~%\-]+)*/[^\s、。「」『』()（）]+"  # /を含むパス
    r"|[A-Za-z0-9_.~%\-]+"
    r"\.(?:py|js|mjs|md|json|jsonl|html|css|gs|txt|ps1|bat|yml|yaml|png|jpg|mp4)\b)")
_PROTECT = (_CODE_SPAN, _QUOTE_LINE, _PATHISH, _QUOTE_SPAN)


def load_tone_rules(path):
    """口調ルール.json を読み込む。読めなければ None(呼び出し側で fail-open)。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _norm(s):
    """人格名の表記ゆれ(中黒・空白)を吸収して突き合わせる(naming_gate と同じ思想)。"""
    return re.sub(r"[・\s]", "", str(s or "")).lower()


def _mask_protected(s):
    """保護span(引用・コード・引用行・パス/URL)を**長さ保存**で潰す(全角空白へ置換)。

    長さを保存するのは、**この文字列の位置がそのまま元テキストの位置**になるからだ
    (書き直しは元テキスト側の同じ添字を差し替える=ズレたら別の場所を壊す)。
    他人格のセリフ引用(例: デブライネが『アメスは「あたし」と言った』)で
    一人称ゲートが誤爆するのを防ぐ=最頻の false-positive を消す。
    """
    out = str(s or "")
    for pat in _PROTECT:
        out = pat.sub(lambda m: "　" * len(m.group(0)), out)
    return out


# 旧名(2026-08-12 以前の呼び出し互換)。中身は保護span全体のマスクへ広がっている。
_strip_quotes = _mask_protected


def _persona_entry(rules, persona):
    """人格エントリを中黒無視で引く。無ければ None(=判定対象外=スキップ)。"""
    personas = (rules or {}).get("personas") or {}
    if persona in personas:
        return personas[persona]
    n = _norm(persona)
    for k, v in personas.items():
        if _norm(k) == n:
            return v
    return None


def _registry_distinctive(rules):
    """レジストリ全体に現れる distinctive 一人称の集合(=誰かの正規一人称であるものだけ)。"""
    personas = (rules or {}).get("personas") or {}
    seen = set()
    for v in personas.values():
        for fp in (v.get("first_person") or []):
            if str(fp) in DISTINCTIVE_MARKERS:
                seen.add(str(fp))
    return seen


def _scan_marker(s, marker):
    """s 中の marker の最初の「有効な」出現位置。無ければ -1。

    ★カタカナ marker(オレ 等)は、直後もカタカナなら別語(オレ→オレンジ)としてスキップ。
      漢字/ひらがな marker(俺・僕・あたし)はこのガードを掛けない。
    """
    is_kata = bool(_KATAKANA.search(marker))
    start = 0
    while True:
        i = s.find(marker, start)
        if i < 0:
            return -1
        after = s[i + len(marker):i + len(marker) + 1]
        if is_kata and after and _KATAKANA.match(after):
            start = i + len(marker)   # オレンジ等=別語=この出現は無効
            continue
        return i


def tone_verdicts(persona, dept, text, rules):
    """口調違反(=一人称の食い違い)の候補一覧を返す(純関数・警告のみ)。

    引数:
      persona : 話者(解決済みの正式名。split_persona_blocks の resolve 結果 or 既定名)。
      dept    : 部屋(監査記録用。判定には現状未使用)。
      text    : ブロック本文。
      rules   : load_tone_rules() の戻り(dict) or None。

    返り値: list[dict]。各要素=
      {"persona","marker","index","own_first_person":[...],"reason":"first_person_mismatch"}
    違反が無ければ空リスト。ルール未ロード/例外/未登録人格は空リスト(fail-open)。
    """
    out = []
    try:
        if not rules:
            return out
        ent = _persona_entry(rules, persona)
        if not ent:
            return out            # 未登録の人格は判定しない(fail-open=鳴らさない)
        own = {str(x) for x in (ent.get("first_person") or [])}
        # 禁止= レジストリ上の distinctive 一人称のうち、自分のものでないもの。
        #   (レジストリに人格を足せば自動で他人格の一人称が禁止対象になる=正本1本)。
        forbid = sorted(_registry_distinctive(rules) - own)
        # ★人格ごとの禁止語(2026-08-12 の発注で対象に入った=二人称「お前」・詫び「すまん」等)。
        #   写像の `forbidden`(人事部門 commit be37d68 で追加。例 オタコン=["お前","あんた","すまん"])。
        #   ★判定材料は口調ルール.json 1本のまま= characters/*.md(散文)は読みに行かない(ORG-11)。
        #   ★人格に `forbidden` が無ければ1件も回らない=その人格の挙動は従来と1ミリも変わらない。
        #   ★`second_person_forbidden` は同義の別名として受ける(写像側の綴り揺れで静かに死なせない)。
        ng2 = [str(x) for x in ((ent.get("forbidden") or [])
                                + (ent.get("second_person_forbidden") or [])) if str(x)]
        # ★方言(関西弁)の検知。既定=全人格が対象(20人格すべて標準語で登録されている)。
        #   関西弁が正の人格が来たら、人事部門が写像へ `"dialect_ok": true` を1行足せば外れる
        #   (このコードは触らない=判定材料は口調ルール.json 1本のまま・ORG-11)。
        want_dialect = not bool(ent.get("dialect_ok"))
        if not forbid and not ng2 and not want_dialect:
            return out
        s = _strip_quotes(text)
        if not s.strip():
            return out
        for m in forbid:
            i = _scan_marker(s, m)
            if i >= 0:
                out.append({
                    "persona": str(persona or ""),
                    "marker": m,
                    "index": i,
                    "own_first_person": sorted(own),
                    "reason": "first_person_mismatch",
                })
        for m in ng2:
            i = _scan_marker(s, m)
            if i >= 0:
                out.append({
                    "persona": str(persona or ""),
                    "marker": m,
                    "index": i,
                    "own_first_person": sorted(own),
                    "reason": "forbidden_word",
                })
        if want_dialect:
            for name, pat in _DIALECT_KANSAI:
                m = re.search(pat, s)
                if m:
                    out.append({
                        "persona": str(persona or ""),
                        "marker": name,
                        "index": m.start(),
                        "own_first_person": sorted(own),
                        "reason": "dialect_kansai",
                    })
        return out
    except Exception:
        return []                 # fail-open=ゲートは配送を殺さない


# 禁止語のうち**二人称**だけは、置換先を写像の `second_person` から機械的に決められる。
#   ★これは「判定」ではない(判定材料は口調ルール.json の forbidden 1本のまま)。
#     「お前」を直す先が『君』だと分かるための**置換先の解決**にだけ使う。
#   ★二人称でない禁止語(例 オタコンの「すまん」)は置換先が写像に無い= **警告のみで通す**。
#     直したいなら人事部門が `forbidden_to` に {"すまん":"ごめん"} を足せばこのコードのまま効く。
_SECOND_PERSON_WORDS = (
    "お前", "おまえ", "あんた", "貴様", "てめえ", "てめー", "君", "あなた", "そなた",
)


def _canonical(words):
    """置換先は**一意に決まる時だけ**返す(HQ裁定 2026-08-12 msg 1536847015886200892)。

    ★リストの先頭を正と決めない。写像は候補の**リスト**で持っており、
      早坂芽衣は ["芽衣","私"]= 先頭決め打ちだと**名前を一人称の位置に差し込む**置換が走る。
    ★候補が2つ以上ある人格(デブライネ/ククール/早坂芽衣=実測3人格)は空を返す
      = その便は書き直さず**警告のみで素通し**。ここは人格の原典に触る領域で、
      沈黙より雑音がマシだが、雑音より**声を壊す方がずっと悪い**(HQ原文)。
    """
    ws = [str(w) for w in (words or []) if str(w)]
    return ws[0] if len(ws) == 1 else ""


def tone_corrections(persona, dept, text, rules):
    """口調違反を**その便だけ書き直す**(2026-08-12 格上げ。naming_corrections の兄弟)。

    返り値: {"fixed": 書き直し後の本文, "applied": [...], "remaining": [...]}
      applied  = 実際に置換した違反(1件=1マーカー。count=置換した出現数)。
      remaining= 置換できずに**警告のみ**で通した違反(従来と同じ扱い)。
    ★再生成しない= 一人称/二人称トークンの機械的置換のみ。往復ゼロ・数字/版/ファイル名に触らない。
    ★**置換先が一意に決まる時だけ置換する**(HQ裁定)。候補が複数ある人格は素通し=警告のみ。
    ★書き直しは1回まで= 置換後に再判定して**まだ違反が残るなら元の本文をそのまま返す**(fail-open)。
    ★保護span(引用・コード・引用行・パス)の中は**書き換えない**(判定と同じマスクを使う=ズレない)。
    ★例外は握り潰して元の本文を返す=ゲートが配送を殺さない。
    """
    out = {"fixed": text, "applied": [], "remaining": []}
    try:
        verdicts = tone_verdicts(persona, dept, text, rules) or []
        if not verdicts:
            return out
        ent = _persona_entry(rules, persona) or {}
        to1 = _canonical(ent.get("first_person"))
        to2 = _canonical(ent.get("second_person"))
        explicit = ent.get("forbidden_to") or {}   # 人事部門が明示した置換先(あれば最優先)
        # 置換先が無い違反は書き直せない=警告のみで通す(黙って落とさない)。
        plan, out["remaining"] = {}, []
        for v in verdicts:
            w = v.get("marker")
            if v.get("reason") == "dialect_kansai":
                to = ""            # ★方言は書き直さない(語尾の置換は文法が変わる)=警告のみ
            elif v.get("reason") == "first_person_mismatch":
                to = to1
            elif w in explicit:
                to = str(explicit.get(w) or "")
            elif w in _SECOND_PERSON_WORDS:
                to = to2
            else:
                to = ""            # 二人称でない禁止語(例「すまん」)=直す先が写像に無い
            if to and to != v.get("marker"):
                plan[v.get("marker")] = to
            else:
                out["remaining"].append(v)
        if not plan:
            return out

        masked = _mask_protected(text)          # 長さ保存=添字はそのまま元テキストの添字
        markers = sorted(plan, key=len, reverse=True)   # 長いマーカーを先に見る
        buf, counts, i, n = [], {}, 0, len(text)
        while i < n:
            hit = ""
            for m in markers:
                if not masked.startswith(m, i):
                    continue                    # 保護span内(全角空白で潰れている)=触らない
                after = text[i + len(m):i + len(m) + 1]
                if _KATAKANA.search(m) and after and _KATAKANA.match(after):
                    continue                    # オレンジ等=別語(判定側と同じガード)
                hit = m
                break
            if hit:
                buf.append(plan[hit])
                counts[hit] = counts.get(hit, 0) + 1
                i += len(hit)
            else:
                buf.append(text[i])
                i += 1
        fixed = "".join(buf)

        if not counts or fixed == text:
            out["remaining"] = verdicts
            return out
        # 長さの帳尻(置換以外を1文字も触っていないことの機械的な裏取り)。
        delta = sum(c * (len(plan[m]) - len(m)) for m, c in counts.items())
        if len(fixed) - len(text) != delta:
            out["remaining"] = verdicts
            return out
        # ★書き直しは1回まで= **直したはずのマーカーがまだ残っていたら**元の本文を通す。
        #   ★2026-08-12 修正= 以前は「違反が1件でも残ったら差し戻し」だった。これだと
        #     **直せない種類の違反**(方言・置換先が一意でない一人称・置換先の無い禁止語)が
        #     同じ便に1つでも在ると、直せるはずの一人称の書き直しまで巻き添えで消えていた。
        #     実物= msg 1536784731872698439 のオタコン便=「俺」(直せる)と「元凶や」(直せない)が同居。
        #   見るのは「plan に載せたマーカーが消えたか」だけ=1回で直りきったかの機械的な確認。
        left = {v.get("marker") for v in (tone_verdicts(persona, dept, fixed, rules) or [])}
        if left & set(plan):
            out["remaining"] = verdicts
            return out

        out["fixed"] = fixed
        out["applied"] = [{
            "persona": str(persona or ""),
            "marker": m, "to": plan[m], "count": c,
            "reason": "tone_rewrite",
        } for m, c in counts.items()]
        return out
    except Exception:
        # fail-open= 書き直しに失敗しても**元の本文で送る**(口調のゲートで沈黙を作らない)。
        return {"fixed": text, "applied": [], "remaining": []}
