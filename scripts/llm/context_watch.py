# -*- coding: utf-8 -*-
"""context_watch — 生きているセッションの**文脈の大きさ**を、relayの管理外まで含めて測る。

なぜ要るか(2026-08-22・研究室HQ実依頼 msg 1540618940533841982):
  Chamiが週間制限98%まで行って3日間このシステムに触れなくなった。HQが消費を実測すると
  **71.2%が cache読み(=文脈の読み直し)**で、その中で1セッションだけ桁が違った。
  session_relay の管理下にある部門は 10〜12万台で回っているのに、**手で開かれた対話
  セッションには 120,000 の圧縮線も 185,000 の交代線も一切かからない**からだ。

★この道具が守る規則は2つ:
  ① 線は**絶対トークン数**で引く。モデルの文脈窓から導かない。
     (旧: 「Claude CLI が約167,000で自動圧縮する」を前提に線を置いていた。これは200K窓の
      実測値で、1M窓のモデルでは同じ線が約93万まで黙って上がる= 実測の最大 933,841 が
      その直前だった。**窓に依存する線は、窓が変わった日に無言で無効化される。**)
  ② 測る対象は relay の管理下だけでなく**生きている全セッション**。管理外こそ穴だ。

使い方:
  python scripts/llm/context_watch.py                     # 直近12時間に動いたセッション
  python scripts/llm/context_watch.py --hours 72 --out local/_ctx.txt
  python scripts/llm/context_watch.py --record            # local/llm/context_watch.jsonl へ1行
  python scripts/llm/context_watch.py --alert             # 線を越えた管理外セッションをHQへ通知

★読むだけ。セッションにも Discord にも書き込まない(--alert を付けた時だけキューへ1本出す)。
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
PROJECTS = os.path.join(os.path.expanduser("~"), ".claude", "projects")
JST = timezone(timedelta(hours=9))
STATE = os.path.join(LOCAL, "llm", "context_watch_state.json")
LEDGER = os.path.join(LOCAL, "llm", "context_watch.jsonl")
ALERT_COOLDOWN_SEC = 3600       # 同じセッションで鳴らし続けない(1時間に1回)

RE_TS = re.compile(r'"timestamp"\s*:\s*"([0-9T:\-\.]+)Z?"')
RE_MODEL = re.compile(r'"model"\s*:\s*"([^"]+)"')
RE_IN = re.compile(r'"input_tokens"\s*:\s*(\d+)')
RE_CC = re.compile(r'"cache_creation_input_tokens"\s*:\s*(\d+)')
RE_CR = re.compile(r'"cache_read_input_tokens"\s*:\s*(\d+)')
# ★部門の判定は **HQの usage_report.py と同じ見立て**を使う(新しい判定を作らない)。
RE_DEPT = re.compile(r'Discordの部屋\s*([a-z0-9\-_]+)')


def lines():
    """圧縮線と交代線は session_relay を**正本**として読む(2か所に数字を置かない)。

    ★読めない時だけ既定値へ倒す(fail-open)。その場合は表にその旨を出す。
    """
    sys.path.insert(0, HERE)
    try:
        import session_relay as sr
        return int(sr.COMPACT_AT_TOKENS), int(sr.ROTATE_AT_TOKENS), "session_relay"
    except Exception:
        return 120000, 185000, "既定値(session_relayを読めなかった)"


def managed_sessions():
    """relayが世代管理しているセッションID(=線が効いている側)。"""
    out = {}
    try:
        with open(os.path.join(LOCAL, "llm", "room_sessions.json"), encoding="utf-8") as f:
            for room, v in (json.load(f) or {}).items():
                sid = str((v or {}).get("active_session_id") or "")
                if sid:
                    out[sid] = room
    except Exception:
        pass
    return out


def classify(path):
    """起動文から「誰のセッションか」を判定する(usage_report.py と同じ規則)。"""
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return "?"
    with f:
        for i, line in enumerate(f):
            if i > 300:
                break
            if '"type":"user"' not in line:
                continue
            m = RE_DEPT.search(line)
            if m:
                return m.group(1)
            if "AI組織の「研究室」セッション" in line:
                return "研究室メイン"
    return "手動セッション等"


def scan(hours):
    """直近 hours に書き込みのあった transcript を読み、1便ごとの文脈の大きさを集める。

    ★文脈の大きさ= その便で実際にモデルへ送った input + cache読み + cache作成。
      Claude Code 自身が記録した usage の実測値であって推定ではない。
    """
    cutoff_mtime = time.time() - hours * 3600
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    if not os.path.isdir(PROJECTS):
        return rows
    for slug in os.listdir(PROJECTS):
        d = os.path.join(PROJECTS, slug)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".jsonl"):
                continue
            p = os.path.join(d, fn)
            try:
                if os.path.getmtime(p) < cutoff_mtime:
                    continue
            except OSError:
                continue
            ctxs, model, last_ts = [], "?", None
            try:
                f = open(p, encoding="utf-8", errors="replace")
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
                        dt = datetime.fromisoformat(mts.group(1)).replace(
                            tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if dt < since:
                        continue
                    mi = RE_IN.search(line)
                    if not mi:
                        continue
                    ctx = int(mi.group(1))
                    mcr, mcc = RE_CR.search(line), RE_CC.search(line)
                    ctx += int(mcr.group(1)) if mcr else 0
                    ctx += int(mcc.group(1)) if mcc else 0
                    if ctx <= 0:
                        continue
                    ctxs.append(ctx)
                    mm = RE_MODEL.search(line)
                    if mm:
                        model = mm.group(1)
                    last_ts = dt
            if not ctxs:
                continue
            rows.append({
                "sid": fn[:8], "path": p, "dept": classify(p), "model": model,
                "n": len(ctxs), "last": ctxs[-1],
                "median": int(statistics.median(ctxs)), "max": max(ctxs),
                "last_ts": last_ts.astimezone(JST).strftime("%m/%d %H:%M") if last_ts else "?",
            })
    return rows


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:
        pass


def alert(over, compact_at, rotate_at):
    """線を越えた**管理外**セッションを研究室HQへ1本出す(キューへ。Discordへは出さない)。

    ★鳴りっぱなしにしない= 同じセッションは ALERT_COOLDOWN_SEC の間は再送しない
      (常に誤発火する安全網は無視される=共通規律§3)。
    """
    st = _load_state()
    now = time.time()
    fresh = [r for r in over if now - float(st.get(r["sid"], 0) or 0) > ALERT_COOLDOWN_SEC]
    if not fresh:
        return 0
    body = ["【文脈の見張り】relayの管理外のセッションが線を越えている(絶対トークン数で判定)。",
            "線= 圧縮 %s / 交代 %s(session_relay が正本)" % (f"{compact_at:,}", f"{rotate_at:,}")]
    for r in fresh:
        body.append("  %s %s モデル=%s 便=%d 中央値=%s 最新=%s 最大=%s (最終 %s)"
                    % (r["sid"], r["dept"], r["model"], r["n"], f"{r['median']:,}",
                       f"{r['last']:,}", f"{r['max']:,}", r["last_ts"]))
    body.append("測り直し= python scripts/llm/context_watch.py --hours 12")
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "dispatch.py"),
                        "--dept", "hq", "--direct", "--from", "イージス研究室(文脈の見張り)",
                        "--body", "\n".join(body)], capture_output=True, timeout=60)
    except Exception:
        return 0
    for r in fresh:
        st[r["sid"]] = now
    _save_state(st)
    return len(fresh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=12.0)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--alert", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    compact_at, rotate_at, src = lines()
    mgd = managed_sessions()
    rows = sorted(scan(a.hours), key=lambda r: -r["median"])
    buf = []

    def out(s=""):
        buf.append(s)

    out("== 生きているセッションの文脈(直近%g時間 / %s JST) ==" % (a.hours, datetime.now(JST).strftime("%m/%d %H:%M")))
    out("線= 圧縮 %s / 交代 %s (出典 %s・★モデルの窓には依存しない)"
        % (f"{compact_at:,}", f"{rotate_at:,}", src))
    out("%-10s%-18s%-9s%6s%10s%10s%10s  %s"
        % ("session", "部門/用途", "管理", "便数", "中央値", "最新", "最大", "最終"))
    over = []
    for r in rows:
        # ★「管理下か」は room_sessions.json の一致だけで決めない。あれは**現行世代しか**
        #   持たないので、relayが回した過去の世代まで「管理外」に見えてしまう(初版で実際に
        #   誤判定した= 改修部門αの旧世代3本が管理外に並んだ)。
        #   → 判定は**起動文**で行う= relayが立てたセッションは必ず部門の起動文を持つ
        #     (classify() が部門スラッグを返す)。手で開いた窓は「研究室メイン」か「手動」。
        #   room_sessions.json は「現行世代かどうか」の表示にだけ使う。
        current = next((v for k, v in mgd.items() if k.startswith(r["sid"])), None)
        relay_born = r["dept"] not in ("研究室メイン", "手動セッション等", "?")
        managed = ("relay:現行" if current else "relay:旧世代") if relay_born else ""
        r["managed"] = managed
        flag = "" if r["median"] < compact_at else ("★交代線超" if r["median"] >= rotate_at else "★圧縮線超")
        out("%-10s%-18s%-12s%6d%10s%10s%10s  %s %s"
            % (r["sid"], r["dept"][:17], (managed or "★手動(管理外)"), r["n"],
               f"{r['median']:,}", f"{r['last']:,}", f"{r['max']:,}", r["last_ts"], flag))
        if not managed and r["median"] >= compact_at:
            over.append(r)
    if not rows:
        out("  (この窓に動いたセッションは無い)")
    out("")
    if over:
        out("★relayの管理外で線を越えているセッション= %d件(ここが週間制限を食う)" % len(over))
    else:
        out("管理外で線を越えているセッションは無い")

    text = "\n".join(buf)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("書き出した: " + a.out)
    else:
        print(text)

    if a.record:
        rec = {"ts": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S"), "hours": a.hours,
               "compact_at": compact_at, "rotate_at": rotate_at,
               "sessions": [{k: r[k] for k in ("sid", "dept", "managed", "model",
                                               "n", "median", "last", "max")} for r in rows]}
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if a.alert and over:
        n = alert(over, compact_at, rotate_at)
        if n:
            print("研究室HQへ通知した: %d件" % n)


if __name__ == "__main__":
    main()
