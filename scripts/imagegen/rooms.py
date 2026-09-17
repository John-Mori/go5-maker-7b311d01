# -*- coding: utf-8 -*-
"""画像生成ルームの正本(どの部屋が、どのLoRAで描くか)。

2026-09-14 研究室HQ。Chami直令 msg 1548842898773123105=
  「カテゴリID: 1548732279973617696 / 部屋ID: 1548514430621319178・1548842219744657449
    二つ部屋を建てた。それぞれのLoRAで画像生成するためのルーム。優依(言語ローカルLLM)が
    橋渡し役になって画像のこれらの部屋に表示する。そのための配線や準備をお願い。
    キャラはカスミと五月で。トラブル時アメスという構成。」

★なぜ**部門(dept)で引くのか**= 表示名で引いていた旧実装が実際に死んでいたから。
  実測(2026-09-14・研究室HQ)=
    local_responder.IMAGE_ROOM = "画像生成ルーム"
    台帳(local/discord_channels.json)の実名 = "ローカルllm-画像生成ルーム-優依"
  → `channel == IMAGE_ROOM` は**一度も真にならず**、generate.py 側の貼り先探索も
    StopIteration で落ちる形だった。responder_log.jsonl 135行のうち**画像便は0件**。
  部屋の表示名はChamiがいつでも変えられる。**変わらないのは id と dept だけ**なので、
  ここは dept を鍵にし、表示名は台帳から実行時に引く。

★LoRAの実体は**まだこの機械に無い**(2026-09-14 実測。D:全体の .safetensors 23件を数え、
  ComfyUI/models/loras は `put_loras_here` だけの空フォルダ)。だから固定のファイル名を
  書かず、**名前の一部(lora_hint)で loras フォルダを探す**形にした=
  Chamiが .safetensors を置いた瞬間に配線が生きる。見つからない間は
  トラブル役が「どこに置けばいいか」を部屋へ言う(silent failにしない)。
  ★誰がその役かは**部屋ごとに引く**= 下の `trouble_persona_of()`(2026-09-17 C-082)。
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))

# ComfyUIのLoRA置き場(実測 2026-09-14= 空。extra_model_paths.yaml は checkpoints だけを
# C:/Users/chami/AIModels/ へ逃がしており、loras はComfyUI本体の下のまま)。
LORA_DIR = os.path.join("D:" + os.sep, "総合スタートファイル", "AIArtCreater",
                        "ComfyUI", "models", "loras")

# 既定のチェックポイント。fusohの2室は「使い方.md」でChamiが本命に据えた Illustrious XL v2.0
# (実測= C:/Users/chami/AIModels/checkpoints/Illustrious-XL-v2.0.safetensors 6,938MB)。
CKPT_ILLUSTRIOUS_V2 = "Illustrious-XL-v2.0.safetensors"
CKPT_WAI = "waiIllustriousSDXL_v170.safetensors"

TROUBLE_PERSONA = "アメス"   # ★**既定値**。部屋が trouble_persona を持たない時だけここへ落ちる(fail-open)
TROUBLE_SUFFIX = "(自動)"    # ★生きている本人の席と混ざらないよう、機械が出した便だと分かる形にする

# ============================================================================
# トラブル名義(2026-09-17 C-082・Chami直令 msg 1550060415462146121)
# ----------------------------------------------------------------------------
# 原文=「**メンバーにアメスを入れちゃってるからダメなのかも。抜いといて。その代わりをカスミに。**」
#   直前の直令(msg 1550057587532365957)=「ローカルは基本的にアメスの役割はカスミがカバーしてよ」。
# → LoRA3室(fusoh_v0 / fusoh_v2 / itsumono)のトラブル名義を **カスミ** へ。
#   ★**定数を書き換えない**= 素の `imagegen` 室(persona=優依)まで一緒に動いてしまうから(C-035)。
#     部屋ごとに `trouble_persona` を持たせ、**持たない部屋は上の定数へ落ちる**= 素の室は1文字も変わらない。
#   ★戻す時も1行(該当室の trouble_persona を消すか書き換えるだけ)。
#
# ★**名義だけ替えると口調が食い違う**(台帳と口のズレ= 今日 ORG-49 で踏んだのと同じ型)。
#   なので文面も名義で引く。★**"アメス" の3文面は 2026-09-17 以前と1文字も同じ**=
#   素のimagegen室から出る文は従来のまま(「広げていない」の証明はここで取れる)。
#   ★カスミの文面は**イージス研究室が書いた仮**だ。声の正本は人事部門(kasumi.md)にある=
#     直しが要るなら人事部門の手番。ここは配線側の置き場でしかない。
_TROUBLE_FALLBACK = "理由が取れなかった。local/llm/responder_log.jsonl を見て。"

TROUBLE_VOICE = {
    "アメス": {
        "lora_missing": (
            "この部屋のLoRAがまだ置き場に無いから、絵は出せない。\n"
            "{why}\n"
            "そこへ .safetensors を置いてくれれば、次の便からそのまま描けるようになってる。"
            "置き場所さえ埋まれば、あたしが出てくる用事はもう無いわ。"
        ),
        "tag_timeout": (
            "日本語を英語のタグに直す係(ローカルのLLM)が時間内に返してこなかったから、"
            "絵まで行けなかった。\n"
            "{why}\n"
            "描く側(ComfyUI)は無罪よ。たいていはVRAMの取り合い="
            "ComfyUIが前の絵のモデルを抱えたままだと、この係が前に進めなくなるの。"
            "もう一度同じ言葉で頼んでくれれば、空けてから引き直すようにしてあるわ。"
        ),
    },
    "カスミ": {
        "lora_missing": (
            "結論から言おう——この部屋のLoRAが置き場に無い。だから絵は出せないのだよ。\n"
            "{why}\n"
            "そこへ .safetensors を置いてくれれば、次の便からそのまま描けるようになっている。"
            "置き場さえ埋まれば、この報せは二度と出ない。それが一番いい終わり方なのだがね。"
        ),
        "tag_timeout": (
            "日本語を英語のタグに直す係(ローカルのLLM)が時間内に返してこなかった。"
            "絵まで行き着けなかったのだよ。\n"
            "{why}\n"
            "描く側(ComfyUI)は無実だ。犯人はたいていVRAMの取り合いでね="
            "ComfyUIが前の絵のモデルを抱えたままだと、この係が前へ進めなくなる。"
            "もう一度、同じ言葉で頼んでくれたまえ。空けてから引き直すようにしてある。"
        ),
    },
}

# ★名義の割り当ては**HQの解釈**だ(Chami原文は「キャラはカスミと五月で」まで。どちらの部屋が
#   どちらか、までは書かれていない)。五月(中野五月=五等分の花嫁)を**漫画**のv2へ、
#   カスミ(霧原かすみ=探偵)を手描き風のv0へ置いた。逆にしたければ下の "persona" を入れ替えるだけ。
#   絵を作るのは優依のローカル経路(local_chain.py)で変わらない=表に出る名義だけの話。

ROOMS = {
    # 既存室(2026-07 開設)。LoRA無し=素のモデルの実験場。名義は優依のまま。
    "imagegen": {
        "lora_hint": None,
        "ckpt": CKPT_WAI,
        "persona": "優依",
        "label": "素のモデル(LoRA無し)",
    },
    # ★2026-09-14 Chamiが建てた2室。
    "imagegen-fusoh-v0": {
        "channel_id": "1548514430621319178",
        "lora_hint": "fusoh_v0",
        "lora_strength": 0.8,
        "ckpt": CKPT_ILLUSTRIOUS_V2,
        "persona": "カスミ",
        "trouble_persona": "カスミ",   # 2026-09-17 C-082(旧= アメス)。平時も主なので名義は変わらない
        "label": "fusoh_v0(手描き風)",
    },
    "imagegen-fusoh-v2": {
        "channel_id": "1548842219744657449",
        "lora_hint": "fusoh_v2",
        "lora_strength": 0.8,
        "ckpt": CKPT_ILLUSTRIOUS_V2,
        "persona": "中野五月",
        # ★この室だけ平時(中野五月)とトラブル時(カスミ)で名義が入れ替わる。Chami原文どおり。
        #   五月へ戻す一言が来たら、この1行を "中野五月" に書き換えれば戻る。
        "trouble_persona": "カスミ",   # 2026-09-17 C-082(旧= アメス)
        "label": "fusoh_v2(漫画)",
    },
    # ★2026-09-16 Chamiが建てた3室目(便 ESC-local-lab-1549779860707090463)。原文=
    #   「1549637404401598495　ここのルームは "D:\総合スタートファイル\AIArtCreater\ComfyUI\
    #     models\loras\itsumono\checkpoint-e50_s600.safetensors"
    #     このRoLAを使って生成してねという部屋。」
    #   ★同日13:25のChami直「今後も1LoRAにつき1部屋を立てる。」「ルールは統一。」の3室目にあたる
    #     =新しい決まりではなく、既に下りている決まりの3回目の実行。
    #   ★実測(2026-09-16・Discord API の GET /channels)= 部屋名「twitter用-生成依頼を冒頭に付ける」。
    #     親カテゴリ= ローカルLLM部門(1548732279973617696)= fusoh 2室と同じ。
    #   ★LoRAの実物も実測済= loras\itsumono\checkpoint-e50_s600.safetensors
    #     (256,056,360バイト・2026-09-16 18:33)。置き場を全部歩いて "itsumono" に当たるのはこの1本だけ
    #     =誤爆しない。hint はフォルダ名で当てている(fusoh 2室と同じ形)。
    #   ★2026-09-17 Chami直令で主人格が決まった(回送= 中野五月[llm-qa] DISPATCH-aegis-gl-1789630298503)。
    #     原文=「なるほど。カスミにやってもらおう。回しといて」(直前=itsumono室に主が未設定で絵が
    #     優依名義で出る、と中野五月が報告した流れ)。→ ここへ "persona" を1行足した=絵の名義がカスミになる。
    #     ★対象はこの1室だけ(C-035)。fusoh 2室・素のimagegen室の名義は1文字も動かしていない。
    #   ★2026-09-17 17:21 Chami直令で**絵の出力名義だけ優依へ戻した**(原文=「画像の出力名義は
    #     優依にしといて。」msg 1550059047619797124)。直前にChamiは「カスミが答えて・ローカルは
    #     カスミがカバー・好きだから」(msg 1550057587532365957)とも言っている=**会話の主はカスミ・
    #     絵の名義は優依**、と役割を分けたのが最新の意図。この "persona" は絵のpost名義にだけ効く
    #     (会話の返信はセッションの [カスミ] タグ側=この値に依らない)。★対象はこの1室だけ(C-035)。
    "imagegen-itsumono": {
        "channel_id": "1549637404401598495",
        "lora_hint": "itsumono",
        "lora_strength": 0.8,
        "ckpt": CKPT_ILLUSTRIOUS_V2,
        "persona": "優依",             # ★絵のpost名義だけ(2026-09-17 Chami直令 msg 1550059047619797124)
        "trouble_persona": "カスミ",   # 2026-09-17 C-082(旧= アメス)。会話の主と同じ人
        "label": "itsumono(twitter用)",
    },
}

def trouble_persona_of(dept):
    """その部屋で「絵が出ない」を言う名義。★ROOMSをその場で読む(定数を判定に使わない)。

    ★持たない部屋は TROUBLE_PERSONA へ落ちる= fail-open。**空席を作らない**=
      名義が引けずに送信が落ちると silent fail(誰も何も言わない)に退化するからだ。
    """
    who = str(((ROOMS.get(dept) or {}).get("trouble_persona") or "")).strip()
    return who or TROUBLE_PERSONA


def trouble_message(dept, kind, why=""):
    """トラブル時に部屋へ出す (名義, 本文)。kind= "lora_missing" / "tag_timeout"。

    ★文面は**名義で引く**(部屋ではない)= 同じ人はどの部屋でも同じ声で喋る。
    ★知らない名義・知らない kind なら既定(アメスの文面)へ落ちる= ここでも黙らない。
    """
    who = trouble_persona_of(dept)
    book = TROUBLE_VOICE.get(who) or TROUBLE_VOICE[TROUBLE_PERSONA]
    tmpl = book.get(kind) or TROUBLE_VOICE[TROUBLE_PERSONA].get(kind)
    if not tmpl:
        # ★知らない kind でも**空文字を返さない**。空を送ると誰も何も言わないのと同じ=
        #   このモジュールが潰そうとしている silent fail そのものになる。
        tmpl = "絵が出せなかった(理由の型『" + str(kind) + "』は文面をまだ持っていない)。\n{why}"
    body = tmpl.replace("{why}", (why or "").strip() or _TROUBLE_FALLBACK)
    return who, body


# LoRAを当てる部屋だけ(既存の imagegen は素のまま=挙動を1文字も変えない)
def lora_depts():
    """LoRAを当てる部屋の一覧。★ROOMSを**その場で**読む=部屋を1件足したら即座に効く。"""
    return tuple(d for d, v in ROOMS.items() if v.get("lora_hint"))


# ★これは「今の一覧」のスナップショットだ(表示・報告用)。**判定に使うな**=
#   判定は下の cue_required() / lora_depts() がROOMSを読み直す形に寄せてある。
LORA_DEPTS = lora_depts()

# ============================================================================
# 合図(雑談と画像注文の線引き)  2026-09-16 イージス研究室
# ----------------------------------------------------------------------------
# 依頼= アメス便 msg 1549468992396329025(依頼元 imagegen-fusoh-v0)。
#   実害= Chamiの雑談「これデーモン?デーモンの返信いらんよ」を優依が絵にしようとした
#         (優依便 1549467703876780033)→ Chamiが「優依!書かなくていいよ!」で制止。
#   真因= local_responder.handle() が「この部屋のChami便は**全部**注文」として
#         語彙ゲート(wants_image)を飛ばして handle_image_request へ直行していた
#         (2026-09-09 中野五月DISPATCHの配線。あの時の原文は「俺が画像生成のプロントを渡す」
#          =注文しか来ない前提だった。雑談も来る部屋になった今は前提が崩れている)。
#
# ★合図を要るのは**Chamiが名指しした2室だけ**(fusoh_v0 / fusoh_v2)。既存の
#   imagegen室は今までどおり全便を注文として扱う=1文字も挙動を変えない(C-035)。
#   広げたくなったら CUE_REQUIRED_DEPTS に dept を1つ足すだけで足りる。
#
# ★2026-09-16 03:0x Chami直で**合図は1本に絞った**。原文=
#     msg 1549476416641572937「生成’依頼  で始まるチャットじゃないと生成が始まらない仕組みにして。
#                              間違えて生成が走らないようにこのチャットで間に ‘をあえて入れた。」
#     msg 1549477000807194637「1。でも印はいらんかな」
#       (直前にアメスが出した二択= 1.「生成依頼」と!印だけを引き金に / 2.「〜の絵を描いて」も残す)
#   → 引き金は**「生成依頼」で始まる時だけ**。`!描`系の印も、「〜の絵を描いて」の曖昧マッチも外す。
#   ★中野五月便(llm-qa)の「LoRA名(fusoh_v0/fusoh_v2)をトリガーに」は**Chami本人のこの決定で
#     置き換わった**= LoRA名は引き金にしない(部屋がどちらのLoRAを使うかは ROOMS が持つ)。
#   ★Chamiが自分で打った「生成’依頼」(間に ‘ )は**当たらないのが正解**= 完全一致の頭合わせ。
# ★2026-09-16 13:25 Chami直で**部屋の建て方そのものが決まった**。原文=
#     msg 1549637220883759176「今後も1LoRAにつき1部屋を立てる。」
#     msg 1549637278559895655「ルールは統一。」
#   → 合図が要る部屋は**LoRAを持つ部屋すべて**。直書きの名簿をやめ、ROOMS から導出する。
#   理由(§3)= 直書きだと3つ目のLoRA部屋を建てた時、**誰かが手でここへ足さない限り**
#   合図が効かない=人手の入口。人手を要件にした機構は実測0件になる型だ。
#   ★今日の値は直書きの時と**同じ2件**= imagegen-fusoh-v0 / v2。挙動は1文字も変わらない。
#   ★既存の imagegen 室は lora_hint=None なので従来どおり素通し(C-035)。
CUE_REQUIRED_DEPTS = LORA_DEPTS

# 引き金はこの1語だけ。★増やす時はChamiの言葉を待つ(勝手に印を足すと誤発火の口が増える)。
#   ★改行を挟んで本文が来る書き方(「生成依頼\n\n銀髪ロング…」)なので、語を剥がす時に改行も落とす
#     (order_of の strip を見ろ)。
CUE_PREFIXES = ("生成依頼",)
_CUE_SORTED = tuple(sorted(CUE_PREFIXES, key=len, reverse=True))


def cue_required(dept):
    """その部屋は合図が要るか。

    ★**LoRAを持つ部屋なら要る**、が唯一の条件(2026-09-16 Chami「ルールは統一。」)。
      ROOMS をその場で読むので、**新しいLoRA部屋を ROOMS に1件足すだけ**で合図が継がれる
      =ここへ名前を書き足す手番は、もう存在しない。
    """
    return bool((ROOMS.get(dept) or {}).get("lora_hint"))


def order_of(dept, text, natural=None):
    """この便を画像注文として拾うか。返り= (拾うか, 絵に渡す本文)。

    natural= 「絵を描いて」を読む日本語判定(local_responder.wants_image)。
             ★合図が要る部屋では**使わない**(2026-09-16 Chami「1。でも印はいらんかな」=
               曖昧マッチを外す決定)。合図の要らない既存室のために引数だけ残してある。
    ★合図を剥がした本文を返す=「生成依頼 銀髪の少女」→「銀髪の少女」。
      合図だけで本文が空なら (True, "") を返す。聞き返すのは呼んだ側の仕事。
    """
    body = (text or "").strip()
    if not body:
        return False, ""
    if cue_required(dept):
        # ★この部屋は「生成依頼」で**始まる**時だけ。それ以外は何を書いてあっても雑談。
        for p in _CUE_SORTED:
            if body.startswith(p):
                return True, body[len(p):].strip(" 　:：、,\r\n\t")
        return False, body
    for p in _CUE_SORTED:
        if body.startswith(p):
            return True, body[len(p):].strip(" 　:：、,\r\n\t")
    return True, body               # 既存室=従来どおり全部注文(C-035)


def local_pipeline_order(dept, text):
    """この便は「合図付きの画像注文」=**ローカルの経路が処理する仕事**か。

    ★2026-09-16 Chami直令(hq msg 1549650439178428447)=
        「生成依頼 から始まった時は画像生成だから、Claud送信用の各種スタンプを押さないで」
      その便を描くのは優依のローカル経路(local_responder → local_chain → ComfyUI)で、
      Claude(司令塔)はその処理系に乗らない。なのに送信印(sendms)や既読/着手を押すと
      **乗っていない経路に乗った印**という嘘がChamiの画面に残る。
      = 2026-09-12「優依の自室にはsendmsを押すな」(NO_SENT_MARK_DEPTS)と同じ理屈の拡張だ。

    ★印を押すか押さないかの判定は**この関数1本**(ORG-11= 判定を2つ持たない)。
      押下点は分かっているだけで5つ(gateway生便/gatewayミラー/handle()の既読/
      relay直前の着手/走行中の既読・束ね印)ある。表を押下点の数だけ写さない。

    ★**合図が要る部屋に限る**(C-035)。既存の `imagegen` 室は Claude 自身が
      `scripts/imagegen/generate.py` を叩いて描く=あそこで印を消すとChamiの画面から
      「Claudeが動いている」合図が消える。Chamiの理由(「画像生成だから」=ローカルが描く)が
      当てはまるのは LoRA部屋だけなので、範囲もそこに合わせる。
    ★fail-open の責任は**呼び側**にある(ここが読めない時は従来どおり押す)。
    """
    if not cue_required(dept):
        return False
    ok, _ = order_of(dept, text)
    return bool(ok)


def cue_help():
    """合図の書き方(部屋へ出す1行)。語は正本のここから引く=説明とコードがずれない。"""
    cue = CUE_PREFIXES[0]
    return ("絵を頼む時は頭に「" + cue + "」と書いてね"
            "(例: 「" + cue + " 銀髪ロング 制服 桜」/ 改行して続けてもいい)。"
            "この言葉で始まらない便は全部、雑談として読むだけにする。")


def channel_name(dept):
    """台帳(discord_channels.json)から今の表示名を引く。★名前を直書きしない。"""
    try:
        chans = json.load(open(os.path.join(ROOT, "local", "discord_channels.json"),
                               encoding="utf-8"))
    except Exception:
        return ""
    for c in chans:
        if c.get("dept") == dept:
            return c.get("name") or ""
    return ""


def dept_of_channel(name):
    """表示名 → dept。画像ルーム以外は None(=この配線に入れない)。"""
    if not name:
        return None
    try:
        chans = json.load(open(os.path.join(ROOT, "local", "discord_channels.json"),
                               encoding="utf-8"))
    except Exception:
        return None
    for c in chans:
        if c.get("name") == name and c.get("dept") in ROOMS:
            return c.get("dept")
    return None


def find_lora(dept):
    """その部屋のLoRAの実ファイル名(ComfyUIへ渡す相対名)を返す。

    返り= (ファイル名 or None, 説明)。**推測で名前を作らない**=実在した物だけ返す。
    """
    conf = ROOMS.get(dept) or {}
    hint = conf.get("lora_hint")
    if not hint:
        return None, "この部屋はLoRA無し(素のモデル)"
    if not os.path.isdir(LORA_DIR):
        return None, "LoRAの置き場そのものが無い: " + LORA_DIR
    # ★**フォルダ名で分けてよい**(2026-09-16 Chami質問・原文「LoRAがふたつあって、LoRAの名前が
    #   ここの部屋名みたいに fusoh_v0 と fusoh_v2 があるから .safetensors 置くためのフォルダ名に
    #   できない?」)。答え= できる。置き場の**下を全部**歩き、hint が**ファイル名でも途中の
    #   フォルダ名でも**当たれば拾う= `loras/fusoh_v0/なんとか.safetensors` でそのまま効く。
    #   ComfyUIは loras からの相対パスを受ける。
    # ★区切りは **os.sep(Windowsなら "\")**。"/" では通らない(2026-09-16 実測)=
    #     `/object_info/LoraLoader` が挙げる実名は
    #       'fusoh_v0.safetensors\\checkpoint-e38_s570.safetensors'
    #     で、"/" にすると `POST /prompt` が **HTTP 400 Bad Request** を返す。
    #     同じタグ列で "\" に替えると 39秒で絵が出た。ここは見た目の綺麗さより実物に合わせる。
    cands = []
    for root, _dirs, files in os.walk(LORA_DIR):
        for f in files:
            if not f.lower().endswith(".safetensors"):
                continue
            rel = os.path.relpath(os.path.join(root, f), LORA_DIR)
            if hint.lower() in rel.lower():
                cands.append(rel)
    if not cands:
        return None, ("『" + hint + "』を含む .safetensors が置き場に無い(下のフォルダも見た)。"
                      "置き場= " + LORA_DIR + " ★ファイル名に入れても、"
                      "『" + hint + "』という名前のフォルダに入れてもいい。")
    # 同じhintで複数あるなら、更新が一番新しいものを使う(学習し直した最新を拾う)
    cands.sort(key=lambda r: os.path.getmtime(os.path.join(LORA_DIR, r)), reverse=True)
    return cands[0], "実在を確認: " + os.path.join(LORA_DIR, cands[0])


def describe():
    """人が読むための一覧(検査用。measure したことだけを書く)。"""
    out = []
    for dept, conf in ROOMS.items():
        lora, why = find_lora(dept)
        out.append("%-20s 部屋=%-32s LoRA=%-28s %s"
                   % (dept, channel_name(dept) or "(台帳に無い)", lora or "(無し)", why))
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(describe())
