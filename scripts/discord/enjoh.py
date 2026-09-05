#!/usr/bin/env python3
"""Discordへ出る本文の合流点ゲート(正本。2026-09-02 イージス研究室)。

いま2つ入っている:
  (1) 炎上表記の正規化(2026-09-02)= 下の A/B。
  (2) 生成ノイズの孤立フィラー行を落とす(2026-09-05・DEF-codex-care-noise-line-20260905)。
      → filler_line_scrub() の docstring に実物と根拠を書いた。

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


# --- (2) 生成ノイズの孤立フィラー行 -------------------------------------------------
# 単独行に立てる「1語だけのASCII」= 落とす対象。長さは12字まで(それ以上は文の可能性)。
_FILLER_LINE_RE = re.compile(r"^[A-Za-z]{1,12}$")
# 日本語本文の中に居ることの判定(ひらがな/カタカナ/漢字)。
_JP_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
_JP_MIN = 20                                     # これ未満なら「日本語本文」と見なさない=触らない
# ★単独行で意味を持ちうる語は落とさない(誤って情報を消す方が事故として重い)。
_KEEP_WORDS = {
    "ok", "ng", "yes", "no", "done", "pass", "fail", "failed", "error", "warn",
    "warning", "todo", "fixme", "note", "tip", "wip", "fyi", "eof", "null", "none",
    "true", "false", "green", "red", "diff", "log", "before", "after", "in", "out",
}


def filler_line_scrub(body, tag="persona_send"):
    """段落と段落の間に挟まった、生成ノイズの孤立フィラー行を落とす。

    実物(DEF-codex-care-noise-line-20260905 / QA起票):
      otacon-radio・2026-09-05 11:44〜11:47 の2便。msg 1545625670191943791(care×1)と
      1545626524974190654(care×4)で、日本語本文の段落間に単独の "care" 行が計5本入った。
      生成側(gpt-5.5)のノイズだと本人が自認(msg 1545627265742807131)。
      ★モデルに「吐くな」は保証させられないので、**出口で剥がす**。

    ★なぜここ(enjoh.py の正本)か= 実物2便は `via=persona_send` で出ている
      (local/llm/send_audit.jsonl の当該 msg_id。argv も persona_send.py)。QAの起票は
      「codex_run.dc_send 直前」も候補に挙げていたが、**そこへ置いてもこの2便は1本も剥がせない**。
      enjoh_backstop は persona_send / bot_send / behop / codex_run / imagegen の5口すべてが
      呼ぶ唯一の合流点なので、ここへ1枚置けば全口に同時に入る(C-064・注入口は1本のまま=ORG-11)。

    ★落とす条件(狭く取る。迷ったら残す):
      - 前後が空行(または本文の先頭/末尾)で挟まれた孤立行であること。
      - 行の中身が **ASCII英字1語のみ**(1〜12字)。数字・記号・空白が混じったら対象外。
      - 本文全体に日本語が _JP_MIN(20)字以上あること= 英語本文の1語行は触らない。
      - コードブロック(```)の中は触らない(実装の説明で見せたい場面がある)。
      - _KEEP_WORDS(OK/NG/done 等、単独で意味を持つ語)は落とさない。
    落とす時は隣接する空行も1本だけ一緒に畳む= 段落の区切り(空行1本)を保つ。
    返り値: 送るべき本文。1本も落とさなければ入力を1ミリも変えない(Noneも型のまま返す)。
    """
    try:
        s = str(body or "")
        if not s or len(_JP_RE.findall(s)) < _JP_MIN:
            return body                           # 日本語本文でない=触らない
        lines = s.split("\n")
        n = len(lines)
        fence = False
        drop = set()
        for i, ln in enumerate(lines):
            t = ln.strip()
            if t.startswith("```"):
                fence = not fence
                continue
            if fence or not _FILLER_LINE_RE.match(t) or t.lower() in _KEEP_WORDS:
                continue
            if (i == 0 or lines[i - 1].strip() == "") and \
               (i == n - 1 or lines[i + 1].strip() == ""):
                drop.add(i)
        if not drop:
            return body
        for i in sorted(drop):                    # 空行の畳み込み(後ろ優先・無ければ前)
            if i + 1 < n and lines[i + 1].strip() == "" and (i + 1) not in drop:
                drop.add(i + 1)
            elif i - 1 >= 0 and lines[i - 1].strip() == "" and (i - 1) not in drop:
                drop.add(i - 1)
        hit = [lines[i].strip() for i in sorted(drop) if lines[i].strip()]
        print(f"[{tag}] ★生成ノイズの孤立フィラー行を合流点で除去({len(hit)}行"
              f" / 語={','.join(sorted(set(hit)))})= DEF-codex-care-noise-line-20260905。",
              file=sys.stderr)
        return "\n".join(lines[i] for i in range(n) if i not in drop)
    except Exception as e:
        print(f"[{tag}] フィラー行スクラブ不能({type(e).__name__})=素通し(送信は殺さない・fail-open)",
              file=sys.stderr)
        return body


def enjoh_backstop(body, tag="persona_send"):
    """Discordへ出る本文を合流点で正規化する(炎上表記 + 生成ノイズの孤立フィラー行)。

    引数 tag は stderr の出所表示だけに使う(判定には効かない)。
    返り値: 送るべき本文。置換が1件も無ければ入力を1ミリも変えない(Noneも型のまま返す)。
    ★名前は据え置き= 5口の呼び出しと既存の配線検査(co_names)を壊さないため。
    """
    body = filler_line_scrub(body, tag=tag)       # ★炎上表記の有無に関係なく必ず通す
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
