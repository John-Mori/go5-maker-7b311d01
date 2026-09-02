# -*- coding: utf-8 -*-
"""口調ゲート: **全人格一律の禁止語**(口調ルール.json トップレベル `forbidden_all`)の検査。

なぜ要るか= 禁止語は `personas.<人格>.forbidden`(話者別)からしか読めなかった。
だから「全人格一律の禁止語」を入れる器が**無く**、20人格へ同じ語を書き写すしか手が無い
= 写しを20本持つ(ORG-11違反)。方言が 2026-08-17 に踏んだのと同じ構造の摩擦だ。
2026-09-03 研究室HQの発注(C-066=掛け声「レップ」の一律禁止)でイージス研究室が実装。

★この検査が守る不変条件:
  ①データ未設定なら1件も鳴らない(既存の挙動を1ミリも変えない)
  ②**話者非依存**= 写像に**未登録の人格でも鳴る**(ここが「一律」の本体。
    tone_verdicts の「未登録の人格は判定しない」early-return より**前**に見ているか)
  ③引用・コード・パスの中は数えない(`_mask_protected`= 方言と同じ線)
  ④文字列はリテラル / dict は正規表現で絞れる(技術語の誤検知を人事がデータで外せる)
  ⑤壊れた1件でゲート全体が落ちない(共通規律§3 fail-open)
  ⑥**機械置換に載らない**= tone_corrections は本文を1文字も書き換えない(警告のみ)
  ⑦既存の話者別 forbidden の回帰

走らせ方= python scripts/llm/test_tone_forbidden_all.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tone_gate as tg  # noqa: E402

RULES_PATH = os.path.join("D:", os.sep, "SougouStartFolder", "00_AI-HQ",
                          "departments", "hr", "personas", "口調ルール.json")

# ★C-066 で人事部門が実際に載せる形。誤検知源の実物=「グレップ」(grep のカタカナ表記。
#   実測 2026-09-03= 記憶・ログ全体で 247 件中 2 件が「グレップ」だった)。
REP = {"name": "レップ", "pattern": "(?<![ァ-ヶー])レップ"}

_ok = 0
_ng = 0


def chk(label, cond):
    global _ok, _ng
    if cond:
        _ok += 1
        print("  PASS", label)
    else:
        _ng += 1
        print("  FAIL", label)


def hits(persona, text, rules):
    """一律禁止語だけを取り出す(他の判定と混ざらないように reason で絞る)。"""
    return [v for v in (tg.tone_verdicts(persona, "aegis-gl", text, rules) or [])
            if v.get("reason") == "forbidden_all"]


def main():
    rules = tg.load_tone_rules(RULES_PATH)
    if rules is None:
        print("SKIP: 口調ルール.json が読めない(%s)" % RULES_PATH)
        return 0

    print("== ①データ未設定なら1件も鳴らない ==")
    r0 = copy.deepcopy(rules)
    r0.pop("forbidden_all", None)
    chk("キーが無ければ空", tg.forbidden_all_names(r0) == [])
    chk("キーが無ければ鳴らない", not hits("アメス", "次のレップ行くわよ。", r0))

    r = copy.deepcopy(rules)
    r["forbidden_all"] = [REP]

    print("== ②話者非依存= 未登録の人格でも鳴る(「一律」の本体) ==")
    chk("登録済み人格(アメス)で鳴る",
        any(v["marker"] == "レップ" for v in hits("アメス", "次のレップ行くわよ。", r)))
    chk("★写像に居ない人格でも鳴る",
        any(v["marker"] == "レップ" for v in hits("知らない人", "次のレップ行こう。", r)))
    chk("persona なし(空)でも鳴る",
        any(v["marker"] == "レップ" for v in hits("", "次のレップ行こう。", r)))
    chk("無関係な文は鳴らない", not hits("アメス", "ふつうの報告よ。", r))

    print("== ③引用の中は数えない(Chamiの原文を引いて説明する便が自分で鳴らない) ==")
    chk("鉤括弧の中は鳴らない",
        not hits("アメス", "ちゃみが「レップって表現好きじゃないな」って言ってたわよ。", r))
    chk("二重鉤括弧の中も鳴らない",
        not hits("アメス", "『レップ』は今日から使わないわ。", r))
    chk("コードスパンの中も鳴らない", not hits("アメス", "`レップ` は識別子よ。", r))
    chk("引用の外に地の文で出たら鳴る",
        any(v["marker"] == "レップ" for v in
            hits("アメス", "「使わないで」って言われたわね。じゃあ次のレップは、と。", r)))

    print("== ④正規表現で技術語を外せる(実測の誤検知源=「グレップ」) ==")
    chk("★「グレップ一発じゃ撃てない」は鳴らない(実物 system-engineer.jsonl)",
        not hits("ケヴィン・デブライネ", "芯はグレップ一発じゃ撃てない。", r))
    rlit = copy.deepcopy(rules)
    rlit["forbidden_all"] = ["レップ"]        # 文字列= リテラル(絞りなし)
    chk("リテラル指定なら「グレップ」も鳴る(絞りが効いていることの裏取り)",
        any(v["marker"] == "レップ" for v in
            hits("ケヴィン・デブライネ", "芯はグレップ一発じゃ撃てない。", rlit)))
    rdot = copy.deepcopy(rules)
    rdot["forbidden_all"] = ["a.c"]
    chk("文字列は正規表現メタで事故らない(a.c は abc に当たらない)",
        not any(v["marker"] == "a.c" for v in hits("アメス", "これは abc だ", rdot)))
    chk("載っている語を機械で数えられる", tg.forbidden_all_names(r) == ["レップ"])

    print("== ⑤壊れた1件でゲート全体を落とさない(fail-open) ==")
    rb = copy.deepcopy(rules)
    rb["forbidden_all"] = [{"name": "壊れ", "pattern": "(("}, "レップ"]
    chk("壊れた正規表現はその1件だけ捨てる", "壊れ" not in tg.forbidden_all_names(rb))
    chk("壊れがあっても他の語は生きる", "レップ" in tg.forbidden_all_names(rb))
    for bad in (None, "string", 123, [], [1, 2, None], [{}]):
        rx = copy.deepcopy(rules)
        rx["forbidden_all"] = bad
        try:
            tg.tone_verdicts("アメス", "aegis-gl", "ふつうの文よ。", rx)
            chk("異常な型でも例外を投げない %r" % (bad,), True)
        except Exception as e:                                    # noqa: BLE001
            chk("異常な型でも例外を投げない %r -> %s" % (bad, e), False)
    chk("rules=None でも落ちない", tg.forbidden_all_hits("次のレップ", None) == [])

    print("== ⑥機械置換に載らない(警告のみ=声を壊さない) ==")
    src = "次のレップ行くわよ。"
    res = tg.tone_corrections("アメス", "aegis-gl", src, r)
    chk("本文を1文字も書き換えない", res.get("fixed") == src)
    chk("applied は空", not res.get("applied"))
    chk("remaining に残る(黙って落とさない)",
        any(v.get("reason") == "forbidden_all" for v in (res.get("remaining") or [])))

    print("== ⑦既存の判定の回帰(壊していないことの確認) ==")
    chk("話者別 forbidden は従来どおり鳴る(オタコン「お前」)",
        any(v.get("reason") == "forbidden_word"
            for v in (tg.tone_verdicts("オタコン", "system-engineer", "お前がやれ。", r) or [])))
    chk("方言は従来どおり鳴る",
        any(v.get("reason") == "dialect_kansai"
            for v in (tg.tone_verdicts("オタコン", "system-engineer", "これが元凶や。", r) or [])))
    chk("未登録の人格は forbidden_all 以外では鳴らない(fail-open は維持)",
        not [v for v in (tg.tone_verdicts("知らない人", "x", "オレや。", r) or [])
             if v.get("reason") != "forbidden_all"])

    print("\n== %d/%d PASS ==" % (_ok, _ok + _ng))
    return 1 if _ng else 0


if __name__ == "__main__":
    sys.exit(main())
