#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""競合YouTubeコミュニティ投稿の日次分析 (2026-09-01 分析部門・三笘/アーモンドアイ / Chami新方針)

Chami要件 (2026-08-31 軍議 msg 1544039212653875352 / 1544040607058493541):
  - 記号・タグ・変数の羅列をやめ、Chamiが一目で読める普通の日本語で出す。
  - 投稿1件ごとに三つだけ書く: ①これは何の投稿か (画像の中身・画風・きわどさ)
    ②何に反応が付いたか (伸びた理由を日本語で) ③次どう擦るか。
  - 当面はYouTube内の話として扱う (Xは対象外)。毎朝8時前後で回す。

やること:
  local/consult_intel/competitor_community.jsonl (competitor_community 収集の出力) を読み、
  各投稿の画像1枚をGeminiに見せて中身・画風・フィード掲載可否を言葉にし、
  票数を「チャンネルの中での相対」で読んで、①②③のレポートを local/ へ書く。

前提: competitor_community.jsonl が新しいこと。収集自体は scripts/comp/community_scrape.py が担う
  (このスクリプトは分析だけ・収集はしない)。behopの画像視覚経路を comp_frames.py と同じ形で使う。
使い方:
  python scripts/analysis/community_daily.py            # 全件を分析してレポートを書く
  python scripts/analysis/community_daily.py --limit 5  # 先頭5件だけ (試し)
  python scripts/analysis/community_daily.py --no-vision # 画像を見ずテキスト/票だけで書く (枠温存)
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "behop"))
import behop  # noqa: E402

SRC = os.path.join(ROOT, "local", "consult_intel", "competitor_community.jsonl")
OUT_DIR = os.path.join(ROOT, "local", "consult_intel")
BASE_MODEL = "gemini-flash-latest"   # comp_frames と同じ基準 (無料枠が広くバッチ向き)

VISION_PROMPT = (
    "この画像はYouTubeショート系チャンネルのコミュニティ投稿に使われた1枚 (多くは1コマ漫画) です。"
    "次を日本語で答え、JSONだけを返してください。\n"
    '{"imageDesc":"画像の中身を1〜2文で。誰が・何をしている・どんな状況か",'
    '"artStyle":"画風を短い一語か二語で (例 現代アニメ塗り/淡い水彩/劇画/デフォルメ/写真)",'
    '"feedRisk":"この画像がYouTubeショートのフィードに問題なく載るかを『載る』『際どい』『隠す必要あり』の三つのどれか一語で。'
    '胸や太もも・下着の露出が強調されていれば載りにくい、という基準で判定する",'
    '"riskReason":"その判定の理由を1文。露出が控えめなら『露出は控えめ』とだけ書く"}\n'
    "余計な説明やコードフェンスは付けず、JSONオブジェクト1つだけを返す。"
)


def vote_num(s):
    """『359』『41』『9.3万』『324万』を整数へ。空は0。"""
    s = (s or "").strip().replace(",", "")
    if not s:
        return 0
    m = re.match(r"^([\d.]+)\s*万", s)
    if m:
        return int(float(m.group(1)) * 10000)
    try:
        return int(float(s))
    except ValueError:
        return 0


def load_posts():
    posts = []
    with open(SRC, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                posts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return posts


def channel_medians(posts):
    """チャンネルごとの票の中央値 (相対の物差し)。"""
    by = {}
    for p in posts:
        by.setdefault(p.get("channel_id", ""), []).append(vote_num(p.get("vote_count")))
    med = {}
    for cid, vs in by.items():
        vs = sorted(vs)
        n = len(vs)
        med[cid] = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
        med[cid] = med[cid] or 0
    return med


def dl_image(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        f.write(r.read())
    return os.path.getsize(path) > 0


def parse_vision(text):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return {
        "imageDesc": str(d.get("imageDesc", "") or "").strip(),
        "artStyle": str(d.get("artStyle", "") or "").strip(),
        "feedRisk": str(d.get("feedRisk", "") or "").strip(),
        "riskReason": str(d.get("riskReason", "") or "").strip(),
    }


def text_kata(text):
    """文面の型を日本語の説明に (記号を出さない)。"""
    t = text or ""
    parts = []
    if any(k in t for k in ["？", "?", "だと思う", "と思う"]):
        parts.append("読者に問いかけて考えさせている")
    if any(k in t for k in ["断れる", "いる？", "いる?", "どっち", "選ぶ", "一緒に"]):
        parts.append("同意やツッコミを誘っている")
    if any(k in t for k in ["すぎ", "でしょ", "ご褒美", "可愛", "かわい", "好き", "照れる"]):
        parts.append("共感を言い切っている")
    if "作者" in t or "@" in t:
        parts.append("作者名を明記して作者側の拡散も取り込んでいる")
    return "、".join(parts) if parts else "短い一言で提示している"


def riff(text, feed_risk):
    t = text or ""
    out = []
    if any(k in t for k in ["断れる", "いる？", "いる?", "どっち", "選ぶ", "一緒に", "？", "?"]):
        out.append("うちの作品でも、コマの状況に『断れる人いる?』『どっちを選ぶ?』のような同意や選択を誘う一言を添えて出す")
    if any(k in t for k in ["すぎ", "でしょ", "ご褒美", "可愛", "かわい", "好き"]):
        out.append("『こんな〇〇、可愛すぎる』の共感言い切り型を、月詠みと宵桜で別々のコマ・別々の言い回しで試す")
    if feed_risk and feed_risk != "載る":
        out.append("露出は電車内で見られて困らないコマに差し替えてから使う")
    if "作者" in t or "@" in t:
        out.append("作者名クレジットを添えて作者側の拡散を取り込む")
    if not out:
        out.append("同じ題材でも一言を『問いかけ』か『共感の言い切り』に変えて、反応が変わるか試す")
    return out


def analyze(posts, medians, do_vision, limit):
    keys = []
    if do_vision:
        key = behop._read(behop.KEY_FILE, "ベホップ用APIキー")
        if BASE_MODEL in behop.list_models(key):
            keys.append(("ベホップ", key))
        try:
            homin = open(os.path.join(ROOT, "local", "gemini_api_key.txt"), encoding="utf-8").read().strip()
        except OSError:
            homin = ""
        if homin and homin != key:
            keys.append(("ホイミン", homin))
        if not keys:
            print("視覚キーが使えない。テキスト/票だけで書く。")
            do_vision = False

    kidx = 0
    blocks = []
    n = 0
    for p in posts:
        if limit and n >= limit:
            break
        n += 1
        ch = p.get("channel_name", "不明チャンネル")
        cid = p.get("channel_id", "")
        text = (p.get("text") or "").replace("\r", " ").replace("\n", " ").strip()
        vc = p.get("vote_count") or ""
        v = vote_num(vc)
        imgs = p.get("image_urls") or []
        ptype = p.get("type", "")

        # (1) 画像の中身・画風・きわどさ
        vis = None
        if do_vision and imgs and kidx < len(keys):
            work = tempfile.mkdtemp(prefix="cd_")
            try:
                fp = os.path.join(work, "img.jpg")
                if dl_image(imgs[0], fp):
                    while kidx < len(keys):
                        kname, kval = keys[kidx]
                        txt = status = None
                        # 一時的な5xx(503=過負荷)は数回まで待って粘る
                        for attempt in range(4):
                            txt, status = behop.ask_pro(kval, VISION_PROMPT, [fp], BASE_MODEL,
                                                        tag="community_daily", who=behop.bundle_of(kname))
                            if status == "ok" or status == "quota":
                                break
                            if status and status.startswith("error:HTTP 5"):
                                wait = 3 * (attempt + 1)
                                print(f"  {kname}が一時エラー({status})→{wait}秒待って再試行")
                                time.sleep(wait)
                                continue
                            break
                        if status == "quota":
                            print(f"  {kname}の無料枠が尽きた(429)→次のキーへ")
                            kidx += 1
                            continue
                        if status == "ok":
                            vis = parse_vision(txt)
                            if vis is None:
                                print(f"  {kname}の応答がJSONで読めなかった: {(txt or '')[:80]}")
                        elif status:
                            print(f"  視覚できず({status}) → {ch} は文面と票だけで書く")
                        break
            except Exception as e:
                print(f"  画像取得/視覚に失敗: {str(e)[:60]}")
            finally:
                shutil.rmtree(work, ignore_errors=True)
            time.sleep(1.0)

        if vis:
            s1 = f"画像の中身は、{vis['imageDesc']} 画風は{vis['artStyle']}。"
            if vis["feedRisk"]:
                s1 += f" きわどさは『{vis['feedRisk']}』({vis['riskReason']})。"
        elif ptype == "poll":
            s1 = "画像のないアンケート投稿。選択肢を出して読者に投票させる形。"
        elif not imgs:
            s1 = "画像のないテキスト投稿。"
        else:
            s1 = "画像はまだ見ていない(この回では未視覚化)。文面と票だけで読む。"

        # (2) なぜ伸びたか
        med = medians.get(cid, 0)
        if med and v >= med * 1.3:
            pos = "このチャンネルの中では反応が強い方"
        elif med and v <= med * 0.7:
            pos = "このチャンネルの中では弱い方"
        else:
            pos = "このチャンネルの中では平均的"
        s2 = f"票は{v}({vc or '表示なし'})。{pos}。文面は{text_kata(text)}。"

        # (3) 次どう擦るか
        fr = vis["feedRisk"] if vis else ""
        s3 = "。".join(riff(text, fr)) + "。"

        head = f"■ {ch}  「{text[:40]}」" if text else f"■ {ch}  (文面なし)"
        blocks.append(head + "\n"
                      + "  どんな投稿か: " + s1 + "\n"
                      + "  なぜ伸びたか: " + s2 + "\n"
                      + "  次どう擦るか: " + s3)
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="先頭N件だけ(0=全件)")
    ap.add_argument("--no-vision", action="store_true", help="画像を見ずテキスト/票だけで書く")
    args = ap.parse_args()

    if not os.path.exists(SRC):
        print(f"ABORT: 材料が無い: {SRC}")
        return 2
    posts = load_posts()
    if not posts:
        print("ABORT: 投稿が0件。収集(community_scrape.py)を先に回す。")
        return 2

    # 収集の鮮度を正直に見せる (一度きりの古いデータで語らないため)
    fetched = sorted({(p.get("fetched_at") or "")[:10] for p in posts if p.get("fetched_at")})
    medians = channel_medians(posts)
    blocks = analyze(posts, medians, not args.no_vision, args.limit)

    today = time.strftime("%Y-%m-%d")
    out = os.path.join(OUT_DIR, f"community_report_{today}.md")
    header = (
        f"# 競合コミュニティ投稿レポート {today}\n\n"
        f"対象 {len(posts)}件 / 収集日 {('・'.join(fetched)) or '不明'}"
        + ("  ※収集日が古い。community_scrape.py で採り直すと最新になる。\n\n"
           if fetched and fetched[-1] < today else "\n\n")
        + "票はチャンネルの規模で桁が違うので、チャンネルの中での相対で読む(巨大集客アカと同人アカを同じ物差しで比べない)。\n\n"
    )
    with open(out, "w", encoding="utf-8") as f:
        f.write(header + "\n\n".join(blocks) + "\n")
    print(f"書いた: {out}  ({len(blocks)}件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
