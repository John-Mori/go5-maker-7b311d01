#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼称ゲートC: フルネーム丸ごと置換(FULL_KEY_SWAP)の回帰テスト。

実行:            python scripts/llm/test_naming_fullkey.py
変異(must-fail): python scripts/llm/test_naming_fullkey.py --mutate

★2026-09-01 新設。引き金= Chami「またアロンソコーチが一ノ瀬怜呼びしてる。直らないの?」
  (msg 1544235216757858398 / 回送= 改善提案部門 1544236056134811698)。
  壊れた実物= naming_audit.jsonl の 2026-09-01 15:19:42 と 15:30:50
  (dept=hq persona=シャビ・アロンソ found="一ノ瀬" reason="forbidden")=
  **台帳では鳴っていたのに本文は1文字も直っていなかった**便。
★ルールは本番の写像(呼称ルール.json)を使わずここで固定する= 人事部門が写像を
  育てても赤にならない(判定の機構だけを検査する)。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import naming_gate as ng   # noqa: E402

results = []

# 本番と同じ形の最小写像= 怜(override.forbidden)・三笘薫(既定の敬称要求)。
RULES = {
    "honorific_required_targets": {
        "三笘薫": {"bare_forms": ["三笘"], "allowed": ["三笘さん"]},
    },
    "target_detect_forms": {
        "一ノ瀬怜": ["怜", "一ノ瀬", "一ノ瀬怜"],
    },
    "speaker_target_overrides": [
        {"speaker": "__男性キャラ__", "target": "一ノ瀬怜",
         "allowed": ["怜"], "yobisute": True, "forbidden": ["一ノ瀬"]},
        {"speaker": "アメス", "target": "一ノ瀬怜",
         "allowed": ["怜"], "forbidden": ["怜さん", "一ノ瀬怜さん"]},
        {"speaker": "早坂芽衣", "target": "一ノ瀬怜",
         "allowed": ["怜ちゃん"], "forbidden": ["怜くん"]},
    ],
    "male_personas": ["シャビ・アロンソ", "ケヴィン・デブライネ", "ククール"],
}

# 事故の実物(2026-09-01 15:30:50 dept=hq シャビ・アロンソ)の書き出し。
REAL = "一ノ瀬怜の「名乗り[名前]を1行目に、を全部屋で見直せ」——却下した。"
REAL_WANT = "怜の「名乗り[名前]を1行目に、を全部屋で見直せ」——却下した。"


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def fix(persona, dept, text):
    return ng.naming_corrections(persona, dept, text, RULES)


def main():
    # ---- 1) 壊れている実物が直ること(0歩目の再現をそのまま検査にした) ----
    v = ng.naming_verdicts("シャビ・アロンソ", "hq", REAL, RULES)
    # ★2026-09-08= 理由の**札**が forbidden から override_allowed へ移った(本文の直り方は不動)。
    #   人事裁定「フル名の内側に収まった当たりは不問」(対人拡張)を入れたので、
    #   『一ノ瀬怜』の中の『一ノ瀬』はもう拾わない= 台帳が「裸の姓で呼んだ」と嘘をつかなくなった。
    #   代わりに**フル名そのもの**が override_allowed で立つ= Chami 2026-09-01
    #   『またアロンソコーチが一ノ瀬怜呼びしてる。直らないの?』の網はそのまま生きている。
    #   ここで見たいのは「死に網でない」ことなので、札ではなく**鳴っていること**を見る。
    check("実物: 検出は前から鳴っていた(死に網ではない)",
          [x for x in v if x.get("reason") in ("forbidden", "override_allowed")])
    r = fix("シャビ・アロンソ", "hq", REAL)
    check("実物: 本文がフルネームごと「怜」へ直る", r["fixed"] == REAL_WANT)
    check("実物: applied に載る", [a for a in r["applied"] if a.get("to") == "怜"])
    check("実物: applied の found は**実際に使われた形**=フルネーム",
          [a for a in r["applied"] if a.get("found") == "一ノ瀬怜"])

    # ---- 2) 地の文でも直る(呼びかけ位置に限らない=Chamiが見た形は全部地の文) ----
    for nm, src, want in (
        ("括弧の中", "プラットフォームSE(一ノ瀬怜)のcommitが効いた。",
         "プラットフォームSE(怜)のcommitが効いた。"),
        ("助詞の前", "デブライネ、一ノ瀬怜に伝えておけ。", "デブライネ、怜に伝えておけ。"),
        ("主語", "一ノ瀬怜が07:00に応答済みだ。", "怜が07:00に応答済みだ。"),
    ):
        check(f"地の文: {nm}", fix("シャビ・アロンソ", "hq", src)["fixed"] == want)

    # ---- 3) 禁止形がフルネームを丸ごと含む形(「一ノ瀬怜さん」)も1スパンで直る ----
    check("フルネーム+敬称: アメスの「一ノ瀬怜さん」→「怜」",
          fix("アメス", "hq", "一ノ瀬怜さんへ回した。")["fixed"] == "怜へ回した。")

    # ---- 4) 触ってはいけない所(ここが崩れたら本文破壊) ----
    for nm, persona, dept, src in (
        ("名乗りタグの中", "一ノ瀬怜", "platform-se", "[一ノ瀬怜] 本文だ。"),
        ("引用の中", "シャビ・アロンソ", "hq", "「一ノ瀬怜」という表記の話だ。"),
        ("人事部門の地の文(2026-08-24の実測)", "シャビ・アロンソ", "hr-room",
         "一ノ瀬怜のoverrideへ1語追加した。"),
        ("既に許容形", "シャビ・アロンソ", "hq", "怜に伝えておけ。"),
        ("裸の姓だけ(置換先が一意でない)", "シャビ・アロンソ", "hq", "一ノ瀬に伝えておけ。"),
        ("愛称ゆれ(フルネームではない)", "早坂芽衣", "hq", "怜くんに聞いた。"),
        ("敬称ゆれの姓+名= 従来どおり警告のみ", "シャビ・アロンソ", "hq", "三笘薫が来た。"),
    ):
        r = fix(persona, dept, src)
        check(f"不変: {nm}", r["fixed"] == src)

    # ---- 5) 直せなかった出現は警告として残る(沈黙にしない) ----
    r = fix("シャビ・アロンソ", "hq", "一ノ瀬に伝えておけ。")
    check("警告: 裸の姓は remaining に残る", len(r["remaining"]) == 1)
    r = fix("シャビ・アロンソ", "hq", "一ノ瀬怜と一ノ瀬の両方が出る便。")
    check("警告: フルネームを直しても、残った裸の姓の警告は消さない",
          r["fixed"] == "怜と一ノ瀬の両方が出る便。" and len(r["remaining"]) == 1)

    # ---- 6) 敬称要求(honorific_required)は範囲外=写像に書いたペアだけ(C-035) ----
    check("範囲: FULL_KEY_SWAP_REASONS に honorific_required は入っていない",
          "honorific_required" not in ng.FULL_KEY_SWAP_REASONS)
    check("敬称要求の裸の姓は従来どおり直る(既存の挙動を壊していない)",
          fix("シャビ・アロンソ", "hq", "三笘が来た。")["fixed"] == "三笘さんが来た。")

    # ---- 7) fail-open(§3 可用性に関わる所は fail-open) ----
    check("fail-open: rules が None なら素通し",
          ng.naming_corrections("シャビ・アロンソ", "hq", REAL, None)["fixed"] == REAL)
    check("fail-open: 空本文", ng.naming_corrections("シャビ・アロンソ", "hq", "", RULES)["fixed"] == "")

    # ---- 8) 配線(共有関数の呼び出し元を数える・§3) ----
    here = os.path.dirname(os.path.abspath(__file__))
    callers = []
    for rel in ("dept_daemon.py", "output_gates.py"):
        with open(os.path.join(here, rel), encoding="utf-8") as f:
            if "naming_corrections(" in f.read():
                callers.append(rel)
    check("配線: naming_corrections の呼び出し元は常駐/relayとミラーの2本",
          sorted(callers) == ["dept_daemon.py", "output_gates.py"])

    ok = sum(1 for _, c in results if c)
    ng_ = len(results) - ok
    print(f"\n{ok} PASS / {ng_} FAIL")
    return 0 if ng_ == 0 else 1


# ---------------------------------------------------------------- 変異(C-053)
#   ★変異は「動く別の実装」へ戻す= 文法を壊した偽の赤にしない。
def _mut_off():
    """変異1= FULL_KEY_SWAP を入れなかった世界(旧の挙動)。動くが実物を直せない。"""
    ng.FULL_KEY_SWAP = False


def _mut_vocative_only():
    """変異2= フルネームも「呼びかけ位置だけ」に閉じた実装。地の文の事故が残る。"""
    orig = ng._is_vocative

    def patched(s, i, end):
        return orig(s, i, end)
    ng._is_vocative = patched
    # full_key の免除を外す= whole_swap の制限をそのまま効かせる
    ng.FULL_KEY_SWAP_REASONS = ()


def _mut_all_reasons():
    """変異3= 理由を絞らず honorific_required まで丸ごと置換する実装。
    動くが「三笘薫が来た」を「三笘さんが来た」へ書き換える(名簿・紹介文が化ける)。"""
    ng.FULL_KEY_SWAP_REASONS = ("forbidden", "override_allowed", "honorific_required")


MUTANTS = (
    ("変異1 FULL_KEY_SWAP 無し(旧の挙動)", _mut_off,
     "実物: 本文がフルネームごと「怜」へ直る"),
    ("変異2 呼びかけ位置だけに閉じる", _mut_vocative_only,
     "地の文: 括弧の中"),
    ("変異3 敬称要求まで丸ごと置換", _mut_all_reasons,
     "不変: 敬称ゆれの姓+名= 従来どおり警告のみ"),
)


def mutate():
    bad = 0
    o_flag, o_reasons, o_voc = ng.FULL_KEY_SWAP, ng.FULL_KEY_SWAP_REASONS, ng._is_vocative
    for name, fn, want_red in MUTANTS:
        del results[:]
        fn()
        try:
            print(f"\n=== {name} ===")
            try:
                main()
            except Exception as e:
                print("  (検査が例外で止まった: %s)" % e)
        finally:
            ng.FULL_KEY_SWAP, ng.FULL_KEY_SWAP_REASONS, ng._is_vocative = o_flag, o_reasons, o_voc
        red = [n for n, c in results if not c]
        hit = want_red in red
        print(f"  → 狙った1件が赤か: {'OK' if hit else 'NG'}  (赤={len(red)}件)")
        if not hit:
            bad += 1
    print(f"\n変異 {len(MUTANTS)}件中 {len(MUTANTS) - bad}件が狙いどおり赤")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(mutate() if "--mutate" in sys.argv else main())
