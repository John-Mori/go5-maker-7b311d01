#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼称ゲートC: 用語の略語(term_abbrev)を正式形へ伸ばす経路の回帰テスト。

実行: python scripts/llm/test_naming_term_abbrev.py

★2026-09-06 新設。引き金= Chami「ニックってわかりにくいから略さないで。
  ニックネームって呼んで」(イージス研究室 msg 1545910062403551252)。
  ★これは**再発**= 前日 09-05 に人事部門でも同じ指摘(msg 1545647615033606154)を
  受けている。心がけでは止まらなかったので機構へ置いた(共通規律§3)。
★壊れている実物(0歩目・全部門の reply 5,653件を走査した実測)= 3件が略りのまま出ていた:
  hr ESC-platform-se-1545905358332100801「画面に出るのはニックの方だから」
  hr 1545641552313851927「サーバー内ニックはUnicode可」
  hr 1545906006675030117「ニックを設定するのは怜」
★ここで釘付けにするのは4つ:
  ① 実物3件が合流点で「ニックネーム」へ伸びること
  ② カタカナ語(パニック/テクニック/ピクニック/クリニック/エニックス/ニックネーム自体)を
     1文字も触らないこと= 境界を緩めた瞬間に赤になる
  ③ autofix を立てていない既存規則(ククール→ク / デブライネ→ブライネ)の挙動が不変なこと
     (C-035= 名指し1件を全体へ広げない)
  ④ 呼称違反が1つも無い便でも効くこと(早期リターンの穴)
★ルールはここで固定する= 人事部門が正本を育てても、その都度赤にならない。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import naming_gate as ng   # noqa: E402

results = []

# 本番と同じ形の最小写像。★autofix が立つ規則と立たない規則を**両方**入れる。
RULES = {
    "abbreviation_forbidden": {
        "_note": "テスト用の最小写像(本番の正本ではない)",
        "ニックネーム": {"forbidden_forms": ["ニック"],
                         "expected": ["ニックネーム"], "autofix": True},
        "ククール": {"forbidden_forms": ["ク"], "expected": ["ククール"]},
        "デブライネ": {"forbidden_forms": ["ブライネ"], "expected": ["デブライネさん"]},
    },
    "target_detect_forms": {},
    "speaker_target_overrides": [],
    "honorific_required_targets": {},
}

# 事故の実物(全部門 reply の走査で当たった3件)の書き出しと、あるべき形。
REAL = [
    ("画面に出るのはニックの方だから見た目は指定どおりになる。",
     "画面に出るのはニックネームの方だから見た目は指定どおりになる。"),
    ("だがサーバー内ニックはUnicode可・32文字までだ",
     "だがサーバー内ニックネームはUnicode可・32文字までだ"),
    ("ニックを設定するのは怜(プラットフォームSE)で正しい",
     "ニックネームを設定するのは怜(プラットフォームSE)で正しい"),
]

# ★境界で落ちなければならないカタカナ語(誤爆したら本文が化ける)。
SAFE = [
    "パニックになったりしないようだな。",
    "長大なプロンプトテクニック集をまとめた。",
    "長時間メンタルクリニックが開いている。",
    "ピクニックの計画を立てる。",
    "発売はスクウェア・エニックスだ。",
    "ニックネームを変える口は1つだけだ。",
    "サーバー内ニックネームはUnicode可だ。",
]


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def fix(text, persona="ケヴィン・デブライネ", dept="aegis-gl", rules=None):
    return ng.naming_corrections(persona, dept, text, rules or RULES)


def main():
    # ---- 1) 壊れている実物が直ること ----
    print("[1] 事故の実物3件")
    for src, want in REAL:
        r = fix(src)
        check(f"実物: {src[:16]}… が伸びる", r["fixed"] == want)
        check("実物: applied は reason=term_abbrev / ニック→ニックネーム",
              len(r["applied"]) == 1
              and r["applied"][0]["reason"] == "term_abbrev"
              and r["applied"][0]["found"] == "ニック"
              and r["applied"][0]["to"] == "ニックネーム"
              and r["applied"][0]["count"] == 1)
        check("実物: 直しきったら警告は残さない",
              not [v for v in r["remaining"] if v.get("found") == "ニック"])

    r = fix("ニックはニックのままだ。ニックを直せ。")
    check("複数出現: 3箇所とも伸びる",
          r["fixed"] == "ニックネームはニックネームのままだ。ニックネームを直せ。"
          and r["applied"][0]["count"] == 3)

    # ---- 2) ★カタカナ語を1文字も触らない(ここが本体) ----
    print("[2] 境界(カタカナ語を触らない)")
    for t in SAFE:
        r = fix(t)
        check(f"境界: {t[:14]}… は無変化",
              r["fixed"] == t
              and not [a for a in r["applied"] if a.get("reason") == "term_abbrev"])

    # ---- 3) autofix を立てていない規則は挙動不変(C-035) ----
    print("[3] 既存規則の不変(C-035)")
    r = fix("クに聞いてくれ。")
    check("既存: ククール→ク は警告のみ(本文は不変)",
          r["fixed"] == "クに聞いてくれ。"
          and not [a for a in r["applied"] if a.get("reason") == "term_abbrev"]
          and [v for v in r["remaining"] if v.get("reason") == "abbreviation"])
    r = fix("ブライネに任せる。", persona="ククール", dept="hr-room")
    check("既存: デブライネ→ブライネ も自動修正されない",
          r["fixed"] == "ブライネに任せる。"
          and not [a for a in r["applied"] if a.get("reason") == "term_abbrev"])
    check("specs: autofix が立った規則だけ拾う(1件)",
          ng._term_abbrev_specs(RULES) == [("ニック", "ニックネーム", "ニックネーム")])
    check("specs: データが無ければ空(fail-open)",
          ng._term_abbrev_specs({}) == [] and ng._term_abbrev_specs(None) == [])
    check("specs: 正式形が略形で始まらない規則は拾わない(丸ごと置換をさせない)",
          ng._term_abbrev_specs({"abbreviation_forbidden": {
              "つべ": {"forbidden_forms": ["つべ"], "expected": ["YouTube"],
                       "autofix": True}}}) == [])

    # ---- 4) 呼称違反ゼロの便でも効く(早期リターンの穴) ----
    print("[4] 呼称違反ゼロの便")
    t = "ニックを揃えた。"
    v = ng.naming_verdicts("ケヴィン・デブライネ", "aegis-gl", t, RULES)
    check("前提: この便に abbreviation 以外の呼称違反は無い",
          not [x for x in v if x.get("reason") != "abbreviation"])
    check("呼称違反ゼロでも伸びる", fix(t)["fixed"] == "ニックネームを揃えた。")

    # ---- 5) 保護域(コードフェンス・引用行・パス)は触らない ----
    print("[5] 保護域")
    t = "設定は `{\"nick\": …}` だ。\n> ニックのままで引用する\n本文のニックを直す。"
    r = fix(t)
    check("保護: 引用行の中は伸ばさない", "> ニックのままで引用する" in r["fixed"])
    check("保護: 地の文だけ伸びる", "本文のニックネームを直す。" in r["fixed"])

    t2 = "scripts/discord/set_codex_nick.py を叩く。"
    check("保護: 英字の nick(APIキー/パス)は対象外", fix(t2)["fixed"] == t2)

    # ---- 6) ★must-fail: 補強前(.bak)では実物が素通しすること ----
    print("[6] must-fail(補強を外すと赤)")
    bak = os.path.join(HERE, "naming_gate.py.bak_20260906_termabbrev")
    if not os.path.exists(bak):
        check("must-fail: .bak が在る(補強前の写しを残す=C-003)", False)
    else:
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("naming_gate_old", bak)
        spec = importlib.util.spec_from_loader("naming_gate_old", loader)
        old = importlib.util.module_from_spec(spec)
        loader.exec_module(old)
        src, want = REAL[0]
        r_old = old.naming_corrections("ケヴィン・デブライネ", "aegis-gl", src, RULES)
        check("must-fail: 補強前は実物を素通ししていた(伸びない)",
              r_old["fixed"] == src and r_old["fixed"] != want)
        check("must-fail: 補強前には term_abbrev の口が無い",
              not hasattr(old, "_term_abbrev_specs"))

    print()
    ng_fail = [n for n, ok in results if not ok]
    print(f"=== {len(results) - len(ng_fail)} PASS / {len(ng_fail)} FAIL ===")
    for n in ng_fail:
        print(f"  [FAIL] {n}")
    return 1 if ng_fail else 0


if __name__ == "__main__":
    sys.exit(main())
