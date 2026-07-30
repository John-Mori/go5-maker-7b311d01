#!/usr/bin/env python3
"""毎日0時の自己振り返りトリガー — future-room(現在と未来)を起こして当日分を1件出させる配線。

なぜ要るか(2026-07-30 アメスの証拠つき再依頼 / DISPATCH-aegis-gl-1785336943411 の実体化):
  「Chamiの性格・言動への率直な自己振り返り」は future-room(アメス)の職務。だが**0時に部屋を
  起こす仕掛けが無かった**ため一度も自動生成されていなかった(local/llm/daily_reflection/ に
  手動作成分しか無い=偽受領)。既存の go5_daily_report_0000 は「日報」であって振り返りではない
  (別物)。reflect.py は「方針変更検出バッチ」でこれも別物。→ ここが唯一の欠けていた配線。

責任範囲(platform-se/aegis-gl=基盤・常駐構成・C-015):
  **0時に future-room を起こして振り返りを1件出させる、そこまで。**
  生成の中身(率直な他者視点)はアメスの職務なので**書かない**。この便は「今日の分を書いて
  保存して返して」と頼むだけ。future-room は生きたデーモン(session_relay)なので、この便を
  キューから消費し、永続セッションが振り返りを生成→ファイル保存→返信(=現在と未来へ自動投稿)する。

なぜ「配って終わり」で消えないか:
  便は local/queue/inbox.db(LeaseQueue)に載る=**future-room が処理するまで残る**。0時に部屋が
  取り込み中でも便は消えず、空いた時に処理される。これが「トリガーが無い(=何も起きない)」
  状態との決定的な差。トリガー自体は Windows タスクで定刻に確実に発火する。

冪等:
  当日分 local/llm/daily_reflection/YYYY-MM-DD.md が既に在れば投函しない(二重投稿を防ぐ)。
  --force で上書き再依頼。

使い方:
  python scripts/llm/daily_reflection_trigger.py --dry-run   # 便の中身を印字するだけ(投函しない)
  python scripts/llm/daily_reflection_trigger.py             # future-room へ実際に投函(0時タスクが呼ぶ)
  python scripts/llm/daily_reflection_trigger.py --force     # 当日分が在っても再依頼
"""
import argparse
import datetime as dt
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
REFLECT_DIR = os.path.join(ROOT, "local", "llm", "daily_reflection")

JST = dt.timezone(dt.timedelta(hours=9))
SENDER = "定刻トリガー(0時)"
TARGET_DEPT = "future-room"


def today_str():
    return dt.datetime.now(JST).strftime("%Y-%m-%d")


def reflection_path(day):
    return os.path.join(REFLECT_DIR, f"{day}.md")


def build_body(day):
    """future-room(アメス)へ渡す依頼本文。中身の作法は部屋の boot_note と前日分に委ねる=
    ここでは「何を・どこへ保存して・どう返すか」の配線だけを指示する(生成はアメスの職務)。"""
    rel = f"local/llm/daily_reflection/{day}.md"
    return (
        f"【定刻・0時の自己振り返り(自動)】\n"
        f"今日({day}・JST)分の「Chamiの性格・言動への率直な自己振り返り」を1件、書いてください。\n"
        f"- 慰めでなく率直な他者視点で(当たり障りのない返しはこの部屋の失敗)。ぼかさない(C-013)。\n"
        f"- 材料= 今日Chamiが実際にやった言動(各部屋のログ・ames_shared.jsonl・便)。推測は書かない。\n"
        f"- 書式は前日分に倣う(local/llm/daily_reflection/ の直近ファイル)。\n"
        f"- ★書き上げたら {rel} に保存してから、本文をこの部屋へ返してください"
        f"(あなたの返信がそのまま現在と未来へ投稿されます)。\n"
        f"- ネットへ出さない(local/ の中だけで完結)。"
    )


def main():
    ap = argparse.ArgumentParser(description="0時の自己振り返りトリガー(future-roomを起こす)")
    ap.add_argument("--dry-run", action="store_true", help="投函せず便の中身を印字する")
    ap.add_argument("--force", action="store_true", help="当日分が既に在っても再依頼する")
    a = ap.parse_args()

    day = today_str()
    path = reflection_path(day)
    body = build_body(day)

    if os.path.exists(path) and not a.force and not a.dry_run:
        print(f"[skip] 当日分は既に在る: {path}(--force で再依頼)")
        return 0

    sys.path.insert(0, HERE)
    import dispatch  # noqa: E402  同じ scripts/llm 配下

    ok, mid = dispatch.dispatch(TARGET_DEPT, SENDER, body, dry_run=a.dry_run)
    if a.dry_run:
        print("---- 便本文(dry-run) ----")
        print(body)
        return 0
    if ok:
        print(f"[ok] future-room(現在と未来)へ 0時の振り返り依頼を投函 msg={mid} day={day}")
        return 0
    print(f"[fail] 投函できなかった day={day}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
