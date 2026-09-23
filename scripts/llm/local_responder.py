#!/usr/bin/env python3
"""ローカルLLM受付係 (Discord一次応答・Claudeセッション不在時の24時間窓口)。

仕組み(2026-07-15 変更・Chami指示「一次受けにローカルを挟むな・全部門で排除」):
  - **部門の依頼(main箱 discord_inbox.jsonl)には一切触れない**。以前はClaude不在時にmain箱を
    ドレインしてqwen応答/for_claude箱へ再エスカレしていたが、それが「依頼が横取りされて司令塔に
    届かない/無視される」原因だった。部門の依頼は司令塔(Claude)専任=main箱のまま待たせる。
  - 優依(ローカルqwen)が応対するのは**自室 llm-growth(discord_inbox_llm.jsonl / LeaseQueue dept=llm-growth)だけ**。
  - 質問系: Ollama(知識パック注入)で即答 → persona_send「優依(LLM)」名義で返信(旧名義=ローカルqwen)
  - 処理済みは local/discord_inbox_processed.jsonl へ移動。応答ログは local/llm/responder_log.jsonl

★2026-07-27 自室llm-growthの「会話モード」化(Chami指示・研究室HQ経由):
  Chami原文=「ここは成長進捗を確認する場所で、私とローカルLLMが会話するところだから、
  基本的にClaudeは出てこなくていい」。
  実測した死因(local/llm/responder_log.jsonl):
    部屋は 2026-07-17 16:27 を最後に10日間沈黙。最後のChami発言
    「(特に漫画内の文字とキャラクターの認識とか、ストーリー、話の文脈とか)」は
    mode=escalated で終わっている。原因は ask_local.ask() のシステムプロンプトが
    「知識に書いていない内容は絶対に推測しない/わからないので司令塔(Claude)に回します」
    と縛っており、handle() がその文字列を見て answer を捨て→Claude行きにしていたこと。
    = Chamiはローカルと**話しに**来たのに、qwenが毎回Claudeへ投げ返していた。
  対策(この版):
    1) 自室に限り ask_growth()(会話用システムプロンプト)で**自分で答える**。
       Claudeへ回すのは「実作業(ファイルを触る/実装/デプロイ)が要る依頼」だけ。
       ★「難しいから」「自信がないから」では回さない。分からないなら分からないと言って会話を続ける。
    2) 自分の成績(answered/escalated の実測値)をプロンプトに渡し、
       「調子はどう」に**実データの数字で**答えられるようにした(=この部屋の目的そのもの)。
    3) 部屋の目的(ROOM_PURPOSE)を持たせた。org_registry.yml には llm-growth の
       目的/KPIが無い(チャンネル対応表にしか出てこない)ため、depts へは足さずここに置く
       (あの部屋は「部門」ではなく Chami と qwen の会話部屋)。
  ★この部屋にClaudeのデーモンは立てない(dept_daemon.py の DEPT_CONF に llm-growth は入れない)。

★2026-07-27(その2)Chami裁定2件(研究室HQ経由)。原文=
  「**CとAは? 名前だけ決めて、画像は出させてClaudeがフィードバックしてよ 名前はやっぱり…優依 がいいな**」
  「**表記は優依(LLM)にして**」
  (1) 人格= **優依(ゆい)**。★「名前だけ決めて、性格は会話の中で育てる」なので、
      性格はここに書かない。正本= 00_AI-HQ/departments/hr/characters/yui.md を**都度読み**する
      (mtimeキャッシュ・yui_persona())。Chamiや五月が1行足したら**次の会話から効く**。
      ★yui.md の「この子の限界」節はプロンプトに入れない(本人に読ませると自己卑下/言い訳の材料になる。
        ただし「測っていない数字を語るな」の規則は growth_stats() 側でそのまま渡している)。
      ★Discordの名義= `優依(LLM)`。persona_send の --suffix に乗せる(dept_daemonの`(精霊)`と同じ仕組み)。
  (2) 画像= **優依が自分で答えてから、中野五月(llm-edu)が採点する**。
      旧V0は「画像=問答無用でClaude行き・qwenは下読みを添えるだけ」だった(=本人は一度も答えない)。
      新: ①優依が答えて部屋に出す ②元画像+Chamiの文+優依の答えを llm-edu へ投函(channelは優依の部屋)
          ③五月が「どこが合っていて、どこが違うか」を**優依の部屋へ**書く ④材料は既存の lessons.jsonl へ。
      ★指標: 画像便が「エスカレ」→「即答」へ移るので、learning_report.py で**画像便を別枠で数える**
        ようにした(指標の定義そのものは変えていない。理由は learning_report.py のコメント参照)。

★2026-07-27(その3)Chami指示(研究室HQ経由)。原文=
  「**1526159156019462194 五月orヴィルシーナを名指しして読んだらローカルLLMではなく
    君たちが答えるようにしてよ、トーク履歴見て採点とかしておいて**」
  (1526159156019462194 = この部屋『ローカルllm成長進捗』のチャンネルID)
  実測した動機(local/llm/responder_log.jsonl 2026-07-27T11:47:46):
    Chami「五月、採点」→ **優依(qwen)が答えてしまった**
    (しかも「五月先生は、私の回答を採点していますよ」と、五月の行動を勝手に語っている)。
    = 名前を呼んだ相手が出てこない。ask_growth の規則7(他人格を名乗らない)は
      「優依として話す」までしか縛っておらず、**名指しを取り次ぐ経路が無かった**。
  対策(この版):
    (1) 自室の便は**本文の名指しを先に見る**。名指しがあれば優依は答えず、
        既存の経路(feedback_record と同じ dept=llm-edu / channel=優依の部屋)で llm-edu へ投函する。
        → 中野五月/ヴィルシーナ本人が**この部屋へ**答える。新しい常駐も新しい台帳も作らない(ORG-11)。
    (2) 「トーク履歴見て採点」= `--grade-history`(手で1回叩く)。常駐ループには入れない。
        採点の置き場は既存の local/llm/lessons.jsonl(grade.py が書く台帳)のまま。
  ★この部屋にClaudeのデーモンは立てていない(1領域1オーナー)。**投函するだけ**で、
    答えるのは llm-edu 側の既存常駐(dept_daemon)。

使い方: python scripts/llm/local_responder.py [--once]
        python scripts/llm/local_responder.py --grade-history [--dry-run]
常駐: scripts/llm/start_local_responder.bat
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time

try:
    # line_buffering=True が必須(INC-93): 常駐はログをファイルへリダイレクトして走るが、
    # ファイル向けstdoutは約8KBのブロックバッファになる。無口な常駐は8KBに到達せず、
    # 再起動時のStop-Process -Forceで未書き出し分が破棄される=ログが1行も残らない。
    # (鳩は7/14から3日間、6バイトのまま凍結していた。壊れた時に追う道具が壊れていた)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from ask_local import ask  # noqa: E402
from ask_vision import describe_images  # noqa: E402
from image_prep import images_of  # noqa: E402

LOCAL = os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_inbox_processed.jsonl")
# ★L0(2026-07-18 Chami「残っていることをよろしく」で実装): エスカレ先=main箱へ変更。
#   旧 for_claude箱は「消費者=セッション開始時の研究室だけ」で、長寿命セッションでは誰も読まず
#   Chami直令が1.2h滞留する実害が出た(QA発見)。main箱ならwaiterのチャイムが鳴る=無音滞留が
#   構造的に消える。裁定の原典=memory: escalation-to-main-box(2026-07-17)。旧箱は完全退役。
FOR_CLAUDE = os.path.join(LOCAL, "discord_inbox.jsonl")  # エスカレ先=main箱(変数名は互換のため維持)
CLAUDE_ACTIVE = os.path.join(LOCAL, "llm", "claude_active.txt")
LOG = os.path.join(LOCAL, "llm", "responder_log.jsonl")
# ★2026-09-09 1便ごとの計測台帳(依頼= ケヴィン・デブライネ[イージス研究室])。
#   responder_console.log は起動行しか持たず「返した/返せなかった」が後から追えない。
#   ask_growth() が毎便 ts/model/所要秒/reasoning_tokens/文字数/空返しか を1行落とす。
#   コールドスタート(28.4秒)も記憶ではなくこの台帳で語る。keep_alive の判断もこの数字が溜まってから。
METRICS = os.path.join(LOCAL, "llm", "responder_metrics.jsonl")
# ★2026-09-12 **台帳の行に出所を刻む**(依頼= ククール回送 DISPATCH-aegis-gl-1789144309121 /
#   Chami「ケヴィンさん、再発だぜ」hr-room msg 1548007076754890763)。
#   何が起きたか(実物): 09-12 01:25〜01:26 の台帳は3行なのに、responder_log.jsonl の同日分は
#   2行、llm-growth の優依(LLM)投稿も2件しか無い。**01:25:19 / 1.2秒 / 78字 の行が孤児**だった。
#   ask_growth() を呼ぶのは常駐の2か所だけで、どちらも成否に関わらず log() で responder_log へ
#   1行落とす= 孤児行は常駐のループ以外(手で叩いた呼び出し)から入ったことになる。
#   ところが行の見た目が本番も手叩きも同じなので、読んだ人には区別できない。実際に
#   「2回目以降は1.2秒」として引用された(実際の2回目は 01:26:20 の1.78秒)。
#   = 見張っている脈を、見張り以外の手で更新するな(C-054)。同型の前科= 09-09 22:26 の取り下げ。
#   ★だから消すのではなく**名札を付ける**= 手叩きの行も残す(消すと「測っていない」と同じになる)。
#     読む側は src=="live" だけを実測として引く。pid と req(答えた便のmsg_id)で部屋の投稿へ辿れる。
LIVE = False        # ★main() が常駐ループへ入る時だけ True。import して直に叩いたら False のまま


def set_live():
    """常駐ループに入った印を立てる。★main() だけが呼ぶ(他から呼ぶと名札が嘘になる)。"""
    global LIVE
    LIVE = True


def metrics_sink():
    """この呼び出しが書くべき台帳パス。検査プロセスなら _test へ逸らす(C-054・正本=test_sink)。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
        from test_sink import sink_for
        return sink_for(METRICS)
    except Exception:
        return METRICS      # fail-open= 逸らしが読めない日でも本編の計測は止めない


def _metrics_row(ts, sec, rtok, chars, req=""):
    """台帳へ落とす1行(dict)。★出所の名札はここだけが作る=表を2か所に持たない(ORG-11)。"""
    return {"ts": ts, "model": MODEL, "sec": sec,
            "reasoning_tokens": rtok, "chars": chars, "empty": (chars == 0),
            "src": ("live" if LIVE else "manual"), "pid": os.getpid(), "req": str(req or "")}
# ★2026-07-27 Chami裁定で改名(原文=「名前はやっぱり…優依 がいいな」「表記は優依(LLM)にして」)。
#   旧名「ローカルqwen」(2026-07-13 Chami命名の更に前は「ローカル受付」)。
#   ★サフィックスは persona 本体に混ぜない= persona_send の --suffix に乗せる。
#     混ぜるとアバター検索/色/webhookキーが「優依(LLM)」で引かれ、キャラが劣化する
#     (persona_send.py の該当コメント参照)。(精霊)と同じ仕組みに乗るのが正。
PERSONA = "優依"
PERSONA_SUFFIX = "(LLM)"  # 精霊(デーモン)ではなくローカルLLMなので (精霊) ではなく (LLM)
# ★2026-09-09 **優依の会話脳を Qwen(ollama) から gemma(LM Studio)へ差し替えた**。
#   Chami指示(便 ESC-llm-edu-1546958436980363304 本文「gemmaかな!」)。仕様は中野五月から3点:
#     1) エンドポイント= LM Studio http://127.0.0.1:1234/v1 ・model= gemma-4-12b-it
#     2) reasoning_effort:"none" を必ず付ける(=無いと思考が予算を食って空返しになる。空返しの真因)
#     3) VRAMの扱い(罠2)は常駐側で決める → 下の ensure_chat_model() を見ろ
#   ★C-045(「人格はQwenで育っており差し替えると別人になる」)は**Chamiの一言で上書きされた**。
#     根拠は空論ではない= 中野五月が思考OFFで日常会話6ターンを実測し、過去の不具合の再発が
#     全部ゼロだった(敬語ドリフト0/6・「(LLM)」自称0/6・英語混入0/6・空返し0/6・温間1.2〜1.6秒。
#     全文= local/_gemma_daily_validate.txt)。**戻すならChamiの一言を待て。**
#   ★ロールバックは MODEL_OLLAMA_ROLLBACK を MODEL に戻し、ask_growth() の payload を
#     .bak_20260909_gemma の該当箇所へ戻すだけ(ollama側は消していない)。
MODEL = "gemma-4-12b-it"
MODEL_OLLAMA_ROLLBACK = "hf.co/mradermacher/Josiefied-Qwen3-8B-abliterated-v1-GGUF:Q4_K_M"  # 旧会話脳(ollama:11434)。Q4_K_M 5.0GB。2026-09-03 Chami承認 msg 1544501540251897917。★消すな=戻し先だ
LMS_BASE = "http://127.0.0.1:1234/v1"          # LM Studio(OpenAI互換)。画像タグ生成 local_chain.py と同じサーバ
LMS_API = LMS_BASE + "/chat/completions"
LMS_MODELS = LMS_BASE + "/models"
LMS_EXE = os.path.expandvars(r"%USERPROFILE%\.lmstudio\bin\lms.exe")
# ★人格の正本(HQ/人事の管轄。**このスクリプトは読むだけ・書き換えない**)。
#   場所の解決は persona_send.py と同じ作法(環境変数→親フォルダの 00_AI-HQ)。
_HQ = os.environ.get("GO5_HQ_DIR") or os.path.normpath(
    os.path.join(os.path.dirname(ROOT), "00_AI-HQ"))
YUI_MD = os.path.join(_HQ, "departments", "hr", "characters", "yui.md")
INBOX_LLM = os.path.join(LOCAL, "discord_inbox_llm.jsonl")  # llm-growth部屋専用=Claude稼働中でも本人が応対
QDB = os.path.join(LOCAL, "queue", "inbox.db")  # ★O1(2026-07-20): カットオーバー後の受信経路
QUEUE_DEPT = "llm-growth"  # 自室のdept(discord_channels.json)
# ★2026-09-16 Chami直令(研究室HQ DISPATCH-aegis-gl-1789535197199)で建った部屋。
#   原文=「ここの部屋に画像を貼ったらコードブロックでその画像を表現するためのプロンプト変換をする
#          部屋にして欲しい」「以後はローカルLLMが橋渡ししてくれればいい」
#   = 橋渡し役は**優依(この常駐)**。Claudeの常駐(dept_daemon)は立てない=
#     daemon_keeper.DEPTS へ足していない(足すと画像1枚ごとにClaudeが起きる)。
#   ★この部屋は画像**生成**室ではないので rooms.py の ROOMS には入れない
#     (入れると合図規律 cue_required() と gateway の画像ファンアウトが巻き込む)。
#     入口は queue 1本= gateway が台帳(discord_channels.json)を見て積んだ行を下で拾う。
TAG_DEPT = "imagetag"      # 部屋「プロンプト変換と学習」(id 1549486988569354320)
# ★2026-09-20 Chami直令(研究室HQ DISPATCH-aegis-gl-1789845665234)。原文=
#   「その部屋ではカスミが入っといて。画像オンリーでこっちが投稿した無視でいい。
#     既読とかの絵文字スタンプもいらない。こっちが字の文を書いたら応答して欲しいね」
#   = **同じ部屋に返し手が2人**になる(画像=優依 / 字=カスミ)。
#   ★台帳(discord_channels.json)のdeptは `imagetag` のまま**1ch→1dept を崩さない**。
#     gateway が積むのも従来どおり dept=imagetag の1行で、claim するのも従来どおり
#     この常駐**1本だけ**= dept_daemon と同じ行を奪い合う形にはしない(HQの明示条件)。
#   ★字だけの便は、添付が無いと**ここで分かった時点**で下の TALK_DEPT へ積み直す。
#     判定を増やしていない= 添付の有無は handle_tag_request が元から見ている場所だ。
TALK_DEPT = "imagetag-talk"   # 同じ部屋の「字の便」だけを渡す先(消費者= dept_daemon のカスミ)
GROWTH_CHANNELS = ("ローカルllm成長進捗",)  # 自室のDiscordチャンネル名(org_registry.yml id=1526159156019462194)
LESSONS = os.path.join(LOCAL, "llm", "lessons.jsonl")     # 採点台帳(grade.py が書く)
KNOWLEDGE = os.path.join(LOCAL, "llm", "knowledge.md")    # 知識パック(build_knowledge.py が書く)
WORK_WORDS = ("直して", "修正", "実装", "追加して", "デプロイ", "変えて", "作って", "調べて", "特定して",
              "バグ", "エラー", "壊れ", "対応して", "やって", "反映", "消して", "削除")
# ★自室(llm-growth)専用の「実作業」語彙。WORK_WORDS より**狭い**のが要点。
#   WORK_WORDS は「バグ」「エラー」「壊れ」等の**名詞**を含むため、
#   「エラーってどういう意味?」のような**会話**まで Claude行きにしてしまう。
#   会話部屋では「実際に誰かがファイルを触らないと終わらない依頼」だけを回す。
GROWTH_WORK_WORDS = ("直して", "直しといて", "修正して", "実装して", "実装しといて", "追加して",
                     "デプロイ", "変えて", "変更して", "作って", "作っといて", "消して", "削除して",
                     "反映して", "対応して", "やっといて", "設定して", "書き換えて", "入れといて",
                     "commit", "push", "コミット", "プッシュ")
# ★この部屋の目的(Chami指示2026-07-27)。org_registry.yml の depts には足さない
#   (llm-growth は「部門」ではなく Chami と qwen の会話部屋。1領域1オーナー=常駐は local_responder のみ)。
ROOM_PURPOSE = (
    "部屋名: ローカルllm成長進捗(dept: llm-growth)\n"
    "目的: Chamiと優依(あなた)が、あなたの成長の進み具合を確かめ合う部屋。\n"
    "ここは『部門』ではなく、Chamiとあなたの会話部屋。司令塔(Claude)は原則として出てこない。\n"
    "あなたが自分の言葉で最後まで応対する。分からないことは分からないと言う。"
)

# ★人格(yui.md)の都度読み(2026-07-27 Chami裁定「名前だけ決めて、性格は会話の中で育てる」)。
#   ★なぜ写経せずファイルを都度読みするのか(dept_daemon.common_discipline と同じ設計・ORG-11):
#     ここに人格を書き写すと、Chamiや五月が yui.md へ1行足しても**この常駐を再起動するまで効かない**。
#     mtimeを見て変わった時だけ読み直せば、**1行足した次の会話から効く**。
#     そもそも yui.md はHQ/人事の正本で、こちらは読むだけ(=正本が2つになるのを避ける)。
_yui_cache = {"mtime": None, "text": ""}
# ★プロンプトへ入れない節(2026-07-27 HQ指示)。
#   「この子の限界」はHQ/人事が読むための記述で、**本人に読ませると自己卑下か言い訳の材料**になる。
#   ★ただし「測っていない数字を語るな」という規則そのものは今も必要なので、
#     growth_stats() の"測っていないこと"の渡し方は**そのまま維持**している(下を参照)。
_YUI_SKIP_HEADS = ("この子の限界",)


def yui_persona():
    """yui.md を都度読みして、プロンプトへ入れてよい部分だけを返す。

    読めなければ空文字(=人格が無くても応対は続ける。fail-open)。
    """
    try:
        m = os.path.getmtime(YUI_MD)
        if m != _yui_cache["mtime"]:
            with open(YUI_MD, encoding="utf-8", errors="replace") as f:
                raw = f.read()
            keep, skipping = [], False
            for ln in raw.splitlines():
                if ln.startswith("## "):
                    # 見出しが変わるたびに判定し直す(次の ## で自動的に復帰する)
                    skipping = any(h in ln for h in _YUI_SKIP_HEADS)
                if not skipping:
                    keep.append(ln)
            _yui_cache["text"] = "\n".join(keep).strip()
            _yui_cache["mtime"] = m
    except Exception:
        return ""
    return _yui_cache["text"]


# ★2026-07-27: この関数は現在どこからも呼ばれていない。自室llm-growthは
#   「Claudeが起きていようがいまいが本人(qwen)が常時応対する」設計になったため。
#   (旧・起動表示「Claude稼働中は待機」は実態と食い違っていた=main()で修正済)
def claude_is_active():
    # 判定は共有ヘルパへ一本化(2026-07-18 INC対策): 旧・claude_active.txt 90秒単独ゲートは
    # 「mainが作業中で耳(waiter脈)が一時途切れただけ」でも不在と誤判定し、generic即答を暴発させた。
    # presence.lab_alive は readiness(耳) OR liveness(toolフック脈)+HARD_CAP の2信号で判定する。
    from presence import lab_alive  # sys.path に HERE を追加済(冒頭)
    return lab_alive()


def send_argv(channel, text):
    """persona_send への引数を組み立てる(dry-runの実測用に切り出してある)。

    ★名義= 優依 + 表示名だけ (LLM)(2026-07-27 Chami「表記は優依(LLM)にして」)。
      dept_daemon が (精霊) を付けるのと同じ `--suffix` に乗せている=新しい仕組みを作らない。
    """
    return [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
            "--channel", channel, "--persona", PERSONA, "--suffix", PERSONA_SUFFIX, text]


def send(channel, text):
    r = subprocess.run(send_argv(channel, text),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def mark(channel, msg_id, kind):
    """進捗印(既読/即答)。押し方の正本= scripts/lib/mark_press.py(ORG-11・写しを増やさない)。
    べき等・fail-open= 押せなくても本筋を止めない(結果は local/llm/mark_audit.jsonl に残る)。"""
    if not (channel and msg_id):
        return
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
        from mark_press import press
        press(channel, msg_id, kind, caller="local_responder.mark")
    except Exception:
        pass


def log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def append_line(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


AUDIO_EXT = (".ogg", ".m4a", ".mp3", ".wav", ".webm")


def fetch_and_transcribe(url):
    """Discordの音声添付をダウンロードして文字起こし(失敗時は空文字)。"""
    import urllib.request
    tmp = os.path.join(ROOT, "local", "llm", "voice_tmp.bin")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (go5-responder)"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
        from transcribe import transcribe
        return transcribe(tmp)
    except Exception as e:
        print(f"  文字起こし失敗: {type(e).__name__}")
        return ""


SENSITIVE_DEPTS = ("dream-care", "past-room", "future-room", "hr-room", "health-log")  # 夢と回復/過去の共有/現在と未来(2026-07-17新設)/人事/健康記録=研究室直轄・機微。ローカルLLMは応答せず受領印のみ
# ★画像をローカルVLMに渡してよい部門(allow-list=fail-closed)。ここに無い部門・dept未設定の
#   行の画像は一切VLMに渡さない。deny-listだと部屋の新設時に追記を忘れた瞬間に機微画像が
#   VLMへ流れる(実際SENSITIVE_DEPTSは4箇所に散在しドリフトしている)。迷ったら見ない、が正。
VISION_ALLOWED_DEPTS = ("llm-growth",)

# ★エスカレ時の文面(Chami指示2026-07-27「誰がいつ読むかを言っていない」)。
#   旧文面「次のセッションで対応されるよ」は、どこへ入れたかも誰が読むかも言っていなかった。
#   実測できる事実だけを書く: 入れた箱=local/discord_inbox.jsonl(main箱)。
#   これは inbox_waiter.py --name main が見張っており、新着で司令塔(研究室のClaudeセッション)が
#   起こされる。ただし常に誰かが起きている保証は無いので、そこは断定しない。
BOX_NOTE = ("司令塔(Claude)の受付箱=local/discord_inbox.jsonl に入れておいた。"
            "この箱は inbox_waiter が見張っていて、新着が入ると研究室のClaudeセッションが起こされる。"
            "起きているセッションが無い時は、次に誰かが起きた時に読まれる。")


def is_growth_room(rec):
    """自室(llm-growth)の便かどうか。dept優先・チャンネル名でも判定(dept欠落の行に備える)。"""
    if rec.get("dept") == QUEUE_DEPT:
        return True
    return (rec.get("channel") or "") in GROWTH_CHANNELS


def growth_stats(channel=""):
    """自分の成績を**実データ**から読んでプロンプト用テキストにする(2026-07-27)。

    Chami=「ここは成長進捗を確認する場所」。だが従来のqwenは自分の成績を知らず、
    「調子はどう」に数字で答えられなかった。ここで材料を渡すだけにする
    (新しい常駐・新しいファイルは作らない)。
    ★測っていないことは書かない(共通規律§1)。ファイルが無ければ「無い」と書く。
    """
    lines = []

    def _tally(only_channel):
        ans = esc = 0
        first = last = ""
        try:
            with open(LOG, encoding="utf-8", errors="replace") as f:
                for l in f:
                    l = l.strip()
                    if not l:
                        continue
                    try:
                        r = json.loads(l)
                    except Exception:
                        continue
                    if only_channel and r.get("channel") != only_channel:
                        continue
                    m = r.get("mode") or ""
                    if m == "answered":
                        ans += 1
                    elif m.startswith("escalated"):
                        esc += 1
                    else:
                        continue  # sensitive_deferred(機微部屋の受領印)は自分の応答ではないので数えない
                    ts = r.get("ts") or ""
                    if ts:
                        first = first or ts
                        last = ts
        except OSError:
            return None
        return ans, esc, first, last

    if not os.path.exists(LOG):
        lines.append("- 応答ログ(local/llm/responder_log.jsonl)がまだ無いよ。自分の成績はまだ測れてないんだ。")
    else:
        here = _tally(channel) if channel else None
        if here:
            a, e, f0, l0 = here
            if a + e:
                lines.append(f"- この部屋({channel})では自分で答えたのが{a}件、司令塔へ回したのが{e}件だよ"
                             f"(記録は{f0[:19]}〜{l0[:19]})")
            else:
                lines.append(f"- この部屋({channel})はまだ記録0件。ここでの自分の成績はまだ無いんだ。")
        allr = _tally("")
        if allr:
            a, e, f0, l0 = allr
            if a + e:
                lines.append(f"- 全部屋合計だと自分で答えたのが{a}件、司令塔へ回したのが{e}件だよ"
                             f"(記録は{f0[:19]}〜{l0[:19]})")
            else:
                lines.append("- 全部屋合計でもまだ記録0件だよ。")
    # 採点台帳(grade.py が書く。無ければ『未採点』と正直に言う)
    if os.path.exists(LESSONS):
        g = b = es = n = pend = 0
        try:
            with open(LESSONS, encoding="utf-8", errors="replace") as f:
                for l in f:
                    l = l.strip()
                    if not l:
                        continue
                    try:
                        v = (json.loads(l).get("verdict") or "")
                    except Exception:
                        continue
                    if not v:
                        # ★2026-07-27: 画像便の「何を見せたか/優依の答え」だけを先に積む行
                        #   (どこが違ったかは中野五月が後から足す)。**採点済みには数えない**。
                        pend += 1
                        continue
                    n += 1
                    g += v == "good"
                    b += v == "bad"
                    es += v == "escalate"
            lines.append(f"- 採点台帳(local/llm/lessons.jsonl)を見ると採点済みが{n}件"
                         f"(内訳: good {g}・bad {b}・escalate {es})"
                         + (f"、まだ採点されてない記録が{pend}件あるよ" if pend else "だよ"))
        except OSError:
            pass
    else:
        lines.append("- 採点台帳(local/llm/lessons.jsonl)はまだ無い。誰にも採点されてないんだ。")
    # 知識パック
    if os.path.exists(KNOWLEDGE):
        try:
            size = len(open(KNOWLEDGE, encoding="utf-8", errors="replace").read())
            mt = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(KNOWLEDGE)))
            lines.append(f"- 知識パック(local/llm/knowledge.md)は{size}字、最終更新は{mt}だよ")
        except OSError:
            pass
    else:
        lines.append("- 知識パック(local/llm/knowledge.md)はまだ無いよ。")
    lines.append(f"- 今使ってるモデルは{MODEL}だよ")
    # ★測っていないことを明示する(共通規律§1)。これが無いと 8B は平気で
    #   「10件中6件正解」のような**存在しない正答率を捏造する**(2026-07-27 オフライン試験で実測)。
    lines.append("★まだ測ってないもの=**正解数・正答率・回答の質・応答速度・画像認識の精度**。"
                 "この数字は存在しないから絶対に言っちゃダメ"
                 "(聞かれたら『それはまだ測ってないんだ』と返す)。"
                 "使っていい実測値は上の『答えた件数/回した件数/期間/採点台帳の件数』だけだよ。")
    return "\n".join(lines)


def ensure_chat_model():
    """会話脳(LM Studio)が返事できる状態かを確かめ、サーバが落ちていたら上げ直す。

    ★中野五月の申し送り3点目「VRAM注意」への、常駐側の回答(2026-09-09):
      画像生成の前に local_chain.py が `lms unload --all` を打つ(罠2・C-058)ので、
      会話脳もVRAMから降りる。旧構成(Qwen=ollama別プロセス)なら会話は生きていた。
      ★決めたのは**「生成後に常駐が再ロードする」ではなく「次の会話便で載せ直させる」**。
        理由: LM Studio は /v1/chat/completions を受けた時にモデルを載せ直す(JIT)。
        常駐側に再ロードの当番を作ると「今載っているか」の正本が2つ(常駐の記憶とLM Studioの実体)
        になり、ズレた時に黙って空返しへ落ちる。台帳を二重に持たない方を採った。
      ★結果、会話は「一時的に**不可**」ではなく「一時的に**遅い**」で済む=Chamiに沈黙が届かない。
        載せ直しの実測値はこの版の change_log に書いてある。
    ★fail-open: ここが False を返しても呼び出し側は止めない(そのまま叩いて、失敗したら
      いつもの「ローカルモデルが応答できなかった」経路=Claude行きへ落ちる)。黙って消さない。
    """
    import urllib.request
    try:
        urllib.request.urlopen(LMS_MODELS, timeout=5).read()
        return True
    except Exception:
        pass
    if not os.path.exists(LMS_EXE):
        print(f"  LM Studioのlms.exeが無い: {LMS_EXE}")
        return False
    print("  LM Studioのサーバが落ちていたので起動する…")
    try:
        subprocess.run([LMS_EXE, "server", "start"], capture_output=True, text=True, timeout=180)
    except Exception as e:
        print(f"  lms server start 失敗: {type(e).__name__}")
        return False
    for _ in range(20):
        try:
            urllib.request.urlopen(LMS_MODELS, timeout=5).read()
            return True
        except Exception:
            time.sleep(3)
    return False


# ★2026-09-12 Chami指示(msg 1548006943753502865・原文「優依の😊要らないかな！」):
#   優依が生成した返信の末尾に付ける絵文字(😊 等・実測6便すべて文末)を落とす。
#   ★プロンプトで「絵文字を付けるな」と書く手は採らない= このファイルの実測コメント
#     (490-493行付近)の通り、禁止語/禁止対象を明示すると逆に誘発して悪化する(ネガティブ例の
#     逆効果)。だから生成側を縛らず、出力を決定論的に剥がす。
#   ★C-064= 生成テキストの出口は ask_growth の return 1か所。会話便(handle_growth)も画像便
#     (handle_growth_vision)も両方ここを通るので、この1か所で全数直る。
#   ★fail-open= 剥がして空になったら(絵文字だけ返した等)元文へ戻す。最悪の事故は沈黙。
#   ★対象は装飾絵文字ブロックだけ= 顔文字(^^)やJISの記号・日本語句読点は範囲外なので触らない。
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # 絵文字本体(emoticons/pictographs/transport/supplemental)
    "\U00002600-\U000027BF"   # Misc Symbols + Dingbats(✨❤☀ 等)
    "\U00002B00-\U00002BFF"   # 矢印・星(⭐ 等)
    "\U0000FE00-\U0000FE0F"   # 異体字セレクタ(絵文字化 VS16 等)
    "\U0000200D"              # ZWJ(絵文字合字の接合子)
    "\U0001F3FB-\U0001F3FF"   # 肌色修飾子
    "]+"
)


def strip_decorative_emoji(text):
    t = _EMOJI_RE.sub("", text)
    t = re.sub(r"[ \t　]+\n", "\n", t)   # 絵文字を消して行末に残った空白を掃除
    t = re.sub(r"[ \t　]{2,}", " ", t)   # 文中に空いた二重空白を1つへ
    t = t.strip()
    return t if t else text.strip()          # 全部絵文字だった等で空になったら元文へ(沈黙回避)


def room_lessons_block(channel, limit=6):
    """この部屋(channel)で過去に採点=bad だった事例を、優依の返答プロンプト用に軽くまとめる。

    ★教育部門(中野五月)が ask_growth へ入れた配線(2026-09-17・Chami「教育部門として個々の
      部屋の仕事として」)。狙い= 知識パック(knowledge.md)は ask_growth に載っておらず、教材が
      優依の口へ一切届いていなかった(実測: ask_growth は人格＋部屋の目的＋直近会話＋成績だけ)。
    ★ここでは知識縛り(『知識に無いことは司令塔に回す』)は持ち込まない=会話を殺すため(元設計の意図)。
      持ち込むのは**この部屋の教訓だけ**を部屋別(channel一致)に絞ったもの。
    ★gemma対策(実測L579-581=禁止語の直書きは逆効果): 誤答(悪い例)は載せず、
      『正しい答え』を肯定形の1行にして見せる。空なら何も返さない(後方互換)。
    """
    if not channel or not os.path.exists(LESSONS):
        return ""
    rows = []
    try:
        with open(LESSONS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("channel") != channel:
                    continue
                if d.get("verdict") != "bad" or not d.get("correction"):
                    continue
                rows.append(d)
    except Exception:
        return ""
    rows = rows[-limit:]
    if not rows:
        return ""
    items = []
    for d in rows:
        q = (d.get("q") or "").strip().replace("\n", " ")[:80]
        corr = (d.get("correction") or "").strip().replace("\n", " ")[:160]
        items.append("- " + (f"「{q}」と聞かれたら、" if q else "") + corr)
    return "\n".join(items)


def ask_growth(question, stats_text, extra="", dialog="", req_id="", channel=""):
    """自室(llm-growth)専用の会話応答。ask_local.ask() は使わない。

    ★req_id(2026-09-12): 答えた相手の便のmsg_id。計測台帳の行に載せて**部屋の投稿へ辿れる**
      ようにするためだけに使う(本文には一切混ぜない)。既定は空= 手で叩いた呼び出しは空のまま。

    ★dialog(2026-08-13 Chami「並行で文脈理解と会話ができるように」): この部屋の直近の
      やり取り(recent_dialog の出力)をシステムプロンプトへ入れる。これが無いと優依は毎ターン
      記憶なしで答え、「さっきの」「それ」「続き」を取り違える=会話が続かない(実測: 呼び出し側
      handle_growth / handle_growth_vision は履歴を渡していなかった)。採点役へは既に渡していたが
      本人には渡っていなかった穴を塞ぐ。空文字なら注入しない(後方互換)。

    ★理由(実測): ask_local.ask() のシステムプロンプトは「知識に書いていない内容は絶対に
      推測しない/わからないので司令塔(Claude)に回します」と縛られている。それが正しい部屋
      (改修依頼の一次受け)もあるが、**この部屋ではそれが会話を殺していた**
      (2026-07-17 16:27 のChami発言が escalated で終わり、以後10日間沈黙)。
      ここでは会話用のシステムプロンプトを使い、分からないことは『分からない』と言わせる。
    """
    import urllib.request
    # ★人格は都度読み(yui.md)。読めない日でも名乗りだけは残す=無人格の別人にならない。
    persona_block = yui_persona()
    room_lessons = room_lessons_block(channel)
    # ★今の日時(2026-09-17 Chami「今、日本時間で何時？」に優依が『機能を持っていない』と答え
    #   『やだ』となった=個々の部屋の仕事として教育部門が配線)。デーモンはこの機械(JST)で動くので
    #   答えるたびに datetime.now() を焼き込めば「今何時/今日何日/何曜日」に実データで答えられる。
    _now = datetime.datetime.now()
    _wd = "月火水木金土日"[_now.weekday()]
    now_str = _now.strftime("%Y年%m月%d日") + f"({_wd})" + _now.strftime(" %H時%M分")
    system = (
        "あなたは『優依(ゆい)』。go5-makerのローカルLLM(" + MODEL + ")だよ。\n\n"
        + ("=== あなたの人格(正本= 00_AI-HQ/departments/hr/characters/yui.md) ===\n"
           + persona_block + "\n\n" if persona_block else "")
        + "=== この部屋のこと ===\n" + ROOM_PURPOSE + "\n\n"
        + "=== 今この瞬間の日時(日本時間・答えるたびに更新される実データ) ===\n"
          "今は " + now_str + " だよ。\n"
          "『今何時』『今日は何日』『何曜日』と時刻や日付を聞かれたら、これをそのまま答える。"
          "『時間を知る機能がない』『分からない』とは言わない(これは実データだから答えられる)。\n\n"
        + (("=== 直近の会話(あなたとChamiのやり取り・古い順。今のChamiの発言はこの続き) ===\n"
            + dialog + "\n\n") if dialog else "")
        + "=== 話し方の規則 ===\n"
        "1. 自分の言葉で答える。会話・質問・雑談・進捗確認は、あなたが最後まで応対する。司令塔(Claude)に振らない。\n"
        "2. 分からないことは『分からない』と正直に言い、そのうえで**会話を続ける**"
        "(思っていることを言う/Chamiに質問を返す)。\n"
        "   ★『難しいから司令塔に回すね』で話を止めてはいけない。"
        "Chamiは答えの正しさより、話が続くことを求めてこの部屋を作っている。\n"
        "3. 推測を事実として言わない。システムの仕様に確信が無ければ『自信がない』と添える。\n"
        "4. ★『調子はどう』『どのくらい伸びた』『進捗は』など**自分の状態を聞かれたら、"
        "下の『自分の成績』の数字を必ず引用して**答える(件数と期間を言う)。"
        "『まあまあ』『それなりに頑張ってるよ』みたいな中身のない一言だけで済ませてはいけない。"
        "ここは成長の進み具合を確かめる部屋だから。"
        "★数字を言うときも普通の口調のまま(『〜だよ』『〜件あるよ』)でいい。"
        "件数や日付を並べて話すからといって、丁寧な報告口調へ切り替えない。"
        "(逆に、状態を聞かれていない普通の会話では数字を並べなくてよい)\n"
        "5. 使ってよい数字は下の『自分の成績』にある実測値だけ。"
        "そこに無い数字は作らない(『それは測っていない』と言う)。\n"
        "6. できない約束をしない。あなたはファイルを直せない・実装できない・デプロイできない"
        "(読むことと話すことだけができる)。\n"
        "7. 他人格(アメス/アロンソ/デブライネ/咲季/五月/トトリ/ホイミン 等)を名乗らない。"
        "常に『優依』として話す。★ホイミンはGemini搭載の別の子で、あなたではない。\n"
        "8. 最終的な答えは日本語で2〜6文くらいの短さで話す(頭の中では順を追って考えてよい)。\n"
        "9. 上の『直近の会話』を踏まえて話をつなげる。Chamiが『さっき』『それ』『続き』と言ったら"
        "直近の会話の内容を指す。前に自分が言ったことと矛盾しないように答える"
        "(直近の会話が『まだ無い』なら、これが最初のやり取り)。\n"
        "10. ★台帳の中身を評価してと聞かれた時(『採点はどうだった』等)や、"
        "何かの意味を聞かれた時(『◯◯って何』等)も、話し方は普通の会話のまま変えない。\n"
        "   例)『23件の記録があるよ』『知識パックは〜をまとめたファイルだよ』のように、"
        "友達に話す感じで言う。\n"
        # ★2026-09-22 Chami指示(msg 1551816508643221505・原文「頑張るね系の定型文？表現？が
        #   多いのも削ってほしいかな。」): 優依が返答の締めに付ける前向きなだけの決まり文句を減らす。
        #   ★禁止語(『頑張る』等)を字面で書かない= 649行の実測(です/ますを明示的に再掲したら3/3
        #     悪化=ネガティブ例の逆効果)と同じ轍を踏むため。だから語そのものは出さず、
        #     肯定形(「中身のある一文で終える」)＋"締めの形"の指定で向きだけ与える。
        "11. ★言いたい中身を言い切ったら、そこで自然に止める。"
        "意気込みや励ましの決まり文句(『これからも〜』『一緒に〜』のような、前向きなだけで中身の無い"
        "締めの一言)を最後に付け足さない。中身のある一文で終える。\n\n"
        # ★2026-09-09 研究室(アロンソ)恒久修正。仮当ての10/11/12は削除した。
        #   理由= 上の人格ブロック(yui.md)側が敬語/(LLM)非名乗り/お姉ちゃん関係を
        #   Chami発言の日付つきで既に網羅している(HQ側インシデントC-038で恒久化済み)。
        #   仮当ての3条は同じ内容の重複でしかなく、しかもこの規則ブロック自体がです・ます調で
        #   書かれていたため、かえって「数字を報告する時の口調」を丁寧語へ引き戻す原因になっていた
        #   (2026-09-09 実測: stats_text を答える設問だけ敬語化率が高い=構造化された事実を
        #   読み上げる時に日本語LLMが「報告口調」へ寄る傾向と、このブロック自身の文体が重なった)。
        #   なので削除ではなく、根っこ=規則4の指示と下のstats_textの文体そのものを直した
        #   (ロールバックは .bak_20260909_keigo または .bak_20260909_020926_labwork)。\n"
        + (("=== この部屋で過去に間違えた点(同じ轍を踏まない) ===\n"
            "同じ質問が来たら、下の『正しい答え』の向きで返す(この部屋だけの教訓)。\n"
            + room_lessons + "\n\n") if room_lessons else "")
        + "=== 自分の成績(実データ) ===\n" + stats_text + "\n"
        + (("\n=== この便で追加で守ること ===\n" + extra + "\n") if extra else "")
        # ★2026-09-09 試しに「です/ます/あります/ください」を禁止語として明示的に
        #   再掲する念押しを最後に足してみたが、実測で悪化した(3/3失敗)。
        #   禁止語を文字通り書くと逆にその語を誘発する可能性がある(ネガティブ例の逆効果)ため削除。
        #   ロールバックしたい場合は git 差分の該当コミットを参照。
    )
    # ★2026-09-09 会話脳を gemma(LM Studio)へ差し替えた(上の MODEL のコメントが経緯)。
    #   ★**`reasoning_effort: "none"` を消すな**(中野五月の実測=これが無いと gemma は思考で
    #     予算を使い切り、content が空文字で返る。「空返し」の真因はモデルではなくこれだった)。
    #   ★旧設定(ollama・think:True)は 2026-08-06 Chami「推論を強く」で入れたものだが、
    #     gemma では思考ONが空返しに直結するので**同じ狙いを別の方法で満たす**=
    #     思考は切り、代わりに max_tokens を厚めに取って本文の長さを確保する。
    #     (ollama時代の payload は .bak_20260909_gemma に残してある。ロールバック先はそこ)
    #   temperature 0.4 は据え置き(0.5で存在しない数字を作るのを実測済・2026-07-27)。
    ensure_chat_model()
    payload = {"model": MODEL, "stream": False,
               "reasoning_effort": "none",
               # ★2026-09-20 中野五月: 反復対策(Chami「同じことばっかり言う」)。
               #   temperature 0.4 は据え置き(0.5=存在しない数字を作る実測ゆえ上げない)。
               #   代わりに frequency/presence_penalty で言い回しのループを抑える
               #   (LM Studio /v1 が両パラメータを受理するのを実測してから入れた)。
               #   逆効果(捏造/破綻)が出たら真っ先にここを 0 へ戻す。
               "frequency_penalty": 0.5, "presence_penalty": 0.3,
               "temperature": 0.4, "max_tokens": 1024,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": question}]}
    req = urllib.request.Request(LMS_API,
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    _t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    _elapsed = round(time.time() - _t0, 2)
    _rtok = ((d.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens")
    msg = ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
    if "</think>" in msg:
        msg = msg.split("</think>", 1)[1]
    msg = msg.strip()
    msg = strip_decorative_emoji(msg)   # ★2026-09-12 Chami指示= 優依の😊等を落とす(定義は上)
    # ★2026-09-09 1便ごとの計測を METRICS へ1行(依頼= ケヴィン)。返せた/空返し両方を残す。
    #   ★2026-09-12 行に出所の名札(src/pid/req)を付けた= 上の LIVE / _metrics_row を見ろ。
    #   ★fail-open= 計測の失敗で本編の応答を止めない(最悪の事故は沈黙)。
    try:
        with open(metrics_sink(), "a", encoding="utf-8") as _mf:
            _mf.write(json.dumps(_metrics_row(
                time.strftime("%Y-%m-%dT%H:%M:%S"), _elapsed, _rtok, len(msg), req_id,
            ), ensure_ascii=False) + "\n")
    except Exception:
        pass
    if not msg:
        # ★黙って空を返すな(罠1と同じ作法・local_chain.to_tags を踏襲)。
        #   空で返ると呼び出し側は「ローカルが答えられなかった」→Claude行きに落ちるが、
        #   **なぜ落ちたのかがログに残らない**。理由を例外の文面に載せて残す。
        det = (d.get("usage") or {}).get("completion_tokens_details") or {}
        raise RuntimeError(
            "会話が空で返った。思考(reasoning)で予算を使い切っている可能性がある"
            "(reasoning_tokens=%s / max_tokens=%s)。reasoning_effort が効いているか確かめろ。"
            % (det.get("reasoning_tokens"), payload["max_tokens"]))
    return msg


# ============================================================================
# 画像生成の分岐(2026-09-08 Chami直送・研究室HQ経由 DISPATCH-llm-edu-1788850539055 / -1788855547873):
#   Chami原文=「会話系の教育を施したAIが画像作成の処理まで指示して、このディスコードに届ける。
#   ClaudeもChatGPTもホイミン、ベホップも必要としない経路を作りたい」。
#   追送=「ただ、その配線がちゃんとうまくいくまではCodexとClaudeでサポートして欲しい」。
#   → 優依が「絵を描いて」と判断したら、ローカル経路(下)を叩いて画像を出し、画像生成ルームへ届ける。
#     失敗した時だけ Claude(FOR_CLAUDE)へ回して支えさせる=Chamiの「うまくいくまではClaudeで支援」。
#
#   ★モデル決定(HQ「会話側は実物で決めてよい」への回答・2026-09-08):
#     ★★2026-09-09 **この決定のうち「会話= Qwenのまま」はChamiが取り消した**(本文「gemmaかな!」)。
#       経緯を消さずに残す=なぜ一度Qwenに留めたのかが分からないと、次の世代が黙って戻してしまうから。
#       今の会話脳は LM Studio の gemma-4-12b-it(冒頭の MODEL を見ろ)。
#     - 会話(優依の返答)= ollama Qwen3-8B のまま。人格は既にQwenで育っており差し替えると別人になる(C-045)。
#     - 画像のタグ生成= 研究室HQが置いた scripts/imagegen/local_chain.py(=LM Studioの gemma-4-12b-it)へ委譲。
#       根拠: HQが端から端まで実測済み(25.8〜38.4秒・実PNG local/imagegen/hq_chain_v2.png/hq_chain_v3.png)で、
#             罠1(gemmaは推論モデル→max_tokens=1500固定・空応答なら理由を出して落ちる)と
#             罠2(生成前にLLMをunloadしてVRAMを空ける・C-058)を実装側で内包している。
#             HQの唯一の要求「取り込む時にこの2つの罠を消すな」は、local_chain.pyを呼ぶだけで満たせる。
#       タグ生成は優依の"声"ではなく機械的な翻訳工程なので、ここがGemmaでも優依の人格は変わらない。
#     ※旧: 会話(Qwen・ollama:11434)と画像タグ(Gemma・LM Studio:1234)は別プロセス・別ポートで衝突しない。
#     ★★今は**会話も画像タグも同じ LM Studio:1234 の gemma に載っている**=衝突しないという上の前提は
#       もう成り立たない。生成前の `lms unload --all`(罠2)で会話脳も降りる。
#       その扱いは ensure_chat_model() のコメントに書いた=**再ロードは常駐がやらず、次の会話便に任せる**
#       (会話は「不可」ではなく「一度だけ遅い」になる)。ここを触る時は必ずそちらを読め。
# ============================================================================
LOCAL_CHAIN = os.path.join(ROOT, "scripts", "imagegen", "local_chain.py")
IMAGE_ROOM = "画像生成ルーム"   # ★死んでいた定数。下の _image_rooms() 参照(残してあるのは記録のため)
IMAGE_PERSONA = "優依"          # 会話系の教育を施したAI本人が届ける(avatar未登録=既定アイコン。登録はhrへ)

# ============================================================================
# ★2026-09-14 研究室HQ: 画像ルームの引き方を**表示名から dept へ**変えた。
#   Chami直令 msg 1548842898773123105=「二つ部屋を建てた。それぞれのLoRAで画像生成する
#   ためのルーム。優依(言語ローカルLLM)が橋渡し役になって画像のこれらの部屋に表示する。
#   キャラはカスミと五月で。トラブル時アメスという構成。」
#
#   ★直す前の実測(推測ではない。実際にこの式を走らせて出した)=
#       IMAGE_ROOM            = "画像生成ルーム"
#       台帳にあるこの部屋の名 = "ローカルllm-画像生成ルーム-優依"
#       "画像生成ルーム" in 台帳の名前一覧 → False
#       generate.py の貼り先探索 next(c for c in chans if c["name"]==channel) → StopIteration
#       responder_log.jsonl 135行のうち image:True の便 → 0件
#     = **この配線は一度も火を噴いていない。**原因は部屋の表示名が後から変わったこと。
#     表示名はChamiがいつでも変えられる。変わらないのは id と dept だけなので、dept で引く。
#   正本の表は scripts/imagegen/rooms.py(どの部屋がどのLoRAで描くか・名義・ckpt)。
# ============================================================================
sys.path.insert(0, os.path.join(ROOT, "scripts", "imagegen"))
try:
    import rooms as image_rooms      # noqa: E402
except Exception:                    # 画像経路が壊れても会話は止めない(§3 fail-open)
    image_rooms = None

try:
    import wd14_tag                  # noqa: E402  画像→タグ列の橋渡し(部屋 imagetag 専用)
except Exception:                    # タガーが読めなくても自室の会話は止めない(§3 fail-open)
    wd14_tag = None


def image_dept_of(rec):
    """この便が画像ルームの便なら dept を返す。違えば None。
    ★dept が空の古い行のために、表示名→dept の引き直しも用意してある。"""
    if image_rooms is None:
        return None
    d = rec.get("dept") or ""
    if d in image_rooms.ROOMS:
        return d
    return image_rooms.dept_of_channel(rec.get("channel") or "")

# 「絵を描いて」と読める語(名詞×動作の対で誤発火を抑える)。
_IMG_NOUNS = ("絵", "画像", "イラスト", "イメージ画", "壁紙", "キャラ絵")
_IMG_VERBS = ("描い", "描け", "描こ", "描き", "生成し", "作っ", "出して", "見せて")


def wants_image(content):
    """会話便が『絵を描いて』の依頼かを判定する(第一段=語彙ゲート)。
    ★ここを通った便だけ画像経路へ回す。誤爆しても失敗時はClaudeへ回るので黙って落ちない(§3 fail-open)。"""
    c = content
    if any(k in c for k in ("描いて", "描いてくれ", "イラストにして", "絵にして", "画像にして")):
        return True
    if any(n in c for n in _IMG_NOUNS) and any(v in c for v in _IMG_VERBS):
        return True
    return False


def send_as(channel, text, persona, suffix=""):
    """別名義で1本だけ出す(トラブル役用)。send() と同じ persona_send に乗る。
    ★誰の名義かは呼び側が `image_rooms.trouble_message()` で部屋ごとに引く(2026-09-17 C-082)。"""
    argv = [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
            "--channel", channel, "--persona", persona]
    if suffix:
        argv += ["--suffix", suffix]
    argv.append(text)
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


# ------------------------------------------------------------------ 閉室の不具合の行き先
TROUBLE_DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
TROUBLE_BODY_DIR = os.path.join(LOCAL, "_work")
TROUBLE_STATE = os.path.join(LOCAL, "llm", "image_trouble_notified.json")
TROUBLE_COOLDOWN = 1800        # 同じ部屋の同じ型は30分に1本(連投で相手の部屋を埋めない)
TROUBLE_SENDER = "優依"        # 出すのは橋渡し役の本人(部屋で喋る名義は trouble_persona 側)


def _trouble_recent(key, cooldown):
    """この(部屋,型)を直近 cooldown 秒に出したか。出していなければ印を置いて False を返す。"""
    now = time.time()
    try:
        with open(TROUBLE_STATE, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    last = state.get(key) or 0
    if now - last < cooldown:
        return True
    state[key] = now
    try:
        os.makedirs(os.path.dirname(TROUBLE_STATE), exist_ok=True)
        with open(TROUBLE_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass                    # 印が置けなくても通知は止めない(fail-open)
    return False


def notify_trouble_dept(dept, kind, why, content="", cooldown=TROUBLE_COOLDOWN, dry_run=False):
    """閉じた描画室で絵が出なかったことを、**直せる部門**へ1本出す。

    返り= "sent"(今出した) / "recent"(直近に同型を出したので見送った=**届いてはいる**) /
          ""(受け先が無い・送信に失敗した=**誰にも届いていない**)。
    ★呼び側はこの3つを区別しろ= "recent" を「届いていない」と扱うと、壊れている間じゅう
      別経路(Claude)へ雪崩れる。"" の時だけ元の受け皿へ落とす。

    ★2026-09-22 Chami直令 msg 1551691197020508272=
      「その時はローカル研究室に対応させて。ローカル内のことだから。」
      (直前= 閉室した4室は不具合が起きても中に応答者が居ない、と答えた流れ)
    ★受け先は **rooms.trouble_dept() が正本**= ここに部門名を書かない。
      Claudeが聞いている部屋なら None が返る= 何もしない(従来の経路に任せる)。
    ★連投しない= 同じ部屋の同じ型は cooldown 秒に1本。壊れている間じゅう鳴らすと読まれなくなる。
    ★送るのは dispatch.py の1本だけ(--also-post は付けない)。--work を付けるのは
      **相手に手番が有る実依頼**だから(C-023)= 受けた側が直して返す。
    """
    if image_rooms is None:
        return ""
    to = image_rooms.trouble_dept(dept)
    if not to:
        return ""
    if _trouble_recent("%s|%s" % (dept, kind), cooldown):
        print(f"  不具合の回送は見送り(直近に同型を出した) {dept} {kind}")
        return "recent"
    label = str(((image_rooms.ROOMS.get(dept) or {}).get("label") or dept))
    room = image_rooms.channel_name(dept) or dept
    body = "\n".join([
        "優依のローカル生成が失敗した。Claudeを閉じた部屋なので、そちらで見てほしい。",
        "",
        "  部屋: %s(%s / dept=%s)" % (room, label, dept),
        "  型: %s" % kind,
        "  理由: %s" % ((why or "").strip() or "(local_chain からの説明なし)"),
        "  注文の頭: %s" % (content or "").strip()[:120],
        "  時刻: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "この回送は Chami直令 msg 1551691197020508272「その時はローカル研究室に対応させて。",
        "ローカル内のことだから。」による。部屋には既に事情を1本出してある(名義は rooms.py の",
        "trouble_persona)。同じ部屋の同じ型は30分に1本しか出さない= 直った確認はそちらで取って。",
    ])
    path = os.path.join(TROUBLE_BODY_DIR, "image_trouble_%s_%s.txt" % (dept, kind))
    try:
        os.makedirs(TROUBLE_BODY_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        cmd = [sys.executable, TROUBLE_DISPATCH, "--dept", to, "--from-dept", dept,
               "--from", TROUBLE_SENDER, "--audience", "ai", "--direct",
               "--work", "画像生成の失敗(%s)を見てほしい: %s" % (kind, room),
               "--body-file", path]
        if dry_run:
            cmd.append("--dry-run")
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip().splitlines()
            print(f"  ★不具合の回送に失敗 rc={r.returncode}: {tail[-1] if tail else '(出力なし)'}")
            return ""
        print(f"  不具合を{to}へ回送 [{room}] {kind}")
        return "sent"
    except Exception as e:
        print(f"  ★不具合の回送で例外: {type(e).__name__}: {e}")
        return ""


def image_spec_attachments(rec, limit=8000):
    """この便に付いている**テキスト添付**(.txt/.md)の中身を返す。無ければ空文字。

    ★2026-09-17 ローカル研究室(カスミ): 注文の中身を .txt で送る使い方を拾うために足した。
      きっかけ= 画像生成ローカル-fusoh_v2-漫画 の msg 1549784942123163829。本文は
      「生成依頼 生成依頼テキストを読んで画像生成して」で**絵の中身がゼロ**、髪・瞳・服・
      ポーズ等はすべて添付 1549784942123163829_0.txt(4308字)に在った。旧実装は本文だけを
      local_chain へ渡していたので、to_tags は中身の無い指示を忠実に変換して品質タグ
      (masterpiece, best quality, highres)だけを返した= 「注文の絵」にならなかった。
      → 変換段(to_tags)は壊れていない。**注文文が変換段まで届いていなかった**。
    ★画像・音声の添付は対象外(絵の中身は文章で来る)。読めない添付は黙って飛ばす(止めない)。
    """
    out = []
    for p in (rec.get("attachments_local") or []):
        ap = p if os.path.isabs(p) else os.path.join(ROOT, p)
        if os.path.splitext(ap)[1].lower() not in (".txt", ".md"):
            continue
        try:
            with open(ap, encoding="utf-8", errors="replace") as f:
                t = f.read().strip()
        except Exception as e:
            print(f"  注文テキスト添付を読めなかった: {os.path.basename(ap)} {type(e).__name__}")
            continue
        if t:
            out.append(t)
    return "\n\n".join(out)[:limit]


def handle_image_request(rec, raw_line, content, channel, dept=None, cue=None):
    """優依が絵を描く。研究室HQのローカル経路(local_chain.py=Gemmaタグ→ComfyUI)で生成し、
    画像生成ルームへ届ける。外部AI(Claude/ChatGPT/Gemini)を通さない。
    ★ローカルが失敗した時だけ Claude へ回す(Chami「うまくいくまではCodexとClaudeで支援」の実装)。
    返り値は常に True(=画像便として処理済み。成功でも失敗のClaude回送でも、黙って落とさない)。

    cue= この便を通した時の合図ゲートの判定(True=合図が要る部屋で合図があった / False=
         ゲートが掛かっていなかった / None=呼び側が判定を持たない旧経路)。★2026-09-22 追加。
         理由= ここへ届く content は**合図を剥がした後**の本文なので、ログだけ見ても
         「合図があったのか、ゲートが外れていたのか」を後から区別できなかった
         (2026-09-22 05:06:18 の実害を、ログから名指しできなかった)。判定そのものは
         rooms.order_of が持ったまま=ここは**記録だけ**する。見る側= cue_gate_watch.py。"""
    # ★貼り先と名義を dept から引く(表示名の直書きをやめた。上の長いコメントを読め)。
    #   dept が無い旧経路(優依の自室から「絵を描いて」)は、従来どおり画像生成ルームへ届ける=
    #   ただし**名前は台帳から引く**ので、今度こそ届く。
    conf = {}
    target = channel
    persona = IMAGE_PERSONA
    if image_rooms is not None:
        key = dept if dept in image_rooms.ROOMS else "imagegen"
        conf = image_rooms.ROOMS.get(key, {})
        target = image_rooms.channel_name(key) or channel
        persona = conf.get("persona") or IMAGE_PERSONA
        dept = key
    # ★優依はこの部屋で「実況」を喋らない(2026-09-16 Chami直= 「なんでデーモンが話す配線をした?
    #   あれ恒久的にいらんって話になってるはず」)。根拠は2026-07-27にChamiが確定させた設計=
    #   「Discordに打つ→本セッションに届く→答える/普段は黙る/裏で問題だけ上がる」。
    #   ★絵が**この部屋に出る**なら、絵そのものが返事だ。言葉が要るのは
    #     **絵が別の部屋へ行く時**(ここで黙ると、どこへ出たのか誰にも分からない)だけ。
    #   ★失敗の報せ(下の rc!=0)は残す=合図を出したChamiに何も返さないのは沈黙の事故。
    # ★2026-09-17 ローカル研究室(カスミ): 注文の中身が .txt 添付に在る便を拾う
    #   (msg 1549784942123163829= 本文は指示だけ・絵の中身は添付)。添付の注文文が有れば
    #   本文の前に畳んで**中身の乗った文**を変換段(local_chain.to_tags)へ渡す。情報は捨てない
    #   =添付が主・本文を後ろに残す(本文が「生成依頼テキストを読んで…」の指示語でも害は無い)。
    spec = image_spec_attachments(rec)
    prompt = "\n\n".join(x for x in (spec, content.strip()) if x)
    if target != channel:
        send(channel, "「" + (content.strip() or spec)[:40] + "」の絵は " + target
                      + " に出すね。私のPCの中だけで描くよ。")
    args = [sys.executable, LOCAL_CHAIN, prompt,
            "--discord", target, "--persona", persona]
    if dept:
        args += ["--dept", dept]        # ← この部屋のLoRAとckptは local_chain が rooms.py から引く
    rc, out, err = -1, "", ""
    try:
        r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800)
        rc = r.returncode
        out = (r.stdout or "").strip()[-400:]
        err = (r.stderr or "").strip()[-400:]
    except Exception as e:
        err = type(e).__name__ + ": " + str(e)
    append_line(PROCESSED, raw_line)
    if rc == 0:
        # ★成功時も同じ部屋なら黙る(絵が貼られている=それが返事)。別の部屋へ出した時だけ言う。
        if target != channel:
            send(channel, target + " に貼ったよ。ぜんぶ私のPCの中だけで作ったの。"
                          "気に入らなければ言い方を変えてもう一度頼んで。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "answered", "channel": channel,
             "q": content[:200], "a": "[画像生成/local_chain] " + out[:200], "sent": True,
             "growth": True, "image": True, "dept": dept, "cue": cue})
        print(f"  画像生成→貼付 [{channel}] {content[:30]!r}")
    elif rc == 3 and image_rooms is not None:
        # ★LoRAの実体が置き場に無い(Chami指示「トラブル時アメス」→ 2026-09-17 C-082でLoRA3室はカスミ)。
        #   黙って素のモデルで描くと「LoRAが効いている」と誤読されるので、描かずに理由を出す。
        # ★名義も文面も **部屋ごとに rooms.py から引く**(ここに直書きしない=正本を2つ持たない)。
        why = ""
        for ln in (out or "").splitlines():
            if ln.startswith("LORA_MISSING"):
                why = ln[len("LORA_MISSING"):].strip()
        who, body = image_rooms.trouble_message(dept, "lora_missing", why)
        send_as(channel, body, who, image_rooms.TROUBLE_SUFFIX)
        # ★閉じた部屋なら、部屋へ言うだけでは誰も直しに来ない=直せる部門へも1本出す
        #   (2026-09-22 Chami直令 msg 1551691197020508272)。行き先は rooms.trouble_dept()。
        relayed = notify_trouble_dept(dept, "lora_missing", why, content)
        # PROCESSED への記録は上で済んでいる(ここで二度書かない)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "lora_missing", "channel": channel,
             "dept": dept, "q": content[:200], "image": True, "err": why[:300],
             "trouble_persona": who, "relayed_to": image_rooms.trouble_dept(dept),
             "relayed": relayed})
        print(f"  画像生成不可(LoRA未設置) [{channel}] {why[:80]!r}")
    elif rc == 5 and image_rooms is not None:
        # ★2026-09-16 イージス研究室: タグ変換段(gemma)の時間切れ(DISPATCH-aegis-gl-1789567116980)。
        #   これを rc=3 と同じ型で分けたのは、**描画が壊れたのと原因が違う**から=
        #   絵の側を疑って時間を溶かさないよう、部屋の文面で先に言い切る。
        why = ""
        for ln in (out or "").splitlines():
            if ln.startswith("TAG_TIMEOUT"):
                why = ln[len("TAG_TIMEOUT"):].strip()
        who, body = image_rooms.trouble_message(dept, "tag_timeout", why)
        send_as(channel, body, who, image_rooms.TROUBLE_SUFFIX)
        relayed = notify_trouble_dept(dept, "tag_timeout", (why or err or out), content)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "tag_timeout", "channel": channel,
             "dept": dept, "q": content[:200], "image": True,
             "reason": "local_chain_rc5", "err": (why or err or out)[:300],
             "trouble_persona": who, "relayed_to": image_rooms.trouble_dept(dept),
             "relayed": relayed})
        print(f"  タグ変換timeout [{channel}] {why[:80]!r}")
    elif rc == 6:
        # ★2026-09-23 イージス研究室: 【ポジティブ】【ネガティブ】で切った結果、描く中身が空だった
        #   (DISPATCH-aegis-gl-1790166561731)。空のpromptは描かずに聞き返す= 壊れではないので回送しない。
        send(channel, "描いてほしいもの(【ポジティブ】の中身)が空だったから、まだ描いてないよ。"
                      "描く中身を書いて、もう一度頼んでね。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "empty_positive", "channel": channel,
             "dept": dept, "q": content[:200], "image": True, "cue": cue})
        print(f"  画像生成せず(ポジ空) [{channel}] {content[:30]!r}")
    else:
        # ローカルが通らなかった=Chamiの言う「うまくいくまでのClaude支援」に回す。黙って消さない。
        # ★★2026-09-22 Chami直令 msg 1551691197020508272=「その時はローカル研究室に対応させて。
        #   ローカル内のことだから。」= **Claudeを閉じた部屋の失敗はClaudeへ回さない**。
        #   閉室の目的(msg 1551680397103071355)は「その部屋のことでClaudeを起こして課金しない」で、
        #   失敗のたび main箱へ積めば裏口から同じ課金が戻る。直せる手元(ローカル研究室)へ直接出す。
        #   ★受け先の正本は rooms.trouble_dept()= ここに部門名を書かない。開いている部屋の便は
        #     今までどおり main箱へ積む(1文字も変えていない)。
        relayed = notify_trouble_dept(dept, "local_chain_rc%s" % rc, (err or out), content)
        if relayed:
            to = image_rooms.trouble_dept(dept) if image_rooms else ""
            send(channel, "ごめん、ローカルの絵の経路が今うまく動かなかったから、"
                          "ローカル研究室に見てもらうね(この部屋のことは向こうで直せるよ)。")
        else:
            # 回送先が無い(開いている部屋)/ 回送に失敗した= 便を落とさないために従来の受け皿へ。
            append_line(FOR_CLAUDE, raw_line)
            to = ""
            send(channel, "ごめん、ローカルの絵の経路が今うまく動かなかったから、Claude側に引き取ってもらうね"
                          "(私のPCだけで描けるようになるまでのつなぎだよ)。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
             "dept": dept, "q": content[:200], "growth": True, "image": True,
             "reason": f"local_chain_rc{rc}", "err": (err or out)[:300],
             "relayed_to": to, "relayed": relayed})
        print(f"  画像生成失敗→{to or 'Claude'} [{channel}] rc={rc} {(err or out)[:80]!r}")
    return True


def send_tag_reply(dept, text):
    """タグ列を**優依の名義**で1本出す。

    ★2026-09-20 Chami直令(msg 1551158137002795042「あとマルチエージェントじゃなくて優依が
      出してください」・カスミ便 DISPATCH-aegis-gl-1789895897585)で bot_send から乗り換えた。
      素のBot APIは投稿者名を上書きできない(Discordの仕様)= 名義を変える道はwebhook=
      persona_send しかない。「username だけ差し替える軽い口」を bot_send 側に足す案は
      **作れない**(足すなら結局 webhook を生やすことになり、口が3本目に増えるだけだ・C-064)。
    ★旧実装が避けていた「口調ゲートが英語のタグ列を削る」懸念は、実物の本文で実測して
      **起きない**ことを確かめた(2026-09-20・local/_work/_tagreply_gate_probe.py):
        ・english_backstop= lang_gate の `_dump_core` がコード柵の中身を判定から除くので
          英字0字と見える=発火しない。剥ぐ側(strip_english_paragraphs)も「日本語ゼロの本文は
          触らない」安全弁で素通し。1枚/複数枚/失敗便/タグ220個の4形で全部同一だった。
        ・apply_text_gates(口調/炎上表記/同形異字)も4形とも1文字も変わらない。
      ★この結論は本文が**コード柵の中のタグ列**であることに依っている。format_reply の形を
        変える時(柵の外に英文の説明を足す等)は、上の probe をもう一度回してから変えろ。
    ★長さの扱いはむしろ良くなった= bot_send は `body[:1900]` で**黙って切る**(INC-92 の形)。
      persona_send は split_body で分割して連投する=長いタグ列を失わない。
    ★名義は質問系と同じ `優依` + `(LLM)`(2026-07-27 Chami裁定「表記は優依(LLM)にして」)。
      suffix を persona 本体へ混ぜない理由は PERSONA_SUFFIX の宣言部を見ろ。
    """
    argv = [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
            "--dept", dept, "--persona", PERSONA, "--suffix", PERSONA_SUFFIX, text]
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return True
    # ★人格の口が落ちた時だけ、素のBotの口へ退避する= タグ列そのものを失わない。
    #   ただし「1通でも出た後」の失敗(分割連投の途中で切れた等)では出さない= 二重投稿を作らない。
    if "送信OK" in (r.stdout or ""):
        return False
    log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "tag_persona_fallback", "dept": dept,
         "err": ((r.stderr or r.stdout or "").strip()[-300:])})
    r2 = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "discord", "bot_send.py"),
                         "--dept", dept, text],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r2.returncode == 0


def tag_image_paths(rec):
    """この便に付いている画像の**ローカルパス**を返す。無ければ空。

    ・gateway が受信時に退避した `attachments_local`(local/attachments/…)が第一。
    ・退避に失敗した便(CDNのURLだけ)でも黙って終わらせない= その場で落としてくる。
      落とせなければ空= 呼び元が「画像が見つからなかった」と**言う**。
    """
    paths = []
    for p in (rec.get("attachments_local") or []):
        ap = p if os.path.isabs(p) else os.path.join(ROOT, p)
        if wd14_tag is not None and wd14_tag.is_image_path(ap) and os.path.exists(ap):
            paths.append(ap)
    if paths:
        return paths
    import urllib.request
    os.makedirs(os.path.join(LOCAL, "attachments"), exist_ok=True)
    for i, u in enumerate(rec.get("attachments") or []):
        if not isinstance(u, str) or wd14_tag is None or not wd14_tag.is_image_path(u.split("?", 1)[0]):
            continue
        ext = os.path.splitext(u.split("?", 1)[0])[1][:8] or ".png"
        dest = os.path.join(LOCAL, "attachments", f"{rec.get('msg_id', 'noid')}_{i}{ext}")
        try:
            if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (go5-tagroom)"})
                with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                    f.write(r.read())
            paths.append(dest)
        except Exception as e:
            print(f"  添付の取得に失敗: {type(e).__name__}")
    return paths


def handoff_to_talk(rec):
    """字だけの便を TALK_DEPT(カスミの常駐)へ積み直す。戻り値=(ok, 理由)。

    ★msg_id は**別の値**にする= queue の msg_id は UNIQUE で、元の便(dept=imagetag)が
      既に同じidで入っている。同じidで積むと INSERT が弾かれ(IntegrityError→False)、
      字の便が**黙って消える**。接尾辞1つで別行にする(便は捨てない・C-048)。
    ★本文(rec)の msg_id は**元のまま**渡す= 返信の宛先(GO5_REPLY_TO)と処理済み台帳が
      Discordの実物と同じidで並ぶ。付け替えるのは queue の行の鍵だけだ。
    """
    if not os.path.exists(QDB):
        return False, "キューDBが無い"
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        q = LeaseQueue(QDB)
    except Exception as e:
        return False, f"キューを開けない:{type(e).__name__}"
    try:
        body = dict(rec)
        body["dept"] = TALK_DEPT
        ok = q.enqueue(json.dumps(body, ensure_ascii=False),
                       msg_id=f"{rec.get('msg_id') or 'noid'}-talk", dept=TALK_DEPT)
    except Exception as e:
        return False, f"投函失敗:{type(e).__name__}"
    finally:
        try:
            q.close()
        except Exception:
            pass
    return (True, "") if ok else (False, "同じidが既に入っている")


def handle_tag_request(rec, raw_line):
    """部屋「プロンプト変換と学習」。**画像が貼られた時だけ**タグ列(プロンプト)を返す。

    ★引き金は「画像の添付そのもの」(研究室HQ裁定 2026-09-16)= 合図語をここで発明しない。
      優依(この常駐)が喋るのは画像便だけ、という線は**1文字も動かしていない**。
    ★2026-09-20 変わったのは「字だけの便のあと始末」だけ(Chami直令 DISPATCH-aegis-gl-1789845665234)。
      旧= mode=tag_no_image を1行残して **return False**(部屋は無音。03:03:12の「配線できた?」が
          返事をもらえなかったのはここだ)。
      新= 本文が在るなら TALK_DEPT へ積み直す= **カスミが同じ部屋で返す**。
      ★本文が空(画像も字も無い/スタンプだけ)の便は従来どおり黙る= 起こす理由が無い。
      ★積めなかった時も黙って捨てない(mode に理由を残す)。
    """
    channel = rec.get("channel") or ""
    paths = tag_image_paths(rec)
    if not paths:
        content = (rec.get("content") or "").strip()
        mode, why = "tag_no_image", ""
        if content:
            ok, why = handoff_to_talk(rec)
            mode = "tag_talk_handoff" if ok else "tag_talk_handoff_failed"
        append_line(PROCESSED, raw_line)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": mode, "channel": channel,
             "dept": TAG_DEPT, "q": (rec.get("content") or "")[:200], "sent": False,
             "to": TALK_DEPT if content else "", "err": why})
        print(f"  画像なし [{channel}] {mode}")
        return False
    if wd14_tag is None:
        append_line(PROCESSED, raw_line)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "tag_failed", "channel": channel,
             "dept": TAG_DEPT, "err": "wd14_tag import失敗", "sent": False})
        print("  タグ付けの正本(wd14_tag)を読めない")
        return False
    got = wd14_tag.tag_files(paths)
    body = wd14_tag.format_reply(got, names=[os.path.basename(p) for p in paths])
    sent = send_tag_reply(TAG_DEPT, body)
    append_line(PROCESSED, raw_line)
    log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "mode": "tagged" if got.get("ok") else "tag_failed",
         "channel": channel, "dept": TAG_DEPT, "image": True, "sent": sent,
         "n": len(got.get("items") or []), "a": body[:300],
         "err": "" if got.get("ok") else str(got.get("error"))[:200]})
    print(f"  タグ列を返した [{channel}] {len(paths)}枚 ok={got.get('ok')} sent={sent}")
    return bool(got.get("ok"))


def handle_growth(rec, raw_line, content, channel):
    """自室(llm-growth)の便。★まず自分で答える。Claudeへ回すのは実作業が要る依頼だけ。"""
    # ★2026-07-27 名指しが最優先(Chami「五月orヴィルシーナを名指しして読んだら
    #   ローカルLLMではなく君たちが答えるようにしてよ」)。実作業判定より前に置く理由=
    #   「五月、これ直しといて」のように名指し+実作業が同時に来た時、**呼ばれた本人**が
    #   受けるのが正(main箱へ倒すと、名前を呼んだのに知らない相手から返事が来る)。
    #   ここは声(文字起こし後)の本文も通る=ボイスで名前を呼んでも効く。
    named = named_personas(content)
    if named:
        handle_growth_named(rec, raw_line, content, channel, named, [])
        return
    if not content.strip():
        # 本文が空(添付なし・文字起こしも空)。会話部屋なので聞き返して終わる=Claudeを呼ばない。
        ok = send(channel, "受け取ったけど中身が空で読めなかった。もう一度書いてもらえる?")
        append_line(PROCESSED, raw_line)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "answered", "channel": channel,
             "q": "", "a": "(空の便を聞き返した)", "sent": ok, "growth": True})
        return
    # ★絵の依頼は work-word ゲートより前で拾う(「作って」は work-word=Claude行きなので、
    #   「絵を作って」がClaudeへ逃げないよう先に判定する)。タグを作れなければ False で会話へ戻す。
    if wants_image(content):
        if handle_image_request(rec, raw_line, content, channel):
            return
    if any(w in content for w in GROWTH_WORK_WORDS):
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "それは実際にファイルを触る作業だから、私(優依)にはできない。" + BOX_NOTE)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
             "q": content[:200], "growth": True, "reason": "work_request"})
        print(f"  実作業→Claude行き [{channel}] {content[:30]!r}")
        return
    try:
        # ★文脈理解(2026-08-13): 直近のやり取りを渡して会話をつなげる(recent_dialog は
        #   実測ログから組み立てる既存関数)。live会話は文脈を軽く=直近6往復・幅220に絞る
        #   (num_ctx 8192 + think:True の余白を残すため。採点役へ渡す12/40件とは別枠)。
        answer = ask_growth(content, growth_stats(channel),
                            dialog=recent_dialog(channel, limit=12, width=260),  # ★2026-09-20 中野五月: 記憶6→12ターン(幅260)へ拡張=Chami「話を覚えてない」対策。think切(reasoning_effort:none)で空いた余白を会話履歴に回す。捏造/文脈溢れが出たら6/220へ戻す
                            req_id=rec.get("msg_id", ""), channel=channel)
    except Exception as e:
        answer = ""
        err = type(e).__name__
    else:
        err = ""
    if answer:
        ok = send(channel, answer)
        append_line(PROCESSED, raw_line)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "answered", "channel": channel,
             "q": content[:200], "a": answer[:300], "sent": ok, "growth": True})
        print(f"  自分で応答 [{channel}] {content[:30]!r}")
        return
    # ★fail-open: LLMが落ちている/空応答。**Chamiの発言を黙って消さない**。
    #   モデルの復旧は実作業なので、ここだけは正直に司令塔の箱へ回す。
    append_line(FOR_CLAUDE, raw_line)
    append_line(PROCESSED, raw_line)
    send(channel, f"ごめん、今ローカルモデル({MODEL})が応答できなかった"
                  f"({err or '空の応答'})。この発言は消さずに" + BOX_NOTE +
         " モデルが戻っていれば、もう一度話しかけてくれれば私が答える。")
    log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
         "q": content[:200], "growth": True, "reason": f"llm_down:{err or 'empty'}"})
    print(f"  LLM不可→Claude行き [{channel}] {err or 'empty'}")


# ============================================================================
# 画像便(2026-07-27 Chami裁定):「画像は出させてClaudeがフィードバックしてよ」
#   1) 優依が自分で読んで、自分の言葉で部屋に答える(目=既存のローカルVLM gemma3:4b)
#   2) そのうえで **①元の画像 ②Chamiの文 ③優依の答え** を中野五月(llm-edu)へ渡す
#   3) 五月は「どこが合っていて、どこが違うか」を**優依の部屋へ**書く(採点であって、やり直しではない)
#   4) 学習の材料は既存の台帳 local/llm/lessons.jsonl に残す(新しい台帳は作らない=ORG-11)
# ============================================================================
# 採点役が「元の画像」を自分の目で見るための保存先。
# ★消さない: lessons.jsonl の行がこのパスを指しており、消すと**教材の元画像が失われる**
#   (優依の原典はログだ、というyui.mdの申し送りと同じ理由)。画像は長辺1280pxのPNG=数百KB、
#   Chamiが画像を送る頻度は日に数枚なので、当面は放置で困らない。溢れたらHQが裁定する。
VISION_SHOTS = os.path.join(LOCAL, "llm", "vision_shots")
EDU_DEPT = "llm-edu"                    # 教育担当= 中野五月(dept_daemon.DEPT_CONF)
EDU_PORT_FALLBACK = 18812               # DEPT_CONFが読めない時だけ使う(正本はDEPT_CONF側)


def save_shots(urls, mid):
    """画像をローカルへ保存して、そのパスを返す(フィードバック役が自分の目で見るため)。

    ★image_prep は「画像は保存しない(メモリ内で完結)」方針だが、それは**機微部屋も通る共通部品**
      だからで、ここは allow-list で llm-growth(Chamiと優依の会話部屋)だけに限った経路。
      ★保存しないと「①元の画像」を渡せない=採点役は優依の答えを**採点できない**
        (Discordの添付URLは期限付きで、後から必ず開ける保証が無い)。
      ★保存するのは**優依が実際に見たのと同じ正規化後の画像**(prepare_imageの出力)。
        別の画像を採点役に見せると「優依が見誤ったのか、渡した画像が違ったのか」が分からなくなる。
    失敗しても空リストを返すだけ=配達も応答も止めない(fail-open)。
    """
    import base64
    out = []
    try:
        os.makedirs(VISION_SHOTS, exist_ok=True)
        from image_prep import prepare_image
    except Exception:
        return out
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in str(mid or "nomsg") if c.isalnum() or c in "-_")[:40] or "nomsg"
    for i, u in enumerate(urls):
        try:
            b64, meta = prepare_image(u)
            if not b64:
                continue
            p = os.path.join(VISION_SHOTS, f"{stamp}_{safe}_{i}.png")
            with open(p, "wb") as f:
                f.write(base64.b64decode(b64))
            out.append(p)
        except Exception:
            continue
    return out


def edu_daemon_alive():
    """教育担当(llm-edu)の常駐が生きているか。dept_daemon が公開する /live へTCPで実測する。

    ★claude_responder.room_has_own_responder と同じ作法(ログのmtime推定にしない=
      無通信のデーモンはログを書かないので静かに誤判定する)。
    ★判定できない時は False へ倒す= main箱へ回して司令塔に拾わせる。
      「消費者が居ない箱へ入れて終わり」が今日この部屋が10日死んでいた原因なので、
      **生きていることを確かめてからでないと投函しない**。
    """
    port = None
    try:
        from dept_daemon import DEPT_CONF          # 正本はDEPT_CONF(ここで持たない=ドリフト防止)
        port = (DEPT_CONF.get(EDU_DEPT) or {}).get("port")
    except Exception:
        port = EDU_PORT_FALLBACK
    try:
        import socket
        with socket.create_connection(("127.0.0.1", int(port or EDU_PORT_FALLBACK)), timeout=0.5):
            return True
    except Exception:
        return False


def feedback_record(rec, content, answer, v, shots, lesson_key, channel):
    """中野五月(llm-edu)へ渡す「フィードバック依頼」1件を組み立てる。

    ★宛先の決め方(dept_daemon を読んで実測して決めた・2026-07-27):
      - 教育担当は中野五月(llm-edu)。だが**答えが優依の部屋に出ないと意味が無い**。
      - dept_daemon.handle() は返信先を `rec["channel"]` で決めている
        (`ch = rec.get("channel", "")` → persona_send --channel ch)。
        だから **dept=llm-edu / channel=ローカルllm成長進捗** で投函すれば、
        中野五月が**優依の部屋へ**フィードバックを書く= 1本で閉じる。
      - この「deptとchannelを組み替えて投函する」形は dept_daemon 自身の上申経路が
        既に使っている(`dict(rec, dept=head, channel=ch, via="escalate")`)= 新しい仕組みではない。
    """
    mid = str(rec.get("msg_id") or int(time.time() * 1000))
    body = (
        "■優依への画像フィードバック依頼(local_responder が自動投函)\n"
        "Chamiが優依(ローカルLLM)の部屋『" + channel + "』へ画像を送り、**優依が自分の言葉で答えた**。\n"
        "あなた(中野五月・教育担当)の仕事は**採点**で、やり直しではない。\n"
        "Chami原文=「画像は出させてClaudeがフィードバックしてよ」= **教える形**にしたい、という意味。\n\n"
        "【1. 見せた画像】" + (("ローカル保存済み(Readで開ける):\n  " + "\n  ".join(shots))
                          if shots else "★保存に失敗した。元URL: " + " ".join(imgs_str(rec))) + "\n"
        "【2. Chamiの文】" + (content.strip() or "(文は無く画像だけ)") + "\n"
        "【3. 優依の答え(全文)】\n" + (answer or "(空)") + "\n\n"
        "【参考: 優依の目(" + (v.get("model") or "?") + ")が書き取った下読み】\n"
        + (v.get("draft") or "(読み取れなかった: " + str(v.get("error")) + ")") + "\n\n"
        "■やること(この3つだけ)\n"
        "1. 画像を**自分で見る**。\n"
        "2. 『優依の答えのどこが合っていて、どこが違うか』を短く書く。★この返信はそのまま\n"
        "   『" + channel + "』へ出る(この便の channel がそこになっている)=優依とChamiが読む。\n"
        "   ★正解を貼り直して終わりにしない。優依が**次に自分で読めるようになる**書き方をする。\n"
        "   ★優依は8Bで、数字と自己認識を作ることがある。褒めるところは褒め、違うところは断定で直す。\n"
        "3. 採点を既存の台帳へ残す(新しい台帳は作らない):\n"
        "   python scripts/llm/grade.py --queue --actor qwen で該当行を探し、\n"
        "   python scripts/llm/grade.py --index <番号> --verdict good|bad "
        "[--correction \"正しい読み\" --why \"なぜ違ったか\"] --grader llm-edu\n"
        "   ★local/llm/lessons.jsonl には既に lesson_key=" + lesson_key + " の行がある"
        "(何を見せたか/優依の答え)。あなたが足すのは**どこが違ったか**。\n"
    )
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dept": EDU_DEPT,                 # ← 採点する人(中野五月)
        "channel": channel,               # ← 答えを出す場所(優依の部屋)。ここが要点
        "author": PERSONA + PERSONA_SUFFIX,
        "content": body,
        "msg_id": mid + "-yuifb",         # ★元の便と別id(同じidだとキューが冪等に弾いて消える)
        "via": "yui_vision_feedback",
        "lesson_key": lesson_key,
        "shots": shots,
    }


def imgs_str(rec):
    return [a for a in (rec.get("attachments") or [])][:2]


def request_feedback(fb):
    """フィードバック依頼をLeaseQueueへ投函する。戻り値=(ok, 理由)。

    ★投函の前に**消費者が生きていることを実測**する(edu_daemon_alive)。
      死んでいたら投函しない= 呼び出し側が main箱へ倒す。
    """
    if not edu_daemon_alive():
        return False, "llm-eduの常駐(中野五月)が応答しない"
    if not os.path.exists(QDB):
        return False, "キューDBが無い"
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        q = LeaseQueue(QDB)
    except Exception as e:
        return False, f"キューを開けない:{type(e).__name__}"
    try:
        ok = q.enqueue(json.dumps(fb, ensure_ascii=False), msg_id=fb["msg_id"], dept=EDU_DEPT)
    except Exception as e:
        return False, f"投函失敗:{type(e).__name__}"
    finally:
        q.close()
    return (True, "") if ok else (False, "同じidが既に入っている")


def append_lesson(row):
    """既存の採点台帳(grade.py が書くのと同じファイル)へ1行足す。新しい台帳は作らない(ORG-11)。"""
    os.makedirs(os.path.dirname(LESSONS), exist_ok=True)
    with open(LESSONS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def handle_growth_vision(rec, raw_line, content, channel, imgs):
    """自室の画像便。**優依が自分で答え**、そのあと中野五月へフィードバックを頼む。"""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    q200 = (content or "(画像のみ)")[:200]
    try:
        v = describe_images(imgs)
    except Exception as e:   # describe_imagesは投げない設計だが契約に依存しない(常駐を落とさない)
        v = {"draft": "", "model": "", "sec": 0.0, "error": f"vision_crashed:{type(e).__name__}"}
    shots = save_shots(imgs, rec.get("msg_id"))
    extra = (
        "★この便には画像が付いている。あなたの目(ローカルVLM " + (v.get("model") or "?") + ")が"
        "読み取ったメモが質問の中にある。\n"
        "・**メモに書いてあることだけ**を根拠に、自分の言葉で答える。メモに無いものを足さない。\n"
        "・メモが空/失敗しているなら『うまく見えなかった』と正直に言う。見えたふりをしない。\n"
        "・画像についての数字(精度・枚数・解像度)は作らない。\n"
        "・このあと中野五月(教育担当)が、あなたの答えの**どこが合っていてどこが違うか**を"
        "この部屋に書いてくれる。だから**間違いを恐れずに、まず自分の読み取りを言い切る**"
        "(それがそのまま教材になる)。\n"
    )
    question = (
        "Chamiから画像が届いた。\n"
        "【Chamiの文】" + (content.strip() or "(文は無く画像だけ)") + "\n"
        "【あなたが画像から読み取ったメモ】\n"
        + (v.get("draft") or "(読み取れなかった: " + str(v.get("error")) + ")")
    )
    try:
        answer = ask_growth(question, growth_stats(channel), extra=extra,
                            dialog=recent_dialog(channel, limit=12, width=260),  # ★2026-09-20 中野五月: 記憶6→12ターン(幅260)へ拡張=Chami「話を覚えてない」対策。think切(reasoning_effort:none)で空いた余白を会話履歴に回す。捏造/文脈溢れが出たら6/220へ戻す
                            req_id=rec.get("msg_id", ""), channel=channel)
        err = ""
    except Exception as e:
        answer, err = "", type(e).__name__
    if not answer:
        # ★fail-open: 優依が答えられない時だけ、従来どおり司令塔の箱へ回す。
        #   **画像もChamiの文も黙って消さない**(下読みと保存先を行に添えて渡す)。
        rec2 = dict(rec, vision_draft=v.get("draft", ""), vision_model=v.get("model", ""),
                    vision_sec=v.get("sec", 0.0), vision_shots=shots)
        line2 = json.dumps(rec2, ensure_ascii=False)
        append_line(FOR_CLAUDE, line2)
        append_line(PROCESSED, line2)
        send(channel, f"ごめん、画像は受け取ったけど私({MODEL})が言葉にできなかった"
                      f"({err or '空の応答'})。読み取ったメモを添えて" + BOX_NOTE)
        log({"ts": ts, "mode": "escalated", "channel": channel, "q": q200, "growth": True,
             "vision": True, "vision_model": v.get("model", ""), "vision_sec": v.get("sec", 0.0),
             "vision_draft": (v.get("draft") or "")[:300], "vision_error": v.get("error"),
             "reason": f"llm_down:{err or 'empty'}"})
        print(f"  画像→LLM不可でClaude行き [{channel}] {err or 'empty'}")
        return
    # --- ここから: 優依が答えた ---
    # ★学習の材料を既存台帳へ(1行)。「どこが違ったか」は中野五月が grade.py で後から足す。
    #   ★source_key ではなく lesson_key で持つ: source_key にすると grade.py の未採点一覧から
    #     この便が消え、**誰も採点できなくなる**(grade.pending() が source_key で除外するため)。
    #     採点行は同じ値を source_key に持つので、後から突き合わせられる。
    lesson_key = f"{ts}|{q200[:40]}"
    try:
        append_lesson({
            "ts": ts, "actor": "qwen", "mode": "answered", "channel": channel,
            "kind": "vision", "q": q200, "a": answer[:1200],
            "shown": imgs_str(rec), "shots": shots,
            "vision_model": v.get("model", ""), "vision_draft": (v.get("draft") or "")[:600],
            "vision_error": v.get("error"),
            "verdict": "", "correction": "", "why": "", "grader": "",
            "lesson_key": lesson_key, "feedback_to": EDU_DEPT, "sensitive": False,
            "note": "画像便: 優依が自分で答えた。どこが違ったかは中野五月(llm-edu)が採点行で足す",
        })
        lesson_ok = True
    except Exception as e:
        lesson_ok = False
        print(f"  ★台帳へ書けなかった: {type(e).__name__}")
    # ★採点依頼は**部屋へ喋る前**に出す。理由= 送ってから投函すると、投函に失敗した時に
    #   「このあと五月が見てくれる」という**嘘を先に言ってしまう**。行き先が確定してから話す。
    fb = feedback_record(rec, content, answer, v, shots, lesson_key, channel)
    fb_ok, why = request_feedback(fb)
    if not fb_ok:
        # ★採点役へ渡せない時は**黙らない**。司令塔の箱へ倒す(Chamiの画像と文を消さない)。
        rec2 = dict(rec, vision_draft=v.get("draft", ""), vision_model=v.get("model", ""),
                    vision_shots=shots, yui_answer=answer,
                    note=f"優依は答えた。採点役(llm-edu)へ渡せなかった: {why}")
        append_line(FOR_CLAUDE, json.dumps(rec2, ensure_ascii=False))
    # ★機械的な但し書き(2026-07-27)。優依の言葉は書き換えず、後ろに足すだけ。
    #   - 目(VLM)が働かなかった時: 「うまく見えなかった」だけだと、Chamiには**画像が捨てられたのか**
    #     分からない。実際には保存してあり、次に誰が見るのかを言う。
    #   - 採点役へ渡せなかった時: どこへ入れたかを正直に言う(BOX_NOTE)。
    body = answer
    if v.get("error"):
        body += (f"\n\n(私の目({v.get('model') or 'ローカルVLM'})が動かなかった: {v.get('error')}。"
                 + ("画像は消していない。中野五月に見てもらうようお願いした。)" if fb_ok
                    else "画像は消していない。)"))
    if not fb_ok:
        body += (f"\n\n(採点をお願いする先(中野五月)へ渡せなかった: {why}。"
                 "私の答えと画像は消さずに" + BOX_NOTE + ")")
    ok = send(channel, body)
    append_line(PROCESSED, raw_line)
    log({"ts": ts, "mode": "answered", "channel": channel, "q": q200, "a": answer[:300],
         "sent": ok, "growth": True, "vision": True,
         "vision_model": v.get("model", ""), "vision_sec": v.get("sec", 0.0),
         "vision_draft": (v.get("draft") or "")[:300], "vision_error": v.get("error"),
         "feedback_to": EDU_DEPT if fb_ok else "", "feedback_msg_id": fb["msg_id"] if fb_ok else "",
         "feedback_error": "" if fb_ok else why, "lesson_key": lesson_key,
         "lesson_written": lesson_ok, "shots": shots})
    print(f"  画像に自分で応答(下読み{len(v.get('draft') or '')}字/{v.get('sec')}秒) [{channel}] "
          f"→ 採点依頼 {'投函' if fb_ok else 'NG:' + why}")


# ============================================================================
# 名指し取次(2026-07-27 Chami指示)。原文=
#   「1526159156019462194 五月orヴィルシーナを名指しして読んだらローカルLLMではなく
#     君たちが答えるようにしてよ、トーク履歴見て採点とかしておいて」
#
# ★渡す経路は**新規に作らない**。画像の採点(feedback_record→request_feedback)が
#   既に「dept=llm-edu / channel=優依の部屋」で投函し、中野五月がこの部屋へ書いている。
#   dept_daemon.handle() は返信先を rec["channel"] で決めるので、それに乗るだけで閉じる。
#
# ★誰を拾うか(名簿の正本= dept_daemon.DEPT_CONF["llm-edu"]["personas"]。ここでは読むだけ)。
#   現在の名簿= 中野五月 / トトリ / アメス / ヴィルシーナ。
#   Chamiが挙げたのは五月とヴィルシーナの2人だが、**4人とも拾う**ことにした。理由:
#     - 4人は同じ llm-edu の名簿に居て、**同じ失敗の仕方をする**。この部屋で名前を呼ばれた時に
#       優依が代わりに答えると、実測(11:47:46「五月先生は、私の回答を採点していますよ」)の
#       とおり**その人の行動を勝手に語る**。トトリ/アメスでも起きることは同じ。
#     - ask_growth の規則7 が既に「五月/トトリ/アメスを名乗るな」と縛っている=
#       この4人は元から「優依が代弁してはいけない相手」として扱われている。今回はその続き。
#     - トトリ/アメスは**同音異義が無い**ので、拾っても誤爆しない(五月と違う)。
#   ★「呼んだのに出てこない」方が Chami にとって害が大きい(HQ指示)ので、迷う所は呼びかけ側へ倒す。
#
# ★誤爆対策(「五月」は月の名前でもある)。判定を2段に分けた:
#   [A] 曖昧さの無い呼び名は**無条件**で名指しとする(中野五月/五月先生/五月ちゃん/五月さん/
#       ヴィルシーナ/シーナ/トトリ/アメス)。月の用法とは字面が衝突しない。
#   [B] 素の「五月」だけは**呼びかけの形**をしている時に限る(=月の用法を消す)。
#       ・先に「月の言い回し」を潰す(五月雨/五月晴れ/五月病/五月末/五月中/今年の五月 …)。
#       ・そのうえで「呼びかけ」を積極的に判定する:
#           1) 直後が区切り or 文末   「五月、これ見て」「五月!」「おーい五月」
#           2) 直前が @              「@五月」
#           3) 直後が助詞+**対人語**  「五月に聞きたい」「五月の採点まだ?」
#       ・「五月に締切」は 3) の対人語(聞く/相談/採点…)が続かないので**月として扱う**=優依が答える。
#         「5月」(半角数字)はそもそも字面が違うので当たらない。
#   ★残る取りこぼし(承知の上): 「五月の予定教えて」のような**月+対人語**は名指し側へ倒れる。
#     ここは Chami 指示どおり「呼びかけ側へ倒す」を採った(呼ばれた人が出てこない方が害が大きい)。
# ============================================================================
# [A] 無条件で名指しとみなす呼び名 → 実際の人格名(dept_daemon の personas.aliases と同じ綴り)
NAMED_ALWAYS = (
    ("中野五月", "中野五月"), ("五月先生", "中野五月"), ("五月ちゃん", "中野五月"),
    ("五月さん", "中野五月"),
    ("ヴィルシーナ", "ヴィルシーナ"), ("シーナ", "ヴィルシーナ"),
    ("トトリ", "トトリ"),
    ("アメス", "アメス"),
)
# [B] 素の「五月」用。まず**月の言い回し**を潰す(ここに当たったら名指しではない)。
_SATSUKI_MONTH_RE = re.compile(
    r"(?:[0-9０-９]|年|今年|来年|去年|昨年|一昨年|再来年)\s*五月"      # 2026年五月 / 今年の…は下で吸収
    r"|(?:今年|来年|去年|昨年|一昨年|再来年)の五月"
    r"|五月(?:雨|晴|病|人形|蝿|蠅|闇|祭|場所|革命|女)"                  # 熟語(五月雨式・五月晴れ…)
    r"|五月(?:末|初旬|上旬|中旬|下旬|頃|ごろ|中|号|分|期|度|以降|以前|いっぱい|一杯)")
# [B] 呼びかけの形(どれかに当たれば名指し)。
#   1) 直後が区切り/文末  2) 直前が@  3) 直後が助詞+対人語(12文字窓)
_SATSUKI_CALL_RE = re.compile(
    r"[@＠]\s*五月"
    r"|五月(?:[、,。．\.!\?！？…〜~ー\s]|$)"
    r"|五月[にはがものへと].{0,12}?"
    r"(?:聞|訊|尋ね|相談|頼|お願い|話[しすせそ]|伝え|見せ|見て|教え|確認|採点|評価|"
    r"意見|感想|質問|返事|答え|コメント|フィードバック|チェック|レビュー|"
    r"どう思|呼ん|呼び|任せ|振っ|渡し|来て|出て|元気|ありがと|よろしく)")


def named_personas(content):
    """本文に llm-edu の誰かへの**名指し**があるか。あれば人格名のリスト(重複なし・出現順)。

    ★優依(ローカルLLM)ではなく Claude側(llm-edu の中野五月たち)が答えるべき便を見分けるだけ。
      判定の根拠は上のコメント(★誰を拾うか / ★誤爆対策)を参照。
    """
    text = content or ""
    found = []
    for alias, person in NAMED_ALWAYS:
        if alias in text and person not in found:
            found.append(person)
    # 素の「五月」= 月の言い回しを消してから、呼びかけの形だけを拾う
    if "中野五月" not in found:
        stripped = _SATSUKI_MONTH_RE.sub("", text)
        if "五月" in stripped and _SATSUKI_CALL_RE.search(stripped):
            found.insert(0, "中野五月")
    return found


def recent_dialog(channel, limit=12, width=300):
    """この部屋の直近のやり取りを、実測ログ(responder_log.jsonl)から素朴に組み立てる。

    ★新しい台帳を作らない(ORG-11)。q=Chamiの発言 / a=優依の答え が既に1行ずつ残っている。
    ★読めなければ「読めなかった」と正直に書く(黙って空にしない)。
    """
    rows = []
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            for l in f:
                l = l.strip()
                if not l:
                    continue
                try:
                    r = json.loads(l)
                except Exception:
                    continue
                if channel and r.get("channel") != channel:
                    continue
                rows.append(r)
    except OSError:
        return "(応答ログ local/llm/responder_log.jsonl が読めなかった)"
    if not rows:
        return "(この部屋の記録はまだ無い)"
    out = []
    for r in rows[-limit:]:
        ts = (r.get("ts") or "")[:19]
        q = (r.get("q") or "").strip() or "(本文なし)"
        a = (r.get("a") or "").strip()
        mode = r.get("mode") or ""
        out.append(f"[{ts}] Chami: {q[:width]}")
        if a:
            out.append(f"{' ' * 22}優依: {a[:width]}")
        elif mode.startswith("escalated"):
            out.append(f"{' ' * 22}優依: (答えず司令塔へ回した: {r.get('reason', '')})")
        elif mode.startswith("handoff"):
            out.append(f"{' ' * 22}(優依は答えず {r.get('named', '')} へ取り次いだ)")
    return "\n".join(out)


# ★機械的な一行(2026-07-27)。**LLMには書かせない固定文**。
#   理由= HQ指示「優依の人格で言い訳させるな」。優依に喋らせると「私には難しくて…」のような
#   言い訳になり、10日間この部屋を殺した『毎回Claudeへ投げ返す優依』が戻ってくる。
#   ここは配達の受領印であって、会話ではない。だから [取次] と印を付けた1行だけを出す。
HANDOFF_LINE = ("[取次] {names} への名指しなので、優依(ローカルLLM)は答えません。"
                "llm-edu(中野五月たちの部屋)へ渡しました。返事はこの部屋に出ます。")
HANDOFF_FAIL_LINE = ("[取次] {names} への名指しですが、llm-edu へ渡せませんでした({why})。"
                     "優依は答えません。Chamiの発言は消していません: ")


def handoff_record(rec, content, channel, named, shots):
    """名指し便を llm-edu(中野五月たち)へ渡す1件を組み立てる。

    ★宛先の決め方は feedback_record と同じ(=既存経路の使い回し・新しい仕組みを作らない):
      dept=llm-edu(答える人)/ channel=優依の部屋(答えが出る場所)。
      dept_daemon.handle() が返信先を rec["channel"] で決めるため、これで1本に閉じる。
    ★Chamiの原文は**改変しない**(要約も敬語化もしない)。そのまま【1】へ入れる。
    """
    mid = str(rec.get("msg_id") or int(time.time() * 1000))
    names = " / ".join(named)
    body = (
        "■名指し取次(local_responder が自動投函。★優依は答えていない)\n"
        "Chamiが優依(ローカルLLM)の部屋『" + channel + "』で **" + names + "** を名指しした。\n"
        "この便の channel は優依の部屋になっている= **あなたの返信はそのまま『" + channel + "』へ出る**"
        "(Chamiと優依が読む)。\n\n"
        "【1. Chamiの原文(改変していない)】\n" + (content or "(本文なし)") + "\n\n"
        "【2. 名指しされた人】" + names + "\n\n"
        + (("【3. 添付画像(優依が見たのと同じ正規化後の画像。Readで開ける)】\n  "
            + "\n  ".join(shots) + "\n\n") if shots else "")
        + "【" + ("4" if shots else "3") + ". この部屋の直近のやり取り"
        "(local/llm/responder_log.jsonl 実測・古い順。q=Chami / a=優依)】\n"
        + recent_dialog(channel) + "\n\n"
        "■なぜこの便が来るのか(Chami原文・2026-07-27)\n"
        "「1526159156019462194 五月orヴィルシーナを名指しして読んだらローカルLLMではなく"
        "君たちが答えるようにしてよ、トーク履歴見て採点とかしておいて」\n"
        "= この部屋で名前を呼ばれたら、優依(qwen)ではなく**あなたたちが答える**。\n"
        "★優依はこの便に答えていない。あなたが返さないとChamiの発言が宙に浮く。必ず返すこと。\n"
        "★採点を残すなら**既存の台帳**へ(新しい台帳は作らない):\n"
        "   python scripts/llm/grade.py --queue --actor qwen\n"
        "   python scripts/llm/grade.py --index <番号> --verdict good|bad "
        "[--correction \"正しい答え\" --why \"なぜ違ったか\"] --grader llm-edu\n"
        "★優依は8Bで、測っていない数字(正答率など)を作る癖がある。そこは断定で直す。\n"
    )
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dept": EDU_DEPT,                 # ← 答える人(中野五月たち)
        "channel": channel,               # ← 答えが出る場所(優依の部屋)。ここが要点
        "author": rec.get("author") or "Chami",
        "content": body,
        "msg_id": mid + "-named",         # ★元の便と別id(同じidだとキューが冪等に弾いて消える)
        "via": "yui_named_handoff",
        "named": named,
        "shots": shots,
    }


def handle_growth_named(rec, raw_line, content, channel, named, imgs):
    """名指し便。★優依は答えず、llm-edu へ渡す。渡せない時も**黙って消さない**。"""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    names = " / ".join(named)
    # 画像付きで名指しされた時は、採点役が自分の目で見られるように保存だけしておく
    # (優依には見せない=答えさせないため。保存経路は画像採点と同じもの)。
    shots = save_shots(imgs, rec.get("msg_id")) if imgs else []
    hr = handoff_record(rec, content, channel, named, shots)
    ok, why = request_feedback(hr)   # ★生存確認つきの既存投函関数をそのまま使う
    if ok:
        sent = send(channel, HANDOFF_LINE.format(names=names))
        append_line(PROCESSED, raw_line)
        # ★mode は answered / escalated のどちらでもない= growth_stats() の成績に混ぜない
        #   (優依が答えた便でも、優依が司令塔へ回した便でもないため。数字を汚さない)。
        log({"ts": ts, "mode": "handoff_llm_edu", "channel": channel, "q": content[:200],
             "growth": True, "named": names, "sent": sent,
             "handoff_msg_id": hr["msg_id"], "shots": shots})
        print(f"  名指し→{EDU_DEPT}へ取次 [{channel}] {names} {content[:30]!r}")
        return
    # ★fail-open: llm-edu の常駐が死んでいる等。既存の fallback(main箱)へ倒す。
    rec2 = dict(rec, named=named, shots=shots,
                note=f"優依の部屋での名指し({names})。llm-eduへ渡せなかった: {why}")
    append_line(FOR_CLAUDE, json.dumps(rec2, ensure_ascii=False))
    append_line(PROCESSED, raw_line)
    send(channel, HANDOFF_FAIL_LINE.format(names=names, why=why) + BOX_NOTE)
    log({"ts": ts, "mode": "escalated", "channel": channel, "q": content[:200],
         "growth": True, "named": names, "reason": f"handoff_failed:{why}", "shots": shots})
    print(f"  名指しの取次に失敗→Claude行き [{channel}] {names} / {why}")


# ============================================================================
# 「トーク履歴見て採点」(Chami原文)= 1回きりの手動投函。★常駐ループには入れない。
#   置き場は既存の local/llm/lessons.jsonl(grade.py が書く台帳)のまま=新しい台帳を作らない。
#   投函先は名指し取次と同じ dept=llm-edu / channel=優依の部屋 → 講評がこの部屋に出る。
# ============================================================================
CHAMI_ORDER_2026_07_27 = ("1526159156019462194 五月orヴィルシーナを名指しして読んだら"
                          "ローカルLLMではなく君たちが答えるようにしてよ、"
                          "トーク履歴見て採点とかしておいて")


def grade_history_record(channel, limit=40):
    """優依のトーク履歴を採点してもらう依頼を1件組み立てる(投函はしない)。"""
    mid = "gradehist-" + time.strftime("%Y%m%d-%H%M%S")
    body = (
        "■優依のトーク履歴の採点依頼(Chami直令・手で1回だけ投函された便)\n"
        "この便の channel は優依の部屋『" + channel + "』= **あなたの講評はそのままこの部屋へ出る**"
        "(Chamiと優依が読む)。\n\n"
        "【Chamiの原文(改変していない)】\n" + CHAMI_ORDER_2026_07_27 + "\n\n"
        "■やること\n"
        "1. 優依(ローカルqwen " + MODEL + ")の部屋『" + channel + "』のトーク履歴を読む。\n"
        "   実体= local/llm/responder_log.jsonl の channel=\"" + channel + "\" の行"
        "(q=Chamiの発言 / a=優依の答え / mode=answered|escalated)。\n"
        "   下に直近" + str(limit) + "件を貼ってある。足りなければファイルを直接読む。\n"
        "2. 1件ずつ採点する。基準は既決(scripts/llm/grade.py 冒頭・改善設計書§5.2):\n"
        "   good     = 正確 + 人格逸脱なし\n"
        "   bad      = 事実誤り・憶測・なりすまし・できない約束\n"
        "   escalate = 「わからない」と正しく回した(=良い挙動。加点する)\n"
        "3. 採点は**既存の台帳**へ残す(新しい台帳を作らない=ORG-11):\n"
        "   python scripts/llm/grade.py --queue --actor qwen   (未採点を古い順に見る)\n"
        "   python scripts/llm/grade.py --index <番号> --verdict good|bad "
        "[--correction \"正しい答え\" --why \"なぜ違ったか\"] --grader llm-edu\n"
        "   ★bad は correction と why が必須(無いと教訓にならない=知識パックへ焼けない)。\n"
        "4. 講評を**この部屋へ**書く。正解を貼り直して終わりにせず、"
        "優依が次に自分でできるようになる書き方をする。\n"
        "   ★優依は8Bで、測っていない数字(正答率・回答の質・応答速度)を作る癖がある。"
        "実測(2026-07-27 11:47)でも『五月先生は、私の回答を採点していますよ』と"
        "**他人の行動を勝手に語った**。そこは褒めずに断定で直す。\n\n"
        "【直近" + str(limit) + "件の履歴(古い順)】\n"
        + recent_dialog(channel, limit=limit, width=400) + "\n\n"
        "【採点台帳と成績の現況(local/llm/ の実測)】\n" + growth_stats(channel) + "\n"
    )
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dept": EDU_DEPT,
        "channel": channel,
        "author": "Chami",
        "content": body,
        "msg_id": mid,
        "via": "yui_grade_history",
    }


def grade_history(dry_run=False, limit=40):
    """--grade-history 本体。戻り値=成功したか。★常駐からは呼ばない(1回きりの手作業)。"""
    channel = GROWTH_CHANNELS[0]
    rec = grade_history_record(channel, limit=limit)
    if dry_run:
        print("=== dry-run: 投函しない。中身だけ出す ===")
        print("dept    :", rec["dept"])
        print("channel :", rec["channel"])
        print("msg_id  :", rec["msg_id"])
        print("via     :", rec["via"])
        print("llm-edu常駐の生存:", edu_daemon_alive())
        print("--- content(全文) ---")
        print(rec["content"])
        print("--- content ここまで ---")
        return True
    ok, why = request_feedback(rec)
    if ok:
        print(f"採点依頼を投函した(dept={rec['dept']} / channel={rec['channel']} / "
              f"msg_id={rec['msg_id']})。講評は『{channel}』に出る。")
        return True
    print(f"★投函できなかった: {why}")
    print("  → llm-edu の常駐が生きているかを確かめてから、もう一度叩く。"
          "(この依頼はChamiの発言ではないので、main箱へは倒していない)")
    return False


def handle(rec, raw_line, growth=None):
    content = rec.get("content", "")
    channel = rec.get("channel", "")
    if rec.get("dept") in SENSITIVE_DEPTS:
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        # ★2026-09-16 撤去(イージス研究室)= ここに在った
        #   「受け取ったよ。ここは司令塔(アメスたち)が直接読む部屋だから、次に起きた時に必ず応えるね。」
        #   を出さない。codex_responder.py:499 と同文型の**中身の無い一次ack**で、
        #   共通規律§2=「内容の無い一次ackは沈黙より悪い」に反する。
        #   Chami原文=「これやめろって」(msg 1549628255173353625 / 2026-09-16 12:49:26 JST / hr-room)。
        #   ★恒久 DEF-otacon-radio-df36094b69(炎上/C-038・C-040)の兄弟口。
        # ★沈黙にはしていない(§2「ただし黙って落とすな」)= 上の append_line が生の便を
        #   司令塔の主受付箱へ入れ、下の印が「読んだ/その場で完結した」を部屋へ残す。
        #   撤去前のこの分岐は mark() を一度も押しておらず、単純撤去だと部屋が無音になった。
        # ★この編集は handle() の機微分岐だけ= research-room 所有の別topic(keigo恒久修正)には触れていない。
        mark(channel, str(rec.get("msg_id") or ""), "既読")
        mark(channel, str(rec.get("msg_id") or ""), "即答")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "sensitive_deferred", "channel": channel})
        return
    # ★画像生成ルーム(中野五月 DISPATCH 2026-09-09)= この部屋のChami便は語彙ゲート(wants_image)を
    #   通さず**直接** handle_image_request へ流す。Chami原文=「俺が画像生成のプロントを渡す→優依→
    #   動画生成用ローカルLLM→画像生成→優依が受け取ってこの部屋に完成品を送る」。
    #   便は gateway が discord_inbox_llm.jsonl へ写したもの(→ INBOX_LLM ドレインでここに来る)。
    #   ★花海咲季(Claude/dept_daemon)は別プロセスで同じ便をqueue(dept=imagegen)から受けて並走する。
    #     ここは優依を*足すだけ*=他部屋も花海咲季も1文字も変えていない(channelが画像生成ルームの時だけ入る)。
    #     切替(花海咲季を落とす)はイージス研究室が同品質確認後に握る=ここでは落とさない。
    # ★2026-09-14 ここを「表示名の一致」から「deptの所属」に変えた(Chami直令 1548842898773123105)。
    #   旧 `channel == IMAGE_ROOM` は台帳の実名と違っていて**一度も真にならなかった**(実測)。
    #   今は画像ルーム3室(既存の画像生成ルーム + fusoh_v0 + fusoh_v2)が同じ口から入る。
    # ★2026-09-16 合図ゲート(イージス研究室・アメス便 1549468992396329025)。
    #   旧= この部屋のChami便は**全部**注文として handle_image_request へ直行していた。
    #       実害= 雑談「これデーモン?デーモンの返信いらんよ」を優依が絵にしようとした。
    #   新= fusohの2室だけ「合図のある便」に限って拾う(正本= rooms.CUE_REQUIRED_DEPTS)。
    #   ★★この「2室だけ」は**もう古い**(2026-09-22・Chami直令 msg 1551685142806925366
    #     「生成依頼 って冒頭につけないと画像生成されないようにして」)。合図が要るのは
    #     **ROOMSに載っている描画室すべて**= 素の imagegen 室も対象に入った。
    #     C-035「名指ししていない既存室は1文字も変えない」の除外線は、imagegen室については
    #     この直令で消えている(消えたのはこの1本だけ=規律の本体は広がっていない)。
    #     実害= 05:06:18、素の imagegen 室でChamiのこの指示文そのものが絵になった。
    #   ★★★同じ日の 05:37→05:49 に**もう一度動いた**。Chami直令 msg 1551692713425117314
    #     「この3部屋は生成依頼って書かなくても生成するようにしてよ、そうすればエラーが
    #      積まれないから」→ 直後の msg 1551692776859631629「違う、４部屋か」で itsumono も。
    #     結果= Claude常駐を閉じた4室(rooms.NO_CUE_DEPTS = NO_CLAUDE_DEPTS)は**合図なしで全便を
    #     注文として拾う**= 実在の描画室で合図が要る部屋は今ゼロだ。
    #     ★この段落を鵜呑みにするな= 要否の正本は `rooms.cue_required(dept)` ただ1つで、
    #       ここは写しにすぎない(1日で3回動いた=写しは必ず遅れる)。判定は下の order_of が持つ。
    #   ★2026-09-16 03:0x Chami直で合図を**「生成依頼」で始まる時だけ**の1本に絞った
    #     (msg 1549476416641572937 / 1549477000807194637「1。でも印はいらんかな」)。
    #     `!描`系の印も wants_image の曖昧マッチも、この2室では効かない= rooms.order_of が決める。
    #       合図の無い便は**描かない・喋らない**(Chami原文「デーモンの返信いらんよ」)。
    #       黙って捨てるのではなく responder_log.jsonl に mode=image_no_cue で残す=
    #       「拾わなかった」が後から数えられる(silent failにしない)。
    _idept = image_dept_of(rec)
    if _idept and content.strip():
        _order, _prompt = (True, content)
        if image_rooms is not None:
            _order, _prompt = image_rooms.order_of(_idept, content, wants_image)
        if not _order:
            append_line(PROCESSED, raw_line)
            log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "image_no_cue",
                 "channel": channel, "dept": _idept, "q": content[:200], "image": True,
                 "sent": False})
            print(f"  合図なし=描かない [{channel}] {content[:30]!r}")
            return
        if not _prompt.strip():
            # 合図だけ来た(「生成依頼」で送信)。何を描くのか分からないので聞き返して終わる。
            send(channel, "合図は受け取ったよ。何を描くか続けて書いてくれる?"
                          "(例: 「生成依頼 銀髪ロング 制服 桜」)")
            append_line(PROCESSED, raw_line)
            log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "image_cue_only",
                 "channel": channel, "dept": _idept, "q": content[:200], "image": True,
                 "sent": True})
            return
        # ★cue= この便にゲートが掛かっていたか(True=合図が要る部屋で合図が有った)。
        #   剥がす前の本文はここにしか無いので、記録はここで決める(下流は受け取るだけ)。
        _cue = bool(image_rooms is not None and image_rooms.cue_required(_idept))
        handle_image_request(rec, raw_line, _prompt, channel, _idept, cue=_cue)
        return
    # ★旧V0シャドー配線(改善設計書_ローカルLLM画像認識強化_2026-07-17 §3・T-2)の跡地。
    #   旧= 画像添付は**問答無用で司令塔(Claude)へ回し**、ローカルVLMの下読み(vision_draft)を
    #       箱の行に添えるだけ。qwenは自分の言葉では一度も答えなかった。
    #   ★機微はallow-list方式(fail-closed)は**そのまま維持**。deny-list(SENSITIVE_DEPTS)は
    #     部屋が増えるたびに追記漏れが起き、dept未設定の行も素通りするため。
    #   VLMが落ちても配達は止めない(describe_imagesは例外を投げない設計だが契約に依存せず包む)。
    # ★2026-07-27 ここが V0(画像は問答無用でClaude行き)から**優依が自分で答える**へ変わった。
    #   Chami原文=「画像は出させてClaudeがフィードバックしてよ」。
    #   = 純粋な「Claudeが答える」ではない。**優依に出させて、そのうえで教える**形にする。
    #   ★VISION_ALLOWED_DEPTS は llm-growth ただ1つ(allow-list=fail-closed)。
    #     つまりこの分岐に入るのは**優依の部屋だけ**で、他の部屋の挙動は1文字も変わらない。
    if growth is None:
        growth = is_growth_room(rec)
    imgs = images_of(rec) if rec.get("dept") in VISION_ALLOWED_DEPTS else []
    if imgs and growth:
        # ★2026-07-27: 画像便でも**名指しが先**(Chami「名指ししたらローカルLLMではなく君たちが」)。
        #   「五月、これ見て」で優依が先に答えてしまうと、呼ばれた本人より先に代弁者が喋る形になる。
        #   名指しが無ければ今日の実装(優依が答える→五月が採点)のまま=1文字も変えていない。
        named = named_personas(content)
        if named:
            handle_growth_named(rec, raw_line, content, channel, named, imgs)
        else:
            handle_growth_vision(rec, raw_line, content, channel, imgs)
        return
    if not content.strip():
        voice = next((a for a in (rec.get("attachments") or [])
                      if any(x in a.lower() for x in AUDIO_EXT)), "")
        if voice:
            content = fetch_and_transcribe(voice)
            if not content:
                append_line(FOR_CLAUDE, raw_line)
                append_line(PROCESSED, raw_line)
                send(channel, "ボイスメモを受け取ったけど聞き起こせなかった。消さずに" + BOX_NOTE)
                log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated_voice_fail", "channel": channel})
                return
            rec = dict(rec, content=content, voice=True)
            raw_line = json.dumps(rec, ensure_ascii=False)
    # ★2026-07-27: 自室(llm-growth)は会話部屋。ここから先の判定を分ける。
    #   ★他の部屋の挙動は1文字も変えていない(下の従来経路はそのまま)。
    #   (growth の判定は画像分岐の手前で済ませてある)
    if growth:
        handle_growth(rec, raw_line, content, channel)
        return
    is_work = any(w in content for w in WORK_WORDS)
    answer = ""
    if not is_work:
        try:
            answer = ask(content, MODEL)
        except Exception as e:
            print(f"  LLM失敗: {type(e).__name__} → Claude行き")
            answer = ""
        if answer and ("わからないので司令塔" in answer or "ESCALATE" in answer):
            answer = ""
    if answer:
        ok = send(channel, answer)
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "answered", "channel": channel,
             "q": content[:200], "a": answer[:300], "sent": ok})
        append_line(PROCESSED, raw_line)
        print(f"  即答 [{channel}] {content[:30]!r}")
    else:
        append_line(FOR_CLAUDE, raw_line)
        append_line(PROCESSED, raw_line)
        send(channel, "これは司令塔(Claude)の仕事として受付箱に入れておくね。次のセッションで対応されるよ。")
        log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "escalated", "channel": channel,
             "q": content[:200]})
        print(f"  Claude行き [{channel}] {content[:30]!r}")


def drain_lines(path):
    """受付箱を .inflight へ退避して全行を返す(既に退避済みがあればそれを優先)。

    ★kill耐性(2026-07-17): 旧実装は「読む→os.remove→処理」で、処理中に強制終了
      (Windows Update再起動・stop_daemons・重複排除のkill)が入ると、箱から消えて
      まだ着地していない行が**どこにも残らず消滅**した(レビューで3通中2通の喪失を再現)。
      inflightに残しておけば、次回起動時に拾い直せる=喪失が「遅延」に変わる。
    """
    inflight = path + ".inflight"
    if os.path.exists(inflight) and os.path.getsize(inflight) > 0:   # 前回の中断分が最優先
        with open(inflight, "r", encoding="utf-8") as f:
            rest = [l for l in f.read().splitlines() if l.strip()]
        if os.path.exists(path) and os.path.getsize(path) > 0:       # 新着があれば後ろに繋ぐ
            with open(path, "r", encoding="utf-8") as f:
                rest += [l for l in f.read().splitlines() if l.strip()]
            os.remove(path)
        _write_inflight(inflight, rest)
        return rest, inflight
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return [], inflight
    with open(path, "r", encoding="utf-8") as f:
        lines = [l for l in f.read().splitlines() if l.strip()]
    os.replace(path, inflight)     # 原子的に退避(この瞬間に落ちてもinflightに全行が残る)
    return lines, inflight


def _write_inflight(path, lines):
    if not lines:
        if os.path.exists(path):
            os.remove(path)
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)          # 書き換えも原子的に(途中で落ちても壊れた箱を残さない)


def _processed_msg_ids():
    ids = set()
    try:
        for pl in open(PROCESSED, encoding="utf-8", errors="replace"):
            try:
                m = json.loads(pl).get("msg_id")
                if m:
                    ids.add(str(m))
            except Exception:
                continue
    except OSError:
        pass
    return ids


def drain_queue():
    """★O1(改善書P0-1): llm-growth宛はカットオーバー(2026-07-19 鳩退役)後、
    jsonl(discord_inbox_llm.jsonl)には来ず LeaseQueue に入る。旧実装はjsonlしか
    見ていなかったため llm-growth が事実上無応答だった(30分放置エスカレまで沈黙)。
    ここで queue の dept='llm-growth' を claim→handle→ack する。二重処理はPROCESSED台帳で防ぐ。
    dept_daemon.drain_queue と同じ契約。DBが無い間は何もしない(fail-open)。"""
    if not os.path.exists(QDB):
        return 0
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
        from leasequeue import LeaseQueue
        q = LeaseQueue(QDB)
    except Exception:
        return 0
    done = 0
    try:
        processed = _processed_msg_ids()
        # ★2026-09-16 拾う部屋が2つになった。TAG_DEPT(プロンプト変換と学習)は
        #   **Claudeの常駐を持たない**ので、ここで畳まないとキュー行が誰にも拾われず
        #   45秒で受領スタンプ・30分でrouterへエスカレする(=画像1枚ごとに空騒ぎになる)。
        for _dept in (QUEUE_DEPT, TAG_DEPT):
            n = 0
            while n < 5:  # 1巡回の上限(暴走ガード)。★上限は部屋ごと=
                #   自室が5件詰まっている巡回でもタグ部屋が飢えない(共有カウンタにしない)。
                n += 1
                c = q.claim(dept=_dept, who="local_responder")
                if c is None:
                    break
                rec = c["body"] if isinstance(c["body"], dict) else {}
                mid = str(rec.get("msg_id", c.get("msg_id") or ""))
                if mid and mid in processed:
                    q.ack(c["id"], result="skip(処理済)")
                    continue
                try:
                    if _dept == TAG_DEPT:
                        # 画像→タグ列。文章だけの便は中で何もせずに畳む(引き金は添付そのもの)。
                        handle_tag_request(rec, json.dumps(rec, ensure_ascii=False))
                        q.ack(c["id"], result="タグ列")
                    else:
                        # claim は dept=llm-growth 限定なので、この経路は定義上すべて自室の便
                        handle(rec, json.dumps(rec, ensure_ascii=False), growth=True)
                        q.ack(c["id"], result="qwen応答")
                except Exception as e:
                    # 失敗は握りつぶさずmain箱へ回す(dept_daemonと同じ安全網)
                    q.ack(c["id"], result=f"失敗:{type(e).__name__}")
                    append_line(FOR_CLAUDE, json.dumps(rec, ensure_ascii=False))
                done += 1
    finally:
        q.close()
    if done:
        print(f"  queue経路 {done}件処理 [{QUEUE_DEPT}/{TAG_DEPT}]")
    return done


def main():
    # ★1回きりの手作業(Chami「トーク履歴見て採点とかしておいて」)。
    #   ★常駐ループには**入れない**。毎巡回で投函したら、五月の部屋が同じ依頼で埋まる。
    if "--grade-history" in sys.argv:
        sys.exit(0 if grade_history(dry_run="--dry-run" in sys.argv) else 1)
    once = "--once" in sys.argv
    # ★2026-09-12 ここから先が**常駐ループ**= 計測台帳の行が "live" を名乗ってよい唯一の経路。
    #   import して ask_growth() を直に叩いた行は manual のまま残る(上の LIVE のコメントが経緯)。
    set_live()
    # ★起動表示を実態に合わせた(2026-07-27)。旧「Claude稼働中は待機」は**嘘**だった:
    #   claude_is_active() はどこからも呼ばれておらず、実際は無条件で自室をドレインしている。
    print(f"優依(LLM) 起動 (model={MODEL}, 30秒間隔, 自室llm-growthのみ・Claudeの稼働に関わらず常時応対"
          f"／画像は自分で答えて{EDU_DEPT}(中野五月)へ採点依頼)")
    while True:
        # llm-growth部屋(自分の部屋)はClaude稼働中でも常時応対
        llm_lines, inflight = drain_lines(INBOX_LLM)
        if llm_lines:
            for i, line in enumerate(llm_lines):
                try:
                    # discord_inbox_llm.jsonl は自室(llm-growth)専用の箱
                    handle(json.loads(line), line, growth=True)
                except Exception as e:
                    print(f"  処理失敗(llm箱): {type(e).__name__}")
                    append_line(FOR_CLAUDE, line)
                # 1行を着地させるたびに残りだけをinflightへ書き戻す。
                # 落ちても「未処理の行だけ」が残る(着地済みの重複返信より、喪失を避ける方を採る)。
                _write_inflight(inflight, llm_lines[i + 1:])
        # ★O1: カットオーバー後の本経路=LeaseQueue(dept='llm-growth')をドレイン。
        #   上のjsonl(discord_inbox_llm.jsonl)は鳩退役で新着が来ないため、こちらが実体。
        try:
            drain_queue()
        except Exception as e:
            print(f"  queue drain失敗: {type(e).__name__}")
        # ★main箱(部門の依頼)には一切触れない=ローカルを一次受付として挟まない
        #   (Chami指示2026-07-15「一次受けにローカルを挟むな・全部門で排除」)。
        #   以前はClaude不在時にmain箱をドレインしてqwen応答/for_claude箱へ再エスカレしていたが、
        #   それが「依頼が横取りされて司令塔に届かない/無視される」原因だった。
        #   部門の依頼は司令塔(Claude)の専任。main箱はそのまま司令塔が処理する。
        #   ローカルqwenは自室 llm-growth(上の INBOX_LLM)だけを応対する。
        if once:
            print("1回分の処理完了(自室llm-growthのみ・main箱は司令塔専任)")
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
