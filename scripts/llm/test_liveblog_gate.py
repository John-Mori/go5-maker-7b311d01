# -*- coding: utf-8 -*-
"""出力ゲートG(実況漏れ)の試験。`python scripts/llm/test_liveblog_gate.py` で直接走る。

★実行で通す(共通規律§3)= ソース検査を1つも書かない。入力を差し替えて経路を通す。
★`--mutate N` = 「動く**別の実装**」へ変異させて、試験が赤くなることを確かめる(C-053)。
    1 … 判定を「名乗り0個だけ」にする(改善提案部門の原案) → 誤発火の試験が赤になるはず
    2 … 声(因子③)を見ない                                   → 同上
    3 … 構造(因子④)を見ない                                 → 同上
    4 … 採用条件から事実の不変を外す                          → 捏造の試験が赤になるはず
    5 … 採用条件から名乗りの確認を外す                        → 名乗り無しの試験が赤になるはず
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import liveblog_gate as G

MUT = 0
for i, a in enumerate(sys.argv):
    if a == "--mutate" and i + 1 < len(sys.argv):
        MUT = int(sys.argv[i + 1])

# --- 変異(どれも「動く別の実装」= 実況は捕まえるが、守りのどこかを外す) ---------
if MUT == 1:                              # 名乗り0個だけで発火(=呼び出し側の①だけ)
    def _v(text):
        t = str(text or "").strip()
        return {"hit": bool(t), "markers": ["(名乗り0個)"], "why": "名乗り0個"}
    G.liveblog_verdict = _v
elif MUT == 2:                            # 声を見ない
    G.has_voice = lambda t: False
elif MUT == 3:                            # 構造(改行)を見ない= 3因子どまり
    def _v3(text):
        t = str(text or "").strip()
        out = {"hit": False, "markers": G.machine_markers(t), "why": "指紋なし/声あり"}
        if t and out["markers"] and not G.has_voice(t):
            out["hit"], out["why"] = True, "構造を見ない変異"
        return out
    G.liveblog_verdict = _v3
elif MUT == 4:                            # 事実の不変を見ない
    G.fact_kept = lambda o, c, allow_add=None: ""
elif MUT == 5:                            # 名乗りを見ない= 声と事実だけで採用する別実装
    def _a5(original, candidate, persona, resolve=None):
        o, c = str(original or "").strip(), str(candidate or "").strip()
        if not c:
            return False, "空の返し"
        if c == o:
            return False, "本文が変わっていない"
        body = G.strip_tag_head(c)
        if not G.has_voice(body):
            return False, "書き直しても声が無い"
        bad = G.fact_kept(o, body)
        return (False, bad) if bad else (True, "")
    G.accept = _a5

FAIL = []
N = [0]


def ok(cond, name, extra=""):
    N[0] += 1
    if not cond:
        FAIL.append("%s %s" % (name, extra))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("  " + extra) if (extra and not cond) else ""))


# --- 実物(0歩目で読んだ改修α部屋の最終投稿・2026-09-02 00:25:27 JST) -----------
REAL = ("打ち切ったが、この便で local\\teian\\candidates_2026-09-02.json、"
        "local\\teian\\synopsis_2026-09-02.json、local\\teian\\candidates_2026-09-01.json、"
        "local\\teian\\content_store.json ほか計5件 を書き換えていた"
        "(実測=作業前後のファイル差分)。完了扱いにせず残してあるから、確かめて要れば拾い直す。")

print("■① 判定= 壊れている実物を捕まえる")
v = G.liveblog_verdict(REAL)
ok(v["hit"] is True, "事故の実物(改修α 00:25)で発火する", v["why"])
ok("winpath" in v["markers"], "実況指紋に生Windowsパスが挙がる", str(v["markers"]))

# 実測で拾った同型(全期間3583便から4因子で出た残り2件)
ok(G.liveblog_verdict(
    "リトライ中はPythonのstdoutバッファで出力が末尾までflushされない。完了通知を待つ。"
)["hit"] is True, "同型: shorts-analyst 2026-09-01T03:00:09")
ok(G.liveblog_verdict(
    "Nova Anime XL(セミリアル塗りの定番・DL 17.5万)をDL中。落ちたら差し替えて生成する。"
)["hit"] is True, "同型: llm-edu 2026-07-29T01:59:13")

print("\n■② 誤発火しない= 人格の声で書けている便には当たらない")
CASES = [
    ("はいはい、監査テストね。local\\_audit_probe.txt 作って、中身「監査テスト」だけ。"
     "ちゃんと読み返して確認したから、空振りじゃないわよ。", "アメスの声(winpath有り・終助詞有り)"),
    ("あ〜〜4連続再起動の件ね。裏でClaudeが何か動いてる最中はアプリ落としただけじゃ"
     "大改修が止まる、リトライなら少し進む…って推理よ。", "hqの声(機械語有り・終助詞有り)"),
    ("上から順に着手した。\n**#7「設計構築」を実物付きで閉じた**\n設計を1本に束ねて回送済み。",
     "構造がある(改行・見出し)"),
    ("受けた。あとで見る。", "実況指紋が無い短文"),
    ("", "空文"),
]
for t, name in CASES:
    ok(G.liveblog_verdict(t)["hit"] is False, "素通し: " + name,
       G.liveblog_verdict(t)["why"])

print("\n■③ 包み直しの採用= 名乗り+声が付き、事実が1つも動いていない時だけ")
GOOD = ("[ケヴィン・デブライネ]\n" + "途中で打ち切ったが、この便で俺は local\\teian\\candidates_2026-09-02.json、"
        "local\\teian\\synopsis_2026-09-02.json、local\\teian\\candidates_2026-09-01.json、"
        "local\\teian\\content_store.json ほか計5件 を書き換えていた"
        "(実測=作業前後のファイル差分)。完了扱いにはしていない、確かめて要れば拾い直してくれ。")
r = G.wrap_once("ケヴィン・デブライネ", "system-engineer", REAL, v["markers"],
                ask=lambda p: GOOD)
ok(r["ok"] is True, "正しく包み直した候補を採用する", r["why"])
ok(r["text"] == GOOD, "採用時は包み直した本文を返す")
ok(r["attempted"] is True, "LLMを1回呼んだと記録する")

print("\n■④ 包み直しの不採用= 元の本文のまま返す(消さない=沈黙にしない)")
BAD = [
    ("", "空の返し"),
    (REAL, "本文が変わっていない"),
    ("俺が書き換えた。確かめてくれ。", "名乗りが無い"),
    ("[アメス]\n" + GOOD.split("\n", 1)[1], "別人の名乗り"),
    ("[ケヴィン・デブライネ]\n俺が計6件 書き換えた、確かめてくれ。", "数字が変わった"),
    ("[ケヴィン・デブライネ]\n俺が local\\teian\\candidates_2026-09-02.json ほか計5件 "
     "を書き換えた(実測=作業前後のファイル差分)、確かめて要れば拾い直してくれ。", "ファイル名が消えた"),
    ("[ケヴィン・デブライネ]\n" + REAL, "包んでも声が無い"),
]
for cand, name in BAD:
    rr = G.wrap_once("ケヴィン・デブライネ", "system-engineer", REAL, v["markers"],
                     ask=lambda p, c=cand: c)
    ok(rr["ok"] is False, "弾く: " + name, "why=" + rr["why"])
    ok(rr["text"] == REAL, "弾いた時は元の本文を返す: " + name)

print("\n■⑤ fail-open= この段が配送を殺さない")


def _boom(p):
    raise RuntimeError("HTTP Error 429: Too Many Requests")


rb = G.wrap_once("ケヴィン・デブライネ", "system-engineer", REAL, v["markers"], ask=_boom)
ok(rb["ok"] is False and rb["text"] == REAL, "LLMが落ちても元の本文を返す", rb["why"])
ok("429" in rb["why"], "落ちた理由を監査へ残す", rb["why"])

print("\n■⑥ 名簿で名乗りを解決する(resolve を渡した時)")
res = (lambda nm: "ケヴィン・デブライネ" if nm in ("ケヴィン・デブライネ", "デブライネ") else None)
r2 = G.wrap_once("ケヴィン・デブライネ", "system-engineer", REAL, v["markers"],
                 resolve=res, ask=lambda p: GOOD.replace("[ケヴィン・デブライネ]", "[デブライネ]"))
ok(r2["ok"] is True, "名簿で解決できる略称の名乗りは通す", r2["why"])
r3 = G.wrap_once("ケヴィン・デブライネ", "system-engineer", REAL, v["markers"],
                 resolve=res, ask=lambda p: GOOD.replace("[ケヴィン・デブライネ]", "[誰か]"))
ok(r3["ok"] is False, "名簿に無い名乗りは弾く", r3["why"])

print("\n■⑦ 事実の不変(呼び名だけ増えてよい)")
ok(G.fact_kept("計5件 を書き換えた", "Chami、計5件 書き換えたぜ") == "",
   "呼びかけ Chami の追加は通す")
ok(G.fact_kept("計5件 を書き換えた", "計5件 を config.json へ書き換えた") != "",
   "元に無いファイル名の追加は弾く")
ok(G.fact_kept("計5件 を書き換えた", "計6件 を書き換えた") != "", "数字の書き換えは弾く")

print("\n■⑧ 指示文= 名乗りと事実の縛りが必ず入る")
p = G.build_prompt("ケヴィン・デブライネ", "system-engineer", REAL, ["winpath"],
                   entry={"first_person": ["俺"], "signature_tails": ["だ", "ぜ"]})
ok("[ケヴィン・デブライネ]" in p, "1行目の名乗りを指示している")
ok("足さない" in p and "削らない" in p, "事実を足すな削るなを指示している")
ok("俺" in p, "写像の一人称を渡している")

print("\n%d件中 %d件PASS / %d件FAIL" % (N[0], N[0] - len(FAIL), len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  ✗ " + f)
    sys.exit(1)
