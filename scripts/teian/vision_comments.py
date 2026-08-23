#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vision_comments.py — 提案決定ページの候補JSONに、挿入画像から生成した④コメント3択を埋める(改修α)。

これは"配管"だけを担う=絵→3択の型/NG語/枠の正本は copy-director が持つ:
  docs/departments/copy-director/vision_3択生成プロンプト仕様.md §4
このツールはそのファイルの §4 プロンプト本文を読み込んで Gemini vision(C-017)へ渡す
=コピー部門がプロンプトを直せば次の実行から効く(型が要調整なら早坂芽衣へ・ツール改修不要)。

入力  = local/teian/candidates_YYYY-MM-DD.json(product-scout/candidates_json.py の出力・comments 空)
出力  = 同スキーマで comments[]={n,text,aim,type,chars,two_line} を埋めた JSON
描画するのは text だけ(KouhoTeian.html)。aim/type/chars/two_line は winning 学習用の付帯。

fail-open: 1候補で vision が失敗しても comments は [] のまま残す
           =ページは「コメント未生成・手入力してください」のフォールバックを出す(可用性優先)。

使い方:
  python scripts/teian/vision_comments.py                       # 最新の候補JSONを in-place で試作(先頭3件)
  python scripts/teian/vision_comments.py --limit 0             # 全候補
  python scripts/teian/vision_comments.py --in <path> --out <path>
  python scripts/teian/vision_comments.py --dry-run             # API を叩かず送信内容だけ確認
前提: Gemini APIキー = local/gemini_api_key.txt(または環境変数 GEMINI_API_KEY)。ask_gemini と共通。
"""
import argparse
import base64
import glob
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
TEIAN_DIR = os.path.join(ROOT, "local", "teian")
KEY_FILE = os.path.join(ROOT, "local", "gemini_api_key.txt")
PROMPT_SPEC = os.path.join(ROOT, "docs", "departments", "copy-director",
                           "vision_3択生成プロンプト仕様.md")

# vision対応の flash 系(安く軽く→確認済みの控え)。ask_gemini と同じ思想でフォールバック。
DEFAULT_MODELS = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
]
# §3 の直接誘導語(1つでも入っていたら不合格=1回だけ生成し直す)。
NG_PHRASES = ("続きは", "概要欄", "見せられない", "続きが気になる方", "リンクから")
# 全角括弧は自動で半角へ寄せる(§3・機械的に直せる違反)。
ZEN2HAN = {"（": "(", "）": ")"}


def read_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def load_prompt():
    """copy-director の仕様書 §4 の ``` フェンス内(vision へ渡すプロンプト本文)を正本として読む。"""
    with open(PROMPT_SPEC, "r", encoding="utf-8") as f:
        md = f.read()
    # 「## 4.」以降で最初に現れる ```...``` を抜く。
    after = md.split("## 4.", 1)
    if len(after) < 2:
        raise RuntimeError(f"プロンプト仕様に §4 が見つからない: {PROMPT_SPEC}")
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", after[1], re.S)
    if not m:
        raise RuntimeError(f"§4 のコードフェンス(プロンプト本文)が見つからない: {PROMPT_SPEC}")
    return m.group(1).strip()


def latest_candidates():
    # ★正規名 candidates_YYYY-MM-DD.json だけを最新候補にする。candidates_*.vision-test.json 等の
    #   変種を掴むと、その隣に synopsis_* サイドカーが無く「あらすじ永久に無」で静かに死ぬため除外する
    #   (テスト固定を使いたい時は --in で明示)。
    canon = re.compile(r"^candidates_\d{4}-\d{2}-\d{2}\.json$")
    files = sorted(f for f in glob.glob(os.path.join(TEIAN_DIR, "candidates_*.json"))
                   if canon.match(os.path.basename(f)))
    if not files:
        raise RuntimeError(f"候補JSONが無い: {TEIAN_DIR}/candidates_YYYY-MM-DD.json")
    return files[-1]


def load_synopsis(inp):
    """候補JSONと同ディレクトリの synopsis_<date>.json(product-scoutが置くPC専用サイドカー)を読み
    {cid: あらすじ本文 or null} を返す。★本文は配信JSON(candidates_*.json)には載っていない=過激本文を
    client面へ流さないため、ここでvisionへ渡すためだけに読む(docへ書き戻さない)。無い/壊れは {} =
    従来どおり絵のみで続行(fail-open・必須依存にしない・回帰ゼロ)。"""
    base = os.path.basename(inp)
    if "candidates_" not in base:
        return {}
    side = os.path.join(os.path.dirname(os.path.abspath(inp)),
                        base.replace("candidates_", "synopsis_", 1))
    if not os.path.exists(side):
        return {}
    try:
        with open(side, "r", encoding="utf-8") as f:
            d = json.load(f)
        syn = d.get("synopsis")
        return syn if isinstance(syn, dict) else {}
    except Exception as e:
        print(f"  [synopsis] 読めず {side}: {e}(絵のみで続行)", file=sys.stderr)
        return {}


def mime_of(url, data):
    u = url.lower()
    if u.endswith(".png"):
        return "image/png"
    if u.endswith(".webp"):
        return "image/webp"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/jpeg"


def fetch_image(url, timeout=30):
    """挿入画像を1枚取得。失敗は None(その画像だけ落とす=fail-open)。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (teian-vision)",
            "Referer": "https://www.dmm.co.jp/",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if not data:
            return None
        return {"mime_type": mime_of(url, data), "data": base64.b64encode(data).decode("ascii")}
    except Exception as e:
        print(f"  [img] 取得失敗 {url} : {e}", file=sys.stderr)
        return None


def call_vision(prompt, image_parts, title, synopsis, key, models, timeout=180):
    """1候補ぶんの画像+プロンプトを投げて生JSON文字列を返す(候補が無ければ '')。
    synopsis は取得できた時だけ §4 プロンプトへ渡す任意メタ(vision仕様§1.5=画像＋あらすじ／失敗なら絵のみ)。"""
    parts = [{"text": prompt}]
    if title:
        parts.append({"text": f"\n【任意メタ】作品タイトル: {title}"})
    if synopsis:
        parts.append({"text": f"\n【任意メタ】あらすじ(解釈材料・題名/煽りに直接使わない): {synopsis}"})
    for ip in image_parts:
        parts.append({"inline_data": ip})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    last_err = None
    for model in models:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + model + ":generateContent?key=" + key)
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            try:
                txt = d["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception:
                txt = ""   # 安全フィルタ等で候補なし
            print(f"  [vision] {model} で応答", file=sys.stderr)
            return txt
        except urllib.error.HTTPError as e:
            last_err = f"{model} HTTP {e.code}"
            if e.code in (400, 404, 429):
                print(f"  [{model}] {e.code}→次のモデルへ", file=sys.stderr)
                continue
            if e.code == 403:
                raise RuntimeError(f"Gemini認証/権限エラー({model} HTTP 403)") from None
            print(f"  [{model}] HTTP {e.code}→次のモデルへ", file=sys.stderr)
            continue
        except Exception as e:
            last_err = f"{model}: {e}"
            print(f"  [{model}] {e}→次のモデルへ", file=sys.stderr)
            continue
    raise RuntimeError(f"全モデルで失敗(最後: {last_err})")


def sanitize_text(t):
    t = (t or "").strip()
    for z, h in ZEN2HAN.items():
        t = t.replace(z, h)
    return t


def has_ng(t):
    return any(p in t for p in NG_PHRASES)


MIN_COMMENTS = 3
MAX_COMMENTS = 3  # ★Chami訂正(2026-08-23・msg 1541032124641972304)=先の5択化(msg 1541009586331320392)は取り下げ。3択のまま据え置き。


def parse_comments(raw):
    """vision の生JSONを comments[] に正規化。3案・text必須・NG語なしを満たさなければ None(=要再生成)。"""
    if not raw:
        return None
    # ```json フェンスが混ざっても拾えるように
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    arr = obj.get("comments") if isinstance(obj, dict) else obj
    if not isinstance(arr, list) or len(arr) < MIN_COMMENTS:
        return None
    out = []
    for i, c in enumerate(arr[:MAX_COMMENTS]):
        if not isinstance(c, dict):
            return None
        text = sanitize_text(c.get("text"))
        if not text or has_ng(text):
            return None
        # chars = 改行記号 '/' を除いた表示文字数
        chars = len(text.replace("/", "").replace("\n", ""))
        out.append({
            "n": i + 1,
            "text": text,
            "aim": (c.get("aim") or "").strip(),
            "type": (c.get("type") or "").strip(),
            "chars": chars,
            "two_line": bool(c.get("two_line")) or ("/" in text),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=None, help="候補JSON(既定=最新)")
    ap.add_argument("--out", dest="out", default=None, help="出力(既定=in-place)")
    ap.add_argument("--limit", type=int, default=3, help="埋める候補数(0=全部・既定3=試作)")
    ap.add_argument("--images", type=int, default=4, help="1候補に渡す画像枚数の上限")
    ap.add_argument("--model", default=None, help="モデル固定(既定=フォールバック)")
    ap.add_argument("--dry-run", action="store_true", help="APIを叩かず送信内容だけ表示")
    ap.add_argument("--force", action="store_true", help="既に comments が有る候補も上書き")
    args = ap.parse_args()

    inp = args.inp or latest_candidates()
    out = args.out or inp
    with open(inp, "r", encoding="utf-8") as f:
        doc = json.load(f)
    cands = doc.get("candidates") or []
    prompt = load_prompt()
    syn_map = load_synopsis(inp)   # {cid: 本文 or null}・無ければ {}(絵のみ)
    models = [args.model] if args.model else list(DEFAULT_MODELS)

    key = "" if args.dry_run else read_key()
    if not args.dry_run and not key:
        print("GeminiのAPIキーが未設定(local/gemini_api_key.txt か GEMINI_API_KEY)", file=sys.stderr)
        sys.exit(2)

    filled = failed = skipped = syn_used = 0
    processed = 0
    for c in cands:
        if args.limit and processed >= args.limit:
            break
        imgs = c.get("images") or []
        if not imgs:
            skipped += 1
            continue
        if c.get("comments") and not args.force:
            skipped += 1
            continue
        processed += 1
        title = c.get("title") or ""
        synopsis = ""
        raw_syn = syn_map.get(c.get("cid"))
        if isinstance(raw_syn, str) and raw_syn.strip():
            synopsis = raw_syn.strip()[:1500]   # 保険で上限。取得できた時だけ渡す
            syn_used += 1
        print(f"[cand {c.get('id')}] {title[:24]} imgs={len(imgs)} あらすじ={'有' if synopsis else '無'}",
              file=sys.stderr)

        if args.dry_run:
            print(f"  (dry-run) 画像{min(len(imgs), args.images)}枚 + §4プロンプト{len(prompt)}字"
                  f" + あらすじ{len(synopsis)}字 を送信予定")
            continue

        parts = []
        for u in imgs[:args.images]:
            ip = fetch_image(u)
            if ip:
                parts.append(ip)
        if not parts:
            print("  画像を1枚も取得できず=fail-open(comments空のまま)", file=sys.stderr)
            failed += 1
            continue

        got = None
        for attempt in range(2):   # NG/形式不良は1回だけ生成し直す(§6・同型リトライ2回まで)
            try:
                raw = call_vision(prompt, parts, title, synopsis, key, models)
            except Exception as e:
                print(f"  vision 呼び出し失敗: {e}", file=sys.stderr)
                break
            got = parse_comments(raw)
            if got:
                break
            print(f"  出力が3案/NG語/形式で不合格→再生成({attempt + 1}/2)", file=sys.stderr)
            time.sleep(1)
        if got:
            c["comments"] = got
            filled += 1
            for cm in got:
                print(f"    {cm['n']}. {cm['text']}  [{cm['aim']}/{cm['type']}/{cm['chars']}字]")
        else:
            failed += 1   # comments は [] のまま(fail-open)

    if not args.dry_run:
        doc.setdefault("vision", {})
        doc["vision"] = {
            "generated_by": "system-engineer/scripts/teian/vision_comments.py",
            "prompt_source": "docs/departments/copy-director/vision_3択生成プロンプト仕様.md §4",
            "filled": filled, "failed": failed, "skipped": skipped,
            "synopsis_used": syn_used,   # あらすじを渡せた候補数(本文はサイドカーのみ・docへ載せない)
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"\nwrote {out}\n埋めた {filled} / 失敗(空のまま) {failed} / 対象外 {skipped}"
              f" / あらすじ添付 {syn_used}")


if __name__ == "__main__":
    main()
