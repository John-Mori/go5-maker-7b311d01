# -*- coding: utf-8 -*-
"""言語ゲートの純関数(英文ダンプ検知・英語前置き剥離)= 全経路の"単一の判定"。

なぜ独立モジュールか(2026-08-23 platform-se・一ノ瀬怜):
  英文ダンプ対策(ORG-23)は 2026-07-21 に一度ミラー経路で塞いだが、別経路(dept_daemon)で
  再発した=**同じ判定が経路ごとに別々に在ると片方だけ直してドリフトする**(P4/C-038)。
  合流点は dept_daemon の送信直前だが、それより下流の**真の合流点=persona_send**(Discordへ
  出る最後の1点)を代打(claude_responder)や直送が通る。判定を1本(このファイル)へ寄せ、
  dept_daemon も persona_send も**このモジュールを引く**=経路が増えても判定はドリフトしない。

  ★このモジュールに人格設定・送信・LLM呼び出しは持たない(純関数だけ)。どのプロセスが
    落ちても再現でき、単体テストで固定できる(test_english_gate.py が dept_daemon 経由で覆う)。
"""
import re

# 日本語(ひらがな・カタカナ・漢字・半角カナ)/ ラテン英字。判定の芯はこの2本だけ。
_JP_RE = re.compile(r"[぀-ヿ一-鿿ｦ-ﾟ]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def detect_english_dump(text):
    """日本語話者の部屋に**本文まるごと英語**(Claude原文ダンプ)が出ていれば info を返す。

    ★正当な日本語本文に英語の固有名詞・URL・コード識別子・規約番号が混じる普通の返信では鳴らない。
      判定前にコード柵・インラインコード・URLを除く(そこに英字が多いのは正当=誤検知の芽を摘む)。
    ★閾値=英字が散文の量(40字以上)あり、かつ日本語がほぼ無い(英字数の15%未満)時だけ。
      実測(花海咲季の英文 msg 1539153227491180624)= 英字≈290/日本語≈9=2%で確実に発火。
      普通の混在返信(オタコン実便=日本語数百字+英単語数十字)は英字<40 or 日本語多数で鳴らない。
    ★**検知するだけ**(自動置換はしない)。空/None/非文字列でも例外を出さない(fail-safe)。
    """
    try:
        s = str(text or "")
        core = re.sub(r"```.*?```", " ", s, flags=re.S)   # コード柵は判定から除く
        core = re.sub(r"`[^`]*`", " ", core)              # インラインコード
        core = re.sub(r"https?://\S+", " ", core)         # URL
        latin = len(_LATIN_RE.findall(core))
        jp = len(_JP_RE.findall(core))
        if latin >= 40 and jp <= latin * 0.15:
            return {"latin": latin, "jp": jp,
                    "ratio": round(jp / float(latin or 1), 3), "excerpt": s[:120]}
        return None
    except Exception:
        return None          # 検査が落ちても応答は続ける(fail-safe)


def strip_english_preamble(text):
    """先頭の英語前置き(段落)だけを剥がし、日本語本文を残す(純関数・テスト可・fail-safe)。

    なぜ detect_english_dump(まるごと英語)が見逃すか(真因):
      あのゲートの閾値は latin>=40 かつ jp<=latin*0.15 =**本文の全部が英語**の時だけ鳴る。
      混在(英語段落数百字+日本語本文数百字)は日本語が多く jp<=latin*0.15 を満たさない=素通り。

    直しの向き(suppress とは分ける・意図的):
      まるごと英語=救う日本語が無い→呼び側の english_gate が再生成/言い換え/保留で処理する。
      混在=**日本語本文は良い**→英語前置きだけ外科的に剥がして本文を残す(握り潰さない)。

    安全弁(通常返信を1ミリも変えない):
      ・頭から日本語なら触らない(前置き無し)。日本語がゼロ(まるごと非日本語)も触らない→後段へ委ねる。
      ・先頭の英字が散文量(40字)未満=固有名詞/URL/短い前置き→触らない。
      ・先頭にコード柵``` があれば触らない(コードを誤って剥がさない・安全側)。
      ・剥がした残りの日本語が薄い(20字未満)=実質まるごと英語→触らない→後段へ委ねる。

    返り値: (out_text, {"stripped":bool, "removed_latin":int})
      stripped=False のとき out_text は入力と同一(通常返信は不変)。
    """
    info = {"stripped": False, "removed_latin": 0}
    try:
        s = str(text or "")
        m = _JP_RE.search(s)
        if not m:
            return s, info                     # 日本語ゼロ=まるごと非日本語→suppressへ委ねる
        cut = m.start()
        if cut == 0:
            return s, info                     # 頭から日本語=前置き無し
        head = s[:cut]
        if "```" in head:
            return s, info                     # 先頭コード柵は剥がさない(安全側)
        core = re.sub(r"`[^`]*`", " ", head)   # インラインコード/URLを除いて散文の英字量を測る
        core = re.sub(r"https?://\S+", " ", core)
        head_latin = len(_LATIN_RE.findall(core))
        if head_latin < 40:
            return s, info                     # 固有名詞/短い前置き=通常返信、触らない
        body = s[cut:].lstrip(" \t\r\n")       # 日本語本文の頭から採用
        if len(_JP_RE.findall(body)) < 20:
            return s, info                     # 残りが薄い=実質まるごと英語→suppress/翻訳へ委ねる
        info["stripped"] = True
        info["removed_latin"] = head_latin
        return body, info
    except Exception:
        return str(text or ""), info           # fail-safe: ゲートで配送を殺さない
