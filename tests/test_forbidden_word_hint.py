#!/usr/bin/env python3
"""封筒の予防ブロック `_forbidden_word_hint`= **この声が使わない語を、書く前に目の前へ置く**か。

★0歩目= 壊れている実物(2026-09-20T02:32:18・軍議 msg 1550922497988362384・三笘薫)
  「…①の提案と一緒に**効いてくるやつよ。**」
  Chami原文 msg 1550924526110642308=「なんか女っぽかったので。**語尾に〜よ をつけるのは
  いいんだけど文脈次第だね**」= **素の「よ」は禁じていない**。禁じているのは台帳に載った形だけ。
★発注= 人事部門ククール上申 `ESC-hr-room-DISPATCH-hr-room-1789864236120`。
★実測(入れる前)= 生成側には口調ルール.jsonの禁止語が1文字も渡っていなかった。
  出力側の保険(ゲートD-2 tone_rewrite)は生きている= 壊れた実物を通したら
  「効いてくるやつよ。」→「効いてくる。」へ書き直して accept した。足りないのは**予防**だけだった。

★ここで見るのは「ソースに文字列が在るか」ではない= **本物の 口調ルール.json を読ませ、
  偽の部屋設定(conf)を渡して関数を実行で通す**。外へ出る手は無い関数なので偽物は要らない。
★must-fail(C-053)= 壊した側は行を消さず**動く別の実装**へ差し替える。3本置いた=
  共通と固有を人数で分けない版 / plain_only を見ない版 / fail-open を持たない版。

走らせ方= `python tests/test_forbidden_word_hint.py`
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import session_relay as SR              # noqa: E402
import tone_gate                        # noqa: E402

FAILS = []


def ok(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- 検査に使う部屋(偽のconf)
# 三笘薫       = 常体で登録・**その人格だけの語**を持つ          … 並ばないといけない
# 一ノ瀬怜     = **敬体**(plain_only なし)だが固有の語を持つ     … 1文字も足してはいけない
# ミギー       = 口調ルール.json に居ない                        … 並んではいけない
ROOM = {"persona": "三笘薫",
        "personas": [{"persona": "一ノ瀬怜"}, {"persona": "存在しない人格ミギー"}]}
# 十王星南 = 常体で登録されているが、禁じているのは**全員共通の事務文体10句だけ**
#            (実測 2026-09-20= 同じ形が他に3人 ケヴィン・デブライネ/ククール/カスミ)
#            … 言うことが無いのだからブロックごと出てはいけない
QUIET_ROOM = {"persona": "十王星南", "personas": []}

COMMON_WORD = "対応しました"        # 実測= 20人格中16人が禁じている(=共通の事務文体)
OWN_WORDS = ("やつよ", "わよ", "かしら")

C1 = "三笘薫の固有の語(やつよ/わよ/かしら)が並ぶ"
C2 = "全員共通の事務文体(「対応しました」)は並ばない"
C3 = "敬体で登録された人格(一ノ瀬怜)には1文字も足さない"
C4 = "口調ルール.jsonに無い人格(ミギー)は並ばない"
C5 = "素の「よ」は禁じない(Chamiの線)"
C6 = "固有の語を持たない部屋にはブロックごと出さない"
C7 = "写像が読めない時は空(fail-open)"
C8 = "写像の読みが例外を投げても空(fail-open)"


def run_checks(fn):
    """8項目を**実行で**通す。例外が出た項目はその場で赤(fail-open が壊れた印)。"""
    out = []

    def call(conf):
        return fn("gunji", conf=conf)

    try:
        got = call(ROOM)
        out.append((C1, all(("「%s」" % w) in got for w in OWN_WORDS), "got=%r" % got[:120]))
        out.append((C2, COMMON_WORD not in got, ""))
        out.append((C3, "一ノ瀬怜" not in got, ""))
        out.append((C4, "ミギー" not in got, ""))
        out.append((C5, "「よ」" not in got, ""))
    except Exception as e:
        for n in (C1, C2, C3, C4, C5):
            out.append((n, False, "例外= %r" % (e,)))

    for name, conf in ((C6, QUIET_ROOM),):
        try:
            out.append((name, call(conf) == "", "got=%r" % call(conf)[:80]))
        except Exception as e:
            out.append((name, False, "例外= %r" % (e,)))

    real = tone_gate.load_tone_rules
    for name, stub in ((C7, lambda *a, **k: None),
                       (C8, _raise)):
        tone_gate.load_tone_rules = stub
        try:
            out.append((name, call(ROOM) == "", ""))
        except Exception as e:
            out.append((name, False, "例外がそのまま出た= %r" % (e,)))
        finally:
            tone_gate.load_tone_rules = real
    return out


def _raise(*a, **k):
    raise IOError("口調ルール.json が壊れている(検査用)")


# ---------------------------------------------------------------- must-fail(動く別の実装)
def hint_no_plain_check(dept, conf=None):
    """★壊した側その1= **plain_only を見ない**版(登録さえ在れば鳴らす)。

    「禁止語を渡すだけなら誰に渡しても害は無い」と考えると、こう書く方が短い。
    落ちるのは**敬体で登録された人格**だ= 常体の男口調を前提にした文言を敬体の声へ渡すことに
    なり、C-035(名指し1人の話を全体へ広げるな)を機構の側から破る。
    """
    try:
        rules = tone_gate.load_tone_rules(SR.TONE_RULES_PATH)
        personas = (rules or {}).get("personas") or {}
        if not personas:
            return ""
        tally = {}
        for k, v in personas.items():
            if str(k).startswith("_") or not isinstance(v, dict):
                continue
            for w in set(SR._forbid_words(v)):
                tally[w] = tally.get(w, 0) + 1
        c = conf or {}
        who_list = [str(c.get("persona") or "")] + [str(p.get("persona") or "")
                                                    for p in (c.get("personas") or ())]
        lines, seen = [], set()
        for who in who_list:
            if not who or who in seen:
                continue
            seen.add(who)
            ent = tone_gate._persona_entry(rules, who)
            if not isinstance(ent, dict):
                continue                       # ★ここで plain_only を見ない
            own = [w for w in SR._forbid_words(ent)
                   if tally.get(w, 0) < SR._FORBID_COMMON_MIN]
            if not own:
                continue
            lines.append("  【%s】使わない: %s"
                         % (who, " / ".join("「%s」" % w for w in own[:SR._FORBID_MAX_WORDS])))
        if not lines:
            return ""
        return "=== ★この声が使わない語 ===\n" + "\n".join(lines) + "\n\n"
    except Exception:
        return ""


def hint_no_failopen(dept, conf=None):
    """★壊した側その2= **try/except を持たない**版(本体は同じ)。

    平時は1文字も違わない出力を出す。落ちるのは台帳が壊れた日だけだ=
    予防線の例外がそのまま封筒の組み立てへ抜け、**その部屋の便が丸ごと出なくなる**。
    §3= 沈黙が最悪の事故。予防線は配送を殺してはいけない。
    """
    rules = tone_gate.load_tone_rules(SR.TONE_RULES_PATH)
    personas = (rules or {}).get("personas") or {}
    if not personas:
        return ""
    tally = {}
    for k, v in personas.items():
        if str(k).startswith("_") or not isinstance(v, dict):
            continue
        for w in set(SR._forbid_words(v)):
            tally[w] = tally.get(w, 0) + 1
    c = conf or {}
    who_list = [str(c.get("persona") or "")] + [str(p.get("persona") or "")
                                                for p in (c.get("personas") or ())]
    lines, seen = [], set()
    for who in who_list:
        if not who or who in seen:
            continue
        seen.add(who)
        ent = tone_gate._persona_entry(rules, who)
        if not isinstance(ent, dict) or not ent.get("plain_only"):
            continue
        own = [w for w in SR._forbid_words(ent) if tally.get(w, 0) < SR._FORBID_COMMON_MIN]
        if not own:
            continue
        lines.append("  【%s】使わない: %s"
                     % (who, " / ".join("「%s」" % w for w in own[:SR._FORBID_MAX_WORDS])))
    if not lines:
        return ""
    return "=== ★この声が使わない語 ===\n" + "\n".join(lines) + "\n\n"


def reds(fn):
    return [r[0] for r in run_checks(fn) if not r[1]]


def main():
    print("■ 本物の 口調ルール.json を読ませ、偽の部屋設定で実行で通す")
    for r in run_checks(SR._forbidden_word_hint):
        ok(*r)

    print("■ must-fail その1= 共通と固有を人数で分けないと、事務文体まで毎便並ぶこと")
    # ★分けない版= 閾値を外す。分けないのだから語数の上限でも隠れないよう同時に外す
    #   (上限で切れて見えなくなると、何が原因で赤くなったのか分からなくなる)。
    keep = (SR._FORBID_COMMON_MIN, SR._FORBID_MAX_WORDS)
    SR._FORBID_COMMON_MIN, SR._FORBID_MAX_WORDS = 10 ** 9, 99
    try:
        bad = reds(SR._forbidden_word_hint)
        ok("分けない実装では C2 と C6 だけが赤くなる", bad == [C2, C6],
           "赤=%d / %s" % (len(bad), " , ".join(bad)))
    finally:
        SR._FORBID_COMMON_MIN, SR._FORBID_MAX_WORDS = keep

    print("■ must-fail その2= plain_only を見ないと、敬体の人格にまで足すこと")
    bad = reds(hint_no_plain_check)
    ok("plain_onlyを見ない実装では C3 だけが赤くなる", bad == [C3],
       "赤=%d / %s" % (len(bad), " , ".join(bad)))

    print("■ must-fail その3= fail-open を外すと、台帳が壊れた日に封筒ごと落ちること")
    bad = reds(hint_no_failopen)
    ok("fail-openを持たない実装では C8 だけが赤くなる", bad == [C8],
       "赤=%d / %s" % (len(bad), " , ".join(bad)))

    print("\n%s  (%d FAIL)" % ("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS),
                               len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
