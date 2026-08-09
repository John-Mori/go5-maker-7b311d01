#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""進捗便の行が途中で切れない、のテスト(2026-08-10 イージス研究室)。

発注= 報告通知(オタコン) msg_id=1536094489456812083。元はChami報告
  msg_id=1536091578341269624「途中で消えててわからない(自分で依頼した内容だし察せはするけど)」。
壊れていた実物= change_log 2026-08-09T21:20:48 の「何」(74字)が44字で切られ
  「…にリンク表示(非SNSはWeb)・メ…」で用言ごと消えていた。

★ここで固めるのは2つ=
  ①**1文が最後まで出る**(44字カットの復活を防ぐ)
  ②長すぎる時も**文の切れ目で畳む**+便全体がDiscordの2000字上限を超えない

実行: python scripts/report/test_report_pulse.py
"""
import importlib.util
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rp_under_test",
                                              os.path.join(HERE, "report_pulse.py"))
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL += 1
        print("  NG  %s" % name)


class T:                                      # ts の代わり(_digest は値を見ない)
    pass


def rows(*whats):
    return [(T(), {"dept": "system-engineer", "何": w}) for w in whats]


# ============ 1) 1文が最後まで出る ============
REAL = ("候補の投稿編集モーダルを刷新=X以外のURLもカードにリンク表示(非SNSはWeb)"
        "・メモをコメント上に統合・URL追加で2つ目以降を1モーダル完結")
check("★実際に切れていた74字の「何」が、最後まで出る", rp._fold(REAL) == REAL)
check("★44字カットが復活していない(旧実装なら「・メ…」で終わっていた)",
      "・メ…" not in rp._fold(REAL) and not rp._fold(REAL).endswith("…"))

out = rp._digest(rows(REAL), "■進捗")
check("便に組んでも最後まで残る", REAL in out)
check("行末に「…」が付かない", not out.rstrip().endswith("…"))

check("短い「何」はそのまま", rp._fold("番人を載せ替えた") == "番人を載せ替えた")
check("改行は1行へ潰す", rp._fold("前半\n後半") == "前半 後半")
check("空でも落ちない", rp._fold(None) == "" and rp._fold("") == "")

# ============ 2) 長文は文の切れ目で畳む ============
long1 = "あ" * 250 + "。" + "い" * 100
f = rp._fold(long1)
check("★上限超えは句点の切れ目で畳む(用言の途中で切らない)", f == "あ" * 250 + "。…")
check("畳んだ結果は上限+2字以内に収まる", len(f) <= rp.LINE_MAX + 2)

f = rp._fold("う" * 200 + "、" + "え" * 200)
check("読点でも畳める", f.endswith("…") and "、" not in f[-3:])

f = rp._fold("お" * 400)                      # 切れ目がまったく無い場合
check("切れ目が無ければ字数で切る(それでも便は出す)",
      len(f) == rp.LINE_MAX + 1 and f.endswith("…"))

f = rp._fold("。" + "か" * 400)                # 切れ目が前すぎる場合
check("★切れ目が前すぎる時は採らない(1字だけの行にしない)", len(f) > 100)

# ============ 3) 便の総量(Discord 2000字上限) ============
big = rp._digest(rows(*(["き" * 500] * 4)), "■進捗")
check("★長文が重なっても便はDiscordの上限に収まる", len(big) <= rp.TEXT_MAX)
check("その時も4行+見出しの形は保つ", len(big.splitlines()) == 5)

many = rp._digest(rows(*(["く"] * 10)), "■進捗")
check("5件以上は最新4件+「ほかN件」のまま(件数の丸めは変えていない)",
      "ほか 6件" in many and len(many.splitlines()) == 6)

print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
