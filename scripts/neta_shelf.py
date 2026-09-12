#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""neta_shelf.py — 集めたネタに「時事棚 / 常在棚」の札を付ける後処理の道具(web-research/カスミ)。

なぜ在るか(2026-09-12 Chami直 ESC-copy-director-1548134259490029629):
  Chami原文=「すぐ投稿しないと意味のないネタと時期をあまり問わないネタと区別して欲しい。
  その区別はここの部門じゃなくていいから。」
  → 棚分けの「運用」は当室(web-research)の持ち物。棚の「基準」の正本は ad研究室のメモ:
     docs/departments/research-room/裁定_ネタの時事常在の棚分けの置き場_2026-09-12.md
  この道具は基準を実装しただけで、閾値(72時間・翌0時)は暫定=正本メモの数字を写している。
  ★基準を勝手に変えない。数字を動かす時は正本メモの版を上げてから写す(下の CRITERIA_REV)。

なぜ「後処理の別道具」か(人手の入口を作らないため):
  scrape/distill の中に判定を埋めると、取得側の改修になり境界を跨ぐ。ここは既に在る出力
  (distilled/*.txt と matome_*.jsonl)を読むだけの独立した棚付けなので、取得3本には触れない。
  = work_scope 内で閉じる(正本メモ §境界)。将来 tags に棚キーを足す段で初めて取得側に入る。

やること(第一版=今在る値だけで回す。取得側の改修なし):
  - local/5ch_research/distilled/*.txt のヘッダ(title / fetched / matome_id / comment_count / bar_ok)を読む。
  - タイトル文字列を主判定にして 時事棚 / 常在棚 を付ける(正本メモ §基準・優先度順)。
  - 時事棚には失効時刻を計算する(具体日付→その日付の翌0時 / 告知・炎上語→fetched_at+72時間・暫定)。
  - 判定材料が足りなければ捨てずに常在棚へ落とす(fail-open。正本メモ §fail-openの向き)。
  - 「薄い(バー15件未満)」蒸留の内訳を、旬で死んだ分(時事×失効済み)と玉が無い分(常在×薄い)に割って見せる。

使い方:
  python scripts/neta_shelf.py                 # 全 distilled を棚分けして内訳を表示
  python scripts/neta_shelf.py --date 2026-09-12
  python scripts/neta_shelf.py --json          # 1行1件の棚台帳を stdout へ(機械向け)
出力:
  local/_work/neta_shelf_<YYYY-MM-DD>.jsonl    (1行=1件・棚の札と失効時刻)
  標準出力に内訳(旬で死んだ / 玉が無い の分解)
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

JST = timezone(timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESEARCH_DIR = os.path.join(ROOT, "local", "5ch_research")
DISTILL_DIR = os.path.join(RESEARCH_DIR, "distilled")
WORK_DIR = os.path.join(ROOT, "local", "_work")

# ★基準の正本= docs/departments/research-room/裁定_ネタの時事常在の棚分けの置き場_2026-09-12.md
#   下の語彙・閾値はそのメモを写したもの。メモの版が上がるまでここを勝手に動かさない。
#   v1.1(2026-09-12 モドリッチ較正1 DISPATCH-web-research-1789176574206)=
#     ①語彙を当てる範囲を「記事タイトル本体」に絞る(サイト名・ブログ名を判定に混ぜない)
#     ②タイトルがサイト名だけのレコードは棚に載せる前に入口で落とす(棚は2つのまま)。
CRITERIA_REV = "2026-09-12 基準 v1.1 (裁定メモ v2)"
BAR = 15  # コメント本数のバー(distill 側と同じ)。薄い=これ未満。

# タイトルの「記事本体 : サイト名」の区切り(実測3種+保険。正本メモ v1.1 §材料①)。
SEPARATORS = (" : ", " – ", " — ", " ｜ ", " | ")
# サイト名だけのレコード(インデックスページ)の署名。区切り無しのタイトルにだけ当てる。
#   実測4件のうち『まとめ速報』2件をこれで拾い、残り(まとめるよ～ん/スレまとめ)は
#   他レコードの接尾辞から自動収集した既知サイト名で拾う(build_rows 参照)。
RE_SITE_NAME = re.compile(r"(まとめ速報|まとめニュース|スレまとめ|速報VIP)\s*$", re.IGNORECASE)

# 告知・速報語(正本メモ §基準 材料1-②)。いずれかを含む→時事。
KW_ANNOUNCE = ["本日", "明日", "いよいよ", "開催", "発表", "延期", "速報",
               "生放送", "配信開始", "予約開始", "カウントダウン", "まもなく"]
# お気持ち・炎上系(材料1-③)。
KW_FLARE = ["お気持ち表明", "お気持ち", "炎上", "謝罪", "引退", "契約解除", "活動休止"]
# イベント日付(例 9/14 21:00 / 9/14 21時 / 9/14 から)。正本メモ材料①は「具体的な日付+時刻」。
#   日付単独は比率(1/2)・分数と誤爆するので、直後に時刻/開始語を伴う時だけ日付と認める。
RE_DATE = re.compile(r"(?<![\d/])([01]?\d)\s*[/／]\s*([0-3]?\d)(?![\d/])")
# 日付の直後(数文字以内)に来る時刻・開始の合図。これが在って初めて「イベント日付」とみなす。
RE_TIME_AFTER = re.compile(r"^\s*(?:[0-2]?\d\s*[:：時]\s*[0-5]?\d?|から|開始|スタート|より|開演)")

# ★72時間は暫定値(正本メモ §時事棚の失効)。速報感が何時間で消えるかを当室もまだ数えていない。
ANNOUNCE_TTL_H = 72


def _now():
    return datetime.now(JST)


def split_title(title):
    """『記事本体 : サイト名』を分ける。最後の区切り以降をサイト名として落とす(v1.1 §材料①)。
    区切りが無ければ本体=全体・サイト名=空。戻り: (body, site_name)。"""
    title = title or ""
    last_pos, last_sep = -1, ""
    for sep in SEPARATORS:
        p = title.rfind(sep)
        if p > last_pos:
            last_pos, last_sep = p, sep
    if last_pos < 0:
        return title.strip(), ""
    return title[:last_pos].strip(), title[last_pos + len(last_sep):].strip()


def is_site_name_only(title, known_sites):
    """タイトルがサイト名・ブログ名だけのレコード(インデックスページ)か。
    区切りが在る=記事本体が在るので対象外。区切り無しで、既知サイト名か署名に当たる時だけ真。"""
    body, site = split_title(title)
    if site:  # 記事本体 : サイト名 の形=本体が在る=記事
        return False
    t = body.strip()
    if not t:
        return True
    if t in known_sites:
        return True
    return bool(RE_SITE_NAME.search(t))


def parse_header(path):
    """distilled txt のヘッダ(空行までの key: value)を読む。"""
    h = {}
    with open(path, encoding="utf-8") as f:
        first = f.readline()
        if first.startswith("# "):
            h["title"] = first[2:].rstrip("\n")
        for line in f:
            line = line.rstrip("\n")
            if not line:
                break
            m = re.match(r"([a-z_]+):\s*(.*)", line)
            if m:
                h[m.group(1)] = m.group(2)
    return h


def load_fetched_map():
    """matome_*.jsonl から matome_id('host:id') → fetched_at(ISO) を作る。失効の基点に使う。"""
    fmap = {}
    for path in glob.glob(os.path.join(RESEARCH_DIR, "matome_*_*.jsonl")):
        base = os.path.basename(path)
        # matome_<host>_<YYYY-MM-DD>.jsonl から host を取り出す
        m = re.match(r"matome_(.+)_\d{4}-\d{2}-\d{2}\.jsonl$", base)
        if not m:
            continue
        host = m.group(1)
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    a = json.loads(line)
                    key = f"{host}:{a.get('id', '')}"
                    fa = a.get("fetched_at")
                    if fa and key not in fmap:
                        fmap[key] = fa
        except (OSError, ValueError):
            continue
    return fmap


def _parse_fetched(fetched_at):
    """fetched_at(ISO)を JST aware に。取れなければ None。"""
    if not fetched_at:
        return None
    try:
        dt = datetime.fromisoformat(fetched_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST)
    except ValueError:
        return None


def _next_midnight_after(month, day, base):
    """タイトルの M/D を base(fetched)以降で最も近い年に解決し、その日付の翌0時を返す。
    イベントを過ぎたら死ぬので失効=イベント日の翌0時(正本メモ §時事棚の失効)。"""
    for year in (base.year, base.year + 1):
        try:
            ev = datetime(year, month, day, tzinfo=JST)
        except ValueError:
            return None
        # イベント日が fetched の前日より前なら翌年扱い(去年の日付を拾わない)
        if ev.date() >= (base.date() - timedelta(days=1)):
            return ev + timedelta(days=1)  # 翌0時
    return None


def classify(title, fetched_at):
    """タイトル主判定で棚と失効時刻を返す。fail-open→常在。
    戻り: (shelf, reason, expire_dt or None)

    ★語彙を当てる範囲は「記事タイトル本体」だけ(v1.1 §材料①)。サイト名・ブログ名
    (最後の区切り以降)は判定に混ぜない=『まとめ速報』等が語彙『速報』で誤爆しないため。"""
    body, _site = split_title(title or "")
    base = _parse_fetched(fetched_at) or _now()

    # ① 具体的な日付+時刻 → 時事。失効=その日付の翌0時。
    #   日付単独(比率 1/2 等)は取らない=直後に時刻・開始語が続く時だけイベント日付とみなす。
    for m in RE_DATE.finditer(body):
        mo, dy = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= dy <= 31):
            continue
        if not RE_TIME_AFTER.match(body[m.end():]):
            continue
        exp = _next_midnight_after(mo, dy, base)
        if exp:
            return "時事", f"具体日付+時刻 {mo}/{dy}", exp

    # ③ お気持ち・炎上系(先に見る=より強い時事性)。失効= fetched+72h(暫定)。
    for kw in KW_FLARE:
        if kw in body:
            return "時事", f"炎上・お気持ち語「{kw}」", base + timedelta(hours=ANNOUNCE_TTL_H)

    # ② 告知・速報語。失効= fetched+72h(暫定)。
    for kw in KW_ANNOUNCE:
        if kw in body:
            return "時事", f"告知・速報語「{kw}」", base + timedelta(hours=ANNOUNCE_TTL_H)

    # 材料が足りない=常在へ落とす(fail-open)。
    return "常在", "時事の材料なし(fail-open)", None


def _to_int(s, default=0):
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return default


def collect_site_names(headers):
    """各レコードの接尾辞(最後の区切り以降=サイト名)を集めて既知サイト名の集合を作る。
    区切り無しのインデックスページ(まとめるよ～ん/スレまとめ 等)を入口で外す照合材料にする。"""
    sites = set()
    for h in headers:
        _body, site = split_title(h.get("title", ""))
        if site:
            sites.add(site)
    return sites


def build_rows(date_filter=None, dropped_out=None):
    """distilled を棚分けする。棚に載せる前に、タイトルがサイト名だけのレコード
    (インデックスページ=実測4件)を入口で外す(v1.1 §材料②。棚は2つのまま)。
    外した件数を dropped_out(list)へ積んで報告に回す。"""
    fmap = load_fetched_map()
    now = _now()

    # 1周目= 全レコードのヘッダを読み、接尾辞から既知サイト名を集める。
    headers = []
    for path in sorted(glob.glob(os.path.join(DISTILL_DIR, "*.txt"))):
        h = parse_header(path)
        if not h.get("title"):
            continue
        if date_filter and h.get("fetched", "").split()[0:1] != [date_filter]:
            continue
        h["_path"] = path
        headers.append(h)
    known_sites = collect_site_names(headers)

    # 2周目= サイト名だけのレコードを入口で落とし、残りを棚分けする。
    rows = []
    for h in headers:
        if is_site_name_only(h["title"], known_sites):
            if dropped_out is not None:
                dropped_out.append({"file": os.path.basename(h["_path"]), "title": h["title"]})
            continue
        mid = h.get("matome_id", "")
        fetched_at = fmap.get(mid)  # 無ければ classify 側で now を基点にする
        shelf, reason, exp = classify(h["title"], fetched_at)
        cc = _to_int(h.get("comment_count"))
        bar_ok = (h.get("bar_ok", "").strip().lower() == "true") or cc >= BAR
        expired = bool(exp and now > exp)
        rows.append({
            "file": os.path.basename(h["_path"]),
            "matome_id": mid,
            "title": h["title"],
            "fetched": h.get("fetched", ""),
            "shelf": shelf,
            "reason": reason,
            "expire_at": exp.isoformat(timespec="minutes") if exp else None,
            "expired": expired,
            "comment_count": cc,
            "bar_ok": bar_ok,
        })
    return rows


def report(rows, dropped=None):
    dropped = dropped or []
    jiji = [r for r in rows if r["shelf"] == "時事"]
    joza = [r for r in rows if r["shelf"] == "常在"]
    under = [r for r in rows if not r["bar_ok"]]
    # 薄い蒸留の内訳(Chami/モドリッチ依頼の核):
    #   旬で死んだ分 = 時事 かつ 失効済み / 玉が無い分 = 常在 かつ 薄い
    dead_by_season = [r for r in under if r["shelf"] == "時事" and r["expired"]]
    no_gem = [r for r in under if r["shelf"] == "常在"]
    jiji_alive_thin = [r for r in under if r["shelf"] == "時事" and not r["expired"]]

    print(f"[neta_shelf] 基準正本= {CRITERIA_REV}(閾値72h/翌0時は暫定)")
    print(f"入口で除外(サイト名だけのインデックス)= {len(dropped)}件")
    for d in dropped:
        print(f"  外: {d['title'][:48]}")
    print(f"対象= {len(rows)}件  時事棚= {len(jiji)}  常在棚= {len(joza)}")
    print(f"バー{BAR}件以上= {len(rows) - len(under)}  薄い(未満)= {len(under)}")
    print("--- 薄い蒸留の内訳(なぜ歩留まりが薄いか)---")
    print(f"  旬で死んだ分(時事×失効済み)= {len(dead_by_season)}件  ← 取得が遅い/頻度不足")
    print(f"  玉が無い分  (常在×薄い)   = {len(no_gem)}件      ← 玉の乏しいソース")
    print(f"  時事だが未失効でまだ薄い    = {len(jiji_alive_thin)}件  ← 今から拾えば間に合う")

    # 時事棚= 失効が近い順(先に死ぬものを先に)。同着は comment 多い順。
    def _exp_key(r):
        return (r["expire_at"] or "9999", -r["comment_count"])
    if jiji:
        print("--- 時事棚(失効が近い順)---")
        for r in sorted(jiji, key=_exp_key):
            flag = "【失効】" if r["expired"] else f"→{r['expire_at']}"
            print(f"  {flag} c={r['comment_count']:>3} {r['title'][:44]}  ({r['reason']})")
    if joza:
        print("--- 常在棚(質=コメント多い順)---")
        for r in sorted(joza, key=lambda r: -r["comment_count"]):
            print(f"  c={r['comment_count']:>3} {r['title'][:48]}")


def main():
    ap = argparse.ArgumentParser(description="集めたネタを時事棚/常在棚へ棚分けする後処理")
    ap.add_argument("--date", default=None, help="fetched がこの日(YYYY-MM-DD)のものだけ対象")
    ap.add_argument("--json", action="store_true", help="棚台帳を1行1件でstdoutへ(機械向け)")
    ap.add_argument("--no-save", action="store_true", help="local/_work へ保存しない")
    args = ap.parse_args()

    dropped = []
    rows = build_rows(args.date, dropped_out=dropped)

    if args.json:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    else:
        report(rows, dropped)

    if not args.no_save and rows:
        os.makedirs(WORK_DIR, exist_ok=True)
        tag = args.date or _now().strftime("%Y-%m-%d")
        out = os.path.join(WORK_DIR, f"neta_shelf_{tag}.jsonl")
        with open(out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if not args.json:
            print(f"→ {out} ({len(rows)}件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
