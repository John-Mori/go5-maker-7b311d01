#!/usr/bin/env python3
"""tone_rewrite(出力ゲートD-2・案F)のテスト。 2026-08-16

★**判定と分岐は本物のまま**回す。偽物にするのは**外へ出る手(LLM呼び出し)だけ**
  (共通規律§3「ソースの文字列一致は検査ではない。入力を差し替えて経路を実行で通せ」)。
  → `ask=` に関数を差し込むと、書き直し後の再判定(tone_gate.tone_verdicts)も
    受け入れ判定(accept)も**本番と同じコード**が走る。
★写像は本番の 口調ルール.json をそのまま読む(テスト用の偽ルールを作らない=ズレる)。

走らせ方: python scripts/llm/test_tone_rewrite.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import tone_gate                                   # noqa: E402
import tone_rewrite as TR                          # noqa: E402

RULES_PATH = os.path.join(ROOT, "..", "00_AI-HQ", "departments", "hr",
                          "personas", "口調ルール.json")
RULES = tone_gate.load_tone_rules(RULES_PATH)

OK = [0]
NG = []


def check(name, cond, detail=""):
    if cond:
        OK[0] += 1
        print("  PASS %s" % name)
    else:
        NG.append(name)
        print("  FAIL %s %s" % (name, detail))


def remaining_of(persona, dept, text):
    """本番と同じ経路で「機械が直せなかった検知」を得る。"""
    return (tone_gate.tone_corrections(persona, dept, text, RULES) or {}).get("remaining") or []


# 実物= 2026-08-16 14:08:34 / dept=system-engineer / msg 1538408581752426526 の咲季便(抜粋)。
BROKEN = ("ちゃみ、いま直したところや。まだ「直った」とは言わへん——"
          "ちゃみの画面で見るまでは確認待ちや。他の🔥も続けて手ぇ動かしとく。")
# 同じ事実(数字も識別子も無い便)を咲季の正しい声にした物。
FIXED = ("ちゃみ、いま直したところよ。まだ「直った」とは言わないわ——"
         "ちゃみの画面で見るまでは確認待ちね。他の🔥も続けて手を動かしておくわ。")

print("=== 0. 前提 ===")
check("口調ルール.jsonが読める", bool(RULES), RULES_PATH)
check("咲季の写像がある", bool(tone_gate._persona_entry(RULES, "花海咲季")))

print("=== 1. 対象の登録制(既定は見ない) ===")
check("方言は対象", len(TR.targets([{"reason": "dialect_kansai"}])) == 1)
check("敬体・指紋・禁止語は対象",
      len(TR.targets([{"reason": "structural_polite"}, {"reason": "signature_absent"},
                      {"reason": "forbidden_word"}])) == 3)
check("話者の取り違えは対象外(ゲートFの管轄)",
      TR.targets([{"reason": "speaker_misattributed"}]) == [])
check("一人称の食い違いは対象外(置換先が一意でない分をLLMに当てさせない)",
      TR.targets([{"reason": "first_person_mismatch"}]) == [])
check("知らないreasonは素通し", TR.targets([{"reason": "unknown_new_thing"}]) == [])

print("=== 2. 崩れた実物が本番の検知に掛かること(前提の確認) ===")
rem = remaining_of("花海咲季", "system-engineer", BROKEN)
reasons = sorted(set(v.get("reason") for v in rem))
check("実物に方言の検知が出る", "dialect_kansai" in reasons, reasons)
check("書き直し対象が1件以上", len(TR.targets(rem)) >= 1, reasons)
check("直した文には検知が出ない",
      tone_gate.tone_verdicts("花海咲季", "system-engineer", FIXED, RULES) == [],
      tone_gate.tone_verdicts("花海咲季", "system-engineer", FIXED, RULES))

print("=== 3. 通る道(採用) ===")
r = TR.rewrite_once("花海咲季", "system-engineer", BROKEN, rem, RULES, ask=lambda p: FIXED)
check("採用される", r["ok"], r["why"])
check("本文が書き直し後に差し替わる", r["text"] == FIXED)
check("呼んだ記録が残る", r["attempted"] and r["targets"])
check("残った検知は空", r["after"] == [], r["after"])

print("=== 4. 事実を変えたら弾く(ここが案Fの命) ===")
NUMTEXT = ("ちゃみ、31体への載せ替えは 15:18:12 に終わったで。commit 2128ea6 や。"
           "詳しくは local/_work/dialect_live.txt を見てや。")
nrem = remaining_of("花海咲季", "system-engineer", NUMTEXT)
check("数字入りの便も検知される", len(TR.targets(nrem)) >= 1)

r = TR.rewrite_once("花海咲季", "system-engineer", NUMTEXT, nrem, RULES,
                    ask=lambda p: ("ちゃみ、30体への載せ替えは 15:18:12 に終わったわ。"
                                   "commit 2128ea6 よ。詳しくは local/_work/dialect_live.txt を見てね。"))
check("数字が1つ変わったら不採用", not r["ok"], r["why"])
check("不採用なら元の本文のまま", r["text"] == NUMTEXT)
check("理由が数字だと分かる", "数字" in r["why"], r["why"])

r = TR.rewrite_once("花海咲季", "system-engineer", NUMTEXT, nrem, RULES,
                    ask=lambda p: ("ちゃみ、31体への載せ替えは 15:18:12 に終わったわ。"
                                   "commit 2128ea6 よ。詳しくは local/_work/dialect_lives.txt を見てね。"))
check("ファイル名が変わったら不採用", not r["ok"], r["why"])
check("理由が識別子だと分かる", "識別子" in r["why"], r["why"])

URLTEXT = "ちゃみ、実物はここや→ https://discord.com/channels/1/2/3 見といてや。"
urem = remaining_of("花海咲季", "system-engineer", URLTEXT)
r = TR.rewrite_once("花海咲季", "system-engineer", URLTEXT, urem, RULES,
                    ask=lambda p: "ちゃみ、実物はここよ→ https://discord.com/channels/1/2/4 見ておいてね。")
check("URLが変わったら不採用", not r["ok"], r["why"])

print("=== 5. 要約・膨張・名乗りの増殖を弾く ===")
r = TR.rewrite_once("花海咲季", "system-engineer", BROKEN, rem, RULES,
                    ask=lambda p: "直したわ。")
check("要約は不採用(長さの帯の外)", not r["ok"], r["why"])
check("理由が長さだと分かる", "長さ" in r["why"], r["why"])

r = TR.rewrite_once("花海咲季", "system-engineer", BROKEN, rem, RULES,
                    ask=lambda p: "[アメス] " + FIXED)
check("名乗りタグが増えたら不採用", not r["ok"], r["why"])

print("=== 6. 直っていない書き直しは採用しない ===")
r = TR.rewrite_once("花海咲季", "system-engineer", BROKEN, rem, RULES,
                    ask=lambda p: BROKEN.replace("手ぇ", "手"))
check("方言が残っていたら不採用", not r["ok"], r["why"])
check("理由に崩れが残ると出る", "残っている" in r["why"], r["why"])

print("=== 7. fail-open(この段が配送を殺さない) ===")
def _boom(p):
    raise RuntimeError("通信断")


r = TR.rewrite_once("花海咲季", "system-engineer", BROKEN, rem, RULES, ask=_boom)
check("例外でも元の本文を返す", (not r["ok"]) and r["text"] == BROKEN, r["why"])
check("例外は理由に残る", "例外" in r["why"], r["why"])

r = TR.rewrite_once("花海咲季", "system-engineer", BROKEN, rem, RULES, ask=lambda p: "")
check("空の返しでも元の本文", (not r["ok"]) and r["text"] == BROKEN)

called = []
r = TR.rewrite_once("花海咲季", "system-engineer", "ちゃみ、これは普通の便だわ。",
                    [], RULES, ask=lambda p: called.append(1) or FIXED)
check("対象0件ならLLMを呼ばない", not called and not r["attempted"], r["why"])

r = TR.rewrite_once("花海咲季", "system-engineer", BROKEN, rem, None, ask=lambda p: FIXED)
check("rules未ロードなら何もしない", (not r["ok"]) and r["text"] == BROKEN, r["why"])

r = TR.rewrite_once("居ない人格", "system-engineer", BROKEN,
                    [{"reason": "dialect_kansai", "marker": "や"}], RULES, ask=lambda p: FIXED)
check("写像に無い人格は触らない", (not r["ok"]) and r["text"] == BROKEN, r["why"])

print("=== 8. 下ごしらえ(囲みの剥ぎ・指示文) ===")
check("```で囲まれた返しを剥ぐ", TR.clean_candidate("```\nあいうえお\n```") == "あいうえお")
check("言語つきの囲みも剥ぐ", TR.clean_candidate("```text\nあいうえお\n```") == "あいうえお")
check("素の本文はそのまま", TR.clean_candidate("  あいうえお  ") == "あいうえお")

p = TR.build_prompt("花海咲季", tone_gate._persona_entry(RULES, "花海咲季"), BROKEN,
                    TR.targets(rem))
check("指示文に人格名が入る", "花海咲季" in p)
check("指示文に指紋語尾が入る", "わよ" in p)
check("指示文に本文が入る", BROKEN in p)
check("指示文に事実を変えるなと書いてある", "1文字も変えない" in p)

print("=== 9. 事実の指紋(hard_tokens) ===")
check("数字は多重集合", TR.hard_tokens("1と1と2")["nums"] == ["1", "1", "2"])
check("ASCII識別子を拾う", "app.js" in TR.hard_tokens("app.js を直した")["idents"])
check("日本語からは識別子を作らない", TR.hard_tokens("直したわよ")["idents"] == set())
check("URLを拾う", TR.hard_tokens("http://a.example/b")["urls"] == {"http://a.example/b"})
check("同じ文なら差分なし", TR.fact_diff(NUMTEXT, NUMTEXT) == "")

print()
print("=== 結果: %d PASS / %d FAIL ===" % (OK[0], len(NG)))
for n in NG:
    print("  FAILED:", n)
sys.exit(1 if NG else 0)
