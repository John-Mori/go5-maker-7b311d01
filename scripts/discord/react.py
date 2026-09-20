#!/usr/bin/env python3
"""Discordメッセージにリアクションを押す (AI組織の進捗印・2026-07-16 Chami依頼)。

3段階印のうち後ろ2つ「既読」「着手」を、応対するClaudeセッションが押す。
(1つ目「送信」は inbox_poller.py が配達時に自動で押す=機械が届けた印)
  送信 = 鳩が箱へ入れた(届いた証明。Claudeが見たとは限らない)
  既読 = Claudeセッションが起床して読んだ(起床直後に押す)
  着手 = 本格的に作業を始めた
これで Chami の画面から「未達 / 届いたが無人 / 読んだ / 着手済み」の4状態が一目で分かる。
※2026-07-17改訂: 旧実装は鳩が配達時に「既読」を押していたが、それは"届いた"であって
  "Claudeが読んだ"ではなかった(Chami指摘)。鳩の印を送信へ改称し、既読はセッションが押す。

使い方:
  python scripts/discord/react.py --channel 改修-依頼 --msg 1526809157544574976
  python scripts/discord/react.py --channel 1525646154933735425 --msg <id> --emoji 既読
オプション:
  --channel  チャンネル名(local/discord_channels.jsonのname) または チャンネルID
  --msg      対象メッセージID(受信箱レコードの msg_id)
  --emoji    絵文字名(既定: 着手)。サーバー絵文字を名前で解決、無ければUnicode代用
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
API = "https://discord.com/api/v10"
# 印の解決(絵文字の実名照合)に使ってよい時間の上限。
# ★なぜ本文のPUTと別の予算にするか(2026-09-06 実測・イージス研究室):
#   呼び側(codex_run.mark_sent / codex_responder.mark)は subprocess を **timeout=30** で切る。
#   一方このスクリプトの api() は 1回20秒×3試行。解決で2往復すると最悪120秒超になり、
#   **呼び側の30秒に必ず負ける**=印が押されないまま無言で殺される。
#   解決は anchor_id という正解を既に持っている上での上乗せ(fail-open)なので、短く切ってよい。
#   PUT本体はこの制限を受けない(押せる時は必ず押す)。
RESOLVE_TIMEOUT = 6
RESOLVE_TRIES = 1
FALLBACK = {"着手": "👀", "既読": "✅", "送信": "📮", "即答": "💬",
            "再発": "🔁", "改悪": "📉"}  # サーバー絵文字が未登録/引けない時だけの代用
# 呼び名(日本語) → Chami登録の実際の絵文字名。どちらで指定しても解決する
# 即答=4段印の新設(Chami発案2026-07-19・QA合意)。サーバー絵文字sokutou作成までは💬で代用
# 再発saihatsu/改悪kaiaku=2026-09-04トトリ仕様で追加(いずれもギルド登録済み)。
ALIAS = {"着手": ["chakusyu", "着手"], "既読": ["kidoku", "既読"], "送信": ["sendms", "送信"],
         "即答": ["sokutou", "即答"], "再発": ["saihatsu", "再発"], "改悪": ["kaiaku", "改悪"]}
# ★IDアンカー(2026-09-04トトリ仕様):カスタム絵文字リアクションは name:id の **id** で
#   描画される(name側は表示名で、Chamiが絵文字名を変えても id が実在すれば custom で出る
#   =enjoh→kokyu が IDで出るのと同型)。ギルドの実名照合(resolve_emoji)を第一とし、
#   照合が1件も当たらなくても、確定IDを持つ印はここで **必ず custom を撃つ**。
#   「引けたのに unicode を残さない」=fail-open は本当に引けない印(即答等)だけに限定する。
EMOJI_ID = {"着手": "1527252032308908172", "既読": "1527252197597777971",
            "送信": "1527369203819085864", "再発": "1531748428827201772",
            "改悪": "1541110670748156014"}
EMOJI_NAME = {"着手": "chakusyu", "既読": "kidoku", "送信": "sendms",
              "再発": "saihatsu", "改悪": "kaiaku"}  # name:id のname側(idで描くので表示名でよい)
# ★受け手=Codex(@ネイキッド・スネーク)の時だけ差し替える3印(Chami指示 2026-09-05・msg 1545618001741611058)。
#   正本= 00_AI-HQ/docs/departments/kaizen-analyst/絵文字管理台帳.md §A.1(改善提案部門が意味を確定・当室は配線=C-015)。
#   なぜ既存絵文字の流用か= ギルドCRUDはChami直命・不可逆(§3.7)。新素材を作らず既存IDを使い回す暫定運用。
#   ★分けるのは送信/既読/着手の**3印だけ**。即答💬/再発🔁/改悪📉/炎上🔥/ゴラッソ⚽/愛❤ は
#     Claude/Codex 共通のまま(C-035=名指し指示を全体へ広げない=Chami明言「ほかは共通認識でOK」)。
#   値= (実名, id)。id が None の印は unicode をそのまま撃つ(🐍=スネーク・素材不要)。
CODEX_OVERRIDE = {
    # ★2026-09-20 Chamiが Codex専用の送信カスタム絵文字を作成(msg 1551219293058768959
    #   「これ、ボスに送った時の送信スタンプね。今まで uptsukiyomi だったからこれからはこれに置き換えて」)。
    #   uptsukiyomi(§B業務印の流用=意味が二重化していた)→ 専用素材へ。
    #   uptsukiyomi は §E「月詠みアップ済」の本来意味へ戻る(流用終了・台帳§A.1は改善提案部門が反映済)。
    "送信": ("Send_MS_Boss", "1551218921170927649"),  # sendms → Send_MS_Boss(Codex専用素材)
    "既読": ("‼️", None),                                # kidoku → ‼️(unicode直撃・2026-09-05トトリ経由Chami指示=followok撤去)
    # ★2026-09-20 Chamiが Codex専用の着手カスタム絵文字を作成(msg 1551192982567387210
    #   「ボス(Codex)の着手スタンプこれにしてね」)。🐍(unicode代用)→ ギルド素材の実物へ差し替え。
    #   意味・種別は改善提案部門が §A.1 の着手Codex列で確定済(当室は配線=C-015)。
    #   id を持つので sendms/uptsukiyomi と同じ経路(実名照合→ID)で custom を撃つ=劣化しない。
    "着手": ("Chakusyu_Boss", "1551192017495785492"),  # chakusyu → Chakusyu_Boss(Codex専用素材)
}
# ★引退した印(**読む側だけ**が使う退避表)。押す側は絶対にここから撃たない。
#   なぜ要るか(2026-09-20 実測・イージス研究室): 着手を🐍から差し替えた瞬間、
#   **過去の@ボス便に付いている🐍**を audit_marks(生存印を読む唯一の器)が着手として読めなくなり、
#   `test_audit_marks_codex.py` が2件赤になった= 2026-09-09 の「生存印なし」誤報9件と同じ形。
#   印は消さずに退避する(C-003)。押す側に印が増減したら、読む側はここも畳んで追随する(ORG-11)。
CODEX_RETIRED = {
    "着手": [("🐍", None)],        # 2026-09-05〜2026-09-20 に押した分(過去便にそのまま残る)
    # 2026-09-05〜2026-09-20 に Codex送信印として押した分(過去便にそのまま残る)。
    # ★読む側だけ= uptsukiyomi は §E「月詠みアップ済」の本来意味へ戻したが、
    #   その意味で押された過去便と、送信印として押された過去便は id では区別できない。
    #   audit_marks(生存印を読む器)は @ボス便の文脈で読むので、ここは送信として畳んでよい。
    "送信": [("uptsukiyomi", "1522060098355069139")],
}


def read_token():
    p = os.path.join(LOCAL, "discord_bot_token.txt")
    with open(p, "r", encoding="utf-8") as f:
        return f.read().strip()


def resolve_channel(spec):
    s = str(spec or "").strip()
    if s.isdigit():
        return s
    with open(os.path.join(LOCAL, "discord_channels.json"), "r", encoding="utf-8") as f:
        for c in json.load(f):
            if c.get("name") == s:
                return str(c.get("id", ""))
    return ""


def api(path, token, method="GET", timeout=20, tries=3):
    req = urllib.request.Request(
        API + path, method=method, data=(b"" if method == "PUT" else None),
        headers={"Authorization": "Bot " + token, "User-Agent": "go5-org-react (personal, v1)"},
    )
    for _ in range(max(1, tries)):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8")
                return json.loads(body) if body else True
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 1))
                except Exception:
                    wait = 1.0
                time.sleep(min(wait, 10) + 0.3)
                continue
            print(f"HTTP {e.code}: {path}")
            return None
    return None


def resolve_emoji(token, cid, name, codex=False):
    """印を name:id へ解決する。IDで撃つ経路に一本化(2026-09-04トトリ仕様)。
    ①ギルドの実名照合を第一(新規追加した絵文字も即使える・現在の実名でnameが揃う)。
    ②照合が1件も当たらなくても、確定IDを持つ印は EMOJI_ID で **必ず custom を撃つ**
      (名前がズレても id が実在すれば描画される=劣化しない。受け入れ条件3)。
    ③IDも持たない印(即答sokutou等)だけ unicode 代用へ落ちる(=本当に引けない時のfail-open)。
    ★codex=True の時、送信/既読/着手の3印だけ §A.1 の代替へ差し替える(受け手=Codex)。
      代替も同じ経路(実名照合→ID)で解決する=劣化しない。id が None の印(🐍)は unicode を直に返す。
    """
    want_name, anchor_id = name, EMOJI_ID.get(name)
    if codex and name in CODEX_OVERRIDE:            # ★Codex受信=3印を差し替え(他印は素通り=共通)
        alt_name, alt_id = CODEX_OVERRIDE[name]
        if alt_id is None:
            return alt_name                         # 🐍 等=ギルド素材が無い unicode はそのまま撃つ
        want_name, anchor_id = alt_name, alt_id
    try:
        ch = api(f"/channels/{cid}", token, timeout=RESOLVE_TIMEOUT, tries=RESOLVE_TRIES)
        gid = str((ch or {}).get("guild_id", "") or "")
        if gid:
            emojis = api(f"/guilds/{gid}/emojis", token,
                         timeout=RESOLVE_TIMEOUT, tries=RESOLVE_TRIES) or []
            # 差し替え時は代替の実名を、通常時は ALIAS(実名→呼び名)を照合する
            wants = [want_name] if (codex and name in CODEX_OVERRIDE) else ALIAS.get(name, [name])
            for want in wants:
                for e in emojis:
                    if e.get("name") == want and e.get("id"):
                        return f"{e['name']}:{e['id']}"
    except Exception:
        pass
    if anchor_id:                                   # 実名照合が外れてもIDで custom を撃つ
        disp = want_name if (codex and name in CODEX_OVERRIDE) else EMOJI_NAME.get(name, name)
        return f"{disp}:{anchor_id}"
    return FALLBACK.get(name, name)


def main():
    args = sys.argv[1:]
    ch = msg = ""
    emoji_name = "着手"
    codex = False                                   # --codex=受け手がCodex(§A.1で3印を差し替える)
    i = 0
    while i < len(args):
        if args[i] == "--channel" and i + 1 < len(args):
            ch = args[i + 1]; i += 2
        elif args[i] == "--msg" and i + 1 < len(args):
            msg = args[i + 1]; i += 2
        elif args[i] == "--emoji" and i + 1 < len(args):
            emoji_name = args[i + 1]; i += 2
        elif args[i] == "--codex":
            codex = True; i += 1
        else:
            i += 1
    if not ch or not msg:
        print("使い方: react.py --channel <名前|ID> --msg <メッセージID> [--emoji 着手]")
        sys.exit(2)
    cid = resolve_channel(ch)
    if not cid:
        print(f"チャンネルを解決できません: {ch}")
        sys.exit(2)
    token = read_token()
    emoji = urllib.parse.quote(resolve_emoji(token, cid, emoji_name, codex=codex))
    ok = api(f"/channels/{cid}/messages/{msg}/reactions/{emoji}/@me", token, method="PUT")
    if ok:
        print(f"リアクションOK → {ch} msg={msg} :{emoji_name}:")
    else:
        print("リアクション失敗(権限/ID/絵文字を確認)")
        sys.exit(1)


if __name__ == "__main__":
    main()
