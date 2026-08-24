# -*- coding: utf-8 -*-
"""FCCへ1件の仕事を丸ごと投げる入口(手数を1コマンドにする)。

★なぜ在るか(2026-08-24 研究室HQ)
C-049 §7-B で「テスト・バグチェックは既定でFCC」と決めたのに、8/24の実務は**0便**だった。
真因は手順が裁定カタログの**本文**にあって、全室へ毎便配られる**見出し**には載らないこと。
= 各室は「FCCでやれ」とだけ言われ、clone→検査→起動→持ち帰りの4手を知らなかった。
**手数が多い道具は使われない。**だからここで1手にする。

    python scripts/llm/fcc_task.py --dept <自分の部門> --name <用途> --prompt-file <お題.md>

やること= ①公開repoの別クローンを用意(無ければ clone・あれば最新へ) ②お題を _TASK.md として置く
③fcc_launch.py(A〜Fの検査つき)経由で claude を回す ④成果(_FCC_REPORT.md と diff)の在りかを出す
⑤change_log.jsonl へ1行積む。

★安全は fcc_launch.py の A〜F(fail-close)がそのまま効く。ここはその手前に
**お題の中身に持ち物が載っていないかの検査**を1枚足すだけで、緩める所は1つも無い。
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import datetime

try:                                      # ★拒否理由が日本語Windowsの出口(cp932)で落ちないように
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
LAUNCH = os.path.join(HERE, "fcc_launch.py")
CHANGE_LOG = os.path.join(REPO, "local", "llm", "change_log.jsonl")
WORK_ROOT = os.environ.get("FCC_WORK_ROOT", r"D:\fcc_work")

# ★お題に載っていたら止める語= 「持ち物」そのもの(C-049 §7「守るのは持ち物であって用途ではない」)。
# 公開repoのコードとエラーメッセージだけを載せる、を機械で担保する。
FORBIDDEN = [
    "00_AI-HQ", "裁定カタログ", "Chami台帳", "characterfile", "characters/",
    "hq_open_items", "open_defects", "change_log.jsonl", "inbox.db",
    "discord.com/channels", "persona_context", "口調ルール",
    ".env", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "SHARED_SECRET",
]
# ★`local/` は語として広すぎる(localhost 等に当たる)ので、パスの形でだけ見る。
FORBIDDEN_PATHISH = ["local/", "local\\"]

DEFAULT_TOOLS = ["Bash(node:*)", "Bash(python:*)", "Bash(npx:*)", "Bash(git status:*)",
                 "Bash(git diff:*)", "Read", "Grep", "Glob", "Write", "Edit"]


def origin_url():
    """本番ツリーの origin(=公開repo)。clone元はここ1本に固定する。"""
    try:
        out = subprocess.check_output(["git", "-C", REPO, "config", "--get", "remote.origin.url"],
                                      stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def check_prompt(text):
    """お題に持ち物が載っていないかを見る。載っていたら理由を返す(空なら通す)。"""
    hits = []
    for w in FORBIDDEN:
        if w in text:
            hits.append(w)
    for w in FORBIDDEN_PATHISH:
        if w in text:
            hits.append(w)
    return hits


def prepare_workspace(name, fresh, refresh):
    ws = os.path.join(WORK_ROOT, name)
    url = origin_url()
    if not url:
        return "", "本番ツリーの origin が読めない(clone元が決まらない)"
    if fresh and os.path.isdir(ws):
        shutil.rmtree(ws, ignore_errors=True)
    if not os.path.isdir(os.path.join(ws, ".git")):
        os.makedirs(WORK_ROOT, exist_ok=True)
        rc = subprocess.call(["git", "clone", "--depth", "1", url, ws])
        if rc != 0:
            return "", "clone に失敗した(%s)" % url
    elif refresh:
        # ★失敗しても止めない(古いクローンでも仕事はできる)= fail-open
        subprocess.call(["git", "-C", ws, "fetch", "--depth", "1", "origin"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.call(["git", "-C", ws, "reset", "--hard", "FETCH_HEAD"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ws, ""


def head_of(ws):
    try:
        out = subprocess.check_output(["git", "-C", ws, "log", "--oneline", "-1"],
                                      stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "replace").strip()
    except Exception:
        return "(不明)"


def append_change_log(dept, name, ws, report, rc):
    rec = {
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "dept": dept,
        "何": "FCCへ仕事を1件載せた(用途=%s・rc=%d)" % (name, rc),
        "なぜ": "C-049 §7-B= テスト・バグチェックは既定でFCC。Anthropicの週枠を使わずに回すため",
        "触った": [ws, report or "(報告ファイル無し)"],
        "commit": "",
        "report_to": dept,
        "fcc": True,
    }
    try:
        with io.open(CHANGE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print("警告: change_log へ積めなかった(仕事自体は終わっている): %s" % e)
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--dept", required=True, help="自分の部門スラッグ(change_logへ積む)")
    ap.add_argument("--name", required=True, help="用途の名前(作業フォルダ名になる)")
    ap.add_argument("--prompt-file", required=True, help="お題を書いた .md(日本語でよい)")
    ap.add_argument("--fresh", action="store_true", help="作業フォルダを作り直す")
    ap.add_argument("--no-refresh", action="store_true", help="既存クローンを最新へ寄せない")
    ap.add_argument("--allow-tools", default="", help="道具の許可を上書き(空白区切り)")
    ap.add_argument("--dry-run", action="store_true", help="検査だけして起動しない")
    ns = ap.parse_args(argv)

    pf = ns.prompt_file if os.path.isabs(ns.prompt_file) else os.path.join(REPO, ns.prompt_file)
    if not os.path.isfile(pf):
        print("お題のファイルが無い: %s" % pf)
        return 2
    text = io.open(pf, encoding="utf-8", errors="replace").read()
    hits = check_prompt(text)
    if hits:
        print("FCCへ出すのを止めた= お題に『持ち物』が載っている(C-049 §7)。")
        for h in sorted(set(hits)):
            print("  ✗ %s" % h)
        print("→ 公開repoのコードとエラーメッセージだけにしてから出し直せ。")
        return 2

    ws, err = prepare_workspace(ns.name, ns.fresh, not ns.no_refresh)
    if err:
        print("作業フォルダを用意できない: %s" % err)
        return 3
    print("作業フォルダ= %s  (%s)" % (ws, head_of(ws)))

    shutil.copyfile(pf, os.path.join(ws, "_TASK.md"))
    report = os.path.join(ws, "_FCC_REPORT.md")
    if os.path.exists(report):
        os.remove(report)                 # ★前回の報告を「今回の成果」と読み違えないため

    tools = ns.allow_tools.split() if ns.allow_tools else DEFAULT_TOOLS
    cmd = [sys.executable, LAUNCH, "--workdir", ws, "--start-server"]
    if ns.dry_run:
        cmd.append("--dry-run")
    cmd += ["--", "-p", "Read ./_TASK.md and do exactly what it says.",
            "--permission-mode", "acceptEdits", "--allowedTools"] + tools
    rc = subprocess.call(cmd)
    if ns.dry_run:
        return rc

    print("")
    if os.path.exists(report):
        print("報告= %s" % report)
    else:
        print("報告ファイル(_FCC_REPORT.md)は作られなかった。お題で出力先を指定しているか見直せ。")
    try:
        diff = subprocess.check_output(["git", "-C", ws, "status", "--porcelain"],
                                       stderr=subprocess.DEVNULL).decode("utf-8", "replace")
        changed = [l for l in diff.splitlines() if l.strip() and "_TASK.md" not in l
                   and "_FCC_REPORT.md" not in l]
        if changed:
            print("クローン内で変わったファイル(持ち帰るならここから diff を取れ):")
            for l in changed[:30]:
                print("  " + l)
        else:
            print("クローン内の実装ファイルは無改変。")
    except Exception:
        pass
    append_change_log(ns.dept, ns.name, ws, report if os.path.exists(report) else "", rc)
    print("★成果を本番ツリーへ持ち帰るのは自分の手番だ(FCCの中では push しない)。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
