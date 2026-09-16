#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回送レート計 = どの部屋が、どれだけ他室へ回しているかを request_log.jsonl の実測で出す。

なぜ在るか= 2026-08-02 Chami「すぐ他に回そうとする癖があるな…構造的な問題だよこれは」
(DEF-hq-2c62407ee9)の恒久側。同じ叱責が 2026-09-16 に再発した(「回しすぎ」)=
規律の文言(共通規律§3.8)だけでは止まらなかった、ということ。心がけに任せず数える。

読むだけ。何も書かない。何も送らない。

  python scripts/llm/relay_rate.py                 # 全部屋・直近24時間と14日
  python scripts/llm/relay_rate.py --dept local-lab
  python scripts/llm/relay_rate.py --hours 24 --json

★この値を各部屋の起動文へ自動で載せる口(dept_daemon/session_relay)は**基盤**=
  イージス研究室 / プラットフォームSEの職責。ここは数える側だけを持つ。
"""
import argparse
import collections
import datetime
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(ROOT, "local", "llm", "request_log.jsonl")

# ---------------------------------------------------------------- 費用の見張り(HQ-0269)
# なぜ在るか= 2026-09-16 研究室HQ `DISPATCH-aegis-gl-1789570636582`。
#   load() は request_log.jsonl(実測 8.5MB)を毎回まるごと舐める。今は 0.125秒/回で
#   余裕があるが、ログは伸び続ける。前の版はこの費用を「効いてきたら直す/その時が
#   来たことは秒数で分かる」と書いていた= ★**人手の入口を要件にした機構**であり、
#   共通規律§3 が禁じている形そのものだ(実測0件になる)。誰も秒数を見ない。
#   → 見張りを機械に持たせる。**閾値を超えた時だけ**、機械が1行残す。
# ★鳴らし方の条件(HQ指定):
#   ① 封筒へは出さない= 毎便鳴る安全網は無視される。
#   ② 残すのは1行でよい。残り先は当室の裁量。
#   ③ 誤発火しないこと= 今の実測 0.125秒に対して閾値は4倍の 0.5秒を取る。
# ★読まれる面へ繋ぐのは session_relay 側(_relay_rate_slow_line)= 台帳の行として
#   所有部門の起動文にだけ出る。この面は boot_hash の外なので、鳴っても全文再送にならない。
SLOW_SEC = 0.5                     # これを超えたら1行残す(既定。環境変数で上書き可)
SLOW_QUIET_SEC = 24 * 3600         # 同じ事実を1日1行までに畳む(警報でログを太らせない)
SLOW_FRESH_SEC = 7 * 24 * 3600     # 直近この期間に鳴っていれば「今も遅い」と見なす
SLOW_LOG = os.path.join(ROOT, "local", "llm", "relay_rate_slow.jsonl")


def slow_sec():
    """閾値(秒)。★呼ぶたびに環境変数を読む= 検査が import 後でも差し替えられる。"""
    try:
        return float(os.environ.get("RELAY_RATE_SLOW_SEC") or SLOW_SEC)
    except (TypeError, ValueError):
        return SLOW_SEC


def slow_log_path():
    """1行を残す先。**ここが正本**(session_relay も CLI もこの関数から貰う= ORG-11)。"""
    return os.environ.get("RELAY_RATE_SLOW_LOG") or SLOW_LOG


def note_slow(elapsed, path, lines):
    """閾値超えを1行だけ残す。**呼び出し元を巻き添えにしない**(何があっても例外を出さない)。

    戻り値= 実際に書いたら True / 畳んだ・書けなかったら False。
    """
    dest = slow_log_path()
    try:
        if os.path.exists(dest) and (time.time() - os.path.getmtime(dest)) < SLOW_QUIET_SEC:
            return False                          # 1日1行(同じ事実を積み上げない)
        d = os.path.dirname(dest)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        rec = {"ts": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
               "dept": "aegis-gl",
               "何": "relay_rate.load() が閾値を超えた= 回送レート計の費用が効き始めた",
               "elapsed_sec": round(float(elapsed), 3),
               "threshold_sec": round(slow_sec(), 3),
               "log": path,
               "log_mb": round(os.path.getsize(path) / 1048576.0, 2) if os.path.exists(path) else None,
               "log_lines": lines,
               "次の一手": "load() を窓で切る(古い行を読まない)か、ESC行だけの索引を持つ"}
        with open(dest, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:                             # noqa: BLE001
        return False                              # 見張りが本体を殺さない


def slow_last():
    """最後に鳴った1行を返す(直近 SLOW_FRESH_SEC 以内のものだけ)。無ければ None。"""
    dest = slow_log_path()
    try:
        if not os.path.exists(dest):
            return None
        last = None
        with open(dest, "rb") as f:
            for raw in f.read().decode("utf-8").splitlines():
                try:
                    last = json.loads(raw)
                except Exception:                 # noqa: BLE001
                    continue
        if not last:
            return None
        t = datetime.datetime.strptime(last.get("ts", ""), "%Y-%m-%dT%H:%M:%S")
        if (datetime.datetime.now() - t).total_seconds() > SLOW_FRESH_SEC:
            return None                           # ★直せば黙る(手で消して回る必要がない)
        return last
    except Exception:                             # noqa: BLE001
        return None


def _sender(request_id):
    """'ESC-local-lab-DISPATCH-local-lab-1549786371537899664' → 'local-lab'。

    回送便の request_id は ESC-<送り元>-<msg_id> だが、dispatch を経由したものは
    間に '-DISPATCH-<送り元>' が挟まる。末尾の数字IDを落としてから、その節を剥がす。
    """
    body = request_id[4:]                     # 'ESC-' を落とす
    head = body.rsplit("-", 1)[0]             # 末尾の msg_id を落とす
    cut = head.find("-DISPATCH-")
    return head[:cut] if cut > 0 else head


def load(path=LOG):
    """ESC便(=他室へ回された便)を request_id ごとに1件へ畳んで返す。

    ★所要時間を自分で測る(HQ-0269)。閾値を超えた便**だけ**が note_slow() で1行残る。
      測るのはここ1箇所= CLI から呼ばれても封筒から呼ばれても同じ見張りが掛かる。
    """
    if not os.path.exists(path):
        return []
    t0 = time.perf_counter()
    rows = {}
    n_lines = 0
    with open(path, "rb") as f:
        for raw in f.read().decode("utf-8").splitlines():
            n_lines += 1
            try:
                d = json.loads(raw)
            except Exception:
                continue                      # 壊れた行は数から落とす(数えたと言わない)
            rid = d.get("request_id", "")
            if not rid.startswith("ESC-") or rid in rows:
                continue                      # 同じ便の state 遷移は1件として数える
            rows[rid] = (_sender(rid), d.get("dept", "?"), d.get("ts", ""))
    out = sorted(rows.values(), key=lambda r: r[2])
    elapsed = time.perf_counter() - t0
    if elapsed > slow_sec():
        note_slow(elapsed, path, n_lines)
    return out


def since(rows, hours):
    edge = (datetime.datetime.now() - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    return [r for r in rows if r[2] >= edge]


def stats(dept, hours=24, path=None):
    """1部屋ぶんの回送レートを返す。**CLIも封筒もここを通す**(ORG-11= 数え方を2つ持たない)。

    ★2026-09-16 イージス研究室が切り出した。理由は2つ=
      ① share の計算式が main() の中にしか無かった= 封筒側へ書き写すと正本が2つになる。
      ② path を引数で受ける= 検査が合成ログを食わせられる(load の既定引数は def 時に
         束縛されるので、LOG を差し替えても効かない)。
    """
    rows = load(path or LOG)
    win = since(rows, hours)
    n = sum(1 for s, _, _ in win if s == dept)
    return {"dept": dept, "hours": hours, "count": n,
            "total_all_rooms": len(win),
            "share_pct": round((100.0 * n / len(win)) if win else 0.0, 1),
            "count_14d": sum(1 for s, _, _ in since(rows, 24 * 14) if s == dept),
            "to": dict(collections.Counter(t for s, t, _ in win if s == dept))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dept", help="この部屋だけを見る(スラッグ)")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _slow = slow_last()
    if _slow:                                       # ★鳴っている時だけ1行(平時は無言)
        print("★この計器自身が遅くなっている= %s に %.2f秒(閾値 %.2f秒)。詳細= %s"
              % (_slow.get("ts", "?"), _slow.get("elapsed_sec") or 0.0,
                 _slow.get("threshold_sec") or 0.0, slow_log_path()))

    if a.dept:
        out = stats(a.dept, a.hours)
        n, share = out["count"], out["share_pct"]
        print(json.dumps(out, ensure_ascii=False) if a.json
              else f"{a.dept}: 直近{a.hours}時間で {n} 件を他室へ回した"
                   f"(全部屋合計 {out['total_all_rooms']} 件の {share:.0f}%)/ 直近14日 {out['count_14d']} 件"
                   + ("\n  宛先= " + ", ".join(f"{k} {v}件" for k, v in out["to"].items()) if out["to"] else ""))
        return

    rows = load()
    win = since(rows, a.hours)
    long = since(rows, 24 * 14)
    by_room = collections.Counter(s for s, _, _ in win)

    if a.json:
        print(json.dumps({"hours": a.hours, "total": len(win),
                          "by_room": dict(by_room)}, ensure_ascii=False))
        return
    print(f"回送便(ESC) 直近{a.hours}時間= {len(win)} 件 / 直近14日= {len(long)} 件")
    for room, n in by_room.most_common():
        to = collections.Counter(t for s, t, _ in win if s == room)
        print(f"  {n:4d}  {room} → " + ", ".join(f"{k}({v})" for k, v in to.most_common()))
    if not win:
        print("  (この窓では0件)")


if __name__ == "__main__":
    main()
