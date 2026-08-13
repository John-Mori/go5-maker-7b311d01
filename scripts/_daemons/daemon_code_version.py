#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""supervise_daemons.ps1 が見ている常駐7本の「今のコードの版」を測る道具。

なぜ要るか= C-042(常駐が読むものを足したら、載せ替えの経路も同時に決めろ)。
  実測した事故(研究室HQ msg 1537346679299112960 / 2026-08-13)=
  イージス研究室が 8/12 02:51 の `bc1e664` で `absence_watchdog.check_stale_dead`
  (デッドレターの滞留警報)を入れたのに、走っていたプロセスは **8/11 23:36 起動**だった。
  常駐は起動時にコードを1回読むだけなので、**3時間早く起動したプロセスが13時間そのまま
  古いコードで走り続けた**= あの警報は一度も鳴かず、08:00 に dead へ落ちた🔥digest が
  12.3時間サイレントになった。**穴を塞ぐために作った機構が、同じ形(載せ替えが無い)で寝ていた。**

  `dept_daemon` は `daemon_keeper.WATCH_FILES` で載せ替わる。だが supervise_daemons.ps1 が
  見ている7本は **生死しか見ていない**= 「直したのに載っていない」を静かに作れる。
  → 生死の監視に**版の監視**を足す。その「版」をここで測る。

測り方=
  各常駐の .py から **推移的に** import している自作モジュール(このrepo内の.py)を ast で辿り、
  その閉包の中の**最も新しい mtime** を「その常駐の版」とする。
  ★import は起動時に1回解決されて sys.modules に固定されるので、関数の中の import も同じ
    (= 走っている間に直しても効かない)。だから閉包で見る。
  ★手で監視リストを書くと必ずずれる(dept_daemon 側で leasequeue/tone_gate/naming_gate/
    persona_send/dept_names の5本が後から見つかった)。だから**リストを持たず毎回辿る**。

★版は mtime ではなく **中身のsha1** で見る(2026-08-13 実測で決めた)。
  最初 mtime で書いたら、7本すべてが同じ秒(15:39:59)を指した= **並列セッションのgit操作**
  (pull --rebase --autostash 等)が作業ツリーを書き戻すと、中身が同じでも mtime が全部動く。
  mtimeで判定すると**git操作のたびに常駐7本が全滅再起動する**。だから閉包の中身のsha1を版とし、
  **起動した瞬間の版を supervise_daemons.ps1 が記録**して、今の版と突き合わせる
  (= プロセスが実際に読んだコードとの比較になる)。mtime は「編集が落ち着いたか」の判定にだけ使う。

★この道具は「今の版」を出すだけで、判定はしない。**起動時の版を控えるのは
  supervise_daemons.ps1**(local/_daemon_codever/<name>.txt へ書く)。
★控えが無い相手(この機構より前から走っているプロセス)は sha1 では比べられない。
  その時だけ **git の最終コミット時刻**(閉包に最後に触れたコミット)と起動時刻を比べる。
  コミット時刻は中身に紐づくので作業ツリーの書き戻しでは動かない=mtimeより硬い。
  1度載せ替われば控えが出来て、以後は sha1 の比較に移る(=不明な相手は数パスで消える)。
  2026-08-13の実測で、5本が 7/29 19:00 起動のまま**14.9日**走っていた=まさにこれに当たる。

使い方=
  python scripts/_daemons/daemon_code_version.py
    → name<TAB>最新mtime<TAB>最新file<TAB>sha1<TAB>最終コミットepoch (1行1常駐)
  python scripts/_daemons/daemon_code_version.py --files absence_watchdog   # 閉包の中身
検査= python scripts/_daemons/test_daemon_code_version.py
"""
import argparse
import ast
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))  # 5SecMovieMaker
PS1 = os.path.join(ROOT, "scripts", "_daemons", "supervise_daemons.ps1")

# import 名 → ファイルを解決する時に見るディレクトリ(各常駐が sys.path へ足している所)。
IMPORT_DIRS = [("scripts", "llm"), ("scripts", "_common"), ("scripts", "discord"),
               ("scripts", "queue"), ("scripts", "_daemons"), ("scripts", "report"),
               ("scripts", "office"), ("scripts", "lib"), ("scripts", "imagegen")]

# ★正本は supervise_daemons.ps1 の $daemons(生死を見ている本人)。ここはその写しで、
#   ずれたら test_daemon_code_version.py が落ちる(両方向で突合する)。
SUPERVISED = [
    ("absence_watchdog", os.path.join("scripts", "discord", "absence_watchdog.py")),
    ("local_responder", os.path.join("scripts", "llm", "local_responder.py")),
    ("gemini_responder", os.path.join("scripts", "llm", "gemini_responder.py")),
    ("office_daily", os.path.join("scripts", "office", "office_daily.py")),
    ("claude_responder", os.path.join("scripts", "llm", "claude_responder.py")),
    ("daemon_keeper", os.path.join("scripts", "_daemons", "daemon_keeper.py")),
    ("discord_gateway", os.path.join("scripts", "queue", "discord_gateway.py")),
]


def local_imports(path, root=ROOT, import_dirs=None):
    """path が import しているこのrepo内の .py を {名前: 絶対パス} で返す。

    ★実行せず ast で読むだけ(副作用ゼロ)。解決できない名前(stdlib・外部)は黙って捨てる。
    """
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except Exception:                                  # noqa: BLE001
        return {}
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    found = {}
    for name in sorted(names):
        for parts in (import_dirs or IMPORT_DIRS):
            cand = os.path.join(root, *parts, name + ".py")
            if os.path.exists(cand):
                found[name] = os.path.normpath(cand)
                break
    return found


def closure(entry_path, root=ROOT, import_dirs=None):
    """entry_path 自身＋推移的に読む自作モジュールの絶対パス一覧(重複なし)。"""
    entry = os.path.normpath(entry_path if os.path.isabs(entry_path)
                             else os.path.join(root, entry_path))
    seen, stack = {entry}, [entry]
    while stack:
        for _name, p in local_imports(stack.pop(), root, import_dirs).items():
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return sorted(seen)


def version_of(entry_path, root=ROOT, import_dirs=None):
    """(閉包の中の最新mtime, そのファイル) を返す。1つも読めなければ (0.0, None)。"""
    newest, who = 0.0, None
    for p in closure(entry_path, root, import_dirs):
        try:
            m = os.path.getmtime(p)
        except OSError:
            continue
        if m > newest:
            newest, who = m, p
    return newest, who


def code_hash(entry_path, root=ROOT, import_dirs=None):
    """閉包の**中身**のsha1(12桁)。ファイル名の並び＋各ファイルのバイト列から作る。

    ★これが「版」。mtime と違って git の書き戻しでは動かない=中身が変わった時だけ変わる。
    ★読めないファイルは名前だけを混ぜる(消えた/壊れたも版の変化として拾う)。
    """
    h = hashlib.sha1()
    for p in closure(entry_path, root, import_dirs):
        h.update(os.path.relpath(p, root).replace("\\", "/").encode("utf-8"))
        try:
            with open(p, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()[:12]


def git_commit_epoch(entry_path, root=ROOT, import_dirs=None):
    """閉包のどれかに最後に触れた**コミット**の時刻(epoch)。取れなければ 0.0。

    ★用途は1つだけ= 「起動時の版を記録していないプロセス」を1回だけ判定する物差し。
      作業ツリーの書き戻し(mtimeが動く)では変わらず、中身が変わった時にだけ進むので、
      「このプロセスの起動より後に、読んでいるコードが変わったか」を硬く言える。
    ★未コミットの編集は見えない= その分は載せ替えない(可用性へ倒す)。
      次のコミットで版が動くので、遅れて必ず載る。
    """
    files = [os.path.relpath(p, root) for p in closure(entry_path, root, import_dirs)]
    if not files:
        return 0.0
    try:
        r = subprocess.run(["git", "-C", root, "log", "-1", "--format=%ct", "--"] + files,
                           capture_output=True, text=True, timeout=30)
    except Exception:                                  # noqa: BLE001
        return 0.0
    out = (r.stdout or "").strip().splitlines()
    try:
        return float(out[0]) if out else 0.0
    except ValueError:
        return 0.0


def dirty_mtime(entry_path, root=ROOT, import_dirs=None):
    """閉包のうち **HEADと違う(未コミットの)** ファイルの、最新mtime。無ければ 0.0。

    ★これも「控えが無い相手」専用の物差し。コミット時刻だけでは**未コミットの編集が見えない**=
      2026-08-13 実測で office_daily(7/29 19:00起動・14.9日)が「コミットは起動より古い」だけで
      「現行を読んでいる」と誤って採用された(実際は build_office.py の当日の編集が未コミット)。
    ★mtime単独は使わない(gitの書き戻しで全部動く)。**HEADと中身が違う**という条件と
      重ねて初めて「起動より後に、実際に書き換わった」と言える。
    """
    files = [os.path.relpath(p, root) for p in closure(entry_path, root, import_dirs)]
    if not files:
        return 0.0
    try:
        r = subprocess.run(["git", "-C", root, "status", "--porcelain", "--"] + files,
                           capture_output=True, text=True, timeout=30)
    except Exception:                                  # noqa: BLE001
        return 0.0
    newest = 0.0
    for line in (r.stdout or "").splitlines():
        rel = line[3:].strip().strip('"')
        if " -> " in rel:                      # rename は右側が今の名前
            rel = rel.split(" -> ")[-1]
        try:
            m = os.path.getmtime(os.path.join(root, rel))
        except OSError:
            continue
        newest = max(newest, m)
    return newest


def supervised_from_ps1(ps1_path=PS1):
    """supervise_daemons.ps1 の $daemons から (Name, Rel) を読む(コメント行は除く)。"""
    out = []
    with open(ps1_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.lstrip().startswith("#"):
                continue
            m = re.search(r"Name='([^']+)'.*?Rel='([^']+)'", line)
            if m:
                out.append((m.group(1), os.path.normpath(m.group(2))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", metavar="NAME", help="その常駐が読む自作モジュールを並べる")
    args = ap.parse_args()

    table = dict(SUPERVISED)
    if args.files:
        rel = table.get(args.files)
        if not rel:
            print("unknown daemon: %s" % args.files, file=sys.stderr)
            return 2
        for p in closure(rel):
            print("%.0f\t%s" % (os.path.getmtime(p), os.path.relpath(p, ROOT)))
        return 0

    # ★ps1が読む形= name / 最新mtime / 最新file / sha1 / 最終コミットepoch / 未コミットの最新mtime。
    #   mtime=「編集が落ち着いたか」/ sha1=「版が変わったか」/ 後ろ2つ=「控えが無い相手」の判定用。
    for name, rel in SUPERVISED:
        epoch, who = version_of(rel)
        print("%s\t%.0f\t%s\t%s\t%.0f\t%.0f" % (name, epoch,
                                                os.path.relpath(who, ROOT) if who else "-",
                                                code_hash(rel), git_commit_epoch(rel),
                                                dirty_mtime(rel)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
