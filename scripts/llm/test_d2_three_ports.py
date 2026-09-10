#!/usr/bin/env python3
"""出力ゲート**D-2**(tone_rewrite)が**外へ撃つ3口すべて**で実行に乗ることの検査。 2026-09-11

発注= Chami「寝る前Go」(msg 1547688457051177000)/ 人事部門アメス(msg 1547688829761224837)。
C-064= 外へ出る手へ足す時は、実際に外へ撃つ点を**全部数えて同時に**入れる。口は3つ:

    口① 常駐        scripts/llm/dept_daemon.py      audit_tone_rewrite
    口② 合流点(webhook) scripts/discord/persona_send.py tone_backstop → tone_rewrite_backstop
    口③ ミラー      scripts/llm/output_gates.py     apply_gates ゲートD-2

★§3= ソース文字列一致で固めない。**偽物にするのは外へ出る手(LLM呼び出し)だけ**で、
  対象判定(targets)・書き直し後の再判定(tone_verdicts)・採否(accept)・各口の分岐は
  **本番のコードをそのまま実行で通す**。差し替え点は `tone_rewrite.ask_cascade` 1つ=
  3口が同じ器(rewrite_once)を引いていることも、この1点差し替えが効くこと自体が証拠になる。
★写像はテスト用の偽物を作らない= 本番の 口調ルール.json をそのまま読む(ORG-11)。
★台帳は本物へ書かない= GO5_LOCAL_DIR を一時ディレクトリへ逃がす(persona_send は
  LOCAL が固定なので TONE_AUDIT だけ差し替える)。

走らせ方: python scripts/llm/test_d2_three_ports.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
HQ = os.path.join(os.path.dirname(ROOT), "00_AI-HQ")

# ★import より前に置く(各モジュールが import 時に台帳のパスを決めるため)。
_TMP = tempfile.mkdtemp(prefix="d2ports_")
os.environ["GO5_LOCAL_DIR"] = _TMP
os.environ.pop("GO5_TONE_REWRITE", None)          # 既定=有効
os.environ.pop("GO5_MIRROR_GATE_FIX", None)       # 既定=ミラーは警告のみ

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import tone_gate                                   # noqa: E402
import tone_rewrite as TR                          # noqa: E402
import output_gates as OG                          # noqa: E402
import persona_send as PS                          # noqa: E402
import dept_daemon as DD                           # noqa: E402

PS.TONE_AUDIT = os.path.join(_TMP, "llm", "tone_audit.jsonl")   # 本物の台帳へ書かない

RULES_PATH = os.path.join(HQ, "departments", "hr", "personas", "口調ルール.json")
RULES = tone_gate.load_tone_rules(RULES_PATH)

PERSONA, DEPT = "アメス", "aegis-gl"
# 実物に寄せた崩れ= 2026-09-11T03:58:34 のアメス便と同じ型(signature_absent「N文中0件」)。
BROKEN = ("配線の穴は3つのうち2つだった。今夜のうちに実装まで持っていく。"
          "検査は入力を差し替えて経路を実行で通す。commit hashでは閉じない。")
# 同じ事実(数字も識別子も落とさない)をアメスの声にした物= 偽のLLMが返す候補。
GOOD = ("配線の穴は3つのうち2つだったのよ。今夜のうちに実装まで持っていくわ。"
        "検査は入力を差し替えて経路を実行で通すのよね。commit hashでは閉じないでちょうだいね。")
CLEAN = GOOD                                        # 崩れていない便(D-2を呼んではいけない)

OK = [0]
NG = []


def check(name, cond, detail=""):
    if cond:
        OK[0] += 1
        print("  PASS %s" % name)
    else:
        NG.append(name)
        print("  FAIL %s %s" % (name, detail))


# --- 外へ出る手だけ偽物にする ------------------------------------------------
CALLS = []
_REAL_ASK = TR.ask_cascade


def fake_ask(prompt, timeout=20, _out=None):
    CALLS.append(prompt)
    if _out is not None:
        _out["engine"] = "fake"
    return GOOD


def boom_ask(prompt, timeout=20, _out=None):
    CALLS.append(prompt)
    raise RuntimeError("外の手が落ちた(429/鍵切れ相当)")


def remaining_of(text):
    return (tone_gate.tone_corrections(PERSONA, DEPT, text, RULES) or {}).get("remaining") or []


# --- 3口を「同じ入力・同じ偽の手」で通す薄い呼び出し -------------------------
def port1(text, persona=PERSONA):
    """口① 常駐。dept_daemon.audit_tone_rewrite(判定も分岐も本物)。"""
    rem = (tone_gate.tone_corrections(persona, DEPT, text, RULES) or {}).get("remaining") or []
    out, _res = DD.audit_tone_rewrite(DEPT, persona, text, rem, {"msg_id": "TEST"})
    return out


def port2(text, persona=PERSONA, audit=True):
    """口② 合流点。persona_send.tone_backstop(ゲートD→D-2の順も本物)。"""
    return PS.tone_backstop(text, persona, DEPT, audit=audit)


def port3(text, persona=PERSONA, fix=True):
    """口③ ミラー。output_gates.apply_gates(既定は警告のみ=fixで格上げ)。"""
    out, _s = OG.apply_gates(DEPT, persona, text, source="mirror", msg_id="TEST", fix=fix)
    return out


PORTS = (("口①dept_daemon", port1), ("口②persona_send", port2), ("口③output_gates", port3))

print("=== 0. 前提(壊れている側を先に見る) ===")
check("口調ルール.jsonが読める", bool(RULES), RULES_PATH)
check("アメスの写像がある", bool(tone_gate._persona_entry(RULES, PERSONA)))
_rem = remaining_of(BROKEN)
check("崩れた実物が signature_absent で検知される",
      any(v.get("reason") == "signature_absent" for v in _rem),
      str([v.get("reason") for v in _rem]))
check("ゲートD(機械置換)はこの崩れを直せない=remainingへ落ちる",
      (tone_gate.tone_corrections(PERSONA, DEPT, BROKEN, RULES) or {}).get("fixed") == BROKEN)
check("正しい声の便は検知ゼロ(偽のLLM候補が本当に合格の形)", not remaining_of(GOOD))

print("=== 1. D-2が3口とも**実行で**通る ===")
TR.ask_cascade = fake_ask
for name, fn in PORTS:
    del CALLS[:]
    got = fn(BROKEN)
    check("%s が書き直しを採用して本文が変わる" % name, got == GOOD, repr(got)[:120])
    check("%s が外の手を1回だけ叩いた" % name, len(CALLS) == 1, str(len(CALLS)))

print("=== 2. 未登録人格は素通し(3口とも1ミリも変えない・往復ゼロ) ===")
for name, fn in PORTS:
    del CALLS[:]
    got = fn(BROKEN, persona="存在しない人格XYZ")
    check("%s 未登録人格は本文不変" % name, got == BROKEN, repr(got)[:80])
    check("%s 未登録人格で外の手を叩かない" % name, len(CALLS) == 0, str(len(CALLS)))

print("=== 3. 崩れが無い便は往復ゼロ・1ミリも変えない ===")
for name, fn in PORTS:
    del CALLS[:]
    got = fn(CLEAN)
    check("%s 正常便は本文不変" % name, got == CLEAN, repr(got)[:80])
    check("%s 正常便で外の手を叩かない" % name, len(CALLS) == 0, str(len(CALLS)))

print("=== 4. キルスイッチ GO5_TONE_REWRITE=0 が3口とも効く ===")
os.environ["GO5_TONE_REWRITE"] = "0"
for name, fn in PORTS:
    del CALLS[:]
    got = fn(BROKEN)
    check("%s キルスイッチで本文不変" % name, got == BROKEN, repr(got)[:80])
    check("%s キルスイッチで外の手を叩かない" % name, len(CALLS) == 0, str(len(CALLS)))
os.environ.pop("GO5_TONE_REWRITE", None)

print("=== 5. fail-open= 外の手が落ちても元の本文が出る(沈黙にしない) ===")
TR.ask_cascade = boom_ask
for name, fn in PORTS:
    del CALLS[:]
    got = fn(BROKEN)
    check("%s 例外でも元の本文" % name, got == BROKEN, repr(got)[:80])
TR.ask_cascade = fake_ask

print("=== 6. 採否は本物のacceptが決める(事実を落とす候補は蹴る) ===")


def lying_ask(prompt, timeout=20, _out=None):
    CALLS.append(prompt)
    # 語尾は正しいが **commit hash という識別子を落とした**候補= accept が蹴るはず。
    return ("配線の穴は3つのうち2つだったのよ。今夜のうちに実装まで持っていくわ。"
            "検査は入力を差し替えて経路を実行で通すのよね。もう閉じていいのよね。")


TR.ask_cascade = lying_ask
for name, fn in PORTS:
    del CALLS[:]
    got = fn(BROKEN)
    check("%s 事実が落ちた候補は不採用=元の本文" % name, got == BROKEN, repr(got)[:120])
    check("%s 不採用でも外の手は叩いている(判定が本物)" % name, len(CALLS) == 1)
TR.ask_cascade = fake_ask

print("=== 7. ミラーの既定(警告のみ)ではD-2を回さない=枠を焼かない ===")
del CALLS[:]
got = port3(BROKEN, fix=None)          # GO5_MIRROR_GATE_FIX 未設定= do_fix False
check("口③ 既定では本文不変", got == BROKEN, repr(got)[:80])
check("口③ 既定では外の手を叩かない", len(CALLS) == 0, str(len(CALLS)))

print("=== 8. audit=False(突合の再現)ではD-2を回さない=枠を焼かない・再現が壊れない ===")


def _ledger_lines():
    p = os.path.join(_TMP, "llm", "tone_audit.jsonl")
    if not os.path.exists(p):
        return 0
    return sum(1 for l in open(p, encoding="utf-8") if l.strip())


del CALLS[:]
n0 = _ledger_lines()
a = port2(BROKEN, audit=True)
n1 = _ledger_lines()
c1 = len(CALLS)
b = port2(BROKEN, audit=False)
n2 = _ledger_lines()
check("口② audit=True は書き直す", a == GOOD, repr(a)[:60])
check("口② audit=True は台帳へ書く", n1 > n0, "%d→%d" % (n0, n1))
check("口② audit=False は本文不変(再現に非決定な段を混ぜない)", b == BROKEN, repr(b)[:60])
check("口② audit=False は外の手を叩かない(枠を焼かない)", len(CALLS) == c1, str(len(CALLS) - c1))
check("口② audit=False は台帳へ1行も書かない", n2 == n1, "%d→%d" % (n1, n2))
# ★機械置換(ゲートD)の側は audit の有無で1ミリも変えない=HQ-0253は生きている。
_MECH = "俺は行くわ。あんたの言うとおりね。今夜のうちに実装まで持っていくわ。合流点で塞ぐのよ。"
check("口② 機械置換は audit 有無で同じ結果(HQ-0253)",
      PS.tone_backstop(_MECH, PERSONA, DEPT, audit=True)
      == PS.tone_backstop(_MECH, PERSONA, DEPT, audit=False) != _MECH)

print("=== 9. 台帳は1本(event=tone_rewrite・口はsrc/sourceで分ける) ===")
_paths = [os.path.join(_TMP, "llm", "tone_audit.jsonl")]
rows = []
for p in _paths:
    if os.path.exists(p):
        rows += [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
rw = [r for r in rows if r.get("event") == "tone_rewrite"]
ports_seen = set((r.get("src") or r.get("source") or "daemon") for r in rw)
check("3口ぶんの tone_rewrite 行が同じ1本へ出た",
      {"daemon", "persona_send", "mirror"} <= ports_seen, str(sorted(ports_seen)))
check("行に書き直し前後の抜粋が入っている",
      all(r.get("excerpt") for r in rw) and any(r.get("excerpt_after") for r in rw))
check("不採用(ok=false)も理由つきで残る=何件弾かれたか後から数えられる",
      any((not r.get("ok")) and r.get("why") for r in rw))

TR.ask_cascade = _REAL_ASK
print("\n%d PASS / %d FAIL" % (OK[0], len(NG)))
for n in NG:
    print("  - %s" % n)
sys.exit(1 if NG else 0)
