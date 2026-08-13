#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""毎朝の改修α(system-engineer=5秒動画メーカー本体)改修/再発の集計。

なぜ要るか= Chami依頼(2026-08-12 ad研究室)「毎朝8時に直近24時間の改修・再発・
依頼傾向を分析し、作成メカニズムの精度を上げ、必要に応じてskill化していく」。
まずは改修α1本に絞る(Chami補足 msg1537114294720794624・C-035=名指しを全体へ広げない)。

規律=
- ★台帳のtsを自前でパースしない。共有 scripts/lib/jsonl_store.py の
  ts_epoch()/read_jsonl() を通す(Zの6行が9時間ずれる・壊れ行が黙って消える穴を塞ぐ。
  イージス研究室 commit d16314b の指示)。
- ★貯め先は1本(記録先を2つ持たない・共通規律§4)= local/llm/kaizen_repair_analysis.jsonl。
- 実装はしない部門なので、これは「数字を出す道具」=自室の武器(C-019/C-027)。

出力= ①Chami向けmarkdownをstdout(毎朝便にそのまま流せる) ②貯め先へ日次1行。
定期トリガー(08:10)は基盤の領分=このパスをイージス研究室へ渡して登録してもらう(C-042)。
"""
import os
import sys
import json
import time
import argparse
import datetime
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))  # 5SecMovieMaker
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from lib.jsonl_store import read_jsonl, ts_epoch  # noqa: E402

CHANGE_LOG = os.path.join(ROOT, "local", "llm", "change_log.jsonl")
STORE = os.path.join(ROOT, "local", "llm", "kaizen_repair_analysis.jsonl")  # 貯め先1本

# 改修α=5秒動画メーカー本体。★deptの綴りが割れている(イージス研究室 実測):
#   system-engineer / system-engineer-alpha(2026-07-26の1行)= どちらも改修α。両方拾う。
#   ★system-engineer-b は改修部門β=別の部屋。入れない(C-035=Chamiが言ったのは改修α)。
DEPTS = ("system-engineer", "system-engineer-alpha")
DEPT_B = "system-engineer-b"  # 改修部門β(別部屋)=明示除外
DEPT_LABEL = "system-engineer"  # 貯め先の記録キー(従来互換)

# クラスタ= (表示名, [キーワード])。上から順に、最初に当たったものへ振る。
# ★増やす時はここへ1行。判定は change_log の「何」フィールド(日本語1文)に対する部分一致。
CLUSTERS = [
    ("投稿履歴/投稿導線", ["投稿履歴", "投稿導線", "投稿完了", "保存中", "drive保存",
                           "重複判定", "dupe", "公開日時", "投稿日", "導線2", "リビルド", "backfill"]),
    ("候補→作成/カテゴリ", ["候補", "AIカテゴリ", "applygenres", "floor", "ジャンル", "カテゴリ"]),
    ("ボタン/レイアウト幅", ["ボタン", "横幅", "width", "flex", "縦積み", "全幅", "レイアウト"]),
    ("アフィリンク/短縮", ["アフィリンク", "短縮url", "link-worker", "af_id", "計測短縮"]),
    ("プレビュー/描画", ["プレビュー", "描画", "座標", "canvas", "フォント", "黒帯"]),
    ("投稿本文/X・Bluesky", ["bluesky", "bsky", "facet", "投稿本文", "x投稿"]),
    ("GAS/記録シート", ["gas", "記録シート", "スプレッドシート", "refreshclicks", "コード.gs"]),
    # ==== 2026-08-13 追加(イージス研究室・Chami指示 ESC-kaizen-analyst-1537342631300829295)====
    # ★経緯= 90日窓352件のうち **116件(33%)が「その他」** に落ちていた(トトリ申告)。
    #   その116件を全文で読み直して型を起こしたのが下の10本。★既存7本より**後ろに置く**=
    #   既存の柱(投稿導線100/候補59/ボタン38)の数は動かさない(再現性を壊さない)。
    #   検査= scripts/kaizen/test_daily_repair_analysis.py(先に13件FAILを見てから入れた)。
    ("端末間同期/ドラフト", ["同期", "ドラフト", "下書き", "sync", "2台目", "端末間",
                             "r2", "kv", "pull", "union", "墓標"]),
    ("販促ラベル/セール札/割引表示", ["セール札", "販促ラベル", "価格ラベル", "割引", "%off",
                                      "%オフ", "定価", "drawdigits", "価格札", "¥価格", "総集編"]),
    ("ランキング/順位表示", ["ランキング", "順位", "renderrank", "ワースト", "総再生数"]),
    ("カレンダー/予約枠", ["カレンダー", "予約", "枠", "schedule", "投稿時刻"]),
    ("CI/版ずれ門番", ["ci", "門", "smoke", "check_", "版ずれ", "?v=", "バンプ", "テスト"]),
    ("iOS Safari表示崩れ/IDB無言死", ["ios safari", "真っ白", "idb", "bfcache", "タブ破棄",
                                       "表示崩れ", "グラデ", "モーダル"]),
    ("競合分析/YouTube統計", ["競合", "youtube統計", "フレーム", "comp_", "再生数スナップ", "計測窓"]),
    ("シート由来行の編集消失", ["シート由来", "historyhasedit", "_fromsheet", "sheet_edit",
                                "保存が巻き戻"]),
    ("計測値の整合(累計/デルタ)", ["デルタ", "累計", "負値", "クリック増分", "下限クランプ"]),
    ("基盤混入(改修αでない)", ["build_office", "daily_report", "黒板", "振り返り", "設計書化"]),
]

# ★「何」が空欄の行は「その他」に紛れさせない。分類器の穴ではなく**台帳への記入の穴**で、
#   直す相手が違う(90日窓で3件実在)。沈黙を可視化する=別ラベルで数える。
EMPTY_LABEL = "★「何」が空欄(台帳の穴)"


def classify(text):
    if not (text or "").strip():
        return EMPTY_LABEL
    t = text.lower()
    for label, kws in CLUSTERS:
        for kw in kws:
            if kw in t:
                return label
    return "その他"


def build(now, hours):
    since = now - hours * 3600
    rows, bad = read_jsonl(CHANGE_LOG)
    picked, undated, unknown_dept = [], 0, 0
    for r in rows:
        dept = r.get("dept")
        if dept == DEPT_B:
            continue  # 改修部門β=別部屋。改修αの集計には入れない
        if not dept:
            # dept欠落=どのフィルタにも掛からない。黙って0にせず別に数えて出す
            e = ts_epoch(r.get("ts"))
            if e is not None and since <= e <= now:
                unknown_dept += 1
            continue
        if dept not in DEPTS:
            continue
        e = ts_epoch(r.get("ts"))
        if e is None:
            undated += 1
            continue
        if since <= e <= now:
            picked.append(r)
    by_cluster = Counter(classify(r.get("何") or r.get("what") or "") for r in picked)
    return picked, by_cluster.most_common(), bad, undated, unknown_dept


def render_md(now, hours, picked, ranked, bad, undated, unknown_dept):
    to_d = datetime.datetime.fromtimestamp(now)
    from_d = datetime.datetime.fromtimestamp(now - hours * 3600)
    wd = "月火水木金土日"[to_d.weekday()]
    # ★件数は走らせた時刻で動く=窓の「いつからいつまで」を必ず併記(イージス研究室の指摘)
    span = (f"{from_d.month}/{from_d.day} {from_d.hour:02d}:{from_d.minute:02d}"
            f" 〜 {to_d.month}/{to_d.day}({wd}) {to_d.hour:02d}:{to_d.minute:02d} JST")
    total = len(picked)
    out = [f"◆改修α 直近{hours:.0f}h集計({span})= 本体改修 {total}件"]
    if ranked:
        top_label, top_n = ranked[0]
        for label, n in ranked:
            mark = "  ★最多=再発の芯" if (label == top_label and top_n >= 2) else ""
            out.append(f"- {label}: {n}件{mark}")
        if top_n >= 2:
            out.append(f"→ 作成メカニズムの精度不足の指し先=「{top_label}」({top_n}件)")
    else:
        out.append("- 対象なし(直近窓に改修αの記録なし)")
    if bad:
        out.append(f"※台帳に読めない行 {len(bad)}件=要手当て")
    if undated:
        out.append(f"※改修αだがts不明で除外 {undated}件")
    if unknown_dept:
        out.append(f"※dept欠落で改修α判定不能 {unknown_dept}件(窓内・別数え)")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--now", type=float, default=None, help="epoch秒。既定=現在時刻")
    ap.add_argument("--no-store", action="store_true", help="貯め先へ書かない(検証用)")
    args = ap.parse_args()

    now = args.now if args.now is not None else time.time()
    picked, ranked, bad, undated, unknown_dept = build(now, args.hours)
    md = render_md(now, args.hours, picked, ranked, bad, undated, unknown_dept)
    print(md)

    if not args.no_store:
        d = datetime.datetime.fromtimestamp(now)
        rec = {
            "ts": d.isoformat(timespec="seconds"),
            "window_h": args.hours,
            "dept": DEPT_LABEL,
            "depts": list(DEPTS),
            "total": len(picked),
            "by_cluster": dict(ranked),
            "top": (ranked[0][0] if ranked else None),
            "bad_lines": len(bad),
            "undated": undated,
            "unknown_dept": unknown_dept,
        }
        with open(STORE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
