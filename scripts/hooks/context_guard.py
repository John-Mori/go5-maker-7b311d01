#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""context_guard — relayの管理外のセッションにも**文脈の上限を効かせる**(2026-08-22 イージス研究室)。

発注= 研究室HQ msg 1540618940533841982。Chamiが週間制限98%まで行って3日間このシステムに
触れなくなった。HQが実測した内訳= 消費の**71.2%が cache読み(文脈の読み直し)**で、
その中で1セッションだけ桁が違った。

  0351851c(研究室メイン・手動)  便7,526  文脈の中央値 486,209  最大 933,992
  relay管理下の部門              いずれも 10〜12万台

穴は2つ重なっている:
  ① 手で開いた窓は session_relay の管理下に無い= 120,000の圧縮線も185,000の交代線も
     **一度もかからない**(relayは自分が起動したセッションしか畳めない)。
  ② その代わりに当てにしていた「Claude CLI が約167,000で自動圧縮する」は**200K窓の実測値**。
     いま研究室メインが使っている claude-sonnet-5 は窓が1M= 同じ自動圧縮が約93万まで
     黙って上がる(実測の最大 933,992 がその直前だ)。
     ★**モデルの窓から導いた線は、窓が変わった日に無言で無効化される。**

→ このhookは **絶対トークン数**で線を引き、越えたセッションに毎ターン警告を出す。
  窓の大きさにもモデルにも依存しない。relayが面倒を見ているセッションでは黙る
  (あちらは便を返した後に自分で `/compact` を撃つ=二重に鳴らすと無視される警報になる)。

★hookに出来ること/出来ないこと(正直に書く):
  hookから `/compact` を**撃つことはできない**(スラッシュコマンドはCLI側の機能で、
  hookの戻り値には無い)。出来るのは「越えたことを、越えている間ずっと、
  セッションとChamiの両方に見せ続ける」ことだ。だから
    - `systemMessage`      … 端末のChamiに見える
    - `additionalContext`  … そのセッション自身が読む(=次のターンで畳む判断ができる)
  の両方へ出す。**そして鳴った事実を必ず台帳へ残す**(旧 progress_mark はログを一切
  残さず「印が付いたか」を誰も測れなかった。同じ轍を踏まない)。

登録= .claude/settings.json の PostToolUse。fail-open= 何が起きても exit 0(セッションを止めない)。
測り直し= python scripts/llm/context_watch.py --hours 12
"""
import json
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
RELAY = os.path.join(ROOT, "scripts", "llm", "session_relay.py")
STATE = os.path.join(LOCAL, "llm", "context_guard_state.json")
LEDGER = os.path.join(LOCAL, "llm", "context_guard.jsonl")
ROOMS = os.path.join(LOCAL, "llm", "room_sessions.json")

WARN_EVERY_SEC = 300            # 同じセッションへ鳴らす間隔の下限(毎ツール呼び出しでは出さない)
TAIL_BYTES = 400_000            # transcriptの末尾だけ読む(24MBの本体を毎回読まない)

RE_IN = re.compile(r'"input_tokens"\s*:\s*(\d+)')
RE_CC = re.compile(r'"cache_creation_input_tokens"\s*:\s*(\d+)')
RE_CR = re.compile(r'"cache_read_input_tokens"\s*:\s*(\d+)')


def lines():
    """圧縮線・交代線は session_relay を正本として読む(数字を2か所に置かない)。

    ★import はしない= hookは全ツール呼び出しで鳴るので、巨大モジュールの読み込みを毎回
      させない。ソースから定数を1行拾うだけにする(値の正本は向こうのまま)。
    """
    try:
        with open(RELAY, encoding="utf-8", errors="replace") as f:
            src = f.read(200_000)
        c = re.search(r"^COMPACT_AT_TOKENS\s*=\s*(\d+)", src, re.M)
        r = re.search(r"^ROTATE_AT_TOKENS\s*=\s*(\d+)", src, re.M)
        if c and r:
            return int(c.group(1)), int(r.group(1))
    except Exception:
        pass
    return 120000, 185000


def relay_managed(sid):
    """relayが世代管理している現行セッションか(=あちらが畳むので黙る)。"""
    try:
        with open(ROOMS, encoding="utf-8") as f:
            for _room, v in (json.load(f) or {}).items():
                if str((v or {}).get("active_session_id") or "") == str(sid):
                    return True
    except Exception:
        pass
    return False


def context_now(path):
    """いまの文脈の大きさ= 直近の便で実際にモデルへ送った総トークン。

    ★input + cache読み + cache作成。Claude Code 自身が usage に記録した実測値であって
      推定ではない。★末尾から探す(最後の1件が「今」)。
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
                f.readline()            # 途中で切れた行は捨てる
            tail = f.read().decode("utf-8", "replace")
    except Exception:
        return 0
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line:
            continue
        mi = RE_IN.search(line)
        if not mi:
            continue
        n = int(mi.group(1))
        mcr, mcc = RE_CR.search(line), RE_CC.search(line)
        n += int(mcr.group(1)) if mcr else 0
        n += int(mcc.group(1)) if mcc else 0
        if n > 0:
            return n
    return 0


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:
        pass


def _record(sid, ctx, level, compact_at, rotate_at):
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": sid, "ctx": ctx,
                "level": level, "compact_at": compact_at, "rotate_at": rotate_at,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def decide(payload, now=None):
    """★本体(純粋関数に近い形)。戻り値= (出力する文字列 or None, ctx, level)。

    検査から入力を差し替えて**この関数ごと**通せるようにしてある(外へ出るのは
    stdout への1回の print だけ)。
    """
    now = now or time.time()
    sid = str(payload.get("session_id") or "")
    tp = payload.get("transcript_path") or ""
    if not sid or not tp:
        return None, 0, ""
    if relay_managed(sid):
        return None, 0, ""              # relayが畳む側=黙る(二重の警報は無視される)
    ctx = context_now(tp)
    compact_at, rotate_at = lines()
    if ctx < compact_at:
        return None, ctx, ""
    level = "rotate" if ctx >= rotate_at else "compact"
    st = _state()
    last = float((st.get(sid) or {}).get("at", 0) or 0)
    if now - last < WARN_EVERY_SEC:
        return None, ctx, level         # 鳴らしっぱなしにしない(間引き)
    st[sid] = {"at": now, "ctx": ctx, "level": level}
    _save(st)
    _record(sid, ctx, level, compact_at, rotate_at)
    if level == "rotate":
        msg = ("★この窓の文脈が %s トークン(交代の線 %s 超)。**この窓は session_relay の"
               "管理外なので、誰も畳んでくれない**。いま抱えている便を返したら、"
               "引き継ぎを書いて `/compact` を撃つか、新しい窓へ交代しろ。"
               "文脈の読み直しは週間制限の71%%を占めている(HQ実測 2026-08-22)。"
               % (f"{ctx:,}", f"{rotate_at:,}"))
    else:
        msg = ("★この窓の文脈が %s トークン(圧縮の線 %s 超)。**この窓は session_relay の"
               "管理外**=自動では畳まれない。区切りのいい所で `/compact` を撃て。"
               % (f"{ctx:,}", f"{compact_at:,}"))
    return msg, ctx, level


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    msg, _ctx, _lv = decide(payload)
    if not msg:
        return
    print(json.dumps({
        "systemMessage": msg,           # 端末のChamiに見える
        "hookSpecificOutput": {         # セッション自身が読む
            "hookEventName": payload.get("hook_event_name") or "PostToolUse",
            "additionalContext": msg,
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)                         # 何があってもセッションを止めない
