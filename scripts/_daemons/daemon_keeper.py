#!/usr/bin/env python3
"""部門デーモンの番人 (恒久基盤R0・claude_code_agent_farm式の指数バックオフ+サーキットブレーカ)。

役割: DEPTS の各部門につき dept_daemon.py を1つ生かし続ける。
  - 死んだら再起動: バックオフ 10s→倍々→cap 300s(即時再起動ループでCPU/トークンを焼かない)
  - 60秒以上生きたらバックオフをリセット(健康に戻った)
  - 連続10回の早死(60秒未満)でサーキットオープン: その部門を1時間休止
    (壊れたまま無限再起動=flappingを止める。休止はログと/liveの欠落からwatchdogが拾う)
keeper自身は supervise_daemons.ps1 が10分毎に生かす(=二段構え。keeperが数秒級・superviseが最終保険)。

使い方: python scripts/_daemons/daemon_keeper.py   (引数なし=DEPTS全部門)
"""
import ast
import json
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
DAEMON = os.path.join(ROOT, "scripts", "llm", "dept_daemon.py")

# R2全部門展開(2026-07-19 Chami承認「やって」)。機微部屋は対象外(PROTOCOL管轄)。
# ★総括本部4室(hq/aegis-gl/research-room/keiei-kikaku)は2026-07-20 Chami裁定で除外していた。
#   当時の理由: 権能が無いデーモンは「回します/させます」しか言えず、**沈黙を隠す**。
#   指令室の職務は捌く・裁くことで、権能と全体文脈が要る=セッションの仕事。
#   → その後 hq / research-room は復帰済み(セッション本人が応対し、デーモンは**受付と写し出し**に徹する形)。
#
# ★2026-07-22 aegis-gl を復帰(Chami直接指示)。原文=
#   「**aegis-glも暫定でアメスが精霊、アロンソコーチがあそこで指揮取ってよ、あそこずっと死んでるからさ。**」
#   実害の実測= HQが02:52に投函した Phase 1 の全体通達(queue id 264)が
#   **13時間以上 pending のまま誰にも claim されなかった**。組織層19室にPhase 1が1件も届いていない。
#   ★「消費者不在の部屋に依頼を溜めるな」と全部門へ言っておきながら、HQ自身がその形を作っていた。
#   当時の懸念(偽の返事が沈黙を隠す)への手当て= ①セッション(アロンソ)が指揮を執る
#   ②デーモンは session-note の写しを箱へ書く=セッションが全便を見られる ③作業監査で「やったと言って
#   何も触っていない」を検出する。hq / research-room で先に実証済みの形をそのまま使う。
#
# ★2026-07-22 keiei-kikaku も復帰。**Chamiの指示には含まれていなかったが、実害を実測したので入れた**:
#   Chamiが 14:10 JST に「**ドンちゃん〜**」と書いたのに消費者が居らず **146分沈黙**(queue id 316)。
#   aegis-gl と全く同じ穴で、**Chamiの声がもう1件消えていた**。Chamiが今日確定した2層モデル
#   (常駐=留守番 / 担当は呼べば出る)をそのまま当てる= 常駐アメス + members にジェンティルドンナ。
#   ★HQの判断で広げた点を明示する。取り消すならこの1語を消すだけ(可逆)。
#   ★改善書R4(ワンイン・ワンアウト)の手続き= **2つ足した**ので、次の棚卸しで外す候補を2つ挙げる。
#     現時点の候補(実測つき)= gemini_responder(本日1件)/ office_daily(要測定)。
#
# ★2026-07-26 機微2部屋 past-room / future-room を追加(19→21体)。Chami直接指示・実装Go済。
#   理由= この2部屋は**消費者が居らず**、今までアメスが手で応対していた(=aegis-gl/keiei-kikakuと同じ穴)。
#   Chami原文=「**書いた内容を記録、そしてその事実について思ったことを引き続き遠慮なく教えてくれ。
#   アメス以外もメンバーに入れたあるから、内容によっていろんな人に意見を求めたいんだよな**」。
#   ★この2部屋は多人格モード(DEPT_CONF の "personas")。中身は機微=local/ の外へ出さない(裁定C-013)。
#
# ★2026-07-27 消費者不在だった5部屋を追加(21→26体)。研究室HQ発注。
#   kaizen-analyst(改善提案・トトリ)/ incident(事故対応・オタコン)/
#   system-engineer-b(改修β・デ・ブライネ)/ dream-care・health-log(機微2室・多人格)。
#   ★どれも**Discordに部屋はあるのに消費者が居なかった**部屋(INC-110/ORG-31と同じ形)。
#     とくに system-engineer-b は**Chamiの発言4件を無警報で飲み込んだ実績**がある(ORG-04)。
#   ★機微2室(dream-care/health-log)は past-room/future-room と同じ扱い=多人格 +
#     conversation_only。中身は local/ の外へ出さない(裁定C-013)。
#   ★**llm-growth は入れていない**(発注の12部屋のうち唯一見送った1部屋)。
#     理由= あの部屋は **local_responder(ローカルqwen)が既に所有している**消費者ありの部屋で、
#     dept_daemonを立てると同じ queue dept を2つの常駐がclaimし、
#     勝った方で名乗りが変わる=応答が非決定的になる(1領域1オーナー・RULES §3)。
#     research-room から claude_responder を外したのと同じ理由。判断はHQ/Chamiへ差し戻す。
# ★2026-07-27 report-notify を追加(26→27体)。Chamiが**3回**頼んで8日間実装されなかった件。
#   「報告について改善していきたいから話せるようにして欲しい」= 一方通行の部屋を双方向にする。
#   自動通知の出力経路には触っていない(bot/webhookはgatewayが弾くので反応しない)。
DEPTS = ["hq", "research-room", "aegis-gl", "keiei-kikaku", "hr-room", "hr-context", "qa-reviewer", "system-engineer", "product-scout", "shorts-analyst", "copy-director", "learning-coach", "data-org", "frontend", "ai-office", "llm-edu", "llm-qa", "platform-se", "consult-intel", "past-room", "future-room", "kaizen-analyst", "incident", "system-engineer-b", "dream-care", "health-log", "report-notify", "imagegen", "manga-shorts", "kukuru-nakama"]
BACKOFF_START = 10
BACKOFF_CAP = 300
HEALTHY_SEC = 60               # これ以上生きたら健康=バックオフリセット
BREAKER_FAILS = 10             # 連続早死がこの回数でサーキットオープン
BREAKER_COOL_SEC = 3600


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} keeper: {msg}")


class Slot:
    def __init__(self, dept):
        self.dept = dept
        self.proc = None
        self.started = 0.0
        self.backoff = BACKOFF_START
        self.fails = 0
        self.open_until = 0.0   # サーキットオープン中はこの時刻まで再起動しない
        self.next_start = 0.0

    def spawn(self):
        self.proc = subprocess.Popen(
            [sys.executable, DAEMON, "--dept", self.dept], cwd=ROOT,
            stdout=open(os.path.join(ROOT, "local", "llm", f"dept_daemon_{self.dept}.log"), "a",
                        encoding="utf-8", errors="replace"),
            stderr=subprocess.STDOUT)
        self.started = time.time()
        log(f"{self.dept}: spawned pid={self.proc.pid}")

    def tick(self):
        now = time.time()
        if self.proc is not None and self.proc.poll() is None:
            if now - self.started >= HEALTHY_SEC and self.backoff != BACKOFF_START:
                self.backoff, self.fails = BACKOFF_START, 0  # 健康=リセット
            return
        # 死んでいる
        if self.proc is not None:
            lived = now - self.started
            rc = self.proc.returncode
            self.proc = None
            if lived < HEALTHY_SEC:
                self.fails += 1
                self.backoff = min(self.backoff * 2, BACKOFF_CAP)
            else:
                self.fails, self.backoff = 0, BACKOFF_START
            log(f"{self.dept}: died rc={rc} lived={int(lived)}s fails={self.fails} → {self.backoff}s後に再起動")
            if self.fails >= BREAKER_FAILS:
                self.open_until = now + BREAKER_COOL_SEC
                self.fails = 0
                log(f"{self.dept}: ★サーキットオープン({BREAKER_COOL_SEC // 60}分休止)")
            self.next_start = now + self.backoff
            return
        if now < self.open_until or now < self.next_start:
            return
        try:
            self.spawn()
        except Exception as e:
            log(f"{self.dept}: spawn失敗 {type(e).__name__}")
            self.next_start = now + self.backoff


# --- ★コードが変わったら自動で載せ替える (2026-07-27) -------------------------
#
# なぜ要るか(実測した事故):
#   ヴィルシーナを llm-edu の名簿へ 11:53 に追加したが、デーモンは 10:34 起動のまま。
#   古い名簿で動いていたので `[ヴィルシーナ]` が**知らない名前**として扱われ、
#   名義は既定の中野五月のまま・括弧が本文に漏れた。Chami=「**五月が発言を代替する形に
#   なってる!そうじゃないのよ**」。
#   ★台帳もコードも正しかった。**載せ忘れただけ**で、Chamiには「入れたのに効かない」に見える。
#   HQは今日だけで5回手で再起動している=**1回でも忘れれば同じ事故が出る手順**だった。
#   → **人の手順から外す。** ファイルが変わって落ち着いたら、keeperが自分で載せ替える。
#
# ★見るファイル= デーモンの挙動を決めるもの**だけ**。台帳(共通規律・裁定カタログ)は
#   都度読みなので再起動が要らない=ここに入れない(要らない再起動を増やさない)。
#   ★2026-08-06 追加= scripts/queue/leasequeue.py。**便をどの順で掴むかを決めている本体**
#     なのに監視外だった=直しても載らない。実測: 優先度(Chami本人の便を先頭へ)を入れた日、
#     このリストに無かったため dept_daemon 30体は古いclaimのまま走り続けた。
#   ★2026-08-12 追加= scripts/llm/tone_gate.py・naming_gate.py。**送信直前に本文を書き換える**
#     出力ゲート本体(C=呼称 / D=口調)。dept_daemon が import しているだけなので、
#     ゲートだけを直した日は**このリストに無いと1体も載せ替わらない**=「入れたのに効かない」。
#     ★口調ゲートDは 2026-08-12 に「警告のみ→違反便だけ書き直す」へ格上げした=
#       本文を触る側になった以上、載せ忘れの窓を残さない。
#   ★2026-08-12 追加(C-042・HQ msg 1536851276933890078)= scripts/discord/persona_send.py と
#     scripts/_common/dept_names.py。dept_daemon が import する自作モジュール8本のうち、
#     この2本だけが監視外だった。**import は起動時に1回解決されるだけ**なので
#     (`from persona_send import split_body` は sys.modules に載って以後固定)、
#     この2本だけを直した日は1体も載せ替わらない=「入れたのに効かない」。
#     - persona_send.py = 送信そのもの(本文の分割 split_body が正本・ORG-11)
#     - dept_names.py   = 部門名の日本語化の正本(Chamiの画面に出る文字列)
#     ★どちらも**コード**なので C-042①の (B)都度読み は採れない=(A)監視対象に入れる。
#     ★載せ忘れの再発は `test_daemon_keeper.py` の「import と WATCH_FILES の突合」で機械が数える。
#   ★2026-08-13 追加(C-042)= scripts/llm/prompt_spill.py。dept_daemon と session_relay が
#     import する新規モジュール(長すぎるpromptをargvから逃がす止血)。**起動時に1回解決される
#     コード**なので都度読みは採れない=(A)監視対象に入れる。
#   ★2026-08-15 追加(C-042)= scripts/llm/meta_strip.py。出力ゲートE(本文末尾の内部メタ剥ぎ)の
#     純関数本体。dept_daemon が合流点で import する**本文を削る側**のコードなので、
#     tone_gate/naming_gate と同じ理由でここに要る(マーカーを1つ足した日に載らないと、
#     「入れたのに漏れ続ける」= 直したはずの事故がそのまま再演される)。
WATCH_FILES = [DAEMON,
               os.path.join(ROOT, "scripts", "llm", "session_relay.py"),
               os.path.join(ROOT, "scripts", "llm", "prompt_spill.py"),
               os.path.join(ROOT, "scripts", "llm", "session_rooms.py"),
               os.path.join(ROOT, "scripts", "llm", "tone_gate.py"),
               os.path.join(ROOT, "scripts", "llm", "naming_gate.py"),
               os.path.join(ROOT, "scripts", "llm", "meta_strip.py"),
               os.path.join(ROOT, "scripts", "queue", "leasequeue.py"),
               os.path.join(ROOT, "scripts", "_common", "session_presence.py"),
               os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
               os.path.join(ROOT, "scripts", "_common", "dept_names.py")]
RELOAD_DEBOUNCE_SEC = 90   # 変更が「落ち着いた」とみなすまで。編集の途中で載せ替えない
# ★2026-07-29 追加。実測した事故=
#   HQと実装エージェントが**何時間も連続で改修**した結果、90秒の間引きを何度も抜けて
#   **全28体が数分おきに再起動し続けた**(platform-se のログで 03:23/03:34/03:50/03:57/
#   04:05/04:13/04:14/04:16/04:24 と9回)。Chami=「プラットホームSE無音なんだけど…」。
#   ★**載せ替えが便の処理を食い潰していた。** 自動化そのものは正しいが、**間隔の下限が無かった。**
#   → **10分に1回まで**。連続改修中は最後の版がまとめて載る(古い版で少し走るより、
#     再起動で便を落とし続ける方が害が大きい)。
RELOAD_MIN_INTERVAL_SEC = 600
# ★処理中のまま長時間待っていることをログへ出す目安。
#   以前はこの時間を超えると強制載せ替えしていたが、親デーモンだけが終了して
#   Claude子プロセスが残り、同一セッションの二重実行と長いlease待ちを作った。
#   現在は警告だけに使い、処理中は何分経っても自動killしない。
RELOAD_FORCE_AFTER_SEC = 45 * 60


def _watch_stamp():
    """監視対象の最終更新(最大値)。読めないファイルは無視する。"""
    ts = []
    for p in WATCH_FILES:
        try:
            ts.append(os.path.getmtime(p))
        except OSError:
            pass
    return max(ts) if ts else 0.0


# ★★処理中マーカー(2026-08-13 イージス研究室 / 設計= 研究室HQ・Fable 5 / 裁定 C-041)。
#   `_inflight_depts` が見ている **リースは「掴んだ瞬間の予告」**であって実占有の申告ではない。
#   dept_daemon 側の extend は fail-open なので、SQLiteが混んで張り直しに失敗した便は
#   リース切れのまま裸で走る。そこを働き手自身の申告(`local/llm/busy/<dept>.json`)で埋める。
#   ★和集合でしか使わない= **殺さない方向にしか働かない**。読めなければ何も足さず今日と同等。
BUSY_DIR = os.path.join(ROOT, "local", "llm", "busy")
BUSY_MARKER_MAX_SEC = 3600     # ★デーモン自身が永久ハングしても1時間で自動失効(永久の人質を作らない)


def _pid_alive_win(pid, alive_pids):
    """pidが生きているか。alive_pids(列挙済み集合)が在ればそれで見る。

    ★列挙できていない時に「死んでいる」と決めない= 分からない時は**生きている扱い**
      (マーカーは殺さない方向にしか働かないので、こちらへ倒すのが安全側)。
    """
    if alive_pids is None:
        return True
    return pid in alive_pids


def _marker_busy(alive_pids=None, now=None):
    """有効な処理中マーカーを持つ部門の集合を返す。

    有効の条件は3つ**全部**= ①読める ②pidが生きている ③mtimeが BUSY_MARKER_MAX_SEC 以内。
    ★読めない/ディレクトリが無い時は **空集合**(=何も足さない)。例外を投げない。
    """
    now = now or time.time()
    out = set()
    try:
        names = os.listdir(BUSY_DIR)
    except OSError:
        return out                            # まだ誰も申告していない/読めない= 今日と同等
    for name in names:
        if not name.endswith(".json"):
            continue                          # .tmp(書きかけ)は読まない
        path = os.path.join(BUSY_DIR, name)
        try:
            age = now - os.path.getmtime(path)
            if age > BUSY_MARKER_MAX_SEC:
                continue                      # 期限切れ= 消し忘れとみなす
            with open(path, "r", encoding="utf-8") as f:
                rec = json.load(f)
            pid = int(rec.get("pid") or 0)
        except (OSError, ValueError, TypeError):
            continue                          # 壊れた1行で判定を落とさない
        if pid <= 0 or not _pid_alive_win(pid, alive_pids):
            continue                          # プロセスが死んだ= 申告は自動失効
        out.add(name[:-5])
    return out


def _alive_dept_pids():
    """走っている dept_daemon の (pidの集合, {pid: dept}) を返す。測れなければ (None, {})。

    ★戻り値のNoneは「測れなかった」= マーカーのpid条件を**生きている扱い**へ倒す合図。
    """
    if os.name != "nt":
        return None, {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'dept_daemon' } | "
             "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return None, {}
    pids, by_pid = set(), {}
    for ln in (out.stdout or "").splitlines():
        parts = ln.split("\t", 1)
        if not parts or not parts[0].strip().isdigit():
            continue
        pid = int(parts[0].strip())
        pids.add(pid)
        m = re.search(r"--dept\s+([A-Za-z0-9_\-]+)", parts[1] if len(parts) > 1 else "")
        if m:
            by_pid[pid] = m.group(1)
    return pids, by_pid


def _inflight_depts(db_path=None, now=None):
    """いま処理中の便が在る部門を返す。読み取り専用。

    戻り値:
      list: 処理中の部門一覧。空listは「処理中なし」。
      None: DBを読めず、処理中か判断できない。載せ替え側は必ず延期する。

    ★LeaseQueueの状態名に ``leased`` は存在しない。claim後も status は ``pending`` のままで、
      未来の lease_until が「処理中」を表す。claim可能条件が lease_until < now なので、
      境界の等値も処理中側(>=)として扱う。

    ★2026-07-29 実測した事故=
      自動載せ替えが**走っている便を踏み潰していた**。keeperの間隔(10分)と、
      relayの後始末(引き継ぎ最大420秒+圧縮100〜140秒)の長さがほぼ同じで、
      終端の無い便が実測3件出た(07:01:48 / 07:13:16 / 07:21:11)。
      予約はプロセス内メモリにしか無いので、殺されると**記録も残らず沈黙する**。
    ★→ **便が1つも走っていない瞬間にだけ載せ替える。** コードが古いまま少し走る方が、
      Chamiの便を落とすより、はるかにましだ(可用性 > 新しさ)。
    ★長時間待っても自動killせず、警告だけを残す。
    """
    db = db_path or os.path.join(ROOT, "local", "queue", "inbox.db")
    if not os.path.exists(db):
        return None
    try:
        import sqlite3
        check_at = time.time() if now is None else float(now)
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=3)
        try:
            rows = con.execute(
                "SELECT DISTINCT dept FROM queue "
                "WHERE status='pending' AND lease_until >= ? "
                "ORDER BY dept", (check_at,)).fetchall()
        finally:
            con.close()
        return [r[0] for r in rows if r and r[0]]
    except Exception:
        # 判定不能を「暇」とみなすと、DB一時異常だけで全28体をkillしてしまう。
        return None


def maybe_reload(slots, state):
    """コードが変わって RELOAD_DEBOUNCE_SEC 落ち着いたら、**暇な部門から順に**載せ替える。

    ★落とすだけ。**立て直すのは tick() の仕事**(=既存の再起動経路を使う。2本持たない)。
    ★事故ではないので backoff/fails を積まない(積むとサーキットが開いて逆に止まる)。
    ★処理中の便はkillしない。再配達できても、最大25分のlease待ち・子Claudeの孤児化・
      同一セッション二重実行が起きるため、「後で戻る」は安全の根拠にならない。

    ★★2026-08-08 変更= **全体一括 → 部門ごと(波)**。
      なぜ= 旧実装は「**30体全部が同時に暇**な瞬間」を待っていた。ところが対話の部屋
      (イージス研究室・研究室HQ等)は1便につき17〜25分leaseを握るので、Chamiや部屋どうしの
      やり取りが続いている間はその瞬間が来ない。**busyな1部屋が、無関係な29体の載せ替えを
      人質に取る**構造だった(実測 2026-08-08 09:34= 処理中3部門/27部門は暇)。
      → 便を握っている部門だけ次の周回へ回し、暇な部門はその場で載せ替える。
      **「便を握っている子はkillしない」という安全の核は1ミリも緩めていない。**
    ★版の混在について= dept_daemon は部門ごとに独立したプロセスで、共有しているのは
      SQLiteのqueueとファイルだけ。数分〜数十分の混在は元々起きている(起動のばらつき)。
      **古い版のまま何日も走る方が害が大きい**(fail-openは6日間1体も抱えないまま眠っていた)。
    ★波(wave)= 「この版を全員に配る」1回の作業。途中で新しい版が出たら波を張り直す
      (RELOAD_MIN_INTERVAL_SEC は**波の開始/張り直し**にだけ効かせる=連続改修中の
      再起動地獄は防いだまま、**始まった波は最後まで配りきる**)。
    """
    now = time.time()
    stamp = _watch_stamp()
    if not stamp:
        return
    if state.get("stamp") is None:          # 起動直後=今のコードで走っている
        state["stamp"] = stamp
        return
    wave = state.get("wave")                # 進行中の波(未配布の部門が残っている)

    # --- 1) 新しい版を検知したら、波を開始する(または新しい版で張り直す) ---
    known = wave["stamp"] if wave else state["stamp"]
    if stamp > known:
        if now - stamp < RELOAD_DEBOUNCE_SEC:   # まだ編集中かもしれない
            return
        last = state.get("last_reload") or 0
        if last and now - last < RELOAD_MIN_INTERVAL_SEC:
            return                          # ★連続改修中の再起動地獄を防ぐ(上のコメント参照)
        wave = {"stamp": stamp, "pending": [s.dept for s in slots], "started": now}
        state["wave"] = wave
        log(f"★コードの更新を検知({time.strftime('%H:%M:%S', time.localtime(stamp))})= "
            f"全{len(slots)}体を、暇な部門から順に載せ替える")
    if not wave:
        return

    # --- 2) 処理中の便を握っている部門は飛ばす(2026-07-29。_inflight_depts の説明を読め) ---
    busy = _inflight_depts()
    if busy is None:
        # fail-closed: 判定不能時は絶対にkillしない。ログは5分に1回へ抑える。
        if now - (state.get("last_unknown_log") or 0) > 300:
            state["last_unknown_log"] = now
            log("コードの更新を検知したが、queueの処理中判定ができないので載せ替えを延期する")
        return
    # ★2026-08-13: リース(予告)だけでなく**働き手自身の申告**も足す(和集合・C-041)。
    #   extend が fail-open で失敗した便はリース切れのまま走っている=ここで拾う。
    alive, _ = _alive_dept_pids()
    busy_set = set(busy) | _marker_busy(alive)
    targets = [s for s in slots if s.dept in wave["pending"] and s.dept not in busy_set]
    for s in targets:
        if s.proc is not None and s.proc.poll() is None:
            try:
                s.proc.kill()
            except Exception:
                pass
        s.proc = None
        s.backoff, s.fails = BACKOFF_START, 0   # 事故ではない
        s.open_until = 0.0
        s.next_start = 0.0
        s.started = 0.0
    if targets:
        done = [s.dept for s in targets]
        wave["pending"] = [d for d in wave["pending"] if d not in set(done)]
        log(f"載せ替えた{len(done)}体: {','.join(done[:8])}"
            f"{'…' if len(done) > 8 else ''} / 残り{len(wave['pending'])}体")
        state["last_reload"] = now

    # --- 3) 全員に配り終えたら波を閉じる。残っているなら待ち時間をログへ ---
    if not wave["pending"]:
        state["stamp"] = wave["stamp"]
        state.pop("wave", None)
        state.pop("first_seen", None)
        log(f"★載せ替え完了= 全{len(slots)}体が"
            f"{time.strftime('%H:%M:%S', time.localtime(wave['stamp']))}の版になった")
        return
    if not state.get("first_seen"):
        state["first_seen"] = wave["started"]
    if now - (state.get("last_busy_log") or 0) > 300:
        state["last_busy_log"] = now
        waited = now - state["first_seen"]
        rest = ",".join(wave["pending"][:6])
        if waited >= RELOAD_FORCE_AFTER_SEC:
            log(f"★載せ替えを{int(waited // 60)}分続けているが、処理中の便を守るため"
                f"この部門は待ち続ける: {rest}")
        else:
            log(f"処理中の便が在るので、この部門は次の周回へ回す: {rest}")


def reap_orphans():
    """自分の管理下にない既存のdept_daemonを起動前に掃除する(2026-07-20 実測事故への恒久対処)。

    何が起きたか: keeperをkillしても**子のdept_daemonは生き残る**(孤児化)。そこへ新keeperが
    起動すると各部門をもう1つ立てるので、全13部門が二重になった。二重化=同じ便に2つの
    デーモンが応答しうる状態で、今日わざわざ塞いだ二重応答の穴が別経路で開く。
    dept_daemonの所有者はkeeper唯一(RULES §3 1領域1オーナー)なので、
    **起動時点で走っているdept_daemonは全て前世代の残骸**とみなして落としてよい。
    ※supervise_daemons.ps1 の重複排除はkeeper/gateway等が対象で、その子までは見ない。

    ★2026-08-13(イージス研究室・HQ恒久依頼/穴3): **暇判定が1つも無かった**。
      実測= 15:40:15「起動前の孤児dept_daemonを掃除: 30件」が、その**39秒前(15:39:36)に
      載せ替え側が正しく守ったばかりの hq / aegis-gl / platform-se を巻き込んで殺した**。
      片方の経路だけ述語を持っていて、もう片方が持っていない=経路ごとにバラバラだった。
      → ここも「リース ∪ 有効な処理中マーカー」の**同じ述語**を差す。守った部門は返り値で返し、
        呼び元が自分のspawnを少し遅らせる(二重化を作らないため)。
    """
    if os.name != "nt":
        return set()
    alive, by_pid = _alive_dept_pids()
    if alive is None:
        log("孤児掃除スキップ(プロセス列挙に失敗)=現行動作のまま続行")
        return set()
    pids = sorted(alive)
    if not pids:
        return set()
    # ★守る対象= 有効なマーカーを持ち、そのマーカーのpidが実在の孤児と一致する部門だけ。
    #   (マーカーが在っても別pidを指しているなら、その孤児は前世代の残骸=落としてよい)
    busy = _marker_busy(alive)
    guarded, guarded_depts = set(), set()
    for pid in pids:
        dept = by_pid.get(pid)
        if not dept or dept not in busy:
            continue
        try:
            with open(os.path.join(BUSY_DIR, dept + ".json"), "r", encoding="utf-8") as f:
                if int(json.load(f).get("pid") or 0) == pid:
                    guarded.add(pid)
                    guarded_depts.add(dept)
        except (OSError, ValueError, TypeError):
            pass
    kill = [p for p in pids if p not in guarded]
    if guarded:
        log("処理中マーカーが有るので孤児を守る pid=%s(部門= %s)"
            % (",".join(str(p) for p in sorted(guarded)), ",".join(sorted(guarded_depts))))
    if not kill:
        return guarded_depts
    log(f"起動前の孤児dept_daemonを掃除: {len(kill)}件 pids={','.join(str(p) for p in kill)}")
    for pid in kill:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=15)
        except Exception:
            pass
    time.sleep(2)   # ポート(18800番台)が解放されるのを待ってから自分の分を立てる
    return guarded_depts


# --- ★名簿(DEPTS)が増減したら、番人の再起動を待たずに追従する(2026-08-08 イージス研究室) --
#
# なぜ要るか(実測した穴):
#   `DEPTS` はモジュールの定数なので**番人が起動した時点で写し取られる**。あとから部屋を足しても、
#   番人を再起動するまで**その部屋は番人の管理下に入らない**。実測=
#     ・ククール-なかま会話を名簿へ足したのは 08-05 08:26。番人は 08-04 00:06 起動のまま。
#     ・そのため 08-08 19:53 の全体載せ替えに**この部屋だけ入らず**、手で起動した
#       pid 50452(親=52596=既に居ない)が**番人の管理外**で走り続けていた。
#   ★怖いのは「動いていない」ことではなく、**死んでも誰も立て直さないのに警報も出ない**ことだ。
#   ★同じ形の対策は既に受信側にある(Discord gatewayは新設chを60秒で自動追従する)。
#     **番人だけが手の再起動を要求していた**=そこを揃える。
#
# ★安全のために踏んでいる手順:
#   ①名簿は**自分のソースから読み直す**(ast.literal_eval=実行しない)。読めない/壊れている/
#     極端に短い名簿は**採用しない**(編集途中のファイルを掴んで全部落とすのを防ぐ)。
#   ②増えた部門は、立てる前に**その部門の孤児プロセスだけ**を落とす(全体のreapはしない=
#     無関係な29体を巻き込まない)。二重化=同じ便に2つが応答する穴を作らない。
#   ③減った部門は、**便を処理中なら落とさない**(次の周回へ回す)。
ROSTER_RECHECK_SEC = 60      # 名簿の読み直し間隔(1分)
ROSTER_SETTLE_SEC = 30       # 編集が落ち着いたとみなすまで
ROSTER_MIN = 5               # これ未満の名簿は「壊れている」とみなして採用しない


def _read_depts_file(path=None):
    """自分のソースから DEPTS を読み直す。読めない/怪しい時は None(=今の名簿のまま)。"""
    src_path = path or os.path.abspath(__file__)
    try:
        if time.time() - os.path.getmtime(src_path) < ROSTER_SETTLE_SEC:
            return None                      # まだ編集中かもしれない
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        m = re.search(r"^DEPTS = (\[[^\]]*\])\s*$", src, re.M)
        if not m:
            return None
        want = ast.literal_eval(m.group(1))
    except Exception:
        return None
    if not isinstance(want, list) or len(want) < ROSTER_MIN:
        return None
    if not all(isinstance(x, str) and x for x in want):
        return None
    seen, out = set(), []
    for d in want:                           # 重複は1つに畳む(二重化の芽を潰す)
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _kill_orphans_for(dept):
    """その部門だけの孤児dept_daemonを落とす(全体のreapはしない)。落とした数を返す。"""
    if os.name != "nt":
        return 0
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'dept_daemon' -and "
             "$_.CommandLine -match '--dept\\s+%s(\\s|$)' } | "
             "ForEach-Object { $_.ProcessId }" % re.escape(dept)],
            capture_output=True, text=True, timeout=30)
        pids = [p.strip() for p in (out.stdout or "").split() if p.strip().isdigit()]
    except Exception:
        return 0
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=15)
        except Exception:
            pass
    return len(pids)


def maybe_adopt(slots, state):
    """名簿の増減に追従する。★立て直すのは tick() の仕事(経路を2本持たない)。"""
    now = time.time()
    if now - (state.get("roster_at") or 0) < ROSTER_RECHECK_SEC:
        return
    state["roster_at"] = now
    want = _read_depts_file()
    if want is None:
        return
    have = [s.dept for s in slots]
    for d in want:
        if d in have:
            continue
        killed = _kill_orphans_for(d)         # 手で起動された同じ部門を先に落とす
        slots.append(Slot(d))
        log(f"★名簿に増えた部門を採用: {d}(番人の再起動を待たない"
            f"{f' / 孤児{killed}件を先に掃除' if killed else ''})")
    drop = [s for s in slots if s.dept not in want]
    if drop:
        busy = _inflight_depts()
        if busy is None:
            return                            # 判定不能=落とさない(fail-closed)
        alive, _ = _alive_dept_pids()
        busy_all = set(busy) | _marker_busy(alive)   # ★載せ替えと同じ述語(2026-08-13)
        for s in drop:
            if s.dept in busy_all:
                log(f"名簿から外れたが便を処理中なので落とさない: {s.dept}")
                continue
            if s.proc is not None and s.proc.poll() is None:
                try:
                    s.proc.kill()
                except Exception:
                    pass
            slots.remove(s)
            wave = state.get("wave")
            if wave:
                wave["pending"] = [d for d in wave["pending"] if d != s.dept]
            log(f"★名簿から外れた部門を停止: {s.dept}")


def _tend_guarded(slots, guarded):
    """守った孤児を見張る。申告が失効したら落として通常運用へ戻す(2026-08-13)。

    ★守っている間は自分のspawnを止める= 孤児と番人の子で**二重化を作らない**。
    ★マーカーが消える/pidが死ぬ= その便は終わった or デーモンごと死んだ。どちらでも
      孤児を落として(残っていれば)通常の立て直しへ返す。★3600秒で自動失効するので、
      守り続けて永久に立て直さない、という詰み方はしない。
    """
    if not guarded:
        return
    alive, _ = _alive_dept_pids()
    still = _marker_busy(alive)
    by_dept = {s.dept: s for s in slots}
    for dept in sorted(guarded):
        s = by_dept.get(dept)
        if dept in still:
            if s is not None:
                s.next_start = time.time() + 30   # 守っている間は立てない(延期し続ける)
            continue
        killed = _kill_orphans_for(dept)
        guarded.discard(dept)
        if s is not None:
            s.next_start = 0.0
        log(f"守っていた孤児の処理中マーカーが失効: {dept}"
            f"(孤児{killed}件を落として通常運用へ戻す)")


def main():
    guarded = set(reap_orphans() or ())
    slots = [Slot(d) for d in DEPTS]
    log(f"起動 depts={DEPTS}"
        + (f" / ★処理中で守った部門= {','.join(sorted(guarded))}" if guarded else ""))
    reload_state = {}
    while True:
        try:
            _tend_guarded(slots, guarded)      # ★守った孤児の後始末(先にやる=立てる前に判定)
        except Exception as e:
            log(f"守った孤児の見張りに失敗(継続) {type(e).__name__}")
        try:
            maybe_adopt(slots, reload_state)   # ★名簿が増減したら追従する
        except Exception as e:
            log(f"名簿の追従に失敗(継続) {type(e).__name__}")
        try:
            maybe_reload(slots, reload_state)   # ★コードが変わったら自動で載せ替える
        except Exception as e:
            log(f"自動載せ替えの判定に失敗(継続) {type(e).__name__}")
        for s in slots:
            try:
                s.tick()
            except Exception as e:
                log(f"{s.dept}: tick失敗 {type(e).__name__}")
        time.sleep(2)


if __name__ == "__main__":
    main()
