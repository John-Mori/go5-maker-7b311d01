#!/usr/bin/env python3
"""persona_send の絵文字バックストップ(合流点で素の🔥→<:enjoh:…>)の回帰ガード。

なぜ要るか(2026-09-01 イージス研究室):
  全部門共通規律§5に「本文の🔥は <:enjoh:1541126866981752883> で書く(素の🔥を地の文に置かない)」と
  既に載っている。それでも生成側が滑り、Chamiから2度目の同じ指摘が来た
  (msg 1544213340853772331「🔥 は <:enjoh:…> に置き換えって**前に言ったはず**」)。
  機構(規律)は在るのに守る側が滑る型= 英語漏れ・口調割れと同じなので、合流点(persona_send)で
  機械的に潰した。起票= 改善提案部門(トトリ)
  docs/departments/kaizen-analyst/型_素の炎上絵文字_送信ゲート正規化_2026-09-01.md
  ★この検査が守るのは「地の文だけを置換し、コードの中は触らない」こと。ここが赤くなったら、
    素の🔥がまたChamiの目の前へ出るか、規律の説明文中の🔥まで壊されるかのどちらかだ。

実行: python scripts/discord/test_enjoh_backstop.py (全PASSで exit 0)
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import persona_send as ps  # noqa: E402

FIRE = "\U0001F525"
ENJOH = "<:enjoh:1541126866981752883>"
P = F = 0


def ok(cond, name):
    global P, F
    if cond:
        P += 1
        print("PASS", name)
    else:
        F += 1
        print("FAIL", name)


# --- 受け入れ条件1: 素の🔥は置換され、出力に素の🔥が残らない ---------------------
# ★実物(トトリ msg 1544213340853772331 でChamiに指摘された表記そのまま)。
real = FIRE + "炎上 9件 → 恒久対策が\"入っていない\"のは1件だけ"
out = ps.enjoh_backstop(real)
ok(FIRE not in out, "1 実物の素の🔥が出力に残らない")
ok(out.startswith(ENJOH), "1 <:enjoh:…> へ置換されている")
ok(out.endswith("のは1件だけ"), "1 本文の残りは1ミリも変わらない")

# 異体字セレクタ付き(🔥️)も同じ字なので拾う= 見た目が同じものを取りこぼさない。
ok(FIRE not in ps.enjoh_backstop("進捗は" + FIRE + "️ だ"), "1 異体字セレクタ付きも拾う")

# 複数個あれば全部。
ok(ps.enjoh_backstop(FIRE + "と" + FIRE).count(ENJOH) == 2, "1 複数の素の🔥を全部置換")

# --- 受け入れ条件2: 既に <:enjoh:…> の便は不変(二重変換なし) --------------------
already = ENJOH + " 恒温9件→ これは既に正しい表記だ。"
ok(ps.enjoh_backstop(already) == already, "2 既に<:enjoh:…>の便は1ミリも変えない")

# 🔥を1つも含まない通常便も不変(誤発火しない=常に誤発火する網は無視される§3)。
normal = "今日の分は全部片付いた。残りは明日でいい。"
ok(ps.enjoh_backstop(normal) == normal, "2 素の🔥が無い通常便は不変")

# --- 受け入れ条件3: コードブロック/インラインcode内は不変(誤爆しない) ------------
# ★規律や実装の説明では素の🔥を**そのまま見せたい**。ここを壊すと説明文が書けなくなる。
inline = "規律§5は `" + FIRE + "` を地の文に置くなと言っている。"
ok(ps.enjoh_backstop(inline) == inline, "3 インラインcode内の🔥は不変")

fenced = "```\n_FIRE_RE = re.compile(\"" + FIRE + "\")\n```"
ok(ps.enjoh_backstop(fenced) == fenced, "3 コードブロック内の🔥は不変")

# ★混在= コードの外だけ置換し、中は残す(片方だけ効く実装を弾く)。
mixed = FIRE + "炎上した。原因は `" + FIRE + "` の直書きだ。"
mout = ps.enjoh_backstop(mixed)
ok(mout.startswith(ENJOH) and "`" + FIRE + "`" in mout,
   "3 混在便=地の文だけ置換しコード内は残す")

# --- fail-open / 型 ------------------------------------------------------------
ok(ps.enjoh_backstop("") == "", "空文字は例外を出さず不変")
ok(ps.enjoh_backstop(None) is None, "Noneは例外を出さず不変(fail-open)")

# --- 配線: main() が実際にこの関数を呼ぶ形でコンパイルされているか ----------------
# ★ソースの文字列一致ではなく**コードオブジェクトの参照名**を見る(SKILL.md「実行で見る」の代替。
#   main()の全実行はwebhookを叩くため、ここでは呼び出しの存在までを担保する)。
ok("enjoh_backstop" in ps.main.__code__.co_names,
   "配線 main() が enjoh_backstop を呼ぶ")
ok(list(ps.main.__code__.co_names).index("enjoh_backstop")
   > list(ps.main.__code__.co_names).index("tone_backstop"),
   "配線 口調ゲートの後に置かれている(置換結果を口調ゲートが壊さない順)")

print(f"\n{P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
