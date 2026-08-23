# -*- coding: utf-8 -*-
"""FCC(Free Claude Code)経由で claude を起動する**唯一の入口**。

裁定 C-049 執行形5 の執行形。A〜Dを**機械で確かめてから**起動し、
1つでも欠けたら **起動を拒む**(exit≠0・理由を1行で出す)。

  A. 起動先が本番の作業ツリーではない(公開repoの別クローン)
  B. --add-dir に 00_AI-HQ を含まない
  C. 子へ渡る CLAUDE_CONFIG_DIR が本番の ~/.claude ではない
  D. 起動フォルダ配下に秘密ファイルが無い(.env / *token* / *secret* / local/ / *.db)
  E. (追加)祖先に CLAUDE.md / MEMORY.md が無い= cwdの上から自動で本文へ載るのを止める
  F. (追加)--add-dir が作業フォルダの外を指していない

★判定に「パス名に local が在るか」のような**文字列当てを使わない**。
  親を1段ずつ上って `os.path.samefile` で突き合わせる=**実在(inode)で見る**。
  Windows の大文字小文字ゆれ・8.3短縮名・ジャンクションを文字列比較は取りこぼす。

使い方:
    python scripts/llm/fcc_launch.py --workdir <公開repoの別クローン> [--start-server]
                                     [--dry-run] [-- <claudeへ渡す引数...>]
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# ★出口の符号化を utf-8 に固定する(2026-08-23 研究室HQ差し戻し・HQ-0188)。
#   日本語Windowsの既定(cp932)へ拒否理由を書くと "✗" が UnicodeEncodeError で落ち、
#   **「なぜ止めたか」が1行も出ずに traceback だけ**になっていた。
#   起動そのものは止まる=fail-close の向きは壊れていない。だが理由を言えない安全網は
#   「起動器が壊れた」と読まれて**迂回される**(共通規律§3「常に誤発火する安全網は無視される」)。
#   ★記号を ASCII へ落とすのではなく**出口を直す**=後から記号や非cp932のパスが理由文へ
#   混ざっても同じ穴が開かない。errors="replace" で、書けない字が来ても**黙らない**。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOME = os.path.expanduser("~")
FCC_ENV = os.path.join(HOME, ".fcc", ".env")
FCC_URL = "http://127.0.0.1:8082"
HQ_ROOT = r"D:\SougouStartFolder\00_AI-HQ"
HOME_CLAUDE = os.path.join(HOME, ".claude")

# 秘密ファイルの見分け(D)。★basename で見る=パス全体への文字列当てにしない。
SECRET_EXACT = {".env"}
SECRET_SUBSTR = ("token", "secret")
SECRET_SUFFIX = (".db",)
SECRET_DIRS = {"local"}
ANCESTOR_LOADED = ("CLAUDE.md", "MEMORY.md")   # E= cwdの祖先から自動で読まれる物

# ★「既にネットに出ている」と認めてよい remote(2026-08-23 研究室HQ差し戻し・C-041)。
#   ここに無い remote / remote無し のフォルダでは、追跡済みでも**公開の証明にならない**=
#   名前当てのまま拒否側へ倒す。増やす時は「本当に誰でも読める公開repoか」を確かめてから。
PUBLIC_ORIGINS = frozenset({"github.com/john-mori/go5-maker-7b311d01"})


# ---------------------------------------------------------------- 実在検査
def _real(p):
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(p or ""))))


def _same(a, b):
    """2つのパスが**同じ実体**か。存在しない側は False(文字列比較へ落とさない)。"""
    try:
        return os.path.samefile(a, b)
    except Exception:
        return False


def _ancestors(path):
    """path 自身から根まで、実在するディレクトリを順に返す。"""
    cur = _real(path)
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        if os.path.isdir(cur):
            yield cur
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt


def _inside(child, parent):
    """child が parent と同じか、その配下か。**実在で**判定する。"""
    if not os.path.isdir(parent):
        return False
    return any(_same(a, parent) for a in _ancestors(child))


def _git_toplevel(start):
    """start を含む git 作業ツリーの根。無ければ ""。"""
    try:
        out = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=20)
        return _real(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else ""
    except Exception:
        return ""


def prod_roots():
    """守る対象= ①この起動器が入っている本番の作業ツリー ②00_AI-HQ。"""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    roots = []
    top = _git_toplevel(here) or _real(here)
    if os.path.isdir(top):
        roots.append(top)
    if os.path.isdir(HQ_ROOT):
        roots.append(_real(HQ_ROOT))
    return roots


# ---------------------------------------------------------------- 引数の解析
def parse_add_dirs(claude_args):
    """claude へ渡す引数から --add-dir の値を**実際に解析して**取り出す(B/F用)。

    `--add-dir X` / `--add-dir=X` / 複数回 のすべてを拾う。
    """
    out = []
    args = list(claude_args or [])
    i = 0
    while i < len(args):
        a = str(args[i])
        if a == "--add-dir":
            if i + 1 < len(args):
                out.append(args[i + 1])
                i += 1
        elif a.startswith("--add-dir="):
            out.append(a.split("=", 1)[1])
        i += 1
    return out


def build_plan(workdir, config_dir, claude_args, home_claude=None, hq_root=None):
    """検査に掛ける「実際に子へ渡る値」を1つの辞書へ畳む。

    ★ここで解決した値をそのまま子へ渡す=**検査した物と起動する物が同一**になる
      (ambient な環境変数を見て判定し、別の値で起動する、をやらない)。
    """
    return {
        "workdir": _real(workdir),
        "config_dir": _real(config_dir) if config_dir else "",
        "config_dir_raw": str(config_dir or ""),
        "add_dirs": [_real(os.path.join(_real(workdir), d))
                     for d in parse_add_dirs(claude_args)],
        "add_dirs_raw": parse_add_dirs(claude_args),
        "prod_roots": prod_roots(),
        "hq_root": _real(hq_root if hq_root else HQ_ROOT),
        "home_claude": _real(home_claude if home_claude else HOME_CLAUDE),
        "claude_args": list(claude_args or []),
    }


# ---------------------------------------------------------------- A〜F
def check_a(plan):
    wd = plan["workdir"]
    if not os.path.isdir(wd):
        return ["A: 作業フォルダが実在しない: %s" % wd]
    bad = []
    for root in plan["prod_roots"]:
        if _inside(wd, root):
            bad.append("A: 作業フォルダが**本番の作業ツリーの中**だ: %s ⊂ %s" % (wd, root))
        elif _inside(root, wd):
            bad.append("A: 作業フォルダが**本番の作業ツリーを飲み込んでいる**: %s ⊃ %s" % (wd, root))
    if not os.path.isdir(os.path.join(wd, ".git")):
        bad.append("A: 公開repoの**クローンではない**(.git が無い): %s" % wd)
    return bad


def check_b(plan):
    bad = []
    for raw, p in zip(plan["add_dirs_raw"], plan["add_dirs"]):
        if _inside(p, plan["hq_root"]):
            bad.append("B: --add-dir が 00_AI-HQ を指している: %s -> %s" % (raw, p))
            continue
        for root in plan["prod_roots"]:
            if _inside(p, root):
                bad.append("B: --add-dir が本番の作業ツリーを指している: %s -> %s" % (raw, p))
                break
    return bad


def check_c(plan):
    cd = plan["config_dir"]
    if not plan["config_dir_raw"].strip():
        return ["C: CLAUDE_CONFIG_DIR が空だ(既定の ~/.claude が読まれる)"]
    if _inside(cd, plan["home_claude"]) or _same(cd, plan["home_claude"]):
        return ["C: CLAUDE_CONFIG_DIR が**本番の ~/.claude** を指している: %s" % cd]
    return []


def _is_secret(name, isdir):
    low = name.lower()
    if isdir:
        return low in SECRET_DIRS
    if low in SECRET_EXACT:
        return True
    if any(s in low for s in SECRET_SUBSTR):
        return True
    return any(low.endswith(s) for s in SECRET_SUFFIX)


def _norm_origin(url):
    """remote の URL を突き合わせ用に均す(https / ssh / .git 有無 / 末尾スラッシュ)。

    `https://github.com/John-Mori/repo.git` も `git@github.com:John-Mori/repo` も
    同じ `github.com/john-mori/repo` になる。
    """
    u = str(url or "").strip().lower()
    if not u:
        return ""
    u = re.sub(r"^[a-z0-9+.-]+://", "", u)     # scheme://
    u = re.sub(r"^[^/@]+@", "", u)             # user@
    u = re.sub(r":(?!\d)", "/", u, count=1)    # scp形式の host:path (ポート番号は残す)
    u = re.sub(r"\.git$", "", u)
    u = re.sub(r"/+", "/", u).rstrip("/")
    return u


def origin_url(wd):
    """作業フォルダの origin。無ければ空文字。"""
    try:
        out = subprocess.run(["git", "-C", wd, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=60)
        return (out.stdout or "").strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _remote_ref(wd):
    """remote 側の実体を指す ref を1つ返す(origin/HEAD → origin/main → origin/master)。"""
    for ref in ("origin/HEAD", "origin/main", "origin/master"):
        try:
            out = subprocess.run(["git", "-C", wd, "rev-parse", "--verify", "-q", ref],
                                 capture_output=True, text=True, timeout=60)
            if out.returncode == 0 and (out.stdout or "").strip():
                return ref
        except Exception:
            pass
    return ""


def published_files(wd):
    """**既にネットに出ている**ファイルの集合(相対パス・小文字)。

    ★なぜ要るか= 公開repoのソースには `update_token.ps1` `js/secret-reveal.js` のように
      名前が秘密っぽいだけの**公開済みのコード**が実在する(この repo で実測7件)。
      名前当てだけで拒むと、C-049 が許した唯一の使い道(公開repoの別クローン)が
      **永久に起動できない**=規則が死ぬ。

    ★★2026-08-23 差し戻し(研究室HQ・C-041)で直した所=
      旧版は `git ls-files`(=**追跡されているか**)を「公開済み」の代理にしていた。
      だが `git init` だけのフォルダに `.env` を置いて commit すれば、**どこにも出ていない秘密が
      「追跡済み」になって通る**。代理が成り立つ条件(=どこへ出ているのか)を測っていなかった。
      今は remote の実体そのものを見る:
        ① origin が **許可リストの公開repo** であること(知らないremoteは公開の証明にならない)
        ② そのファイルが **remote側のツリーに在る**こと(ローカルcommitだけの物は含まれない)
      どちらかが欠けたら**空集合**=名前当てがそのまま効いて拒否側へ倒れる(fail-close)。
    """
    try:
        if _norm_origin(origin_url(wd)) not in PUBLIC_ORIGINS:
            return set()                       # remote無し / 知らないremote = 公開の証明が無い
        ref = _remote_ref(wd)
        if not ref:
            return set()                       # remote側のツリーを引けない = 同上
        out = subprocess.run(["git", "-C", wd, "ls-tree", "-r", "--name-only", ref],
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            return set()
        return {p.strip().replace("/", os.sep).lower()
                for p in out.stdout.splitlines() if p.strip()}
    except Exception:
        return set()


# 旧名。呼び出し元が残っていても静かに別物にならないよう、同じ物を指す。
tracked_files = published_files


def find_secrets(wd, limit=20):
    """作業フォルダ配下の秘密ファイルを実際に歩いて数える(D)。

    追跡済み(=公開済み)のファイルは数えない。**未追跡**の `.env` / `*token*` /
    `*secret*` / `local/` / `*.db` が、実務の持ち物が紛れ込んだ印だ。
    """
    hits = []
    wd = _real(wd)
    tracked = published_files(wd)          # ★「追跡済み」でなく「公開済み」で見る(C-041)
    for cur, dirs, files in os.walk(wd):
        dirs[:] = [d for d in dirs if d != ".git"]
        for d in list(dirs):
            if _is_secret(d, True):
                rel = os.path.relpath(os.path.join(cur, d), wd)
                # 追跡済みのファイルを1つでも抱えるディレクトリは公開物=数えない
                if not any(t.startswith(rel.lower() + os.sep) for t in tracked):
                    hits.append(rel + os.sep)
                    dirs.remove(d)
        for f in files:
            if _is_secret(f, False):
                rel = os.path.relpath(os.path.join(cur, f), wd)
                if rel.lower() not in tracked:
                    hits.append(rel)
        if len(hits) >= limit:
            break
    return hits


def check_d(plan):
    if not os.path.isdir(plan["workdir"]):
        return []                      # A が既に拒んでいる
    hits = find_secrets(plan["workdir"])
    if not hits:
        return []
    return ["D: 作業フォルダに秘密ファイルが在る(%d件): %s%s"
            % (len(hits), " / ".join(hits[:5]), " …" if len(hits) > 5 else "")]


def check_e(plan):
    """★追加= 祖先の CLAUDE.md / MEMORY.md。cwdの**上**に在るだけで本文へ載る。

    作業フォルダ自身の CLAUDE.md は公開repoの中身なので対象にしない(既に公開されている)。
    """
    wd = plan["workdir"]
    bad = []
    for a in _ancestors(wd):
        if _same(a, wd):
            continue
        for name in ANCESTOR_LOADED:
            p = os.path.join(a, name)
            if os.path.isfile(p):
                bad.append("E: 祖先に %s が在る(cwdの上から自動で本文へ載る): %s" % (name, p))
    return bad


def check_f(plan):
    """★追加= --add-dir が作業フォルダの外。B(00_AI-HQ・本番)以外の外も塞ぐ。"""
    bad = []
    for raw, p in zip(plan["add_dirs_raw"], plan["add_dirs"]):
        if _inside(p, plan["hq_root"]):
            continue                   # B が拒む(二重に数えない)
        if any(_inside(p, r) for r in plan["prod_roots"]):
            continue                   # B が拒む
        if not _inside(p, plan["workdir"]):
            bad.append("F: --add-dir が作業フォルダの外を指している: %s -> %s" % (raw, p))
    return bad


CHECKS = [("A", check_a), ("B", check_b), ("C", check_c),
          ("D", check_d), ("E", check_e), ("F", check_f)]


def preflight(plan):
    """A〜Fを全部走らせ、**拒否理由のリスト**を返す(空=起動してよい)。

    ★1つ落ちても残りを走らせる= 直す側が全部を一度に見られる。
    """
    reasons = []
    for _name, fn in CHECKS:
        try:
            reasons.extend(fn(plan))
        except Exception as e:                       # 検査自身が落ちたら**拒否**へ倒す
            reasons.append("%s: 検査が例外で落ちた(%s)=判定不能のため起動しない"
                           % (_name, type(e).__name__))
    return reasons


# ---------------------------------------------------------------- 起動
def load_fcc_token():
    try:
        for ln in io.open(FCC_ENV, encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith("ANTHROPIC_AUTH_TOKEN="):
                return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def server_alive(timeout=3):
    try:
        with urllib.request.urlopen(FCC_URL + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def start_server(wait=40):
    """★常駐にしない= 使う時だけ起こし、起動器が終わったら落とす。

    理由= 常駐にすると 127.0.0.1:8082 が**開きっぱなし**になる。
    FCCは使う頻度が低い(C-049 執行形6=主戦場ではない)ので、
    開けている時間を短くする方が得だ。
    """
    exe = shutil.which("fcc-server")
    if not exe:
        return None
    p = subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(wait):
        if server_alive():
            return p
        time.sleep(1)
    return p


def child_env(plan, token):
    e = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    e["ANTHROPIC_BASE_URL"] = FCC_URL
    e["ANTHROPIC_AUTH_TOKEN"] = token
    e["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
    e["CLAUDE_CONFIG_DIR"] = plan["config_dir"]       # ★検査した値そのものを渡す
    for k in ("DISABLE_AUTOUPDATER", "DISABLE_FEEDBACK_COMMAND",
              "DISABLE_ERROR_REPORTING", "DISABLE_TELEMETRY"):
        e[k] = "1"
    return e


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--workdir", required=True, help="公開repoの別クローン(使い捨て)")
    ap.add_argument("--config-dir", default="",
                    help="子へ渡す CLAUDE_CONFIG_DIR。省略時は使い捨ての一時フォルダを作る")
    ap.add_argument("--start-server", action="store_true",
                    help="FCCサーバが落ちていたら起こす(終了時に落とす)")
    ap.add_argument("--dry-run", action="store_true", help="検査だけして起動しない")
    ap.add_argument("rest", nargs=argparse.REMAINDER, help="-- のあとは claude へ素通し")
    ns = ap.parse_args(argv)

    claude_args = [a for a in ns.rest if a != "--"]
    cfg = ns.config_dir
    made_cfg = ""
    if not cfg:
        made_cfg = cfg = tempfile.mkdtemp(prefix="fcc_cfg_")

    plan = build_plan(ns.workdir, cfg, claude_args)
    reasons = preflight(plan)
    if reasons:
        print("起動を拒否した(C-049 執行形5)。欠けている条件:")
        for r in reasons:
            print("  ✗ " + r)
        if made_cfg:
            shutil.rmtree(made_cfg, ignore_errors=True)
        return 2

    print("A〜F 全通過。作業=%s / 設定=%s" % (plan["workdir"], plan["config_dir"]))
    if ns.dry_run:
        return 0

    token = load_fcc_token()
    if not token:
        print("起動できない: ~/.fcc/.env に ANTHROPIC_AUTH_TOKEN が無い")
        return 3

    proc = None
    if not server_alive():
        if not ns.start_server:
            print("起動できない: FCCサーバ(%s)が応答しない。--start-server を付けるか "
                  "先に fcc-server を起こせ" % FCC_URL)
            return 4
        proc = start_server()
        if not server_alive():
            print("起動できない: fcc-server を起こしたが /health が返らない")
            if proc:
                proc.terminate()
            return 4

    exe = shutil.which("claude") or "claude"
    try:
        rc = subprocess.call([exe] + claude_args, cwd=plan["workdir"],
                             env=child_env(plan, token))
    finally:
        if proc:
            proc.terminate()
    return rc


if __name__ == "__main__":
    sys.exit(main())
