#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codex_run — Codex(GPT-5.4)の頭脳と口。behop.py の Codex版 (2026-09-05 platform-se・配線依頼=ケヴィン)。

なぜ在るか(Chami設計):
  「システム設計・重い実装は Codex の方が強い」ので、重い改修を Codex へ回せる口を作る。
  形は べホップ(Gemini)と同じ= 部屋 → 発言 → 実行 → 返信。手本は scripts/behop/behop.py。

構成(束を分ける=べホップと同じ作法):
  頭脳 = Codex CLI (codex exec)。ChatGPTログイン(~/.codex/auth.json)を借りる。
  口   = 専用Discord bot。トークン=local/discord_codex_token.txt (Chami設置待ち・未設置なら投稿しない)
  モデル= gpt-5.5 (既定)。★2026-09-05 10:21 に gpt-5.4 が打ち切られた(同日 05:49 までは通っていた)。
          実測(10:35 研究室HQ): グローバルの CLI 0.120.0 では **どのモデルも** 400
          「not supported when using Codex with a ChatGPT account」で1文字も生成しない。
          gpt-5.5 だけ文面が違い「requires a newer version of Codex. Please upgrade」=版数切れが真因。
          橋専用に CLI 0.153.4 を local/codex_cli へ入れたら gpt-5.5 が通った("OK" を実受信)。
          なお -codex 系(gpt-5.5-codex / gpt-5.4-codex)は新CLIでも ChatGPTアカウントでは不可。

★INC-99 対策(ケヴィンの必須条件・これが無い配線は入れない):
  (a) **専用の作業場所で走らせる**= 実行ごとに repo の HEAD から git worktree を切り、
      その中だけで codex exec を回す。共有の作業ツリーでは絶対に走らせない。
      worktree add は新しい枝と別ディレクトリを作るだけで、共有ツリーを checkout も stash もしない
      = 他室の作業を消さない(並列gitの clobber を構造で避ける)。
  (b) **走り出す前に所有権を宣言する**= scripts/ownership.py claim を先に叩き、
      終わったら release する。黒板に載ってから初めて codex を起動する。

★CODEX_HOME を分ける理由(実測 2026-09-05):
  正本 ~/.codex/config.toml は**Codexデスクトップ版**用(gpt-5.6-sol / model_reasoning_effort="max" /
  MCP・プラグイン多数)で、CLI 0.120.0 はこれを読むと "unknown variant `max`" 等で**起動前に落ちる**。
  -c 上書きでも救えない(パースがファイル読込時に先に失敗する)。
  → 橋専用の CODEX_HOME(local/codex_home)に CLI互換の最小 config.toml を置き、
    ChatGPTログイン(auth.json)だけは正本から**毎回コピー**して借りる(トークンは随時更新されるため)。

使い方:
  python scripts/codex/codex_run.py --ping                        # 生存確認(投稿しない)
  python scripts/codex/codex_run.py --ask "..." --tag room        # 生成して印字のみ
  python scripts/codex/codex_run.py --ask "..." --to <ch名|ID> --tag room  # Codexとして投稿
  python scripts/codex/codex_run.py --ask-file p.txt --to <ch>    # 依頼文をファイルから
オプション:
  --model <name>  モデル明示(既定 gpt-5.4) / --sandbox read-only|workspace-write(既定 workspace-write)
  --timeout <秒>  codex exec の上限(既定 600) / --keep-worktree  変更が無くても worktree を残す
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))          # 5SecMovieMaker
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")

# --- 橋専用 CODEX_HOME(CLI互換の最小設定 + 正本からコピーした auth.json) ---
BRIDGE_HOME = os.path.join(LOCAL, "codex_home")
REAL_CODEX_HOME = os.environ.get("CODEX_REAL_HOME") or os.path.join(
    os.path.expanduser("~"), ".codex")
REAL_AUTH = os.path.join(REAL_CODEX_HOME, "auth.json")

# --- 作業場所(専用worktree)。共有ツリー(ROOT)では走らせない ---
WT_BASE = os.path.normpath(os.path.join(ROOT, "..", "codex_worktrees"))

# --- 口(専用bot)・宛先解決 ---
TOKEN_FILE = os.path.join(LOCAL, "discord_codex_token.txt")
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
DC_API = "https://discord.com/api/v10"

# --- 所有権黒板 ---
OWNERSHIP = os.path.join(ROOT, "scripts", "ownership.py")
OWNER = "codex"

DEFAULT_MODEL = "gpt-5.5"

# --- 橋専用の Codex CLI(グローバル/デスクトップ版には触らない) ---
# ★実測 2026-09-05: グローバルの npm CLI は 0.120.0 で、サーバがこの版を切ったため
#   どのモデルを渡しても 400 になる。橋だけ新版を持たせて版数を独立させる。
#   入れ直し= npm install --prefix ./local/codex_cli @openai/codex@latest
BRIDGE_CLI_JS = os.path.join(LOCAL, "codex_cli", "node_modules", "@openai",
                             "codex", "bin", "codex.js")
LOG = os.path.join(LOCAL, "llm", "codex_run_log.jsonl")


def _resolve_codex_cmd():
    """codex CLI を起動する argv の先頭部分を返す。

    ★Windows対策(実測 2026-09-05): PATH 上の `codex` は npm の .CMD シムで、
    Python の CreateProcess(shell=False)は .cmd を直接起動できず FileNotFoundError になる。
    シムは中で `node .../@openai/codex/bin/codex.js %*` を呼ぶだけなので、
    実体の codex.js を node で直接回す形へ解決する(cmd.exe 経由の引数破損も避ける)。

    ★版数対策(実測 2026-09-05): 橋専用CLI(local/codex_cli)が在ればそれを最優先で使う。
      グローバルは 0.120.0 のまま = サーバに切られて全モデルが 400 になるため。
    """
    node = shutil.which("node")
    if node and os.path.exists(BRIDGE_CLI_JS):
        return [node, BRIDGE_CLI_JS]

    exe = shutil.which("codex")
    if exe:
        low = exe.lower()
        if low.endswith((".cmd", ".bat")):
            js = os.path.join(os.path.dirname(exe), "node_modules", "@openai",
                              "codex", "bin", "codex.js")
            if os.path.exists(js):
                return [shutil.which("node") or "node", js]
            return [exe]                            # シム直叩きは最後の手段
        return [exe]                                # .exe / 拡張子なしの実体はそのまま
    return ["codex"]                                # 見つからなければ従来どおり


CODEX_CMD = _resolve_codex_cmd()


def effective_sandbox(sandbox):
    """このOSで実際に適用するサンドボックスモードへ翻訳する。

    ★Windows対策(実測 2026-09-05): Codex の OSレベルsandbox は Linux(Landlock)/
    macOS(Seatbelt)専用で **Windows には無い**。そのため `workspace-write` は強制できず、
    approvals 無効(approval_policy="never")と組むと**安全側で read-only に落ちて1文字も書けない**
    (out.txt に "read-only filesystem sandbox and approvals are disabled")。
    → Windowsで書き込みが要るタスクは `danger-full-access` にする以外に道がない。
      その場合の隔離は Codex内蔵sandbox ではなく **専用worktree(-C で cwd 固定)+ 所有権宣言**
      の2層で担保する(=ケヴィンの必須条件そのもの。共有ツリーには -C を向けない)。
    read-only はそのまま(書かない ping 等はこれで足りる)。
    """
    if sandbox == "workspace-write" and os.name == "nt":
        return "danger-full-access"
    return sandbox


def _read(path, what, hard=True):
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        if hard:
            print(f"ABORT: {what}が未設置 ({path})")
            sys.exit(2)
        return ""


def _log(rec):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass                                        # 計測は本番を止めない


# ---------------------------------------------------------------------------
# CODEX_HOME(頭脳の設定と資格情報)
# ---------------------------------------------------------------------------
def ensure_home(model, sandbox):
    """橋専用 CODEX_HOME を用意して env を返す。

    - config.toml= CLI互換の最小設定を毎回書き直す(正本のデスクトップ版設定は使わない)。
    - auth.json = 正本 ~/.codex/auth.json を**毎回コピー**(ChatGPTトークンは随時更新される)。
      正本が無い/ログインしていなければ ABORT(頭脳が動かないので投稿もしない)。
    """
    os.makedirs(BRIDGE_HOME, exist_ok=True)
    cfg = (
        f'model = "{model}"\n'
        'model_reasoning_effort = "high"\n'
        'approval_policy = "never"\n'
        f'sandbox_mode = "{effective_sandbox(sandbox)}"\n'
    )
    with open(os.path.join(BRIDGE_HOME, "config.toml"), "w", encoding="utf-8") as f:
        f.write(cfg)
    if not os.path.exists(REAL_AUTH):
        print(f"ABORT: ChatGPTログインが見当たらない ({REAL_AUTH})。Codexにログインしてから。")
        sys.exit(2)
    shutil.copyfile(REAL_AUTH, os.path.join(BRIDGE_HOME, "auth.json"))
    env = dict(os.environ)
    env["CODEX_HOME"] = BRIDGE_HOME
    return env


# ---------------------------------------------------------------------------
# 専用worktree(INC-99対策の核・ケヴィンの必須条件a)
# ---------------------------------------------------------------------------
def _git(args, cwd=ROOT):
    return subprocess.run(["git", "-C", cwd] + args, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def make_worktree(tag):
    """ROOT の HEAD から専用 worktree を切る。共有ツリーには一切触れない。

    戻り値 (path, branch, base_sha)。失敗時は (None, None, None)。
    """
    os.makedirs(WT_BASE, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() else "-" for c in (tag or "run"))[:24] or "run"
    branch = f"codex/{safe}-{stamp}-{os.getpid()}"
    path = os.path.join(WT_BASE, f"{safe}-{stamp}-{os.getpid()}")
    base = _git(["rev-parse", "HEAD"]).stdout.strip()
    r = _git(["worktree", "add", "-b", branch, path, "HEAD"])
    if r.returncode != 0:
        print(f"ABORT: worktree作成失敗: {r.stderr.strip()[:200]}")
        return None, None, None
    return path, branch, base


def worktree_changed(path, base_sha):
    """worktree に変更(未コミット or base以降のコミット)があるか。"""
    dirty = _git(["status", "--porcelain"], cwd=path).stdout.strip()
    ahead = _git(["rev-list", f"{base_sha}..HEAD", "--count"], cwd=path).stdout.strip()
    return bool(dirty) or (ahead not in ("", "0"))


def remove_worktree(path, branch):
    """変更が無い worktree と枝を掃除する(ディスク肥大を防ぐ)。"""
    _git(["worktree", "remove", "--force", path])
    if branch:
        _git(["branch", "-D", branch])


# ---------------------------------------------------------------------------
# 所有権(ケヴィンの必須条件b)
# ---------------------------------------------------------------------------
def claim(topic, note=""):
    r = subprocess.run([sys.executable, OWNERSHIP, "claim", topic, "--owner", OWNER,
                        "--note", note or "codex bridge auto"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0


def release(topic, note=""):
    subprocess.run([sys.executable, OWNERSHIP, "release", topic, "--owner", OWNER,
                    "--note", note or "codex bridge done"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# codex exec(頭脳を回す)
# ---------------------------------------------------------------------------
def run_codex(prompt, worktree, env, model, timeout, sandbox):
    """codex exec を専用worktree内で回し、最終メッセージを返す。

    戻り値 (text, ok)。ok=False なら text は失敗理由(人向け)。
    - -o で最終メッセージだけをファイルへ書かせる(900KBのログを漁らない)。
    - --skip-git-repo-check= worktreeもrepoだが将来 add-dir 併用でも落ちないよう明示。
    """
    last = os.path.join(worktree, ".codex_last_message.txt")
    try:
        if os.path.exists(last):
            os.remove(last)
    except OSError:
        pass
    cmd = CODEX_CMD + ["exec", "-C", worktree, "--skip-git-repo-check",
                       "-s", effective_sandbox(sandbox), "-m", model, "-o", last, prompt]
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"(生成失敗: codex exec が {timeout}秒で応答しなかった)", False
    text = ""
    try:
        text = open(last, encoding="utf-8").read().strip()
    except OSError:
        text = ""
    if not text:
        # -o が空= 401/400等でモデルが1文字も返していない。stdoutから理由を拾う。
        tail = (r.stdout or "") + (r.stderr or "")
        reason = "不明"
        for key in ("not supported", "invalid_request", "unauthorized", "401", "429",
                    "Error loading config"):
            if key in tail:
                reason = key
                break
        return f"(生成失敗: Codexが応答を返さなかった [{reason}] rc={r.returncode})", False
    return text, True


# ---------------------------------------------------------------------------
# 口(Discordへ Codex bot として投稿)= behop.dc_send を踏襲
# ---------------------------------------------------------------------------
def resolve_channel(target):
    if str(target).isdigit():
        return str(target)
    chans = json.load(open(CHANNELS_FILE, encoding="utf-8"))
    ch = next((c for c in chans if c.get("name") == target or c.get("dept") == target), None)
    if not ch:
        print(f"ABORT: チャンネル未登録: {target}")
        sys.exit(4)
    return str(ch["id"])


def dc_send(token, channel_id, text):
    """Codex(bot本人)として投稿。2000字制限は段落優先で分割(behop踏襲)。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
        from enjoh import enjoh_backstop
        text = enjoh_backstop(text, tag="codex")
    except Exception:
        pass                                        # fail-open= 投稿は殺さない
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
                     "User-Agent": "go5-codex/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                mid = json.loads(r.read().decode("utf-8")).get("id", "")
            print(f"投稿OK (Codex) msg={mid}" + (f" [{i+1}通目]" if i else ""))
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print("投稿失敗: HTTP 403 = Codex bot がこのチャンネルに入室していない。"
                      "Discordのチャンネル設定→権限でCodexのbotを追加。")
            else:
                print(f"投稿失敗: HTTP {e.code}")
            return False
        time.sleep(0.4)
    return True


# ---------------------------------------------------------------------------
# 生存確認
# ---------------------------------------------------------------------------
def do_ping(model, sandbox, timeout):
    """頭脳(実生成を1発)と口(bot本人の確認)を通す。★実生成まで通す(behop do_ping と同趣旨)。"""
    env = ensure_home(model, "read-only")           # pingは書かせない
    wt, branch, base = make_worktree("ping")
    if not wt:
        return 6
    topic = f"codex-ping-{os.getpid()}"
    claimed = claim(topic, "ping")
    t0 = time.time()
    try:
        text, ok = run_codex("reply with the single word PONG and nothing else",
                             wt, env, model, min(timeout, 180), "read-only")
    finally:
        if claimed:
            release(topic, "ping done")
        remove_worktree(wt, branch)
    secs = time.time() - t0
    if not ok:
        print(f"頭脳NG ({secs:.1f}秒): {text}")
        return 6
    print(f"頭脳OK: {model} が {secs:.1f}秒で応答 ({len(text)}字): {text[:60]!r}")

    token = _read(TOKEN_FILE, "Codex botトークン", hard=False)
    if not token:
        print("口: discord_codex_token.txt 未設置(Chami設置待ち)。頭脳のみ緑=部屋接続はトークン設置で開通。")
        return 0
    try:
        req = urllib.request.Request(f"{DC_API}/users/@me",
                                     headers={"Authorization": f"Bot {token}",
                                              "User-Agent": "go5-codex/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            me = json.loads(r.read().decode("utf-8"))
        print(f"口OK: {me.get('username')} (id={me.get('id')})")
    except urllib.error.HTTPError as e:
        print(f"口NG: HTTP {e.code}(トークンを確認)")
        return 7
    return 0


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------
def answer(prompt, to=None, tag="cli", model=DEFAULT_MODEL, sandbox="workspace-write",
           timeout=600, keep_worktree=False):
    """1件を Codex に投げ、(必要なら)Codexとして投稿する。戻り値=終了コード。"""
    env = ensure_home(model, sandbox)
    wt, branch, base = make_worktree(tag)
    if not wt:
        return 6
    topic = f"codex-{tag}-{time.strftime('%H%M%S')}-{os.getpid()}"
    claimed = claim(topic, f"codex run: {prompt[:60]}")
    if not claimed:
        print(f"注意: 所有権の宣言に失敗(黒板不通)。それでも隔離worktree内なので続行する: {topic}")
    t0 = time.time()
    changed = False
    try:
        text, ok = run_codex(prompt, wt, env, model, timeout, sandbox)
        changed = worktree_changed(wt, base)
    finally:
        if claimed:
            release(topic, "done" + (" (変更あり=worktree保持)" if changed else ""))
    secs = time.time() - t0

    print(f"--- Codex ({model}, {secs:.1f}秒, {'OK' if ok else '失敗'}) ---")
    print(text)
    if changed:
        print(f"★worktreeに変更あり= {wt}(枝 {branch})。共有ツリーへは自動反映しない。"
              f"取り込みは差分を確認して意図的に。")
    _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": tag, "model": model,
          "secs": round(secs, 1), "ok": ok, "changed": changed, "worktree": wt if changed else "",
          "q": prompt[:200], "a": text[:300]})

    # 掃除= 変更が無ければ worktree を消す。あれば残す(差分を人が確認して取り込むため)。
    if not changed and not keep_worktree:
        remove_worktree(wt, branch)

    if to:
        if ok:
            token = _read(TOKEN_FILE, "Codex botトークン")
            dc_send(token, resolve_channel(to), text)
        else:
            print("生成失敗のため投稿は中止(失敗文をDiscordへ流さない)")
            return 5
    return 0 if ok else 5


def main():
    ap = argparse.ArgumentParser(description="Codex(GPT-5.4)の頭脳と口。behop.pyのCodex版。")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--ask")
    ap.add_argument("--ask-file")
    ap.add_argument("--to")
    ap.add_argument("--tag", default="cli")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--sandbox", default="workspace-write",
                    choices=["read-only", "workspace-write", "danger-full-access"])
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--keep-worktree", action="store_true")
    a = ap.parse_args()

    if a.ping:
        return do_ping(a.model, a.sandbox, a.timeout)
    prompt = a.ask
    if a.ask_file:
        prompt = open(a.ask_file, encoding="utf-8").read().strip()
    if not prompt:
        print("使い方: codex_run.py --ping | --ask <文|--ask-file p> [--to <ch名|ID>] "
              "[--tag <用途>] [--model m] [--sandbox m] [--timeout s] [--keep-worktree]")
        return 1
    return answer(prompt, to=a.to, tag=a.tag, model=a.model, sandbox=a.sandbox,
                  timeout=a.timeout, keep_worktree=a.keep_worktree)


if __name__ == "__main__":
    sys.exit(main())
