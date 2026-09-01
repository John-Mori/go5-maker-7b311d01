#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""candidates_json.py — 提案決定ページ用の候補JSON(comments以外)を実データで出す(十王星南)。
正本schema= docs/設計・調査/提案決定ページ_設計書.md §2。
出力= local/teian/candidates_YYYY-MM-DD.json(改修αのページが読む)。

★このツールは"候補の選定と根拠(metrics)"だけを埋める。comments は空配列(visionが後で埋める)。
採点は daily_pick.py の score/posted_recent を再利用=部門の選定軸を1本に保つ(single-source)。
- 動画生成用の画像(sampleImageURL.sample_l のコマ)が無い作品は動画化できない=候補から除外。
- 除外=直近3日に投稿 ∪ 直近10件の投稿に含まれる作品(posted_log・fail-open・Chami 2026-08-23=日数 OR 件数のどちらか該当で除外・K=10確定)。
- Books(cid が d_ 以外)で info_json が無い物は「未収録」=推測で埋めず books_uncovered へ cid 直書きで明示。
"""
import json, io, os, sys, math, datetime, subprocess, re, time, tempfile
import html as _html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_pick as dp

def revenue_rate(cid):
    """還元率(payout)= Books 0.70 / 同人 0.35(設計書§2)。"""
    return 0.35 if cid.startswith("d_") else 0.70

def rank_score(cid, sales):
    """★ページの並び順の正=分析(shorts-analyst)確定式 score = revenue_rate × log1p(sales_n)。
    候補を分けるのは需要(sales_n)と還元率だけ=再生/変換は素材/導線に支配され候補を分けない(指標定義 commit 4588d7f)。"""
    return round(revenue_rate(cid) * math.log1p(sales or 0), 4)

# ── あらすじ(作品紹介)取得 ─────────────────────────────────────────────
# Chami 2026-08-15「あらすじ表示はいらんけど、スクレイピングで取得して内容考慮して決めて」。
# ★あらすじ本文は vision(④コメント生成)の"判断材料"であって画面に出さない。かつ過激本文を
#   client面へ流さないため、本文は配信されるcandidates JSONには載せず PC専用サイドカーへ書く
#   (publish_candidates.py は candidates_<date>.json を丸ごとR2へ上げる=そこへ本文を入れると即漏れる)。
DMM_DOUJIN_BASE = "https://www.dmm.co.jp/dc/doujin/-/detail/=/cid="
_SCRAPE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

def page_url_for(cid):
    """あらすじを読む作品ページURL。同人(d_)は取得可。Books(b/k/s…)はページ構成が別で
    cidだけでは確実に組み立てられない=Noneを返して null で続行(推測URLを叩かない)。"""
    return (DMM_DOUJIN_BASE + cid + "/") if cid.startswith("d_") else None

def _fetch_page(url):
    """curlで1ページ取得(urllibはDMMのTLS指紋で無応答になる=curl一択・fanza-worker同型のage-gate)。
    国内IP前提でage_checkクッキーを付与。失敗はNone。"""
    try:
        p = subprocess.run(
            ["curl", "-sL", "--max-time", "25", "-A", _SCRAPE_UA,
             "-H", "Cookie: age_check_done=1; ckcy=1; cklg=ja",
             "-H", "Accept-Language: ja,en-US;q=0.7", url],
            capture_output=True, shell=True)
        if p.returncode != 0 or not p.stdout:
            return None
        return p.stdout.decode("utf-8", "replace")
    except Exception:
        return None

def extract_synopsis(html):
    """作品ページHTMLから作品紹介(あらすじ)本文を抜く純関数。同人ページは
    <div class="summary__txt"> に全文が入る。取れなければNone(推測で埋めない)。"""
    if not html:
        return None
    m = re.search(r'class="summary__txt"[^>]*>(.*?)</div>', html, re.S)
    if not m:
        return None
    t = re.sub(r'<br\s*/?>', '\n', m.group(1))
    t = re.sub(r'<[^>]+>', '', t)
    t = _html.unescape(t)
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t).strip()
    return t or None

def synopsis_for(cid, fetch=_fetch_page, cache=None):
    """cidのあらすじを返す(取得できなければNone)。★取得失敗は絶対に例外を投げない=
    パイプラインを止めない(fail-open・必須依存にしない)。成功分はcacheに載せ再取得しない
    (Noneはキャッシュせず次回リトライ=一時的な取得失敗を固定化しない)。"""
    if cache is not None and cache.get(cid):
        return cache[cid]
    s = None
    url = page_url_for(cid)
    if url:
        try:
            s = extract_synopsis(fetch(url))
        except Exception:
            s = None
    if cache is not None and s:
        cache[cid] = s
    return s

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "local", "teian")
OUT_DIR = os.path.abspath(OUT_DIR)
SYN_CACHE = None  # main() で OUT_DIR 確定後に設定
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
SYNC_BUCKET = "go5-sync-images"
SYNC_STATE_KEY = "state/sync-v1.json"
SYNC_IMAGE_BASE = "https://go5-sync.trustsignalbot.workers.dev/img/"
_CID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")

def images_of(info):
    """挿入画像=フルカラーのコマ(sample_l 優先)。URL配列を返す。"""
    si = info.get("sampleImageURL") or {}
    if isinstance(si, dict):
        for k in ("sample_l", "sample_s"):
            im = (si.get(k) or {}).get("image")
            if im: return [u for u in im if u]
    return []

def platform_of(cid):
    return "doujin" if cid.startswith("d_") else "books"


def _json_value(value, default):
    """同期state内のJSON文字列を安全に復号する純関数。壊れた値はdefault(fail-open)。"""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _record_value(rec):
    """同期stateのLWWレコード {t,v}/{t,d} から値だけを取り出す。墓標はNone。"""
    if not isinstance(rec, dict) or rec.get("d"):
        return None
    return rec.get("v")


def _collect_img_hashes(value, out):
    """旧IDB同期値から {__img:<sha256>} を再帰的に集める。"""
    if isinstance(value, dict):
        h = str(value.get("__img") or "").lower()
        if _HASH_RE.fullmatch(h):
            out.append(h)
            return
        for v in value.values():
            _collect_img_hashes(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_img_hashes(v, out)


def parse_ready_sync_bundle(raw, image_base=SYNC_IMAGE_BASE):
    """sync-workerのR2 stateから、投稿用画像を持つcidと候補メタだけを抜く。

    返り値={cid:{vision_images:[公開R2 URL], item:{候補行}}}。秘密/設定/本文は返さない。
    URL台帳(go5_image_manifest_v1)を正とし、台帳に明示空 keys:[] があれば旧IDB参照を
    復活させない。台帳に記録が無い旧作品だけIDBの__imgをfallbackに使う。
    """
    outer = _json_value(raw, {})
    if not isinstance(outer, dict):
        return {}
    state = _json_value(outer.get("blob"), outer)
    if not isinstance(state, dict):
        return {}
    ls = state.get("ls") if isinstance(state.get("ls"), dict) else {}
    idb = state.get("idb") if isinstance(state.get("idb"), dict) else {}

    # 候補は cand_items と cand_items__<tab> の和集合。新しい行をcidごとに採る。
    items = {}
    item_at = {}
    for key, rec in ls.items():
        if not re.match(r"^cand_items(?:__.*)?$", str(key)):
            continue
        rows = _json_value(_record_value(rec), [])
        if not isinstance(rows, list):
            continue
        rec_at = float((rec or {}).get("t") or 0) if isinstance(rec, dict) else 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("cid") or "").strip()
            if not _CID_RE.fullmatch(cid):
                continue
            at = float(row.get("addedAt") or rec_at or 0)
            if cid not in items or at >= item_at.get(cid, 0):
                items[cid], item_at[cid] = dict(row), at

    # 旧同期値の__imgは台帳が無い作品だけのfallback。
    refs = {}
    for key, rec in idb.items():
        key = str(key)
        if not key.startswith("ref:"):
            continue
        cid = key[4:]
        if not _CID_RE.fullmatch(cid):
            continue
        hashes = []
        _collect_img_hashes(_record_value(rec), hashes)
        if hashes:
            refs[cid] = list(dict.fromkeys(hashes))

    manifest_rec = ls.get("go5_image_manifest_v1")
    manifest = _json_value(_record_value(manifest_rec), {})
    if isinstance(manifest, dict):
        for rid, rec in manifest.items():
            rid = str(rid)
            if not rid.startswith("ref:"):
                continue
            cid = rid[4:]
            if not _CID_RE.fullmatch(cid) or not isinstance(rec, dict) or not isinstance(rec.get("keys"), list):
                continue
            hashes = [str(h or "").lower() for h in rec.get("keys", [])]
            if any(not _HASH_RE.fullmatch(h) for h in hashes):
                continue
            # 明示空も正本。古いIDB参照で画像を復活させない。
            if hashes:
                refs[cid] = list(dict.fromkeys(hashes))
            else:
                refs.pop(cid, None)

    base = str(image_base or SYNC_IMAGE_BASE).rstrip("/") + "/"
    return {
        cid: {
            "vision_images": [base + h for h in hashes],
            "item": items.get(cid, {}),
        }
        for cid, hashes in refs.items() if hashes
    }


def load_ready_sync_library():
    """R2の同期stateを一時ファイルへ読み、ready用の最小情報だけ返す。

    state本体は設定等も含むためログ/成果物へ残さず、必ず一時ファイルを削除する。
    wrangler未認証・R2未到達は空dictで日次生成を継続(fail-open)。
    """
    private_tmp = os.path.join(REPO_ROOT, "local", "_work")
    os.makedirs(private_tmp, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="go5-ready-state-", suffix=".json", dir=private_tmp)
    os.close(fd)
    os.remove(tmp)  # wrangler --file は「新規作成先」を要求するため、予約名だけ残して実体は消す。
    try:
        cmd = ["npx", "wrangler", "r2", "object", "get",
               f"{SYNC_BUCKET}/{SYNC_STATE_KEY}", "--remote", "--file", tmp]
        p = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, shell=True)
        if p.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) <= 0:
            return {}
        with open(tmp, "r", encoding="utf-8") as f:
            return parse_ready_sync_bundle(f.read())
    except Exception:
        return {}
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def works_for_cids(cids):
    """ready cidの作品情報をD1から取得。SQLへ入れるcidは厳格な許可文字だけ。"""
    valid = sorted({str(c) for c in cids if _CID_RE.fullmatch(str(c))})
    out = {}
    for start in range(0, len(valid), 80):
        chunk = valid[start:start + 80]
        if not chunk:
            continue
        quoted = ",".join("'" + c + "'" for c in chunk)
        try:
            rows = dp.d1("SELECT cid, title, info_json, sales_n FROM works WHERE cid IN (" + quoted + ")")
        except Exception:
            rows = []
        for row in rows:
            cid = str(row.get("cid") or "")
            if cid in chunk:
                out[cid] = row
    return out


def build_ready_library(sync_ready, work_rows, excluded, main_cids, last_posted,
                        posted_ch_map, closed_ch):
    """投稿用画像あり作品を既存候補と分離したready_libraryへ整形する純関数。

    commentsは空で作り、carry_content/visionが空欄だけを埋める。既存20件はcandidates側を
    正として重複させず、直近投稿除外も同じ集合を使う。
    """
    excluded, main_cids = set(excluded or []), set(main_cids or [])
    ready = []
    for cid in sorted(sync_ready):
        if cid in excluded or cid in main_cids or not _CID_RE.fullmatch(cid):
            continue
        ref = sync_ready.get(cid) or {}
        vision_images = [u for u in (ref.get("vision_images") or []) if isinstance(u, str) and u.startswith("http")]
        if not vision_images:
            continue
        row, item = work_rows.get(cid) or {}, ref.get("item") or {}
        try:
            info = json.loads(row.get("info_json") or "{}")
        except Exception:
            info = {}
        pr = info.get("prices") or {}
        price = dp.num(pr.get("price"))
        lp = dp.num(pr.get("list_price"))
        if price is None:
            price = dp.num(item.get("price"))
        if lp is None:
            lp = dp.num(item.get("listPrice"))
        disc = round((lp - price) / lp * 100) if (price is not None and lp) else dp.num(item.get("discountPct"))
        rev = review_of(info)
        if rev is None and (item.get("reviewCount") is not None or item.get("reviewAvg") is not None):
            rev = {"count": dp.num(item.get("reviewCount")), "average": item.get("reviewAvg")}
        sales = dp.num(row.get("sales_n"))
        samples = images_of(info)
        thumb = item.get("thumb") or ""
        if not samples and isinstance(thumb, str) and thumb.startswith("http"):
            samples = [thumb]
        ready.append({
            "id": "ready-" + cid,
            "cid": cid,
            "platform": platform_of(cid),
            "title": row.get("title") or item.get("title") or cid,
            "last_posted": (last_posted or {}).get(cid),
            "posted_ch": {
                "acc1": (posted_ch_map or {}).get(cid, {}).get("acc1"),
                "acc2": (posted_ch_map or {}).get(cid, {}).get("acc2"),
            },
            "ready_ch": {
                "acc1": cid not in (closed_ch or {}).get("acc1", set()),
                "acc2": cid not in (closed_ch or {}).get("acc2", set()),
            },
            "images": samples,
            "vision_images": vision_images,
            "metrics": {
                "sales_n": sales,
                "review": rev,
                "price": price,
                "list_price": lp,
                "discount_pct": disc,
                "revenue_rate": revenue_rate(cid),
                "score": rank_score(cid, sales),
                "past_similar_recovery": None,
            },
            "manual": True,
            "comments": [],
            "_fromLibrary": True,
        })
    ready.sort(key=lambda c: (-(c.get("metrics", {}).get("score") or 0), c.get("cid") or ""))
    return ready

# posted_log の channel 値 → 表示チャンネル名(記録_ch1/記録_ch2 と同じ2ch)。
CH_NAME = {"acc1": "月詠み", "acc2": "宵桜艶帖"}

def _posted_at_jst_date(s):
    """posted_at(UTC ISO・末尾Z)を JST の 'YYYY-MM-DD' へ。★DiscordではなくD1のUTC=+9する。"""
    try:
        base = str(s)[:19]  # '2026-08-21T14:40:18'(小数秒/Zは落とす)
        dt = datetime.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S") + datetime.timedelta(hours=9)
        return dt.date().isoformat()
    except Exception:
        return None

def last_posted_by_channel():
    """戻り値=(m, by_ch) の2つ組(1回のD1問い合わせから両方を作る=posted_logの二度引きをしない)。
    m: {cid: {'date':'YYYY-MM-DD'(JST), 'channel':'月詠み'|'宵桜艶帖'}} 各cidの"最新の"投稿(全期間・chを問わない)。
      ★『この作品は○ch用』の割り当てをやめ(Chami『作品はどっちでも可』2026-08-23)、直近でどちら
        のchにいつ投稿したかだけを持たせる=出所は posted_log(記録_ch1/記録_ch2 のD1形)。
    by_ch: {cid: {'acc1':'YYYY-MM-DD'|欠, 'acc2':'YYYY-MM-DD'|欠}} 各cid×chの最終投稿日(PK=(cid,channel)
      につき最大1行=DESC不要でそのまま採用)。channel別分岐の土台(posted_chの元データ)。
    取得失敗/空なら空dict2つ(fail-open=最終投稿が引けなくても候補生成は止めない)。"""
    try:
        rows = dp.d1("SELECT cid, channel, posted_at FROM posted_log ORDER BY posted_at DESC")
        m, by_ch = {}, {}
        for r in rows:
            cid, ch, pa = r.get("cid"), r.get("channel"), r.get("posted_at")
            if not cid:
                continue
            d = _posted_at_jst_date(pa)
            if cid not in m and d:       # ★DESC順=各cidで最初に見た行が最新
                m[cid] = {"date": d, "channel": CH_NAME.get(ch, ch)}
            if ch in CH_NAME and d:      # ch別は m の重複ガードと独立に全行から拾う
                by_ch.setdefault(cid, {})[ch] = d
        return m, by_ch
    except Exception:
        return {}, {}

def _content_store_path():
    return os.path.join(OUT_DIR, "content_store.json")


def carry_content(out_candidates, today, ready_library=None):
    """再生成しても既に埋めた④comments/room_commentsを消さない(Chami『再生成不要』2026-08-23)。
    候補の並び/顔ぶれは毎回引き直すが、中身は cid で持ち越す。durableな出所=content_store.json
    (cid毎)＋当日ファイル(念のため拾う)。★中身の生成はしない=空のままの新規cidは vision/軍議が後で埋める。
    2026-08-23の事故=このツールが毎回 comments=[]・room_comments無しで丸ごと上書きし、充填済み20件を
    毎回消していた(publishはC-038ガードで止まるがローカルは全消し)=その恒久止血。"""
    store_path = _content_store_path()
    try:
        with open(store_path, encoding="utf-8") as f:
            store = json.load(f)
    except Exception:
        store = {}
    # 当日ファイルに残っている中身も store へ吸い上げる(store が空/欠けても拾える)
    try:
        with open(os.path.join(OUT_DIR, f"candidates_{today}.json"), encoding="utf-8") as f:
            old = json.load(f)
        old_rows = list(old.get("candidates", []) or []) + list(old.get("ready_library", []) or [])
        for c in old_rows:
            cid = c.get("cid")
            if not cid:
                continue
            cm, rc = c.get("comments") or [], c.get("room_comments") or {}
            ex = c.get("explainer")   # ★解説(コピー部が書く)も comments と同じく cid で持ち越す(Chami『再生成不要』)
            if cm or rc or ex:
                cur = store.get(cid) or {}
                if cm:
                    cur["comments"] = cm
                if rc:
                    cur["room_comments"] = rc
                if ex:
                    cur["explainer"] = ex
                store[cid] = cur
    except Exception:
        pass
    # store から今回の候補へ持ち越す(cid一致のみ・無い物は空のまま)
    all_rows = list(out_candidates or []) + list(ready_library or [])
    for c in all_rows:
        saved = store.get(c["cid"]) or {}
        if saved.get("comments"):
            c["comments"] = saved["comments"]
        if saved.get("room_comments"):
            c["room_comments"] = saved["room_comments"]
        if saved.get("explainer"):
            c["explainer"] = saved["explainer"]   # ★解説(コピー部)。無ければ付けない=ページは fail-open で非表示
    # store を最新化して保存(durable=当日ファイルが消えても中身が生き残る)
    try:
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def review_of(info):
    rev = info.get("review") or {}
    c = dp.num(rev.get("count"))
    try: a = float(rev.get("average")) if rev.get("average") not in (None, "") else None
    except: a = None
    if c is None and a is None: return None
    return {"count": c, "average": a}

def main():
    w = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    today = datetime.date.today().isoformat()
    posted_any = dp.excluded_cids()          # 除外集合=直近3日∪直近10件(OR=どちらか該当で除外)
    last_posted, posted_ch_map = last_posted_by_channel()  # {cid:{date,channel}} / {cid:{acc1,acc2}}
    # ★『直近枠が開けば可』(Chami 2026-08-29)=ch別の"閉じている"集合。含まれない=そのchへ今すぐ可。
    closed_ch = {"acc1": dp.excluded_cids_ch("acc1"), "acc2": dp.excluded_cids_ch("acc2")}

    rows = dp.d1("SELECT cp.cid, cp.source, w.title, w.info_json, w.sales_n FROM candidate_pool cp "
                 "JOIN works w ON w.cid=cp.cid WHERE w.info_json IS NOT NULL AND w.info_json<>''")
    cand = []
    for r in rows:
        try: info = json.loads(r["info_json"])
        except: continue
        cid = r["cid"]
        imgs = images_of(info)
        if not imgs: continue                # 動画化の素材が無い=除外
        if cid in posted_any: continue       # 直近3日∪直近10件に該当=除外(OR=どちらか該当で除外)
        pr = info.get("prices") or {}
        price, lp = dp.num(pr.get("price")), dp.num(pr.get("list_price"))
        disc = round((lp - price) / lp * 100) if (price is not None and lp) else None
        rev = review_of(info)
        x = dict(cid=cid, title=r.get("title") or "", price=price, lp=lp, disc=disc,
                 rc=(rev or {}).get("count"), avg=(rev or {}).get("average"),
                 sales=r.get("sales_n"), imgs=len(imgs), src=r.get("source"),
                 _images=imgs, _review=rev, _platform=platform_of(cid))
        x["select_score"] = dp.score(x)                       # 候補入りの選定軸(価格/割引/実売/レビュー)
        x["rank_score"] = rank_score(cid, r.get("sales_n"))   # ★ページの並び順の正(分析確定式)
        cand.append(x)

    # ★並び順は分析 score(revenue_rate×log1p(sales_n))を正とする(設計書§3)。
    cand.sort(key=lambda x: (-x["rank_score"], -x["select_score"]))
    top = cand[:20]                          # ★物量=10→20(Chami 2026-08-23『3日経ったら別chで投稿できる物量』)

    # ★『この作品は○ch用』の割り当ては廃止(Chami『作品はどっちでも可』)。代わりに last_posted を持たせ、
    #   どちらのchにいつ投稿したかを表示=chの最終判断はページ側/Chami(channel_provisional も廃止)。
    out_candidates = []
    for i, x in enumerate(top):
        out_candidates.append({
            "id": f"cand-{i+1:03d}",
            "cid": x["cid"],
            "platform": x["_platform"],
            "title": x["title"],
            "last_posted": last_posted.get(x["cid"]),   # {date,channel} or None(未投稿)
            "posted_ch": {                              # ★追加のみ(既存フィールドは無変更・C-010)
                "acc1": posted_ch_map.get(x["cid"], {}).get("acc1"),
                "acc2": posted_ch_map.get(x["cid"], {}).get("acc2"),
            },
            "ready_ch": {                               # ★直近枠が開けば可(Chami 2026-08-29)= true=そのchへ今すぐ投稿可
                "acc1": x["cid"] not in closed_ch["acc1"],
                "acc2": x["cid"] not in closed_ch["acc2"],
            },
            "images": x["_images"],
            "metrics": {
                "sales_n": x["sales"],
                "review": x["_review"],       # FANZA実データ(有れば)。★並び順には使わない(分析確定)
                "price": x["price"], "list_price": x["lp"], "discount_pct": x["disc"],
                "revenue_rate": revenue_rate(x["cid"]),
                "score": x["rank_score"],     # ★ページの並び順の正=分析式 revenue_rate×log1p(sales_n)
                "select_score": x["select_score"],  # 商品選定の候補入り選定軸(価格/割引/実売/レビュー)
                "past_similar_recovery": None # ★成約は観測不可=分析が null 固定と確定
            },
            "manual": (x["src"] == "main"),
            "comments": []                    # visionが後で3択を埋める
        })

    # ★投稿用画像ありだが当日top20にいない作品も、PC側visionへ通すため別配列で配信する。
    #   candidatesへ混ぜるとpool選定とroom_comments必須ガードを変えてしまうため分離する。
    #   R2 stateが読めない日は空で継続し、前日の配信や既存20件を壊さない(fail-open)。
    sync_ready = load_ready_sync_library()
    work_rows = works_for_cids(sync_ready.keys()) if sync_ready else {}
    ready_library = build_ready_library(
        sync_ready, work_rows, posted_any, {c["cid"] for c in out_candidates},
        last_posted, posted_ch_map, closed_ch)

    # ★再生成で消さない: candidates/ready_library双方の充填済み内容をcidで持ち越す。
    carry_content(out_candidates, today, ready_library)

    # Books未収録(info_jsonが無い=title/販売数が引けない)を穴として明示(推測で埋めない)
    uncov = dp.d1("SELECT cp.cid FROM candidate_pool cp LEFT JOIN works w ON w.cid=cp.cid "
                  "WHERE cp.cid NOT LIKE 'd\\_%' ESCAPE '\\' AND (w.info_json IS NULL OR w.info_json='')")
    books_uncovered = [r["cid"] for r in uncov if r.get("cid")]

    doc = {
        "date": today,
        "generated_by": "product-scout/candidates_json.py",
        "note": ("並び順の正=分析 score(revenue_rate×log1p(sales_n))降順(設計書§3)。"
                 "select_score は商品選定の候補入り選定軸で、並び順には使わない。"
                 "作品はどっちのchでも可=ch割り当ては廃止。last_posted={date,channel} は各作品の最終投稿"
                 "(記録=posted_log・全期間・未投稿は null)。表示例『8/22 月詠み』。"
                 "posted_ch={acc1,acc2}(各cidの)は各chでの最終投稿日(YYYY-MM-DD・未投稿はnull)=ch別分岐の土台(追加のみ)。"
                 "ready_ch={acc1,acc2}(bool)は『直近枠が開けば可』(Chami 2026-08-29)=そのchへ今すぐ投稿可か"
                 "(true=そのchの直近3日∪直近10件に入っていない=枠が開いている)。ページはこれで共通/月詠み/酔桜を仕分ける。"
                 "past_similar_recovery は成約が観測不可=分析が null 固定と確定。comments は vision が後埋め。"
                 "あらすじ本文は配信しない(client面へ過激本文を出さない)=PC専用サイドカー synopsis_<date>.json 側に置く。"),
        "candidates": out_candidates,
        # 投稿用画像あり・当日top20外。vision_comments.pyは④commentsだけを空欄充填し、
        # KouhoTeian.htmlは端末内REFとcid一致したカードにこのメタ/3択を合流する。
        "ready_library": ready_library,
        "books_uncovered": books_uncovered,   # DB未収録のBooks cid(推測で埋めていない穴)
        # ★除外集合を候補ページへも渡す(直近3日∪直近10件=Chami裁定・OR)。候補JSONは既にこれで
        #   絞った物だが、候補ページ側は端末内ライブラリ(cand_items)を"今すぐ投稿できる"へ合流させる=
        #   合流分は生成側の除外を通らない。ここで同じ除外cidを配ってページ側の合流でも弾く(single-source)。
        #   出所=posted_log(全期間の投稿cidそのものではなく"直近窓"だけ・fail-openで空なら弾かない)。
        "excluded_cids": sorted(posted_any),
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"candidates_{today}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    # ── あらすじサイドカー(PC専用・配信しない) ─────────────────────────────
    # ★候補JSON本体には本文を載せない(publishが丸ごとR2へ上げる=client漏れ)。vision(改修α)は
    #   このサイドカーを cid で引いて判断材料にする。取得失敗は null=パイプラインは止めない(fail-open)。
    global SYN_CACHE
    SYN_CACHE = os.path.join(OUT_DIR, "synopsis_cache.json")
    try:
        with open(SYN_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    syn_map, got = {}, 0
    for c in out_candidates:
        cid = c["cid"]
        hit = bool(cache.get(cid))
        try:
            s = synopsis_for(cid, cache=cache)
        except Exception:
            s = None                      # ★1件の失敗で候補生成全体を落とさない
        syn_map[cid] = s
        if s:
            got += 1
        if not hit and page_url_for(cid):
            time.sleep(0.8)               # 実取得の時だけ間隔(cacheヒットは待たない)
    try:
        with open(SYN_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass
    syn_path = os.path.join(OUT_DIR, f"synopsis_{today}.json")
    with open(syn_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": today,
            "generated_by": "product-scout/candidates_json.py",
            "note": ("PC専用=R2/clientへは配信しない(過激本文をclient面へ出さない・表示もしない)。"
                     "vision(改修α)が cid で引いて④コメント生成の判断材料にする。取れなければ null。"),
            "synopsis": syn_map,          # {cid: 本文 or null}
        }, f, ensure_ascii=False, indent=2)

    w.write(f"wrote {path}\n候補{len(out_candidates)}件 / ready追加{len(ready_library)}件 / "
            f"Books未収録{len(books_uncovered)}件 / 母集団{len(cand)}件\n")
    w.write(f"wrote {syn_path}\nあらすじ取得 {got}/{len(out_candidates)} 件(取れない分は null=生成は継続)\n")
    w.flush()

if __name__ == "__main__":
    main()
