#!/usr/bin/env python3
"""Discordキャラ名義送信 (人格ごとの表示名/アイコンで発言。Bot1つで全キャラ対応)。

仕組み: 各チャンネルにWebhookを自動作成(初回のみ・要Manage Webhooks権限)し、
username/avatar_url上書きで送信する。Webhook URLは local/discord_webhooks_auto.json にキャッシュ。

使い方:
  python scripts/discord/persona_send.py --channel "研究室-コーチングルーム" --persona "アメス" "本文..."
  python scripts/discord/persona_send.py --dept qa-reviewer --persona "ジェンティルドンナ" --avatar https://... "本文"
  echo 本文 | python scripts/discord/persona_send.py --dept research-room --persona "シャビ・アロンソ"
  # 本文の渡し方は3通り: 裸の引数 / --body "<文章>" / --body-file <path>(長文・改行はこれが安全)
  # 色付きカード(Embed): --color red|orange|green|blue|grey|#RRGGBB [--etitle 見出し]
  python scripts/discord/persona_send.py --channel 報告-通知 --persona オタコン --color green --etitle "デプロイ完了" "本文"
本文はDiscordマークダウン対応(**太字** *斜体* __下線__ ~~打消~~ `code` > 引用 - リスト)。

アイコン: --avatar <画像URL> 省略可(省略時はDiscord既定アバター+キャラ名)。
         local/persona_avatars.json ({"アメス":"https://...", ...}) があれば自動適用。
"""
import json
import os
import re
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


def enlarge_headings(text, mark="**"):
    """embed descriptionの本文を読みやすくする(Chami指示2026-08-09・学習部屋だけ)。

    Discordの embed description は通常メッセージ本文より一段小さく描画される。
    文字を大きくする手段は見出し(`# `/`## `/`### `)しか無いが、最小のH3ですら
    Chamiに「まだ大きい」(msg=1536098736755834993・2026-08-09)=H3と普通の中間サイズは
    Discordに存在しない。よって★既定は太字(`**…**`)=大きさは普通のままだが、細い既定より
    はっきり読める(H2→H3→太字と一段ずつ下げてきた到達点)。もっと大きくしたい時は
    mark に "### "/"## " を渡せば見出し化する余地は残す。
    ★見出しカード化・全文の過剰装飾はしない(C-035)。
    既に見出し/引用/箇条書き等の構造行(先頭が # > - *、または番号付き "1." )や
    既に太字(`**`)を含む行は二重装飾で崩れるので触らない。空行も触らない(段落間隔を保つ)。
    ★字数は足す前提で呼び側が split_body(…, 4000) すること(4096上限の安全域)。
    """
    # mark が見出し(末尾スペース付き)なら行頭付与、そうでなければ太字で行を包む
    heading = mark.endswith(" ")
    out = []
    for ln in text.split("\n"):
        s = ln.lstrip()
        if not s:
            out.append(ln)                       # 空行=段落の切れ目。触らない
        elif s[0] in "#>-*" or re.match(r"\d+\.\s", s) or "**" in ln:
            out.append(ln)                       # 構造行/既に太字の行は素通し(二重装飾で崩れる)
        elif heading:
            out.append(mark + ln)                # 見出しモード=行頭に `### ` 等
        else:
            out.append(f"{mark}{ln}{mark}")      # 太字モード=行を `**…**` で包む
    return "\n".join(out)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # stdin もUTF-8に。Windowsの既定stdin=cp932のままだと `echo 日本語 | persona_send`
    # (パイプ経路)でUTF-8バイトをcp932誤デコード→日本語だけ文字化け(縺ヨ繧九…)する。
    # argv経路(CreateProcessWでUnicode渡し)は化けないが、stdin経路の根治にこれが必要(2026-07-15)。
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    # ★stderrもUTF-8へ(2026-07-28)。警告はここへ出しているのに、Windowsの既定stderr=cp932の
    #   ままだと**日本語の警告が文字化けして読めない**(実測)。「黙って壊れた本文を出さない」ための
    #   警告が読めなければ意味が無いので、出口の文字コードも揃える。
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
# ペルソナ台帳の正本=研究室HQ(2026-07-18移転・docs/departments/personas/README_移転.md)
_HQ_ROOT = os.environ.get("GO5_HQ_DIR") or os.path.normpath(
    os.path.join(os.path.dirname(ROOT), "00_AI-HQ"))
LOCAL = os.path.join(ROOT, "local")
HOOKS_CACHE = os.path.join(LOCAL, "discord_webhooks_auto.json")
AVATARS_FILE = os.path.join(LOCAL, "persona_avatars.json")
API = "https://discord.com/api/v10"


def _persona_aliases():
    """manifestの id(ラテン)→ name(かな)の別名表を作る(ames→アメス 等)。
    yaml非妥当なmanifestもあるので行テキストで拾う(他script同様)。"""
    import glob
    amap = {}
    # ★参照先は2箇所を見る(2026-07-22 hr-context・実測で塞いだ穴):
    #   ペルソナ台帳は2026-07-18にHQ(00_AI-HQ/departments/hr/personas)へ移転したが、
    #   ここはrepo側(docs/departments/personas)を見たままだった。移転後そこはREADMEのみ=
    #   **別名表が0件**になり、ames→アメスの解決(D1)が黙って死んでいた
    #   (resolve_personaが'ames'をそのまま返し、デフォルトアイコン+ラテン綴りで送られる事故の再来)。
    #   旧パスも残す=将来どちらに置かれても拾える(fail-safe)。
    bases = [os.path.join(_HQ_ROOT, "departments", "hr", "personas"),
             os.path.join(ROOT, "docs", "departments", "personas")]
    seen = set()
    for base in bases:
        for p in glob.glob(os.path.join(base, "**", "persona_manifest.yml"), recursive=True):
            if p in seen:
                continue
            seen.add(p)
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


# ★表記ゆれ→正式名(2026-07-28)。**人格設定は一切ここに書かない**(正本= persona_manifest.yml の `name:`)。
#   ここに載せるのは manifest から機械的に導けない**綴りの揺れ**だけ。
#   なぜ要るか= avatars.json は「同じ顔を別綴りでも出す」ために別名キーを持っている。
#   その結果 resolve_persona が別綴りをそのまま通し、**同じ人が別名義のwebhookで喋る**
#   (実測 2026-07-27: 1525646154933735425 に `ケヴィン・デ・ブライネ` と `デブライネ` の2本)。
#   ★アバター登録(avatars.json)は消さない= 別名でも顔は出る。名義だけを正式名へ寄せる。
_SPELLING_CANON = {
    "デ・ブライネ": "ケヴィン・デ・ブライネ",
    "ケヴィン・デブライネ": "ケヴィン・デ・ブライネ",
}


def _dept_conf_aliases():
    """DEPT_CONF の personas[].aliases → 正式名。**別名の正本はあそこ1本**(ORG-11)。

    ★2026-07-28 実測で足した。Chami=「さっきの咲季とかも差分の画像も出ない」。
      改修αに `咲季` 名義の投稿があり **avatar=None・07-28に新しいwebhookが生えていた**。
      原因= avatars.json のキーは `花海咲季` だけで、**短い呼び名 `咲季` では顔が引けない**。
      同じ形が `五月`(→中野五月) `シーナ`(→ヴィルシーナ) にもある(実測で未解決)。
      ★手で別名表に足すと**同じ表が2つ**になる。DEPT_CONF の personas[].aliases が既に
      「シーナ→ヴィルシーナ」を持っているので、**そこを引く**。
    ★重い import なので**引けなかった時だけ**呼ぶ(通常の送信は従来どおりの速さ)。
    ★失敗しても送信は続ける(顔が出ないだけ。黙って落とさない)。
    """
    out = {}
    try:
        import sys as _s
        _s.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        from dept_daemon import DEPT_CONF
    except Exception:
        return out
    for conf in DEPT_CONF.values():
        for p in (conf.get("personas") or ()):
            nm = p.get("persona")
            if not nm:
                continue
            for a in (p.get("aliases") or ()):
                if a and a != nm:
                    out.setdefault(str(a), nm)
        # personas を持たない部屋は persona 名そのものだけ(別名は無い)
    return out


def _canonical_names():
    """別名(display_name / ラテンid / 綴りの揺れ)→ 台帳の正式名。

    正本は persona_manifest.yml の `name:`。`display_name:`(Discord表示名)は
    system-engineer の `デブライネ` だけが持つ実測値なので、**この経路で効くのは
    デ・ブライネ1人**(他の人格の名義は1バイトも変わらない)。
    """
    canon = {}
    import glob
    bases = [os.path.join(_HQ_ROOT, "departments", "hr", "personas"),
             os.path.join(ROOT, "docs", "departments", "personas")]
    seen = set()
    for base in bases:
        for p in glob.glob(os.path.join(base, "**", "persona_manifest.yml"), recursive=True):
            if p in seen:
                continue
            seen.add(p)
            cur = {}
            try:
                for line in open(p, encoding="utf-8", errors="replace"):
                    s = line.strip()
                    if s.startswith("- id:"):
                        if cur.get("name"):
                            for a in (cur.get("id"), cur.get("display_name")):
                                if a and a != cur["name"]:
                                    canon[a] = cur["name"]
                        cur = {"id": s.split(":", 1)[1].strip()}
                    elif s.startswith("name:") and "display_name:" not in s:
                        cur["name"] = s.split(":", 1)[1].strip()
                    elif s.startswith("display_name:"):
                        # 行末コメント(# Discord等の表示名…)を落とす
                        cur["display_name"] = s.split(":", 1)[1].split("#", 1)[0].strip()
            except OSError:
                continue
            if cur.get("name"):
                for a in (cur.get("id"), cur.get("display_name")):
                    if a and a != cur["name"]:
                        canon[a] = cur["name"]
    canon.update(_SPELLING_CANON)
    return canon


def resolve_persona(name):
    """人格名を正規化する(QA D1・2026-07-18)。avatars.jsonのキーにあればそのまま。
    ラテンidなら manifestの かな名へ解決(ames→アメス)。未登録なら stderr へ大声で警告
    (=無人代打が persona=ames を渡してデフォルトアイコン+名前amesで黙って送っていた事故の根治)。
    喪失させないため送信自体は続行する(fail-open)。

    ★2026-07-28 追加: **正式名への寄せを avatars.json のキー判定より先に**行う。
      旧実装は「avatars.jsonにキーがあればそのまま」だったため、別名キー(`デブライネ`)が
      そのまま通り、同じ部屋に **2つの名義の webhook** が生まれていた(実測)。
    """
    canon = _canonical_names().get(name)
    if canon and canon != name:
        print(f"[persona_send] 正式名へ正規化: {name!r} -> {canon!r}"
              f"(正本= persona_manifest.yml の name:)", file=sys.stderr)
        return canon
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
    # ★ここまでで引けなかった時だけ DEPT_CONF の personas[].aliases を見る(2026-07-28)。
    #   呼び名(咲季 / 五月 / シーナ …)はあそこが正本。**別名表を2つ持たない**(ORG-11)。
    #   ★重いので最後の手段。通常の送信は上で解決して終わる。
    dmap = _dept_conf_aliases()
    if name in dmap:
        resolved = dmap[name]
        print(f"[persona_send] 呼び名を正式名へ: {name!r} -> {resolved!r}"
              f"(正本= DEPT_CONF の personas[].aliases)", file=sys.stderr)
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
            # ★再招待URLを案内しない (2026-07-19 Chami指摘): 再認可はbotロールの権限をURLの
            #   permissions値で**置き換える**ため、値が古いと既存権限 (リアクション等) が消える退行になる。
            #   安全なのはロール編集=既存に足すだけ。
            print("Webhook管理権限がありません。サーバー設定→ロール→botのロール(MultiAgent)→権限→"
                  "「ウェブフックの管理」をONにしてください(ロール編集は追加のみ=既存権限は減りません)。")
            sys.exit(3)
        raise
    url = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"
    cache[channel_id] = url
    with open(HOOKS_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    return url


PERSONA_HOOKS_CACHE = os.path.join(LOCAL, "discord_webhooks_personas.json")


def _avatar_data_uri(persona):
    """人格の標準アイコンをdata URIへ (Webhook自身のアバター設定用・作成時のみ)。失敗はNone (名前だけでも価値がある)。"""
    try:
        av = json.load(open(AVATARS_FILE, encoding="utf-8")).get(persona)
        if isinstance(av, list):
            av = av[0] if av else None
        if not av:
            return None
        import base64
        import subprocess
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".img")
        os.close(fd)
        try:
            r = subprocess.run(["curl", "-s", "-o", tmp, "--max-time", "15",
                                "--max-filesize", "8000000", av], capture_output=True, timeout=25)
            if r.returncode == 0 and os.path.getsize(tmp) > 0:
                data = open(tmp, "rb").read()
                mime = "image/png"
                if data[:3] == b"\xff\xd8\xff":
                    mime = "image/jpeg"
                elif data[:4] == b"RIFF":
                    mime = "image/webp"
                elif data[:6] in (b"GIF87a", b"GIF89a"):
                    mime = "image/gif"
                return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    except Exception:
        pass
    return None


def ensure_persona_webhook(channel_id, persona, token):
    """人格専用Webhookの取得/作成 (2026-07-18 Chami Go「タップで別人格が出る」の根治)。

    従来は全人格が1本のWebhook(go5-persona)を共有し、発言ごとに名前/アイコンを上書きしていた。
    Discordのプロフィール表示(タップ)はWebhook単位のため、直前に喋った別人格の姿が
    キャッシュ表示される事象が起きていた。人格ごとにWebhookを分ける(名前=人格名・
    Webhook自身のアバター=標準アイコン)ことで、タップ時も常に本人が出る。
    1ch上限15本到達や作成失敗時は従来の共有Webhookへフォールバック(fail-open=送信は死なせない)。
    """
    cache = {}
    if os.path.exists(PERSONA_HOOKS_CACHE):
        try:
            cache = json.load(open(PERSONA_HOOKS_CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    key = f"{channel_id}:{persona}"
    if key in cache:
        return cache[key]
    try:
        hooks = api(f"/channels/{channel_id}/webhooks", token)
        hook = next((h for h in hooks if h.get("name") == persona and h.get("token")), None)
        if not hook:
            payload = {"name": persona[:80]}
            uri = _avatar_data_uri(persona)
            if uri:
                payload["avatar"] = uri
            hook = api(f"/channels/{channel_id}/webhooks", token, payload)
    except urllib.error.HTTPError as e:
        # 403 (Webhook管理権限なし) でも従来の共有Webhookはキャッシュで生きている場合が多い。
        # ここでexitすると「昨日まで送れていた送信」を壊す退行になるため、必ずフォールバックする。
        # 人格別表示を有効化するにはbotへ「ウェブフックの管理」権限の再付与が要る (Chami作業・報告済)。
        print(f"[persona_send] 人格別Webhook不可(HTTP {e.code})→共有Webhookへフォールバック"
              + (" ※権限再付与で人格別が有効になる" if e.code == 403 else ""), file=sys.stderr)
        return ensure_webhook(channel_id, token)
    url = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"
    cache[key] = url
    with open(PERSONA_HOOKS_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    return url


COLORS = {"red": 0xED4245, "orange": 0xE67E22, "yellow": 0xFEE75C, "green": 0x57F287,
          "blue": 0x5865F2, "purple": 0x9B59B6, "grey": 0x95A5A6, "pink": 0xEB459E}

# 値を取らないフラグ(下の方で sys.argv から直接読んでいる)。★rest(=本文)へ混ぜない。
# --print-id: 投稿の実Discord message_idを stdout に `msg=<id>` で出す(?wait=true を強制)。
#   C-023(2026-07-30)で dispatch の実依頼を表投稿する時、そのIDでリアクションを着弾させるため。
#   通常のdept投稿はwait無しでIDを返さないので、この口を足した(mirror名義以外でもIDを取れる)。
_BARE_FLAGS = ("--nobold", "--silent", "--print-id", "--plain", "--big")
# 「未知のオプション」らしさの判定。`---`(Markdownの区切り線)や `--` 単体は本文なので除く。
_UNKNOWN_FLAG_RE = re.compile(r"^--[A-Za-z][A-Za-z0-9-]*$")


def sanitize_rest(rest):
    """本文に紛れ込んだ**未知の `--xxx`** を握りつぶさない(2026-07-28)。

    実測事故(2026-07-27 20:33 / 2026-07-28 00:29・5secシステム改修部門α):
      呼び側が `--body "対応しました(v=425)。…"` と叩いたが persona_send は `--body` を
      知らなかったため、`--body` という**文字列がそのまま本文の先頭**として投稿された。
      webhookは204を返すので送信側は成功と誤認し、**壊れた本文だけがChamiに見えていた**。
    → 方針:
      1) `--body` は正式に受け付ける(下の引数解析)。**呼び側は既にそう叩いている**ので素直。
      2) それでも残った未知の `--xxx` は **stderrへ大声で警告**する(黙って投稿しない)。
      3) **本文の先頭に来ている**未知フラグだけ落とす。本文が `--word` で始まることは
         実運用では無く、そこに居るのは十中八九「解析されなかったフラグ」だから。
         ★途中に出てくるものは**落とさない**(本文を削るほうが害が大きい=喪失させない)。
    """
    unknown = [t for t in rest if _UNKNOWN_FLAG_RE.match(t)]
    if not unknown:
        return rest
    print(f"[persona_send] ★警告: 未知の引数 {unknown} を本文として受け取った。"
          f"綴り間違い/未対応オプションの可能性がある(既知= --channel/--dept/--persona/"
          f"--suffix/--avatar/--color/--etitle/--body/--body-file/--nobold/--silent/--plain/--big)。",
          file=sys.stderr)
    out = list(rest)
    dropped = []
    while out and _UNKNOWN_FLAG_RE.match(out[0]):
        dropped.append(out.pop(0))
    if dropped:
        print(f"[persona_send] ★本文の先頭にあった {dropped} は投稿本文から外した"
              f"(引数の解析漏れとみなす)。", file=sys.stderr)
    return out


def main():
    args = sys.argv[1:]
    channel = dept = persona = avatar = color = etitle = body_file = None
    body_arg = None  # --body <文章>(2026-07-28 追加。sanitize_rest の説明を参照)
    suffix = ""      # 表示名にだけ足す肩書(例 "(常駐)")。人格の解決には使わない
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
        elif a == "--suffix" and i + 1 < len(args):
            suffix = args[i + 1]; i += 2      # 表示名の肩書のみ(アバター/色/webhookは素の人格名で引く)
        elif a == "--avatar" and i + 1 < len(args):
            avatar = args[i + 1]; i += 2
        elif a == "--color" and i + 1 < len(args):
            color = args[i + 1]; i += 2
        elif a == "--etitle" and i + 1 < len(args):
            etitle = args[i + 1]; i += 2
        elif a == "--body-file" and i + 1 < len(args):
            body_file = args[i + 1]; i += 2   # 本文をファイルから読む(heredoc/shell quoting崩れを回避=送信信頼性)
        elif a == "--body" and i + 1 < len(args):
            body_arg = args[i + 1]; i += 2    # 本文を引数で明示(2026-07-28。sanitize_rest の説明を参照)
        elif a in _BARE_FLAGS:
            i += 1                            # 値なしフラグ。後で sys.argv から読むのでここでは捨てる(本文へ混ぜない)
        else:
            rest.append(a); i += 1
    rest = sanitize_rest(rest)                # 未知の --xxx を黙って本文にしない(2026-07-28)
    if not persona or not (channel or dept):
        print("使い方: persona_send.py (--channel <名前> | --dept <slug>) --persona <キャラ名> [--avatar URL] [--body <文章> | --body-file path | 本文]")
        sys.exit(1)
    if body_file:
        body = open(body_file, "r", encoding="utf-8").read().strip()
    elif body_arg is not None:
        body = body_arg.strip()
        if rest:
            # --body と裸の本文が両方来た= 解析漏れの疑い。**捨てた側を必ず見せる**(黙って消さない)。
            print(f"[persona_send] ★警告: --body 以外にも本文らしき引数 {rest} が来たが、"
                  f"--body の内容を採用した。", file=sys.stderr)
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
    hook_url = ensure_persona_webhook(str(ch["id"]), persona, token)  # 人格別 (タップ表示の根治2026-07-18)
    # ★表示名だけに肩書を足す(2026-07-20 Chami指摘への対処)。
    #   「デーモンではない人格とデーモンである人格が同じ場合、どちらが言ったか判別がつかない」。
    #   ★suffixを persona 本体に混ぜてはいけない: アバター検索/色/webhookキーが全て
    #     その名前で引かれるため、混ぜるとアイコンが消え色も落ちる(=キャラが劣化する)。
    #     解決・アバター・色・webhookは**素の人格名**で行い、最後にusernameだけへ足す。
    display = f"{persona}{suffix}" if suffix else persona
    payload = {"username": display[:80]}
    plain = "--plain" in sys.argv   # 素の色モード= 左に色線だけ・本文は普通の文字(見出し化/太字化しない)
    plain_color = None              # embedは投稿段で本文チャンク毎に組む(長文で黙って切らないため)
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
        if plain:
            # 素の色モード(Chami指定2026-08-09 msg=1536092125127508029・学習部屋だけ):
            #   embed の左カラーバーだけ人格色。本文は description にそのまま=見出しにも太字にもしない。
            #   title無し=大文字の見出しカードにならない。長文は投稿段で split_body(4000) して連投
            #   (embed description上限4096字に対する安全域)=黙って切らない(INC-92を再発させない)。
            plain_color = c
        elif etitle:
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
    # ★--print-id: mirror名義でなくても実Discord msg_idを返す(C-023の実依頼表投稿用)。
    #   通知の抑制(4096)は付けない=実依頼は相手部門に気づいてほしいため。
    want_id = mirror or ("--print-id" in sys.argv)

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
        if plain_color is not None:
            # 素の色モード= embed{description:本文, color:人格色}(title無し/太字無し)を
            # 本文チャンク毎に1通ずつ。分割時の無音化・username変更は content 経路と同じ作法。
            base_silent = 4096 if (mirror or "--silent" in sys.argv) else 0
            # --big= 本文を"少し大きい普通の文字"にする(各行頭に `## `・Chami指示2026-08-09
            #   msg=1536095016634679307「標準だと字が小さくなるから大きくするように」・学習部屋だけ)。
            #   ★見出しカード化/全文太字化はしない(C-035)。分割は付与後の字数で行い黙って切らない。
            src = enlarge_headings(body) if "--big" in sys.argv else body
            for i, part in enumerate(split_body(src, 4000)):
                pl = {"username": display[:80],
                      "embeds": [{"description": part, "color": plain_color}]}
                if avatar:
                    pl["avatar_url"] = avatar
                fl = base_silent
                if i >= 1:
                    fl |= 4096  # 2通目以降は無音(1通目だけ通知・Chami指示2026-08-06)
                    pl["username"] = f"{display}(続き{i + 1})"[:80]  # 畳み解除でアイコン再表示
                if fl:
                    pl["flags"] = fl
                st, mid = post(pl, want_id=want_id)
                print(f"送信OK → {ch.get('name')} as {persona} (HTTP {st})"
                      + (f" msg={mid}" if mid else "") + (f" [{i+1}通目]" if i else ""))
                time.sleep(0.4)
        elif "embeds" in payload:
            st, mid = post(payload, want_id=want_id)
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
                # 分割連投は2通目以降を無音化する(Chami指示2026-08-06 msg=1534698298105925793:
                # 「同じ内容を分割して送信する時は通知や通知音は最初の1通目だけに」)。
                # 1通目=既存の通知挙動のまま / 2通目以降=SUPPRESS_NOTIFICATIONS(4096)を必ず立てる。
                # mirror/--silentで全通無音の場合は payload["flags"] が既に4096なので影響なし。
                if i >= 1:
                    pl["flags"] = pl.get("flags", 0) | 4096
                    # 2通目以降は username を変える(Chami指摘2026-08-06 msg=1534626915787472926:
                    # 「連投するとアイコンが見えなくてよくわからない」)。
                    # Discordは"同一webhook+同一username+同一avatar"が連続すると2通目以降の
                    # ヘッダー(名前とアイコン)を畳む。誰が喋っているか分からなくなるのはこれが原因。
                    # usernameを1文字でも変えると畳みが解けてアイコンが再表示される。
                    # avatar_urlは据え置き=同じ顔のまま「(続き2)」だけが付く。
                    pl["username"] = f"{display}(続き{i + 1})"[:80]
                st, mid = post(pl, want_id=want_id)
                print(f"送信OK → {ch.get('name')} as {persona} (HTTP {st})"
                      + (f" msg={mid}" if mid else "") + (f" [{i+1}通目]" if i else ""))
                time.sleep(0.4)  # webhookのレート制限を避ける
    except Exception as e:
        print(f"送信失敗: {type(e).__name__}")
        sys.exit(3)


if __name__ == "__main__":
    main()
