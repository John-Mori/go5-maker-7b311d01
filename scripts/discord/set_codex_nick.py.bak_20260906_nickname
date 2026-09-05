# -*- coding: utf-8 -*-
"""set_codex_nick — Codex bot(ネイキッド・スネーク)のサーバー内ニックネームを正本へ合わせる。

なぜ在るか(2026-09-06 aegis-gl・オタコン便 msg 1545905734544527431 (2)):
  画面に出る名前は **botアカウント本人の表示名**だ(codex_run.dc_send は webhook ではなく
  bot 本人として投稿する)。グローバル username は新方式で `[a-z0-9_.]` しか通らないので
  「スネーク🐍Codex」は **username では原理的に置けない**(実測 2026-09-05: username=Codex_SnakeBot)。
  置ける口は1つだけ= サーバー内ニックネーム `PATCH /guilds/{guild}/members/@me {"nick": …}`
  (Unicode可・32文字以内。ニックが在れば表示はそちらが優先される)。
  この PATCH は Codex botトークンが要る。そのトークンは人事部門のセッションからは
  deny で読めない= 人事では撃てない。だから基盤(イージス研究室)側に口を置く。

正本(ここに名前の写しを持たない= 人事部門が値を変えたら次の実行から効く):
  00_AI-HQ/departments/hr/personas/呼称ルール.json → codex_bot_display.確定表示名

使い方:
  python scripts/discord/set_codex_nick.py            … 現在の nick を測るだけ(既定は読み取り)
  python scripts/discord/set_codex_nick.py --apply    … 正本の値へ揃える(PATCH してから測り直す)

★トークンは読むだけで、出力にもログにも出さない。
"""
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
HQ = os.environ.get("GO5_HQ_DIR") or os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ"))

TOKEN_FILE = os.path.join(LOCAL, "discord_codex_token.txt")
NAMING_RULES = os.path.join(HQ, "departments", "hr", "personas", "呼称ルール.json")
DC_API = "https://discord.com/api/v10"
UA = "go5-codex-nick/1.0"

# 台帳(codex_bot_display)に書いてあるギルド。JSONに guild_id キーが無いのでここに持つ。
GUILD_ID = os.environ.get("GO5_GUILD_ID") or "1498341160207515678"


def wanted_nick():
    """正本の確定表示名。読めなければ空(=撃たない)。"""
    try:
        with open(NAMING_RULES, encoding="utf-8") as f:
            d = json.load(f)
        return str((d.get("codex_bot_display") or {}).get("確定表示名") or "").strip()
    except Exception as e:
        print(f"正本を読めない({type(e).__name__}) = {NAMING_RULES}")
        return ""


def _token():
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        print(f"ABORT: Codex botトークンが未設置 ({TOKEN_FILE})")
        return ""


def _call(method, path, token, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(DC_API + path, data=data, method=method,
                                 headers={"Authorization": "Bot " + token,
                                          "Content-Type": "application/json",
                                          "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def current(token):
    """今サーバーに出ている名前を測って返す (nick, username)。

    ★読みと書きで**パスが違う**(実測 2026-09-06):
      読み= `GET /guilds/{g}/members/{bot_id}`。`.../members/@me` は bot トークンでは
            HTTP 400 になる(あれは OAuth2 bearer 用の口だ)。
      書き= `PATCH /guilds/{g}/members/@me`(こちらは bot トークンで通る)。
    """
    me = _call("GET", "/users/@me", token)
    m = _call("GET", f"/guilds/{GUILD_ID}/members/{me.get('id')}", token)
    return (m.get("nick") or ""), str(me.get("username") or "")


def main():
    apply_it = "--apply" in sys.argv
    token = _token()
    if not token:
        return 2
    want = wanted_nick()
    try:
        nick, uname = current(token)
    except urllib.error.HTTPError as e:
        print(f"測れない: HTTP {e.code}(botがこのサーバーに居ないか権限不足)")
        return 3
    print(f"現在: nick={nick!r} / username={uname!r} / 正本={want!r}")
    if not want:
        print("正本が空= 撃たない(人事部門が値を入れてから)")
        return 4
    if nick == want:
        print("一致している= することは無い")
        return 0
    if not apply_it:
        print("ズレている。揃えるなら --apply を付けて実行する")
        return 1
    try:
        _call("PATCH", f"/guilds/{GUILD_ID}/members/@me", token, {"nick": want})
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        print(f"PATCH失敗: HTTP {e.code} {detail}")
        if e.code == 403:
            print("→ botに『ニックネームの変更』権限が無い。サーバー設定でCodexのロールへ付ける。")
        return 5
    # ★書いた後に**測り直した値**で言う(C-048)。PATCHの戻りを信じない。
    nick2, _u2 = current(token)
    print(f"測り直し: nick={nick2!r} → " + ("一致(揃った)" if nick2 == want else "まだズレている"))
    return 0 if nick2 == want else 6


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
