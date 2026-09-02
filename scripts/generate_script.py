#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_script.py — 5ch動画の台本ジェネレータ(改修α / モドリッチ発注
msg1544667374827872356・正本=🐧さん作成マニュアル マニュアル⑩)。

なぜ在るか:
  「5ch動画」事業(project_pivot-5ch-vtuber-manga)でAIが担うのは編集ではなく
  骨格生成。scrape_5ch.py が拾った勢いスレから、マニュアル指定の7ブロック
  台本(①タイトル〜⑦締め・約57秒)の"下書き"を機械で組む。人間(Chami)が
  YMM4で最終編集する前提の骨格であって、これ自体を無編集で投稿する完成品
  ではない(丸パクリ禁止=マニュアル⑧のNGそのもの)。

やること/やらないこと:
  - スレのレス(posts)から ">>N" 被参照数を「勢い」の代理指標にしてコメを
    順位付けするだけ。感情分類(インパクト/リアクション/ツッコミ)は自動
    判定できないので、順位を仮ラベルとして割り振る一次案止まり=人間の
    リライトが前提(マニュアル⑧「丸パクリ禁止」に合わせた設計)。
  - 画像は本文中のURL(imgur等)を拾って提示するだけで、鎖骨/生足の画像
    自体を判定する画像解析はしない(そのNGは人間の目視チェック向けに
    注記を出すだけ)。
  - NG語(マニュアル⑧)はテロップ化候補の文中で機械的に言い換える
    (おっぱい→OP / Xカップ→X杯)。

使い方:
  python scripts/generate_script.py --board streaming              # 最新日付・勢い1位
  python scripts/generate_script.py --board streaming --rank 2     # 勢い3位(0始まり)
  python scripts/generate_script.py --board streaming --key 1788100588
出力:
  local/scripts/<board>_<key>.md  (人間が読む台本ドラフト)
  local/scripts/<board>_<key>.json (同内容の構造化データ)
"""
import argparse
import glob
import json
import os
import re
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IN_DIR = os.path.join(ROOT, "local", "5ch")
OUT_DIR = os.path.join(ROOT, "local", "scripts")

# マニュアル⑧のNG語言い換え(露骨語→言い換え)。丸ごと弾かず、テロップに使える
# 形へ機械的に変換する。パターンは実例(おっぱい/Gカップ)から一般化しすぎず、
# 明示された語+「◯カップ」の規則的パターンだけに絞る(過剰検知を避ける)。
NG_LITERAL = {
    "おっぱい": "OP",
    "オッパイ": "OP",
    "おぱい": "OP",
}
_NG_CUP = re.compile(r"([A-Zａ-ｚa-z])\s*カップ")

# 画像URL抽出(imgur / pbs.twimg / i.imgur 等、拡張子つきの直リンクのみ)。
_IMG_URL = re.compile(r"https?://\S+?\.(?:jpe?g|png|gif|webp)", re.I)
# 被参照アンカー(">>123" 形式。全角>>も来るため両方拾う)
_ANCHOR = re.compile(r"(?:>>|＞＞)(\d+)")
# OPの規約テンプレ判定(!extend: や sage進行推奨など、板ルール文はコメ候補から除外)
_TEMPLATE_MARK = re.compile(r"!extend:|sage進行推奨|次スレは|VIPQ2_EXTDAT")

MIN_COMMENT_LEN = 6
# テロップに使う前提の「一言反応」上限。これを超える長文(告知/長い持論)は
# 反応集のスレコメとして不向きなので候補から外す(実データで長文広告が
# 被参照数の多さだけで上位に来る事故が実測されたための対策)。
MAX_COMMENT_LEN = 120


def ng_filter(text):
    """マニュアル⑧のNG語を言い換える。戻り値=(置換後テキスト, 置換した語のリスト)。"""
    hits = []
    out = text
    for word, repl in NG_LITERAL.items():
        if word in out:
            hits.append(f"{word}→{repl}")
            out = out.replace(word, repl)

    def _cup_sub(m):
        hits.append(f"{m.group(1)}カップ→{m.group(1)}杯")
        return f"{m.group(1)}杯"

    out = _NG_CUP.sub(_cup_sub, out)
    return out, hits


def extract_image_urls(text):
    return _IMG_URL.findall(text)


def is_template(index, text):
    if index == 0:
        return True  # レス1=OP。板ルール転記が大半でコメ候補にしない
    if _TEMPLATE_MARK.search(text):
        return True
    return False


def rank_comments(posts, top_n=12):
    """">>N" 被参照数を勢いの代理指標として、コメ候補を順位付けする。
    戻り値: [{"res": レス番号(1始まり), "text": 本文, "score": 被参照数,
              "images": [...]}]  score降順・同点は本文が長い方を先に。
    """
    anchor_count = {}
    for text in posts:
        for m in _ANCHOR.finditer(text):
            n = int(m.group(1))
            anchor_count[n] = anchor_count.get(n, 0) + 1

    candidates = []
    for i, text in enumerate(posts):
        res_no = i + 1
        if is_template(i, text):
            continue
        body = text.strip()
        if len(body) < MIN_COMMENT_LEN or len(body) > MAX_COMMENT_LEN:
            continue
        candidates.append({
            "res": res_no,
            "text": text.strip(),
            "score": anchor_count.get(res_no, 0),
            "images": extract_image_urls(text),
        })
    candidates.sort(key=lambda c: (c["score"], len(c["text"])), reverse=True)
    return candidates[:top_n]


def find_thread_files(board, date=None):
    if date:
        path = os.path.join(IN_DIR, f"threads_{board}_{date}.jsonl")
        if not os.path.exists(path):
            raise SystemExit(f"見つからない: {path}")
        return path
    cands = sorted(glob.glob(os.path.join(IN_DIR, f"threads_{board}_*.jsonl")))
    if not cands:
        raise SystemExit(f"{board} のデータが無い。先に scrape_5ch.py --board {board} を実行して。")
    return cands[-1]


def load_threads(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def pick_thread(threads, key=None, rank=0):
    if key:
        for t in threads:
            if t.get("key") == key:
                return t
        raise SystemExit(f"key={key} が見つからない")
    ordered = sorted(threads, key=lambda t: t.get("ikioi", 0), reverse=True)
    if rank >= len(ordered):
        raise SystemExit(f"rank={rank} が範囲外(スレ数={len(ordered)})")
    return ordered[rank]


def build_script(thread):
    posts = thread.get("posts", [])
    ranked = rank_comments(posts, top_n=12)

    title_raw = thread["title"]
    title_ng, title_hits = ng_filter(title_raw)

    def take(n):
        chunk = ranked[:n]
        del ranked[:n]
        out = []
        for c in chunk:
            body_ng, hits = ng_filter(c["text"])
            out.append({
                "res": c["res"],
                "text": body_ng,
                "ng_hits": hits,
                "images": c["images"],
            })
        return out

    block3 = take(5)   # メイン画像+スレコメ3〜5件
    block4 = take(3)   # 全体紹介+反応2〜3件
    block5 = take(2)   # サブピックアップ2件
    block6 = take(2)   # 番外ネタ1〜2件

    all_images = []
    for c in ranked + block3 + block4 + block5 + block6:
        all_images.extend(c.get("images", []) if isinstance(c, dict) else c["images"])

    script = {
        "source": {
            "board": thread["board"],
            "key": thread["key"],
            "url": thread["url"],
            "ikioi": thread["ikioi"],
            "res": thread["res"],
        },
        "title_raw": title_raw,
        "title_ng_hits": title_hits,
        "blocks": [
            {
                "no": 1, "name": "タイトル", "time": "0-2s",
                "note": "【朗報/悲報】+スレタイ要約(丸パクリ禁止・リライト必須)。ピンク太字・放射状背景",
                "draft_text": f"【悲報/朗報】{title_ng} www",
            },
            {
                "no": 2, "name": "導入", "time": "3-6s",
                "note": "スレ内容を一言",
                "draft_text": f"{title_ng}がこちら",
            },
            {
                "no": 3, "name": "メイン画像+スレコメ", "time": "6-20s",
                "note": "インパクト→リアクション→ツッコミ順(順位は代理指標=要リライト)",
                "comments": block3,
            },
            {
                "no": 4, "name": "全体紹介+反応", "time": "21-32s",
                "note": "集合/全体画像+反応コメ",
                "comments": block4,
            },
            {
                "no": 5, "name": "サブピックアップ", "time": "33-43s",
                "note": "別対象+反応コメ(名前あれば表示)",
                "comments": block5,
            },
            {
                "no": 6, "name": "番外ネタ", "time": "44-50s",
                "note": "脱線/比較+笑えるコメ",
                "comments": block6,
            },
            {
                "no": 7, "name": "締め", "time": "51-57s",
                "note": "社会的/文化的視点+ユーモアの一言(要人力執筆・自動生成なし)",
                "draft_text": "",
            },
        ],
        "image_candidates": sorted(set(all_images)),
        "ng_check_reminder": [
            "鎖骨/生足が見える画像は使用禁止(目視チェック必須・本ツールは画像解析していない)",
            "性的表現の直接語は機械置換済みだが、置換漏れが無いか目視で最終確認",
        ],
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
    }
    return script


def render_markdown(script):
    lines = []
    s = script["source"]
    lines.append(f"# 台本ドラフト: {script['title_raw']}")
    lines.append("")
    lines.append(f"- 板={s['board']} key={s['key']} 勢い={s['ikioi']}/日 レス数={s['res']}")
    lines.append(f"- 元スレ: {s['url']}")
    lines.append(f"- 生成: {script['generated_at']}")
    if script["title_ng_hits"]:
        lines.append(f"- タイトルNG置換: {', '.join(script['title_ng_hits'])}")
    lines.append("")
    CIRCLED = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤", 6: "⑥", 7: "⑦"}
    for b in script["blocks"]:
        mark = CIRCLED.get(b["no"], str(b["no"]))
        lines.append(f"## {mark}{b['name']}({b['time']})")
        lines.append(f"- {b['note']}")
        if "draft_text" in b:
            lines.append(f"- テロップ案: {b['draft_text']}" if b["draft_text"] else "- テロップ案: (人力執筆)")
        for c in b.get("comments", []):
            img = f" [画像:{c['images'][0]}]" if c["images"] else ""
            ng = f" (NG置換:{', '.join(c['ng_hits'])})" if c["ng_hits"] else ""
            lines.append(f"  - レス{c['res']}: {c['text']}{img}{ng}")
        lines.append("")
    lines.append("## 画像候補(本文中のURL・目視で鎖骨/生足チェック要)")
    for u in script["image_candidates"]:
        lines.append(f"- {u}")
    lines.append("")
    lines.append("## NGチェック")
    for r in script["ng_check_reminder"]:
        lines.append(f"- {r}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="5ch動画台本ジェネレータ(骨格ドラフト生成)")
    ap.add_argument("--board", required=True)
    ap.add_argument("--date", default=None)
    ap.add_argument("--key", default=None, help="スレkeyを直接指定(未指定なら勢い順)")
    ap.add_argument("--rank", type=int, default=0, help="勢い順位(0始まり・--key未指定時)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    path = find_thread_files(args.board, args.date)
    threads = load_threads(path)
    thread = pick_thread(threads, key=args.key, rank=args.rank)

    script = build_script(thread)

    os.makedirs(OUT_DIR, exist_ok=True)
    base = args.out or os.path.join(OUT_DIR, f"{thread['board']}_{thread['key']}")
    md_path = base + ".md"
    json_path = base + ".json"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(script))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    print(f"[i] 入力元: {path}")
    print(f"[i] 対象スレ: {thread['title']} (key={thread['key']} 勢い={thread['ikioi']})")
    print(f"[done] {md_path}")
    print(f"[done] {json_path}")


if __name__ == "__main__":
    main()
