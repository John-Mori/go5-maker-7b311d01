#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_pulse — 定期発火の進捗押し出し便(可視化・★督促ではない)。

背景(HQ発注 DISPATCH-aegis-gl / Chami重大インシデント 2026-08-01〜02):
  完了報告の「押し出し」経路が無かった。change_log.jsonl は §3.8で「貯めるだけ・
  知らせに行くな(Chami『テキストだけ貯めといて』)」の**受動台帳**で、Chamiが自分で
  見に行かない限り進捗が可視化されない。→ Chami「応答なし・自律的報告なし・改善してくれ」。
  日次報告便(daily_report.py)は0時/8時の2便で"動静の件数"は出すが、
  **「何を改修したか(change_log)」を押し出さない**=作業の実物が見えない。

役割(HQ指定「数時間ごと or 日次で change_log/git log の未報告分を整形しChamiの部屋へ1通」):
  数時間ごとに発火し、前回マーカー以降の change_log の"未報告分"だけを
  結論行(§4.5 目安5行以内)へ丸めて報告部屋へ1通。
  ★**新規が無ければ沈黙**(督促にしない=ORG-42「常に鳴る警報は読まれなくなる」。
  純粋な生存確認は日次便=daily_report.py の担当。ここは"変化があった時だけ"喋る)。

v1の範囲(★正直に明記=daily_report.py の作法を踏襲):
  正本= change_log.jsonl(§3.8の curated ledger。何/なぜ/commit が揃う)。
  ★**change_log に無い素のcommit**(bump等)は v1では拾わない。二重報告と騒音を避けるため。
  必要になったら git log 側の"changelogに無いcommit"を副節で足す(未実装)。

マーカー: local/llm/report_pulse_marker.json = {"last_ts": ISO8601}
  ★**送信に成功した時だけ前進**させる(送信失敗で取りこぼさない=§3 fail-open寄り)。
  初回(マーカー無し)は現時点の最新entryで**種蒔きのみ・送信しない**(過去249件を一気に吐かない)。

使い方: python scripts/report/report_pulse.py [--send]
  --send無し = 印字のみ(検証用・マーカー不変)。
"""
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
CHANGE_LOG = os.path.join(LOCAL, "llm", "change_log.jsonl")
MARKER = os.path.join(LOCAL, "llm", "report_pulse_marker.json")

sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
try:
    from dept_names import dept_ja           # 部門名は日本語で(C-020・Chami指示)
except Exception:                            # fail-safe: 変換できなくても便は必ず出す
    def dept_ja(slug, with_slug=False):
        return slug

JST = timezone(timedelta(hours=9))
WEEK = ("月", "火", "水", "木", "金", "土", "日")


def _parse_ts(s):
    """change_log の ts をaware datetimeへ。tz無しはJSTとみなす。壊れていればNone。"""
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=JST) if dt.tzinfo is None else dt


def _load_marker():
    try:
        return _parse_ts(json.load(io.open(MARKER, encoding="utf-8")).get("last_ts"))
    except Exception:
        return None


def _save_marker(ts_dt):
    with io.open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"last_ts": ts_dt.isoformat()}, f, ensure_ascii=False)


def _entries():
    """change_log を新しい順ではなく、そのまま(古い→新しい)で読み、(ts_dt, rec)の列にする。"""
    out = []
    if not os.path.exists(CHANGE_LOG):
        return out
    for l in io.open(CHANGE_LOG, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            rec = json.loads(l)
        except ValueError:
            continue
        ts = _parse_ts(rec.get("ts"))
        if ts is not None:
            out.append((ts, rec))
    out.sort(key=lambda x: x[0])
    return out


def _trim(s, n=44):
    s = str(s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def build(send=False):
    """戻り値: (本文 or None, 前進させるべきts or None, 状態文字列)。"""
    entries = _entries()
    if not entries:
        return None, None, "change_log が空"
    newest_ts = entries[-1][0]
    marker = _load_marker()

    if marker is None:                       # ★初回=種蒔きのみ(過去分を吐かない)
        if send:
            _save_marker(newest_ts)
        return None, None, f"初回:マーカーを {newest_ts.isoformat()} で種蒔き(送信なし)"

    fresh = [(ts, r) for (ts, r) in entries if ts > marker]
    if not fresh:
        return None, None, "未報告なし(前回以降に新規のchange_logは無い)=沈黙"

    now = datetime.now(JST)
    head = f"■進捗 {now.month}/{now.day:02d}({WEEK[now.weekday()]}) {now:%H:%M} — 前回以降 {len(fresh)}件"
    # 本文は結論行のみ。5行に収めるため、明細は最大4件+超過は「他N件」。
    body_lines, LIMIT = [], 4
    show = fresh[-LIMIT:] if len(fresh) > LIMIT else fresh   # 新しい順に近い方(末尾)を優先
    for ts, r in show:
        body_lines.append(f"・{dept_ja(r.get('dept', '?'))}: {_trim(r.get('何'))}")
    if len(fresh) > LIMIT:
        body_lines.append(f"・(ほか {len(fresh) - LIMIT}件は change_log 参照)")
    text = "\n".join([head] + body_lines)
    return text, newest_ts, f"未報告 {len(fresh)}件 → 送信対象"


def main():
    send = "--send" in sys.argv
    text, advance_ts, state = build(send=send)
    print(state)
    if text is None:
        return 0
    print("----")
    print(text)
    if not send:
        return 0
    tmp = os.path.join(LOCAL, "_report_pulse_body.txt")
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
         "--dept", "report-notify", "--persona", "オタコン", "--body-file", tmp],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    ok = r.returncode == 0
    print((r.stdout or "").strip().splitlines()[-1] if r.stdout else f"送信rc={r.returncode}")
    if ok and advance_ts is not None:        # ★送れた時だけマーカーを前進(取りこぼし防止)
        _save_marker(advance_ts)
        print(f"マーカー前進: {advance_ts.isoformat()}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
