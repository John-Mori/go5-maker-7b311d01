#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""職掌ガードが「引用された語」で誤発火しないことの回帰検査(2026-09-13 イージス研究室)。

壊れた実物(0歩目に見たもの):
  改善提案部門 トトリ `DISPATCH-aegis-gl-1789265265890`(2026-09-13T11:07:51)。
  当室の診断返信の中に**引用した**シャビ・アロンソの待機ackへ、待ち解除機構が文字列一致し、
  誤って追撃を撃った。「引用・コードブロック・他msg転記内の語は検知対象から外し、
  新規に書いた行だけ判定してほしい」と、当室の scope_guard へ載せる判断を回付された。
  scope_guard も同じ語一致なので、同じ穴を**先回りで**塞ぐ(C-038は再発を待たない)。

何を見るか:
  ① `_scope_own_words` = 本文から「今そこで新しく書いた行」だけを残す。
  ② `_scope_guard_hint` = 引用の中にしか語が無い便では鳴らない。
     ★ただし**黙って落とさない**= scope_guard.jsonl へ `抑止` 付きで1行残る。
  ③ 抑止が広すぎないこと= 引用の**外**に1語でも在れば従来どおり鳴る。

★C-053= 「壊した側」は動く別の実装へ戻して作る(`--mutate` で 2026-09-13以前=
  引用を見ない版へ差し替え、同じ検査が赤くなることを見る)。
★外へ出る手(監査ファイルへの追記)は temp へ向けるだけで、判定と分岐は本物のまま回す。

使い方:
  python scripts/llm/test_scope_guard_quote.py
  python scripts/llm/test_scope_guard_quote.py --mutate
"""
import argparse
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import session_relay as sr        # noqa: E402

PASS, FAIL = [], []

DEPT = "llm-edu"
# ★本物の表(00_AI-HQ/.../部屋の職掌.json)は都度読みなので、検査では表だけ差し替える。
#   語は実物の out_words から実在する3語を借りる(架空の語で検査すると本物とズレる)。
ROW = {
    "out_words": ["キュー", "配送", "常駐"],
    "回す先": ["プラットフォームSE", "イージス研究室"],
    "out_label": "基盤の話題",
    "in_hint": "ローカルLLMの学習",
    "黙る発信元": ["platform-se", "aegis-gl", "hq"],
}


def ok(cond, what):
    (PASS if cond else FAIL).append(what)
    print(("  PASS  " if cond else "  FAIL  ") + what)


def _mutant_own_words(txt):
    """2026-09-13以前= 引用もコードも転記も見ない(本文まるごとが判定対象)。"""
    return str(txt or "")


def _rec(content, **kw):
    r = {"author": "chami_fusoh", "msg_id": "1548000000000000000", "content": content}
    r.update(kw)
    return r


def _log_lines(p):
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8").read().splitlines() if l.strip()]


def check_own_words():
    print("① _scope_own_words(新しく書いた行だけ残す)")
    f = sr._scope_own_words
    ok("キュー" not in f("> 前の便: キューが詰まっています\nこれ、どう読む?"),
       "行頭 `>` の引用行は落とす ★これが事故の実物")
    ok("キュー" not in f("これ見て\n```\nキューの残り: 3\n```\nどう?"),
       "``` のコードブロックは落とす")
    ok("キュー" not in f("転記する\n--- 本文ここから ---\nキューが詰まった\n--- 本文ここまで ---\n以上"),
       "`--- 本文ここから/ここまで ---` の転記は落とす")
    ok("キュー" in f("キューを増やしたい"), "普通の行は残す(落とし過ぎていない)")
    ok("キュー" in f("> 引用です\nキューの話をしたい"),
       "引用と地の文が混ざっていたら、地の文は残る")
    ok("配送" in f("彼は「配送」と言った"),
       "★「」は落とさない(日本語では強調にも使う= 落とすと本物を取りこぼす)")
    ok("常駐" in f("```\nコード\n```\n常駐の話"),
       "閉じたコードブロックの後ろは判定に戻る")
    for bad in (None, 123, ""):
        try:
            f(bad)
            ok(True, f"fail-open: {bad!r} で例外を出さない")
        except Exception as e:                               # noqa: BLE001
            ok(False, f"fail-open: {bad!r} で例外({type(e).__name__})")


def _run_hint(content, **kw):
    """本物の _scope_guard_hint を回す(表と監査の書き先だけ差し替える)。"""
    return sr._scope_guard_hint(_rec(content, **kw), DEPT)


def check_hint():
    print("② _scope_guard_hint(引用の中だけの語では鳴らさない・ただし黙って落とさない)")
    d = tempfile.mkdtemp(prefix="scope_guard_q_")
    log = os.path.join(d, "scope_guard.jsonl")
    keep_log, keep_tbl = sr.SCOPE_GUARD_LOG, sr._room_scope_table
    sr.SCOPE_GUARD_LOG = log
    sr._room_scope_table = lambda: {DEPT: ROW}
    try:
        h = _run_hint("トトリの便を貼る。\n> 配送のキューが詰まっています\nこれ、うちの話?")
        ok(h == "", "引用の中にしか語が無い便では封筒へ1文字も足さない ★これが事故の実物")
        rows = _log_lines(log)
        ok(len(rows) == 1 and rows[0].get("抑止") == "引用・コード・転記の中だけ",
           "★黙って落とさない= 監査へ `抑止` 付きで1行残る(取りこぼしを後から数えられる)")
        ok(set(rows[0].get("当たった語") or ()) >= {"配送", "キュー"},
           "抑止の行には「何が当たったか」を全部残す")

        h2 = _run_hint("> 配送の話です\nうちでキューを作りたい")
        ok("職掌の外" in h2, "引用の外に1語でも在れば従来どおり鳴る(抑止が広すぎない)")
        rows = _log_lines(log)
        ok(len(rows) == 2 and "抑止" not in rows[1], "普通の発火の行には `抑止` を付けない")
        ok(rows[1].get("当たった語") == ["キュー"],
           "★鳴った時に記録する語は、引用の外で当たった語だけ(配送は入らない)")
        ok("配送" not in h2, "封筒に見せる語も、引用の外で当たった語だけ")

        h3 = _run_hint("うちでキューを作りたい", from_dept="platform-se")
        ok(h3 == "" and len(_log_lines(log)) == 2,
           "黙る発信元は従来どおり鳴らず、抑止の行も積まない(監査を汚さない)")

        h4 = _run_hint("今日の学習の進み具合はどう?")
        ok(h4 == "" and len(_log_lines(log)) == 2, "語が1つも無い便は従来どおり素通り")
    finally:
        sr.SCOPE_GUARD_LOG, sr._room_scope_table = keep_log, keep_tbl


def check_real_table():
    """③ 本物の表で、実際に鳴った便と同じ形が今も鳴るか(取りこぼしを作っていないか)。"""
    print("③ 本物の表で確認(10:17:14 に実際に鳴ったのと同じ形の本文)")
    d = tempfile.mkdtemp(prefix="scope_guard_r_")
    keep_log = sr.SCOPE_GUARD_LOG
    sr.SCOPE_GUARD_LOG = os.path.join(d, "scope_guard.jsonl")
    try:
        tbl = sr._room_scope_table()
        ok(bool(tbl.get(DEPT)), f"本物の表に {DEPT} の行が在る(都度読みが生きている)")
        h = _run_hint("配送タイミングと既読・着手マークの話。常駐とキューの封筒はどう回る?")
        ok("職掌の外" in h, "★10:17:14 の発火と同じ形は今も鳴る(引用除外で殺していない)")
    finally:
        sr.SCOPE_GUARD_LOG = keep_log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true",
                    help="引用を見ない版(2026-09-13以前)へ差し替えて赤くなるか見る")
    a = ap.parse_args()
    if a.mutate:
        print("★--mutate: 引用・コード・転記を見ない実装へ差し替えて回す\n")
        sr._scope_own_words = _mutant_own_words

    t0 = time.time()
    check_own_words()
    check_hint()
    if not a.mutate:
        check_real_table()
    else:
        # ★③は「今も鳴る」側の検査= 変異体でも緑のままになる(抑止が消えるだけ)。
        #   届かない検査を must-fail の材料に数えない。
        print("③ は変異体でも緑のまま(抑止が消えるだけ)なので --mutate では回さない")

    print("\n%d PASS / %d FAIL (%.1f秒)" % (len(PASS), len(FAIL), time.time() - t0))
    for f in FAIL:
        print("  FAIL: " + f)
    if a.mutate:
        if FAIL:
            print("must-fail: OK(変異体は赤くなった)")
            return 0
        print("must-fail: NG(変異体が緑のまま= この検査は何も見ていない)")
        return 1
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
