#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""空撃ち(C-075)の件数を数える(2026-09-10 イージス研究室)。

何のためか= HQの発注②「**いきなり本起票にするな。まずログだけの空撃ちで丸1日回し、
  増える件数を実測してから有効化しろ**」を実行するための物差し。
  トトリの心配は「誤検知で空起票を量産する」ことで、その答えは**倒す向きを変えることではなく、
  量を先に測ること**だ、というのがこの道具の存在理由。

読む物= `local/llm/dept_daemon_<dept>.log` に出る `REQ-SHADOW` の行だけ。
  ★**新しい台帳を作らない**(共通規律§3)。常駐が既に吐いている .log を後ろから読むだけで、
    どのファイルにも1バイトも書かない。

見る数字:
  総数            … 本起票へ上げたら台帳へ触る便の数(相槌と「閉じ方が書けない」は既に除いてある)
  kind=request    … **新しいIDが増える**分。これが台帳の増分そのもの。
  kind=nudge      … 既存REQへ寄る分(寄せ先が在れば件数は増えない)。
  oldnet=0        … ★**本当の増分**= 今の網(find_waiting/find_working)では拾えていなかった便。
  oldnet=1        … 今も拾えている便=有効化しても台帳は太らない。
  母数            … 現在生きている REQ の件数(open_defects.jsonl を畳んだ実数)。

有効化(実測の後で):
  `local/llm/req_trigger.json` に `{"mode":"on"}` を置く= 常駐を建て直さずに本起票へ上がる。
  戻す時は `{"mode":"shadow"}`(または札を消す)。緊急停止だけは env `GO5_REQ_TRIGGER=off` が勝つ。

実行:
  python scripts/llm/req_shadow_count.py                 # 直近24時間
  python scripts/llm/req_shadow_count.py --hours 48
  python scripts/llm/req_shadow_count.py --since 2026-09-10T12:00:00 --dept aegis-gl
  python scripts/llm/req_shadow_count.py --list          # 拾った行をそのまま出す
"""
import os
import sys
import glob
import argparse
import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LOG_GLOB = os.path.join(ROOT, "local", "llm", "dept_daemon_*.log")
sys.path.insert(0, HERE)

MARK = "REQ-SHADOW"          # ★正本は dept_daemon.REQUEST_SHADOW_MARK(下で突き合わせる)


def _mark():
    """目印は常駐側の定数を正本にする(ここへ写しを置かない・ORG-11)。"""
    try:
        import dept_daemon as dd
        return dd.REQUEST_SHADOW_MARK
    except Exception:                                  # noqa: BLE001
        return MARK                                    # 読めなくても数えられる方へ倒す


def field(line, key):
    for tok in line.split():
        if tok.startswith(key + "="):
            return tok[len(key) + 1:]
    return ""


def rows(since=None, until=None, dept=None, pattern=None):
    """空撃ちの行を集める。★ts が読めない行は捨てずに `?` として数え、黙って消さない。"""
    mark, out = _mark(), []
    for path in sorted(glob.glob(pattern or LOG_GLOB)):
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if mark not in line:
                    continue
                d = field(line, "dept") or os.path.basename(path)[12:-4]
                ts = field(line, "ts")
                if dept and d != dept:
                    continue
                if ts and since and ts < since:
                    continue
                if ts and until and ts > until:
                    continue
                out.append({"dept": d, "ts": ts or "?", "msg": field(line, "msg"),
                            "kind": field(line, "kind"), "oldnet": field(line, "oldnet"),
                            "line": line.rstrip(), "file": os.path.basename(path)})
    return out


def live_requests():
    """母数を2つ返す= (今生きている REQ, 起票された累計)。読めなければ (None, None)。

    ★2つ要る理由= 台帳を畳むと「確認済」が落ちる。**累計376 / 生き219**(2026-09-10 実測)で
      数字が食い違うので、どちらの話をしているかを毎回はっきりさせる。
      増分が効くのは**生きている方**(起動文に載って部屋を押すのはこちら)。
    """
    try:
        import session_relay as SR
        req = [d for d in SR.fold_defects() if d.get("kind") == SR.DEFECT_KIND_REQUEST]
        return sum(1 for d in req if d["status"] == SR.DEFECT_OPEN), len(req)
    except Exception:                                  # noqa: BLE001
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0, help="直近N時間(既定24=丸1日)")
    ap.add_argument("--since", default="", help="ISO(例 2026-09-10T12:00:00)。--hours より優先")
    ap.add_argument("--until", default="")
    ap.add_argument("--dept", default="")
    ap.add_argument("--list", action="store_true", help="拾った行をそのまま出す")
    ap.add_argument("--logs", default="", help="読む .log のglobを差し替える(検査・退避ログ用)")
    a = ap.parse_args()

    since = a.since
    if not since and a.hours:
        since = (datetime.datetime.now()
                 - datetime.timedelta(hours=a.hours)).strftime("%Y-%m-%dT%H:%M:%S")
    pattern = a.logs or LOG_GLOB
    got = rows(since or None, a.until or None, a.dept or None, pattern)

    by_dept, by_kind, by_old = {}, {}, {}
    for r in got:
        by_dept[r["dept"]] = by_dept.get(r["dept"], 0) + 1
        by_kind[r["kind"] or "?"] = by_kind.get(r["kind"] or "?", 0) + 1
        by_old[r["oldnet"] or "?"] = by_old.get(r["oldnet"] or "?", 0) + 1
    真の増分 = sum(1 for r in got if r["oldnet"] == "0" and r["kind"] == "request")

    print(f"空撃ち(C-075) 期間: {since or '全部'} 〜 {a.until or '今'}"
          + (f" / 部門={a.dept}" if a.dept else ""))
    print(f"  読んだ .log = {len(glob.glob(pattern))}ファイル"
          + (f"({pattern})" if a.logs else ""))
    print(f"  空撃ちの行 = {len(got)}件")
    print(f"  kind別  : " + (", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())) or "なし"))
    print(f"  oldnet別: " + (", ".join(f"{k}={v}" for k, v in sorted(by_old.items())) or "なし"))
    print(f"  ★本当の増分(kind=request かつ oldnet=0) = {真の増分}件")
    if by_dept:
        print("  部門別:")
        for k, v in sorted(by_dept.items(), key=lambda x: -x[1]):
            n0 = sum(1 for r in got if r["dept"] == k and r["oldnet"] == "0"
                     and r["kind"] == "request")
            print(f"    {k:<16} {v:>5}件(うち本当の増分 {n0})")
    n, total = live_requests()
    if n is None:
        print("  母数: 台帳が読めなかった(数字を推測しない)")
    else:
        print(f"  母数: 今生きている REQ = {n}件 / 起票された累計 = {total}件")
        if 真の増分 and n:
            print(f"        → この期間の増分を生きている方へ足すと {n + 真の増分}件 "
                  f"(×{(n + 真の増分) / n:.2f})")
    if a.list:
        print("")
        for r in got:
            print(f"  {r['file']}: {r['line']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
