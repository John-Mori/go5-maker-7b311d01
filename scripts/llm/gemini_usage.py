#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Geminiの使用量を1呼び出し1行で記録する(2026-08-18 研究室HQ・Chami「1週間流して測ってから」)。

なぜ在るか:
  Chamiが「API側に課金して月2000円つけたらClaude側は助かるか」と聞いた(msg 1538949280876724276)。
  ★測っていない数字を語らないので、まず**実際に何をどれだけGeminiへ流したか**を1週間貯める。
  課金の判断はその数字でやる(枯れていない枠に払うのを避ける)。

設計:
  - **追記のみ**。既存行は書き換えない。壊れても生成側を巻き込まない(例外は握りつぶす=fail-open)。
  - 記録先は1本 `local/llm/gemini_usage.jsonl` だけ(記録先を2つ持たない)。
  - 本文そのものは残さない(長くなる・機微が混じる)。**長さと結果だけ**を数える。

1行の形:
  {"ts","who","tag","model","in_chars","out_chars","images","ok","err","secs"}
    who   = "behop" | "homin"     どちらの束か(資格情報を跨がない設計の確認にも使う)
    tag   = 用途ラベル(例 "cli" / "comp_frames" / "responder")。何に効いたかを後で分ける軸
    model = 実際に生成に成功した(または最後に試した)モデル名
    ok    = True/False、err = "HTTP 429" 等
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
USAGE_FILE = os.path.join(LOCAL, "llm", "gemini_usage.jsonl")
# ★2026-09-06 イージス研究室: 検査プロセスが書いた行の退避先(本番台帳と分ける)。
TEST_USAGE_FILE = os.path.join(LOCAL, "llm", "gemini_usage_test.jsonl")


def _under_test():
    """検査プロセスから呼ばれているかを、呼び出し側の申告なしで判定する。

    ★なぜ在るか(2026-09-06 イージス研究室・実測):
      `scripts/teian/test_body_bytes_regression.py` は urlopen だけを偽物にして
      call_vision を**本物のまま**走らせる正しい検査だが、本物の経路には _usage() が
      入っている= 検査1回につき "HTTP 429" の行が4本、**本番の課金台帳へ**入っていた
      (09-06 の3回で12行)。この台帳は「429の段数」で課金の是非を判定する脈だ
      = 共通規律§4「見張っている脈を、見張り以外の手で更新するな」(C-054)。
      ★検査側に「書くな」と申告させる作りにはしない= 人手の入口を要件にした機構は
      実測0件になる。**書く側(ここ)が自分で判定して逸らす。**
    ★偽陽性は本番の行を取りこぼす向きなので、判定は狭く取る(名前が test の実行体だけ)。"""
    if os.environ.get("GEMINI_USAGE_SINK_TEST") == "1":
        return True
    if "pytest" in sys.modules:
        return True
    argv0 = os.path.basename((sys.argv[0] if sys.argv else "") or "").lower()
    return argv0.startswith("test_") or argv0.endswith("_test.py") or argv0 == "pytest"


def sink_file():
    """この呼び出しの記録先を返す(本番 or 検査退避)。"""
    return TEST_USAGE_FILE if _under_test() else USAGE_FILE


def log(who, tag, model, in_chars, out_chars=0, images=0, ok=True, err="", secs=0.0, err_detail=""):
    """1行追記する。★失敗しても絶対に例外を投げない(生成の邪魔をしない)。

    err_detail: 2026-09-06 ad研究室指摘=err は複数の読み手(gemini_usage_report.py)が
      「短い定型文(HTTP 429 等)」を前提に完全一致キー集計/文字列countしている脈。
      本文入りの長い err を流すとその読み手が壊れる(共通規律§3「見張っている脈を、
      見張り以外の手で更新するな」)。だから **err はこれまでどおり短いまま据え置き**、
      HTTPエラー本文などの詳細情報は別欄 err_detail へ入れる(呼び出し元は任意・既定は空)。"""
    try:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
            "who": who,
            "tag": tag or "",
            "model": model or "",
            "in_chars": int(in_chars or 0),
            "out_chars": int(out_chars or 0),
            "images": int(images or 0),
            "ok": bool(ok),
            "err": err or "",
            "secs": round(float(secs or 0.0), 2),
            "err_detail": err_detail or "",
        }
        path = sink_file()
        if path is not USAGE_FILE and path != USAGE_FILE:
            rec["test"] = True      # 退避先でも「検査の行」だと分かる形で残す(消さない)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_all(path=None):
    """記録を全部読む(壊れた行は飛ばす=1行の破損で集計が死なない)。

    ★既定は sink_file()= **自分が書いた先を読む**(書きと読みの先を揃える)。
      検査プロセスなら退避先、本番プロセスなら本番台帳。
      本番台帳を名指しで読みたい時は read_all(gemini_usage.USAGE_FILE)。"""
    path = path or sink_file()
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
    return out
