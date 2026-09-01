#!/usr/bin/env python3
"""persona_send の口調バックストップ(合流点の口調ゲート)の回帰ガード。

なぜ要るか(2026-09-01 platform-se・一ノ瀬怜):
  英語ダンプは english_backstop(2026-08-23)が合流点で塞いだが、口調(男口調「俺」等)は
  上流 dept_daemon の tone_gate だけで、無人代打(claude_responder)や直送は persona_send を
  素通りしていた= 🔥 DEF-99f9503e37(アメスの口調バグ)の再発の構造的真因。
  tone_backstop を persona_send.main() へ入れ、合流点で機械修正(俺→あたし等)するようにした。
  ★この検査が守るのは「合流点で口調を直す純関数が生きていること」=経路が増えても口調が
    ドリフトしないこと。ここが緑でなくなったら、代打/直送の口調崩れがまた素通りする。

実行: python scripts/discord/test_tone_backstop.py
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import persona_send as ps  # noqa: E402

P = F = 0


def ok(cond, name):
    global P, F
    if cond:
        P += 1
        print("PASS", name)
    else:
        F += 1
        print("FAIL", name)


# 0) ルール正本が引ける前提(引けないと全てfail-openで素通し=検査の意味が無い)。
ok(os.path.exists(ps.TONE_RULES_PATH), "口調ルール正本が在る(TONE_RULES_PATH)")

# 1) ★核心= アメスの男口調「俺」を合流点で「あたし」へ機械修正する(代打/直送の残穴)。
broken = "俺がずっと見ててやる。心配すんな。"
fixed = ps.tone_backstop(broken, "アメス", "past-room")
ok("あたし" in fixed and "俺" not in fixed,
   "アメスの一人称「俺」→「あたし」を合流点で直す")

# 2) 別名(ames)は resolve_persona 後に呼ばれる前提= 正式名で引く。
#    ここでは正式名「アメス」で直ること(=ルールが名で引けること)を担保する。
ok(ps.tone_backstop("俺は行くわ。", "アメス", "") != "俺は行くわ。",
   "dept未指定でも一人称は直る(room profile非依存)")

# 3) 正常な地の声は1ミリも変えない(誤発火しないこと=常に誤発火する網は無視される§3)。
normal = "もう、何やってんのよ。あたしが見ててあげるから。"
ok(ps.tone_backstop(normal, "アメス", "past-room") == normal,
   "正常なアメス便は不変")

# 4) ミラー名義(Chami本人)は英語でも男口調でも触らない。
mirror = "俺はこう思うんだよね。"
ok(ps.tone_backstop(mirror, "Chami(音声入力)", "past-room") == mirror,
   "ミラー(Chami本人)は触らない")

# 5) 口調ルールに無い人格は素通し(fail-open=送信を殺さない)。
unknown = "俺の勝手だろ。"
ok(ps.tone_backstop(unknown, "存在しない人格XYZ", "past-room") == unknown,
   "未登録人格は素通し(fail-open)")

# 6) None/空でも例外を出さない(fail-safe)。
try:
    ps.tone_backstop(None, "アメス", "past-room")
    ps.tone_backstop("", "アメス", "past-room")
    ok(True, "None/空でも例外を出さない")
except Exception:
    ok(False, "None/空でも例外を出さない")

# 7) main() に tone_backstop が実際に配線されている(呼ばれない純関数は死んでいる§3)。
src = open(os.path.join(HERE, "persona_send.py"), encoding="utf-8", errors="replace").read()
ok("body = tone_backstop(" in src,
   "main() が tone_backstop を送信直前に呼んでいる(配線)")

print(f"\n{P} PASS / {F} FAIL")
sys.exit(1 if F else 0)
