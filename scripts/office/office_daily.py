#!/usr/bin/env python3
"""AIオフィス 配達係(常駐): 定期的にオフィスを再生成し、1日1回サマリをDiscordへ送る。

設計: docs/設計・調査/AIオフィス_部屋型_改善書_v1.md K-3(配線) / Chami裁定2026-07-17=「Discordに日次サマリ配達」

なぜ要るか(NEW-2): これまでオフィスは **再生成する係も、Chamiの目に届ける経路も居なかった**。
  だから3日前の画面が置きっぱなしになっていた。ChamiはDiscord中心の運用なので、
  「新鮮なHTMLをPCで待つ」のではなく **サマリの方からDiscordへ出向く** のが実動線に合う。

やること:
  ①REBUILD_MIN毎に build_office.py を実行(=Chamiが開いた時に常に新しい)
  ②JSTのSEND_HOUR台に入ったら、その日のサマリを1回だけ report-notify chへ送る
    送り主=メタルギアMk.II(機械的アナウンスの担当・Chami指定2026-07-14)

常駐の作法: scripts/_daemons/supervise_daemons.ps1 が1インスタンスだけ維持・自動復旧する
  (可視bat/pauseに戻さない=go5_daemons_hidden)。ポーラー等と同じく**監視付きの無限ループ**。
  ※heartbeat.pyの「終了条件のない無限ループ禁止」は**生存信号**の話。ここは脈を打たないので対象外。

手動実行: python scripts/office/office_daily.py --once   (今すぐ1回だけ生成して送る=動作確認用)
"""
import argparse
import datetime
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_office as bo  # noqa: E402
from office_core import esc, is_jst_today, jst_str, normalize_dept, to_jst  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = bo.ROOT
LOCAL = bo.LOCAL
STATE = os.path.join(LOCAL, "office", "_last_daily.txt")   # 送信済みのJST日付(重複配達の防止)
SCRATCH = os.path.join(LOCAL, "office", "_summary.txt")     # 本文(--body-file経由=長文の化け防止)

REBUILD_MIN = 30          # 再生成の間隔(分)
SEND_HOUR_JST = 9         # 日次サマリを送るJSTの時刻(この時以降で最初のパス)
TICK_SEC = 60
SEND_DEPT = "report-notify"
SEND_PERSONA = "メタルギアMk.II"


def build(open_it=False):
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "office", "build_office.py")]
    if open_it:
        cmd.append("--open")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        return r.returncode, (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"再生成に失敗: {e}"


def compose():
    """サマリ本文をオフィスと同じ実データから組む(表示とサマリの二重実装をしない)。"""
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    now_ep = time.time()
    ok, d1, err = bo.fetch_d1(bo.D1_QUERIES)
    tasks = d1.get("tasks", [])
    L = [f"📊 AIオフィス日次サマリ ({to_jst(now).strftime('%m/%d')} JST)"]

    if not ok:
        L.append(f"⚠ D1取得失敗のためタスク系は不明: {err[:120]}")
    else:
        done = [t for t in tasks if is_jst_today(t.get("completed_at"), now)]
        opens = [t for t in tasks if t.get("status") in ("open", "in_progress")]
        chg = [c for c in d1.get("changes", []) if is_jst_today(c.get("created_at"), now)]
        L.append(f"未完了 {len(opens)}件 / 本日完了 {len(done)}件 / 本日のCHG {len(chg)}件")
        pend = [r for r in d1.get("reqs", []) if str(r.get("status")) in ("proposed", "approved")]
        blocked = [t for t in tasks if t.get("status") == "blocked"]
        if pend or blocked:
            L.append(f"👑 Chami待ち: 承認待ち{len(pend)}件 / 承認ブロック{len(blocked)}件")
            for r in pend[:3]:
                L.append(f"  ・{r.get('req_code')} [{r.get('status')}] {esc(r.get('problem'), 40)}")
            for t in blocked[:3]:
                L.append(f"  ・🛑 {t.get('assigned_dept')} {esc(t.get('summary'), 40)}")
        else:
            L.append("👑 Chami待ち: なし")
        if done:
            L.append("✅ 本日の完了:")
            for t in done[:5]:
                L.append(f"  ・{esc(t.get('result') or t.get('summary'), 50)}")

    pres = bo.load_presence(now_ep)
    active = [d for d, v in pres.items() if v[0] == "active"]
    L.append(f"🪟 在席: {len(active)}窓" + (f" ({', '.join(sorted(active)[:6])})" if active else ""))

    inbox = bo.load_inbox_counts()
    if inbox:
        L.append("📬 配達済み未処理: " + " / ".join(f"{k}:{v}" for k, v in sorted(inbox.items())))

    dmn, _ = bo.load_daemons()
    bad = [n for n, s in dmn if s != "ok"]
    L.append(f"⚙ 機械室: 常駐{len(dmn)}匹" + ("・全部ok" if dmn and not bad else f"・要注意={','.join(bad)}" if bad else "・ログなし"))

    inc = bo.load_latest_incident()
    if inc:
        L.append(f"🚨 最新: INC-{inc[0]} ({inc[1]}) {esc(inc[2], 44)}")

    git = bo.load_git_log(3)
    if git:
        L.append("🔧 直近の変更:")
        for g in git:
            L.append(f"  ・{jst_str(g['ts'])} {esc(g['subject'], 46)}")

    L.append("")
    L.append("画面で見る: python scripts/office/build_office.py --open (部屋・立ち絵・タイムライン付き)")
    return "\n".join(L)


def send(body):
    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    with open(SCRATCH, "w", encoding="utf-8") as f:
        f.write(body)
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
           "--dept", SEND_DEPT, "--persona", SEND_PERSONA, "--body-file", SCRATCH]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"送信失敗: {e}")
        return False
    out = (r.stdout or "") + (r.stderr or "")
    okd = r.returncode == 0 and "204" in out          # HTTP 204を確認するまで「送った」と言わない
    print(("送信OK: " if okd else "送信失敗: ") + out.strip()[:160])
    return okd


def already_sent_today(now):
    return open(STATE, encoding="utf-8").read().strip() == to_jst(now).strftime("%Y-%m-%d") \
        if os.path.exists(STATE) else False


def mark_sent(now):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        f.write(to_jst(now).strftime("%Y-%m-%d"))


def main():
    ap = argparse.ArgumentParser(description="AIオフィス配達係")
    ap.add_argument("--once", action="store_true", help="今すぐ1回だけ生成して送る(動作確認)")
    ap.add_argument("--dry-run", action="store_true", help="送らずに本文だけ出す")
    args = ap.parse_args()

    if args.dry_run:
        print(compose())
        return 0
    if args.once:
        code, out = build()
        print(out)
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        okd = send(compose())
        if okd:
            mark_sent(now)
        return 0 if okd else 1

    print(f"office_daily開始: {REBUILD_MIN}分毎に再生成 / JST{SEND_HOUR_JST}時台に日次サマリ→{SEND_DEPT}")
    last_build = 0.0
    while True:                                        # 監視付き常駐(supervise_daemons.ps1が1個だけ維持)
        try:
            now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            if time.time() - last_build >= REBUILD_MIN * 60:
                code, out = build()
                last_build = time.time()
                print(f"[{jst_str(now)}] 再生成(code={code}) {out.splitlines()[0] if out else ''}")
            if to_jst(now).hour >= SEND_HOUR_JST and not already_sent_today(now):
                if send(compose()):
                    mark_sent(now)
        except Exception as e:                         # 常駐は1回の失敗で死なない(次のtickで再挑戦)
            print(f"tickで例外(継続する): {e}")
        time.sleep(TICK_SEC)


if __name__ == "__main__":
    sys.exit(main())
