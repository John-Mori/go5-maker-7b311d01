# -*- coding: utf-8 -*-
"""ハングル検知を「コード柵の中は見ない」へ揃えた件の検査台(2026-09-17・イージス研究室)。

出どころ= Chami依頼(msg 1550002171422969919 → 1550002312519352321)
  「わざとハングルを混ぜたテスト会話では ⚠️(自動)生成不良 を出さない/数えない」。
  数える側(warn_gen_count.py)は改善提案部門が確認済み=追加実装ゼロ。
  こちらは**器**= dept_daemon.detect_hangul が生の本文へ _HANGUL_RE を掛けていた分。

★何を見ているか(芯)= 「柵の中は鳴らない」だけでは検査にならない。**柵の外は今までどおり鳴る**
  ことと、**旧実装なら同じ本文で鳴った**ことを同じ場面で並べて初めて、変えた範囲が見える。
★送信可否は1ミリも触っていない=ここは**検知だけ**の検査。

  実行= python scripts/llm/test_hangul_mask_code_spans.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # scripts/
sys.path.insert(0, os.path.join(ROOT, "llm"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import dept_daemon as dd    # noqa: E402

OK = []
NG = []


def check(name, cond, extra=""):
    (OK if cond else NG).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + (("  " + extra) if extra else ""))


# ---------------------------------------------------------------- 1) 退行なし
bare = "판断待ちボードへ2件を追記しました"
hit = dd.detect_hangul(bare)
check("素のハングルは今までどおり鳴る(退行なし)", bool(hit) and hit["char"] == "판",
      repr(hit and hit["char"]))
check("index は原文基準", bool(hit) and hit["index"] == bare.index("판"),
      "index=%s" % (hit and hit["index"]))
check("context に原文の前後が載る", bool(hit) and "断待ち" in hit["context"])

# 柵が在っても、柵の外のハングルは鳴る。位置も原文基準のまま(マスクは長さを保存する)。
mixed = "報告です。\n```\n판\n```\nこの판は地の文です"
hit = dd.detect_hangul(mixed)
check("柵の外のハングルは鳴る(柵が在っても見逃さない)", bool(hit))
check("柵を跨いでも index は原文基準", bool(hit) and mixed[hit["index"]] == "판"
      and hit["index"] == mixed.rindex("판"), "index=%s" % (hit and hit["index"]))

# ---------------------------------------------------------------- 2) 今回の直し
check("```で囲んだハングルは鳴らない", dd.detect_hangul("テスト会話です\n```\n판단\n```\n以上") is None)
check("インラインコードのハングルは鳴らない", dd.detect_hangul("`판` は判の韓国語読み") is None)
check("URL の中のハングルは鳴らない", dd.detect_hangul("出典 https://example.com/판단 を見よ") is None)
check("柵だけの本文は鳴らない", dd.detect_hangul("```판```") is None)

# ---------------------------------------------------------------- 3) 印の経路(detect_nonjp)
n = dd.detect_nonjp("テスト会話\n```\n판단\n```\nここは日本語")
check("detect_nonjp も柵内ハングルでは印を付けない", n is None, repr(n))
n = dd.detect_nonjp("柵内は```판```。地の文に实况が混じった")
check("柵内ハングルを飛ばした後、地の文の簡体字は拾う(順番は不変)",
      bool(n) and n.get("kind") == "simplified", repr(n and n.get("kind")))
n = dd.detect_nonjp("판断待ちボード")
check("素のハングルは今までどおり kind=hangul", bool(n) and n.get("kind") == "hangul")

# ---------------------------------------------------------------- 4) 隣の検知器は不変
check("簡体字: 素の混入は鳴る(不変)", bool(dd.detect_simplified("实况ではなく実況だ")))
check("簡体字: 柵の中も従来どおり鳴る(今回は触っていない)",
      bool(dd.detect_simplified("```\n实况\n```")))
check("キリル: 素の混入は鳴る(不変)", bool(dd.detect_cyrillic("[Ккール] と名乗った")))
check("キリル: 柵の中は鳴らない(2026-09-02 から不変)",
      dd.detect_cyrillic("```\n[Ккール]\n```") is None)

# ---------------------------------------------------------------- 5) fail-safe
for bad in (None, "", 0, 12.5, [], {"a": 1}, object()):
    try:
        dd.detect_hangul(bad)
        ok = True
    except Exception:
        ok = False
    if not ok:
        break
check("None・空・非文字列でも例外を出さない(fail-safe)", ok)

# ---------------------------------------------------------------- 6) must-fail(旧実装との対比)
# 旧実装= マスクを通さずに生の本文へ _HANGUL_RE を掛けていた。**同じ本文で鳴ったこと**を
# ここで実際に走らせて見せる。これが鳴らなければ、上の PASS は「元から鳴らない本文」を
# 見ていただけ=検査になっていない。
fenced = "テスト会話です\n```\n판단\n```\n以上"
old_hit = dd._HANGUL_RE.search(fenced)          # ← 旧実装と同じ式(マスク無し)
check("must-fail: 旧実装(生判定)は同じ本文で鳴る = OLD-HIT:%s" % (old_hit and old_hit.group(0)),
      old_hit is not None)
check("must-fail: 新実装は同じ本文で鳴らない(差分がここに在る)",
      dd.detect_hangul(fenced) is None)

# 旧実装が本当にその形だったか(現物の控えで確かめる。記憶で言わない)
bak = os.path.join(os.path.dirname(ROOT), "local", "_work", "dept_daemon.py.bak.20260917_1345")
src_now = open(os.path.join(ROOT, "llm", "dept_daemon.py"), encoding="utf-8").read()
if os.path.exists(bak):
    src_old = open(bak, encoding="utf-8").read()
    check("控え(.bak)の旧実装は _HANGUL_RE.search(s) だった",
          "_HANGUL_RE.search(s)" in src_old)
else:
    check("控え(.bak)が在る", False, bak)
check("現行は _HANGUL_RE.search(_mask_code_spans(s)) へ揃っている",
      "_HANGUL_RE.search(_mask_code_spans(s))" in src_now
      and "_HANGUL_RE.search(s)" not in src_now)
check("範囲(_HANGUL_RE)は変えていない",
      re.search(r'_HANGUL_RE = re\.compile\(r"\[가-힣ᄀ-ᇿㄱ-ㆎ\]"\)', src_now) is not None)

print("-" * 60)
print("%d PASS / %d FAIL" % (len(OK), len(NG)))
if NG:
    for n in NG:
        print("  FAIL: " + n)
    sys.exit(1)
print("ALL PASS")
