# -*- coding: utf-8 -*-
"""検査18(文書mdの簡体字)の検査(イージス研究室 / 2026-09-01)。

場面(実物)= 送信口のルールAへ簡体字を合流させた直後、研究室HQが
  `docs/` + `00_AI-HQ/departments/` + `00_AI-HQ/status/` の md 354ファイル/42,773行を走査し、
  **混入10行**(うち9行が `docs/departments/kaizen-analyst/名乗り漏れ_開き括弧なしタグ_型.md`)を出した。
  Discord側の事故4行より**ファイル側の方が多い**= ゲートの射程外に大きい塊が在った。
  ファイル書き込みには合流点が無い(Write/Edit/Bashと無数)ので、ゲートではなく**日次の検査**にした。

★この検査で守りたい失敗は1つだ= **除外を広げ過ぎて、本物の混入が黙って消えること。**
  検査は書かない・直さない・失敗させない(bumpしない)ので、唯一の実害が「見えなくなる」ことになる。

★C-053= 壊した側は**動く別の実装**であること。
  ここでの「別実装」= 除外の物差しを「前置き」まで広げた `scan_loose()`。
  それ自体は完全に動く(同じ入力を受け、同じ形を返す)。違うのは**除外が1語広い**だけ。
  そしてその1語で、実物の型doc9行のうち複数が**静かに消える**= 偽の緑になる。

    python tests/test_simplified_md_check.py
"""
import io
import os
import re
import shutil
import sys
import tempfile

HQ_SCRIPTS = r"D:\SougouStartFolder\00_AI-HQ\scripts"
sys.path.insert(0, HQ_SCRIPTS)
import relay_health as rh                       # noqa: E402

NG = []
RUN = []


def check(name, cond):
    """数え方は1つに揃える= `check()` を呼んだ回数 == PASS行+FAIL行 == 末尾の総数。"""
    RUN.append(name)
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        NG.append(name)


def scan(root, talking=None):
    """検査18の本体を、走査先だけ差し替えて**実行で**通す(判定と分岐は本物のまま)。

    偽物にするのは外から与える2つ(走査先ディレクトリ・除外の物差し)だけ。
    表の読み込み・findall・除外・集約・表示は relay_health のコードがそのまま走る。
    """
    keep_roots, keep_talk, keep_prob = rh.SIMPLIFIED_MD_ROOTS, rh.SIMPLIFIED_MD_TALKING, rh.problems
    buf = io.StringIO()
    keep_out = sys.stdout
    rh.SIMPLIFIED_MD_ROOTS = (root,)
    if talking is not None:
        rh.SIMPLIFIED_MD_TALKING = talking
    sys.stdout = buf
    try:
        rh.check_simplified_md()
    finally:
        sys.stdout = keep_out
        rh.SIMPLIFIED_MD_ROOTS = keep_roots
        rh.SIMPLIFIED_MD_TALKING = keep_talk
    return buf.getvalue(), rh.problems - keep_prob


def scan_loose(root):
    """動く別実装= 除外の物差しに「前置き」を足しただけの検査18(C-053の壊した側)。

    「前置き实况の話をしている行は引用だろう」は**一見もっともらしい**。
    だが実物の型docは、まさに「前置き实况」という語で**壊れた字のまま書かれている**。
    つまりこの1語で、本物の混入が引用として黙って落ちる。
    """
    return scan(root, talking=re.compile(r"簡体字|常用漢字|混入|hangul_audit|简|前置き"))


# 実物の型doc(名乗り漏れ_開き括弧なしタグ_型.md)から、性質の違う行をそのまま採った
TYPEDOC = "\n".join([
    "# 名乗り漏れ 乙 の型",
    "つまり丙という別種ではなく**乙そのもの**(単独人格部屋＋前置き实况)。",          # L11相当= 本物の混入
    "セッションが書いた前置き实况も先頭 `[名前]` タグもそのまま顔で出る。",          # L57相当= 本物の混入
    "引き金3は「前置き实况＋タグ」の複合で、单独部屋では前置きも落ちない。",         # L69相当= 1行に2種
    "普通の日本語の行= 単独部屋の実況は前置きとして落とす。",                       # 混入なし
])
# 規律・PDCA・台帳のように「この件を論じている」ので字を引用して当然の行
TALKING = "\n".join([
    "- **表記**= 半角括弧 `()`/★**簡体字を混ぜるな**(実況であって实况ではない)",
    "- HQが走査した。本物の混入=**4行・2部屋**(实况)。",
])

tmp = tempfile.mkdtemp(prefix="simpmd_")
try:
    io.open(os.path.join(tmp, "型.md"), "w", encoding="utf-8").write(TYPEDOC)
    io.open(os.path.join(tmp, "規律.md"), "w", encoding="utf-8").write(TALKING)

    out, delta = scan(tmp)

    # --- 1) ★must-fail: 除外を1語広げた「動く別実装」は、本物の混入を静かに落とす ----------
    out_loose, _ = scan_loose(tmp)
    check("must-fail: 除外に『前置き』を足すと混入が消える(偽の緑)",
          "混入なし" in out_loose and "★混入" not in out_loose)
    check("本物の検査18は同じ入力で混入を見つける", "★混入 3行" in out)

    # --- 2) 引用(論じている行)は★にしない・ただし件数は必ず見せる -------------------------
    check("論じている行2行は除外され、件数が表示される", "除外 2行" in out)
    check("除外した行は★の側に混ざっていない", "規律.md" not in out)

    # --- 3) 1行に2種入っていたら両方出す(型doc L69= 实 と 单) ---------------------------
    check("1行2種を取りこぼさない(实→実 と 单→単 が両方出る)",
          "实→実" in out and "单→単" in out)

    # --- 4) 表は借り物であること(送信口と同じ1本=物差しを二重に持たない) ------------------
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "scripts", "llm"))
    import lang_gate                            # noqa: E402
    check("走査の見出しに表の字数が出る(送信口と同じ表を引いている)",
          ("表 %d 字" % len(lang_gate._SIMPLIFIED_MAP)) in out)

    # --- 5) ★総合判定を赤くしない(HQ裁定= 数えるだけ・失敗させない) ---------------------
    check("bump していない(常時赤で検査が無視されるのを避ける)", delta == 0)

    # --- 6) 混入が無い所では静かにする(騒がしい安全網は無視される) -----------------------
    clean = tempfile.mkdtemp(prefix="simpmd_clean_")
    try:
        io.open(os.path.join(clean, "きれい.md"), "w", encoding="utf-8").write(
            "実況の前置きは落とす。単独部屋でも同じだ。机の上に書類を据える。")
        out_clean, delta_clean = scan(clean)
        check("混入なしの時は『混入なし』とだけ言う",
              "混入なし" in out_clean and "★混入" not in out_clean)
        check("混入なしでも bump しない", delta_clean == 0)
    finally:
        shutil.rmtree(clean, ignore_errors=True)

    # --- 7) 読めないファイルや空の走査先で検査を落とさない(fail-safe) --------------------
    empty = tempfile.mkdtemp(prefix="simpmd_empty_")
    try:
        out_empty, _ = scan(empty)
        check("走査先が空でも例外を出さず0行と言う",
              "0 ファイル / 0 行" in out_empty and "混入なし" in out_empty)
    finally:
        shutil.rmtree(empty, ignore_errors=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("-" * 60)
print("%d/%d PASS%s" % (len(RUN) - len(NG), len(RUN),
                        "" if not NG else "  NG: " + " / ".join(NG)))
sys.exit(1 if NG else 0)
