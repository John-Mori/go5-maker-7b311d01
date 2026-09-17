#!/usr/bin/env python3
"""must-fail試験: Codexの内部引き継ぎメモを無人代打がDiscordへ追送しない。

実害(2026-09-17 platform-se): Codexの完了返信 msg 1549988243628494870 の17秒後に、
研究室(無人代打)が「受領。本対応は担当セッションへ引き継ぎます。」
(msg 1549988316189949954)を追送した。

原因は、codex_responder がworktree引き継ぎメモを main箱へ通常レコードとして書き、
claude_responder が利用者の新着と誤認したこと。内部メモは type=session-note とし、
研究室セッションには残すがDiscord返信の対象から外す。
"""
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# tokenless_router.py は運用localにだけ在る依存。ここで試す分岐は固定文判定ではないため、
# clean worktreeでも import できる最小の偽物を置く(外へ出る手と同じく試験内だけ)。
if "tokenless_router" not in sys.modules:
    tokenless = types.ModuleType("tokenless_router")
    tokenless.scripted_reply = lambda content, who: None
    sys.modules["tokenless_router"] = tokenless
import codex_responder as codex  # noqa: E402
import claude_responder as fallback  # noqa: E402


def make_codex_note():
    """成功+worktree保持の本経路を通し、main箱へ書く内部メモを捕まえる。"""
    writes = []
    codex.append_line = lambda path, line: writes.append((path, line))
    codex.mark = lambda *a, **k: None
    codex.codex_answer = lambda *a, **k: (True, r"D:\worktrees\sample", "")
    codex._start_lease_extender = lambda *a, **k: None
    codex.usage_limit_hold = lambda: (False, None)
    codex.clear_usage_limit = lambda why="": False
    codex.log = lambda rec: None

    rec = {
        "content": "@ボス この不具合を修正して、回帰検査まで通してくれ",
        "msg_id": "1549984851648716904",
        "channel_id": "1528653749747191882",
        "channel": "🌏プラットフォームse-一ノ瀬怜",
        "codex_origin_dept": "platform-se",
        "dept": "codex",
    }
    mode = codex.handle(rec, json.dumps(rec, ensure_ascii=False), lease_id="test")
    notes = [json.loads(line) for path, line in writes if path == codex.FOR_CLAUDE]
    return mode, notes


def fallback_handled(record):
    """無人代打の本物のcycle分岐へ1行を通し、Discord送信相当のhandle呼出を数える。"""
    handled = []
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.close()
    fallback.INBOX = tmp.name
    fallback.lab_alive = lambda: False
    fallback.cycle_queue = lambda token=None: None
    fallback.processed_ids = lambda: set()
    fallback.append_processed = lambda line: None
    fallback.room_has_own_responder = lambda dept: False
    fallback.handle = lambda rec, token=None: (handled.append(rec) or True)
    try:
        fallback.cycle()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return handled


def main():
    fails = []
    mode, notes = make_codex_note()
    if mode != "answered":
        fails.append(f"Codex成功経路を通っていない: mode={mode!r}")
    if len(notes) != 1:
        fails.append(f"worktree引き継ぎメモが1件でない: {notes!r}")
        note = notes[0] if notes else {}
    else:
        note = notes[0]
    if note.get("type") != "session-note":
        fails.append(f"内部メモに type=session-note が無い: {note!r}")
    if "worktree" not in note:
        fails.append(f"引き継ぎにworktreeが残っていない: {note!r}")

    leaked = fallback_handled(note)
    if leaked:
        fails.append("session-noteを無人代打が利用者発言と誤認し、Discord追送経路へ入れた")

    # 対照: typeの無い通常レコードではhandleが呼ばれる。
    control = dict(note)
    control.pop("type", None)
    control["msg_id"] = "control-user-message"
    if not fallback_handled(control):
        fails.append("対照の通常レコードまで抑止した=試験が偽緑")

    print(f"mode={mode} / note_type={note.get('type')!r} / leaked={len(leaked)}")
    if fails:
        for failure in fails:
            print("NG: " + failure)
        return 1
    print("OK: Codex内部メモは研究室へ残るが、無人代打のDiscord追送対象にならない")
    return 0


if __name__ == "__main__":
    sys.exit(main())
