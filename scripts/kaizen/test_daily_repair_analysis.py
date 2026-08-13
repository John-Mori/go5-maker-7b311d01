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
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))   # …/5SecMovieMaker
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
from daily_repair_analysis import (classify, build, render_md,   # noqa: E402
                                   LEGACY_TS_SOURCE)

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


# ==== 2026-08-14 追加(イージス研究室)= 毎朝出る「※ts不明で除外」の切り分け ====
# なぜ要るか= 実測で毎朝の便に `※改修αだがts不明で除外 2件` が出続けていた。中身は
#   7/29の履歴2行(`ts_source=self(機構導入前・未検証)`)だけで、**永久に0にならない**。
#   24hの窓の報告に16日前の履歴が「除外」と並ぶ=読む側には今日こぼれたように見える。
# ★ここは classify と違い**実行で通す**(共通規律§3=文字列一致は検査ではない)。
#   外へ出る手(読む台帳)だけ差し替え、判定と分岐は本物のまま build() を回す。
import time                                                    # noqa: E402
import datetime                                                # noqa: E402

_JST = datetime.timezone(datetime.timedelta(hours=9))


def _row(ts, extra=None):
    r = {"ts": ts, "dept": "system-engineer", "何": "候補→作成のカテゴリ判定を修正",
         "なぜ": "検査用", "触った": "app.js", "commit": "dummy"}
    r.update(extra or {})
    return r


def _ledger(rows):
    fd, p = tempfile.mkstemp(prefix="repairwin_", suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def build_cases():
    """(名前, 判定) のリストを返す。"""
    out = []
    now = time.time()
    in_win = datetime.datetime.fromtimestamp(now - 3600, _JST).isoformat(timespec="seconds")

    # 機構導入前の履歴(実物と同じ形)= 本文から消す。ただし数は残す
    p = _ledger([_row(in_win),
                 _row("2026-07-29T", {"ts_source": LEGACY_TS_SOURCE}),
                 _row("2026-07-29", {"ts_source": LEGACY_TS_SOURCE})])
    picked, ranked, bad, undated, unk, legacy = build(now, 24.0, path=p)
    md = render_md(now, 24.0, picked, ranked, bad, undated, unk)
    out.append(("窓内の1件は拾う", len(picked) == 1))
    out.append(("★機構導入前の読めないts 2件は undated に数えない", undated == 0))
    out.append(("★その2件は undated_legacy として残る(黙って捨てない)", legacy == 2))
    out.append(("★毎朝の本文に『ts が読めず除外』の※行が出ない", "読めず除外" not in md))
    os.unlink(p)

    # 機構導入**後**に書かれた読めない ts= 新しい穴。従来どおり本文へ出す
    p = _ledger([_row(in_win), _row("2026-08-14T", {"ts_source": "machine"})])
    picked, ranked, bad, undated, unk, legacy = build(now, 24.0, path=p)
    md = render_md(now, 24.0, picked, ranked, bad, undated, unk)
    out.append(("印の無い読めないtsは undated に数える", undated == 1))
    out.append(("★新しい穴は本文へ出る", "★新しい穴" in md))
    out.append(("それは legacy に混ぜない", legacy == 0))
    os.unlink(p)

    # 回帰= 改修部門βは入れない / dept欠落は別数え(既存の振る舞いを動かしていない)
    p = _ledger([_row(in_win), _row(in_win, {"dept": "system-engineer-b"}),
                 _row(in_win, {"dept": None})])
    picked, ranked, bad, undated, unk, legacy = build(now, 24.0, path=p)
    out.append(("回帰: 改修部門βは集計に入らない", len(picked) == 1))
    out.append(("回帰: dept欠落は unknown_dept で別数え", unk == 1))
    os.unlink(p)

    # ★綴りの正本合わせ= session_relay が印を変えたらここで落ちる(黙ってすり抜けない)
    try:
        import session_relay as SR
        out.append(("★印の綴りが session_relay.CHANGE_TS_LEGACY と一致",
                    SR.CHANGE_TS_LEGACY == LEGACY_TS_SOURCE))
    except Exception as e:                                     # noqa: BLE001
        out.append((f"session_relay を読めない({type(e).__name__})", False))
    return out


def main():
    ng = 0
    for text, expect in CASES:
        got = classify(text)
        if got != expect:
            ng += 1
            print(f"FAIL: {(text or '(空)')[:36]!r}\n      期待={expect} / 実際={got}")
    extra = build_cases()
    for name, ok in extra:
        if not ok:
            ng += 1
            print(f"FAIL: {name}")
    total = len(CASES) + len(extra)
    if ng:
        print(f"\nNG {ng}/{total}")
        return 1
    print(f"OK {total}/{total} 全PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
