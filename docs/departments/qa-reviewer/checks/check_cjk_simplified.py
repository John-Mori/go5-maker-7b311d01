#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""簡体字混入チェック(QA・AI不要の決定的リンタ)。

Chamiの要望(2026-09-06)=「PythonやAIを使わない軽いチェックが欲しい、ローカルqwenでも」への答え。
この判定に**AIは要らない**。簡体字かどうかは `lang_gate._SIMPLIFIED_MAP`(常用漢字と簡体字の集合差の表)
との**文字集合の照合**で確定する=無料・確定的・オフライン。qwen も Codex も不要。

★判定の芯は1本(lang_gate)を借りる=表を二重に持たない(ドリフト防止)。ここは検知するだけ。
  自動置換はしない(理由= lang_gate.detect_simplified の docstring。「实况ではなく実況」のような
  字そのものを論じた正当な引用まで壊すから)。直し方は「再生成1回」で、それは生成側(基盤)の仕事。

使い方:
    python check_cjk_simplified.py --file path.txt
    python check_cjk_simplified.py --text "DevTools无く"
    echo "本文" | python check_cjk_simplified.py

exit 0 = 混入なし / exit 1 = 混入あり(該当字・日本語字・位置・前後を1件ずつ表示)。
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))


def _scan(text, span=20):
    """本文中の簡体字を全件返す。lang_gate の表(単一の真実)を借りる。"""
    import lang_gate  # 芯は借りる=表を二重に持たない
    s = str(text or "")
    hits = []
    for m in lang_gate._SIMPLIFIED_RE.finditer(s):
        i = m.start()
        c = m.group(0)
        hits.append({
            "char": c,
            "jp": lang_gate._SIMPLIFIED_MAP.get(c, ""),
            "codepoint": "U+%04X" % ord(c),
            "index": i,
            "context": s[max(0, i - span):i + 1 + span],
        })
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--text")
    args = ap.parse_args()
    if args.text is not None:
        text = args.text
    elif args.file:
        text = open(args.file, encoding="utf-8", errors="replace").read()
    else:
        text = sys.stdin.read()

    hits = _scan(text)
    if hits:
        print(f"FAIL: check_cjk_simplified (簡体字{len(hits)}件)")
        for h in hits:
            jp = f"=日本語では{h['jp']}" if h["jp"] else ""
            print(f"  - {h['char']}({h['codepoint']}){jp} 位置={h['index']} 前後=…{h['context']}…")
        return 1
    print("PASS: check_cjk_simplified (簡体字の混入なし)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
