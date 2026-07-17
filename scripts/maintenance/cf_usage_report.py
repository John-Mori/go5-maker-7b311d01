#!/usr/bin/env python3
"""Cloudflare Workers の日次リクエスト数を取得してDiscordへ1行で報告する(B-4)。

なぜ要るか(2026-07-16の実体験):
  無料枠10万req/日の超過を **超過メールで知った**。しかも真犯人(go5-sync 159k/日)は
  Chamiがダッシュボードのスクショを送ってくれるまで特定できず、こちらの初回診断は外れていた。
  =「見えない系は必ず焼ける」(設計原則P-3)。修正後も「効いたかはChamiが手で見る」ままだった。
  → 毎朝1行、Worker別の実測を自動で出す。8万/日を超えたら警告する。

前提(Chamiの手作業・1回だけ):
  local/cf_api_token.txt   … Cloudflare APIトークン(**Account Analytics:Read のみ**の最小権限)
  local/cf_account_id.txt  … アカウントID(ダッシュボードのURLに出る32桁)
  ※どちらも local/ (gitignore済) に置く。**チャットへ貼らない**・ログに出さない。
  ※未設定なら何もせず終了する(常駐を壊さない)。

使い方:
  python scripts/maintenance/cf_usage_report.py            # 前日分を取得しDiscordへ報告
  python scripts/maintenance/cf_usage_report.py --dry      # 送信せず結果だけ表示(設定確認用)
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
TOKEN_FILE = os.path.join(LOCAL, "cf_api_token.txt")
ACCT_FILE = os.path.join(LOCAL, "cf_account_id.txt")
GQL = "https://api.cloudflare.com/client/v4/graphql"

FREE_LIMIT = 100000      # 無料枠(req/日)
WARN_AT = 80000          # ここを超えたら警告(8万/日=黄信号・設計書の基準)


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def fetch_usage(token, account_id, day):
    """指定日(UTC)のWorker別リクエスト数を返す: [(script_name, requests), ...]"""
    query = """
    query($acct: String!, $start: Date!, $end: Date!) {
      viewer {
        accounts(filter: {accountTag: $acct}) {
          workersInvocationsAdaptive(limit: 100, filter: {date_geq: $start, date_leq: $end}) {
            sum { requests }
            dimensions { scriptName }
          }
        }
      }
    }"""
    body = json.dumps({"query": query, "variables": {"acct": account_id, "start": day, "end": day}}).encode("utf-8")
    req = urllib.request.Request(
        GQL, data=body,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "User-Agent": "go5-cf-usage (personal, v1)"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode("utf-8"))
    if j.get("errors"):
        # トークン/権限の誤りはここに出る。**エラー本文に秘密は含めない**(メッセージのみ)
        msgs = "; ".join(str(e.get("message", "")) for e in j["errors"])
        raise RuntimeError("Cloudflare API: " + msgs)
    accts = (((j.get("data") or {}).get("viewer") or {}).get("accounts") or [])
    if not accts:
        return []
    rows = accts[0].get("workersInvocationsAdaptive") or []
    out = []
    for r_ in rows:
        name = ((r_.get("dimensions") or {}).get("scriptName")) or "?"
        n = ((r_.get("sum") or {}).get("requests")) or 0
        out.append((name, int(n)))
    out.sort(key=lambda x: -x[1])
    return out


def fmt(n):
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def build_line(day, rows):
    total = sum(n for _, n in rows)
    parts = " / ".join(f"{name} {fmt(n)}" for name, n in rows if n > 0) or "(呼び出しなし)"
    head = f"☁️ Cloudflare {day}: {parts}　計 {fmt(total)} / 枠 {fmt(FREE_LIMIT)}"
    if total >= FREE_LIMIT:
        return head + "\n🚨 **上限超過**。Workerが停止した可能性がある。改修αへ調査を回してくれ。"
    if total >= WARN_AT:
        return head + f"\n⚠️ **黄信号**({fmt(WARN_AT)}/日超)。このペースだと上限に届く。原因の特定を。"
    return head


def send(text):
    p = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
         "--dept", "system-engineer", "--persona", "花海咲季", text],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode == 0


def main():
    dry = "--dry" in sys.argv
    token, acct = read(TOKEN_FILE), read(ACCT_FILE)
    if not token or not acct:
        # 未設定は正常系。常駐を壊さず静かに終わる(Chamiがトークンを置いたら自動で動き出す)
        print("CFトークン/アカウントIDが未設定のためスキップ(local/cf_api_token.txt, local/cf_account_id.txt)")
        return 0
    day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")  # 前日(UTC)=枠のリセット単位
    try:
        rows = fetch_usage(token, acct, day)
    except Exception as e:
        msg = f"☁️ Cloudflare使用量を取得できなかった({type(e).__name__}: {e})。トークンの権限(Account Analytics:Read)を確認して。"
        print(msg)
        if not dry:
            send(msg)
        return 1
    line = build_line(day, rows)
    print(line)
    if dry:
        print("(--dry のため送信しない)")
        return 0
    return 0 if send(line) else 1


if __name__ == "__main__":
    sys.exit(main())
