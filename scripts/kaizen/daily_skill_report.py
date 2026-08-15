# -*- coding: utf-8 -*-
"""毎朝の「新規skill化」報告(改善提案部門)。

なぜ要るか= Chami依頼 2026-08-15(便 msg=1537997282610249800)
  「毎日朝8時に新規skill化したものを報告して、どんなスキルかを簡単説明してよ。
    それまで裏で作るべきスキル案を探しといて。別にその日はなかったらないというのでいい」

この部門で言う「skill化」= 再発の型・作成時プリフライト・skillの下書きを
  docs/departments/kaizen-analyst/ 配下へ**新規に書き上げること**(自室の職務・BOOT.md)。
  → だから検知は「その窓の間に **新規追加(git A)** された .md」= 既存doc(BOOT等)の
     編集は「新規skill化」ではないので出さない(git の diff-filter=A が編集を自然に落とす)。

正直さ(共通規律§1)=
  ・数字(件数)は git を**実行して**数える。推測しない。
  ・その日に無ければ「本日はなし」と出す(Chami明示=無ければ無いでいい)。
  ・「どんなスキルか」の一言は、ファイル自身の最初の散文を**抜き出す**(生成で盛らない)。
     さらに詳しい説明は、この報告を受け取った担当セッション(トトリ/アスナ)が声で足す。

窓の既定= 直近24h(毎朝の便に1回ずつ乗る形。二重に数えない)。
手で試す= PYTHONIOENCODING=utf-8 python scripts/kaizen/daily_skill_report.py
          （窓を変える例）--hours 48
"""
import argparse
import datetime as dt
import io
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SKILL_DIR = "docs/departments/kaizen-analyst"   # repo相対(gitに渡す)

# ★「新規skill化」ではない自室インフラdoc= 新規追加でもここに載れば報告から外す。
#   (型/プリフライト/skill下書き "以外" の常設文書。増えたら1行足す)
INFRA_BASENAMES = {
    "BOOT.md",
    "behavior-patterns.md",
    "request-patterns.md",
    "improvement-findings.md",
    "設計書_改善提案部門の再設計.md",
    "skill_backlog.md",            # ★裏で貯める「作るべきスキル案」= 型そのものではない
}


def _git(args):
    r = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else ""


def new_skill_files(now, hours):
    """窓の間に新規追加(A)された型ファイルのrepo相対パスを返す。"""
    since = dt.datetime.fromtimestamp(now - hours * 3600).strftime("%Y-%m-%d %H:%M:%S")
    until = dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
    out = _git(["log", "--since", since, "--until", until,
                "--diff-filter=A", "--name-only", "--pretty=format:",
                "--", SKILL_DIR + "/"])
    paths = []
    seen = set()
    for line in out.splitlines():
        p = line.strip()
        if not p or p in seen:
            continue
        if not p.startswith(SKILL_DIR + "/") or not p.endswith(".md"):
            continue
        if os.path.basename(p) in INFRA_BASENAMES:
            continue
        seen.add(p)
        paths.append(p)
    return paths


def describe(path):
    """(題名, 一言) を返す= ファイル自身の言葉。生成で盛らない。"""
    fp = os.path.join(ROOT, path.replace("/", os.sep))
    title = os.path.basename(path)
    blurb = ""
    try:
        with io.open(fp, encoding="utf-8") as f:
            lines = [l.rstrip("\n") for l in f.readlines()[:60]]
    except OSError:
        return title, blurb
    for l in lines:                       # 題名= 最初の "# " 見出し
        if l.startswith("# "):
            title = l[2:].strip()
            break
    for l in lines:                       # 一言= 最初の"見出しでも引用でも罫線でもない"散文
        s = l.strip()
        if not s or s.startswith(("#", ">", "-", "|", "---")):
            continue
        blurb = s
        break
    if len(blurb) > 140:
        blurb = blurb[:139] + "…"
    return title, blurb


def render(now, hours):
    dfrom = dt.datetime.fromtimestamp(now - hours * 3600).strftime("%-m/%-d %H:%M") \
        if os.name != "nt" else dt.datetime.fromtimestamp(now - hours * 3600).strftime("%#m/%#d %H:%M")
    duntil = dt.datetime.fromtimestamp(now).strftime("%#m/%#d %H:%M") if os.name == "nt" \
        else dt.datetime.fromtimestamp(now).strftime("%-m/%-d %H:%M")
    span = "%s〜%s" % (dfrom, duntil)
    paths = new_skill_files(now, hours)
    if not paths:
        return "◆新規skill化 直近%.0fh(%s)= 本日はなし" % (hours, span)
    out = ["◆新規skill化 直近%.0fh(%s)= %d件" % (hours, span, len(paths))]
    for p in paths:
        title, blurb = describe(p)
        base = os.path.basename(p)
        out.append("- %s(%s)" % (title, base))
        if blurb:
            out.append("  %s" % blurb)
    return "\n".join(out)


def main():
    import time
    ap = argparse.ArgumentParser(description="毎朝の新規skill化を数えて報告する")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--now", type=float, default=None, help="epoch秒。既定=現在時刻")
    a = ap.parse_args()
    now = a.now if a.now is not None else time.time()
    print(render(now, a.hours))


if __name__ == "__main__":
    main()
