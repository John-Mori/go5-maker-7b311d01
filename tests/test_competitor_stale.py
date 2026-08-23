# -*- coding: utf-8 -*-
"""競合日次の鮮度ゲート(stale_reason / main の STALE_EXIT)の must-fail テスト。

狙い= PC側日次集計が「今日の競合_日次行が無い」を赤にできることを、実行で1回通す
     (AD研究室モドリッチ依頼 2026-08-23・silent green 再発止め C-038)。
GASのsnapshotDateはJST(Session.getScriptTimeZone→Asia/Tokyo)・PCのtodayもJST=時差ずれ無し。
daemonは08:00起動=04:00のrunCompetitorDaily後=「本日分未着(lag=1)」は真に上流が書けていないサイン。

must-fail の勘所:
 - 「今日の行が無い(昨日どまり=lag=1)=赤」は"新しい網"。旧しきい値 lag>=2 のコードでは
   ここが None(緑)を返すので**このテストは落ちる**=網が効いていない状態を機械で暴く。
 - 外へ出る手(GAS取得=fetch)だけ偽物にし、判定(stale_reason)と分岐(main の return)は本物のまま回す。
走らせ方: python tests/test_competitor_stale.py
"""
import os, sys, datetime, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "analysis"))
import competitor_daily as C

PASS = FAIL = 0


def chk(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name)


def dstr(days_ago):
    return (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()


# --- 1) 純関数 stale_reason: 今日=緑 / 昨日以前・空・不正=赤 ---
chk("今日の行が有る(lag=0)=緑(None)", C.stale_reason(dstr(0)) is None)
chk("今日の行が無い(昨日どまり lag=1)=赤", bool(C.stale_reason(dstr(1))))   # ★新しい網。旧 lag>=2 では緑で落ちる
chk("2日遅れ=赤", bool(C.stale_reason(dstr(2))))
chk("5日遅れ=赤", bool(C.stale_reason(dstr(5))))
chk("空=赤", bool(C.stale_reason("")))
chk("?=赤", bool(C.stale_reason("?")))
chk("不正な日付=赤", bool(C.stale_reason("not-a-date")))


# --- 2) main() 実行: 外部の手(fetch)だけ偽物・判定と分岐は本物 ---
def fake_titles(snap):
    return {"titles": [
        {"title": "テスト題名A", "videoId": "vidA", "channelName": "chX",
         "speed": 100, "subscriberCount": 1000, "snapshotDate": snap},
        {"title": "テスト題名B？", "videoId": "vidB", "channelName": "chX",
         "speed": 50, "subscriberCount": 1000, "snapshotDate": snap},
    ]}


# 赤: 上流が古い → main は集計へ進まず STALE_EXIT を返す(ファイル書き込み前に return)
C.fetch = lambda: fake_titles(dstr(3))
sys.argv = ["competitor_daily.py"]        # --emit を含めない=stderr へ理由を出して rc を返す
chk("main: 上流が古いと rc=STALE_EXIT(3)=赤", (C.main() or 0) == C.STALE_EXIT)

# 緑: 上流が今日 → ゲートを越えて集計まで進む。出力先は temp へ退避し実データを汚さない
with tempfile.TemporaryDirectory() as td:
    C.OUTDIR = os.path.join(td, "competitor_daily")
    C.LEDGER = os.path.join(td, "ledger.jsonl")
    C.METRICS = os.path.join(td, "metrics.jsonl")
    C.fetch = lambda: fake_titles(dstr(0))
    sys.argv = ["competitor_daily.py"]
    chk("main: 今日の行が有ると集計へ進む(rc=0)=緑", (C.main() or 0) == 0)
    chk("緑のとき当日レポート(.md)が書かれる",
        os.path.exists(os.path.join(C.OUTDIR, dstr(0) + ".md")))

print("---")
print("PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
