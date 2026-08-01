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
import os
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
DEPTS = ["hq", "research-room", "aegis-gl", "keiei-kikaku", "hr-room", "hr-context", "qa-reviewer", "system-engineer", "product-scout", "shorts-analyst", "copy-director", "learning-coach", "data-org", "frontend", "ai-office", "llm-edu", "llm-qa", "platform-se", "consult-intel", "past-room", "future-room", "kaizen-analyst", "incident", "system-engineer-b", "dream-care", "health-log", "report-notify", "imagegen"]
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
WATCH_FILES = [DAEMON,
               os.path.join(ROOT, "scripts", "llm", "session_relay.py"),
               os.path.join(ROOT, "scripts", "llm", "session_rooms.py"),
               os.path.join(ROOT, "scripts", "_common", "session_presence.py")]
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
    """コードが変わって RELOAD_DEBOUNCE_SEC 落ち着いたら、全部の子を載せ替える。

    ★落とすだけ。**立て直すのは tick() の仕事**(=既存の再起動経路を使う。2本持たない)。
    ★事故ではないので backoff/fails を積まない(積むとサーキットが開いて逆に止まる)。
    ★処理中の便はkillしない。再配達できても、最大25分のlease待ち・子Claudeの孤児化・
      同一セッション二重実行が起きるため、「後で戻る」は安全の根拠にならない。
    """
    now = time.time()
    stamp = _watch_stamp()
    if not stamp:
        return
    if state.get("stamp") is None:          # 起動直後=今のコードで走っている
        state["stamp"] = stamp
        return
    if stamp <= state["stamp"]:
        return
    if now - stamp < RELOAD_DEBOUNCE_SEC:   # まだ編集中かもしれない
        return
    last = state.get("last_reload") or 0
    if last and now - last < RELOAD_MIN_INTERVAL_SEC:
        return                              # ★連続改修中の再起動地獄を防ぐ(上のコメント参照)
    # ★処理中の便が在る間は載せ替えない(2026-07-29。上の _inflight_depts の説明を読め)。
    busy = _inflight_depts()
    if busy is None:
        # fail-closed: 判定不能時は絶対にkillしない。ログは5分に1回へ抑える。
        if now - (state.get("last_unknown_log") or 0) > 300:
            state["last_unknown_log"] = now
            log("コードの更新を検知したが、queueの処理中判定ができないので載せ替えを延期する")
        return
    waited = now - (state.get("first_seen") or now)
    if busy:
        if not state.get("first_seen"):
            state["first_seen"] = now
        if now - (state.get("last_busy_log") or 0) > 300:
            state["last_busy_log"] = now
            waited = now - state["first_seen"]
            if waited >= RELOAD_FORCE_AFTER_SEC:
                log(f"★コード更新を{int(waited // 60)}分待っているが、処理中の便を守るため"
                    f"載せ替えを延期し続ける: {','.join(busy[:6])}")
            else:
                log(f"コードの更新を検知したが、処理中の便が在るので待つ: {','.join(busy[:6])}")
        return
    state.pop("first_seen", None)
    log(f"★コードの更新を検知({time.strftime('%H:%M:%S', time.localtime(stamp))})= 全{len(slots)}体を載せ替える")
    for s in slots:
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
    state["stamp"] = stamp
    state["last_reload"] = now


def reap_orphans():
    """自分の管理下にない既存のdept_daemonを起動前に掃除する(2026-07-20 実測事故への恒久対処)。

    何が起きたか: keeperをkillしても**子のdept_daemonは生き残る**(孤児化)。そこへ新keeperが
    起動すると各部門をもう1つ立てるので、全13部門が二重になった。二重化=同じ便に2つの
    デーモンが応答しうる状態で、今日わざわざ塞いだ二重応答の穴が別経路で開く。
    dept_daemonの所有者はkeeper唯一(RULES §3 1領域1オーナー)なので、
    **起動時点で走っているdept_daemonは全て前世代の残骸**とみなして落としてよい。
    ※supervise_daemons.ps1 の重複排除はkeeper/gateway等が対象で、その子までは見ない。
    """
    if os.name != "nt":
        return
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'dept_daemon' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=30)
        pids = [p.strip() for p in (out.stdout or "").split() if p.strip().isdigit()]
    except Exception as e:
        log(f"孤児掃除スキップ({type(e).__name__})=現行動作のまま続行")
        return
    if not pids:
        return
    log(f"起動前の孤児dept_daemonを掃除: {len(pids)}件 pids={','.join(pids)}")
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=15)
        except Exception:
            pass
    time.sleep(2)   # ポート(18800番台)が解放されるのを待ってから自分の分を立てる


def main():
    reap_orphans()
    slots = [Slot(d) for d in DEPTS]
    log(f"起動 depts={DEPTS}")
    reload_state = {}
    while True:
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
