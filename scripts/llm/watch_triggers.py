# -*- coding: utf-8 -*-
"""watch_triggers — 「後で見よう」を**人の記憶から外して仕組みに移す**引き金置き場。

★なぜ在るか(2026-08-29 研究室HQ HQ-0220 / HQ-0218 → イージス研究室)
  HQ-0220「★ただし『置く』と『忘れる』は違う。**1日の投函数が200を超えた日が来たら、その日の
  うちに冷えの間隔分布を取り直す**——この引き金をそっちの側の仕組みに載せてくれ(人の記憶に置くな)。」
  HQ-0218「①frontend は不採用。ただし『月100便を超えたら再検討』を**人の記憶に置くな**=
  work_model_check.py か月次の検査へ閾値を仕込め。」「②…**判定の実行も仕組みに載せろ。**」

★載せ方= 新しい定刻タスクを作らない。**既に定刻で回っている quota_alarm.py の頭から呼ぶ**
  (発火しない安全網は検証されない=§3。タスク登録を増やすほど死角が増える)。
  ここは「条件を見て、超えていたら測って、便を1本出す」だけ。判断はしない。

引き金:
  T1 冷えの間隔分布 : 今日(JST)の投函数 > 200 → cold_gap_report を回して便を出す(1日1回まで)
  T2 格下げの見張り : local/llm/model_downgrade_watch.json の部屋を reround_check で毎回見る。
                      **基準+50%を超えたら即戻す**(_model_override.json から外す)。
                      judge_at を過ぎたら判定して見張りを閉じる。
  T3 frontend再検討 : work_audit.jsonl の frontend work便が直近30日で100を超えたら便を出す(月1回まで)
  T4 痩身の見張り   : 引き継ぎブロックの痩身(HQ-0220③)。判定日(2026-09-12)に close_item.py の
                      実行回数を投入前後で比べ、**戻す線を下回っていたらその場で off にする**。
  T5 FCCの気づかせ線: C-049 §7-B(2026-08-29 HQ依頼)。判定日に fcc_usage の①(載せた仕事の件数)が
                      0から動いたかを測る。★戻す引き金ではない=効かなければ次の手をHQへ返す。

使い方:
  python scripts/llm/watch_triggers.py            # 引き金を1周(定刻から呼ばれる形)
  python scripts/llm/watch_triggers.py --dry-run  # 判定だけ見る(便は出さない)
"""
import argparse
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
LOCAL = os.path.join(ROOT, "local")
DB = os.path.join(LOCAL, "queue", "inbox.db")
STATE = os.path.join(LOCAL, "llm", "watch_triggers_state.json")
WATCH = os.path.join(LOCAL, "llm", "model_downgrade_watch.json")
OVERRIDE = os.path.join(LOCAL, "_model_override.json")
AUDIT = os.path.join(LOCAL, "llm", "work_audit.jsonl")
COLD_LOG = os.path.join(LOCAL, "llm", "cold_gap_history.jsonl")
DEFECTS = os.path.join(LOCAL, "llm", "open_defects.jsonl")
SLIM = os.path.join(LOCAL, "llm", "handoff_slim.json")
ACCESS_LOG = os.path.join(LOCAL, "llm", "ledger_access.jsonl")
FCC_HINT = os.path.join(LOCAL, "llm", "fcc_hint.json")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")

POST_PER_DAY = 200          # T1の引き金(HQ-0220 指定)
FRONTEND_PER_MONTH = 100    # T3の引き金(HQ-0218 ①指定)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


SEND_DRY = False    # ★配線の検証用= dispatch.py は本当に起動するが投函だけ止める(§3)


def send(title, text, dry):
    """イージス研究室へ便を1本。★Discordへ人が投げるのではなく、定刻の機械が出す便。"""
    body = "【定刻の引き金(watch_triggers) → イージス研究室】%s\n\n%s" % (title, text)
    print(body)
    if dry:
        print("---- dry-run: 送らない ----")
        return True
    path = os.path.join(LOCAL, "_watch_trigger_body.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    cmd = [sys.executable, DISPATCH, "--dept", "aegis-gl", "--direct",
           "--from", "watch_triggers(定刻)", "--audience", "ai", "--body-file", path]
    if SEND_DRY:
        cmd.append("--dry-run")
        print("   ★--send-dry: dispatch.py は本当に起動するが投函はしない")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("   dispatch rc=%s %s" % (p.returncode, (p.stdout or p.stderr or "").strip()[:160]))
    return p.returncode == 0


def posts_today(now):
    """今日(JST)の投函数= inbox.db に積まれた便の数。"""
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    con = sqlite3.connect(DB)
    try:
        return con.execute("select count(*) from queue where enqueued_at >= ?", (d0,)).fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------- T1
def t1_cold_gap(now, st, dry):
    n = posts_today(now)
    today = now.strftime("%Y-%m-%d")
    print("T1 投函 今日 %d件(引き金 %d) / 最後に測った日 %s"
          % (n, POST_PER_DAY, st.get("t1_last_date") or "-"))
    if n <= POST_PER_DAY or st.get("t1_last_date") == today:
        return False
    import cold_gap_report as cg
    text, d = cg.summary(168.0)
    d["ts"] = now.isoformat()
    d["posts_today"] = n
    os.makedirs(os.path.dirname(COLD_LOG), exist_ok=True)
    with open(COLD_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
    ok = send("T1= 今日の投函が %d件(>%d)。冷えの間隔分布を取り直した。" % (n, POST_PER_DAY),
              text + "\n\n★前回との比較= local/llm/cold_gap_history.jsonl(この便で1行増えた)。"
                     "\n★これは HQ-0220 の『投函が増えた日に測り直す』引き金。保温の裁定(不採用)は"
                     "変わっていない= 数字が動いたかどうかだけ見ればよい。", dry)
    if ok and not dry:
        st["t1_last_date"] = today
    return True


# ---------------------------------------------------------------- T2
def t2_downgrade(now, st, dry):
    import reround_check as rr
    watch = read_json(WATCH, {}) or {}
    fired = False
    for dept, w in list(watch.items()):
        if w.get("closed"):
            continue
        base = float(w["baseline_pct"])
        lim = float(w["rollback_pct"])
        n, re, cur = rr.measure(dept, float(w["start_ts"]), time.time())
        due = time.time() >= float(w["judge_at"])
        print("T2 %s 基準 %.2f%% → 投入後 %.2f%%(便 %d)/ 戻す線 %.2f%% / 判定日まで %.1f日"
              % (dept, base, cur, n, lim, (float(w["judge_at"]) - time.time()) / 86400))
        if n < int(w.get("min_n", 20)):
            continue                      # 母数が足りないうちは判定しない(fail-quality)
        over = cur > lim
        if not over and not due:
            continue
        if over:
            back = rollback(dept, dry)
            send("T2= %s の往復率が戻す線を超えた。**Sonnetを戻した**。" % dept,
                 "  基準(投入前14日) %.2f%% → 投入後 %.2f%%(便 %d・投げ直し %d)\n"
                 "  戻す線= 基準+%.0f%%= %.2f%% → **超えた**\n"
                 "  %s\n"
                 "  ★この計器は別話題の投げ直しも拾う=**絶対値ではなく基準との差**で判断している。"
                 % (base, cur, n, re, (float(w.get("rollback_mult", 1.5)) - 1) * 100, lim, back), dry)
        else:
            send("T2= %s の判定日。往復は増えていない=**続行**。" % dept,
                 "  基準(投入前14日) %.2f%% → 投入後 %.2f%%(便 %d・投げ直し %d)\n"
                 "  戻す線 %.2f%% を下回ったまま %.1f日経過= 受け入れ条件②を満たす。"
                 % (base, cur, n, re, lim, (time.time() - float(w["start_ts"])) / 86400), dry)
        if not dry:
            w["closed"] = now.isoformat()
            w["result"] = "rollback" if over else "keep"
            w["final_pct"] = round(cur, 2)
            w["final_n"] = n
            watch[dept] = w
            write_json(WATCH, watch)
        fired = True
    return fired


def rollback(dept, dry):
    """_model_override.json の work から外す(★.bak を取ってから= C-003)。"""
    doc = read_json(OVERRIDE)
    if not doc or dept not in (doc.get("work") or {}):
        return "→ _model_override.json に %s は居ない(既に戻っている)" % dept
    if dry:
        return "→ dry-run: %s を work から外すところ" % dept
    shutil.copy2(OVERRIDE, OVERRIDE + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
    doc["work"].pop(dept, None)
    write_json(OVERRIDE, doc)
    return "→ local/_model_override.json の work から %s を外した(.bak あり)" % dept


# ---------------------------------------------------------------- T3
def t3_frontend(now, st, dry):
    cut = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    n = 0
    if os.path.exists(AUDIT):
        for ln in io.open(AUDIT, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                j = json.loads(ln)
            except ValueError:
                continue
            if j.get("dept") == "frontend" and str(j.get("ts") or "") >= cut:
                n += 1
    month = now.strftime("%Y-%m")
    print("T3 frontend の work便 直近30日 %d件(引き金 %d) / 最後に鳴らした月 %s"
          % (n, FRONTEND_PER_MONTH, st.get("t3_last_month") or "-"))
    if n <= FRONTEND_PER_MONTH or st.get("t3_last_month") == month:
        return False
    ok = send("T3= frontend の work便が直近30日で %d件(>%d)。格下げの再検討の線を越えた。" % (n, FRONTEND_PER_MONTH),
              "  HQ-0218 ①= frontend の格下げは**不採用**(便が少なく利益が月$12・固定費に負ける)。\n"
              "  ただし『月100便を超えたら再検討』が条件だった。**いま超えた**。\n"
              "  ★再検討の型= C-059(先に採算)。①価格比2.5で節約を出す ②寄り道の固定費(min_work_sec)\n"
              "  ③**Opusのまま残る便と隣り合うか**(HQ-0218の選択軸)を見てから決める。", dry)
    if ok and not dry:
        st["t3_last_month"] = month
    return True


# ---------------------------------------------------------------- T4
def _confirm_rate(t0, t1):
    """[t0,t1) に台帳へ積まれた confirm 行の数と 1日あたり。

    ★close_item.py は**受理した時も弾かれた時も**行を残す= confirm行の数≒実行回数。
    ★この計器は遡れる(台帳に ts が入っている)= 投入前の基準を後から計算できる。
    """
    n = 0
    if os.path.exists(DEFECTS):
        for ln in io.open(DEFECTS, encoding="utf-8-sig", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                j = json.loads(ln)
            except ValueError:
                continue
            if j.get("op") != "confirm":
                continue
            ts = str(j.get("ts") or "")
            if len(ts) >= 10 and t0 <= ts[:19] < t1:
                n += 1
    days = max((datetime.strptime(t1[:19], "%Y-%m-%dT%H:%M:%S")
                - datetime.strptime(t0[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds() / 86400.0, 0.5)
    return n, n / days


def _access_since(t0):
    """痩身で足した「台帳を開く手」(close_item.py --show/--list)が実際に使われた回数。
    ★★基準は無い(投入前の grep はどこにも記録されていない)= **前後比較には使えない**。
      使うのは「引く手が0のまま」= ポインタが死んでいる、という一方向の検出だけ。
    """
    n = 0
    if os.path.exists(ACCESS_LOG):
        for ln in io.open(ACCESS_LOG, encoding="utf-8", errors="replace"):
            try:
                j = json.loads(ln.strip() or "{}")
            except ValueError:
                continue
            if str(j.get("ts") or "") >= t0:
                n += 1
    return n


def t4_handoff_slim(now, st, dry):
    """引き継ぎブロックの痩身(HQ-0220③)を2週間後に判定し、落ちていたら**その場で戻す**。

    HQ 実行条件2= 「投入から2週間後(2026-09-12目安)に、close_item.py の実行回数 /
      該当台帳へのgrepアクセス頻度を投入前後で比較し、**有意に落ちていたら差し戻す**」。
    ★「有意に」の線は**投入前に数字で書いた**(local/llm/handoff_slim.json の rollback_rate)。
      後から線を引くと、どんな結果でも「有意ではない」と言えてしまう(T2と同じ作法)。
    ★母数が足りない窓では判定しない= 基準の confirm が min_n 未満なら「判定不能」として
      **戻しも続行も宣言せず**便だけ出す(0件と0件を比べて『落ちていない』と言わない)。
    """
    doc = read_json(SLIM, {}) or {}
    if not doc.get("on") or doc.get("closed"):
        print("T4 痩身= %s" % ("入っていない" if not doc.get("on") else "判定済(%s)" % doc.get("closed")))
        return False
    since = str(doc["since"])
    nowiso = now.strftime("%Y-%m-%dT%H:%M:%S")
    bn, brate = doc["baseline_n"], float(doc["baseline_rate"])
    an, arate = _confirm_rate(since, nowiso)
    lim = float(doc["rollback_rate"])
    acc = _access_since(since)
    due = nowiso >= str(doc["judge_at"])
    print("T4 close_item 実行 基準 %.2f件/日(前%d日 %d件) → 投入後 %.2f件/日(%d件)"
          " / 戻す線 %.2f / 台帳を開いた手 %d回 / 判定日 %s%s"
          % (brate, doc["baseline_days"], bn, arate, an, lim, acc,
             doc["judge_at"][:10], "(到来)" if due else ""))
    if not due:
        return False
    if bn < int(doc.get("min_n", 10)):
        send("T4= 痩身の判定日。**判定不能**(基準の母数が %d件しかない)。" % bn,
             "  投入前%d日の close_item 実行が %d件(%.2f件/日)= この計器では有意も何も言えない。\n"
             "  ★戻していない・続行とも言っていない。**判定できなかった**と書く(§4.55)。\n"
             "  次にやるなら窓を伸ばすか、計器を替える方だ。" % (doc["baseline_days"], bn, brate), dry)
    elif arate < lim:
        back = slim_rollback(dry)
        send("T4= 痩身の投入後に台帳を引く手が落ちた。**引き継ぎブロックを戻した**。",
             "  close_item 実行 基準 %.2f件/日(前%d日 %d件) → 投入後 %.2f件/日(%d件)\n"
             "  戻す線 %.2f件/日(基準の%.0f%%)を**下回った**\n"
             "  台帳を開いた手(--show/--list) %d回 ★これには投入前の基準が無い= 参考値\n"
             "  %s\n"
             "  ★HQ-0220③ 実行条件2 の執行。『読まれない引き継ぎは無いのと同じ』の見張りだ。"
             % (brate, doc["baseline_days"], bn, arate, an, lim,
                100 * float(doc.get("rollback_frac", 0.5)), acc, back), dry)
    else:
        send("T4= 痩身の判定日。台帳を引く手は落ちていない=**続行**。",
             "  close_item 実行 基準 %.2f件/日(前%d日 %d件) → 投入後 %.2f件/日(%d件)\n"
             "  戻す線 %.2f件/日を上回ったまま %.1f日経過= 痩身はこのまま残す。\n"
             "  台帳を開いた手(--show/--list) %d回 ★投入前の基準が無い=参考値。0回なら\n"
             "    ポインタが死んでいる合図なので、次の世代はそこを見ろ。"
             % (brate, doc["baseline_days"], bn, arate, an, lim,
                (now - datetime.strptime(since[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=JST))
                .total_seconds() / 86400.0, acc), dry)
    if not dry:
        # ★★読み直してから書く。slim_rollback が同じファイルを書き替えている=
        #   頭で読んだ doc をそのまま書き戻すと **戻したはずの on が生き返る**
        #   (検査 F で実際に緑→赤で捕まえた。便には「戻した」と書いてあるのに戻っていない、
        #    という §4.55 で一番やってはいけない形だった)。
        doc = read_json(SLIM, doc) or doc
        doc["closed"] = nowiso
        doc["final_rate"] = round(arate, 3)
        doc["final_n"] = an
        doc["access_n"] = acc
        write_json(SLIM, doc)
    return True


def slim_rollback(dry):
    """痩身を切る(★.bak を取ってから= C-003)。触るのはスイッチ1個。台帳は読まない・書かない。"""
    doc = read_json(SLIM)
    if not doc or not doc.get("on"):
        return "→ handoff_slim.json は既に off"
    if dry:
        return "→ dry-run: handoff_slim.json を off にするところ"
    shutil.copy2(SLIM, SLIM + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
    doc["on"] = False
    doc["off_by"] = "watch_triggers T4"
    write_json(SLIM, doc)
    return "→ local/llm/handoff_slim.json を off にした(.bak あり)= 次の便から全文へ戻る"


# ---------------------------------------------------------------- T5
def t5_fcc_hint(now, st, dry):
    """C-049 §7-B の気づかせ線が効いたかを、判定日に**機械が**測る。

    HQ の指定(2026-08-29 `DISPATCH-aegis-gl-1787949604668`)= 「効いたかどうかは
      `python scripts/llm/fcc_usage.py --days 7` の**①が0から動くか**で判定する。」
    ★①=「FCCへ載せた仕事の件数」。②(上流へ流した要求)は据え付け検証で116件在るが、
      **それは仕事ではない**ので判定に使わない(0と0を比べない/据え付けを成果と読まない)。
    ★線は投入前に書いてある= `local/llm/fcc_hint.json` の judge_at と threshold(1件)。
      ★**戻す引き金ではない**= 0のままなら「気づかせるだけでは足りない」が結論で、
        次の手(既定の変更・入口の統合)をHQへ返す話になる。線を消して終わりにしない。
    """
    doc = read_json(FCC_HINT, {}) or {}
    if not doc.get("on") or doc.get("closed"):
        print("T5 FCC気づかせ線= %s"
              % ("入っていない" if not doc.get("on") else "判定済(%s)" % doc.get("closed")))
        return False
    import fcc_usage as FU
    since = datetime.now().astimezone() - timedelta(days=int(doc.get("window_days", 7)))
    n1 = len(FU.tasks(since))
    nowiso = now.strftime("%Y-%m-%dT%H:%M:%S")
    due = nowiso >= str(doc["judge_at"])
    print("T5 FCCへ載せた仕事(直近%d日) %d件(投入前 %d件 / 線 %d件) / 判定日 %s%s"
          % (int(doc.get("window_days", 7)), n1, int(doc.get("baseline_tasks", 0)),
             int(doc.get("threshold", 1)), doc["judge_at"][:10], "(到来)" if due else ""))
    if not due:
        return False
    if n1 >= int(doc.get("threshold", 1)):
        send("T5= FCCの気づかせ線が効いた。①が0から動いた。",
             "  fcc_usage --days %d の① = **%d件**(投入前は %d件)。\n"
             "  ★これは『載った』であって『節約が出た』ではない= 幅はC-049実測で0.81%%。\n"
             "  主戦場は便の床のままだ(HQの但し書き)。ここを広げに行くな。"
             % (int(doc.get("window_days", 7)), n1, int(doc.get("baseline_tasks", 0))), dry)
    else:
        send("T5= FCCの気づかせ線は**効かなかった**(①が0のまま)。",
             "  投入 %s から %d日、fcc_usage --days %d の① = **%d件**。\n"
             "  ★気づかせるだけでは足りない、が実測の結論だ。線を消すのではなく、\n"
             "    次の手(既定そのものを変える/入口を1本に寄せる)をHQへ返す案件になる。\n"
             "  ★但し書きは生きている= FCCの節約幅は0.81%%。**床の作業を止めてまでやるな。**"
             % (str(doc.get("since"))[:16], int(doc.get("window_days", 7)),
                int(doc.get("window_days", 7)), n1), dry)
    if not dry:
        doc = read_json(FCC_HINT, doc) or doc      # ★書く前に読み直す(T4で踏んだ穴と同じ形)
        doc["closed"] = nowiso
        doc["final_tasks"] = n1
        write_json(FCC_HINT, doc)
    return True


def run(dry=False, only=None, save_state=True):
    """引き金を1周。★定刻の相乗り口(quota_alarm.py の頭から呼ばれる)。"""
    now = datetime.now(JST)
    st = read_json(STATE, {}) or {}
    fired = 0
    for name, fn in (("t1", t1_cold_gap), ("t2", t2_downgrade), ("t3", t3_frontend),
                     ("t4", t4_handoff_slim), ("t5", t5_fcc_hint)):
        if only and only != name:
            continue
        try:
            if fn(now, st, dry):
                fired += 1
        except Exception as e:                       # 引き金1本の失敗で他を止めない
            print("%s 失敗: %s: %s" % (name, type(e).__name__, e))
    if not dry and save_state:
        write_json(STATE, st)
    return fired


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--send-dry", action="store_true",
                    help="dispatch.py まで本当に起動するが投函だけ止める(配線の検証)")
    ap.add_argument("--posts", type=int, default=None, help="T1の引き金を一時的に変える(検証用)")
    ap.add_argument("--only", choices=["t1", "t2", "t3", "t4", "t5"])
    a = ap.parse_args()
    global SEND_DRY, POST_PER_DAY
    SEND_DRY = a.send_dry
    if a.posts is not None:
        POST_PER_DAY = a.posts
    # ★検証(--posts で引き金を下げた回)は台帳に足跡を残さない= 本番の1日1回を食い潰さない
    print("→ 発火 %d本" % run(a.dry_run, a.only, save_state=(a.posts is None)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
