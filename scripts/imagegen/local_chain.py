# -*- coding: utf-8 -*-
"""ローカル完結の画像経路(日本語の一言 → 絵)。

  python scripts/imagegen/local_chain.py "夜の書店で本を読む女の子"
  python scripts/imagegen/local_chain.py "..." --discord "画像生成ルーム" --persona "花海咲季"

Claude / ChatGPT / Gemini(ホイミン・ベホップ)を一切通さない。使うのは
  会話= LM Studio `gemma-4-12b-it`  http://127.0.0.1:1234/v1 (OpenAI互換)
  画像= ComfyUI + Illustrious-XL-v2.0  http://127.0.0.1:8188
の2本だけ。前提と実測は local/llm/local_only_chain_20260908.md。

★研究室HQが2026-09-08に置いた参考実装。所有はローカルllm教育部門(DISPATCH-llm-edu-1788850539055)。
  local_responder.py へ取り込む時は、この2つの罠を消さないこと=
    罠1 gemma-4-12b-it は推論モデル。思考は reasoning_content へ入り content とは別枠。
        max_tokens が小さいと思考で使い切って content が空文字で返る(実測: 300 → 空)。
        ★2026-09-16 追記(イージス研究室・実測)= 思考量は同じ注文でも毎回ばらつく
          (reasoning_tokens 911 / 1159 / 1210 / 1890)。旧既定1500は分布のど真ん中=
          五分五分で空が返っていた。既定を4000にし、空なら思考の中の最終案を拾い、
          それも外れたら予算倍で1回引き直す(to_tags / salvage_tags)。
          ★`enable_thinking=false` も `reasoning_effort=low` もこのモデルでは効かない
            (どちらも reasoning_tokens=1497 で打ち切り・content 0字)。思考は止められない。
    罠2 LLM常駐 + SDXL同時ロードの瞬間が 15,416MiB / 16,303MiB(残り0.9GB)。
        既定で画像生成の前にLLMを降ろす(C-058)。降ろしたくない時は --keep-model。
        ★2026-09-16 追記(イージス研究室・実測)= **逆向きも詰まる**。ComfyUIが描き終えた後も
          SDXLを抱えたままだと(実測 15,757MiB/16,303MiB・GPU 100%)、次の注文のタグ変換が
          前に進まず **382.8秒たっても返らない**。/free でVRAMを返させた瞬間に完了し、
          続く2回は 59.3秒 → 6.2秒。だから TAG_TIMEOUT(既定180秒)で早く諦め、
          1回目の時間切れでは free_comfy_vram() を叩いてから1回だけ引き直す。
          二度とも駄目なら rc=5(TAG_TIMEOUT)で親へ返す。
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    # ★親(local_responder)は stdout を utf-8 で読む。ここを直さないと日本語の
    #   失敗理由が cp932 で出て、部屋に文字化けが貼られる(実測 2026-09-14)。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LMS_API ="http://127.0.0.1:1234/v1/chat/completions"
LMS_EXE = os.path.expandvars(r"%USERPROFILE%\.lmstudio\bin\lms.exe")
CHAT_MODEL = "gemma-4-12b-it"
COMFY_API = "http://127.0.0.1:8188"
CKPT = "Illustrious-XL-v2.0.safetensors"
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))

#: タグ変換1回あたりのハード上限(秒)。★推測で置いた数字ではない。2026-09-16 実測=
#    ComfyUIがVRAMを掴んだまま(15,757MiB / 16,303MiB・GPU 100%)だと **382.8秒たっても
#    返ってこない**。ComfyUIに /free でVRAMを返させた直後に同じ呼び出しが完了し、
#    続く2回は **59.3秒 → 6.2秒**。つまり空きがあれば10秒未満、冷えていても1分で返る。
#    180秒 = 実測最悪(59.3秒)の3倍。ここを超えたら「返ってこない側」に入っている。
#  ★旧既定は900秒だった= 事故当日(22:39:51起動→22:55:00死亡・約909秒)の待ち時間そのもの。
TAG_TIMEOUT = float(os.environ.get("IMAGEGEN_TAG_TIMEOUT") or 180)


class TagTimeout(RuntimeError):
    """タグ変換段(gemma)が制限時間内に返さなかった。

    ★描画段(ComfyUI)の失敗とは別物として扱う= 部屋に出す文面も分ける。
    """

# ★2026-09-17 ローカル研究室(カスミ): 教材 local/attachments/imagegen_totags_kyozai_go5org_00017.md
#   の P1〜P3 を SYSTEM に効かせた。plumbing 修正(07720c5)で注文文が to_tags まで届くように
#   なったが、それだけでは「届いた注文を注文通りのタグにする」品質は上がらない=ここが直しどころ。
#     P1 全要素を落とすな(各カテゴリから最低1タグ)
#     P2 優先度=語順+中強調((tag:1.2)、盛りすぎ厳禁)
#     P3 語彙の穴は自然文で残す(無理に既定タグへ丸めて消さない)
#   ★P4(除外→negative)は to_tags の出力契約(positiveの1本)を変える別口=まだ触っていない。
#     P5(4:5比)は generate.py の EmptyLatentImage で to_tags の話ではない。
SYSTEM = (
    "あなたは日本語の指示をSDXL(Illustrious系・Danbooru語彙前提)向けの英語プロンプトへ変換する係です。\n"
    "出力はカンマ区切りの英語タグ列だけ。説明・前置き・引用符・見出しは書かない。\n"
    "変換のルール:\n"
    "1) 指示に出てくる要素(髪・瞳・顔/表情・体型・服装・ポーズ・構図/視点・背景・光)を、"
    "各カテゴリから最低1つはタグにする。カテゴリを丸ごと落とさない。\n"
    "2) 「最優先」「特に」など強調された要素は、タグ列の前方に置き (tag:1.2) の中強調で効かせる"
    "(1.3以上には盛らない)。\n"
    "3) Danbooru語彙に無い細かな特徴(例:花弁のように重なった虹彩)は、既存タグへ無理に丸めず、"
    "短い英語の自然文で言い換えて残す(消さない)。\n"
    "末尾に品質タグ(masterpiece, best quality, highres)を必ず含める。"
)

# ★2026-09-23 イージス研究室(P4= 除外→negative)。発注= 研究室HQ DISPATCH-aegis-gl-1790166561731 /
#   Chami原文 msg 1552295146882736229「【ポジティブ】【ネガティブ】で分けれたらいいな」。
#   ネガ側は SYSTEM を流用しない= SYSTEM は品質タグを必ず足すので、ネガへ masterpiece 等が入ると逆に効く。
NEG_SYSTEM = (
    "あなたは日本語で書かれた『絵に描いてほしくないもの』を、SDXL(Illustrious系・Danbooru語彙前提)の"
    "ネガティブプロンプト用の英語タグへ変換する係です。\n"
    "出力はカンマ区切りの英語タグ列だけ。説明・前置き・引用符・見出しは書かない。\n"
    "書かれたものだけをタグにする。品質タグ(masterpiece 等)や、書かれていない要素は足さない。"
)

_MARK_RE = re.compile(r"【(ポジティブ|ネガティブ)】")


def split_pos_neg(text):
    """本文を【ポジティブ】【ネガティブ】で切り分ける。返り値= (ポジ本文, ネガ本文 or None)。

    ★マーカーが1つも無い時は (text, None)= 旧経路と1バイトも変えない(仕様A)。
    ★マーカーより前の地の文はポジへ入れる(仕様C)。同じマーカーが複数あれば順に繋ぐ。
    ★中身が空のマーカーは無かったものとして扱う= ネガが空なら None を返す(仕様3)。
    """
    text = str(text or "")
    parts = _MARK_RE.split(text)
    if len(parts) == 1:
        return text, None
    pos = [parts[0].strip()]
    neg = []
    for kind, body in zip(parts[1::2], parts[2::2]):
        (pos if kind == "ポジティブ" else neg).append(body.strip())
    pos_s = "\n".join(p for p in pos if p)
    neg_s = "\n".join(n for n in neg if n)
    return pos_s, (neg_s or None)


def _post(url, payload, timeout=None):
    """LM Studioへ1発投げる。★時間切れは TagTimeout に化かして上へ返す。

    ★socket の読み取り待ちは `socket.timeout` でも `URLError(reason=timeout)` でも
      上がってくる(どちらで来るかは接続段か読み取り段かで変わる)。両方を同じ口で受ける
      = 片方だけ拾う実装は「たまに素の例外が漏れる」という分かりにくい壊れ方になる。
    """
    timeout = TAG_TIMEOUT if timeout is None else timeout
    req = urllib.request.Request(
        url, json.dumps(payload).encode("utf-8"), {"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except socket.timeout:
        raise TagTimeout("%.0f秒たっても応答が無かった" % (time.time() - t0))
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise TagTimeout("%.0f秒たっても応答が無かった" % (time.time() - t0))
        raise
    except TimeoutError:
        raise TagTimeout("%.0f秒たっても応答が無かった" % (time.time() - t0))


def free_comfy_vram():
    """ComfyUIが遊んでいるならVRAMを返させる(戻り値= 返させたか)。

    ★2026-09-16 実測でここが16分ハングの正体だった= ComfyUIがSDXLを抱えたまま
      15,757MiB/16,303MiB を占め、gemma が前に進めない。/free を叩いたら 9,197MiB まで
      落ち、その瞬間に止まっていた呼び出しが完了した。
    ★描画待ちの列がある時は触らない(人の絵を巻き添えにしない)。失敗しても止めない。
    """
    try:
        q = json.loads(urllib.request.urlopen(COMFY_API + "/queue", timeout=10).read())
        if q.get("queue_running") or q.get("queue_pending"):
            return False
        req = urllib.request.Request(
            COMFY_API + "/free",
            json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8"),
            {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception:
        return False


def ensure_server():
    """LM Studioのサーバが落ちていたら上げる(電源断のあと上がってこないため)。"""
    try:
        urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=5).read()
        return True
    except Exception:
        pass
    if not os.path.exists(LMS_EXE):
        print("LM Studioのlms.exeが見つからない: " + LMS_EXE)
        return False
    print("LM Studioのサーバが落ちていたので起動する…")
    subprocess.run([LMS_EXE, "server", "start"], capture_output=True, text=True, timeout=180)
    for _ in range(20):
        try:
            urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=5).read()
            return True
        except Exception:
            time.sleep(3)
    return False


#: タグ列らしい1行か= カンマが3つ以上・日本語を含まない・記号だけでない。
#  ★形は測って決めた(2026-09-16実測)= 思考の中では `Final Tag List:` の直後に
#    `long hair, black hair, red hair, ... , masterpiece, best quality, highres`
#    という**完成した1行**が書かれてから、その後で推敲に戻って予算を食い潰す。
#    つまり空contentの時でも、**答えはもう書かれている**ことが多い。
_JP = re.compile(r"[ぁ-んァ-ヶ一-龠]")


def _looks_like_tags(line):
    line = line.strip().strip("*").strip("`").strip()
    if line.count(",") < 3 or _JP.search(line):
        return ""
    if not re.search(r"[a-zA-Z]{3}", line):
        return ""
    return line


def salvage_tags(reasoning):
    """思考(reasoning_content)から、貼れる形のタグ列を1行だけ拾う。

    ★これは「推測で埋める」ではない= モデルが自分で書いた最終案をそのまま拾うだけだ。
      拾えなければ空を返す(でっち上げない)。
    """
    if not reasoning:
        return ""
    lines = reasoning.splitlines()
    # ① 「Final Tag List:」等の見出しの直後を最優先で見る(実測で一番当たる)
    for i, ln in enumerate(lines):
        if re.search(r"(final|finished|result).{0,12}(tag|prompt|list)", ln, re.I):
            for nxt in lines[i + 1:i + 4]:
                got = _looks_like_tags(nxt)
                if got:
                    return got
            got = _looks_like_tags(ln.split(":", 1)[-1] if ":" in ln else "")
            if got:
                return got
    # ② 見出しが無ければ、末尾から見て最初のタグ列らしい行(推敲後=新しい方を採る)
    for ln in reversed(lines):
        got = _looks_like_tags(ln)
        if got:
            return got
    return ""


def to_tags(text, max_tokens=4000, system=None):
    """日本語 → 英語タグ列。★max_tokensを削るな(罠1)。

    ★2026-09-16 ここで実際に絵が出なくなった(imagegen-fusoh-v0・reason=local_chain_rc1)。
      測ったらこうだった= 同じ注文文で reasoning_tokens が **911 / 1159 / 1210 / 1890** と
      毎回ばらつく。**旧既定の1500は分布のど真ん中**で、超えた回は content が空になる。
      = 「たまに落ちる」のではなく**五分五分の賭けを既定にしていた**。
    ★つまみで思考を止める道は塞がっている(実測)=
      `chat_template_kwargs={"enable_thinking": False}` も `reasoning_effort="low"` も
      このモデルでは無視され、どちらも reasoning_tokens=1497 で予算を食い切って空を返した。
      だから「思考をやめさせる」ではなく「**思考しても落ちない**」形にする。
    ★三段で受ける(可用性に関わる所は fail-open= 判定不能なら喋る側へ倒す)=
      ① 予算を実測の最大(1890)の倍以上へ上げる
      ② それでも空なら、思考の中に既に書かれている最終案を拾う(salvage_tags)
      ③ それでも空なら、予算を倍にして1回だけ引き直す
      ここまで外れて初めて例外にする。**例外の文面は残す**= 黙って空を返さない。
    """
    tried = []
    for attempt in (1, 2):
        budget = max_tokens * attempt
        try:
            d = _post(LMS_API, {
                "model": CHAT_MODEL, "temperature": 0.4, "max_tokens": budget,
                "messages": [{"role": "system", "content": system or SYSTEM},
                             {"role": "user", "content": text}],
            })
        except TagTimeout as e:
            tried.append("%s回目: %s" % (attempt, e))
            if attempt == 2:
                raise TagTimeout(
                    "タグ変換が %.0f秒×2回とも返らなかった(%s)。"
                    % (TAG_TIMEOUT, " / ".join(tried)))
            # ★1回目の時間切れは、たいてい VRAM の食い合いだ(上の実測)。
            #   空けてから1回だけ引き直す。空けられなければそのまま引き直す。
            freed = free_comfy_vram()
            print("  タグ変換が時間切れ(%s)。ComfyUIのVRAM解放=%s。もう1回だけ引く…"
                  % (e, "した" if freed else "できなかった"))
            continue
        msg = d["choices"][0]["message"]
        det = d.get("usage", {}).get("completion_tokens_details", {})
        tried.append("%s回目: reasoning_tokens=%s / max_tokens=%s"
                     % (attempt, det.get("reasoning_tokens"), budget))
        tags = (msg.get("content") or "").strip().strip('"').replace("\n", " ")
        if tags:
            return tags
        tags = salvage_tags(msg.get("reasoning_content") or "")
        if tags:
            # ★拾って進んだことを黙らせない(どこから来た値かが後で分かるように)
            print("  content が空だったので思考の中の最終案を拾った: " + tags[:120])
            return tags
    # 罠1をそのまま踏んだ時に、黙って空を返さず理由を出す
    raise RuntimeError(
        "タグ列が空で返った。思考(reasoning)で予算を使い切り、思考の中からも拾えなかった"
        "(%s)。モデル %s の挙動が変わっていないか見ろ。" % (" / ".join(tried), CHAT_MODEL))


def unload_llm():
    """画像生成の前にVRAMを空ける(罠2)。失敗しても止めない。"""
    if not os.path.exists(LMS_EXE):
        return
    try:
        subprocess.run([LMS_EXE, "unload", "--all"], capture_output=True, text=True, timeout=120)
    except Exception:
        pass


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    channel = persona = out = None
    keep = False
    dept = lora = None
    ckpt = CKPT
    lora_strength = 0.8
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--discord":
            channel = args[i + 1]; i += 2
        elif a == "--persona":
            persona = args[i + 1]; i += 2
        elif a == "--out":
            out = args[i + 1]; i += 2
        elif a == "--keep-model":
            keep = True; i += 1
        elif a == "--dept":
            dept = args[i + 1]; i += 2
        elif a == "--lora":
            lora = args[i + 1]; i += 2
        elif a == "--lora-strength":
            lora_strength = float(args[i + 1]); i += 2
        elif a == "--ckpt":
            ckpt = args[i + 1]; i += 2
        else:
            rest.append(a); i += 1
    text = " ".join(rest)
    # ★2026-09-23 【ポジティブ】【ネガティブ】の切り分け(上の split_pos_neg)。マーカー無しは旧と同じ。
    pos_text, neg_text = split_pos_neg(text)
    if not pos_text.strip():
        # ★空のpromptを ComfyUI へ投げない(HTTP 400 の件と同じ穴)= rc=6 で親に聞き返させる
        print("EMPTY_POSITIVE 描く中身(ポジティブ)が空だった")
        sys.exit(6)

    # ★2026-09-14 研究室HQ: --dept を足した(Chami直令 msg 1548842898773123105)。
    #   部屋ごとにLoRAが違うので、**どのLoRAで描くかは部屋(dept)から引く**。正本= rooms.py。
    #   --dept を付けない従来の呼び方は1文字も挙動が変わらない(既定のCKPT・LoRA無し)。
    if dept:
        sys.path.insert(0, _HERE)
        import rooms                                  # noqa: E402
        conf = rooms.ROOMS.get(dept)
        if conf is None:
            print("知らない部屋だ: " + dept + " (正本= scripts/imagegen/rooms.py)")
            sys.exit(4)
        ckpt = conf.get("ckpt") or ckpt
        lora_strength = conf.get("lora_strength", lora_strength)
        if lora is None and conf.get("lora_hint"):
            lora, why = rooms.find_lora(dept)
            if not lora:
                # ★黙って素のモデルで描かない= LoRA別の部屋なのにLoRA無しの絵が出ると
                #   「効いている」と誤読される。理由を出して止める(トラブル役が拾う)。
                print("LORA_MISSING " + why)
                sys.exit(3)
            print("LoRA: " + lora + " (強さ %.2f) / %s" % (lora_strength, why))

    if not ensure_server():
        print("LM Studioのサーバが上がらない。ここで止める。")
        sys.exit(2)

    t0 = time.time()
    try:
        tags = to_tags(pos_text)
        neg_tags = to_tags(neg_text, system=NEG_SYSTEM) if neg_text else ""
    except TagTimeout as e:
        # ★ここで黙って落ちない= 親(local_responder)は rc だけを見る。rc=5 を
        #   「タグ変換の時間切れ」専用にして、部屋に読める文面を出させる(rc=3 の LORA_MISSING と同じ型)。
        print("TAG_TIMEOUT %s" % e)
        sys.exit(5)
    t1 = time.time()
    print("タグ列(%.1f秒): %s" % (t1 - t0, tags))

    if not keep:
        unload_llm()

    cmd = [sys.executable, os.path.join(ROOT, "scripts", "imagegen", "generate.py"),
           "--ckpt", ckpt]
    if lora:
        cmd += ["--lora", lora, "--lora-strength", str(lora_strength)]
    if out:
        cmd += ["--out", out]
    caption = text
    if neg_tags:
        # ★既定ネガは落とさない= NEG_DEFAULT の後ろへ足す(置き換えると品質用の除外が消える)。
        #   値の正本は generate.py の1か所(ここへ写さない)。
        sys.path.insert(0, _HERE)
        from generate import NEG_DEFAULT            # noqa: E402
        cmd += ["--neg", NEG_DEFAULT + ", " + neg_tags]
        print("ネガ指定: %s → %s" % (neg_text, neg_tags))
        # ★効いたかをChamiが目で見られるよう、投稿に使ったネガ(指定分)を1行載せる
        caption = pos_text + "\n(描かないもの: %s → %s)" % (neg_text.replace("\n", " "), neg_tags)
    if channel and persona:
        cmd += ["--discord", channel, "--persona", persona, "--caption", caption]
        # ★2026-09-16 イージス研究室: タグ変換段の秒数を渡す(Chami原文=「かかった時間も
        #   教えてもらえるようにして」)。描画段は generate.py が自分で測る=
        #   投稿本文には「所要 N秒(タグ変換 A秒 / 描画 B秒)」が載る。
        cmd += ["--tag-seconds", "%.1f" % (t1 - t0)]
    cmd.append(tags)
    r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace", timeout=1800)
    sys.stdout.write(r.stdout or "")
    if r.returncode != 0:
        sys.stderr.write(r.stderr or "")
        sys.exit(r.returncode)
    print("合計 %.1f秒" % (time.time() - t0))


if __name__ == "__main__":
    main()
