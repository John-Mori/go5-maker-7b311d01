# -*- coding: utf-8 -*-
"""家PC(DESKTOP-6CK4A5B)の Chrome リモートデスクトップが数分で切れる件の恒久対策。

出所= 研究室HQ→イージス研究室 実依頼 msg_id=1537729916135542784(2026-08-14)。
Chamiの選択= 選択肢3(恒久対策)。

--------------------------------------------------------------------------
■ 何が起きているか(2026-08-14 16:50 JST にイージス研究室が実測。推測ではない)
--------------------------------------------------------------------------
Wi-Fi(中継機 Extender-A-7DE0-WPA3 / Realtek 8812BU)に、ルータ広告(RA)由来の
グローバルIPv6が **8本** 生えていて、**全部 ValidLifetime 00:04:46** だった。

  PrefixOrigin=RouterAdvertisement SuffixOrigin=Random  … 一時アドレス(RFC 4941)×7
  PrefixOrigin=RouterAdvertisement SuffixOrigin=Link    … 安定アドレス×1

★ここがHQの見立てと1点ちがう。**安定アドレス(Link)も同じ 00:04:46 だった。**
  つまり寿命4分46秒は「一時アドレスの設定」ではなく **RAが配っているprefixの寿命**。
  Windows側の上限は `Maximum Valid Lifetime 7d / Maximum Preferred Lifetime 1d` で、
  短くしているのは100%ルータ(中継機)側。

  → だから「寿命が短いから切れる」ではない。寿命は直らない。
    切れる本当の理由は **一時アドレスが約5分ごとに"別のアドレスへ入れ替わる"** こと。
    CRD(chromoting)はICEで掴んだ送信元アドレスに紐づいて通信するので、
    そのアドレスが Deprecated に落ちた瞬間に経路が死ぬ。
    実測のセッション長 19秒/29秒/3分04秒/4分35秒/20分18秒/1分29秒 は、
    「寿命4分46秒」より短い側にばらけている= 入れ替わりのタイミング依存。

  → 打ち手は「一時アドレスをやめて、安定アドレス1本に固定する」。
    アドレス文字列が変わらなくなるので、RAが届き続けるかぎり経路は死なない。

--------------------------------------------------------------------------
■ 提案された3案のうち、この台本が実行するのは1だけ。理由も書く
--------------------------------------------------------------------------
 1 `netsh interface ipv6 set privacy state=disabled` … ★やる(上記のとおり効く)
 2 親機へ繋ぎ替える / 有線 … ★台本ではやらない。**物理**。しかも 16:52 のスキャンで
   見えたSSIDは中継機 `Extender-A-7DE0-WPA3` **1本だけ**だった(親機 aterm-d2c531-a /
   pr500k-271238-* はプロファイル登録はあるが電波が届いていない)。
   = 今の設置場所では「親機へ繋ぎ替える」は選べない。有線かPCの移動が要る。
 3 中継機のRA設定を直す … ★根っこはここだが、中継機側は未測定。管理画面が要る。

 ● `randomizeidentifiers=disabled` は **やらない**(依頼には入っていたが外した)。
   privacy を切った時点で残る安定アドレスは既に「毎回同じ」なので、切断は止まる。
   randomizeidentifiers を切っても止まり方は良くならず、
   代わりに安定アドレスの下64bitが **MACそのもの(EUI-64)** になって外へ出る。
   得が無く privacy だけ落ちる= 入れない。どうしても要るなら --with-eui64 で明示的に。

--------------------------------------------------------------------------
■ もう一つの依頼「昇格せずに chromoting を再起動できる経路」
--------------------------------------------------------------------------
実測した詰まり:
  sc sdshow chromoting = ...(A;;CCLCSWLOCRRC;;;IU) … 対話ユーザーに RP/WP が無い
  = Restart-Service も net stop も Access is denied。HQの報告どおり。
  go5_* の登録タスク25本は **全て RunLevel=Limited**(＝既存の常駐に相乗りもできない)。
  非昇格から `schtasks /create /rl highest` も実測で Access is denied。

打ち手= **SYSTEM/最上位で走る"引き金だけ"のタスクを1本登録する**(go5_crd_restart)。
  登録には昇格が1回要るが、登録さえ済めば **以後は非昇格のまま**
  `schtasks /run /tn go5_crd_restart` で chromoting を再起動できる。
  ★サービスのACL(sdset)を緩めるより狭い。開始/停止の一般権限を渡さず、
    「再起動という決まった動作」だけを渡す形にしてある。

--------------------------------------------------------------------------
■ 使い方
--------------------------------------------------------------------------
  python scripts/_daemons/crd_ipv6_fix.py --check      … 昇格不要。今の状態を測るだけ
  python scripts/_daemons/crd_ipv6_fix.py --apply      … ★昇格が要る(1と引き金タスク)
  python scripts/_daemons/crd_ipv6_fix.py --rollback   … ★昇格が要る(元へ戻す)
  python scripts/_daemons/crd_ipv6_fix.py --watch 30 --minutes 60
        … 昇格不要。Wi-Fiのグローバルv6と chromoting の接続/切断を記録し続ける。
          「入れた」と「直った」を混ぜないための計測。--apply の前後で回して比べる。

  ワンタップ版= scripts/_daemons/fix_crd_ipv6.bat (右クリック→管理者として実行)

★--apply は必ず先に現状を local/_work/ へ控える(C-003 消さずに退避する)。
"""
import argparse
import ctypes
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(ROOT, "local", "_work")
LOG = os.path.join(ROOT, "local", "_crd_ipv6_fix.log")
WATCH_JSONL = os.path.join(WORK, "crd_ipv6_watch.jsonl")
TASK = "go5_crd_restart"          # 非昇格から引ける「chromoting再起動」の引き金


# ---------------------------------------------------------------- 土台
def log(msg):
    line = "%s %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _dec(b):
    """★netsh の出力エンコーディングは"呼ばれた端末"で変わる。実測(2026-08-14):

      PowerShell から   → 英語("Use Temporary Addresses : enabled")
      Git Bash から     → 日本語の **utf-8**("一時アドレスの使用 : enabled")
      タスクスケジューラ→ cp932 になりうる(run_kaizen_daily_repair.py の実例)

    ★utf-8 を先に試すこと。cp932 はほぼ何を食わせても例外を出さない
      (=先に置くと utf-8 のバイト列を黙って化けさせて通す)。実際それで
      「一時アドレス: None」と読めなくなっていた。順番そのものがバグだった。
    """
    for enc in ("utf-8", "cp932"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("cp932", errors="replace")


def sh(args):
    """外部コマンドを1本走らせて (exit, 出力) を返す。"""
    p = subprocess.run(args, capture_output=True)
    return p.returncode, (_dec(p.stdout) + _dec(p.stderr)).strip()


def ps(cmd):
    """PowerShell を1本走らせる(-NoProfile= 個人設定に振り回されない)。"""
    return sh(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd])


def is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------------------------------------------------------------- 計測
def wifi_v6():
    """Wi-Fiのグローバルv6を (アドレス, 由来, 状態, 残り寿命) で返す。

    ★fe80(リンクローカル)と ::1 は経路に使われないので落とす。見たいのは外向きの1本。
    """
    cmd = ("Get-NetIPAddress -AddressFamily IPv6 -InterfaceAlias 'Wi-Fi' "
           "-ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike 'fe80*' } | "
           "ForEach-Object { '{0}|{1}|{2}|{3}' -f $_.IPAddress,$_.SuffixOrigin,"
           "$_.AddressState,$_.ValidLifetime }")
    rc, out = ps(cmd)
    rows = []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) == 4 and ":" in parts[0]:
            rows.append({"addr": parts[0], "suffix": parts[1],
                         "state": parts[2], "valid": parts[3]})
    return rows


def privacy_state():
    """一時アドレスが有効か。読めなければ None(=分からないものを断定しない)。"""
    rc, out = sh(["netsh", "interface", "ipv6", "show", "privacy"])
    m = re.search(r"Use Temporary Addresses\s*:\s*(\w+)", out)
    if not m:                      # 日本語UIの netsh(実測の表記は「一時アドレスの使用」)
        m = re.search(r"一時アドレス.{0,4}使用\s*:\s*(\S+)", out)
    return m.group(1) if m else None


def task_exists(name=TASK):
    rc, _ = sh(["schtasks", "/query", "/tn", name])
    return rc == 0


def do_check(verbose=True):
    rows = wifi_v6()
    priv = privacy_state()
    randomized = [r for r in rows if r["suffix"].lower() == "random"]
    stable = [r for r in rows if r["suffix"].lower() != "random"]
    if verbose:
        log("== 現状 ==")
        log("  昇格           : %s" % ("あり" if is_elevated() else "なし(--apply は打てない)"))
        log("  一時アドレス   : %s" % priv)
        log("  Wi-Fiのv6      : 合計%d本 / 一時%d本 / 安定%d本"
            % (len(rows), len(randomized), len(stable)))
        for r in rows:
            log("    %-42s %-8s %-11s 残り %s"
                % (r["addr"], r["suffix"], r["state"], r["valid"]))
        log("  引き金タスク %s : %s" % (TASK, "登録済" if task_exists() else "未登録"))
        # ★「効いた」の判定条件をここに書いておく= 後から誰が見ても同じ基準で測れる
        log("  ---- 直ったと言える条件 ----")
        log("   (1) 一時アドレスが0本になり、安定アドレスが1本だけ残る")
        log("   (2) そのアドレス文字列が15分たっても変わらない(--watch で確認)")
        log("   (3) CRDのセッションが実測の天井 4分35秒 を超えて続く")
    return {"privacy": priv, "rows": rows, "task": task_exists(),
            "elevated": is_elevated()}


def _secs(v):
    """'00:04:49' / '1.02:03:04' を秒に。読めなければ None。"""
    if not v:
        return None
    d = 0
    if "." in v and ":" in v and v.index(".") < v.index(":"):
        head, v = v.split(".", 1)
        try:
            d = int(head)
        except ValueError:
            return None
    p = v.split(":")
    try:
        p = [int(x.split(".")[0]) for x in p]
    except ValueError:
        return None
    while len(p) < 3:
        p.insert(0, 0)
    return d * 86400 + p[0] * 3600 + p[1] * 60 + p[2]


def do_watch(every, minutes):
    """★「入れた」と「直った」を分けるための計測(§4.55)。

    見るのは3つ。垂れ流さず、意味のある瞬間だけ JSONL に落とす。

      ① 入れ替わり  … 使っている(Preferred)アドレスが別物になった
      ② RAの到着    … 残り寿命が"増えた"瞬間= ルータ広告が届いた合図。
                       ★これを測る理由= この機体のIPv6は寿命が約5分しかなく、
                         全アドレスが同じ寿命を共有している。RAの間隔が5分を
                         超えると **全部まとめて消える**。CRDが数分で死ぬのが
                         「一時アドレスの入れ替わり」なのか「RAの取りこぼしで
                         v6ごと落ちる」のかは、ここを測らないと決まらない。
                         打ち手が変わる(前者=privacy停止で足りる/後者=中継機が真因)。
      ③ 全滅        … グローバルv6が0本になった= その瞬間CRDは必ず切れる
    """
    os.makedirs(WORK, exist_ok=True)
    import time
    end = dt.datetime.now() + dt.timedelta(minutes=minutes)
    last_key, last_left = None, None
    flips, blackouts, ra_at, ra_gaps = 0, 0, None, []
    log("== 計測開始 == %d秒ごと・%d分間 → %s" % (every, minutes, WATCH_JSONL))

    def put(kind, **kw):
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind}
        rec.update(kw)
        with io.open(WATCH_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    while dt.datetime.now() < end:
        rows = wifi_v6()
        pref = sorted([r["addr"] for r in rows if r["state"].lower() == "preferred"])
        key = ",".join(pref)
        left = max([s for s in (_secs(r["valid"]) for r in rows) if s is not None] or [None])

        if not rows:
            blackouts += 1
            log("★グローバルv6が0本= この瞬間CRDは切れる(%d回目)" % blackouts)
            put("blackout", n=blackouts)
        elif last_left is not None and left is not None and left > last_left + 5:
            now = dt.datetime.now()
            gap = int((now - ra_at).total_seconds()) if ra_at else None
            if gap:
                ra_gaps.append(gap)
                log("RA到着: 前回から %d秒 (寿命 %s秒 → %s秒)" % (gap, last_left, left))
            ra_at = now
            put("ra", gap_sec=gap, valid_sec=left)
        elif ra_at is None:
            ra_at = dt.datetime.now()

        if key != last_key:
            if last_key is not None:
                flips += 1
                log("★入れ替わり %d回目: %s → %s" % (flips, last_key or "(無)", key or "(無)"))
            put("addr", preferred=pref, all=rows, flip=flips)
            last_key = key
        last_left = left
        try:
            time.sleep(every)
        except KeyboardInterrupt:
            break

    log("== 計測終了 == %d分" % minutes)
    log("  使用アドレスの入れ替わり : %d回" % flips)
    log("  グローバルv6の全滅       : %d回" % blackouts)
    if ra_gaps:
        log("  RAの間隔(秒)             : 最短%d / 最長%d / 回数%d"
            % (min(ra_gaps), max(ra_gaps), len(ra_gaps)))
        log("  ★最長が寿命(約290秒)を超えていたら、真因は中継機のRA間隔。")
    else:
        log("  RAの到着                 : この窓では捉えられなかった(窓を伸ばせ)")
    log("★入れ替わり0回・全滅0回なら固定できている。1回でもあればそこでCRDは切れる。")
    return 0


# ---------------------------------------------------------------- 変更
def _backup():
    """★変えるものを、変える前に控える(C-003)。控えられなければ変えない。"""
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, "crd_ipv6_before_%s.txt"
                        % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    chunks = []
    for title, args in (("show privacy", ["netsh", "interface", "ipv6", "show", "privacy"]),
                        ("show global", ["netsh", "interface", "ipv6", "show", "global"]),
                        ("sdshow chromoting", ["sc", "sdshow", "chromoting"])):
        rc, out = sh(args)
        chunks.append("## %s (exit=%s)\n%s" % (title, rc, out))
    chunks.append("## Wi-Fi IPv6\n%s"
                  % json.dumps(wifi_v6(), ensure_ascii=False, indent=2))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write("# 変更前の控え %s by aegis-gl\n\n"
                % dt.datetime.now().isoformat(timespec="seconds"))
        f.write("\n\n".join(chunks) + "\n")
    return path


def do_apply(with_eui64=False):
    if not is_elevated():
        log("★昇格していない= 何も変えずに終わる。")
        log("  この台本の --apply は管理者権限が要る(netsh の設定変更と、")
        log("  最上位タスクの登録。どちらも非昇格では Access is denied だと実測済み)。")
        log("  → scripts/_daemons/fix_crd_ipv6.bat を右クリック→「管理者として実行」。")
        return 2

    bak = _backup()
    log("控えた: %s" % bak)

    # (1) 一時アドレスをやめる。store=persistent= 再起動しても残す
    rc, out = sh(["netsh", "interface", "ipv6", "set", "privacy",
                  "state=disabled", "store=persistent"])
    log("privacy disabled: exit=%s %s" % (rc, out))
    if rc != 0:
        log("★失敗した= ここで止める(半端に入れない)。控え= %s" % bak)
        return 1

    if with_eui64:
        # ★既定では通らない道(上の理由)。明示的に指定した時だけ。
        rc2, out2 = sh(["netsh", "interface", "ipv6", "set", "global",
                        "randomizeidentifiers=disabled", "store=persistent"])
        log("randomizeidentifiers disabled: exit=%s %s" % (rc2, out2))

    # (2) 非昇格から引ける「chromoting再起動」の引き金を1本だけ登録する
    #     ★トリガーを付けない= 勝手には走らない。手で /run した時だけ動く。
    if task_exists():
        log("引き金タスク %s は既にある= 触らない" % TASK)
    else:
        cmd = (
            "$a = New-ScheduledTaskAction -Execute 'powershell.exe' "
            "-Argument '-NoProfile -WindowStyle Hidden -Command \"Restart-Service chromoting\"'; "
            "$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount "
            "-RunLevel Highest; "
            "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
            "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5); "
            "Register-ScheduledTask -TaskName '%s' -Action $a -Principal $p -Settings $s "
            "-Description 'CRD host restart trigger (aegis-gl 2026-08-14). "
            "Run it non-elevated: schtasks /run /tn %s' -Force | Out-Null; 'OK'"
            % (TASK, TASK)
        )
        rc3, out3 = ps(cmd)
        log("引き金タスク登録: exit=%s %s" % (rc3, out3))
        if rc3 != 0:
            log("★タスク登録は失敗したが、(1)は入っている= 切断対策そのものは有効。")

    log("== 変更後 ==")
    do_check()
    log("★ここまでは『入れた』。『直った』はまだ言えない。")
    log("  --watch 30 --minutes 20 を回して、入れ替わり0回を見てから直ったと言うこと。")
    return 0


def do_rollback():
    if not is_elevated():
        log("★昇格していない= 戻せない。fix_crd_ipv6.bat を管理者として実行し --rollback を選べ。")
        return 2
    bak = _backup()
    log("戻す前の控え: %s" % bak)
    rc, out = sh(["netsh", "interface", "ipv6", "set", "privacy",
                  "state=enabled", "store=persistent"])
    log("privacy enabled(元へ): exit=%s %s" % (rc, out))
    rc2, out2 = sh(["netsh", "interface", "ipv6", "set", "global",
                    "randomizeidentifiers=enabled", "store=persistent"])
    log("randomizeidentifiers enabled(元へ): exit=%s %s" % (rc2, out2))
    if task_exists():
        rc3, out3 = sh(["schtasks", "/delete", "/tn", TASK, "/f"])
        log("引き金タスク削除: exit=%s %s" % (rc3, out3))
    do_check()
    return 0


def main():
    ap = argparse.ArgumentParser(description="家PCのCRD切断(IPv6一時アドレスの入れ替わり)の恒久対策")
    ap.add_argument("--check", action="store_true", help="測るだけ(昇格不要)")
    ap.add_argument("--apply", action="store_true", help="★昇格が要る。一時アドレス停止＋引き金タスク登録")
    ap.add_argument("--rollback", action="store_true", help="★昇格が要る。元へ戻す")
    ap.add_argument("--with-eui64", action="store_true",
                    help="randomizeidentifiers も切る(既定では切らない。理由は冒頭)")
    ap.add_argument("--watch", type=int, metavar="SEC", help="SEC秒ごとにアドレスの入れ替わりを記録")
    ap.add_argument("--minutes", type=int, default=20, help="--watch の長さ(既定20分)")
    a = ap.parse_args()

    if a.watch:
        return do_watch(a.watch, a.minutes)
    if a.apply:
        return do_apply(with_eui64=a.with_eui64)
    if a.rollback:
        return do_rollback()
    do_check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
