#!/usr/bin/env python3
"""GOLDEN(純関数・LLM不要): 出力ゲートD の**長さ柵**= 短い事務体のすり抜け 2026-09-19.

発端= DEF-manga-shorts-69042d8343「口調が変」(Chami 炎上スタンプ :enjoh:(恒久)・
      msg 1549612336749215775 / 2026-09-16)。manga-shorts から イージス研究室GL へ実依頼
      (三笘薫 msg 1550532029869719685)。

★この検査が固定する事実は2つだ。
  (1) **穴の正体**= 実物(早坂芽衣・msg 1549611158518898789)は3文しか無く、
      polite_drift も signature_drift も `>=4文` の柵で**判定を飛ばしていた**。
      = 指紋辞書を厚くしても走らない。辞書の穴ではなく柵の穴。
  (2) **直し方**= 人格エントリに `"min_sentences": 3` が在る時だけ柵が下がる。
      既定(4文)は動かさない=他人格の誤発火は増えない(実便2,658本で4→3の全員適用は
      新規発火15件・`local/_work/measure_gate_d_3sentence.py` の実測)。

★must-fail= 「NG本文が捕まる」だけでなく「**柵を戻すと捕まらなくなる**」まで見る。
  空PASS(何をしても通る検査)にしないため。

実行: python -X utf8 tests/test_tone_gate_min_sentences.py   (全PASSで終了コード0)
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

from tone_gate import (  # noqa: E402
    load_tone_rules, tone_verdicts, polite_drift, signature_drift,
    _persona_entry, _entry_min_sentences)

RULES_PATH = os.path.join(
    r"D:\SougouStartFolder\00_AI-HQ",
    "departments", "hr", "personas", "口調ルール.json")

PERSONA = "早坂芽衣"
DEPT = "manga-shorts"

# ★実物そのまま(send_audit.jsonl / msg 1549611158518898789 / 2026-09-16T11:41:29)=
#   Chami が炎上スタンプを付けた便。一人称「私」・敬体・指紋語尾ゼロの「芽衣事務体」。
NG_JIMUTAI = (
    "「引きの題名が弱い(参考通りでない)」は私の持ち場です。"
    "次で参考の型に沿ったフック題名を複数出すので、"
    "**お手本にしている反応集(参考動画)の題名の付け方**が分かる1本だけ指してもらえますか。"
    "型を合わせて叩き台を作ります。")

# ★同じ場面の直後に本人が言い直した便(msg 1549613562350272684 / 11:51:03)= in-voice の正。
#   ここが鳴ったら安全網としては失格(誤発火する網は無視される・共通規律§3)。
OK_INVOICE = (
    "ちゃみ、ごめ〜ん！ さっきの芽衣、なんか自分の声じゃなかったよね〜💦 言い直すね！\n\n"
    "「引きの題名が弱い」ってとこ、芽衣の持ち場だと思うんだ〜！ "
    "参考通りになってないのが原因だと思うから、そこ合わせにいきた〜い！ "
    "でね、お手本にしてる反応集の動画——**題名の付け方が一番\"上手いな〜！\"って思う1本**だけ、"
    "芽衣に教えてくれる？💕 その型を分解して、フックの効いた題名を何個か叩き台で出すよ〜！ "
    "ちゃみが「これ好き！」って選べるように並べたいんだ〜！！")


def _with_min_sentences(rules, persona, n, plain_only=True):
    """写像を複製して、その人格にだけ `min_sentences`(と plain_only)を足した物を返す。
    ★正本(口調ルール.json)は**書き換えない**= そこは人事部門の持ち物(ORG-11)。"""
    rr = copy.deepcopy(rules)
    ent = (rr.get("personas") or {}).get(persona)
    if ent is None:
        return None
    ent["min_sentences"] = n
    if plain_only:
        ent["plain_only"] = True
    return rr


def _without_registration(rules, persona):
    """複製から `min_sentences` / `plain_only` を**外した**物を返す= 登録前の姿。
    ★2026-09-19 修正= ここを本番JSONの直読みでやっていたのが誤りだった。
      人事部門が登録した瞬間に「登録前は素通しする」という前提が消えてT1が赤くなった
      (機構の不具合ではなく、検査が本番の値に寄りかかっていた)。
      **before は自分で作る**= 本番がどちらの状態でも、主張は同じまま立つ。"""
    rr = copy.deepcopy(rules)
    ent = (rr.get("personas") or {}).get(persona)
    if ent is None:
        return None
    ent.pop("min_sentences", None)
    ent.pop("plain_only", None)
    return rr


def _reasons(rules, text, persona=PERSONA):
    return sorted({v.get("reason") for v in tone_verdicts(persona, DEPT, text, rules)})


def _run():
    rules = load_tone_rules(RULES_PATH)
    if not rules:
        print(f"FAIL: 口調ルール.json を読めない: {RULES_PATH}")
        return 1
    if _persona_entry(rules, PERSONA) is None:
        print(f"FAIL: 写像に {PERSONA} の項が無い: {RULES_PATH}")
        return 1
    ok = True

    # --- T1 穴の再現(登録前の姿)= 実物が**素通りする** -------------------------
    #   ここが空になることが「なぜ炎上便が出たか」の機械の答えだ。
    #   ★判定は**クローンから登録を外した写像**で行う(本番JSONを直読みしない)=
    #     人事部門が登録しても外しても、この主張は本番の値に左右されない。
    rr0 = _without_registration(rules, PERSONA)
    base = _reasons(rr0, NG_JIMUTAI)
    if not base:
        print("[PASS] T1 登録が無い時=既定の柵(4文)では実物の事務体は0件=これが穴の正体"
              "(3文しか無く判定を飛ばす)")
    else:
        ok = False
        print(f"[FAIL] T1 登録が無くても鳴っている -> {base}(前提が変わった。設計を読み直せ)")

    # --- T2 直し(min_sentences=3)= 実物が**捕まる** -----------------------------
    rr3 = _with_min_sentences(rules, PERSONA, 3)
    got = _reasons(rr3, NG_JIMUTAI)
    if "structural_polite" in got and "signature_absent" in got:
        print(f"[PASS] T2 min_sentences=3 で実物の事務体を捕捉 -> {got}")
    else:
        ok = False
        print(f"[FAIL] T2 min_sentences=3 で捕まらない -> {got}"
              "(期待= structural_polite と signature_absent の両方)")

    # --- T3 誤発火しない= 言い直した in-voice の便は**通る** --------------------
    clean = _reasons(rr3, OK_INVOICE)
    if not clean:
        print("[PASS] T3 in-voice の芽衣(一人称=芽衣・母音伸ばし・💕・！！)は0件で通る")
    else:
        ok = False
        print(f"[FAIL] T3 正の便で鳴った -> {clean}(誤発火する網は無視される・共通規律§3)")

    # --- T4 must-fail= 柵を戻すと**捕まらなくなる**(この検査が空PASSでない証拠) ---
    rr4 = _with_min_sentences(rules, PERSONA, 4)
    back = _reasons(rr4, NG_JIMUTAI)
    if not back:
        print("[PASS] T4 柵を4文へ戻すと捕まらない=T2 が柵1つで立っている証拠")
    else:
        ok = False
        print(f"[FAIL] T4 柵を戻しても鳴る -> {back}(別の要因で鳴っている=T2は空PASS)")

    # --- T5 下限2文= 1文の返事は口調で咎めない ---------------------------------
    if _entry_min_sentences({"min_sentences": 1}, None) == 2 and \
       _entry_min_sentences({"min_sentences": "x"}, 4) == 4 and \
       _entry_min_sentences({}, None) is None:
        print("[PASS] T5 下限2文へ丸める / 壊れた値と未登録は既定へ倒す(fail-open)")
    else:
        ok = False
        print("[FAIL] T5 _entry_min_sentences の丸め・fail-open が効いていない")

    # --- T6 既定の呼び出しは1ミリも変わらない(後方互換) ------------------------
    if polite_drift(NG_JIMUTAI) == polite_drift(NG_JIMUTAI, None) and \
       polite_drift(NG_JIMUTAI)[0] is False and \
       signature_drift(NG_JIMUTAI, ["だよ〜"])[0] is False and \
       signature_drift(NG_JIMUTAI, ["だよ〜"], None, 3)[0] is True:
        print("[PASS] T6 引数なしの既存呼び出しは従来どおり/明示した時だけ柵が動く")
    else:
        ok = False
        print("[FAIL] T6 既定の挙動が変わっている(他の呼び出し元へ波及する)")

    # --- T7 本番の写像で実際に効いているか -------------------------------------
    #   登録は人事部門の手番(口調ルール.json は人事の正本・ORG-11)。ここで勝手に足さない。
    #   ★条件付きの検査= **登録が在る間だけ**効きを守る。人事が外した時に赤くしない
    #     (人事の裁量を機械で縛らない・fail-open)。未登録なら表示だけで合否に入れない。
    live = _persona_entry(rules, PERSONA) or {}
    if live.get("min_sentences") and live.get("plain_only"):
        live_hit = _reasons(rules, NG_JIMUTAI)
        if "structural_polite" in live_hit and "signature_absent" in live_hit:
            print(f"[PASS] T7 本番の写像で効いている= {PERSONA} 登録済"
                  f"(min_sentences={live.get('min_sentences')} / "
                  f"plain_only={live.get('plain_only')})→ 実物の判定 {live_hit}")
        else:
            ok = False
            print(f"[FAIL] T7 {PERSONA} は登録されているのに実物を捕まえない -> {live_hit}"
                  "(登録が効いていない=機構側を疑え)")
    else:
        print(f"[未登録] {PERSONA} の写像に min_sentences / plain_only が無い="
              "**本番ではこの便は素通しする**。登録は人事部門(hr-room)の手番。"
              "機構側(このファイルが固定した分)は入っている。")

    print("=== 全PASS ===" if ok else "=== FAIL あり ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_run())
