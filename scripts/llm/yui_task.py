#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yui_task.py — ローカルLLM「優依」に定型作業を裏で回させてClaudeのトークンを節約する道具。

なぜ在るか(Chami指示 msg 1544837976561946745「両方試してみて」・learning-coach室):
  優依(8B)は文脈読解に天井があるので、要約(畳んで捨てる)・選別(足切り)のような
  「優依が消したら見えない」仕事は渡さない。渡すのは失敗しても損失が出ない2つだけ:
    draft = 下書き(叩き台)。Claude/Chamiが必ず書き直す前提の頭出し一本。外しても害ゼロ。
    tag   = 仕分け(消さず札だけ)。★足切り禁止=1行ずつ元を丸ごと残し、tagsだけ足す。
            候補は1件も落とさない(落とせない=このスクリプトが構造で保証する)。

使い方:
  # 下書き: お題を渡してたたき台を一本もらう
  python scripts/llm/yui_task.py draft --brief "白銀ノエルの水着回、漫画風ショートのX訴求コメント"
  python scripts/llm/yui_task.py draft --brief-file お題.txt

  # 仕分け: 5chスレのjsonlに札を貼る(足切りせず全件出力)
  python scripts/llm/yui_task.py tag --in local/5ch/threads_streaming_2026-09-03.jsonl --limit 20
  # → local/5ch/threads_..._tagged.jsonl (元の全行 + "tags" 付き) を書く

前提: Ollama起動中(http://localhost:11434)。既定モデル= 優依の現行(abliterated版)。
"""
import argparse
import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
# 優依の現行モデル(local_responder.py と同じ・差し替え時はここも合わせる)
DEFAULT_MODEL = "hf.co/mradermacher/Josiefied-Qwen3-8B-abliterated-v1-GGUF:Q4_K_M"


def _chat(system, user, model, num_ctx=8192, temperature=0.4):
    payload = {"model": model, "stream": False, "think": False,
               "keep_alive": "30m",
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "options": {"temperature": temperature, "num_ctx": num_ctx}}
    req = urllib.request.Request("http://localhost:11434/api/chat",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    msg = (d.get("message") or {}).get("content", "")
    if "</think>" in msg:
        msg = msg.split("</think>", 1)[1]
    return msg.strip()


def do_draft(brief, model):
    system = (
        "あなたはローカルの下書き係『優依』です。渡されたお題に対して、"
        "SNS(X/YouTube)向けの短い訴求コメントの『たたき台』を作ります。"
        "これは最終文ではなく、司令塔(Claude)や運用者が必ず書き直す前提の頭出しです。"
        "出力ルール: (1)日本語 (2)3案まで、各案は1〜2文で短く (3)煽りすぎ・嘘の煽りは避ける "
        "(4)説明・前置き・言い訳は書かず、案だけを『1. 2. 3.』で並べる。/no_think"
    )
    user = f"お題: {brief}\n\n上のお題で、短い訴求コメントのたたき台を3案。"
    return _chat(system, user, model, temperature=0.6)


TAG_SYSTEM = (
    "あなたはローカルの仕分け係『優依』です。5chスレッド1件の情報を読み、札(tags)を貼るだけの仕事です。"
    "★あなたは候補を捨てたり足切りしたりしません。判断は司令塔(Claude)がします。あなたは目印を付けるだけ。"
    "次のJSON1個だけを出力してください(前置き・説明・コードブロック記法は禁止):"
    '{"box":"ホロ|にじ|その他|不明", "topic":"内容を5〜12字で", '
    '"manga_fit":"高|中|低", "note":"一言(任意・無ければ空文字)"}'
    " box=どの箱(ホロライブ/にじさんじ/その他/判断不能は不明)。"
    " manga_fit=漫画風ショートのネタに向くか(物語性・感情の起伏があるほど高)。/no_think"
)


def do_tag_one(title, res, ikioi, model):
    user = f"タイトル: {title}\nレス数: {res}\n勢い: {ikioi}"
    raw = _chat(TAG_SYSTEM, user, model, temperature=0.2)
    # JSON抽出(モデルが前後に何か付けても中括弧だけ拾う)
    try:
        s = raw[raw.index("{"): raw.rindex("}") + 1]
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {"box": "不明", "topic": "", "manga_fit": "低", "note": "優依の出力を解釈できず(要人手)", "_raw": raw[:200]}


def do_tag(in_path, limit, model):
    with open(in_path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()]
    out_path = in_path.rsplit(".jsonl", 1)[0] + "_tagged.jsonl"
    kept = 0
    tagged = 0
    with open(out_path, "w", encoding="utf-8") as w:
        for i, ln in enumerate(lines):
            try:
                item = json.loads(ln)
            except Exception:
                # ★壊れた行も落とさない=そのまま通す(構造で候補を守る)
                w.write(ln if ln.endswith("\n") else ln + "\n")
                kept += 1
                continue
            if limit and i < limit:
                item["tags"] = do_tag_one(item.get("title", ""), item.get("res", ""),
                                          item.get("ikioi", ""), model)
                tagged += 1
            # limit を超えた行も★捨てずに素通し(tagsは付けないだけ)
            w.write(json.dumps(item, ensure_ascii=False) + "\n")
            kept += 1
    return out_path, kept, tagged


LOG_SYSTEM = (
    "あなたは基盤ログの一次トリアージ係『優依』です。ログ1行を読み、程度の札を貼るだけです。"
    "★あなたは行を消したり要約で畳んだりしません。分類の目印を付けるだけ。最終判断は司令塔(Claude)がします。"
    "次のJSON1個だけを出力(前置き・説明・コードブロック記法は禁止):"
    '{"level":"情報|警告|要対応", "kind":"種類を5〜10字で", "one":"一言(任意)"}'
    " level: 正常稼働・okは情報。retry/遅延/一時失敗は警告。停止(stopped/dead)・例外・error・失敗継続は要対応。"
    " ★迷ったら重い側へ倒す(見落としより過検出が安全)。/no_think"
)


def do_log_one(line, model):
    raw = _chat(LOG_SYSTEM, f"ログ行: {line}", model, temperature=0.1)
    try:
        s = raw[raw.index("{"): raw.rindex("}") + 1]
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # ★解釈できない時は fail-open=要対応へ倒す(沈黙より過検出)
    return {"level": "要対応", "kind": "優依が解釈不能", "one": raw[:80]}


def do_log(in_path, tail, model):
    with open(in_path, "r", encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]
    if tail:
        lines = lines[-tail:]
    out_path = os.path.join(ROOT, "local", "_work", "yui_logtri.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    counts = {"情報": 0, "警告": 0, "要対応": 0}
    flagged = []
    with open(out_path, "w", encoding="utf-8") as w:
        for ln in lines:  # ★全行を回す=1行も飛ばさない
            tg = do_log_one(ln, model)
            lv = tg.get("level", "要対応")
            counts[lv] = counts.get(lv, 0) + 1
            if lv != "情報":
                flagged.append((lv, tg.get("kind", ""), ln[:90]))
            w.write(json.dumps({"line": ln, "tri": tg}, ensure_ascii=False) + "\n")
    return out_path, counts, flagged


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    d = sub.add_parser("draft")
    d.add_argument("--brief", default="")
    d.add_argument("--brief-file", default="")
    d.add_argument("--model", default=DEFAULT_MODEL)

    t = sub.add_parser("tag")
    t.add_argument("--in", dest="in_path", required=True)
    t.add_argument("--limit", type=int, default=20, help="札を貼る先頭N件(0=全件・残りは素通し)")
    t.add_argument("--model", default=DEFAULT_MODEL)

    g = sub.add_parser("log")
    g.add_argument("--in", dest="in_path", required=True)
    g.add_argument("--tail", type=int, default=20, help="末尾N行だけトリアージ(0=全行)")
    g.add_argument("--model", default=DEFAULT_MODEL)

    a = ap.parse_args()
    if a.mode == "draft":
        brief = a.brief
        if a.brief_file:
            with open(a.brief_file, "r", encoding="utf-8") as f:
                brief = f.read().strip()
        if not brief:
            print("お題(--brief か --brief-file)が空です。", file=sys.stderr)
            sys.exit(1)
        print(do_draft(brief, a.model))
    elif a.mode == "tag":
        out, kept, tagged = do_tag(a.in_path, a.limit, a.model)
        print(f"[仕分け完了] 出力={out}\n入力{kept}件を全件保持(落とし=0)・うち{tagged}件に札を貼った。")
    elif a.mode == "log":
        out, counts, flagged = do_log(a.in_path, a.tail, a.model)
        total = sum(counts.values())
        print(f"[ログ一次トリアージ] 出力={out}")
        print(f"{total}行を全行保持(落とし=0)。情報{counts['情報']}/警告{counts['警告']}/要対応{counts['要対応']}")
        if flagged:
            print("--- 拾い上げ(情報以外) ---")
            for lv, kind, ln in flagged:
                print(f"[{lv}] {kind}: {ln}")
        else:
            print("拾い上げ0=異常なし(全て情報)。")


if __name__ == "__main__":
    main()
