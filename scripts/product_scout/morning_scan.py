#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""毎朝の採算速報 (product-scout・裁定4・Chami依頼2026-07-18「ちゃんと毎朝欲しい/実装go」)。

市場全体巡回(Worker cron・毎朝06:00 JSTにD1 market_snapshotへ保存)は既に本番稼働済み。
このスクリプトは保存済みデータを読むだけ(D1はSELECT=読み取りのみ・書き込みは一切行わない)。
採算予選(docs/departments/product-scout/selection-rules.md 準拠:
discount_pct>=40 かつ review_count>=30 かつ review_avg>=4.4)を review_count 降順で最大3件抽出し、
通過が1件以上あればクラウディア名義で product-scout チャンネルへ自動投稿する。
予選通過がゼロの日は何も投稿しない(ノイズゼロ設計=selection-rules.md「予選通過ゼロの日は提案を出さない」)。

使い方:
  python scripts/product_scout/morning_scan.py            # 本番(予選通過があれば投稿)
  python scripts/product_scout/morning_scan.py --dry-run  # 投稿せず抽出結果を表示するだけ(マーカーも書かない)

冪等性: local/product_scout_morning_last.txt に最後に投稿した日付(YYYY-MM-DD)を記録する。
同じ日付ならタスクの二度発火・窓側スキャンとの重複があっても再投稿しない。--dry-run 時はマーカーを書かない。
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
WORKER_DIR = os.path.normpath(os.path.join(ROOT, "fanza-worker"))
MARKER = os.path.join(LOCAL, "product_scout_morning_last.txt")
BODY_FILE = os.path.join(LOCAL, "_product_scout_morning_body.txt")

JST = timezone(timedelta(hours=9))

# 採算予選の閾値(selection-rules.md「定期スキャン」節 準拠・暫定値=較正対象)
MIN_DISCOUNT_PCT = 40
MIN_REVIEW_COUNT = 30
MIN_REVIEW_AVG = 4.4
TOP_N = 3


def today_jst():
    return datetime.now(JST).strftime("%Y-%m-%d")


def fetch_snapshot(day):
    """当日分の market_snapshot を wrangler D1 SELECT(読み取りのみ)で取得する。失敗時は None。"""
    sql = (
        "SELECT cid,title,price,list_price,discount_pct,review_count,review_avg,rank "
        f"FROM market_snapshot WHERE day='{day}'"
    )
    cmd = f'npx wrangler d1 execute go5_fanza --remote --json --command "{sql}"'
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            cwd=WORKER_DIR, shell=True, timeout=120)
    except Exception as e:
        # subprocessのstderrをそのまま垂れ流さない(秘密混入対策)。種別のみ1行で報告する。
        print(f"wrangler呼び出しに失敗しました({type(e).__name__})")
        return None
    if r.returncode != 0:
        print("wrangler呼び出しに失敗しました(returncode!=0)")
        return None
    out = r.stdout or ""
    start = out.find("[")
    if start < 0:
        print("wrangler出力の解析に失敗しました(JSON配列が見つかりません)")
        return None
    try:
        data = json.loads(out[start:])
        return data[0].get("results", [])
    except Exception:
        print("wrangler出力の解析に失敗しました(JSONパースエラー)")
        return None


def select_top(rows):
    """採算予選: discount_pct>=40 かつ review_count>=30 かつ review_avg>=4.4。review_count降順で上位TOP_N件。"""
    qualified = []
    for row in rows:
        discount_pct = row.get("discount_pct")
        review_count = row.get("review_count")
        review_avg = row.get("review_avg")
        if discount_pct is None or review_count is None or review_avg is None:
            continue
        if discount_pct >= MIN_DISCOUNT_PCT and review_count >= MIN_REVIEW_COUNT and review_avg >= MIN_REVIEW_AVG:
            qualified.append(row)
    qualified.sort(key=lambda r: r.get("review_count") or 0, reverse=True)
    return qualified[:TOP_N]


def short_title(title, limit=24):
    title = (title or "").strip()
    return title if len(title) <= limit else title[:limit] + "…"


def fmt_yen(v):
    return f"¥{v:,}" if isinstance(v, (int, float)) else "?"


def fmt_avg(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else str(v)


def build_body(day, picks):
    lines = [f"今朝の市場・採算速報(自動) {day}"]
    for row in picks:
        cid = row.get("cid") or "?"
        title = short_title(row.get("title"))
        discount_pct = row.get("discount_pct")
        review_count = row.get("review_count")
        rank = row.get("rank")
        rank_s = str(rank) if rank is not None else "-"
        lines.append(
            f"- {cid} / {title} / {fmt_yen(row.get('price'))}"
            f"(定価{fmt_yen(row.get('list_price'))}・{discount_pct}%OFF)"
            f" / レビュー{review_count}件×{fmt_avg(row.get('review_avg'))} / rank{rank_s}"
        )
    lines.append("これは採算面だけの速報。素材(1コマ目の停止力・電車内基準)は窓が開いた時にA-E最終判定")
    return "\n".join(lines)


def already_posted(day):
    if not os.path.exists(MARKER):
        return False
    try:
        with open(MARKER, "r", encoding="utf-8") as f:
            return f.read().strip() == day
    except Exception:
        return False


def mark_posted(day):
    with open(MARKER, "w", encoding="utf-8") as f:
        f.write(day)


def post(body):
    with open(BODY_FILE, "w", encoding="utf-8") as f:
        f.write(body)
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
             "--dept", "product-scout", "--persona", "クラウディア", "--body-file", BODY_FILE],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        print(f"Discord投稿の呼び出しに失敗しました({type(e).__name__})")
        return False
    print(r.stdout.strip())
    if r.returncode != 0:
        print("Discord投稿に失敗しました")
        return False
    return True


def main():
    dry_run = "--dry-run" in sys.argv
    day = today_jst()

    if not dry_run and already_posted(day):
        print(f"{day} は投稿済み(二重投稿防止・{MARKER})")
        return 0

    rows = fetch_snapshot(day)
    if rows is None:
        return 1  # 失敗は1行報告済み・部分投稿なしで終了
    if not rows:
        print(f"{day} の market_snapshot は0件です。")
        return 0

    picks = select_top(rows)
    if not picks:
        print(f"{day}: 採算予選(discount_pct>={MIN_DISCOUNT_PCT} review_count>={MIN_REVIEW_COUNT} "
              f"review_avg>={MIN_REVIEW_AVG})の通過0件。投稿なし。")
        return 0

    body = build_body(day, picks)
    if dry_run:
        print(body)
        return 0

    ok = post(body)
    if ok:
        mark_posted(day)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
