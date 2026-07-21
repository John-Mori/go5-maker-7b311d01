#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discord_gateway — discord.py Gatewayで新着をpush受信し、リースキューへ入れる (恒久解 案A)。

現行の鳩(inbox_poller・15秒RESTポーリング)を将来置き換える受信口。本ファイルは
strangler移行の第一段=**シャドウモード**で動く:
  - Discord Gateway(WebSocket)で on_message を**即時**受信 (ポーリング周期という概念が消える)
  - 受信レコードを LeaseQueue(SQLite) へ enqueue する (msg_id冪等=二重投入無視)
  - ★返信しない・旧inbox(JSONL)に触らない・旧鳩と同時に動いてよい
    (両者は別の宛先へ書くso衝突しない。キューのmsg_id冪等が二重処理も防ぐ)
これにより「新しい受信経路が本番と同じ入力を正しく捌けるか」を、動いている系に一切
リスクを与えずに実測できる。切替(consumerを繋ぐ・旧鳩を止める)は別段階・Chami可視化の上で。

必要な前提 (Chamiのみ可能な設定):
  Discord Developer Portal → 対象Bot → Bot → Privileged Gateway Intents →
  「MESSAGE CONTENT INTENT」をON。これが無いと on_message の content が空になる
  (privileged intent。REST読取り=現行鳩には不要だったが、Gateway受信には必須)。
  未設定のまま起動すると discord.errors.PrivilegedIntentsRequired で即座に落ちる(=検知できる)。

使い方:
  python scripts/queue/discord_gateway.py --selftest   # Discordに繋がず内部配線だけ検証
  python scripts/queue/discord_gateway.py              # シャドウ稼働 (要 MESSAGE CONTENT INTENT)
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
GW_PULSE = os.path.join(LOCAL, "queue", "_gateway_pulse.txt")


def _touch_pulse():
    """discord.pyのイベントループが実際に回っているかのliveness証跡(2026-07-19 INC対策)。

    2026-07-19実測: TCP:443は張られたままdiscord.py内部のイベント処理だけが無言で
    詰まり、on_readyの二度目以降が「接続」ログだけ出して「掃除」まで到達しない事故が
    発生(数時間、Discordの新着に一切反応しない=TCP生存≠アプリ生存)。job_prune等の
    周期ジョブは間隔が長い(600s〜24h)ため生死判定に使えない。専用の高頻度脈を持つ。
    """
    try:
        os.makedirs(os.path.dirname(GW_PULSE), exist_ok=True)
        with open(GW_PULSE, "a", encoding="utf-8"):
            pass
        os.utime(GW_PULSE, None)
    except OSError:
        pass
sys.path.insert(0, HERE)
from leasequeue import LeaseQueue  # noqa: E402

TOKEN_FILE = os.path.join(LOCAL, "discord_bot_token.txt")
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
QUEUE_DB = os.path.join(LOCAL, "queue", "inbox.db")
LOG_FILE = os.path.join(LOCAL, "discord_gateway.log")

# --- 段階2: 鳩の周期ジョブの移植 (Gate条件1・2026-07-18 QA実装) ---
# ★ACTIVE_JOBS=Falseの間、周期ジョブ(受領スタンプ/エスカレート)は完全停止=シャドウ据え置き。
#   理由: シャドウ中はqueueを誰も消費しない=全行が「未claim滞留」に見え、窓が即答する部屋にも
#   受領文が飛ぶ過剰動作になる。カットオーバー(consumer稼働)時に GO5_GATEWAY_JOBS=1 で解禁する。
#   添付退避(P4相当)だけは受信時の記録行為なので常時有効(送信を伴わない・無害)。
def _cutover_conf():
    """切替設定の正本=local/queue/cutover.json(env変数より優先)。

    2026-07-19実測: User環境変数はハーネス/スケジューラの環境スナップショットに埋もれて
    子プロセスへ届かないことがある(gatewayがshadowで再起動する事故)。ファイルなら
    どの経路で起動しても同じ値を読む=決定論的。無ければenvへフォールバック。
    """
    import json as _json
    p = os.path.join(LOCAL, "queue", "cutover.json")
    try:
        return _json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


_CONF = _cutover_conf()
ACTIVE_JOBS = str(_CONF.get("gateway_jobs", os.environ.get("GO5_GATEWAY_JOBS", ""))) == "1"
# パイロット限定用のdept allowlist (カンマ区切り・空=全部門)。手順書§2-1「data-org箱だけ仮点灯」を
# 正確に実現する (無いとリハーサル中に他部屋へも受領印が飛ぶ=QAレビュー指摘の是正)。
# 対象: 受領印(ack)・エスカレート・送信印(A2)。受信/添付退避は全部門のまま (無害な記録行為)。
JOBS_DEPTS = frozenset(d.strip() for d in str(_CONF.get("gateway_jobs_depts",
    os.environ.get("GO5_GATEWAY_JOBS_DEPTS", ""))).split(",") if d.strip())
# ★2026-07-19 Chami指示「この発言要らないんだけど…」で無効化(鳩P1と同時・詳細はinbox_poller.py参照)
ACK_ENABLED = False
ACK_AFTER_SEC = 45                                    # 未claim滞留→受領スタンプまで (鳩P1と同値)
ACK_LEDGER = os.path.join(LOCAL, "ack_ledger.txt")    # ★鳩P1と同一台帳=並走中の二重ack防止
ACK_SENSITIVE = ("dream-care", "past-room")           # 機微部屋はPROTOCOL管轄 (鳩P1と同値)
ACK_PERSONA = "メタルギアMk.II"
ACK_TEXT = "受領した。担当の起床後に返答する。"
STALE_ESCALATE_SEC = 30 * 60                          # 未claim放置→router(研究室)へ付け替え (sweep相当)
# ★総括本部4室=デーモンを撤去し「人格を持つ本人(セッション)が応対する」と決めた部屋
#   (Chami裁定2026-07-20)。この4室は router へ付け替えてはいけない(2026-07-21 ORG-12で発覚):
#   セッションが留守の間に30分sweepがrouterへ回す→claude_responder(無人代打)が偽ackして
#   done化→**次にセッションが開いてもwaiterに出てこない=Chamiの依頼が10時間消える**。
#   これらはpendingのまま自分のdeptで待たせ、absence_watchdogが15分で沈黙を可視化する。
#   偽の返事より沈黙が良い(Chami既決)。router除外と同じ理屈=本人が最終処理する部屋を奪わない。
SESSION_OWNED_DEPTS = ("hq", "aegis-gl", "research-room", "keiei-kikaku")
ESCALATE_LEDGER = os.path.join(LOCAL, "escalate_ledger.txt")
ATTACH_DIR = os.path.join(LOCAL, "attachments")       # P4相当 (鳩と同一ディレクトリ=切替前後で連続)
ATTACH_MAX_BYTES = 20 * 1024 * 1024
ATTACH_KEEP_DAYS = 14


GW_LOCK = os.path.join(LOCAL, "queue", "_gateway.lock")


def _pid_alive(pid):
    """PIDが生きているか(Windows/POSIX両対応)。判定不能はFalse=起動を止めない側へ倒す。"""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                k.CloseHandle(h)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def claim_singleton():
    """既に生きたgatewayが居るなら自分は起動しない(2026-07-21 ORG-22・ad研究室からの差し戻し)。

    ★なぜ要るか: gatewayには多重起動ガードが無かった。supervise_daemons は「プロセスが0なら起動」
      なので、手動再起動と巡回が重なると**2本立ち得る**。実際 ad研究室(AD-GL)が二重起動を
      観測してHQへ差し戻してきた(3階梯のエスカレーションが機能した実例)。
      被害は限定的だった(queueのmsg_id冪等が効き、実測で**重複msg_id 0件**)が、
      受領スタンプやescalateジョブは二重に走るため、根本を塞ぐ。

    ★**fail-open**: ロックが読めない・PID判定に失敗した等の「分からない」時は**起動する**。
      ここはDiscord受信の唯一の入口で、**起動を止める誤判定は全部屋の沈黙**を意味する。
      重複の害(スタンプ二重)より、不在の害(全便が届かない)の方が桁違いに大きい。
    """
    try:
        with open(GW_LOCK, encoding="utf-8") as f:
            old = int(f.read().strip().split()[0])
    except Exception:
        old = 0
    if old and old != os.getpid() and _pid_alive(old):
        log(f"既に稼働中のgateway pid={old} を検出。二重起動を避けて終了する。")
        return False
    try:
        os.makedirs(os.path.dirname(GW_LOCK), exist_ok=True)
        with open(GW_LOCK, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}\n")
    except OSError:
        pass            # 書けなくても起動は続ける(fail-open)
    return True


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_channel_map():
    """channel_id -> {name, dept} を作る (受信を台帳のchだけに絞る)。"""
    try:
        chans = json.load(open(CHANNELS_FILE, encoding="utf-8"))
    except OSError:
        return {}
    return {str(c.get("id")): {"name": c.get("name", ""), "dept": c.get("dept", "router")}
            for c in chans if str(c.get("id", "")).isdigit()}


def record_from_message(m, chinfo):
    """discord.Message → 現行鳩と同じ形のレコード (後段が共通に読めるようにキーを揃える)。"""
    return {
        "ts": m.created_at.isoformat() if m.created_at else "",
        "channel": chinfo.get("name", ""),
        "dept": chinfo.get("dept", "router"),
        "author": getattr(m.author, "name", "?"),
        "author_id": str(getattr(m.author, "id", "") or ""),
        "content": m.content or "",
        "attachments": [a.url for a in m.attachments],
        "msg_id": str(m.id),
    }


def _ledger_load(path):
    try:
        return set(l.strip() for l in open(path, encoding="utf-8") if l.strip())
    except OSError:
        return set()


def _ledger_append(path, key):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(str(key) + "\n")
    except OSError:
        pass


def _send_persona(target, text, by_dept=False):
    """Mk.II名義の定型送信 (persona_send流用=既存の別名義/台帳運用と同一)。同期呼び=to_threadで包むこと。"""
    import subprocess
    try:
        args = [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py")]
        args += (["--dept", target] if by_dept else ["--channel", target])
        args += ["--persona", ACK_PERSONA, text]
        r = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _stash_attachments(urls, msg_id):
    """添付をlocalへ写す (P4相当・鳩と同実装/同宛先)。同期呼び=to_threadで包むこと。"""
    import subprocess
    saved = []
    if not urls:
        return saved
    os.makedirs(ATTACH_DIR, exist_ok=True)
    for i, u in enumerate(urls):
        if not u:
            continue
        ext = os.path.splitext(u.split("?", 1)[0])[1][:8] or ".bin"
        dest = os.path.join(ATTACH_DIR, f"{msg_id}_{i}{ext}")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            saved.append(os.path.join("local", "attachments", os.path.basename(dest)))
            continue  # 鳩が先に保存済み (並走中の重複DL回避)
        try:
            r = subprocess.run(["curl", "-s", "-o", dest, "--max-time", "15",
                                "--max-filesize", str(ATTACH_MAX_BYTES), u],
                               capture_output=True, timeout=25)
            if r.returncode == 0 and os.path.getsize(dest) > 0:
                saved.append(os.path.join("local", "attachments", os.path.basename(dest)))
            elif os.path.exists(dest):
                os.remove(dest)
        except Exception:
            pass
    return saved


def _dept_allowed(dept, allow=None):
    allow = JOBS_DEPTS if allow is None else allow
    return not allow or dept in allow


def ack_pass(q, now=None, allow=None):
    """P1相当: 未claimのままACK_AFTER_SEC滞留した行へ受領スタンプ (1msg1回・鳩と共有台帳)。

    返り値=送った(ch名)のリスト。send関数はテストで差し替え可能にするためq側でなくここで束ねる。
    allow=dept allowlist (パイロット限定・既定は環境変数JOBS_DEPTS)。
    """
    now = now or time.time()
    acked = _ledger_load(ACK_LEDGER)
    sent = []
    for r in q.stale_pending(older_sec=ACK_AFTER_SEC):
        try:
            body = json.loads(r["body"]) if isinstance(r["body"], str) else r["body"]
        except ValueError:
            continue
        mid = str(r.get("msg_id") or "")
        ch = body.get("channel", "")
        if not mid or not ch or mid in acked:
            continue
        if body.get("dept") in ACK_SENSITIVE or not _dept_allowed(r.get("dept"), allow):
            continue
        sent.append((mid, ch))
    return sent


def escalate_pass(q, now=None, allow=None):
    """sweep相当: 30分放置をrouter(研究室)へ付け替える対象。

    2026-07-18改: stale_pending→**abandoned** (リース失効放置の全部) へ変更。研究室指摘の
    エッジ=一度claimされnackされた行 (deliveries>0) がstale_pendingでは検出外に落ちるため。
    処理中 (リース有効) は含まれないので、働いている行を奪うことはない。
    """
    now = now or time.time()
    done = _ledger_load(ESCALATE_LEDGER)
    out = []
    for r in q.abandoned(older_sec=STALE_ESCALATE_SEC):
        mid = str(r.get("msg_id") or "")
        if not mid or mid in done or r.get("dept") == "router":
            continue
        if r.get("dept") in SESSION_OWNED_DEPTS:
            continue        # ★本人セッションが処理する部屋=routerへ奪わない(ORG-12)
        if not _dept_allowed(r.get("dept"), allow):
            continue
        out.append(r)
    return out


def run_selftest():
    """Discordに接続せず、レコード生成→enqueue→冪等→statsの内部配線だけ検証する。"""
    import tempfile
    import shutil
    d = tempfile.mkdtemp(prefix="qa_gw_")
    try:
        q = LeaseQueue(os.path.join(d, "inbox.db"))

        class _A:  # 疑似 author
            name = "chami_fusoh"
            id = 490925528367497227

        class _M:  # 疑似 message
            id = 999001
            content = "テスト発言"
            created_at = None
            author = _A()
            attachments = []
        chinfo = {"name": "品質管理部門", "dept": "qa-reviewer"}
        rec = record_from_message(_M(), chinfo)
        ok1 = q.enqueue(json.dumps(rec, ensure_ascii=False), msg_id=rec["msg_id"], dept=rec["dept"])
        ok2 = q.enqueue(json.dumps(rec, ensure_ascii=False), msg_id=rec["msg_id"], dept=rec["dept"])
        c = q.claim(dept="qa-reviewer")
        print(f"  {'PASS' if ok1 else 'FAIL'}: 受信レコードをenqueueできる")
        print(f"  {'PASS' if ok2 is False else 'FAIL'}: 同一msg_idの再受信は無視 (鳩と並走しても二重処理しない)")
        print(f"  {'PASS' if c and c['body']['content']=='テスト発言' else 'FAIL'}: claimで内容が取れる")
        print(f"  {'PASS' if c and c['dept']=='qa-reviewer' else 'FAIL'}: deptが保たれる")
        # --- 周期ジョブの判定ロジック (送信はしない・純粋な対象抽出のみ) ---
        q2 = LeaseQueue(os.path.join(d, "jobs.db"))
        mk = lambda mid, dept, ch: q2.enqueue(  # noqa: E731
            json.dumps({"channel": ch, "dept": dept, "content": "x", "msg_id": mid},
                       ensure_ascii=False), msg_id=mid, dept=dept)
        mk("S1", "meeting-a", "会議室α")       # 滞留→ackすべき
        mk("S2", "dream-care", "夢と回復")      # 機微→ack対象外
        mk("S3", "qa-reviewer", "品質管理")     # 新鮮のまま残す
        # S1/S2だけ古く見せる (テスト専用の時刻操作)
        q2._db.execute("UPDATE queue SET enqueued_at = enqueued_at - 100 WHERE msg_id IN ('S1','S2')")
        targets = ack_pass(q2)
        ok5 = [m for m, _ in targets] == ["S1"]
        print(f"  {'PASS' if ok5 else 'FAIL'}: ack対象=滞留のみ (機微・新鮮は除外) {targets}")
        q2._db.execute("UPDATE queue SET enqueued_at = enqueued_at - 3600 WHERE msg_id='S1'")
        esc = escalate_pass(q2)
        ok6 = [r["msg_id"] for r in esc] == ["S1", "S2"] or [r["msg_id"] for r in esc] == ["S1"]
        # 機微部屋もエスカレートは対象 (読まれない事実の可視化はPROTOCOL P0-2と整合)。routerは除外
        print(f"  {'PASS' if ok6 else 'FAIL'}: エスカレ対象=30分放置のみ {[r['msg_id'] for r in esc]}")

        # --- パイロット限定allowlist (手順書§2-1の実効化) ---
        ok7 = ack_pass(q2, allow=frozenset(["data-org"])) == [] \
            and [m for m, _ in ack_pass(q2, allow=frozenset(["meeting-a"]))] == ["S1"]
        print(f"  {'PASS' if ok7 else 'FAIL'}: dept allowlistで対象を限定できる (パイロット=1部門だけ点灯)")
        # --- nack済み行のエスカレ (abandoned化・研究室指摘エッジ) ---
        cS = q2.claim(dept="meeting-a")
        q2.nack(cS["id"])  # claim→nack=deliveries=1 (stale_pendingでは見えなくなる)
        esc2 = [r["msg_id"] for r in escalate_pass(q2)]
        ok8 = "S1" in esc2
        print(f"  {'PASS' if ok8 else 'FAIL'}: nack済み放置もエスカレ対象に拾う (abandoned) {esc2}")

        allok = (ok1 and (ok2 is False) and c and c["body"]["content"] == "テスト発言"
                 and ok5 and ok6 and ok7 and ok8)
        print(f"\n== selftest {'PASS' if allok else 'FAIL'} ==")
        return 0 if allok else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_gateway():
    import asyncio
    import discord
    from discord.ext import tasks

    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    chan_map = load_channel_map()
    q = LeaseQueue(QUEUE_DB)

    intents = discord.Intents.default()
    intents.message_content = True  # ★要 Developer Portal での有効化 (privileged)
    client = discord.Client(intents=intents)

    # --- 周期ジョブ (Gate条件1の移植分。ACTIVE_JOBS=Falseの間は起動しない) ---
    @tasks.loop(seconds=30)
    async def job_ack():
        """P1相当: 未claim滞留45秒→Mk.II受領スタンプ (鳩と共有台帳=並走中も二重ackなし)。"""
        if not ACK_ENABLED:
            return  # Chami指示2026-07-19で停止(コードは残置=再有効化はフラグ1つ)
        try:
            for mid, ch in ack_pass(q):
                ok = await asyncio.to_thread(_send_persona, ch, ACK_TEXT)
                _ledger_append(ACK_LEDGER, mid)  # 成否問わず1回で打ち止め (鳩P1と同方針)
                log(f"受領スタンプ [{ch}] msg={mid} {'OK' if ok else 'FAIL'}")
        except Exception as e:
            log(f"job_ack失敗(継続): {type(e).__name__}")  # ループは死なせない (L3規律)

    @tasks.loop(seconds=600)
    async def job_escalate():
        """sweep相当: 未claim放置30分→routerへ付け替え+incident chへ可視化。"""
        try:
            for r in escalate_pass(q):
                if q.reroute(r["id"], "router"):
                    _ledger_append(ESCALATE_LEDGER, r["msg_id"])
                    log(f"エスカレート msg={r['msg_id']} dept={r['dept']}→router (30分未claim)")
                    await asyncio.to_thread(
                        _send_persona, "incident",
                        f"未claim30分の滞留をrouter(研究室)へ回した (元dept={r['dept']})。", True)
        except Exception as e:
            log(f"job_escalate失敗(継続): {type(e).__name__}")

    @tasks.loop(hours=24)
    async def job_prune():
        """添付退避の掃除 (P4相当・14日) + 古いdone行の掃除 + チャンネル名の日次追従 (A10)。"""
        try:
            cutoff = time.time() - ATTACH_KEEP_DAYS * 86400
            n = 0
            if os.path.isdir(ATTACH_DIR):
                for fn in os.listdir(ATTACH_DIR):
                    p = os.path.join(ATTACH_DIR, fn)
                    if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                        os.remove(p)
                        n += 1
            purged = q.purge_done()
            log(f"掃除: 添付{n}件・done行{purged}件")
        except Exception as e:
            log(f"job_prune失敗(継続): {type(e).__name__}")
        try:
            # A10: 台帳の表示名をDiscordの実名へ追従 (旧鳩sync_channel_names_の日次版・裁定2026-07-18)
            changed = 0
            reg = json.load(open(CHANNELS_FILE, encoding="utf-8"))
            for c in reg:
                cid = str(c.get("id", ""))
                ch = client.get_channel(int(cid)) if cid.isdigit() else None
                real = getattr(ch, "name", None)
                if real and c.get("name") != real:
                    log(f"名前追従: {c.get('name')} -> {real}")
                    c["name"] = real
                    if cid in chan_map:
                        chan_map[cid]["name"] = real
                    changed += 1
            if changed:
                with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
                    json.dump(reg, f, ensure_ascii=False, indent=1)
        except Exception as e:
            log(f"名前追従失敗(継続): {type(e).__name__}")

    @tasks.loop(seconds=60)
    async def job_reload_channels():
        """台帳(discord_channels.json)の更新を拾って監視chを入れ替える(2026-07-20 Vol.3)。

        なぜ要るか(実測した事故):
          chan_mapは起動時に1回読むだけだった。frontend部門は7/20 16:37に台帳へ足されたが、
          gatewayは7/19 21:10から動き続けていたため**その部屋を一生見なかった**。
          配線(registry/DEPT_CONF/keeper/port)は全て正しく、registry_tool --check も通る。
          キュー行が1つも生まれないので未配送監視にもorphan監視にも引っかからない
          = **誰も気づけない完全な沈黙**(INC-110と同じ構図の別経路)。
          再起動で直る類だが、「新部門を足したらgatewayを再起動」という運用規律に頼るのは
          忘れた時に無警報で沈むということ。機構で担保する。
        """
        try:
            mt = os.path.getmtime(CHANNELS_FILE)
        except OSError:
            return
        if mt == job_reload_channels.__dict__.get("mtime"):
            return
        job_reload_channels.__dict__["mtime"] = mt
        fresh = load_channel_map()
        if not fresh:
            log("台帳の再読込: 0件だったので入れ替えを見送る(壊れたファイルで監視を失わない)")
            return
        added = set(fresh) - set(chan_map)
        removed = set(chan_map) - set(fresh)
        if added or removed:
            for cid in added:
                log(f"監視ch追加: {fresh[cid].get('name')} (dept={fresh[cid].get('dept')})")
            for cid in removed:
                log(f"監視ch削除: {chan_map[cid].get('name')}")
        chan_map.clear()          # 束縛を差し替えず中身を入れ替える(閉包が見ているのは同じdict)
        chan_map.update(fresh)

    @tasks.loop(seconds=45)
    async def job_pulse():
        """イベントループ自体が生きている証跡を45秒毎に打つ(ジョブ内容と無関係・常時稼働)。"""
        _touch_pulse()

    @client.event
    async def on_ready():
        mode = "jobs=ON" if ACTIVE_JOBS else "shadow(jobs=OFF)"
        log(f"gateway接続 ({mode}): {client.user} / 監視ch {len(chan_map)}件 / queue={QUEUE_DB}")
        _touch_pulse()
        if not job_pulse.is_running():
            job_pulse.start()
        # 台帳追従はACTIVE_JOBSに関係なく回す(受信対象の決定はシャドウ/本番の区別と無関係。
        # むしろシャドウ中こそ「見えていない部屋」を作らないことに意味がある)
        if not job_reload_channels.is_running():
            job_reload_channels.start()
        if ACTIVE_JOBS:
            for j in (job_ack, job_escalate, job_prune):
                if not j.is_running():
                    j.start()

    @client.event
    async def on_message(m):
        _touch_pulse()  # 実メッセージが処理経路を通った証跡(job_pulseの45秒より高解像度)
        if m.author.bot or m.webhook_id:
            # 鳩と同じ例外 (2026-07-18 Chami指示): Chamiミラーには送信印だけ押す (enqueueしない)。
            # jobsゲート内=シャドウ無副作用の原則維持。鳩と並走中は同一絵文字が1個に収束=無害。
            if (ACTIVE_JOBS and m.webhook_id
                    and str(getattr(m.author, "name", "")).startswith("Chami(")):
                try:
                    emoji = (discord.utils.get(m.guild.emojis, name="sendms")
                             or discord.utils.get(m.guild.emojis, name="送信") or "📮")
                    await m.add_reaction(emoji)
                except Exception as e:
                    log(f"ミラー送信印失敗(継続): {type(e).__name__}")
            return  # Bot/Webhookの発言は無視 (自分の返信でループしない=鳩と同じ方針)
        cid = str(m.channel.id)
        if cid not in chan_map:
            # ★黙って捨てない(2026-07-20)。ここは「人が話しかけたのに何も起きない」唯一の分岐で、
            #   キュー行が生まれない=未配送監視もorphan監視も反応しない完全な沈黙点だった。
            #   ch単位で1回だけ記録する(同じ部屋の連投でログを埋めない)。
            seen = on_message.__dict__.setdefault("unknown_ch", set())
            if cid not in seen:
                seen.add(cid)
                log(f"★台帳外chへの発言を破棄: #{getattr(m.channel, 'name', cid)} (id={cid}) "
                    f"from={getattr(m.author, 'name', '?')} — 台帳未登録かgatewayが未追従")
            return
        # ★集中ウィンドウのDiscordトリガー(2026-07-21 Chami要望)。
        #   人間の発言(bot/webhookは上で除外済み)が「集中」「focus」で始まる時だけ、
        #   デーモンの見張り間隔を速くする札(local/llm/focus_until.txt)を立てる。
        #   「集中60」「focus 90」で分指定・「集中off」で終了。誤爆しないよう**先頭一致**に限定。
        _txt = (m.content or "").strip()
        _low = _txt.lower()
        # ★集中ウィンドウは2026-07-21に廃止(常時2秒)。このトリガーは無効化した。
        #   放置すると「集中オフだった場合は…」のような**普通の文**が先頭一致で誤爆し、
        #   さらに文中の数字(「10時間前」の10)を分数として拾って札を立てていた(実測)。
        #   Chamiは「作動してそう」と正しく疑い、HQは誤ったgrep(存在しないパス)で否定した。
        if False:
            try:
                import re as _re
                arg = _txt[2:].strip() if _low.startswith("集中") else _txt[5:].strip()
                focus_file = os.path.join(LOCAL, "llm", "focus_until.txt")
                if arg in ("off", "終了", "0", "オフ"):
                    try:
                        os.remove(focus_file)
                    except OSError:
                        pass
                    msg = "集中ウィンドウ終了(平常=遅い間隔)"
                else:
                    mm = _re.search(r"\d+", arg)
                    minutes = int(mm.group(0)) if mm else 60
                    os.makedirs(os.path.dirname(focus_file), exist_ok=True)
                    with open(focus_file, "w", encoding="utf-8") as f:
                        f.write(str(time.time() + minutes * 60))
                    msg = f"集中ウィンドウ開始 {minutes}分(この間デーモンは速く拾う)"
                log(f"集中トリガー[{chan_map[cid].get('name', cid)}]: {msg}")
                try:
                    emoji = discord.utils.get(m.guild.emojis, name="着手") or "⚡"
                    await m.add_reaction(emoji)
                except Exception:
                    pass
            except Exception as e:
                log(f"集中トリガー失敗(継続): {type(e).__name__}")
            return   # 集中コマンドは会話ではないのでenqueueしない
        rec = record_from_message(m, chan_map[cid])
        if rec["attachments"]:
            # P4相当: CDN失効前にlocalへ写す。to_thread=イベントループを塞がない (OpenClaw #4864の教訓)
            try:
                paths = await asyncio.to_thread(_stash_attachments, rec["attachments"], rec["msg_id"])
                if paths:
                    rec["attachments_local"] = paths
            except Exception as e:
                log(f"添付退避失敗(URLのみで続行): {type(e).__name__}")
        added = q.enqueue(json.dumps(rec, ensure_ascii=False), msg_id=rec["msg_id"], dept=rec["dept"])
        st = q.stats()
        log(f"受信[{rec['channel']}] msg={rec['msg_id']} {'enqueue' if added else '重複無視'} "
            f"(ready={st['ready']} leased={st['leased']})")
        if ACTIVE_JOBS and added and _dept_allowed(rec["dept"]):
            # A2: 送信印 (3段印の1段目=「届いた」の即可視化・裁定2026-07-18で移植)。
            # 並走中は鳩と二重押しになるが、同一Bot同一絵文字はDiscord側で1個に収束=無害。
            try:
                emoji = (discord.utils.get(m.guild.emojis, name="sendms")
                         or discord.utils.get(m.guild.emojis, name="送信") or "📮")
                await m.add_reaction(emoji)
            except Exception as e:
                log(f"送信印失敗(配達は継続): {type(e).__name__}")

    try:
        client.run(token, log_handler=None)
    except discord.errors.PrivilegedIntentsRequired:
        log("ABORT: MESSAGE CONTENT INTENT が未設定です。Developer Portalで有効化が必要 "
            "(Bot設定→Privileged Gateway Intents→MESSAGE CONTENT INTENT=ON)。")
        return 2
    except discord.errors.LoginFailure:
        log("ABORT: Botトークンが無効です (local/discord_bot_token.txt を確認)。")
        return 3
    return 0


def main():
    if "--selftest" in sys.argv:
        return run_selftest()          # selftestは接続しないので単一化の対象外
    if not claim_singleton():
        return 0                        # 既に稼働中=正常終了(superviseが再起動を繰り返さない)
    return run_gateway()


if __name__ == "__main__":
    sys.exit(main())
