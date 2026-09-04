#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打ち切り救出の言語掛け金の試験(2026-09-04・イージス研究室)。

引き金= ad研究室ルカ・モドリッチ msg 1545234410331185197
  「manga-shorts 09:40:39 に救出が発火したが着地していない(09:40:41 英文ダンプ
   ゲートで戻った)。打ち切り→救出→着地を1本の鎖として閉じろ」

★この試験が固定する事実:
  (1) 英文ダンプの発話は救出の候補から落ちる= 送信直前のゲートで戻される物を、
      そもそも拾わない。
  (2) 英語の前置き+日本語本文は、前置きだけ剥がして**本文は救出する**
      (丸ごと捨てると、出来ている返信を捨てることになる)。
  (3) 拾える物が1本も無い時は **空を返す**= 呼び元は打ち切り通知へ落ちる。
      ★ここで英文を返してはいけない(ゲートに戻され便ごと消える=沈黙)。
  (4) 日本語の返信の扱いは**変えていない**(.bak の実装と本文が一致する)。

  記録(transcript)は本物の形の jsonl を一時ファイルで組み、`_salvage_timeout_reply`
  を**実行で**通す(ソースの文字列一致で済ませない・共通規律§3)。

  python scripts/llm/test_salvage_ja.py            … 通常(全部緑であるべき)
  python scripts/llm/test_salvage_ja.py --mutate N … わざと壊す(赤くなるべき)
      1: 言語の掛け金を外す(英文でも拾う=修正前の実装)
      2: 拾えない時に空でなく英文を返す(=ゲートで戻り、沈黙になる)
      3: 混在を丸ごと捨てる(=出来ている日本語の返信まで落とす)
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import session_relay as sr                                  # noqa: E402

MUTATE = 0
for i, a in enumerate(sys.argv):
    if a == "--mutate" and i + 1 < len(sys.argv):
        MUTATE = int(sys.argv[i + 1])

PASS = FAIL = 0


def ok(cond, name, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [NG] {name}" + (f"  … {detail}" if detail else ""))


# ── わざと壊す(must-fail)。★C-053= 壊した側も「動く別の実装」にする ────────
if MUTATE == 1:
    # 修正前と同じ= 言語を見ずに何でも拾う。
    sr._salvage_lang_ok = lambda t: (True, str(t or ""), "掛け金なし")
elif MUTATE == 2:
    # 拾えない時に空を返さず、英文をそのまま渡す(=送信直前のゲートで戻る)。
    _orig = sr._salvage_lang_ok
    sr._salvage_lang_ok = lambda t: (True, str(t or ""), "常に可")
elif MUTATE == 3:
    # 混在を救わず丸ごと捨てる(前置きを剥がさない)。
    def _strict(t):
        s = str(t or "")
        if not s.strip():
            return False, s, "空"
        try:
            from lang_gate import detect_english_dump
            if detect_english_dump(s):
                return False, s, "英文ダンプ"
        except Exception:                               # noqa: BLE001
            return True, s, "素通し"
        return True, s, "日本語"
    sr._salvage_lang_ok = _strict


# ── 記録(transcript)の組み立て ───────────────────────────────────
# ★本物の形に合わせる: 1行1JSON、type=user/assistant、message.content はブロック配列。
NOW = time.time()


def _iso(ep):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ep)) + ".000Z"


def _row(kind, text, ep, sidechain=False):
    return {"type": kind, "isSidechain": sidechain, "timestamp": _iso(ep),
            "message": {"role": kind, "content": [{"type": "text", "text": text}]}}


def _human(text, ep):
    return {"type": "user", "isSidechain": False, "timestamp": _iso(ep),
            "message": {"role": "user", "content": text}}


TMP = tempfile.mkdtemp(prefix="salvage_ja_")


def run(assistant_texts, label):
    """記録を書いて `_salvage_timeout_reply` を実行で通す。(本文, 理由) を返す。"""
    sid = f"test-{label}-{int(NOW)}"
    path = os.path.join(TMP, sid + ".jsonl")
    rows = [_row("assistant", "前のターンの返信(拾ってはいけない)", NOW - 600),
            _human("Chamiの入力", NOW - 300)]
    for i, t in enumerate(assistant_texts):
        rows.append(_row("assistant", t, NOW - 100 + i))
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # ★記録の場所の解決は本物のまま回したいが、置き場はテスト側で決める。
    #   外へ出る手(ファイルの探索)だけ差し替え、判定と分岐は本物を通す。
    orig = sr._transcript_path
    sr._transcript_path = lambda s, cwd=None: path
    try:
        return sr._salvage_timeout_reply(sid, NOW - 290, cwd=None)
    finally:
        sr._transcript_path = orig


# ── 検体 ─────────────────────────────────────────────────────────
JA = "[ヴィルシーナ]\n受け取った。滞留の件は今日中に潰す。実物は次便で出す。"
EN = ("Let me check the daemon logs first. I will read the relay source and "
      "search for the timeout branch, then run the test suite to confirm the "
      "behaviour before reporting back to the room with the results.")
MIX = (EN + "\n\n[ヴィルシーナ]\n調べた。打ち切りは600秒のhard-killで、"
            "常駐の側に落ち度は無い。")

print(f"=== 打ち切り救出 日本語掛け金 試験 (mutate={MUTATE}) ===")

# ── 1) 日本語の返信は今までどおり拾う ────────────────────────────
print("\n[1] 日本語の返信(従来の振る舞いを壊していないか)")
body, why = run([JA], "ja")
ok(JA.split("\n")[1] in body, "★日本語の返信はそのまま救出される", repr(body[:40]))
ok("英文" not in why, "余計な理由が付かない", why)

# ── 2) 英文ダンプは拾わない=空を返す ────────────────────────────
print("\n[2] 英文ダンプだけの時(モドリッチの実物と同じ場面)")
body, why = run([EN], "en")
ok(body == "", "★英文ダンプは救出しない(送信直前のゲートで戻る物を拾わない)", repr(body[:60]))
ok(body == "" and why, "★空振りの理由が残る=呼び元は打ち切り通知へ落ちる", why)

# ── 3) 英語の前置き+日本語本文は本文を救う ──────────────────────
print("\n[3] 混在(英語の作業メモ→日本語の返信)")
body, why = run([MIX], "mix")
ok("常駐の側に落ち度は無い" in body, "★日本語の本文は捨てない", repr(body[:60]))
ok("daemon logs" not in body,
   "★英語の前置きは剥がして届ける(丸ごと捨ても丸ごと送りもしない)", repr(body[:80]))
try:
    from lang_gate import detect_english_dump
    ok(detect_english_dump(body) is None,
       "★救出した本文は英文ダンプゲートを通る(鎖が閉じる)",
       json.dumps(detect_english_dump(body) or {}, ensure_ascii=False))
except Exception as e:                                  # noqa: BLE001
    ok(False, "lang_gate を読めない", str(e))

# ── 4) 英文メモ+日本語の返信が別の発話で来た時 ──────────────────
print("\n[4] 発話が分かれている時(英文メモ1本+日本語の返信1本)")
body, why = run([EN, JA], "en_ja")
ok(body.startswith("[ヴィルシーナ]"), "★名乗り付きの日本語だけを拾う", repr(body[:30]))
ok("English" not in body and "daemon logs" not in body, "英文メモは混ざらない", repr(body[:80]))
ok("英文1本を捨てた" in why, "落とした数が理由に残る", why)

# ── 5) fail-open(判定できない時は喋る側へ倒す) ──────────────────
print("\n[5] fail-open")
g, b, w = sr._salvage_lang_ok(JA)
ok(g is True and b, "日本語は可", w)
g, b, w = sr._salvage_lang_ok("")
ok(g is False, "空は不可(拾う物が無い)", w)
_bad = os.path.join(TMP, "nonexistent.jsonl")
sr._transcript_path, _o = (lambda s, cwd=None: _bad), sr._transcript_path
try:
    body, why = sr._salvage_timeout_reply("x", NOW - 290, cwd=None)
    ok(body == "" and "記録ファイルが無い" in why, "記録が無くても例外を出さない", why)
finally:
    sr._transcript_path = _o

# ── 6) 退行(.bak と日本語の扱いが一致する) ─────────────────────
print("\n[6] 退行(変更前の実装と日本語の扱いが一致)")
BAK = os.path.join(HERE, "session_relay.py.bak_20260904_salvage_ja")
old = None
try:
    # ★拡張子が .py でないので loader を明示する(spec_from_file_location だけだと
    #   loader=None のまま返り、静かに読み込めない=退行の突き合わせが空振りする)。
    loader = importlib.machinery.SourceFileLoader("session_relay_old", BAK)
    spec = importlib.util.spec_from_loader("session_relay_old", loader)
    old = importlib.util.module_from_spec(spec)
    loader.exec_module(old)
except Exception as e:                                  # noqa: BLE001
    print(f"  (.bak を読めない: {e})")

if old is not None:
    sid = "regress"
    path = os.path.join(TMP, sid + ".jsonl")
    rows = [_human("Chamiの入力", NOW - 300),
            _row("assistant", JA, NOW - 100)]
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    o1, o2 = sr._transcript_path, old._transcript_path
    sr._transcript_path = lambda s, cwd=None: path
    old._transcript_path = lambda s, cwd=None: path
    try:
        a, _ = sr._salvage_timeout_reply(sid, NOW - 290, cwd=None)
        b, _ = old._salvage_timeout_reply(sid, NOW - 290, cwd=None)
        ok(a == b and a, "★日本語の便では変更前と本文が完全一致", repr((a[:20], b[:20])))
        # 英文では**違う**のが今回の変更点(一致したら掛け金が効いていない)。
        path2 = os.path.join(TMP, "regress_en.jsonl")
        with open(path2, "w", encoding="utf-8") as f:
            f.write(json.dumps(_human("Chamiの入力", NOW - 300), ensure_ascii=False) + "\n")
            f.write(json.dumps(_row("assistant", EN, NOW - 100), ensure_ascii=False) + "\n")
        sr._transcript_path = lambda s, cwd=None: path2
        old._transcript_path = lambda s, cwd=None: path2
        a2, _ = sr._salvage_timeout_reply("regress_en", NOW - 290, cwd=None)
        b2, _ = old._salvage_timeout_reply("regress_en", NOW - 290, cwd=None)
        ok(a2 == "" and b2 != "",
           "★英文の便では変更前と振る舞いが変わる(これが今回の手当て)",
           repr((a2[:20], b2[:20])))
    finally:
        sr._transcript_path, old._transcript_path = o1, o2
else:
    ok(False, "★.bak が読めない(退行を突き合わせられない)", BAK)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n=== {PASS}/{PASS + FAIL} PASS ===")
sys.exit(1 if FAIL else 0)
