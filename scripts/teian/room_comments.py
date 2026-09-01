#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""room_comments.py — 提案決定ページの候補JSONに、挿入画像から生成した room_comments
(=三笘薫と早坂芽衣の"推し文"解説)を埋める(改修α)。vision_comments.py の鏡写し。

これは"配管"だけを担う=声/型の正本は別に在る:
  型   = docs/departments/copy-director/room_comments生成プロンプト仕様.md §4
  声   = 00_AI-HQ/departments/hr/characters/mitoma.md・mei.md の「★声の型」節
このツールは §4 プロンプト本文＋両人格の声の型を Gemini vision(C-017)へ渡す
=コピー部門が型を、人事部門が声を直せば次の実行から効く(ツール改修不要)。

room_comments は「Chami専用の使い捨てpitch(公開されない)」=④comments(確定物)とは別物:
  ④comments      → vision_comments.py(大タイトル3択・Chamiが選び焼く確定物)
  room_comments  → このツール(三笘/芽衣が推すか語る・使い捨て・新cidだけ自動生成)

入力  = local/teian/candidates_YYYY-MM-DD.json(④comments は生成済みでも空でも可)
出力  = 同スキーマで room_comments={mitoma, main:{by,text}} を埋めた JSON

持続化(§6)= fill-empty-only。既に room_comments が埋まっている cid は温存し上書きしない
             (Chamiが手で直した1件も守る)。空(新規cid)だけ生成する。--force で全上書き。

fail-open: 1候補で vision が失敗しても room_comments は無いまま残す(可用性優先)。

使い方:
  python scripts/teian/room_comments.py                # 最新の候補JSONの「空だけ」in-place で埋める
  python scripts/teian/room_comments.py --limit 3      # 先頭3件だけ(試作)
  python scripts/teian/room_comments.py --in <path> --out <path>
  python scripts/teian/room_comments.py --dry-run      # API を叩かず送信内容だけ確認
  python scripts/teian/room_comments.py --force        # 既存 room_comments も再生成(声の刷新用・要Go)
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
HQ_ROOT = os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ"))
TEIAN_DIR = os.path.join(ROOT, "local", "teian")
KEY_FILE = os.path.join(ROOT, "local", "gemini_api_key.txt")
PROMPT_SPEC = os.path.join(ROOT, "docs", "departments", "copy-director",
                           "room_comments生成プロンプト仕様.md")
# 声の正本=characterfile(HQリポ・公開repoへ写さない=実行時に読むだけ)。
CHARS = os.path.join(HQ_ROOT, "departments", "hr", "characters")

# vision対応の flash 系(vision_comments と同じ思想でフォールバック)。
DEFAULT_MODELS = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
]
# 全角括弧は自動で半角へ寄せる(型§4「半角括弧のみ」・機械的に直せる違反)。
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
    after = md.split("## 4.", 1)
    if len(after) < 2:
        raise RuntimeError(f"プロンプト仕様に §4 が見つからない: {PROMPT_SPEC}")
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", after[1], re.S)
    if not m:
        raise RuntimeError(f"§4 のコードフェンス(プロンプト本文)が見つからない: {PROMPT_SPEC}")
    return m.group(1).strip()


def load_voice(fname):
    """characterfile の「## ★声の型」節本文を返す(声の正本=characterfile)。無ければ ''。
    ★HQリポの中身は公開repoへ写さない=ここで読むのは vision へ渡すためだけ(docへ書き戻さない)。"""
    path = os.path.join(CHARS, fname)
    if not os.path.exists(path):
        print(f"  [声] characterfile が無い {path}(声の型なしで続行)", file=sys.stderr)
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            md = f.read()
    except Exception as e:
        print(f"  [声] 読めず {path}: {e}(声の型なしで続行)", file=sys.stderr)
        return ""
    m = re.search(r"##\s*★?\s*声の型[^\n]*\n(.*?)(?=\n##\s|\Z)", md, re.S)
    return m.group(1).strip() if m else ""


def build_full_prompt(prompt):
    """§4プロンプトの前後に、三笘/芽衣の characterfile『声の型』を添える(型§4の指示)。"""
    voice_mi = load_voice("mitoma.md")
    voice_me = load_voice("mei.md")
    if not (voice_mi or voice_me):
        return prompt
    head = ("【声の正本=characterfile『声の型』(型より優先。ここへ寄せる)】\n"
            "◆三笘薫(mitoma):\n" + (voice_mi or "(声の型 未取得)") + "\n\n"
            "◆早坂芽衣(mei):\n" + (voice_me or "(声の型 未取得)") + "\n\n"
            "──────────\n")
    tail = ("\n──────────\n★最後にもう一度=三笘は「俺」で締めは「〜よ」か短い言い切り"
            "(「〜だ。」の角を出さない)、芽衣は「芽衣」で母音を伸ばし「〜と思うんだ〜！」+💕。")
    return head + prompt + tail


def latest_candidates():
    canon = re.compile(r"^candidates_\d{4}-\d{2}-\d{2}\.json$")
    files = sorted(f for f in glob.glob(os.path.join(TEIAN_DIR, "candidates_*.json"))
                   if canon.match(os.path.basename(f)))
    if not files:
        raise RuntimeError(f"候補JSONが無い: {TEIAN_DIR}/candidates_YYYY-MM-DD.json")
    return files[-1]


def load_synopsis(inp):
    """候補JSONと同ディレクトリの synopsis_<date>.json(product-scoutのPC専用サイドカー)を読み
    {cid: あらすじ本文 or null} を返す。過激本文は配信JSONへ載せない=vision へ渡すためだけ。
    無い/壊れは {}=絵のみで続行(fail-open)。vision_comments.py と同作法。"""
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
            "User-Agent": "Mozilla/5.0 (teian-room)",
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


def call_vision(prompt, image_parts, title, synopsis, comments, metrics, key, models, timeout=180):
    """1候補ぶんの画像+プロンプト+メタ(タイトル/あらすじ/④comments/指標)を投げて生JSON文字列を返す。
    ④comments と metrics は type§4 の材料(番号参照・販売数など)=取れた時だけ渡す。"""
    parts = [{"text": prompt}]
    if title:
        parts.append({"text": f"\n【任意メタ】作品タイトル: {title}"})
    if synopsis:
        parts.append({"text": f"\n【任意メタ】あらすじ(解釈材料・実名や露骨語に使わない): {synopsis}"})
    if comments:
        lines = "\n".join(f"  {c.get('n', i + 1)}. {c.get('text', '')}"
                          for i, c in enumerate(comments))
        parts.append({"text": f"\n【生成済みの大タイトル3択(番号で参照可)】\n{lines}"})
    if metrics:
        parts.append({"text": f"\n【指標(与えられた値だけ使う・無い数字は作らない)】"
                              f"{json.dumps(metrics, ensure_ascii=False)}"})
    for ip in image_parts:
        parts.append({"inline_data": ip})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.85,
            # ★2.5/3.x flash は思考トークン(thoughtsTokenCount≈1700)を maxOutputTokens から食う。
            #   512だと本文が出る前に尽きて {"  で切れる。出力は短いが枠は広く取る(実測STOPに2048必要)。
            "maxOutputTokens": 2048,
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


def parse_room(raw):
    """vision の生JSONを room_comments に正規化。mitoma と main.text の両方が要る(片方でも欠けたら None=要再生成)。"""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    mi = sanitize_text(obj.get("mitoma"))
    main = obj.get("main")
    if isinstance(main, dict):
        me = sanitize_text(main.get("text"))
        by = (main.get("by") or "早坂芽衣").strip() or "早坂芽衣"
    else:
        me = sanitize_text(main)
        by = "早坂芽衣"
    if not mi or not me:
        return None
    return {"mitoma": mi, "main": {"by": by, "text": me}}


def _rc_ok(rc):
    """既存 room_comments が「埋まっている」か(run_daily_teian.snapshot と同判定)。"""
    if not isinstance(rc, dict) or not rc.get("mitoma"):
        return False
    main = rc.get("main")
    return bool(main.get("text")) if isinstance(main, dict) else bool(main)


def _merge_targets(doc):
    """candidates と ready_library を1本の対象リストに束ねる。cidで重複排除(candidates優先)し、
    score降順=KouhoTeianの表示順に揃える(Chami『ランキングの上から出して』)。要素は doc 内の
    オブジェクト参照そのもの=ここへ room_comments を書けば doc に反映される。"""
    rows = list(doc.get("candidates") or []) + list(doc.get("ready_library") or [])
    seen = set()
    uniq = []
    for c in rows:
        cid = c.get("cid")
        if cid and cid in seen:
            continue
        if cid:
            seen.add(cid)
        uniq.append(c)
    uniq.sort(key=lambda c: (c.get("metrics") or {}).get("score") or 0, reverse=True)
    return uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=None, help="候補JSON(既定=最新)")
    ap.add_argument("--out", dest="out", default=None, help="出力(既定=in-place)")
    ap.add_argument("--limit", type=int, default=0, help="埋める候補数(0=全部・既定)")
    ap.add_argument("--images", type=int, default=4, help="1候補に渡す画像枚数の上限")
    ap.add_argument("--model", default=None, help="モデル固定(既定=フォールバック)")
    ap.add_argument("--dry-run", action="store_true", help="APIを叩かず送信内容だけ表示")
    ap.add_argument("--force", action="store_true",
                    help="既に room_comments が有る候補も上書き(声の刷新用・§6=要Go)")
    args = ap.parse_args()

    inp = args.inp or latest_candidates()
    out = args.out or inp
    with open(inp, "r", encoding="utf-8") as f:
        doc = json.load(f)
    cands = _merge_targets(doc)   # candidates + ready_library をscore降順で(readyも軍議を付ける)
    prompt = build_full_prompt(load_prompt())
    syn_map = load_synopsis(inp)
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
        imgs = c.get("vision_images") or c.get("images") or []
        if not imgs:
            skipped += 1
            continue
        if _rc_ok(c.get("room_comments")) and not args.force:
            skipped += 1   # §6 fill-empty-only=既存の手当を温存
            continue
        processed += 1
        title = c.get("title") or ""
        synopsis = ""
        raw_syn = syn_map.get(c.get("cid"))
        if isinstance(raw_syn, str) and raw_syn.strip():
            synopsis = raw_syn.strip()[:1500]
            syn_used += 1
        print(f"[cand {c.get('id')}] {title[:24]} imgs={len(imgs)} あらすじ={'有' if synopsis else '無'}",
              file=sys.stderr)

        if args.dry_run:
            print(f"  (dry-run) 画像{min(len(imgs), args.images)}枚 + §4+声の型プロンプト{len(prompt)}字"
                  f" + あらすじ{len(synopsis)}字 + ④comments{len(c.get('comments') or [])}案 を送信予定")
            continue

        parts = []
        for u in imgs[:args.images]:
            ip = fetch_image(u)
            if ip:
                parts.append(ip)
        if not parts:
            print("  画像を1枚も取得できず=fail-open(room_comments無しのまま)", file=sys.stderr)
            failed += 1
            continue

        got = None
        for attempt in range(2):   # 形式不良は1回だけ生成し直す(同型リトライ2回まで)
            try:
                raw = call_vision(prompt, parts, title, synopsis,
                                  c.get("comments") or [], c.get("metrics") or {},
                                  key, models)
            except Exception as e:
                print(f"  vision 呼び出し失敗: {e}", file=sys.stderr)
                break
            got = parse_room(raw)
            if got:
                break
            print(f"  出力が mitoma/main 形式で不合格→再生成({attempt + 1}/2)", file=sys.stderr)
            time.sleep(1)
        if got:
            c["room_comments"] = got
            filled += 1
            print(f"    mitoma: {got['mitoma']}")
            print(f"    {got['main']['by']}: {got['main']['text']}")
        else:
            failed += 1   # room_comments は無いまま(fail-open)

    if not args.dry_run:
        doc.setdefault("room_vision", {})
        doc["room_vision"] = {
            "generated_by": "system-engineer/scripts/teian/room_comments.py",
            "prompt_source": "docs/departments/copy-director/room_comments生成プロンプト仕様.md §4",
            "voice_source": "00_AI-HQ/departments/hr/characters/mitoma.md・mei.md ★声の型",
            "filled": filled, "failed": failed, "skipped": skipped,
            "synopsis_used": syn_used,
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"\nwrote {out}\n埋めた {filled} / 失敗(無しのまま) {failed} / 対象外(温存/画像無) {skipped}"
              f" / あらすじ添付 {syn_used}")


if __name__ == "__main__":
    main()
