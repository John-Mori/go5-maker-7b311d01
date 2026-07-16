#!/usr/bin/env python3
"""Discord受信ポーラー (Phase DB・AI組織のIN口)。

各部門チャンネルの発言をポーリングで拾い、local/discord_inbox.jsonl へ追記する。
常駐起動: scripts/discord/start_discord_inbox.bat (または python inbox_poller.py)
動作テスト: python scripts/discord/inbox_poller.py --once

前提(local/・全てgitignore済):
  discord_bot_token.txt   … BotトークンURL1行(手順=local/discord_bot_setup.md)
  discord_channels.json   … [{"name":"総合-受付","id":"<チャンネルID>","dept":"router"},...]
仕様:
  - 初回はチャンネルの最新メッセージIDだけ記録し、過去ログは取り込まない
  - Bot/Webhook発言(author.bot / webhook_id)は無視(自分の返信で無限ループしないため)
  - トークン等の秘密は出力しない
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")  # テスト用にlocal/差し替え可
TOKEN_FILE = os.path.join(LOCAL, "discord_bot_token.txt")
CHANNELS_FILE = os.path.join(LOCAL, "discord_channels.json")
STATE_FILE = os.path.join(LOCAL, "discord_inbox_state.json")
INBOX_FILE = os.path.join(LOCAL, "discord_inbox.jsonl")
POLLER_ACTIVE = os.path.join(LOCAL, "llm", "poller_active.txt")  # 死活の脈(absence_watchdogが鮮度を監視)
POLL_SEC = 15
API = "https://discord.com/api/v10"

# --- 部門常駐セッション分離(2026-07-14) ---
# 部門窓(別Claude Codeセッション)が heartbeat.py --name <dept> で
# local/llm/claude_active_<dept>.txt を打っている間だけ、その部門宛ての新着を
# local/inbox/<dept>.jsonl へ配達する(main箱に入れない=窓ごとの役割分離)。
# 窓が死ねば脈が止まり(TTL10分)、以後の新着は従来通りmain箱へ。
# 取り残し対策: 脈が古い部門箱に未処理が残っていれば巡回ごとにmain箱へ書き戻す(自己修復)。
RESIDENT_FRESH_SEC = 90


def dept_active(dept):
    if not dept or dept in ("router", "llm-growth", "gemini"):  # 総合受付/qwenの部屋/Gemini専用部屋は対象外
        return False
    p = os.path.join(LOCAL, "llm", f"claude_active_{dept}.txt")
    try:
        return (time.time() - os.path.getmtime(p)) < RESIDENT_FRESH_SEC
    except OSError:
        return False


def dept_box(dept):
    return os.path.join(LOCAL, "inbox", f"{dept}.jsonl")


def touch_poller_active():
    """巡回ごとに死活の脈を打つ。absence_watchdogがこの鮮度で『ポーラー停止』を検知する。
    ポーラーが死ぬと新着が一切配達されず=チャイム全体が沈黙するため、単独の死活監視が要る。"""
    try:
        os.makedirs(os.path.dirname(POLLER_ACTIVE), exist_ok=True)
        with open(POLLER_ACTIVE, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())) + "\n")
    except OSError:
        pass


def sweep_stale_dept_boxes():
    d = os.path.join(LOCAL, "inbox")
    if not os.path.isdir(d):
        return
    for fn in os.listdir(d):
        if not fn.endswith(".jsonl"):
            continue
        dept = fn[:-len(".jsonl")]
        if dept_active(dept):
            continue
        p = os.path.join(d, fn)
        try:
            if os.path.getsize(p) == 0:
                continue
            with open(p, "r", encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            if lines:
                with open(INBOX_FILE, "a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            open(p, "w").close()
            print(f"{time.strftime('%H:%M:%S')} 常駐不在の部門箱を回収 [{dept}] {len(lines)}件→main")
        except OSError:
            pass


def read_token():
    if not os.path.exists(TOKEN_FILE):
        print("Botトークン未設定: local/discord_bot_token.txt がありません(手順=local/discord_bot_setup.md)")
        sys.exit(2)
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def read_channels():
    if not os.path.exists(CHANNELS_FILE):
        print("チャンネル表未設定: local/discord_channels.json がありません(手順=local/discord_bot_setup.md)")
        sys.exit(2)
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        chans = json.load(f)
    return [c for c in chans if str(c.get("id", "")).strip().isdigit()]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def api_get(path, token):
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": "Bot " + token, "User-Agent": "go5-org-inbox (personal, v1)"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 2))
                except Exception:
                    wait = 2.0
                time.sleep(min(wait, 30) + 0.5)
                continue
            raise
    return None


# --- 既読リアクション(2026-07-16 Chami依頼) ---
# 配達した瞬間にカスタム絵文字「既読」を押す=「届いた」をトークンゼロで可視化。
# 「無視されてる/考え中/未達」の区別と確認往復の削減が目的。着手印はClaude側が
# scripts/discord/react.py で押す(2段階)。未登録の間はUnicode✅で代用し、
# 登録され次第(10分毎に再解決)自動でカスタム絵文字に切り替わる。失敗しても配達は止めない。
import urllib.parse

REACT_READ_NAME = "既読"          # サーバー絵文字名(Chami登録)
REACT_READ_FALLBACK = "✅"    # ✅(未登録時の代用)
_react = {"guild": "", "emoji": "", "at": 0.0}


def api_put_(path, token):
    req = urllib.request.Request(
        API + path, method="PUT", data=b"",
        headers={"Authorization": "Bot " + token, "User-Agent": "go5-org-inbox (personal, v1)"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return 200 <= r.status < 300
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 1))
                except Exception:
                    wait = 1.0
                time.sleep(min(wait, 10) + 0.3)
                continue
            return False  # 権限なし(403)等は諦める(配達最優先)
        except Exception:
            return False
    return False


def resolve_read_emoji_(token, any_cid):
    """「既読」カスタム絵文字を name:id 形式で解決(10分キャッシュ)。無ければ✅。"""
    now = time.time()
    if _react["emoji"] and (":" in _react["emoji"] or now - _react["at"] < 600):
        return _react["emoji"]  # カスタム解決済みは恒久・✅代用中は10分毎に再解決
    _react["at"] = now
    try:
        if not _react["guild"]:
            ch = api_get(f"/channels/{any_cid}", token)
            _react["guild"] = str((ch or {}).get("guild_id", "") or "")
        if _react["guild"]:
            for e in (api_get(f"/guilds/{_react['guild']}/emojis", token) or []):
                if e.get("name") == REACT_READ_NAME and e.get("id"):
                    _react["emoji"] = f"{REACT_READ_NAME}:{e['id']}"
                    print(f"{time.strftime('%H:%M:%S')} 既読絵文字を解決: :{REACT_READ_NAME}:")
                    return _react["emoji"]
    except Exception:
        pass
    _react["emoji"] = REACT_READ_FALLBACK
    return _react["emoji"]


def react_read_(cid, mid, token):
    try:
        emoji = urllib.parse.quote(resolve_read_emoji_(token, cid))
        api_put_(f"/channels/{cid}/messages/{mid}/reactions/{emoji}/@me", token)
    except Exception:
        pass  # リアクション失敗で配達を止めない


def poll_channel(ch, token, state, out):
    cid = str(ch["id"])
    last = state.get(cid)
    if not last:
        msgs = api_get(f"/channels/{cid}/messages?limit=1", token)
        state[cid] = msgs[0]["id"] if msgs else "0"
        return 0
    msgs = api_get(f"/channels/{cid}/messages?limit=50&after={last}", token)
    if not msgs:
        return 0
    msgs.sort(key=lambda m: int(m["id"]))  # 古い順に処理
    new = 0
    for m in msgs:
        state[cid] = m["id"]
        if m.get("webhook_id") or m.get("author", {}).get("bot"):
            continue
        rec = {
            "ts": m.get("timestamp", ""),
            "channel": ch.get("name", cid),
            "dept": ch.get("dept", "router"),
            "author": m.get("author", {}).get("username", "?"),
            "content": m.get("content", ""),
            "attachments": [a.get("url") for a in m.get("attachments", [])],
            "msg_id": m["id"],
        }
        out.append(rec)
        react_read_(cid, m["id"], token)  # 既読印=「届いた」を即可視化(トークンゼロ・失敗しても配達継続)
        new += 1
    return new


def main():
    once = "--once" in sys.argv
    token = read_token()
    channels = read_channels()
    if not channels:
        print("有効なチャンネルIDが0件です。local/discord_channels.json のidを埋めてください。")
        sys.exit(2)
    print(f"受信ポーラー開始: {len(channels)}チャンネルを{POLL_SEC}秒間隔で監視" + (" (--once)" if once else ""))
    while True:
        touch_poller_active()  # 死活の脈(watchdogが監視・ポーラー停止=チャイム沈黙の単一障害点)
        state = load_state()
        sweep_stale_dept_boxes()  # 常駐が消えた部門箱の取り残しをmainへ回収
        out = []
        for ch in channels:
            try:
                poll_channel(ch, token, state, out)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    print("トークンが無効です(401)。local/discord_bot_token.txt を確認してください。")
                    sys.exit(3)
                print(f"チャンネル取得失敗 [{ch.get('name')}] HTTP {e.code} (権限/IDを確認)")
            except Exception as e:
                print(f"チャンネル取得失敗 [{ch.get('name')}] {type(e).__name__}")
        if out:
            # llm-growth(ローカルqwenの部屋)は専用受付箱へ=ローカルLLMが常時応対(Claude稼働中でも)。
            # ただし名前呼び(アメス/アロンソ等)を含む発言はClaude側へ配達=呼べば本人が出てくる(Chami指定2026-07-13)
            CALL_WORDS = ("アメス", "アロンソ", "監督", "司令塔", "Claude", "claude")
            QWEN_WORDS = ("ローカル", "qwen", "Qwen")
            # トークン節約(Chami承認2026-07-14・案A): 簡単な質問はローカルqwenが一次回答し、
            #   コード変更・数字・投稿など誤答が怖い依頼はClaudeへ回す。誤爆を避けるため保守的に判定。
            WORK_WORDS = ("改修", "修正", "直し", "直す", "変更", "追加", "実装", "作っ", "作成", "してくれ",
                          "対応", "バグ", "エラー", "ボタン", "表示", "幅", "位置", "デプロイ", "反映",
                          "変えて", "移動", "削除", "登録", "設定して", "頼む", "お願い", "やって", "解析")
            Q_MARKS = ("?", "？", "教え", "わかる", "分かる", "どれくらい", "どのくらい", "何", "なに",
                       "どう", "いくら", "かな", "だっけ", "ですか", "だろうか", "ある?", "ある？")
            SENSITIVE_DEPTS = ("dream-care", "past-room", "hr-room", "hr-context", "health-log")  # 機微/司令塔直轄=ローカル一次回答しない
            def _is_simple_q(r):
                c = r.get("content") or ""
                if r.get("attachments"):
                    return False                                  # 画像添付=作業依頼が多い
                if r.get("dept") in SENSITIVE_DEPTS:
                    return False
                if any(w in c for w in CALL_WORDS):
                    return False                                  # 名前呼び=本人(Claude)へ
                if any(w in c for w in WORK_WORDS):
                    return False                                  # 依頼語=Claudeへ
                if len(c) > 200:
                    return False                                  # 長文=仕様/依頼の可能性
                return any(m in c for m in Q_MARKS)               # 質問らしさがある短文だけローカルへ
            # ★他部屋の「ローカル一次受付」は一時停止(Chami指定2026-07-14「まだ早い」)。
            #   デブライネ/咲季/コーチ(先生)等の名前呼びをローカルが横取りしてしまう問題のため。
            #   再開時は、全人格名+コーチ/先生をCALL_WORDSに入れてから _is_simple_q(r) へ戻すこと。
            LOCAL_FIRST_ENABLED = False
            def _is_llm(r):
                c = r.get("content") or ""
                if r.get("dept") == "llm-growth":
                    return not any(w in c for w in CALL_WORDS)  # 彼女の部屋: 名前呼び以外は彼女
                if r.get("dept") == "imagegen":
                    return any(w in c for w in QWEN_WORDS)      # 画像生成室: 逆に呼ばれた時だけ彼女
                return LOCAL_FIRST_ENABLED and _is_simple_q(r)  # 他部屋の一次受付は停止中(上記)
            # Gemini専用部屋(dept=="gemini")は独立レーン→discord_inbox_gemini.jsonlのみ(qwenのllm-growthと同じ扱い・main/llm/dept箱には入れない)
            gemini_out = [r for r in out if r.get("dept") == "gemini"]
            base = [r for r in out if r.get("dept") != "gemini"]
            llm_out = [r for r in base if _is_llm(r)]
            rest = [r for r in base if not _is_llm(r)]
            # 部門常駐セッションが生きていればその部門箱へ、いなければmain箱へ
            dept_out = [r for r in rest if dept_active(r.get("dept", ""))]
            main_out = [r for r in rest if not dept_active(r.get("dept", ""))]
            if main_out:
                with open(INBOX_FILE, "a", encoding="utf-8") as f:
                    for rec in main_out:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            for rec in dept_out:
                bp = dept_box(rec["dept"])
                os.makedirs(os.path.dirname(bp), exist_ok=True)
                with open(bp, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if llm_out:
                with open(os.path.join(LOCAL, "discord_inbox_llm.jsonl"), "a", encoding="utf-8") as f:
                    for rec in llm_out:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if gemini_out:
                with open(os.path.join(LOCAL, "discord_inbox_gemini.jsonl"), "a", encoding="utf-8") as f:
                    for rec in gemini_out:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"{time.strftime('%H:%M:%S')} 新着{len(out)}件 → 受付箱(main={len(main_out)}/dept={len(dept_out)}/llm={len(llm_out)}/gemini={len(gemini_out)})")
        save_state(state)
        if once:
            print(f"1回分の巡回完了(新着{len(out)}件)")
            break
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
