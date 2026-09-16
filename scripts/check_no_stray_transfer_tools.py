#!/usr/bin/env python3
"""5SECルート直下に「スマホ転送/受信サーバー」系の成果物が落ちていないか弾く機械チェック。

炎上の実物(Chami指摘 2026-09-16「5SECのフォルダにbat置くな、関係ない。」):
  スマホ→PC転送の受信サーバー/起動batが、この運営runtimeフォルダ直下に混入した。
  真因は機構側 = 部門セッションは cwd=D:\\SougouStartFolder\\5SecMovieMaker で回るため、
  Chami個人の手道具(受信サーバー等)を作ると既定でここへ落ちる。
  持ち場は C-015拡張(2026-09-16) の通り E:\\転送ツール\\ 一式であって、この運営runtimeではない。

このチェッカは「置き場違い」を目で気付く前に機械で止めるためのもの。ルート直下(再帰しない)だけを見る:
  - 転送/受信系のファイル名シグネチャ(受信サーバー / スマホ受信 / upload_server / 転送ツール など)
  - ルート直下の .bat/.vbs/.lnk が E:\\転送ツール を参照している(=手道具の入口が紛れ込んだ)
いずれかを見つけたら終了コード1。E:\\転送ツール\\ 側は検査対象外(正しい持ち場なので)。

使い方:
  python scripts/check_no_stray_transfer_tools.py            # 既定=このrepoのルート直下を検査
  python scripts/check_no_stray_transfer_tools.py <dir>      # 指定ディレクトリの直下を検査
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

# 転送/受信系の手道具シグネチャ(ファイル名で判定)。持ち場は E:\転送ツール\ なのでルート直下に在ってはいけない。
NAME_SIG = re.compile(r"(受信サーバー|スマホ受信|スマホ.?転送|upload_server|転送ツール)", re.IGNORECASE)
# ルート直下の起動系が E:\転送ツール を指していたら、入口(bat/vbs/lnk)が紛れ込んだと判断。
POINTS_TO_TOOLDIR = re.compile(r"E:\\+転送ツール", re.IGNORECASE)
LAUNCHER_EXT = {".bat", ".vbs", ".cmd", ".ps1", ".lnk"}


def check_root(target):
    hits = []
    try:
        entries = os.listdir(target)
    except OSError as e:
        print(f"検査対象を開けない: {target} ({e})", file=sys.stderr)
        return None
    for name in entries:
        path = os.path.join(target, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if NAME_SIG.search(name):
            hits.append((name, "転送/受信系のファイル名"))
            continue
        if ext in LAUNCHER_EXT and ext != ".lnk":
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    body = f.read()
            except OSError:
                body = ""
            if POINTS_TO_TOOLDIR.search(body):
                hits.append((name, "E:\\転送ツール を指す起動ファイル"))
    return hits


def main():
    targets = sys.argv[1:] or [ROOT]
    total = 0
    for t in targets:
        t = os.path.normpath(os.path.abspath(t))
        hits = check_root(t)
        if hits is None:
            return 2
        for (name, why) in hits:
            print(f"{t}{os.sep}{name}  [{why}]")
            total += 1
    if total:
        print(f"\n置き場違い {total} 件。転送/受信系は E:\\転送ツール\\ が持ち場(C-015拡張)。"
              "ルート直下から退避してから作業を続けること。")
        return 1
    print("OK: ルート直下に転送/受信系の混入なし。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
