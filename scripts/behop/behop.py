#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""behop — ベホップ (強Gemini) の頭脳と口。 (2026-07-19 QA配線・Chami Go)

構成 (Chami設計2026-07-18):
  頭脳 = Geminiの強モデル。キー=local/gemini_api_key_behop.txt (森光技研Logosの事業用・正規利用)
  口   = 専用Discord bot。トークン=local/discord_behop_token.txt (非公開bot・最小権限・Intents OFF)
  役割 = 重い下書き・長文整形・要約・画像読み。**判断・コード・数字・データ編集は渡さない** (縄張り規約)
  ホイミン (弱・私用キー・共有bot) とは束を分ける: 資格情報を跨いで使い回さない。

使い方:
  python scripts/behop/behop.py --ping     # 生存確認 (投稿しない)。★実生成を1発通す=緑なら本番も通る
  python scripts/behop/behop.py --ask "質問"                    # 生成して印字のみ
  python scripts/behop/behop.py --ask-file p.txt --to <ch名|ID> # 生成してベホップとして投稿
  python scripts/behop/behop.py --ask "..." --image a.png --to <ch>   # 画像つき
  --model <name> で強モデルの明示指定も可 (既定は優先リスト→実在照会で自動選択)
"""
import base64
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")

# 使用量の記録 (2026-08-18 研究室HQ)。★取り込みに失敗しても生成は続ける (計測が本番を止めない)。
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
try:
    import gemini_usage
except Exception:
    gemini_usage = None

KEY_FILE = os.path.join(LOCAL, "gemini_api_key_behop.txt")       # Chami設置名が正 (2026-07-18 23:25)
TOKEN_FILE = os.path.join(LOCAL, "discord_behop_token.txt")
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
GEM_API = "https://generativelanguage.googleapis.com/v1beta"
DC_API = "https://discord.com/api/v10"

# ★固定の優先リスト (旧 PREFERRED) は**廃止した** (2026-08-18)。
#   理由= あれが「モデル名の世代交代に追随しない」原因そのものだったから。
#   実測 2026-08-17: 先頭2つ (gemini-3-pro-latest / gemini-3-pro) は**そもそも存在しない名前**で、
#   毎回2段を空振りに使っていた。順番は下の model_score() が ListModels の実物から毎回組み直す。
#   手で先頭を決めたい時は `--model <name>` を使う (それが明示指定の役目)。

# ListModels 自体が落ちた時だけ使う最後の綱 (fail-open: 何も試さずに死ぬより、古くても試す)。
EMERGENCY = ("gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest")

# ★テキストを返さないモデルを梯子に入れない (2026-08-18 実測で判明)。
#   ListModels は generateContent 対応で37種返すが、その中には画像出力(-image / nano-banana)、
#   音声(-tts / lyria)、別製品(deep-research / antigravity / robotics / computer-use)、
#   別系統(gemma)が混ざっている。これらは叩いても text パートが返らず、
#   **空文字を「成功」として返してしまう**=静かに壊れる。名前で先に外す。
NON_TEXT = ("image", "nano-banana", "tts", "audio", "lyria", "veo", "imagen", "embedding",
            "deep-research", "antigravity", "robotics", "computer-use", "live", "gemma")

LADDER_LIMIT = 6          # 1回の生成で叩く上限。これ以上は待ち時間の方が害になる

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif"}


# ---------------------------------------------------------------------------
# モデルの序列 (2026-08-18 恒久対策・研究室HQ依頼)
#
# なぜ在るか= 降格ラダーが固定リストで、モデル名の世代交代に追随していなかった。
#   実測 (2026-08-17 研究室HQ): gemini-3-pro-latest/gemini-3-pro=404、gemini-pro-latest=429、
#   gemini-2.5-pro=404、gemini-flash-latest=503。固定リストは「今そこに在る名前」を知らない。
# ★前提= **ListModels に載っている ≠ 生成が通る。** 載っていても 404/429/503 は普通に返る。
#   だから序列は「名前から読める強さ」で決め、**通るかどうかは実際に叩いて確かめる**。
# ---------------------------------------------------------------------------

def is_text_model(name):
    """テキストを返す見込みのあるモデルか。★名前で外す=叩いてから空文字で気づくより早い。"""
    n = (name or "").lower()
    return bool(n) and not any(w in n for w in NON_TEXT)


def model_tier(name):
    """名前から階層を読む。3=pro / 2=flash / 1=flash-lite / 0=読めない。
    ★読めない名前を捨てない (0 として最後尾に置くだけ)= 未知の新モデルを黙って落とさないため。"""
    n = (name or "").lower()
    if "flash-lite" in n or "flash-8b" in n or "lite" in n:
        return 1
    if "flash" in n:
        return 2
    if "pro" in n or "ultra" in n:
        return 3
    return 0


def model_gen(name):
    """名前から世代番号を読む (2.5 / 3.1 / 3.7)。

    ★10以上は世代ではなく**日付**だと見なして捨てる。実測 2026-08-18:
      `deep-research-pro-preview-12-2025` の "12" を世代と読んで、
      3.1系より上に並べていた (最初の数字をそのまま採ると日付を掴む)。
    """
    m = re.search(r"(\d+(?:\.\d+)?)", (name or "").lower())
    if not m:
        return 0.0
    v = float(m.group(1))
    return v if v < 10 else 0.0


def model_score(name):
    """並べ替えのキー (大きいほど強い)。降順に並べると pro→flash→flash-lite になる。

    (階層, 安定度, latestエイリアスか, 世代番号)
      安定度  = preview/exp/thinking は 0 (同じ階層なら安定版を先に叩く)
      latest  = `-latest` は世代交代に自動追随するので、同じ階層では番号付きより先。
                ★これが「3.x系が出ても固定リストを書き換えずに済む」核心。
      世代番号= model_gen() (日付を世代と読まない)
    """
    n = (name or "").lower()
    stable = 0 if ("preview" in n or "-exp" in n or "exp-" in n or "thinking" in n) else 1
    latest = 1 if n.endswith("-latest") else 0
    return (model_tier(name), stable, latest, model_gen(name))


def _best_of_tier(ranked, tier):
    for m in ranked:
        if model_tier(m) == tier:
            return m
    return None


def build_ladder(avail, first=None, limit=LADDER_LIMIT):
    """実際に叩く順番を作る。★純粋関数=ネットワークに触らないので検査できる。

    ①明示指定 (--model) があれば先頭 → ②ListModelsの実物を model_score() の強い順
    最後に**必ず最軽量の段を末尾へ置く**(≒最も生きている可能性が高い段)。
    ★これが止血の恒久版= 上が全部死んでも「下に生きている段へ必ず降りる」ことを構造で保証する。
    ★固定の名前リストは持たない= 名前の世代交代は model_score() が毎回読み直す。
    """
    seen = [m for m in (avail or ()) if m and is_text_model(m)]
    ranked = sorted(seen, key=model_score, reverse=True)
    pool = ranked or list(EMERGENCY)          # ListModelsが落ちた時だけ最後の綱を使う
    out = []

    def add(m):
        if m and m not in out:
            out.append(m)

    add(first)                                 # 明示指定は在庫に無くても叩く (§pick_model 参照)
    for m in pool:
        add(m)

    floor = _best_of_tier(pool, 1) or _best_of_tier(pool, 2)
    if floor and floor in out and out.index(floor) >= limit:
        out.remove(floor)                      # 切り落とされる位置に居るなら末尾へ回す
    out = out[:limit]
    if floor and floor not in out:
        out = out[:max(1, limit - 1)] + [floor]
    return out


def _read(path, what):
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        print(f"ABORT: {what}が未設置 ({path})")
        sys.exit(2)


def list_models(key):
    req = urllib.request.Request(f"{GEM_API}/models?key={key}&pageSize=200",
                                 headers={"User-Agent": "go5-behop/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for m in data.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            out.append(m.get("name", "").split("/")[-1])
    return out


def pick_model(key, override=None):
    """先頭に置くモデルと、ListModelsで見えたモデル一覧を返す。
    ★ListModelsが落ちても止めない (avail=[] で返し、build_ladder が EMERGENCY を使う)。"""
    try:
        avail = list_models(key)
    except Exception as e:
        print(f"注意: ListModelsが引けない ({type(e).__name__})。既知の段だけで試す")
        avail = []
    if override:
        if override not in avail and avail:
            # ★止めない= ListModelsに載っていない ≠ 生成できない。載っている ≠ 生成が通る、の裏返し。
            print(f"注意: 指定モデル {override} はListModelsに見当たらないが、そのまま叩いてみる")
        return override, avail
    ladder = build_ladder(avail)
    if not ladder:
        print("ABORT: 使えるモデルがありません")
        sys.exit(3)
    return ladder[0], avail


def _gen_once(key, model, payload):
    req = urllib.request.Request(
        f"{GEM_API}/models/{model}:generateContent?key={key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "go5-behop/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(pt.get("text", "") for pt in data["candidates"][0]["content"]["parts"])


def _usage(tag, model, prompt, images, out="", ok=True, err="", t0=None):
    """使用量を1行残す (2026-08-18)。失敗しても呼び出し側へ影響させない。"""
    if not gemini_usage:
        return
    gemini_usage.log("behop", tag, model, len(prompt or ""), len(out or ""),
                     len(images or ()), ok, err, (time.time() - t0) if t0 else 0.0)


def ask(key, model, prompt, image_paths=(), avail=(), tag="cli"):
    """生成。429 (割当超過)/404は下位モデルへ自動降格して粘る (無料枠のproは割当が極小のため)。
    トレースバックで落とさない=部品として使う側 (セッション/将来のresponder) を巻き込まない。

    ★戻り値= **(text, used_model) のタプル** (2026-08-18に単独の text から変更した)。
      used_model= 実際に生成が通った段の名前。**全段ダメだった時は None** で、
      text 側に「(生成失敗: …)」という人向けの文が入る。
      → **成否の判定は text の中身ではなく used_model の None かどうかで見ること**
        (失敗時も text は空にならないので、`if text:` では死んでいるのに生きて見える)。
      ★model 引数は「先頭に置きたい段」であって、返ってくる段とは限らない (降格するため)。

    model=None を渡してよい。その時は ListModels の実物から build_ladder() が先頭を決める。
    """
    parts = [{"text": prompt}]
    for p in image_paths:
        ext = os.path.splitext(p)[1].lower()
        with open(p, "rb") as f:
            parts.append({"inline_data": {"mime_type": MIME.get(ext, "image/png"),
                                          "data": base64.b64encode(f.read()).decode("ascii")}})
    payload = {"contents": [{"parts": parts}]}
    ladder = build_ladder(avail, first=model)
    # ★実際に最初に叩く段。model=None (無指定) の時、降格の注記や失敗行に "None" と出ていた
    #   (2026-08-18 研究室HQ指摘)。Noneは割当超過していない=指定が無かっただけで、
    #   ログを読む人が「Noneというモデルが落ちた」と誤解する。先頭の実名で言う。
    head = model or (ladder[0] if ladder else None)
    trail = []                      # ★どの段が何で落ちたかを全部持つ (最後の1つだけ見せない)
    last_err = "?"
    t0 = time.time()
    for m in ladder:
        try:
            text = _gen_once(key, m, payload)
            if not (text or "").strip():
                # ★空応答は成功ではない (2026-08-18)。画像/音声モデルや安全停止では text パートが
                #   無く、旧コードは空文字を「生成成功」として返していた=呼び出し側から見て静かな死。
                last_err = "空応答"
                trail.append(f"{m}={last_err}")
                continue
            if m != head:
                print(f"(注: {head}が割当超過等のため {m} へ降格して生成)")
            # ★2026-08-18 研究室HQ: 成功時も「降りてくる途中で何が落ちたか」を残す。
            #   ここを空にしていたため、proが429で空振りしても最終的に成功すれば記録が
            #   err="" になり、課金判断の軸(429の件数)が実測 0件 という嘘になっていた。
            _usage(tag, m, prompt, image_paths, text, True, " / ".join(trail), t0)
            return text, m
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            trail.append(f"{m}={last_err}")
            # 429(割当)/404(未提供)/400 に加え、5xx(混雑・一時障害)も「その段が今ダメ」なだけ。
            # ★2026-08-17 止血: 503でbreakしていたため、下に生きている段(flash系)が残っていても
            #   梯子ごと降りて「生成失敗」になっていた(実測: 2.5-pro=404 → flash-latest=503 → 中断)。
            if e.code in (429, 404, 400) or 500 <= e.code < 600:
                time.sleep(1.5)
                continue
            break
        except (KeyError, IndexError):
            last_err = "応答形式が想定外"
            trail.append(f"{m}={last_err}")
            continue
        except Exception as e:
            last_err = type(e).__name__
            trail.append(f"{m}={last_err}")
            break
    detail = " / ".join(trail) or last_err
    _usage(tag, head, prompt, image_paths, "", False, detail[:200], t0)
    # ★全段の内訳を出す= 「梯子が降りた結果ダメだった」のか「1段目で門前払い」なのかを見分けるため。
    return f"(生成失敗: 試した{len(trail)}段すべて不通 [{detail}]。時間を置くか--modelで明示指定を)", None


def ask_pro(key, prompt, image_paths=(), model="gemini-2.5-pro", tag="ask_pro"):
    """pro単一モデルで生成。flashへ降格しない (認識の質を落とさないための専用経路)。
    共有の ask() とは別物: ask() は無料proの割当が尽きるとflashへ落として粘るが、
    こちらは「proの無料枠で読めるだけ読み、尽きたら打ち切る」用途 (競合フレーム日次収集)。

    戻り値 (text, status):
      ("...", "ok")             成功
      (None,  "quota")          pro無料枠が尽きた (HTTP 429)。呼び出し側はその日を打ち切る
      (None,  "error:<detail>") それ以外の失敗。呼び出し側はこの1件だけスキップ
    """
    parts = [{"text": prompt}]
    for p in image_paths:
        ext = os.path.splitext(p)[1].lower()
        with open(p, "rb") as f:
            parts.append({"inline_data": {"mime_type": MIME.get(ext, "image/png"),
                                          "data": base64.b64encode(f.read()).decode("ascii")}})
    payload = {"contents": [{"parts": parts}]}
    t0 = time.time()
    try:
        text = _gen_once(key, model, payload)
        _usage(tag, model, prompt, image_paths, text, True, "", t0)
        return text, "ok"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _usage(tag, model, prompt, image_paths, "", False, "HTTP 429", t0)
            return None, "quota"
        _usage(tag, model, prompt, image_paths, "", False, f"HTTP {e.code}", t0)
        return None, f"error:HTTP {e.code}"
    except (KeyError, IndexError):
        _usage(tag, model, prompt, image_paths, "", False, "応答形式が想定外", t0)
        return None, "error:応答形式が想定外"
    except Exception as e:
        _usage(tag, model, prompt, image_paths, "", False, type(e).__name__, t0)
        return None, f"error:{type(e).__name__}"


PING_PROMPT = "ping。「OK」とだけ返して。"


def do_ping(key, override=None, check_bot=True):
    """生存確認。★ListModelsだけでなく **generateContent を1発通す**。

    なぜ実生成まで通すか (2026-08-18 恒久対策・研究室HQ指摘):
      旧pingは ListModels しか叩かず、本番経路 (generateContent) を一度も通していなかった。
      結果、**pingは緑のまま本番が死んでいる**状態が起きた (実測 2026-08-17)。
      共通規律§3「静かに壊れる推定を使わない=生死そのものを見る」の違反だったので、
      「使えるはず」ではなく「実際に1文字返ってきた」を確認する形にした。
    ★戻り値は終了コード。生成が通らなければ**非0**=pingが緑にならない。
    """
    m, avail = pick_model(key, override)
    ladder = build_ladder(avail, first=m)
    print(f"キーOK: 使用可能モデル{len(avail)}種 / 先頭={m}")
    print(f"降格ラダー({len(ladder)}段): " + " → ".join(ladder))

    t0 = time.time()
    text, used = ask(key, m, PING_PROMPT, (), avail, tag="ping")
    secs = time.time() - t0
    if not used:
        print(f"実生成NG ({secs:.1f}秒): {text}")
        print("★ListModelsは引けているのに generateContent が全段で通らない=本番経路は死んでいる")
        return 6
    print(f"実生成OK: {used} が {secs:.1f}秒で応答 ({len((text or '').strip())}字) "
          + ("[先頭のまま]" if used == m else f"[{m}から降格]"))

    if check_bot:
        token = _read(TOKEN_FILE, "ベホップbotトークン")
        req = urllib.request.Request(f"{DC_API}/users/@me",
                                     headers={"Authorization": f"Bot {token}",
                                              "User-Agent": "go5-behop/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            me = json.loads(r.read().decode("utf-8"))
        print(f"botOK: {me.get('username')}#{me.get('discriminator')} (id={me.get('id')})")
    return 0


def resolve_channel(token, target):
    if str(target).isdigit():
        return str(target)
    chans = json.load(open(CHANNELS_FILE, encoding="utf-8"))
    ch = next((c for c in chans if c.get("name") == target or c.get("dept") == target), None)
    if not ch:
        print(f"ABORT: チャンネル未登録: {target}")
        sys.exit(4)
    return str(ch["id"])


def dc_send(token, channel_id, text):
    """ベホップ (bot本人) として投稿。2000字制限は段落優先で分割。"""
    chunks, cur = [], ""
    for ln in text.splitlines(keepends=True):
        if len(cur) + len(ln) > 1900:
            chunks.append(cur)
            cur = ""
        cur += ln
    if cur.strip():
        chunks.append(cur)
    for i, c in enumerate(chunks or [text]):
        req = urllib.request.Request(
            f"{DC_API}/channels/{channel_id}/messages",
            data=json.dumps({"content": c}).encode("utf-8"),
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                     "User-Agent": "go5-behop/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                mid = json.loads(r.read().decode("utf-8")).get("id", "")
            print(f"投稿OK (ベホップ) msg={mid}" + (f" [{i+1}通目]" if i else ""))
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"投稿失敗: HTTP 403 = ベホップbotがこのチャンネルに入室できていない。"
                      f"Discordでそのチャンネルの設定→権限→メンバー/ロールを追加→Behop_Gemini を追加")
            else:
                print(f"投稿失敗: HTTP {e.code}")
            return False
        time.sleep(0.4)
    return True


def main():
    args = sys.argv[1:]
    prompt = model = to = ask_file = None
    images = []
    ping = "--ping" in args
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--ask" and i + 1 < len(args):
            prompt = args[i + 1]; i += 2
        elif a == "--ask-file" and i + 1 < len(args):
            ask_file = args[i + 1]; i += 2
        elif a == "--image" and i + 1 < len(args):
            images.append(args[i + 1]); i += 2
        elif a == "--to" and i + 1 < len(args):
            to = args[i + 1]; i += 2
        elif a == "--model" and i + 1 < len(args):
            model = args[i + 1]; i += 2
        else:
            i += 1
    key = _read(KEY_FILE, "ベホップ用APIキー")
    if ping:
        return do_ping(key, model)
    if ask_file:
        prompt = open(ask_file, encoding="utf-8").read().strip()
    if not prompt:
        print("使い方: behop.py --ping | --ask <文|--ask-file p> [--image p]... [--to <ch名|ID>] [--model m]")
        return 1
    m, avail = pick_model(key, model)
    text, used = ask(key, m, prompt, images, avail)
    print(f"--- ベホップ ({used or '失敗'}) ---")
    print(text)
    if to and used:
        token = _read(TOKEN_FILE, "ベホップbotトークン")
        dc_send(token, resolve_channel(token, to), text)
    elif to:
        print("生成失敗のため投稿は中止 (失敗文をDiscordへ流さない)")
        return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
