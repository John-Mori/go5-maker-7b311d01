# -*- coding: utf-8 -*-
"""competitor_daily の オチ絵結合(SA-H011) の検証。
題名だけでなく 4-5秒目のオチ絵(frameText/panelDesc)を日次へ結合できることを機械で確かめる。
実データのフィード鮮度に依存せず、純粋関数 hook_type/oti_cell を直接叩く。
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "analysis"))
import competitor_daily as C

fail = 0
def eq(name, got, want):
    global fail
    ok = got == want
    print(("PASS " if ok else "FAIL ") + name + (" got=%r" % (got,) if not ok else ""))
    if not ok: fail += 1
def truthy(name, cond):
    global fail
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fail += 1

# 1) 絵未取得(vision空)は必ず「絵未取得」=題名だけで語らせないための番人
eq("oti_empty", C.oti_cell({"frameText": "", "panelDesc": ""}), "絵未取得")
eq("oti_none", C.oti_cell({}), "絵未取得")
eq("hook_empty", C.hook_type("", ""), "絵未取得")

# 2) 実サンプル(7/30 vision実物)=焼き込み＋コマ内容が並び、絵未取得にならない
cell = C.oti_cell({"frameText": "「素敵な子」の評価が1コマで崩壊する瞬間",
                   "panelDesc": "窓掃除をする女子生徒を見上げる男子生徒と裏の顔を見せる女子生徒"})
truthy("oti_filled_has_yakikomi", cell.startswith("焼込『"))
truthy("oti_filled_not_missing", cell != "絵未取得")
truthy("oti_filled_has_panel", "女子生徒" in cell)

# 3) hookType 粗分類=frameText/panelDesc のキーワードで絵側の型が付く
eq("hook_gap", C.hook_type("評価が1コマで崩壊する瞬間", "裏の顔を見せる女子生徒"), "ギャップ")
eq("hook_challenge", C.hook_type("完全に理性を試しにくる先生のジト目", "上目遣いの先生"), "挑発")
eq("hook_comment", C.hook_type("※続きはコメ欄で", "運動会の一場面"), "続きはコメ欄")
truthy("hook_other_when_no_keyword", C.hook_type("普通の日常の一コマ", "教室で談笑") in ("その他",))

print("---")
print("ALL PASS" if fail == 0 else "%d FAIL" % fail)
sys.exit(1 if fail else 0)
