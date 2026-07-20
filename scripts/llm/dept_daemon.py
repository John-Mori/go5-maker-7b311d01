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
WORK_TIMEOUT = 600             # ツール付き作業(work_generate)の上限
WORK_MODEL = "sonnet"          # ★O3(裁-3): 作業agentのモデルを固定(実装の物量=sonnet・分業表準拠)
# ★O3(裁-3・改善書P1-5): 作業agentの許可ツールを最小allowlistへ固定。旧 bypassPermissions は
#   「何でも実行可」=プロンプトインジェクション耐性が最弱線だった。--print(headless)では未許可
#   ツールは自動拒否(プロンプトを出せないため)=allowlist外は安全に落ちる。ファイル作業+検証に
#   必要な範囲だけ許可。Bashのコマンド単位のさらなる絞り込みはO5の follow-up。
WORK_ALLOWED_TOOLS = ["Read", "Edit", "Write", "Grep", "Glob", "Bash"]
# 作業依頼キーワード(=main箱回送 or work_scope部門でのwork_generate起動の判定に使う)。
# ★依頼形(〜して/〜お願い等)に限定する(2026-07-20 qa-reviewer点検・過剰回送修正=INC本文参照)。
#   旧版は「反映」「実装」「修正」「デプロイ」等を裸の名詞で拾っており、"反映完了したら知らせて"
#   のような単なる報告依頼(情報要求)にも一致→研究室への過剰回送(実測 hq 8件+hr-context 5件)の主因だった。
#   バグ/エラー/壊れ は完了報告パターン(「〜したら知らせて」)と結びつかない症状語のため対象外
#   (system-engineerの通常のバグ報告受理を壊さないよう保守的に現状維持)。
WORK_WORDS = ("直して", "直しといて", "修正して", "修正お願い", "実装して", "実装お願い",
              "追加して", "デプロイして", "デプロイお願い", "変えて", "作って", "調べて",
              "特定して", "バグ", "エラー", "壊れ", "対応して", "やって",
              "反映して", "反映お願い", "反映をお願い", "消して", "削除して", "削除お願い")
# 情報要求語(教えて/知らせて/確認して 等)。WORK_WORDSはこれらとは重複しない設計
# (=情報要求のみの文はWORK_WORDSに一致せず自動的にis_work=Falseになる)。
# テスト(test_dept_daemon_classify.py)で非重複と分類結果を検証する。
INFO_WORDS = ("教えて", "教えてほしい", "知らせて", "確認して", "見てほしい", "見せて")


def classify_work(content):
    """本文が「作業依頼」かどうかを判定する(main箱回送/work_scope起動の判定に使用)。

    単純なWORK_WORDS部分一致だが、判定ロジックを1箇所に集約することで
    generate()とhandle()の重複判定がズレる事故を防ぐ(2026-07-20)。
    """
    return any(w in str(content) for w in WORK_WORDS)


# 部門→(characterfile, 記憶ストア, 送信ペルソナ名, /liveポート, 作業範囲)。R2で全部門へ拡張(2026-07-19 Chami「やって」)。
# work_scope: 定義があると作業依頼(WORK_WORDS)をツール付きagentで**部屋の中で完結**させる
#   (2026-07-18 Chami「反映作業もここでやれないのか?」への恒久回答)。範囲外はmain箱へ回送。
# work_scope無し: 会話はキャラで即応・作業依頼はキャラの声で受けてmain箱へ回送(研究室が本対応)。
# 機微部屋(dream-care/past-room/health-log)は対象外=PROTOCOL管轄・デーモン化しない。
_CHAR = os.path.join(HQ, "departments", "hr", "characters")
_MEM = os.path.join(HQ, "departments", "hr", "memory")
DEPT_CONF = {
    "hq": {  # 研究室HQの二段構え: アメスが即応・判断/作業はアロンソ(研究室)へ回送
        "character": os.path.join(_CHAR, "ames.md"),
        "memory": os.path.join(_MEM, "hq.jsonl"),
        "persona": "アメス",
        "port": 18800,
    },
    "hr-room": {
        "character": os.path.join(_CHAR, "kukuru.md"),
        "memory": os.path.join(_MEM, "hr-room.jsonl"),
        "persona": "ククール",
        "port": 18801,
        "work_scope": (
            "あなたが自分で完結してよい作業(hr範囲):\n"
            "- ペルソナ台帳・人事文書の編集: D:\\SougouStartFolder\\00_AI-HQ\\departments\\hr\\ 配下\n"
            "- アバター/差分の反映: local/attachments/ の画像を local/persona_avatars.json へ登録"
            "(R2アップロードは scripts/discord/migrate_avatars_to_r2.py の put_r2 関数を使う"
            "=sha256キー・URL=https://go5-sync.trustsignalbot.workers.dev/img/<sha256>。"
            "台帳は必ず .bak を作ってから書き換え、登録後にURLへHEADして200を確認)\n"
            "- local/persona_sprites/・local/persona_context/ の整理\n"
            "範囲外(=回送): 上記以外のコード変更・他部門/他PJのファイル・GAS/Worker/デプロイ・queue/常駐の改修"
        ),
    },
    "hr-context": {  # ククールのもう一つの部屋(キャラ背景の聞き取り)。記憶は部屋別
        "character": os.path.join(_CHAR, "kukuru.md"),
        "memory": os.path.join(_MEM, "hr-context.jsonl"),
        "persona": "ククール",
        "port": 18807,
    },
    "qa-reviewer": {
        "character": os.path.join(_CHAR, "gentildonna.md"),
        "memory": os.path.join(_MEM, "qa-reviewer.jsonl"),
        "persona": "ジェンティルドンナ",
        "port": 18802,
        "work_scope": (
            "あなたが自分で完結してよい作業(品質・監査範囲。正本=D:\\SougouStartFolder\\00_AI-HQ\\"
            "departments\\qa\\BOOT.md・検証標準.md):\n"
            "- 品質基準の策定・保守: 検証標準.md(8条・判定様式)の追記/更新\n"
            "- 独立検証・Release Gate判定(APPROVED/APPROVED WITH CONDITIONS/REJECTED/ESCALATED)\n"
            "- 回帰チェック実行: python docs/departments/qa-reviewer/checks/run_all.py\n"
            "- インシデント→回帰テスト化(docs/departments/qa-reviewer/checks/ への追加)\n"
            "範囲外(=回送): 検証対象そのものの実装修正(直すのは実装部門)・他PJの品質基準変更(HQへ相談)"
        ),
    },
    "system-engineer": {
        "character": os.path.join(_CHAR, "debruyne.md"),
        "memory": os.path.join(_MEM, "system-engineer.jsonl"),
        "persona": "ケヴィン・デ・ブライネ",
        "port": 18803,
        "work_scope": (
            "あなたが自分で完結してよい作業(改修範囲。正本=docs/departments/system-engineer/BOOT.md):\n"
            "- フロント(Pages)/GAS/Workerの改修実装\n"
            "- ★着手前に必ず所有権黒板を確認: python scripts/ownership.py check \"<キーワード>\""
            "(exit=2=作業中なら実装しない。exit=0=空きなら claim してから着手・完了で release)\n"
            "範囲外(=回送): 所有権が競合する変更・人事/QA/座標系(CLAUDE.md §3)を壊す変更・"
            "他部門の担当ドキュメント"
        ),
    },
    "product-scout": {
        "character": os.path.join(_CHAR, "sena.md"),
        "memory": os.path.join(_MEM, "product-scout.jsonl"),
        "persona": "十王星南",
        "port": 18804,
        "work_scope": (
            "あなたが自分で完結してよい作業(商品-候補範囲。正本=docs/departments/product-scout/BOOT.md):\n"
            "- 素材・潜在力の一次評価(星南)・採算/投入条件/A〜E判定(クラウディア)\n"
            "- 評価結果をdocs/departments/product-scout/配下の記録ファイルへ追記\n"
            "範囲外(=回送): コード実装・他部門の担当領域・投稿可否の最終判断(qa-reviewerへ)"
        ),
    },
    "shorts-analyst": {
        "character": os.path.join(_CHAR, "modric.md"),
        "memory": os.path.join(_MEM, "shorts-analyst.jsonl"),
        "persona": "ルカ・モドリッチ",
        "port": 18805,
        "work_scope": (
            "あなたが自分で完結してよい作業(分析範囲。正本=docs/departments/shorts-analyst/BOOT.md):\n"
            "- 内部KPI・確実性・最終整理(モドリッチ)/外部調査・競合・新仮説(アーモンドアイ)\n"
            "- 分析結果をdocs/departments/shorts-analyst/(hypotheses.md・STATUS.md等)へ記録\n"
            "範囲外(=回送): コード実装・投稿判断そのもの(qa-reviewer/copy-directorと合議)"
        ),
    },
    "copy-director": {
        "character": os.path.join(_CHAR, "mitoma.md"),
        "memory": os.path.join(_MEM, "copy-director.jsonl"),
        "persona": "三笘薫",
        "port": 18806,
        "work_scope": (
            "あなたが自分で完結してよい作業(コピー部範囲。正本=docs/departments/copy-director/BOOT.md・"
            "copy-rules.md):\n"
            "- 訴求文・タイトル・作者名表記・Bluesky投稿文・画像フック評価・コピー改善\n"
            "- 執筆前にcopy-rules.mdのガードレール(字数・規約)を通す\n"
            "- タスク後の知見をcopy-rules/winning-patterns/rejected-patternsのいずれかへ1行追記\n"
            "範囲外(=回送): 露出・煽り判定に迷う/評価が割れる境界事例は**自己判断で通さず**回送"
            "(規約の最終判断はCreativeだけで行わない)・コード実装"
        ),
    },
    "learning-coach": {  # 4コーチ対等の中からChami指名(2026-07-19「学習室はヴィルシーナで」)
        "character": os.path.join(_CHAR, "verxina.md"),
        "memory": os.path.join(_MEM, "learning-coach.jsonl"),
        "persona": "ヴィルシーナ",
        "port": 18808,
        "work_scope": (
            "あなたが自分で完結してよい作業(学習範囲。正本=docs/departments/learning-coach/BOOT.md):\n"
            "- 質問への解説・学ぶ順序の提示(2層モデル=人格層はコーチ4人・知識層は"
            "personas/instructors/を書棚として参照)\n"
            "- 理解確認は短く1問程度(過剰な小テストはしない)\n"
            "範囲外(=回送): コード実装・他部門の担当内容"
        ),
    },
}


def log(dept, msg):
    print(f"{time.strftime('%H:%M:%S')} [{dept}] {msg}")


# ★O5(2026-07-20): 認証失効の自動検知。cli_auth_token.txt(claude setup-token由来)は
#   自動更新が無く失効する(2026-07-19に49hで401失効を実測)。失効すると generate/work_generate が
#   静かに失敗しmain箱へescalateするだけ=Lab生存中は露見しない。ここで401を検知し報告-通知へ
#   1回だけ(1hクールダウン・全9デーモン共有state)警報する=「気づけない沈黙の劣化」を潰す。
_AUTH_ALERT_STATE = os.path.join(LOCAL, "_auth_alert_state.json")
_AUTH_ALERT_COOLDOWN = 3600


def _looks_like_auth_failure(text):
    t = text or ""
    return ("token has expired" in t
            or "OAuth" in t and "authenticate" in t
            or ("401" in t and "authenticate" in t)
            or "Failed to authenticate" in t)


def _maybe_alert_auth(dept, output):
    if not _looks_like_auth_failure(output):
        return
    now = time.time()
    try:
        st = json.load(open(_AUTH_ALERT_STATE, encoding="utf-8"))
    except Exception:
        st = {}
    if now - st.get("last", 0) < _AUTH_ALERT_COOLDOWN:
        return
    msg = (f"🔑 **認証失効の疑い**(自動検知): dept={dept} のClaude呼び出しが認証エラーを返した。"
           "local/cli_auth_token.txt のOAuthトークンが失効している可能性(自動更新なし)。"
           "対処: PCで `claude setup-token` を実行し、出力を local/cli_auth_token.txt へ上書き保存。"
           "その間、キャラの生成応答はmain箱へ自動escalateされる(取りこぼしは無し・研究室が対応)。")
    try:
        subprocess.run([sys.executable, PERSONA_SEND, "--dept", "report-notify", "--persona", "オタコン", msg],
                       capture_output=True, timeout=60)
        json.dump({"last": now}, open(_AUTH_ALERT_STATE, "w", encoding="utf-8"))
        log(dept, "認証失効を検知→報告-通知へ警報")
    except Exception:
        pass


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
    def _token(self):
        """★2026-07-20(裁4): トークンを都度読む。更新が艦隊再起動なしで即反映される
        (今夜の痛み=失効→再認証後に全再起動、を次回から不要にする)。読めなければ起動時値へ。"""
        try:
            t = open(TOKEN_FILE, encoding="utf-8").read().strip()
            if t:
                return t
        except OSError:
            pass
        return self.token

    def generate(self, rec):
        character = open(self.conf["character"], encoding="utf-8").read()
        mem = self.memory_tail()
        mem_text = "\n".join(
            f"- {m['ts']} {m['from']}:「{m['content'][:120]}」→ オレ:「{m['reply'][:120]}」"
            for m in mem) or "(まだ無い)"
        content = str(rec.get("content", ""))
        atts = rec.get("attachments") or []
        att_note = f"\n(添付{len(atts)}件あり。画像の中身は見えていない=見えている振りをしない)" if atts else ""
        is_work = classify_work(content)
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
        env["CLAUDE_CODE_OAUTH_TOKEN"] = self._token()
        p = subprocess.run([CLAUDE, "--print", prompt], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=PRINT_TIMEOUT)
        reply = (p.stdout or "").strip()
        if p.returncode != 0 or not reply:
            _maybe_alert_auth(self.dept, (p.stdout or "") + (p.stderr or ""))
            return (None, is_work)
        return (reply, is_work)

    def work_generate(self, rec):
        """作業依頼をツール付きagentで部屋の中で完結させる(hr範囲=work_scope)。

        契約: agentは返信本文を reply_file に書く。範囲外で研究室回送が要る時だけ esc_flag を作る。
        stdoutは使わない(マーカー混入やメタ出力の事故を排除=決定論的な受け渡し)。
        """
        character = open(self.conf["character"], encoding="utf-8").read()
        mem = self.memory_tail()
        mem_text = "\n".join(
            f"- {m['ts']} {m['from']}:「{m['content'][:120]}」→ 自分:「{m['reply'][:120]}」"
            for m in mem) or "(まだ無い)"
        reply_file = os.path.join(LOCAL, f"_daemon_workreply_{self.dept}.txt")
        esc_flag = os.path.join(LOCAL, f"_daemon_escalate_{self.dept}.flag")
        for p in (reply_file, esc_flag):
            try:
                os.remove(p)
            except OSError:
                pass
        atts = rec.get("attachments_local") or []
        att_note = ("\n添付(ローカル保存済み): " + ", ".join(atts)) if atts else ""
        prompt = (
            "あなたは以下のcharacterfileのキャラクターであり、部門の実作業も行う担当者です。\n"
            f"{self.conf['work_scope']}\n\n"
            f"=== characterfile ===\n{character}\n\n"
            f"=== 直近の記憶(古→新) ===\n{mem_text}\n\n"
            f"=== 依頼(送信者: {rec.get('author','')}) ===\n{rec.get('content','')}{att_note}\n\n"
            "■やること\n"
            "1. 依頼がhr範囲内なら、その場で作業を完遂する(検証まで。憶測で完了と言わない)。\n"
            f"2. 完了/結果の返信本文(キャラの声・短く)を {reply_file} に書く。\n"
            f"3. hr範囲外で研究室への回送が必要な場合だけ、空ファイル {esc_flag} を作り、"
            "返信には「受けた・研究室へ回す」旨を書く。\n"
            "4. 秘密(トークン/PW)は出力しない。Discordへの直接送信はしない(送信はシステムが行う)。"
        )
        env = dict(os.environ)
        env["CLAUDE_CODE_OAUTH_TOKEN"] = self._token()
        # ★promptはstdinで渡す(引数で渡すと--add-dirが可変長のためpromptまでdirとして
        #   飲み込み「Input must be provided」で即死する=2026-07-18に実障害。stdinは
        #   Windowsのコマンドライン長制限(約32K)の回避にもなる)
        # ★O3: bypassPermissions を廃し、最小allowlist + モデル固定で起動。
        #   --allowedTools は可変長。直後に別フラグ(--add-dir)が来るのでツール列はそこで区切られる。
        #   promptはstdin(引数だと可変長フラグが飲み込む2026-07-18の実障害の回避)。
        p = subprocess.run(
            [CLAUDE, "--print", "--model", WORK_MODEL,
             "--allowedTools", *WORK_ALLOWED_TOOLS,
             "--add-dir", HQ],
            input=prompt, cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=WORK_TIMEOUT)
        reply = ""
        if os.path.exists(reply_file):
            reply = open(reply_file, encoding="utf-8", errors="replace").read().strip()
        escalate = os.path.exists(esc_flag)
        if p.returncode != 0 or not reply:
            _maybe_alert_auth(self.dept, (p.stdout or "") + (p.stderr or ""))
            return None, True  # 失敗=安全側(回送)へ
        return reply, escalate

    # --- 1件処理 ---
    def handle(self, rec, raw_line):
        ch = rec.get("channel", "")
        mid = str(rec.get("msg_id", ""))
        if not self.dry_run and ch and mid:
            subprocess.run([sys.executable, REACT, "--channel", ch, "--msg", mid,
                            "--emoji", "既読"], capture_output=True, timeout=60)
        is_work = classify_work(rec.get("content", ""))
        try:
            if is_work and self.conf.get("work_scope"):
                # 作業依頼は部屋の中で完結を試みる(範囲外だけ回送=escalate)
                reply, is_work = self.work_generate(rec)  # is_work=回送要否に読み替え
            else:
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
            ok = self.handle(rec, line)
            if not ok:
                # ★失敗を黙って落とさない(2026-07-18実障害: 「ククール、反映して。」が
                #   生成失敗→箱から消失=INC-103族)。failedへ記録し、main箱へ回送
                #   (研究室が安全網として本対応。二重処理はprocessed台帳が防ぐ)
                with open(self.box + ".failed.jsonl", "a", encoding="utf-8") as f:
                    f.write(line.rstrip("\n") + "\n")
                with open(MAIN_INBOX, "a", encoding="utf-8") as f:
                    f.write(line.rstrip("\n") + "\n")
                log(self.dept, f"処理失敗→failed記録+main箱へ回送 msg={rec.get('msg_id')}")
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

    def drain_queue(self):
        """LeaseQueue経路のドレイン(切替④の必須前提・2026-07-19)。

        カットオーバー後はjsonlに新着が来ない=queueを読めないデーモンは盲目になる
        (手順書_受信基盤切替_段階2 §1-0と同じ穴のデーモン版)。claim→handle→ack。
        DBが無い間は何もしない(fail-open)。二重処理はprocessed台帳で防ぐ。
        """
        qdb = os.path.join(LOCAL, "queue", "inbox.db")
        if not os.path.exists(qdb):
            return 0
        try:
            sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
            from leasequeue import LeaseQueue
            q = LeaseQueue(qdb)
        except Exception:
            return 0
        done = 0
        try:
            processed = set()
            try:
                for pl in open(PROCESSED, encoding="utf-8", errors="replace"):
                    try:
                        m = json.loads(pl).get("msg_id")
                        if m:
                            processed.add(str(m))
                    except Exception:
                        continue
            except OSError:
                pass
            while done < 5:  # 1巡回の上限(暴走ガード)
                c = q.claim(dept=self.dept, who=f"dept_daemon:{self.dept}")
                if c is None:
                    break
                rec = c["body"] if isinstance(c["body"], dict) else {}
                mid = str(rec.get("msg_id", c.get("msg_id") or ""))
                if mid and mid in processed:
                    q.ack(c["id"], result="skip(処理済)")
                    continue
                ok = self.handle(rec, json.dumps(rec, ensure_ascii=False))
                q.ack(c["id"], result="キャラ応答" if ok else "失敗(main回送済)")
                if not ok:  # jsonl側drainと同じ安全網: 失敗はmain箱へ
                    with open(MAIN_INBOX, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done += 1
        finally:
            q.close()
        if done:
            log(self.dept, f"queue経路 {done}件処理")
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
                    n = self.drain() + self.drain_queue()
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
