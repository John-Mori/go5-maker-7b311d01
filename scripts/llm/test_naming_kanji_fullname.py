#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼称ゲート#3: 漢字フル名(三笘薫/一ノ瀬怜)の限定解禁の回帰テスト。

実行:            python scripts/llm/test_naming_kanji_fullname.py
変異(must-fail): python scripts/llm/test_naming_kanji_fullname.py --mutate

★2026-09-02 新設。出典= docs/departments/kaizen-analyst/設計_4種不具合恒久策_横断_2026-09-02.md §2-3
  (Chami承認済み・msg 1544671294820196453 の #3)。設計の逐語=
    検知: 「漢字フル名(2字以上連結)+ 直後の敬称/呼びかけ位置」の複合パターンに限って解禁。
          単字裸呼び(「怜」単独)は引き続き対象外(C-035)。
    挙動: **警告のみ**(偽陽性を数えてから格上げ)。
★0歩目(壊れていた実物)= デブライネの便に「三笘薫、進捗を頼む。」と出ても**1件も鳴らなかった**。
  真因は2枚: ①bare="三笘薫" の位置で allowed「三笘」が prefix として当たり許容形と読まれた
  (漢字名は `_boundary_ok` の対象外=カタカナ名だけが守られていた) ②怜/芽衣/咲季は
  honorific_required_targets に居ない(人事の意図)ので allowed が無く「判定不能=不問」だった。
★use / mention の線= 「呼んでいる」のは①直後に敬称 ②呼びかけ位置(行頭+直後が読点)だけ。
  名簿の列挙・表の行・出典の括弧・設定キーの説明は**言及**であって呼びかけではない。
  実測(2026-09-02・実便1,909本)で自動修正の差は0件=本文は1文字も変えていない。
★ルールは本番の写像を使わずここで固定する(人事部門が写像を育てても赤にならない)。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import naming_gate as ng   # noqa: E402

results = []

# 本番と同じ形の最小写像。★怜/芽衣/咲季は honorific_required に**置かない**
#   (本番の呼称ルール.json と同じ状態= 検出だけ target_detect_forms に在る)。
RULES = {
    "honorific_required_targets": {
        "三笘薫": {"bare_forms": ["三笘", "三笘薫"], "allowed": ["三笘さん"]},
    },
    "target_detect_forms": {
        "一ノ瀬怜": ["怜", "一ノ瀬", "一ノ瀬怜"],
        "早坂芽衣": ["芽衣"],
        "花海咲季": ["咲季"],
    },
    "speaker_target_overrides": [
        {"speaker": "ケヴィン・デブライネ", "target": "三笘薫", "allowed": ["三笘"]},
        {"speaker": "ルカ・モドリッチ", "target": "三笘薫", "allowed": ["三笘"]},
        {"speaker": "三笘薫", "target": "三笘薫",
         "allowed": ["三笘", "俺"], "forbidden": ["三笘さん"]},
        {"speaker": "アーモンドアイ", "target": "早坂芽衣", "allowed": ["芽衣"]},
        {"speaker": "__男性キャラ__", "target": "一ノ瀬怜",
         "allowed": ["怜"], "yobisute": True, "forbidden": ["一ノ瀬"]},
    ],
    "male_personas": ["シャビ・アロンソ", "ケヴィン・デブライネ", "ククール"],
}


def check(name, cond):
    results.append((name, bool(cond)))
    print(("  OK  " if cond else "  NG  ") + name)


def hits(who, text):
    """(target, found, reason) の集合。"""
    return {(v.get("target"), v.get("found"), v.get("reason"))
            for v in ng.naming_verdicts(who, "hr-room", text, RULES)}


def fixed(who, text, dept="aegis-gl"):
    """★測る部屋は hr-room ではない。人事部門は VOCATIVE_ONLY_DEPTS=
    「呼びかけ位置だけ直す」部屋なので、地の文の言及はそもそも別の弁(voc_only)で
    止まる=#3 が足したガード(`_fullname_called`)を一度も通らない。
    ガードそのものを検査するには、地の文も直す普通の部屋で測る。"""
    return ng.naming_corrections(who, dept, text, RULES).get("fixed")


def main():
    print("=== 呼称ゲート#3: 漢字フル名の限定解禁 ===")

    # --- A 鳴ってほしい(呼んでいる) --------------------------------------
    check("A1 呼び捨て可の話者がフル名で呼んだ(0歩目の実物)",
          ("三笘薫", "三笘薫", "override_allowed")
          in hits("ケヴィン・デブライネ", "三笘薫、進捗を頼む。"))
    check("A2 既定さん付けの話者がフル名+敬称",
          ("三笘薫", "三笘薫", "honorific_required")
          in hits("トトリ", "三笘薫さん、確認しました。"))
    check("A3 期待呼称が未定義の対象をフル名+敬称(怜)",
          ("一ノ瀬怜", "一ノ瀬怜さん", "kanji_fullname")
          in hits("トトリ", "一ノ瀬怜さん、確認しました。"))
    check("A4 同上(芽衣)",
          ("早坂芽衣", "早坂芽衣さん", "kanji_fullname")
          in hits("ククール", "早坂芽衣さん、よろしく。"))
    check("A5 フル名が呼びかけ位置(敬称なし・咲季)",
          ("花海咲季", "花海咲季", "kanji_fullname")
          in hits("トトリ", "花海咲季、これ見て。"))

    # --- B 黙ってほしい(呼んでいない/正しい形) ---------------------------
    check("B1 単字裸呼びは対象外のまま(C-035)",
          not hits("トトリ", "怜に伝えた。"))
    check("B2 呼び捨てを許された話者の正しい形",
          not hits("アーモンドアイ", "芽衣、おはよう。"))
    check("B3 既定の正しいさん付け",
          not hits("トトリ", "三笘さんに聞いた。"))
    check("B4 mention: 地の文でフル名に言及しただけ",
          not hits("トトリ", "一ノ瀬怜のcharacterfileを直した。"))
    check("B5 退行監視: 既存の呼び捨て違反は鳴り続ける",
          ("三笘薫", "三笘", "honorific_required")
          in hits("トトリ", "三笘に頼んだ。"))

    # --- C 自動修正は mention を1文字も触らない(設計=警告のみ) ------------
    #   ★下の5本は実便の地の文の型。話者は短縮形が期待される側(override allowed=
    #     「三笘」)= フル名→姓の丸ごと置換(FULL_KEY_SWAP)が届く経路で、#3 で判定域を
    #     広げた結果この経路へ新たに届くようになった出現。ここが書き換わると
    #     「■出典=分析部門(三笘)」「| 三笘 | 三笘 | 三笘さん |」に化ける。
    #     ★現行の実装では書き換わらない(実測: 実便1,909本で自動修正の差 0件)。
    #     それを保っているのが `_fullname_called` の1本= この検査の対象。
    WHO_SHORT = "ケヴィン・デブライネ"
    for label, src in (
        ("表の行", "| 三笘薫 | 三笘 | 三笘さん | 11 | 5 | 4 |"),
        ("出典の括弧", "■出典=分析部門(三笘薫)の共有正本 docs/departments/"),
        ("名簿の列挙", "参加人格8名=三笘薫/アーモンドアイ/オタコン"),
        ("設定キーの説明", "room_comments.mitoma(=三笘薫の一言)"),
        ("アイコンの説明", "実アイコン(三笘薫・早坂芽衣のDiscordアバター画像)"),
    ):
        check("C mention を触らない: %s" % label, fixed(WHO_SHORT, src) == src)
    # ★逆側の釘= 呼びかけは今までどおり直る(沈黙にはしない)。
    check("C use は直る: 呼びかけ位置のフル名は姓へ寄せる",
          fixed(WHO_SHORT, "三笘薫、進捗を頼む。") == "三笘、進捗を頼む。")

    # --- D 自称(話者==対象)は #3 の対象外(2026-09-02 人事裁定) ----------------
    #   裁定= DISPATCH-aegis-gl-1788355470901(ククール)。逐語=
    #     「`_is_self`(speaker==target)は kanji_fullname 検出を発火させない。
    #       呼称ゲートの目的は"対人呼称の崩れ"であって、自称は対人呼称じゃない」
    #     「Chamiが名指しで禁じた自称形だけは別経路で引き続き捕捉しろ
    #       =三笘の『三笘さん』・モドリッチの『ルカ』。これは self-override 行の forbidden が拾う」
    #   ★D1 が裁定前の本番との差= 敬称付きの自称フル名は**鳴っていた**(form != key だったため)。
    check("D1 自称のフル名+敬称は鳴らさない(裁定で不問)",
          not [v for v in hits("早坂芽衣", "早坂芽衣さん、です。")
               if v[2] == "kanji_fullname"])
    check("D2 自称のフル名が呼びかけ位置でも鳴らさない",
          not hits("花海咲季", "花海咲季、いきます。"))
    check("D3 禁じられた自称形は別経路で今までどおり鳴る(三笘さん)",
          ("三笘薫", "三笘さん", "forbidden")
          in hits("三笘薫", "三笘さん、了解した。"))
    check("D4 自称の除外を他人へ広げない(同じ本文でも話者が違えば鳴る)",
          ("早坂芽衣", "早坂芽衣さん", "kanji_fullname")
          in hits("トトリ", "早坂芽衣さん、です。"))

    ok = all(c for _, c in results)
    print("\n%d件中 %d件OK" % (len(results), sum(1 for _, c in results if c)))
    return 0 if ok else 1


# ==== 変異(must-fail)= どれも「動く別実装」であること(C-053)==================
def _mut_called_anywhere():
    """別実装: フル名が出ていれば常に『呼んでいる』と見る(use/mention を分けない)。"""
    ng._fullname_called = lambda s, i, key: str(key or "")


def _mut_honorific_only():
    """別実装: 敬称が直後に在る時だけ呼称と見る(呼びかけ位置を落とす)。"""
    def honorific_only(s, i, key):
        s = str(s or "")
        key = str(key or "")
        if not key:
            return ""
        for h in ng._HONORIFICS:
            if s.startswith(h, i + len(key)):
                return key + h
        return ""
    ng._fullname_called = honorific_only


def _mut_gate_off():
    """旧本番: 漢字フル名の判定そのものを持たない(#3 以前)。"""
    ng._kanji_fullname_verdicts = lambda persona, text, rules, seen_targets=(): []


def _mut_prefix_ok():
    """旧本番: 許容形が同じ位置に prefix として当たれば『許容形』と数える(穴)。"""
    def prefix_ok(text, bare, allowed):
        s = str(text or "")
        i = s.find(str(bare or ""))
        if i < 0:
            return False
        return any(a and s.startswith(str(a), i) for a in allowed)
    ng._appears_as_allowed = prefix_ok


def _mut_self_bare_only():
    """旧本番(裁定前): 自称を除くのは『フル名を裸で書いた時』だけ=敬称が付くと鳴る。

    ★行を消す変異ではなく、2026-09-02 22:20(commit 4084259)まで本番で動いていた
      実装をそのまま置き直す(C-053)。差は `_is_self` を見る位置だけ。
    """
    def old_impl(persona, text, rules, seen_targets=()):
        out = []
        if not ng.KANJI_FULLNAME_GATE:
            return out
        rules = rules or {}
        s = str(text or "")
        if not s:
            return out
        hrt = rules.get("honorific_required_targets") or {}
        detect = rules.get("target_detect_forms") or {}
        overrides = rules.get("speaker_target_overrides") or []
        keys = []
        for src in (hrt, detect):
            if isinstance(src, dict):
                for k in src:
                    if str(k).startswith("_") or k in keys:
                        continue
                    keys.append(k)
        for ov in overrides:
            tk = (ov or {}).get("target") if isinstance(ov, dict) else None
            if tk and tk != "*" and tk not in keys:
                keys.append(tk)
        for tk in keys:
            if tk in seen_targets:
                continue
            if not ng._is_kanji_fullname(tk) or tk not in s:
                continue
            ov = ng._effective_override(persona, tk, overrides)
            ent = hrt.get(tk) if isinstance(hrt.get(tk), dict) else {}
            allowed = [str(a) for a in ((ov or {}).get("allowed")
                                        or ent.get("allowed") or []) if str(a)]
            if tk in allowed:
                continue
            i = 0
            while True:
                i = s.find(tk, i)
                if i < 0:
                    break
                form = ng._fullname_called(s, i, tk)
                if not form:
                    i += 1
                    continue
                end = i + len(form)
                if form in allowed:
                    i = end
                    continue
                if ng._is_self(persona, tk) and form == tk:
                    i = end
                    continue        # ←ここが旧仕様(裸の時だけ不問)
                out.append({"target": tk, "found": form,
                            "expected": allowed, "reason": "kanji_fullname"})
                break
        return out
    ng._kanji_fullname_verdicts = old_impl


MUTANTS = (
    ("変異1 use/mention を分けない", _mut_called_anywhere,
     "C mention を触らない: 表の行"),
    ("変異2 呼びかけ位置を見ない(敬称だけ)", _mut_honorific_only,
     "A5 フル名が呼びかけ位置(敬称なし・咲季)"),
    ("変異3 漢字フル名の判定を持たない(旧本番)", _mut_gate_off,
     "A3 期待呼称が未定義の対象をフル名+敬称(怜)"),
    ("変異4 prefix を許容形と数える(旧本番の穴)", _mut_prefix_ok,
     "A1 呼び捨て可の話者がフル名で呼んだ(0歩目の実物)"),
    ("変異5 自称を裸の時だけ不問にする(裁定前の本番)", _mut_self_bare_only,
     "D1 自称のフル名+敬称は鳴らさない(裁定で不問)"),
)


def mutate():
    bad = 0
    saved = (ng._fullname_called, ng._kanji_fullname_verdicts, ng._appears_as_allowed)
    for name, fn, want_red in MUTANTS:
        del results[:]
        fn()
        try:
            print("\n=== %s ===" % name)
            try:
                main()
            except Exception as e:
                print("  (検査が例外で止まった: %s)" % e)
        finally:
            (ng._fullname_called, ng._kanji_fullname_verdicts,
             ng._appears_as_allowed) = saved
        red = [n for n, c in results if not c]
        hit = want_red in red
        print("  → 狙った1件が赤か: %s  (赤=%d件)" % ("OK" if hit else "NG", len(red)))
        if not hit:
            bad += 1
    print("\n変異 %d件中 %d件が狙いどおり赤" % (len(MUTANTS), len(MUTANTS) - bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(mutate() if "--mutate" in sys.argv else main())
