#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_synopsis.py — あらすじ取得(candidates_json.py)のmust-fail検査。
外へ出る手(HTTP=fetch)だけ偽物にし、判定(extract_synopsis)と分岐(synopsis_for)は本物のまま回す。
検証3点(依頼の受け入れ条件):
  ① あらすじ有りページ → synopsis が入る(非null・本文を含む)
  ② 無いページ         → null
  ③ 取得が例外/失敗    → null かつ例外を投げない(パイプラインを止めない)
走らせ方: python docs/departments/product-scout/tools/test_synopsis.py
"""
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import candidates_json as cj

# 実ページ相当の最小HTML(同人ページは <div class="summary__txt"> に全文)
HTML_WITH = ('<html><body><div class="summary__txt">'
             '「都会の子って……」<br>まさか、田舎のJKが……。&amp;続き'
             '</div></body></html>')
HTML_WITHOUT = '<html><body><div class="other">レビュー65件</div></body></html>'

fails = []
def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

# ── extract_synopsis(純関数・本物) ───────────────────────────────
s = cj.extract_synopsis(HTML_WITH)
chk("①有り: 本文が入る(非null)", s is not None)
chk("①有り: 本文を含む", bool(s) and "田舎のJK" in s)
chk("①有り: HTMLエンティティを復号(&amp;→&)", bool(s) and "&続き" in s)
chk("①有り: タグが残っていない", bool(s) and "<" not in s and ">" not in s)
chk("②無し: null", cj.extract_synopsis(HTML_WITHOUT) is None)
chk("②空HTML: null", cj.extract_synopsis("") is None)

# ── synopsis_for(分岐は本物・fetchだけ偽物) ─────────────────────
chk("①有り経路: synopsis_for が本文を返す",
    cj.synopsis_for("d_1", fetch=lambda u: HTML_WITH) is not None)
chk("②無し経路: synopsis_for が null",
    cj.synopsis_for("d_2", fetch=lambda u: HTML_WITHOUT) is None)

# ③ 取得が例外でも落ちない(fail-open=パイプラインを止めない)
def boom(u):
    raise RuntimeError("network down")
try:
    r = cj.synopsis_for("d_3", fetch=boom)
    chk("③取得例外: nullで継続(例外を投げない)", r is None)
except Exception:
    chk("③取得例外: nullで継続(例外を投げない)", False)

# Books(d_以外)は URL を組まない=fetchを呼ばずに null(推測URLを叩かない)
called = {"n": 0}
def spy(u):
    called["n"] += 1
    return HTML_WITH
chk("Books: page_url_for が None", cj.page_url_for("b_9") is None)
chk("Books: fetchを呼ばず null", cj.synopsis_for("b_9", fetch=spy) is None and called["n"] == 0)
chk("同人: page_url_for が作品ページURL",
    (cj.page_url_for("d_1") or "").endswith("cid=d_1/"))

print(("\nALL PASS" if not fails else "\nFAILED: " + ", ".join(fails)))
sys.exit(0 if not fails else 1)
