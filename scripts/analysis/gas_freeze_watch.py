# -*- coding: utf-8 -*-
"""GAS(競合"動画"日次の上流)が凍結し続ける間だけ鳴らす、分析部門・自室の監視口。

背景(HQ-0230 / DISPATCH-shorts-analyst-1788307335393):
  2026-09-02 の「差し替え」(msg 1544486499653910629)で毎朝の押し出しを競合"動画"日次から
  競合"コミュニティ"ブリーフへ替えた。その結果、上流GAS(runCompetitorDaily 04:00)が
  8/18 で止まっている事実を毎朝知らせていた唯一の口も一緒に黙った(C-044= 監視だけ先に降りた)。
  → 凍結が続く間だけ・毎朝同じにならない形で鳴る口を、分析部門の自室で作り直す(C-027)。

Chami が却下したのは「毎朝まったく同じ文が Chami の部屋に出る」こと(msg 1544485816288419840)。
  だからこの口は:
    - 鳴らす先= Chami の部屋ではなく 研究室HQ(AI便)。復旧はGAS本体=改修α/基盤の手番で、HQが差配する。
    - 頻度= 凍結を新規に検知した初回に1本、その後は凍結が続く限り7日ごとに1本だけ(週次リマインド)。
      毎日は鳴らさない(=Chamiが嫌った"毎朝同じ"の再来を避ける)。文面には経過日数を入れ、鳴るたびに中身が変わる。
    - 復旧= 上流に新しい日付が入ったら「復旧した」を1本だけ出して状態をクリア。
  凍結判定は rc に頼らない(--emit は凍結でも rc=0 を返す=2026-09-02 実測)。
  competitor_daily.py --emit の stdout にある「上流スナップが YYYY-MM-DD で停止」を拾って判定する。

実行= 毎朝08:00の常駐(competitor_daily.ps1)が community_daily_push.py の後に本スクリプトを呼ぶ。
状態= local/gas_freeze_watch.state(JSON)/ 監視の全実行ログ= local/gas_freeze_watch.log(UTF-8・毎回書く=沈黙日でも実物が残る)。
--dry: 判定と本文組み立てまで走らせるが HQ へは出さず、鳴らす予定の本文を stdout に見せるだけ(配線検証用)。
"""
import os, sys, re, json, subprocess, datetime, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable or "python"
EMIT = [PY, os.path.join("scripts", "analysis", "competitor_daily.py"), "--emit"]
DISPATCH = [PY, os.path.join("scripts", "llm", "dispatch.py"),
            "--dept", "hq", "--from-dept", "shorts-analyst",
            "--from", "アーモンドアイ(分析部門)", "--audience", "ai"]
STATE = os.path.join(ROOT, "local", "gas_freeze_watch.state")
LOG = os.path.join(ROOT, "local", "gas_freeze_watch.log")
DRY = "--dry" in sys.argv
REPING_EVERY = 7  # 凍結が続く間の再通知間隔(日)
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
FREEZE_RE = re.compile(r"上流スナップが\s*(\d{4}-\d{2}-\d{2})\s*で停止")


def _log(msg):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %s" % (stamp, msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line)


def _load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(d):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def _clear_state():
    try:
        os.remove(STATE)
    except OSError:
        pass


def _ring(body):
    """HQ(AI便)へ1本出す。--dry は出さずに本文だけ見せる。"""
    if DRY:
        _log("--dry: HQへは出さず本文表示\n----\n%s\n----" % body)
        return True
    fd, path = tempfile.mkstemp(prefix="gasfreeze_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        r = subprocess.run(DISPATCH + ["--body-file", path], cwd=ROOT, env=CHILD_ENV,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        if r.returncode == 0:
            _log("HQへ送信OK")
            return True
        _log("HQへ送信NG rc=%d err=%s" % (r.returncode, ((r.stderr or r.stdout or "").strip())[:300]))
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _days_since(stale):
    d = datetime.date.fromisoformat(stale)
    return (datetime.date.today() - d).days


def main():
    _log("=== GAS凍結監視 開始 (dry=%s) ===" % DRY)
    try:
        r = subprocess.run(EMIT, cwd=ROOT, env=CHILD_ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        _log("competitor_daily --emit タイムアウト(600秒超)。今回は判定できず(状態は据え置き)。")
        return 1

    out = (r.stdout or "") + "\n" + (r.stderr or "")
    m = FREEZE_RE.search(out)
    state = _load_state()

    if not m:
        # 凍結の痕跡なし= 上流が新しい日付を書けている(=復旧)か、そもそも正常。
        if state.get("stale"):
            _log("復旧を検知(前回凍結 %s)。復旧を1本出して状態をクリア。" % state["stale"])
            _ring("[アーモンドアイ] 競合「動画」日次の上流GASが復旧したわ。%s で止まっていた"
                  "スナップに新しい日付が入ったのを確認。凍結監視はいったん鳴り止めにするわね。"
                  "(動画の一行を朝のブリーフへ戻すのは分析部門で別途やるわ)" % state["stale"])
            if not DRY:
                _clear_state()
        else:
            _log("凍結なし=正常。鳴らさない。")
        return 0

    # 凍結中
    stale = m.group(1)
    days = _days_since(stale)
    prev_stale = state.get("stale")
    notified_days = state.get("notified_days", -999)

    if prev_stale != stale:
        reason = "新規検知"
        fire = True
    elif days - notified_days >= REPING_EVERY:
        reason = "%d日ごとの再通知" % REPING_EVERY
        fire = True
    else:
        reason = "既に%d日前に通知済み(次は%d日目以降)" % (notified_days, notified_days + REPING_EVERY)
        fire = False

    _log("凍結中: 上流=%s / %d日経過 / 判定=%s" % (stale, days, reason))

    if not fire:
        return 0

    body = ("[アーモンドアイ] 競合「動画」日次の上流GASがまだ止まってるわ。"
            "上流スナップが %s で停止したまま今日で%d日目。"
            "runCompetitorDaily(04:00)が新規行を書けていない状態が続いてる。"
            "朝の押し出しはコミュニティ・ブリーフに差し替え済みだから Chami の部屋は汚さないけれど、"
            "GAS本体の復旧はこちらの手には余るから、改修α/基盤への差配はHQでお願い。"
            "凍結が続く限り%d日ごとにここへ鳴らすわ(復旧を確認したら鳴り止める)。"
            % (stale, days, REPING_EVERY))

    if _ring(body):
        if not DRY:
            state = {"stale": stale, "notified_days": days,
                     "opened": state.get("opened") or datetime.date.today().isoformat(),
                     "last_ring": datetime.datetime.now().isoformat(timespec="seconds")}
            _save_state(state)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
