#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""部屋の人格名簿が「編集済み」なのか「走行中の常駐に載っている」のかを見る。

★2026-09-03 改善提案部門トトリの発注(受け入れ条件1=反映ゲート)。イージス研究室が実装。
  壊れた実物= 分析部門の名簿へ早坂芽衣を足した直後、`[早坂芽衣]` が地の文へ漏れた。
  「足した」と「載った」の間には窓がある。これまでその窓を**機械で見る手段が無かった**。

見ているもの(2つを突き合わせるだけ・純粋な読み取り):
  1. オンディスク名簿 = `scripts/llm/dept_daemon.py` の DEPT_CONF(ast で文字列だけ拾う)
  2. 載っている名簿   = `local/_daemon_codever/roster_<dept>.json`
     (常駐が起動した瞬間に自分で書いた控え= 推測でなく実測。C-041)

判定:
  反映済     : 2つが一致
  ★反映待ち : オンディスクに居るのに載っていない人が居る = **その人の名義で喋らせるな**
  ★退役待ち : 載っているのにオンディスクから消えた人が居る(害は小さい)
  控えなし   : roster_*.json が無い = 常駐がこの版より前に起動した(不明・fail-open)

★fail-open: 判定できない時は「不明」を返す。ここが赤いことを理由に便を止める使い方はしない
  (止めるのは §3 の逆= 沈黙が最悪の事故)。使い道は「新人格を名義に選ぶ前の確認」だ。

使い方:
  python scripts/_daemons/dept_roster_lag.py                  # 全部屋
  python scripts/_daemons/dept_roster_lag.py --dept shorts-analyst
  python scripts/_daemons/dept_roster_lag.py --dept shorts-analyst --name 早坂芽衣
      → 終了コード 0 = その人は載っている / 1 = まだ載っていない / 2 = 不明
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAEMON = os.path.join(ROOT, "scripts", "llm", "dept_daemon.py")
SNAP_DIR = os.path.join(ROOT, "local", "_daemon_codever")

OK, LAG, RETIRE, UNKNOWN = ("反映済", "★反映待ち", "★退役待ち", "控えなし")


def ondisk_rosters():
    """オンディスクの DEPT_CONF から `{dept: [人格名, ...]}`。読めなければ {}。"""
    sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
    try:
        # ★名簿の読み方を2つ持たない(ORG-11)= 本体と同じ関数をそのまま使う。
        from dept_daemon import _parse_dept_conf_rosters
    except Exception:
        return {}
    try:
        conf = _parse_dept_conf_rosters(DAEMON)
    except Exception:
        return {}
    return {d: [p.get("persona") for p in (c.get("personas") or ())]
            for d, c in conf.items()}


def loaded_roster(dept, snap_dir=None):
    """常駐が起動時に控えた名簿 `(names, started, pid)`。控えが無ければ (None, 0, 0)。"""
    path = os.path.join(snap_dir or SNAP_DIR, f"roster_{dept}.json")
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        return ([str(n) for n in (rec.get("names") or ())],
                int(rec.get("started") or 0), int(rec.get("pid") or 0))
    except Exception:
        return (None, 0, 0)


def verdict(disk_names, loaded_names):
    """純粋関数。戻り値 (判定, 載っていない人, 消えた人)。"""
    if loaded_names is None:
        return (UNKNOWN, [], [])
    missing = [n for n in (disk_names or ()) if n not in loaded_names]
    extra = [n for n in loaded_names if n not in (disk_names or ())]
    if missing:
        return (LAG, missing, extra)
    if extra:
        return (RETIRE, missing, extra)
    return (OK, [], [])


def main():
    ap = argparse.ArgumentParser(description="人格名簿の反映ズレ(編集済み vs 載っている)")
    ap.add_argument("--dept")
    ap.add_argument("--name", help="この人格が載っているかだけを見る(終了コードで返す)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    disk = ondisk_rosters()
    if not disk:
        print("不明: オンディスク名簿を読めなかった(fail-open)")
        return 2
    depts = [a.dept] if a.dept else sorted(disk)

    if a.name:
        if not a.dept:
            print("--name は --dept と一緒に使う")
            return 2
        loaded, _st, _pid = loaded_roster(a.dept)
        if loaded is None:
            print(f"{UNKNOWN}: {a.dept} の控えが無い(常駐がこの版より前に起動)")
            return 2
        if a.name in loaded:
            print(f"{OK}: {a.dept} の走行中の常駐に「{a.name}」は載っている")
            return 0
        on = a.name in (disk.get(a.dept) or ())
        why = "名簿を編集したがまだ載せ替えていない" if on else "オンディスク名簿にも居ない"
        print(f"{LAG if on else UNKNOWN}: {a.dept} に「{a.name}」は載っていない({why})")
        return 1

    rows = []
    for d in depts:
        loaded, started, pid = loaded_roster(d)
        v, missing, extra = verdict(disk.get(d) or [], loaded)
        rows.append((d, v, missing, extra, pid))
    w = max([len(r[0]) for r in rows] + [4])
    for d, v, missing, extra, pid in rows:
        note = ""
        if missing:
            note += " 載っていない= " + "/".join(missing)
        if extra:
            note += " 消えた= " + "/".join(extra)
        if pid:
            note += f" (pid {pid})"
        print(f"{d.ljust(w)}  {v}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
