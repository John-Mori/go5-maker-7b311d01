#!/usr/bin/env python3
"""Discordキャラ名義送信 (人格ごとの表示名/アイコンで発言。Bot1つで全キャラ対応)。

仕組み: 各チャンネルにWebhookを自動作成(初回のみ・要Manage Webhooks権限)し、
username/avatar_url上書きで送信する。Webhook URLは local/discord_webhooks_auto.json にキャッシュ。

使い方:
  python scripts/discord/persona_send.py --channel "研究室-コーチングルーム" --persona "アメス" "本文..."
  python scripts/discord/persona_send.py --dept qa-reviewer --persona "ジェンティルドンナ" --avatar https://... "本文"
  echo 本文 | python scripts/discord/persona_send.py --dept research-room --persona "シャビ・アロンソ"
  # 色付きカード(Embed): --color red|orange|green|blue|grey|#RRGGBB [--etitle 見出し]
  python scripts/discord/persona_send.py --channel 報告-通知 --persona オタコン --color green --etitle "デプロイ完了" "本文"
本文はDiscordマークダウン対応(**太字** *斜体* __下線__ ~~打消~~ `code` > 引用 - リスト)。

アイコン: --avatar <画像URL> 省略可(省略時はDiscord既定アバター+キャラ名)。
         local/persona_avatars.json ({"アメス":"https://...", ...}) があれば自動適用。
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

LIMIT = 1900  # Discordの本文上限2000字に対する安全域


def split_body(text, limit=LIMIT):
    """長文をDiscordの上限内へ"意味の切れ目"で分割する(切り捨てない=INC-92)。

    優先順: 段落(空行) → 行 → 字数。
    旧実装は body[:1900] で黙って捨てており、webhookが204を返すため送信側は成功と誤認、
    Chamiには文の途中で切れたものが届いていた(実例=6452字が1900字で切れた)。
    """
    text = text.rstrip("\n")
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n\n"):
        piece = para if not cur else cur + "\n\n" + para
        if len(piece) <= limit:
            cur = piece
            continue
        if cur:
            parts.append(cur)
            cur = ""
        if len(para) <= limit:
            cur = para
            continue
        # 段落単体が長い→行で割る
        for ln in para.split("\n"):
            piece = ln if not cur else cur + "\n" + ln
            if len(piece) <= limit:
                cur = piece
                continue
            if cur:
                parts.append(cur)
                cur = ""
            # 行単体が長い→字数で割る(最後の手段)
            while len(ln) > limit:
                parts.append(ln[:limit])
                ln = ln[limit:]
            cur = ln
    if cur:
        parts.append(cur)
    return parts

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # stdin もUTF-8に。Windowsの既定stdin=cp932のままだと `echo 日本語 | persona_send`
    # (パイプ経路)でUTF-8バイトをcp932誤デコード→日本語だけ文字化け(縺ヨ繧九…)する。
    # argv経路(CreateProcessWでUnicode渡し)は化けないが、stdin経路の根治にこれが必要(2026-07-15)。
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
HOOKS_CACHE = os.path.join(LOCAL, "discord_webhooks_auto.json")
AVATARS_FILE = os.path.join(LOCAL, "persona_avatars.json")
API = "https://discord.com/api/v10"


def _persona_aliases():
    """manifestの id(ラテン)→ name(かな)の別名表を作る(ames→アメス 等)。
    yaml非妥当なmanifestもあるので行テキストで拾う(他script同様)。"""
    import glob
    amap = {}
    base = os.path.join(ROOT, "docs", "departments", "personas")
    for p in glob.glob(os.path.join(base, "**", "persona_manifest.yml"), recursive=True):
        cur_id = None
        try:
            for line in open(p, encoding="utf-8", errors="replace"):
                s = line.strip()
                if s.startswith("- id:") or (s.startswith("id:") and cur_id is None):
                    cur_id = s.split(":", 1)[1].strip()
                elif s.startswith("name:") and cur_id:
                    nm = s.split(":", 1)[1].strip()
                    if cur_id and nm:
                        amap[cur_id] = nm
                    cur_id = None
        except OSError:
            continue
    return amap


def resolve_persona(name):
    """人格名を正規化する(QA D1・2026-07-18)。avatars.jsonのキーにあればそのまま。
    ラテンidなら manifestの かな名へ解決(ames→アメス)。未登録なら stderr へ大声で警告
    (=無人代打が persona=ames を渡してデフォルトアイコン+名前amesで黙って送っていた事故の根治)。
    喪失させないため送信自体は続行する(fail-open)。"""
    known = set()
    if os.path.exists(AVATARS_FILE):
        try:
            known = set(json.load(open(AVATARS_FILE, encoding="utf-8")).keys())
        except Exception:
            pass
    if name in known:
        return name
    amap = _persona_aliases()
    if name in amap:
        resolved = amap[name]
        print(f"[persona_send] 別名解決: {name!r} -> {resolved!r}", file=sys.stderr)
        return resolved
    if known:
        print(f"[persona_send] ★警告: 未登録の人格名 {name!r}(avatars.jsonにキー無し・別名表にも無し)。"
              f"このままだとデフォルトアイコン+その綴りの表示名で送られます。"
              f"ラテン綴りなら かな名で渡し直してください。", file=sys.stderr)
    return name


def api(path, token, payload=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Authorization": "Bot " + token, "Content-Type": "application/json",
                 "User-Agent": "go5-org-persona (personal, v1)"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_webhook(channel_id, token):
    cache = {}
    if os.path.exists(HOOKS_CACHE):
        with open(HOOKS_CACHE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    if channel_id in cache:
        return cache[channel_id]
    try:
        hooks = api(f"/channels/{channel_id}/webhooks", token)
        hook = next((h for h in hooks if h.get("name") == "go5-persona" and h.get("token")), None)
        if not hook:
            hook = api(f"/channels/{channel_id}/webhooks", token, {"name": "go5-persona"})
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("Webhook管理権限がありません。再招待URL(Manage Webhooks追加済み)を開いて認証し直してください:")
            print("https://discord.com/oauth2/authorize?client_id=1525787101055160360&scope=bot&permissions=536939520")
            sys.exit(3)
        raise
    url = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"
    cache[channel_id] = url
    with open(HOOKS_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    return url


COLORS = {"red": 0xED4245, "orange": 0xE67E22, "yellow": 0xFEE75C, "green": 0x57F287,
          "blue": 0x5865F2, "purple": 0x9B59B6, "grey": 0x95A5A6, "pink": 0xEB459E}


def main():
    args = sys.argv[1:]
    channel = dept = persona = avatar = color = etitle = body_file = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--channel" and i + 1 < len(args):
            channel = args[i + 1]; i += 2
        elif a == "--dept" and i + 1 < len(args):
            dept = args[i + 1]; i += 2
        elif a == "--persona" and i + 1 < len(args):
            persona = args[i + 1]; i += 2
        elif a == "--avatar" and i + 1 < len(args):
            avatar = args[i + 1]; i += 2
        elif a == "--color" and i + 1 < len(args):
            color = args[i + 1]; i += 2
        elif a == "--etitle" and i + 1 < len(args):
            etitle = args[i + 1]; i += 2
        elif a == "--body-file" and i + 1 < len(args):
            body_file = args[i + 1]; i += 2   # 本文をファイルから読む(heredoc/shell quoting崩れを回避=送信信頼性)
        else:
            rest.append(a); i += 1
    if not persona or not (channel or dept):
        print("使い方: persona_send.py (--channel <名前> | --dept <slug>) --persona <キャラ名> [--avatar URL] [--body-file path | 本文]")
        sys.exit(1)
    if body_file:
        body = open(body_file, "r", encoding="utf-8").read().strip()
    else:
        body = " ".join(rest) if rest else sys.stdin.read().strip()
    if not body:
        print("本文が空です。")
        sys.exit(1)
    with open(os.path.join(LOCAL, "discord_bot_token.txt"), "r", encoding="utf-8") as f:
        token = f.read().strip()
    with open(os.path.join(LOCAL, "discord_channels.json"), "r", encoding="utf-8") as f:
        channels = json.load(f)
    field, key = ("name", channel) if channel else ("dept", dept)
    ch = next((c for c in channels if c.get(field) == key and str(c.get("id", "")).strip().isdigit()), None)
    if not ch:
        print(f"チャンネル未登録: {key}")
        sys.exit(2)
    persona = resolve_persona(persona)  # QA D1: ames→アメス等の別名解決+未登録は大声警告
    if not avatar and os.path.exists(AVATARS_FILE):
        with open(AVATARS_FILE, "r", encoding="utf-8") as f:
            avatar = json.load(f).get(persona)
        if isinstance(avatar, list) and avatar:
            # ランダムアバター(咲季方式・Chami指定2026-07-13): 毎回ランダム・ただし2回連続同じ画像は禁止
            import random
            last_p = os.path.join(LOCAL, "persona_avatar_last.json")
            last = {}
            try:
                last = json.load(open(last_p, encoding="utf-8"))
            except Exception:
                pass
            cands = [u for u in avatar if u != last.get(persona)] or avatar
            avatar = random.choice(cands)
            last[persona] = avatar
            with open(last_p, "w", encoding="utf-8") as f:
                json.dump(last, f, ensure_ascii=False, indent=1)
    hook_url = ensure_webhook(str(ch["id"]), token)
    payload = {"username": persona[:80]}
    if color == "auto":
        # 話者のテーマカラー(local/persona_colors.json)で送る。未定義なら通常メッセージにフォールバック
        try:
            color = json.load(open(os.path.join(LOCAL, "persona_colors.json"), encoding="utf-8")).get(persona)
        except Exception:
            color = None
    if color:
        c = COLORS.get(color.lower())
        if c is None:
            try:
                c = int(color.lstrip("#"), 16)
            except ValueError:
                c = COLORS["blue"]
        if etitle:
            # 明示見出しモード: 見出し+太字本文(--nobold で太字解除)
            desc = body[:3900]
            if "--nobold" not in sys.argv:
                desc = "\n".join(
                    (f"**{ln}**" if ln.strip() and "**" not in ln else ln) for ln in desc.splitlines())
            payload["embeds"] = [{"title": etitle[:250], "description": desc[:4000], "color": c}]
        else:
            # 全文見出しモード(Chami指定2026-07-13): 本文を丸ごと見出し(大きい文字)で出す。
            # 見出しは256字制限+マークダウン非対応のため、装飾を除去し段落単位で複数カードに分割(最大10)。
            plain = body.replace("**", "").replace("__", "")
            chunks, cur = [], ""
            for ln in plain.splitlines():
                ln = ln.rstrip()
                if not ln:
                    if cur:
                        chunks.append(cur); cur = ""
                    continue
                while len(ln) > 240:
                    if cur:
                        chunks.append(cur); cur = ""
                    chunks.append(ln[:240]); ln = ln[240:]
                cur = (cur + "\n" + ln) if cur and len(cur) + len(ln) < 230 else (chunks.append(cur) or ln if cur else ln)
            if cur:
                chunks.append(cur)
            embs = [{"title": ch[:250], "color": c} for ch in chunks[:10]]
            rest = "\n".join(chunks[10:])
            if rest:
                embs[-1]["description"] = ("**" + rest[:3800] + "**")
            payload["embeds"] = embs
    if avatar:
        payload["avatar_url"] = avatar

    # ミラー名義 (Chami(from Claude)/Chami(音声入力)等) は通知を鳴らさない (Chami指示2026-07-18:
    # 「自分の発言だし通知消したい」)。専用bot新設は不要 — Discordのサイレントフラグ
    # (SUPPRESS_NOTIFICATIONS=4096) で同じ目的を達成する (メッセージは普通に見え、通知だけ出ない)。
    # あわせて wait=true で送信結果のmsg_idを取得し表示する=貼った本人が既読/着手印を押せるように。
    mirror = persona.startswith("Chami(")
    if mirror or "--silent" in sys.argv:
        payload["flags"] = 4096

    def post(pl, want_id=False):
        url = hook_url + ("?wait=true" if want_id else "")
        req = urllib.request.Request(
            url, data=json.dumps(pl).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "go5-org-persona (personal, v1)"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            if want_id:
                try:
                    data = json.loads(r.read().decode("utf-8"))
                    return r.status, str(data.get("id", ""))
                except ValueError:
                    return r.status, ""
            return r.status, ""

    try:
        if "embeds" in payload:
            st, mid = post(payload, want_id=mirror)
            print(f"送信OK → {ch.get('name')} as {persona} (HTTP {st})" + (f" msg={mid}" if mid else ""))
        else:
            # 長文は切り捨てず"分割して連投"する(2026-07-17・INC-92)。
            # 旧実装は body[:1900] で黙って捨てていた: Discordの上限は2000字だが、
            # webhookはHTTP 204を返すので送信側は成功と誤認し、Chamiには文の途中で
            # 切れたものが届いていた(実例=アメスの6452字が1900字で切れ「途中で話止まってるぜ?」)。
            # 段落(空行)優先→行→字数の順で切れ目を選び、意味の切れ目で分ける。
            for i, part in enumerate(split_body(body)):
                pl = dict(payload)
                pl["content"] = part
                st, mid = post(pl, want_id=mirror)
                print(f"送信OK → {ch.get('name')} as {persona} (HTTP {st})"
                      + (f" msg={mid}" if mid else "") + (f" [{i+1}通目]" if i else ""))
                time.sleep(0.4)  # webhookのレート制限を避ける
    except Exception as e:
        print(f"送信失敗: {type(e).__name__}")
        sys.exit(3)


if __name__ == "__main__":
    main()
