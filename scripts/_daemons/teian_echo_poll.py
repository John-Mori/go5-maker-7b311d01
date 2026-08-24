#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""提案決定 → 軍議エコー(経路B)のポーラー(プラットフォームSE / 一ノ瀬怜 / 2026-08-23)。

依頼元= イージス研究室GL(ケヴィン・デ・ブライネさん) msg 1540852033240830002。
レビュー反映= msg 1540854800458186823(返す物1〜3)。

■何をするか
  改修α(提案決定ページ)で「この作品・この④コメント・このchで投稿決定」を押すと、
  GAS `op=teian_decide` がスプレッドシートのシート「提案決定」へ1行追記する。
  **その新しい行が生えたら、軍議へ dispatch する**=これが経路B(webhook経路Aは
  チャンネル所有がChami/HQ待ちで止まっているため不採用)。

■読む相手(改修αへ別便で発注済みの読み取り口。口が生えるまではfail-openで静かに待つ)
  `?action=teian_decisions&since_row=<N>`(読み取り専用)
    → {ok:true, headers:[...], lastRow:<int>, rows:[{row:<int>, values:[...]}, ...]}
  `row` はシートの行番号そのもの。シートがまだ無い時は ok:true, lastRow:0, rows:[]。
  列(9)= 決定日時 / 候補日 / 候補ID / 作品cid / プラットフォーム / チャンネル /
          作品タイトル / ④コメント / 経路。

■受け入れ条件(デ・ブライネさん指定・C-046 / C-042)
  1. トリガーは行=実イベント。閉じ方は「その行を軍議へ配達し終えたこと」で決まる。
  2. 冪等は行番号の水位1本(teian_decide_row.txt に配達済みの最大row)。dispatch成功時だけ進める。
  3. 初回の水位は導入時点の lastRow(過去の決定を一斉に流さない)。
  4. 配達は dispatch.py --dept gunji(webhookを直接叩かない=名義・キュー・既読印が付く方)。
     ★gunjiの部門長は research-room に解決されるため --direct を明示(軍議自身が決めた経路への
       依頼元への配達=飛び級ではない)。名義は --from-dept platform-se(返す物3)。
  5. fail-open: GASが落ちている/HTMLが返る/JSONが壊れている時は、水位を進めず静かに次周期へ。
  6. 常駐にせず**5分間隔のタスクスケジューラ**で回す(register_teian_echo_task.ps1)。
     ★載せ替え経路(C-042)= タスクは毎回この .py を pythonw で新規起動する=
       コードを直せば次のtickで自動的に効く。daemon_keeper / supervise_daemons /
       preflight_daemon_lifecycle には足さない(常駐ではないため触る必要が無い)。
  7. 検査は実行で通す(test_teian_echo_poll.py)。外へ出る手(HTTP・dispatch・部屋への警報)だけ
     偽物にし、水位の判定と分岐は本物を回す。

■警報の設計(返す物1・2の反映)
  ・**ログは継ぎ目の内側にある**= run_once はログ先を wm_path と同じディレクトリに導出する。
    検査は一時ディレクトリの wm_path を渡すだけで、本番ログ(local/_state/…)を一切汚さない
    (返す物1= 検査が本番ログへ作り話を書く事故の恒久対策)。
  ・**連続失敗カウンタは1本**(teian_decide_fail.txt)。fetch失敗も配達失敗(blocked)も同じ本数に
    積む。「きれいに1周できた」時だけ0へ戻す。
  ・閾値ちょうど(既定3回)で**1回だけ**鳴らす。毎周期は鳴らさない(常に誤発火する安全網は無視される)。
  ・鳴らし先は失敗の質で分ける(返す物2):
    - **口がまだ無い(未初期化=水位ファイル未作成)の fetch 失敗**= 既知の待ち。部屋へは出さない
      (口の実装待ちの間に部屋で狼少年をやらない)。
    - **初期化後の fetch 失敗(=口が生えていたのに落ちた)/ 配達失敗(blocked)**= 本物の異常。
      **部屋へ**1回出す(イージス研究室宛)。決定は記録されているのに軍議へ届かない状態=
      うちのKPI A1(誰にも掴まれず沈黙した依頼)そのもの=看過しない。
  ・★どの質の失敗も、閾値ちょうどで **hq_open_items.md へ「入れた(確認待ち)」を1行**残す(返す物2の追い込み)。
    ローカルログ(teian_decide_poll.log)は誰も読まない=デ・ブライネさん指摘。**受け手が読む面**は
    §4.55の hq_open_items.md=生きた消費者(常駐/開いたセッション)が居なくても後から必ず読まれる。
    口待ちの静観すら「入れた(確認待ち)」として可視化する(部屋では鳴らさない=狼少年にはしない)。
    追記のみ(並行編集を壊さない)・末尾の状態印で二重に開かない/復旧時に1回だけ✅を足す。

使い方:
  python scripts/_daemons/teian_echo_poll.py            # 1周(既定・スケジューラが5分毎に呼ぶ)
  python scripts/_daemons/teian_echo_poll.py --dry-run  # 測定のみ(配達せず・水位も書かない)
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
STATE_DIR = os.path.join(LOCAL, "_state")
WATERMARK = os.path.join(STATE_DIR, "teian_decide_row.txt")
FAIL_COUNT = os.path.join(STATE_DIR, "teian_decide_fail.txt")
POLL_LOG = os.path.join(STATE_DIR, "teian_decide_poll.log")
GAS_CONFIG = os.path.join(ROOT, "scripts", "gas_deploy_config.json")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")

# ★受け手が読む durable な面(§4.55)。00_AI-HQ は 5SecMovieMaker の隣。
HQ_ROOT = os.path.join(os.path.dirname(ROOT), "00_AI-HQ")
HQ_OPEN_ITEMS = os.environ.get("GO5_HQ_OPEN_ITEMS") or os.path.join(HQ_ROOT, "status", "hq_open_items.md")

# 列名(headersが来ない/欠けている時のフォールバック順。改修αのHEADと同順)
COLUMNS = ["決定日時", "候補日", "候補ID", "作品cid", "プラットフォーム",
           "チャンネル", "作品タイトル", "④コメント", "経路"]

# 連続何回失敗したら1回だけ鳴らすか(毎周期は鳴らさない=fail-open)
ALERT_AT = 3

# ★返す物4= 未初期化のまま「時間で」滞留した時に部屋へ escalate する周期。
#   タスクは5分間隔=連続失敗数nが経過時間の代理。288回=約24時間ごとに部屋へ1回だけ。
#   増分でなく経過(滞留時間)で検知しないと「静かな死」を見逃す(HQ KPI・実例=Chami便が13日間無警報)。
POLL_INTERVAL_MIN = 5
WAIT_ALERT_EVERY = 288

# 初期化後の異常を出す部屋(発注元=この経路の運用者)
ALERT_DEPT = "aegis-gl"


# ---- 小さな入出力(水位・失敗カウンタ・ログ) --------------------------------

def _read_int(path):
    try:
        with open(path, encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _write_int(path, n):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(str(int(n)))
    os.replace(tmp, path)


def _write_why(path, why):
    """直近の失敗理由を1語だけ残す(復旧の一報がそれを読んで喋る)。書けなくても本流は止めない。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write((why or "").strip() or "不明(理由を持たない継ぎ目)")
        os.replace(tmp, path)
    except OSError:
        pass


def _reset(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _age_text(n, minutes_per=POLL_INTERVAL_MIN):
    """連続失敗数nを経過時間の言葉にする。★1時間未満は「約N分」(整数除算で常に「約0時間」になる穴の恒久対策)。

    実害= 閾値ちょうど(n=3=15分)の警報が「約0時間待機している」と出て、受け手が滞留量を読めない
    (2026-08-23 14:47 にイージス研究室へ実際にそう届いた便がある)。
    """
    m = int(n) * int(minutes_per)
    return f"約{m // 60}時間" if m >= 60 else f"約{m}分"


def _log(line, log_path=POLL_LOG):
    """運用ログへ1行。★log_path を引数化してある=検査は継ぎ目の内側で逃がせる(返す物1)。"""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")
    print(line)


# ---- 外へ出る手(テストで偽物に差し替える3つの継ぎ目: fetch / deliver / alert) ----

def exec_url():
    """gitignore下の gas_deploy_config.json から exec URL を読む(実体はこのPCにある)。"""
    with open(GAS_CONFIG, encoding="utf-8") as f:
        return json.load(f)["execUrl"]


# ★★2026-08-25 イージス研究室。**警報が原因を言えなかった**ので足した。
#   事故= 00:52 に「3回連続で読めない」が鳴ったが、`teian_decide_poll.log` の最終行は
#   **2026-08-23 08:02**(=初期化の行)のまま。本物の失敗の枝が logf を1行も書いていなかった。
#   受け取った側は「404なのか / タイムアウトなのか / JSONが壊れたのか」を**警報から知る術が無く**、
#   同じ口を自分で叩き直すまで何も分からない(実測でそうなった)。
#   → 失敗の**理由を1語**だけ持ち回る。返り値の契約(None)は変えない=呼び手は1行も変わらない。
_LAST_FAIL = ""                              # 直近の fetch 失敗の理由(1語+補足)


def last_fetch_fail():
    """直近の `fetch_decisions` が None を返した理由。成功した後は空文字。

    語= config(execUrlが読めない)/ http-<コード or 例外名> / not-json(HTML等)
        / json-broken / ok-false / rows-missing / lastrow-bad。
    ★継ぎ目の偽物(検査)を使った時は空のまま= 呼び手は「不明」として扱う。
    """
    return _LAST_FAIL


def fetch_decisions(since_row, timeout=25, retry_timeout=90, retry_wait=3):
    """GASの読み取り口を叩く。**継ぎ目#1(HTTP)**。

    正常= {ok:true, lastRow:int, rows:[...]} の dict を返す。
    HTTP失敗 / HTMLが返る / JSONが壊れている / ok!=true / 構造が欠ける = None(=fail-open)。
    ★ここで例外を投げない=呼び手(run_once)は None を「静かに次周期へ」に倒す。
    ★None を返す時は **必ず `_LAST_FAIL` に理由を置く**(空のまま返すと警報がまた黙る)。

    ★★2026-08-25 イージス研究室= **転送層の失敗(http-*)は1周の中で1回だけ引き直す。**
      実測(同じURLへ10連打・8/25 01:24)= 1〜4回目が27秒超で TimeoutError、5回目以降は
      2.2秒で成功。GASは呼ばれない間があくと立ち上げに25秒以上かかる= 5分間隔の巡回は
      毎回**冷えた所を踏む**。1本目が立ち上げを兼ねるので、2本目は温まった所に当たる。
      2本目だけ待ち時間を伸ばす(retry_timeout)のは、立ち上げそのものが25秒に収まらない
      ケースを1本目の短さで切り捨てないため。引き直すのは http-* だけ=
      config-/not-json/ok-false は設定と実装の誤りで、引き直しても同じ答えしか返らない。
    """
    global _LAST_FAIL

    def fail(why):
        global _LAST_FAIL
        _LAST_FAIL = why
        return None

    try:
        base = exec_url()
    except Exception as e:                  # noqa: BLE001
        return fail(f"config-{type(e).__name__}")
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}action=teian_decisions&since_row={int(since_row)}"
    raw = None
    for attempt, tmo in enumerate(((timeout, retry_timeout) if retry_timeout else (timeout,))):
        if attempt:
            time.sleep(retry_wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "go5-teian-echo/1.0"})
            with urllib.request.urlopen(req, timeout=tmo) as r:
                raw = r.read().decode("utf-8", errors="replace").strip()
            break
        except urllib.error.HTTPError as e:
            why = f"http-{e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            why = f"http-{type(e).__name__}"
        _LAST_FAIL = why
    if raw is None:
        return fail(_LAST_FAIL)             # 引き直しても駄目だった=最後の理由をそのまま出す
    if not raw or raw[0] not in "{[":       # HTMLエラーページ等はJSONで始まらない
        return fail("not-json")
    try:
        data = json.loads(raw)
    except Exception:                       # noqa: BLE001
        return fail("json-broken")
    if not isinstance(data, dict) or data.get("ok") is not True:
        return fail("ok-false")
    if not isinstance(data.get("rows"), list):
        return fail("rows-missing")
    try:
        int(data.get("lastRow"))
    except (TypeError, ValueError):
        return fail("lastrow-bad")
    _LAST_FAIL = ""
    return data


def deliver_row(row, dry_run=False):
    """1行を軍議へ配達する。**継ぎ目#2(dispatchのPopen)**。成功=True。

    dispatch.py は全成功で exit 0 を返す。0以外は失敗として水位を進めない。
    """
    fields = row_fields(row)
    body = build_body(fields, row.get("row"))
    cmd = [sys.executable, DISPATCH, "--dept", "gunji",
           "--from", "提案決定→軍議エコー(プラットフォームSE)",
           "--from-dept", "platform-se",   # 出しているのはプラットフォームSEの機構(返す物3)
           "--direct",              # gunjiの部門長=research-room に解決されるため。依頼元(軍議)への配達。
           "--audience", "ai",      # AI(部門)宛の機械エコー
           "--body", body]
    if dry_run:
        print("  [dry-run] gunji へ配達(実際には出さない):")
        print("  " + body.replace("\n", "\n  "))
        return True
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=120,
                           encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"  [配達失敗] row={row.get('row')} {type(e).__name__}: {e}")
        return False
    if p.returncode != 0:
        print(f"  [配達失敗] row={row.get('row')} exit={p.returncode} {(p.stdout or '')[-200:]}")
        return False
    return True


def alert_room(reason, dept=ALERT_DEPT, recovered=False):
    """初期化後の異常を**部屋へ**1回出す。**継ぎ目#3(dispatchのPopen)**。返り値は使わない。

    ★run_once が「閾値ちょうど」でしか呼ばない=毎周期は鳴らさない。
    ★recovered=True= 復旧の一報(鳴らした警報の後始末)。警報を出した部屋に「戻った」も出す
      =片側だけだと部屋には壊れたままに見え、毎回人が測り直す羽目になる(2026-08-23の実例)。
    """
    if recovered:
        body = ("【提案決定→軍議エコー・復旧】" + reason + "\n"
                "(自動: teian_echo_poll / 直前に出した警報の後始末・1回だけ)")
    else:
        body = ("【提案決定→軍議エコー・警報】" + reason + "\n"
                "(自動: teian_echo_poll / これは連続失敗が閾値に達した時だけの1回・毎周期は鳴らさない)")
    try:
        subprocess.run([sys.executable, DISPATCH, "--dept", dept,
                        "--from", "提案決定→軍議エコー(プラットフォームSE)",
                        "--from-dept", "platform-se",
                        "--audience", "ai", "--body", body],
                       capture_output=True, timeout=120,
                       encoding="utf-8", errors="replace")
    except Exception:
        pass          # 警報の送信失敗で本体を巻き添えにしない


def _last_state(content, kind):
    """teian-echo:<kind> の最後の状態を返す('OPEN'/'RESOLVED'/None)。追記のみで開閉を判定する。"""
    state = None
    tag = f"teian-echo:{kind} "
    for line in content.splitlines():
        i = line.find(tag)
        if i < 0:
            continue
        rest = line[i + len(tag):].strip()
        if rest.startswith("OPEN"):
            state = "OPEN"
        elif rest.startswith("RESOLVED"):
            state = "RESOLVED"
    return state


def note_open_item(kind, text, resolve=False, path=HQ_OPEN_ITEMS):
    """受け手が読む durable な面(hq_open_items.md)へ1行。**継ぎ目#4**。

    ★追記のみ=HQが並行して書くファイルを壊さない(C-003 / 並行編集事故の回避)。
      開閉は「末尾の teian-echo:<kind> 状態印」で表す=二重に開かない/復旧時に1回だけ✅。
    - resolve=False: 直近が OPEN でなければ「入れた(確認待ち)」を追記(閾値ちょうどで1回)。
    - resolve=True : 直近が OPEN の時だけ「✅復旧」を追記(復旧時に1回)。
    戻り値= 追記したか(True/False)。送信失敗で本体は巻き添えにしない。
    """
    try:
        content = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    except Exception:
        content = ""
    last = _last_state(content, kind)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    if resolve:
        if last != "OPEN":
            return False
        block = (f"\n<!-- teian-echo:{kind} RESOLVED {stamp} -->\n"
                 f"- ✅ {stamp} 提案決定→軍議エコー(経路B) 復旧: {text}(platform-se)\n")
    else:
        if last == "OPEN":
            return False
        block = (f"\n## {stamp} 提案決定→軍議エコー(経路B) = 入れた(確認待ち) [teian-echo:{kind}]\n"
                 f"<!-- teian-echo:{kind} OPEN {stamp} -->\n"
                 f"- {text}(自動: teian_echo_poll / platform-se)\n")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(block)
    except Exception:
        return False
    return True


# ---- 純粋な組み立て(値のマッピングと本文) ----------------------------------

def row_fields(row):
    """{列名: 値} を作る。headersが来ていればそれで、無ければ固定順(COLUMNS)で対応づける。"""
    values = row.get("values") or []
    headers = row.get("_headers") or COLUMNS
    out = {}
    for i, name in enumerate(headers):
        out[str(name)] = values[i] if i < len(values) else ""
    return out


def build_body(fields, rownum):
    """軍議へ渡す本文。チャンネル名・作品タイトル・④コメント・cid・決定日時(JST)を必ず含む。"""
    g = lambda k: (fields.get(k) or "").strip() if isinstance(fields.get(k), str) else fields.get(k, "")
    return (
        "【提案決定→軍議エコー(経路B)】投稿決定が1件記録されました。\n"
        f"- チャンネル: {g('チャンネル')}\n"
        f"- 作品: {g('作品タイトル')}(cid={g('作品cid')})\n"
        f"- ④コメント: {g('④コメント')}\n"
        f"- プラットフォーム: {g('プラットフォーム')}\n"
        f"- 決定日時(JST): {g('決定日時')}\n"
        f"- 候補日/候補ID: {g('候補日')} / {g('候補ID')}\n"
        f"- 経路: {g('経路')}\n"
        f"(自動配達: 提案決定シート row={rownum} / 経路B・水位1本)"
    )


# ---- 本体の判定と分岐(テストは本物を回す) ----------------------------------

def run_once(fetch, deliver, alert=None, note=None, wm_path=WATERMARK, fail_path=FAIL_COUNT,
             alert_at=ALERT_AT, wait_alert_every=WAIT_ALERT_EVERY, log_path=None):
    """1周分の水位ロジック。fetch/deliver/alert/note は継ぎ目(テストで偽物を注入)。

    ★log_path は既定で wm_path と同じディレクトリへ導出する=検査は一時ディレクトリの
      wm_path を渡すだけで本番ログを汚さない(返す物1の恒久対策)。
    ★note は「受け手が読む durable な面(hq_open_items.md)」への追記=継ぎ目#4。
      検査は偽物を注入するので本番の hq_open_items.md を1バイトも触らない。

    戻り値= {"status": ..., "watermark": int, "delivered": int, "fails": int}
      status: "init"(初回=水位だけ置く) / "ok"(配達した/対象なし・カウンタ0へ) /
              "fail-open"(GASが読めない=水位据え置き) / "blocked"(配達失敗で水位据え置き)
    """
    if alert is None:
        alert = alert_room
    if note is None:
        note = note_open_item
    if log_path is None:
        log_path = os.path.join(os.path.dirname(wm_path) or STATE_DIR, "teian_decide_poll.log")
    logf = lambda line: _log(line, log_path)

    initialized = os.path.exists(wm_path)
    since = 0 if not initialized else (_read_int(wm_path) or 0)

    # ★復旧の一報の判定材料= この周に入る前の連続失敗数と、その時「部屋で実際に鳴っていたか」。
    #   鳴っていない失敗(未初期化の既知の待ち・閾値未満)に復旧を出すと、警報より復旧の方が多くなる。
    prev_fails = _read_int(fail_path) or 0
    alarm_had_rung = (prev_fails >= alert_at) if initialized else \
                     bool(wait_alert_every) and prev_fails >= wait_alert_every
    # ★★2026-08-25 イージス研究室= **復旧の一報も理由を持ち回る。**
    #   8/25 01:17 に届いた復旧便は「原因は不明のまま自然復旧した」と書いてあったが、
    #   同じ時刻の運用ログは理由(http-TimeoutError / http-404)を**知っていた**=
    #   56f3c54 で警報側だけ直し、復旧側は「原因を言えない」まま残っていた(同じ穴の1つ隣)。
    why_path = fail_path + ".why"
    prev_why = ""
    try:
        with open(why_path, encoding="utf-8") as f:
            prev_why = f.read().strip()
    except OSError:
        pass

    def ring_recovery(what):
        if alarm_had_rung:
            alert(f"{what}(連続{prev_fails}回・{_age_text(prev_fails)}ぶり)。"
                  f"読み取り口も配達も戻っている。直前の失敗理由="
                  f"{prev_why or '不明(理由を持たない継ぎ目)'}。同じ形で再発したら追う。",
                  recovered=True)

    data = fetch(since)
    if data is None:
        # fail-open: 水位を進めない。連続失敗カウンタに積む。
        n = (_read_int(fail_path) or 0) + 1
        _write_int(fail_path, n)
        _write_why(why_path, last_fetch_fail())   # 復旧の一報が理由を言えるように残す
        at_threshold = (n == alert_at)
        # n は5分刻み=経過時間の代理。周期ちょうど(約24h,48h…)を「時間で滞留」の合図に使う。
        at_period = bool(wait_alert_every) and (n % wait_alert_every == 0)
        if initialized:
            # 口は生えていたのに落ちた=本物の異常。★閾値ちょうど **または** 周期(約24h)ごとに部屋へ1回。
            #   n==alert_at の一発だけだと、口が落ちたまま続くと2度と鳴らない=静かな死
            #   (デブライネさん指摘 2026-08-23 / C-041=一度の観測を状態の代理にするな)。
            # ★★2026-08-25 イージス研究室= **失敗した周は必ず1行ログを残す**。
            #   ここは今まで alert/note しか呼んでおらず、鳴らない周(閾値未満・閾値を跨いだ後)は
            #   跡が1行も残らなかった= 00:52 の警報を受けた時、ログの最終行は 8/23 08:02 のまま
            #   で「いつから・何回・何が原因で」が**警報からも台帳からも分からなかった**。
            why = last_fetch_fail() or "不明(理由を持たない継ぎ目)"
            logf(f"[fail-open] 提案決定エコー: 読み取り口が読めない({n}回連続・理由={why}・"
                 f"水位={since}据え置き)。")
            if at_threshold or at_period:
                alert(f"GASの読み取り口が{n}回連続で読めない(理由={why})。"
                      f"水位={since}のまま{_age_text(n)}待機している。")
                note("read-fail", f"GASの読み取り口が{n}回連続で読めない(理由={why})。"
                                  f"水位={since}のまま。")
        else:
            # 口がまだ無い=既知の待ち。閾値では部屋で鳴らさない(狼少年回避)=ログ+受け手が読む面に1回。
            if at_threshold:
                logf(f"[fail-open] 提案決定エコー: 読み取り口がまだ無い(既知・{n}回連続)。"
                     f"水位ファイルは作らずに待機。")
                note("bootstrap-wait",
                     f"経路Bは稼働中・改修αの読み取り口(?action=teian_decisions)がまだ無いため"
                     f"fail-openで静観中(連続{n}回・水位ファイルは未作成・部屋では鳴らさない)。")
            # ★返す物4= 未初期化のまま「時間で」滞留したら周期ちょうどで部屋へ1回escalate。
            #   n==alert_at の1回きりだと、口が生えないまま忘れられても跡は最初の1行だけ=静かな死。
            if at_period:
                alert(f"提案決定→軍議エコー(経路B)は改修αの読み取り口(?action=teian_decisions)が"
                      f"無いまま{_age_text(n)}(連続{n}回)待ち続けている。決定は提案決定シートに溜まるのに"
                      f"誰も『まだ届いていない』と気づけない=読み取り口の実装が忘れられていないか確認してほしい。")
        return {"status": "fail-open", "watermark": since, "delivered": 0, "fails": n}

    if not initialized:
        # 初回の水位= 導入時点の lastRow。過去の決定は一斉に流さない。きれいに1周=カウンタ0へ。
        last = int(data["lastRow"])
        _write_int(wm_path, last)
        _reset(fail_path)
        logf(f"[初期化] 提案決定エコーの水位を lastRow={last} に置いた(既存の決定は配達しない)。")
        note("bootstrap-wait", f"改修αの読み取り口が生えて水位を lastRow={last} に初期化した。", resolve=True)
        ring_recovery(f"改修αの読み取り口が生えて水位を lastRow={last} に初期化した")
        return {"status": "init", "watermark": last, "delivered": 0, "fails": 0}

    headers = data.get("headers") if isinstance(data.get("headers"), list) else None
    rows = sorted(data.get("rows", []), key=lambda r: int(r.get("row", 0)))
    delivered = 0
    for row in rows:
        rownum = int(row.get("row", 0))
        if rownum <= since:
            continue               # ★冪等の核: 水位以下は配達済み=二度出さない
        if headers:
            row = dict(row, _headers=headers)
        if not deliver(row):
            # 配達に失敗した行で止める=水位をその手前に留める(再送は最大1行)。
            # ★blocked も同じカウンタに積む(返す物2)。決定は記録されているのに軍議へ届かない=沈黙させない。
            n = (_read_int(fail_path) or 0) + 1
            _write_int(fail_path, n)
            _write_why(why_path, f"配達失敗(dispatch・row={rownum})")
            logf(f"[据え置き] row={rownum} の配達に失敗。水位={since} のまま次周期へ(連続{n}回)。")
            # ★閾値ちょうど **または** 周期(約24h)ごとに部屋へ1回。配達不能が続いても
            #   n==alert_at の一発だけだと2度と鳴らない=静かな死(デブライネさん指摘 2026-08-23 / C-041)。
            if n == alert_at or (wait_alert_every and n % wait_alert_every == 0):
                alert(f"決定は記録されているのに軍議へ配達できない状態が{n}回続いている(row={rownum}・{_age_text(n)})。"
                      f"dispatch側を確認してほしい。水位={since}のまま。")
                note("deliver-blocked",
                     f"決定は記録されているのに軍議へ配達できない状態が{n}回(row={rownum})。水位={since}のまま。")
            return {"status": "blocked", "watermark": since, "delivered": delivered, "fails": n}
        since = rownum
        _write_int(wm_path, since)  # ★1行ずつ進める=途中で落ちても再送は最大1行
        delivered += 1

    _reset(fail_path)               # きれいに1周できた=連続失敗カウンタを畳む
    _reset(why_path)                # ★理由は復旧の一報を出した「後」に消す(下の ring_recovery は prev_why を持っている)
    # 開いていた警報を受け手が読む面で閉じる(復旧時に各種1回だけ✅)。
    for k in ("read-fail", "deliver-blocked", "bootstrap-wait"):
        note(k, "1周を正常に完了(連続失敗カウンタを畳んだ)。", resolve=True)
    # ★部屋で鳴らした警報にだけ、部屋で「戻った」を返す(durable面のRESOLVEDだけだと部屋には壊れたままに見える)。
    ring_recovery(f"1周を正常に完了した(水位={since}・この周で{delivered}行配達)")
    return {"status": "ok", "watermark": since, "delivered": delivered, "fails": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="測定のみ(軍議へ配達せず・水位も書かない)")
    a = ap.parse_args()

    if a.dry_run:
        since = _read_int(WATERMARK)
        data = fetch_decisions(0 if since is None else since)
        if data is None:
            print("[dry-run] GASの読み取り口が読めない(fail-open該当)。水位は据え置き。")
            return 0
        rows = sorted(data.get("rows", []), key=lambda r: int(r.get("row", 0)))
        new = [r for r in rows if int(r.get("row", 0)) > (since or 0)]
        print(f"[dry-run] lastRow={data.get('lastRow')} 現水位={since} "
              f"新規{len(new)}行(初回なら水位を lastRow に置くだけ・配達0)")
        headers = data.get("headers") if isinstance(data.get("headers"), list) else None
        for r in new:
            deliver_row(dict(r, _headers=headers) if headers else r, dry_run=True)
        return 0

    res = run_once(fetch_decisions, deliver_row)
    if res["status"] in ("ok", "init") and res["delivered"]:
        _log(f"[配達完了] {res['delivered']}行を軍議へ配達。水位={res['watermark']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
