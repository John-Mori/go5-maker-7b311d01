# -*- coding: utf-8 -*-
"""msg_text — Discordの1通から**人が読む文字**を全部集める(判定はこの1本だけ・ORG-11)。

なぜ在るか:
  2026-09-05 11:00:36 の commit `1b46147` で改修α室の投稿を `persona_send --color auto` に
  したところ、**本文が `embeds[].title` へ移り `content` は0字**になった。
  `content` しか見ていなかった着地判定が、着いている返信を「不着」と読み始めた
  (実測= msg 1545618308370399244 は content 0字・embeds[0].title に判定キーが一字一句在る)。
  研究室HQが止血として同じ関数を2箇所へ**別々に**置いた:
    - `scripts/llm/dept_daemon.py::_msg_text`
    - `scripts/_daemons/replied_recheck.py::msg_text`
  止血の申し送りが「恒久では1本に寄せてくれ」だったので、ここへ寄せた
  (イージス研究室・アメスの回送 DISPATCH-aegis-gl-1788581567519 便6-1)。

★二重実装が危ないのは重複そのものではない。**片方だけ直した日に、同じ便を
  「読めた/読めない」で割る**ことだ。判定は1本しか持たない(ORG-11)。

★fail-open の向き= 拾いすぎ側へ倒す。判定の材料は多い方が安全で、
  足りない(=0字に見える)方が事故になる。だから題・説明・fieldsを全部足す。

使う側:
    sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
    from msg_text import msg_text
"""


def msg_text(m):
    """1通(Discord APIのmessageオブジェクト)から人が読む文字を連結して返す。

    集める先= `content` / `embeds[].title` / `embeds[].description` /
              `embeds[].fields[].name` / `embeds[].fields[].value`。
    ★区切りは半角スペース1つ= 「本文をそのまま見せる」用途ではなく
      **判定(キーが在るか)と検索**のための平文だ。表示に使うなら元の構造を見ろ
      (`scripts/discord/read_msg.py` は表示側なので、題・説明を別々に印字している)。
    ★辞書以外や欠けたキーが来ても落ちない= 判定器が例外で死ぬのが一番の事故。
    """
    if not isinstance(m, dict):
        return ""
    parts = [str(m.get("content") or "")]
    for e in (m.get("embeds") or []):
        if not isinstance(e, dict):
            continue
        parts.append(str(e.get("title") or ""))
        parts.append(str(e.get("description") or ""))
        for f in (e.get("fields") or []):
            if not isinstance(f, dict):
                continue
            parts.append(str(f.get("name") or ""))
            parts.append(str(f.get("value") or ""))
    return " ".join(p for p in parts if p)


def msg_text_obj(m):
    """discord.py のオブジェクト(Message等)から**同じ**平文を作るアダプタ。

    RESTの口(requests+json)は辞書で来るが、Gateway経路(`scripts/queue/discord_gateway.py`)は
    discord.py のオブジェクトで来る。**判定を2つ持たない**(ORG-11)ので、ここは
    「形を辞書へ揃えるだけ」に徹し、中身の判断は上の `msg_text()` へ丸ごと預ける。

    ★embed 1枚が壊れていても全部を捨てない= その1枚だけ諦めて残りを返す(fail-open)。
    """
    if m is None:
        return ""
    if isinstance(m, dict):
        return msg_text(m)
    embeds = []
    for e in (getattr(m, "embeds", None) or ()):
        try:
            d = e.to_dict()
        except Exception:                       # noqa: BLE001
            continue
        if isinstance(d, dict):
            embeds.append(d)
    return msg_text({"content": getattr(m, "content", None) or "", "embeds": embeds})
