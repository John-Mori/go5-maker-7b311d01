# -*- coding: utf-8 -*-
"""封筒(毎便すべての部門へ注入される文章)自身が、呼称の正本に反する綴りを教えていないか検査する。

★なぜ要るか(2026-08-23・イージス研究室からの §3.9横展開 / Chami原文 msg 1540937050579148820
  「いつまで経ってもキャラがちゃんと設定した呼び方じゃなくてどっかでミスる」)
  `裁定カタログ.md` の見出し4件が「ケヴィン・デ・ブライネ」(旧綴り)のままだった。
  この見出しは **dept_daemon が毎便すべての部門のプロンプトへ注入している**。
  同じ封筒の共通規律§5には「★『デブライネ』は中黒なし」と書いてある=
  **規律が禁じている綴りを、同じ封筒が4回教えていた。**
  出力側(呼称ゲート)をいくら直しても、**入力が間違いを教えている間は生成側の穴は塞がらない**
  (共通規律 §4.55「生成側の穴は、作る側を直して初めて『直った』」)。

★何を見るか
  ①呼称の正本 `00_AI-HQ/departments/hr/personas/呼称ルール.json` から**正しい人名**を集める。
  ②その人名の「中黒(・)を1つ足した/1つ削った」**近傍のゆれ**を機械で作る。
  ③封筒に載る文章の中に、そのゆれが出ていないか探す。

★何を見ていないか(誤読を防ぐために先に書く)
  ゆれの作り方は**中黒の増減だけ**だ。表記ゆれ全般(長音・カタカナ英字)は見ていない。
  ここが黙っても「呼称は全部正しい」ではない。**中黒ゆれだけは二度と入らない**、が正確な意味。

使い方:
  python scripts/llm/envelope_naming_check.py          # 違反が在れば exit 1
"""
import io
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    # ★裸で呼ぶな。pythonw.exe や出力を持たない親から取り込むと sys.stdout が None で、
    #   AttributeError で**取り込みごと落ちる**(2026-08-23 イージス研究室の実測=
    #   毎時起きて一度も検査しない見張りが出来上がるところだった)。
    #   ここは表示の都合であって判定ではない=用意できない時は黙って諦めて、scan() は通す。
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HQ = r"D:\SougouStartFolder\00_AI-HQ"
NAMES_JSON = os.path.join(HQ, "departments", "hr", "personas", "呼称ルール.json")
CATALOG = os.path.join(HQ, "裁定カタログ.md")
RULES = os.path.join(HQ, "departments", "00_common", "全部門共通規律.md")

NAKAGURO = "\u30fb"


def canonical_names(path=NAMES_JSON):
    """正本から**正しい人名**を集める。中黒を含む名前だけが対象(ゆれる余地が在るのはそこ)。"""
    with io.open(path, encoding="utf-8") as f:
        d = json.load(f)
    names = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and NAKAGURO in k and not k.startswith("_"):
                    names.add(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            if NAKAGURO in node and 3 <= len(node) <= 14 and " " not in node:
                names.add(node)

    walk(d)
    return sorted(names)


def variants(name):
    """`name` の**中黒ゆれ**を作る(1つ削る / 1つ足す)。正しい綴り自身は含めない。"""
    out = set()
    for i, ch in enumerate(name):                       # 中黒を1つ削る
        if ch == NAKAGURO:
            out.add(name[:i] + name[i + 1:])
    for i in range(1, len(name)):                       # 中黒を1つ足す
        if name[i - 1] == NAKAGURO or name[i] == NAKAGURO:
            continue
        out.add(name[:i] + NAKAGURO + name[i:])
    out.discard(name)
    return sorted(out)


def envelope_sources():
    """封筒へ実際に載る文章。★カタログは**見出し行だけ**が載る(dept_daemon `### C-` 抽出)。

    本文(過去の記録・引用)は載らないので検査しない= そこは旧綴りのままで正しい。
    """
    src = []
    if os.path.isfile(RULES):
        src.append((RULES, io.open(RULES, encoding="utf-8").read().split("\n"), 1))
    if os.path.isfile(CATALOG):
        lines = io.open(CATALOG, encoding="utf-8").read().split("\n")
        heads = [(i + 1, ln) for i, ln in enumerate(lines)
                 if ln.startswith("### C-") or ln.startswith("| C-")]
        src.append((CATALOG, heads, 0))
    return src


def scan():
    names = canonical_names()
    bad = []
    for name in names:
        vs = variants(name)
        for path, lines, mode in envelope_sources():
            seq = enumerate(lines, 1) if mode else lines
            for no, ln in seq:
                for v in vs:
                    if v in ln:
                        bad.append((path, no, name, v, ln.strip()[:70]))
    return names, bad


def main():
    names, bad = scan()
    print("封筒の呼称検査 / 正本の人名 %d件(中黒を含むもの)" % len(names))
    if not bad:
        print("違反なし= 封筒は正しい綴りだけを教えている")
        return 0
    print("★違反 %d件= **毎便すべての部門へ配られている文章**が誤った綴りを教えている:" % len(bad))
    for path, no, name, v, ln in bad:
        print("  x %s:%d  正=%s / 出ている綴り=%s" % (os.path.basename(path), no, name, v))
        print("      %s" % ln)
    return 1


if __name__ == "__main__":
    sys.exit(main())
