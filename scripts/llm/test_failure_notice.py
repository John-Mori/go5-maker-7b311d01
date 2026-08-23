# -*- coding: utf-8 -*-
"""suppress_failure_notice() の全分岐を回す(dept_daemon の失敗終端報告の可否)。

なぜ要るか= この述語は「Chamiに無音のまま止まって見せない」ための可用性判定だ。
  実物(2026-08-23 Chami「改修αが30分以上動かなくて止まってる？」)= 打ち切りが
  何度も無音で再配達され、Chamiには何十分も沈黙が続いていた。判定を1文字間違えると
  「また黙る」か「連投で履歴が汚れる」のどちらかに戻るので、全分岐を機械で固定する。

★must-fail= 述語を「timeoutでも一般失敗と同じ(3回目まで伏せる)」に戻した変異体で
  同じ表明が**落ちる**ことを確認する(常にPASSする空検査ではない)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as dd

FAIL = []


def _ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAIL.append(msg)


def _spec():
    """(kind, delivery_count) -> 伏せるべきか。テスト対象の期待仕様。"""
    return [
        # timeout= 部屋へは一切出さない(常に伏せる。Chami「削除で」2026-08-23)。
        (("timeout", 1), True, "timeout・配達1回目= 伏せる(確定情報ゼロで意味がない)"),
        (("timeout", 3), True, "timeout・配達3回目= 伏せる"),
        (("timeout", None), True, "timeout・配達数不明でも= 伏せる"),
        # 一般の配送失敗= 再配達3回目で初めて出す(1・2回目は伏せる)。
        (("", 1), True,  "一般失敗・配達1回目= 伏せる"),
        (("", 2), True,  "一般失敗・配達2回目= 伏せる"),
        (("", 3), False, "一般失敗・配達3回目= 出す(もう後が無い)"),
        (("auth", 1), True, "auth失敗・配達1回目= 伏せる(timeout以外の一般失敗と同じ)"),
        (("", None), False, "一般失敗・配達数不明= 出す側へ倒す"),
    ]


def _touched_spec():
    """(touched入力, 期待するsubstantive件数, 期待する報告が空か, ラベル)。"""
    codever = ["~local\\_daemon_codever\\dept_hr-room.txt",
               "~local\\_daemon_codever\\dept_platform-se.txt"]
    busy = ["~local\\llm\\busy\\gunji.json"]
    churn_only = codever + busy + ["~local\\persona_avatars.json",
                                   "~local\\llm\\room_sessions.json"]
    real = ["scripts/llm/daily_report.py"] + codever
    return [
        ([], 0, True, "touched空= 報告は空(黙る)"),
        (churn_only, 0, True, "churnだけ(codever/busy/脈)= 実体0=黙る"),
        (real, 1, False, "実体1件+churn混在= 実体だけ拾って報告する"),
        (["app.js", "app.js"], 1, False, "重複は1件に畳む"),
    ]


def main():
    for (kind, dl), want, label in _spec():
        got = dd.suppress_failure_notice(kind, dl)
        _ok(got == want, f"{label} → suppress={got}")

    # ★must-fail: timeoutを一般失敗と同一視する変異体(_dl<3で伏せる=3回目は出す)なら、
    #   「timeout・配達3回目= 伏せる」の期待が壊れるはず(変異体は出してしまう)。
    def mutant(kind, delivery_count):
        if delivery_count is None:
            return False
        return delivery_count < 3     # ← timeoutを部屋へ出さない特別扱いを消した壊れた版
    _ok(mutant("timeout", 3) is False
        and dd.suppress_failure_notice("timeout", 3) is True,
        "must-fail: timeout特別扱いを消した変異体は配達3回目に誤って出す(本物は伏せる)")

    # --- 打ち切りの"確定結果": substantive_touched / format_timeout_result ---
    for touched, n_want, empty_want, label in _touched_spec():
        subst = dd.substantive_touched(touched)
        _ok(len(subst) == n_want, f"{label} → substantive={subst}")
        line = dd.format_timeout_result(touched)
        _ok((line == "") is empty_want,
            f"{label} → report_empty={line == ''}")
    # 実体があれば触ったファイル名が本文に載る(確定事実を名指しする)。
    _ok("daily_report.py" in dd.format_timeout_result(["scripts/llm/daily_report.py"]),
        "実体変更のファイル名が確定結果の本文に載る")

    # pick_timeout_touched: msg_id一致かつ打ち切り監査(rc==-1 / hard timeout)だけ拾う。
    entries = [
        {"msg_id": "M1", "rc": 0, "stdout_tail": "success", "touched": ["a.py"]},
        {"msg_id": "M2", "rc": -1, "stdout_tail": "hard timeout(強制終了)", "touched": ["b.py"]},
        {"msg_id": "M1", "rc": -1, "stdout_tail": "hard timeout(強制終了)", "touched": ["c.py"]},
        {"msg_id": "M1", "rc": -1, "stdout_tail": "hard timeout(強制終了)", "touched": ["d.py"]},
    ]
    _ok(dd.pick_timeout_touched(entries, "M1") == ["d.py"],
        "pick: M1の打ち切り監査を最新1件だけ拾う(成功rc=0は無視)")
    _ok(dd.pick_timeout_touched(entries, "M2") == ["b.py"], "pick: 別msg_idは混ぜない")
    _ok(dd.pick_timeout_touched(entries, "M9") == [], "pick: 該当なしは空")

    # ★must-fail: churnを落とさない変異体(そのまま返す)なら、churnだけの入力でも
    #   「実体あり」と誤判定して報告が非空になる=「churnだけ=黙る」の期待が壊れる。
    churn_only = ["~local\\_daemon_codever\\dept_hr-room.txt", "~local\\llm\\busy\\gunji.json"]
    def mutant_touched(touched):
        return [str(p).lstrip("~") for p in (touched or [])]   # ← churn除去を消した壊れた版
    _ok(len(mutant_touched(churn_only)) > 0
        and dd.substantive_touched(churn_only) == [],
        "must-fail: churn除去を消した変異体はchurnだけでも実体ありと誤る(本物は空)")

    print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAIL"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
