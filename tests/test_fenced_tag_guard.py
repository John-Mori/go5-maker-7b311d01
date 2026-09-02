# -*- coding: utf-8 -*-
"""恒久策#4の**両側**を固定する検査(イージス研究室 / 2026-09-02)。

設計書 §5-6(`docs/departments/kaizen-analyst/設計_4種不具合恒久策_横断_2026-09-02.md`)の要求=
  「`[ККール]` が `[ククール]` へ**直らなければ fail**、かつ**コード柵の中が直ったら fail**」。
前半は `scripts/llm/test_nonjp_gate.py:test_homoglyph_tag_fix` で既に緑。
ここは**後半**= 柵の中の `[名前]` を名乗りとして拾わないこと、を実行で固定する。

場面(実物)= 2026-09-02 に本番の `split_persona_blocks` へ通した検体
  "```\\n[ККール] これはコード例だ\\n```\\n本文はここ。"
  期待  [(None, 原文そのまま)]
  実際  [('ククール', 'これはコード例だ\\n```\\n本文はここ。')]
  = 柵の**開き行ごと**落ちてコードブロックが割れ、コード例のつもりの字が名義になった。

★C-053 の must-fail は「動く別の実装」へ戻す= `_fenced_lines` を
  **2026-09-02 の本番そのもの(柵を数えない)** へ差し替える。その実装でも普通の便の
  名乗り解決は正しく動く(=空実装ではない)ので、赤くなるのは柵の便だけになる。

    python tests/test_fenced_tag_guard.py
"""
import os
import sys

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PJ, "scripts", "llm"))
import dept_daemon as d                      # noqa: E402

NG = []
RUN = []
NAMES = ("ククール", "五月")

# 実物の検体(2026-09-02 に本番へ通したもの)
FENCE_ONLY = "```\n[ККール] これはコード例だ\n```\n本文はここ。"
HEAD_THEN_FENCE = "[ККール] 本文の頭で化けた。\n\n```\n[ククール] 柵の中\n```"
PLAIN_BROKEN = "[ККール] その2枚、もう入ってるぜ。"


def check(name, cond):
    """数え方は1つ= `check()` を呼んだ回数 == PASS行+FAIL行 == 末尾の総数。"""
    RUN.append(name)
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        NG.append(name)


def resolve(nm):
    return "ククール" if str(nm).strip() == "ククール" else None


def split(text):
    """台帳へ書かずに分割だけ回す(外へ出る手だけ偽物・判定と分岐は本物)。"""
    real = d._audit_tag
    seen = []
    d._audit_tag = lambda dept, who, outcome, line="": seen.append(outcome)
    try:
        return d.split_persona_blocks(text, resolve, dept="aegis-gl", names=NAMES), seen
    finally:
        d._audit_tag = real


# --- 1) ★設計§5-6 前半: 柵の外の化けタグは今までどおり直る(直らなければ fail) --------
blocks, seen = split(PLAIN_BROKEN)
check("§5-6前半: 柵の外の [ККール] は [ククール] へ直る",
      len(blocks) == 1 and blocks[0][0] == "ククール")
check("§5-6前半: 漏れ→救済の順で数える(化けた回数が消えない)",
      seen == ["tag_homoglyph_leak", "tag_homoglyph_rescued"])

# --- 2) ★設計§5-6 後半: 柵の**中**は名乗りではない(直ったら fail) -------------------
blocks, seen = split(FENCE_ONLY)
check("§5-6後半: 柵の中の [ККール] を名義に採らない(名義未解決のまま)",
      len(blocks) == 1 and blocks[0][0] is None)
check("§5-6後半: 柵の中を1文字も剥がさない(コードブロックが割れない)",
      len(blocks) == 1 and blocks[0][1] == FENCE_ONLY)
check("§5-6後半: 柵の中は救済としても数えない(台帳を汚さない)",
      "tag_homoglyph_rescued" not in seen)

# --- 3) 頭が化けた便+柵= 救済はする / 柵の中身は保つ(片側だけ効かせる) ---------------
blocks, seen = split(HEAD_THEN_FENCE)
check("併存: 頭の化けタグは救済される", len(blocks) == 1 and blocks[0][0] == "ククール")
check("併存: 柵の中の [ククール] で**ブロックを割らない**", len(blocks) == 1)
check("併存: 柵の中身が原文のまま残る(3行とも欠けない)",
      blocks and "```\n[ククール] 柵の中\n```" in blocks[0][1])

# --- 4) fail-open= 閉じ忘れた柵で名乗り解決を殺さない ----------------------------------
blocks, _ = split("```\n[ККール] 閉じ忘れの柵")
check("fail-open: 閉じ忘れた柵は柵の外扱い(従来どおり救済する)",
      len(blocks) == 1 and blocks[0][0] == "ククール")
check("fail-open: `_fenced_lines` は例外でも空集合(従来挙動)", d._fenced_lines(None) == set())
check("fail-open: 柵が無い便では1行も柵と数えない",
      d._fenced_lines(["[ククール] ふつうの便", "2行目。"]) == set())

# --- 5) `_fenced_lines` そのものの健全性(印の取り違えで誤って全文を柵にしない) --------
check("柵: ``` の開閉で挟まれた行(柵の行込み)を返す",
      d._fenced_lines(["a", "```", "x", "```", "b"]) == {1, 2, 3})
check("柵: ~~~ も柵として数える",
      d._fenced_lines(["~~~", "x", "~~~"]) == {0, 1, 2})
check("柵: 別の印では閉じない(``` を ~~~ で閉じたことにしない)",
      d._fenced_lines(["```", "x", "~~~", "y"]) == set())

# --- 6) ★must-fail: `_fenced_lines` を**2026-09-02の本番**(柵を数えない)へ戻す --------
#   これは「動く別の実装」= 柵を持たない便では今も正しく名乗りを解決する。
#   足りないのは「柵の中を除く」一点だけ= だから 1)は緑のまま 2)だけが赤くなるはず。
def _fenced_none(lines):
    """動く別実装= 柵という概念が無かった頃の本番(常に空集合)。"""
    return set()


real_fenced = d._fenced_lines
try:
    d._fenced_lines = _fenced_none
    blocks_mut, _ = split(FENCE_ONLY)
    check("must-fail: 柵を数えない実装だと**柵の中が名義になる**(この検査が意味を持つ)",
          len(blocks_mut) == 1 and blocks_mut[0][0] == "ククール"
          and blocks_mut[0][1] != FENCE_ONLY)
    blocks_ok, _ = split(PLAIN_BROKEN)
    check("must-fail: その別実装でも普通の便は正しく解ける(空実装ではない)",
          len(blocks_ok) == 1 and blocks_ok[0][0] == "ククール")
finally:
    d._fenced_lines = real_fenced

blocks, _ = split(FENCE_ONLY)
check("must-fail後: 本物へ戻して柵の便がまた守られる", blocks[0][0] is None)

print("-" * 60)
print("%d/%d PASS%s" % (len(RUN) - len(NG), len(RUN),
                        "" if not NG else "  NG: " + " / ".join(NG)))
sys.exit(1 if NG else 0)
