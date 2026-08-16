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
    # ★2026-08-15 否定の「へん」= 関西弁の「ない」相当(行かへん/起こさせへん/勝てへん)。
    #   実物= msg 1538011230134870106 の花海咲季便「黙って消えるのだけは、もう起こさせへん」。
    #   saki.md L13 が「〜へん」を✗例に挙げていたのに、見張りが一人も居なかった穴(C-038)。
    #   ★誤検知よけ= (1)直前を否定語幹の あ段/え段 かなに限る → 「大変(たいへん)」は直前「い」で
    #   外れ、「そのへん(その辺)」は直前「の」で外れる。(2)後続「な」を外す → 「変な(へんな)」を
    #   拾わない。部首名(木偏=き/糸偏=と)も直前かなの段が違い当たらない。
    #   ★拾い漏れる側へ倒す= い段語幹(見へん/起きへん)は「い」衝突を避け今回入れない(次便で
    #   出たら足す・この列の方針どおり)。実測= discord_processed.jsonl 3287便中の「へん」出現は
    #   全てChami本人の発話で、ゲートは人格の出力しか見ない=人格便での誤検知ゼロ。
    ("へん(否定)", r"(?<=[かさたなはまらわがざだばけせてねめれげぜべ])へん(?!な)"),
    # ★2026-08-15 断定「なんよ」= 標準「なのよ/なんだよ」の西日本形。実物= msg
    #   1538011748916011110 の花海咲季便「まだ後手なんよな」。咲季の正の語尾は「のよ/だわ/わね」で
    #   「なんよ」は出ない。★誤検知よけ= 後続「う/だ」を外す=「何曜日(なんようび)」「なんだ」を拾わない。
    #   実測: discord_processed.jsonl 3401テキスト中の「なんよ」出現ゼロ=誤検知ゼロ。
    #   ★同便の「わけちゃう」「変えていくで」は入れない= 「ちゃう」は「〜しちゃう」(実測19件)と、
    #   文末「で」は「下で/肩で」と衝突し、咲季の正しい声まで疑わせる(この列の方針=拾い漏れる側へ倒す)。
    ("なんよ", r"なんよ(?![うだ])"),
    # ★2026-08-16 断定「や」の**ひらがな末**形。上の「や(断定)」は直前を漢字/カタカナに限って
    #   いたので、送り仮名で終わる語(確認待ち・好き・終わり)に付く「や」が丸ごと漏れていた。
    #   実物= msg 1538408581752426526 の花海咲季便「ちゃみの画面で見るまでは確認待ちや。」
    #   (この便で拾えたのは「へん(否定)」1個だけ=網が粗かった)。
    #   ★誤検知よけ(実データで決めた・hr/memory の人格出力3121便=106万字で計測):
    #     ・**句読点を必須**にし `$` を使わない → 途中で切れた記録(「Chamiがや」「本当にや」)を拾わない。
    #     ・直前 い/お を外す → 「いや。」「おや?」を拾わない。
    #     ・直前 う を外す → 「いこうや。」「やろうや。」(全国区の勧誘)を拾わない。
    #     ・拗音(ゃゅょ)を外す → 「そりゃ。」「じゃ。」を拾わない。
    #   実測= 上の106万字での誤検知**0件**、実物の「確認待ちや。」は拾う。
    ("や(断定・かな末)", r"(?<![いおうゃゅょ])(?<=[ぁ-ん])や(?=[。！!？?])"),
    # ★2026-08-16 1音名詞の長音化(手ぇ/気ぃ)。同じ咲季便の「他の🔥も続けて手ぇ動かしとく」。
    #   ★**登録制**にした= 「漢字＋小書きかな」で素に張ると「悪ぃ」(関東の俗語・実測7件)まで
    #   関西弁として鳴ってしまい、その人格の正しい声まで疑わせる。だから**伸ばす1音名詞だけ**を
    #   並べる。実測= 106万字で5件(手ぇ4・気ぃ1)、無関係な誤検知**0件**。足りなければ字を足す。
    ("1音名詞の長音化", r"(?<=[手気血目名身背歯毛])[ぁぃぅぇぉ]"),
    # ★2026-08-16 完了の「〜てもうた/てまう」と接続詞「ほな」。標準語と読みが被る形が無く、
    #   実測= 106万字で出現**0件**(=誤検知0)。今は鳴っていないが、網の穴として先に塞ぐ。
    #   ★「ほなみ」(人名)・「ほなた」は後続で外す。
    ("てもうた", r"てもうた|てもた|てまう"),
    ("ほな", r"ほな(?![みた])"),
    # ★入れなかったもの(2026-08-16・実測で落とした)= 「〜しとく」(握っとく/覚えとく/伝えとく)。
    #   関西弁ではなく**全国区の口語**(「〜ておく」の縮約)で、106万字に38件・話者もデブライネ/
    #   アメス/ククールと広い。鳴らせば全部が誤検知になる。「かな＋小書きかな」も同様に却下
    #   (「あぁ」「なぁ」「ざまぁ」で138件)。
)

# ★2026-08-15 追加(案D《肯定条件》の第1段)= **構造ドリフト(敬体)の検知**。
#   ここまでの検知はすべて「語」の一致だ。だが実測したのはその逆の穴で、
#   口調ルール.json の forbidden に入っている案A指紋10句(「対応しました」「いたしました」
#   「承知しました」等)は **完全一致の定型句** なので、「〜が必要です」「〜だと思います」
#   という **ふつうの敬体** には1文字も当たらない。
#   実物= 2026-08-15 にアロンソ名義の便が標準体で出ているのに、tone_audit.jsonl の
#   hq 行は 8/12 が最後(しかも中身は引用に対する first_person の誤検知だけ)=
#   **標準体を見ている計器がどこにも無い**。語で網を細かくしても追いつかない
#   (敬体の言い方は無限にある)ので、**文末の分布**という別の軸で見る。
#
#   ★誤発火する安全網は無視される(共通規律§3)。だから **1文の丁寧表現では鳴らさない**=
#     文が4つ以上あり、その3つ以上・かつ半分以上が敬体で終わる時だけ1件出す
#     (地の文ごと敬体へ倒れた便だけを拾い、引用や1行の丁寧語は素通しする)。
#   ★★**既定は「見ない」**= 写像に `"plain_only": true` がある人格だけ判定する。
#     方言(dialect_ok)と**向きが逆**なのには実測の理由がある: 21人格のうち
#     トトリ・田中琴葉・中野五月など**敬体が正の人格が多数居り**、案A指紋10句は
#     その全員にも一律で入っている(=指紋の有無では常体/敬体を判別できない)。
#     既定ONで実便407件へ当てたら15件鳴り、**その全部が敬体を正とする人格の便**だった。
#     鳴りっぱなしのゲートは無視される(共通規律§3)ので、**登録した人格だけ**を見る。
#     ★登録するのは人事部門(口調ルール.json は人事の正本・ORG-11)=このコードは触らない。
#   ★体言止めは **入れない**= 箇条書き・見出し・ファイル名の行と衝突して誤検知が多く、
#     この列の方針(拾い漏れる側へ倒す)に反する。実物が出てから足す。
_SENTENCE_SPLIT = re.compile(r"[。！？\?\!\n]+")
_POLITE_TAIL = re.compile(
    r"(?:です|ます|ません|でした|ました|ましょう|でしょう|ください|ですね|ますね"
    r"|ですよ|ますよ|ですか|ますか|ございます)$")
_POLITE_MIN_SENTENCES = 4      # これ未満の短文は判定しない(1〜2文の丁寧語で鳴らさない)
_POLITE_MIN_HITS = 3           # 敬体で終わる文の最低数
_POLITE_MIN_RATIO = 0.5        # かつ、判定した文の半分以上


def polite_drift(text):
    """敬体へ構造的に倒れているかを測る。返り値=(鳴らすか, 敬体文数, 判定文数, 最初の位置)。

    ★純関数(引数以外を読まない)。tone_verdicts から呼ぶが、**単体でも測れる**ようにしてある
      = この判定の閾値だけを実便へ当てて誤検知率を数えられるようにするため。
    ★保護span(引用・コード・パス)は _mask_protected で潰してから数える=
      他人の便を引用した敬体で鳴らない。
    """
    s = _mask_protected(text)
    hits, total, first = 0, 0, -1
    pos = 0
    for part in _SENTENCE_SPLIT.split(s):
        if not part:
            continue
        start = s.find(part, pos)
        if start >= 0:
            pos = start + len(part)
        body = part.strip().strip("　")
        # 記号だけ・短すぎる断片(箇条書きの見出し・表の行)は文として数えない。
        if len(body) < 6:
            continue
        total += 1
        if _POLITE_TAIL.search(body):
            hits += 1
            if first < 0:
                first = max(start, 0)
    ok = (total >= _POLITE_MIN_SENTENCES
          and hits >= _POLITE_MIN_HITS
          and hits >= total * _POLITE_MIN_RATIO)
    return ok, hits, total, first


# ★2026-08-15 追加(案D《肯定条件》の第2段)= **指紋語尾ドリフト**の検知。
#   Chami原文「ずっとこんな感じでいれてるけど効かないね」(msg 1538153136953495612)。
#   実物= 花海咲季名義の便が「したよ／ほんとに無い。／読んでから。」= **常体のまま**
#   「〜わよ/〜わ/〜のよ」という**その人格の指紋が丸ごと消えている**。
#   ★上の polite_drift は「敬体へ倒れた」しか見ない(文末が です/ます 等)= この実物には
#     1文字も当たらない。禁止語リスト(forbidden)も**完全一致の定型句**なので当たらない。
#     つまり「らしさが抜けた」を見ている計器がどこにも無かった。ククール(人事部門)の
#     見立てどおり= polite_drift が敬体の半分・こちらが常体のまま個性が溶ける方の半分。
#
#   ★測り方= **禁止(語の一致)ではなく必須(肯定条件)**。人格に「必須の語尾集合」が
#     登録されている時、**その便のどこにも1つも出ていない**なら1件出す。
#   ★★既定は「見ない」= 写像に `"signature_tails": [...]` がある人格だけ判定する
#     (plain_only と同じ向き。登録するのは人事部門= 口調ルール.json が正本・ORG-11)。
#   ★誤発火を作らない側へ二重に倒す(共通規律§3「常に誤発火する安全網は無視される」):
#     (1) **判定に足る長さ**は polite_drift と同じ数え方= 6字以上の文が4つ以上ある便だけ。
#         1〜3文の短い返事で「らしさが無い」と鳴らさない。
#     (2) **指紋を探す側は広く**= 文末だけでなく**読点区切りの断片の末尾**も見て、
#         後ろに付く終助詞(ね/よ/な…)は剥いでから照合する(「無いわよね」→「無いわ」)。
#         さらに**短い文も証拠に数える**(「そうよ。」1つで鳴らない)。
#         = 拾い漏れる側(鳴らさない側)へ倒す。
#   ★書き直しはしない= 語尾の置換は文法が変わる(このファイル冒頭の方針と同じ)。
#     検知して session_relay が次の封筒へ突き返す(reason="signature_absent")。
_SIG_MIN_SENTENCES = 4         # これ未満の短い便は判定しない
_SIG_SPLIT = re.compile(r"[。！？\?\!\n、，,]+")   # 証拠探しは読点でも区切る
_SIG_TRAIL = "ねよなのさぞぜっーｰ〜～…♪!！?？。、 　\t—–‼︎️★☆♡♥"   # 指紋の後ろに付く終助詞・記号
# ★指紋の**直後に付く括弧**を落としてから照合する。これを入れないと
#   「入れたわよ**(v=564・確認待ち)**。」= 咲季のいちばん咲季らしい一文が
#   「末尾が『)』だから指紋なし」と判定される。実測(下の 134便)で**誤検知の大半がこれ**だった。
_SIG_PAREN = re.compile(r"(?:[（(][^（）()]*[）)]|[\[［【][^\]］】]*[\]］】])$")


def _sig_tailcut(body):
    """指紋語尾の照合前に、末尾の飾り(終助詞・記号・括弧書き)を剥ぐ。

    「入れたわよ(v=564・確認待ち)」→「入れたわよ」→(終助詞よを剥ぐ)→「入れたわ」。
    ★剥ぐのは**照合用のコピー**だけ=本文には触らない。★最大8回で止める(暴走しない)。
    """
    s = str(body or "")
    for _ in range(8):
        t = _SIG_PAREN.sub("", s.rstrip(_SIG_TRAIL)).rstrip(_SIG_TRAIL)
        if t == s:
            break
        s = t
    return s


def signature_drift(text, tails):
    """指紋語尾が便のどこにも無いかを測る。返り値=(鳴らすか, 見つかった数, 判定文数, 位置)。

    ★純関数(引数以外を読まない)= この判定だけを実便へ当てて誤検知率を数えられる。
    ★保護span(引用・コード・パス)は _mask_protected で潰してから見る。
      = 引用の中に指紋があっても「本人が喋った」とは数えない…のではなく**逆**で、
        引用の中の敬体で鳴らないのと同じ理屈で、**引用の中の指紋を証拠にしない**。
        こちらは「証拠が減る=鳴りやすくなる」側なので、判定文数も同じマスクで数える
        (引用だけの便は文数が足りず判定されない)。
    """
    ts = [str(t) for t in (tails or []) if str(t)]
    if not ts:
        return False, 0, 0, -1
    s = _mask_protected(text)
    total = 0
    for part in _SENTENCE_SPLIT.split(s):
        body = part.strip().strip("　")
        if len(body) >= 6:          # 記号だけ・箇条書きの見出しは文と数えない(polite と同じ)
            total += 1
    if total < _SIG_MIN_SENTENCES:
        return False, 0, total, -1
    found, at = 0, -1
    pos = 0
    for part in _SIG_SPLIT.split(s):
        if not part:
            continue
        start = s.find(part, pos)
        if start >= 0:
            pos = start + len(part)
        body = part.strip().strip("　")
        if not body:
            continue
        tail = _sig_tailcut(body)
        for t in ts:
            if body.endswith(t) or (tail and tail.endswith(t)):
                found += 1
                if at < 0:
                    at = max(start, 0)
                break
    return (found == 0), found, total, at


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


def _mask_persona_names(masked, text, rules):
    """レジストリに載っている**人格の氏名そのもの**を判定・書き直しから外す(長さ保存)。

    なぜ: 「ルカ・モドリッチ」の中の「ルカ」を禁止語として書き換えると
      『【実依頼 / from ルカ・モドリッチ】』→『from 俺・モドリッチ』になる
      (2026-08-16 の実測 msg 1538149223348834345 ほか。FP監査で最多の誤爆だった)。
      **氏名は呼称ゲートCの管轄**だ。口調ゲートDは名前の中に手を入れない。
    ★氏名の中だけを潰す= 単独で出た「ルカ」は今までどおり検知・書き直しの対象。
    ★masked と text は同じ長さである前提(_mask_protected が長さ保存だから成り立つ)。
    """
    try:
        if len(masked) != len(text):
            return masked
        names = [str(k) for k in ((rules or {}).get("personas") or {}) if len(str(k)) >= 3]
        if not names:
            return masked
        buf = list(masked)
        for nm in sorted(names, key=len, reverse=True):
            start = 0
            while True:
                i = text.find(nm, start)
                if i < 0:
                    break
                for j in range(i, i + len(nm)):
                    buf[j] = "　"
                start = i + len(nm)
        return "".join(buf)
    except Exception:
        return masked           # fail-open= マスクに失敗しても判定は従来どおり回す


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


# ============================================================================
# ★2026-08-16 追加(2件目)= **便の途中で声が入れ替わる**型を、1点だけ機械で掴む。
# ----------------------------------------------------------------------------
# 実物(軍議 msg 1538228314689376330・2026-08-16 01:50):
#   花海咲季の名義で出た便が、前半は咲季の声(「〜のよ」「〜わ」)で、末尾だけ書き手の地の声へ
#   落ち、**「わたしか咲季が答えるから」**= 自分を三人称で呼ぶ文になった。
# ★なぜ既存のゲートで掴めないか:
#   - 一人称ゲート(first_person_mismatch)= 「わたし」は咲季の正規一人称なので当たらない。
#   - 指紋ゲート(signature_absent)= 指紋語尾が**便全体でゼロ**の時しか鳴らない。前半に在れば黙る。
#   - 名義ゲートF(misattributed_speaker)= 便まるごとの取り違えを見る。**途中から**は対象外。
#   → 「自分の名前を三人称の主語に使う」は、どの人格でも成立しない**構造の矛盾**だ。
#     声の良し悪し(主観)を測らずに、途中交代を1点で掴める。
# ★警告のみ(applied には入れない)。名前を機械が別の語へ置換すると文が壊れる=直す先は生成側。
# ★既定=全人格が対象。外すのは写像へ `"self_name_ok": true` を足した人格だけ(方言と同じ形)。
_SELF_PARTICLES = ("が", "は", "も")
_KANJI4 = re.compile(r"^[一-鿿]{4}$")
_SENT_SPLIT = re.compile(r"[。\n!?！？]")


def _self_name_forms(persona, ent=None):
    """話者自身を指す呼び名の候補(フルネーム＋姓/名)を機械的に作る。

    ★増やしすぎない= 中黒で割る(ルカ・モドリッチ→ルカ/モドリッチ)か、
      **漢字4文字**を2+2で割る(花海咲季→花海/咲季)だけ。別名表は持たない
      (持てば20人格ぶんの保守が増え、判定材料が2本になる=ORG-11)。
    ★カタカナ名は割らない。実測した誤検知= ククール→「クク」「ール」で
      本文の「ル**ールは**」に当たった(2026-08-16・実データ1,443便の走査で4件)。
    ★**その人格の一人称に入っている名前は候補にしない**(早坂芽衣の一人称は
      ["芽衣","私"]= 「芽衣は〜」は自称であって三人称ではない。同走査で14件)。
    ★`forbidden` に既に載っている名前も外す(モドリッチの自称「ルカ」は
      既存の禁止語ゲートの担当= 二重に数えない)。
    """
    n = str(persona or "").strip()
    if not n:
        return []
    forms = [n]
    if "・" in n:
        forms += [p for p in n.split("・") if p]
    elif _KANJI4.match(n):
        forms += [n[:2], n[2:]]
    own = {str(x) for x in ((ent or {}).get("first_person") or [])}
    ng = {str(x) for x in ((ent or {}).get("forbidden") or [])}
    out = []
    for f in dict.fromkeys(forms):
        if len(f) >= 2 and f not in out and f not in own and f not in ng:
            out.append(f)
    return out


def self_third_person(persona, text, ent=None):
    """話者が**自分を三人称の他者として並べている**箇所を返す ((marker, index) or (None,-1))。

    ★条件は2つ**同じ文の中で**揃った時だけ= ①自分の一人称 ②自分の名前＋主語の助詞。
      「わたしか咲季が答えるから」= わたし(自分)と咲季(自分)が別人として並ぶ=構造の矛盾。
    ★名前を出すだけでは鳴らさない(「ククールが持つぜ」は自称のニュアンスで正常。
      実データ1,443便で、この「同じ文で併記」条件を足すと検知は 34件→数件へ落ちる)。
    ★判定は保護span(引用・コード・パス)を潰した本文で行う= 他人の発言の引用に
      自分の名前が出るのは正常なので数えない。
    """
    try:
        s = _mask_protected(text)
        if not s.strip():
            return (None, -1)
        own = [str(x) for x in ((ent or {}).get("first_person") or []) if str(x)]
        if not own:
            return (None, -1)          # 一人称が写像に無い人格は判定しない(fail-open)
        forms = _self_name_forms(persona, ent)
        if not forms:
            return (None, -1)
        base = 0
        for sent in _SENT_SPLIT.split(s):
            if sent and any(w in sent for w in own):
                for f in forms:
                    for p in _SELF_PARTICLES:
                        for cand in (f + p, f + "さん" + p):
                            i = sent.find(cand)
                            if i >= 0:
                                return (cand, base + i)
            base += len(sent) + 1
        return (None, -1)
    except Exception:
        return (None, -1)


# ============================================================================
# ★2026-08-16 追加= **名義の取り違え**(話者そのものが違う)を、口調の崩れと切り分ける。
# ----------------------------------------------------------------------------
# 実物(軍議 msg 1538227900598190230・2026-08-16 01:49:43):
#   改修αのセッションが1便の中で各部門へ向けた講義を書き、`[名前]` を**宛先の見出し**として
#   使った。機構は `[名前]` を**話者**として読むので、オタコンの言葉が
#   十王星南/早坂芽衣/アーモンドアイ/ルカ・モドリッチ/三笘薫/花海咲季 の名義とアイコンで出た。
#   さらに悪いことに、出力ゲートD(書き直し)が本文の「僕」を各名義の一人称へ**機械的に置換**し
#   (tone_audit の tone_fix 3件= 僕→俺 / 僕→俺 / 僕→わたし)、
#   **取り違えの証拠を消して"それらしい別人の声"に仕立てて**しまった。
#   実害= 花海咲季名義の便が「**わたしか咲季が答えるから**」= 自分を三人称で呼ぶ文になった。
#
# ★切り分けの原則= 「一人称が1つ違う」は口調の崩れだが、
#   **自分の一人称がどこにも無く、同じ部屋の"別の1人"の一人称だけが在る**なら、
#   それは崩れではなく **話者の取り違え**だ。直す先は言葉ではなく**名義**。
# ★決められない時は必ず None を返す(=従来どおりの書き直しへ倒す)。
#   曖昧なまま名義を動かす方が事故が大きい(名義はChamiの画面でそのまま人格に見える)。
def misattributed_speaker(persona, text, rules, roster):
    """名義の取り違えなら「本当の話者」を返す。決められなければ None。

    引数:
      persona : `[名前]` で解決された話者(正式名)。
      text    : そのブロックの本文。
      rules   : load_tone_rules() の戻り(dict) or None。
      roster  : **その部屋に居る人格の正式名**の列(dept_daemon の conf["personas"])。
                ★部屋の名簿の外へは絶対に出さない= resolve_persona_tag と同じ閉じた集合。

    返り値: 別人格の正式名(str) or None。

    None を返す条件(=判定しない):
      - rules 未ロード / persona が写像に無い / persona に first_person が無い
      - 本文に persona 自身の一人称が**1つでも**在る(=ただの口調の揺れ)
      - 他人格の一人称が **0人ぶん** or **2人以上ぶん** 見つかる(誰の言葉か決められない)
    """
    try:
        if not rules or not roster:
            return None
        ent = _persona_entry(rules, persona)
        if not ent:
            return None
        own = [str(x) for x in (ent.get("first_person") or []) if str(x)]
        if not own:
            return None
        s = _strip_quotes(text)          # 引用・コード・パスは数えない(誤爆の本命)
        if not s.strip():
            return None
        for m in own:
            if _scan_marker(s, m) >= 0:
                return None              # 自分の一人称が在る=取り違えではない
        # ★指紋語尾を持つ人格は、それが1つでも在れば**タグを信じる**。
        #   実物(軍議 msg 1538228314689376330)= 花海咲季のブロックは第1段落が
        #   「足しておく**わ**／描くの**よ**／鉄則**ね**」= 紛れもなく咲季の声で、
        #   最終段落だけが相方(オタコン)の声へ落ちていた=**便の途中で崩れた**形。
        #   これを丸ごとオタコン名義へ振り替えると、咲季の言葉をオタコンの口へ移してしまう。
        #   名義を動かす誤りは「他人のアイコンで別人の言葉を出す」=最も害が大きいので、
        #   証拠が割れている便は動かさない(=従来どおり口調ゲートDへ落とす)。
        sig = [str(x) for x in ((ent.get("signature_tails") or [])
                                + (ent.get("signature_endings") or [])) if str(x)]
        if sig:
            hit, found, _total, _at = signature_drift(s, sig)
            if found:
                return None              # 本人の指紋が在る=タグは正しい(途中で崩れただけ)
        cands = set()
        for name in roster:
            if _norm(name) == _norm(persona):
                continue
            e2 = _persona_entry(rules, name)
            if not e2:
                continue
            for m in (str(x) for x in (e2.get("first_person") or []) if str(x)):
                # ★「私」のように複数の人格が共有する一人称では決められない= 除外。
                #   distinctive(誰か1人の指紋になる一人称)だけを証拠に使う。
                if m in DISTINCTIVE_MARKERS and _scan_marker(s, m) >= 0:
                    cands.add(str(name))
        if len(cands) == 1:
            return cands.pop()
        return None                      # 0人=証拠なし / 2人以上=決められない
    except Exception:
        return None                      # fail-open= 判定に転んだら従来どおり


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
        # ★2026-08-15 追加: 構造ドリフト(敬体)を見るか。★既定=見ない。
        #   常体が正の人格へ人事部門が "plain_only": true を足した時だけ回る(定数群の説明)。
        want_polite = bool(ent.get("plain_only"))
        # ★2026-08-15 追加: 指紋語尾(必須語尾)。★既定=見ない。
        #   写像に `"signature_tails": ["わよ","わ","のよ",...]` を足した人格だけ回る。
        #   ★`signature_endings` は同義の別名として受ける(綴り揺れで静かに死なせない=
        #     forbidden / second_person_forbidden と同じ扱い)。
        sig = [str(x) for x in ((ent.get("signature_tails") or [])
                                + (ent.get("signature_endings") or [])) if str(x)]
        want_self = not bool(ent.get("self_name_ok"))     # ★2026-08-16 追加(既定=見る)
        if (not forbid and not ng2 and not want_dialect and not want_polite
                and not sig and not want_self):
            return out
        s = _mask_persona_names(_strip_quotes(text), text, rules)
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
        if want_polite:
            hit, hits, total, at = polite_drift(text)
            if hit:
                out.append({
                    "persona": str(persona or ""),
                    # marker は「何を見て鳴らしたか」がそのまま台帳に残る形にする
                    # (件数を後から数え直せる=一度の観測を状態の代理にしない・C-041)。
                    "marker": "敬体%d/%d文" % (hits, total),
                    "index": at,
                    "own_first_person": sorted(own),
                    "reason": "structural_polite",
                })
        if want_self:
            # ★2026-08-16 追加(便の途中で声が入れ替わる型・上の self_third_person の説明)。
            #   警告のみ= 名前を機械が置換すると文が壊れる。突き返し(session_relay)へ載せて
            #   **次の便の生成側**へ返すのが正しい直し方。
            _sf, _si = self_third_person(persona, text, ent)
            if _sf:
                out.append({
                    "persona": str(persona or ""),
                    "marker": "自分を三人称で呼んでいる(「%s」)" % _sf,
                    "index": _si,
                    "own_first_person": sorted(own),
                    "reason": "self_third_person",
                })
        if sig:
            hit, found, total, at = signature_drift(text, sig)
            if hit:
                out.append({
                    "persona": str(persona or ""),
                    # ★何を見て鳴らしたか(文数)と、**正しい語尾**をそのまま marker に載せる。
                    #   突き返し(session_relay)はこの marker を1行で出すので、
                    #   読んだ人格が「何を書けばよかったか」まで一目で分かる。
                    "marker": "指紋語尾なし(%d文中0件・正=%s)" % (total, "/".join(sig[:6])),
                    "index": at,
                    "own_first_person": sorted(own),
                    "reason": "signature_absent",
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
            if v.get("reason") in ("dialect_kansai", "signature_absent"):
                to = ""            # ★方言・指紋語尾は書き直さない(語尾の置換は文法が壊れる)=警告のみ
                #   ★指紋語尾は「無い」ことの検知だ。**足す**書き直しは再生成になる
                #     (「したよ」→「したわよ」で済む保証がどこにも無い)= 突き返しで人格が直す。
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

        # 長さ保存=添字はそのまま元テキストの添字。氏名の中(=呼称ゲートCの管轄)も外す。
        masked = _mask_persona_names(_mask_protected(text), text, rules)
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
