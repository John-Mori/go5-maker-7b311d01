#!/usr/bin/env python3
"""この運営runtimeフォルダに「スマホ転送/受信サーバー」系の手道具が混入していないか弾く機械チェック。

炎上の実物(Chami指摘 2026-09-16「5SECのフォルダにbat置くな、関係ない。」msg 1549490188701409385):
  スマホ→PC転送の受信サーバー一式(ファイアウォール許可bat + 受信サーバー起動bat)が、
  この運営runtimeの中に混入した。実際の置き場は **ルート直下ではなく** `local\\file_transfer\\` の中だった:
    local\\file_transfer\\1_ファイアウォール許可_管理者.bat
    local\\file_transfer\\2_受信サーバー起動.bat
  真因は機構側 = 部門セッションは cwd=D:\\SougouStartFolder\\5SecMovieMaker で回るため、
  Chami個人の手道具(受信サーバー等)を作ると既定でここへ落ちる。
  持ち場は C-015拡張(2026-09-16) の通り E:\\転送ツール\\ 一式であって、この運営runtimeではない。

【旧版の穴(2026-09-16 モドリッチ訂正 msg 1549587672538939464)】
  旧版はルート直下(非再帰)しか見なかったので、`local\\file_transfer\\` の中の実物を素通しした。
  かつ受入テストをルート直下のダミーで済ませ、壊れていた実物と同じ場面で叩いていなかった(§4.55の0歩目違反)。

【この版の作り】拡張子(.bat/.vbs 等)単独では絶対に弾かない —— この運営runtimeは正規の起動batだらけで、
  拡張子で弾くと誤検知で真っ赤になり誰も見なくなる(モドリッチ指摘#3)。「転送/受信の意味」で効かせる:
    (a) ファイル名が転送/受信系シグネチャ(受信サーバー / スマホ転送 / upload_server / 転送ツール / file_transfer)
    (b) 転送バンドルのフォルダ(file_transfer / 受信サーバー / スマホ転送 …)の中に在る launcher/成果物
        ← 名前が当たらない `1_ファイアウォール許可_管理者.bat` はこれで捕まる
    (c) launcher(.bat/.vbs/.cmd/.ps1)の中身が E:\\転送ツール を指す / 転送・受信サーバーを起動する
  再帰する。ただし機械が書くデータ・ログ(corpus / codex_home / queue / discord / llmログ / .git / worktree /
  産業廃棄物)は舐めない —— 手でダブルクリックする道具はそこには置かれず、舐めると誤検知と遅さを招くだけ。
  E:\\転送ツール\\ 側(正しい持ち場)はそもそも検査対象外(このrepoの外)。

使い方:
  python scripts/check_no_stray_transfer_tools.py            # 既定=このrepoを検査(データ/ログ除外して再帰)
  python scripts/check_no_stray_transfer_tools.py <dir>      # 指定ディレクトリを検査(除外なしで全再帰=テスト再現用)
違反があれば終了コード1(pre-commit / 起動フックへ配線して自動で弾ける。配線は基盤の持ち場)。
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))

# (a) 転送/受信系の手道具シグネチャ(ファイル名で判定)。持ち場は E:\転送ツール\ なのでこのrepoに在ってはいけない。
NAME_SIG = re.compile(r"(受信サーバー|スマホ受信|スマホ.?転送|upload_server|転送ツール|ファイル転送|file.?transfer)", re.IGNORECASE)
# (b) 転送バンドルのフォルダ名。この名のフォルダの中身は「バンドルごと置き場違い」なので全部弾く。
DIR_SIG = re.compile(r"(file.?transfer|ファイル転送|受信サーバ|スマホ転送|スマホ受信)", re.IGNORECASE)
# (c-1) launcherの中身が E:\転送ツール を指す = 手道具の入口が紛れ込んだ。
POINTS_TO_TOOLDIR = re.compile(r"E:\\+転送ツール", re.IGNORECASE)
# (c-2) launcherの中身が転送/受信サーバーを起動している。firewall(netsh)単独では判定しない(CRD修復等の正規batと衝突するため)。
CONTENT_SIG = re.compile(r"(受信サーバー|スマホ受信|スマホ.?転送|upload_server|転送ツール|ファイル転送)", re.IGNORECASE)
LAUNCHER_EXT = {".bat", ".vbs", ".cmd", ".ps1", ".lnk"}

# 既定検査(argv無し=このrepo)で舐めないディレクトリ。手でダブルクリックする道具は置かれない機械データ/ログ/退避。
SKIP_DIR_BASENAMES = {".git", "node_modules", ".mypy_cache", "__pycache__", ".pytest_cache"}
SKIP_REL_PREFIXES = (
    "local/corpus", "local/codex_home", "local/codex_cli", "local/queue",
    "local/attachments", "local/inbox", "local/discord", "local/llm",
    ".claude/worktrees", "産業廃棄物",
)


def _rel(root, path):
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path.replace(os.sep, "/")


def check_tree(target, apply_skips):
    """target配下を再帰。apply_skips=Trueなら既定の除外を効かせる(=このrepo検査)。"""
    hits = []
    if not os.path.isdir(target):
        print(f"検査対象を開けない: {target}", file=sys.stderr)
        return None
    for dirpath, dirnames, filenames in os.walk(target):
        # ディレクトリの剪定(再帰に入る前に間引く)
        pruned = []
        for d in list(dirnames):
            rel_d = _rel(target, os.path.join(dirpath, d))
            if apply_skips and (d in SKIP_DIR_BASENAMES or
                                any(rel_d == p or rel_d.startswith(p + "/") for p in SKIP_REL_PREFIXES)):
                continue
            pruned.append(d)
        dirnames[:] = pruned

        # (b) このフォルダ自体が転送バンドルか(親のどこかにDIR_SIGを含むフォルダが在るか)
        rel_dir = _rel(target, dirpath)
        in_transfer_dir = any(DIR_SIG.search(seg) for seg in rel_dir.split("/") if seg not in (".", ""))

        for name in filenames:
            path = os.path.join(dirpath, name)
            if not os.path.isfile(path):
                continue
            rel_f = _rel(target, path)
            ext = os.path.splitext(name)[1].lower()

            if NAME_SIG.search(name):                       # (a) ファイル名
                hits.append((rel_f, "転送/受信系のファイル名"))
                continue
            if in_transfer_dir:                             # (b) 転送バンドルの中身(名前不問)
                hits.append((rel_f, "転送バンドル(file_transfer等)の中の混入物"))
                continue
            if ext in LAUNCHER_EXT and ext != ".lnk":       # (c) launcherの中身
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        body = f.read()
                except OSError:
                    body = ""
                if POINTS_TO_TOOLDIR.search(body):
                    hits.append((rel_f, "E:\\転送ツール を指す起動ファイル"))
                elif CONTENT_SIG.search(body):
                    hits.append((rel_f, "転送/受信サーバーを起動する内容"))
    return hits


def check_root(target):
    """後方互換API。呼び手= scripts/hooks/stray_transfer_guard.decide_stray()(SessionStart/
    UserPromptSubmit相乗り)。旧版は「ルート直下(非再帰)」だったが、炎上の実物は
    local\\file_transfer\\ の中だった(モドリッチ訂正 msg 1549587672538939464)ため、
    この版は既定除外つきの再帰検査へ委譲する。判定は1本(ORG-11)=あちらを直せば
    commit経路(main)も起動側hookも同時に直る。戻り= [(相対パス, 理由), ...] / None(検査不能)。"""
    return check_tree(target, apply_skips=True)


def main():
    args = sys.argv[1:]
    if args:
        # 明示ディレクトリ指定=除外なしで全再帰(炎上再現テスト・任意ディレクトリ検査用)
        targets = [(os.path.normpath(os.path.abspath(a)), False) for a in args]
    else:
        targets = [(ROOT, True)]
    total = 0
    for (t, apply_skips) in targets:
        hits = check_tree(t, apply_skips)
        if hits is None:
            return 2
        for (rel_f, why) in sorted(hits):
            print(f"{t}{os.sep}{rel_f.replace('/', os.sep)}  [{why}]")
            total += 1
    if total:
        print(f"\n置き場違い {total} 件。転送/受信系は E:\\転送ツール\\ が持ち場(C-015拡張)。"
              "このruntimeから退避してから作業を続けること。")
        return 1
    print("OK: 転送/受信系の混入なし。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
