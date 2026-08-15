#!/usr/bin/env python3
"""GOLDEN: 名乗り → characterfile の引き当て(表記ゆれで素通しにならないこと)。

真因(2026-08-15 実測)= `_character_by_persona` が**完全一致1本**で、名乗りと
characterfileの見出しが1文字でも違うと空を返す。空= `no_character` で
**その便は口調変換を通らず素通しで部屋へ出る**(黙って落ちるので誰も気付かない)。
実例= 名乗り「ケヴィン・デ・ブライネ」/ 見出し「ケヴィン・デブライネ」=中黒1つ違い。

対策= 完全一致で外れたら**中黒・空白を落とした形**で照合し直す。ただし
2人以上へ当たったら人違いなので採らない(素通しのまま=安全側)。

★表記の正誤は人事部門の管轄。ここが見るのは「どちらで名乗っても同じ人へ着く」配線だけ。

実行: python tests/test_persona_render_name.py   (全PASSで終了コード0)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import persona_render as pr  # noqa: E402

FAIL = []


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAIL.append(label)


def headings():
    """characters/*.md の見出しから (名前, ファイル名) を集める。"""
    out = []
    for fn in sorted(os.listdir(pr._CHAR_DIR)):
        if not fn.endswith(".md"):
            continue
        try:
            head = open(os.path.join(pr._CHAR_DIR, fn), encoding="utf-8").readline()
        except OSError:
            continue
        m = re.match(r"#\s*characterfile:\s*([^(（\n]+)", head)
        if m:
            out.append((m.group(1).strip(), fn))
    return out


def main():
    names = headings()
    check("①-a characterfileが読める場所にある(見出しつき %d件)" % len(names), len(names) >= 15)

    # ②本丸= 中黒の入った名乗りでも引ける。名乗りはイージス研究室の起動文の表記。
    body = pr._character_by_persona("ケヴィン・デ・ブライネ")
    check("②-a 中黒ありの名乗りで引ける(修正前は0字)", len(body) > 1000)
    check("②-b 引いたのは本人のファイル", "デブライネ" in (body.splitlines() or [""])[0])
    check("②-c 見出しどおりの表記でも従来どおり引ける",
          len(pr._character_by_persona("ケヴィン・デブライネ")) > 1000)

    # ③完全一致は先に見る=優先順位を変えていない。全キャラで退行なし。
    miss = [n for n, _ in names if len(pr._character_by_persona(n)) < 200]
    check("③-a 見出しの表記そのままなら全員引ける(引けない= %s)" % (miss or "なし"), not miss)

    # ④でっち上げない。判定不能は空=素通し(fail-open)。
    check("④-a 存在しない人格は空", pr._character_by_persona("居ない人") == "")
    check("④-b 空文字・Noneは空",
          pr._character_by_persona("") == "" and pr._character_by_persona(None) == "")

    # ⑤正規化で2人が同じ形へ潰れると人違いになる。実データで衝突していないこと。
    keys = {}
    for n, fn in names:
        keys.setdefault(pr._name_key(n), []).append(fn)
    dup = {k: v for k, v in keys.items() if len(v) > 1}
    check("⑤-a 中黒を落としても衝突しない(衝突= %s)" % (dup or "なし"), not dup)

    # ⑥衝突した時は採らない(人違いを出すくらいなら素通し)。合成データで分岐を通す。
    real_dir = pr._CHAR_DIR
    try:
        import tempfile
        tmp = tempfile.mkdtemp()
        for i, fn in enumerate(("a.md", "b.md")):
            with open(os.path.join(tmp, fn), "w", encoding="utf-8") as f:
                f.write("# characterfile: 山田%s太郎(検証用)\n" % ("・" if i else "") + "x" * 900)
        pr._CHAR_DIR = tmp
        # ★完全一致する名乗り(山田太郎)は①で決着してしまうので、
        #   どちらとも完全一致しない形(空白区切り)で②の分岐へ入れる。
        check("⑥-a 正規化後に2人へ当たったら引かない(人違いを出さない)",
              pr._character_by_persona("山田 太郎") == "")
        check("⑥-b 完全一致するなら衝突していても引ける",
              len(pr._character_by_persona("山田・太郎")) > 100)
    finally:
        pr._CHAR_DIR = real_dir

    print("\n%d PASS / %d FAIL" % (10 - len(FAIL), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
