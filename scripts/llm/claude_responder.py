#!/usr/bin/env python3
"""無人時のClaude応答係 (研究室が死んでいる間、main箱を claude --print で処理する常駐)。

なぜ要るか(2026-07-17に判明した真因):
  Discordの配達(鳩)は常駐で生きているが、**返すのは開いたClaudeセッションだけ**。全セッションが
  死ぬと、送信スタンプは付くのに反応が無い(Chamiの「大至急」が3時間放置=INC-98)。
  台本で対話セッションを復活させる案は認証(未ログイン)と対話プロンプトの無人実行で行き詰まった。
  → 解決: **`claude --print` は無人でツール実行まで完走する**(認証はCLAUDE_CODE_OAUTH_TOKEN・
    信頼/MCP/権限で止まらない・実測でDiscord自律投稿まで成功)。対話セッションを生かし続ける
    代わりに、新着1件ごとに使い捨ての --print を回す。止まる所が無い=死なない。

責任範囲(1つだけ):
  **main箱(local/discord_inbox.jsonl)を、研究室セッションが死んでいる時だけ**処理する。
  研究室が生きている時は触らない(本人が応対する)。=最後の受け皿。

ガード(安全のため):
  - 研究室が生存(claude_active.txt が新しい)なら何もしない=多重応答を防ぐ。
  - 機微部屋(dream-care/past-room/health-log)の**内容には触らない**(privacy)。無人シグナルは
    absence_watchdog が別途出す。ここではprocessed送りにせず残す(本人/研究室が後で応対)。
  - 処理済み台帳(discord_processed.jsonl)で二重処理を防ぐ。
  - 1巡回あたりの上限(暴走・費用の歯止め)。
  - Chamiのサブスクを使うため呼び出しは最小限に。

前提: local/cli_auth_token.txt (claude setup-token のOAuthトークン・gitignore済)。

使い方:
  python scripts/llm/claude_responder.py --once   # 1巡回で終了(点検/テスト)
  python scripts/llm/claude_responder.py          # 常駐(POLL秒間隔)
"""
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
INBOX = os.path.join(LOCAL, "discord_inbox.jsonl")
PROCESSED = os.path.join(LOCAL, "discord_processed.jsonl")
TOKEN_FILE = os.path.join(LOCAL, "cli_auth_token.txt")
LAB_PULSE = os.path.join(LOCAL, "llm", "claude_active.txt")     # readiness=waiterの脈(箱を見ている)
LAB_TOOL_PULSE = os.path.join(LOCAL, "llm", "lab_tool_pulse.txt")  # liveness=presence hookの脈(道具を使って働いている)
CLAUDE = r"C:\Users\chami\.local\bin\claude.exe"

POLL_SEC = 20
# ★2信号判定へ改訂(2026-07-18・S1 presence hook導入・出荷前批評のfatal指摘反映):
#   readiness(waiter脈) < READY_SEC          → 生存(耳が箱を見ている=本人が応対する)
#   さもなくば liveness(hook脈) < BUSY_SEC
#     かつ readiness < HARD_CAP_SEC          → 生存扱い(処理中で耳が一時停止。ターン末尾に再武装される猶予)
#   それ以外                                  → 死亡=代打が出る
# HARD_CAP: livenessがいくら新しくても、耳が45分止まったままなら代打を出す(硬い上限)。
#   これが無いと「耳が死んだまま作業を続ける研究室」が新着を永久に放置できてしまう
#   (=フック導入が900秒の安全網を撤廃してしまう、という批評の指摘への対処)。
# 旧LAB_ALIVE_SEC=900(閾値だけで凌ぐ応急)はこの2信号で置き換え。INC-94の誤発火は
# liveness猶予で防ぎ、真の死亡はreadiness 90秒+liveness 300秒で従来より速く検知できる。
READY_SEC = 90                 # waiterは監視中2秒毎に脈を打つ=90秒あれば十分
BUSY_SEC = 300                 # 直近5分以内にツール実行があれば「処理中」とみなす
HARD_CAP_SEC = 45 * 60         # 耳の停止がこれを超えたら、働いていても代打を出す
MAX_PER_CYCLE = 3              # 1巡回で処理する上限(暴走と費用の歯止め)
SENSITIVE_DEPTS = ("dream-care", "past-room", "health-log")


def read_token():
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _age(path):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return float("inf")


def lab_alive():
    ready = _age(LAB_PULSE)       # readiness: 耳(waiter)が箱を見ているか
    if ready < READY_SEC:
        return True
    busy = _age(LAB_TOOL_PULSE)   # liveness: 道具を使って働いているか(presence hook)
    return busy < BUSY_SEC and ready < HARD_CAP_SEC


def processed_ids():
    ids = set()
    if not os.path.exists(PROCESSED):
        return ids
    for line in open(PROCESSED, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line).get("msg_id")
            if m:
                ids.add(str(m))
        except Exception:
            continue
    return ids


def build_prompt(rec):
    """研究室の代打として1件を処理させる指示。Claudeがrepoを読んで適切な人格で応対する。"""
    ch = rec.get("channel", "")
    dept = rec.get("dept", "router")
    author = rec.get("author", "")
    content = rec.get("content", "")
    return (
        "あなたは go5-maker AI組織の『研究室』の無人代打です(claude --print・使い捨て起動)。"
        "全セッションが落ちている間、Chamiのメッセージ1件を処理して応答するのが仕事です。\n\n"
        f"■受信: チャンネル『{ch}』(部門 {dept})・送信者 {author}\n"
        f"■本文:\n{content}\n\n"
        "■やること\n"
        "1. まず既読を押す: python scripts/discord/react.py --channel " + json.dumps(ch, ensure_ascii=False) + " --msg " + str(rec.get("msg_id", "")) + " --emoji 既読\n"
        "2. 内容を判断し、Discordへ短く返信する。返信は必ず本文をファイルに書いてから "
        "python scripts/discord/persona_send.py --channel <ch名かID> --persona '研究室(無人代打)' --body-file <path> で送る。\n"
        "   ★あなたは使い捨ての無人代打で、アメス/ククール等の作り込まれたリッチ人格を演じ切れない="
        "無理に演じると口調が崩れ『キャラ設定が壊れた』という誤認を生む(実害・QA確認2026-07-18・D2)。"
        "だから演技も気の利いた文章も一切しない。名乗りは『研究室(無人代打)』。"
        "★中身は"
        "**機械的に極めて短く**返す(Chami指定2026-07-18『もっと機械的に』)。原則この定型のみ: "
        "『受領。担当の起床後に返答。』。案件の一言要約を足すなら『受領(＜3〜10字の用件＞)。担当の起床後に返答。』まで。"
        "挨拶・気遣い・説明・敬語での長文は付けない。\n"
        "3. コード実装や横断の重い依頼なら、その場で全部やろうとせず『無人代打が受領。担当セッションが起きたら本対応する』旨を短く返す"
        "(あなたは使い捨てなので長い作業は残さない)。\n"
        "4. 秘密(トークン/アプリPW/af_id)は出力しない。断定できない数字は調べてから。\n"
        "完了したら done とだけ返してください。"
    )


def handle(rec, token):
    env = dict(os.environ)
    env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    prompt = build_prompt(rec)
    try:
        p = subprocess.run(
            [CLAUDE, "--print", "--permission-mode", "bypassPermissions", prompt],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        ok = (p.returncode == 0)
        tail = (p.stdout or "")[-200:]
        print(f"  応答 [{rec.get('channel')}] rc={p.returncode} {tail!r}")
        return ok
    except subprocess.TimeoutExpired:
        print(f"  タイムアウト [{rec.get('channel')}]")
        return False
    except Exception as e:
        print(f"  失敗 [{rec.get('channel')}] {type(e).__name__}")
        return False


def append_processed(line):
    with open(PROCESSED, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def cycle(token):
    if lab_alive():
        print("研究室が生存=代打しない(多重応答防止)")
        return
    if not os.path.exists(INBOX) or os.path.getsize(INBOX) == 0:
        return
    done = processed_ids()
    lines = [l for l in open(INBOX, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    remaining, sent = [], 0
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            remaining.append(line)
            continue
        mid = str(rec.get("msg_id", ""))
        if mid in done:
            continue  # 二重処理しない(main箱からは落とす)
        if rec.get("dept") in SENSITIVE_DEPTS:
            remaining.append(line)  # 機微は内容に触れず残す(本人/研究室が応対・watchdogが無人signal)
            continue
        if sent >= MAX_PER_CYCLE:
            remaining.append(line)  # 上限。次巡回へ
            continue
        # 処理直前に研究室が起きていないか再確認(競合防止)
        if lab_alive():
            remaining.append(line)
            continue
        ok = handle(rec, token)
        append_processed(line)  # 成否に関わらず台帳へ(暴走・無限再試行を防ぐ)
        sent += 1
    # main箱を「残す分」だけに書き戻す(処理済み+機微以外は消える)
    with open(INBOX, "w", encoding="utf-8") as f:
        for line in remaining:
            f.write(line + "\n")
    if sent:
        print(f"{time.strftime('%H:%M:%S')} 無人代打で {sent} 件処理")


def main():
    once = "--once" in sys.argv
    token = read_token()
    if not token:
        print("cli_auth_token.txt が無い=無人代打は不可(claude setup-token を実行し保存)")
        return 2
    print(f"claude無人応答係 起動 ({'--once' if once else f'{POLL_SEC}秒間隔'}・研究室が死んでいる間のみ動く)")
    while True:
        try:
            cycle(token)
        except Exception as e:
            print(f"巡回失敗: {type(e).__name__}")
        if once:
            break
        time.sleep(POLL_SEC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
