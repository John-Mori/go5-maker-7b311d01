#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提案日次チェーン起動器の警報ロジックの回帰テスト。

実行:            python scripts/_daemons/test_teian_daily_job.py
変異(must-fail): python scripts/_daemons/test_teian_daily_job.py --mutate

★2026-09-02 新設。引き金= 初日(09-02 07:00)の実測で C-046 の穴が出たこと:
  チェーンは exit=2(publish の空配信ガード)で止まったが、起動器は「非0=故障」としか
  読まず、**閉じ条件(room_comments を埋める)を持っていない改修部門α**へ3日おきに
  永久に便を打つ形になっていた。当てる先の無い警報は二度目から読まれない(規律§3)。
  そこで止まり方を classify で3つに分け、宛先と間隔を変えた。ここで釘付けにする。

★釘付けにする芯は「黙る側へ倒れないこと」:
  - 合図行が変わったら guard と判定できなくなる → **fail(=毎3日・改修部門α)へ倒れる**
  - 止まり方が変わった日は間隔を無視して必ず1通
  - 直った日は必ず1通(閉じる便)
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_daily_teian_job as J   # noqa: E402

results = []
GUARD_OUT = ("⑤ 配信 publish_candidates.py(空配信ガード)\n"
             "  - ready:dmmmg_1731(④comments)\n"
             "→ 未充填の候補があり配信を止めた(上の一覧)。軍議で room_comments を埋めて再実行。")


def check(name, cond):
    results.append((name, bool(cond)))
    print(("  OK  " if cond else "  NG  ") + name)


def st(kind, last_alert):
    return {"last_kind": kind, "last_ok": kind == "ok", "last_alert_date": last_alert}


def main():
    print("=== 提案日次 起動器: 止まり方の切り分けと警報間隔 ===")

    print("\n[1] 止まり方の切り分け")
    check("exit=0 は ok", J.classify(0, "") == "ok")
    check("exit=2 + 合図行 は guard", J.classify(2, GUARD_OUT) == "guard")
    check("exit=1 は fail(合図行があっても exit が違えば guard にしない)",
          J.classify(1, GUARD_OUT) == "fail")
    check("★合図行が変わったら guard と読まない= fail へ倒す(黙る側へ倒さない)",
          J.classify(2, "⑤ 配信 publish_candidates.py で何かあった") == "fail")
    check("タイムアウト(124)は fail", J.classify(124, "★3600秒で打ち切った") == "fail")

    print("\n[2] 宛先= 閉じ条件の鍵を持つ部屋")
    check("guard の宛先は軍議(room_comments を埋められる側)",
          J.alert_dept("guard") == "gunji")
    check("fail の宛先は改修部門α(チェーン本体の持ち主)",
          J.alert_dept("fail") == "system-engineer")

    print("\n[3] 節目は間隔を無視して必ず1通")
    check("成功→guard(初日)は出す",
          J.should_alert(st("ok", "2026-09-02"), "guard", "2026-09-02"))
    check("★guard→fail(設計どおりの停止が本当の故障に変わった)は出す",
          J.should_alert(st("guard", "2026-09-02"), "fail", "2026-09-02"))
    check("fail→guard も出す",
          J.should_alert(st("fail", "2026-09-02"), "guard", "2026-09-02"))
    check("guard→ok(戻った日)は必ず出す= 閉じる便",
          J.should_alert(st("guard", "2026-09-02"), "ok", "2026-09-05"))

    print("\n[4] 同じ止まり方が続く間の間隔")
    check("fail 継続: 翌日は出さない",
          not J.should_alert(st("fail", "2026-09-02"), "fail", "2026-09-03"))
    check("fail 継続: 3日後は出す",
          J.should_alert(st("fail", "2026-09-02"), "fail", "2026-09-05"))
    check("★guard 継続: 3日後は出さない(改修αへの永久便を作らない)",
          not J.should_alert(st("guard", "2026-09-02"), "guard", "2026-09-05"))
    check("guard 継続: 14日後は出す(止まったまま忘れられない)",
          J.should_alert(st("guard", "2026-09-02"), "guard", "2026-09-16"))
    check("成功が続く日は黙る",
          not J.should_alert(st("ok", "2026-09-02"), "ok", "2026-09-30"))

    print("\n[5] 読めない状態は鳴らす側へ(fail-open)")
    check("last_alert_date が空なら出す",
          J.should_alert(st("guard", ""), "guard", "2026-09-03"))
    check("日付が壊れていても出す",
          J.should_alert(st("guard", "きのう"), "guard", "2026-09-03"))
    check("last_kind が無い旧stateでも落ちない(last_ok から読む)",
          J.should_alert({"last_ok": True}, "guard", "2026-09-02"))

    print("\n[6] 便の本文は閉じ条件を必ず書く")
    for k in ("guard", "fail", "ok"):
        b = J.build_body(k, 2, GUARD_OUT, "2026-09-02", 1)
        check("%s の本文に閉じ方が書いてある" % k,
              ("閉じ条件" in b) or ("閉じる" in b))
    check("guard の本文で「落ちた」と断定しない",
          "設計どおりの停止" in J.build_body("guard", 2, GUARD_OUT, "2026-09-02", 1))
    check("guard の本文に --publish-force 禁止が残っている",
          "--publish-force` は使うな" in J.build_body("guard", 2, GUARD_OUT, "2026-09-02", 1))

    bad = sum(1 for _, c in results if not c)
    print("\n%d件中 %d件OK / %d件NG" % (len(results), len(results) - bad, bad))
    return 0 if bad == 0 else 1


# --- must-fail 変異(C-053: 壊れた実装ではなく「もっともらしく動く別実装」) ---

def _mut_code_only():
    """exit だけで guard を決める(合図行を見ない)。
    ★動く。だが**たまたま2で落ちた本物の故障**が14日間の静かな側へ沈む。"""
    J.classify = lambda code, out: "ok" if code == 0 else (
        "guard" if code == J.GUARD_CODE else "fail")


def _mut_same_interval():
    """間隔を止まり方で分けず、全部3日にする(=元の実装)。
    ★動く。だが軍議しか閉じられない停止を3日おきに鳴らし続ける= 元の穴に戻る。"""
    J.should_alert = (lambda state, kind, today, quiet_days=J.QUIET_DAYS,
                      guard_quiet_days=J.GUARD_QUIET_DAYS:
                      _orig_should(state, kind, today, quiet_days, quiet_days))


def _mut_interval_only():
    """間隔だけで決め、止まり方の変化を節目として見ない。
    ★動く。だが guard→fail(本当に壊れた日)が間隔の内側だと黙って通る。"""
    def f(state, kind, today, quiet_days=J.QUIET_DAYS,
          guard_quiet_days=J.GUARD_QUIET_DAYS):
        if kind == "ok":
            return not bool((state or {}).get("last_ok", True))
        return _orig_should(dict(state or {}, last_kind=kind), kind, today,
                            quiet_days, guard_quiet_days)
    J.should_alert = f


def _mut_dept_owner():
    """宛先を「チェーンの持ち主」で決める(全部 改修部門α)。
    ★動く。だが閉じ条件を持たない部屋へ出す= 当てる先の無い便に戻る。"""
    J.alert_dept = lambda kind: J.DEPT


_orig_should = J.should_alert
_orig_class = J.classify
_orig_dept = J.alert_dept

MUTANTS = (
    ("exit だけで guard を決める", _mut_code_only,
     "★合図行が変わったら guard と読まない= fail へ倒す(黙る側へ倒さない)"),
    ("間隔を分けない(全部3日)", _mut_same_interval,
     "★guard 継続: 3日後は出さない(改修αへの永久便を作らない)"),
    ("止まり方の変化を節目として見ない", _mut_interval_only,
     "★guard→fail(設計どおりの停止が本当の故障に変わった)は出す"),
    ("宛先を持ち主で決める", _mut_dept_owner,
     "guard の宛先は軍議(room_comments を埋められる側)"),
)


def mutate():
    bad = 0
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
            J.should_alert, J.classify, J.alert_dept = (
                _orig_should, _orig_class, _orig_dept)
        red = [n for n, c in results if not c]
        hit = want_red in red
        print("  → 狙った1件が赤か: %s  (赤=%d件)" % ("OK" if hit else "NG", len(red)))
        if not hit:
            bad += 1
    print("\n変異 %d件中 %d件が狙いどおり赤" % (len(MUTANTS), len(MUTANTS) - bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(mutate() if "--mutate" in sys.argv else main())
