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
import random          # ★口調監査の突合キー audit_id を作るため(2026-09-16)
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
    # ★空行(=文の代わりの余白)が大きいとChami(msg=1536099144203108412・2026-08-09)。
    #   連続する空行を1つの改行へ畳んで縦の隙間を詰める(段落の大きな余白を出さない)。
    return re.sub(r"\n(?:[ \t]*\n)+", "\n", "\n".join(out))

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
#   ★2026-08-15 向きを反転した。人事部門の裁定で **正= ケヴィン・デブライネ(中黒なし)** に確定
#   (共通規律§5「デブライネは中黒なし」/ 呼称ルール.json・ROSTER.md・debruyne.md と一致)。
#   反転前はこの表が送信直前に **中黒なし→中黒あり** へ書き戻しており、上流(org_registry・
#   口調ルール)をいくら正へ寄せても **Discordに出る名義だけが旧綴りに戻っていた**(実測)。
_SPELLING_CANON = {
    "デ・ブライネ": "ケヴィン・デブライネ",
    "デブライネ": "ケヴィン・デブライネ",
    "ケヴィン・デ・ブライネ": "ケヴィン・デブライネ",
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
    # ★最後の手段: 同形異字(ホモグリフ)で化けた名義を正名へ寄せる(2026-09-04)。
    #   `[ККール]`(キリルК U+041A) / `[KKール]`(ラテンK) が別名表のどれにも当たらず、
    #   化けた綴りのまま username に載って Chami の画面が「(KKール)」になっていた。
    #   一意に決まる時だけ寄せる= 2人に当たる字面は化けたまま出す(取り違えない)。
    fixed, why = _homo_canon(name, known | set(_canonical_names().values()) if known else None)
    if fixed and fixed != name:
        print(f"[persona_send] 同形異字を正名へ: {name!r} -> {fixed!r}({why})", file=sys.stderr)
        return fixed
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
# --print-id: 投稿の実Discord message_idを stdout に `msg=<id>` で出す。
#   C-023(2026-07-30)で dispatch の実依頼を表投稿する時、そのIDでリアクションを着弾させるため。
#   ★2026-09-03 以降は**全便でIDを取る**ので、このフラグを付けても挙動は変わらない
#   (既存の呼び出し元 dispatch.py が渡してくるので、本文へ混ざらないようここに残す)。
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


ENGLISH_AUDIT = os.path.join(LOCAL, "llm", "english_audit.jsonl")
# 口調監査は dept_daemon と同じ1本(event=tone_fix/tone)。記録先を2つ持たない(§4)。
TONE_AUDIT = os.path.join(LOCAL, "llm", "tone_audit.jsonl")
# 口調ルールの正本=研究室HQ(ORG-11)。dept_daemon の TONE_RULES_PATH と同じ1本。
TONE_RULES_PATH = os.path.join(_HQ_ROOT, "departments", "hr", "personas", "口調ルール.json")

# ==== 突合キー audit_id(2026-09-16・AD研究室 msg 1549614905580068977 ④)==============
#   ★実測= tone_audit.jsonl の event=tone_fix 173行のうち **24行に msg_id が無い**(13.9%)。
#     全部この persona_send が書いた行だ。理由は単純で、**ゲートを当てる時点では
#     DiscordのIDがまだ存在しない**(IDは投稿のレスポンスで初めて返る)。
#   ★だから「後から入れる」のではなく、**先に自分で鍵を作る**=
#     ゲートを当てた瞬間に audit_id を1つ発行して全行に載せ、投稿が成功したら
#     `event=audit_link` で audit_id ↔ msg_id を1行残す。2本を鍵で繋ぐ。
#   ★分割連投(1本の本文が2通に割れる)では audit_link が2行出る= それが実態だ。
#     1つの audit_id に msg_id が複数ぶら下がる形を潰さない(潰すと片方が辿れなくなる)。
#   ★記録先は既存の tone_audit.jsonl 1本のまま(§4= 置き場を2つ持たない)。
_AUDIT_ID = ""


def _new_audit_id():
    """ゲート通過1回ぶんの突合キーを作る。衝突しなければ形は何でもいい= 時刻+乱数。"""
    return "PS-%d-%04d" % (int(time.time() * 1000), random.randint(0, 9999))


def _audit_link(msg_id, channel="", persona="", dept=""):
    """audit_id ↔ 実msg_id を1行で繋ぐ。投稿が**成功した時だけ**書く(出ていない便を繋がない)。"""
    try:
        if not _AUDIT_ID or not str(msg_id or ""):
            return
        os.makedirs(os.path.dirname(TONE_AUDIT), exist_ok=True)
        with open(TONE_AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "event": "audit_link", "src": "persona_send",
                "audit_id": _AUDIT_ID, "msg_id": str(msg_id),
                "persona": str(persona or ""), "dept": str(dept or ""),
                "channel": str(channel or ""),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _audit_tone(persona, dept, applied, remaining):
    """口調の機械修正/警告を dept_daemon と同じ tone_audit.jsonl へ残す(src=persona_send・記録先を2つ持たない§4)。
    失敗しても送信判定は変えない(fail-safe)。"""
    try:
        os.makedirs(os.path.dirname(TONE_AUDIT), exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(TONE_AUDIT, "a", encoding="utf-8") as f:
            for a in (applied or ()):
                f.write(json.dumps({
                    "ts": ts, "dept": dept, "event": "tone_fix", "src": "persona_send",
                    "persona": str(persona or ""), "marker": a.get("marker", ""),
                    "to": a.get("to", ""), "count": a.get("count", 1),
                    "reason": a.get("reason", "tone_rewrite"),
                    "audit_id": _AUDIT_ID,        # ★投稿後の audit_link 行と繋ぐ鍵
                }, ensure_ascii=False) + "\n")
            for v in (remaining or ()):
                f.write(json.dumps({
                    "ts": ts, "dept": dept, "event": "tone", "src": "persona_send",
                    "persona": str(persona or ""), "marker": v.get("marker", ""),
                    "reason": v.get("reason", ""),
                    "audit_id": _AUDIT_ID,
                }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _audit_tone_rewrite(persona, dept, before, res):
    """ゲートD-2の結果を dept_daemon と**同じ1本**へ残す(src=persona_send・§4)。
    常駐側 dept_daemon.audit_tone_rewrite が書く行と同じ形。失敗しても送信判定は変えない。"""
    try:
        os.makedirs(os.path.dirname(TONE_AUDIT), exist_ok=True)
        with open(TONE_AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "dept": dept, "event": "tone_rewrite", "src": "persona_send",
                "persona": str(persona or ""),
                "ok": bool(res.get("ok")),
                "targets": res.get("targets") or [],
                "after": res.get("after") or [],
                "why": res.get("why") or "",
                "elapsed_ms": res.get("elapsed_ms", 0),
                "engine": res.get("engine") or "",
                "excerpt": str(before or "")[:200],          # ★書き直し**前**
                "excerpt_after": str(res.get("text") or "")[:200],
                "audit_id": _AUDIT_ID,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _audit_structure(persona, dept, body, tag):
    """★軸②(構造)と軸③(他人格の混入)を**数えて置くだけ**の一段(2026-09-16・AD研究室 msg
    1549597333283676171 便6で owner=イージス研究室・可否は人事部門と改修αが既に出している)。

    ★閾値を置かない・何も書き換えない・何も落とさない。理由はAD研究室の corpus 実測=
      崩れた便の bold は 3、平時の中央値 1・最大 5 で**分離しない**。ここで線を引くと
      正当な技術説明を殴る。分布が溜まるまでは数えるだけ= 軸②が通った順番(検知先行)。
    ★数えるのは **200字の抜粋ではなく本文全体**(モドリッチの注文)。崩れは後半に出る=
      抜粋で数えると見えない。台帳は既存の tone_audit.jsonl 1本(記録先を2つ持たない§4)。
    ★例外は全部飲む= この監査で送信を殺さない(他の sink と同じ fail-safe)。
    """
    try:
        _llm = os.path.join(ROOT, "scripts", "llm")
        if _llm not in sys.path:
            sys.path.insert(0, _llm)
        from tone_structure import count_structure
        row = count_structure(body, persona=persona)
        row.update({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dept": dept, "event": "tone_structure", "src": tag or "persona_send",
            "persona": str(persona or ""),
            "audit_id": _AUDIT_ID,
        })
        os.makedirs(os.path.dirname(TONE_AUDIT), exist_ok=True)
        with open(TONE_AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def tone_rewrite_backstop(body, persona, dept, rules, remaining, audit=True, ask=None):
    """出力ゲート**D-2**(案F)を合流点にも当てる(2026-09-11・Chami「寝る前Go」)。

    ★なぜ足したか= D-2(`tone_rewrite.rewrite_once`)は 2026-08-16 に**常駐(dept_daemon)にだけ**
      置かれた。だが外へ撃つ口は3つ在る(C-064)= dept_daemon / **ここ(webhookの合流点)** /
      output_gates(ミラー)。実測(tone_audit.jsonl・書き直し対象reasonのtone行186件)で
      **D-2が回っていない31件のうち13件がこの口**だった。基準便= 2026-09-11T03:58:34 の
      アメス便(dept=aegis-gl・signature_absent「9文中0件」・src=persona_send)。
      ゲートDは置換先が一意な分しか直せず、指紋語尾/方言/敬体は `remaining` へ落ちる。
      **この口はそれを台帳へ書くだけで捨てていた**=崩れたままChamiの画面に出ていた。
    ★handoff §7「最後の合流点にLLM往復を足すな=fail-openの設計を壊す。Goを取れ」への答え=
      そのGoが出た(Chami msg 1547688457051177000)。壊さないための縛りを以下に置く:
      - `remaining` が空なら**呼ばない**(正常便は往復ゼロ・1ミリも変わらない)。
      - 例外・鍵なし・写像に人格が無い= 元の本文をそのまま返す(fail-open= 沈黙にしない)。
      - 採否は tone_rewrite.accept 1本(数字/識別子/URLの不変 → 長さの帯 → 崩れが消えたか)。
      - キルスイッチ `GO5_TONE_REWRITE=0`。3口すべてが同じ環境変数を見る。
      - timeout は常駐(20秒)より短い12秒= ここはChamiの画面までの最後の1段だから。
    ★`ask` 引数= must-fail検査が**外へ出る手だけ**を偽物にするための口(判定と分岐は本物のまま)。
    ★★audit=False では**回さない**(2026-09-11・HQ-0253の但し書き)。
      audit=False の唯一の呼び元は `dept_daemon._gated_like_persona_send`=
      **送信の実在確認が「投げた形」を再現する再生**で、本当に送る場面ではない。
      ここでD-2を回すと (a) 再生のたびに共有鍵のGemini枠(20/日/モデル)を焼き、
      (b) LLMの出力は毎回違うので**再現にならない**(突合鍵がかえって食い違う)。
      機械置換(ゲートD)は決定的なので従来どおり audit の有無で1ミリも変えない。
      **非決定な段だけをこの但し書きの対象にする**= HQ-0253の狙い(再現できること)を守る側。

    返り値: 送るべき本文(str)。採用された時だけ書き直し後、それ以外は入力を1ミリも変えない。
    """
    try:
        if not remaining:
            return body                       # 直せない崩れが無い= 往復しない
        if not audit:
            return body                       # 突合の再現= 非決定な段は回さない(上の但し書き)
        if str(os.environ.get("GO5_TONE_REWRITE", "1")).strip().lower() in ("0", "off", "false"):
            return body                       # キルスイッチ
        if os.path.join(ROOT, "scripts", "llm") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        import tone_rewrite
        res = tone_rewrite.rewrite_once(persona, dept or "", body, remaining, rules,
                                        ask=ask, timeout=12) or {}
        if not res.get("attempted"):
            return body                       # 対象なし/鍵なし/写像に人格が無い= 静かに従来どおり
        if audit:
            _audit_tone_rewrite(persona, dept, body, res)
        if res.get("ok"):
            if audit:
                print(f"[persona_send] ★口調D-2: 合流点で書き直した"
                      f"({','.join(res.get('targets') or [])})。", file=sys.stderr)
            return res.get("text") or body
        if audit:
            print(f"[persona_send] 口調D-2 不採用({res.get('why')})=元の本文で送る(fail-open)。",
                  file=sys.stderr)
        return body
    except Exception as e:
        if audit:
            print(f"[persona_send] 口調D-2 不能({type(e).__name__})=素通し(送信は殺さない)。",
                  file=sys.stderr)
        return body                           # この段が配送を殺さない


def tone_backstop(body, persona, dept, audit=True):
    """Discordへ出る**最後の合流点**の口調ゲート(2026-09-01 platform-se・一ノ瀬怜)。

    英語ダンプは english_backstop(2026-08-23)が合流点で塞いだが、**口調(男口調「俺」等)は
    上流(dept_daemon)の tone_gate だけ**で、無人代打(claude_responder)や直送は素通りだった
    = 🔥 DEF-99f9503e37(アメスの口調バグ)が再発する構造的真因(英語だけ合流点で塞ぎ口調は支流のまま)。
    判定・修正は tone_gate 1本を引く(dept_daemon と同じ純関数=経路が増えてもドリフトしない)。

    ★機械置換のみ(俺→あたし等・置換先が一意な時だけ・**再生成しない**)。方言・指紋語尾・威圧は
      書き直さない=tone_corrections の設計どおり(remaining は警告記録だけ・往復ゼロ)。
    ★fail-open: ルール未ロード/例外は素通し=送信を殺さない(最悪の事故は沈黙)。
    ★ミラー名義(Chami(...))はChami本人の言葉=対象外(触らない)。
    ★persona は**正式名へ解決済み**で渡すこと(口調ルールは「アメス」で引く=ames のままだと引けない)。
    ★audit=False(2026-09-09 HQ-0253)= 直した本文は同じだが**台帳へ書かず黙る**。実在確認側が
      「実際に投げた本文」を再現するために同じゲートを通すので、そこで tone_audit が二重に増えると
      口調違反の件数が嘘になる。★返す本文は audit の有無で1ミリも変えない(判定は1本・ORG-11)。

    返り値: 送るべき本文(str)。修正できた時だけ書き直し後を返す(それ以外は入力を1ミリも変えない)。
    """
    try:
        if str(persona or "").startswith("Chami("):
            return body                       # ミラー=Chami本人の発言。触らない
        if not os.path.exists(TONE_RULES_PATH):
            return body                       # ルール正本が無い=素通し(fail-open)
        if os.path.join(ROOT, "scripts", "llm") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        import tone_gate
        rules = tone_gate.load_tone_rules(TONE_RULES_PATH)
        if not rules:
            return body
        res = tone_gate.tone_corrections(persona, dept or "", body, rules) or {}
        applied = res.get("applied") or []
        remaining = res.get("remaining") or []
        if (applied or remaining) and audit:
            _audit_tone(persona, dept, applied, remaining)
        if applied:
            if audit:
                markers = ", ".join(f"{a.get('marker')}→{a.get('to')}" for a in applied)
                print(f"[persona_send] ★口調を合流点で機械修正({markers})=上流ゲートを通らない"
                      f"代打/直送の残穴を塞ぐ(DEF-99f9503e37)。", file=sys.stderr)
            body = res.get("fixed") or body
        # ★ゲートD-2(2026-09-11)= 機械が直せなかった `remaining` をここで1回だけ書き直す。
        #   常駐と同じ順(D→D-2)。remaining が空ならこの下は即 return= 正常便は不変。
        return tone_rewrite_backstop(body, persona, dept, rules, remaining, audit=audit)
    except Exception as e:
        if audit:
            print(f"[persona_send] 口調ゲート不能({type(e).__name__})=素通し(送信は殺さない・fail-open)",
                  file=sys.stderr)
        return body


# ★炎上表記ゲート(素の🔥→<:enjoh:…> / 絵文字に隣接したラベル「炎上」→「恒久」)。
#   2026-09-01 はここ(webhook口)にだけ実装を置いた。だがDiscordへ本文をPOSTする口はもう1つ
#   (Bot API= bot_send.py)在り、そちらは素通しのままだった= 部分適用。それがChamiの再指摘
#   (REQ-kaizen-analyst-90ebe8bfc8)の真因なので、実装の正本を enjoh.py へ出して両方から呼ぶ。
#   ★名前 enjoh_backstop は据え置き= main() の呼び出しと回帰テストの配線検査を壊さないため。
_ENJOH_HERE = os.path.dirname(os.path.abspath(__file__))
if _ENJOH_HERE not in sys.path:
    sys.path.insert(0, _ENJOH_HERE)
try:
    from enjoh import ENJOH_EMOJI, ack_backstop as _ack_gate, enjoh_backstop as _enjoh_gate
except Exception as _e:                        # 正本が読めない時も送信は殺さない(fail-open)
    print(f"[persona_send] 炎上表記ゲートの正本 enjoh.py を読めない({type(_e).__name__})=素通し。",
          file=sys.stderr)
    ENJOH_EMOJI = "<:enjoh:1541126866981752883>"

    def _enjoh_gate(body, tag="persona_send", quiet=False):
        return body

    def _ack_gate(body, tag="persona_send", peel=None, quiet=False):
        return False                           # 判定が読めない= 落とさない側へ倒す


# ★同形異字(ホモグリフ)ゲート(2026-09-04・依頼=人事部門ククール)。正本= homoglyph.py を
#   persona_send と bot_send の両方から呼ぶ(炎上ゲートと同じ型・C-064)。
#   実物= msg 1545137710820360214 の本文「オレ(ККール)の持ち場だ」= キリルК U+041A。
try:
    from homoglyph import (canonical_name as _homo_canon,
                           homoglyph_backstop as _homo_gate)
except Exception as _e:                        # 正本が読めない時も送信は殺さない(fail-open)
    print(f"[persona_send] 同形異字ゲートの正本 homoglyph.py を読めない({type(_e).__name__})=素通し。",
          file=sys.stderr)

    def _homo_gate(body, persona=None, dept=None, tag="", channel=None, audit=True):
        return body

    def _homo_canon(name, names=None):
        return "", "unavailable"


# ★末尾マークダウン片ゲート(2026-09-20・型=改善提案部門/トトリ・起点=Chami msg 1551230317585760277)。
#   正本は md_tail.py 1本を persona_send と bot_send の両方から呼ぶ(炎上/同形異字と同じ型・C-064)。
#   ★口が2つ在るのに片方にだけ入れて割れた 2026-09-01 の型を繰り返さないため先に両方へ通す
#     (実測では stray 12件は全て persona_send 経由= bot_send 側は予防)。
try:
    from md_tail import trailing_md_backstop as _md_tail_gate
except Exception as _e:                        # 正本が読めない時も送信は殺さない(fail-open)
    print(f"[persona_send] 末尾マークダウン片ゲートの正本 md_tail.py を読めない({type(_e).__name__})=素通し。",
          file=sys.stderr)

    def _md_tail_gate(body, tag="persona_send", quiet=False):
        return body


# ★地の文の裸バッククォート・ゲート(2026-09-21・起点=Chami msg 1551266364231000136
#   「余計なコードブロックいらんて」)。正本は md_ticks.py 1本を persona_send と bot_send の
#   両方から呼ぶ(md_tail と同じ型)。★末尾ゲートの**後ろ**に置く= 先に末尾を落としてから
#   本文の中を見る(逃がした柵 \` を末尾判定に食わせない)。
try:
    from md_ticks import literal_tick_backstop as _md_ticks_gate
except Exception as _e:                        # 正本が読めない時も送信は殺さない(fail-open)
    print(f"[persona_send] 裸バッククォート・ゲートの正本 md_ticks.py を読めない({type(_e).__name__})=素通し。",
          file=sys.stderr)

    def _md_ticks_gate(body, tag="persona_send", quiet=False):
        return body


def enjoh_backstop(body, quiet=False):
    """Discordへ出る本文の炎上表記ゲート(実装は enjoh.py が正本)。

    Chami原文(msg 1544213340853772331)=「🔥 は <:enjoh:1541126866981752883> に置き換えって
    **前に言ったはず**」= 少なくとも2回目の同じ指摘。全部門共通規律§5に既に載っているのに
    生成側が滑る型(英語漏れ・口調割れと同じ)なので、心がけではなく合流点で機械的に潰す。
    起票= 改善提案部門(トトリ)docs/departments/kaizen-analyst/型_素の炎上絵文字_送信ゲート正規化_2026-09-01.md
    """
    return _enjoh_gate(body, tag="persona_send", quiet=quiet)


def apply_text_gates(body, persona=None, dept=None, tag="persona_send", audit=True):
    """★Discordへ出る本文が**最後に通る3ゲートの合流点**。ここを通った文字列が実際に投稿される。

    2026-09-09 HQ-0253(イージス研究室 第55世代)で切り出した。それまで3ゲートは main() の中に
    並んで書かれているだけで、**外から「投げた形」を再現する手段が無かった**。
    実害= 送信の実在確認(dept_daemon.verify_replied)は persona_send へ渡す**前**の本文から
    突合鍵(先頭40字/末尾25字)を作っていたため、enjoh_backstop が末尾の素の🔥を
    `<:enjoh:1541126866981752883>`(26字)へ膨らませた便で鍵が実物と食い違い、
    実在するのに `replied_unverified` が積まれていた。
    ★ゲートごとに突合側で対処してはいけない(ゲートは3つ在り、また増える)。
      **合流点を1本にして、判定する側はそこを呼ぶ**(ORG-11= 同じ判定を2箇所に持たない・C-064)。

    順序は main() の従来どおり 口調 → 炎上表記 → 同形異字 → 末尾マークダウン片。★勝手に入れ替えない。
    ★末尾マークダウン片ゲート(2026-09-20)を**最後**に置く理由= 上の3ゲートは本文を書き換える
      (口調の直し・🔥の置換・同形異字の正規化)。片を落とすのは**実際に投稿される最終形**に
      対してでなければ、書き換えで生えた/ずれた末尾を見落とす。_audit_structure の**前**=
      数えるのは削った後の形(投稿される形)。
    ★english_backstop はここに**含めない**= あれは本文を直すだけでなく「送らない(None)」を
      返す関門で、判定の意味が違う(突合の再現に使うと、送らない便を再現できなくなる)。
    ★audit=False= 変換は同じまま台帳とstderrへ出さない。突合の再現で二重記帳しないため。
    ★fail-open= 3ゲートはいずれも例外を自分で飲んで素通しする(送信を殺さない)。
    ★audit=True の入口で突合キー audit_id を1つ発行する= ここが「1便ぶんのゲート通過」の
      境目だからだ(3つの監査は別々の関数から書かれるが、同じ1便を指している)。
      audit=False(突合の再現)では**発行しない**= 書かない行に鍵は要らないし、
      直前の実便の鍵を踏み潰すと投稿後の audit_link が別の便へ繋がる。
    """
    global _AUDIT_ID
    if audit:
        _AUDIT_ID = _new_audit_id()
    body = tone_backstop(body, persona, dept, audit=audit)
    body = enjoh_backstop(body, quiet=not audit)
    body = _homo_gate(body, persona=persona, dept=dept, tag=tag, audit=audit)
    body = _md_tail_gate(body, tag=tag, quiet=not audit)
    body = _md_ticks_gate(body, tag=tag, quiet=not audit)
    # ★構造監査(軸②/軸③)は**3ゲートの後**= 実際に投稿される文字列をそのまま数える。
    #   audit=False(突合の再現)では書かない= 同じ便を2行数えたら分布が歪む。
    if audit:
        _audit_structure(persona, dept, body, tag)
    return body


# ★共通の送信ログ(2026-09-02・研究室HQからの恒久依頼)。Discordへ実際にHTTPを撃つ口は
#   bot_send.main() と この下の post() の2つだけ= その2点だけから同じ正本を呼ぶ
#   (炎上表記ゲートを片方にだけ入れて割れた 2026-09-01 の型を繰り返さない)。
try:
    from send_audit import record as _send_record
except Exception:                              # ログが無くても送信は殺さない(fail-open)
    _send_record = None


def _audit_send(**kw):
    try:
        if _send_record is not None:
            _send_record("persona_send", **kw)
    except Exception:
        pass


def _audit_english_suppressed(persona, channel, hit, body):
    """英文ダンプで送信保留したことを監査へ残す(dept_daemon と同じ置き場・ORG-23)。失敗しても送信判定は変えない。"""
    try:
        os.makedirs(os.path.dirname(ENGLISH_AUDIT), exist_ok=True)
        with open(ENGLISH_AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "src": "persona_send", "event": "english_dump_suppressed", "ref": "ORG-23",
                "persona": persona, "channel": channel,
                "latin": hit.get("latin"), "jp": hit.get("jp"), "ratio": hit.get("ratio"),
                # ★kind/func= 2026-09-06 に足した混在型("mixed")と全文英語("whole")の別。
                #   QAが台帳で偽陽性率を数える時、どちらの枝が鳴ったかが分からないと直せない。
                "kind": hit.get("kind"), "func": hit.get("func"),
                "body": str(body or "")[:400],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def english_backstop(body, persona, channel):
    """Discordへ出る**最後の合流点**の言語ゲート(2026-08-23 platform-se・一ノ瀬怜)。

    dept_daemon の返信は上流の english_gate を通るが、無人代打(claude_responder)や直送は
    **persona_send が唯一の関門**=ここを通らない英語ダンプは誰も止めない(🔥 DEF-f827f07985 の残穴)。
    判定は lang_gate 1本を引く(dept_daemon と同じ=経路が増えてもドリフトしない)。

    ① 英語前置き+日本語本文 → 前置きを剥がし、日本語本文だけ送る(握り潰さない)。
    ② 日本語本文+**末尾/中間の英語段落** → その段落だけ剥いで日本語本文を送る
       (2026-09-16 aegis-gl・ケヴィン・デブライネ / Chami msg 1549527667571818507「末尾の
       英文いらんて」恒久+再発=4度目)。★剥ぐ手 `strip_english_paragraphs` は 09-11 から
       lang_gate に在ったが、呼んでいたのは enjoh.py だけで**この最後の合流点が引いていなかった**
       =穴は閾値でも関数不在でもなく**配線**。新しい判定は作らない(ORG-11=判定を2つに割らない)。
    ③ 本文まるごと英語(救う日本語が無い)→ **送らない**(Chami裁定ORG-23=英語を晒すより送らない)。
    ★fail-open: モジュールが読めない/例外は素通し=送信を殺さない(最悪の事故は沈黙)。
    ★ミラー名義(Chami(...))はChami本人の言葉=Claudeの英文ダンプではない→対象外(触らない)。

    返り値: 送るべき本文(str) / None=保留(呼び側が送信を止める)。
    """
    try:
        if str(persona or "").startswith("Chami("):
            return body                       # ミラー=Chami本人の発言。英語でも触らない
        if os.path.join(ROOT, "scripts", "llm") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        from lang_gate import (detect_english_dump, strip_english_preamble,
                               strip_english_paragraphs)
        out, pre = strip_english_preamble(body)
        if pre.get("stripped"):
            print(f"[persona_send] ★英語前置きを剥離(英字{pre.get('removed_latin')})→日本語本文だけ送る",
                  file=sys.stderr)
            body = out
        # 末尾/中間の純英語段落。安全弁は lang_gate 側(日本語ゼロは触らない・名乗りタグを
        # 含む段落は剥がない・残る日本語が20字未満なら何もしない)=通常返信は1ミリも変わらない。
        out, para = strip_english_paragraphs(body)
        if para.get("stripped"):
            _by = ",".join(para.get("by") or [])
            _ex = (para.get("excerpts") or [""])[0][:80]
            # stderr は上流の capture_output で消える。既存の enjoh_scrub 台帳へ、
            # persona_send 直通口で剥いだ事実も残す。判定・除去は lang_gate のまま。
            try:
                from enjoh import scrub_audit
                scrub_audit("english_para", "persona_send", para["stripped"],
                            f"latin={para.get('removed_latin')} by={_by} | {_ex}")
            except Exception:
                pass
            print(f"[persona_send] ★英語段落を{para['stripped']}件剥離"
                  f"(英字{para.get('removed_latin')}・判定{_by})→日本語本文だけ送る。"
                  f"冒頭=…{_ex}…", file=sys.stderr)
            body = out
        hit = detect_english_dump(body)
        if hit is None:
            return body                       # 通常返信=1ミリも変えない
        _audit_english_suppressed(persona, channel, hit, body)
        _kind = "本文まるごと英語" if hit.get("kind") != "mixed" else \
                f"英語の作業ナレーション混在(英語機能語{hit.get('func')}語)"
        print(f"[persona_send] ★{_kind}(英字{hit['latin']}/日本語{hit['jp']}・比{hit['ratio']})"
              f"=送信を保留した。日本語話者の部屋にClaude原文の英語ダンプを出さない(ORG-23/Chami裁定)。"
              f"冒頭=…{hit['excerpt']}…", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[persona_send] 言語ゲート不能({type(e).__name__})=素通し(送信は殺さない・fail-open)",
              file=sys.stderr)
        return body


# ── 二重投稿ガード(2026-09-13・研究室HQ/シャビ・アロンソ DISPATCH-platform-se-1789239112088)──
#   実害: 自動復帰した研究室(main)セッション(lab_owner_pid)が、main箱へ回送された部屋の便を
#   処理して、その部屋の担当セッションが生きているのに**同じ persona 名義でその部屋へ中身無し
#   ackを投稿**した= 同じ人格が同じ部屋で19秒差で二重に喋った(Chami msg
#   1548403851043016705「これいらんよ、どうした?」)。止血(lab_revive_prompt.pyのプロンプト文)は
#   **人へのお願い**であって機構ではない(§3 心がけに任せない・機構に載せる)。
#   → Discordへ出る唯一の関門(OUT口)で機械的に止める。
#
#   ★誤発火を作らない(HQ明言「誤発火を作るなら入れない方が良い」・§3「常に誤発火する安全網は
#     無視される」)。そのため**測った事故の署名に完全一致した時だけ**ブロックする:
#       (1) 宛先が「担当=対話セッション本人」の部屋で、担当セッションが**今生きて働いている**
#           (interactive_presence_<dept>.txt が PRESENCE_TTL 以内)
#       (2) この persona_send を起こしたのが**研究室(main)セッション**
#           (自分の先祖プロセスに lab_owner_pid が居る)、かつ
#       (3) その lab_owner_pid が部屋の担当pidと**別物**(=研究室が他所の部屋を代弁している)。
#   この3条件が全部成立する時だけ掛かる= 部屋本人の返信(mirror hook=部屋セッションpidの子)も、
#   dept_daemon(lab_owner_pidの子ではない別デーモン)も、ここには絶対に掛からない。
#   材料が読めない/プロセス表が取れない/判定不能は**素通し**(fail-open)。素通しても本人の1本は
#   出るので可用性は落ちない(止めるのは"二重"の側だけ)。
#   ★bot_send は persona 名義を持たない(--persona を拒否しpersona_sendへ誘導)= 同一persona二重は
#     構造的に起きない。よってこのガードは persona_send 1口だけで足りる(C-064の全数確認の結論)。
def _ancestry_pids(procs, start=None):
    """自分から親を辿った pid 集合(自分自身を含む)。procs={pid:(ppid,exe)}。輪でも抜ける。"""
    out = set()
    pid = start if start is not None else os.getpid()
    for _ in range(24):
        if pid in out or pid not in procs:
            break
        out.add(pid)
        pid = procs[pid][0]
    return out


def _room_live_owner(dept):
    """部屋<dept>の担当=対話セッションが今生きて働いているか+その担当pid。無ければ (False, 0)。

    正本は session_rooms(在席の記録元)。ここに写しを持たない= 在席TTL/置き場が変わっても追従する。
    """
    if not dept:
        return (False, 0)
    try:
        if os.path.join(ROOT, "scripts", "llm") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
        from session_rooms import presence_path, PRESENCE_TTL
        p = presence_path(dept)
        if (time.time() - os.path.getmtime(p)) >= PRESENCE_TTL:
            return (False, 0)          # 在席が古い= 担当は働いていない= 他者が出しても二重にならない
        try:
            pid = int((json.loads(open(p, encoding="utf-8").read() or "{}") or {}).get("pid") or 0)
        except Exception:
            pid = 0                    # 旧形式(pid無し)でも「生きている」判定は有効
        return (True, pid)
    except Exception:
        return (False, 0)


def _lab_owner_pid():
    """研究室(main)セッションのPID。inbox_waiter が武装時に1行だけ残す。無ければ 0。"""
    try:
        return int(open(os.path.join(LOCAL, "llm", "lab_owner_pid.txt"),
                        encoding="utf-8").read().strip() or 0)
    except Exception:
        return 0


def dupe_post_block_reason(dept, persona):
    """測った二重投稿事故の署名に一致する時だけ理由文字列を返す。不一致/判定不能は None(=素通し)。"""
    if not dept:
        return None
    live, room_pid = _room_live_owner(dept)
    if not live:
        return None                    # (1)不成立: 部屋の担当が働いていない
    lab = _lab_owner_pid()
    if not lab:
        return None                    # 研究室pid不明= 判定材料なし= 素通し(fail-open)
    try:
        from session_rooms import proc_table
        procs = proc_table()
    except Exception:
        procs = {}
    if not procs:
        return None                    # プロセス表が取れない= 判定不能= 素通し(fail-open)
    if lab not in _ancestry_pids(procs):
        return None                    # (2)不成立: この送信は研究室(main)の子ではない(部屋本人/デーモン)
    if room_pid and room_pid == lab:
        return None                    # (3)不成立: 研究室自身がこの部屋の担当= 正規の返信
    return (f"研究室(main pid={lab})が、担当セッション(pid={room_pid or '?'})の生きている部屋"
            f"[{dept}]へ persona『{persona}』名義で投稿しようとした= 二重投稿")


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
    # ★最後の合流点の言語ゲート(2026-08-23)。無人代打・直送を含む全persona送信がここを通る。
    #   英語前置きは剥がし、本文まるごと英語は送らない(ORG-23/🔥 DEF-f827f07985 の残穴を塞ぐ)。
    gated = english_backstop(body, persona, channel or dept)
    if gated is None:
        sys.exit(4)               # 英文ダンプ=保留。webhookを叩かない=Discordに英語を出さない
    body = gated
    # ★2026-09-10 定型ack denylist(依頼= 改善提案部門トトリ・炎上 msg 1547305004069560351)。
    #   「受け取った。処理を開始する。完了結果は保存してから返す。」= 日本語20字超で**空便ガードに
    #   かからない**が中身は無い便。「内容の無い一次ackは沈黙より悪い」(共通規律§2)を機械へ落とす。
    #   判定の正本は enjoh.ack_only_reason 1本(bot_send / codex_run / dept_daemon も同じ関数を引く)。
    #   ★名乗り `[名前]` は本文ではないので剥がしてから見る= 「[オタコン] 受け取った。」も止まる。
    def _peel_self_tag(ln):
        m = re.match(r"^\s*[\[［]([^\]］\n]{1,20})[\]］]\s*", ln or "")
        return (ln[m.end():] if m and m.group(1).strip() == str(persona).strip() else ln)

    if _ack_gate(body, tag="persona_send", peel=_peel_self_tag):
        _audit_send(body=body, event="blocked", status="ack_only",
                    channel=str(channel or ""), dept=str(dept or ""), persona=str(persona))
        print("内容の無い一次ackは沈黙より悪い(共通規律§2)ので送信しません。\n"
              "  作業の結果か、今わかっている実物を本文にしてください。")
        sys.exit(4)
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
    # ★二重投稿ガード(2026-09-13)。ch解決後=宛先deptは ch['dept'] が正本(--channel指定でも引ける)。
    #   resolve_persona の後= 正式名で理由文へ出すため。掛かるのは測った事故の署名のみ(上の説明)。
    _dupe = dupe_post_block_reason(str(ch.get("dept") or dept or ""), persona)
    if _dupe:
        _audit_send(body=body, event="blocked", status="dupe_guard",
                    channel=str(ch.get("name") or channel or ""),
                    dept=str(ch.get("dept") or dept or ""), persona=str(persona))
        print("二重投稿ガード: " + _dupe + "\n"
              "  この部屋は担当セッション本人が答える。研究室(main)からの代弁は出さない"
              "(共通規律§3=心がけに任せず機構で止める)。", file=sys.stderr)
        sys.exit(5)
    # ★口調の合流点ゲート(2026-09-01)。英語は上で塞いだが口調は支流(dept_daemon)だけだった=
    #   代打/直送の男口調「俺」等が素通りしていた(DEF-99f9503e37 の構造的真因)。resolve_persona の
    #   後=正式名で口調ルールを引くため。機械置換のみ・fail-open=送信は殺さない。
    #   ★絵文字の合流点ゲート(2026-09-01)= 素の🔥を地の文に置くなという規律は在るのに生成側が滑る
    #     (Chami msg 1544213340853772331=少なくとも2回目の指摘)。
    #   ★同形異字の合流点ゲート(2026-09-04)= 地の文の自称・言及が化けても誰も直していなかった。
    #   ★2026-09-09 HQ-0253= この3行を apply_text_gates() 1本へ寄せた(順序は従来のまま)。
    #     実在確認(dept_daemon.verify_replied)が**同じ1本**を呼んで「投げた形」を再現するため。
    #     ここをバラして書き戻すと、突合鍵がまた投稿前の本文からできて宙に浮く。
    body = apply_text_gates(body, persona=persona, dept=dept, tag="persona_send")
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
    # (msg_idの取得は名義に関係なく全便で行う。下の post() を見ろ)
    mirror = persona.startswith("Chami(")
    if mirror or "--silent" in sys.argv:
        payload["flags"] = 4096
    # ★--print-id: 旧仕様の残り。今は全便でmsg_idを取るので指定の有無で挙動は変わらない
    #   (既存の呼び出し側を壊さないため引数としては受け続ける)。
    #   通知の抑制(4096)は mirror/--silent の時だけ= 実依頼は相手部門に気づいてほしいため。

    def post(pl):
        # ★2026-09-03 全便で wait=true にした(モドリッチ経由・改修αの実測)。
        #   旧実装は mirror名義か --print-id の時だけ wait=true を付けていた。付けないと
        #   Discordは **HTTP 204・本文なし** を返す= msg_idが取れない= send_audit に
        #   msg_id="" で残る。実測 406便中336便(82.8%)が空で、whatis.py が
        #   「msg_id→どの部門の誰が何のために出した便か」を機械で辿れなかった
        #   (Chamiが16:57に指した便が3台帳のどれにも無かった件がこれ)。
        #   wait=true にすると Discord は **200 + メッセージJSON** を返す= idが取れる。
        #   ★代償: 成功時のHTTPが 204→200 に変わる。stdoutの "204" を成功判定に使って
        #     いた呼び出し元3本(broadcast.py / office_daily.py / winupdate_message.py)は
        #     同じcommitで「送信OK + rc=0」判定へ直した(C-064: 出口を変える時は撃つ点を全部数える)。
        url = hook_url + "?wait=true"
        req = urllib.request.Request(
            url, data=json.dumps(pl).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "go5-org-persona (personal, v1)"},
        )
        # ★送信ログ用に、実際にDiscordへ渡す本文をpayloadから取り出す(content / embed両対応)。
        _sent = pl.get("content") or "".join(
            str((e or {}).get("description", "")) for e in (pl.get("embeds") or []))
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                mid = ""
                try:
                    # ★id が取れなくても送信は成功している= ここで例外を上へ出さない
                    #   (記録のためにDiscordへ出た言葉を失う方が損だ)。
                    data = json.loads(r.read().decode("utf-8"))
                    mid = str((data or {}).get("id", "") or "")
                except Exception:
                    mid = ""
                _audit_send(body=_sent, status=str(r.status), channel_id=str(ch.get("id", "")),
                            channel=str(ch.get("name", "")), dept=str(ch.get("dept", "")),
                            persona=str(persona), msg_id=mid)
                # ★ゲート時に発行した audit_id と、今返ってきた実msg_id を繋ぐ1行。
                #   ここが実IDを知る**唯一の点**だ(HTTPを撃つ口はこの post() だけ)。
                _audit_link(mid, channel=str(ch.get("name", "")), persona=str(persona),
                            dept=str(ch.get("dept", "")))
                return r.status, mid
        except Exception as e:
            _audit_send(body=_sent, status="ERR:" + type(e).__name__,
                        channel_id=str(ch.get("id", "")), channel=str(ch.get("name", "")),
                        dept=str(ch.get("dept", "")), persona=str(persona))
            raise                       # ★握り潰さない= 上の例外処理(分割連投の再試行等)を変えない

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
                st, mid = post(pl)
                print(f"送信OK → {ch.get('name')} as {persona} (HTTP {st})"
                      + (f" msg={mid}" if mid else "") + (f" [{i+1}通目]" if i else ""))
                time.sleep(0.4)
        elif "embeds" in payload:
            st, mid = post(payload)
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
                st, mid = post(pl)
                print(f"送信OK → {ch.get('name')} as {persona} (HTTP {st})"
                      + (f" msg={mid}" if mid else "") + (f" [{i+1}通目]" if i else ""))
                time.sleep(0.4)  # webhookのレート制限を避ける
    except Exception as e:
        print(f"送信失敗: {type(e).__name__}")
        sys.exit(3)


if __name__ == "__main__":
    main()
