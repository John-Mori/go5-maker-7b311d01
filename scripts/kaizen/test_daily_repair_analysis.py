#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_repair_analysis.classify() の分類テスト(純関数)。

なぜ要るか= 2026-08-13 実測で 90日窓 352件のうち **116件(33%)が「その他」** に落ちていた。
「その他」は共通項が見えていない穴で、ここが厚いと"見えている再発"しかskill化できない
(トトリの申告・Chami指示 ESC-kaizen-analyst-1537342631300829295「ここを潰すようにして」)。

★このテストは**先に落ちるのを見てから**置いた(その他=116の時点で 10件FAIL)。
走らせ方= python scripts/kaizen/test_daily_repair_analysis.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from daily_repair_analysis import classify  # noqa: E402

# (実際に change_log に在った「何」の文, 期待クラスタ)
CASES = [
    # --- 既存3本の柱。ここが動いたら回帰=先に疑うのはこちら ---
    ("投稿履歴のリビルドで公開日時が飛ぶ件を修正", "投稿履歴/投稿導線"),
    ("候補→作成のAIカテゴリ判定を一本化(applyGenres)", "候補→作成/カテゴリ"),
    ("投稿ボタンが横幅を食って縦積みになる件をflexで修正", "ボタン/レイアウト幅"),
    # --- 2026-08-13 追加分(その他116件の実測から) ---
    ("ドラフトの動画本体を2台目でもDL可能に(R2 on-demand取り寄せ)", "端末間同期/ドラフト"),
    ("宵桜(acc2)のセール札価格PNGを焼き込み文字拡大版へ差し替え", "販促ラベル/セール札/割引表示"),
    ("ランキングにワースト再生数モード(少ない順)を切替追加", "ランキング/順位表示"),
    ("カレンダーの今日スクロール不発と本命★の縦ズレを修正", "カレンダー/予約枠"),
    ("CIにnodeテスト全実行の門を追加(恒久-4)", "CI/版ずれ門番"),
    ("core/idb-store.jsのget()を源でfail-open(reject時null)に。iOS Safari", "iOS Safari表示崩れ/IDB無言死"),
    ("競合代表フレーム取得を日次自動化(go5_comp_frames_daily)", "競合分析/YouTube統計"),
    ("シート由来行の編集が一瞬反映後に消える再発を修正", "シート由来行の編集消失"),
    ("クリック/再生の週・今日・昨日デルタの負値を0下限へ丸める", "計測値の整合(累計/デルタ)"),
    ("build_office.pyにキューDB可視化と所有権黒板セクションを追加", "基盤混入(改修αでない)"),
    # --- 台帳の穴。空欄を「その他」に紛れさせない(沈黙の可視化) ---
    ("", "★「何」が空欄(台帳の穴)"),
    ("   ", "★「何」が空欄(台帳の穴)"),
    (None, "★「何」が空欄(台帳の穴)"),
]


def main():
    ng = 0
    for text, expect in CASES:
        got = classify(text)
        if got != expect:
            ng += 1
            print(f"FAIL: {(text or '(空)')[:36]!r}\n      期待={expect} / 実際={got}")
    total = len(CASES)
    if ng:
        print(f"\nNG {ng}/{total}")
        return 1
    print(f"OK {total}/{total} 全PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
