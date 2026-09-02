#!/usr/bin/env python3
"""Discordへ出る本文の炎上表記ゲート(正本。2026-09-02 イージス研究室)。

なぜここに独立して在るか:
  2026-09-01 に persona_send.py(webhook口)へ同じゲートを入れた。だが**Discordへ本文をPOSTする口は
  2つ**あり(webhook=persona_send / Bot API=bot_send)、Bot API側は素通しのままだった
  = 部分適用。実例= absence_watchdog.py:1328 の配送失敗警報は bot_send 経由なので、素の🔥が
  そのままChamiの目の前に出ていた。Chamiの再指摘(REQ-kaizen-analyst-90ebe8bfc8)の真因はこれ。
  → 片方に置いた実装は必ずもう片方と割れる。だから**正本を1つにして両方の口から呼ぶ**。

このゲートが直す物は2つ(トトリの指示 REQ-kaizen-analyst-90ebe8bfc8):
  A. 素の 🔥 → カスタム絵文字 <:enjoh:1541126866981752883>
  B. 表示ラベルの語「炎上」→「恒久」(★絵文字に隣接している時だけ。地の文の「炎上」は触らない)

★かける面/かけない面(ここを混ぜると逆に汚くなる):
  かける = Discordのメッセージとして投稿される本文(persona_send / bot_send の出口)。
  かけない = ターミナル出力・部門の起動文脈(close_item.py の凡例行、session_relay の起票ヘッダ等)。
            <:enjoh:…> はDiscordのメッセージ内でしか絵文字に描画されない。文脈へ置換すると
            生の文字列 "<:enjoh:1541126866981752883>" がそのまま読まれる=逆に汚い。
★地の文だけ置換する。コードブロック(```)とインラインコード(`…`)の中は触らない
  = 規律や実装の説明で素の🔥を**そのまま見せたい**場面があるため(誤発火する安全網は無視される)。
★fail-open: 例外は素通し=送信を殺さない(最悪の事故は沈黙)。
"""
import re
import sys

ENJOH_EMOJI = "<:enjoh:1541126866981752883>"
_FIRE_RE = re.compile("\U0001F525️?")           # 素の🔥(異体字セレクタ付きも拾う)
_CODE_SPLIT_RE = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)   # 奇数要素=コード=触らない

# ラベルB: 絵文字に隣接した「炎上」だけを「恒久」へ。
#   拾う  = "<:enjoh:…>炎上 9件" / "<:enjoh:…>(炎上)" / "<:enjoh:…>【炎上=…】"
#   拾わない= "先週の炎上の件" のような地の文(=語の意味ごと壊すのを防ぐ)。
#   後続が区切り(空白/数字/閉じ括弧/=/:/句読点/行末)の時だけ= 「炎上した」「炎上案件」は不変。
_LABEL_RE = re.compile(r"(" + re.escape(ENJOH_EMOJI) + r"\s*[(【]?)炎上(?=[)】\s0-9=:、。」]|$)")


def enjoh_backstop(body, tag="persona_send"):
    """Discordへ出る本文の炎上表記を合流点で正規化する。

    引数 tag は stderr の出所表示だけに使う(判定には効かない)。
    返り値: 送るべき本文。置換が1件も無ければ入力を1ミリも変えない(Noneも型のまま返す)。
    """
    try:
        s = str(body or "")
        if "\U0001F525" not in s and ENJOH_EMOJI not in s:
            return body                       # 対象が無い=何もしない(大多数の便はここで抜ける)
        parts = _CODE_SPLIT_RE.split(s)
        n = m = 0
        for i in range(0, len(parts), 2):     # 偶数=コード外=地の文
            parts[i], k = _FIRE_RE.subn(ENJOH_EMOJI, parts[i])
            parts[i], j = _LABEL_RE.subn(r"\g<1>恒久", parts[i])
            n += k
            m += j
        if not n and not m:
            return body                       # 対象はコードの中だけだった=触らない
        print(f"[{tag}] ★炎上表記を合流点で正規化(素の🔥→<:enjoh:…> {n}件 / ラベル炎上→恒久 {m}件)"
              f"= Chami指摘の再発を機械的に潰す(共通規律§5・REQ-kaizen-analyst-90ebe8bfc8)。",
              file=sys.stderr)
        return "".join(parts)
    except Exception as e:
        print(f"[{tag}] 炎上表記ゲート不能({type(e).__name__})=素通し(送信は殺さない・fail-open)",
              file=sys.stderr)
        return body
