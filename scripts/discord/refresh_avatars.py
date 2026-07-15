#!/usr/bin/env python3
"""persona_avatars.json のDiscord CDNアバターURLを一括で再署名(refresh)する。

背景(2026-07-15 INC・タスク8):
  Discordの添付CDN URLは署名付き(?ex=失効時刻)で、数十時間〜数日で失効する。
  失効するとpersona_send.pyのwebhookアバターもオフィス(build_office.py)のサムネも
  404で表示されなくなる(デブライネのIMG_0962が実際に失効=プロフィール未表示)。
  Discord API `POST /attachments/refresh-urls` は、元の添付メッセージが削除されていない限り
  失効URLでも新しい署名URLを返す。これを全アバターへ回すことで表示を回復・維持する。

使い方:
  python scripts/discord/refresh_avatars.py            # 失効(または残り寿命<48h)のみ再署名
  python scripts/discord/refresh_avatars.py --all      # 全URLを再署名
  python scripts/discord/refresh_avatars.py --check     # 到達性チェックのみ(書き換えない)

恒久運用: セッション開始時や1日1回このスクリプトを回せば、メッセージを消さない限りアバターは維持される。
  真の恒久化(R2等へ画像を落として自前ホスト)は別TODO。ここはDiscordのAPI内で完結する回復策。
"""
import argparse
import json
import os
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
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
AVATARS = os.path.join(LOCAL, "persona_avatars.json")
API = "https://discord.com/api/v10"
CDN = "https://cdn.discordapp.com/"
REFRESH_MARGIN = 48 * 3600  # 残り寿命がこれ未満なら先回りで再署名


def token():
    return open(os.path.join(LOCAL, "discord_bot_token.txt"), encoding="utf-8").read().strip()


def expiry_of(url):
    """URLの ?ex= (16進Unix秒) を返す。無ければNone。"""
    try:
        q = url.split("?", 1)[1]
        for kv in q.split("&"):
            if kv.startswith("ex="):
                return int(kv[3:], 16)
    except Exception:
        pass
    return None


def iter_urls(avatars):
    """(persona, index or None, url) を列挙。indexはlist内位置(str型は None)。"""
    for persona, v in avatars.items():
        if isinstance(v, str):
            yield persona, None, v
        elif isinstance(v, list):
            for i, u in enumerate(v):
                yield persona, i, u


def reachable(url):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def refresh_batch(urls, tok):
    """refresh-urls APIで一括再署名。{original: refreshed} を返す。"""
    out = {}
    # APIは一度に多数受けるが、安全のため50件ずつ
    for i in range(0, len(urls), 50):
        chunk = urls[i:i + 50]
        body = json.dumps({"attachment_urls": chunk}).encode()
        req = urllib.request.Request(API + "/attachments/refresh-urls", data=body,
                                     headers={"Authorization": "Bot " + tok,
                                              "Content-Type": "application/json",
                                              "User-Agent": "go5-org refresh (personal)"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
            for pair in data.get("refreshed_urls", []):
                out[pair["original"]] = pair["refreshed"]
        except urllib.error.HTTPError as e:
            print(f"  refresh失敗 HTTP {e.code}: {e.read()[:200]!r}")
        time.sleep(0.3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全URLを再署名(既定は失効/残り<48hのみ)")
    ap.add_argument("--check", action="store_true", help="到達性チェックのみ(書き換えない)")
    args = ap.parse_args()

    avatars = json.load(open(AVATARS, encoding="utf-8"))
    now = time.time()

    if args.check:
        ng = 0
        for persona, idx, url in iter_urls(avatars):
            if CDN not in url:
                continue
            ok = reachable(url)
            if not ok:
                ng += 1
                where = persona if idx is None else f"{persona}[{idx}]"
                print(f"  ✗ {where}: 到達不可(失効の可能性)")
        print(f"チェック完了: 到達不可 {ng} 件")
        return 0

    targets = []
    for persona, idx, url in iter_urls(avatars):
        if CDN not in url:
            continue
        exp = expiry_of(url)
        need = args.all or exp is None or (exp - now) < REFRESH_MARGIN
        if need:
            targets.append(url)
    targets = list(dict.fromkeys(targets))  # 重複除去
    if not targets:
        print("再署名が必要なURLはありません(全て十分な残り寿命)。")
        return 0

    print(f"再署名対象: {len(targets)} 件 → Discord refresh-urls")
    mapping = refresh_batch(targets, token())
    if not mapping:
        print("再署名結果が空でした(メッセージ削除済み等)。手動でアバター再投稿が必要かもしれません。")
        return 1

    # 書き戻し
    changed = 0
    for persona, v in list(avatars.items()):
        if isinstance(v, str):
            if v in mapping:
                avatars[persona] = mapping[v]; changed += 1
        elif isinstance(v, list):
            for i, u in enumerate(v):
                if u in mapping:
                    v[i] = mapping[u]; changed += 1
    with open(AVATARS, "w", encoding="utf-8") as f:
        json.dump(avatars, f, ensure_ascii=False, indent=1)
    print(f"更新完了: {changed} 件のURLを再署名して書き戻しました。(persona_avatars.json)")
    miss = [u for u in targets if u not in mapping]
    if miss:
        print(f"  ※ {len(miss)} 件は再署名できず(元メッセージ削除の可能性)=手動再投稿が必要")
    return 0


if __name__ == "__main__":
    sys.exit(main())
