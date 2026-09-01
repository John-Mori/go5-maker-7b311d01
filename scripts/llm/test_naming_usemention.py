#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼称ゲートC: 計器の過大計上(use/mention・語境界・台帳の found)の回帰テスト。

実行:            python scripts/llm/test_naming_usemention.py
変異(must-fail): python scripts/llm/test_naming_usemention.py --mutate

★2026-09-02 新設。引き金= 人事部門ククールの検算(便6/6)
  「pinは効いているのに件数が動かない。計器が use/mention を数えているのでは」。
  こちらの計器で裏を取った結果、**過大計上の実体は use/mention ではなく計器の欠陥2つ**だった:
    ① 語境界なしの部分一致 = グッズ部屋の「**メル**カ**リ**」が『ルカを裸で呼んだ』として鳴る
       (ククールが「ヴィルシーナ×2・アメス×1の誤検知」と見た3件の正体)。
    ② 同じ位置に長短2形が当たると**短い方**を台帳へ書く = 「シャビ・アロンソ」と
       書いた便が found="シャビ" として残り、**裸の姓で呼んだように見える**。
  併せて use/mention の保護(コード/引用行/パス)も入れたので、ここで釘付けにする。
★ルールは本番の写像を使わずここで固定する(人事部門が写像を育てても赤にならない)。
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import naming_gate as ng   # noqa: E402

results = []

# 本番と同じ形の最小写像(ルカ・モドリッチ / シャビ・アロンソ の2対象だけ)。
RULES = {
    "honorific_required_targets": {
        "ルカ・モドリッチ": {"bare_forms": ["モドリッチ", "ルカ・モドリッチ"],
                             "allowed": ["モドリッチさん"],
                             "forbidden": ["ルカ・モドリッチ"]},
        "シャビ・アロンソ": {"bare_forms": ["アロンソ", "シャビ", "シャビ・アロンソ"],
                             "allowed": ["アロンソさん", "アロンソコーチ"]},
    },
    "target_detect_forms": {"ルカ・モドリッチ": ["ルカ"]},
    "speaker_target_overrides": [
        {"speaker": "ククール", "target": "ルカ・モドリッチ", "allowed": ["モドリッチ"]},
        {"speaker": "ククール", "target": "シャビ・アロンソ",
         "allowed": ["アロンソコーチ", "アロンソ監督"]},
    ],
}
WHO = "ククール"


def check(name, cond):
    results.append((name, bool(cond)))
    print(("  OK  " if cond else "  NG  ") + name)


def hits(text):
    """(target, found) の集合。"""
    return {(v.get("target"), v.get("found"))
            for v in ng.naming_verdicts(WHO, "hr-room", text, RULES)}


def main():
    print("=== 呼称ゲートC: 過大計上の回帰 ===")

    # --- ① 語境界: カタカナ語の中に埋まった名前は数えない -------------------
    check("誤検知: 「メルカリ」は『ルカ』ではない",
          ("ルカ・モドリッチ", "ルカ") not in hits("メルカリと駿河屋で買った。"))
    check("誤検知: 「ルカリオ」は『ルカ』ではない(後ろだけで切れる)",
          ("ルカ・モドリッチ", "ルカ") not in hits("ルカリオのアクスタを追加した。"))
    check("取りこぼし無し: 同じ便に本物の裸「ルカ」が在れば鳴る",
          ("ルカ・モドリッチ", "ルカ") in hits("メルカリで買った。ルカ、これ見て。"))
    check("取りこぼし無し: 中黒は語の区切り=「シャビ・アロンソ」の中の姓は見える",
          ng._boundary_ok("シャビ・アロンソ", 4, "アロンソ"))
    check("明示の禁止形は生きたまま: 「ルカ・モドリッチ」は違反",
          ("ルカ・モドリッチ", "ルカ・モドリッチ") in hits("ルカ・モドリッチさんへ渡す。"))

    # --- ② 台帳の found: 同位置なら長い形を書く ----------------------------
    h = hits("シャビ・アロンソに渡した。")
    check("台帳: 「シャビ・アロンソ」は found=シャビ・アロンソ(裸の姓に見せない)",
          ("シャビ・アロンソ", "シャビ・アロンソ") in h)
    check("台帳: 同じ便を found=シャビ として二重に数えない",
          ("シャビ・アロンソ", "シャビ") not in h)

    # --- ③ use/mention: コード・引用行・パスの中は呼びかけではない ----------
    check("mention: コードフェンスの中の裸「ルカ」は数えない",
          ("ルカ・モドリッチ", "ルカ") not in hits("直した。\n```\nルカ\n```\n以上。"))
    check("mention: 行頭 > の引用の中は数えない",
          ("ルカ・モドリッチ", "ルカ") not in hits("指摘はこれ。\n> ルカ、と書いていた\n直す。"))
    check("mention: パス/ファイル名の中は数えない",
          ("シャビ・アロンソ", "アロンソ")
          not in hits("characters/アロンソ.md を直した。"))
    check("use: 地の文の呼びかけは今までどおり鳴る",
          ("シャビ・アロンソ", "アロンソ") in hits("アロンソ、これ見てくれ。"))

    # --- ④ 当たった現場を台帳へ残す(excerpt=頭200字では読めなかった) -------
    long_text = "あ" * 300 + "ルカ、これ見て。"
    v = [x for x in ng.naming_verdicts(WHO, "hr-room", long_text, RULES)
         if x.get("found") == "ルカ"]
    check("現場: 300字目より後で当たっても near に現物が残る",
          bool(v) and "ルカ" in (v[0].get("near") or ""))
    check("現場: その便での出現数 hits が入る",
          bool(v) and v[0].get("hits") == 1)
    # 許容形が先に出ている便で、窓が**咎めた出現**を指すこと(excerpt と同じ嘘をつかない)
    v2 = [x for x in ng.naming_verdicts(WHO, "hr-room",
                                        "アロンソコーチ、頼む。あとでアロンソに渡す。", RULES)
          if x.get("target") == "シャビ・アロンソ"]
    check("現場: 窓が指すのは先頭の許容形ではなく後ろの裸の姓",
          bool(v2) and v2[0].get("at") == 14 and v2[0].get("hits") == 1)
    # 自動修正が「メルカリ」を書き換えないこと(境界は置換側にも効く)
    fx = ng.naming_corrections(WHO, "hr-room", "メルカリで買った。", RULES)
    check("自動修正: 「メルカリ」を1文字も触らない",
          fx.get("fixed") == "メルカリで買った。" and not fx.get("applied"))

    ng_ok = all(c for _, c in results)
    print("\n%d件中 %d件OK" % (len(results), sum(1 for _, c in results if c)))
    return 0 if ng_ok else 1


# ==== 変異(must-fail)= どれも「動く別実装」であること(C-053)==================
def _mut_no_boundary():
    """旧本番: 語境界を見ない素の部分一致。"""
    ng._boundary_ok = lambda s, i, f: True


def _mut_boundary_prev_only():
    """別実装: 境界を**手前だけ**見る(「ルカリオ」が抜ける)。"""
    def prev_only(s, i, f):
        if not f or any(not ng._is_katakana(c) or c in ng._KATA_SEP for c in f):
            return True
        return not (i > 0 and ng._kata_word_ch(s[i - 1]))
    ng._boundary_ok = prev_only


def _mut_boundary_all_forms():
    """別実装: 境界を**漢字名にも**広げる(取りこぼしを作る側の事故)。"""
    def broad(s, i, f):
        if not f:
            return True
        if i > 0 and not re.match(r"[\s、。()（）「」]", s[i - 1]):
            return False
        j = i + len(f)
        return j >= len(s) or bool(re.match(r"[\s、。()（）「」]", s[j]))
    ng._boundary_ok = broad


def _mut_shortest_form():
    """旧本番: 同じ位置なら**先に見つけた(短い)形**を採る。"""
    def shortest(text, forms):
        s = str(text or "")
        best = None
        for f in forms:
            f = str(f or "")
            if not f:
                continue
            i = 0
            while True:
                i = s.find(f, i)
                if i < 0:
                    break
                if ng._boundary_ok(s, i, f):
                    break
                i += 1
            if i >= 0 and (best is None or i < best[0]):
                best = (i, f)
        return best
    ng._find_forms = shortest


def _mut_no_protect():
    """旧本番: コード/引用行/パスを覆わない。"""
    ng._mask_protected = lambda s: str(s or "")


def _mut_no_hits():
    """旧本番: 当たった現場を台帳へ足さない(excerpt だけ)。"""
    ng._attach_hits = lambda out, masked, original: out


MUTANTS = (
    ("変異1 語境界を見ない(旧本番)", _mut_no_boundary,
     "誤検知: 「メルカリ」は『ルカ』ではない"),
    ("変異2 境界を手前だけ見る", _mut_boundary_prev_only,
     "誤検知: 「ルカリオ」は『ルカ』ではない(後ろだけで切れる)"),
    ("変異3 境界を漢字名にも広げる", _mut_boundary_all_forms,
     "明示の禁止形は生きたまま: 「ルカ・モドリッチ」は違反"),
    ("変異4 同位置は短い形を採る(旧本番)", _mut_shortest_form,
     "台帳: 「シャビ・アロンソ」は found=シャビ・アロンソ(裸の姓に見せない)"),
    ("変異5 保護マスク無し(旧本番)", _mut_no_protect,
     "mention: コードフェンスの中の裸「ルカ」は数えない"),
    ("変異6 現場を残さない(旧本番)", _mut_no_hits,
     "現場: 300字目より後で当たっても near に現物が残る"),
)


def mutate():
    bad = 0
    saved = (ng._boundary_ok, ng._find_forms, ng._mask_protected, ng._attach_hits)
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
            (ng._boundary_ok, ng._find_forms,
             ng._mask_protected, ng._attach_hits) = saved
        red = [n for n, c in results if not c]
        hit = want_red in red
        print("  → 狙った1件が赤か: %s  (赤=%d件)" % ("OK" if hit else "NG", len(red)))
        if not hit:
            bad += 1
    print("\n変異 %d件中 %d件が狙いどおり赤" % (len(MUTANTS), len(MUTANTS) - bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(mutate() if "--mutate" in sys.argv else main())
