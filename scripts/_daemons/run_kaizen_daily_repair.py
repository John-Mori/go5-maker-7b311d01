# -*- coding: utf-8 -*-
"""毎朝8:10の起動器= 改修αの24h集計を走らせて、結果を改善提案部門へ届ける。

なぜ起動器が「届ける」までやるか(C-036)=
  集計だけ走らせて `kaizen_repair_analysis.jsonl` に貯めても、**誰も読まない**。
  対話セッションの自発報告を当てにしない= **終わった瞬間に起動器自身が結果を出す**。
  経路は既存の se_daily_review.ps1 と**同じ形**にする(dispatch.py のキュー投函・
  `--also-post` は付けない=Discordへ直接は出さない。受けた部屋が自分の名義で出す)。

なぜ .ps1 ではなく .py か=
  ①`dispatch.py --body-file` は本文を **utf-8** で読む。PowerShell 5.1 の
    `Out-File -Encoding utf8` は **BOM付き**を書くので、本文の先頭に `﻿` が乗る
    (2026-08-13 に change_log.jsonl の1行目が同じ理由で読めなくなっていた実例あり)。
    Python から BOM無しで書けばこの穴を最初から作らない。
  ②`.ps1` は日本語が書けない(BOM無しをANSIで読まれて化ける)= 意図をコメントに残せない。

登録= scripts/_daemons/register_kaizen_daily_repair.ps1(タスク名 go5_kaizen_daily_0810)
  ★08:00ちょうどは既に3本(go5_daily_report_0800 / go5_reaction_watch_0800 /
    go5_se_daily_review_0800)が団子になっているので **08:10** に置く。
手で試す= python scripts/_daemons/run_kaizen_daily_repair.py --dry-run
"""
import argparse
import datetime as dt
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ANALYSIS = os.path.join(ROOT, "scripts", "kaizen", "daily_repair_analysis.py")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
LOG = os.path.join(ROOT, "local", "_kaizen_daily_repair.log")
BODY = os.path.join(ROOT, "local", "_work", "kaizen_daily_repair_body.txt")
DEPT = "kaizen-analyst"          # 改善提案部門(この集計の持ち主)
# ★2026-08-23 手2(研究室HQ): 絵文字監視(8:00)が書いた「全部屋スタンプ一覧」を、この8:10の便で
#   一緒に読む。以前は絵文字監視が改善提案部門を**もう1回起こして**渡していた(実測 約1,600万/日)。
#   起こすのを1つ止め、傾向を見るための一覧はファイルから取り込む。★本日ぶんが無ければ捏造せず
#   「無い」と書く(古い一覧を今日のものとして混ぜない)。
KAIZEN_DIGEST = os.path.join(ROOT, "local", "_work", "reaction_watch_kaizen_digest.md")


def read_todays_emoji_digest():
    """絵文字監視が本日書いた全部屋一覧を返す。無い/古い時は None(捏造しない)。"""
    try:
        if not os.path.exists(KAIZEN_DIGEST):
            return None
        # 本日(ローカル)書かれたものだけを採る= 古い一覧を今日の便に混ぜない。
        mtime = dt.date.fromtimestamp(os.path.getmtime(KAIZEN_DIGEST))
        if mtime != dt.date.today():
            return None
        with io.open(KAIZEN_DIGEST, encoding="utf-8") as f:
            return f.read().strip() or None
    except Exception:
        return None


def log(msg):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "%s %s" % (stamp, msg)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _child_env():
    """★子のpythonに UTF-8 で喋らせる(2026-08-13 実測で焼かれた)。

    タスクスケジューラから走らせると端末が無く、子のstdoutは**cp932**になる。
    こちらが utf-8 として読むので `◆改修α` が `?????C??` に化け、
    `errors="replace"` が化けたまま通す= **中身が壊れた本文がそのまま投函される**。
    既存の se_daily_review.ps1 が `$env:PYTHONIOENCODING = 'utf-8'` を置いているのと同じ理由。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run(cmd):
    return subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=_child_env())


def main():
    ap = argparse.ArgumentParser(description="改修αの24h集計を走らせて改善提案部門へ届ける")
    ap.add_argument("--dry-run", action="store_true",
                    help="集計は走らせるが、投函しない(本文を表示して終わる)")
    a = ap.parse_args()

    if not os.path.exists(ANALYSIS):
        log("★台本が無い= %s / 何も投函せず終わる" % ANALYSIS)
        return 1

    r = run([ANALYSIS])
    body = (r.stdout or "").strip()
    if r.returncode != 0 or not body:
        # ★黙って落とすな= 失敗そのものを届ける(沈黙が最悪の事故)。
        body = ("★毎朝の改修α集計が失敗した(exit=%s)。\n"
                "--- stderr ---\n%s" % (r.returncode, (r.stderr or "")[:1500]))
        log("★集計が失敗した exit=%s" % r.returncode)

    # ★化けた本文を投函しない= 壊れたものを黙って配るくらいなら、壊れたと言う。
    #   `errors="replace"` は文字化けを **例外ではなく U+FFFD** にして通してしまうので、
    #   ここで数えて止める(2026-08-13 実測= cp932の本文がそのまま投函された)。
    if "�" in body:
        n = body.count("�")
        log("★本文が化けている(U+FFFD %d個)= 集計結果は投函しない" % n)
        body = ("★毎朝の改修α集計は走ったが、**本文が文字化けした**(U+FFFD %d個)。\n"
                "子プロセスの出力エンコーディングを疑え(PYTHONIOENCODING)。\n"
                "化けた本文は捨てた= %s のログを見てくれ。" % (n, LOG))

    # ★手2: 絵文字監視(8:00)が書いた本日の全部屋一覧を、この便に畳み込む(別便で起こさない)。
    digest = read_todays_emoji_digest()
    if digest:
        body += ("\n\n"
                 "======================================================\n"
                 "■ 本日の絵文字スタンプ 全部屋一覧(絵文字監視が8時に書いた・傾向確認用)\n"
                 "  ※これは「その場で対応」ではなく傾向を見るための一覧。個別の🔥/再発は\n"
                 "    各部屋へ別に配られ、未確認台帳にも積まれている。\n"
                 "======================================================\n"
                 + digest)
        log("絵文字一覧を畳み込んだ(%d字)" % len(digest))
    else:
        body += ("\n\n■ 本日の絵文字スタンプ 全部屋一覧: 無し"
                 "(絵文字監視が本日ぶんをまだ書いていない/新規スタンプが0件)。")
        log("絵文字一覧は本日ぶん無し= 畳み込まない")

    if a.dry_run:
        log("--dry-run= 投函しない。本文は以下:")
        print(body)
        return 0

    os.makedirs(os.path.dirname(BODY), exist_ok=True)
    with io.open(BODY, "w", encoding="utf-8") as f:     # ★BOM無しで書く(上の理由)
        f.write(body + "\n")

    # ★C-050の宛先宣言(2026-08-23)= この集計から出る提案はChamiが読む=返信を削らせない。
    d = run([DISPATCH, "--dept", DEPT, "--direct", "--audience", "chami",
             "--from", "自動(毎朝8:10の改修α集計)", "--body-file", BODY])
    log("投函 exit=%s / %s" % (d.returncode, (d.stdout or d.stderr or "").strip()[:300]))
    return d.returncode


if __name__ == "__main__":
    sys.exit(main())
