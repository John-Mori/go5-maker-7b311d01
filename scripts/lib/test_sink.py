#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「今、検査プロセスから呼ばれているか」の判定の**正本**(2026-09-06 イージス研究室)。

★なぜ1か所に集めるか(ORG-11= 表を2か所に持つと必ず片方が腐る):
  この判定は `gemini_usage.py`(課金の脈)と `invisible.py`(不可視文字の見張りの脈)の
  両方が要る。判定の規則(どの実行体名を検査とみなすか)を2か所に写すと、片方だけ
  直された時にもう片方が黙って古い規則で動き続ける。**規則はここだけに書く。**

★なぜ要るか(実測・2026-09-06):
  - `scripts/teian/test_body_bytes_regression.py` は urlopen だけ偽物にして本物の経路を
    走らせる正しい検査だが、その経路の使用量記録が **本番の課金台帳**へ "HTTP 429" を
    4行ずつ入れていた(09-06 の3回で12行)。
  - `scripts/discord/test_invisible.py` は1回走るごとに **本番の不可視文字台帳**へ2行
    入れていた。09-04 に台帳を作ってから溜まった16行は**全部が検査の行**= 本番の検出は0件。
  どちらも共通規律§4「見張っている脈を、見張り以外の手で更新するな」(C-054)だ。

★設計の向き(ここが肝):
  判定は **書く側**が自分でやる。検査側に「書くな」と申告させる作りにはしない
  = 人手の入口を要件にした機構は実測0件になる(申告し忘れた検査から汚れる)。
  そして判定は**狭く**取る。誤って「検査だ」と判定すると**本番の記録を取りこぼす**からだ
  (取りこぼしは静かに数字を減らす=課金判断を誤らせる)。名前が test の実行体だけを見る。
"""
import os
import sys


def under_test():
    """検査プロセスから呼ばれているなら True。★呼び出し側の申告に依存しない。

    見るのは3つだけ:
      1. 環境変数 GEMINI_USAGE_SINK_TEST=1 … 明示の逸らし(検査の入れ子や手動確認用)
      2. pytest が読み込まれている
      3. 実行体(sys.argv[0])の名前が test_ で始まる / _test.py で終わる / pytest
    ★ここを広げる時は「本番の記録を取りこぼす向きへ倒れる」ことを必ず思い出せ。
    """
    try:
        if os.environ.get("GEMINI_USAGE_SINK_TEST") == "1":
            return True
        if "pytest" in sys.modules:
            return True
        argv0 = os.path.basename((sys.argv[0] if sys.argv else "") or "").lower()
        return argv0.startswith("test_") or argv0.endswith("_test.py") or argv0 == "pytest"
    except Exception:
        return False


def sink_for(prod_path, suffix="_test"):
    """本番の台帳パスを渡すと、この呼び出しが書くべきパスを返す。

    検査プロセスなら `<名前>_test.<拡張子>`、本番プロセスならそのまま。
    ★台帳ごとに逸らし先を手書きさせない(手書きは必ずどれか1本が忘れられる)。
    """
    if not under_test():
        return prod_path
    base, ext = os.path.splitext(prod_path)
    return base + suffix + ext
