#!/usr/bin/env python3
"""quota_alarm — 週の課金枠の燃え方を**自前の量**で見張り、危ない時だけ鳴らす。

★発注(2026-08-23 研究室HQ msg 1540938360464474273 → イージス研究室)
  「`quota_burn.py` を定刻に載せろ。★鳴らす引き金に『Chamiが画面を見て%を教える』を使うな
   (人間を計器にするな)。自前で持てる量= 重み付き換算の週累計。**先週の同時刻との比**で
   鳴らせば外部の%は要らない。どうしても%が要るなら週1回だけ画面の実測で較正し、以後は
   換算値で外挿。その場合は必ず"推定"と明示させろ。C-046= 鳴った時に打てる手を一緒に出せ。」

★測る量(全部こちらが自分で持てる)
  1. **週累計の重み付き換算値**(`quota_burn.weighted` の合計)。単位は無い=比を見るための量。
  2. **先週の同じ経過時間までの累計**。倍率 = 今週 / 先週。
  3. (任意)較正点があれば「推定 %」。★出力には必ず **推定** と書く。

★鳴らし方(常に誤発火する安全網は無視される・共通規律§3)
  - 既定の閾値= 先週比 1.30倍 以上、**または** 推定%の枯渇時刻が次のリセットより前。
  - 鳴るのは**便を1本出す時だけ**。落ち着いていれば台帳へ1行残して黙る。
  - 同じ警報を鳴らし続けない= `--quiet-hours`(既定12時間)の間は再送しない。
  - ★C-046= 鳴らす本文に**打てる手**(quota_guard.ps1 の1行と、いま食っている上位の部屋)を必ず入れる。

使い方:
  python scripts/llm/quota_alarm.py                 # 見張り1回(定刻タスクはこれ)
  python scripts/llm/quota_alarm.py --dry-run       # 鳴らさずに判定だけ見る
  python scripts/llm/quota_alarm.py --calibrate 46  # 画面の「すべてのモデル」%を1回だけ教える
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import quota_burn as qb                                            # noqa: E402

JST = qb.JST
LOCAL = os.path.join(ROOT, "local")
LEDGER = os.path.join(LOCAL, "llm", "quota_burn.jsonl")
CALIB = os.path.join(LOCAL, "_quota_calibration.json")
STAMP = os.path.join(LOCAL, "_quota_alarm_last.json")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
GUARD = r"scripts\_daemons\quota_guard.ps1"

RATIO_ALARM = 1.30          # 先週の同時刻比。これ以上で鳴らす
# ★24時間。理由は「うるさいから」ではなく**この警報自体が枠を食うから**(2026-08-23 実測):
#   8/23 05〜10時の窓で **投函 159件 → API便 4,609回**= 1投函あたり平均 29往復。
#   週全体が 10,083便なので、**便を1本増やすたびに週の約0.3%が消える。**
#   12時間ごとに鳴らすと、それだけで週 4% を見張りが食う=見張りが病気になる。
QUIET_HOURS = 24.0          # 同じ警報を鳴らし直さない時間(下限。これに加えて下の rearm 条件も要る)

# ★2026-09-07 追加(イージス研究室)= **累計の比は、週の途中で一度跳ねると週末まで戻らない**。
#   実測(`local/llm/quota_burn.jsonl`): 週リセット 09/05 03:00 の直後から 09/07 04:00 まで
#   **14回の巡回が全部 alarm=True**、比は 2.43→3.97→3.06 と一度も 1.30 を割っていない。
#   同じ時刻の「今の速さ」は 直近6時間 便72 に対し先週の同6時間 便238 = **0.30倍**= 既に鎮火済み。
#   つまり本文の「次の巡回で下回れば静かになる」は**到達不能な閉じ方**で、警報は
#   毎日おなじ文を撃ち続ける(1投函あたり約29往復=週の約0.3%を見張りが焼く)。
#   → 時計だけで鳴らし直さない。**状況が変わった時だけ再武装する**(§4=止めるのは同じ文の再送だけ)。
RATE_WINDOW_H = 6.0         # 「今の速さ」を見る窓。累計とは別に、先週の同じ窓と比べる
REARM_GROWTH = 1.30         # 前回鳴らした時から累計がこの倍率まで伸びたら、話が変わったので鳴らし直す

# ★2026-08-29 追加(イージス研究室)= **分母が薄いと比が暴れる**。実測: 週リセットが 03:00 なので
#   リセット直後は「先週の同区間」が 03:00〜04:45 の**便7本**しかなく、比が 242.29倍 と出た。
#   同じ瞬間を先週まるごとの平均ペースと比べると **2.02倍** = 桁が2つ違う。
#   → 同区間の便数が MIN_PREV_N 未満なら、比較の相手を**先週まるごとの平均ペース**へ切り替える
#     (鳴らさないのではなく、**基準を取り替える**。黙らせると本物の急増を落とす)。
#   ★出力には必ずどちらの基準で見たかを書く= 読む側が桁を誤解しないため。
MIN_PREV_N = 30


def window_total(start, end):
    """[start, end) の重み付き換算合計と便数。"""
    rows = qb.collect(start.astimezone(timezone.utc))
    rows = [r for r in rows if r[2].astimezone(JST) < end]
    return sum(qb.weighted(r) for r in rows), len(rows)


def by_dept(start, end, top=5):
    rows = qb.collect(start.astimezone(timezone.utc))
    rows = [r for r in rows if r[2].astimezone(JST) < end]
    dm = qb.dept_map()
    tot = sum(qb.weighted(r) for r in rows) or 1.0
    agg = {}
    for r in rows:
        k = dm.get(r[0], "手動/不明")
        agg[k] = agg.get(k, 0.0) + qb.weighted(r)
    return [(k, v / tot * 100) for k, v in sorted(agg.items(), key=lambda x: -x[1])[:top]]


def rate_now(now, hours):
    """「今の速さ」= 直近 hours 時間 と、**先週の同じ時刻・同じ長さ**の窓を比べる。

    累計の比は週の途中で一度跳ねると戻らない(定数の注記)。こちらは窓が移動するので、
    鎮火すれば下がる= **打てる手(止める・ずらす・落とす)が効く場面かどうか**がこれで分かる。
    戻り値= (今の換算, 今の便数, 先週の換算, 先週の便数, 比 or None)
    """
    cur_w, cur_n = window_total(now - timedelta(hours=hours), now)
    p_end = now - timedelta(days=7)
    prev_w, prev_n = window_total(p_end - timedelta(hours=hours), p_end)
    return cur_w, cur_n, prev_w, prev_n, (cur_w / prev_w if prev_w > 0 else None)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="鳴らさず判定だけ(本文を画面に出す)")
    # ★検証用(共通規律§3)= **外へ出る手だけ偽物にし、判定と分岐は本物のまま回す**。
    #   dispatch.py を実際に subprocess で起動し、投函だけ止める(--dry-run を渡す)。
    #   「送る処理を呼ばない」テストは配線を1本も見ていないので、それはしない。
    ap.add_argument("--send-dry", action="store_true",
                    help="dispatch.py まで本当に起動するが、投函だけ止める(配線の検証)")
    ap.add_argument("--calibrate", type=float, default=None,
                    help="使用状況画面の『すべてのモデル』の%%。週1回だけ渡す")
    ap.add_argument("--ratio", type=float, default=RATIO_ALARM)
    ap.add_argument("--quiet-hours", type=float, default=QUIET_HOURS)
    ap.add_argument("--rate-window", type=float, default=RATE_WINDOW_H,
                    help="「今の速さ」を見る窓(時間)。既定 %g" % RATE_WINDOW_H)
    ap.add_argument("--rearm-growth", type=float, default=REARM_GROWTH,
                    help="前回鳴らした時から累計がこの倍率へ伸びたら鳴らし直す。既定 %g" % REARM_GROWTH)
    a = ap.parse_args()

    # ★引き金置き場を先に1周(2026-08-29 HQ-0220/HQ-0218=「人の記憶に置くな。仕組みに載せろ」)。
    #   新しい定刻タスクを増やさず、**既に定刻で回っているこの見張りに相乗り**させる
    #   (タスクを増やすほど「登録したが動いていない」死角が増える=§3)。
    #   ★ここが落ちても課金の見張りは止めない。
    try:
        import watch_triggers                                       # noqa: E402
        watch_triggers.SEND_DRY = a.send_dry
        watch_triggers.run(dry=a.dry_run)
    except Exception as e:
        print("watch_triggers 失敗(課金の見張りは続ける): %s: %s" % (type(e).__name__, e))

    now = datetime.now(JST)
    start = qb.last_reset(now)
    nxt = start + timedelta(days=7)
    elapsed_h = (now - start).total_seconds() / 3600.0
    span_h = 168.0

    cur_w, cur_n = window_total(start, now)

    # 先週の「同じ経過時間まで」= 同じ形の窓どうしを比べる(片方だけ長い比較をしない)
    prev_start = start - timedelta(days=7)
    prev_w, prev_n = window_total(prev_start, prev_start + timedelta(hours=elapsed_h))
    basis = "先週の同区間"
    if prev_n < MIN_PREV_N:
        # 分母が薄い= 同区間の比は使わない。先週まるごとの平均ペースを同じ長さへ引き伸ばす。
        full_w, full_n = window_total(prev_start, start)
        if full_n > 0:
            basis = ("先週まるごとの平均ペース(同区間は便 %d本しかない= 分母が薄いので基準を替えた)"
                     % prev_n)
            prev_w, prev_n = full_w / span_h * elapsed_h, full_n
    ratio = (cur_w / prev_w) if prev_w > 0 else None

    # 「今の速さ」= 累計とは別の物差し。鎮火したかどうかはこちらでしか分からない。
    r_cur_w, r_cur_n, r_prev_w, r_prev_n, rate_ratio = rate_now(now, a.rate_window)

    if a.calibrate is not None:
        write_json(CALIB, {"ts": now.isoformat(), "week_start": start.isoformat(),
                           "used_pct": a.calibrate, "weighted": cur_w,
                           "note": "画面の実測。以後はこの比で外挿する=出る%は推定"})
        print("較正を記録: 使用 %.1f%% ↔ 換算 %.0f (週 %s〜)"
              % (a.calibrate, cur_w, start.strftime("%m/%d")))

    # 推定%(較正点が**同じ週**に在る時だけ。無ければ %の話は一切しない=推測で埋めない)
    est_pct = eta = None
    cal = read_json(CALIB)
    if cal and cal.get("week_start") == start.isoformat() and cal.get("weighted"):
        per_unit = float(cal["used_pct"]) / float(cal["weighted"])
        est_pct = cur_w * per_unit
        rate = est_pct / elapsed_h if elapsed_h > 0 else 0
        if rate > 0 and est_pct < 100:
            eta = now + timedelta(hours=(100 - est_pct) / rate)

    time_pct = elapsed_h / span_h * 100

    print("== quota_alarm / %s JST ==" % now.strftime("%m/%d %H:%M"))
    print("週の経過= %.1f/168時間(%.1f%%) / 換算= %.0f(便 %d)" % (elapsed_h, time_pct, cur_w, cur_n))
    if ratio is None:
        print("先週の同区間= 記録が無い(比較なし)")
    else:
        print("基準= %s" % basis)
        print("  → %.0f(便 %d) → **今週は %.2f倍**" % (prev_w, prev_n, ratio))
    if rate_ratio is None:
        print("今の速さ(直近%g時間)= 先週の同じ窓に記録が無い(比較なし)" % a.rate_window)
    else:
        print("今の速さ(直近%g時間)= %.0f(便 %d) / 先週の同じ窓 %.0f(便 %d) → **%.2f倍**"
              % (a.rate_window, r_cur_w, r_cur_n, r_prev_w, r_prev_n, rate_ratio))
    if est_pct is None:
        print("推定%= 出さない(今週の較正点が無い。--calibrate <画面の%> を1回だけ渡すと出る)")
    else:
        print("★推定 使用 %.1f%%(較正 %s の外挿= **推定値**。正はChamiの画面)"
              % (est_pct, (cal.get("ts") or "")[:16]))
        if eta:
            print("★推定 100%%到達 %s / 次のリセット %s"
                  % (eta.strftime("%m/%d %H:%M"), nxt.strftime("%m/%d %H:%M")))

    reasons = []
    kinds = []
    burning_now = rate_ratio is not None and rate_ratio >= a.ratio
    if ratio is not None and ratio >= a.ratio:
        reasons.append("%s の %.2f倍(閾値 %.2f)" % (basis, ratio, a.ratio))
        kinds.append("cumulative")
    if burning_now:
        reasons.append("今の速さ(直近%g時間)が 先週の同じ窓の %.2f倍(閾値 %.2f)"
                       % (a.rate_window, rate_ratio, a.ratio))
        kinds.append("rate")
    if eta is not None and eta < nxt:
        reasons.append("推定で %s に枯渇= 次のリセット %s まで %.1f日 止まる"
                       % (eta.strftime("%m/%d %H:%M"), nxt.strftime("%m/%d %H:%M"),
                          (nxt - eta).total_seconds() / 86400))
        kinds.append("eta")

    tops = by_dept(now - timedelta(hours=24), now)

    rec = {"ts": now.isoformat(), "elapsed_h": round(elapsed_h, 2),
           "weighted": round(cur_w), "n": cur_n,
           "prev_weighted": round(prev_w), "prev_n": prev_n,
           "ratio": round(ratio, 3) if ratio else None, "basis": basis,
           "rate_window_h": a.rate_window, "rate_n": r_cur_n, "rate_prev_n": r_prev_n,
           "rate_ratio": round(rate_ratio, 3) if rate_ratio is not None else None,
           "est_pct": round(est_pct, 1) if est_pct else None,
           "alarm": bool(reasons), "reasons": reasons, "kinds": kinds}

    if not reasons:
        rec["suppressed"] = None
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("→ 静か。台帳へ1行だけ残して黙る。")
        return 0

    print("→ ★警報: " + " / ".join(reasons))

    # ── 再武装(rearm)= 時計だけで鳴らし直さない ─────────────────────────────
    # 実測(定数の注記): 累計の比は週の途中で跳ねると週末まで 1.30 を割らない= 毎日おなじ文が出る。
    # **止めるのは同じ文の再送だけ**(§4)= 話が変わったら必ず鳴らす。変わった、の定義は3つ:
    #   1. 週が替わった(前回の警報は別の週の話)
    #   2. **今も速い**(rate 閾値超え= 止める・ずらす・落とすが効く場面)
    #   3. 累計が前回鳴らした時から REARM_GROWTH 倍まで伸びた / 新しい種類の理由が増えた
    # どれにも当たらない= 昨日と同じ事実を言い直すだけ。台帳へ残して黙る。
    suppressed = None
    last = read_json(STAMP, {})
    if last.get("ts"):
        try:
            age = (now - datetime.fromisoformat(last["ts"])).total_seconds() / 3600.0
        except ValueError:
            age = None
        if age is not None and age < a.quiet_hours:
            suppressed = "前回 %.1f時間前に鳴らした= %.0f時間は鳴らし直さない" % (age, a.quiet_hours)
        elif last.get("week_start") == start.isoformat():
            grew = last.get("weighted") and cur_w >= float(last["weighted"]) * a.rearm_growth
            new_kind = set(kinds) - set(last.get("kinds") or [])
            if not (burning_now or grew or new_kind):
                suppressed = ("状況が前回と同じ(今の速さ %s / 累計 %.0f→%.0f= %.2f倍 <閾値 %.2f> / "
                              "理由の種類も同じ)= 同じ文を再送しない"
                              % ("%.2f倍" % rate_ratio if rate_ratio is not None else "比較なし",
                                 float(last["weighted"]), cur_w,
                                 cur_w / float(last["weighted"]) if last.get("weighted") else 0.0,
                                 a.rearm_growth))

    rec["suppressed"] = suppressed
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    if suppressed:
        print("   (%s)" % suppressed)
        return 0

    body = [
        "【定刻の見張り(quota_alarm) → イージス研究室】週の課金枠の燃え方が閾値を超えた。",
        "",
        "■ なぜ鳴らしたか",
    ] + ["  ・" + r for r in reasons] + [
        "",
        "■ 自前で持っている量(外部の%に依存しない)",
        "  週の経過 %.1f/168時間(%.1f%%) / 換算 %.0f(便 %d)" % (elapsed_h, time_pct, cur_w, cur_n),
        "  基準= %s" % basis,
        "  基準の量 %.0f(便 %d)" % (prev_w, prev_n),
    ]
    if rate_ratio is None:
        body.append("  今の速さ(直近%g時間)= 先週の同じ窓に記録が無い(比較なし)" % a.rate_window)
    else:
        # ★2026-09-08: 「= 今も速い」だけを出すと嘘になる場面がある。6時間窓は**終わったバースト
        #   を引きずる**= 09-08 22:00 は 326便のうち 264便が5時間前の17時1本で、直近2時間は8便
        #   しか無いのに「今も速い」と名乗った。窓の中身(直近1時間/2時間)を並べて、読む側が
        #   「まだ燃えているのか / もう終わったのか」を自分で判定できるようにする。
        _h1 = window_total(now - timedelta(hours=1), now)[1]
        _h2 = window_total(now - timedelta(hours=2), now)[1]
        body.append("  今の速さ(直近%g時間)= 便 %d / 先週の同じ窓 便 %d → **%.2f倍**%s"
                    % (a.rate_window, r_cur_n, r_prev_n, rate_ratio,
                       "= 窓の中では速い" if burning_now else "= もう鎮火している(累計だけが先行)"))
        body.append("  ★窓の中身= 直近1時間 便 %d / 直近2時間 便 %d"
                    "(この2つが小さい時、上の倍率は**もう終わったバーストの残り火**だ)"
                    % (_h1, _h2))
    if est_pct is not None:
        body.append("  ★推定 使用 %.1f%%(較正点からの外挿= **推定**。正はChamiの画面)" % est_pct)
    body += [
        "",
        "■ 直近24時間で食っている部屋(重み付き換算のシェア)",
    ] + ["  %5.1f%%  %s" % (p, k) for k, p in tops] + [
        "",
        "■ いま打てる手(C-046= 閉じ方をここに書く)",
        "  1. 朝の定刻をずらす   : powershell -File %s -Action stagger" % GUARD,
        "  2. 朝の定刻を1日止める: powershell -File %s -Action thin" % GUARD,
        "  3. 戻す               : powershell -File %s -Action restore" % GUARD,
        "  4. 部屋のモデルを落とす: local/_model_override.json の enabled を true にして部屋を書く",
        "     (会話の部屋と真因追跡はOpusのまま= C-014。落とすのは機械が機械へ出す便だけ)",
        "",
        "",
        "  ★閉じ方(2026-09-07 訂正)= **累計の比は週の途中で跳ねると週末まで戻らない**"
        "(実測: 09/05〜09/07 の14巡回が全部 alarm=True・比は一度も 1.30 を割っていない)。",
        "  だから『次の巡回で下回れば静かになる』は到達不能だった。今の閉じ方はこの3つ=",
        "   ・週が替わる(次のリセット %s)" % nxt.strftime("%m/%d %H:%M"),
        "   ・**今の速さ**が閾値を割る(上の行。割っている間は同じ文を再送しない)",
        "   ・累計が前回の警報から %.2f倍まで伸びる/新しい理由が増える= その時はまた鳴る"
        % a.rearm_growth,
        # ★2026-09-08 訂正: 上の3つの手前に**%.0f時間の下限**がある(L265)。実物= 09-07 07:00 は
        #   `rate` という新しい理由が立った(2.86倍)のに「前回3.0時間前に鳴らした」で黙った。
        #   「必ずまた鳴る」と書くと、この下限に当たった時に本文が嘘になる。だから明記する。
        "   ★ただし前の警報から %.0f時間は鳴らし直さない(この警報自身も枠を食うため)。"
        "その間に理由が増えても黙る= 台帳 `local/llm/quota_burn.jsonl` の `suppressed` に残る。"
        % a.quiet_hours,
        "  詳しい内訳= python scripts/llm/quota_burn.py --by dept / --by hour",
    ]
    text = "\n".join(body)

    if a.dry_run:
        print("---- dry-run: 送らない本文 ----")
        print(text)
        return 0

    path = os.path.join(LOCAL, "_quota_alarm_body.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    cmd = [sys.executable, DISPATCH, "--dept", "aegis-gl", "--direct",
           "--from", "quota_alarm(定刻)", "--audience", "ai", "--body-file", path]
    if a.send_dry:
        cmd.append("--dry-run")
        print("   ★--send-dry: dispatch.py は本当に起動するが投函はしない")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("   dispatch rc=%s %s" % (p.returncode, (p.stdout or p.stderr or "").strip()[:200]))
    if p.returncode == 0:
        # ★rearm の材料を残す= 次回「話が変わったか」を機械が判定できる形にする(人の記憶に置かない)
        write_json(STAMP, {"ts": now.isoformat(), "reasons": reasons, "kinds": kinds,
                           "week_start": start.isoformat(), "weighted": round(cur_w),
                           "rate_ratio": round(rate_ratio, 3) if rate_ratio is not None else None})
    return 0


if __name__ == "__main__":
    sys.exit(main())
