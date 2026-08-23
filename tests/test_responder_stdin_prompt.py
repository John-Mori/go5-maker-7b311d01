# -*- coding: utf-8 -*-
"""無人代打(claude_responder)の prompt が argv でなく stdin で渡ることの検査(2026-08-24 イージス研究室)。

★なぜ要るか(実障害):
  Windowsのコマンドライン上限は 32,767字。prompt を argv の末尾に置くと、長い便で CreateProcess が
  **WinError 206** を返し、Pythonは `FileNotFoundError: ファイル名または拡張子が長すぎます` として
  投げる= 「ファイルが無い」に見える起動失敗になる。
  実測= `DISPATCH-system-engineer-1786575652694` が 2026-08-13 08:08〜08:29 に5回連続でこれで落ち、
  その依頼は最後まで完了しなかった(request_log.jsonl に failed×5・completed 無し)。
  session_relay / dept_daemon / persona_render は同日 stdin 化されたが、無人代打だけ argv のまま
  残っていた(2026-08-24に stdin 化)。

★検査の作り: 外へ出る手(subprocess.run=実際のCLI起動)だけ偽物にし、**argvの組み立てと prompt の
  渡し方は本物のまま**通す。プロセスは起動しないので Discord へは何も出ない。

実行= python tests/test_responder_stdin_prompt.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import claude_responder as cr  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WIN_ARGV_LIMIT = 32767
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  << " + detail) if not cond else ""))


class FakeProc(object):
    returncode = 0
    stdout = "done"
    stderr = ""


def capture(rec, runner=None):
    """本物の handle() を通し、CLIへ渡された argv と stdin を捕まえる(起動はしない)。"""
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = list(argv)
        seen["input"] = kw.get("input")
        return FakeProc()

    keep_run, keep_tok = cr.subprocess.run, None
    try:
        cr.subprocess.run = runner or fake_run
        cr.handle(rec, "dummy-token")
    finally:
        cr.subprocess.run = keep_run
        del keep_tok
    return seen


def rec_with(content):
    return {"channel": "イージス研究室", "dept": "aegis-gl", "author": "Chami",
            "content": content, "msg_id": "1533071316071092274"}


print("\n--- ① 普通の長さの便 ---")
s = capture(rec_with("これ直しといて"))
check("promptがargvに載っていない", not any("これ直しといて" in a for a in s["argv"]), repr(s["argv"]))
check("promptがstdinで渡っている", "これ直しといて" in (s["input"] or ""), repr((s["input"] or "")[:80]))
check("argvは起動フラグだけ", s["argv"][1:] == ["--print", "--permission-mode", "bypassPermissions"],
      repr(s["argv"]))

print("\n--- ② 上限(32,767字)を超える便でも argv は太らない ---")
big = "あ" * 40000
s2 = capture(rec_with(big))
argv_len = sum(len(a) + 1 for a in s2["argv"])
check("argv長が上限のはるか下(実測%d字)" % argv_len, argv_len < 1000, str(argv_len))
check("40,000字の本文はstdin側に在る", len(s2["input"] or "") > 40000, str(len(s2["input"] or "")))


# ================================================================ must-fail
def _mf_argv_prompt():
    """壊した側= **動く別の実装**「promptをargv末尾に置く」(2026-08-24以前の実物の形)。
    40,000字の便でWindowsの上限を超える= 本番なら WinError 206 で握り潰される。
    戻り= (壊した側のargv長が上限超えか, 今の実装のargv長が上限超えか)。"""
    holder = {}

    def argv_style_run(argv, **kw):
        holder["now"] = list(argv)                             # 今の実装が渡したargv
        holder["broken"] = list(argv) + [kw.get("input") or ""]  # 旧実装と同じ形(promptを末尾へ)
        return FakeProc()

    capture(rec_with("あ" * 40000), runner=argv_style_run)
    length = lambda a: sum(len(x) + 1 for x in a)  # noqa: E731
    return length(holder["broken"]) > WIN_ARGV_LIMIT, length(holder["now"]) > WIN_ARGV_LIMIT


print("\n--- must-fail(壊した側=旧argv実装へ戻して、上限を超えることを実行で確かめる) ---")
_got = _mf_argv_prompt()
check("must-fail 旧argv実装なら上限超え/今の実装は超えない", _got == (True, False), repr(_got))

ng = [n for n, ok in RESULTS if not ok]
print("\n===== %d件中 %d件PASS =====" % (len(RESULTS), len(RESULTS) - len(ng)))
if ng:
    print("FAIL — %d件: %s" % (len(ng), ng))
    sys.exit(1)
print("ALL PASS")
