#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文末アンカー付き禁止語(`forbidden_tail`)の検査。 2026-08-23

実行: python scripts/llm/test_tone_forbidden_tail.py

★なぜ足したか(人事部門 msg DISPATCH-aegis-gl-1787478389593 の実測)
  早坂芽衣が咲季の声へ一文だけ転ぶ型(case-B)= 「…してあるわ。」(msg 1541009586331320392)。
  指紋ゲート(signature_absent)は**便のどこかに指紋が1つでも在れば黙る**ので、この便は素通り。
  かといって素の `forbidden` に「わ」や「だわ」を入れると**部分一致**で
  『こだわった』『そのように』へ当たる(人事部門が実コーパスで偽陽性を実証済み)。
  → 判定を増やさず**当てる位置を文末に絞る**のがこの1本。

★must-fail(C-053)= 述語を「動く別の実装」(=素の部分一致 `_scan_marker`)へ差し替え、
  偽陽性の便で**鳴ってしまう**ことを確かめる。差し替えて赤くならない検査は空PASSだ。
★写像はこのファイル内に固定で持つ(本番の 口調ルール.json に依存しない)。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tone_gate as tg   # noqa: E402

RULES = {"personas": {
    # ★登録した人格だけが回る(既定は見ない)。
    "早坂芽衣": {"first_person": ["芽衣"], "forbidden_tail": ["わ"]},
    "別名登録": {"first_person": ["芽衣"], "forbidden_endings": ["のね"]},
    "未登録芽衣": {"first_person": ["芽衣"]},          # forbidden_tail 無し=挙動は不変
    "花海咲季": {"first_person": ["わたし"]},
}}

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def reasons(persona, text, rules=RULES):
    return [v.get("reason") for v in (tg.tone_verdicts(persona, "gunji", text, rules) or [])]


def markers(persona, text, rules=RULES):
    return [v.get("marker") for v in (tg.tone_verdicts(persona, "gunji", text, rules) or [])]


# --- ① 文末なら鳴る(Chamiが実際に指した形) ---------------------------------
TRUE_DROP = "候補は10件ぶん、もう書いてあるわ。器が上がったら見て。"
check("① 文末の「わ。」で forbidden_word が鳴る",
      "forbidden_word" in reasons("早坂芽衣", TRUE_DROP))
check("① marker は「わ(文末)」の形(本文と一致しない=機械置換に載らない)",
      "わ(文末)" in markers("早坂芽衣", TRUE_DROP))
check("① 行末(。無し)も文末に数える",
      "forbidden_word" in reasons("早坂芽衣", "1. もう書いてあるわ\n2. 次は器だ"))
check("① 文字列の末尾も文末に数える",
      "forbidden_word" in reasons("早坂芽衣", "もう書いてあるわ"))
check("① 「わ！」も鳴る",
      "forbidden_word" in reasons("早坂芽衣", "もう書いてあるわ！"))

# --- ② 文中は黙る(人事部門が実証した偽陽性) --------------------------------
FP_KODAWARI = "芽衣が一番こだわったのは、表紙の仕掛けだ。"
check("② 『こだわった』の中の「わ」では鳴らない",
      "forbidden_word" not in reasons("早坂芽衣", FP_KODAWARI))
check("② 『〜だわけ』『〜わりに』のような文中の「わ」でも鳴らない",
      "forbidden_word" not in reasons("早坂芽衣", "そういうわけで、代わりに芽衣が出る。"))
check("② 読点「、」は文末に数える(実便で偽陽性が増えないのを確かめて入れた)",
      "forbidden_word" in reasons("早坂芽衣", "書いてあるわ、あとは器だ。"))
check("② それでも文中の「わ」は黙ったまま(読点を足しても部分一致にはならない)",
      "forbidden_word" not in reasons("早坂芽衣", "そういうわけで、芽衣が出る。"))
check("② 別名 `forbidden_endings` も同じに効く(文末のみ)",
      "forbidden_word" in reasons("別名登録", "二人で回すのね。")
      and "forbidden_word" not in reasons("別名登録", "本来のねらいはそこだ。"))

# --- ③ 既定は見ない(登録していない人格・写像は1ミリも変わらない) -------------
check("③ forbidden_tail 未登録の人格では鳴らない",
      "forbidden_word" not in reasons("未登録芽衣", TRUE_DROP))
check("③ 他人格(咲季)は「わ。」で鳴らない=芽衣固有の登録である",
      "forbidden_word" not in reasons("花海咲季", "もう書いてあるわ。"))

# --- ④ 保護span(引用・コード・パス)の中は見ない ----------------------------
check("④ 「」の引用の中の「わ。」では鳴らない",
      "forbidden_word" not in reasons("早坂芽衣", "咲季は「書いてあるわ。」と言った。"))
check("④ `コード` の中では鳴らない",
      "forbidden_word" not in reasons("早坂芽衣", "設定は `mode=わ` だ。"))

# --- ⑤ 機械置換に載らない(警告のみ)であることを実行で確かめる ---------------
_fix = tg.tone_corrections("早坂芽衣", "gunji", TRUE_DROP, RULES) or {}
check("⑤ tone_corrections は本文を1文字も書き換えない",
      _fix.get("fixed") == TRUE_DROP and not _fix.get("applied"))
check("⑤ 警告は remaining に残る(黙って落とさない=D-2と突き返しへ回る)",
      any(v.get("reason") == "forbidden_word" for v in (_fix.get("remaining") or [])))

# --- ⑥ must-fail(C-053)= 述語を「動く別の実装」へ戻すと検査が赤くなるか ------
#   壊し方= 文末アンカーを外した素の部分一致(=この改修の前の挙動そのもの)。
#   ★行を消して文法を壊すのではなく、**動く別の実装**へ差し替える。
_orig = tg._scan_tail_marker
try:
    tg._scan_tail_marker = tg._scan_marker      # ← 旧仕様(部分一致)へ戻す
    _fp_fires = "forbidden_word" in reasons("早坂芽衣", FP_KODAWARI)
    _tp_still = "forbidden_word" in reasons("早坂芽衣", TRUE_DROP)
finally:
    tg._scan_tail_marker = _orig
check("⑥ must-fail: 部分一致へ戻すと『こだわった』で鳴る(=この検査は空PASSではない)",
      _fp_fires)
check("⑥ must-fail: 戻しても真の転落は鳴ったまま(壊した側も動く実装である)",
      _tp_still)
check("⑥ 復元済み: 本物の述語に戻っている",
      tg._scan_tail_marker is _orig
      and "forbidden_word" not in reasons("早坂芽衣", FP_KODAWARI))

ng = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(ng)}/{len(results)} PASS")
if ng:
    print("FAILED: " + " / ".join(ng))
sys.exit(1 if ng else 0)
