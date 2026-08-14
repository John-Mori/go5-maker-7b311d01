#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPv6 の RA(ルータ広告)受信間隔と アドレス寿命 の比を実測する物差し。

★なぜ作ったか(2026-08-15 / 研究室HQ msg DISPATCH-aegis-gl-1786738828759):
  「寿命が 4分43秒 しかない=余裕ゼロ。RAを1回取りこぼしただけで失効して CRD が落ちる」
  という読みが出た。だが**寿命の絶対値だけでは余裕は決まらない**。決めるのは
      余裕 = 寿命 ÷ RAの受信間隔  (= 何回連続で取りこぼしたら失効するか)
  であって、寿命が5分でも RA が30秒ごとに来ていれば 10回連続で落とさないと死なない。
  HQ自身が「判定条件は RA受信間隔と lifetime の比」と書いた。その比を測る器がこれだ。

★測り方(受動観測・パケットキャプチャ不要・管理者権限不要):
  Windows は RA を受け取るたびにアドレスの残り寿命を設定値へ**巻き戻す**。
  だから残り寿命を細かくサンプリングして「値が増えた瞬間」を数えれば、
  それがそのまま**この端末が実際に受け取れた RA の時刻**になる。
  取りこぼした RA は巻き戻しが起きない=間隔が伸びる形で必ず見える。

★C-041(一度の観測を状態の代理にするな): 1回 `netsh` を叩いた値では何も言えない。
  時系列で、最小残り寿命(=実際どこまで expiry に近づいたか)まで見る。
★C-036(長い処理は起動器自身が結果を出す): サンプルは1行ずつ即ディスクへ落とし、
  最後にレポートも自分で書く。対話セッションが落ちても測定結果は残る。
  (2026-08-14 の45分watchが完了記録なしで消えた件の再発防止)

使い方:
  python scripts/_daemons/ra_lifetime_watch.py --minutes 40
  python scripts/_daemons/ra_lifetime_watch.py --minutes 5 --interval 3   # 短く試す
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUTDIR = os.path.join(ROOT, "local", "_work", "ra_watch")

# 無限寿命(infinite)は TimeSpan.MaxValue で来るので、これを超えたら無限とみなす
INFINITE = 10 ** 9

# 常駐側の PowerShell。1本だけ起動して回し続ける(5秒ごとに powershell.exe を
# 起こし直すと測定そのものが重くなるため)。
PS_LOOP = r"""
$ErrorActionPreference = 'SilentlyContinue'
while ($true) {
  'TS|' + (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
  Get-NetIPAddress -AddressFamily IPv6 |
    Where-Object { $_.PrefixOrigin -eq 'RouterAdvertisement' } |
    ForEach-Object {
      'A|{0}|{1}|{2}|{3}|{4}' -f $_.IPAddress,
        [long]$_.ValidLifetime.TotalSeconds,
        [long]$_.PreferredLifetime.TotalSeconds,
        $_.AddressState, $_.InterfaceIndex
    }
  'END'
  [Console]::Out.Flush()
  Start-Sleep -Seconds %INTERVAL%
}
"""


def ps(cmd):
    """使い捨ての PowerShell 実行(最後の突き合わせ用)。"""
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout or ""


def chromoting_events(since, until):
    """窓の中の CRD 接続(Id 1)/切断(Id 2) を拾う。切断と失効が重なるかを見るため。"""
    q = ("Get-WinEvent -FilterHashtable @{LogName='Application';ProviderName='chromoting';"
         "StartTime=[datetime]'%s'} -ErrorAction SilentlyContinue | "
         "Where-Object { $_.Id -in 1,2 } | Sort-Object TimeCreated | "
         "ForEach-Object { '{0}|{1}' -f $_.TimeCreated.ToString('yyyy-MM-ddTHH:mm:ss'), $_.Id }"
         % since.strftime("%Y-%m-%d %H:%M:%S"))
    out = []
    for ln in ps(q).splitlines():
        ln = ln.strip()
        if "|" not in ln:
            continue
        ts, _, eid = ln.partition("|")
        if since.isoformat() <= ts <= until.isoformat():
            out.append((ts, int(eid)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=40.0, help="観測する長さ(分)")
    ap.add_argument("--interval", type=int, default=5, help="サンプリング間隔(秒)")
    ap.add_argument("--tag", default="", help="出力ファイル名に足す目印")
    a = ap.parse_args()

    os.makedirs(OUTDIR, exist_ok=True)
    started = dt.datetime.now()
    stamp = started.strftime("%Y%m%d_%H%M") + (("_" + a.tag) if a.tag else "")
    samples_path = os.path.join(OUTDIR, f"samples_{stamp}.jsonl")
    report_path = os.path.join(OUTDIR, f"report_{stamp}.md")
    deadline = started + dt.timedelta(minutes=a.minutes)

    print(f"観測開始 {started:%m/%d %H:%M:%S} → {deadline:%H:%M:%S} "
          f"({a.minutes:g}分 / {a.interval}秒ごと)")
    print(f"サンプル: {samples_path}")

    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         PS_LOOP.replace("%INTERVAL%", str(a.interval))],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", bufsize=1)

    # addr -> {"prev": 前回の pref, "resets": [巻き戻った時刻], "maxlife": 設定寿命,
    #          "minlife": 実測の最小残り, "first": 初出, "last": 最終観測}
    st = {}
    ts_now = None
    seen_this_round = set()
    n_rounds = 0

    try:
        with open(samples_path, "w", encoding="utf-8") as fp:
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("TS|"):
                    ts_now = line[3:]
                    seen_this_round = set()
                    continue
                if line == "END":
                    n_rounds += 1
                    # 消えたアドレス(=失効して落ちた)を記録する
                    for addr, s in st.items():
                        if s["alive"] and addr not in seen_this_round:
                            s["alive"] = False
                            s["gone"].append(ts_now)
                            fp.write(json.dumps({"ts": ts_now, "ev": "gone", "addr": addr},
                                                ensure_ascii=False) + "\n")
                    fp.flush()
                    if dt.datetime.now() >= deadline:
                        break
                    continue
                if not line.startswith("A|"):
                    continue

                _, addr, valid, pref, state, ifidx = line.split("|", 5)
                valid, pref = int(valid), int(pref)
                if valid > INFINITE:      # infinite = 手動/リンクローカル相当。対象外
                    continue
                seen_this_round.add(addr)
                s = st.setdefault(addr, {"prev": None, "resets": [], "maxlife": 0,
                                         "minlife": 10 ** 9, "first": ts_now, "last": ts_now,
                                         "alive": True, "gone": [], "state": state,
                                         "ifidx": ifidx})
                if not s["alive"]:        # 一度消えて生き返った(=新しく降ってきた)
                    s["alive"] = True
                    s["resets"].append(ts_now)
                s["last"], s["state"] = ts_now, state
                s["maxlife"] = max(s["maxlife"], valid)
                s["minlife"] = min(s["minlife"], valid)
                # ★巻き戻り検知= 残り寿命が前回より増えた ⇒ その瞬間 RA を受け取った
                if s["prev"] is not None and valid > s["prev"] + 1:
                    s["resets"].append(ts_now)
                    fp.write(json.dumps({"ts": ts_now, "ev": "ra", "addr": addr,
                                         "from": s["prev"], "to": valid},
                                        ensure_ascii=False) + "\n")
                s["prev"] = valid
                fp.write(json.dumps({"ts": ts_now, "ev": "s", "addr": addr,
                                     "valid": valid, "pref": pref, "st": state},
                                    ensure_ascii=False) + "\n")
    except KeyboardInterrupt:
        print("中断された。ここまでの分でレポートを書く。")
    finally:
        proc.kill()

    ended = dt.datetime.now()
    write_report(report_path, st, started, ended, a, n_rounds, samples_path)
    print(open(report_path, encoding="utf-8").read())
    return 0


def _intervals(resets):
    out = []
    for i in range(1, len(resets)):
        d = (dt.datetime.fromisoformat(resets[i]) - dt.datetime.fromisoformat(resets[i - 1]))
        out.append(int(d.total_seconds()))
    return out


def write_report(path, st, started, ended, a, n_rounds, samples_path):
    dur = (ended - started).total_seconds()
    evs = chromoting_events(started, ended)

    # 全アドレスの巻き戻りを1本のRA受信列にまとめる(同じRAが全アドレスを一度に巻き戻すため、
    # 秒単位で丸めて重複を潰す)。これが「この端末が受け取れたRAの時刻」だ。
    all_resets = sorted({r for s in st.values() for r in s["resets"]})
    gaps = _intervals(all_resets)
    maxlife = max([s["maxlife"] for s in st.values()] or [0])
    minlife = min([s["minlife"] for s in st.values() if s["minlife"] < 10 ** 9] or [0])

    L = []
    L.append(f"# IPv6 RA受信間隔 × アドレス寿命 の実測")
    L.append("")
    L.append(f"- 観測: {started:%m/%d %H:%M:%S} 〜 {ended:%H:%M:%S} "
             f"({dur/60:.1f}分 / {a.interval}秒ごと / {n_rounds}回サンプル)")
    L.append(f"- 生データ: `{os.path.relpath(samples_path, ROOT)}`")
    L.append("")
    L.append("## 結論に使う3つの数")
    L.append("")
    L.append(f"| 測ったもの | 値 |")
    L.append(f"|---|---|")
    L.append(f"| 設定されている寿命 L(観測した最大値) | **{maxlife}秒 ({maxlife/60:.1f}分)** |")
    if gaps:
        L.append(f"| RAの受信間隔(中央値) | **{sorted(gaps)[len(gaps)//2]}秒** |")
        L.append(f"| RAの受信間隔(**最悪** = 一番空いた時) | **{max(gaps)}秒** |")
        L.append(f"| 余裕 = L ÷ 最悪間隔 = **何回連続で取りこぼしたら失効するか** | "
                 f"**{maxlife/max(gaps):.1f}回** |")
    else:
        L.append("| RAの受信間隔 | **観測窓内で巻き戻りゼロ**(RAが1回も来ていない) |")
        L.append("| 余裕 | 測定不能(下の注意を読め) |")
    pct = f"(L の {100*minlife/maxlife:.0f}%)" if maxlife else "(比較対象なし)"
    L.append(f"| 実測の最小残り寿命(**実際にどこまで失効に近づいたか**) | "
             f"**{minlife}秒**{pct} |")
    L.append("")

    L.append("## 読み方")
    L.append("")
    if gaps and maxlife:
        n_loss = maxlife / max(gaps)
        if n_loss >= 4:
            L.append(f"- **余裕はゼロではない。** RA を **{n_loss:.0f}回連続**で取りこぼして"
                     f"はじめて失効する。1回の取りこぼしでは落ちない。")
        elif n_loss >= 2:
            L.append(f"- **余裕は薄い。** RA を {n_loss:.0f}回連続で落とすと失効する。")
        else:
            L.append(f"- **余裕がほぼ無い。** RA を1回落とすと失効する= HQの読みどおり。")
        L.append(f"- 実測の最小残り寿命は **{minlife}秒**。観測窓の中で失効まで"
                 f"{minlife}秒の距離が最短だった(0秒に触れていなければ一度も失効していない)。")
    gone = [(addr, g) for addr, s in st.items() for g in s["gone"]]
    L.append(f"- 窓内で**アドレスが消えた回数: {len(gone)}回**"
             + ("" if not gone else " ← 失効が実際に起きている"))
    for addr, g in gone[:10]:
        L.append(f"    - {g}  {addr}")
    L.append("")

    L.append("## CRD(chromoting)との突き合わせ")
    L.append("")
    if not evs:
        L.append("- 窓内に接続/切断イベントなし(Chamiが使っていない時間帯)。"
                 "**切断と失効が重なるかはこの窓では判定できない**=窓を伸ばすか、使用中に測る。")
    else:
        for ts, eid in evs:
            near = [g for _, g in gone if abs((dt.datetime.fromisoformat(g)
                                               - dt.datetime.fromisoformat(ts)).total_seconds()) <= 30]
            tag = "接続" if eid == 1 else "切断"
            L.append(f"- {ts}  {tag}" + ("  ★30秒以内にアドレス失効あり" if near else ""))
    L.append("")
    L.append("## アドレス別")
    L.append("")
    for addr, s in sorted(st.items()):
        iv = _intervals(s["resets"])
        L.append(f"- `{addr}` ({s['state']}) 巻き戻り{len(s['resets'])}回"
                 + (f" / 間隔 中央{sorted(iv)[len(iv)//2]}s 最悪{max(iv)}s" if iv else "")
                 + f" / 残り寿命 最小{s['minlife']}s")
    L.append("")
    L.append("---")
    L.append("★この器は受動観測だ。RA そのものを見ているのではなく、"
             "**RA が届いた結果**(残り寿命の巻き戻り)を見ている。"
             "届かなかった RA は『間隔が伸びた』形で現れる=取りこぼしはこの数え方で漏れない。")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
