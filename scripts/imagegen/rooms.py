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
  トラブル役(アメス)が「どこに置けばいいか」を部屋へ言う(silent failにしない)。
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

TROUBLE_PERSONA = "アメス"   # Chami指示「トラブル時アメス」= 失敗の報せはこの名義で出す
TROUBLE_SUFFIX = "(自動)"    # ★生きているアメスの席と混ざらないよう、機械が出した便だと分かる形にする

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
        "label": "fusoh_v0(手描き風)",
    },
    "imagegen-fusoh-v2": {
        "channel_id": "1548842219744657449",
        "lora_hint": "fusoh_v2",
        "lora_strength": 0.8,
        "ckpt": CKPT_ILLUSTRIOUS_V2,
        "persona": "中野五月",
        "label": "fusoh_v2(漫画)",
    },
}

# LoRAを当てる部屋だけ(既存の imagegen は素のまま=挙動を1文字も変えない)
LORA_DEPTS = tuple(d for d, v in ROOMS.items() if v.get("lora_hint"))

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
# ★合図の形= 「頭に付ける印」または「日本語の言い回し」のどちらでもよい(片方だけだと
#   取りこぼす)。印だけにすると素のプロンプト(「銀髪ロング 制服 桜」)が通らなくなり、
#   言い回しだけにすると印を打った短い注文が通らなくなる。
CUE_REQUIRED_DEPTS = ("imagegen-fusoh-v0", "imagegen-fusoh-v2")

# 頭に付ける印。Discordの `/` はスラッシュコマンドUIを出してしまうので使わない。
# ★先頭の「生成依頼」はChami本人が決めた語(2026-09-16 02:32 msg=画像生成ローカル-fusoh_v0手描き風・
#   原文「生成依頼 / これがひとまずトリガーワードの一つとして設定しといて」)。**Chamiの語を先頭に置く**=
#   部屋へ出す説明(cue_help)にもこれが最初に載る。★改行を挟んで本文が来る書き方なので、
#   印を剥がす時に改行も落とす(order_of の strip を見ろ)。
CUE_PREFIXES = ("生成依頼", "!描いて", "!描", "!draw", "!e", "!絵",
                "絵:", "絵:", "画:", "画:", "描いて:", "描いて:")
_CUE_SORTED = tuple(sorted(CUE_PREFIXES, key=len, reverse=True))


def cue_required(dept):
    """その部屋は合図が要るか。"""
    return dept in CUE_REQUIRED_DEPTS


def order_of(dept, text, natural=None):
    """この便を画像注文として拾うか。返り= (拾うか, 絵に渡す本文)。

    natural= 「絵を描いて」を読む日本語判定(local_responder.wants_image を渡す想定)。
             語彙ゲートの正本は向こうにあるので、こちらでは持たず**受け取る**。
    ★合図の印を剥がした本文を返す=「!描 銀髪の少女」→「銀髪の少女」。
      印だけで本文が空なら (True, "") を返す。聞き返すのは呼んだ側の仕事。
    """
    body = (text or "").strip()
    if not body:
        return False, ""
    for p in _CUE_SORTED:
        if body.startswith(p):
            return True, body[len(p):].strip(" 　:：、,\r\n\t")
    if not cue_required(dept):
        return True, body           # 既存室=従来どおり全部注文
    if natural is not None and natural(body):
        return True, body
    return False, body


def cue_help():
    """合図の書き方(部屋へ出す1行)。印は正本のここから引く=説明とコードがずれない。"""
    return ("絵を頼む時は頭に " + " / ".join(CUE_PREFIXES[:5])
            + " のどれかを付けてね(例: 「!描 銀髪ロング 制服 桜」)。"
              "「〜の絵を描いて」と書いてくれても拾うよ。それ以外は雑談として読むだけにする。")


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
    cands = sorted(f for f in os.listdir(LORA_DIR)
                   if f.lower().endswith(".safetensors") and hint.lower() in f.lower())
    if not cands:
        return None, ("『" + hint + "』を含む .safetensors が置き場に無い。置き場= " + LORA_DIR)
    # 同じhintで複数あるなら、更新が一番新しいものを使う(学習し直した最新を拾う)
    cands.sort(key=lambda f: os.path.getmtime(os.path.join(LORA_DIR, f)), reverse=True)
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
