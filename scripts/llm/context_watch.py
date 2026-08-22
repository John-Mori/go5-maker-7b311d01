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
  python scripts/llm/context_watch.py --alert             # 線を越えたセッションをHQへ通知
                                                          # (★管理下・管理外の両方。越え方で分ける)

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
STALE_SEC = 1800                # 30分書き込みが無ければ「もう走っていない」と見る
# ★relayは便の**途中**では圧縮しない。便を返してから後始末で撃つ(実測 2026-08-22:
#   予約16:41:29→実行16:45:17=228秒 / 16:59:23→17:02:39=196秒 / 17:11:50→17:15:36=226秒)。
#   その間に線を越えた行を見て「撃てていない」と言うと、**必ず**誤発火する。
COMPACT_LAG_SEC = 900           # 越えてからこの秒数までは「処理中」とみなす(実測の約4倍)

# ★★2026-08-22 研究室HQ 指摘1(msg 1540622895687139438)= **管理下も数える**。
#   初版は over の条件に `not managed` を入れていた。結果、線を越えていても relay管理下なら
#   1件も数えず --alert も撃たなかった。実測でその時いちばん食っていたのは
#   2f7b8457(イージス研究室・relay管理下・中央値 215,522=交代線を30,522超)で、
#   **一番大きいセッションが見張りに1件も映らない**状態だった。
#   これは「線を引いたら、その線が効かない経路を全部数える」(共通規律§3 / C-042)の再演だ。
#   管理外の穴を塞いで、管理外だけを見る見張りを付けたら、管理下の穴が残った。
#   → 判定は**越え方の種類**で分ける(原因も次の一手も違うため):
#     管理外 = 線が最初から効かない(手で開いた窓)
#     未発火 = 線は効くはずなのに越えている(relayが撃てていない)
#     見失い = 現行世代として登録されていないのに書き込みが続いている
#     交代済 = 既に交代した旧世代が窓に残っているだけ(**鳴らさない**=誤発火にしない)
#
# ★★2026-08-22(2回目・イージス研究室)**「未発火」を中央値だけで決めていたのが誤りだった。**
#   実測(17:16): hq c27eec97 を「未発火」と出したが、同じ12時間に relay は**4回**圧縮している
#     16:30 124,149→8,114 / 16:45 171,240→10,502 / 17:02 171,799→9,039 / 17:12 129,472→10,404
#   (出典 local/llm/dept_daemon_hq.log)。イージス研究室 2f7b8457 も 16:45 と 17:15 に撃っている。
#   ★理由は判定の形そのものだ= **圧縮は 120,000 で撃つので、正常な部屋の記録には
#     必ず 120,000 超の行が並ぶ。**その並びの中央値を線と比べれば、**撃てば撃つほど
#     「未発火」に見える。**忙しい部屋では永久に消えない=常に誤発火する安全網(共通規律§3)。
#   → 「撃てていない」は **最後の圧縮より後にまだ線を越えている**ことで測る(時系列で見る)。
#     圧縮済 = 越えた後にちゃんと圧縮が走っている(鳴らさない)
#     処理中 = 越えた便がまだ新しい(relayは便の終わりに撃つ)= 結果待ち(鳴らさない)
OVER_KINDS = {
    "管理外": "relayの管理外(手で開いた窓)= 圧縮線も交代線も一切かからない",
    "未発火": "relay管理下なのに越えている= relayが撃てていない(線の物差しか、圧縮しても落ちない)",
    "見失い": "現行世代として登録されていないのに書き込みが続いている= relayが世代を見失った",
    "圧縮済": "越えた後に圧縮が走っている= relayは撃てている(**鳴らさない**)",
    "処理中": "越えた便がまだ新しい= relayは便の終わりに撃つので結果待ち(**鳴らさない**)",
}

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
            stamps, bounds = [], []          # ★便ごとの時刻 / 圧縮の区切りの時刻(判定を時系列で見るため)
            try:
                f = open(p, encoding="utf-8", errors="replace")
            except OSError:
                continue
            with f:
                for line in f:
                    if '"usage"' not in line and "compact_boundary" not in line:
                        continue
                    if "compact_boundary" in line and '"usage"' not in line:
                        # ★圧縮の区切りには usage が無い。ここで拾わないと
                        #   「撃てているのに未発火」を永久に出し続ける(この節の冒頭参照)。
                        mb = RE_TS.search(line)
                        if mb:
                            try:
                                bounds.append(datetime.fromisoformat(mb.group(1)).replace(
                                    tzinfo=timezone.utc).timestamp())
                            except ValueError:
                                pass
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
                    stamps.append(dt.timestamp())
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
                "last_epoch": last_ts.timestamp() if last_ts else 0.0,
                "ctxs": ctxs, "stamps": stamps, "bounds": bounds,
                "n_compact": len(bounds),
            })
    return rows


def mark_managed(rows, mgd):
    """各行に「relayの管理下か」を書き込む(表示と判定で同じ値を使う=2か所で判定しない)。

    ★「管理下か」は room_sessions.json の一致だけで決めない。あれは**現行世代しか**
      持たないので、relayが回した過去の世代まで「管理外」に見えてしまう(初版で実際に
      誤判定した= 改修部門αの旧世代3本が管理外に並んだ)。
      → 判定は**起動文**で行う= relayが立てたセッションは必ず部門の起動文を持つ
        (classify() が部門スラッグを返す)。手で開いた窓は「研究室メイン」か「手動」。
      room_sessions.json は「現行世代かどうか」の区別にだけ使う。
    """
    for r in rows:
        current = next((v for k, v in (mgd or {}).items() if k.startswith(r["sid"])), None)
        relay_born = r["dept"] not in ("研究室メイン", "手動セッション等", "?")
        r["managed"] = ("relay:現行" if current else "relay:旧世代") if relay_born else ""
    return rows


def _fired_since(r, compact_at, now):
    """relay管理下の線超を、**最後の圧縮より後にまだ越えているか**で分ける。

    返す値= "未発火"(撃てていない) / "圧縮済"(越えた後に撃っている) / "処理中"(結果待ち)。

    ★中央値では測れない= 圧縮は 120,000 で撃つので、**正常に撃っている部屋ほど
      記録に 120,000 超の行が並ぶ**(その行が無ければ、そもそも撃つ理由が無い)。
      中央値と線を比べる限り、健康な部屋が永久に「未発火」で鳴り続ける(実測 hq= 4回撃って未発火)。
    ★時刻が読めない行(手で作った行・古い呼び出し)は **"未発火" へ倒す**=
      判定不能を「大丈夫」の側へ倒すと、本当の穴が黙って消える(fail-open は喋る側)。
    """
    ctxs, stamps = r.get("ctxs") or [], r.get("stamps") or []
    bounds = r.get("bounds")
    if bounds is None or not stamps or len(stamps) != len(ctxs):
        return "未発火"
    last_b = max(bounds) if bounds else 0.0
    overs = [t for c, t in zip(ctxs, stamps) if t > last_b and c >= compact_at]
    if not overs:
        return "圧縮済"
    if now - max(overs) < COMPACT_LAG_SEC:
        return "処理中"
    return "未発火"


def judge(rows, compact_at, rotate_at, now=None):
    """線を越えている行を**管理下・管理外の両方**から拾い、越え方の種類を付けて返す。

    ★戻り値の各行に足すもの:
        over_kind : OVER_KINDS のキー、または "交代済"(=鳴らさない)
        level     : "交代線超" / "圧縮線超"
        alert     : 通知に載せるか(交代済だけ False)
    ★中央値で判定する= 一発の行き過ぎではなく**定常的に越えているか**を見る
      (C-041= 一度の観測を状態の代理にするな)。
    """
    now = time.time() if now is None else now
    over = []
    for r in rows:
        if r["median"] < compact_at:
            continue
        r["level"] = "交代線超" if r["median"] >= rotate_at else "圧縮線超"
        managed = r.get("managed") or ""
        if not managed:
            r["over_kind"] = "管理外"
        elif managed == "relay:現行":
            r["over_kind"] = _fired_since(r, compact_at, now)
        elif now - float(r.get("last_epoch") or 0) < STALE_SEC:
            r["over_kind"] = "見失い"
        else:
            r["over_kind"] = "交代済"          # 既に交代した窓の残骸=鳴らす意味がない
        r["alert"] = r["over_kind"] not in ("交代済", "圧縮済", "処理中")
        over.append(r)
    return over


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
    """線を越えたセッションを研究室HQへ1本出す(キューへ。Discordへは出さない)。

    ★★2026-08-22 HQ指摘1で**管理下も載せる**。ただし一緒くたにはしない=
      「線が効かない窓(管理外)」と「線が効くはずなのに撃てていない(未発火)」は
      **原因も次の一手も違う**。受け手がそこを読み間違えないよう、種類ごとに分けて書く。
    ★鳴りっぱなしにしない= 同じセッションは ALERT_COOLDOWN_SEC の間は再送しない
      (常に誤発火する安全網は無視される=共通規律§3)。
    """
    st = _load_state()
    now = time.time()
    fresh = [r for r in over if r.get("alert", True)
             and now - float(st.get(r["sid"], 0) or 0) > ALERT_COOLDOWN_SEC]
    if not fresh:
        return 0
    body = ["【文脈の見張り】文脈の線を越えているセッションがある(絶対トークン数で判定)。",
            "線= 圧縮 %s / 交代 %s(session_relay が正本)" % (f"{compact_at:,}", f"{rotate_at:,}")]
    for kind in ("未発火", "見失い", "管理外"):
        grp = [r for r in fresh if r.get("over_kind") == kind]
        if not grp:
            continue
        body.append("")
        body.append("■%s= %s (%d件)" % (kind, OVER_KINDS[kind], len(grp)))
        for r in grp:
            body.append("  %s %s [%s] %s モデル=%s 便=%d 中央値=%s 最新=%s 最大=%s (最終 %s)"
                        % (r["sid"], r["dept"], r.get("managed") or "手動", r.get("level", ""),
                           r["model"], r["n"], f"{r['median']:,}",
                           f"{r['last']:,}", f"{r['max']:,}", r["last_ts"]))
    body.append("")
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
    mark_managed(rows, mgd)
    over = judge(rows, compact_at, rotate_at)
    for r in rows:
        flag = ("★%s(%s)" % (r["level"], r["over_kind"])) if r.get("level") else ""
        out("%-10s%-18s%-12s%6d%10s%10s%10s  %s %s"
            % (r["sid"], r["dept"][:17], (r["managed"] or "★手動(管理外)"), r["n"],
               f"{r['median']:,}", f"{r['last']:,}", f"{r['max']:,}", r["last_ts"], flag))
    if not rows:
        out("  (この窓に動いたセッションは無い)")
    out("")
    if over:
        for kind in ("未発火", "見失い", "管理外", "交代済", "圧縮済", "処理中"):
            grp = [r for r in over if r["over_kind"] == kind]
            if grp:
                out("★%s= %d件%s" % (kind, len(grp),
                                    "" if kind in ("未発火", "見失い", "管理外") else "(鳴らさない)"))
        out("  ※越え方の意味= " + " / ".join("%s: %s" % (k, v) for k, v in OVER_KINDS.items()))
    else:
        out("線を越えているセッションは無い(管理下・管理外とも)")

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
               "sessions": [dict({k: r[k] for k in ("sid", "dept", "managed", "model",
                                                    "n", "median", "last", "max")},
                                 over_kind=r.get("over_kind", ""), level=r.get("level", ""))
                            for r in rows]}
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if a.alert and over:
        n = alert(over, compact_at, rotate_at)
        if n:
            print("研究室HQへ通知した: %d件" % n)


if __name__ == "__main__":
    main()
