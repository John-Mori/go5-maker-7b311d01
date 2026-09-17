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
import json
import os
import re
import sys
import time

# ★2026-09-12(イージス研究室)= 剥いだ事実を**残す**ための台帳。
#   実測した穴: dept_daemon は persona_send を `capture_output=True` で起動し(L9885)、
#   rc==0 の時は stderr を**捨てている**。つまり合流点のゲートが実便で仕事をしても、
#   その audit 行はどのログにも残らない= 「入れた」を「効いた」へ上げる目が無い(§4.55)。
#   → 剥いだ時だけ1行 append する。fail-open(書けなくても便を巻き込まない)。
#   ★検査の行を本番の台帳へ混ぜない= sink_for(C-054・invisible.py と同じ正本を使う)。
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "local")
SCRUB_AUDIT_FILE = os.path.join(LOCAL, "llm", "enjoh_scrub.jsonl")

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


def filler_line_scrub(body, tag="persona_send", quiet=False):
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
        if not quiet:
            print(f"[{tag}] ★生成ノイズの孤立フィラー行を合流点で除去({len(hit)}行"
                  f" / 語={','.join(sorted(set(hit)))})= DEF-codex-care-noise-line-20260905。",
                  file=sys.stderr)
        return "\n".join(lines[i] for i in range(n) if i not in drop)
    except Exception as e:
        if not quiet:
            print(f"[{tag}] フィラー行スクラブ不能({type(e).__name__})=素通し(送信は殺さない・fail-open)",
                  file=sys.stderr)
        return body


def fire_normalize(body, tag="dispatch", quiet=False):
    """★炎上表記(A/B)**だけ**を当てる。フィラー行スクラブは含まない。

    ★2026-09-07 追加(イージス研究室)= **第6の口 `scripts/llm/dispatch.py` のため**に切り出した。
      改善提案部門の発注 `DISPATCH-aegis-gl-1788739848001` は「dispatch経由にはゲートが効いている」
      と書いていたが、**実測ではdispatchはこのゲートを1度も通っていない**(呼んでいるのは
      persona_send / bot_send / codex_run / behop / imagegen の5口だけ)。実物= 部門記憶の受信content
      2026-09-02〜09-07 で **DISPATCH/ESC封筒 22通が素の🔥を載せて各部屋へ届いていた**
      (うち12通が絵文字監視digestの見出し・残り10通は各室が自分で書いた地の文)。
    ★なぜ enjoh_backstop をそのまま呼ばないか= 封筒の本文には識別子だけの独立行が普通に出る。
      `filler_line_scrub` は「孤立した1語のASCII」を落とす作りなので、封筒に当てると
      `dispatch` のような行を消しかねない= **依頼の情報を消す方が事故として重い**。
      だから封筒には A/B だけを当てる(ORG-11= 正本はこの1本のまま)。
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
        if not quiet:
            print(f"[{tag}] ★炎上表記を合流点で正規化(素の🔥→<:enjoh:…> {n}件 / ラベル炎上→恒久 {m}件)"
                  f"= Chami指摘の再発を機械的に潰す(共通規律§5・REQ-kaizen-analyst-90ebe8bfc8)。",
                  file=sys.stderr)
        return "".join(parts)
    except Exception as e:
        if not quiet:
            print(f"[{tag}] 炎上表記ゲート不能({type(e).__name__})=素通し(送信は殺さない・fail-open)",
                  file=sys.stderr)
        return body


# --- (3) 定型ack denylist ---------------------------------------------------------
# ★2026-09-10(イージス研究室・発注= 改善提案部門トトリの上申)。炎上 + 再発の恒久策。
#   実物= 🚬無線通信-オタコン 2026-09-10 02:56 に出た
#     「受け取った。処理を開始する。完了結果は保存してから返す。」
#   Chami原文=「このやり取りいらない」→(再発)「効いてません」。
#   真因の1つ(codex_responder.py:546 notify_room の定型テキスト)は 09-10 09:36 に撤去済。
#   だが**撤去は1箇所の守り**で、次の実装が同じ文を書けば戻る(送信印で一度やられている)。
#   → 判定の正本をここに置き、Discordへ出る各口から引く(炎上表記ゲートと同じ型)。
#
# ★語ではなく**文**の集合で持つ / 部分一致で落とさない:
#   本文を文へ割り、**全部の文が下の句**の時だけ「言うことが無い」とする。
#   「受け取った。ログの末尾は 09-10 だ。」は2文目が句に無い= **送る**(情報を消さない)。
# ★迷ったら喋る側へ倒す(規律§3): 長い本文は見ない / 句に無い1単位が在れば送る /
#   例外は素通し。**誤って黙らせる方が事故として重い**。
ACK_MAX_CHARS = 200
_ACK_PHRASES = frozenset([
    # 受領だけを言う文
    "受け取った", "受け取りました", "受け取ります", "受けとった", "受領した", "受領しました",
    "受け付けた", "受け付けました", "承知した", "承知しました", "了解した", "了解しました",
    "把握した", "把握しました", "確認した", "確認しました",
    # 着手だけを言う文
    "処理を開始する", "処理を開始します", "処理を始める", "処理を始めます", "処理する",
    "処理します", "対応を開始する", "対応を開始します", "対応する", "対応します",
    "作業を開始する", "作業を開始します", "着手する", "着手します",
    "これから対応する", "今から対応する", "確認を開始する", "確認する", "確認します",
    # 結果を後で返すとだけ言う文
    "完了結果は保存してから返す", "完了結果は保存してから返します",
    "完了したら返す", "完了したら報告する", "完了したら報告します",
    "完了後に報告する", "完了後に報告します", "終わり次第報告する", "終わり次第報告します",
    "終わったら報告する", "結果は追って返す", "結果は追って報告する", "結果は追って共有する",
    "追って返す", "追って報告する", "追って報告します", "追って共有する",
    "少々お待ちください", "しばらくお待ちください", "お待ちください",
    # 英語の同型(小文字で引く)
    "ack", "acked", "acknowledged", "received", "roger", "understood", "noted",
    "onit", "workingonit", "willreportback", "processing", "started",
    # ★2026-09-17 追加(イージス研究室・発注= ローカル研究室カスミ DISPATCH-aegis-gl-1789632009829
    #   / Chami直令 msg 1550050117401313311)。「裏(--audience ai)で回した便に表で了解を出すな」の
    #   機構化。**語を増やす前に実測した**= local/llm/send_audit.jsonl 全3,306行のうち、200字未満で
    #   受領系の語を含みながらこのゲートを**通り抜けていた**便は42件/31種。その内訳は
    #     ・12件= 「受領。本対応は担当セッションへ引き継ぎます。」(hr-room/astro-room/manga-shorts/
    #       imagegen-itsumono/platform-se/llm-growth の6室。多くは 研究室(無人代打) 名義)
    #     ・残り30種= どれも中身の在る本文(=落としてはいけない)。
    #   → 足すのは**実物で出た無情報の文とその同義形だけ**。「待機します」「確認します」等の
    #     既出の類型に揃える。文の集合で持つ設計(部分一致で落とさない)はそのまま。
    "受領", "受領です", "本対応は担当セッションへ引き継ぎます", "担当セッションへ引き継ぎます",
    "担当セッションへ引き継ぎました", "本対応は担当へ引き継ぎます", "担当へ引き継ぎます",
    "担当セッションに引き継ぎます", "担当セッションへ回します",
    "承知いたしました", "了解いたしました", "承りました", "かしこまりました",
    "対応いたします", "対応を進めます", "確認のうえ対応します", "確認のうえ対応いたします",
    "確認の上対応します", "確認して対応します",
    "待機します", "引き続き待機します", "こちらは引き続き待機します", "待機を継続します",
])
_ACK_DROP_RE = re.compile(r"[\s\*`_~>#\-–—・:：]+")          # 空白と装飾は落としてから引く
_ACK_EDGE = "。．.!！?？、,…‥ー()（）[]{}「」『』\"'“”‘’ 　"
# 文の切れ目。★半角句点 ｡ も入れる= 割る前に NFKC を通すが、「割る」と「引く」で正規化が
#   ずれると片方だけすり抜ける(実測= `受け取った｡処理を開始する｡` がすり抜けた)。
_ACK_SPLIT_RE = re.compile(r"[。｡．.!！?？;；\n]+")


def ack_norm(unit):
    """1文を denylist と突き合わせる形へ(NFKC・空白と装飾を除去・両端の句読点を落とす)。"""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(unit or ""))
    return _ACK_DROP_RE.sub("", s).strip(_ACK_EDGE).lower()


def ack_only_reason(body, peel=None):
    """その本文は**既知の定型ackだけ**でできているか。戻り= 落とす理由の1行 / 送るなら ""。

    peel= 行から名乗りタグ等を剥がす任意の関数(line)->line。渡さなければ行をそのまま見る。
    ★空・空白だけの本文はここでは落とさない("" を返す)= 空の判定は各口の持ち場
      (dept_daemon の `_is_empty_body` / persona_send の「本文が空です」)。判定を二重に持たない。
    ★例外は握って "" (=送る)。ゲートの故障で部屋を黙らせない。
    """
    try:
        import unicodedata
        s = str(body or "").strip()
        if not s or len(s) > ACK_MAX_CHARS:
            return ""
        units = []
        for ln in s.split("\n"):
            if not ln.strip():
                continue
            if callable(peel):
                ln = peel(ln) or ""
                if not ln.strip():
                    continue
            for u in _ACK_SPLIT_RE.split(unicodedata.normalize("NFKC", ln)):
                n = ack_norm(u)
                if n:
                    units.append(n)
        if not units or not all(u in _ACK_PHRASES for u in units):
            return ""
        return "定型ackだけで中身が無い(%d文= %s)" % (len(units), " / ".join(units[:4]))
    except Exception:
        return ""


def ack_backstop(body, tag="persona_send", peel=None, quiet=False):
    """出口用の薄い包み。落とすなら理由を stderr へ出して True を返す(送るなら False)。

    ★黙って落とさない= 呼んだ口が必ず台帳(send_audit 等)へ blocked を残すこと。
    """
    why = ack_only_reason(body, peel=peel)
    if not why:
        return False
    if not quiet:
        print(f"[{tag}] ★定型ack denylist= {why} → 送らない。"
              f"内容の無い一次ackは沈黙より悪い(共通規律§2・2026-09-10 恒久策)。", file=sys.stderr)
    return True


# --- (3) 生成が漏らす制御タグ ---------------------------------------------------------
# 実物(2026-09-11 msg 1547703386911285425・system-engineer / Chami が 恒久+再発 を二重スタンプ):
#   投稿が3層になっていた= 日本語本文 + `<system>WIPは付けない。実際に調べる。</system>` +
#   末尾の英語1文。中の指示は**こちらが与えた運転指示**であって、Chamiへ見せる本文ではない。
# ★scripts全体を grep して、この除去は**どこにも無かった**(改善提案部門トトリの実測・該当0)。
#   名乗りタグ `[…]` の剥離は在るが、あれは行頭1個の別物。だから新設してここへ足す。
_CONTROL_TAG_NAMES = (
    "system", "thinking", "thought", "reasoning", "scratchpad", "internal",
    "assistant", "human", "user", "instructions", "antml:thinking",
)
_CT = "|".join(re.escape(n) for n in _CONTROL_TAG_NAMES)
# 対で閉じている塊= 中身ごと落とす。
_CONTROL_BLOCK_RE = re.compile(r"<(" + _CT + r")\b[^>\n]*>.*?</\1\s*>", re.S | re.I)
# 閉じ損ねて片方だけ残った札= その札だけ落とす(中身は本文かもしれないので消さない)。
_CONTROL_LONE_RE = re.compile(r"</?(?:" + _CT + r")\b[^>\n]*>", re.I)


def scrub_audit_file():
    """この呼び出しが書くべき台帳のパス(本番 or 検査退避)。"""
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
        from test_sink import sink_for
        return sink_for(SCRUB_AUDIT_FILE)
    except Exception:
        return SCRUB_AUDIT_FILE


def scrub_audit(kind, tag, n, detail=""):
    """合流点が**実便で**何を剥いだかを1行残す。剥いだ時だけ呼ぶ。

    ★なぜ要るか= stderr は dept_daemon の capture_output に吸われて消える(モジュール冒頭の注記)。
      残らないと、この部屋は「入れた(確認待ち)」から一生動けない。
    ★fail-open= 書けなくても False を返すだけ。呼び出し元(=送信)は絶対に巻き込まない。
    """
    try:
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind,
               "tag": str(tag or ""), "n": int(n or 0), "detail": str(detail or "")[:200]}
        path = scrub_audit_file()
        if path != SCRUB_AUDIT_FILE:
            row["test"] = True       # 退避先でも「検査の行」だと分かる形で残す(消さない)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def control_tag_scrub(body, tag="persona_send", quiet=False):
    """本文へ漏れた制御タグ(`<system>…</system>` 等)を剥ぐ純関数。

    かける面= Discordへ投稿される本文。かけない面= コードブロック / インラインコード
      (規律や実装の説明で `<system>` を**そのまま見せたい**場面がある。誤発火する安全網は無視される)。
    ★対で閉じた塊は中身ごと落とす= 中身は運転指示であって読み手への文章ではない。
      片割れの札だけ残っている時は**札だけ**落とす= 本文を巻き添えにしない。
    ★剥いだ結果が空/空白だけになるなら**元をそのまま返す**= 沈黙を作らない(最悪の事故は沈黙)。
    ★fail-open: 例外は素通し。
    """
    try:
        if not body:
            return body
        src = str(body)
        parts = _CODE_SPLIT_RE.split(src)
        n = 0
        found = []                                   # 剥いだ札の現物(台帳へ残す証拠)
        for i in range(0, len(parts), 2):            # 偶数=地の文だけ(奇数=コード=触らない)
            s = parts[i]
            found += [m.group(1) for m in _CONTROL_BLOCK_RE.finditer(s)]
            s, c1 = _CONTROL_BLOCK_RE.subn("", s)
            found += [m.group(0) for m in _CONTROL_LONE_RE.finditer(s)]
            s, c2 = _CONTROL_LONE_RE.subn("", s)
            if c1 or c2:
                n += c1 + c2
                parts[i] = s
        if not n:
            return body
        out = re.sub(r"\n{3,}", "\n\n", "".join(parts)).strip()
        if not out:
            return body                              # 全部が制御タグだった=判断を後段へ委ねる
        if not quiet:
            print(f"[{tag}] ★合流点で制御タグを剥いだ({n}件)= `<system>` 等は運転指示であって"
                  f"読み手への本文ではない(2026-09-11 恒久策)。", file=sys.stderr)
        try:
            scrub_audit("control_tag", tag, n, ",".join(found))
        except Exception:
            pass          # ★台帳の失敗で**剥ぎ取りを取り消さない**(外側の except は body を
                          #   そのまま返す=漏れる。記録の都合で本文の安全を下げてはいけない)
        return out
    except Exception:
        return body


# --- (4) 末尾/中間に居座る英語段落 -----------------------------------------------------
def english_para_scrub(body, tag="persona_send", quiet=False):
    """日本語の便に混じった純英語の散文段落を剥ぐ(判定と除去の正本は lang_gate.py)。

    ★ここは**薄い包み**= 判定を持たない。言語の判定器を2本に増やすと必ず割れる(ORG-11)。
      実体= scripts/llm/lang_gate.py の strip_english_paragraphs()(安全弁と根拠はそちらの
      docstring に書いた)。読めなければ素通し= 便を止めない(fail-open)。
    """
    try:
        if not body:
            return body
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm")
        if d not in sys.path:
            sys.path.insert(0, d)
        from lang_gate import strip_english_paragraphs
        out, info = strip_english_paragraphs(body)
        if not info.get("stripped"):
            return body
        if not quiet:
            print(f"[{tag}] ★合流点で英語段落を剥いだ({info['stripped']}件/英字"
                  f"{info['removed_latin']}字・by={','.join(info.get('by') or [])})= "
                  f"{(info.get('excerpts') or [''])[0][:60]}", file=sys.stderr)
        try:
            scrub_audit("english_para", tag, info.get("stripped"),
                        f"latin={info.get('removed_latin')} by={','.join(info.get('by') or [])} "
                        f"| {(info.get('excerpts') or [''])[0][:100]}")
        except Exception:
            pass          # ★control_tag_scrub と同じ理由= 台帳の失敗で本文を漏らさない
        return out
    except Exception as e:
        if not quiet:
            print(f"[{tag}] 英語段落ゲートの正本 lang_gate.py を読めない({type(e).__name__})=素通し",
                  file=sys.stderr)
        return body


def enjoh_backstop(body, tag="persona_send", quiet=False):
    """Discordへ出る本文を合流点で正規化する(炎上表記 + 生成ノイズの孤立フィラー行)。

    引数 tag は stderr の出所表示だけに使う(判定には効かない)。
    返り値: 送るべき本文。置換が1件も無ければ入力を1ミリも変えない(Noneも型のまま返す)。
    ★名前は据え置き= 5口の呼び出しと既存の配線検査(co_names)を壊さないため。
    ★2026-09-07= 中身を fire_normalize() へ切り出しただけで、この関数の振る舞いは変えていない
      (フィラー行スクラブ → 炎上表記、の順も同じ)。
    ★quiet=True(2026-09-09 HQ-0253・イージス研究室)= **変換はそのまま・stderr へ出さない**だけ。
      送信の実在確認(dept_daemon.verify_replied)が「実際に投げた本文」を再現するために同じ
      ゲートを通す。そこで「合流点で正規化した」と鳴ると、**送っていない2度目の正規化**が
      起きたように読める(ログを読む人が事故を数え間違える)。返す本文は1ミリも変わらない。
    ★2026-09-11= 前段に2枚足した(発注= 改善提案部門トトリ / 実物= msg 1547703386911285425)。
      順番に理由が在る= 制御タグ(3)を先に剥ぐと、その中身の英語が英語段落(4)の判定へ混ざらない。
      英語段落(4)の次にフィラー行(1)= 段落を剥いだ跡に1語だけ残った行をそこで拾える。
      炎上表記(2)は最後= 置換であって除去ではないので、除去が全部済んだ本文に当てるのが素直。
    """
    body = control_tag_scrub(body, tag=tag, quiet=quiet)   # (3) 漏れた <system> 等
    body = english_para_scrub(body, tag=tag, quiet=quiet)  # (4) 末尾/中間の純英語段落
    body = filler_line_scrub(body, tag=tag, quiet=quiet)   # ★炎上表記の有無に関係なく必ず通す
    return fire_normalize(body, tag=tag, quiet=quiet)
