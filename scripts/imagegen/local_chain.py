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
"""
import json
import os
import re
import subprocess
import sys
import time
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
CKPT = "Illustrious-XL-v2.0.safetensors"
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))

SYSTEM = (
    "あなたは日本語の指示をSDXL(Illustrious系)向けの英語プロンプトへ変換する係です。\n"
    "出力はカンマ区切りの英語タグ列だけ。説明・前置き・引用符は書かない。\n"
    "品質タグ(masterpiece, best quality, highres)を必ず末尾に含める。"
)


def _post(url, payload, timeout=900):
    req = urllib.request.Request(
        url, json.dumps(payload).encode("utf-8"), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


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


def to_tags(text, max_tokens=4000):
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
        d = _post(LMS_API, {
            "model": CHAT_MODEL, "temperature": 0.4, "max_tokens": budget,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": text}],
        })
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
    tags = to_tags(text)
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
    if channel and persona:
        cmd += ["--discord", channel, "--persona", persona, "--caption", text]
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
