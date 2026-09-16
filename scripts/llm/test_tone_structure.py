#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""構造指標カウンタ(tone_structure)の回帰ガード。

★この試験は「崩れているか」を判定しない= カウンタが**数え間違えない**ことだけを固定する。
  閾値は分布が溜まってから(2026-09-16・AD研究室 msg 1549597333283676171 便6)。

★実物での確認は `--real` で行う。炎上した実便(msg 1549490190299697224・花海咲季名義)は
  **ここに本文を焼き込まない**= あの便にはLAN内IPとTailscale IPが載っている。
  repoへ運営の実本文を写さない(HQ資料の非公開原則)。読むのは local/corpus/chami.jsonl の実物。
  実物が無い環境では **skip** と出す= 「無かった」を「緑」に化けさせない。

実行= python scripts/llm/test_tone_structure.py [--real]   (rc=0 で緑 / rc=1 で赤)
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from tone_structure import (COMPOSITE_KEYS, composite_score,         # noqa: E402
                            count_structure, other_persona_material)

PASS = 0
FAIL = 0


def _check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  got={got!r} want={want!r}")


# 崩れ便の**骨格だけ**を写した型(本文は写さない)。区切り線+名前の太字見出し+太字番号ラベル。
SHAPE_BROKEN = (
    "前置きの一文だ。\n"
    "\n"
    "---\n"
    "\n"
    "**咲季**\n"
    "\n"
    "本題の導入があるわよ。\n"
    "\n"
    "**① 最初の1回だけ**:手順その一。\n"
    "**② 送りたい時**:手順その二。\n"
    "**③ スマホのブラウザ**で開く。\n"
    "\n"
    "---\n"
    "\n"
    "締めの一文だ。\n"
)
# 同じ内容を地の文でつないだ形(人事が saki.md へ入れた○例と同じ型)。
SHAPE_PLAIN = (
    "前置きの一文だ。本題の導入があるわよ。"
    "最初の1回だけ手順その一をやって、送りたい時に手順その二、"
    "あとはスマホのブラウザで開くだけ。締めの一文だ。\n"
)


def main():
    real = "--real" in sys.argv
    print("== 構造指標カウンタ 回帰ガード ==")

    b = count_structure(SHAPE_BROKEN, persona="花海咲季")
    p = count_structure(SHAPE_PLAIN, persona="花海咲季")

    # ① 軸②の各指標を**個別に**固定する。合計だけ見ると1つ壊れても他で埋まって気付かない。
    _check("① 区切り線を2本数える", b["hr"], 2)
    _check("① 太字の節見出しを4本数える(名前見出し+番号ラベル3本)", b["bold_head"], 4)
    _check("① 太字番号ラベルを3本数える(①②③)", b["numlabel"], 3)
    _check("① 太字の総数は4(名前+ラベル3)", b["bold"], 4)
    _check("① 地の文版は区切り線ゼロ", p["hr"], 0)
    _check("① 地の文版は太字見出しゼロ", p["bold_head"], 0)
    _check("① 地の文版は太字番号ラベルゼロ", p["numlabel"], 0)

    # ② must-fail。★指標が死んで全部0を返すようになったら、上の①は「地の文版」側だけ緑のまま
    #   通ってしまう。**崩れ側が地の文側より必ず大きい**ことを別に固定する(検査が生きている証拠)。
    _check("② must-fail: 崩れ骨格の指標は地の文より大きい(全0に退化していない)",
           (b["hr"] + b["bold_head"] + b["numlabel"]) > (p["hr"] + p["bold_head"] + p["numlabel"]),
           True)

    # ③ 箇条書きと深さ。番号ラベルだけでなく素の箇条書きも拾えること。
    nest = "- 親\n  - 子\n    - 孫\n1. 番号\n・中黒\n"
    n = count_structure(nest, persona=None)
    _check("③ 箇条書きを5行数える", n["bullet"], 5)
    _check("③ 入れ子の最大深さは2", n["bullet_depth"], 2)

    # ④ 軸③= 他人格の固有名詞・一人称。★**自分のものは数えない**(数えたら偽の赤)。
    mat = other_persona_material("ケヴィン・デブライネ")
    _check("④ 自分の名前が他人格一覧に入っていない",
           "ケヴィン・デブライネ" in mat["names"], False)
    _check("④ 人事部門の口調ルールから他人格を引けている(0件なら台帳を見失っている)",
           len(mat["names"]) > 0, True)
    mixed = count_structure("アメスに聞け。あたしが見た。俺はそう思う。", persona="ケヴィン・デブライネ")
    _check("④ 他人格の名前「アメス」を1件数える", mixed["other_names"].get("アメス"), 1)
    _check("④ 他人格の一人称「あたし」を1件数える",
           mixed["other_first_person"].get("あたし"), 1)
    _check("④ 自分の一人称「俺」は混入として数えない",
           "俺" in mixed["other_first_person"], False)
    # ★アメス自身が「あたし」と言っても混入にしない= 名義で持ち主が変わる。
    own = count_structure("あたしが見たわよ。", persona="アメス")
    _check("④ 名義がアメスなら「あたし」は混入ゼロ", own["other_first_person_total"], 0)

    # ⑤ 判定を混ぜていないこと。★戻り値に真偽や「崩れ」が入ったら閾値を置いたのと同じ。
    _check("⑤ 戻り値に真偽値が混ざっていない(閾値を置かない段階)",
           [k for k, v in b.items() if isinstance(v, bool)], [])

    # ⑦ 合成の定義。★これは 2026-09-16 に当室が実際にズラした箇所だ
    #   (AD研究室 msg 1549612208940654593= 同じ195便から >0 が 63 と 27 に割れた)。
    #   定義が**道具の中に1本だけ**在ること、bullet/bold を巻き込んでいないことを固定する。
    _check("⑦ 合成の定義が hr+bold_head+numlabel の3本だけ",
           list(COMPOSITE_KEYS), ["hr", "bold_head", "numlabel"])
    mix = count_structure("---\n**■ 見出し**\n- あ\n- い\n**① 手順**\n**太字**", persona=None)
    _check("⑦ composite が3本の和と一致する",
           mix["composite"], mix["hr"] + mix["bold_head"] + mix["numlabel"])
    _check("⑦ composite に bullet を混ぜていない(平時の箇条書きで膨らませない)",
           mix["composite"] < mix["hr"] + mix["bold_head"] + mix["numlabel"] + mix["bullet"],
           True)
    _check("⑦ count_structure の戻り値が composite を持つ(口で運ばない)",
           "composite" in b, True)
    _check("⑦ 台帳の古い行(composite キー無し)も同じ関数で同じ値になる",
           composite_score({k: mix[k] for k in ("hr", "bold_head", "numlabel")}),
           mix["composite"])

    # ⑥ 実物(--real)。炎上した実便を corpus から読んで、数字を**出す**。判定はしない。
    if real:
        src = os.path.join(ROOT, "local", "corpus", "chami.jsonl")
        body = None
        try:
            with open(src, encoding="utf-8") as f:
                for ln in f:
                    if "1549490190299697224" not in ln:
                        continue
                    d = json.loads(ln)
                    r = d.get("reply_to") or {}
                    if r.get("msg_id") == "1549490190299697224":
                        body = r.get("content")
                        break
        except OSError:
            pass
        if not body:
            print("  SKIP  ⑥ 実物 msg 1549490190299697224 が corpus に無い(緑にはしない)")
        else:
            r = count_structure(body, persona="花海咲季")
            print(f"  実測 msg 1549490190299697224(花海咲季・9/15 炎上便):")
            for k in ("chars", "lines", "bold", "bold_head", "hr", "numlabel",
                      "bullet", "other_names_total", "other_first_person_total"):
                print(f"      {k} = {r[k]}")
            _check("⑥ 実物で区切り線を2本拾う(骨格の写しと同じ形)", r["hr"], 2)
            _check("⑥ 実物で太字番号ラベルを3本拾う(①②③)", r["numlabel"], 3)
            _check("⑥ 実物の composite が9(2+4+3・同じ関数で出した値)",
                   r["composite"], 9)

    print(f"\n{PASS} PASS / {FAIL} FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
