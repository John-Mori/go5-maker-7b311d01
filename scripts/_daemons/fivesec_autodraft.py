"""β-5c: 朝の無人ドラフト自動作成の起動係(設計_無人ドラフト自動作成_20261024.md)。

5S部門が書いた LocalData/fivesec/daily_pick_YYYYMMDD.json の各作品について、
本番ページ(専用プロファイルの Chrome)で FivesecAutoDraft.run(spec) を1本ずつ呼び、ドラフトを作る。

- 台帳 LocalData/fivesec/autodraft_ledger_YYYYMMDD.json に作品ごとの試行回数と結果を残す。
  30分おきに何度起こされても、済んだ作品は飛ばし、1作品3回まで。
- cloud:false(R2に実体が見えない)は失敗に数える。同期が未設定で --allow-no-sync の時だけ cloud を問わない
  (Chamiが⚙の2欄を入れるまではスマホから見えないドラフトになる=5S部門 了承済み)。
- 画像(hook.url)はPython側で落としてから b64 でページへ渡す(ページから外部へは取りに行かない)。
- 本番に FivesecAutoDraft.version が無い(=旧デプロイ)なら作らずに止めて知らせる。
- 知らせは 5S部門(fivesecmm)へ1日に 成功1回・失敗1回まで。
- sync token はページ内の Go5Sync が持つ。ここでは configured() の真偽だけを見て、中身は読まない。
"""
import argparse
import base64
import datetime
import json
import os
import subprocess
import sys
import urllib.request

PROD_URL = "https://john-mori.github.io/go5-maker-7b311d01/"
LOCAL_ROOT = r"D:\SougouStartFolder\LocalData\fivesec"
PROFILE = r"D:\SougouStartFolder\LocalData\fivesec_autodraft_profile"
IMG_DIR = os.path.join(LOCAL_ROOT, "autodraft_img")
LOG_PATH = os.path.join(LOCAL_ROOT, "autodraft.log")
DISPATCH = r"D:\SougouStartFolder\5SecMovieMaker\scripts\llm\dispatch.py"
MAX_ATTEMPTS = 3
MAX_RUN_ERRORS = 3
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(rec):
    os.makedirs(LOCAL_ROOT, exist_ok=True)
    line = json.dumps(dict({"at": now_iso()}, **rec), ensure_ascii=False)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def ledger_path(date):
    return os.path.join(LOCAL_ROOT, f"autodraft_ledger_{date}.json")


def load_ledger(date):
    p = ledger_path(date)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"date": date, "items": {}, "run_errors": [], "notified": {"ok": False, "fail": False}}


def save_ledger(led):
    p = ledger_path(led["date"])
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def fetch_image(cid, url, date):
    os.makedirs(IMG_DIR, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1].lower() or ".jpg"
    path = os.path.join(IMG_DIR, f"{date}_{cid}{ext}")
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if len(data) < 1024:
            raise ValueError(f"image too small ({len(data)}B)")
        with open(path, "wb") as f:
            f.write(data)
    with open(path, "rb") as f:
        data = f.read()
    mime = "image/png" if ext == ".png" else "image/webp" if ext == ".webp" else "image/jpeg"
    return {"b64": base64.b64encode(data).decode("ascii"), "type": mime, "name": os.path.basename(path)}


# daily_pick の1作品 → FivesecAutoDraft.run の spec。#top に載る題名は titles[0]、残りは見直し用の別題。
def to_spec(item, date, test):
    titles = [str(t.get("text", "")) for t in (item.get("titles") or []) if t.get("text")]
    hook = item.get("hook") or {}
    return {
        "cid": item["cid"], "date": date, "rank": int(item.get("rank") or 0),
        "title": titles[0] if titles else "", "circle": item.get("circle", ""),
        "workUrl": item.get("work_url", ""), "altTitles": titles[1:],
        "hookNote": hook.get("note", ""), "test": bool(test),
    }


def item_done(st):
    return bool(st and (st.get("ok") or st.get("attempts", 0) >= MAX_ATTEMPTS))


def notify(body, dry_run):
    cmd = [sys.executable, DISPATCH, "--dept", "fivesecmm", "--from-dept", "system-engineer",
           "--from", "オタコン", "--audience", "ai", "--direct", "--body", body]
    if dry_run:
        cmd.append("--dry-run")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"rc": r.returncode, "dry_run": dry_run, "tail": (r.stdout + r.stderr).strip()[-200:]}


def summary_lines(led):
    out = []
    for cid, st in sorted(led["items"].items(), key=lambda kv: kv[1].get("rank", 0)):
        if st.get("ok"):
            out.append(f"{st.get('rank')}位 {cid}: stockId={st.get('id')} cloud={st.get('cloud')} ({st.get('at')})")
        else:
            out.append(f"{st.get('rank')}位 {cid}: 失敗 {st.get('attempts')}回 理由={st.get('reason')} {st.get('detail', '')[:80]}")
    return out


def maybe_notify(led, kind, head, a):
    if not a.notify or led["notified"].get(kind):
        return
    body = (f"[β-5c 無人ドラフト・改修β] {head}\n" + "\n".join(summary_lines(led)) +
            f"\n台帳= {ledger_path(led['date'])}(--direct: 5S部門のおすすめから作った結果返し)")
    led["notified"][kind] = notify(body, a.dry_run) | {"at": now_iso()}
    save_ledger(led)


def run_error(led, reason, detail, a, fatal=False):
    led["run_errors"].append({"at": now_iso(), "reason": reason, "detail": detail[:300]})
    save_ledger(led)
    log({"run_error": reason, "detail": detail[:300]})
    if fatal or len(led["run_errors"]) >= MAX_RUN_ERRORS:
        maybe_notify(led, "fail", f"{led['date']} の自動ドラフトを作れていない: {reason} {detail[:160]}", a)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y%m%d"))
    ap.add_argument("--json", default=None, help="入力(既定 LocalData/fivesec/daily_pick_<date>.json)")
    ap.add_argument("--profile", default=PROFILE)
    ap.add_argument("--url", default=PROD_URL)
    ap.add_argument("--allow-no-sync", action="store_true", help="同期未設定でも作る(cloud は問わない)")
    ap.add_argument("--test", action="store_true", help="アプリの testMode で作る")
    ap.add_argument("--limit", type=int, default=0, help="先頭から何作品まで(0=全部)")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--notify", action="store_true", help="5S部門へ知らせる(成功1回・失敗1回/日)")
    ap.add_argument("--dry-run", action="store_true", help="知らせを dispatch --dry-run にする")
    a = ap.parse_args()

    os.makedirs(LOCAL_ROOT, exist_ok=True)
    led = load_ledger(a.date)
    src = a.json or os.path.join(LOCAL_ROOT, f"daily_pick_{a.date}.json")
    if not os.path.exists(src):
        if led["items"] and all(item_done(s) for s in led["items"].values()):
            log({"date": a.date, "skip": "all_done_no_input"})
            return 0
        return run_error(led, "no_input", f"{src} が無い(daily_pick_手順.md の9.)", a)
    with open(src, encoding="utf-8") as f:
        pick = json.load(f)
    items = sorted(pick.get("items") or [], key=lambda i: int(i.get("rank") or 0))
    if a.limit:
        items = items[:a.limit]
    for it in items:
        led["items"].setdefault(it["cid"], {"rank": int(it.get("rank") or 0), "attempts": 0, "ok": False})
    todo = [it for it in items if not item_done(led["items"][it["cid"]])]
    if not todo:
        log({"date": a.date, "skip": "all_done"})
        return 0

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            args = ["--autoplay-policy=no-user-gesture-required"]
            if a.headful:
                args.append("--window-position=-32000,0")
            ctx = p.chromium.launch_persistent_context(
                a.profile, channel="chrome", headless=not a.headful, args=args,
                viewport={"width": 430, "height": 900})
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                # 作成後はドラフト一覧が前面になり go5_active_tab='tabStock' が残る=次に開くと Stock.html へ飛ぶ。
                # 動画作成タブで開き直す(アプリ側の挙動は変えない)。
                page.add_init_script("try{ if(!/Stock|StockLists/.test(location.pathname)) localStorage.setItem('go5_active_tab','tabMovie'); }catch(e){}")

                def open_app():
                    page.goto(a.url, wait_until="load", timeout=60000)
                    page.wait_for_function("() => window.FivesecAutoDraft && window.FivesecAutoDraft.version >= 1",
                                           timeout=30000)

                try:
                    open_app()
                except Exception:
                    return run_error(led, "version_missing",
                                     f"本番に FivesecAutoDraft.version が無い(旧デプロイ) url={page.url}", a, fatal=True)
                ver = page.evaluate("() => FivesecAutoDraft.version")
                configured = page.evaluate("() => !!(window.Go5Sync && Go5Sync.configured && Go5Sync.configured())")
                log({"date": a.date, "ver": ver, "configured": configured, "todo": [i["cid"] for i in todo]})
                if not configured and not a.allow_no_sync:
                    return run_error(led, "sync_unconfigured", "専用プロファイルの⚙同期2欄が未入力", a, fatal=True)
                for n, it in enumerate(todo):
                    if n:
                        open_app()  # 1本ごとに動画作成タブから開き直す(前の作品の一覧表示・入力を持ち越さない)
                    st = led["items"][it["cid"]]
                    st["attempts"] += 1
                    st["at"] = now_iso()
                    try:
                        hook = it.get("hook") or {}
                        if not hook.get("url"):
                            raise ValueError("hook.url が無い")
                        spec = to_spec(it, a.date, a.test)
                        spec["image"] = fetch_image(it["cid"], hook["url"], a.date)
                        if not configured:
                            spec["allowNoSync"] = True
                        r = page.evaluate("(s) => FivesecAutoDraft.run(s)", spec)
                    except Exception as e:  # noqa: BLE001 - 作品単位で記録して次へ
                        r = {"ok": False, "reason": "runner", "detail": f"{type(e).__name__}: {str(e)[:200]}"}
                    r = r or {"ok": False, "reason": "empty"}
                    # 同期が入っているのに R2 に見えないのは失敗。未設定(--allow-no-sync で通した時)だけ cloud を問わない
                    ok = bool(r.get("ok")) and (r.get("cloud") is True or not configured)
                    st.update({"ok": ok, "id": r.get("id"), "cloud": r.get("cloud"), "dup": bool(r.get("dup")),
                               "reason": None if ok else (r.get("reason") or "cloud_false"),
                               "detail": str(r.get("detail") or "")})
                    save_ledger(led)
                    log({"date": a.date, "cid": it["cid"], "attempt": st["attempts"], "result": {k: v for k, v in r.items() if k != "detail"}, "ok": ok})
                if configured:
                    try:
                        page.evaluate("() => Go5Sync.flushSync && Go5Sync.flushSync()")
                        page.wait_for_timeout(3000)
                    except Exception as e:  # noqa: BLE001
                        log({"flush_error": f"{type(e).__name__}: {str(e)[:200]}"})
            finally:
                ctx.close()
    except Exception as e:  # noqa: BLE001 - プロファイルが開いている等
        return run_error(led, "launch", f"{type(e).__name__}: {str(e)[:240]}", a)

    states = [led["items"][it["cid"]] for it in items]
    if all(item_done(s) for s in states):
        if all(s.get("ok") for s in states):
            maybe_notify(led, "ok", f"{a.date} のおすすめ{len(states)}本をドラフトに入れた。", a)
        else:
            maybe_notify(led, "fail", f"{a.date} のおすすめのうち作れなかった作品がある。", a)
    return 0 if all(s.get("ok") for s in states) else 1


if __name__ == "__main__":
    sys.exit(main())
