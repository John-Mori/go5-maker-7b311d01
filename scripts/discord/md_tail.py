#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""末尾マークダウン片ゲートの**正本**(2026-09-20・イージス研究室)。

起点= Chami 便 msg 1551230317585760277「細かいんだけどさあ、語尾に余計なやつ付いてるんだよね、
恒久改善してください」。指していたのは msg 1551223793593360465 の末尾 `…組み込むわよ。``` 。
型= docs/departments/kaizen-analyst/型_末尾マークダウン片_送信ゲート正規化_2026-09-20.md(改善提案部門)。

何を落とすか= **本文の末尾に接する、対応の無いバッククォート片だけ**。
  ・句点直後の空バッククォート(`。``` など中身の無いコード span が文末に貼り付いたもの)
  ・最終行が ``` だけの孤立フェンス(開き柵が無い閉じ柵/閉じの無い開き柵)
何を落とさないか= `--list` のような**中身のある**インラインコード、開き+閉じの揃った正規
  コードブロックの閉じ柵、**本文中間**のバッククォート(C-056= 消して改悪にしない)。

★新しいパーサを書かない(ORG-11)。判定は既存の `lang_gate._mask_code_spans` 1本を引く。
  あれは「中身の揃ったコード柵/インラインコード/URL」を**長さを保存して**空白へ潰す。
  潰れずに末尾へ生き残ったバッククォート= 対応の無い片、という読み方だけをここで足す。
★fail-open= lang_gate が読めない/例外なら素通し(送信は殺さない・現行3ゲートと同じ向き)。
★閉じを自動で補わない(推測でコードブロックを作らない)。消すだけ。
★本文が空になる削りはしない(白紙の便を投げない)。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 末尾に接する「バッククォートと空白だけ」の区間。★バッククォートを1つは含むこと。
_TAIL_RE = re.compile(r"[`\s]*`[`\s]*$")


def _mask(text):
    """lang_gate._mask_code_spans を引く(読めなければ None= 判定しない)。"""
    try:
        _llm = os.path.join(ROOT, "scripts", "llm")
        if _llm not in sys.path:
            sys.path.insert(0, _llm)
        from lang_gate import _mask_code_spans
        return _mask_code_spans(text)
    except Exception:
        return None


def find_stray_tail(body):
    """末尾の余計なマークダウン片の**開始位置**を返す(無ければ None)。判定だけ・直さない。

    手順:
      1. 原文の末尾から「バッククォート/空白だけ」の区間 T を取る(k= その開始位置)。
      2. T の中のバッククォートが**T より前と組んでいる**なら触らない。
         判定= `mask(全文)[:k]` と `mask(全文[:k])` が違う= 境界をまたぐ span が在る、ということ
         (例: `python … --list` の閉じ / 正規コードブロックの閉じ柵)。
      3. またいでいなければ T は stray= T は定義上「バッククォートと空白」しか含まないので、
         そこで閉じている span は**中身が空**(`。``` の空インラインコード)か、
         相手のいない孤立フェンスのどちらかしか有り得ない。
    ★2で不明(マスク不能)なら None= 素通し。
    ★「マスク後に生き残った柵だけ削る」では足りない= 実測で分かった。`。``` は左から
      `` `` `` が空 span として**潰れてしまい**、Chamiが指した実物(msg 1551223793593360465
      / 2026-09-20T22:29:32 花海咲季)が素通りした。潰れたかどうかではなく
      **前と組んでいるか**で見る。
    """
    s = str(body or "")
    if "`" not in s:
        return None
    m = _TAIL_RE.search(s)
    if not m:
        return None                       # 末尾がバッククォートで終わっていない=対象外
    k = m.start()
    masked = _mask(s)
    if masked is None or len(masked) != len(s):
        return None                       # 判定できない=素通し(fail-open)
    head_masked = _mask(s[:k])
    if head_masked is None or masked[:k] != head_masked:
        return None                       # 境界をまたぐ span が在る= 末尾は legit な閉じ
    return k


def strip_stray_tail(body):
    """余計な末尾片を落とした本文と、落とした片を返す。

    返り値= (新しい本文, 落とした文字列)。落とさなかった時の第2要素は "" 。
    """
    s = str(body or "")
    k = find_stray_tail(s)
    if k is None:
        return s, ""
    out = s[:k].rstrip()
    if not out.strip():
        return s, ""                      # 全部消える= 白紙の便になる。削らない(fail-safe)
    return out, s[k:]


def trailing_md_backstop(body, tag="persona_send", quiet=False):
    """Discordへ出る本文から末尾の余計なマークダウン片を落とす(送信口から呼ぶ入口)。

    ★例外は自分で飲んで原文を返す= ここで送信を殺さない。
    """
    try:
        out, cut = strip_stray_tail(body)
        if cut and not quiet:
            print(f"[{tag}] ★末尾の余計なマークダウン片を除去({cut!r})"
                  f"=生成側の閉じ忘れ/空コード span を合流点で落とす(型=改善提案部門 2026-09-20)。",
                  file=sys.stderr)
        return out
    except Exception as e:
        if not quiet:
            print(f"[{tag}] 末尾マークダウン片ゲート不能({type(e).__name__})=素通し(fail-open)",
                  file=sys.stderr)
        return body
