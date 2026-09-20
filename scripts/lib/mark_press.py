#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""進捗印(既読/着手/即答/送信)を react.py へ押させる口の**正本**(2026-09-06 イージス研究室)。

★なぜ1か所に集めるか(ORG-11= 表を2か所に持つと必ず片方が腐る):
  同じ subprocess 呼び出しが `scripts/llm/codex_responder.py:mark()` と
  `scripts/codex/codex_run.py:mark_sent()` に**写しで2本**あった。両方とも
  `capture_output=True` + `except Exception: pass` で、react.py の returncode も
  stderr も捨てていた。押せたのか押せなかったのかが**どこにも残らない**。

★実測(2026-09-06・イージス研究室):
  - 送信印(uptsukiyomi)が付かない便があり、原因が2日わからなかった。わからなかったのは
    ログが無いからで、機構の複雑さのせいではない。**この無言が本体の不具合だ。**
  - 印ごとに費用が違う。react.py の resolve_emoji は
      着手(🐍)・既読(‼️) … id を持たない unicode = **即return・HTTP往復ゼロ**
      送信(uptsukiyomi) … id を持つ custom = `/channels` → `/guilds/{id}/emojis` の**2往復**
    だから通信が揺れた時、**送信印だけが単独で落ちる**。「既読と着手は付くのに送信だけ
    付かない」という報告された症状の形と一致する。
    ★2026-09-20 更新= Codexの着手が 🐍 → `Chakusyu_Boss`(id持ちcustom)へ差し替わった
      (Chami指示・react.py CODEX_OVERRIDE)。よって**Codex便の着手も送信と同じ2往復**になった
      =遅い側の費用は倍。ただし resolve_emoji は解決に失敗してもID直撃へ倒れる(unicodeへ劣化しない)
      ので、落ちるとしても「押せない」ではなく「遅い」。予算は 6秒×1試行×2往復=最悪12秒 < TIMEOUT 30秒。
  - 呼び側の timeout=30 に対し、react.py の api() は 20秒×3試行。解決で2往復すると
    最悪120秒超= 呼び側が先に切る。react.py 側の解決予算を短く切って直したが、
    それでも**押せなかった事実は残さないと次も同じ2日を使う**。

★作法:
  - fail-open。印は本筋を絶対に止めない(押せなくても例外を上へ投げない)。
  - べき等。react.py の PUT /@me は同じ印の二度押しが no-op。
  - 記録は C-054 に従い、検査プロセスからは本番台帳へ書かない(test_sink.sink_for)。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
REACT = os.path.join(ROOT, "scripts", "discord", "react.py")
AUDIT = os.path.join(LOCAL, "llm", "mark_audit.jsonl")

# 呼び側が subprocess を切るまでの秒数。react.py の解決予算(RESOLVE_TIMEOUT×RESOLVE_TRIES×2往復)
# より必ず大きく取る。ここを縮めると「解決には成功しているのに押す前に殺される」が戻る。
TIMEOUT = 30

sys.path.insert(0, HERE)
try:
    from test_sink import sink_for                    # noqa: E402
except Exception:                                     # 判定が読めない時は本番へ書く側へ倒す
    def sink_for(p, suffix="_test"):
        return p


def _audit(row):
    """押した結果を1行残す。★記録の失敗で印の経路を壊さない。"""
    try:
        path = sink_for(AUDIT)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def press(channel, msg_id, emoji, codex=False, caller="", timeout=TIMEOUT):
    """印を1つ押す。押せたかどうかを dict で返す(呼び側は無視してもよい=fail-open)。

    戻り値: {"ok": bool, "returncode": int|None, "error": str, "secs": float}
      ok=True は react.py が exit 0 を返した時だけ。★「呼んだ」と「押せた」を混ぜない(§4.55)。
    """
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "caller": str(caller or ""),
           "channel": str(channel or ""), "msg": str(msg_id or ""),
           "emoji": str(emoji or ""), "codex": bool(codex)}
    if not (channel and msg_id):
        row.update({"ok": False, "returncode": None, "error": "no_target", "secs": 0.0})
        _audit(row)
        return {"ok": False, "returncode": None, "error": "no_target", "secs": 0.0}
    argv = [sys.executable, REACT, "--channel", str(channel), "--msg", str(msg_id),
            "--emoji", str(emoji)]
    if codex:
        argv.append("--codex")
    t0 = time.time()
    rc, err = None, ""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
        rc = p.returncode
        if rc != 0:
            # react.py は失敗理由を stdout へ print する(HTTP xxx / リアクション失敗…)ので両方拾う。
            err = ((p.stdout or b"").decode("utf-8", "replace").strip() + " " +
                   (p.stderr or b"").decode("utf-8", "replace").strip()).strip()
    except subprocess.TimeoutExpired:
        err = f"timeout_{timeout}s"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    secs = round(time.time() - t0, 2)
    out = {"ok": rc == 0, "returncode": rc, "error": err[:400], "secs": secs}
    row.update(out)
    _audit(row)
    return out
