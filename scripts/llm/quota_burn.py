#!/usr/bin/env python3
"""quota_burn — **週の使用量(課金枠)の燃焼率**を測る。読むだけ・何も変更しない。

★なぜ要るか(2026-08-23 研究室HQ msg 1540936153224581215)
  Chamiがスマホの「使用状況」画面を見て **「使用量やばいことなってるって」** と持ってきた。
  実測= 週の 20.3% しか経っていない時点で **46% 使用済み**(= 持続可能な速さの 2.26倍)。
  **機械は一度も鳴っていない。** 既存の計器はどれも別の物を見ていた:
    - `context_watch.py`      = 1セッションの**文脈の大きさ**(圧縮/交代の線)
    - `context_budget.py`     = 人物コンテキストの**ファイル容量**(manifest 8KB / detail 48KB)
  どちらも「**組織全体が週の枠をどれだけ食ったか**」を見ていない。
  = 気づけるのはChamiのスマホだけ、という状態だった。ここを塞ぐのがこの計器。

★何を数えるか
  transcript(`~/.claude/projects/**/*.jsonl`)の `usage` を、**週のリセット以降**だけ集める。
  Claude Code 自身が記録した実測値であって推定ではない。

★★何を数えていないか(誤読を防ぐために先に書く)
  ここが出す「%」は **Anthropic の使用状況画面の % そのものではない**。
  向こうの重み付けは公開されていない。ここは下の `W_*` / `MODEL_W` という
  **こちらの仮定**で重みを付けた**順位と傾き**を見るための物差しだ。
  → **「どこが食っているか」「速すぎるか」には使える。「あと何%」には使うな。**
     残量の正は**Chamiのスマホの画面**(または /usage)。この計器はそれを**説明する**側。

使い方:
  python scripts/llm/quota_burn.py                    # 週(直前のリセット以降)の内訳
  python scripts/llm/quota_burn.py --used 46          # 画面の実測%を渡すと燃焼率と枯渇時刻を出す
  python scripts/llm/quota_burn.py --hours 6          # 直近6時間だけ(山を切り出す)
  python scripts/llm/quota_burn.py --by hour          # 時間帯別(定刻トリガーの山を見る)
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LOCAL = os.path.join(ROOT, "local")
PROJECTS = os.path.expanduser(r"~\.claude\projects")

# ★週のリセット= 土 03:00 JST(Chamiの画面「リセット: 土 3:00」2026-08-23 実測)
RESET_WEEKDAY = 5          # 月=0 … 土=5
RESET_HOUR = 3

# 重み(仮定。cache読みは安く、出力は高い、という定性を数にしただけ)
W_IN, W_CACHE_CREATE, W_CACHE_READ, W_OUT = 1.0, 1.25, 0.1, 5.0
MODEL_W = {"opus": 5.0, "fable": 5.0, "sonnet": 1.0, "haiku": 0.27}

RE_TS = re.compile(r'"timestamp":"([0-9T:\-\.]+)Z?"')
RE_MODEL = re.compile(r'"model":"([^"]+)"')
RE_IN = re.compile(r'"input_tokens":(\d+)')
RE_CC = re.compile(r'"cache_creation_input_tokens":(\d+)')
RE_CR = re.compile(r'"cache_read_input_tokens":(\d+)')
RE_OUT = re.compile(r'"output_tokens":(\d+)')


def model_weight(model):
    m = (model or "").lower()
    for k, v in MODEL_W.items():
        if k in m:
            return v
    return 1.0                      # 知らないモデルは Sonnet 相当へ倒す(盛らない側)


def last_reset(now=None):
    """直前の「土 03:00 JST」を返す。"""
    now = now or datetime.now(JST)
    d = now
    while True:
        cand = d.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)
        if d.weekday() == RESET_WEEKDAY and cand <= now:
            return cand
        d -= timedelta(days=1)


def dept_map():
    """sid(先頭8桁) → 部門。`context_watch.jsonl` の**全履歴**から引く。

    ★`room_sessions.json` は**現行世代しか**持たないので、旧世代が全部「不明」に落ちる
      (初版で実際にそうなり、44.5%が「?」になった)。見張りの台帳は過去の世代も
      名前つきで残しているので、そちらを正にする。
    """
    m = {}
    p = os.path.join(LOCAL, "llm", "context_watch.jsonl")
    if not os.path.exists(p):
        return m
    with open(p, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            for s in rec.get("sessions", []):
                d, sid = s.get("dept") or "", s.get("sid")
                if sid and d and d != "手動セッション等":
                    m[sid] = d
    return m


def collect(since_utc):
    """since 以降の usage を (sid, model, 時刻) 単位で集める。"""
    rows = []
    if not os.path.isdir(PROJECTS):
        return rows
    for path in glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True):
        sid = os.path.basename(path)[:8]
        try:
            f = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with f:
            for line in f:
                if '"usage"' not in line:
                    continue
                mts = RE_TS.search(line)
                if not mts:
                    continue
                try:
                    dt = datetime.fromisoformat(mts.group(1)).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if dt < since_utc:
                    continue
                model = (RE_MODEL.search(line) or [None, "?"])[1] if RE_MODEL.search(line) else "?"
                if model == "<synthetic>":      # 実際にモデルへ行っていない行
                    continue
                def n(rx):
                    mm = rx.search(line)
                    return int(mm.group(1)) if mm else 0
                rows.append((sid, model, dt, n(RE_IN), n(RE_CC), n(RE_CR), n(RE_OUT)))
    return rows


def weighted(r):
    return (r[3] * W_IN + r[4] * W_CACHE_CREATE + r[5] * W_CACHE_READ
            + r[6] * W_OUT) * model_weight(r[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--used", type=float, default=None,
                    help="使用状況画面の『すべてのモデル』の%%(これを渡すと燃焼率と枯渇時刻を出す)")
    ap.add_argument("--hours", type=float, default=None, help="週でなく直近N時間で切る")
    ap.add_argument("--by", choices=("dept", "hour", "model", "session"), default="dept")
    ap.add_argument("--top", type=int, default=20)
    # ★2026-08-23 研究室HQ追加(②=workだけSonnet の受け入れ判定のため)
    #   組織全体の sonnet便数は「その日どの部屋が動いたか」で勝手に動く= 曜日が違えば比較にならない。
    #   ②が効いたかは **名指しした部屋の中でモデルの内訳がどう変わったか** で見るのが正しい。
    #   → `--dept hq,system-engineer,platform-se --by model` で組成に依らない割合が出る。
    ap.add_argument("--dept", default=None,
                    help="部門で絞る(カンマ区切りのslug)。--by model と併せると『その部屋の中でどのモデルが動いたか』")
    ap.add_argument("--model", default=None,
                    help="モデルで絞る(部分一致。例 sonnet)。--by dept と併せると『どの部屋がそのモデルを動かしたか』")
    ap.add_argument("--ago", type=float, default=0.0,
                    help="窓の右端をN時間前へずらす(--hours と併用)。過去の同じ長さ・同じ時刻帯の窓を後から取り直す")
    a = ap.parse_args()

    now = datetime.now(JST)
    end = now - timedelta(hours=a.ago) if a.ago else now
    if a.hours:
        start = end - timedelta(hours=a.hours)
        label = "直近 %g 時間" % a.hours
    else:
        start = last_reset(now)
        label = "週(リセット %s(%s) 03:00 以降)" % (
            start.strftime("%m/%d"), "月火水木金土日"[start.weekday()])
    if a.ago:
        label = "%s 〜 %s JST(%s)" % (
            start.strftime("%m/%d %H:%M"), end.strftime("%m/%d %H:%M"),
            "月火水木金土日"[start.weekday()])
    rows = collect(start.astimezone(timezone.utc))
    if a.ago:                                   # 右端で切る(collect は左端しか見ない)
        e_utc = end.astimezone(timezone.utc)
        rows = [r for r in rows if r[2] <= e_utc]

    # 部門は「絞る時」にも要る= --by dept 以外でも引く
    dmap = dept_map() if (a.by == "dept" or a.dept) else {}
    if a.dept:
        want = {s.strip() for s in a.dept.split(",") if s.strip()}
        rows = [r for r in rows if dmap.get(r[0], "手動/不明") in want]
        label += " / 部門= " + ",".join(sorted(want))
    if a.model:
        rows = [r for r in rows if a.model.lower() in (r[1] or "").lower()]
        label += " / モデル= " + a.model

    print("== 使用量の燃焼 / %s / いま %s JST ==" % (label, now.strftime("%m/%d %H:%M")))
    if not rows:
        print("この窓に便が無い")
        return
    tot_w = sum(weighted(r) for r in rows)
    n = len(rows)
    s_in = sum(r[3] for r in rows); s_cc = sum(r[4] for r in rows)
    s_cr = sum(r[5] for r in rows); s_out = sum(r[6] for r in rows)
    ctx = s_in + s_cc + s_cr
    print("便数= {:,} / 入力= {:,} / cache作成= {:,} / cache読み= {:,} / 出力= {:,}".format(
        n, s_in, s_cc, s_cr, s_out))
    print("1便あたりの文脈= {:,}(うち cache読みが {:.1f}% = 毎便おなじ文脈を読み直している)".format(
        int(ctx / n), s_cr / ctx * 100 if ctx else 0))

    # ★ここだけが「速さ」の話。画面の実測%を渡された時にしか言わない(推測で埋めない)
    if a.used is not None and not a.hours:
        nxt = start + timedelta(days=7)
        el = (now - start).total_seconds() / 3600.0
        span = (nxt - start).total_seconds() / 3600.0
        pace = (a.used / (el / span * 100.0)) if el > 0 else 0
        rate = a.used / el if el > 0 else 0
        print()
        print("週の経過= %.1f/%.0f時間(%.1f%%) / 使用= %.1f%% → **時間比の %.2f倍**"
              % (el, span, el / span * 100, a.used, pace))
        if rate > 0:
            eta = now + timedelta(hours=(100 - a.used) / rate)
            print("燃焼= %.2f%%/時 → 100%%到達 %s / 次のリセットは %s"
                  % (rate, eta.strftime("%m/%d %H:%M"), nxt.strftime("%m/%d %H:%M")))
            if eta < nxt:
                print("★★このままだと **%s から %s まで %.1f日** 枠切れで止まる"
                      % (eta.strftime("%m/%d %H:%M"), nxt.strftime("%m/%d %H:%M"),
                         (nxt - eta).total_seconds() / 86400))
            sustain = (100 - a.used) / ((nxt - now).total_seconds() / 3600.0)
            print("持続可能な速さ= %.2f%%/時(= いまの 1/%.1f に落とす)" % (sustain, rate / sustain))

    print()
    print("★シェアは「重み付き換算」= 入力%.1f / cache作成%.2f / cache読み%.1f / 出力%.1f × モデル係数"
          % (W_IN, W_CACHE_CREATE, W_CACHE_READ, W_OUT))
    print("★これはAnthropicの割合の出し方ではない= **順位を見る物差し**。残量の正はChamiの画面。")
    print()

    if a.by == "hour":
        agg = collections.OrderedDict()
        for r in sorted(rows, key=lambda x: x[2]):
            k = r[2].astimezone(JST).strftime("%m/%d %H時")
            v = agg.setdefault(k, [0.0, 0, 0])
            v[0] += weighted(r); v[1] += 1; v[2] += r[5]
        print("%-12s %6s %8s %14s" % ("時間帯", "シェア", "便数", "cache読み(百万)"))
        for k, (w, c, cr) in agg.items():
            print("%-12s %5.1f%% %8d %14.1f" % (k, w / tot_w * 100, c, cr / 1e6))
        return

    keyf = {"dept": lambda r: dmap.get(r[0], "手動/不明"),
            "model": lambda r: r[1],
            "session": lambda r: r[0]}[a.by]
    agg = {}
    for r in rows:
        v = agg.setdefault(keyf(r), [0.0, 0, 0, 0])
        v[0] += weighted(r); v[1] += 1; v[2] += r[5]; v[3] += r[6]
    head = {"dept": "部門", "model": "モデル", "session": "session"}[a.by]
    print("%6s  %-26s %6s %16s %12s %11s" % ("シェア", head, "便数", "cache読み", "出力", "1便平均"))
    for k, (w, c, cr, out) in sorted(agg.items(), key=lambda x: -x[1][0])[:a.top]:
        print("%5.1f%%  %-26s %6d %16s %12s %11s"
              % (w / tot_w * 100, str(k)[:26], c, "{:,}".format(cr),
                 "{:,}".format(out), "{:,}".format(int(cr / c)) if c else "-"))


if __name__ == "__main__":
    main()
