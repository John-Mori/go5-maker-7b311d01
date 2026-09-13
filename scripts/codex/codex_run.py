#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codex_run — Codexの頭脳と口。behop.py の Codex版 (2026-09-05 platform-se・配線依頼=ケヴィン)。

なぜ在るか(Chami設計):
  「システム設計・重い実装は Codex の方が強い」ので、重い改修を Codex へ回せる口を作る。
  形は べホップ(Gemini)と同じ= 部屋 → 発言 → 実行 → 返信。手本は scripts/behop/behop.py。

構成(束を分ける=べホップと同じ作法):
  頭脳 = Codex CLI (codex exec)。ChatGPTログイン(~/.codex/auth.json)を借りる。
  口   = 専用Discord bot。トークン=local/discord_codex_token.txt (Chami設置待ち・未設置なら投稿しない)
  モデル= gpt-5.6-terra (既定)。★2026-09-05 10:21 に gpt-5.4 が打ち切られた(同日 05:49 までは通っていた)。
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
  --model <name>  モデル明示(未指定なら部門別ルータ) / --sandbox read-only|workspace-write(既定 workspace-write)
  --origin-dept <dept>  @ボス召喚元の部門(未指定なら既定モデル)
  --reasoning-effort <effort>  推論強度を明示(未指定なら部門別ルータ)
  --timeout <秒>  codex exec の上限(既定 1800) / --keep-worktree  変更が無くても worktree を残す
"""
import argparse
import hashlib
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

DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_REASONING_EFFORT = "medium"

# Codex専用のモデル政策(2026-09-06 Chami指示)。
# 公式OpenAI Docs上の現在値に合わせ、普段は balanced の 5.6 Terra、失敗単価が高い
# 基盤・QA・研究判断だけ 5.6 Sol へ上げる。Lunaは速いが、Codexへ投げる時点で
# 実装/設計の重みがあるため既定ルートには使わない。
# ★実測(2026-09-06 14:4x イージス研究室・使い捨てCODEX_HOME)= 両モデルとも
#   rc=0 / 応答 'ok'。このアカウントで実在する= 名前が架空でないことを確かめた上で着地。
CODEX_SOL_DEPTS = frozenset((
    "hq", "aegis-gl", "research-room", "keiei-kikaku",
    "system-engineer", "system-engineer-b", "platform-se", "frontend",
    "qa-reviewer", "llm-qa", "data-org", "incident",
))
CODEX_TERRA_DEPTS = frozenset((
    "hr-room", "hr-context", "kukuru-nakama", "otacon-radio", "gunji",
    "product-scout", "shorts-analyst", "copy-director", "learning-coach",
    "learning-coach-2", "ai-office", "llm-edu", "consult-intel",
    "past-room", "future-room", "soudan-room", "goods-afi", "someday-room",
    "web-research", "kaizen-analyst", "dream-care", "report-notify",
    "imagegen", "health-log", "manga-shorts",
))


def codex_model_for(origin_dept="", explicit_model=None, explicit_effort=None):
    """Codex実行のモデルと推論強度を決める。

    explicit_model は CLIで人が指定した値なので最優先する。origin_dept は
    @ボス召喚元の部門で、キュー上の処理dept='codex'とは別に見る。
    """
    if explicit_model:
        return explicit_model, (explicit_effort or DEFAULT_REASONING_EFFORT)
    dept = str(origin_dept or "").strip()
    if dept in CODEX_SOL_DEPTS:
        return "gpt-5.6-sol", (explicit_effort or "high")
    if dept in CODEX_TERRA_DEPTS:
        return DEFAULT_MODEL, (explicit_effort or DEFAULT_REASONING_EFFORT)
    return DEFAULT_MODEL, (explicit_effort or DEFAULT_REASONING_EFFORT)

# --- 橋専用の Codex CLI(グローバル/デスクトップ版には触らない) ---
# ★実測 2026-09-05: グローバルの npm CLI は 0.120.0 で、サーバがこの版を切ったため
#   どのモデルを渡しても 400 になる。橋だけ新版を持たせて版数を独立させる。
#   入れ直し= npm install --prefix ./local/codex_cli @openai/codex@latest
BRIDGE_CLI_JS = os.path.join(LOCAL, "codex_cli", "node_modules", "@openai",
                             "codex", "bin", "codex.js")
LOG = os.path.join(LOCAL, "llm", "codex_run_log.jsonl")
OUTBOX_DIR = os.path.join(LOCAL, "llm", "codex_outbox")
REACT = os.path.join(ROOT, "scripts", "discord", "react.py")


def _env_int(name, default, minimum=1, maximum=86400):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = int(default)
    return max(minimum, min(maximum, value))


# 重い設計・実装が実測600秒を越えたため、短い固定上限ではなく環境変数で調整可能にする。
DEFAULT_TIMEOUT = _env_int("CODEX_EXEC_TIMEOUT_SEC", 1800, minimum=60, maximum=7200)

# --- 全部屋記憶(ボス=ネイキッド・スネークの連続性。Chami指示 2026-09-05 msg 1545647769631334470
#     「あとボスも全部屋で記憶を保つようにしてくれ」)。
#   webhook人格の全部屋記憶は session_relay.SHARED_MEMORY_BY_PERSONA が持つが、Codexは
#   サブプロセス経路(この codex_run.py)なのでそちらの配線が届かない= ここに同じ思想で1本持たせる。
#   ★思想はアメス初出時のChami原文と同じ=「1部屋=1セッションだと部屋ごとに記憶が分かれて互いを知らない。
#     ずっと一緒にいたいから、部屋をまたぐ1本の記憶を持たせる」。ボスは全部屋で同じ一人。
#   ★置き場= 他の *_shared.jsonl と同じ 00_AI-HQ/departments/hr/memory/(人事部門の記憶棚)。
#   ★local/HQ内で完結=ネットへ出さない(C-013)。読み書きは fail-open(記憶で本筋を止めない)。
HQ = os.environ.get("GO5_HQ_DIR") or os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ"))
SNAKE_SHARED_MEMORY = os.path.join(HQ, "departments", "hr", "memory", "snake_shared.jsonl")
SNAKE_MEM_RECALL_RECORDS = 12        # プロンプトへ載せる直近件数(argvを膨らませない上限)
SNAKE_MEM_RECALL_CHARCAP = 4000      # 載せる記憶ブロックの文字上限(超えたら古い方を落とす)


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
# 生成結果の耐久保存 (Discord送信より必ず先)
# ---------------------------------------------------------------------------
def _safe_result_key(value):
    raw = str(value or "").strip()
    safe = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in raw)
    safe = safe.strip(".-")[:100]
    if safe:
        return safe
    return time.strftime("run-%Y%m%d-%H%M%S-") + str(os.getpid())


def result_path(request_id):
    return os.path.join(OUTBOX_DIR, _safe_result_key(request_id) + ".json")


def _read_result(path):
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def load_saved_result(request_id):
    """元Discord msg_idに対応する保存済み生成結果を返す。"""
    if not str(request_id or "").strip():
        return None
    rec = _read_result(result_path(request_id))
    if rec and str(rec.get("text") or "").strip():
        return rec
    return None


def _write_result(path, rec):
    """同一ボリューム内のos.replaceで、途中までのJSONを正本にしない。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save_generated_result(request_id, channel, prompt, text, reply_to="",
                           worktree="", model="", chunks=None):
    """生成済み全文と送信位置を保存する。失敗時は例外を返し、呼び側は投稿しない。"""
    rid = str(request_id or "").strip() or _safe_result_key("")
    path = result_path(rid)
    prepared = list(chunks if chunks is not None else prepare_discord_chunks(text))
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec = {
        "version": 1,
        "request_id": rid,
        "status": "generated",
        "created_at": now,
        "updated_at": now,
        "channel": str(channel or ""),
        "channel_id": str(channel) if str(channel or "").isdigit() else "",
        "reply_to": str(reply_to or ""),
        "prompt": str(prompt or ""),
        "text": str(text or ""),
        "text_sha256": hashlib.sha256(str(text or "").encode("utf-8")).hexdigest(),
        "chunks": prepared,
        "chunk_count": len(prepared),
        "sent_count": 0,
        "message_ids": [],
        "worktree": str(worktree or ""),
        "model": str(model or ""),
        "last_error": "",
        "completion_recorded": False,
    }
    _write_result(path, rec)
    print(f"★生成結果を送信前保存= {path} chunks={len(prepared)}")
    return path


# ---------------------------------------------------------------------------
# 全部屋記憶(ボス=ネイキッド・スネーク)
#   load= 生成前に直近の記憶をプロンプトへ載せる(部屋をまたいで思い出す)。
#   append= 実際に部屋へ投稿できた1往復だけを1行足す(CLIテスト等 to=None は記録しない)。
#   どちらも fail-open= 記憶の読み書きで応答を絶対に止めない。
# ---------------------------------------------------------------------------
def _load_snake_memory():
    """snake_shared.jsonl の直近を、プロンプトへ載せる読める塊にして返す。無ければ空。"""
    try:
        with open(SNAKE_SHARED_MEMORY, encoding="utf-8") as f:
            recs = [json.loads(l) for l in f if l.strip()]
    except Exception:
        return ""
    if not recs:
        return ""
    recs = recs[-SNAKE_MEM_RECALL_RECORDS:]
    lines = []
    for r in recs:
        room = str(r.get("room", "")).strip()
        q = str(r.get("q", "")).replace("\n", " ").strip()
        a = str(r.get("a", "")).replace("\n", " ").strip()
        ts = str(r.get("ts", "")).strip()
        lines.append(f"- [{ts} / 部屋 {room}] 依頼: {q[:160]} / あなたの返答: {a[:200]}")
    block = "\n".join(lines)
    if len(block) > SNAKE_MEM_RECALL_CHARCAP:        # 上限超過は古い方から落とす
        block = block[-SNAKE_MEM_RECALL_CHARCAP:]
        block = block[block.find("\n- ") + 1:] if "\n- " in block else block
    return block


def _room_label(to):
    """記憶に残す部屋名。channels.json で id/名前→dept に寄せる(読める名前で覚える)。fail-open=素の値。"""
    try:
        chans = json.load(open(CHANNELS_FILE, encoding="utf-8"))
        s = str(to)
        for c in chans:
            if s in (str(c.get("id", "")), str(c.get("name", ""))):
                return str(c.get("dept") or c.get("name") or s)
    except Exception:
        pass
    return str(to)


def _append_snake_memory(room, q, a):
    """実際に部屋へ投稿できた1往復を1行足す。fail-open。"""
    try:
        os.makedirs(os.path.dirname(SNAKE_SHARED_MEMORY), exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "room": _room_label(room), "q": (q or "")[:500], "a": (a or "")[:800]}
        with open(SNAKE_SHARED_MEMORY, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass                                        # 記憶は本番を止めない


# ---------------------------------------------------------------------------
# CODEX_HOME(頭脳の設定と資格情報)
# ---------------------------------------------------------------------------
def ensure_home(model, sandbox, reasoning_effort=DEFAULT_REASONING_EFFORT):
    """橋専用 CODEX_HOME を用意して env を返す。

    - config.toml= CLI互換の最小設定を毎回書き直す(正本のデスクトップ版設定は使わない)。
    - auth.json = 正本 ~/.codex/auth.json を**毎回コピー**(ChatGPTトークンは随時更新される)。
      正本が無い/ログインしていなければ ABORT(頭脳が動かないので投稿もしない)。
    """
    os.makedirs(BRIDGE_HOME, exist_ok=True)
    cfg = (
        f'model = "{model}"\n'
        f'model_reasoning_effort = "{reasoning_effort}"\n'
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
    # ★ChatGPTログイン一本化(Chami指示 msg 1545613962807083040 / 指示書#12・#13)=
    #   子プロセスからは OpenAI APIキー系を**外す**。理由は二つ:
    #   (1) ChatGPTプランの利用枠内でだけ使う運用なので、枠切れ時にAPI従量課金へ勝手に
    #       流れる余地を根本から断つ(APIキーが子プロセスに無ければフォールバックできない)。
    #   (2) ChatGPT認証済みでも APIキー系環境変数が居ると codex exec が失敗する事例が
    #       報告されている(openai/codex#27651)ため、子プロセスの環境を明示的に管理する。
    #   ★消すのは**この子プロセス用のコピー(env)だけ**= グローバル環境や他用途のキーには触れない。
    for _k in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        env.pop(_k, None)
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


def auto_land(path, branch, base_sha):
    """Codexの成果枝を共有ツリーの現在枝へ取り込む(Chami常時承認 2026-09-10)。

    黙って壊さないための入場条件= 全部満たした時だけ merge する。
      a) 共有ツリーが枝にいる(detached HEADなら触らない)
      b) codex側が commit 済み(未コミットの散らかりは取り込まない)
      c) base 以降に commit がある
      d) merge-tree が衝突なし
      e) 枝が触る道が共有ツリーで未コミット変更中でない(他人の作業を潰さない)
    戻り値 (landed: bool, why: str)。
    """
    cur = _git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if not cur or cur == "HEAD":
        return False, "共有ツリーがdetached HEAD"
    if _git(["status", "--porcelain"], cwd=path).stdout.strip():
        return False, "codex側に未コミットの変更が残っている"
    ahead = _git(["rev-list", f"{base_sha}..{branch}", "--count"]).stdout.strip()
    if ahead in ("", "0"):
        return False, "取り込むcommitが無い"
    probe = _git(["merge-tree", "--write-tree", cur, branch])
    if probe.returncode != 0:
        return False, "衝突あり(merge-treeが非0)"
    files = [ln for ln in _git(["diff", "--name-only", f"{base_sha}..{branch}"])
             .stdout.splitlines() if ln.strip()]
    if not files:
        return False, "差分ファイルが無い"
    dirty = _git(["status", "--porcelain", "--"] + files).stdout.strip()
    if dirty:
        first = dirty.splitlines()[0].strip()[:80]
        return False, f"取り込み先が編集中: {first}"
    msg = (f"取り込み: codex {branch} ({ahead}commit)\n\n"
           f"Chamiの常時承認(2026-09-10)により自動取り込み。"
           f"入場条件= 衝突なし・取り込み先に未コミット変更なし。")
    r = _git(["merge", "--no-ff", "-m", msg, branch])
    if r.returncode != 0:
        _git(["merge", "--abort"])
        return False, f"merge失敗(中止済み): {r.stderr.strip()[:120]}"
    return True, _git(["rev-parse", "--short", "HEAD"]).stdout.strip()


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
# 失敗理由の一次資料= CLI自身のセッション記録(2026-09-06 研究室HQ・仮当て C-033)
# ---------------------------------------------------------------------------
FAIL_RAW = os.path.join(LOCAL, "llm", "codex_fail_raw.jsonl")


def _last_session_error(since_ts):
    """橋専用 CODEX_HOME の rollout から、この実行の task_complete.error.message を拾う。

    ★なぜ在るか(実物 2026-09-06 14:11)= 従来は codex exec の stdout+stderr **全体**を
      substring 照合して失敗理由バケツを決めていた。Codexが**こちらのソースを読んだ**だけで
      tool出力に codex_run.py L14 の「not supported when using Codex with a ChatGPT account」
      が載るため、実際は繋がっている橋を「橋(Codex回線)不通」と誤診断してChamiへ誤報していた。
      CLIが自分で書く rollout の error.message を一次資料として先に読む。fail-open(読めなければ空)。
    """
    try:
        base = os.path.join(BRIDGE_HOME, "sessions")
        # ★同時実行(QUEUE_CLAIM_CAP=2)で他の便のセッションを掴まないよう、
        #   mtimeの新しさではなく**ファイル名の開始時刻が t_start に一番近いもの**を選ぶ。
        best, best_gap = "", None
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                    continue
                stamp = fn[len("rollout-"):len("rollout-") + 19]
                try:
                    started = time.mktime(time.strptime(stamp, "%Y-%m-%dT%H-%M-%S"))
                except ValueError:
                    continue
                gap = started - since_ts
                if gap < -10 or gap > 120:
                    continue
                if best_gap is None or abs(gap) < abs(best_gap):
                    best, best_gap = os.path.join(root, fn), gap
        if not best:
            return ""
        msg = ""
        with open(best, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"task_complete"' not in line:
                    continue
                try:
                    pl = (json.loads(line).get("payload") or {})
                except Exception:
                    continue
                err = pl.get("error") or {}
                if isinstance(err, dict) and err.get("message"):
                    msg = str(err["message"])
        return msg
    except Exception:
        return ""


# 失敗理由バケツの語。★ここに足す前に「その語はCLIが書くのか」を確かめること。
FAIL_KEYS = ("not supported", "invalid_request", "unauthorized", "401", "429",
             "Error loading config")


def classify_failure(session_error, stderr):
    """応答が空だった時の失敗理由を1語に決める(2026-09-06 イージス研究室・恒久)。

    ★★素材は**CLIが書いたものだけ**に限る= rollout の error.message と **stderr**。
      **stdout を渡すな。** codex exec の stdout にはモデルのtool出力(event_msg)が
      そのまま流れる。実物 2026-09-06T14-08-52 の rollout では、Codexがこちらのソースを
      読んだせいで codex_run.py L14 の自分のコメント文字列が **857KBの1行**に載っていた。
      旧実装は stdout+stderr の全文を substring 照合していたので、これを拾って
      reason='not supported' → 橋不通 → Chamiへ「橋が落ちている」と誤報した。
      **Codexがこちらのソースを読むだけで再発する**構造だったので、素材の側で線を引く。

    ★実測(2026-09-06 14:33・使い捨てCODEX_HOMEで再現)= CLIは自分のエラーを stderr へ書く。
        rc=1 / stdout 0バイト / stderr 929バイト
        stderr= `ERROR: {"type":"error","status":400,...
                 "The 'gpt-5.5-codex' model is not supported when using Codex with a ChatGPT account."}`
      = stdout を捨てても**本物の検出は1件も落ちない**。落ちるのは誤診断だけだ。

    ★過去5件の 'not supported' を数え直した結果、**1件も「橋不通」ではなかった**:
        09-05 11:50 = モデル名がChatGPTアカウントで使えない(橋は生きている)
        09-05 10:21×2 / 10:26 = rollout 8行で中断・error欄なし(理由はstderrのみ)
        09-06 14:11 = 上記の誤診断
      橋不通の文面へ落とす前に、この履歴を疑うこと(codex_responder.BRIDGE_DOWN_REASONS)。
    """
    err = str(session_error or "")
    if err and ("usage policy" in err or "flagged as potentially violating" in err):
        # 依頼文/素材が方針フィルタに弾かれた= 橋は生きている。橋不通と混ぜない。
        return "usage_policy"
    hay = err if err else str(stderr or "")
    if "usage limit" in hay or "purchase more credits" in hay:
        # ★2026-09-10 研究室HQ 止血= Codexアカウントの**利用枠切れ**。
        #   実物= local/llm/codex_fail_raw.jsonl の 2026-09-10T02:40:33 / 02:41:40 の2件。
        #   session_error(=CLIが書いた rollout の error.message)と stderr の両方に
        #   `You've hit your usage limit. Visit …/settings/usage to purchase more credits
        #    or try again at Sep 16th, 2026 5:23 AM.` が入っていた= 語の出所はCLI(上の★条件を満たす)。
        #   ここが無かったので reason='不明' → codex_responder が『うまく処理できなかった』の
        #   定型で部屋へ返し、Chamiが「具体的にどこが理解できないか」と聞いても同じ文が出た。
        #   ★"429" とは別バケツにする= 枠切れは橋不通(BRIDGE_DOWN_REASONS)ではない。
        #     橋は生きていて、枠だけが尽きている。混ぜるとChamiへ誤報になる。
        return "usage_limit"
    for key in FAIL_KEYS:
        if key in hay:
            return key
    return "不明"


def _log_fail_raw(rec):
    """失敗の生の理由を残す。捨てると次の調査がまた推測から始まる。fail-open。"""
    try:
        os.makedirs(os.path.dirname(FAIL_RAW), exist_ok=True)
        with open(FAIL_RAW, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# codex exec(頭脳を回す)
# ---------------------------------------------------------------------------
def run_codex(prompt, worktree, env, model, timeout, sandbox):
    """codex exec を専用worktree内で回し、最終メッセージを返す。

    戻り値 (text, ok)。ok=False なら text は失敗理由(人向け)。
    - -o で最終メッセージだけをファイルへ書かせる(900KBのログを漁らない)。
    - --skip-git-repo-check= worktreeもrepoだが将来 add-dir 併用でも落ちないよう明示。
    ★2026-09-05 aegis-gl 実測の直し= `-o` の置き場は worktree の中なので **untracked のまま残ると
      `worktree_changed()` が毎回 True になる**(実物= brieftest-red の worktree に
      `?? .codex_last_message.txt` だけが残り「実装が残った」と誤判定された)。
      読み終わったら**必ず消す**= 生成物でない足跡で司令塔への引き継ぎを起こさない。
    """
    last = os.path.join(worktree, ".codex_last_message.txt")

    def _drop_last():
        try:
            if os.path.exists(last):
                os.remove(last)
        except OSError:
            pass

    _drop_last()
    cmd = CODEX_CMD + ["exec", "-C", worktree, "--skip-git-repo-check",
                       "-s", effective_sandbox(sandbox), "-m", model, "-o", last, prompt]
    t_start = time.time()
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        _drop_last()
        return f"(生成失敗: codex exec が {timeout}秒で応答しなかった)", False
    text = ""
    try:
        text = open(last, encoding="utf-8").read().strip()
    except OSError:
        text = ""
    _drop_last()
    if not text:
        # -o が空= モデルが最終メッセージを1文字も返していない。
        # ★2026-09-06 研究室HQ 仮当て= 一次資料はCLI自身の rollout(_last_session_error)。
        #   stdout+stderr の全文照合は**Codexがこちらのソースを読んだ足跡**まで拾うので、
        #   一次資料が取れたときはそちらだけを見る(誤って「橋不通」と言わないため)。
        err = _last_session_error(t_start)
        # ★判定に渡すのは rollout の error と stderr だけ(classify_failure の docstring)。
        #   stdout は**記録には残すが判定には使わない**= モデルが書いた文字列で診断しない。
        reason = classify_failure(err, r.stderr)
        _log_fail_raw({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model,
                       "rc": r.returncode, "reason": reason,
                       "session_error": err[:1000],
                       "stderr_tail": (r.stderr or "")[-1000:],
                       "stdout_tail": (r.stdout or "")[-500:],   # 調査用。判定には使わない
                       "worktree": worktree})
        return f"(生成失敗: Codexが応答を返さなかった [{reason}] rc={r.returncode})", False
    return text, True


# ---------------------------------------------------------------------------
# 口(Discordへ Codex bot として投稿)= behop.dc_send を踏襲
# ---------------------------------------------------------------------------
def resolve_channel(target):
    if str(target).isdigit():
        return str(target)
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        chans = json.load(f)
    ch = next((c for c in chans if c.get("name") == target or c.get("dept") == target), None)
    if not ch:
        raise LookupError(f"チャンネル未登録: {target}")
    return str(ch["id"])


# Codex席の話者名。呼称ゲートCへ渡す speaker= 人事部門が確定した表示名と同じ文字列にする
# (codex_responder.PERSONA_TENTATIVE と一致させること。ズレると呼称ルール.json の
#  「ネイキッド・スネーク→一ノ瀬怜」行にも __男性キャラ__ の傘にも当たらず、行が休眠する)。
CODEX_PERSONA = "ネイキッド・スネーク"


def prepare_discord_chunks(text):
    """出口ゲートを一度だけ通し、Discordの文字数上限より安全側で分割する。

    ★空リストを返したら「この便は出さない」= dc_send_chunks は {"ok":True,"sent_count":0} を返す。
    """
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
        from enjoh import enjoh_backstop
        text = enjoh_backstop(text, tag="codex")
    except Exception:
        pass                                        # fail-open= 投稿は殺さない
    # ★2026-09-10 定型ack denylist(依頼= 改善提案部門トトリ / 炎上 msg 1547305004069560351)。
    #   炎上の実物「受け取った。処理を開始する。完了結果は保存してから返す。」は
    #   codex_responder.notify_room → dc_send → **この関数**を通っていた= Codex席の唯一の出口。
    #   一次ack本文そのものは 09-10 09:36 に codex_responder から撤去済だが、撤去は1箇所の守り。
    #   次の世代が別実装で同じackを書けば戻る(送信印で前に一度やられている)ので、合流点にも置く。
    #   判定の正本は enjoh.ack_only_reason 1本だけ(写しを持たない・ORG-11)。
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
        from enjoh import ack_backstop
        if ack_backstop(text, tag="codex"):
            return []                               # ★1通も出さない= 沈黙の方がマシ(共通規律§2)
    except Exception:
        pass                                        # fail-open= 判定が読めないなら喋る側へ倒す
    # ★2026-09-05(aegis-gl)呼称ゲートC。**Codex席の出口はここ1つだけ**=撃つ点を数えた(C-064):
    #     codex_run.py:540(本応答) / codex_responder.notify_room(短い通知)
    #   の2箇所とも dc_send を通る。だから当てるのはこの1箇所でよい。
    #   実測(2026-09-05)= それまで Codex の発話は**どのゲートも通っていなかった**。呼称ルール.json
    #   へスネークの行を作っても(人事部門 msg 1545698215322714152 の返り)、通り道が無く休眠する。
    #   ★当てるのは呼称だけ・呼びかけ位置だけ= dispatch と同型(理由は
    #     output_gates.apply_naming_gate_only の docstring)。口調Dは当てない。
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        import output_gates as _og
        text, _ = _og.apply_naming_gate_only("", CODEX_PERSONA, text, source="codex")
    except Exception:
        pass                                        # fail-open= 投稿は殺さない
    chunks, cur = [], ""
    for ln in text.splitlines(keepends=True):
        # 改行のない長文も2000字を越えないよう先に刻む。
        if len(ln) > 1900:
            if cur:
                chunks.append(cur)
                cur = ""
            while len(ln) > 1900:
                chunks.append(ln[:1900])
                ln = ln[1900:]
        if len(cur) + len(ln) > 1900:
            if cur:
                chunks.append(cur)
            cur = ""
        cur += ln
    if cur.strip():
        chunks.append(cur)
    return chunks or [text]


def dc_send_chunks(token, channel_id, chunks, start_index=0, on_progress=None):
    """チャンク列を投稿する。sent_countは先頭から何通完了したかを返す。"""
    try:
        start_index = max(0, int(start_index or 0))
    except (TypeError, ValueError):
        start_index = 0
    start_index = min(start_index, len(chunks))
    sent_count = start_index
    message_ids = []
    for i in range(start_index, len(chunks)):
        c = chunks[i]
        req = urllib.request.Request(
            f"{DC_API}/channels/{channel_id}/messages",
            data=json.dumps({"content": c}).encode("utf-8"),
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                     "User-Agent": "go5-codex/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                mid = json.loads(r.read().decode("utf-8")).get("id", "")
            sent_count = i + 1
            message_ids.append(str(mid or ""))
            if on_progress:
                on_progress(sent_count, str(mid or ""))
            print(f"投稿OK (Codex) msg={mid}" + (f" [{i+1}通目]" if i else ""))
        except urllib.error.HTTPError as e:
            if e.code == 403:
                error = ("HTTP 403 = Codex bot がこのチャンネルに入室していない。"
                         "Discordのチャンネル設定→権限でCodexのbotを追加。")
            else:
                error = f"HTTP {e.code}"
            print(f"投稿失敗: {error}")
            return {"ok": False, "sent_count": sent_count,
                    "message_ids": message_ids, "error": error}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            error = type(e).__name__
            print(f"投稿失敗: {error}")
            return {"ok": False, "sent_count": sent_count,
                    "message_ids": message_ids, "error": error}
        except Exception as e:
            error = type(e).__name__
            print(f"投稿失敗: {error}")
            return {"ok": False, "sent_count": sent_count,
                    "message_ids": message_ids, "error": error}
        time.sleep(0.4)
    return {"ok": True, "sent_count": sent_count,
            "message_ids": message_ids, "error": ""}


def dc_send_result(token, channel_id, text, start_index=0, on_progress=None):
    """Codex(bot本人)として投稿し、詳細な送信結果を返す。"""
    return dc_send_chunks(token, channel_id, prepare_discord_chunks(text),
                          start_index=start_index, on_progress=on_progress)


def dc_send(token, channel_id, text):
    """既存呼び出し互換の真偽値ラッパー。"""
    return dc_send_result(token, channel_id, text).get("ok") is True


def _deliver_saved_result(path, token, target=None):
    """保存済み結果を未送信チャンクから再開する。生成処理は一切行わない。"""
    rec = _read_result(path)
    if not rec or not str(rec.get("text") or "").strip():
        return {"ok": False, "sent_count": 0, "message_ids": [],
                "error": "saved_result_missing", "channel_id": ""}
    destination = str(target or rec.get("channel_id") or rec.get("channel") or "")
    try:
        channel_id = resolve_channel(destination)
    except (Exception, SystemExit) as e:
        rec.update({"status": "send_failed", "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "last_error": f"{type(e).__name__}: {e}"})
        _write_result(path, rec)
        print(f"SEND_FAILED saved_result={path} error={type(e).__name__}")
        return {"ok": False, "sent_count": int(rec.get("sent_count") or 0),
                "message_ids": [], "error": str(e), "channel_id": ""}

    chunks = list(rec.get("chunks") or prepare_discord_chunks(rec.get("text", "")))
    sent_count = max(0, min(int(rec.get("sent_count") or 0), len(chunks)))
    rec.update({"status": "sending", "channel_id": channel_id,
                "chunk_count": len(chunks), "chunks": chunks,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "last_error": ""})
    _write_result(path, rec)

    def checkpoint(done_count, message_id):
        rec["sent_count"] = done_count
        if message_id:
            rec.setdefault("message_ids", []).append(message_id)
        rec["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _write_result(path, rec)

    result = dc_send_chunks(token, channel_id, chunks, start_index=sent_count,
                            on_progress=checkpoint)
    rec["sent_count"] = int(result.get("sent_count") or sent_count)
    # monkeypatchや将来実装がcheckpointを使わない場合にもmsg_idを失わない。
    for mid in result.get("message_ids") or []:
        if mid and mid not in rec.setdefault("message_ids", []):
            rec["message_ids"].append(mid)
    rec["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if result.get("ok"):
        rec.update({"status": "sent", "sent_at": rec["updated_at"], "last_error": ""})
    else:
        rec.update({"status": "send_failed", "last_error": str(result.get("error") or "unknown")})
    _write_result(path, rec)
    result["channel_id"] = channel_id
    if not result.get("ok"):
        print(f"SEND_FAILED saved_result={path} error={rec['last_error']}")
    return result


def mark_sent(channel_id, msg_id):
    """送信(uptsukiyomi)を押す。dc_send が実際にHTTP成功を返した時だけ呼ぶ口
    (2026-09-05 トトリ経由Chami指示②=送信だけスタンプが空撃ちだった穴を埋める)。
    べき等・fail-open(印は本筋を絶対に止めない=react.py mark()と同じ作法)。

    ★2026-09-06(イージス研究室)= 押した結果を捨てるのをやめた。従来は returncode も stderr も
      捨てていたので「押せなかった」が**どこにも残らず**、送信印の不発を2日追えなかった。
      押し方の正本は scripts/lib/mark_press.py へ一本化(codex_responder.mark と写しだった)。
      戻り値は呼び側が使ってもよいが、fail-open は変わらない(印は本筋を止めない)。"""
    if not msg_id:
        return {"ok": False, "returncode": None, "error": "no_target", "secs": 0.0}
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
        from mark_press import press
        return press(channel_id, msg_id, "送信", codex=True, caller="codex_run.mark_sent")
    except Exception as e:
        return {"ok": False, "returncode": None, "error": f"{type(e).__name__}: {e}", "secs": 0.0}


def _record_delivery_completion(path, fallback_to=None):
    """送信後の記憶・送信印を一度だけ処理する。

    ★completion_recorded と sent_mark_ok を分ける(2026-09-06 イージス研究室)。
      従来は印の成否に関わらず completion_recorded=True になっていたので、
      レコードを見ても「押されたのか」が判別できなかった。この1欄が無いために
      不発の調査が実物ではなく推測から始まっていた(§4.55 入れた/効いた/直った)。"""
    rec = _read_result(path)
    if not rec or rec.get("completion_recorded"):
        return
    room = str(fallback_to or rec.get("channel_id") or rec.get("channel") or "")
    _append_snake_memory(room, rec.get("prompt", ""), rec.get("text", ""))
    if rec.get("reply_to"):
        r = mark_sent(rec.get("channel_id") or room, rec.get("reply_to")) or {}
        rec["sent_mark_ok"] = bool(r.get("ok"))
        rec["sent_mark_error"] = str(r.get("error") or "")
    rec["completion_recorded"] = True
    rec["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_result(path, rec)


def list_outbox():
    """保存済み結果の状態を表示する。"""
    try:
        names = sorted(n for n in os.listdir(OUTBOX_DIR) if n.endswith(".json"))
    except OSError:
        names = []
    if not names:
        print("outboxなし")
        return 0
    for name in names:
        rec = _read_result(os.path.join(OUTBOX_DIR, name)) or {}
        print(f"{rec.get('request_id', name[:-5])} status={rec.get('status', 'unknown')} "
              f"channel_id={rec.get('channel_id', '')} "
              f"sent={rec.get('sent_count', 0)}/{rec.get('chunk_count', 0)}")
    return 0


def resend_outbox(target="all"):
    """未送信の保存結果を再送する。targetはallまたはrequest_id。"""
    token = _read(TOKEN_FILE, "Codex botトークン")
    try:
        paths = [os.path.join(OUTBOX_DIR, n) for n in sorted(os.listdir(OUTBOX_DIR))
                 if n.endswith(".json")]
    except OSError:
        paths = []
    matched = 0
    failed = 0
    for path in paths:
        rec = _read_result(path) or {}
        rid = str(rec.get("request_id") or os.path.basename(path)[:-5])
        if target not in ("", "all", rid, os.path.basename(path)):
            continue
        if rec.get("status") == "sent":
            _record_delivery_completion(path)
            continue
        matched += 1
        result = _deliver_saved_result(path, token)
        if result.get("ok"):
            _record_delivery_completion(path)
            print(f"再送OK request_id={rid}")
        else:
            failed += 1
            print(f"再送失敗 request_id={rid} error={result.get('error', '')}")
    if not matched:
        print("再送対象なし")
    return 8 if failed else 0


# ---------------------------------------------------------------------------
# 生存確認
# ---------------------------------------------------------------------------
def do_ping(model, sandbox, timeout, reasoning_effort=DEFAULT_REASONING_EFFORT):
    """頭脳(実生成を1発)と口(bot本人の確認)を通す。★実生成まで通す(behop do_ping と同趣旨)。"""
    env = ensure_home(model, "read-only", reasoning_effort)  # pingは書かせない
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
def answer(prompt, to=None, tag="cli", model=None, sandbox="workspace-write",
           timeout=DEFAULT_TIMEOUT, keep_worktree=False, briefing=True, reply_to=None,
           request_id=None, origin_dept="", reasoning_effort=None):
    """1件を Codex に投げ、(必要なら)Codexとして投稿する。戻り値=終了コード。

    briefing=True(既定)で規律を注入する(Chami指示 2026-09-05)= worktree の
    local/CODEX_BRIEFING.md へ全文を置き、プロンプト先頭へ芯を載せる。詳細= codex_briefing.py。
    ★台帳とログには**依頼本文だけ**を残す(規律は毎回同じ= 台帳を規律で埋めない)。
    """
    # 同じDiscord便が再配達された場合、生成済み全文があればCodexを再実行せず送信だけ再開する。
    if to and request_id:
        existing = load_saved_result(request_id)
        if existing:
            path = result_path(request_id)
            print(f"★保存済み結果を再利用= {path} status={existing.get('status', 'unknown')}")
            if existing.get("status") != "sent":
                token = _read(TOKEN_FILE, "Codex botトークン")
                try:
                    delivered = _deliver_saved_result(path, token, target=to)
                except Exception as e:
                    print(f"SEND_FAILED saved_result={path} error={type(e).__name__}")
                    return 8
                if not delivered.get("ok"):
                    return 8
            _record_delivery_completion(path, fallback_to=to)
            return 0

    model, reasoning_effort = codex_model_for(origin_dept, model, reasoning_effort)
    env = ensure_home(model, sandbox, reasoning_effort)
    wt, branch, base = make_worktree(tag)
    if not wt:
        return 6
    topic = f"codex-{tag}-{time.strftime('%H%M%S')}-{os.getpid()}"
    claimed = claim(topic, f"codex run: {prompt[:60]}")
    if not claimed:
        print(f"注意: 所有権の宣言に失敗(黒板不通)。それでも隔離worktree内なので続行する: {topic}")
    full_prompt = prompt
    # 全部屋記憶を思い出す(部屋宛=to がある実運用の時だけ。CLIテストには載せない)。
    mem_block = _load_snake_memory() if to else ""
    if briefing:
        try:
            sys.path.insert(0, HERE)
            import codex_briefing
            codex_briefing.install(wt)
            full_prompt = codex_briefing.preamble_for(prompt, memory=mem_block)
            print(f"規律を注入= {os.path.join(wt, codex_briefing.BRIEF_REL)}"
                  + f" / 人格を注入= {os.path.join(wt, codex_briefing.PERSONA_REL)}"
                  + (f" / 記憶 {len(mem_block)}字を同梱" if mem_block else ""))
        except Exception as e:
            # fail-open= 規律が組めなくても依頼そのものは通す(沈黙が最悪の事故)。
            print(f"注意: 規律の注入に失敗(素の依頼で続行): {type(e).__name__}")
    t0 = time.time()
    changed = False
    try:
        text, ok = run_codex(full_prompt, wt, env, model, timeout, sandbox)
        changed = worktree_changed(wt, base)
    finally:
        if claimed:
            release(topic, "done" + (" (変更あり=worktree保持)" if changed else ""))
    secs = time.time() - t0

    route = f", origin={origin_dept}" if origin_dept else ""
    print(f"--- Codex ({model}/{reasoning_effort}{route}, {secs:.1f}秒, {'OK' if ok else '失敗'}) ---")
    print(text)
    landed, land_why = (False, "")
    if changed and ok:
        try:
            landed, land_why = auto_land(wt, branch, base)
        except Exception as e:
            landed, land_why = False, f"自動取り込みが例外で中断: {type(e).__name__}"
    if changed:
        if landed:
            print(f"★共有ツリーへ取り込み済み= {land_why}(枝 {branch})。実物確認はまだ=ブラウザで見るまで「直った」と書かない。")
        else:
            print(f"★worktreeに変更あり= {wt}(枝 {branch})。自動取り込みを見送った理由= "
                  f"{land_why or 'Codexの回答が失敗扱い'}。取り込みは差分を確認して意図的に。")
    _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": tag, "model": model,
          "reasoning_effort": reasoning_effort, "origin_dept": origin_dept,
          "secs": round(secs, 1), "ok": ok, "changed": changed, "worktree": wt if changed else "",
          "landed": landed, "land_why": land_why,
          "q": prompt[:200], "a": text[:300], "request_id": str(request_id or "")})

    saved_path = ""
    if to and ok:
        try:
            chunks = prepare_discord_chunks(text)
            saved_path = _save_generated_result(
                request_id, to, prompt, text, reply_to=reply_to,
                worktree=wt if changed else "", model=model, chunks=chunks)
        except Exception as e:
            # 保存できていない本文はDiscordへ送らない。送信成功後のプロセス死で成果が消えるため。
            print(f"outbox保存失敗: {type(e).__name__}: {e}")

    # 掃除= 変更が無ければ worktree を消す。あれば残す(差分を人が確認して取り込むため)。
    # 取り込み済みなら作業場だけ畳む。枝は追跡用に残す(mainに入っているので消しても復元できるが、由来を辿れる方を優先)。
    if not keep_worktree:
        if not changed:
            remove_worktree(wt, branch)
        elif landed:
            _git(["worktree", "remove", "--force", wt])

    if to:
        if ok:
            if not saved_path:
                print("outboxへ保存できないためDiscord投稿を中止")
                return 9
            token = _read(TOKEN_FILE, "Codex botトークン")
            try:
                delivered = _deliver_saved_result(saved_path, token, target=to)
            except Exception as e:
                print(f"SEND_FAILED saved_result={saved_path} error={type(e).__name__}")
                return 8
            posted = delivered.get("ok") is True
            # ★送信スタンプは「生成成功」ではなく「実際にDiscordへ投稿できた」時だけ押す
            #   (dc_sendの戻り値は従来ここで捨てられていて空撃ちの原因だった=2026-09-05修理②)。
            if posted:
                _record_delivery_completion(saved_path, fallback_to=to)
            else:
                print(f"投稿失敗。生成結果は保存済みなので再生成せず再送できる: {saved_path}")
                return 8
        else:
            print("生成失敗のため投稿は中止(失敗文をDiscordへ流さない)")
            return 5
    return 0 if ok else 5


def main():
    ap = argparse.ArgumentParser(description="Codexの頭脳と口。behop.pyのCodex版。")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--list-outbox", action="store_true",
                    help="保存済みCodex生成結果の送信状態を表示")
    ap.add_argument("--resend-outbox", nargs="?", const="all", default=None,
                    help="未送信結果を再送する。省略時は全件、値指定時はrequest_idだけ")
    ap.add_argument("--ask")
    ap.add_argument("--ask-file")
    ap.add_argument("--to")
    ap.add_argument("--reply-to", default=None,
                    help="投稿成功時に送信スタンプを押す先のmsg_id(2026-09-05配線②)")
    ap.add_argument("--request-id", default=None,
                    help="生成結果の保存・再送に使う冪等キー。通常は元Discord msg_id。")
    ap.add_argument("--tag", default="cli")
    ap.add_argument("--model", default=None)
    ap.add_argument("--origin-dept", default="",
                    help="@ボス召喚元の部門。未指定ならCodex既定モデルを使う")
    ap.add_argument("--reasoning-effort", default=None,
                    choices=["minimal", "low", "medium", "high", "xhigh"],
                    help="Codexの推論強度。未指定なら部門別ルータを使う")
    ap.add_argument("--sandbox", default="workspace-write",
                    choices=["read-only", "workspace-write", "danger-full-access"])
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--keep-worktree", action="store_true")
    ap.add_argument("--no-briefing", action="store_true",
                    help="規律を注入しない(検査で赤を見る時だけ使う。本番では使うな)")
    a = ap.parse_args()

    if a.ping:
        model, effort = codex_model_for(a.origin_dept, a.model, a.reasoning_effort)
        return do_ping(model, a.sandbox, a.timeout, effort)
    if a.list_outbox:
        return list_outbox()
    if a.resend_outbox is not None:
        return resend_outbox(a.resend_outbox)
    prompt = a.ask
    if a.ask_file:
        prompt = open(a.ask_file, encoding="utf-8").read().strip()
    if not prompt:
        print("使い方: codex_run.py --ping | --ask <文|--ask-file p> [--to <ch名|ID>] "
              "[--tag <用途>] [--model m] [--sandbox m] [--timeout s] [--keep-worktree]")
        return 1
    return answer(prompt, to=a.to, tag=a.tag, model=a.model, sandbox=a.sandbox,
                  timeout=a.timeout, keep_worktree=a.keep_worktree,
                  briefing=not a.no_briefing, reply_to=a.reply_to,
                  request_id=a.request_id,
                  origin_dept=a.origin_dept, reasoning_effort=a.reasoning_effort)


if __name__ == "__main__":
    sys.exit(main())
