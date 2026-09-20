#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地の文の裸バッククォート・ゲートの**正本**(2026-09-21・イージス研究室)。

起点= Chami 便 msg 1551266364231000136「余計なコードブロックいらんて」。
指していたのは msg 1551239290879475896(デブライネ・2026-09-20T23:31)。
実測= あの便は Discord 上で**14区間・計722字がコード扱い**になっていた。中身は日本語の地の文で、
  一番大きい塊は 220字(複数行)。原因は「バッククォートそのものを話題にした」3か所=
  「中間の ` は1文字も触らない」/「型の本文は「```」だった」/「実物の末尾は「``」だった」。
  この裸の柵が柵の対合をずらし、以降のインラインコードが**1つずれて**地の文を飲んだ。

何を直すか= **文字として書かれた柵(=literal mention)だけ**をバックスラッシュで逃がす。
  ① 引用符に丸ごとくるまれた柵 = 「```」『``』"`"
  ② 前後が半角/全角スペースの孤立柵 = 中間の ` は
何を触らないか=
  ・中身のあるインラインコード(`--list` / `11474a8`)= 前後が空白で挟まれていない
  ・正規のコードブロック(```…```)の柵と中身= lang_gate の柵パターンで丸ごと除外する
  ・改行に接する柵(行頭の開き柵/行末の閉じ柵)= 上の②から改行を外してある
  ・既にバックスラッシュで逃がしてある柵

★新しいマークダウンパーサを書かない(ORG-11)。コードブロックの範囲は既存の
  `lang_gate._MASK_PATTERNS[0]`(柵の型)を引く。ここが足すのは「柵の**周りの1文字**を見る」
  という読み方だけ。
★fail-open= lang_gate が読めない/例外なら素通し(送信は殺さない・現行4ゲートと同じ向き)。
★消さない・並べ替えない= 逃がすだけ(見える文字は1字も減らない)。
★末尾に接する片は `md_tail.py` の持ち場。ここは**本文の中**を見る(順番= md_tail の後)。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_RUN_RE = re.compile(r"`+")
_JP_RE = re.compile(r"[ぁ-んァ-ヶ一-龥]")

# 1か所ずつ当て直す反復の安全弁(1便あたりの逃がし上限)。実測の最大は3か所。
_MAX_PASSES = 24

# ①の判定に使う引用符。開きと閉じは同じ添字で対応させる(ASCII引用符は開き=閉じ)。
_QUOTE_OPEN = "「『【（(\"'"
_QUOTE_CLOSE = "」』】）)\"'"

# ②の判定に使う空白。★改行を入れない= 行頭/行末の柵は正規のブロックの可能性がある。
_INLINE_WS = " \t　"


def _fence_re():
    """正規コードブロックの型を lang_gate から引く(読めなければ None= 判定しない)。"""
    try:
        _llm = os.path.join(ROOT, "scripts", "llm")
        if _llm not in sys.path:
            sys.path.insert(0, _llm)
        from lang_gate import _MASK_PATTERNS
        return _MASK_PATTERNS[0]
    except Exception:
        return None


def _fence_spans(text):
    """```…``` の区間を返す。None= 判定できない(呼び側は素通しする)。"""
    pat = _fence_re()
    if pat is None:
        return None
    return [(m.start(), m.end()) for m in pat.finditer(text)]


def _already_escaped(text, pos):
    """その柵が既にバックスラッシュで逃がされているか(直前の連続 \\ が奇数個)。"""
    n = 0
    i = pos - 1
    while i >= 0 and text[i] == "\\":
        n += 1
        i -= 1
    return n % 2 == 1


def find_literal_runs(body):
    """「文字として書かれた柵」の区間 [(start, end), ...] を返す。判定だけ・直さない。

    None= 判定できない(lang_gate が読めない)= 呼び側は素通しする。
    """
    s = str(body or "")
    if "`" not in s:
        return []
    fences = _fence_spans(s)
    if fences is None:
        return None
    # ★インラインコードの**中身**に居る柵は触らない= `` ` `` / ` ``` `(柵を見せるための
    #   正しい書き方)の内側。囲みの柵そのもの(区間の端)は候補に残す。
    inner = [(a + n, e - n) for a, e, c in code_spans(s)
             for n in ((e - a - len(c)) // 2,)]
    out = []
    for m in _RUN_RE.finditer(s):
        a, b = m.start(), m.end()
        if any(fa <= a and b <= fb for fa, fb in fences):
            continue                       # 正規のコードブロックの中身/柵= 触らない
        if any(ia <= a and b <= ib for ia, ib in inner):
            continue                       # インラインコードの中身= 引用された柵
        if _already_escaped(s, a):
            continue
        prev = s[a - 1] if a > 0 else ""
        nxt = s[b] if b < len(s) else ""
        hit = False
        if prev in _QUOTE_OPEN and prev and nxt in _QUOTE_CLOSE and nxt:
            hit = True                     # ①「```」= 引用符に丸ごとくるまれている
        elif prev in _INLINE_WS and prev and nxt in _INLINE_WS and nxt:
            hit = True                     # ②中間の ` は= 前後が空白の孤立柵
        if hit:
            out.append((a, b))
    return out


def prose_swallowed(text):
    """コード扱いの区間のうち**地の文を飲んでいる**字数(改行か仮名/漢字を含む区間の合計)。

    ★この物差しが「余計なコードブロック」の実体だ= 短いコード片(`--list`)は0点、
      日本語や複数行を飲んだ塊だけが点になる。
    """
    n = 0
    for _, _, c in code_spans(text):
        if "\n" in c or _JP_RE.search(c):
            n += len(c)
    return n


def _swallowed(text):
    """コード扱いの区間の**総**字数。地の文でなくても増えたら採らない(第2の物差し)。

    ★これが要る実物= 柵そのものを見せるための二重柵の書き方(実便 1545697738899984394)。
      中身が記号だけなので `prose_swallowed` は動かないが、逃がすとコード箱の中に
      バックスラッシュが増えて**見た目が悪くなる**。総量で止める。
    """
    return sum(len(c) for _, _, c in code_spans(text))


def escape_literal_ticks(body):
    """文字として書かれた柵を逃がした本文と、逃がした個数を返す= (新しい本文, 件数)。

    ★候補(①②)を**まとめて逃がさない**= 1か所当てるたびに候補を取り直し、prose_swallowed が
      悪化しない時だけ採る。取り直しが要る理由は2つとも実測で分かった=
        ・柵を見せるための正しい書き方(二重柵でくるんだ引用)の内側は、前後が空白で②に見える。
          1か所ごとに数え直せば、その柵は「インラインコードの中身」として候補から外れる。
        ・壊れた便は対合がずれている= 先頭の1か所を逃がすまで、後ろの柵が誤って開いた
          巨大な区間の中に隠れて見えない。当て直して初めて表に出る。
      (台帳の実便3081件で悪化0を実測)
    """
    s = str(body or "")
    cur = s
    applied = 0
    for _ in range(_MAX_PASSES):
        runs = find_literal_runs(cur)
        if not runs:
            break
        picked = None
        p0, s0 = prose_swallowed(cur), _swallowed(cur)
        for a, b in runs:
            trial = cur[:a] + "\\`" * (b - a) + cur[b:]
            if prose_swallowed(trial) <= p0 and _swallowed(trial) <= s0:
                picked = trial
                break
        if picked is None:
            break
        cur = picked
        applied += 1
    return cur, applied


def literal_tick_backstop(body, tag="persona_send", quiet=False):
    """Discordへ出る本文の裸バッククォートを逃がす(送信口から呼ぶ入口)。

    ★例外は自分で飲んで原文を返す= ここで送信を殺さない。
    """
    try:
        out, n = escape_literal_ticks(body)
        if n and not quiet:
            print(f"[{tag}] ★地の文の裸バッククォート {n}か所を逃がした"
                  f"=対合がずれて地の文がコード扱いになるのを止める"
                  f"(起点=Chami msg 1551266364231000136)。", file=sys.stderr)
        return out
    except Exception as e:
        if not quiet:
            print(f"[{tag}] 裸バッククォート・ゲート不能({type(e).__name__})=素通し(fail-open)",
                  file=sys.stderr)
        return body


def code_spans(text):
    """Discord と同じ読み方で「コード扱いになる区間」を返す= [(start, end, 中身), ...]。

    ★検査と実測のための**読み取り専用**の道具(送信経路からは呼ばない)。
      CommonMark と同じ= n連の柵で開き、**ちょうど n 連**の柵で閉じる。逃がした柵(\\`)は数えない。
    """
    s = str(text or "")
    runs = [(m.start(), m.end(), m.end() - m.start())
            for m in _RUN_RE.finditer(s) if not _already_escaped(s, m.start())]
    out = []
    i = 0
    while i < len(runs):
        a, e, n = runs[i]
        j = i + 1
        while j < len(runs) and runs[j][2] != n:
            j += 1
        if j < len(runs):
            out.append((a, runs[j][1], s[e:runs[j][0]]))
            i = j + 1
        else:
            i += 1
    return out
