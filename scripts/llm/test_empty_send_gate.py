# -*- coding: utf-8 -*-
"""空便ガード(`sendable_blocks`)の検査。`python scripts/llm/test_empty_send_gate.py` で直接走る。

なぜ要るか(2026-09-03 炎上・Chamiが :enjoh: を押した実物):
  データ整理部門で **本文が名乗りタグだけの便**がDiscordへ出た。
  実物= `local/llm/send_audit.jsonl:253`
    {"ts":"2026-09-03T02:58:58","persona":"田中琴葉","status":"204","chars":6,"head":"[田中琴葉]"}
  = 6文字= `[田中琴葉]` そのもの。Chamiの「保留で。優先度低。」という**返事の要らない
  打ち切りの指示**に対して、部屋のセッションが言うことが無いまま名乗りだけを返し、
  それが1文字も止められずに表へ出た。内容の無い一次ackは沈黙より悪い(共通規律§2)。

  経路= `split_persona_blocks` は名乗りを解決したあと本文が空になると
  **fail-open で生の文字列を返す**(5913行「落とした結果が空= 落とさず従来どおり出す」)。
  その fail-open 自体は「前置きだけが中身だった」便を沈黙させないための正しい守りだが、
  **中身が名乗りしか無い便**まで素通しになっていた。送信ループ(8221行〜)は
  `_part` をそのまま body ファイルへ書いており、**空かどうかを一度も見ていない**。

★この検査が守る不変条件:
  ①名乗りタグだけ / 空白だけの本文は**送らない**(表に出さない)
  ②中身が1文字でも在るブロックは**1文字も削らない**(沈黙を作らない= fail-open の向きは維持)
  ③複数人格の便は**残ったブロックだけ**を順序どおり送る
  ④名簿で引けないタグ(`[検証]` 等)は名乗りではない= **本文として送る**(取り違えない)

★must-fail= 「strip して空かだけ」を見る変異体(=オタコンの原案の素朴版)では
  実物 `[田中琴葉]` が素通りすることを、同じ表明で確かめる。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as dd  # noqa: E402

FAIL = []


def ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAIL.append(msg)


# データ整理部門の名簿(実物と同じ3人)。resolve は「通用する正式名 or None」を返す約束。
ROSTER = ("オタコン", "田中琴葉", "紫雲清夏")


def resolve(nm):
    n = str(nm or "").strip()
    return n if n in ROSTER else None


def main():
    print("== ①空の本文は送らない ==")
    # ★実物そのもの= split の fail-open が生文字列で返した形((None, 生text))。
    ok(dd.sendable_blocks([(None, "[田中琴葉]")], resolve) == [],
       "実物 send_audit:253 の `[田中琴葉]`(6文字)は1通も送らない")
    ok(dd.sendable_blocks([("田中琴葉", "")], resolve) == [],
       "名義は解けたが本文が空= 送らない")
    ok(dd.sendable_blocks([("田中琴葉", "   \n\n\t ")], resolve) == [],
       "空白と改行だけ= 送らない")
    ok(dd.sendable_blocks([("田中琴葉", "[田中琴葉]\n\n[田中琴葉]")], resolve) == [],
       "名乗りが2行あっても中身が無ければ送らない")

    print("== ②中身が在るブロックは1文字も削らない(沈黙を作らない) ==")
    body = "うん、この炎上、原因が見えたよ。\n\n[保留]という文字列も本文だ。"
    got = dd.sendable_blocks([("オタコン", body)], resolve)
    ok(got == [("オタコン", body)], "本文はそのまま(改行も丸括弧も1文字も触らない)")
    ok(dd.sendable_blocks([("田中琴葉", "[田中琴葉] 了解")], resolve)
       == [("田中琴葉", "[田中琴葉] 了解")],
       "同じ行に中身が続く名乗りは**中身が在る**= 送る")
    ok(dd.sendable_blocks([(None, "了解")], resolve) == [(None, "了解")],
       "名義未解決でも中身が在れば送る(既定人格の名義で出る従来どおり)")

    print("== ③複数ブロックは残った分だけを順序どおり ==")
    ok(dd.sendable_blocks([("オタコン", "中身あり"), ("田中琴葉", "")], resolve)
       == [("オタコン", "中身あり")],
       "空のブロックだけ落ちる")
    ok(dd.sendable_blocks([("オタコン", ""), ("田中琴葉", "後ろだけ中身")], resolve)
       == [("田中琴葉", "後ろだけ中身")],
       "先頭が空でも後ろは生き残る")
    ok(dd.sendable_blocks([("オタコン", "一"), ("田中琴葉", "二"), ("紫雲清夏", "三")], resolve)
       == [("オタコン", "一"), ("田中琴葉", "二"), ("紫雲清夏", "三")],
       "全部中身が在れば順序ごとそのまま")
    ok(dd.sendable_blocks([("オタコン", "[オタコン]"), ("田中琴葉", "  ")], resolve) == [],
       "全ブロックが空= 1通も送らない(=返信そのものを出さない)")

    print("== ④名簿で引けないタグは名乗りではない= 本文として送る ==")
    ok(dd.sendable_blocks([(None, "[検証]")], resolve) == [(None, "[検証]")],
       "`[検証]` は名簿に無い= ただの本文。勝手に消さない")
    ok(dd.sendable_blocks([(None, "[田中琴葉]")], lambda nm: None) == [(None, "[田中琴葉]")],
       "resolve が誰も引けない部屋では落とさない(取り違えるより残す=fail-open)")
    ok(dd.sendable_blocks([("田中琴葉", "[田中琴葉]")], None) == [],
       "resolve 無しでも、ブロックの名義と同じ名乗りだけなら空と分かる")

    print("== ⑤入力を壊さない・例外を投げない ==")
    src = [("オタコン", "中身")]
    dd.sendable_blocks(src, resolve)
    ok(src == [("オタコン", "中身")], "渡された _blocks を破壊しない")
    ok(dd.sendable_blocks([], resolve) == [], "空リストは空リスト")
    ok(dd.sendable_blocks([("オタコン", None)], resolve) == [], "本文 None でも落ちない")

    print("== ⑥must-fail(動く別の実装= strip して空かだけを見る素朴版) ==")

    def mutant(blocks, resolve=None):
        return [(w, p) for (w, p) in (blocks or []) if str(p or "").strip()]

    ok(mutant([(None, "[田中琴葉]")], resolve) == [(None, "[田中琴葉]")]
       and dd.sendable_blocks([(None, "[田中琴葉]")], resolve) == [],
       "素朴版は実物 `[田中琴葉]` を素通しする(本物は止める)")
    ok(mutant([("オタコン", "中身")], resolve) == [("オタコン", "中身")]
       and dd.sendable_blocks([("オタコン", "中身")], resolve) == [("オタコン", "中身")],
       "素朴版も本物も、中身の在る便は同じに通す(変異体は**動く別の実装**である)")

    print("\n== %d件 FAIL ==" % len(FAIL) if FAIL else "\n== 全てPASS ==")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
