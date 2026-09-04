# -*- coding: utf-8 -*-
"""GAS(競合"動画"日次の上流)が凍結し続ける間だけ鳴らす、分析部門・自室の監視口。

背景(HQ-0230 / DISPATCH-shorts-analyst-1788307335393):
  2026-09-02 の「差し替え」(msg 1544486499653910629)で毎朝の押し出しを競合"動画"日次から
  競合"コミュニティ"ブリーフへ替えた。その結果、上流(競合"動画"日次)が
  8/18 で止まっている事実を毎朝知らせていた唯一の口も一緒に黙った(C-044= 監視だけ先に降りた)。
  → 凍結が続く間だけ・毎朝同じにならない形で鳴る口を、分析部門の自室で作り直す(C-027)。

Chami が却下したのは「毎朝まったく同じ文が Chami の部屋に出る」こと(msg 1544485816288419840)。
  だからこの口は:
    - 鳴らす先= Chami の部屋ではなく 研究室HQ(AI便)。復旧はGAS本体=改修α/基盤の手番で、HQが差配する。
    - 頻度= 凍結を新規に検知した初回に1本、その後は凍結が続く限り7日ごとに1本だけ(週次リマインド)。
      毎日は鳴らさない(=Chamiが嫌った"毎朝同じ"の再来を避ける)。文面には経過日数を入れ、鳴るたびに中身が変わる。
    - 復旧= 上流に前回停止より新しい日付が1つ実際に入ったのを観測できた時だけ「復旧した」を1本だけ
      出して状態をクリア(経路の別は問わない。文面が消えただけ=②部分失敗/例外/文面変更では鳴り止めない=穴B)。
  凍結判定は rc に頼らない(--emit は凍結でも rc=0 を返す=2026-09-02 実測)。
  competitor_daily.py --emit の stdout から凍結の日付を拾って判定する。lag>=2 の「上流スナップが
  YYYY-MM-DD で停止」だけでなく lag==1 の「本日分の競合_日次行が未着(最新スナップ=YYYY-MM-DD…)」も拾う
  (=再凍結の初日から鳴る=穴A)。復旧は正常時サマリ先頭「競合ランキング分析 YYYY-MM-DD(…」の日付で判定する。

実行= 毎朝08:00の常駐(competitor_daily.ps1)が community_daily_push.py の後に本スクリプトを呼ぶ。
状態= local/gas_freeze_watch.state(JSON)/ 監視の全実行ログ= local/gas_freeze_watch.log(UTF-8・毎回書く=沈黙日でも実物が残る)。
--dry: 判定と本文組み立てまで走らせるが HQ へは出さず、鳴らす予定の本文を stdout に見せるだけ(配線検証用)。
"""
import os, sys, re, json, subprocess, datetime, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# ★部門名は台帳(00_AI-HQ/org_registry.yml の display_ja)が正本= ここに手書きしない
#   (2026-09-04 配線。改称騒ぎ= Chamiが「5chシステム構築部門α」へ改名し同日10:22に撤回した。
#    次に名前が動いても手書きを掃かずに済むよう、ここで台帳へ寄せた。dept_ja は台帳の
#   mtime を都度見るので、次に改称されてもこのファイルは触らずに済む)。
#   fail-safe= 台帳が読めなければスラッグをそのまま返す(便そのものは絶対に落とさない)。
sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
try:
    from dept_names import dept_ja                     # noqa: E402
except Exception:                                      # noqa: BLE001
    def dept_ja(slug, with_slug=False):
        return slug
PY = sys.executable or "python"
EMIT = [PY, os.path.join("scripts", "analysis", "competitor_daily.py"), "--emit"]
# 鳴り先= HQ(復旧の差配) + research-room(=ad研究室・この凍結を閉じる責任を持つ当室の依頼元。
#   REQ-research-room-de08ad55fc / Chami 2026-08-22「これはインシデントよ」認定案件。
#   HQだけに鳴ると閉じる側=モドリッチに何も届かない=2026-09-03/04が誰にも鳴っていなかった真因)。
#   dispatch.py は --dept a,b,c で同報できる(2026-09-04 モドリッチ依頼で追加)。
DISPATCH = [PY, os.path.join("scripts", "llm", "dispatch.py"),
            "--dept", "hq,research-room", "--from-dept", "shorts-analyst",
            "--from", "アーモンドアイ(分析部門)", "--audience", "ai"]
STATE = os.path.join(ROOT, "local", "gas_freeze_watch.state")
LOG = os.path.join(ROOT, "local", "gas_freeze_watch.log")
DRY = "--dry" in sys.argv
REPING_EVERY = 7  # 凍結が続く間の再通知間隔(日)
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
# 凍結の日付を2文面とも拾う(穴A)= lag>=2「上流スナップが YYYY-MM-DD で停止」/ lag==1「最新スナップ=YYYY-MM-DD」。
#   どちらでも group(1) に停止の起点日が入る。正常時サマリ「競合ランキング分析 …」や②(部分失敗)には
#   この2語が出ないので誤検知しない。
FREEZE_RE = re.compile(r"(?:上流スナップが|最新スナップ=)\s*(\d{4}-\d{2}-\d{2})")
# 復旧はpositiveに判定する(穴B)= 正常時サマリ先頭「競合ランキング分析 YYYY-MM-DD(…」の現在スナップ日。
RECOVER_RE = re.compile(r"競合ランキング分析\s*(\d{4}-\d{2}-\d{2})")


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
        # 凍結文面なし。ただし「文面が消えた」だけでは復旧と断じない(穴B)。②部分失敗・例外・
        #   タイムアウト・文面変更でも m は None になり得る。前回 stale より新しい snapshotDate を
        #   1つ実際に観測できた時だけ復旧としてクリアし、それ以外は状態を据え置く(誤って鳴り止めない)。
        if state.get("stale"):
            rm = RECOVER_RE.search(out)
            fresh = rm.group(1) if rm else None
            if fresh and fresh > state["stale"]:
                _log("復旧を検知(前回凍結 %s → 新スナップ %s)。復旧を1本出して状態をクリア。"
                     % (state["stale"], fresh))
                _ring("[アーモンドアイ] 競合「動画」日次の上流に新しい日付が入ったわ(経路の別は問わない)。"
                      "%s で止まっていたスナップが %s まで進んだのを確認。凍結監視はいったん鳴り止めにするわね。"
                      "(動画の一行を朝のブリーフへ戻すのは分析部門で別途やるわ)" % (state["stale"], fresh))
                if not DRY:
                    _clear_state()
            else:
                why = ("新スナップ %s は前回停止 %s より新しくない" % (fresh, state["stale"])) if fresh \
                      else "正常時サマリ(競合ランキング分析 行)を取れず=②部分失敗/例外/文面変更のいずれか"
                _log("復旧未確認のため状態据え置き(%s)。" % why)
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

    body = ("[アーモンドアイ] 競合「動画」日次の上流がまだ止まってるわ。"
            "上流スナップが %s で停止したまま今日で%d日目。"
            "上流(競合_日次)に新規行が入らない状態が続いてる(収集経路の別は問わない="
            "2026-09-04以降はPC側 go5_comp_daily 05:30 が主・GAS 04:00 はフォールバック)。"
            "朝の押し出しはコミュニティ・ブリーフに差し替え済みだから Chami の部屋は汚さないけれど、"
            "どの経路でも本日分が書けていない=復旧はこちらの手に余るから、%s/基盤への差配はHQでお願い。"
            "凍結が続く限り%d日ごとにここへ鳴らすわ(復旧を確認したら鳴り止める)。"
            % (stale, days, dept_ja("system-engineer"), REPING_EVERY))

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
