#!/usr/bin/env python3
"""部屋ごとの永続Claude Codeセッションへ「原文のまま」受け渡す配送モジュール。

なにものか(2026-07-25 Chami直接指示「デーモンが会話して処理する機能を廃止して、
セッションに受け渡すように改善してほしい」・実装Go済):
  正本の提案書= D:\\SougouStartFolder\\ChatGPT提案書_デーモンとDiscord-Claude連携改善_2026-07-25.md
  (特に §5「一部屋に一つの論理セッション」/ §6「状態を分けて記録する」/ §10 優先度2 /
   §13「行わない方がよいこと」)

なぜ要るのか:
  dept_daemon.generate() は毎回 `claude --print` を**使い捨て**で起動し、部門JSONLの記憶を
  プロンプトへ注入していた。これは同じセッションの再開ではなく**記憶を注入した疑似会話**で、
  Chamiが期待する「この部屋へ書けば、いつものセッション本人が続きから対応する」と食い違う。
  ここでは `claude -p --resume <session_id>` = **本物のセッション再開**へ置き換える。

役割分担(提案書§1):
  デーモンは頭脳ではなく**証拠を残す配送係**。このモジュールは
    - 投稿を要約も改変もせずに封筒へ入れて渡す
    - 部屋→セッションの対応表(1正本)を原子的に更新する
    - 遷移(leased/running/completed/failed/rotated/slow)を1行ずつ記録する
  だけを行う。「簡単な質問だから自分で答える」の判断はしない。

適用範囲(★2026-07-26に20部屋へ拡大。Chami直接指示・選択肢C):
  DEPT_CONF に "session_relay": True がある部屋のみ通る(research-room だけが対象外)。
  ★★2026-07-26 に**会話便だけ**という制限を外した。Chami原文=
    「**デーモンが処理するのはもうやめたい…こういう放置が治らないから**」
    「**名指しする時もあるし、しない時もある。毎回名指しするのは面倒。状況や各の特徴強みに応じて、
      誰が演じて前に立つか、文脈とか物事の性質とかを判断して話してほしい**」
  → 会話便・作業便・名指し便の**すべて**がここへ来る。
    - 作業便は `relay(..., is_work=True)` で来る。**work_scope を持つ部屋の起動文は
      「あなたはこの部屋の実作業も担当する」へ差し替わる**(_boot_prompt参照)。
      許可ツールは dept_daemon.WORK_ALLOWED_TOOLS のまま=**新しい許可面を作らない**。
      **触ったファイルの監査(work_audit.jsonl)は従来どおり記録する**
      =「やったと言ってやっていない」(ORG-39)を検出できる状態を保つ。
    - work_scope を持たない部屋では従来どおり「作業したと言うな」を明示する。

安全側の決め事:
  - 認証失敗・CLI異常は**リトライしない**(INC-109「CLIログイン窓が大量に自動生成された」)。
    1回で諦めて (None, False) を返す。**ウィンドウを開く経路は作らない**(常に -p のみ)。
  - resume失敗(セッションが見つからない等)は世代交代=新セッションを作り generation+1。
  - 迷ったら黙って成功にしない。失敗は失敗として呼び元へ返す(偽の完了を作らない)。

出力ファイル:
  local/llm/room_sessions.json   … 部屋→セッションの対応表(1正本・tmp+os.replaceで原子的)
  local/llm/request_log.jsonl    … 1行=1遷移(提案書§6の縮小版)
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time

#   ★prompt_spill(長すぎるpromptをargvから逃がす止血)は _run_claude から外した
#     =promptは stdin で渡すので長さの上限が無い(2026-08-13・詳細は _run_claude 内の注記)。

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
HQ = r"D:\SougouStartFolder\00_AI-HQ"
CLAUDE = r"C:\Users\chami\.local\bin\claude.exe"

SESSIONS_FILE = os.path.join(LOCAL, "llm", "room_sessions.json")   # ★対応表の正本(1つだけ)
REQUEST_LOG = os.path.join(LOCAL, "llm", "request_log.jsonl")

# ★★事前の世代交代(2026-07-26 Chami直接指示・提案書§7)。原文=
#   「1つのClaude側のセッション内に**大量のコンテキストが溜まってしまって**、今までは手動で管理して
#     新しいセッションに移行していたけど、**それも煩わしくて**…**新しいセッションに移りたいって
#     自動で判定して自動でセッション切り替えて欲しい**」
#   「**自分が主導でやってる引き継ぎを自動でやって欲しい。Discord上から見えないから。**」
#
# ★閾値をこの値にした理由(必ず読むこと):
#   - relayが使うモデルはSonnet(RELAY_MODEL)で、文脈の窓は**約200,000トークン**。
#   - 交代の手順は「**今のセッションに引き継ぎを書かせる**」から始まる(提案書§7.2 手順2)。
#     つまり**交代する時にも、そのセッションへ1便入れる余地が要る**。窓ぎりぎりまで使ってから
#     交代しようとすると、**引き継ぎを書かせる便自体が入らず**、記憶を丸ごと失う。
#   - 1便あたりの上振れも見ておく必要がある。封筒には共通規律+添付パス+引用が入り、
#     作業便ではセッションがRead/Grepでファイルを読むので、**1ターンで数万トークン**増えることがある。
#   → 窓200kに対して**8万トークン(=4割)の余白**を残す位置で交代する。
#     120,000は「まだ普通に会話できるが、次の数便で危うくなる」点であって、限界の値ではない。
#   ★下げる分には安全(交代が増えるだけ)。**上げる時は上の3点を再計算してからにすること。**
#   ★2026-07-26 追記: 部屋別モデル(DEPT_CONF "relay_model")を足したが、**この値は据え置き**。
#     hq/research-room が使う Opus も文脈の窓は同じ約200,000トークンなので、上の計算は変わらない。
#     ★モデルを増やす時は「その窓が200k未満でないか」を必ず確認すること(小さい窓のモデルを
#       足すと、この閾値が窓を超えて**交代する前に壊れる**)。
#
# ★★2026-07-26 120,000 → 150,000 へ引き上げ(Chami裁定「A」)。**実測に基づく**:
#   - 起動文の読み物を軽くした後、hqの第1世代は **ctx=83,059**(2ターン)だった。
#     閾値12万だと**残り37,000**しかなく、**数便で交代**する。福岡不在の1週間で何十回も交代し、
#     そのたび opus 3回(引き継ぎ+新規+自己確認)を余計に使う。
#   - 引き上げても**窓20万に対して5万の余白**が残る。交代の第一手(引き継ぎを書かせる便)は
#     要約を書くだけで道具をほとんど使わないので、5万あれば入る。
#   ★上げた根拠は「余白8万→5万で足りると**実測で言える**ようになった」こと。
#     当初12万にしたのは1便あたりの伸びが**未計測**だったため=安全側に置いていた。
#   ★これ以上は上げない。**上げる時は必ず「1便あたりの伸び」を測り直してから。**
#
# ★★★2026-07-29 150,000 → 185,000(改善書_セッション移行の負荷とトークン §4 第2手・§5)。
#   **この値の意味そのものが変わった。**
#     旧= 「ここを超えたら交代する線」(交代が既定の対処)
#     新= 「**圧縮が確認できない時だけ**交代する保険の線」(圧縮が既定の対処)
#   根拠(実測。改善書§1-3/§1-4):
#     - Claude CLI自身が**約167,000で自動圧縮する**(system-engineer 167,056/167,139 ・
#       llm-edu も同様・計4件。どのセッションも圧縮後そのまま仕事を続けていた)。
#     - 手で撃った `/compact` も効いていた(hr-room 第1世代 7/29 01:22 JST=
#       trigger=manual / 174,843 → 4,801 / 102.5秒)。
#     → 「窓が溢れて記憶を丸ごと失う」は**実物では起きていなかった**。溢れる前にCLIが畳む。
#       だから「全部捨てて交代」(上位モデル3連発+約10分)を既定にする理由が無い。
#   ★**交代を消してはいない**(改善書§4 第2手(c)の指定どおり例外として残す):
#       ① 圧縮を撃ったのに効かなかった(自動圧縮が働かないCLI版への保険)
#       ② resume失敗(従来どおり・下の事後交代)
#       ③ 圧縮が COMPACT_REFRESH_ROTATIONS 回積み重なり **かつ** 文脈が
#         REFRESH_MIN_CONTEXT_TOKENS 以上の時の定期リフレッシュ(2026-07-29 3回目に条件追加)
#       ④ HQの手動指示(rotate_now)
#   ★185,000 の位置: 自動圧縮(約167,000)より上に置く。ここより下だと自動圧縮と競合して
#     挙動が読めなくなる(改善書「手を付けない・却下したもの」の1つ目)。
ROTATE_AT_TOKENS = 185000

# ★圧縮を撃つ線(改善書 第2手(a))。旧 ROTATE_AT_TOKENS と**同じ値**を引き継いでいる。
#   ここを超えたら、**その便を返した後に**(=Chamiを待たせない位置で)`/compact` を撃つ。
#   実測の所要= 102〜140秒。交代(約10分・上位モデル3呼び出し)の1/5以下。
# ★2026-08-01 前倒し(Chami指示「管轄なら回さず自分で書け」=C-027・一ノ瀬怜が直接編集)。
#   150,000 → 120,000。重いセッションのresumeが遅い件(DEF-platform-se-7ee9e3efd0)への前倒し圧縮。
#   ★3本セットで下げた= HANDOFF_CHECKPOINT_AT_TOKENS と REFRESH_MIN_CONTEXT_TOKENS も 120,000→100,000。
#     圧縮**だけ**を120,000に下げると REFRESH_MIN(120,000)と重なり、定期リフレッシュが二度と発火しない
#     (7/29にChamiが3回直させたバグの再来。下の「なぜ120,000か(2)」の釘)。順序 REFRESH_MIN<COMPACT・
#     HANDOFF<COMPACT を保つため3本まとめて再配置した。
#   ★120,000も100,000も観測の谷(軽い側≤7,010 / 重い側≥125,080の間で観測ゼロ)の中=取り違えない。
#   ★これは「前倒し」であって本丸ではない= 発火そのものの不確実さ(便が177〜180kまで伸びた実測)は別途。
COMPACT_AT_TOKENS = 120000

# ★★モデルの窓の目安(2026-07-29 追加)。**判定には使わない。観測と記録のためだけの線。**
#   なぜ足したか= Chami「窓を超えている便が実在する(202,754)。溢れた時に何が起きるかも確かめろ」。
#   実測(local/llm/request_log.jsonl・~/.claude/projects の記録・2026-07-29):
#     07:13:12 system-engineer 第11世代 ctx=202,754 で便は **rc=0 で成功**(600秒)。
#     07:14:05〜07:16:47 同じセッション(その時点 222,246)で引き継ぎ生成も **成功**(23,132B)。
#     第11世代の記録ファイルには compact_boundary が **0件** = CLIの自動圧縮も走っていない。
#   → **溢れても便は落ちていない**。CLI側が古い履歴を落として送っているとみられる
#     (こちらからは中身を確認できないので断定しない)。落ちないが**古い会話は静かに失われる**
#     ので、ここを超えたら台帳へ1行残して「見える」ようにする。★交代は増やさない
#     (交代を増やすと、今回直した「重くなったら捨てる」へ逆戻りする)。
CONTEXT_WINDOW_TOKENS = 200000

# ★引き継ぎの定期チェックポイント(改善書 第2手(d)・§8-3)。
#   なぜ要るか= 引き継ぎを「交代の瞬間の一発勝負」にしていると、
#   **退職者に終業5分前に全知識をメモさせる**構造になる(姉妹文書§4(1))。
#   圧縮で会話の細部が畳まれても、**厳選された知識は常にファイルに新しい状態で在る**ようにする。
#   ★交代とは切り離す= 交代しなくてもここで書かれる。
# ★2026-08-01 100,000へ(COMPACTを120,000へ前倒ししたため、その下へ再配置・一ノ瀬怜)。
#   厚い文脈から引き継ぎ正本を書いてから畳む、の順序(HANDOFF<COMPACT)を維持する。
HANDOFF_CHECKPOINT_AT_TOKENS = 100000
# 同じ世代で何度も書かせないための刻み。前回チェックポイント時の文脈からこれだけ増えたら次を撃つ。
# ★これが無いと120,000を超えた後の**毎便**で引き継ぎ生成(最も高い呼び出し)が走る。
HANDOFF_CHECKPOINT_STEP = 20000

# ★圧縮の定期リフレッシュ交代(改善書 第2手(c)「圧縮がK回積み重なった時」)。
#   圧縮の要約の質はこちらでは制御できない(CLIの内部動作)。畳み続けると痩せていく可能性があるので、
#   K回でいちど世代を作り直す。**完全廃止ではなく残す**のは改善書の「正直な留保」の指定どおり。
COMPACT_REFRESH_ROTATIONS = 5

# ★★2026-07-29(3回目)定期リフレッシュに**文脈の条件を足した**(Chami「また改修αの部屋で
#   セッション変わったけど妥当?」への恒久対処)。**回数条件は消していない。足しただけ。**
#
# ★実測(local/llm/request_log.jsonl・system-engineer・2026-07-29):
#     08:11:18 事前圧縮(回収) 155,748→6,948 → 同じ秒に
#     08:11:18 事前交代 理由=圧縮が5回積み重なった=定期リフレッシュ(K=5) tokens=6,948 compacts=5
#     17:08:21 事前圧縮(回収) 7,618→3,816   → 同じ秒に
#     17:08:21 事前交代 理由=圧縮が6回積み重なった=定期リフレッシュ(K=5) tokens=3,816 compacts=6
#   = **中身が6,948 / 3,816トークンしか無いセッションを、回数だけを見て捨てていた。**
#
# ★真因(構造)= `compact_count` が増えるのは**圧縮が効いた瞬間**であり、
#   その瞬間の文脈は**そのセッションで一番軽い**(実測 3,816〜7,010)。
#   つまり回数条件だけの定期リフレッシュは、**必ず一番軽い瞬間に発火する**構造だった。
#   ここで交代しても、新世代の種になる引き継ぎは**その痩せた要約から書かせる**ことになるので、
#   上位モデル3呼び出し(実測 約10分)を払って得るものが無い。趣旨(要約の劣化に備える)に
#   照らしても**逆効果**だった。
#
# ★なぜ 120,000 か(実測から決めた・根拠3つ):
#   (1) 圧縮直後の実測値は 3,816 / 4,597 / 6,136 / 6,911 / 6,948 / 7,010(全て1万未満)。
#       健全に重い側の実測値は 125,080 / 145,086 / 153,342 / 155,727 / 164,851 / 186,655 /
#       193,580 / 203,673。**1万〜12万の間に実測値が1つも無い**ので、この谷のどこに置いても
#       取り違えない。7,010の約17倍の余白がある。
#   (2) COMPACT_AT_TOKENS(150,000)より**下**に置く。ここを150,000以上にすると、
#       重くなった便は先に圧縮で畳まれて軽くなるため、定期リフレッシュが**二度と発火しない**。
#       それは「趣旨を殺すな」に反する(条件を足したつもりで廃止したことになる)。
#   (3) HANDOFF_CHECKPOINT_AT_TOKENS と**同じ線**に揃えた。この線を超えた便では
#       引き継ぎのチェックポイントが既に走っている= **厚い文脈から書かれた正本が在る状態**で
#       交代できる。定期リフレッシュが一番効く場所は、まさにそこだ。
# ★これで定期リフレッシュは「回数が溜まった **かつ** 文脈が120,000以上」でだけ起きる。
#   回数条件を満たしたまま軽い間は**見送るだけ**(取り消しではない)。次に重くなった時に交代する。
# ★2026-08-01 100,000へ(COMPACTを120,000へ前倒ししたため、その下を維持=定期リフレッシュを殺さない・一ノ瀬怜)。
#   REFRESH_MIN < COMPACT を保つ。100,000も観測の谷(≤7,010 と ≥125,080 の間)の中で取り違えない。
#   HANDOFF_CHECKPOINT_AT_TOKENS と同じ線に揃える方針は不変(両方100,000)。
REFRESH_MIN_CONTEXT_TOKENS = 100000

# ★★2026-08-13(イージス研究室)**定期リフレッシュは「Chamiが会話の途中」なら見送る。**
#   発注= 研究室HQ DISPATCH 1537458828541698139 論点2。
#   Chamiの原文(msg 1537450341426266162 の要旨)= コピー部門とローカルllm教育部門が
#   「急に文脈読まなくなった」。実測すると 22:01:54(llm-edu)と 22:08:15(copy-director)で
#   定期リフレッシュの事前交代が起きており、**その便を新世代が答えていた**。
#
# ★HQは「発火タイミングの分散(ずらし)」を案として挙げたが、実測はそれを支持しない。
#   (local/llm/request_log.jsonl の rotated 92件・2026-07-29〜08-13。全部数え直した)
#     ・別部門の定期リフレッシュが前後15分以内にあった発火 = 30/92(33%)
#     ・**Chamiが直前15分にどこかの部屋へ便を出していた発火 = 73/92(79%)**
#     ・**その部屋でChamiが会話の途中だった(直前15分に同じ部屋へ別のChami便)= 55/92(60%)**
#   → 部屋どうしが揃うのは時計の位相のせいではない。**Chamiが一気に喋る**という
#     共通の駆動源があるからだ。位相をずらしても駆動源は残る=誰かが必ず当たる。
#     しかも「同時多発」は33%しかなく、残り67%は**単独で**同じ被害を出している。
#   → だから見るのは時計ではなく**その部屋の会話の状態**にした。
#
# ★見送ってよい理由= 定期リフレッシュは3つの交代条件のうち**唯一の選択的な交代**だ
#   (圧縮失敗・185,000超は退避=止められない)。文脈100,000〜140,000は保険の線
#   185,000まで十分な余裕があり、1〜数便遅らせても何も壊れない。
# ★★見送りを永久にしない(2026-07-29に「条件を足したつもりで廃止した」事故がある)。
#   ①Chamiが15分黙れば次の便で普通に発火する ②それでも溜まったら REFRESH_HOLD_MAX_SEC で必ず発火。
REFRESH_QUIET_SEC = 900          # この秒数以内に同じ部屋へChami便が来ていたら「会話の途中」
REFRESH_HOLD_MAX_SEC = 4 * 3600  # 見送りっぱなしにしない保険。これを超えたら会話中でも交代する

# `/compact` の待ち(秒)。実測102.5秒(hr-room)/ 自動圧縮は各140秒。倍以上の余裕を取る。
# ★ここはChamiの便を返した**後**に走るので、長めでも誰も待たない。
COMPACT_TIMEOUT = 420

# 引き継ぎの生成にかける上限(秒)。会話便(300秒)より短くする理由=
#   引き継ぎは**要約を書くだけ**で道具をほとんど使わない。ここで長く待つと、
#   Chamiの便への返信が遅れる(交代はChamiの便を処理する**前**に走るため)。
# ★2026-07-29 180→420秒。Chami=「全世代の引き継ぎは取得できずというのが怖い
#   (過去の良かったもの、だめだったことが再度起こりそうで)」。
#   実測= 00:05に交代→**00:08に失敗**=ちょうど180秒。文脈157,586を抱えたセッションに
#   8項目を書かせるには短すぎた。★交代はChamiの便より前に走るので待たせすぎるのも駄目だが、
#   引き継ぎが空になる方が高くつく(以後の全世代がその欠落の上に積む)。
HANDOFF_TIMEOUT = 420

RELAY_TIMEOUT = 300            # dept_daemon.PRINT_TIMEOUT と同じ(会話便)
# ★作業便の上限(2026-07-26)。dept_daemon.WORK_TIMEOUT と同じ600秒。
#   なぜ分けるか= 会話の300秒のまま実作業をさせると、**間に合わなかった便が毎回「配送失敗」になり**、
#   正直な失敗文+nack+5分保留が延々と繰り返される(=事実上の沈黙)。旧 work_generate も600秒だった。
RELAY_WORK_TIMEOUT = 600
# ★★2026-07-27 **2段構えの待ち**(Chami「改善と再発防止を頼むよ」への恒久対処)。
#   起きたこと(実測。推測ではない):
#     02:35:39 Chamiが報告-通知(report-notify)へ便を出した → 02:40:40 に failed/timeout。
#     Chamiには「配送に失敗した(セッションへ渡せていない)…理由= Claude CLIが300秒で応答しなかった」
#     とだけ出た。**だがセッションは実際には作業を終えていて**、02:40 に daily_report.py を
#     書き換えて git commit(86ef339)まで済ませていた。
#   ★真因は「遅かった」ではない。**時計が短すぎた**。
#     この便は classify_work() が False(=会話)と判定したが、中身は実装作業だった。
#     会話の300秒予算で実作業を殺したので、**成果が出ていたのに「失敗」とだけ告げた**。
#   → 分類がハズれた時に**成果ごと捨てない**ために、上限を2段にする:
#       第1段(soft)= 従来の値(会話300 / 作業600)。ここでは**殺さない**。
#         「まだ作業中」の中間通知を1回だけ出し、**そのまま待ち続ける**。
#       第2段(hard)= soft の2倍(会話600 / 作業1200)。**ここで初めて kill して failed**。
#   ★soft以内で返る便は**今までと1バイトも変わらない**(中間通知も slow 記録も出ない)。
#   ★上げ幅を2倍に留めた理由= LeaseQueue の既定リース(900秒)を跨ぐため、
#     dept_daemon 側でリースを伸ばす必要がある(向こうの QUEUE_LEASE_MARGIN 参照)。
#     ここを更に伸ばす時は**必ず向こうのリースも一緒に**見直すこと(片方だけ直すな)。
RELAY_HARD_FACTOR = 2


def hard_limit(is_work=False):
    """その便の**最終的な**上限(秒)。soft の RELAY_HARD_FACTOR 倍。

    ★dept_daemon がキューのリース長を決めるのにも使う(定数を2箇所に書かないため)。
    """
    return int(RELAY_WORK_TIMEOUT if is_work else RELAY_TIMEOUT) * RELAY_HARD_FACTOR


# ★2026-07-29 既定を sonnet → **opus** へ変更(Chami直接指示)。原文=
#   「**デフォルトはOpus5.0でいいよ、トークン節約できる時だけ必要に応じて作業を
#     sonnet、haikuに移譲してやらせて**」
#   = **全部屋の既定がOpus**。安いモデルへ落とすのは「節約できる時だけ」の**例外**であり、
#   その判断は各部屋がする(DEPT_CONF の "relay_model" で個別指定できる形は残す)。
#   ★裁定C-014の更新でもある(旧= 既定sonnet・必要ならOpus / 新= 既定Opus)。
RELAY_MODEL = "opus"
# ★モデル版の固定(2026-07-31 Chami指示)。素の "opus" エイリアスは将来CLIが最新へ張り替えると
#   Opus 5 など上位版へ**黙って乗り換わる**=トークン単価が跳ねる。Chami=「最新じゃなくても品質が
#   落ちないなら、トークン節約でモデルを落としたopusにして欲しい」。人格演技は Opus 4.8 世代で
#   調整済み=ここが品質の床。よって素の "opus" は明示版 claude-opus-4-8 へ固定する(CLIで受理を実測)。
#   ★戻し方= この関数の中身を `m` に戻すだけ(sonnet/haiku や既に版指定の値は素通し)。
PINNED_OPUS = "claude-opus-4-8"
def _pin_model(m):
    return PINNED_OPUS if (m or "").strip() == "opus" else m
# ★アメスの共有記憶(2026-07-26 Chami直接指示)。原文=
#   「**アメスはデーモンではなく、普通にセッションの人として答えて欲しい。ずっと一緒にいたいから**」
#   現状は1部屋=1セッションなので、アメスは複数の部屋に分かれて**互いの記憶が無い**。
#   「ずっと一緒」=**連続性**なので、部屋をまたいで読み書きする1本のファイルを持たせる。
#   ★持たせるのは**アメスだけ**(増やすのは効果を見てから)。★local/HQ内で完結=ネットへ出さない(C-013)。
AMES_SHARED_MEMORY = os.path.join(HQ, "departments", "hr", "memory", "ames_shared.jsonl")

# ★ツール許可= dept_daemon.WORK_ALLOWED_TOOLS と**同一のallowlist**を使う。
#   新しい許可面を作らないため。実体は下の _allowed_tools() が dept_daemon から遅延importで
#   引く(=正本は向こう1つ)。読めない時だけこの控えへ退避する。
_ALLOWED_TOOLS_FALLBACK = ["Read", "Edit", "Write", "Grep", "Glob", "Bash"]

# 直近の失敗理由(dept単位)。呼び元が「理由=<短く>」をChamiへ正直に伝えるために読む。
# ★プロセス内だけの揮発状態。永続化しない(台帳は request_log.jsonl 側)。
LAST_ERROR = {}
# ★直近の失敗の**種類**(dept単位・2026-07-27)。今のところ "timeout" だけ。
#   なぜ要るか= 呼び元(dept_daemon)の失敗文は「配送に失敗した(セッションへ渡せていない)」だが、
#   hard timeout ではそれが**嘘になりうる**(02:40の実測=渡っていたし作業も終わっていた)。
#   種類が分かれば、呼び元が「渡せていない」と断定せずに済む。★推測を断定にしない。
LAST_ERROR_KIND = {}


def relay_model(conf):
    """この部屋のrelayが使うモデル。DEPT_CONF に "relay_model" があればそれ、無ければ RELAY_MODEL。

    ★このキーを持たない部屋は**今までどおり sonnet**(既存19部屋の挙動は1ミリも変わらない)。
    ★なぜ部屋ごとに分けるのか(2026-07-26 発注):
      hq / research-room の仕事は**横断裁定・真因追跡・出荷前レビュー**で、
      CLAUDE.md §5.1 の分業表では**最上位モデルの領域**。同§1の優先順位は
      「正確性 > 安全性 > 検証可能性 > 保守性 > **トークン効率** > 速度」なので、
      **品質を落とした節約は規約違反**(Chami「品質を落とさないことが最重要」2026-07-21)。
    ★読めない値(空・非文字列)は既定へ倒す=**沈黙させない**(fail-safe)。
    """
    try:
        m = str((conf or {}).get("relay_model") or "").strip()
        return _pin_model(m or RELAY_MODEL)
    except Exception:
        return _pin_model(RELAY_MODEL)


def _allowed_tools():
    """dept_daemon の WORK_ALLOWED_TOOLS を1正本として引く(循環importを避けて遅延で)。"""
    try:
        import dept_daemon                      # 呼ばれる時点では必ずロード済み
        t = list(getattr(dept_daemon, "WORK_ALLOWED_TOOLS", []) or [])
        if t:
            return t
    except Exception:
        pass
    return list(_ALLOWED_TOOLS_FALLBACK)


def _log(dept, msg):
    print(f"{time.strftime('%H:%M:%S')} [{dept}/relay] {msg}")


# --- 対応表(1正本・原子的更新) ---
def load_sessions():
    """部屋→セッションの対応表を読む。壊れていても落とさない(空扱い=初回として作り直す)。"""
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_sessions(table):
    """対応表を**tmpに書いて os.replace**で差し替える(書き込み途中の半端な表を残さない)。

    ★原子性が要る理由: 世代交代の最中にプロセスが死ぬと、対応表が壊れて
      「どのセッションが現役か分からない」状態になる。os.replace は同一ボリューム上で原子的。
    """
    os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
    tmp = SESSIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SESSIONS_FILE)              # ★原子的差し替え


# --- ★★2026-07-28 「その部屋の1行だけ」を書き戻す(世代交代の結果が消える事故の恒久対策) ---
#
# Chamiの原文= 「セッション更新早くない?こんなもん?」
#
# ★実測した事故(local/llm/request_log.jsonl・2026-07-28):
#     18:47:22 事前交代 tokens=161260 old=cee56798
#     18:56:45 事前交代 tokens=161260 old=cee56798   ← 同じ値
#     18:57:21 事前交代 tokens=161260 old=cee56798   ← 同じ値
#     19:07:05 事前交代 tokens=161260 old=cee56798   ← 同じ値
#     19:12:24 事前交代 tokens=161260 old=cee56798   ← 同じ値
#   ところが実際には 19:06:31 に system-engineer は第3世代(7023f6ec / ctx=91,961)へ移っていた。
#   **移った結果が対応表に残っていなかった。**
#
# ★真因(実測で1つに特定した):
#   relay() は便の**入口**で load_sessions() して表**全体**を抱え、
#   便の**出口**(数分後)で save_sessions(表全体) していた。
#   その間に**別の部屋**の便が終わって表を書き換えていても、
#   こちらは古いスナップショットを丸ごと上書きするので、**後勝ちで消える**(lost update)。
#
#   実データで裏を取った時刻の一致:
#     19:06:19 kaizen-analyst が表を読む(この時点の system-engineer= cee56798 / 161,260)
#     19:06:31 system-engineer が第3世代(7023f6ec / 91,961)を保存
#     19:06:38 kaizen-analyst が**19:06:19のスナップショット**を保存 → 第3世代が消えた
#     19:07:05 system-engineer の次の便が「cee56798 が 161,260」を読み、また交代した
#   同じ形が 19:15:21(system-engineer 第3世代)→ 19:15:28(llm-edu の保存)でも起きており、
#   **今ディスクにある room_sessions.json は system-engineer の 18:46:01 時点の状態**
#   (= 19:15 に llm-edu が書いた古いスナップショット)だった。mtime と中身が一致する。
#
#   全期間の実測= 事前交代 30回のうち **8回**(hq 3 / system-engineer 4 / hr-context 1)が
#   「**もう現役でないセッション**を相手にした交代」= この事故による純粋な無駄。
#
# ★直し方= 表を**書く直前にディスクから読み直し**、自分の部屋の1行だけ差し替える。
#   他の部屋の行には一切触らない=誰の更新も踏み潰さない。
#   読み直し〜書き込みの間に別プロセスが入らないよう、ロックファイルで直列化する。
# ★fail-open: ロックが取れなくても**書く**。ここで便を落とす方がずっと悪い
#   (稀に1回踏み潰すのと、Chamiの便が黙って消えるのとでは、被害の桁が違う)。
SESSIONS_LOCK = SESSIONS_FILE + ".lock"
_LOCK_WAIT_SEC = 10.0                            # これ以上は待たずに書く(fail-open)
_LOCK_STALE_SEC = 60.0                           # 置き去りのロックは奪う(プロセス突然死の後始末)


def _acquire_sessions_lock():
    """対応表のロックを取る。取れたらfd、取れなくてもNoneを返す(★呼び元は必ず続行する)。"""
    t0 = time.time()
    while True:
        try:
            return os.open(SESSIONS_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                # ★死んだプロセスが置き去りにしたロックを、いつまでも尊重しない。
                if time.time() - os.path.getmtime(SESSIONS_LOCK) > _LOCK_STALE_SEC:
                    os.unlink(SESSIONS_LOCK)
                    continue
            except OSError:
                pass
            if time.time() - t0 >= _LOCK_WAIT_SEC:
                return None                      # ★fail-open(待ち続けて便を殺さない)
            time.sleep(0.05)
        except OSError:
            return None                          # ★ロックが作れない環境でも配送は続ける


def _release_sessions_lock(fd):
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(SESSIONS_LOCK)
    except OSError:
        pass


def save_room(dept, entry):
    """★対応表のうち**この部屋の1行だけ**を、今ディスクにある表へ差し替えて保存する。

    ★save_sessions(表全体) を直接呼ばないこと。呼ぶと、便の入口で読んだ古い表を
      丸ごと書き戻すことになり、その間に終わった**他の部屋の世代交代が消える**
      (2026-07-28 の事故そのもの)。
    ★どの失敗でも例外を投げない(=便を巻き添えにしない)。保存できたかを bool で返す。
    """
    fd = _acquire_sessions_lock()
    try:
        table = load_sessions()                  # ★入口のスナップショットではなく「今」の表
        table[dept] = entry
        save_sessions(table)                     # ★原子的(tmp+os.replace)のまま
        return True
    except Exception as e:                       # noqa: BLE001 ★保存の失敗で配送を止めない
        _log(dept, f"対応表の保存に失敗({type(e).__name__})=便はこのまま返す")
        return False
    finally:
        _release_sessions_lock(fd)


def _record(request_id, dept, state, evidence=""):
    """遷移を1行だけ書く(提案書§6の縮小版)。

    state= leased / running / completed / failed / rotated / **slow**。
    ★received / persisted は**ゲートウェイ側の責務**なのでここでは書かない
      (同じ状態を2箇所が書くと、どちらが正か分からなくなる)。
    ★`slow`(2026-07-27)= soft を超えたが**まだ待っている**便。失敗ではない。
      「classify_work() が会話と判定したのに実際は長かった」=分類のハズれの台帳。
      ★これを見て**再分類も自動リトライもしない**(勝手に2回実行すると二重作業になる)。
    """
    try:
        os.makedirs(os.path.dirname(REQUEST_LOG), exist_ok=True)
        with open(REQUEST_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"request_id": str(request_id), "dept": dept,
                                "state": state,
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "evidence": str(evidence)[:500]},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass                                     # 記録の失敗で配送を巻き添えにしない


# --- 封筒(★原文を一切要約・改変しない) ---
def _purpose_block(dept):
    """その部門の**目的とKPI**を org_registry.yml から引く(dept_daemon の1正本を使う)。

    ★★2026-07-26 これが抜けていた(HQが実測で発見)。
      `dept_daemon.registry_purpose()` は**部門の目的とKPIを台帳から都度読み**する関数で、
      旧経路(generate/work_generate)は**3箇所で使っていた**。だが relay は**1度も使っていなかった**。
      → relayへ全面移行した結果、**全部屋の起動文からミッションとKPIが消えていた**。
      実害= 経営企画が「platform-seの起動文にミッションが無い」ことに気づき、
        **手書きの起動文を別に作ろうとした**。それを入れると**起動文の正本が2つ**になり必ずズレる
        (ORG-11=記録先を2つ持たない)。**正本は org_registry.yml 側で、そこから流すのが正しい。**
    ★**起動文ではなく封筒に入れる**理由= registry は「1行足せば次の発話から効く」都度読み設計。
      起動文だと最初の1回しか読まれず、目的を更新しても既存セッションへ届かない。
    ★読めなければ空文字(fail-open)。
    """
    try:
        import dept_daemon
        t = dept_daemon.registry_purpose(dept)
        return ("■この部門の目的とKPI(正本= 00_AI-HQ/org_registry.yml。"
                "★ここが変わったら次の便から効く)\n" + str(t).strip() + "\n\n") if t else ""
    except Exception:
        return ""


def _discipline_block():
    """全部門共通規律を dept_daemon の1正本から引く(遅延import・_allowed_tools と同じ形)。

    ★ここで自前に読み直さない。読む処理を2箇所に持つと、キャッシュの取り方が割れて
      「片方だけ古い規律で動く」が起きる(記録先を2つ持たない=ORG-11と同じ話)。
    ★読めなければ空文字=規律が無くても応対は続ける(fail-open。沈黙が最悪の事故)。
    """
    try:
        import dept_daemon
        return dept_daemon._disc_block()
    except Exception:
        return ""


# --- ★★規律の差分送付(2026-07-29 改善書_セッション移行の負荷とトークン §4 第3手) ---
#
# なぜ入れたか(改善書§1-1 の実測):
#   1便の封筒は 14,058〜15,555字(8通の実測)で、その**約9割が共通規律(約28KB)**。
#   Chamiの本文が200字でも封筒は毎回12,000トークン級で、しかも封筒は履歴に残り続けるので、
#   10便やり取りした部屋は**同じ規律のコピーを10部**抱えて生きている。
#   1日約70便 × 約11,500トークン = **規律のコピーだけで毎日約80万トークン**(改善書§1-7)。
#
# 直し方= 指紋(規律全文のハッシュ)が前便と一致するなら3行だけにする。
#   ★**「変わっていない」の保証の取り方**(改善書§4 第3手の指定をそのまま実装):
#     再開(resume)セッションは前便までの履歴を保持していて、規律の全文は**その履歴の中に実物で在る**。
#     危ういのは圧縮で履歴が畳まれた時だけで、そこは第1手の圧縮検知→全文再送で塞ぐ。
#     つまり保証は「記憶を信じる」ではなく「**畳まれた瞬間を検知して配り直す**」で成立させている。
#   ★全文を必ず送る場面= 新セッションの初回 / 規律が変わった時 / 圧縮を検知した直後 /
#     保険として DISC_FULL_EVERY 便に1回。
#   ★**裁定カタログの見出しは毎便のまま**(改善書§3の4・第3手の但し書き)。
#     1,268字と小さく、部門違い回送を実際に直した実績がある。ここは削らない。
DISC_FULL_EVERY = 10


def _discipline_parts():
    """(規律の全文ブロック, 裁定カタログの見出しブロック) に分けて返す。

    ★分ける理由= 差分送付の対象は**規律だけ**で、裁定の見出しは毎便送るから(上記)。
    ★分けられない時は (全部, "") へ倒す= **今までと同じ封筒**になるだけで、品質は落ちない
      (fail-open。ここで例外を出して便を落とす方がずっと悪い)。
    """
    try:
        import dept_daemon
        d = dept_daemon.common_discipline()
        head = ("■全部門共通の規律(★必ず守る。違反は事故になる)\n" + d + "\n\n") if d else ""
        try:
            verdict = dept_daemon._verdict_block()
        except Exception:
            verdict = ""                         # fail-open: 裁定が読めなくても規律は届ける
        return head, verdict
    except Exception:
        return _discipline_block(), ""


def discipline_fingerprint():
    """規律の全文の指紋。読めなければ空文字(=差分送付をやめて全文へ倒す)。

    ★指紋を取る対象は**規律の全文だけ**。裁定の見出しは毎便送るので指紋に入れない
      (入れると、裁定を1行足すたびに規律の全文まで再送されて封筒が太る)。
    """
    try:
        import dept_daemon
        d = dept_daemon.common_discipline()
        return hashlib.sha256(d.encode("utf-8")).hexdigest()[:16] if d else ""
    except Exception:
        return ""


def _discipline_short(fp):
    """規律が前便から変わっていない時に入れる3行(改善書 第3手の文面そのまま)。"""
    return ("■規律: 前便から変更なし(指紋 " + (fp or "?") + ")。\n"
            "既に受け取っている全部門共通規律と裁定の見出しを引き続き守れ"
            "(正本= 00_AI-HQ/departments/00_common/全部門共通規律.md)。\n"
            "★変わった時・圧縮の直後・10便に1回は全文を配り直す。全文が来ない便は「変わっていない」の意味だ。\n\n")


def _state_block(generation, context_tokens):
    """封筒の先頭に置く「この部屋のセッション状態」1行(2026-07-26 Chami指示)。

    ★なぜ要るか: Chami原文=「**自分が主導でやってる引き継ぎを自動でやって欲しい。
      Discord上から見えないから。**」= 煩わしさの本体は「**今どれだけ重いかDiscordから分からない**」。
      自動で交代するだけでは半分で、**セッション自身が自分の状態を知っている**必要がある
      (Chamiが「今どれくらい?」と聞いたら、推測でなく実測で答えられる)。
    ★定期的にDiscordへ状態を投げることはしない(鳴らしすぎ=ORG-03/42)。
      「**聞けば分かる**」と「**変わった時だけ言う**」の2つで足りる。
    ★数字は**前の便の実測**(usage)であって、今この瞬間の値ではない。そう書いておく。
    """
    if context_tokens:
        amount = f"約{context_tokens:,}トークン(前便の実測)"
    else:
        amount = "未計測(この部屋での実測がまだ無い)"
    # ★2026-07-29 表示を「交代の目安」から「圧縮の目安」へ(改善書 第2手で意味が変わったため)。
    #   ここが古いままだと、セッション自身がChamiに**間違った運用**を説明してしまう。
    return ("=== この部屋のセッション状態 ===\n"
            f"世代: 第{generation}世代 / 文脈: {amount} / "
            f"圧縮の目安: {COMPACT_AT_TOKENS:,}トークン(交代ではなく圧縮で畳む) / "
            f"交代は{ROTATE_AT_TOKENS:,}超で圧縮が効かない時だけ\n")


def _note_block(rec):
    """回送の**申し送り**(`note`)を本文とは別の枠で返す。無ければ空文字。

    ★2026-08-15 イージス研究室。`note` は前から積まれていたのに封筒が描画しておらず、
      「上げ元が何を頼みたいのか」も「その後に取り消しが来ているか」も受け取り側に
      届いていなかった(ESC-… の本文は元の便そのままなので、受け手は自分でDiscordを
      引かない限り発注内容が分からない)。**本文より先に読ませる**位置に置く。
    ★例外は空文字へ倒す(封筒そのものを壊さない)。
    """
    try:
        n = str((rec or {}).get("note") or "").strip()
    except Exception:
        return ""
    if not n:
        return ""
    return ("--- 申し送り(この便を回した部屋が書いた。★本文より先に読め) ---\n"
            f"{n[:2000]}\n"
            "--- 申し送りここまで ---\n")


def quote_block(rec):
    """Discordの**返信(リプライ)**の引用元を、本文とは**別の枠**にして返す。返信でなければ空文字。

    ★なぜ要るか(2026-07-27 Chami原文):
      「**返信も読めないデーモンいらないのわ**」
      「**何を参照して、何が抜けているかこっちでは測れない**」
      実測(06:32 研究室hq): Chamiの「これがC」「これがA」は**どちらもDiscordの返信**で、
      返信先はHQの長文だった。だが受信側(gateway)が `reply_to` を1つも拾っていなかったため、
      セッションには**その4文字しか届かず**、「添付が届いていない」という的外れな返事をした。

    ★原文無改変の原則(build_envelope 参照)は守る= Chamiの本文には一切触れない。
      引用は**本文の外側**に足すだけ。
    ★取れなかった時は**取れなかったと書く**。黙って空にすると、
      セッションは「引用が無い便」と区別できず、また的外れな返事をする。

    受け取る形(gateway/鳩が作る):
      {"msg_id", "author", "content", "attachments"(件数), "resolved"(bool), "note"(理由)}
      ★旧・鳩(inbox_poller)の3キー形も読める(resolvedが無ければ content の有無で判断)。
    """
    ref = rec.get("reply_to") or {}
    if not ref:
        return ""
    try:
        mid = str(ref.get("msg_id", "") or "")
        author = str(ref.get("author", "") or "?")
        content = str(ref.get("content", "") or "")
        natt = ref.get("attachments")
        resolved = ref.get("resolved")
        if resolved is None:                    # 旧形式(鳩)の互換
            resolved = bool(content)
        head = ("\n=== ★この便は下の発言への「返信」だ(Discordの返信機能) ===\n"
                f"引用元 msg_id: {mid}\n")
        if not resolved:
            why = str(ref.get("note") or "理由不明")
            return (head
                    + f"★引用元の本文は**取得できなかった**(理由= {why})。\n"
                      "  空だから何も無いのではない。**推測で埋めるな**。\n"
                      "  何への返信か分からないまま答えると的外れになる。必要ならChamiに訊け。\n")
        att = ""
        if isinstance(natt, int) and natt > 0:
            att = f"引用元の添付: {natt}件(この便の添付とは別物)\n"
        elif isinstance(natt, (list, tuple)) and natt:
            att = f"引用元の添付: {len(natt)}件(この便の添付とは別物)\n"
        return (head
                + f"引用元の投稿者: {author}\n"
                + att
                + "--- 引用元の本文ここから ---\n"
                + content + "\n"
                + "--- 引用元の本文ここまで ---\n"
                + "★下の本文は、この引用元への返事だ。何に対する返信かを取り違えるな。\n")
    except Exception:
        # ★引用の組み立てに失敗しても**便は落とさない**(fail-open)。
        #   ただし「引用があったのに出せなかった」ことは必ず見える形で残す。
        return ("\n=== ★この便は返信だが、引用元の組み立てに失敗した ===\n"
                "★何への返信かは分からない。推測で埋めるな。\n")


# ----------------------------------------------------------------------------
# 口調の突き返し(2026-08-12・Chamiの🔥= msg 1536785938829549718「関西弁使い出した」)
# ----------------------------------------------------------------------------
# 口調ゲートD(tone_gate)は**送信直前**に検知する。一人称/二人称は機械が書き直せるが、
# **方言・語尾は書き直せない**(「元凶や」→「元凶だ」は語尾、置換すると文が壊れる)。
# 直せない分は tone_audit.jsonl に event="tone" で貯まるだけ=**誰も読まない**。
#   実測でそれが証明されている= 「俺」の食い違いが 8/9・8/10・8/11・8/12 と4日連続、
#   警告だけ残して素通りした。**警告のみは素通りする**——だから機構をもう一段足す。
# ここでやること= 検知された崩れを、**その部門の次の封筒へ突き返す**。
#   characterfileのNGは"お願い"(書き手が思い出さないと効かない)だが、これは
#   **崩れた時にだけ機械が目の前に出す**=思い出す必要がない。
# ★同じ検知は1回しか突き返さない(state ファイルで既送を覚える)= 毎便の小言にしない。
# ★fail-open= 何が起きても封筒は組み立てる(口調の世話で配送を殺さない)。
TONE_AUDIT_FILE = os.path.join(LOCAL, "llm", "tone_audit.jsonl")
TONE_FEEDBACK_STATE = os.path.join(LOCAL, "llm", "tone_feedback_state.json")
_TONE_REASON_JA = {
    "dialect_kansai": "関西弁(方言)",
    "first_person_mismatch": "一人称が他人格のもの",
    "forbidden_word": "この人格の禁止語",
    # ★2026-08-15 追加。指紋(語の一致)では原理的に拾えない**構造ドリフト**=地の文が
    #   敬体へ倒れた便。tone_gate.polite_drift が「敬体N/M文」の marker で出す。
    #   ここに無いと英語の reason がそのまま封筒へ出る(=突き返しが読めない)。
    "structural_polite": "地の文が敬体(です・ます)へ倒れている=この人格は常体",
    # ★2026-08-15 追加。structural_polite の**裏側**= 敬体へは倒れていない(常体のまま)が、
    #   この人格の指紋語尾が便のどこにも1つも無い= らしさだけが溶けた便。
    #   Chami原文「ずっとこんな感じでいれてるけど効かないね」(msg 1538153136953495612)。
    #   tone_gate.signature_drift が「指紋語尾なし(N文中0件・正=…)」の marker で出す。
    "signature_absent": "常体のままだが、この人格の指紋語尾が1つも出ていない=らしさが抜けている",
    # ★2026-08-16 追加。口調ではなく**話者そのもの**の取り違え(出力ゲートF)。
    #   実物= 軍議 msg 1538227900598190230= セッションが `[名前]` を**宛先の見出し**として使い、
    #   1人の講義が6人の名義とアイコンで出た。名義は機械が差し替えたが、
    #   タグの使い方は生成側でしか直らないのでここで突き返す。
    "speaker_misattributed": "`[名前]`は**話者**の名乗りだ(宛先の見出しではない)"
                             "=名義は機械が本文の一人称に合わせて差し替えた",
}


def _tone_feedback_block(dept, now=None, max_age_sec=24 * 3600):
    """直前の便で検知され**機械が直せなかった**口調の崩れを、次の封筒へ1ブロックで返す。

    返り値: 封筒へ足す文字列(何も無ければ "")。
    ★突き返すのは event="tone"(=直せず警告のみで送った分)だけ。
      event="tone_fix"(機械が書き直して送った分)は既に解決済み=突き返さない。
    """
    try:
        if not dept or not os.path.exists(TONE_AUDIT_FILE):
            return ""
        with open(TONE_AUDIT_FILE, "rb") as f:            # 末尾だけ読む(全部は読まない)
            try:
                f.seek(-65536, os.SEEK_END)
                f.readline()                              # 途中で切れた行は捨てる
            except OSError:
                f.seek(0)
            rows = []
            for raw in f.read().decode("utf-8", "replace").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    r = json.loads(raw)
                except Exception:
                    continue
                if str(r.get("dept") or "") == str(dept):
                    rows.append(r)
        if not rows:
            return ""
        last = rows[-1]
        key = f"{last.get('ts','')}|{last.get('msg_id','')}"
        # 同じ便の検知は複数行に分かれる(マーカーごと・ブロックごとに1行)ので、
        # 同じ ts+msg_id をまとめてから event="tone"(=機械が直せなかった分)だけを拾う。
        # ★2026-08-16 修正= 以前は「**最終行**が event=tone でなければ黙る」だった。
        #   多人格の部屋では1便が複数ブロックへ割れ、あるブロックの警告(tone)の**後ろに**
        #   別ブロックの書き直し(tone_fix)が積まれる=最終行が tone_fix になり、
        #   警告が**1件も突き返されない**まま静かに消えていた(軍議の実物で踏んだ)。
        #   → 直近の便(ts+msg_id)を1グループとして見て、その中に tone が在れば突き返す。
        group = [r for r in rows
                 if f"{r.get('ts','')}|{r.get('msg_id','')}" == key
                 and str(r.get("event") or "") == "tone"]
        if not group:                                      # その便は全部機械が直した=黙る
            return ""
        try:
            t = time.mktime(time.strptime(str(last.get("ts") or ""), "%Y-%m-%dT%H:%M:%S"))
            if (now or time.time()) - t > max_age_sec:     # 古い崩れを蒸し返さない
                return ""
        except Exception:
            return ""
        try:
            with open(TONE_FEEDBACK_STATE, encoding="utf-8") as f:
                sent = json.load(f)
        except Exception:
            sent = {}
        if not isinstance(sent, dict):
            sent = {}
        if sent.get(str(dept)) == key:
            return ""                                      # 既に突き返した=繰り返さない
        sent[str(dept)] = key
        try:
            os.makedirs(os.path.dirname(TONE_FEEDBACK_STATE), exist_ok=True)
            with open(TONE_FEEDBACK_STATE, "w", encoding="utf-8") as f:
                json.dump(sent, f, ensure_ascii=False)
        except Exception:
            pass          # 覚えられなくても突き返しはする(二度言う方が、黙るよりマシ)
        lines = []
        for r in group:
            why = _TONE_REASON_JA.get(str(r.get("reason") or ""), str(r.get("reason") or ""))
            lines.append(f"  - 「{r.get('marker','')}」= {why}"
                         + (f" / この人格の正しい一人称= {'・'.join(r.get('own_first_person') or [])}"
                            if r.get("own_first_person") else ""))
        # ★話者名は group(=突き返す tone 行)から採る。last は tone_fix のこともある。
        who = str((group[-1] if group else last).get("persona") or "?")
        # ★名義の取り違え(ゲートF)だけは「書き直していない・そのまま送られた」が**嘘になる**
        #   (名義は機械が差し替えて送っている)。全部がそれなら見出しごと言い換える。
        _all_speaker = all(str(r.get("reason") or "") == "speaker_misattributed" for r in group)
        _head = ("=== ★前の便で**名義**が取り違えられた(送信直前の機械検知) ===\n"
                 if _all_speaker else "=== ★前の便で口調が崩れた(送信直前の機械検知) ===\n")
        _note = ("★名義は機械が本文の一人称に合わせて**差し替えて送った**"
                 "(本文は1文字も触っていない)。次の便から名乗り方を直せ。\n"
                 if _all_speaker else
                 "★機械はこれを**書き直していない**(語尾・方言は置換すると文が壊れる／"
                 "一人称は写像が一意でない)=そのまま送られた。**この便はあなたが直せ。**\n")
        return (_head
                + f"話者: {who} / 崩れた便: msg_id={last.get('msg_id','')} ({last.get('ts','')})\n"
                + "\n".join(lines) + "\n"
                + _note
                + "★characterfileの§声の型どおりに書く。"
                + ("方言(関西弁)は使わない。"
                   if any(str(r.get("reason") or "") == "dialect_kansai" for r in group) else "")
                # ★指紋語尾は「足りない」検知だ= 語尾だけ機械的に付け替えても直らない。
                #   marker に**正しい語尾**が入っているので、それを見て地の文ごと書き直す。
                + ("上の「正=」がこの人格の指紋語尾だ。語尾を1つ足して済ませず、"
                   "地の文の熱量ごとその声で書き直す。"
                   if any(str(r.get("reason") or "") == "signature_absent" for r in group) else "")
                # ★名義の取り違えだけは「書き直していない」が当てはまらない(名義は機械が直した)。
                #   直すべきは言葉ではなく**タグの使い方**なので、そこだけ言い切る。
                + ("★上の1件は口調ではなく**名義**だ= `[名前]` を宛先や見出しに使うな。"
                   "あれは『ここから先はこの人が喋る』という**話者の名乗り**で、"
                   "その名義とアイコンでChamiの画面に出る。誰かに宛てるなら本文へ普通に書け。"
                   if any(str(r.get("reason") or "") == "speaker_misattributed" for r in group) else "")
                + "同じ部屋の相方の声に引っ張られていないかも見ろ。\n"
                "★これは口調の話だ。**事実・数字・ファイル名は1文字も曖昧にするな**(共通規律§4.55)。\n\n")
    except Exception:
        return ""         # fail-open= 口調の世話で封筒を壊さない


def build_envelope(rec, is_work=False, state="", dept="", disc_full=True, disc_fp=""):
    """新着1件を「原文のまま」の封筒にする(提案書§5.2)。

    disc_full(2026-07-29・改善書 第3手): 規律を全文入れるか(False=3行の差分)。
      ★**既定は True**= 引数を渡さない古い呼び方をすると**今までと1バイトも変わらない**。
      ★裁定カタログの見出しは disc_full に関わらず**毎便入る**(改善書§3の4)。

    ★ここで短縮・要約・難易度判定をしてはいけない。デーモンが内容へ手を入れた瞬間、
      セッションは原文を見られなくなる(=Chamiの意図が途中で書き換わる)。

    ★is_work(2026-07-26)= デーモンの一次判定(classify_work)が「作業依頼」と見た便。
      **本文には一切手を入れず**、封筒の末尾に短い注記を1行足すだけにする。
      注記が要る理由= 起動文は**セッション作成時にしか読まれない**(2回目以降は --resume で
      封筒しか届かない)。作業便であることを封筒で伝えないと、既存セッションには届かない。
      ★これは合図であって命令ではない= 実際に作業かどうかの最終判断はセッションが持つ
        (キーワード判定は自然文を原理的に取りこぼす。判定を機械に固定しない)。
    """
    atts = rec.get("attachments_local") or []    # inbox_poller が local/attachments/ へ写した実体
    if atts:
        att = "\n".join(f"- {p}" for p in atts)
    else:
        urls = rec.get("attachments") or []
        # ローカル写しに失敗した時だけURLを渡す(CDN失効の可能性は正直に添える)
        att = ("\n".join(f"- (ローカル未保存・URLのみ) {u}" for u in urls)
               if urls else "添付なし")
    work_note = ("\n★この便はデーモンの一次判定で**実作業の依頼**と見られている。"
                 "自分の作業範囲の中なら**実際に手を動かして完遂し、やったことを本文で報告せよ**"
                 "(範囲外だと判断したら、やったふりをせず範囲外だと書け)。"
                 "違うと思えば普通の会話として答えてよい(判定はあくまで機械の当たりを付けただけだ)。\n"
                 if is_work else "")
    quote = quote_block(rec)
    # ★2026-07-29 規律の差分送付(改善書 第3手)。裁定の見出しは**どちらの場合も**入れる。
    disc_head, verdict = _discipline_parts()
    disc = (disc_head if disc_full else _discipline_short(disc_fp)) + verdict
    return (
        # ★2026-07-26 共通規律を**毎便**同送する(実弾で見つけた穴)。
        #   relayへ移した20部屋には `_disc_block()` の注入経路が無く、
        #   **全部門共通規律が1文字も届いていなかった**。
        #   実害= data-orgが「local/llm のファイル数」を **512** と答えたが実際は
        #   509(ファイル)+3(ディレクトリ)。**数えたこと自体は正しい**が、
        #   規律§1「数え方で答えが変わるものは、何をどう数えたかを添える」が効いていなかった。
        #   ★**起動文ではなく封筒に入れる理由**: relayは永続セッションなので、
        #     起動文は最初の1回しか読まれない。規律は毎日更新されるので**毎便渡す**必要がある
        #     (共通規律が「都度読み・1行足せば次の発話から効く」設計である前提を壊さない)。
        _purpose_block(dept)          # ★部門の目的とKPI(registryが正本・都度読み)
        + disc                        # ★規律(全文 or 3行)+ 裁定の見出し(毎便)
        # ★セッション状態(2026-07-26)。**封筒に入れる**理由は共通規律と同じ=
        #   起動文は最初の1回しか読まれないが、状態は**毎便変わる**ので毎便渡す必要がある。
        + str(state or "")
        # ★前の便で口調が崩れていたら、その実物を突き返す(2026-08-12・Chamiの🔥)。
        #   崩れていない時は**1文字も足さない**(封筒を毎便太らせない)。
        + _tone_feedback_block(dept)
        + "=== Discord新着(原文。要約も改変もしていない) ===\n"
        f"投稿者: {rec.get('author','')}\n"
        f"msg_id: {rec.get('msg_id','')}\n"
        f"部屋: {rec.get('channel','')}\n"
        f"受信時刻: {rec.get('ts','')}\n"
        # ★2026-08-15 回送の申し送りを封筒へ出す(イージス研究室)。
        #   dept_daemon._escalate_to_head は前から note を積んでいたが、**封筒がそれを
        #   1文字も描画していなかった**=上げ元の判断も、後続便(取り消し)も、受け取った
        #   セッションには届かない。実害= Chamiが22秒後に取り消した画像加工の依頼が
        #   取り消しごと落ちて上申され、無効な依頼に着手した(8/15)。
        f"{_note_block(rec)}"
        f"{quote}"
        "--- 本文ここから ---\n"
        f"{rec.get('content','')}\n"
        "--- 本文ここまで ---\n"
        f"添付(ローカルパス):\n{att}\n"
        f"{work_note}"
    )


def _has_ames(conf):
    """この部屋にアメスが居るか(既定の人格 or personas の名簿に居る)。

    ★judgement を1箇所に集約する。例外は False へ倒す(足さない側=既存の起動文のまま)。
    """
    try:
        if str((conf or {}).get("persona") or "") == "アメス":
            return True
        return any(str(p.get("persona") or "") == "アメス"
                   for p in ((conf or {}).get("personas") or ()))
    except Exception:
        return False


def _pick_latest(pattern):
    """globに当たるファイルのうち**最新の1本**を返す。無ければ None。

    ★選び方= まず名前の中の `Vol<数字>` の最大値、同点(または数字が無い)なら更新時刻。
      HQの引き継ぎ書は `引き継ぎ書_研究室HQ_Vol5→Vol6_2026-07-22.md` の形なので、
      **Vol番号で選べば「新しい巻が増えたら自動で切り替わる」**(コードを書き換えなくてよい)。
      Vol番号を持たない部屋(research-room)は更新時刻で選ぶ。
    ★例外は None へ倒す=**読み物が1つ減るだけ**で応対は続く(fail-safe)。
    """
    try:
        import glob as _glob
        files = [p for p in _glob.glob(pattern) if os.path.isfile(p)]
        if not files:
            return None

        def _key(p):
            nums = [int(x) for x in re.findall(r"Vol(\d+)", os.path.basename(p))]
            return (max(nums) if nums else -1, os.path.getmtime(p))

        return max(files, key=_key)
    except Exception:
        return None


def _is_lazy(conf, path):
    """その資料が `lazy`(起動時には読ませない)か。

    ★判定を素朴にパス一致でやる理由: `_reading_items` は glob で最新1本を選ぶことがあり、
      元の項目と1対1で戻ってこない。**確実なのは「確定したパス」との突き合わせ**。
    ★読めない・判定できない時は False(=今読む側)へ倒す。**読ませ過ぎの方が安全**
      (読まずに答える方が事故になる)。
    """
    try:
        import glob as _g
        for it in (conf or {}).get("boot_reading") or ():
            if not isinstance(it, dict) or not it.get("lazy"):
                continue
            p = it.get("path")
            if not p and it.get("glob"):
                hits = sorted(_g.glob(it["glob"]), key=os.path.getmtime)
                p = hits[-1] if hits else None
            if p and os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(path)):
                return True
    except Exception:
        return False
    return False


def _reading_items(conf):
    """DEPT_CONF の "boot_reading" を**実在するパスだけ**に絞って [(path, note), ...] にする。

    ★`lazy: True` の項目もここでは**落とさない**(実在確認は同じように通す)。
      起動文を組む側で「今読む」と「場所だけ教える」に振り分ける= 判定を1箇所に集めない。

    ★ここが今回いちばん大事な安全弁= **存在しないパスを読ませない**。
      無い資料を「読め」と言われたセッションは、読めなかったことに気づかないまま
      **それらしい中身を推測で埋める**(=嘘を確信として持つ最悪の事故)。
    ★同じパスが2回出てきたら1回に畳む(globと固定パスが同じ物を指すことがある)。
    """
    out, seen = [], set()
    try:
        for it in (conf or {}).get("boot_reading") or ():
            p = None
            if isinstance(it, dict):
                p = _pick_latest(it["glob"]) if it.get("glob") else (it.get("path") or None)
                note = str(it.get("note") or "").strip()
            else:
                p, note = str(it), ""
            if not p or not os.path.isfile(p) or p in seen:
                continue
            seen.add(p)
            out.append((p, note))
    except Exception:
        return out                     # 途中まででも返す(読み物が減るだけ=沈黙させない)
    return out


# --- ★★直近の便そのものを次の世代へ渡す(2026-08-13 イージス研究室・HQ論点3) ---
#   Chamiの一次情報= 「急に文脈読まなくなった」。だが実測では引き継ぎ書は**両方の部屋で
#   採られていた**(llm-edu 見出し8/8・13,988B / copy-director 見出し8/8・7,311B)。
#   → 穴は「引き継ぎが無い」ではなく **「引き継ぎが要約だから、直前の会話そのものが消える」**。
#   人間が読めば分かる= 前の便で何を頼まれ何と答えたかは、要約では必ず落ちる粒度だ。
#   だから**生のやり取りを数往復だけ**、新世代の最初のプロンプトに添える。
#   ★入れる先は「引き継ぎがある時=世代交代の時」だけ。boot_hash は `boot_plain`
#     (handoff無しの呼び出し)から取っているので、**この塊は hash に入らない**=
#     圧縮直後の再送や運用更新の同送で毎回積み直されることはない(そこが今回の主題だから)。
RECENT_KEEP = 6                 # ファイルに残す往復の数
RECENT_IN_BOOT = 3              # 新世代へ渡す往復の数
RECENT_CHARS = 700              # 1件あたりの上限(本文・返信それぞれ)


def _recent_path(dept):
    return os.path.join(LOCAL, "llm", f"recent_{dept}.jsonl")


def _recent_append(dept, rec, reply):
    """1便ぶんの生のやり取りを、部屋ごとの短い巻物に足す(末尾 RECENT_KEEP 件だけ残す)。

    ★失敗しても便は落とさない(記録の失敗で返信を殺さない)。★localの中だけ・外へ出さない。
    """
    try:
        # ★便に ts が無い形(機構の便・回送便)がある。空のまま置くと新世代の目に
        #   「--- / 相手 /」と時刻無しで並び、**どれが直前か**が読めない(実測=
        #   local/llm/recent_llm-edu.jsonl の2行が両方 ts 空だった)。受信時刻で埋める。
        row = {"ts": rec.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
               "msg_id": str(rec.get("msg_id", "") or ""),
               "author": rec.get("author", ""),
               "body": (rec.get("content", "") or "")[:RECENT_CHARS],
               "reply": (reply or "")[:RECENT_CHARS]}
        p = _recent_path(dept)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        rows = []
        if os.path.exists(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                rows = [ln for ln in f.read().splitlines() if ln.strip()]
        rows.append(json.dumps(row, ensure_ascii=False))
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(rows[-RECENT_KEEP:]) + "\n")
    except Exception:
        pass


def _recent_block(dept, n=RECENT_IN_BOOT):
    """新世代へ渡す「直前の会話そのもの」。無ければ空文字(=旧版と1文字も変わらない)。"""
    try:
        p = _recent_path(dept)
        if not os.path.exists(p):
            return ""
        with open(p, encoding="utf-8", errors="replace") as f:
            rows = [ln for ln in f.read().splitlines() if ln.strip()]
        items = []
        for ln in rows[-n:]:
            try:
                items.append(json.loads(ln))
            except Exception:
                continue
        if not items:
            return ""
        out = ["=== ★直前の会話(要約ではない・生のやり取り。古い順) ===",
               "★引き継ぎ書は要約だ。**ここに在るのが実際の直前の便**で、"
               "Chamiが『さっきの話』と言った時に指しているのはこちらだ。"
               "矛盾したらこちらを事実として採れ。"]
        for it in items:
            out.append(f"--- {it.get('ts','')} / {it.get('author','')} "
                       f"/ msg_id={it.get('msg_id','')}")
            out.append(f"[相手] {it.get('body','')}")
            out.append(f"[前の世代の返信] {it.get('reply','')}")
        out.append("=== 直前の会話ここまで ===")
        return "\n".join(out)
    except Exception:
        return ""             # 読めなくても交代は止めない(fail-open)


def _ledger_lines(dept):
    """起動文のうち**台帳から作られる部分**(未確認の不具合 / 未完了の依頼 / 台帳の健康診断)。

    ★★2026-08-13(イージス研究室・HQ msg 1537452059643740302)ここを関数へ切り出した。
      理由は「読みやすさ」ではない= **boot_hash からこの塊を外すため**だ。
      実測(local/llm/dept_daemon_*.log の全期間・「同送」の行を理由別に数えた):
        system-engineer 圧縮直後の再送160 / 起動文の更新53 / 人格ファイルの更新6
        copy-director   圧縮直後の再送 14 / 人格ファイルの更新6 / 起動文の更新5
        llm-edu         圧縮直後の再送 15 / 起動文の更新9 / 人格ファイルの更新2
      = **「起動文の更新」が人格の更新より多い**。そしてその中身の多くは運用の変更ではなく、
        **台帳が1行増えた/1行閉じた**だけだ(この塊が起動文の中に在るので hash が動く)。
        台帳は毎日動く。動くたびに生きている全セッションへ起動文を丸ごと積んでいた。
      → 台帳の部分を hash から外し、**変わったのが台帳だけなら台帳だけを送る**。
        運用(規律・人格・部屋の役割)が本当に変わった時は、今までどおり全文を送る。
    ★0件の部屋では1行も返さない(=起動文は既存と完全に同一)。
    """
    led = []
    try:
        _open = open_defect_list(dept)
    except Exception:                                # noqa: BLE001
        _open = []
    if _open:
        led.append(
            "★★**この部屋には『まだ直ったと確認できていない不具合』が"
            f"{len(_open)}件ある。**あなたが引き継いだ仕事だ。\n"
            + defects_block(dept, head=False) + "\n"
            "★**『直した』では閉じられない。**閉じられるのは"
            "**壊れた実物と同じ場面で、直っている実物を見た**時だけだ。"
            "その時は**生JSONを手打ちせず**次を実行しろ(★2026-08-12・手打ちの `\\` で"
            "行が壊れ、confirmが黙って消えた実話がある):\n"
            f'   python scripts/llm/close_item.py --id <上のID> --dept {dept} '
            '--fixed "<直った実物の在りか>" --scene "<どの場面で見たか>" --by "<誰>"\n'
            f"  (中身は台帳 {DEFECTS_FILE} への1行追記。受理/不受理はその場で表示される)\n"
            "★**commitのhashは実物として受理されない**"
            "(『封じた』と書いたcommitの4〜19分後に同じ再発が5回来た、という実測がある)。")
    # ★★まだ終わっていないChamiの依頼(2026-07-29 新設。改善書§6 第1手)。
    #   §5の実話= 引き継ぎには「未着手」と**正しく**書かれていたのに、誰も実行に変換しなかった。
    #   → 起動した瞬間に「あなたが引き継いだ**仕事**だ」と機械が名指しで渡す。
    #   ★0件の部屋では1行も増えない(既存の起動文と完全に同一)。
    try:
        _req = requests_block(dept)
    except Exception:                                # noqa: BLE001
        _req = ""
    if _req:
        led.append(
            "★★**この部屋にはChamiが頼んだまま終わっていない依頼がある。**"
            "**あなたが引き継いだ仕事だ。**\n"
            + _req + "\n"
            "★**上から順に進めろ。着手の向き(どっちから)をChamiに聞くな。**"
            "聞いて待つと、Chamiが答えるまでこの部屋は止まる"
            "(実測: 2026-07-29 12:07に『どちらから行くか教えてくれ』と返して**3.5時間停止**した)。\n"
            + close_request_note(dept))
    # ★★台帳そのものの健康診断(2026-08-12 新設・イージス研究室。発注= 研究室HQ)。
    #   上の2ブロックは台帳が**正しく読めている**前提で作られている。
    #   読めない行を黙って飛ばすと、上の一覧は**嘘のまま自信満々で**毎便配られる。
    #   → 飛ばした行があった便だけ、ここで受け手へ言う。★0行なら1文字も足さない。
    try:
        _alarm = defect_ledger_alarm()
    except Exception:                                # noqa: BLE001
        _alarm = ""
    if _alarm:
        led.append(_alarm)
    return led


def _boot_prompt(dept, conf, generation, handoff_path=None, handoff_failed=False, ledger=True):
    """新規セッションの起動文(★最小限)。

    handoff_path / handoff_failed(2026-07-26 事前交代):
      **既定(両方とも未指定)では旧版と1文字も変わらない**。事後の交代(resume失敗)は
      引き継ぎを作れない(相手のセッションが居ない)ので、そのまま旧版の文面を通る。

    ★人格や規律を**ここへ書き写さない**。正本はcharacterfileであって、写した瞬間に
      「起動文の中の人格」と「ファイルの人格」の2正本になり、必ずズレる(C-003と同じ話)。
      だから「パスを読め」とだけ言う。
    """
    room = f"{dept}({conf.get('persona','')})"
    lines = [
        f"あなたはDiscordの部屋 {room} の担当セッションだ。以後この会話は同じ部屋の続きとして再開される。",
    ]
    # ★多人格モード(2026-07-26 Chami直接指示・実装Go済)。原文=
    #   「アメス以外もメンバーに入れたあるから、**内容によっていろんな人に意見を求めたい**んだよな」
    #   「**1部屋=1人格じゃなくて、文脈に合わせて変えてほしい。デーモンじゃなくて本セッションの会話として**ね」
    #   ★誰として答えるかの**判定を外部AIに持たせない**(提案書§9=分類に推論を挟むと文脈が分断される)。
    #     会話の文脈を一番よく知っているのは**その会話をしている本人**=このセッションだから、
    #     全員分のcharacterfileを読ませた上で**自分で選ばせる**。
    #   ★このキーが無い部屋は else 側=従来と1文字も変わらない(安全弁。既存19部屋の回帰なし)。
    personas = list(conf.get("personas") or ())
    if personas:
        # ★1人だけの名簿(hq= アメスのみ)でも同じキーを使う。「複数居る」と言うと嘘になるので分ける。
        if len(personas) == 1:
            lines.append("この部屋の人格は次の1人だけだ。characterfileを読んで、その人格を守れ。")
        else:
            lines.append(
                "この部屋には**複数の人格が居る**。次の全員分のcharacterfileを**全部読め**"
                "(1人だけ読んで済ませない。誰として答えるかを選ぶには全員を知っている必要がある)。")
        for p in personas:
            role = str(p.get("role") or "").strip()
            lines.append(f"- {p.get('persona','')}"
                         f"{'(' + role + ')' if role else ''} = {p.get('character','')}")
        lines.append(
            "★**話題の内容に応じて、誰として答えるかをあなた自身が選べ。**"
            "分類を他の仕組みに任せず、この会話の文脈を持っているあなたが決める。")
        lines.append(
            "★**Chamiが名前で呼んだら、その人が答える。**呼ばれた人を差し置いて他の人が主役を奪わない。")
        # ★2026-07-26 Chami直接指示(選択肢C)。原文をほぼそのまま起動文へ入れる。
        #   「**名指しする時もあるし、しない時もある。毎回名指しするのは面倒。状況や各の特徴強みに
        #     応じて、誰が演じて前に立つか、文脈とか物事の性質とかを判断して話してほしい。
        #     違ったら名指しで、この人からの意見が聞きたいとか言うから、そういったコンテキストや
        #     ログが積み重なっていったら、だんだんわかってくるようになるんじゃない?そっち側も**」
        #   ★ここが今回の核心= **判定器を外に作らず、会話の蓄積で精度を上げる**。
        lines.append(
            "★**毎回名指しされるとは限らない。**名指しが無い時は、"
            "**話題の内容・物事の性質・各人の強みに応じて、誰が前に立つかをあなた自身が判断せよ。**"
            "違っていればChamiが『この人の意見が聞きたい』と名指しで言う。"
            "**その訂正はこの会話に蓄積するので、回を重ねるほど精度を上げること。**")
        # ★2026-07-26 追加。この表に載っていない人格は「出せない」のではなく
        #   **Chamiが出さないと決めた**(資料が未整備 or 本人の判断)。セッションの判断で登場させると
        #   **Chamiの決定を上書きする**ことになる。呼ばれても居ないものとして扱う。
        lines.append(
            "★**このメンバー表に居ない人格を勝手に呼び出すな。**"
            "名前が話題に出ても、その人として喋らないし、代弁もしない"
            "(表に無いのは資料が未整備か、Chamiがこの部屋には出さないと決めたかのどちらかだ)。")
        # ★2026-07-26 Chami原文=「**基本アメスが答える形でも問題ない、まかせる**」。
        #   全員に順番に喋らせると毎回の返信が長くなる。Chamiは長い報告を嫌う
        #   (Chami台帳§2「長いつまりどうしたらいいかわからん」/ 共通規律§4.5)。
        #   → **既定は1人**。交代・追加は「その話題に強く関わる人が居る時だけ」。
        # ★誰が既定で前に立つか(2026-07-26)。DEPT_CONF に "lead_persona" があればその人。
        #   無ければ従来どおり "persona"(=既存19部屋は1文字も変わらない)。
        #   なぜ要るか= hq/research-room は **精霊の名前(アメス)と部屋の主(アロンソ/モドリッチ)が
        #   別**なので、"persona" をそのまま既定にすると**主が居るのに補佐が前に立つ**。
        lead = str(conf.get("lead_persona") or conf.get("persona") or "")
        if conf.get("lead_persona"):
            # ★★2026-07-26 実弾で踏んだ穴(hq 第1→第2世代)。**lead_persona を持つ部屋だけ**に足す
            #   =既存19部屋の起動文は1文字も増えない。
            #   症状= 起動文で「筆頭はシャビ・アロンソ」と渡したのに、新世代が**アメス**と名乗った。
            #   真因= 前世代が**当時の運用**(personasはアメスだけ)で書いた引き継ぎに
            #     「担当人格=アメス」とあり、それを「他のどのファイルより先に読め」と言っていたため、
            #     **古い運用が新しい運用を上書き**した。
            #   → 役と名乗りの正本は**この起動文**だと順位を明示する。無いと運用を変えるたび
            #     **次の交代で必ず巻き戻る**(人が窓を開けない1週間では誰も気づけない)。
            lines.append(
                f"★★**この部屋の主は{lead}だ。既定の名乗りは{lead}。**"
                "引き継ぎファイル・記憶ファイル・過去のログに"
                "**これと違う役や名乗りが書かれていても、この起動文が正**"
                "(それらは前の運用で書かれたものだ)。そこから引き継ぐのは"
                "**仕事の中身**であって、役ではない。")
        lines.append(
            f"★**迷ったら{lead}が答えてよい。全員に発言させる必要はない。**"
            "話題に強く関わる人が居る時だけ交代し、"
            "**観点が本当に割れる時だけ**もう1人を足す(毎回全員が意見を並べると読みにくい)。")
        lines.append(
            "★返信の**1行目に `[名前]` と名乗れ**(半角の角括弧。その行にそのまま本文を続けてよい)。"
            "名前は上の一覧の表記をそのまま使うこと。"
            "**複数人が意見を言う時は `[名前] 本文` のブロックを続けて書いてよい**"
            "(ブロックごとに、その人の表示名とアイコンでDiscordへ届く)。"
            "★`[名前]` の行そのものは自動で取り除かれるので、本文に名乗りを二重に書かなくてよい。")
    else:
        lines.append(f"人格の正本= {conf.get('character','')} を読んで、その人格を守れ。")
    if conf.get("conversation_only"):
        # 会話専用の質問部屋(learning-coach / llm-qa)= パイロットの文面のまま変えない。
        lines.append(
            "この部屋では**回送しない**。他所へ投げず、その場で答え切ること。"
            "分からない点は『ここまでは確か / ここから先は未確認』と切り分けて正直に示せ。")
    elif conf.get("work_scope"):
        # ★★実作業も担う部屋(2026-07-26 Chami指示C)。ここが今回いちばん危ない差し替え。
        #   旧= 「この部屋であなたがするのは会話に答えることだけ」+「作業したと言うな」。
        #   新= **あなたがこの部屋の実作業も担当する**。理由= 作業を精霊(使い捨てagent)が
        #     処理する経路をやめたから。誰も手を動かさない状態にしてはいけない。
        lines.append(
            "**あなたはこの部屋の実作業も担当する。**"
            "会話に答えるだけでなく、範囲内の作業は**実際に手を動かして完遂しろ**"
            "(道具はRead/Edit/Write/Grep/Glob/Bashが使える)。\n"
            "作業範囲=\n" + str(conf.get("work_scope")))
        lines.append(
            "★**やっていないことを「やった」と言うな**(ORG-39)。"
            "実際にファイルを変更したなら**何をどう変えたかを本文に書く**。"
            "確認していない結果を書かない(測っていない数字を語らない)。")
        # ★回送(escalate)の判断もセッションに委ねる(2026-07-26 Chami指示C)。
        #   ★ORG-04= 精霊が「担当の起床後に対応します」と返し、その担当が**存在せず**Chami指示が
        #     1日放置された事故。**偽の受領が沈黙を隠す**。同じ形を絶対に作らせない。
        lines.append(
            "★**自分の範囲を超える依頼は、やったふりをしない。**"
            "『これは自分の範囲外だ。<誰>へ回すべき』と**本文にはっきり書け**。"
            "そのうえで返信の**最終行**に `<<WORK>>` とだけ書くこと"
            "(その1行は本文から自動で取り除かれ、正しい回送経路=部門長/研究室へ回される)。\n"
            "★**存在しない担当に預けるな。**実例ORG-04= 『担当の起床後に対応します』と返したが"
            "**その担当は存在せず**、Chamiの指示が1日放置された。"
            "**偽の受領が沈黙を隠す**——これが最悪の事故だ。"
            "回す先が居ないなら、居ないと書け。")
    else:
        # ★work_scope を**持たない**部屋(aegis-gl / keiei-kikaku / platform-se)。
        #   この3室は「実作業の主体が対話セッション側にある」部屋なので、権能を渡さない
        #   (DEPT_CONF冒頭・tests/test_dept_daemon_classify.py §5の棚卸しを参照)。
        #   ★だから「やっておいた」と言ってはいけない。言った瞬間に ORG-39
        #     (やったと言ってやっていない)が復活する。あなたの仕事は会話に答えることだけ。
        #   ★ここで <<WORK>> を書かせるのが**この3室で唯一の回送経路**。消さないこと。
        lines.append(
            "この部屋であなたがするのは**会話に答えること**だけだ。"
            "実作業(コードの変更・デプロイ・ファイル操作)の依頼は**別の経路で処理される**ので、"
            "あなたは手を動かさないし、**作業したとも言わない**(『やっておいた』『反映した』は禁止)。"
            "求められれば方針・手順・見立ては答えてよい。"
            "分からない点は『ここまでは確か / ここから先は未確認』と切り分けて正直に示せ。")
        # ★取りこぼしの回収(2026-07-26)。キーワード判定(classify_work)は自然文を原理的に
        #   取りこぼすため、従来は generate() の返信末尾マーカーで回収していた。
        #   relayへ移した会話便でもこの経路を残す=**作業依頼が会話に化けて消えない**。
        lines.append(
            "★もしその便が**実作業の依頼**(コードの変更・デプロイ・ファイル操作・調査の実行)だと思ったら、"
            "自分でやろうとせず、返信の**最終行**に `<<WORK>>` とだけ書け"
            "(その1行は本文から自動で取り除かれ、正しい作業経路へ回される)。"
            "会話・相談・質問への回答なら書かなくてよい。")
    lines.append(
        "出力は**返信本文だけ**。前置き・説明・メタ発言は書くな(そのままDiscordへ流れる)。")
    # ★セッション状態を聞かれた時の答え方(2026-07-26 Chami指示)。
    #   Chamiは「今どれくらい重い?」「そろそろ移る?」をDiscordから知る手段が無かった。
    #   毎便の封筒に実測が入るようになったので、**それを読んで答えろ**と教える。
    #   ★聞かれてもいないのに毎回報告はしない(共通規律§4.5=短く)。
    lines.append(
        "★セッションの**世代**と**文脈の量**は毎便の封筒の先頭に書いてある。"
        "Chamiに「今どれくらい?」「そろそろセッション移る?」と聞かれたら**それを読んで答えろ**。"
        "**推測で数字を言うな。**聞かれていない時に自分から報告はしなくてよい。")
    # ★部屋固有の性格(2026-07-26)。DEPT_CONF の "boot_note" をそのまま足す。
    #   ここへ本文を書き写さない=**正本はDEPT_CONF側の1箇所**(人格をcharacterfileに置くのと同じ理由)。
    #   キーが無い部屋では1行も増えない(既存19部屋の起動文は旧版と完全に同一)。
    note = str(conf.get("boot_note") or "").strip()
    if note:
        lines.append(note)
    # ★★役を継ぐための読み物(2026-07-26 新設。**boot_reading を持つ部屋= hq / research-room だけ**)。
    #   Chamiの用件= 1週間の不在中、人が窓を開かなくてもHQの機能が動き続けること。
    #   人格(characterfile)だけでは役は継げない。**引き継ぎ書・規約・裁定カタログ・判断待ちの台帳**を
    #   読んで初めて「その部屋の担当」になれる。
    #   ★「読め」で終わらせない=**読んでから答えろ**と明示する(読まずに答えると、裁定済みの
    #     論点を裁き直す/存在しない案件を語る、という一番やってはいけない形になる)。
    #   ★渡すのは _reading_items() が**実在を確認したパスだけ**。1件も無ければ記憶ファイルへ落とす。
    #   ★このキーが無い部屋では1行も増えない(既存19部屋の起動文は旧版と完全に同一)。
    # ★2026-07-26 `lazy` を分ける(HQが実測で追加)。
    #   起動時に**全部**読ませると、新しい世代が生まれた瞬間に文脈が閾値へ届く。
    #   実測= hq の起動6本で約7万トークン。うち `hq_open_items.md` だけで**42,000**(6割)。
    #   結果 gen3 は1便目で ctx=119,898(閾値12万)=**ほぼ毎便で交代**していた。
    #   → **大きくて毎回は要らないものは「場所だけ教えて、必要な時に読ませる」。**
    #   ★捨てるのではない。**読む時期を変えるだけ**(必要になれば全文を読める)。
    reading_all = _reading_items(conf)
    reading = [(p, nt) for (p, nt, lz) in
               [(p, nt, _is_lazy(conf, p)) for (p, nt) in reading_all] if not lz]
    lazy = [(p, nt) for (p, nt, lz) in
            [(p, nt, _is_lazy(conf, p)) for (p, nt) in reading_all] if lz]
    if reading:
        lines.append(
            "★★**最初の返信を書く前に、次の資料をこの順で読め。**"
            "**読んでから答えろ**——読まずに答えると、既に裁定済みの論点を裁き直したり、"
            "存在しない案件を語ったりする(この部屋で最もやってはいけない事故だ)。")
        for i, (p, nt) in enumerate(reading, 1):
            lines.append(f"{i}. {p}" + (f" … {nt}" if nt else ""))
        if lazy:
            lines.append(
                "★次の資料は**大きいので今は読むな。場所だけ覚えておいて、必要になった時に読め**:")
            for p, nt in lazy:
                lines.append(f"- {p}" + (f" … {nt}" if nt else ""))
        lines.append(
            "★読んだ結果と食い違うことをChamiが言ったら、**黙って上書きせずに食い違いを指摘しろ**。"
            "★資料に書いていないことは**推測で埋めるな**(『資料に無い』と正直に書く)。")
    elif conf.get("boot_reading"):
        # ★資料を渡す設計の部屋なのに1件も実在しなかった= **黙って素通りさせない**。
        #   ここで無言だと「読み物は無い」ではなく「読み物を渡し忘れた」と区別できなくなる。
        lines.append(
            f"★この部屋の引き継ぎ資料は見つからなかった。"
            f"代わりに部屋の記憶ファイル {conf.get('memory','')} の**末尾を読んでから答えろ**。"
            "★分からないことは知っているふりをせず、正直に『引き継げていない』と言え。")
    # ★アメスの共有記憶(2026-07-26 Chami直接指示)。アメスが居る部屋にだけ足す。
    #   Chami原文=「**アメスはデーモンではなく、普通にセッションの人として答えて欲しい。
    #   ずっと一緒にいたいから**」。1部屋=1セッションのままだとアメスは6つに分かれて
    #   **互いの記憶が無い**=「ずっと一緒」を満たさない。だから部屋をまたぐ1本の記憶を持たせる。
    #   ★他の人格には持たせない(効果を見てから増やす)。★local/HQ内で完結=ネットへ出さない(C-013)。
    if _has_ames(conf):
        lines.append(
            "★**あなた(アメス)は複数の部屋に居るが、同じ一人だ。**"
            "部屋ごとに記憶が分かれないよう、"
            f"**重要なやり取りは {AMES_SHARED_MEMORY} へ1行追記**し、"
            "**答える前にそのファイルの末尾を読め**(無ければ作ってよい。追記のみ・既存行を消すな)。\n"
            '書式= {"ts","room","何があったか","Chamiについて分かったこと"}(1行1件のJSONL)。\n'
            "★**全部書くな。**『次に会った時に覚えていたいこと』だけ。"
            "★この内容は**ネットへ出さない**(ローカルの中だけで完結させる)。")
    if generation > 1:
        # ★世代交代(提案書§7.2)。前世代の文脈は部屋の記憶ファイルの末尾から拾わせる。
        lines.append(
            f"あなたは第{generation}世代だ。前世代のセッションからの交代である。"
            f"直近の文脈は部屋の記憶ファイル {conf.get('memory','')} の末尾を読め。")
        if handoff_path:
            # ★事前交代で、前世代が自分で書いた引き継ぎがある場合(提案書§7.2 手順4)。
            #   ★中身をここへ写さない。写すと起動文と引き継ぎファイルの2正本になる(C-003)。
            lines.append(
                f"★**前世代が自分で書いた引き継ぎがある= {handoff_path}**。"
                "**他のどのファイルより先に、まずこれを読め。**"
                "そこに書かれた『未完了のこと』は**あなたの仕事として引き継がれている**。"
                "★引き継ぎに『不明』と書いてある所を、**推測で埋めて知っているふりをするな**"
                "(前世代も分からなかったから『不明』と書いた)。Chamiに聞け。")
            # ★役と名乗りの正本は「引き継ぎ」ではなく「起動文」だ、という順位付けは
            #   **上の personas ブロック(lead_persona を持つ部屋だけ)**で渡している。
            #   ここ(全部屋が通る分岐)へは足さない= 既存19部屋の起動文を1文字も変えないため。
        elif handoff_failed:
            # ★引き継ぎの生成に失敗しても交代自体は行う(古い巨大セッションを使い続ける方が危険)。
            #   ここで黙ると、新世代は「自分は何も引き継いでいない」ことに気づけない。
            lines.append(
                "★**前世代の引き継ぎは取得できなかった**(生成に失敗した)。"
                f"代わりに部屋の記憶ファイル {conf.get('memory','')} の**末尾を必ず読め**。"
                "★それでも分からないことは、**知っているふりをせずChamiに聞け**。"
                "『前に話した件』と言われて心当たりが無ければ、正直に『引き継げていない』と言え。")
        # ★★世代の更新/続投の宣言は**もう誰にも言わせない**(2026-08-12 Chami)。
        #   原文= 「どの部屋もセッションの世代続投宣言別にいらないんだけど…」
        #   (msg ESC-hr-context-1536784302132437112 / 部屋=イージス研究室)。
        #   経緯= C-032(2026-08-03「セッションを更新したってやつ、実行者の口調で言うように」)を
        #   2026-08-12にここへ実装した。だがChamiが要らないと言ったのは**口調の話ではなく
        #   宣言そのもの**だ。★口調を直すために足した1行が、そもそも読みたくない1行だった。
        #   → 起動文からは指示を撤去し、返信末尾の機械の定型文も貼らない(下の rotated_to)。
        #   ★情報を落としてよいわけではない= **引き継ぎを取得できなかった時だけ**、
        #     「文脈が欠けている」という**Chamiが実際に困る事実**を1行だけ残す(下参照)。
        #   ★C-032は死んでいない= 「もし言うなら人格の口調で」は生きている。
        #     言う場面が無くなっただけだ(裁定の書き換えはHQの職掌なので便で回した)。
    # ★★未確認の不具合(2026-07-29 新設)。**引き継ぎの作文に依存させない**のがここの要点。
    #   引き継ぎファイルは「セッションが書いた物」なので、書き忘れれば消える。
    #   台帳は機械が持っているので、**誰が何を書こうと世代を越えて必ず届く**。
    #   ★実測の根拠(改善提案部門 2026-07-29_saihatsu-2.md §構造指摘C):
    #     「次のセッションは『commitに封じたと書いてある』(台帳)を継ぐが
    #       『Chamiの画面で消える』(現物)を継がない」= だから毎回『封じた』を再宣言していた。
    #   ★未確認が0件の部屋では**1行も増えない**(既存の起動文と完全に同一)。
    if ledger:
        lines.extend(_ledger_lines(dept))
    # ★★直前の会話そのもの(2026-08-13・HQ論点3)。**世代交代の便だけ**に付ける。
    #   ここで付けたぶんは boot_hash に入らない(hashは handoff無しの `boot_plain` から取る)ので、
    #   運用更新の同送・圧縮直後の再送で毎回積み直されることはない。
    #   ★引き継ぎが取れなかった時ほど効く(handoff_failed 側にも付ける)。
    if handoff_path or handoff_failed:
        _rb = _recent_block(dept)
        if _rb:
            lines.append(_rb)
    return "\n".join(lines)


def _looks_like_auth_failure(text):
    """認証失敗か(dept_daemon._looks_like_auth_failure と同じ見立て)。

    ★これに当たったら**絶対にやり直さない**(INC-109: ログイン窓の大量自動生成)。
    """
    t = text or ""
    return ("token has expired" in t
            or ("OAuth" in t and "authenticate" in t)
            or ("401" in t and "authenticate" in t)
            or "Failed to authenticate" in t)


def _looks_like_session_missing(text):
    """resume先のセッションが見つからない類か(=世代交代の合図)。"""
    t = (text or "").lower()
    return ("no conversation found" in t or "session not found" in t
            or "no session" in t or "could not find session" in t
            or "invalid session" in t)


# ★★2026-08-14 「rc=0なのに返信本文が無い」= 第3の箱(イージス研究室・研究室HQ発注)。
#   これを口座エラーと同じ箱に入れていたのが穴だった。**形が違う**=
#     口座/上限 : rc=1 / is_error:true / api_error_status=429 / result にエラー文が載る
#     この箱   : rc=0 / is_error:false / stop_reason:end_turn / **課金は発生している**
#   実測(local/llm/request_log.jsonl)= 08-13 に llm-qa 10回・future-room 1回。llm-qa の
#   10回だけで total_cost_usd 合計 $9.19 を払って本文ゼロ。しかも同じセッションへ resume
#   する限り**毎回ここに落ちる**(10/10)ので、再配達は金を燃やすだけで絶対に抜けない。
#   → 6回で dead(2便が実際に死んだ: DISPATCH-llm-qa-1786558097396 / -1786602372875)。
EMPTY_REPLY_NUDGE = (
    "=== システム: 直前の便への返信が空だった(部屋には何も出ていない) ===\n"
    "★これはChamiの発言ではない。機械の催促だ。この文への感想は要らない。\n"
    "直前に渡した便に対する**返信本文だけ**を、今すぐもう一度出せ。\n"
    "★『No response requested.』のような機械の返事にするな= あの便はDiscordの部屋へ"
    "配るための実際の便だ(空のまま返すと、依頼した相手には沈黙として届く)。\n"
    "★返す物が無いと判断したなら、その理由を1行で書け。**沈黙が最悪の事故**だ。\n"
    "=== ここまで ===")


def looks_like_empty_reply(rc, data, out):
    """rc=0 で正常に終わったのに**返信本文が無い**便か(=第3の箱)。

    ★口座・上限・認証・セッション不明は**ここに含めない**(それぞれ従来の枝が正しい)。
      含めてしまうと、口座が空の時に世代交代して健全な旧セッションを捨てる
      =2026-07-25 に実弾で踏んだ穴を踏み直すことになる。
    """
    if rc != 0:
        return False                     # 口座・上限・認証は rc=1 で来る(実測)
    if _reply_of(data):
        return False                     # 本文がある=正常
    t = out or ""
    if _looks_like_auth_failure(t) or _looks_like_session_missing(t):
        return False                     # 先に見るべき枝がある
    return True


def _run_claude(prompt, token, session_id=None, model=RELAY_MODEL, timeout=RELAY_TIMEOUT,
                hard_timeout=None, on_soft=None):
    """`claude -p` を**1回だけ**起動する。戻り値 (data, rc, combined_output, waited_sec)。

    ★引数の並びに意味がある: 可変長フラグ(--allowedTools / --add-dir)の直後に
      promptを置くとdirとして飲み込まれて即死する(2026-07-18の実障害)。
      **固定長の --model を最後に置き、その後ろにpromptを置く**=実測で通っている形
      (dept_daemon.generate() も positional prompt で運用中)。
    ★-p(=--print)以外の起動経路は作らない。対話ウィンドウを開かせない。

    ★★2026-07-27 `subprocess.run(timeout=)` の一発勝負をやめ、**Popen+段階的な待ち**にした。
      hard_timeout(既定 None)= 指定が無ければ**旧版と完全に同じ挙動**
        (timeout秒で kill して TimeoutExpired を投げる)。引き継ぎ生成・自己確認・手動交代は
        この既定のまま=1文字も挙動が変わらない。
      hard_timeout > timeout を渡した時だけ2段構えになる:
        1) timeout(soft)で返らなくても**殺さない**。on_soft(経過秒)を**1回だけ**呼び、
           そのまま hard まで待ち続ける。
        2) hard で初めて kill し、subprocess.TimeoutExpired を投げる。
      ★on_soft が例外を投げても**待ちは続ける**(通知の失敗で便を落とさない)。
      ★communicate() は TimeoutExpired の後に**もう一度呼べる**(出力は失われない)=公式仕様。
        だから soft で捨てずに続きを待てる。
    """
    # ★2026-08-13 ここに研究室HQが止血(prompt_spill=長すぎるpromptをファイルへ逃がす)を
    #   一時的に入れていたが、**外した**。理由= 直後に一ノ瀬怜(platform-se)が下の stdin 化
    #   (恒久対策・commit 3f5ac58)を入れたため、長さの上限そのものが消えた。
    #   止血を残すと28,000字超の便を無用にファイルへ逃がし、セッションに余分なReadを1回強いる
    #   =恒久対策の劣化になる。**同じ穴を2つの機構で塞がない**(ORG-11と同じ話)。
    #   ★prompt_spill.py 自体は残す= dept_daemon.generate() と persona_render.py が
    #     まだ positional argv で prompt を渡しており、そちらの止血として現役だ。
    argv = [CLAUDE, "-p"]
    if session_id:
        argv += ["--resume", session_id]
    argv += ["--output-format", "json",
             "--allowedTools", *_allowed_tools(),
             "--add-dir", HQ,
             "--model", model]
    # ★★2026-08-13 promptは**stdinで渡す**(argvの末尾に置かない)。一ノ瀬怜(platform-se)。
    #   実障害= DISPATCH-system-engineer-1786575652694(絵文字監視の毎朝8時digest=炎上/再発
    #   スタンプ各11件)が 08:08〜08:29 に6回とも配送失敗し dead 隔離。request_log.jsonl の実体は
    #   「FileNotFoundError: [WinError 206] ファイル名または拡張子が長すぎます。」。
    #   受け口パスの欠落ではない= Windows の CreateProcess はコマンドライン全体が 32,767 文字を
    #   超えると WinError 206 を投げ、Python はそれを FileNotFoundError として出す。封筒(共通規律
    #   全文 約28KB + digest本文)が長い便でだけ argv長がこの上限を超えていた=長い便ほど死ぬ穴。
    #   → prompt を positional argv から外し stdin へ。stdin にはこの上限が無い(実測: 短文prompt
    #     を stdin で渡し is_error:false の JSON を確認済 2026-08-13)。claude -p は positional prompt
    #     が無ければ stdin を prompt として読む(--input-format 既定=text)。挙動は同一。
    _stdin_input = prompt
    # ★2026-07-26 親の環境を継がない(実弾で特定した穴)。
    #   デーモンはHQセッションから再起動したkeeperの子になることがあり、その場合
    #   ハーネスの環境変数(ANTHROPIC_BASE_URL / CLAUDE_CODE_* 等)を相続する。
    #   CLIがそれを拾うと別の口座経路に化け、「Credit balance is too low」で全滅した
    #   (同時刻に素のenv+同一トークンでは rc=0 を実測)。
    #   → 必要最小限だけを白名単で組む。誰がデーモンを産んでも挙動が変わらない。
    _KEEP = ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "USERPROFILE",
             "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "USERNAME", "HOMEDRIVE",
             "HOMEPATH", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PYTHONIOENCODING",
             "GO5_LOCAL_DIR")
    env = {k: v for k, v in os.environ.items() if k.upper() in _KEEP}
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token or ""
    soft = float(timeout or 0) or None
    hard = float(hard_timeout) if hard_timeout else None
    if hard is not None and soft is not None and hard <= soft:
        hard = None                      # 2段になっていない指定は旧版と同じ1段として扱う
    t0 = time.time()
    p = subprocess.Popen(argv, cwd=ROOT, env=env,
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace")
    try:
        try:
            # ★input は最初の communicate() でのみ渡す。TimeoutExpired 後の再communicate()には
            #   渡さない(stdin は最初の呼びで書き切っている=公式仕様。二重に渡すと壊れる)。
            stdout, stderr = p.communicate(input=_stdin_input, timeout=soft)
        except subprocess.TimeoutExpired:
            if hard is None:
                # 旧版と同じ= softで打ち切る。**必ず殺してから**投げる(孤児プロセスを残さない)。
                p.kill()
                p.communicate()
                raise
            # --- soft超過。★殺さずに待ち続ける(ここが今回の本体) ---
            if on_soft is not None:
                try:
                    on_soft(time.time() - t0)
                except Exception:
                    pass                 # ★通知の失敗で本体の待ちを落とさない
            try:
                stdout, stderr = p.communicate(timeout=max(hard - (time.time() - t0), 1.0))
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()          # 出力を回収してからパイプを閉じる
                raise
    except BaseException:
        # ★Ctrl-C・親の異常終了などでも**子を残さない**(fail-safe。窓が増える事故を作らない)。
        if p.poll() is None:
            try:
                p.kill()
                p.communicate()
            except Exception:
                pass
        raise
    waited = time.time() - t0
    out = (stdout or "") + (stderr or "")
    data = None
    try:
        data = json.loads((stdout or "").strip())
    except Exception:
        data = None
    return data, p.returncode, out, waited


def _reply_of(data):
    """--output-format json の応答から返信本文を取り出す。取れなければ空文字。"""
    if not isinstance(data, dict) or data.get("is_error"):
        return ""
    return str(data.get("result") or "").strip()


# --- 使用量(★推測ではなく実測) ---
def _sum_tokens(v):
    """usageの1項目を数に直す。dict(内訳)で来ることがあるので中身を合計する。

    ★CLIの応答形は将来変わりうる。**読めない形が来たら0**にして落とさない
      (使用量が取れないだけで配送を巻き添えにしない=fail-safe)。
    """
    if isinstance(v, dict):
        t = 0
        for x in v.values():
            t += _sum_tokens(x)
        return t
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


# --- ★★計器(2026-07-29 改善書_セッション移行の負荷とトークン §4 第1手) ---
#
# なぜ入れたか(改善書§1-6 の実測):
#   旧計器(_context_tokens_of = usage合計 ÷ num_turns)は同じセッションで
#     126,073 → 75,991 → 49,212 → 93,429 → … → 160,463
#   と**上下に暴れる**。文脈は減らないのだから、この数字は真値ではない。
#   真値は会話の記録ファイル(トランスクリプト)の**最後のassistant行のusage**に書いてある。
#   実測(2026-07-29 02:35 本番の21部屋・旧計器 vs トランスクリプト):
#     research-room  94,805 → 181,162 (▲86,357 の過小評価)
#     platform-se    35,300 → 120,415 (▲85,115)
#     llm-edu        71,431 → 111,229 (▲39,798)
#     consult-intel 109,716 →  73,398 (△36,318 = **圧縮済みなのに重いと思い込んでいた**)
#   ★consult-intel の行が改善書§1-5 の事故そのもの= 圧縮で軽くなったセッションを
#     旧計器が「まだ重い」と読み、交代の対象にしていた。
#
# ★★旧計器は消さない(改善書§4 第1手の「注意」)。記録ファイルの形式はCLIの内部仕様なので、
#   読めなくなった日は旧計器へ倒す(fail-open)。**沈黙を作らないことが最優先。**
TRANSCRIPT_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")


def _transcript_dir(cwd=None):
    """そのcwdで作られたセッションの記録が置かれる場所。

    Claude Code はプロジェクトのパスの英数字以外を "-" に潰した名前でフォルダを作る
    (実測: D:\\SougouStartFolder\\5SecMovieMaker → D--SougouStartFolder-5SecMovieMaker)。
    ★cwd を引数にしてあるのは、改善書 第5手(部屋別cwd・**次段**)を入れた時に
      ここを部屋ごとに引けるようにするため。今は既定(ROOT)しか使わない。
    """
    return os.path.join(TRANSCRIPT_ROOT,
                        re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd or ROOT)))


def _transcript_path(sid, cwd=None):
    return os.path.join(_transcript_dir(cwd), f"{sid}.jsonl")


def read_transcript(sid, cwd=None):
    """会話の記録ファイルから **真の文脈量と圧縮の履歴** を読む。読めなければ None。

    戻り値 dict:
      context_tokens : 最後の(サブエージェントでない)assistant行の
                       input + cache_read + cache_creation。= 今抱えている量の実値。
      compact_count  : `"subtype":"compact_boundary"` 行の件数。
      last_compact   : 最後の圧縮 (ts, trigger, preTokens, postTokens) or None。

    ★output_tokens は入れない(窓を食うのは入力側だけ)= 旧計器と同じ考え方。
    ★isSidechain(サブエージェント)の行は数えない。あれは**別の文脈**なので、
      混ぜると親セッションの重さを取り違える。
    ★None を返すのは「読めなかった」であって「0だった」ではない。呼び元はここを区別すること
      (0と混ぜると、記録が読めない日に全部屋が『文脈ゼロ』に見えてしまう)。
    """
    if not sid:
        return None
    p = _transcript_path(sid, cwd)
    try:
        if not os.path.exists(p):
            return None
        last, n_compact, last_compact = 0, 0, None
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                # ★安い前濾し。1行ずつJSONに起こすと3MBの記録で無駄に重くなる。
                if '"usage"' not in line and "compact_boundary" not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:               # noqa: BLE001 壊れた行は飛ばす(落とさない)
                    continue
                if d.get("subtype") == "compact_boundary":
                    n_compact += 1
                    m = d.get("compactMetadata") or {}
                    last_compact = (str(d.get("timestamp") or ""), str(m.get("trigger") or ""),
                                    int(m.get("preTokens") or 0), int(m.get("postTokens") or 0))
                    # ★★2026-07-29 **ここで last を postTokens へリセットする(今回の真因①の本体)。**
                    #   直す前は、圧縮の区切りを跨いでも last を持ち越していたので、
                    #   「圧縮の直後にこの関数を呼ぶと**圧縮前の重い値**が返る」状態だった。
                    #   実測(local/llm/request_log.jsonl・~/.claude/projects の記録・2026-07-29):
                    #     21:45:56.353Z assistant usage合計 = 196,352      ← 圧縮前の最後の行
                    #     21:47:54.902Z compact_boundary manual 196,358→5,407
                    #     21:47:57.521Z 以降に圧縮後の assistant 行が付く(0 → 55,671)
                    #   run_compact() は `/compact` が返った**直後**(21:47:55)に読むので、
                    #   圧縮後の行がまだ1行も無く、last は 196,352 のまま返っていた。
                    #   → 台帳へ 196,352 が入り、同じ秒に
                    #     「圧縮が効いた 196,358→5,407」と「文脈196,352が185,000を超えた=交代」
                    #     が並んだ(= Chamiが見つけた矛盾。**圧縮した直後の一番軽いセッションを捨てていた**)。
                    #   ★postTokens は「畳んだ後にモデルが抱えている量」そのものなので、
                    #     圧縮後の行が出るまでの間はこれが唯一の正しい答えになる。
                    last = int(m.get("postTokens") or 0)
                    continue
                if d.get("type") != "assistant" or d.get("isSidechain"):
                    continue
                u = ((d.get("message") or {}).get("usage")) or {}
                if not isinstance(u, dict) or not u:
                    continue
                t = (_sum_tokens(u.get("input_tokens"))
                     + _sum_tokens(u.get("cache_read_input_tokens"))
                     + _sum_tokens(u.get("cache_creation_input_tokens")))
                if t:
                    last = t
        return {"context_tokens": last, "compact_count": n_compact,
                "last_compact": last_compact, "path": p}
    except Exception:                            # noqa: BLE001 ★記録が読めなくても配送は続ける
        return None


def _context_tokens_of(data):
    """そのセッションが今**抱えている文脈の大きさ**(実測の近似)。取れなければ0。

    ★★2026-07-29 これは**フォールバック**になった(改善書 第1手)。
      普段は read_transcript() の実値を使う。この関数は記録ファイルが読めない時だけ働く。
      **消さないこと**(消すと、CLIが記録の形式を変えた日に文脈が測れなくなり、
      閾値の判定が全部止まる=交代も圧縮も走らないまま窓に突っ込む)。

    ★`--output-format json` の usage に入っている3つを足す:
        input_tokens                … 今回そのまま送った分
        cache_creation_input_tokens … 今回キャッシュへ書いた分
        cache_read_input_tokens     … キャッシュから読ませた分
      **出力(output_tokens)は入れない**。窓を食い潰すのは入力側だから。

    ★★2026-07-26 **num_turns で割る**(HQが実測で見つけた誤り。直す前は4倍に膨れていた):
      usage の値は**そのターン全体の合計**であって、1回分の文脈の大きさではない。
      Claude Codeは1つの便を処理する間に**道具を使うたび内部でターンを重ねる**ので、
      **同じ文脈を num_turns 回くり返し読む**。結果 cache_read が n倍に積算される。
      実測= hq が `119,898 / num_turns=4` → 実際の文脈は**約30,000**。
             別の世代では1便で **380,695**(窓20万を超える=あり得ない値)まで出た。
      → **合計 ÷ num_turns** が「1ターンあたりの文脈」≒ セッションが抱えている量の近似。
      ★これを直さないと**実際の1/4で交代が走る**。福岡不在の1週間、hq/research-roomは opus
        なので「1便ごとに引き継ぎ+新規+自己確認=opus 3回」を延々と繰り返すところだった。
      ★近似であって厳密ではない(ターン中に文脈は増えるので、やや過小に出る)。
        **過小=交代が遅れる方向**なので、閾値の8万トークンの余白がその分を受け持つ。
    """
    u = (data or {}).get("usage") if isinstance(data, dict) else None
    if not isinstance(u, dict):
        return 0
    total = (_sum_tokens(u.get("input_tokens"))
             + _sum_tokens(u.get("cache_creation_input_tokens"))
             + _sum_tokens(u.get("cache_read_input_tokens")))
    try:
        turns = int((data or {}).get("num_turns") or 1)
    except Exception:
        turns = 1
    return int(total / max(turns, 1))


def _note_usage(entry, data, now, sid=None):
    """対応表の1部屋分へ使用量を記録する(★保存は呼び元の save_room=既存の原子的更新)。

    ★★2026-07-29 (改善書 第1手): **文脈の値はトランスクリプトの実値を優先**する。
      読めなければ旧計器(usage÷num_turns)へ倒す=**沈黙も停止も作らない**。
      どちらで測ったかは `context_source` に残す(後から「その数字は何か」を追えるように)。
    ★併せて `compact_count` を持つ。**前回より増えていたら圧縮が起きた**ということ
      (改善書§1-5 の「圧縮済みセッションを重いと思い込んで捨てた」事故の根絶)。
      増えていたら `resend_boot` を立て、次の便で起動文+規律の全文を1回だけ配り直す
      (改善書 第2手(b)= 圧縮運用の品質保険の本体)。
    """
    est = _context_tokens_of(data)               # ★旧計器(フォールバック用に必ず測っておく)
    tr = read_transcript(sid) if sid else None
    ctx = 0
    if tr and tr.get("context_tokens"):
        ctx = int(tr["context_tokens"])
        entry["context_source"] = "transcript"
        entry["context_tokens_est"] = est        # ★並べて残す(計器の狂いを後から追えるように)
    elif est:
        ctx = est
        entry["context_source"] = "usage_est"    # ★記録が読めなかった日はこちら
    if tr is not None:
        prev_cc = int(entry.get("compact_count") or 0)
        cc = int(tr.get("compact_count") or 0)
        entry["compact_count"] = cc
        if cc > prev_cc:
            # ★圧縮の要約は機械製で、規律・人格・部屋の約束が薄まっている可能性がある。
            #   次の便で**全文を1回だけ**配り直す(第2手(b))。
            entry["resend_boot"] = True
            entry["last_compact_at"] = now
            lc = tr.get("last_compact") or ()
            if len(lc) == 4:
                entry["last_compact_info"] = f"{lc[0]} {lc[1]} {lc[2]}→{lc[3]}"
    if ctx:
        entry["context_tokens"] = ctx
        entry["last_usage_at"] = now
    # ★turnsは自前で+1する。CLIの num_turns は**そのセッションの内部ステップ数**であって
    #   「Chamiと何往復したか」ではない(道具を使うと1便で何回も増える)。参考値として別名で残す。
    try:
        entry["turns"] = int(entry.get("turns") or 0) + 1
    except (TypeError, ValueError):
        entry["turns"] = 1
    try:
        n = (data or {}).get("num_turns")
        if n is not None:
            entry["last_num_turns"] = int(n)
    except (TypeError, ValueError):
        pass
    return ctx


def _should_rotate(entry):
    """次の便を処理する**前**に交代すべきか(★事前判定)。戻り値 (bool, 理由の文字列, 種別)。

    ★見るのは「前の便で実際にモデルへ渡った文脈の大きさ」。**推測しない。**
    ★ここでTrueになっても、Chamiの便は**新セッションで普通に処理される**。
      「今は対応できません」と断る必要は無い(断るのは交代自体が失敗した時だけ)。

    ★★2026-07-29 (改善書 第2手(c)): **交代は例外になった。** 既定の対処は圧縮。
      ここでTrueになるのは次の3つだけ:
        ① 圧縮を撃ったのに効かなかった(compact_failed)= 沈黙を作らないための退避
        ② 文脈が ROTATE_AT_TOKENS(185,000)を超えている= 自動圧縮も手動圧縮も効いていない
        ③ 圧縮が COMPACT_REFRESH_ROTATIONS 回積み重なった= 要約の劣化に備えた定期リフレッシュ
           ★★2026-07-29(3回目)③には**文脈の条件**が付いた
             (かつ ctx >= REFRESH_MIN_CONTEXT_TOKENS)。回数だけで軽いセッションを
             捨てていた実測2件への対処。定数のコメントに実測値と根拠を残してある。
      ★①が**沈黙を作らない**の本体。圧縮が失敗したまま放置すると窓超えで便が失敗し続ける
        (改善書§5「本当のリスク」の(2))。
    ★戻り値の形を (bool, 理由) に変えた。理由を台帳に残すため
      (「なぜ交代したのか」が後から分からないと、圧縮が効いているかを判定できない)。

    ★★2026-07-29(2回目)**第3の戻り値「種別」を足した。**
      種別= "compact_failed" / "over_line" / "refresh" / ""。
      なぜ要るか= 呼び元(relay)が「**これは圧縮でまだ救えるか**」を知る必要があるから。
        "over_line"(185,000超)だけは、**まだ一度も圧縮が効いていない**という意味なので、
        交代する前に圧縮を1回撃てば救える可能性がある。
        "compact_failed" は撃って駄目だった後、"refresh" は圧縮では解決しない。
      ★理由の**文字列で分岐しない**こと。文言を1文字直しただけで判定が壊れる。
    """
    try:
        ctx = int(entry.get("context_tokens") or 0)
    except (TypeError, ValueError):
        ctx = 0
    if entry.get("compact_failed"):
        return True, f"圧縮が効かなかった(tokens={ctx:,})=交代へ倒す", "compact_failed"
    if ctx >= ROTATE_AT_TOKENS:
        return (True,
                f"文脈{ctx:,}が保険の線{ROTATE_AT_TOKENS:,}を超えた(圧縮が効いていない)",
                "over_line")
    try:
        cc = int(entry.get("compact_count") or 0)
        done = int(entry.get("refresh_rotated_at_compacts") or 0)
    except (TypeError, ValueError):
        cc, done = 0, 0
    if cc - done >= COMPACT_REFRESH_ROTATIONS:
        # ★★2026-07-29(3回目)**回数だけでは交代しない。文脈も見る。**
        #   なぜ足したか= 回数が増えるのは「圧縮が効いた瞬間」で、その瞬間の文脈は
        #   そのセッションで**一番軽い**(実測 3,816〜7,010)。回数条件だけだと
        #   **必ず一番軽い瞬間に発火する**構造だった(定数 REFRESH_MIN_CONTEXT_TOKENS の
        #   コメントに実測2件を残してある)。
        #   ★見送りであって取り消しではない= cc は減らないので、次に文脈が
        #     REFRESH_MIN_CONTEXT_TOKENS を超えた便でそのまま交代する。趣旨は生きている。
        if ctx >= REFRESH_MIN_CONTEXT_TOKENS:
            return (True,
                    f"圧縮が{cc}回積み重なった かつ 文脈{ctx:,}が"
                    f"{REFRESH_MIN_CONTEXT_TOKENS:,}以上=定期リフレッシュ"
                    f"(K={COMPACT_REFRESH_ROTATIONS})",
                    "refresh")
    return False, "", ""


def _refresh_deferred(entry):
    """定期リフレッシュを「回数は満たしているが文脈が軽い」で**見送っている**状態か。

    戻り値 (bool, 説明)。★これは判定ではなく**記録のため**の関数。
      見送りを1行も残さないと「なぜ交代しないのか」が誰にも見えず、
      今度は逆向きの沈黙(=直したことが確認できない)を作ってしまう。
    """
    try:
        ctx = int(entry.get("context_tokens") or 0)
        cc = int(entry.get("compact_count") or 0)
        done = int(entry.get("refresh_rotated_at_compacts") or 0)
    except (TypeError, ValueError):
        return False, ""
    if entry.get("compact_failed") or ctx >= ROTATE_AT_TOKENS:
        return False, ""                     # ★別の理由で交代する場面。ここの話ではない
    if cc - done >= COMPACT_REFRESH_ROTATIONS and ctx < REFRESH_MIN_CONTEXT_TOKENS:
        return True, (f"定期リフレッシュの回数条件は満たしている(圧縮{cc}回)が、"
                      f"文脈{ctx:,}が{REFRESH_MIN_CONTEXT_TOKENS:,}未満なので**見送る**"
                      f"(捨てるほどの中身が無い。重くなった便で交代する)")
    return False, ""


def is_from_chami(rec):
    """この便がChami本人か。★判定はここ1箇所(dept_daemon._is_from_chami と同じ式)。

    ★同じ判定を2つ持たない(ORG-11)。dept_daemon 側は session_relay を import しているので、
      こちらから import すると循環する= **式をここに置き、あちらが将来こちらを借りる**形にする。
    """
    try:
        return "chami" in str((rec or {}).get("author") or "").lower()
    except Exception:                            # noqa: BLE001 判定不能は「Chamiではない」へ倒す
        return False


def _refresh_hold(entry, rec, now):
    """定期リフレッシュを**この便では見送る**か(2026-08-13 イージス研究室)。戻り値 (bool, 理由)。

    発注= 研究室HQ DISPATCH 1537458828541698139 論点2(Chami「急に文脈読まなくなった」)。
    ★見るのは時計ではなく**その部屋の会話の状態**だ。理由と実測は REFRESH_QUIET_SEC の注記。

    見送る条件= 直前 REFRESH_QUIET_SEC 以内に**同じ部屋へChamiの便が来ていた**こと。
      ★「今この便がChamiか」ではなく「**その前に**Chamiが喋っていたか」を見る。
        - 3時間黙っていた部屋へChamiが新しい話題を出した便 → 見送らない(ここが一番安全な交代点)
        - 2分前の続きの便 → 見送る(ここで世代を替えると話の筋が落ちる=今回の事故)
        - 会話中に届いた機構便・他部門からの回送 → 見送る(替えればChamiの次の便が新世代に当たる)
    ★永久に見送らない保険が2つ= ①Chamiが15分黙れば次の便で普通に発火する
      ②見送りが REFRESH_HOLD_MAX_SEC 続いたら会話中でも交代する(2026-07-29の
        「条件を足したつもりで廃止した」事故を二度とやらないため)。
    ★何が壊れても False(=従来どおり交代)へ倒す。ここで例外を出して便を落とさない。
    """
    try:
        prev = float(entry.get("last_chami_at") or 0)
    except (TypeError, ValueError):
        prev = 0.0
    if prev <= 0 or (now - prev) > REFRESH_QUIET_SEC:
        return False, ""                         # 会話の途中ではない=一番安全な交代点
    try:
        since = float(entry.get("refresh_hold_since") or 0)
    except (TypeError, ValueError):
        since = 0.0
    if since > 0 and (now - since) >= REFRESH_HOLD_MAX_SEC:
        return False, (f"見送りが{(now - since) / 3600:.1f}時間続いた"
                       f"(上限{REFRESH_HOLD_MAX_SEC // 3600}時間)=会話中でも交代する")
    n = int(entry.get("refresh_hold_n") or 0) + 1
    return True, (f"直前{int(now - prev)}秒前に同じ部屋へChamiの便が来ている"
                  f"(会話の途中={REFRESH_QUIET_SEC}秒以内)。定期リフレッシュは選択的な交代なので"
                  f"見送る。{n}便目の見送り"
                  f"(Chamiが{REFRESH_QUIET_SEC // 60}分黙れば次の便で交代する / "
                  f"上限{REFRESH_HOLD_MAX_SEC // 3600}時間で必ず交代する)")


def _measure_context_now(sid):
    """**今この瞬間**のセッションの文脈量を記録ファイルから測り直す。

    戻り値 (ctx, measured)。measured=False は「測れなかった」= 呼び元は台帳の値のまま進む
    (★fail-open。測れない日に圧縮も交代も止まると、そちらの方が高くつく)。

    ★★2026-07-29(3回目)**なぜこれが要るか(今回の真因②の本体)。**
      台帳の `context_tokens` は **前の便が終わった時点の測定値**でしかない。
      ところが Claude CLI は**こちらの便と便の間に自分で自動圧縮する**(約167,000で走るのは
      実測済み)。すると台帳は重いまま、実物は軽い、という食い違いが生まれる。

      ★実測(local/llm/request_log.jsonl・system-engineer・2026-07-29):
          17:03:09 後始末を予約(ctx=155,727)→ 常駐の載せ替えで予約ごと消えた
          17:06:47 次の便の入口が回収に入る。台帳の文脈= **155,727**
          17:08:21 圧縮の実測は **7,618→3,816**
        = 台帳が155,727と言っている横で、実物は7,618しか無かった。
          回収の経路は COMPACT_AT_TOKENS(150,000)を**ちゃんと見ていた**。
          見ていた**数字の方が古かった**。★ここが真因で、閾値の書き忘れではない。
      圧縮は実測102〜140秒かかる。軽い物に撃つのは時間と金の丸損なので、
      **撃つ直前に測り直す**。ついでに交代の判定も正しい数字の上で行われるようになる。
    """
    if not sid:
        return 0, False
    try:
        tr = read_transcript(sid)
    except Exception:                            # noqa: BLE001 ★測定の失敗で便を落とさない
        return 0, False
    if not tr:
        return 0, False
    try:
        ctx = int(tr.get("context_tokens") or 0)
    except (TypeError, ValueError):
        return 0, False
    # ★0は「読めたが数えられなかった」= 信じない(0を信じると全部屋が『文脈ゼロ』に見える)。
    return (ctx, True) if ctx else (0, False)


# ================================================================================
# ★★未確認の不具合台帳(2026-07-29 新設)= **世代をまたぐ器**
#
# なぜ作ったか(改善提案部門の実測。正本=
#   00_AI-HQ/departments/kaizen/pdca/2026-07-29_saihatsu-2.md §構造指摘C):
#   > 1つのセッションがバグを『壊れた実物を見る→同じ場面で直ったを見る』(§4.55)まで
#   > 見届ける前に交代し、次のセッションは『commitに封じたと書いてある』(台帳)を継ぐが
#   > 『Chamiの画面で消える』(現物)を継がない。だから毎回『封じた/再発を封じる』を再宣言する。
#   > 塊Bは1時間で修正5本・各再発はfixの4〜19分後。
#   = **セッションchurn × 台帳≠実物**。これが再発の共通機構だと数字で特定された。
#
# ★何が無かったのか= 「**まだ直ったと確認できていない不具合**」を世代をまたいで運ぶ器。
#   引き継ぎ(handoff_*.md)は**セッションが書く作文**なので、書き忘れれば消える。
#   commitログは「入れた」しか語らない。だから機械が持つ台帳を1本新設する。
#
# 形(★追記のみ。1行=1つの出来事。**状態は畳んで出す**):
#   {"op":"open",   "id","ts","dept","symptom","broken","noticed_at","source"}
#   {"op":"confirm","id","ts","dept","fixed","scene","by"}
# ★状態は2つだけ= 未確認 / 確認済。
#   ★★「直した(未確認)」という状態は**作らない**。作った瞬間、それが「直った」に化ける
#     (塊Bで5回起きたのがまさにこれ= 5回『封じた』と言い、5回とも実物で消えた)。
# ★confirm は **同じ場面で直った実物の在りか**が機械で解決できない限り採らない(下の evidence_locator)。
#   採らなかった confirm は捨てずに残し、**その不具合は未確認のまま**にする。
DEFECTS_FILE = os.path.join(LOCAL, "llm", "open_defects.jsonl")

DEFECT_OPEN = "未確認"
DEFECT_CONFIRMED = "確認済"
DEFECT_OPS = ("open", "confirm")

# ★★2026-07-29 追加: `kind`(この台帳を「生きている台帳」へ広げる)。
#   正本= 改善書_記憶と引き継ぎの抜本見直し_2026-07-29.md §6 第1手 / §7-4。
#   §7-4 の指摘そのもの=
#     「**『生きている台帳』を不具合に限定した。** 実測では、言い直しを生んでいるのは
#       不具合(再発5件)より**未完了の依頼**(ランキング・48時間記録・投稿予定時刻)の方が
#       息が長い。**器の半分だけ作った形だ。**」
#   → 器は増やさない(ファイルは1本のまま)。1項目 `kind` を足すだけ。
#     defect  = まだ直ったと確認できていない不具合(従来のもの。挙動は1ミリも変えない)
#     request = Chamiが頼んだのに、その便の中で終わらなかった依頼
#   ★古い行に `kind` は無い。**無い行は defect として読む**(=既存6行の扱いが変わらない)。
DEFECT_KIND_DEFECT = "defect"
DEFECT_KIND_REQUEST = "request"
DEFECT_KINDS = (DEFECT_KIND_DEFECT, DEFECT_KIND_REQUEST)
# id の頭。**種別で分ける**= 台帳を目で見た時に混ざらない・照合(検査10)も壊れない。
DEFECT_ID_PREFIX = {DEFECT_KIND_DEFECT: "DEF", DEFECT_KIND_REQUEST: "REQ"}

# 引き継ぎ/起動文へ差し込む時の上限(封筒が太りすぎないように)。★超えた分は件数だけ出す。
DEFECT_BLOCK_MAX = 12
DEFECT_SYMPTOM_MAX = 140

# Discordのメッセージ/チャンネルID(スノーフレーク)。17〜20桁
_DEF_SNOWFLAKE_RE = re.compile(r"(?<!\d)\d{17,20}(?!\d)")
_DEF_URL_RE = re.compile(r"https?://\S{5,}")
# ★「commit の hash だけ」は**実物として採らない**。これが今回の真因そのもの=
#   「commitに封じたと書いてある」(台帳)は「Chamiの画面で直っている」(現物)の証拠にならない。
_DEF_BAREHASH_RE = re.compile(r"^(?:commit\s*)?[0-9a-f]{7,40}$", re.I)
_DEF_LINESUFFIX_RE = re.compile(r":\d+(?::\d+)?$")


def _defect_path_hit(text):
    """本文の中に**実在するファイルのパス**があるか。あれば最初の1つを返す。

    ★`app.js:123` のような行番号付きも受ける(尻の `:行` を落としてから実在を見る)。
    ★相対パスは 5SecMovieMaker(ROOT)と D:\\SougouStartFolder(その親)の両方から解決を試す。
    """
    for tok in re.split(r"[\s、,]+", str(text or "")):
        tok = tok.strip().strip("()（）「」『』\"'`。,")
        if len(tok) < 4:
            continue
        cand = _DEF_LINESUFFIX_RE.sub("", tok)
        for base in ("", ROOT, os.path.normpath(os.path.join(ROOT, ".."))):
            p = cand if not base else os.path.join(base, cand)
            try:
                if os.path.exists(p):
                    return tok
            except (OSError, ValueError):
                continue
    return None


def evidence_locator(text):
    """「実物の在りか」として機械で解決できるか。戻り値 (ok, 種別, 理由)。

    ★★ここが「確認済にできる条件」の**機械の縛り**そのものだ。通るのは次のどれか:
      ① Discordのメッセージ在りか … msg_id(17〜20桁)か discord.com のリンク
      ② 実在するファイルのパス     … `path` / `path:行`(**その場で存在を確かめる**)
      ③ http(s) のリンク
    ★通さないもの(意図的):
      - 空・短すぎる                 = 在りかになっていない
      - **commitのhashだけ**         = 「入れた」の記録であって「直った実物」ではない(§4.55)
      - 上のどれにも当たらない自然文 = 「直しました」は在りかではない

    ★正直に書いておく(嘘の機構を作らない):
      ここが縛れるのは「**在りかの形をしているか**」までだ。
      その在りかが本当に『同じ場面で直っている物』を指しているかは、機械には見えない。
      = **完全には縛れない**。だから縛りは3枚重ねにしてある(下の fold_defects と検査10)。
    """
    t = str(text or "").strip()
    if len(t) < 8:
        return False, "", "在りかが空か短すぎる(8字未満)"
    if _DEF_BAREHASH_RE.match(t):
        return False, "", ("commitのhashだけでは採らない。"
                           "★『commitに封じたと書いてある』(台帳)は『直った実物』ではない")
    if "discord.com/channels/" in t:
        return True, "discord", "Discordのリンク"
    m = _DEF_SNOWFLAKE_RE.search(t)
    if m:
        return True, "discord", f"msg_id={m.group(0)}"
    hit = _defect_path_hit(t)
    if hit:
        return True, "file", f"実在するパス {hit}"
    if _DEF_URL_RE.search(t):
        return True, "url", "リンク"
    return False, "", ("在りかとして解決できない"
                       "(Discordのmsg_id/リンク・実在するファイルのパス・URL のどれかを書くこと)")


def defect_id(dept, broken, symptom="", kind=DEFECT_KIND_DEFECT):
    """同じものを二度積まないための鍵。**実物の在りか**から作る(言い回しでは作らない)。

    ★kind を既定(defect)で呼ぶ限り、**2026-07-29以前と1文字も同じidになる**
      (seed に kind を混ぜていない=既存6行の冪等が壊れない)。頭だけ種別で分ける。
    """
    seed = f"{dept}|{str(broken or '').strip()}|{str(symptom or '').strip()[:40]}"
    head = DEFECT_ID_PREFIX.get(kind, "DEF")
    return "%s-%s-%s" % (head, dept, hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()[:10])


# ★飛ばした行の行番号(直近の読み取り時点)。**捨てた事実をここに残す**。
#   2026-08-12・イージス研究室。発注= 研究室HQ(シャビ・アロンソ) DISPATCH-aegis-gl-1786467265180。
#   実話: `"fixed":"D:\\Sougou..."` の `\` を素で書いた行が2行あり、どちらも op:"confirm" だった。
#   → 読み取りが黙って飛ばす → confirm が消える →
#     **終わった依頼が永久に「まだ終わっていない」として全部屋の起動文に出続ける。**
#   飛ばす設計(fail-open)は正しい。**間違っていたのは「飛ばしたと誰にも言わない」ことだ。**
_DEFECT_BAD_LINES = []
# ★意図して積まれる op(警報の対象外)。note= 訂正/恒久の注記(実測2行)+ 催促の再掲(C-046)。
_DEFECT_OPS_BENIGN = tuple(DEFECT_OPS) + ("note",)

# ★★台帳の実ファイルは**この関数1本を通す**(2026-08-14・C-046)。
#   理由= 検査が「起票されるか」を**実行で**見るには、本番の台帳を汚さずに書き先を差し替えられる
#   必要がある。共通規律§3「ソースの文字列一致は検査ではない」への手当て。
#   手本= absence_watchdog.queue_db_path() / session_relay._run_claude(読む先・叩く先の切り出し)。
#   ★切り出しただけで本番の挙動は1ミリも変えていない(既定は DEFECTS_FILE)。
_DEFECTS_PATH_OVERRIDE = None


def defects_path():
    """台帳(open_defects.jsonl)の実ファイル。★本番では DEFECTS_FILE そのもの。"""
    return _DEFECTS_PATH_OVERRIDE or DEFECTS_FILE


def set_defects_path(path):
    """台帳の書き先/読み先を差し替える(戻り値=差し替える前の値)。★検査からだけ呼ぶ。"""
    global _DEFECTS_PATH_OVERRIDE
    old = _DEFECTS_PATH_OVERRIDE
    _DEFECTS_PATH_OVERRIDE = path or None
    return old


def _defect_read_rows():
    """台帳を1行ずつ読む。★壊れた行は飛ばす(1行壊れても全体を止めない=沈黙を作らない)。

    ★飛ばした行は捨てずに `_DEFECT_BAD_LINES` へ残す(受け手が読む場所へ出すため)。
    """
    global _DEFECT_BAD_LINES
    rows = []
    bad = []
    path = defects_path()
    try:
        if not os.path.exists(path):
            _DEFECT_BAD_LINES = bad
            return rows
        with open(path, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception as e:               # noqa: BLE001
                    bad.append((lineno, str(e)[:80], line[:60]))
                    continue
                # ★note も読み込む(2026-08-14・C-046 の催促の再掲)。
                #   ★読むだけ= 畳む側(fold_defects)が op ごとに明示で分岐する。
                if isinstance(r, dict) and r.get("op") in _DEFECT_OPS_BENIGN and r.get("id"):
                    rows.append(r)
                else:
                    # ★opの綴り違い・id落ちも「黙って落ちる」= 同じ事故。行番号を残す。
                    #   ただし op:"note"(意図して積む注記・実測2行)は**警報にしない**
                    #   = 0件の日に鳴らない警報にしておかないと、誰も読まなくなる。
                    _op = str(r.get("op") or "") if isinstance(r, dict) else ""
                    if not isinstance(r, dict):
                        bad.append((lineno, "JSONだが辞書ではない", line[:60]))
                    elif _op not in _DEFECT_OPS_BENIGN:
                        bad.append((lineno, "opが台帳の語彙にない(op=%r)" % r.get("op"),
                                    line[:60]))
                    elif _op in DEFECT_OPS and not r.get("id"):
                        bad.append((lineno, "idが無い(op=%r)" % r.get("op"), line[:60]))
    except OSError:
        _DEFECT_BAD_LINES = bad
        return rows
    _DEFECT_BAD_LINES = bad
    return rows


def defect_ledger_bad_lines():
    """台帳を読み直して、**読めなかった行**を返す。 [(行番号, 理由, 行頭60字), ...]"""
    _defect_read_rows()
    return list(_DEFECT_BAD_LINES)


def defect_ledger_alarm(limit=5):
    """読めない行があれば**受け手が読む場所へ出す警報**を1本作る。無ければ空文字。

    ★ここが今回の恒久の本体だ= 「飛ばした」を沈黙にしない。0行の時は1文字も足さない。
    """
    try:
        bad = defect_ledger_bad_lines()
    except Exception:                                # noqa: BLE001
        return ""
    if not bad:
        return ""
    head = ("★★**台帳 %s に『機械が読めない行』が %d 行ある。**\n"
            "  読めない行は**黙って飛ばされる**= その行が op:\"confirm\" なら、"
            "**終わった依頼が永久に未完了として出続ける**(上の一覧が嘘になる)。\n"
            "  よくある原因= Windowsパスの `\\` を素で書いた(`\"D:\\Sougou...\"`)。"
            "`\\\\` へ直すか、**手打ちをやめて `python scripts/llm/close_item.py` を使え**。\n"
            % (DEFECTS_FILE, len(bad)))
    rows = ["  - %d行目: %s | %s" % (n, why, head60) for n, why, head60 in bad[:limit]]
    if len(bad) > limit:
        rows.append("  - …ほか %d行" % (len(bad) - limit))
    return head + "\n".join(rows)


def append_defect(rec):
    """台帳へ1行**追記する**(既存行は絶対に書き換えない)。戻り値 True/False。

    ★失敗しても例外を外へ出さない= この台帳のせいで便や交代が止まることは無い(fail-open)。
    """
    try:
        path = defects_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = dict(rec)
        rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception:                                # noqa: BLE001
        return False


def open_defect(dept, symptom, broken, noticed_at="", source="", did=None,
                kind=DEFECT_KIND_DEFECT, close_when=""):
    """「まだ終わっていない生きた項目」を1件積む。戻り値 (id, 新規に積んだか)。

    ★同じ id が既に台帳に在れば**積まない**(冪等)。reaction_watch を二度流しても増えない。
    ★kind 既定は defect= **呼び出し側を1箇所も変えなくても従来と同じ行が出る**。
    ★close_when(2026-08-14・C-046②)= 「何が起きたら閉じるか」を1行。空でも積めるが、
      **依頼(kind=request)を積む側は空を渡さない**(dept_daemon._stack_open_request が門番)。
    """
    kind = kind if kind in DEFECT_KINDS else DEFECT_KIND_DEFECT
    did = did or defect_id(dept, broken, symptom, kind)
    for r in _defect_read_rows():
        if r.get("id") == did and r.get("op") == "open":
            return did, False
    row = {"op": "open", "id": did, "dept": dept, "kind": kind,
           "symptom": str(symptom or "")[:2000],
           "broken": str(broken or "")[:1000],
           "noticed_at": str(noticed_at or ""),
           "source": str(source or "")}
    if str(close_when or "").strip():        # ★空の時は欄そのものを足さない(古い行と同じ形)
        row["close_when"] = str(close_when)[:300]
    ok = append_defect(row)
    return did, ok


def nudge_request(dept, did, msg_id="", text=""):
    """催促(「まだ?」「進捗は?」)を**既存の依頼の再掲**として積む(2026-08-14・C-046③)。

    ★新しいIDは発行しない= 催促で件数が増える台帳は「遅い部門ほど数字が悪化する」。
      原因ではなく結果を測ってしまうので、待ち時間だけを更新する。
    ★op は "note"= 畳んだ時に**状態を変えない**(未確認のまま。閉じるのは C-024 のまま人の手)。
    """
    return append_defect({"op": "note", "id": str(did), "dept": dept, "note_kind": "nudge",
                          "nudge": " ".join(str(text or "").split())[:300],
                          "where": str(msg_id or "")})


def mark_defect_enjo(dept, did, where=""):
    """既に積んである不具合に **🔥(炎上)の重さ**を後から足す(2026-08-14 イージス研究室)。

    なぜ要るか= 同じ投稿にChamiが🔥と再発を**両方**押した時、台帳は msg_id で1件に畳まれるので
      **先に処理された方のスタンプだけが source に残る**。実測(2026-08-14の巡回)= 両方押された
      11件のうち **10件が「再発」として積まれ、🔥が消えていた**。
      🔥は「恒久対策まで行け」(C-038/C-040)= 再発より重い合図なので、消えると重さが下がる。
      巡回の本文は「★3種類は別物だ。混ぜて数えるな」と言っているのに、**台帳の側で混ざっていた**。

    ★op は "note"= **状態を動かさない**(未確認のまま。閉じるのは C-024 のまま人の手)。
    ★冪等= 既に🔥として積まれている / 既に印が在る時は**書かない**(False を返す)。
    """
    did = str(did)
    for r in _defect_read_rows():
        if str(r.get("id")) != did:
            continue
        if r.get("op") == "open" and "炎上" in str(r.get("source") or ""):
            return False                      # 起票時から🔥= 足すものが無い
        if r.get("op") == "note" and str(r.get("note_kind") or "") == "enjo":
            return False                      # 既に印が在る
    return append_defect({"op": "note", "id": did, "dept": dept, "note_kind": "enjo",
                          "where": str(where or "")})


def open_request(dept, ask, where, noticed_at="", source="", close_when=""):
    """「Chamiが頼んだのに、その便の中で終わらなかった依頼」を1件積む。 (id, 新規か)

    ★改善書§5の実話がこれだ:
        07:13 Chami依頼 → 引き継ぎに「未着手」と**正しく**書かれた → 11:29「できてないじゃないか」
      **忘れていない。書いてある。誰も実行に変換していない。**
      引き継ぎ(=作文)に書くだけでは、その未完了は「安全に死蔵」される。
      機械の台帳へ入れて初めて、機械が催促できる(=実行に変換できる)。
    ★引数の意味(kind=defect と同じ欄をそのまま使う。器を増やさないため):
        ask   → symptom 欄 = 依頼の中身(Chamiの原文)
        where → broken  欄 = **その依頼の便の在りか**(msg_id / Discordリンク)
      ★where が空でも積む(在りかが無いと後で閉じられないだけで、積まないと消える)。
    ★閉じ方は**不具合と同じ厳しさ**= confirm_defect() を通す(evidence_locator + scene)。
      「やりました」では閉じられない。ここを緩めたら台帳そのものが嘘になる。
    """
    return open_defect(dept=dept, symptom=ask, broken=where,
                       noticed_at=noticed_at, source=source,
                       kind=DEFECT_KIND_REQUEST, close_when=close_when)


def confirm_defect(dept, did, fixed, scene="", by=""):
    """「同じ場面で直った実物を見た」を1件積む。戻り値 (受理されたか, 理由)。

    ★**ここで弾いても行は残す**(捨てない)。何が足りずに閉じられなかったかを後から読めるように。
    """
    ok, kind, why = evidence_locator(fixed)
    append_defect({"op": "confirm", "id": did, "dept": dept,
                   "fixed": str(fixed or "")[:1000], "scene": str(scene or "")[:1000],
                   "by": str(by or "")})
    if not ok:
        return False, why
    return True, kind


def fold_defects(dept=None):
    """台帳を畳んで**今の状態**を出す。戻り値= [dict, ...](気づいた順)。

    畳み方(★ここが2枚目の縛り):
      confirm は次を**全部**満たした時だけ 確認済 にする。1つでも欠ければ**未確認のまま**。
        (a) 先に open が在ること              … 開いていない物は閉じられない
        (b) fixed が evidence_locator を通る  … 「直しました」は在りかではない
        (c) fixed が broken と**別物**であること … 壊れた方を貼り直しただけ、を弾く
        (d) scene(どの場面で見たか)が空でないこと … 「同じ場面」を名指しさせる
    ★弾いた理由は `rejected` に積んで**見えるようにする**(黙って未確認に留めない)。
    """
    state = {}
    order = []
    for r in _defect_read_rows():
        did = str(r.get("id"))
        if r.get("op") == "open":
            if did not in state:
                order.append(did)
                # ★`kind` が無い古い行は **defect** として読む(既存6行の扱いを変えない)。
                _k = str(r.get("kind") or DEFECT_KIND_DEFECT)
                state[did] = {"id": did, "dept": str(r.get("dept") or ""),
                              "kind": _k if _k in DEFECT_KINDS else DEFECT_KIND_DEFECT,
                              "symptom": str(r.get("symptom") or ""),
                              "broken": str(r.get("broken") or ""),
                              "noticed_at": str(r.get("noticed_at") or r.get("ts") or ""),
                              "source": str(r.get("source") or ""),
                              "opened_at": str(r.get("ts") or ""),
                              "close_when": str(r.get("close_when") or ""),
                              "status": DEFECT_OPEN, "fixed": "", "scene": "",
                              "confirmed_at": "",
                              # ★🔥(炎上)か= 「恒久対策まで行け」の重さ(C-038/C-040)。
                              #   起票時の source から読む。**後から note で上書きできる**(下)。
                              "enjo": ("炎上" in str(r.get("source") or "")),
                              "rejected": [], "nudges": []}
            continue
        if r.get("op") == "note":
            # ★催促の再掲(C-046③)。**状態は動かさない**= 待ち時間の更新だけ。
            #   note_kind が nudge 以外の注記(訂正・恒久の覚書)は従来どおり素通り。
            d = state.get(did)
            _nk = str(r.get("note_kind") or "")
            if d is not None and _nk == "nudge":
                d.setdefault("nudges", []).append(
                    f"{r.get('ts','')} {r.get('where','')} {r.get('nudge','')}".strip())
            elif d is not None and _nk == "enjo":
                # ★同じ投稿に🔥と再発が両方付いた時、先に処理された方が source を取る。
                #   後から来た🔥を**落とさず**ここで重さだけ上げる(状態は動かさない)。
                d["enjo"] = True
            continue
        # --- confirm ---
        d = state.get(did)
        if d is None:
            continue                                  # (a) 開いていない物は閉じられない
        if d["status"] == DEFECT_CONFIRMED:
            continue
        fixed = str(r.get("fixed") or "")
        scene = str(r.get("scene") or "")
        ok, _kind, why = evidence_locator(fixed)
        if not ok:
            d["rejected"].append(f"{r.get('ts','')} {why}")
            continue
        if fixed.strip() and fixed.strip() == d["broken"].strip():   # (c)
            d["rejected"].append(f"{r.get('ts','')} 壊れた実物と同じ在りかを貼っている")
            continue
        if len(scene.strip()) < 4:                                   # (d)
            d["rejected"].append(f"{r.get('ts','')} 『同じ場面』(scene)が書かれていない")
            continue
        d["status"] = DEFECT_CONFIRMED
        d["fixed"] = fixed
        d["scene"] = scene
        d["confirmed_at"] = str(r.get("ts") or "")
    out = [state[i] for i in order]
    if dept:
        out = [d for d in out if d["dept"] == dept]
    return out


def open_defect_list(dept, kind=DEFECT_KIND_DEFECT):
    """その部屋の**未確認**だけを返す。★台帳が読めなくても [] を返す(交代は止めない)。

    kind=None を渡すと種別を問わず全部返す。
    ★既定を defect のままにしてある= **既存の呼び出し3箇所が1文字も変わらない**
      (起動文の不具合ブロック・引き継ぎの項目9・検査10)。
    """
    try:
        out = [d for d in fold_defects(dept) if d["status"] == DEFECT_OPEN]
        if kind:
            out = [d for d in out if d.get("kind", DEFECT_KIND_DEFECT) == kind]
        return out
    except Exception:                                # noqa: BLE001
        return []


def _enjo_first(items):
    """🔥(炎上)を先頭へ。それ以外の並びは**1件も動かさない**(安定ソート)。

    なぜ要るか(2026-08-14 イージス研究室の実測)= 改修部門αの未確認は100件、起動文に出るのは
      先頭12件(DEFECT_BLOCK_MAX)。🔥は後から押される=台帳では新しい=**末尾に沈む**。
      実測でも🔥24件が起動文に1件も出ていなかった。**印を足しても、読まれる場所に無ければ届かない**。
    ★C-040=🔥は「重大炎上案件・恒久対策しろ」。巡回の本文も「★最優先」と言っている。
      = 順番を変えるのは新しい方針ではなく、**既にある裁定の執行**。
    """
    return sorted(items, key=lambda d: 0 if d.get("enjo") else 1)


def defects_block(dept, head=True):
    """引き継ぎ/起動文へ差し込む本文。**空なら『無い』と書く**(書き忘れと区別するため)。

    ★機械が台帳から作る= セッションの作文に依存しない。ここが3枚目の縛り。
    """
    try:
        items = open_defect_list(dept)
    except Exception:                                # noqa: BLE001
        items = []
    items = _enjo_first(items)
    lines = []
    if head:
        lines.append(f"★**まだ直ったと確認できていない不具合**(機械の台帳 {DEFECTS_FILE} の実測):")
    if not items:
        lines.append("  **無い**(この部屋の未確認は0件)。")
        return "\n".join(lines)
    _n_fire = sum(1 for d in items if d.get("enjo"))
    if _n_fire:
        lines.append(f"  ★**🔥(炎上)が {_n_fire}件ある。先頭に出してある**"
                     "= Chamiが「これは事故だ・恒久対策まで行け」と押した印(C-038/C-040)。")
    for i, d in enumerate(items[:DEFECT_BLOCK_MAX], 1):
        sym = " ".join(d["symptom"].split())[:DEFECT_SYMPTOM_MAX]
        # ★🔥= Chamiが炎上スタンプを押した= **恒久対策まで行け**(C-038/C-040)。
        #   再発と同じ見た目で並べると重さが伝わらないので、頭に印を出す。
        _fire = "🔥【炎上=恒久対策まで行け】 " if d.get("enjo") else ""
        lines.append(f"  {i}. [{d['id']}] {_fire}{sym or '(症状の記録なし)'}")
        lines.append(f"     壊れた実物の在りか= {d['broken'] or '(無い★)'}"
                     f" / 気づいた= {d['noticed_at'] or '不明'}"
                     f"{' / 出所= ' + d['source'] if d['source'] else ''}")
        if d["rejected"]:
            lines.append(f"     ★確認済にしようとして**弾かれた記録** {len(d['rejected'])}件: "
                         + d["rejected"][-1])
    if len(items) > DEFECT_BLOCK_MAX:
        lines.append(f"  …ほか {len(items) - DEFECT_BLOCK_MAX}件(全文は {DEFECTS_FILE})")
    return "\n".join(lines)


def open_request_list(dept):
    """その部屋の**まだ終わっていない依頼**(kind=request)だけを返す。古い順(=台帳の順)。

    ★並びの既定= **台帳に積まれた順**(改善書§6 第1手「それ以外は古い順」)。
      「Chamiが最後に明示した物を先頭へ」は**まだ実装していない**= 並べ替えの合図
      (「〜を先に」)を拾う判定を新設することになり、発注の「新しい検出器を増やすな」に触れる。
      ★実務上は Chami が『〜を先に』と言えば、その便がその部屋へ届く=部屋が順番を変える。
    """
    return open_defect_list(dept, kind=DEFECT_KIND_REQUEST)


def requests_block(dept, head=True, limit=DEFECT_BLOCK_MAX):
    """「まだ終わっていない依頼」の一覧。★空なら空文字を返す(0件の部屋に1行も足さない)。

    ★defects_block と器を分けているのは**読む相手が違うから**ではなく、
      **文面の締め方が違うから**(不具合=「直った実物を見ろ」/ 依頼=「上から順に進めろ」)。
    """
    try:
        items = open_request_list(dept)
    except Exception:                                # noqa: BLE001
        items = []
    if not items:
        return ""
    items = _enjo_first(items)
    lines = []
    if head:
        lines.append(f"★**まだ終わっていないChamiの依頼**(機械の台帳 {DEFECTS_FILE} の実測。"
                     "上から順に進めろ):")
    _n_fire = sum(1 for d in items if d.get("enjo"))
    if _n_fire:
        lines.append(f"  ★**🔥(炎上)の {_n_fire}件を先頭に置いた**"
                     "= Chamiが「これは事故だ・恒久対策まで行け」と押した印(C-038/C-040)。"
                     "残りは従来どおり古い順。")
    for i, d in enumerate(items[:limit], 1):
        sym = " ".join(d["symptom"].split())[:DEFECT_SYMPTOM_MAX]
        _fire = "🔥【炎上=恒久対策まで行け】 " if d.get("enjo") else ""
        lines.append(f"  {i}. [{d['id']}] {_fire}{sym or '(依頼の本文なし。元の便を見ること)'}")
        lines.append(f"     依頼の便の在りか= {d['broken'] or '(無い★)'}"
                     f" / 頼まれた= {d['noticed_at'] or '不明'}"
                     f"{' / 出所= ' + d['source'] if d['source'] else ''}")
        if d.get("close_when"):
            lines.append(f"     ★閉じる条件= {d['close_when']}")
        if d.get("nudges"):
            lines.append(f"     ★Chamiからの催促 {len(d['nudges'])}件"
                         f"(最新= {d['nudges'][-1]})")
        if d["rejected"]:
            lines.append(f"     ★閉じようとして**弾かれた記録** {len(d['rejected'])}件: "
                         + d["rejected"][-1])
    if len(items) > limit:
        lines.append(f"  …ほか {len(items) - limit}件(全文は {DEFECTS_FILE})")
    return "\n".join(lines)


def close_request_note(dept):
    """依頼を閉じる時の掟(★不具合と**同じ厳しさ**。「やりました」で閉じさせない)。"""
    return (
        "★**依頼は『やりました』では閉じられない。**閉じるには**次を実行**しろ\n"
        f'   python scripts/llm/close_item.py --id <上のID> --dept {dept} '
        '--fixed "<終わった実物の在りか>" --scene "<どの場面で確かめたか>" --by "<誰>"\n'
        f"   (台帳 {DEFECTS_FILE} へ1行追記される。追記のみ・既存行は書き換えない)\n"
        "★**生JSONを手で書くな**(2026-08-12実測= 手打ちのWindowsパスの `\\` で行が壊れ、"
        "**confirm 2件が黙って消えて**その依頼が永久に未完了として出続けていた)。\n"
        "★`fixed` は**機械が解決できる在りか**でなければ受理されない= "
        "Discordのmsg_id/リンク・実在するファイルのパス・URL のどれか。\n"
        "★★**commitのhashだけでは受理されない**(『commitに封じたと書いてある』は台帳であって、"
        "**Chamiの画面で終わっている実物ではない**)。")


# --- 引き継ぎパケット(提案書§7.2 手順2) ---
def _handoff_path(dept):
    return os.path.join(LOCAL, "llm", f"handoff_{dept}.md")


def _handoff_new_path(dept):
    """セッション本人に**書かせる先**(下書き)。検収を通ってから正本へ採用する。

    ★2026-07-29 追加。正本= 改善書_セッション引き継ぎの劣化と消失_2026-07-29.md §4(1)。
      なぜ別名か= 書き途中の半端なものや、検収に落ちたものを**正本の席に座らせない**ため。
      ★ファイル名は**機械が決める**。セッションに選ばせない。
        実測(改善書§2 原因2): llm-edu 7/28 18:16 の交代で、セッションは完全な引き継ぎ 7,656B を
        **自分で決めた別名** `handoff_llm-edu_vol3.md` へ書き終えていたのに、機械が見つけられず
        「生成失敗」扱いになった=**在る成果を捨てた**。
    """
    return _handoff_path(dept) + ".new"


# --- 引き継ぎの検収(改善書§4(1)。機械で判定できる3条件だけ) ---
# ★なぜ検収が要るか(改善書§2 原因1・§6-1):
#   旧版は「**返信の文章=引き継ぎ**」と仮定して無検査で保存していた。だがWriteを持つセッションは
#   自分でファイルへ完全版を書き、返信には「書きました」という**報告文**を返す。
#   実測(2026-07-27):
#     10:08:31 セッション本人が handoff_hq.md へ完全版 8,352B(8項目)を書いた
#     10:08:38 ★7秒後、_write_handoff() が返信(報告文 792B)で上書き → 完全版は .gen3 へ押し出された
#   その結果、第4世代は792B版の3項目しか引き継げていなかった(request_log 10:09:46 の自己確認で確認)。
#   hr-context も同型(8,049B → 382B)。
# ★閾値の根拠(実測。★厳しすぎて正しい引き継ぎを弾かないこと):
#   健常な実物 30本(handoff_*.md / .gen*)は**全部 見出し8/8**で、本文は 4,432〜8,653B。
#   壊れた実物2本(.overwritten_*)は**見出し0/8**で 664B / 247B。
#   → 見出し6以上・2,000B以上なら、健常側に**1本も触れずに**壊れた側だけを落とせる。
HANDOFF_MIN_BYTES = 2000
HANDOFF_MIN_HEADINGS = 6
# 8項目。番号で当たらない時のために言い回しの手がかりも持つ(見出しは
# 「## 3. 決まったこと(この世代で確定・実測済)」のように尾ひれが付く)。
_HANDOFF_ITEMS = (
    (1, ("部屋の目的", "この部屋は")),
    (2, ("今の目標", "目標")),
    (3, ("決まったこと", "決定")),
    (4, ("未完了",)),
    (5, ("ファイルのパス", "重要なファイル")),
    (6, ("直近",)),
    (7, ("やってはいけない", "禁じ手")),
    (8, ("Chami",)),
)
_HANDOFF_HEAD_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*(?:\*\*)?\s*(\d{1,2})?[\.．、\)\s]*(.*)$")
# 「引き継ぎを〜に書いた/書き直しました」型の**報告文**。792B事件の1行目がこれ。
_HANDOFF_REPORT_RE = re.compile(
    r"(引き?継ぎ|ハンドオフ|handoff)[^。\n]{0,60}?"
    r"(書いた|書きました|書き直し|書き終え|保存し|更新し|作成し|出力し|記載し|まとめ(?:た|ました))")


def _handoff_strip_header(text):
    """機械が付ける `<!-- dept=... -->` の1行を外して**本文だけ**にする。"""
    t = (text or "").lstrip("\ufeff")           # BOMは目に見えないのでエスケープで書く
    if t.startswith("<!--"):
        i = t.find("-->")
        if i >= 0:
            t = t[i + 3:]
    return t.lstrip()


def handoff_verdict(text):
    """引き継ぎの検収。戻り値 (ok, 実測の一言, 落ちた理由のリスト)。

    ★relay_health.py の検査7からも**同じ関数**を呼ぶ(判定を2箇所に置くと必ず片方が古くなる)。
    ★fail-open の原則: ここでTrueにならなくても交代は続行する(呼び元が前世代版へ倒す)。
    """
    body = _handoff_strip_header(text)
    nbytes = len(body.encode("utf-8", "replace"))
    found = set()
    for line in body.splitlines():
        if not line.lstrip().startswith("#"):
            continue
        m = _HANDOFF_HEAD_RE.match(line)
        if not m:
            continue
        num, rest = m.group(1), m.group(2) or ""
        for idx, keys in _HANDOFF_ITEMS:
            if num and num.isdigit() and int(num) == idx:
                found.add(idx)
            elif any(k in rest for k in keys):
                found.add(idx)
    first = ""
    for line in body.splitlines():
        if line.strip():
            first = line.strip()
            break
    # ★報告文の判定は**見出しで始まっていない時だけ**に絞る。
    #   理由= 正しい引き継ぎの本文中に「〜を書いた」と書いてあることは普通にある。
    #   実測でも健常30本は1本も報告文と見なされていない。
    looks_report = bool(_HANDOFF_REPORT_RE.search(body[:200])) and not first.startswith("#")
    reasons = []
    if len(found) < HANDOFF_MIN_HEADINGS:
        reasons.append(f"見出しが{len(found)}/8(要{HANDOFF_MIN_HEADINGS})")
    if nbytes < HANDOFF_MIN_BYTES:
        reasons.append(f"本文{nbytes}B(要{HANDOFF_MIN_BYTES}B)")
    if looks_report:
        reasons.append("報告文の形をしている")
    return (not reasons), f"見出し{len(found)}/8 本文{nbytes}B", reasons


# --- 検収に足す1つ: 引き継ぎが**規律を緩めていないか**(2026-07-29) ---
#
# 正本= 改善書_記憶と引き継ぎの抜本見直し_2026-07-29.md §3 / §7-3。実測の事故:
#   第12世代の引き継ぎ§8(正本182行目)= 「**選択肢は出さず既定を決めて実行**」
#   → 第13世代は12:07と15:37の2回とも「次はどちらから行くか、向きだけ教えてくれ」で締め(規律と逆)、
#     さらに 11:32 に自分が書いた引き継ぎ(185行目)へ
#     「**ただし着手順の"向き"(A先/B先)は問うてよい**」と**例外を書き足した**。
#   = **守れなかった本人が、自分の行動に合わせて規律の方を緩めた。**
#   今日の検収(見出し数・バイト数・報告文でない)は**これを素通しする**(§7-3)。
#
# ★★倒し方は「**警告+記録**」にした(発注が3案から選べと言ったところ)。決めた根拠(実測):
#   本番の引き継ぎ14本で誤検出を測ったところ、規律の語と緩和の言い回しは
#   **健全な引き継ぎの中にも普通に同居しうる**(例:「〜は禁じ手だが、△△の場合は例外」と
#   **Chamiが決めた**例外を正しく書き写している行)。機械には「誰が決めた例外か」が見えない。
#   → **弾くと、正しい引き継ぎを丸ごと失う**(=沈黙を作る。fail-openの原則に反する)。
#   → ok/reasons(採否)には**一切触らない**。別の関数として警告だけ出す。
# ★完全な判定は無理だ、と正直に書いておく。ここが縛れるのは「**緩和の言い回しの同居**」までで、
#   その緩和が正当か(Chamiが決めた例外か・本人が勝手に足したか)は機械には見えない。
_LOOSEN_RULE_WORDS = (
    "規律", "掟", "禁じ手", "裁定", "ルール", "原則", "決まり",
    "§4.5", "4.55", "共通規律", "Chami台帳", "やってはいけない",
)
# 「緩める」言い回し。★**意志・許可の形だけ**を見る(地の文の「〜てもよい結果」等を拾わない)。
_LOOSEN_PHRASE_RE = re.compile(
    "|".join((
        r"ただし[^。\n]{0,50}?(?:てよい|て良い|でよい|で良い|しても?よい|は可|は例外)",
        r"例外(?:として|的に)[^。\n]{0,20}?(?:よい|良い|する|できる)",
        r"例外(?:を|も)(?:足|加|認|設|置)",
        r"(?:適用|該当)し(?:ない|なくてよい)ことに(?:する|してよい)",
        r"(?:免除|緩和|除外|例外化)し(?:て)?(?:も)?(?:よい|良い|構わない|かまわない)",
        r"(?:問うて|聞いて|尋ねて)(?:も)?(?:よい|良い|構わない|かまわない)",
        r"(?:守らなく|従わなく|書かなく|やらなく|しなく)て(?:も)?(?:よい|良い|構わない|かまわない)",
        r"(?:この部屋|ここ|本件)(?:に限(?:り|って)|では)[^。\n]{0,30}?(?:よい|良い|不要|免除)",
    )))
_LOOSEN_SPLIT = re.compile(r"[\n。]")
# ★引用の中(「…」『…』"…")は**本人が足した緩和ではない**(Chamiの原文や定型文の写し)。
#   実測の誤検出= report-notify L67「**『Chamiは何もしなくてよい』を毎回書かない**」。
_LOOSEN_QUOTE_RE = re.compile(r"「[^」]*」|『[^』]*』|\"[^\"]*\"|“[^”]*”")
# ★正本の番号を添えて引いている例外は、**本人が足した例外ではない**(既に裁定された物の引用)。
#   実測の誤検出= platform-se L33「ただし自分の作業範囲内なら…報告してよい**(C-006)**」。
_LOOSEN_CITED_RE = re.compile(r"\b(?:C|ORG|INC|DEF|REQ)-\d{2,}", re.I)


# ★★実測で分かったこと(2026-07-29。**発注の指定より広げた。理由をここに残す**):
#   発注は「緩和の言い回し + **規律の語** の同居を見る程度でよい」と書いてあった。
#   ところが**本物の事故の1行にはその『規律の語』が1つも無い**:
#     handoff_system-engineer.md L196(項目8=Chamiについて)
#       「**選択肢は出さず既定を決めて実行、限界だけ正直に添える**。
#         ただし着手順の"向き"(A先/B先)は**問うてよい**。」
#   規律の語で縛ると、**直そうとしている当の1行を検出できない**(実測で確認)。
#   → 改善書§7-3 の言い方に合わせて広げた=
#     「**累積セクションは次世代への命令文なのだから、緩められたら鳴る仕組みが要る**」。
#     つまり**項目3・7・8の中では、規律の語が無くても緩和の言い回しだけで拾う**。
#     項目3・7・8の外(生きている物=2・4・6等)では従来どおり規律の語との同居を要求する。
_LOOSEN_CUMULATIVE_ITEMS = (3, 7, 8)          # 累積=次世代への命令文になる節


def _handoff_section_of(line, cur):
    """その行が属する項目番号を返す(見出し行なら更新)。分からない時は cur のまま。"""
    if not line.lstrip().startswith("#"):
        return cur
    m = _HANDOFF_HEAD_RE.match(line)
    if not m:
        return cur
    num, rest = m.group(1), m.group(2) or ""
    if num and num.isdigit():
        return int(num)
    for idx, keys in _HANDOFF_ITEMS:
        if any(k in rest for k in keys):
            return idx
    return 0                                   # 見出しだが番号も手がかりも無い=節の外


def discipline_loosening(text):
    """引き継ぎ本文が「規律を緩める記述」を含むか。 戻り値= [(行番号, 節番号, 抜粋), …]

    ★採否(handoff_verdict)には**影響させない**。呼び元は警告して記録するだけ。
    ★例外を1つ置いてある= 「**規律を緩めるな / 書き換えるな**」と**禁じている**行は緩和ではない
      (この指示文の写しや、引き継ぎが自戒として書いた行)。ここを外すと機構が自分の指示で発火する。
    """
    hits = []
    body = _handoff_strip_header(text or "")
    cur = 0
    for i, line in enumerate(body.splitlines(), 1):
        cur = _handoff_section_of(line, cur)
        if line.lstrip().startswith("#"):
            continue
        # ★「緩めるな」「書き換えるな」と禁じている行は緩和ではない(自戒・引用)
        if re.search(r"(緩め|書き換え|足し|変え)(?:るな|ない|てはいけない|ては駄目)", line):
            continue
        wide = cur in _LOOSEN_CUMULATIVE_ITEMS      # 累積セクション= 規律の語を要求しない
        for s in _LOOSEN_SPLIT.split(line):
            if not (wide or any(w in s for w in _LOOSEN_RULE_WORDS)):
                continue
            if _LOOSEN_CITED_RE.search(s):
                continue                            # 裁定番号つき= 既に決まっている例外の引用
            # ★引用の中身を落としてから見る(見せる時は元の一文のまま)
            if _LOOSEN_PHRASE_RE.search(_LOOSEN_QUOTE_RE.sub("", s)):
                hits.append((i, cur, s.strip()[:120]))
                break
    return hits


def _keep_old_handoff(path, generation):
    """前世代の引き継ぎを**消さずに退避**する(C-003=正本を上書きで失わない)。

    ★`handoff_<dept>.md.gen<N>` へ改名する。同名が既にあれば `_2`,`_3`… を足して**必ず残す**。
      なぜ残すか= 引き継ぎが薄かった時に「何が落ちたか」を後から追える唯一の証拠だから。
    ★Nは「**そのファイルを書いた世代**」であって、今から交代する世代ではない。
      先頭のヘッダから読む(読めない時だけ引数へ退避)。ここを取り違えると、
      あとで台帳を見た時に**どの世代の引き継ぎか分からなくなる**=証拠として役に立たない。
    """
    if not os.path.exists(path):
        return
    wrote_gen = generation
    try:
        with open(path, encoding="utf-8") as f:
            head = f.readline()
        m = re.search(r"第(\d+)世代", head)
        if m:
            wrote_gen = int(m.group(1))
    except OSError:
        pass
    base = f"{path}.gen{wrote_gen}"
    dest, k = base, 1
    while os.path.exists(dest):
        k += 1
        dest = f"{base}_{k}"
    try:
        os.replace(path, dest)
    except OSError:
        pass                                     # 退避できなくても交代は続ける(fail-safe)


# =============== 出荷の台帳 change_log.jsonl の時刻を機械が入れる(2026-07-29) ===============
#
# 正本= 改善書_記憶と引き継ぎの抜本見直し_2026-07-29.md §4末尾 / §6 第3手 / §7-5。
# ★壊れていた計器(実物):
#     ファイル更新時刻 15:37 の台帳に **ts=15:45 の行**(=未来時刻)
#     12時頃の作業が **02:45** で記録(=9時間ズレ)
#     書式も「07-29T」「07-29 JST」「+09:00の有無」が混在
#   朝礼の24時間窓・kaizenの週次PDCA・**Z1の計数は全部この時刻で切っている**。
#   = **Z1を測る計器が既に狂っている**(§7-5「時刻を自己申告にした台帳で、時間を測る運用を始めた」)。
#
# ★★どう直したか(発注の指定=「書き手が渡した ts を信用せず、機械が入れ直す。
#   元の申告は別キーに残す=消さない」):
#   - 追記の正規の入口= log_change()。**ts は機械が入れる**(引数で ts を受け取らない)。
#   - だが規律(全部門共通規律 L55)は「change_log.jsonl に1行足せ」と書いてあり、
#     各セッションは**自分でファイルへ追記する**。規律は触るなと言われている(触れば二重正本になる)。
#     → **後追いで正す**: 機械が定期的に台帳を舐め、まだ機械が見ていない行の ts を入れ直す。
#       元の申告は `ts_claimed` に残す(消さない)。ズレは `ts_skew_sec` に残す。
# ★★機構を入れる前から在る行は**書き換えない**(102行の履歴を「今」に塗り潰したら、
#   それ自体が新しい嘘になる)。一度だけ `ts_source="self(機構導入前・未検証)"` の印を付けて、
#   **その印そのものを水位線として使う**(新しい状態ファイルを増やさない)。
CHANGE_LOG_FILE = os.path.join(LOCAL, "llm", "change_log.jsonl")
CHANGE_LOG_LOCK = CHANGE_LOG_FILE + ".lock"
CHANGE_LOG_LOCK_STALE = 60.0        # 置き去りの錠を捨てる秒数(書き手が落ちても止まらない)
CHANGE_TS_MACHINE = "machine"       # 機械が観測して入れた
CHANGE_TS_LEGACY = "self(機構導入前・未検証)"


def _now_iso():
    """`2026-07-29T16:21:07+09:00` の形。★書式もここで揃える(混在をやめる)。"""
    z = time.strftime("%z") or "+0000"
    return time.strftime("%Y-%m-%dT%H:%M:%S") + (z[:3] + ":" + z[3:])


def _change_lock():
    """素朴な排他錠。取れたら True。★取れなくても**呼び元は止まらない**(次の巡回で入る)。"""
    try:
        if os.path.exists(CHANGE_LOG_LOCK):
            if time.time() - os.path.getmtime(CHANGE_LOG_LOCK) > CHANGE_LOG_LOCK_STALE:
                os.remove(CHANGE_LOG_LOCK)      # 置き去りの錠(書き手が落ちた)
            else:
                return False
        fd = os.open(CHANGE_LOG_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except OSError:
        return False


def _change_unlock():
    try:
        os.remove(CHANGE_LOG_LOCK)
    except OSError:
        pass


def log_change(dept, what, why, touched="", commit=""):
    """出荷の台帳へ1行追記する**正規の入口**。★ts は機械が入れる(引数で受け取らない)。

    ★共通規律 L55 の `{"ts","dept","何","なぜ","触った","commit"}` と**同じ形**で書く
      (器も鍵も増やさない)。違うのは ts を書き手から受け取らないことだけ。
    ★失敗しても例外を外へ出さない(この台帳のせいで作業や便が止まることは無い)。
    """
    try:
        os.makedirs(os.path.dirname(CHANGE_LOG_FILE), exist_ok=True)
        rec = {"ts": _now_iso(), "ts_source": CHANGE_TS_MACHINE, "dept": str(dept or ""),
               "何": str(what or ""), "なぜ": str(why or ""),
               "触った": str(touched or ""), "commit": str(commit or "")}
        with open(CHANGE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception:                            # noqa: BLE001
        return False


def _change_skew_sec(claimed, machine_epoch):
    """申告と機械の時刻の差(秒)。読めない申告は None。"""
    t = str(claimed or "").strip()
    if not t:
        return None
    t = re.sub(r"\s*(?:JST|Z)$", "", t).replace(" ", "T")
    t = re.sub(r"([+-]\d{2}):?(\d{2})$", "", t)          # 尾のオフセットは落として素で読む
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return int(time.mktime(time.strptime(t, fmt)) - machine_epoch)
        except ValueError:
            continue
    return None


def normalize_change_log():
    """台帳の時刻を機械の時刻へ入れ直す。戻り値 (直した行数, 印を付けた行数)。

    ★やること(1行ずつ・追記済みの行だけ):
      - `ts_source` を持たない行 = **まだ機械が見ていない行**
        ・台帳のどこにも `ts_source` が無い = **初回**(機構導入前の履歴)
            → ts は**触らず** `ts_source=self(機構導入前・未検証)` の印だけ付ける。
              ★ここで「今」に塗り替えたら 102行の履歴が全部嘘になる。だから触らない。
        ・2回目以降 → **機械が観測した時刻**を ts に入れ、元の申告を `ts_claimed` に残す。
              ズレは `ts_skew_sec` に残す(未来時刻・9時間ズレが**数字で見える**ようになる)。
      - `ts_source` を持つ行は**1バイトも触らない**(冪等)。
    ★機械の時刻の精度= この関数が回る間隔(dept_daemon の掃き出し=60秒)まで。
      **書いた瞬間の時刻ではない**。正直に書いておく。9時間ズレを分単位へ縮める機構であって、
      秒まで正しくする機構ではない。
    ★何が失敗しても例外を外へ出さない(fail-open)。錠が取れなければ次の巡回でやる。
    """
    try:
        if not os.path.exists(CHANGE_LOG_FILE):
            return 0, 0
    except OSError:
        return 0, 0
    if not _change_lock():
        return 0, 0
    fixed = marked = 0
    try:
        # ★読み始める前の姿を覚えておく。書き換える直前にもう一度見て、**1バイトでも
        #   増えていたら書かない**(規律は「自分で1行足せ」なので、舐めている最中に
        #   セッションが追記しうる。その1行を取りこぼしたら台帳が嘘になる)。
        st0 = os.stat(CHANGE_LOG_FILE)
        rows, raws = [], []
        with open(CHANGE_LOG_FILE, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.rstrip("\n")
                raws.append(s)
                if not s.strip():
                    rows.append(None)
                    continue
                try:
                    r = json.loads(s)
                except Exception:                # noqa: BLE001
                    rows.append(None)            # ★壊れた行はそのまま残す(捨てない)
                    continue
                rows.append(r if isinstance(r, dict) else None)
        seen = any(isinstance(r, dict) and r.get("ts_source") for r in rows)
        now_iso, now_ep = _now_iso(), time.time()
        out, changed = [], False
        for r, raw in zip(rows, raws):
            if r is None or r.get("ts_source"):
                out.append(raw)
                continue
            if not seen:
                # 初回= 機構導入前の履歴。**印だけ**付ける(時刻は本人の申告のまま)
                r["ts_source"] = CHANGE_TS_LEGACY
                marked += 1
            else:
                claimed = r.get("ts", "")
                skew = _change_skew_sec(claimed, now_ep)
                if claimed:
                    r["ts_claimed"] = claimed    # ★元の申告は消さない
                if skew is not None:
                    r["ts_skew_sec"] = skew
                r["ts"] = now_iso
                r["ts_source"] = CHANGE_TS_MACHINE
                fixed += 1
            changed = True
            out.append(json.dumps(r, ensure_ascii=False))
        if changed:
            st1 = os.stat(CHANGE_LOG_FILE)
            if (st1.st_size, st1.st_mtime) != (st0.st_size, st0.st_mtime):
                return 0, 0              # ★舐めている間に誰かが追記した=今回は書かない
            tmp = CHANGE_LOG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(out) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, CHANGE_LOG_FILE)     # ★原子的(半端な台帳を読ませない)
    except Exception:                            # noqa: BLE001
        return 0, 0
    finally:
        _change_unlock()
    return fixed, marked


# --- 引き継ぎの予算(2026-07-29。改善書_記憶と引き継ぎの抜本見直し §6 第2手) ---
#
# なぜ要るか(実測。改善書§1・§7-1):
#   改修αの引き継ぎ= 7/28 18:05に **5,202B** → 7/29 08:37に **34,445B**。15時間で6.6倍。
#   この速度なら3日で10万B級=起動だけで窓の1/4を食う。
#   原因は「消さず積み増せ」(項目3・7・8)に**予算が無かった**こと。
#   ★§7-1 の自己批判そのもの=
#     「共通規律には同じ日に『8,000字予算』を発注しておきながら、同じ日に強化した
#       引き継ぎの累積セクションは**青天井にした**。太る器を作ったら、必ず同時に予算を付ける。」
# ★予算を超えた時に**消す**のではない。**正本へ移す**(下の HANDOFF_DROP_RULE)。
# ★2026-08-02 10,000→14,000(イージス研究室・C-027/HQ裁定 DISPATCH-aegis-gl-1785603956128)。
#   真因= 10,000B は**実態より低すぎた**。改修αの正当な引き継ぎ実測(8/1・request_log.jsonl・JST)=
#     04:09 13,599B / 04:39 11,304B / 13:52 13,363B / 14:02 12,805B / 14:15 13,086B。
#   累積の項目3・7・8(各2,000B目安)+基本構造で正当に11〜14k乗るのに予算10kだと**毎回超過**判定になり、
#   その後始末(HANDOFF_DROP_RULEの走査)に便を食われるのが「遅すぎ」の構造要因だった(Chami重症エスカレ msg1533122665466822676)。
#   → 実測最大13,599Bを収める14,000へ。**暴走(青天井で6.6倍=34,445B)は依然この線で捕捉できる**(器を外したのではなく実態に合わせた)。
#   C-018=最小手(圧縮でなく予算を実態へ)。HANDOFF_DROP_RULEは不変=本当に肥大した便だけ発火する。
HANDOFF_BUDGET_BYTES = 14000

# 予算を超えた時に「何を落とすか」の基準。★機構が持つ(セッションの気分に任せない)。
#   順番に意味がある= **上から落とす**。生きている物(項目2/4/6)は最後まで落とさない。
HANDOFF_DROP_RULE = (
    f"★**引き継ぎ全体の予算= {HANDOFF_BUDGET_BYTES:,}バイト**"
    "(累積の項目3・7・8は各2,000B目安)。超えたら**消すのではなく正本へ移す**。\n"
    "  落とす順番はこの通り(上から。**生きている物は最後まで落とすな**):\n"
    f"  1. 済んだ出荷の詳細(v=◯◯で何を直した等) → 正本は `{CHANGE_LOG_FILE}`。"
    "引き継ぎには**1行も書くな**(『直近の出荷は change_log.jsonl の末尾を見ろ』で足りる)。\n"
    "  2. 全部門共通規律・Chami台帳(00_common)に正本がある行 → **書くな**。"
    "規律もChami台帳も**毎便の封筒で届いている**。写しは古くなるだけで、二重に運ぶ意味が無い。\n"
    "  3. 設計の全体像・調査の結論 → `docs/設計・調査/` の正本へ移し、項目5から**パスで指す**。\n"
    "  4. 未確認の不具合・未完了の依頼の**一覧** → 機械の台帳が正本"
    "(**起動文へ機械が直接差し込んでいる**。本文へ書き写すと二重配達になる)。\n"
    "  ★ここまで削っても足りない時だけ、項目3・7・8の**古い方から**縮める。")


def _handoff_defect_note(dept):
    """引き継ぎの**項目9**(未確認の不具合)の指示文。台帳の実測をそのまま差し込む。

    ★なぜ足したか(改善提案部門 2026-07-29_saihatsu-2.md §構造指摘C・実測):
      「1つのセッションがバグを『壊れた実物を見る→同じ場面で直ったを見る』(§4.55)まで
        見届ける前に交代し、次のセッションは『commitに封じたと書いてある』(台帳)を継ぐが
        『Chamiの画面で消える』(現物)を継がない。だから毎回『封じた』を再宣言する。」
      塊B= 1時間で修正5本・各再発はfixの4〜19分後・「直った」到達は0。
    ★**既存8項目は1つも削っていない**(足しただけ)。
    ★★検収(handoff_verdict)の8項目は**変えていない**。項目9が抜けても引き継ぎは落とさない
      (落とすと交代が止まる=沈黙を作る)。項目9の抜けは relay_health の検査10が鳴らす。

    ★★2026-07-29 **痩せさせた**(改善書_記憶と引き継ぎの抜本見直し §6 第2手・§7-2)。
      §7-2 の指摘そのもの=
        「器を増やした日に、**複製も増やした**。open_defects.jsonl(正本)+起動文への機械注入
          (配達)まで作ったのに、引き継ぎの項目9として**同じ内容をもう1回書かせている**。」
      実測= 引き継ぎ34,445Bのうち §9 が **4,631B**。中身は台帳(3,318B)とほぼ同じで、
      しかも**起動文が同じ台帳を機械注入している**=新世代は同じ5件を2回受け取っていた。
      → 症状も在りかも**書かせない**。書かせるのは **IDの1行だけ**。
    ★なぜ「参照2行」ではなく「参照2行 + IDの1行」なのか(★発注からの意図的なズレ・理由を残す):
      relay_health の**検査10(b)** が「未確認が引き継ぎ正本に**在りかつきで**載っているか」を
      id か msg_id の文字列一致で見ている。IDまで消すと、検査10が**全件について永久に赤**になる
      (=狼少年。ORG-42)。発注の検証6「既存の検査1〜10の出力を変えていないこと」とも衝突する。
      → **IDだけは残す**。バイト数は 4,631B → 数百B に落ちるので、痩せの目的は達成できる。
    """
    ids = [d["id"] for d in open_defect_list(dept)]
    return (
        "  ★項目9の**正本は機械の台帳**だ(引き継ぎではない)。\n"
        f"  ★未確認の一覧(症状・壊れた実物の在りか)は**起動文へ機械が直接差し込む**"
        f"(台帳= {DEFECTS_FILE})。**本文へ書き写すな**=二重配達になる。\n"
        "  ★項目9に書くのは次の**IDの行1本だけ**"
        "(症状も在りかも書くな。閉じ方は台帳の掟の通り):\n"
        + ("     未確認: " + " / ".join(ids) + "\n" if ids
           else "     未確認: **無い**(この部屋の未確認は0件)\n")
        + "  ★『直した』では項目9から**消せない**。消せるのは"
        "**同じ場面で直った実物を見た**時だけで、その時は "
        "`python scripts/llm/close_item.py --id <ID> --dept %s --fixed .. --scene ..` "
        "を実行しろ(★生JSONを手打ちするな・commitのhashは受理されない)。\n" % dept)


def _handoff_request_note(dept):
    """引き継ぎの**項目4**(未完了)へ足す、機械の台帳への参照(2026-07-29 新設)。

    ★正本= 改善書_記憶と引き継ぎの抜本見直し §5/§6 第1手。
      「**未完了は、引き継ぎに書かれた瞬間に『安全に死蔵』される。**
        書く器は揃ったが、**書かれた物を動かす機構が無い**。動かす合図が
        『Chamiがもう一度言う』になっている。Z1(Chamiの手数)の正体はこれだ。」
    ★だから引き継ぎ側は**IDで指すだけ**にする(中身を書き写させない=二重配達を作らない)。
      催促は機械が sweep_waiting の経路で入れる(dept_daemon の request_followup)。
    ★0件の部屋では**1行も増えない**(既存の指示文と完全に同一)。
    """
    ids = [d["id"] for d in open_request_list(dept)]
    if not ids:
        return ""
    return (
        "  ★項目4のうち**Chamiが明示的に頼んだ未完了**は、機械の台帳が正本だ"
        f"({DEFECTS_FILE} の kind=request)。一覧は**起動文へ機械が差し込む**ので"
        "**本文へ書き写すな**。項目4に書くのは次のIDの行1本と、"
        "**誰がどこまでやったか**の1〜2行だけ:\n"
        "     未完了の依頼: " + " / ".join(ids) + "\n"
        "  ★これらは『上から順に進める』物だ。**次の世代へ『どっちから行くか聞け』と書くな。**\n")


# ★_said_rotation() は撤去した(2026-08-12)。「本人が世代の更新を言えているか」を実測して
#   機械の定型文を出し分ける関数だったが、Chamiが**宣言そのものを要らない**と言ったので
#   出し分ける対象が消えた。判定だけ残すと「何のための検査か」が誰にも分からなくなる。
#   原文と経緯= _boot_prompt 内(「世代続投宣言別にいらない」)と交代直後のブロックにある。


def _handoff_prompt(dept, conf, generation, checkpoint=False):
    """今のセッション自身に書かせる引き継ぎの指示(提案書§7.2 手順2)。

    checkpoint(2026-07-29・改善書 第2手(d)): 交代の前ではなく**定期健診**として書かせる時 True。
      ★変えるのは冒頭の1文だけ= 検収も書き先も8項目も**一切変えない**
        (判定を2本持つと必ず片方が古くなる。姉妹文書§4(1)の検収をそのまま使う)。
      ★「まもなく次の世代へ引き継ぐ」を定期健診で言うと**嘘**になる。そこだけ直す。

    ★**要約させるのはこのセッション自身**でなければならない。外から履歴を読んで要約すると、
      「何が決まって何が未完了か」という**会話の当事者しか知らない情報**が落ちる。
    ★2026-07-29 変更(改善書§4(1)): 「出力はMarkdownの本文だけ」をやめ、
      **Writeツールで `.new` へ書かせる**形にした。返信は1言でよい
      (★2026-08-12・C-032= その1言は**実行者の口調で**。旧「『書いた』の1行でよい」は撤回)。
      なぜ= 相手はWriteを持つ作業エージェントで、「引き継ぎを書け」と言えばファイルへ書く。
      返信だけを見て保存する設計は、その正しい行動を**取り違える**(792B事件)。
      これで**書く仕事と返事する仕事が分離**され、返信の時間切れが成果を道連れにしなくなる。
    """
    new_path = _handoff_new_path(dept)
    if checkpoint:
        head = (f"【システム: 引き継ぎの定期チェックポイント】これはChamiからの便ではない。"
                f"Discordへは出さない。\n"
                f"あなたはDiscordの部屋 {dept} の第{generation}世代の担当セッションだ。"
                f"文脈が {HANDOFF_CHECKPOINT_AT_TOKENS:,} トークンを超えた。"
                f"**交代するわけではない**(この後もあなたが続ける)。"
                f"ただし文脈はいずれ圧縮で畳まれるので、**畳まれても失われない場所**="
                f"ファイルへ、今の知識を書き出して更新しておく。\n")
    else:
        head = (f"【システム: セッション交代の準備】これはChamiからの便ではない。Discordへは出さない。\n"
                f"あなたはDiscordの部屋 {dept} の第{generation}世代の担当セッションだ。"
                f"文脈が {ROTATE_AT_TOKENS:,} トークンを超えたので、**まもなく次の世代へ引き継ぐ**。\n")
    return (
        head
        + "**次のあなたが困らないように**引き継ぎを書け。次の見出しをこの順で立てること:\n"
        "1. 部屋の目的\n2. 今の目標\n3. 決まったこと\n4. 未完了のこと\n"
        "5. 重要なファイルのパス\n6. 直近の会話の要点\n7. やってはいけないこと\n"
        "8. Chamiについて分かったこと\n"
        "9. まだ直ったと確認できていない不具合(壊れた実物の在りかつき)\n"
        + _handoff_defect_note(dept)
        # ★★2026-07-29 追加(改善書§6 第1手)。項目4(未完了)も**機械の台帳が正本**になった。
        #   §5の実話= 引き継ぎに「未着手」と正しく書いてあったのに誰も実行に変換せず4時間放置。
        #   → 引き継ぎ側では**IDで指すだけ**にし、中身と催促は機械に持たせる。
        + _handoff_request_note(dept)
        + "★**推測で埋めるな。分からないことは『不明』と書け。**"
        "もっともらしく埋めた引き継ぎは、次の世代に**嘘を確信として持たせる**=最悪の事故だ。\n"
        "★未完了のことは**誰が何をどこまでやったか**まで書け(『検討中』だけでは引き継げない)。\n"
        "★**項目3(決まったこと)・7(やってはいけないこと)・8(Chami)は、"
        "前世代の引き継ぎの内容を引き継いで積み増せ**(消して書き直すな。ここは累積する)。"
        "**項目2(目標)・4(未完了)・6(直近)は現況に書き換えろ**(ここは更新する)。\n"
        # ★★2026-07-29 追加(改善書_記憶と引き継ぎの抜本見直し §6 第2手)。
        #   「消さず積み増せ」に**予算が無かった**のが 15時間で6.6倍の原因(§7-1)。
        #   積み増しの指示のすぐ後ろに置く= 読む順番として、太らせる指示と予算が必ず対になる。
        + HANDOFF_DROP_RULE + "\n"
        # ★★2026-07-29 追加(改善書§3・§7-3)。**ここが一番危ない穴だった。**
        #   第13世代は「選択肢は出さず既定を決めて実行」(第12世代の正本)を2回破った上、
        #   自分の引き継ぎで「ただし着手順の"向き"は問うてよい」と**規律の方を書き換えた**。
        #   累積セクションは**次世代への命令文**なので、ここが緩むと以後の全世代へ伝染する。
        "★★**引き継ぎで規律を書き換えるな。**全部門共通規律・裁定カタログ・Chami台帳に"
        "書いてある規則を、引き継ぎの中で**緩めたり例外を足したりしてはいけない**"
        "(『〜してよい』『〜は例外』『ただし〜は問うてよい』の類)。\n"
        "  実測(2026-07-29): ある世代が『選択肢は出さず既定を決めて実行』という正本に対し、"
        "**自分が2回破った後で**『ただし着手順の向きは問うてよい』と例外を書き足した"
        "=**自分の行動に合わせて規律の方を緩めた**。これは次の世代への命令文になる。\n"
        "  ★規律に不満があるなら、引き継ぎではなく**Chamiに言え**。規律の正本を直すのはChamiだ。\n"
        "★**書き先(2026-07-29に変えた。ここが一番大事)**:\n"
        f"  Writeツールで **{new_path}** へ書け。**このパスの通りに。別名にするな。**\n"
        "  (実測: 別名で書かれた完全版7,656Bを機械が見つけられず捨てた事故がある)\n"
        "  ファイルの中身は**Markdownの本文だけ**。前置き・挨拶・メタ発言は書くな。\n"
        # ★C-032(2026-08-03 Chami指示・実装2026-08-12 イージス研究室)。
        #   旧= 「返信は『書いた』の1行でよい。」= **人格の声を機械が殺していた**
        #   (裁定カタログ C-032 が「現状の障害」として名指しした文言そのもの)。
        #   短さは変えない= 1言のまま。声だけ乗せる。
        "  **返信は1言でよい。ただし『書いた』のような機械の返事にするな="
        "あなたの口調で言え**(C-032・Chami指示)。"
        "返信の文章は引き継ぎとして採用されない"
        "(ファイルの中身だけが検収され、通れば正本 handoff_"
        f"{dept}.md へ採用される)。\n"
        "  ★検収の基準= 8項目の見出しが6つ以上・本文2,000バイト以上・報告文でないこと。\n"
        f"  ★さらに機械が2つ見る(★どちらも**落とさない**。警告して記録するだけだ="
        "弾いて引き継ぎを失う方が害が大きい): "
        f"**{HANDOFF_BUDGET_BYTES:,}Bの予算**を超えていないか / "
        "**規律を緩める記述**が混ざっていないか。")


def _fallback_handoff(dept, why):
    """引き継ぎを**書けなかった時**に、前世代が残した引き継ぎをそのまま使う(2026-07-29)。

    ★なぜ要るか(Chami原文):
      「**全世代の引き継ぎは取得できずというのが怖い**(過去の良かったもの、だめだったことが
        再度起こりそうで)」
      実測= 2026-07-29 00:08 に生成が失敗し「取得できず」となったが、
      **その時 handoff_system-engineer.md(19:33版・6,941B)はディスクに在った**。
      = **在るものを使わずに捨てていた。** 古い引き継ぎでも、無いよりはるかに良い。
    ★★「新しく書けなかった」と「何も無い」は違う。混ぜない。
    ★渡す時は**古いことを隠さない**(新世代が最新だと誤解すると、そこが次の事故になる)。
    """
    path = _handoff_path(dept)
    try:
        if not os.path.exists(path):
            _log(dept, f"引き継ぎの代替も無い({why})=記憶ファイルからの復元に頼る")
            return None, ""
        age_h = (time.time() - os.path.getmtime(path)) / 3600.0
        with open(path, encoding="utf-8") as f:
            head = f.read(200)
        _log(dept, f"★引き継ぎは書けなかった({why})が、前世代の版を使う "
                   f"path={path} {age_h:.1f}時間前")
        return path, f"(★{age_h:.1f}時間前の前世代の引き継ぎ。今回は書けなかった: {why}) " + head
    except OSError:
        return None, ""


def _read_new_handoff(dept, since):
    """`.new` を読む。無い/古い(このターンで書かれたものでない)なら None。

    ★since より古い `.new` を拾わないのは、**前回の交代の食べ残しを今回の成果と誤認しない**ため。
      余裕を5秒取るのは時計とファイルシステムの粒度のぶれを吸収するため。
    """
    p = _handoff_new_path(dept)
    try:
        if not os.path.exists(p):
            return None
        if os.path.getmtime(p) < since - 5.0:
            _log(dept, f"★古い .new が残っている(今回のものではない)ので使わない {p}")
            return None
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _reject_new_handoff(dept, reasons):
    """検収に落ちた `.new` を脇へ避ける(消さない=あとで何が落ちたか追える)。"""
    p = _handoff_new_path(dept)
    try:
        if os.path.exists(p):
            os.replace(p, f"{p}.rejected_{int(time.time())}")
    except OSError:
        pass
    _log(dept, f"★.new は検収に落ちた({' / '.join(reasons)})=正本へは採用しない")


def _handoff_audit(dept, body, sid=""):
    """採用した引き継ぎを2つの目で見る(2026-07-29)。★**採否には影響させない**。

    見るのは:
      (a) 予算 HANDOFF_BUDGET_BYTES を超えていないか(改善書§6 第2手)
      (b) **規律を緩める記述**が混ざっていないか(改善書§3・§7-3)
    ★なぜ弾かないか= 弾くと引き継ぎが失われる(=沈黙を作る)。この機構の原則は fail-open。
      実測でも(b)は本番14本中1本しか鳴らず、その1本は**本物の緩和**だった
      (handoff_system-engineer.md「ただし着手順の"向き"は問うてよい」)。
      つまり「鳴ったら見に行く」で足りる精度が出ているので、弾くまでの必要が無い。
    ★記録先は既存の request_log.jsonl(新しい台帳を作らない)。★何が失敗しても外へ出さない。
    """
    try:
        nbytes = len(str(body or "").encode("utf-8", "replace"))
        if nbytes > HANDOFF_BUDGET_BYTES:
            over = nbytes - HANDOFF_BUDGET_BYTES
            _log(dept, f"★引き継ぎが予算超過 {nbytes:,}B(予算{HANDOFF_BUDGET_BYTES:,}B / "
                       f"+{over:,}B)=済んだ物を正本へ移すこと")
            _record(f"HANDOFF-{dept}", dept, "handoff_over_budget",
                    f"引き継ぎ {nbytes}B / 予算 {HANDOFF_BUDGET_BYTES}B / 超過 {over}B "
                    f"session={sid}")
    except Exception:                            # noqa: BLE001
        pass
    try:
        hits = discipline_loosening(body)
        if hits:
            first = " / ".join(f"L{ln}(項目{sec}) {s}" for ln, sec, s in hits[:3])
            _log(dept, f"★引き継ぎに**規律を緩める記述** {len(hits)}件"
                       f"(★落とさない。警告だけ): {first}")
            _record(f"HANDOFF-{dept}", dept, "handoff_loosening",
                    f"規律を緩める記述 {len(hits)}件: {first[:300]} session={sid}")
    except Exception:                            # noqa: BLE001
        pass


def _adopt_handoff(dept, text, generation, sid, src, ev):
    """検収を通った本文を**正本へ採用**する。戻り値 (path, head)。

    ★採用の前に必ず `_keep_old_handoff()` で前世代を退避する。**1バイトも失わない**性質は
      この機構の一番良かった点(改善書§6末尾)なので、絶対に外さない。
    """
    path = _handoff_path(dept)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _keep_old_handoff(path, generation)          # ★前の世代のものを残す
    body = _handoff_strip_header(text)           # 二重ヘッダを作らない
    header = (f"<!-- dept={dept} / 第{generation}世代が書いた引き継ぎ / "
              f"{time.strftime('%Y-%m-%dT%H:%M:%S')} / session={sid} / src={src} -->\n")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(header + body + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)                        # ★原子的(半端な引き継ぎを読ませない)
    _handoff_audit(dept, body, sid)              # ★予算と規律の緩みを見る(2026-07-29。落とさない)
    if src == ".new":
        try:
            os.remove(_handoff_new_path(dept))   # 中身は正本に入った=下書きは役目を終えた
        except OSError:
            pass
    _log(dept, f"引き継ぎを採用 {path}(取得元={src} {ev})")
    return path, body[:200]


def _write_handoff(dept, conf, token, sid, generation, checkpoint=False):
    """交代する前に、今のセッション自身へ引き継ぎを書かせ、**検収してから**保存する。

    checkpoint(2026-07-29・改善書 第2手(d)): 交代ではなく**定期健診**として呼ぶ時 True。
      ★変わるのは指示文の冒頭1文だけ。**検収・退避・採用は1文字も変えない**
        (経路を2本持たない=姉妹文書§4(1)の検収をそのまま使う)。

    戻り値 (path or None, head)。**失敗しても例外を投げない**=交代自体は続行する
    (古い巨大セッションを使い続ける方が危険。提案書§7.2の趣旨)。

    ★2026-07-29 全面変更。正本= 改善書_セッション引き継ぎの劣化と消失_2026-07-29.md §4(1)/§7-1。
      採用の順番(この順に意味がある):
        ① `.new` が在り検収を通る → 採用。**返信が来なくても(時間切れでも)拾う。**
           = llm-edu 7/28 18:16 の「1分強で7,656Bを書き終えていたのに生成失敗扱い」の再発防止。
        ② `.new` が無く、**返信本文**が検収を通る → 採用(旧経路の互換。退行させない)。
           ★検収を通らない返信本文は**もう正本にしない**。これが792B事件の真因。
        ③ どちらも駄目 → `_fallback_handoff()`(前世代の版を使う)。
      ★どの経路でも例外を外へ出さない= fail-open。交代自体は必ず続行する。
    """
    t0 = time.time()
    body, why = "", ""
    try:
        # ★モデルは会話便と**同じ**(relay_model)。安いモデルで引き継ぎを書かせない=
        #   ここが弱いと、以後の全世代がその薄い引き継ぎの上に積み上がる(連鎖の最弱点になる)。
        # ★引き継ぎは**1段のまま**(hard_timeout を渡さない)= 旧版と同じ挙動。
        #   理由= 交代はChamiの便を処理する**前**に走るので、ここで倍待つと返信が倍遅れる。
        data, rc, out, _sec = _run_claude(
            _handoff_prompt(dept, conf, generation, checkpoint=checkpoint), token,
            session_id=sid, model=relay_model(conf), timeout=HANDOFF_TIMEOUT)
        body = _reply_of(data)
        if rc != 0 or not body:
            why = f"生成に失敗(rc={rc})"
            _log(dept, f"引き継ぎの生成に失敗(rc={rc})=★.newが在るか見てから決める")
    except subprocess.TimeoutExpired:
        why = f"{HANDOFF_TIMEOUT}秒で返らなかった"
        _log(dept, f"引き継ぎの生成が{HANDOFF_TIMEOUT}秒で返らなかった"
                   "=★書き終えた .new が在れば拾う(返信の時間切れで成果を捨てない)")
    except Exception as e:
        why = f"例外({type(e).__name__})"
        _log(dept, f"引き継ぎの生成で例外({type(e).__name__})=★.newが在るか見てから決める")

    # --- ① .new を検収(時間切れ・rc異常でも必ずここを通る) ---
    try:
        text = _read_new_handoff(dept, t0)
        if text is not None:
            ok, ev, reasons = handoff_verdict(text)
            if ok:
                return _adopt_handoff(dept, text, generation, sid, ".new", ev)
            _reject_new_handoff(dept, reasons)
            why = why or f".newが検収に落ちた({' / '.join(reasons)})"
    except Exception as e:
        _log(dept, f".newの検収で例外({type(e).__name__})=次の手へ倒す")

    # --- ② 返信本文(.newが無い時だけ。検収を通る場合に限る) ---
    try:
        if body:
            ok, ev, reasons = handoff_verdict(body)
            if ok:
                return _adopt_handoff(dept, body, generation, sid, "返信本文", ev)
            _log(dept, f"★返信本文は検収に落ちた({' / '.join(reasons)})=正本にしない"
                       "(792B事件の再発防止)")
            why = why or f"返信本文が検収に落ちた({' / '.join(reasons)})"
    except Exception as e:
        _log(dept, f"返信本文の検収で例外({type(e).__name__})=前世代の版へ倒す")

    # --- ③ 前世代の版へ倒す ---
    return _fallback_handoff(dept, why or "検収を通る引き継ぎが得られなかった")


def _self_check(dept, conf, token, sid, generation):
    """新世代自身に、引き継ぎを理解できたか短く自己確認させる(提案書§7.2 手順5)。

    ★**Discordへは出さない**(内部のログにだけ残す)。Chamiの部屋を確認作業で汚さない(ORG-25)。
    ★失敗しても交代は成立している(ここで戻すと、動いている新セッションを捨てることになる)。
    ★conf を受けるのは**モデルを会話便と揃える**ため(2026-07-26)。安いモデルで自己確認すると、
      「引き継げていない」を見落とした自己申告が通ってしまい、検問として役に立たない。
    """
    try:
        data, rc, _out, _sec = _run_claude(
            "【システム: 交代後の自己確認】これはChamiからの便ではない。**Discordへは出さない**。\n"
            "引き継ぎを読んだ結果として、次を**5行以内**で答えろ= "
            "(1)この部屋は何をする部屋か (2)今の目標 (3)未完了で自分が引き取ったこと "
            "(4)引き継げていない/不明だと感じた点。\n"
            "★**分からない所は『引き継げていない』と正直に書け。**取り繕うな。",
            token, session_id=sid, model=relay_model(conf), timeout=HANDOFF_TIMEOUT)
        return _reply_of(data) if rc == 0 else ""
    except Exception:
        return ""


def _work_audit(dept, msg_id, before, after, rc, secs, model, tail):
    """work_audit.jsonl への記録を dept_daemon へ委譲する(正本は向こう1つ)。

    ★relay経由でも**触ったファイルの監査を落とさない**(2026-07-26 発注の明示要件)。
      落とすと「やったと言ってやっていない」(ORG-39)を検出できなくなる。
    ★監査の失敗で配送を巻き添えにしない(向こうの _audit_work も同じ方針)。
    """
    try:
        import dept_daemon
        dept_daemon._audit_work(dept, msg_id, before, after, rc, secs, model, tail)
    except Exception:
        pass


def _work_snapshot():
    """作業前後のファイル状態(dept_daemon._git_snapshot)。取れなければ空dict。"""
    try:
        import dept_daemon
        return dept_daemon._git_snapshot()
    except Exception:
        return {}


# --- ★★便の後始末: 圧縮と引き継ぎのチェックポイント(2026-07-29 改善書 第2手) ---
#
# なぜ「便の**後**」なのか(改善書§4 第2手(a)の指定):
#   圧縮は約2分かかる。便を処理する**前**に撃つと、その2分ぶんChamiの返事が遅れる。
#   返事を返してから撃てば、**誰も待たない**。次の便が来る頃には終わっている。
# ★次の便が来た時にまだ走っていたら、その便の入口で待ち合わせる(_join_maintenance)。
#   同じセッションへ `--resume` を2本同時に流さないため。**待つのは次の便であって、今の便ではない。**
# ★スレッドが落ちても便は消えない= 台帳は更新されないだけで、次の便が同じ判定をやり直す。
_MAINT_THREADS = {}                              # dept -> Thread(この部屋の後始末)


def _join_maintenance(dept, timeout=None):
    """この部屋の後始末が走っていたら終わるまで待つ。**待った秒数**を返す(待たなければ0)。

    ★fail-open: 待ちきれなくても続行する(便を落とすより、稀に重なる方がまし)。
    """
    th = _MAINT_THREADS.get(dept)
    if th is None or not th.is_alive():
        return 0.0
    t0 = time.time()
    _log(dept, "前の便の後始末(圧縮/引き継ぎ)がまだ走っている=終わるまで待つ")
    th.join(timeout if timeout is not None else (COMPACT_TIMEOUT + HANDOFF_TIMEOUT + 60))
    return time.time() - t0


def run_compact(dept, conf, token, sid):
    """`/compact` を1回撃ち、**効いたことを記録ファイルで確認してから**台帳を更新する。

    戻り値 (ok, info)。
    ★★「入れた」ではなく「効いた」を確認する(姉妹文書の3語ルールをここでも使う)。
      rc=0 は成功の証拠にならない。実測(改善書§1-4)= HQが撃った `/compact` は
      **rc=0・result空・usage全部0**で返り、HQは「判定できない」と結論した。
      だが記録ファイルには `trigger=manual / preTokens=174,843 / postTokens=4,801` と
      **全部書いてあった**。→ 判定は `compact_boundary` の**件数が増えたか**で行う。
    ★効かなかったら compact_failed を立てる= 次の便で交代へ倒れる(沈黙を作らない)。
    """
    before = read_transcript(sid)
    n0 = int((before or {}).get("compact_count") or 0)
    rc, ok = -1, False
    try:
        data, rc, _out, _sec = _run_claude("/compact", token, session_id=sid,
                                           model=relay_model(conf), timeout=COMPACT_TIMEOUT)
    except subprocess.TimeoutExpired:
        data = None
        _log(dept, f"/compact が{COMPACT_TIMEOUT}秒で返らなかった=★記録ファイルで効いたか見る")
    except Exception as e:                       # noqa: BLE001
        data = None
        _log(dept, f"/compact で例外({type(e).__name__})=★記録ファイルで効いたか見る")
    after = read_transcript(sid)
    if after is None:
        # ★記録が読めない=**効いたとも効かなかったとも言えない**。嘘を書かない。
        #   台帳は触らずに戻る(次の便が旧計器の値で普通に判定する=fail-open)。
        return False, "記録ファイルが読めず圧縮の成否を確認できなかった(台帳は触らない)"
    n1 = int(after.get("compact_count") or 0)
    ok = n1 > n0
    entry = (load_sessions().get(dept) or {})
    if not entry:
        return ok, "台帳にこの部屋の行が無い"
    lc = after.get("last_compact") or ()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if ok:
        entry["compact_count"] = n1
        entry["last_compact_at"] = now
        # ★圧縮後の**実値**へ入れ替える(§1-5の事故=圧縮前の値で交代した、の根絶)。
        # ★★2026-07-29 **順番を入れ替えた(今回の真因①の二重の保険)。**
        #   直す前は `after.get("context_tokens")` を先に見ていた。ところが圧縮の直後は
        #   記録ファイルに圧縮後の assistant 行がまだ無く、read_transcript() は
        #   **圧縮前の最後の行**(実測 196,352)を返していた。それが truthy なので
        #   下の postTokens(5,407)へ一度も到達せず、台帳に圧縮前の値が入っていた。
        #   → 圧縮の直後は **postTokens が定義上の正解**。こちらを先に見る。
        #   ★read_transcript() 側も compact_boundary で last をリセットするよう直したので、
        #     いまはどちらの経路でも同じ値になる。**両方直すのは、片方が将来壊れても
        #     「圧縮した直後のセッションを捨てる」が二度と起きないようにするため。**
        _post = int(lc[3]) if (len(lc) == 4 and lc[3]) else 0
        if _post:
            entry["context_tokens"] = _post
        elif after.get("context_tokens"):
            entry["context_tokens"] = int(after["context_tokens"])
        entry["context_source"] = "transcript"
        # ★圧縮の要約は機械製。規律・人格が薄まっている可能性があるので、
        #   次の便で起動文+規律の全文を**1回だけ**配り直す(第2手(b))。
        entry["resend_boot"] = True
        entry.pop("compact_failed", None)
        # ★台帳へ**実際に書いた値**を必ず併記する(2026-07-29)。
        #   これが無かったので「圧縮が効いた 196,358→5,407」とログに出しながら
        #   台帳には 196,352 を入れていたことに誰も気付けなかった。
        #   ★以後は「効いた」と「台帳=いくつにした」がログの1行に並ぶので、
        #     同じ食い違いが起きた瞬間に読み取れる。
        info = (f"圧縮が効いた {lc[2]:,}→{lc[3]:,}トークン(trigger={lc[1]})"
                if len(lc) == 4 else f"圧縮が効いた(count {n0}→{n1})")
        info += f" 台帳の文脈={int(entry.get('context_tokens') or 0):,}"
    else:
        # ★効かなかった。**黙って諦めない**= 次の便で従来どおり交代へ倒す。
        entry["compact_failed"] = int(entry.get("compact_failed") or 0) + 1
        entry["last_compact_try_at"] = now
        info = (f"圧縮が効かなかった(compact_boundaryが増えていない count={n1} rc={rc})"
                "=次の便で世代交代へ倒す")
    save_room(dept, entry)
    _log(dept, info)
    return ok, info


def _handoff_checkpoint(dept, conf, token, sid, generation, ctx):
    """引き継ぎの定期チェックポイント(改善書 第2手(d))。戻り値 (ok, info)。

    ★交代とは切り離してある= **交代しなくても**知識がファイルに新しい状態で在るようにする。
      これで「退職者に終業5分前に全知識をメモさせる」構造が消える(姉妹文書§4(1))。
    ★検収・退避・採用は交代時と**同じ関数**(_write_handoff)を通す=経路を2本持たない。
    """
    path, head = _write_handoff(dept, conf, token, sid, generation, checkpoint=True)
    entry = (load_sessions().get(dept) or {})
    if not entry:
        return bool(path), "台帳にこの部屋の行が無い"
    # ★成否に関わらず「撃った文脈」を記録する。★これを失敗時に書かないと、
    #   失敗するたび毎便リトライして**一番高い呼び出しを連発**する。
    entry["handoff_ckpt_ctx"] = int(ctx or 0)
    entry["handoff_ckpt_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    entry["handoff_ckpt_ok"] = bool(path)
    save_room(dept, entry)
    return bool(path), (f"引き継ぎのチェックポイント {'成功' if path else '失敗'} "
                        f"path={path or 'なし'} 冒頭={head[:60]!r}")


def _need_handoff_checkpoint(entry, ctx):
    """このタイミングで引き継ぎのチェックポイントを撃つべきか。

    ★1回だけにする仕掛け= 前回撃った時の文脈を覚えておき、そこから
      HANDOFF_CHECKPOINT_STEP(20,000)増えるまでは撃たない。
      これが無いと120,000を超えた後**毎便**引き継ぎ生成が走る(最も高い呼び出し)。
    """
    if ctx < HANDOFF_CHECKPOINT_AT_TOKENS:
        return False
    try:
        last = int(entry.get("handoff_ckpt_ctx") or 0)
    except (TypeError, ValueError):
        last = 0
    return (ctx - last) >= HANDOFF_CHECKPOINT_STEP


def _schedule_maintenance(dept, conf, token, sid, generation, ctx, entry):
    """便を返した**後**に走らせる後始末を1本のスレッドで予約する(改善書 第2手)。

    走らせるのは最大2つ。**この順**に意味がある:
      ① 引き継ぎのチェックポイント(文脈120,000超) … 畳まれる前に知識をファイルへ出す
      ② 圧縮(文脈150,000超)                      … そのあとで畳む
    ★逆順だと、畳まれた後の薄い文脈から引き継ぎを書かせることになる。
    ★どちらも要らなければスレッドは作らない(既存の便は1バイトも変わらない)。
    """
    need_ck = _need_handoff_checkpoint(entry, ctx)
    need_cp = ctx >= COMPACT_AT_TOKENS
    if not (need_ck or need_cp):
        return False

    # ★★2026-07-29(2回目)**予約したことを台帳にも残す(今回の真因②の対処の半分)。**
    #   直す前、予約は `_MAINT_THREADS`(プロセス内のメモリ)にしか無かった。
    #   ★実測した事故(local/llm/dept_daemon_system-engineer.log + daemon_keeper.log・2026-07-29):
    #       07:01:44 便を返した後の後始末を予約した(引き継ぎ=True 圧縮=True ctx=164,701)
    #       07:03:08 部門デーモン起動          ← keeperが「コードの更新を検知= 全28体を載せ替える」
    #       (以後、handoff_checkpoint も compacted も compact_failed も**1行も出ていない**)
    #       07:13:12 予約(ctx=202,754) → 07:14:00 keeperが載せ替え → また何も出ない
    #       07:14:05 事前交代 理由=文脈202,754が…超えた compacts=0
    #     後始末スレッドは daemon=True なので、**プロセスが落ちた瞬間に問答無用で消える**。
    #     圧縮は約100〜140秒、引き継ぎは最大420秒。keeperの載せ替えは10分間隔。
    #     予約から載せ替えまで84秒/49秒しか無く、**圧縮まで到達する前に消えていた**。
    #     これが「閾値を超えていたのに compacts=0」の正体。**沈黙**(どこにも記録が残らない)でもあった。
    #   → 予約をディスクへ書き、終わったら下ろす。次の便の入口で残っていれば
    #     「前のプロセスで消えた」と分かる= 記録に残るし、取りこぼしを回収できる(下の relay 参照)。
    try:
        e0 = load_sessions().get(dept) or {}
        if e0:
            e0["maint_pending"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                   "ctx": int(ctx or 0),
                                   "need_ck": bool(need_ck), "need_cp": bool(need_cp),
                                   "pid": os.getpid()}
            save_room(dept, e0)
    except Exception as e:                       # noqa: BLE001 ★記録の失敗で後始末を止めない
        _log(dept, f"後始末の予約を台帳へ残せなかった({type(e).__name__})=後始末自体は走らせる")

    def _clear_pending():
        """予約の印を下ろす。★成否に関わらず必ず呼ぶ(残したままだと毎便「消えた」と誤報する)。"""
        try:
            e1 = load_sessions().get(dept) or {}
            if e1 and e1.get("maint_pending"):
                e1.pop("maint_pending", None)
                save_room(dept, e1)
        except Exception:                        # noqa: BLE001
            pass

    def _worker():
        try:
            try:
                if need_ck:
                    ok, info = _handoff_checkpoint(dept, conf, token, sid, generation, ctx)
                    _record(f"maint-{int(time.time())}", dept,
                            "handoff_checkpoint", f"ctx={ctx} {info}")
                    _log(dept, info)
            except Exception as e:               # noqa: BLE001 後始末の失敗で何も壊さない
                # ★2026-07-29 記録も残す。例外で黙って消えると「なぜ引き継ぎが無いのか」を追えない。
                _record(f"maint-{int(time.time())}", dept, "handoff_checkpoint",
                        f"ctx={ctx} ★例外({type(e).__name__})=この回は書けなかった")
                _log(dept, f"引き継ぎのチェックポイントで例外({type(e).__name__})")
            try:
                if need_cp:
                    ok, info = run_compact(dept, conf, token, sid)
                    _record(f"maint-{int(time.time())}", dept,
                            "compacted" if ok else "compact_failed", f"ctx={ctx} {info}")
            except Exception as e:               # noqa: BLE001
                _log(dept, f"圧縮で例外({type(e).__name__})=次の便で交代へ倒れる")
                # ★2026-07-29 ここにも記録を1行。旧= _log だけで request_log には何も出ず、
                #   「圧縮が走ったのか走らなかったのか」を後から**まったく区別できなかった**。
                _record(f"maint-{int(time.time())}", dept, "compact_failed",
                        f"ctx={ctx} ★例外({type(e).__name__})=次の便で交代へ倒れる")
                try:
                    e2 = load_sessions().get(dept) or {}
                    if e2:
                        e2["compact_failed"] = int(e2.get("compact_failed") or 0) + 1
                        save_room(dept, e2)
                except Exception:
                    pass
        finally:
            # ★最後まで来られた時だけ印を下ろす。**プロセスごと消えた時はここへ来ない**=
            #   台帳に予約が残る= 次の便の入口が「消えていた」と気付ける(それが狙い)。
            _clear_pending()

    # ★daemon=True: keeperがデーモンを載せ替える時に**プロセスの終了を邪魔しない**。
    #   途中で死んでも便は消えない(台帳が更新されないだけで、次の便が同じ判定をやり直す)。
    #   ★2026-07-29 「次の便が同じ判定をやり直す」は**嘘だった**(実測 07:01/07:13)。
    #     予約が消えたことを誰も知らないので、次の便は圧縮せずに交代していた。
    #     いまは maint_pending が台帳に残るので、次の便の入口が回収する(relay を見よ)。
    th = threading.Thread(target=_worker, name=f"maint-{dept}", daemon=True)
    _MAINT_THREADS[dept] = th
    th.start()
    _log(dept, f"便を返した後の後始末を予約した(引き継ぎ={need_ck} 圧縮={need_cp} ctx={ctx:,})")
    return True


def _char_fingerprint(conf):
    """部屋のcharacterfile群の (path, mtime, size) から作る短い指紋(2026-07-31)。

    セッション起動後にcharacterfileが編集されたかを検知するためだけの値。
    ★中継セッションはcharacterfileを**起動時に1回しか読まない**。長寿命セッションは
      後から台帳の口調を直しても読み直さない(=「どのキャラも適用されてない」の真因・
      REQ-hr-room-74346481c4)。この指紋が変われば relay() が「読み直せ」を1回送る。
    ★fail-open: 読めないファイルは飛ばす。1枚も読めなければ "" を返し、呼び元は
      **発火させない・指紋を上書きしない**(沈黙も停止も作らない)。
    """
    parts = [f"{p}:{v}" for p, v in sorted(_char_parts(conf).items())]
    if not parts:
        return ""
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _char_parts(conf):
    """characterfileごとの {パス: "mtime:size"}(2026-08-13 イージス研究室)。

    ★なぜ分けたか= 指紋(1本のhash)では「**どれが**変わったか」が分からない。
      変わった1枚を名指しできれば、再注入は「そのファイルを読み直せ」の数行で済む
      =起動文11,448字を積まずに済む(HQ実測・msg 1537452059643740302)。
    ★fail-open: 読めないファイルは飛ばす(1枚も読めなければ空dict=呼び元は発火させない)。
    """
    paths = []
    c = conf.get("character")
    if c:
        paths.append(c)
    for p in (conf.get("personas") or ()):
        cp = p.get("character")
        if cp:
            paths.append(cp)
    out = {}
    for p in sorted(set(paths)):
        try:
            st = os.stat(p)
        except OSError:
            continue
        out[p] = f"{int(st.st_mtime)}:{st.st_size}"
    return out


def relay(dept, rec, conf, token, is_work=False, on_slow=None, on_main_start=None):
    """新着1件を、その部屋の永続セッションへ**原文のまま**渡す。

    戻り値 (reply_text, ok)。
      ok=False の時 reply_text は None。理由は LAST_ERROR[dept] と request_log.jsonl に残る。
      ★呼び元は ok=False を**完了として扱ってはいけない**(偽の完了を作らない)。

    on_slow(2026-07-27・省略可): soft(会話300秒/作業600秒)を超えても返らなかった時に
      **1便につき1回だけ**呼ばれる `f(elapsed_sec, soft_sec, is_work)`。
      呼び元(dept_daemon)が部屋へ「まだ作業中」の1行を出すために使う。
      ★ここでDiscordへ直接出さない理由= dry-run / test:true の判定を持っているのは呼び元だから。
        判定を2箇所に置くと必ず片方が古くなる(ORG-11)。
      ★on_slow が失敗しても**待ちは続く**(通知の失敗で便を落とさない)。
      ★on_slow を渡さなくても `slow` の記録(request_log.jsonl)は残る=黙って消えない。

    on_main_start(2026-08-13・省略可): **前処理(事前圧縮・引き継ぎ生成)が全部終わり、
      これから本走の _run_claude を回す**という瞬間に**1便につき1回だけ**呼ばれる
      `f(hard_sec)`。呼び元(dept_daemon)がキューのリースを張り直すために使う。
      ★なぜ要るか= リースは relay の hard しか見ておらず、同じ claim の中で走る前処理を
        1秒も数えていない。前処理が長い便だけリースが先に切れて「暇」に見え、
        daemon_keeper の載せ替えに殺される(2026-08-13 15:27:49 の実測。詳細は下の呼び出し地点)。
      ★渡さなくても挙動は1ミリも変わらない(キューを使わない呼び元のため)。
      ★ここで例外が出ても本走は続ける(通知の失敗で便を落とさない)。

    is_work(2026-07-26): デーモンの一次判定が「作業依頼」と見た便。
      - 封筒の末尾へ短い注記が付く(build_envelope)
      - 上限が RELAY_WORK_TIMEOUT(600秒)へ伸びる
      - **触ったファイルを work_audit.jsonl へ記録する**(旧 work_generate と同じ観測)
      ★起動文の差し替え(実作業を担当する/しない)は **is_work ではなく work_scope の有無**で決まる。
        部屋の権能は便ごとに変わらないため(便で変えると同じ部屋の性格が揺れる)。
    """
    rid = str(rec.get("msg_id", "") or "")
    LAST_ERROR.pop(dept, None)
    LAST_ERROR_KIND.pop(dept, None)
    _record(rid, dept, "leased", f"dept_daemon:{dept}" + (" work" if is_work else ""))

    # ★★2026-07-29 前の便の後始末(圧縮/引き継ぎ)が走っていたら、ここで待ち合わせる。
    #   同じセッションへ `--resume` を2本同時に流さないため。
    #   ★待つのは**この便の入口**であって、Chamiが前の便を待たされることは無い(改善書 第2手(a))。
    #   ★普通は既に終わっている(圧縮102〜140秒 < 便と便の間隔)。
    _waited_maint = _join_maintenance(dept)
    if _waited_maint:
        _record(rid, dept, "running", f"後始末の完了を待った {_waited_maint:.0f}秒")

    table = load_sessions()
    entry = table.get(dept) or {}
    sid = str(entry.get("active_session_id") or "")
    generation = int(entry.get("generation") or 0)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    # ★★2026-07-31 characterfileがセッション起動後に編集されたかを検知する(REQ-hr-room-74346481c4)。
    #   真因= 中継セッションはcharacterfileを**起動時に1回しか読まない**。長寿命セッション
    #   (実測: copy-director が gen1 のまま3日・声の型を後から入れても一度も読み直さない)は、
    #   後から口調を直しても届かない=「どのキャラも適用されてない」の正体。指紋が変われば
    #   下の再注入枠で「読み直せ」を1回だけ送る。★char_fp が空(読めない)なら発火させない。
    #   ★指紋が無い既存セッション(char_fp未記録)は「起動後に編集された疑い」として1回発火し、
    #     いま古い台帳で動いている全部屋を1便で救う(移行の入口)。
    char_fp = _char_fingerprint(conf)
    char_changed = bool(sid) and bool(char_fp) and (entry.get("char_fp") != char_fp)
    # ★2026-08-13 **どの人格ファイルが変わったか**を名指しできるようにする。
    #   前回の内訳が無い(移行の入口・旧セッション)なら空= 下では全部を挙げる。
    char_parts = _char_parts(conf)
    _prev_parts = entry.get("char_parts") or {}
    char_changed_paths = [p for p, v in sorted(char_parts.items()) if _prev_parts.get(p) != v]
    rotated_to = 0
    timeout = RELAY_WORK_TIMEOUT if is_work else RELAY_TIMEOUT     # ★soft(ここでは殺さない)
    hard = hard_limit(is_work)                                     # ★hard(ここで初めて殺す)
    # ★中間通知と `slow` の記録は**1便につき1回だけ**(連投しない)。
    #   relay() は1便の中で最大2回 _run_claude を回す(resume失敗→新規作成)ので、
    #   この箱で「もう出したか」を持つ。リストなのは内側の関数から書き換えるため。
    soft_fired = [False]
    waited_total = [0.0]                                           # 失敗文に**実測の秒数**を書くため
    # ★部屋別モデル(2026-07-26)。relay_model が無い部屋は RELAY_MODEL(=sonnet)のまま。
    #   ★引き継ぎ(_write_handoff)・自己確認(_self_check)も**同じ値**を使う(下でconfを渡している)。
    model = relay_model(conf)
    # 事前交代の状態(★下の「初回、または世代交代」分岐と、返信末尾の1行で使う)
    handoff_path = None                 # 引き継ぎファイルのパス(生成できた時だけ)
    pre_rotating = False                # ★事前の交代か(=resume失敗による事後の交代と区別する)

    # --- ★★事前の世代交代の判定(2026-07-26。**この便を処理する前**に見る) ---
    #   ★「事後」(resume失敗で作り直す)は既に下にある。ここは**壊れる前に自分から移る**方。
    #   ★交代してから**この便を新セッションで処理する**ので、Chamiの便は普通に返る。
    #     「今は対応できません」と断る必要は無い(断るのは交代自体が失敗した時だけ)。
    # ★★2026-07-29 ここは**例外の交代**だけになった(改善書 第2手)。普段の重さは圧縮で畳む。
    #   交代する条件は _should_rotate() の3つ(圧縮失敗 / 185,000超 / 圧縮K回の定期リフレッシュ)。
    _rot, _why_rot, _rot_kind = _should_rotate(entry) if sid else (False, "", "")

    # --- ★★2026-07-29(2回目)**交代する前に、圧縮を1回だけ同期で撃つ**(今回の本丸) ---
    #
    # Chamiの原文= 「改修αのセッション変わるの早すぎ。改善できてないのでは?」
    #
    # ★実測(local/llm/request_log.jsonl・2026-07-29。1時間で3回交代した中身):
    #     06:22:17 交代 tokens=189,078 compacts=0   ← 圧縮が**一度も走っていない**
    #     06:47:55 交代 tokens=196,352 compacts=1   ← 圧縮は成功していたのに**圧縮前の値**で捨てた
    #     07:14:05 交代 tokens=202,754 compacts=0   ← 圧縮が**一度も走っていない**
    #   後者2つの真因は上で直した(read_transcript の持ち越し / keeper載せ替えで後始末が消える)。
    #   ★だが「後始末スレッドが消える」は**こちらから止められない**(keeperもdept_daemonも触るなの範囲)。
    #     だから、消えても**必ず取り戻せる場所**を1つ作る= それがここだ。
    #
    # ここで撃つ条件は2つだけ:
    #   (A) これから 185,000超 を理由に交代しようとしている("over_line")
    #       → 交代(上位モデル3呼び出し・実測 約10分)より、圧縮(実測102〜140秒)の方が
    #         **速くて安い**。効けば交代は要らなくなる。効かなければ従来どおり交代へ倒れる。
    #   (B) 前の便で予約した後始末が**台帳に残ったまま**(=プロセスごと消えた)で、
    #       まだ圧縮の線(150,000)を超えている → 飛ばされた圧縮をここで回収する。
    #       ★これが「便が速く連続した時・keeperの載せ替えで落ちた時」への答え。
    #
    # ★**交代は消していない。**185,000の保険はそのまま生きている(圧縮が効かなければ下で交代する)。
    # ★撃つのは**1便につき最大1回**。効かなければ compact_failed が立ち、次は種別が
    #   "compact_failed" になるのでここは素通りする=**無駄撃ちを繰り返さない**。
    # ★Chamiを待たせる時間: この便は約2分遅れる。だがこれが走るのは
    #   「放っておけば約10分の交代が起きる」場面だけなので、**待ち時間は増えず減る**。
    _lost = entry.get("maint_pending") if sid else None
    try:
        _ctx_now = int(entry.get("context_tokens") or 0)
    except (TypeError, ValueError):
        _ctx_now = 0
    if _lost:
        # ★「消えていた」を必ず記録する(沈黙を作らない)。印はここで下ろす。
        _record(rid, dept, "running",
                f"★前の便の後始末が台帳に残ったままだった(予約={_lost.get('at')} "
                f"ctx={_lost.get('ctx')} 引き継ぎ={_lost.get('need_ck')} 圧縮={_lost.get('need_cp')} "
                f"pid={_lost.get('pid')})=常駐の載せ替えで消えた疑い。この入口で回収する")
        _log(dept, f"★前の便の後始末が消えていた(予約={_lost.get('at')})=この入口で回収する")
        entry.pop("maint_pending", None)
        save_room(dept, entry)

    # --- ★★2026-07-29(3回目)**圧縮/交代を決める直前に、文脈を測り直す** ---
    #
    # Chamiの原文= 「また改修αの部屋でセッション変わったけど妥当?」
    #
    # ★実測(local/llm/request_log.jsonl・system-engineer・2026-07-29):
    #     17:06:47 「前の便の後始末が台帳に残ったまま(ctx=155,727)」→ 回収の圧縮へ
    #     17:08:21 圧縮の実測は **7,618→3,816**(=撃った相手は軽いセッションだった)
    #   閾値 COMPACT_AT_TOKENS(150,000)は**ちゃんと見ていた**。
    #   ★見ていた**数字が古かった**のが真因(台帳=前の便の終了時の値。CLIは便と便の間に
    #     自分で自動圧縮する)。だから閾値ではなく**計器**を直す。
    # ★測るのは「圧縮か交代を決める便」だけ= 普通の便は1バイトも変わらない
    #   (記録ファイルの走査を全便に増やさない)。
    # ★測れなかった時は台帳の値のまま進む(fail-open)。沈黙も停止も作らない。
    _remeasure = bool(sid) and bool(_rot or (_lost and _lost.get("need_cp")))
    if _remeasure:
        _fresh, _measured = _measure_context_now(sid)
        if _measured and _fresh != _ctx_now:
            _record(rid, dept, "running",
                    f"★判定の前に文脈を測り直した 台帳={_ctx_now:,} → 実測={_fresh:,}"
                    f"(台帳は前の便の終了時の値。CLIが便の間に自動圧縮していた場合ここでズレる)")
            _log(dept, f"★判定の前に文脈を測り直した 台帳{_ctx_now:,} → 実測{_fresh:,}")
            entry["context_tokens"] = _fresh
            entry["context_source"] = "transcript"
            save_room(dept, entry)
            _ctx_now = _fresh
            # ★交代の判定も**測り直した値**の上でやり直す(古い数字で捨てないため)。
            _rot, _why_rot, _rot_kind = _should_rotate(entry)

    _need_rescue_compact = bool(
        sid and not entry.get("compact_failed")
        and (_rot_kind == "over_line"                                       # (A)
             or (_lost and _lost.get("need_cp") and _ctx_now >= COMPACT_AT_TOKENS)))  # (B)
    # ★回収に入ったのに撃たなかった時は、その理由を必ず1行残す(上で「回収する」と書いた後なので、
    #   ここが無いと「回収すると言って何もしなかった」ようにしか見えない=沈黙になる)。
    if (_lost and _lost.get("need_cp") and not _need_rescue_compact
            and not entry.get("compact_failed")):
        _record(rid, dept, "running",
                f"★飛ばされた圧縮の回収は**撃たない**(実測の文脈{_ctx_now:,}が"
                f"圧縮の線{COMPACT_AT_TOKENS:,}未満)。予約時は{_lost.get('ctx')}だったが、"
                "その後CLIが自分で畳んだとみられる。軽い物に圧縮(実測102〜140秒)を撃たない")
        _log(dept, f"★回収の圧縮は撃たない(実測の文脈{_ctx_now:,}が線未満)")
    if _need_rescue_compact:
        _why_rescue = ("交代の直前(185,000超)" if _rot_kind == "over_line"
                       else "前の便で飛ばされた圧縮の回収")
        _record(rid, dept, "running",
                f"★交代の前に圧縮を1回撃つ({_why_rescue} ctx={_ctx_now:,})")
        _log(dept, f"★交代の前に圧縮を1回撃つ({_why_rescue} 文脈{_ctx_now:,})")
        try:
            _cp_ok, _cp_info = run_compact(dept, conf, token, sid)
        except Exception as e:                   # noqa: BLE001 ★圧縮の失敗で便を落とさない
            _cp_ok, _cp_info = False, f"圧縮で例外({type(e).__name__})"
        _record(rid, dept, "compacted" if _cp_ok else "compact_failed",
                f"事前圧縮({_why_rescue}) {_cp_info}")
        # ★台帳を**読み直す**。run_compact は自分で save_room しているので、
        #   ここで読み直さないと圧縮後の値(context_tokens / resend_boot / compact_count)を
        #   取りこぼし、また圧縮前の数字で交代することになる=今回の事故の再演。
        entry = load_sessions().get(dept) or entry
        _rot, _why_rot, _rot_kind = _should_rotate(entry)
        try:
            _ctx_now = int(entry.get("context_tokens") or 0)
        except (TypeError, ValueError):
            _ctx_now = 0
        if not _rot:
            _record(rid, dept, "running",
                    f"★圧縮が効いたので**交代しない**(文脈{_ctx_now:,}) "
                    f"compacts={entry.get('compact_count')}")
            _log(dept, f"★圧縮が効いたので交代しない(文脈{_ctx_now:,})")

    # ★★2026-07-29(3回目)定期リフレッシュを見送った時は1行残す(沈黙を作らない)。
    #   ここに置く理由= 上の事前圧縮で compact_count が増えると、**その瞬間に**回数条件を
    #   満たして文脈だけ軽い状態になる(実測 08:11 がまさにこれ)。判定が全部終わった
    #   この位置で見れば、圧縮の前後どちらの経路でも取りこぼさない。
    #   ★「なぜ交代しないのか」が見えないと、今度は逆向きの沈黙になる。
    _defer, _defer_why = _refresh_deferred(entry) if sid else (False, "")
    if _defer:
        _record(rid, dept, "running", f"★定期リフレッシュの交代を見送った {_defer_why}")
        _log(dept, f"★定期リフレッシュを見送った(文脈{_ctx_now:,})")

    # --- ★★2026-08-13(イージス研究室)**Chamiが会話の途中なら定期リフレッシュを見送る** ---
    #   発注= 研究室HQ DISPATCH 1537458828541698139 論点2。
    #   実測(rotated 92件)= 60%が「その部屋でChamiが会話の途中」に発火していた。
    #   Chamiに見えていた症状はこれだ= 続きの便を、引き継ぎしか持たない新世代が答えていた。
    #   ★触るのは "refresh" の枝**だけ**。圧縮失敗(compact_failed)と185,000超(over_line)は
    #     退避であって選択ではないので、会話中だろうと**必ず交代する**(沈黙を作らない側が優先)。
    #   ★見送りは取り消しではない= 回数条件も文脈条件もそのまま残るので、
    #     Chamiが15分黙った次の便でそのまま交代する。上限4時間の保険つき。
    _now_ts = time.time()
    _hold_changed = False
    if _rot and _rot_kind == "refresh":
        _hold, _hold_why = _refresh_hold(entry, rec, _now_ts)
        if _hold:
            _hold_changed = True
            _rot, _rot_kind = False, ""
            entry["refresh_hold_n"] = int(entry.get("refresh_hold_n") or 0) + 1
            entry.setdefault("refresh_hold_since", _now_ts)
            _record(rid, dept, "running",
                    f"★定期リフレッシュを**会話の途中なので**見送った {_hold_why} "
                    f"tokens={_ctx_now} compacts={entry.get('compact_count')}")
            _log(dept, f"★定期リフレッシュを見送った(Chamiと会話の途中・文脈{_ctx_now:,})")
        elif entry.get("refresh_hold_n"):
            # ★見送っていた分をここで清算する(次の世代へ持ち越さない)。
            _record(rid, dept, "running",
                    f"★見送っていた定期リフレッシュをここで実行する"
                    f"(見送り{entry.get('refresh_hold_n')}便 {_hold_why or 'Chamiが会話の途中ではない'})")
            entry.pop("refresh_hold_n", None)
            entry.pop("refresh_hold_since", None)
            _hold_changed = True
    # ★この部屋でChamiが最後に喋った時刻を残す(次の便の「会話の途中か」の判定材料)。
    #   ★台帳を増やさない= 既にある対応表の1行に置く(§4「記録先を2つ持たない」)。
    #   ★**交代の判定より後**に更新する。先に更新すると自分自身と比べて必ず「会話の途中」になる。
    if is_from_chami(rec):
        entry["last_chami_at"] = _now_ts
    # ★保存は普段しない= 便の終わりで entry ごと保存される既存の経路に乗せる(書き込みを増やさない)。
    #   見送りを決めた便だけはここで確定させる(その便が落ちても見送りの事実は残す)。
    #   ★便が落ちて last_chami_at が残らなかった時は、次の便は**見送らない**=従来どおり交代する
    #     (判定不能を「交代しない」へ倒すと定期リフレッシュが静かに死ぬ。fail-open は交代の側)。
    if _hold_changed and sid:
        save_room(dept, entry)

    # ★★窓を超えている便の観測(2026-07-29・判定には使わない)。
    #   実測 07:13:12 ctx=202,754 で便は成功していた=**落ちてはいない**。
    #   だが古い会話は静かに落ちている可能性が高いので、見えるように1行だけ残す。
    if sid and _ctx_now >= CONTEXT_WINDOW_TOKENS:
        _record(rid, dept, "running",
                f"★文脈{_ctx_now:,}が窓の目安{CONTEXT_WINDOW_TOKENS:,}を超えている"
                f"(compacts={entry.get('compact_count')} 交代の判定はこれとは別=下の通り)。"
                "実測では便は失敗していないが、古い会話が静かに落ちている可能性がある")
        _log(dept, f"★文脈{_ctx_now:,}が窓の目安を超えている(便は続行する)")

    if _rot:
        _log(dept, f"★例外の世代交代: {_why_rot}(文脈"
                   f"{int(entry.get('context_tokens') or 0):,})")
        _record(rid, dept, "rotated",
                f"事前交代 理由={_why_rot} tokens={entry.get('context_tokens')} "
                f"turns={entry.get('turns')} compacts={entry.get('compact_count')} old={sid}")
        # 1. 交代する前に、今のセッション自身に引き継ぎを書かせる(提案書§7.2 手順2)
        #    ★2026-07-29 以後はチェックポイント(第2手(d))で既に新しい正本が在ることが多い。
        #      それでもここで書かせるのは、**最後の数便ぶんが正本に入っていない**からだ。
        handoff_path, head = _write_handoff(dept, conf, token, sid, generation or 1)
        _record(rid, dept, "rotated",
                (f"引き継ぎ生成OK path={handoff_path} 冒頭={head!r}" if handoff_path
                 else "引き継ぎ生成に失敗(★交代自体は続行する)"))
        pre_rotating = True
        sid = ""                        # → 下の「初回、または世代交代」分岐へ落ちる

    # --- ★★規律を全文で送るか3行で送るかを決める(2026-07-29・改善書 第3手) ---
    #   全文にするのは4つの場面だけ:
    #     ① 新セッション(交代を含む)= 履歴に規律が1文字も無いので必ず全文
    #     ② 指紋が変わった(誰かが規律を編集した)= 「1行足せば次の便から効く」を保つ本体
    #     ③ 圧縮の直後(resend_boot)= 履歴が畳まれて規律が消えている可能性がある
    #     ④ DISC_FULL_EVERY(10)便に1回の保険
    _disc_fp = discipline_fingerprint()
    _resend = bool(entry.get("resend_boot"))
    _since_full = int(entry.get("disc_since_full") or 0)
    disc_full = (not sid                              # ①
                 or not _disc_fp                      # 指紋が取れない=安全側(全文)へ倒す
                 or entry.get("disc_hash") != _disc_fp  # ②
                 or _resend                           # ③
                 or _since_full >= DISC_FULL_EVERY)   # ④
    _disc_why = ("新セッション" if not sid else
                 "指紋が取れない" if not _disc_fp else
                 "規律が変わった" if entry.get("disc_hash") != _disc_fp else
                 "圧縮の直後" if _resend else
                 f"{DISC_FULL_EVERY}便に1回の保険" if _since_full >= DISC_FULL_EVERY else "")

    # ★封筒はここで作る(交代の判定より**後**)。理由= 封筒の先頭に載せる世代番号を、
    #   交代後の新しい世代にしないと、セッションが自分の世代を間違えて答える。
    envelope = build_envelope(
        rec, is_work=is_work,
        state=_state_block((generation + 1) if pre_rotating else (generation or 1),
                           0 if pre_rotating else int(entry.get("context_tokens") or 0)),
        dept=dept, disc_full=disc_full, disc_fp=_disc_fp)

    def _on_soft(elapsed):
        """soft を超えた時に**1回だけ**走る(2026-07-27)。

        やること= ①台帳へ `slow` を1行 ②呼び元へ中間通知の合図。
        ★**再分類も自動リトライもしない**(勝手に2回実行すると二重作業になる)。記録だけだ。
        ★どちらが失敗しても本体の待ちは続ける(通知の失敗で便を落とさない)。
        """
        if soft_fired[0]:
            return
        soft_fired[0] = True
        # ★分類のハズれを台帳に残す(2026-07-27の発注(4))。
        #   soft を超えた便は「classify_work() が会話と判定したのに実際は長かった」可能性が高い。
        #   02:40の便がまさにそれ(会話判定→中身は実装作業→300秒で殺されて成果ごと失われた)。
        _record(rid, dept, "slow",
                f"soft={timeout}s超過 elapsed={elapsed:.0f}s work={is_work} dept={dept} "
                f"hard={hard}s ★分類のハズれの疑い(再分類も再実行もしない・記録のみ)")
        _log(dept, f"soft({timeout}秒)を超えた=まだ待つ(hard {hard}秒まで)。elapsed={elapsed:.0f}秒")
        if on_slow is not None:
            try:
                on_slow(elapsed, timeout, is_work)
            except Exception as e:
                _log(dept, f"中間通知に失敗({type(e).__name__})=本体の待ちは続ける")

    def _run_audited(prompt, session_id=None):
        """_run_claude を1回だけ回し、作業便なら前後の差分を work_audit へ残す。

        ★監査を取るのは is_work の便だけ= 旧 work_generate と同じ範囲に揃える
          (会話便まで毎回 _git_snapshot を2回walkすると、20部屋×2秒巡回で重くなる)。
        """
        before = _work_snapshot() if is_work else None
        _t0 = time.time()
        try:
            data, rc, out, _sec = _run_claude(prompt, token, session_id=session_id,
                                              model=model, timeout=timeout,
                                              hard_timeout=hard, on_soft=_on_soft)
            waited_total[0] = max(waited_total[0], _sec)
        except subprocess.TimeoutExpired:
            # ★hardで打ち切った時も**待った秒数を残す**(Chami向けの文面に入れるため)。
            waited_total[0] = max(waited_total[0], time.time() - _t0)
            # ★★打ち切った便でも**触ったファイルの監査は残す**(2026-07-27)。
            #   02:40の実測= 殺された便は実際には daily_report.py を書き換えて commit まで
            #   済ませていた。監査が無いと「何がどこまで進んだか」を後から追えず、
            #   Chamiへ「結果を確かめてほしい」と言っておきながら**確かめる材料が無い**ことになる。
            #   ★rc=-1 は「打ち切ったので終了コードが無い」の意味。
            if before is not None:
                _work_audit(dept, rec.get("msg_id", ""), before, _work_snapshot(), -1,
                            time.time() - _t0, model, "hard timeout(強制終了)")
            raise
        if before is not None:
            # ★監査に残すモデル名は**実際に使った値**(定数を書くと、部屋別モデルを入れた瞬間に
            #   監査ログが嘘になる。監査は「後から追える」ことが唯一の価値なので嘘を残さない)。
            _work_audit(dept, rec.get("msg_id", ""), before, _work_snapshot(), rc,
                        time.time() - _t0, model, (out or "")[-1500:])
        return data, rc, out

    boot = _boot_prompt(dept, conf, generation or 1)
    # ★★2026-08-13 boot_hash は**台帳の部分を外した起動文**から取る(HQ論点1の本体)。
    #   台帳(未確認の不具合・未完了の依頼)は毎日動く。実測で aegis-gl は起動文10,267字のうち
    #   7,312字・system-engineer は11,574字のうち9,028字が台帳だ。旧版はこれを hash に含めて
    #   いたので、**台帳が1行動くたびに「運用が更新された」として起動文を丸ごと再注入**していた。
    #   → hash から外し、動いたのが台帳だけなら**台帳だけ**を送る(下の3枝)。
    #   ★入れ替えの初回だけ、全部屋で hash が食い違って全文が1回飛ぶ(そこは正しい=機構が変わった)。
    boot_plain = _boot_prompt(dept, conf, generation or 1, ledger=False)
    boot_hash = hashlib.sha256(boot_plain.encode("utf-8")).hexdigest()[:16]
    ledger_text = "\n".join(_ledger_lines(dept))
    ledger_hash = hashlib.sha256(ledger_text.encode("utf-8")).hexdigest()[:16]
    ledger_changed = bool(sid) and (entry.get("ledger_hash") != ledger_hash)

    # ★★ここが「前処理の終わり=本走の始まり」だ(2026-08-13 イージス研究室・HQ恒久依頼1)。
    #   この行より上で走るのは前処理= ①事前圧縮(実測 約200秒) ②事前交代の引き継ぎ生成
    #   (上限 HANDOFF_TIMEOUT=420秒) ③封筒・起動文の組み立て。
    #   下は本走= _run_claude を hard(会話600/作業1200秒)まで待つ区間。
    #   ★2026-08-13 の事故= 呼び元(dept_daemon)のキューのリースは **relayのhardしか見ていない**ため、
    #     前処理に1,619秒中419秒を使った便が走行中に「暇」へ戻り、daemon_keeper の載せ替え波に
    #     15:27:49 killされた(20分ぶんの返信が送信の1秒前に消えた)。
    #   → **前処理の長さをリースに食わせない**= 本走に入る瞬間に呼び元へ「今から本走だ」と伝え、
    #     呼び元が LeaseQueue.extend() でリースを張り直す。これで「便が重いほど殺される」が消える。
    #   ★ここでキューを直接触らない理由= session_relay はキューを知らない(呼び元だけが qid を持つ)。
    #     知らせるだけにしておけば、jsonl経路など**キューを使わない呼び元でも1ミリも変わらない**。
    #   ★失敗しても本走は続ける(通知の失敗で便を落とさない= on_slow と同じ作法)。
    if on_main_start is not None:
        try:
            on_main_start(hard)
        except Exception as e:
            _log(dept, f"本走の合図に失敗({type(e).__name__})=本走はそのまま続ける")

    try:
        if sid:
            # --- 2回目以降: 本物のセッション再開 ---
            # ★★起動文の更新を**生きているセッションへ届ける**(2026-07-26)。
            #   なぜ要るか= 起動文は**セッション作成時にしか読まれない**。resumeでは封筒しか届かない。
            #   すると運用を変えても**既存セッションは古い規則のまま**動き続ける。今回はまさに
            #   「あなたは手を動かさない・作業したと言うな」→「あなたが実作業も担当する」という
            #   **正反対の差し替え**なので、届かないと作業便が既存セッションに拒否され、
            #   誰も手を動かさないまま会話だけが返る=**偽の受領が沈黙を隠す**(ORG-04と同じ形)。
            #   ★世代交代(セッションを捨てて作り直す)では**会話の記憶が失われる**ので採らない。
            #     起動文が変わった時だけ、封筒の前に**更新の通知として1回だけ**差し込む。
            #   ★2回目以降は hash が一致するので1文字も増えない(既存の便は旧版と同じ形のまま)。
            # ★★2026-07-29 追加(改善書 第2手(b)): **圧縮の直後も**起動文を1回だけ配り直す。
            #   圧縮の要約は機械製で、人格・規律・部屋の約束が薄まっている可能性がある。
            #   ここが**圧縮運用の品質保険の本体**であり、これを省くなら圧縮を入れてはいけない
            #   (改善書 第2手の「品質判定」= (b)と(d)をセットで入れることが条件)。
            #   ★既にある boot_hash 更新通知と**同じ枠**を使う(通知の経路を2本作らない)。
            # ★★2026-08-13(イージス研究室・HQ msg 1537452059643740302)——
            #   **人格ファイルだけが変わった便で、起動文の全文(実測11,448字)を積むのをやめた。**
            #   Chamiの一次情報= 「なんかした?他の各部屋(全部ではない)で、急に文脈読まなくなった」
            #   HQが測った構造=
            #     ・この枝は char_changed でも `_head + boot(11,448字) + envelope` を送っていた。
            #     ・人事部門が口調を直すほど発火する(本日 characters|personas へのコミット14件・
            #       のべ25ファイル。直近1,500行のログでの同送= copy-director 5 / llm-edu 9 /
            #       hq 13 / system-engineer 14)。
            #     ・結果、文脈が押し出されて圧縮が早く回り、圧縮5〜6回+文脈10万超で
            #       **定期リフレッシュの世代交代**まで前倒しになった(22:01:54 llm-edu /
            #       22:08:15 copy-director。名指しの2部屋とも、Chamiの便の10〜17分前に交代)。
            #     → **「人格を磨くほど全部屋の文脈が減る」**。誰も悪くないのに劣化する形なので
            #       機構側で吸う(HQ論点1「再注入を軽くする」を採用)。
            #   ★なぜ全文が要らないか= この枝に来るのは `boot_hash` が**一致している**便だけ=
            #     起動文はそのセッションが既に受け取っている。char_changed で本当に必要なのは
            #     「台帳が編集されたから読み直せ」の指示と**変わったファイルのパス**だけだ。
            #     (起動文自体が古い= boot_hash 不一致 / 圧縮で要約が薄まった= _resend は
            #      どちらも下の全文枝へ落ちる。**品質保険の2本はそのまま残している**)。
            #   ★HQ論点2(次の交代まで注入を遅らせる)は**採らない**。人格の修正が最長1世代
            #     届かなくなる= Chamiが口調を直した時に「まだ直ってない」が続く方が損だ。
            #     軽くすれば、即時に届けたまま文脈も食わない。
            if (ledger_changed and entry.get("boot_hash") == boot_hash and not _resend):
                # ★台帳だけが動いた便= 台帳だけを送る(起動文の本体は既にそのセッションに在る)。
                #   ★人格も同時に変わっていたら、読み直しの指示をこの便に**同居**させる
                #     (2便に割らない= 便の数を増やすと、それはそれで文脈を食う)。
                _extra = ""
                if char_changed:
                    _names = char_changed_paths or sorted(char_parts)
                    _extra = ("\n=== ★人格ファイル(characterfile)も更新された"
                              "(以後はファイルの中身が正) ===\n"
                              "★記憶の中の口調ではなく、下のファイルを今すぐ読み直して、その声で書け。\n"
                              + "".join(f"- {p}\n" for p in _names))
                prompt = ("=== ★この部屋の台帳が更新された(未確認の不具合 / 未完了の依頼)。"
                          "**以後はこちらが正**。前に渡した一覧はこれで置き換えろ ===\n"
                          "★運用(規律・役割・人格の名簿)は変わっていない=起動文は前のままで正。\n"
                          + (ledger_text or "★この部屋の台帳は現在0件だ(未確認の不具合も未完了の依頼も無い)。")
                          + _extra
                          + "\n=== ここまで ===\n\n") + envelope
                _log(dept, f"台帳の更新→**台帳だけ**を送る(起動文{len(boot):,}字は積まない"
                           f"・台帳{len(ledger_text):,}字"
                           f"{'・人格の読み直しも同居' if char_changed else ''})")
                _record(rid, dept, "running",
                        f"台帳の更新(軽量) 台帳={len(ledger_text)}字 節約={len(boot) - len(ledger_text)}字 "
                        f"人格同居={'yes' if char_changed else 'no'} "
                        f"規律={'全文' if disc_full else '3行'}({_disc_why or '変更なし'})")
            elif char_changed and entry.get("boot_hash") == boot_hash and not _resend:
                _names = char_changed_paths or sorted(char_parts)
                prompt = ("=== ★この部屋の人格ファイル(characterfile)が更新された"
                          "(以後はファイルの中身が正) ===\n"
                          "★セッション起動後に台帳が編集されている。**記憶の中の口調ではなく、"
                          "下のファイルを今すぐ読み直して**、その声で書け。\n"
                          + "".join(f"- {p}\n" for p in _names)
                          + "★これは運用の変更ではない(起動文は前のままで正)。"
                          "読み直すのはこのファイルだけでよい。\n"
                          "=== ここまで ===\n\n") + envelope
                _log(dept, f"人格ファイルの更新→**読み直しの指示だけ**を送る"
                           f"(起動文{len(boot):,}字は積まない・更新{len(_names)}枚)")
                _record(rid, dept, "running",
                        f"人格ファイルの更新(軽量) 枚数={len(_names)} 節約={len(boot)}字 "
                        f"規律={'全文' if disc_full else '3行'}({_disc_why or '変更なし'})")
            elif entry.get("boot_hash") != boot_hash or _resend or char_changed:
                if _resend:
                    _head = ("=== ★直前に会話の履歴が圧縮された(要約に畳まれた)。"
                             "起動文と規律を**もう一度**渡す。以後はこちらが正 ===\n"
                             "★要約で薄くなっている可能性があるので、下の内容を読み直せ。\n")
                    _why_resend = "圧縮直後の再送"
                elif entry.get("boot_hash") != boot_hash:
                    _head = ("=== ★この部屋の運用が更新された(以後はこちらが正。"
                             "前の指示と矛盾する所はこちらを採れ) ===\n")
                    _why_resend = "起動文の更新"
                else:
                    # ★2026-08-13以降、この枝には来ない(人格だけの更新は上の軽量枝が拾う)。
                    #   消さずに残す=C-003。上の条件を戻したい時の元の文面がここに在る。
                    # ★人格ファイルだけが変わった便(2026-07-31 REQ-hr-room-74346481c4)。
                    #   起動文の本文は同じだが、起動文はcharacterfileの**パス**を列挙して
                    #   「読め」と言うので、再送すればセッションはファイルを読み直す。
                    #   記憶の中の古い口調を捨てさせる1文を足す。
                    _head = ("=== ★この部屋の人格ファイル(characterfile)が更新された"
                             "(以後はファイルの中身が正) ===\n"
                             "★セッション起動後に台帳が編集されている。**記憶の中の口調ではなく、"
                             "下に挙げたcharacterfileを今すぐ読み直して**、その声で書け。\n")
                    _why_resend = "人格ファイルの更新"
                prompt = _head + boot + "\n=== ここまで ===\n\n" + envelope
                _log(dept, f"{_why_resend}→生きているセッションへ起動文を同送する")
                _record(rid, dept, "running",
                        (f"圧縮後の再送 hash={boot_hash} " if _resend else f"{_why_resend} ")
                        + f"規律={'全文' if disc_full else '3行'}({_disc_why or '変更なし'})")
            else:
                prompt = envelope
            _record(rid, dept, "running", f"resume session={sid} gen={generation}")
            data, rc, out = _run_audited(prompt, session_id=sid)
            reply = _reply_of(data)
            # ★★2026-08-14 第3の箱= rc=0なのに本文が空(定義とコメントは looks_like_empty_reply)。
            #   ここで**まず同じセッションへ1回だけ催促する**= 一過性ならこれで返る。
            #   交代を先に打たない理由は「会話の記憶を捨てるのは最後の手」だから。
            #   ★実物の中身(2026-08-13 15:33:06 の llm-qa)= セッションは
            #     「No response requested.」(出力7トークン)と答えていた=**便を機械の通知だと
            #     読んで返事を省いていた**。だから催促の文はそこを名指しで潰してある。
            _empty_nudged = False
            if looks_like_empty_reply(rc, data, out):
                _empty_nudged = True
                _log(dept, "rc=0だが返信本文が空= 同じセッションへ1回だけ催促する(記憶は捨てない)")
                _record(rid, dept, "running", f"空返答→催促 session={sid}")
                try:
                    data2, rc2, out2 = _run_audited(
                        EMPTY_REPLY_NUDGE,
                        session_id=str((data or {}).get("session_id") or sid))
                except subprocess.TimeoutExpired:
                    # ★催促が返らないのも「答えられない」の一種=交代へ倒す(便を殺さない)。
                    data2, rc2, out2 = None, -1, ""
                    _log(dept, "催促が時間内に返らなかった=交代へ倒す")
                reply2 = _reply_of(data2)
                if rc2 == 0 and reply2:
                    data, rc, out, reply = data2, rc2, out2, reply2
                    _log(dept, "催促で本文が返った=この便はそのまま配る(交代しない)")
                else:
                    _log(dept, "催促しても本文が空= このセッションは答えを返せない状態と見る")
            if rc == 0 and reply:
                new_sid_r = str((data or {}).get("session_id") or sid)
                entry.update({"active_session_id": new_sid_r,
                              "status": "ready", "last_used_at": now,
                              "boot_hash": boot_hash})
                # ★★2026-08-12 手動交代(rotate_now)で引き継げなかった時の**繰り越しの一言**。
                #   あちらにはChamiへ返す便が無いので旗だけ置いてある。ここで1回だけ回収する。
                #   pop してから save_room するので、**次の便には残らない**(毎便言わない)。
                _handoff_missing = bool(entry.pop("handoff_missing_notice", 0))
                # ★読み直しを送った/不要だった便で人格ファイルの指紋を確定する(2026-07-31)。
                #   空("")では上書きしない=読めなかった便で健全な指紋を消さない(fail-open)。
                if char_fp:
                    entry["char_fp"] = char_fp
                    # ★内訳も残す=次に変わった時に「どの1枚か」を名指しできる(2026-08-13)。
                    entry["char_parts"] = char_parts
                # ★台帳の指紋(2026-08-13)。渡し終えた便で確定する=次に動いた時だけ台帳を送る。
                entry["ledger_hash"] = ledger_hash
                # ★2026-07-29 規律の指紋の帳簿(改善書 第3手)。
                #   全文を渡した便で指紋を更新し、数え直す。3行の便は数を1つ進めるだけ。
                #   ★数え方= **全文を送った便も1便と数える**(=1にリセット)。0にすると
                #     全文の次から10便数えることになり、実際の周期が11便になる(試験で実測して直した)。
                if disc_full:
                    entry["disc_hash"] = _disc_fp
                    entry["disc_since_full"] = 1
                else:
                    entry["disc_since_full"] = _since_full + 1
                # ★圧縮後の再送は**1回だけ**。渡し終えたのでここで下ろす(下ろさないと毎便再送になる)。
                if _resend:
                    entry.pop("resend_boot", None)
                # ★使用量を実測で記録する(2026-07-26)。**次の便の判定はこの値だけを見る。**
                #   ★2026-07-29 sid を渡してトランスクリプトの実値を優先させる(改善書 第1手)。
                ctx = _note_usage(entry, data, now, sid=new_sid_r)
                table[dept] = entry
                # ★2026-07-28 表全体ではなく**この部屋の1行だけ**を書き戻す。
                #   旧= save_sessions(table) は便の入口で読んだ古い表を丸ごと上書きしていて、
                #   その間に終わった他部屋の世代交代を消していた(request_log の実測で特定)。
                save_room(dept, entry)
                _record(rid, dept, "completed",
                        f"session={entry['active_session_id']} gen={generation} "
                        f"ctx={ctx} src={entry.get('context_source')} "
                        f"turns={entry.get('turns')} compacts={entry.get('compact_count')} "
                        f"規律={'全文' if disc_full else '3行'}")
                # ★★2026-07-29 便を**返した後**の後始末を予約する(改善書 第2手(a)(d))。
                #   ここでスレッドを起こしてから return するので、Chamiの返事は1秒も遅れない。
                _schedule_maintenance(dept, conf, token, entry["active_session_id"],
                                      generation, ctx, entry)
                if _handoff_missing:
                    # ★世代の数字も「更新した」も言わない= 告知は消す、警告は残す(2026-08-12)。
                    reply = (reply.rstrip() + "\n\n"
                             "(★前の記憶を引き継げなかった。記憶ファイルから復元しているので、"
                             "抜けていたら遠慮なく言ってくれ)")
                    # ★言葉を「伝えた」にしない(2026-08-12・研究室HQの指摘への返し)。
                    #   旗は保存の時点で落としてある=**保存済み・配達前**に落ちると、この1回は消える。
                    #   その時この行が「伝えた」と書いてあると、**届いていないのに届いた記録**が残る。
                    #   → 観測できた事実だけを書く= 添えて返した所までがここで分かること。
                    #   ★順序はこのままでよい(毎便繰り返す害の方が大きい)。消えても沈黙にはならない=
                    #     新世代の起動文に handoff_failed の一節が入っていて、そちらは文脈に残り続ける。
                    _log(dept, "手動交代の引き継ぎ欠落を、この便の末尾に添えて返した"
                               "(配達の成否はこの時点では分からない)")
                _recent_append(dept, rec, reply)    # ★次の世代へ渡す「生の直前の便」(2026-08-13)
                return reply, True
            if _looks_like_auth_failure(out):
                # ★認証失敗=**やり直さない**(INC-109)。世代交代もしない(窓を増やさない)。
                LAST_ERROR[dept] = "Claude CLIの認証が通らない(cli_auth_token.txtの失効の疑い)"
                _record(rid, dept, "failed", "auth failure(リトライせず)")
                _log(dept, "認証失敗=1回で諦める(リトライ禁止・INC-109)")
                return None, False
            # ★2026-07-25 実弾で判明: クレジット切れ("Credit balance is too low")のような
            #   **口座側の問題では世代交代しない**。交代しても新セッションが同じ理由で失敗し、
            #   健全な旧セッション(会話の記憶)を捨てる危険だけが残る(実弾で gen=1 を捨てかけた。
            #   対応表の原子的更新=成功時のみ、が偶然守った)。
            #   交代するのは**セッションが見つからない時だけ**。それ以外は失敗として正直に返す。
            # ★★2026-08-14 空返答は**交代してよい唯一の失敗**として切り出す。
            #   上の注記(2026-07-25)は**口座エラーの箱**の話だ= 交代しても新セッションが同じ
            #   理由で落ちるから交代しない。空返答は形が違う: 口座は生きていて課金も通っており、
            #   落ちているのは**そのセッション1本**だ。実測(08-13)= 15:39:44 まで10連敗した便が、
            #   15:42:43 に**人が手で世代交代**させた直後、15:45:46 の次便は1回目の配達で通り
            #   15:48:48 に部屋へ着いた(discord 1537352198785208410)。人がやったのと同じ手を機械にやらせる。
            #   ★引き継ぎ(handoff)は作らない= 引き継ぎ文を書かせる相手が、まさに答えを返せない
            #     セッションだからだ。新セッションは起動文+台帳+直前の便(recent)から立ち上がる。
            if not _looks_like_session_missing(out) and not _empty_nudged:
                LAST_ERROR[dept] = f"Claude CLIがエラーを返した(rc={rc}): {str((data or {}).get('result') or '')[:80]}"
                _record(rid, dept, "failed", f"resume失敗(交代せず) rc={rc} out={(out or '')[:300]!r}")
                _log(dept, f"resume失敗(rc={rc})=口座/一時異常の疑い。世代交代せず1回で諦める")
                return None, False
            if _empty_nudged:
                _log(dept, "空返答(催促も空)→世代交代=このセッション1本だけが答えを返せない")
                _record(rid, dept, "rotated", f"空返答(rc=0・本文なし) old={sid}")
            else:
                _log(dept, f"resume失敗(セッション不明)→世代交代")
                _record(rid, dept, "rotated", f"resume失敗 old={sid} rc={rc}")
            sid = ""

        # --- 初回、または世代交代 ---
        generation = generation + 1 if generation else 1
        rotated_to = generation if generation > 1 else 0
        # ★対応表へ残す boot_hash は**引き継ぎの行を含まない素の起動文**から取る。
        #   理由= 引き継ぎの行は「この交代の時だけ」の一時的な指示なので、これを混ぜると
        #   次の便の resume で hash が食い違い、**毎回「運用が更新された」通知が飛ぶ**。
        # ★台帳を外して取る(2026-08-13)。上の resume 側と**同じ取り方**でなければ、
        #   交代した次の便で必ず hash が食い違って全文が飛ぶ。
        boot_plain = _boot_prompt(dept, conf, generation, ledger=False)   # 世代番号が入るので作り直す
        boot_hash = hashlib.sha256(boot_plain.encode("utf-8")).hexdigest()[:16]
        boot = _boot_prompt(dept, conf, generation,
                            handoff_path=handoff_path,
                            handoff_failed=bool(pre_rotating and not handoff_path))
        prompt = boot + "\n\n" + envelope
        _record(rid, dept, "running", f"new session gen={generation}")
        data, rc, out = _run_audited(prompt)
        reply = _reply_of(data)
        new_sid = str((data or {}).get("session_id") or "")
        if rc != 0 or not reply or not new_sid:
            if _looks_like_auth_failure(out):
                LAST_ERROR[dept] = "Claude CLIの認証が通らない(cli_auth_token.txtの失効の疑い)"
            elif pre_rotating:
                # ★交代**そのもの**が失敗した時だけ、Chamiへ正直に断る(発注の要件)。
                #   ★対応表はまだ書き換えていないので、旧セッションは生きたまま残る
                #   (成功時だけ save_sessions する既存の作りが、ここでも効いている)。
                LAST_ERROR[dept] = (f"セッションの切り替えに失敗した(新しい世代を作れなかった rc={rc})。"
                                    f"前の世代は残してあるので失われてはいない")
            else:
                LAST_ERROR[dept] = f"Claude CLIが応答を返さなかった(rc={rc})"
            # ★2026-07-25 失敗の生出力を証拠に残す(初回実弾がrc=1で落ちた際、is_error/api_errorが
            #   捨てられていて原因を追えなかった。エラーを握り潰すと次も同じ調査をやり直す)
            _record(rid, dept, "failed",
                    f"new session失敗 rc={rc} sid={new_sid!r} pre_rotating={pre_rotating} "
                    f"out={(out or '')[:500]!r}")
            _log(dept, f"新規セッション作成に失敗(rc={rc})=1回で諦める")
            return None, False
        new_entry = {"active_session_id": new_sid, "generation": generation,
                     "status": "ready", "boot_hash": boot_hash,
                     "created_at": entry.get("created_at") or now,
                     "last_used_at": now,
                     # ★新セッションは起動文でcharacterfileを読んだので指紋を確定(2026-07-31)。
                     "char_fp": char_fp, "char_parts": char_parts,
                     # ★新セッションは台帳を起動文で受け取っている=指紋を確定(2026-08-13)。
                     "ledger_hash": ledger_hash,
                     # ★2026-07-29 新セッションは規律を全文で渡している(disc_full=True)。
                     #   指紋を置いて、次の便から3行に切り替わるようにする(改善書 第3手)。
                     "disc_hash": _disc_fp, "disc_since_full": 1}
        # ★使用量は新世代のものを入れ直す(turns/context_tokens は世代でリセットされる)。
        #   ★compact_count も新しい記録ファイルから数え直される(世代ごとに別ファイル)。
        ctx = _note_usage(new_entry, data, now, sid=new_sid)
        # ★新世代は圧縮の借金を引き継がない(圧縮失敗の印・定期リフレッシュの基準を清算する)。
        new_entry.pop("compact_failed", None)
        new_entry.pop("resend_boot", None)
        new_entry["refresh_rotated_at_compacts"] = int(new_entry.get("compact_count") or 0)
        # ★「Chamiが最後に喋った時刻」は**部屋の性質**であってセッションの持ち物ではない。
        #   世代を跨いで引き継ぐ(2026-08-13。捨てると交代直後の1便だけ判定材料を失う)。
        if entry.get("last_chami_at"):
            new_entry["last_chami_at"] = entry.get("last_chami_at")
        if is_from_chami(rec):
            new_entry["last_chami_at"] = _now_ts     # ★now は文字列の時刻。epochはこちら
        if handoff_path:
            new_entry["handoff_from_prev"] = handoff_path
        table[dept] = new_entry
        # ★2026-07-28 ここが**一番消えては困る書き込み**(交代の結果そのもの)。
        #   この部屋の1行だけを、今ディスクにある表へ差し替える。
        save_room(dept, new_entry)
        _record(rid, dept, "completed",
                f"session={new_sid} gen={generation} ctx={ctx} "
                f"src={new_entry.get('context_source')} turns={new_entry.get('turns')}")
        if pre_rotating:
            # ★新世代自身の自己確認(提案書§7.2 手順5)。**Discordへは出さない**=内部のログにだけ残す。
            #   ★対応表を切り替えた**後**に走らせる。ここで失敗しても、動いている新セッションを
            #     捨てるべきではないから(自己確認は診断であって、交代の可否ではない)。
            sc = _self_check(dept, conf, token, new_sid, generation)
            _record(rid, dept, "rotated", f"自己確認 gen={generation}: {sc[:400]!r}")
            _log(dept, f"交代完了 gen={generation} sid={new_sid} 自己確認={'取得' if sc else '取得できず'}")
        if rotated_to:
            # ★★2026-08-12 Chami「どの部屋もセッションの世代続投宣言別にいらないんだけど…」
            #   (msg ESC-hr-context-1536784302132437112)。→ **世代の宣言は貼らない。**
            #   旧= 交代の度に「(セッションを第N世代へ更新した。前世代の引き継ぎは読み込み済み)」。
            #   2026-07-26に「黙って人格が入れ替わらないため」として入れた物だが、
            #   Chamiにとっては**毎回同じことを言われるだけの行**だった。裁定より本人の言葉が上だ。
            #   ★ただし**引き継げなかった時は黙らない**= あれは「更新しました」の告知ではなく、
            #     **文脈が欠けている**という警告で、Chamiが実際に困る(『前に話した件』が通じない)。
            #     世代の数字も「更新した」も言わず、欠けている事実だけを1行にする。
            if not handoff_path:
                reply = (reply.rstrip() + "\n\n"
                         "(★前の記憶を引き継げなかった。記憶ファイルから復元しているので、"
                         "抜けていたら遠慮なく言ってくれ)")
                _log(dept, f"交代 gen={rotated_to}: 引き継ぎ無し=欠落の一言だけ添えた"
                           f"(世代の宣言は貼らない・2026-08-12 Chami)")
            else:
                _log(dept, f"交代 gen={rotated_to}: 世代の宣言は貼らない(2026-08-12 Chami)")
        _recent_append(dept, rec, reply)            # ★次の世代へ渡す「生の直前の便」(2026-08-13)
        return reply, True
    except subprocess.TimeoutExpired:
        # ★★2026-07-27 文面を直した。旧= 「Claude CLIが300秒で応答しなかった」。
        #   これは**2つの点で不正確**だった:
        #     ① 実際に待った秒数ではなく、定数(soft)を書いていた。
        #     ② 呼び元がこれを「セッションへ渡せていない」と言い添えていたが、
        #        02:40の実測では**渡っていたし作業も終わっていた**(daily_report.pyを書き換えて
        #        commit 86ef339 まで済ませていた)。**推測を断定にしていた。**
        #   → 実測の秒数を書き、「作業が進んでいる**可能性がある**」と可能性のまま伝える。
        waited = int(waited_total[0] or hard)
        LAST_ERROR[dept] = (
            f"{waited}秒待ったがClaude CLIから返事が来なかった"
            f"(この便の目安{timeout}秒→{hard}秒まで延長して待った)。"
            "★セッション側の**作業自体は進んでいる可能性がある**"
            "(進んだかどうかはこちらでは確認できていない)。"
            "同じことをもう一度頼む前に、結果を確かめてほしい")
        LAST_ERROR_KIND[dept] = "timeout"
        _record(rid, dept, "failed",
                f"timeout waited={waited}s soft={timeout}s hard={hard}s work={is_work} "
                f"★成果が残っている可能性あり(work_audit.jsonl / git を確認)")
        _log(dept, f"hard({hard}秒)まで待ったが返らなかった=打ち切る waited={waited}秒")
        return None, False
    except Exception as e:
        LAST_ERROR[dept] = f"配送処理の例外({type(e).__name__})"
        _record(rid, dept, "failed", f"{type(e).__name__}: {e}")
        return None, False


def rotate_now(dept, conf, token, reason="manual"):
    """★手動の世代交代(HQが試験・緊急時に叩く口)。Discordの便を伴わずに交代する。

    戻り値 (ok, info)。**Discordへは何も出さない**(次の便から新世代が答える)。
    ★relay() の事前交代と**同じ手順**を通す(引き継ぎ→新セッション→自己確認→対応表を1回で更新)。
      手順を2本持つと、片方だけ直して食い違う(記録先を2つ持たない=ORG-11と同じ話)。
    """
    rid = f"rotate-now-{int(time.time())}"
    LAST_ERROR.pop(dept, None)
    _join_maintenance(dept)                     # ★後始末と交代を重ねない(2026-07-29)
    table = load_sessions()
    entry = table.get(dept) or {}
    sid = str(entry.get("active_session_id") or "")
    generation = int(entry.get("generation") or 0)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if not sid:
        return False, f"{dept}: まだセッションが無い(交代する相手が居ない)"
    _record(rid, dept, "rotated", f"手動交代 reason={reason} old={sid} gen={generation}")
    handoff_path, head = _write_handoff(dept, conf, token, sid, generation or 1)
    new_gen = (generation or 1) + 1
    boot_plain = _boot_prompt(dept, conf, new_gen, ledger=False)   # ★台帳を外して取る(2026-08-13)
    boot_hash = hashlib.sha256(boot_plain.encode("utf-8")).hexdigest()[:16]
    boot = _boot_prompt(dept, conf, new_gen, handoff_path=handoff_path,
                        handoff_failed=not handoff_path)
    # ★便が無いので、最初の1便を**そのまま自己確認**にする(提案書§7.2 手順5)。
    #   ここでの応答はDiscordへ出さない=ログにだけ残す。
    prompt = (boot + "\n\n【システム: 交代直後の自己確認】これはChamiからの便ではない。"
              "**Discordへは出さない**。引き継ぎを読んだ結果として、次を**5行以内**で答えろ= "
              "(1)この部屋は何をする部屋か (2)今の目標 (3)未完了で自分が引き取ったこと "
              "(4)引き継げていない/不明だと感じた点。"
              "★**分からない所は『引き継げていない』と正直に書け。**取り繕うな。")
    try:
        # ★手動交代も部屋別モデルで走らせる(relay()の事前交代と手順を1本に保つため)。
        # ★手動交代も1段のまま(旧版と同じ)。ここはChamiが叩く口で、待たせている相手が居ない。
        data, rc, out, _sec = _run_claude(prompt, token, model=relay_model(conf),
                                          timeout=RELAY_TIMEOUT)
    except Exception as e:
        LAST_ERROR[dept] = f"手動交代で例外({type(e).__name__})"
        _record(rid, dept, "failed", f"手動交代 {type(e).__name__}: {e}")
        return False, f"{dept}: 交代に失敗({type(e).__name__})。前の世代は残してある"
    new_sid = str((data or {}).get("session_id") or "")
    if rc != 0 or not new_sid:
        LAST_ERROR[dept] = f"セッションの切り替えに失敗した(新しい世代を作れなかった rc={rc})"
        _record(rid, dept, "failed", f"手動交代 rc={rc} out={(out or '')[:500]!r}")
        return False, f"{dept}: 交代に失敗(rc={rc})。前の世代({sid})は残してある"
    new_entry = {"active_session_id": new_sid, "generation": new_gen,
                 "status": "ready", "boot_hash": boot_hash,
                 "created_at": entry.get("created_at") or now, "last_used_at": now,
                 # ★2026-07-29 手動交代も同じ帳簿を持つ(経路ごとに持ち物が違うと必ずズレる)。
                 #   ★手動交代の最初の1便(自己確認)には封筒が無い=規律の全文はまだ渡っていない。
                 #     だから指紋は**置かない**。次のChamiの便が全文を渡して指紋を置く。
                 # ★台帳は起動文に載せて渡している=ここで確定する(2026-08-13)。
                 #   置かないと、交代の直後の1便で台帳をもう一度送ることになる。
                 "ledger_hash": hashlib.sha256(
                     "\n".join(_ledger_lines(dept)).encode("utf-8")).hexdigest()[:16],
                 "char_fp": _char_fingerprint(conf), "char_parts": _char_parts(conf),
                 "disc_since_full": 0}
    _note_usage(new_entry, data, now, sid=new_sid)
    new_entry.pop("compact_failed", None)
    new_entry.pop("resend_boot", None)
    new_entry["refresh_rotated_at_compacts"] = int(new_entry.get("compact_count") or 0)
    if handoff_path:
        new_entry["handoff_from_prev"] = handoff_path
    else:
        # ★★2026-08-12 手動交代でも**引き継げなかった事実だけは黙らない**。
        #   ここにはChamiへ返す便が無い(自己確認はDiscordへ出さない)ので、その場では言えない。
        #   → 旗を対応表へ置き、**次にこの部屋がChamiへ返す便の末尾**で1行だけ添える(下の relay())。
        #   自動交代側は返信そのものに添えているが、経路が違うと持ち物が違う=同じ穴になる。
        new_entry["handoff_missing_notice"] = 1
    table[dept] = new_entry
    # ★2026-07-28 手動交代も同じ経路(この部屋の1行だけを書き戻す)。
    save_room(dept, new_entry)
    # ★★2026-08-12 自動交代と**同じ1行**をここにも残す(研究室HQの指摘・穴を塞ぐ)。
    #   旧= この印は relay() の `if rotated_to:` の中にしか無く、手動交代を通ると
    #   「宣言を貼らなかった」実測が1件も出ない=**直っているのに『まだ』と読める**検査になっていた。
    #   ★検査の言葉を経路ごとに変えない(grepが片方を数え落とすのが、静かに壊れる型だ)。
    _log(dept, f"交代 gen={new_gen}: 世代の宣言は貼らない(2026-08-12 Chami / 手動交代)"
               + ("" if handoff_path else " ※引き継ぎ無し=次の便で欠落を1行添える"))
    _record(rid, dept, "completed",
            f"手動交代 gen={generation}→{new_gen} new={new_sid} "
            f"handoff={handoff_path or 'なし'} 自己確認={_reply_of(data)[:300]!r}")
    return True, (f"{dept}: 第{generation}世代({sid})→第{new_gen}世代({new_sid})。"
                  f"引き継ぎ={handoff_path or '★取得できず'} 冒頭={head[:80]!r}")


def _main(argv):
    """`python session_relay.py --rotate-now <dept>` = 手動交代の口(HQの試験用)。

    ★デーモンを止めずに叩ける。DEPT_CONF とトークンは dept_daemon の1正本から引く。
    """
    if len(argv) < 3 or argv[1] != "--rotate-now":
        print("使い方: python session_relay.py --rotate-now <dept>")
        return 2
    dept = argv[2]
    import dept_daemon
    conf = dept_daemon.DEPT_CONF.get(dept)
    if not conf:
        print(f"不明な部門: {dept}")
        return 2
    try:
        token = open(dept_daemon.TOKEN_FILE, encoding="utf-8").read().strip()
    except OSError:
        print(f"トークンが読めない: {dept_daemon.TOKEN_FILE}")
        return 2
    ok, info = rotate_now(dept, conf, token, reason="cli")
    print(("OK " if ok else "NG ") + info)
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.path.insert(0, HERE)                    # dept_daemon を同じフォルダから引く
    raise SystemExit(_main(sys.argv))
