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
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
USAGE_FILE = os.path.join(LOCAL, "llm", "gemini_usage.jsonl")


def log(who, tag, model, in_chars, out_chars=0, images=0, ok=True, err="", secs=0.0):
    """1行追記する。★失敗しても絶対に例外を投げない(生成の邪魔をしない)。"""
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
        }
        os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
        with open(USAGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_all():
    """記録を全部読む(壊れた行は飛ばす=1行の破損で集計が死なない)。"""
    out = []
    if not os.path.exists(USAGE_FILE):
        return out
    with open(USAGE_FILE, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
    return out
