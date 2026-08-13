# -*- coding: utf-8 -*-
"""dept_daemon の発火判定(classify_work / split_work_marker)の回帰テスト。

背景(2026-07-20 組織層GL室): キャラが「回します」と返したのに機構は何も回さない事故。
真因=返信を書く判断者(キャラLLM)と発火の判断者(キーワード)が別人だったこと。
対処=キャラ自身の申告(WORK_MARKER)を返信末尾に載せ、同一判断者から発火させる。

★このテストの役目は「キーワードで頑張らせないこと」の固定。
  自然文の取りこぼしはキーワードでは直さない(直そうとすると必ず再発する)。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts", "llm"))
import dept_daemon as D  # noqa: E402
import session_relay as _R  # noqa: E402  ★relay_model / 起動文の回帰に使う(2026-07-26)

# 人格の原典(persona_context)の置き場。member_call の既定と同じ1正本を指す。
_CTX = os.path.join(D.ROOT, "local", "persona_context")

fails = []


def eq(got, want, label):
    if got != want:
        fails.append(f"{label}: got={got!r} want={want!r}")


# --- 1. WORK_WORDS と INFO_WORDS は重複しない(情報要求だけの文は発火しない) ---
overlap = [w for w in D.WORK_WORDS if any(i in w or w in i for i in D.INFO_WORDS)]
eq(overlap, [], "WORK_WORDSとINFO_WORDSの重複")
eq(D.classify_work("反映完了したら知らせて"), False, "報告依頼は作業ではない")
eq(D.classify_work("これ教えて"), False, "質問は作業ではない")

# --- 2. キーワードが効く素直な依頼 ---
eq(D.classify_work("ここ直して"), True, "素直な依頼")
eq(D.classify_work("削除お願い"), True, "お願い形")

# --- 3. ★自然文はキーワードでは取れない(仕様として固定する) ---
#     ここをTrueにしようとしてWORK_WORDSへ語を足すのは禁止。回収はマーカーの仕事。
eq(D.classify_work("設計して手足として動かして"), False,
   "★2026-07-20に実際に沈黙した実測文。キーワードでは取れないのが仕様(マーカーが回収する)")
eq(D.classify_work("この件、そっちで巻き取っておいてほしい"), False,
   "自然文はキーワードでは取れない(=マーカーが回収する)")

# --- 4. マーカーの抽出と除去 ---
body, dec = D.split_work_marker("了解、研究室へ回すわ。\n<<WORK>>")
eq(body, "了解、研究室へ回すわ。", "マーカー行を除去")
eq(dec, True, "申告を検出")

body, dec = D.split_work_marker("おはよう。今日も張り切っていくわよ。")
eq(body, "おはよう。今日も張り切っていくわよ。", "マーカー無しは素通し")
eq(dec, False, "申告なし")

body, dec = D.split_work_marker("受けたわ。 <<WORK>> ")
eq(body, "受けたわ。", "行内マーカーでも拾って除く")
eq(dec, True, "行内マーカーを検出")

body, dec = D.split_work_marker("やっておくね<<WORK>>")
eq(body, "やっておくね", "本文末尾に直結したマーカーも除去")
eq(dec, True, "直結マーカーを検出")

body, dec = D.split_work_marker("<<WORK>>")
eq(body, "", "マーカーのみなら本文は空(呼び出し側が回送へ倒す)")
eq(dec, True, "マーカーのみでも申告は立つ")

eq(D.split_work_marker(None), ("", False), "Noneでも落ちない")

# --- 5. 部門の性質と発火経路の対応(棚卸しの固定) ---
#     forward_all=中継部屋 / work_scope=部屋内完結 / どちらも無し=会話部屋(申告時のみ回送)
relay = sorted(k for k, v in D.DEPT_CONF.items() if v.get("forward_all"))
# ★forward_all は「**main箱(=研究室HQの受信箱)を読む対話セッションが居る部屋**」だけに付ける。
#   main箱はHQの箱であって各部門の箱ではない。部門に付けると依頼がHQへ流れてHQを汚す。
#   2026-07-20 21:20 Chami明示で組織層3室(aegis-gl/keiei-kikaku/platform-se)から外した。
#   原文=「便をHQへ回送する設定なので→これが間違い。ここがこのカテゴリIDで起こった内容を
#   改修する場所」。組織層の部門は**組織層の中で完結**させる。
#   ★外しても沈黙しない: 実作業依頼は WORK_MARKER(キャラ申告)+申告漏れ救済で回送される。
#     forward_all はマーカーが無かった時代の代替手段で、いまは冗長かつ有害だった。
#   残す2室の理由:
#     hq            研究室HQセッションがmain箱を読む本来の宛先
#     research-room 事業層(ad研究室 Vol.9セッションが受ける)=**他オーナーにつき変更しない**
eq(relay, ["hq", "research-room"],
   "★forward_allはmain箱を読む対話セッションが居る部屋のみ(組織層の部門には付けない)")
talk = sorted(k for k, v in D.DEPT_CONF.items()
              if not v.get("forward_all") and not v.get("work_scope"))
# ★hr-contextを外した(2026-07-20 Chami指示・RULES §7.6): 人事の部屋で人事の作業ができないのは
#   職責と権限の食い違い。work_scopeを付与して部屋の中で完結できるようにした。
#   会話専用に残してよいのは**質問部屋**だけ(答えるのが仕事。ツールを持たせると
#   「調べて」の一言でファイルを触りに行く)。
# consult-intel(🐧コンサル情報)は2026-07-20の配線時点では会話専用だった。
# ★RULES §7.6の判断=**完了(2026-07-20・配線した経営企画セッションが決定)= work_scopeを付与**。
#   理由: この部門の目的②が「local/consult_intel/🐧さん情報.mdへ蓄積する」=ファイル作業であり、
#   会話専用のままだとアーモンドアイは**自分の主たる職務に対して「研究室へ回す」としか言えない**
#   (can-doとwill-doの食い違い=ククールが踏んだ穴と同型)。
#   さらに work_generate 経路は O3 の allowlist で固めてあり、無制限な generate() より安全側に倒れる。
#   範囲は蓄積と整理まで。施策の実行(投稿・訴求文の変更・作品選定の確定)は各部門の職責として持たせない。
# ★2026-07-20 21:20: forward_allを外した組織層3室がここへ移った。会話専用に見えるが理由が違う:
#   llm-qa       質問部屋(答えるのが仕事。ツールを持たせると「調べて」でファイルを触りに行く)
#   aegis-gl     **GL(対話セッション)が常駐し自分で改修する部屋**。アメスは補佐で即応を担う。
#                実作業の主体が対話セッション側なので、デーモンにツールを持たせない。
#   keiei-kikaku 部門の設立・改廃は台帳と艦隊を触る=対話セッションが責任を持つ
#   platform-se  人格未定(RULES §7.5)。職責が確定するまでツールを渡さない
# ★どの部屋も作業依頼で沈黙はしない: WORK_MARKER+申告漏れ救済でmain箱へ回送される。
# ★2026-07-26 機微2部屋 past-room / future-room を追加(Chami直接指示・実装Go済)。
#   この2部屋は "conversation_only": True の**多人格モード**(DEPT_CONF の "personas")で、
#   回送もwork_generateもしない=work_scopeを持たないのが正しい姿。
#   ここは「DEPT_CONFに何が居るか」の名簿検査なので、部屋を増やせば必ず更新が要る
#   (挙動の期待値が変わったのではない)。
# ★2026-07-27 消費者不在だった5部屋を配線(研究室HQ発注)。全て work_scope 無し=ここへ入る。
#   kaizen-analyst    改善提案。**実装しない**部門(実装は各担当部門の職責)
#   incident          事故対応。切り分けと引き渡しが仕事で、復旧の実作業は担当部門が持つ
#   system-engineer-b 改修β。★改修の実作業はαが担当(2026-07-21 ORG-32)=βに実装権は与えない
#   dream-care        機微室。conversation_only(past-room/future-roomと同じ)
#   health-log        機微室。conversation_only(同上)
#   ★会話から始める=発注の指示。実作業が要るようになったら work_scope を足す(可逆)。
#   ★作業依頼で沈黙はしない: WORK_MARKER+申告漏れ救済でmain箱へ回送される(既存と同じ)。
# ★★2026-08-05 aegis-gl と platform-se をこの一覧から**外した**(work_scopeを付与した)。
#   研究室HQ・Chami「任せる」(msg 1534333840468873436)。理由の詳細は DEPT_CONF 側の注記。
#   要点= 上の101-104行の前提が2つとも実測で崩れていた:
#     aegis-gl    「実作業の主体はGLの対話セッション側」→ その窓が開いていない時間帯、
#                 この部屋は計画を返すだけで誰も手を動かさない部屋になっていた
#                 (2026-08-04 22:44受領→23:37時点で commit 0 / change_log 0 / work_audit 0)。
#     platform-se 「人格未定だからツールを渡さない」→ 2026-07-27 に一ノ瀬怜で確定済み=理由が消滅。
#   ★Chami裁定 C-027(各部門は自分の持ち場のコードも配線も書いてよい)と正面から矛盾していた。
#   ★不可逆(push/デプロイ/削除/課金/公開)は work_scope の「範囲外」節で従来どおり回送させる。
# ★2026-08-05 manga-shorts を追加(名簿の追従漏れ。**この行はずっと赤かった**=部屋を足した時に
#   一覧を更新していない。挙動の期待値が変わったのではなく、実在の部屋を書き足しただけ)。
#   ★常に赤い検査は読まれなくなる(§3「常に誤発火する安全網は無視される」)ので合わせておく。
# ★2026-08-13 kukuru-nakama を追加(名簿の追従漏れ。**8/5に部屋を足してからずっと赤かった**)。
#   実在の部屋を書き足しただけで、期待値の意味は変えていない。
#   ★新しい部屋を足したらこの一覧も足すこと=足さないとこの検査が常に赤くなり、
#     一緒に並んでいる**本物の退行が埋まる**(HQ指摘 2026-08-13)。
eq(talk, ["dream-care", "future-room", "health-log", "incident", "kaizen-analyst",
          # ★2026-07-27 report-notify 追加。一方通行だった報告通知部屋を双方向にした
          #   (Chamiが3回頼んだ件)。通知の出力経路には触らないので conversation_only。
          "keiei-kikaku", "kukuru-nakama", "llm-qa", "manga-shorts", "past-room",
          "report-notify", "system-engineer-b"],
   "会話専用の部屋(実作業は対話セッション側が担う)")
# 残りは全て work_scope 持ち=マーカー申告でwork_generateへ二段昇格する
for name, conf in D.DEPT_CONF.items():
    if name not in relay and name not in talk:
        if not conf.get("work_scope"):
            fails.append(f"{name}: work_scopeも forward_all も無い(消費者不在の穴)")

# --- 6. 申告漏れの監査と救済(2026-07-20 Chami「着手して」) ---
#     残る唯一の再発経路=キャラが約束したのに申告を書き漏らす便。出力側の事後監査で拾う。
eq(bool(D.find_promise("あぁ、受けたぜ。少し待ってろ。")), True, "約束表現を検出")
eq(D.find_promise("オレが手をつけるぜ"), "手をつける", "実測された約束文(2026-07-20 hr-context)")
# ★初版のPROMISE_WORDS(〜ておく形のみ)が1語も拾えなかった実測文。口語の語尾に頼らない回帰
eq(bool(D.find_promise("あぁ、了解だ——聞き取り項目の一覧な。整理してそっちに出すぜ。少し待ってろ。")),
   True, "★実測の口語約束(2026-07-20 hr-context・初版が取りこぼした文)")
eq(D.find_promise("それは無理だな。研究室に聞いてくれ。"), None, "約束していない返信は素通し")
eq(D.find_promise("いい天気だな。"), None, "雑談は素通し")
# ★★実測の**誤検出**(2026-07-20 21:10 consult-intel)。裸のテ形「整理して」を入れていたため
#   「約束」ではなく**否定文の説明**に一致し、main箱へ誤回送→無人代打が二重応答した。
#   誤検出はタダではない(利用者に見える実害)ので、descriptiveな地の文を拾わないことを固定する。
eq(D.find_promise("受け取って整理してファイルに積んで満足、は成果じゃないわ。"), None,
   "★実測の誤検出: 地の文のテ形は約束ではない(consult-intel・二重応答の原因)")
eq(D.find_promise("接続不良の原因切り分けと復旧、定期検査が担当範囲ね。"), None,
   "★担当範囲の説明文を約束と誤認しない(platform-se)")
# ただし同じ動詞でも**意志の文末形**なら拾う(再現率を落とさないことの確認)
eq(bool(D.find_promise("整理して出すぜ。")), True, "テ形+意志の文末形は拾う")
eq(bool(D.find_promise("作業が要る話は研究室に回すわ。")), True, "回送の約束は拾う")

# 一致箇所の前後が証拠として残る(reply切り詰めで一致語が消える事故への対処)
_ctx = D._match_context("あ" * 300 + "出すぜ" + "い" * 300, "出すぜ")
eq("出すぜ" in _ctx, True, "matched_contextに一致語が含まれる")
eq(len(_ctx) <= 90, True, "matched_contextは前後40字程度に収まる")
eq(D.find_promise(None), None, "Noneでも落ちない")
eq(D.find_promise(""), None, "空でも落ちない")

# 監査ログは一時ファイルへ逃がす(本番の local/_marker_audit.jsonl を汚さない)
import tempfile  # noqa: E402
_orig_audit = D.MARKER_AUDIT
D.MARKER_AUDIT = os.path.join(tempfile.mkdtemp(), "_marker_audit.jsonl")
try:
    _rec = {"msg_id": "t1", "content": "これ整理しておいてほしい"}
    # 申告あり=正常。救済は不要(二重発火させない)
    eq(D.audit_marker("t", _rec, "受けたぜ", True, False), False, "申告ありは救済しない")
    # ★本命: 約束しているのに申告なし・キーワードも不一致=旧実装なら沈黙していた便
    eq(D.audit_marker("t", _rec, "あぁ、やっておくぜ", False, False), True,
       "★約束あり・申告なし・kw不一致=救済する(沈黙させない)")
    # キーワードが既に拾っている便は回送済み=沈黙事故ではないので分子に数えない
    eq(D.audit_marker("t", _rec, "あぁ、やっておくぜ", False, True), False,
       "kwが拾っている便は救済不要(分母外)")
    # 約束していない返信は記録も救済もしない
    eq(D.audit_marker("t", _rec, "おはよう。いい天気だな。", False, False), False,
       "雑談は記録も救済もしない")

    _events = [json.loads(l) for l in open(D.MARKER_AUDIT, encoding="utf-8")
               if l.strip()]
    eq([e["event"] for e in _events],
       ["declared", "miss", "miss_covered_by_keyword"],
       "監査ログは declared/miss/miss_covered_by_keyword の3種のみ(雑談は残さない)")
    eq(_events[1]["matched"], "やっておく", "取りこぼし便に検出語が残る")
finally:
    D.MARKER_AUDIT = _orig_audit

# --- 7. 名指しの後の「会話の継続」(2026-07-22 Chamiが踏んだ事故) ---
#     実測ログ: 16:29「三笘さんと話したい」→三笘が応答。16:31 その返事の続きで人格が常駐へ戻り、
#     さらに回送まで走った。=会話が1往復で切れていた。
#     ★時刻は now= で注入する(21分待たない)。


#     ★★2026-07-26: **DEPT_CONF から members が無くなった**(personas へ統合。上の §5 参照)。
#       ここは「members 経路のコードが壊れていないこと」の回帰なので、**合成confで回す**。
#       - コードを消さない(C-003)以上、動くことは押さえておく必要がある
#       - 実運用の部屋を使うと、名簿の運用変更でこのテストが赤くなり教訓が消える
#       実運用側の回帰(=members を持つ部屋が0で、名指し経路が発火しないこと)は §5 と
#       下の「安全弁」ループが担当する。


def _room(dept, conf=None):
    """__init__の副作用(トークン読み込み等)を避け、判定に要る分だけ持つDaemonを作る。"""
    d = D.Daemon.__new__(D.Daemon)
    d.dept, d._member, d._member_sticky = dept, None, None
    d.conf = conf if conf is not None else D.DEPT_CONF[dept]
    return d


def _who(d, text, now):
    m, why = d._resolve_member(text, D.classify_work(text), now=now)
    return (m["persona"] if m else "常駐:" + d.conf["persona"]), why


# 旧 shorts-analyst(常駐=アーモンドアイ / メンバー=三笘薫)を合成で再現する
_LEGACY = {
    "persona": "アーモンドアイ",
    "character": D.DEPT_CONF["shorts-analyst"]["character"],
    "members": ({"persona": "三笘薫",
                 "character": D.os.path.join(D._CHAR, "mitoma.md"),
                 "aliases": ("三笘", "みとま", "ミトマ", "mitoma")},),
}

T0 = 1_000_000.0
r = _room("shorts-analyst", _LEGACY)
eq(_who(r, "三笘さんと話したい", T0), ("三笘薫", "名指し呼び出し"), "1 名指しヒット")
eq(_who(r, "君を最高にリスペクトしている。色々部門の仕事を任せたいから頼む。思って。", T0 + 120),
   ("三笘薫", "名指しの継続"), "★2 実測の事故文(名前が無い返事の続き)= 三笘が継続する")
eq(_who(r, "ありがとう", T0 + 200), ("三笘薫", "名指しの継続"), "3 継続")
eq(_who(r, "アーモンドアイ、KPIの数字は?", T0 + 260),
   ("常駐:アーモンドアイ", ""), "4 常駐を呼んだら継続を打ち切る")
eq(_who(r, "最近どう?", T0 + 300), ("常駐:アーモンドアイ", ""), "5 打ち切り後は常駐のまま")

r = _room("shorts-analyst", _LEGACY)           # 6 期限切れ(20分)
_who(r, "三笘さんと話したい", T0)
eq(_who(r, "ありがとう", T0 + 21 * 60), ("常駐:アーモンドアイ", ""), "6 21分後は期限切れ")
r = _room("shorts-analyst", _LEGACY)
_who(r, "三笘さんと話したい", T0)
eq(_who(r, "ありがとう", T0 + 19 * 60), ("三笘薫", "名指しの継続"), "19分後はまだ継続(境界)")

# ★ゲート4: 作業依頼は従来どおり(常駐+回送)。ここを緩めると work_generate も回送も止まる。
r = _room("shorts-analyst", _LEGACY)
_who(r, "三笘さんと話したい", T0)
eq(_who(r, "ここ直して", T0 + 60), ("常駐:アーモンドアイ", ""), "作業依頼は常駐へ戻す(既存の扱い)")
eq(_who(r, "ありがとう", T0 + 90), ("常駐:アーモンドアイ", ""), "作業依頼で継続は切れている")

# ★安全弁: membersを持たない部屋は1ミリも変わらない(必ず常駐)
for _dept in sorted(k for k, v in D.DEPT_CONF.items() if not v.get("members")):
    _r = _room(_dept)
    for _t, _dt in (("三笘さんと話したい", 0), ("ありがとう", 120)):
        eq(_r._resolve_member(_t, D.classify_work(_t), now=T0 + _dt), (None, ""),
           f"membersなしの部屋は従来どおり({_dept}/{_t})")
# ★★2026-07-26 Chami直接指示(選択肢C)で **members を personas へ統合**した。
#   原文=「デーモンが処理するのはもうやめたい」「名指しする時もあるし、しない時もある。
#   毎回名指しするのは面倒。状況や各の特徴強みに応じて、誰が演じて前に立つかを判断して話してほしい」
#   → **members を持つ部屋は0**になり、名指しも relay(部屋の永続セッション)が受ける。
#   ★member_call / _resolve_member の**コードは残っている**(C-003=消さない)。
#     上のループで全21室を通しており、「members が無い部屋では必ず常駐(=経路が発火しない)」
#     ことをそのまま回帰として押さえている。
eq(sorted(k for k, v in D.DEPT_CONF.items() if v.get("members")), [],
   "★members は personas へ統合済み(名指しもセッションが受ける)")
# 旧 members の3室が personas 側で名簿を持っていること(顔ぶれを落としていないことの確認)
for _need, _who in (("consult-intel", "三笘薫"), ("copy-director", "三笘薫"),
                    ("shorts-analyst", "三笘薫")):
    _roster = [p["persona"] for p in (D.DEPT_CONF[_need].get("personas") or ())]
    eq(_who in _roster, True, f"{_need} の personas に {_who} が居ること")
# ★relayを持つ部屋(=research-room以外の20室)は personas か単独人格のどちらかで必ず名義が引ける
for _d, _v in sorted(D.DEPT_CONF.items()):
    if _v.get("session_relay"):
        eq(bool(_v.get("personas") or _v.get("character")), True,
           f"{_d}: relay室に人格の正本が無い")
# ★★2026-07-26 **方針を反転した**(Chami発注・8月6日からの1週間の不在に備える)。
#   旧= 「hqのpersonasはアメスだけ。**アロンソを入れない**(relayが演じたら本人を騙る)」。
#   新= **アロンソを筆頭に入れる**。理由は下の在席判定の回帰がそのまま根拠になっている:
#     handle() は `if self.interactive_alive():` で**人が開いた窓が生きている間はrelayも精霊も
#     動かさない**ので、**同じ人が2人同時に存在することは構造上あり得ない**。
#     relayが出るのは本人が居ない時だけ= それは騙りではなく**引き継ぎ**。
#   ★この2室だけ。他19室の personas / relay_model / 起動文は**1文字も変えていない**。
for _d, _who, _char in (("hq", "シャビ・アロンソ", "alonso.md"),
                        ("research-room", "ルカ・モドリッチ", "modric.md")):
    _c = D.DEPT_CONF[_d]
    _roster = [p["persona"] for p in _c["personas"]]
    eq(_roster[0], _who, f"★{_d} の personas の**筆頭**は部屋の主({_who})")
    eq("アメス" in _roster, True, f"★{_d} の personas にアメスが残っている(留守番の補佐)")
    eq(_c.get("lead_persona"), _who, f"★{_d} の既定で前に立つのは {_who}")
    # ★資産の実在(原典の無いキャラは演じない= 2026-07-20 Chami指示)。
    #   ここが落ちたら「演じられない人格を名簿に入れた」= 入れてはいけない状態。
    _cf = [p["character"] for p in _c["personas"] if p["persona"] == _who][0]
    eq(os.path.basename(_cf), _char, f"{_d}: {_who} のcharacterfileのパス")
    eq(os.path.isfile(_cf), True, f"★{_d}: {_who} のcharacterfileが実在すること")
    eq(D.persona_source_exists(_CTX, os.path.splitext(_char)[0]), True,
       f"★{_d}: {_who} の原典(persona_context)が実在すること")
    # ★relayのモデル= 横断裁定・真因追跡・出荷前レビューの部屋なので最上位(CLAUDE.md §5.1)。
    # ★2026-08-13 期待値を「文字列 'opus' と完全一致」から**opus系に解決されること**へ直した。
    #   旧= `relay_model(_c) == "opus"`。ところが relay_model() は別名を実物のモデルIDへ
    #   ピン留めして返す(_pin_model)ので、hq='claude-opus-5' / research-room='opus'→
    #   'claude-opus-4-8' となり**両方とも赤**だった=**モデルを1つ上げるたびに落ちる検査**。
    #   この検査が守りたいのは「安い方へ落としていないこと」(C-014・品質を落とした節約をしない)で、
    #   **どのIDに固定されているか**ではない。だから系列で見る。
    eq(str(_c.get("relay_model") or "").startswith(("opus", "claude-opus")), True,
       f"★{_d} のrelayは opus 系を指定していること(品質を落とした節約をしない)")
    eq(_R.relay_model(_c).startswith("claude-opus"), True,
       f"★{_d}: relay_model() が opus 系の実IDへ解決されること")
    # ★起動文に渡す読み物は**実在するものだけ**(存在しないパスを読ませない)。
    _items = _R._reading_items(_c)
    eq(len(_items) > 0, True, f"★{_d}: 起動時に読む資料が1件以上実在すること")
    eq(all(os.path.isfile(p) for p, _n in _items), True,
       f"★{_d}: 起動文に渡すパスが全て実在すること")
    _boot = _R._boot_prompt(_d, _c, 1)
    eq(all(p in _boot for p, _n in _items), True, f"★{_d}: 起動文に資料のパスが載っていること")
    eq("読んでから答え" in _boot, True, f"★{_d}: 「読んでから答えろ」が起動文に入っていること")
    eq(_c.get("forward_all"), True, f"★{_d} のforward_allは維持(便は本人のmain箱へ届き続ける)")
# ★hq の読み物は §0「Vol.6 開始手順」の順(引き継ぎ書→RULES→裁定カタログ→台帳)。
_hq_read = [p for p, _n in _R._reading_items(D.DEPT_CONF["hq"])]
eq("引き継ぎ書_研究室HQ_Vol" in _hq_read[0], True, "★hqは最新の引き継ぎ書を**最初に**読む")
for _must in ("RULES.md", "裁定カタログ.md", "pending_decisions.md", "hq_open_items.md",
              "Chami台帳.md"):
    eq(any(_must in p for p in _hq_read), True, f"★hqの読み物に {_must} が入っていること")
# ★research-room へは**HQの引き継ぎ書を渡さない**(事業部の文脈。役と職責を取り違えるため)。
eq(any("引き継ぎ書_研究室HQ" in p for p, _n in _R._reading_items(D.DEPT_CONF["research-room"])),
   False, "★research-roomにHQの引き継ぎ書を渡していない")
# ★relay_model を持たない部屋は**既定に従う**こと(部屋ごとに勝手なモデルが混ざらない)。
# ★2026-08-13 期待値を直した。旧は「hq/research-room 以外は relay_model を持たない・既定は
#   sonnet」だったが、①既定(RELAY_MODEL)が opus になり(C-014「既定は Opus」)②aegis-gl が
#   'claude-opus-5' を明示するようになり、**28部屋ぶんが常に赤**だった。
#   → 部屋名の一覧(すぐ腐る)ではなく**規則**で見る= 明示が無ければ既定・どの部屋も opus 系。
for _d, _v in sorted(D.DEPT_CONF.items()):
    if _v.get("relay_model") is None:
        eq(_R.relay_model(_v), _R._pin_model(_R.RELAY_MODEL),
           f"{_d}: relayのモデルは既定に従う(部屋ごとの独自値を持たない)")
    eq(_R.relay_model(_v).startswith("claude-opus"), True,
       f"★{_d}: relayのモデルが opus 系であること(安い方へ落としていない・C-014)")
    if _d in ("hq", "research-room"):
        continue
    eq(_v.get("boot_reading"), None, f"{_d}: boot_reading を持たない(起動文が増えない)")
    # ★lead_persona は「複数人格の部屋で既定に前へ立つ人」。持つこと自体は正しい(manga-shorts等)。
    #   守るべき不変条件は**その人が名簿に居ること**(居ない人を既定に据えると誰も出られない)。
    if _v.get("lead_persona"):
        eq(_v["lead_persona"] in [p["persona"] for p in (_v.get("personas") or [])], True,
           f"★{_d}: lead_persona({_v['lead_persona']})が personas に実在すること")
eq(D.resident_aliases(D.DEPT_CONF["shorts-analyst"]), ("アーモンドアイ", "アイ"),
   "常駐の別名はpersonaから作る(本名+末尾2文字)")
# ★短い名前は切らない(「アメス」→「メス」のような意味の壊れた別名を作らない)
eq(D.resident_aliases({"persona": "アメス"}), ("アメス",), "3文字の常駐名は切らない")
eq(D.resident_aliases({"persona": "ヴィルシーナ"}), ("ヴィルシーナ",),
   "長音で始まる断片(ーナ)は別名にしない")
eq(D.resident_aliases({}), (), "personaが無くても落ちない")

# --- 7. 待ちの秒数(2段構え)が session_relay と dept_daemon で食い違わないこと ---
# ★★2026-07-27 の恒久対処の固定。02:35:39の便は「会話300秒」の予算で殺されたが、
#   中身は実装作業で、**セッションは作業を終えて commit までしていた**(86ef339)。
#   → soft(ここでは殺さない)/ hard(ここで初めて殺す)の2段にした。
#   ここが落ちる時は「**片方だけ直した**」時だ。両方を揃えてから直すこと。
eq(D.PRINT_TIMEOUT, _R.RELAY_TIMEOUT, "★会話便のsoftが2ファイルで一致していること")
eq(D.WORK_TIMEOUT, _R.RELAY_WORK_TIMEOUT, "★作業便のsoftが2ファイルで一致していること")
eq(_R.hard_limit(False), _R.RELAY_TIMEOUT * _R.RELAY_HARD_FACTOR, "会話便のhardはsoftの2倍")
eq(_R.hard_limit(True), _R.RELAY_WORK_TIMEOUT * _R.RELAY_HARD_FACTOR, "作業便のhardはsoftの2倍")
eq(_R.RELAY_HARD_FACTOR >= 2, True, "hardはsoftより長いこと(2段になっていること)")
# ★キューのリースは**作業便のhardより長い**こと。短いと待っている最中にリースが切れ、
#   同じ便が再配達されて**同じ作業を2回走らせる**(=リトライを増やさない、に反する)。
sys.path.insert(0, os.path.join(D.ROOT, "scripts", "queue"))
import leasequeue as _Q  # noqa: E402
eq(_R.hard_limit(True) + D.QUEUE_LEASE_MARGIN > _R.hard_limit(True), True,
   "リースの余白が正であること")
eq(_R.hard_limit(True) + D.QUEUE_LEASE_MARGIN > _Q.DEFAULT_LEASE_SEC, True,
   "★relay部屋のリースは既定(900秒)より長い=作業便のhardを跨げること")
# ★relay() が on_slow(中間通知の合図)を受け取れること= 呼び元との約束を固定する。
import inspect  # noqa: E402
eq("on_slow" in inspect.signature(_R.relay).parameters, True,
   "★relay() が on_slow を受け取ること(中間通知の合図)")
eq("hard_timeout" in inspect.signature(_R._run_claude).parameters, True,
   "★_run_claude が hard_timeout を受け取ること(2段構えの待ち)")

# --- 7.5 本走の開始でリースを張り直す(2026-08-13・HQ恒久依頼1の固定) ---
# ★事故= `DISPATCH-hq-1786600848694`(15:00:50 claim)は前処理(引き継ぎ生成419秒)＋本走1,197秒で
#   **1,619秒**占有したのに、リースは hard+余白= 1,500秒しか無かった。119秒足りず走行中に「暇」へ
#   戻り、daemon_keeper の載せ替えに 15:27:49 killされた=20分ぶんの返信が送信の1秒前に消えた。
# ★穴の形= リースが **relayのhardしか見ていない**(同じclaimの中の前処理を1秒も数えない)。
#   → 前処理が終わって本走へ入る所でリースを張り直す。ここが落ちる時は、その合図か
#     張り直しの呼び出しが**消えている**時だ(HQの実測=extend()は在るのに呼び出しが0箇所だった)。
eq("on_main_start" in inspect.signature(_R.relay).parameters, True,
   "★relay() が on_main_start を受け取ること(本走の開始の合図)")
_rel_src = open(_R.__file__, encoding="utf-8", errors="replace").read()
_dd_src = open(D.__file__, encoding="utf-8", errors="replace").read()
eq(_dd_src.count("on_main_start=_on_main_start"), 1,
   "★dept_daemon が relay() へ本走の合図を渡していること")
eq(".extend(" in _dd_src, True,
   "★dept_daemon が LeaseQueue.extend() を実際に呼んでいること(在るだけで呼ばれない、を防ぐ)")
eq(hasattr(_Q.LeaseQueue, "extend"), True, "LeaseQueue に extend が在ること")
# ★合図を出す位置= 前処理(引き継ぎ生成)の**後**・本走(_run_audited)の**前**。
#   位置が前後すると意味が消える(前処理の前で張り直しても前処理ぶんを食う)。
_i_handoff = _rel_src.find("handoff_path, head = _write_handoff(")
_i_signal = _rel_src.find("on_main_start(hard)")
_i_run = _rel_src.find("_run_audited(boot")
if _i_run < 0:
    _i_run = _rel_src.find("data, rc, out = _run_audited(")
eq(_i_handoff > 0 and _i_signal > _i_handoff, True,
   "★本走の合図は引き継ぎ生成(前処理)より後で出すこと")
eq(_i_run > 0 and _i_signal < _i_run, True,
   "★本走の合図は _run_audited(本走)より前で出すこと")
# ★止血(QUEUE_LEASE_MARGIN 900)を**外したまま**であること= 二重に塞がない(HQの指示)。
#   余白で前処理を包む設計に戻っていたら、ここが落ちる。
eq(D.QUEUE_LEASE_MARGIN < _R.HANDOFF_TIMEOUT, True,
   "★余白で前処理(引き継ぎ生成420秒)を包み直していないこと=恒久策と二重に塞がない")
# ★extend() が本当にリースを先へ動かすこと(実物で1回通す)。
_tmpdb = os.path.join(D.ROOT, "local", "_work", "test_lease_extend.db")
os.makedirs(os.path.dirname(_tmpdb), exist_ok=True)
if os.path.exists(_tmpdb):
    os.remove(_tmpdb)
_q = _Q.LeaseQueue(_tmpdb, lease_sec=60)
_q.enqueue({"msg_id": "T-lease-1", "content": "x"}, msg_id="T-lease-1", dept="aegis-gl")
_c = _q.claim(dept="aegis-gl", who="test")
eq(bool(_c), True, "検証用の便を claim できること")
if _c:
    _before = _q._db.execute("SELECT lease_until FROM queue WHERE id=?", (_c["id"],)).fetchone()[0]
    eq(_q.extend(_c["id"], lease_sec=3600), True, "★extend() が処理中の行に効くこと")
    _after = _q._db.execute("SELECT lease_until FROM queue WHERE id=?", (_c["id"],)).fetchone()[0]
    eq(_after - _before > 3000, True, "★extend() でリースの期限が実際に先へ動くこと")
try:
    _q._db.close()
    os.remove(_tmpdb)
except OSError:
    pass

# --- 7.6 事故そのものを再現する(keeperの目で見る・2026-08-13) ---
# ★ここが本体の証拠だ。上の 7.5 は「配線が在るか」しか見ていない。
#   keeper が「暇」と判定する道具(daemon_keeper._inflight_depts)へ**同じ形の便**を通し、
#   ①張り直さないと 1,600秒の時点で暇に見える(=killされる) ②張り直せば処理中に見える、を出す。
# ★時計は動かせないので、**リース秒数を前へずらして同じ lease_until を作る**=
#   「claimの419秒後に1,500秒で張り直す」は「今 1,919秒で張り直す」と同じ期限になる。
sys.path.insert(0, os.path.join(D.ROOT, "scripts", "_daemons"))
import daemon_keeper as _K  # noqa: E402
_tmpdb2 = os.path.join(D.ROOT, "local", "_work", "test_lease_inflight.db")
if os.path.exists(_tmpdb2):
    os.remove(_tmpdb2)
_lease = _R.hard_limit(True) + D.QUEUE_LEASE_MARGIN            # いまの実物のリース(1,500秒)
_pre = 419                                                     # 事故便の前処理(引き継ぎ生成)の実測
_q2 = _Q.LeaseQueue(_tmpdb2, lease_sec=_lease)
_q2.enqueue({"msg_id": "T-inflight-1", "content": "x"}, msg_id="T-inflight-1", dept="hq")
_c2 = _q2.claim(dept="hq", who="test")
import time as _time  # noqa: E402
_t0 = _time.time()
_occupied = _pre + 1197                                        # 事故便の実占有=1,616秒
eq(_lease < _occupied, True,
   "★前提: リース(%d秒)は事故便の占有(%d秒)より短い=張り直しが要る" % (_lease, _occupied))
eq(_K._inflight_depts(_tmpdb2, now=_t0 + _occupied), [],
   "★事故の再現: 張り直さないと本走の途中で「暇」に見える(=載せ替えにkillされる)")
_q2.extend(_c2["id"], lease_sec=_pre + _lease)                 # = 前処理の後に張り直した状態
eq(_K._inflight_depts(_tmpdb2, now=_t0 + _occupied), ["hq"],
   "★恒久策: 本走の開始で張り直せば、同じ時刻に「処理中」と見える(守られる)")
eq(_K._inflight_depts(_tmpdb2, now=_t0 + _pre + _lease + 60), [],
   "★張り直しても期限は有限=デーモンが死んだら再配達へ戻ること(永久ロックにしない)")
try:
    _q2._db.close()
    os.remove(_tmpdb2)
except OSError:
    pass

if fails:
    print("FAIL " + str(len(fails)) + "件")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("PASS dept_daemon 発火判定"
      "(classify_work / split_work_marker / 部門棚卸し / 申告漏れ監査 / 名指しの継続 / "
      "待ちの秒数の一致)")
