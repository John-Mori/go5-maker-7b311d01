#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""chami_identity — 「この便を書いたのはChami本人か」の判定を置く**唯一の場所**。

★なぜ1本にしたか(2026-09-16・研究室HQ(シャビ・アロンソ)からの宿題1):
  同じ値の写しが3箇所に散っていた=
    scripts/discord/absence_watchdog.py L225  CHAMI_USERNAMES
    scripts/discord/reaction_watch.py   L118  CHAMI_USER_ID
    scripts/llm/codex_responder.py      L78   両方(2026-09-16に3本目として足された)
  ユーザ名かIDが変わった日に**3箇所を直す必要があり、直し忘れた1箇所が黙って誤判定する**。
  誤判定の向きは場所ごとに違う=
    ・codex_responder  → Chamiの「回すな」という指示そのものを回し返す(実害・11:47と11:48に実測)
    ・absence_watchdog → Chamiが待っているのに「Chamiの発言が無い」と読んで警報が鳴らない
    ・reaction_watch   → Chamiが押した印を「機械が押した」と読んで巡回から落ちる
  どれも**沈黙**の形で出る=気付けない。だから正本を1つにする(ORG-11)。

★判定に使う値(この2つだけ。ここを直せば全部に効く):
  CHAMI_USERNAMES  Discordのユーザ名。小文字で突き合わせる。
  CHAMI_USER_ID    数値ID(実測 2026-07-29)。★名前は変えられるがIDは変わらない=**IDが主**。

★入口は3つの形で来る。呼ぶ側が形を気にしなくて済むよう、ここで全部吸収する=
  ① キューの便        {"author": "chami_fusoh", "author_id": "4909..."}   (discord_gateway が毎便入れる)
  ② Discord APIの投稿 {"author": {"id": "4909...", "username": "chami_fusoh"}}
  ③ Discord APIの人   {"id": "4909...", "username": "chami_fusoh"}         (リアクションを押した人)

★人手の入口を前提にしない(共通規律§3)。機械が自動で載せる author / author_id / id だけを見る。
  本文の署名や `--from` のような**人が書く値では判定しない**=書き忘れた瞬間に判定が壊れるからだ。

★import に try/except を被せるな。
  ここが読めない時に黙って写しの縮退へ落ちると、**判定が壊れたことに誰も気付けない**
  (2026-09-16 第62世代の実測= `except Exception` がImportErrorを飲んで安全網が無音で無効化された)。
  読めなければ起動時に ImportError で落ちる方がよい。常駐の起動ログに出る。
"""

CHAMI_USERNAMES = ("chami_fusoh",)
CHAMI_USER_ID = "490925528367497227"


def is_chami_username(name):
    """ユーザ名がChamiのものか(大文字小文字と前後の空白は無視する)。"""
    return str(name or "").strip().lower() in CHAMI_USERNAMES


def is_chami_id(user_id):
    """数値IDがChamiのものか。★名前より強い証拠=先に見る。"""
    return str(user_id or "").strip() == CHAMI_USER_ID


def is_chami_user(user):
    """Discord APIの**人**オブジェクト({"id","username"})がChami本人か。

    リアクションを押した人の一覧(reaction_watch)のように、便ではなく人が渡る所で使う。
    """
    if not isinstance(user, dict):
        return False
    return is_chami_id(user.get("id")) or is_chami_username(user.get("username"))


def from_chami(rec):
    """この**便**を書いたのがChami本人か。キューの便でもDiscord APIの投稿でも同じ答えを返す。

    ★author が辞書(Discord API)でも文字列(キュー)でも通る。形の違いで判定が割れないようにする。
    """
    if not isinstance(rec, dict):
        return False
    if is_chami_id(rec.get("author_id")):
        return True
    author = rec.get("author")
    if isinstance(author, dict):
        return is_chami_user(author)
    return is_chami_username(author)
