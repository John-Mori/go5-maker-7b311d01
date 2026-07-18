#!/usr/bin/env python3
"""部門常駐デーモン (恒久基盤R0・2026-07-18 Chami承認「着手して」)。

なにものか:
  「キャラ=データ、セッション=使い捨て」原則(00_AI-HQ/設計書_恒久基盤リサーチ_2026-07-18.md §3)の実装第1号。
  部門のキャラクターを対話TUIセッションではなく常駐デーモンとして提供する。
  人格=characterfile(HQ管轄)・記憶=jsonlストア(HQ管轄)——**どちらもプロセスの外**にあるため、
  このプロセスが何度死んでもキャラは死なない(daemon_keeperが数秒で再起動し、記憶は繋がる)。

対話窓との共存(重要):
  対話TUI窓(open_dept_window)が開いている間=その部門のinbox_waiterプロセスが居る間は、
  デーモンは**完全に待機**する(箱に触れない=多重応答なし)。窓が閉じた/死んだ瞬間から
  デーモンが同じキャラとして応対を引き継ぐ。=「窓は人間の操作卓、常在はデーモン」。

presence:
  毎ループ claude_active_<dept>.txt をtouchする(唯一の書き手が対話窓waiterからデーモンに拡張)。
  → pollerは部門箱へ配送し続け、watchdog P2「窓死」通知は鳴らない(部門は実際に有人=デーモン)。
  加えて /live /ready をHTTPで公開(k8s probeパターン。mtime推定をR2でこれに置換する布石)。

応答の生成:
  claude --print(CLAUDE_CODE_OAUTH_TOKEN・タイムアウト300s)に characterfile+記憶末尾N件+新着 を
  渡し、**返信本文だけ**を生成させる(ツール実行はさせない=口調崩れ・暴走の面を最小化)。
  送信(persona_send)・既読(react)・記憶追記・台帳記帳はデーモンが機械的に行う=確実性を機械に、
  人格を生成に、で分担する。

使い方:
  python scripts/llm/dept_daemon.py --dept hr-room          # 常駐
  python scripts/llm/dept_daemon.py --dept hr-room --once   # 1巡回(点検)
  python scripts/llm/dept_daemon.py --dept hr-room --once --dry-run  # 送信せず生成まで(テスト)
テスト: 環境変数 GO5_LOCAL_DIR があれば local/ の代わりにそれを使う。
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
HQ = r"D:\SougouStartFolder\00_AI-HQ"
TOKEN_FILE = os.path.join(LOCAL, "cli_auth_token.txt")
PROCESSED = os.path.join(LOCAL, "discord_processed.jsonl")
CLAUDE = r"C:\Users\chami\.local\bin\claude.exe"
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
REACT = os.path.join(ROOT, "scripts", "discord", "react.py")
MAIN_INBOX = os.path.join(LOCAL, "discord_inbox.jsonl")

POLL_SEC = 3                    # 箱の見張り間隔(waiterの2秒に準拠した軽さ)
INTERACTIVE_CHECK_SEC = 30      # 対話窓waiterの存在確認の間隔(プロセス列挙は重いのでキャッシュ)
MEMORY_TAIL = 20                # promptへ注入する記憶の末尾件数
PRINT_TIMEOUT = 300
WORK_WORDS = ("直して", "修正", "実装", "追加して", "デプロイ", "変えて", "作って", "調べて",
              "特定して", "バグ", "エラー", "壊れ", "対応して", "やって", "反映", "消して", "削除")

# 部門→(characterfile, 記憶ストア, 送信ペルソナ名, /liveポート)。R2で全部門へ拡張。
DEPT_CONF = {
    "hr-room": {
        "character": os.path.join(HQ, "departments", "hr", "characters", "kukuru.md"),
        "memory": os.path.join(HQ, "departments", "hr", "memory", "hr-room.jsonl"),
        "persona": "ククール",
        "port": 18801,
    },
}


def log(dept, msg):
    print(f"{time.strftime('%H:%M:%S')} [{dept}] {msg}")


class Daemon:
    def __init__(self, dept, dry_run=False):
        if dept not in DEPT_CONF:
            raise SystemExit(f"未対応dept: {dept} (DEPT_CONFへ登録を)")
        self.dept = dept
        self.conf = DEPT_CONF[dept]
        self.dry_run = dry_run
        self.box = os.path.join(LOCAL, "inbox", f"{dept}.jsonl")
        self.pulse = os.path.join(LOCAL, "llm", f"claude_active_{dept}.txt")
        self.last_loop = 0.0            # /live用: 最終ループ完了時刻
        self._interactive_until = 0.0   # 対話窓チェックのキャッシュ期限
        self._interactive = False
        self.token = ""
        try:
            self.token = open(TOKEN_FILE, encoding="utf-8").read().strip()
        except OSError:
            pass

    # --- 対話窓の検出(居るならデーモンは待機) ---
    def interactive_alive(self):
        now = time.time()
        if now < self._interactive_until:
            return self._interactive
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                 "Where-Object { $_.CommandLine -match 'inbox_waiter' -and "
                 f"$_.CommandLine -match '--name +{self.dept}( |$)' }}).Count"],
                capture_output=True, text=True, timeout=25)
            self._interactive = int((r.stdout or "0").strip() or 0) > 0
        except Exception:
            self._interactive = False  # 判定不能=デーモンが受ける(可用性優先)
        self._interactive_until = now + INTERACTIVE_CHECK_SEC
        return self._interactive

    # --- presence ---
    def touch_pulse(self):
        os.makedirs(os.path.dirname(self.pulse), exist_ok=True)
        with open(self.pulse, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()) + "\n")

    # --- 記憶 ---
    def memory_tail(self):
        p = self.conf["memory"]
        if not os.path.exists(p):
            return []
        rows = []
        for line in open(p, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return rows[-MEMORY_TAIL:]

    def memory_append(self, rec, reply):
        p = self.conf["memory"]
        os.makedirs(os.path.dirname(p), exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "msg_id": str(rec.get("msg_id", "")),
                 "from": rec.get("author", ""), "content": str(rec.get("content", ""))[:500],
                 "reply": reply[:500]}
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # --- 応答生成(claude --print・本文のみ) ---
    def generate(self, rec):
        character = open(self.conf["character"], encoding="utf-8").read()
        mem = self.memory_tail()
        mem_text = "\n".join(
            f"- {m['ts']} {m['from']}:「{m['content'][:120]}」→ オレ:「{m['reply'][:120]}」"
            for m in mem) or "(まだ無い)"
        content = str(rec.get("content", ""))
        atts = rec.get("attachments") or []
        att_note = f"\n(添付{len(atts)}件あり。画像の中身は見えていない=見えている振りをしない)" if atts else ""
        is_work = any(w in content for w in WORK_WORDS)
        work_note = ("\n★この便は作業依頼の可能性が高い。内容に踏み込まず「研究室へ回す」と短く伝えろ"
                     "(回送はシステムが自動でやる)。" if is_work else "")
        prompt = (
            "あなたは以下のcharacterfileのキャラクターとして、Discordの新着1件に返信する。\n"
            "出力は【返信本文のみ】。前置き・説明・引用符・メタ発言・箇条書きの分析は一切禁止。"
            "キャラの声で、チャットとして自然な短さで。\n\n"
            f"=== characterfile ===\n{character}\n\n"
            f"=== 直近の記憶(古→新) ===\n{mem_text}\n\n"
            f"=== 新着(送信者: {rec.get('author','')}) ===\n{content}{att_note}{work_note}"
        )
        env = dict(os.environ)
        env["CLAUDE_CODE_OAUTH_TOKEN"] = self.token
        p = subprocess.run([CLAUDE, "--print", prompt], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=PRINT_TIMEOUT)
        reply = (p.stdout or "").strip()
        return (reply, is_work) if p.returncode == 0 and reply else (None, is_work)

    # --- 1件処理 ---
    def handle(self, rec, raw_line):
        ch = rec.get("channel", "")
        mid = str(rec.get("msg_id", ""))
        if not self.dry_run and ch and mid:
            subprocess.run([sys.executable, REACT, "--channel", ch, "--msg", mid,
                            "--emoji", "既読"], capture_output=True, timeout=60)
        try:
            reply, is_work = self.generate(rec)
        except subprocess.TimeoutExpired:
            log(self.dept, f"生成タイムアウト msg={mid}")
            return False
        if not reply:
            log(self.dept, f"生成失敗 msg={mid}")
            return False
        if self.dry_run:
            log(self.dept, f"[dry-run] reply={reply[:100]!r} work={is_work}")
        else:
            body = os.path.join(LOCAL, f"_daemon_reply_{self.dept}.txt")
            with open(body, "w", encoding="utf-8") as f:
                f.write(reply)
            r = subprocess.run([sys.executable, PERSONA_SEND, "--channel", ch,
                                "--persona", self.conf["persona"], "--body-file", body],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            if r.returncode != 0:
                log(self.dept, f"送信失敗 msg={mid}")
                return False
            if is_work:  # 作業依頼はmain箱へ機械的に回送(研究室が本対応)
                with open(MAIN_INBOX, "a", encoding="utf-8") as f:
                    f.write(raw_line.rstrip("\n") + "\n")
            with open(PROCESSED, "a", encoding="utf-8") as f:
                f.write(raw_line.rstrip("\n") + "\n")
        self.memory_append(rec, reply)
        log(self.dept, f"応答完了 msg={mid} work={is_work}")
        return True

    # --- 箱ドレイン(INC-100対策: inflight退避→1件着地毎に書き戻し) ---
    def drain(self):
        if not os.path.exists(self.box) or os.path.getsize(self.box) == 0:
            return 0
        inflight = self.box + ".inflight"
        try:
            os.replace(self.box, inflight)  # 原子的退避
        except OSError:
            return 0
        lines = [l for l in open(inflight, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
        done = 0
        for i, line in enumerate(lines):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            self.handle(rec, line)
            done += 1
            rest = lines[i + 1:]  # 残りだけをinflightへ書き戻す(kill耐性)
            with open(inflight, "w", encoding="utf-8") as f:
                for l in rest:
                    f.write(l + "\n")
        try:
            if os.path.getsize(inflight) == 0:
                os.remove(inflight)
        except OSError:
            pass
        return done

    def recover_inflight(self):
        """前回killの取り残し(inflight)を起動時に箱へ戻す=喪失を遅延に変える。"""
        inflight = self.box + ".inflight"
        if os.path.exists(inflight) and os.path.getsize(inflight) > 0:
            with open(inflight, encoding="utf-8", errors="replace") as f:
                data = f.read()
            with open(self.box, "a", encoding="utf-8") as f:
                f.write(data if data.endswith("\n") else data + "\n")
            os.remove(inflight)
            log(self.dept, "inflight回収→箱へ戻した")

    # --- /live /ready ---
    def start_probe_server(self):
        daemon = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/live":
                    ok = (time.time() - daemon.last_loop) < 30  # ループが30秒止まったら死
                elif self.path == "/ready":
                    ok = bool(daemon.token) and os.path.exists(CLAUDE)
                else:
                    ok = False
                self.send_response(200 if ok else 503)
                self.end_headers()
                self.wfile.write(b"ok" if ok else b"ng")

            def log_message(self, *a):  # アクセスログは出さない
                pass

        try:
            srv = ThreadingHTTPServer(("127.0.0.1", self.conf["port"]), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            log(self.dept, f"probe: http://127.0.0.1:{self.conf['port']}/live /ready")
        except OSError as e:
            log(self.dept, f"probe起動失敗(続行): {type(e).__name__}")

    # --- メインループ ---
    def run(self, once=False):
        if not self.token:
            log(self.dept, "cli_auth_token.txt なし=生成不可。claude setup-token を")
            return 2
        log(self.dept, f"部門デーモン起動 (character={os.path.basename(self.conf['character'])}"
                       f"{'・dry-run' if self.dry_run else ''})")
        self.start_probe_server()
        self.recover_inflight()
        while True:
            try:
                if self.interactive_alive():
                    pass  # 対話窓が生きている=本人が応対。箱に触れない(脈も窓waiterが打つ)
                else:
                    self.touch_pulse()
                    n = self.drain()
                    if n:
                        log(self.dept, f"{n}件処理")
                self.last_loop = time.time()
            except Exception as e:
                log(self.dept, f"ループ失敗: {type(e).__name__}: {e}")
            if once:
                return 0
            time.sleep(POLL_SEC)


def main():
    ap = argparse.ArgumentParser(description="部門常駐デーモン(キャラ=データ・R0)")
    ap.add_argument("--dept", required=True)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return Daemon(a.dept, dry_run=a.dry_run).run(once=a.once)


if __name__ == "__main__":
    sys.exit(main())
