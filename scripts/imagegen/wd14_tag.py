#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像 → プロンプト(タグ列)の橋渡し。部屋「プロンプト変換と学習」の中身。

Chami原文(研究室HQ経由・2026-09-16)=
  「ここの部屋に画像を貼ったらコードブロックでその画像を表現するためのプロンプト変換をする部屋にして欲しい」
  「もちろん、環境作りはClaudeにお願いして、以後はローカルLLMが橋渡ししてくれればいい」

裁定(研究室HQ・同日)で縛ってあること:
  ・`D:\\local-ai\\` は**読み取り専用**。橋渡しのコードはこちら(5SecMovieMaker)に置く。
  ・**外部API・有料APIは使わない**。全部この機械の中で閉じる(WD14はCPU実行=VRAM0)。
  ・**新規導入はするな**。だから当室のPythonへ onnxruntime を入れず、
    向こうの `.venv` へ `_wd14_runner.py` を渡して走らせる(下の TAGGER_PY)。
  ・**引き金は「画像の添付そのもの」**。合図語をこちらで発明しない。
  ・この部屋は LoRAカテゴリの合図規律(「生成依頼」)の**対象外**=
    `scripts/imagegen/rooms.py` の ROOMS には**入れない**。入れると
    `cue_required()`/`_image_depts()` の両方が拾ってしまう(C-035=名指しを広げない)。

実測(2026-09-16・local/attachments/1549517543079804996_0.png):
  モデル読み込み込みで **1.9秒**・タグ9件。「数秒で返る」は満たしている。
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

# 向こう(読み取り専用)の実体。パスを2か所に持たないため、ここが唯一の正本。
TOOL_DIR = r"D:\local-ai\tools\wd14"
TAGGER_PY = os.path.join(TOOL_DIR, ".venv", "Scripts", "python.exe")
MODEL_ONNX = os.path.join(TOOL_DIR, "model", "model.onnx")
RUNNER = os.path.join(HERE, "_wd14_runner.py")

# しきい値。WD14の慣例値(general 0.35 / character 0.85)から動かしていない。
GENERAL_TH = 0.35
CHARACTER_TH = 0.85
TIMEOUT_SEC = 180
MAX_IMAGES = 4          # 1便で読むのはここまで(連投で機械を占有させない)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


def is_image_path(p):
    return str(p or "").lower().endswith(IMAGE_EXT)


def available():
    """タガーが今この機械で走れるか。走れない時に**黙って空を返さない**ための判定。"""
    return os.path.exists(TAGGER_PY) and os.path.exists(MODEL_ONNX) and os.path.exists(RUNNER)


def tag_files(paths, general=GENERAL_TH, character=CHARACTER_TH, timeout=TIMEOUT_SEC):
    """画像ファイル(ローカルパス)を読んで [{path, general, character, rating, scores}] を返す。

    失敗は例外にせず `{"ok": False, "error": ...}` で返す= 部屋の応答を止めない
    (この部屋の失敗は「返事が来ない」ではなく「理由が出る」であるべき)。
    """
    files = [p for p in (paths or []) if is_image_path(p) and os.path.exists(p)][:MAX_IMAGES]
    if not files:
        return {"ok": False, "error": "no_image", "items": []}
    if not available():
        return {"ok": False, "error": "tagger_missing", "items": []}
    argv = [TAGGER_PY, RUNNER, "--general", str(general), "--character", str(character)] + files
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "items": []}
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()[-1:] or [""]
        return {"ok": False, "error": f"tagger_rc={r.returncode}: {tail[0][:200]}", "items": []}
    try:
        got = json.loads((r.stdout or "").strip())
    except ValueError:
        return {"ok": False, "error": "bad_json", "items": []}
    return got if isinstance(got, dict) else {"ok": False, "error": "bad_json", "items": []}


def prompt_of(item):
    """1枚分のタグ列 → そのままコピペできる1行のプロンプト。

    ・キャラ名(category 4)を先頭に置く= 画風より先に「誰か」を決めるのがプロンプトの慣例。
    ・`_` は空白へ開く。ただし顔文字(`^_^` など)は開くと壊れるので、英数字に挟まれた
      `_` だけを対象にする。
    ・rating(sensitive など)は**入れない**= あれは分類であってプロンプトではない。
    """
    import re
    tags = list(item.get("character") or []) + list(item.get("general") or [])
    out = []
    for t in tags:
        t = str(t)
        if not re.fullmatch(r"[0-9a-zA-Z_]+", t):
            out.append(t)          # 顔文字・記号タグは触らない
        else:
            out.append(t.replace("_", " "))
    return ", ".join(out)


def format_reply(result, names=None):
    """Discordへ出す本文。コードブロックの中は**プロンプトだけ**(そのまま貼れる形)。"""
    if not result.get("ok"):
        why = {
            "no_image": "画像が見つからなかった(添付の保存に失敗したかも)。",
            "tagger_missing": f"タガーの実体が見つからない({TOOL_DIR})。",
            "timeout": "タグ付けが時間切れになった。",
            "bad_json": "タガーの出力を読めなかった。",
        }.get(result.get("error"), f"タグ付けに失敗した({result.get('error')})。")
        return "うまくいかなかった: " + why
    items = result.get("items") or []
    if not items:
        return "うまくいかなかった: タグが1件も出なかった。"
    names = names or []
    chunks = []
    for i, it in enumerate(items):
        label = names[i] if i < len(names) else os.path.basename(it.get("path") or "")
        head = f"**{label}**  (rating: {it.get('rating') or '?'})" if len(items) > 1 \
            else f"(rating: {it.get('rating') or '?'})"
        body = prompt_of(it).replace("```", "'''")     # 念のため囲いを壊させない
        chunks.append(head + "\n```\n" + body + "\n```")
    return "\n".join(chunks)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="画像→プロンプト(タグ列)。手で確かめる用。")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--general", type=float, default=GENERAL_TH)
    ap.add_argument("--character", type=float, default=CHARACTER_TH)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    got = tag_files(a.paths, a.general, a.character)
    if a.json:
        print(json.dumps(got, ensure_ascii=False, indent=1))
    else:
        print(format_reply(got))
    return 0 if got.get("ok") else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
