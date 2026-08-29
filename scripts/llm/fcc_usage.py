# -*- coding: utf-8 -*-
"""FCC(Free Claude Code)が実務にどれだけ載っているかを実測する。

★作った理由= 「FCCの効果どうなった?」に手で数えて答えていた(2026-08-24・2026-08-29 の2回)。
   手で数えると毎回ちがう嘘をつく(全部門共通規律 §1)ので、数え方をここへ1本化する。

数えるもの(2系統。どちらも実物を読む。台帳の自己申告は使わない)
  ①仕事の件数 = local/llm/change_log.jsonl の fcc:true 行(fcc_task.py が書く)
  ②上流へ流した要求 = ~/.fcc/logs/server.log* の中で、実際に Provider へ POST した行

使い方
  python scripts/llm/fcc_usage.py            … 全期間
  python scripts/llm/fcc_usage.py --days 7   … 直近7日だけ
"""
import argparse
import datetime
import glob
import io
import json
import os
import sys

try:                                      # ★日本語Windowsの出口(cp932)で文字化けさせない
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHANGE_LOG = os.path.join(REPO, "local", "llm", "change_log.jsonl")
FCC_LOG_DIR = os.path.join(os.path.expanduser("~"), ".fcc", "logs")

# ★server.log の1行が「上流へ実際に投げた」印。title生成のスキップ等は数えない。
_UPSTREAM = "/v1/chat/completions"


def _parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def tasks(since):
    """fcc_task.py 経由で実際に載せた仕事。"""
    out = []
    if not os.path.exists(CHANGE_LOG):
        return out
    with io.open(CHANGE_LOG, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue  # 壊れ行は黙って飛ばす(数を盛らない)
            if r.get("fcc") is not True:
                continue
            ts = _parse_ts(r.get("ts"))
            if since and ts and ts < since:
                continue
            out.append((ts, r.get("dept"), r.get("何", "")))
    return out


def upstream(since):
    """Provider へ実際に投げた要求。戻り= (件数, 最終時刻)。"""
    n = 0
    last = None
    for path in sorted(glob.glob(os.path.join(FCC_LOG_DIR, "server.log*"))):
        with io.open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                if _UPSTREAM not in ln:
                    continue
                try:
                    ts = _parse_ts(json.loads(ln).get("time"))
                except Exception:
                    ts = None
                if since and ts and ts < since:
                    continue
                n += 1
                if ts and (last is None or ts > last):
                    last = ts
    return n, last


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--days", type=int, default=0, help="直近N日だけ数える(既定=全期間)")
    a = ap.parse_args(argv)

    since = None
    if a.days > 0:
        since = datetime.datetime.now().astimezone() - datetime.timedelta(days=a.days)

    label = "全期間" if since is None else "直近%d日" % a.days
    ts_list = tasks(since)
    n_up, last_up = upstream(since)

    print("== FCC 実務投入の実測(%s) ==" % label)
    print("①載せた仕事(fcc_task.py 経由) = %d 件" % len(ts_list))
    for ts, dept, nani in ts_list[-10:]:
        print("   %s  %s  %s" % (str(ts)[:19], dept, str(nani)[:70]))
    print("②上流へ流した要求(server.log) = %d 件 / 最終 %s"
          % (n_up, str(last_up)[:19] if last_up else "(無し)"))

    if not os.path.isdir(FCC_LOG_DIR):
        print("→ ★ログ置場が無い(%s)。FCCは一度も立っていない。" % FCC_LOG_DIR)
    elif len(ts_list) == 0 and n_up > 0:
        print("→ ★**据え付けは動いたが、実務は1件も載っていない。**"
              "②だけ在って①が0= 走ったのは検証便であって仕事ではない。節約は0。")
    elif len(ts_list) == 0:
        print("→ ★**実務0件。**節約は0。")
    else:
        print("→ 実務に載っている。①の内訳を見て、どの部門が使っているかを確かめろ。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
