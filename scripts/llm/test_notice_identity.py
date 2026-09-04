# -*- coding: utf-8 -*-
"""名義と口調のねじれ(🔥DEF-aegis-gl-08c9e9de6d)の回帰ガード。

事故= 打ち切り通知(msg 1545215532939218985)が
      「メタルギアMk.II の名前で、ケヴィン・デブライネの口調」で出た。
真因= 「この便を誰の名義で出すか」の判断が**2箇所**に居た
      (①出力ゲートGが包み直す先 ②送信側の --persona)。

この試験が守るのは1つ= **その2つが常に同じ答えを出すこと**。

★実行で通す(共通規律§3)= ソースの文字列一致を1つも書かない。
  本物の `dept_daemon.machine_named_delivery` / `liveblog_gate_applies` /
  `Daemon.machine_named` / `Daemon.outgoing_persona` を、入力を差し替えて呼ぶ。
  外へ出る手(persona_send の起動)は1度も呼ばない= 判定と分岐だけを本物のまま回す。

★`--mutate N` = 「動く**別の実装**」へ変異させ、試験が赤くなることを確かめる(C-053)。
    1 … ゲートGが機械名義の便も通す(=2026-09-04より前の実装)
    2 … 送信側が名義を自前で決める(判定を2箇所に戻す)
    3 … ゲートGの包み直し先を effective_persona 固定にする(判定を2箇所に戻す)
    4 … machine_named_delivery が _liveblog_notice を見ない
    5 … 話者依存ゲート(C/D/D-2/H)が effective_persona を見る(=2026-09-04 12:11 の実装)
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as D

MUT = 0
for i, a in enumerate(sys.argv):
    if a == "--mutate" and i + 1 < len(sys.argv):
        MUT = int(sys.argv[i + 1])

# --- 変異(どれも「動く別の実装」= 通知は出るが、守りのどこかを外す) -----------------
if MUT == 1:                      # ゲートGが機械名義の便も通す(事故当時の実装)
    D.liveblog_gate_applies = (
        lambda n, unresolved, machine_named: bool(n == 1) and bool(unresolved))
elif MUT == 2:                    # 送信側が自前で名義を決める(判定が2箇所へ戻る)
    def _own(self, who=None):
        return who or self.effective_persona()
    D.Daemon.outgoing_persona = _own
elif MUT == 3:                    # 包み直す先を既定人格に固定(ゲートG側だけ別の答えを持つ)
    D.Daemon.outgoing_persona = (
        lambda self, who=None: who or self.effective_persona())
elif MUT == 4:                    # ゲートGが倒した機械名義を名義判定が見落とす
    D.machine_named_delivery = lambda relay_nack, liveblog_notice: bool(relay_nack)
elif MUT == 5:                    # 口調ゲートが既定人格を見る(第2の口が開いたままの実装)
    D.Daemon.gate_speaker = (
        lambda self, who=None: who or self.effective_persona())

FAIL = []
N = [0]


def ok(cond, name, extra=""):
    N[0] += 1
    if cond:
        print("  ok   %s" % name)
    else:
        FAIL.append(name)
        print("  FAIL %s %s" % (name, extra))


def daemon(dept="aegis-gl", persona="ケヴィン・デブライネ",
           relay_nack=False, liveblog_notice=False, wrapped=False):
    """本物の Daemon を __init__ を通さずに組む= 判定に要る属性だけ載せる。

    ★偽物にしたのは「部屋の設定の読み込み」だけで、判定のコードは1行も差し替えていない。
    """
    d = D.Daemon.__new__(D.Daemon)
    d.dept = dept
    d.conf = {"persona": persona, "personas": [{"persona": persona}]}
    d._member = None
    d._persona_ready = True
    d._relay_nack = relay_nack
    d._liveblog_notice = liveblog_notice
    d._liveblog_wrapped = wrapped
    return d


MP = D.MACHINE_PERSONA
KDB = "ケヴィン・デブライネ"

print("== 1) 名義の判定(machine_named_delivery)= 真理値表 ==")
ok(D.machine_named_delivery(False, False) is False, "普通の返信は人格名義")
ok(D.machine_named_delivery(True, False) is True, "打ち切り/失敗の告知は機械名義")
ok(D.machine_named_delivery(False, True) is True, "ゲートGが倒した便は機械名義")
ok(D.machine_named_delivery(True, True) is True, "両方立っても機械名義")

print("== 2) ★事故の実物と同じ形= 打ち切り通知はゲートGを通さない ==")
# 事故当時の便: 名乗り0個・声なし・改行なしの生ログ(format_timeout_result の出力そのもの)
raw = D.format_timeout_result(["scripts/llm/dept_daemon.py", "scripts/llm/tone_gate.py"])
nack = daemon(relay_nack=True)
ok(nack.machine_named() is True, "打ち切り便は machine_named=True")
ok(D.liveblog_gate_applies(1, True, nack.machine_named()) is False,
   "★打ち切り便はゲートGを通さない(=誰の口調にも包み直されない)")
ok(nack.outgoing_persona(None) == MP, "打ち切り便の名義は %s" % MP,
   "実際=%r" % nack.outgoing_persona(None))
ok(nack.outgoing_persona(KDB) == MP,
   "打ち切り便は [名前] が付いていても機械名義(人格を騙らない)")
ok("時間切れで打ち切った。" in raw, "検体= format_timeout_result の実出力", "実際=%r" % raw[:60])
ok("[" not in raw and "俺" not in raw and "あたし" not in raw,
   "検体に名乗りも一人称も無い(=ゲートGの網に当たる形)")

print("== 3) 普通の返信はゲートGを通り、包み直す先と送信名義が一致する ==")
plain = daemon()
ok(plain.machine_named() is False, "普通の返信は machine_named=False")
ok(D.liveblog_gate_applies(1, True, plain.machine_named()) is True,
   "★名義未解決の1ブロックはゲートGを通る(実況漏れの網は生きている)")
ok(plain.outgoing_persona(None) == KDB, "包み直す先=部屋の既定人格")
ok(plain.outgoing_persona("アメス") == "アメス", "[名前] が解決していればその人の名義")
ok(D.liveblog_gate_applies(2, True, False) is False, "ブロックが2つならゲートGは通らない")
ok(D.liveblog_gate_applies(1, False, False) is False, "名義が解決済みならゲートGは通らない")

print("== 4) ★不変条件= 包み直す先と送信名義が食い違う組み合わせが1つも無い ==")
# ゲートGを通る便では「包み直す先」= outgoing_persona()、送信名義も outgoing_persona(_who)。
# 全ての状態でこの2つが同じ人を指すことを、状態を総当たりして確かめる。
bad = []
for rn in (False, True):
    for ln in (False, True):
        d = daemon(relay_nack=rn, liveblog_notice=ln)
        passes = D.liveblog_gate_applies(1, True, d.machine_named())
        if not passes:
            continue                       # 通らない便には包み直しが無い= ねじれようがない
        wrap_target = d.outgoing_persona()          # ゲートGが包み直す先
        send_name = d.outgoing_persona(wrap_target)  # 包み直し後に解決される名義
        if wrap_target != send_name or send_name == MP:
            bad.append((rn, ln, wrap_target, send_name))
ok(not bad, "★ゲートGを通る全状態で 包み直す先==送信名義 かつ 機械名義ではない",
   "食い違い=%r" % (bad,))

print("== 5) ゲートGが倒した便(包み直せなかった)は機械名義で、二度と包み直されない ==")
fell = daemon(liveblog_notice=True)
ok(fell.machine_named() is True, "倒した便は machine_named=True")
ok(fell.outgoing_persona(None) == MP, "倒した便の名義は %s" % MP)
ok(D.liveblog_gate_applies(1, True, fell.machine_named()) is False,
   "倒した便を再びゲートGへ入れない(二重包み直しの禁止)")

print("== 6) 再発検知の不変条件が「起こりえない」ことを状態で確かめる ==")
# `_liveblog_wrapped and machine_named()` は本番では成立しないはず。
# ★成立させられるのは、外から手で両方立てた時だけ= その時は検知が True を返す。
never = [(rn, ln) for rn in (False, True) for ln in (False, True)
         if D.liveblog_gate_applies(1, True, D.machine_named_delivery(rn, ln))
         and D.machine_named_delivery(rn, ln)]
ok(not never, "包み直しに入った便が同時に機械名義になる状態は存在しない", "存在=%r" % never)
forced = daemon(relay_nack=True, wrapped=True)
ok(forced.machine_named() and forced._liveblog_wrapped,
   "★手で作れば検知条件は成立する(=安全網が発火する形を持っている)")

print("== 7) ★第2の口= 話者依存ゲート(C/D/D-2/H)も同じ名義から話者を引く ==")
# 実物(2026-09-04 12:11 hq)= ゲートGは通さなかったのに、口調ゲートDが話者を「アメス」として
# 判定し `signature_absent` を出し、D-2が「打ち切った。」→「打ち切ったわ。」へ書き直した。
# 送信名義は メタルギアMk.II。名前は機械・口調はアメス= ゲートGと同じねじれの別の口。
# ★本物の tone_gate.tone_corrections を、話者だけ差し替えて呼ぶ(ソースの文字列一致は書かない)。
import tone_gate as T

_rules = T.load_tone_rules(D.TONE_RULES_PATH)
ok(bool(_rules), "口調ルールが読める(=このゲートは生きている)")
hq_nack = daemon(dept="hq", persona="アメス", relay_nack=True)
hq_plain = daemon(dept="hq", persona="アメス")

ok(hq_nack.gate_speaker(None) == MP, "打ち切り便のゲート話者は %s" % MP,
   "実際=%r" % hq_nack.gate_speaker(None))
ok(hq_plain.gate_speaker(None) == "アメス", "普通の便のゲート話者は既定人格(挙動は不変)")
ok(hq_plain.gate_speaker("シャビ・アロンソ") == "シャビ・アロンソ",
   "[名前] が解決していればその人(挙動は不変)")

_base = T.tone_corrections("アメス", "hq", raw, _rules) or {}
ok([v.get("reason") for v in (_base.get("remaining") or [])] == ["signature_absent"],
   "★基準線= 既定人格を話者にすると口調ゲートが本当に噛む(=この検体は罠として生きている)",
   "実際=%r" % (_base.get("remaining"),))

_fixed = T.tone_corrections(hq_nack.gate_speaker(None), "hq", raw, _rules) or {}
ok(not (_fixed.get("remaining") or []) and not (_fixed.get("applied") or []),
   "★打ち切り便は口調ゲートに1件も引っかからない(=誰の口調へも寄せられない)",
   "残=%r 直=%r" % (_fixed.get("remaining"), _fixed.get("applied")))
ok(_fixed.get("fixed", raw) == raw, "★打ち切り便の本文は1文字も書き換わらない")

print()
print("== %d/%d %s ==" % (N[0] - len(FAIL), N[0], "PASS" if not FAIL else "FAIL"))
if FAIL:
    for f in FAIL:
        print("  - %s" % f)
sys.exit(1 if FAIL else 0)
