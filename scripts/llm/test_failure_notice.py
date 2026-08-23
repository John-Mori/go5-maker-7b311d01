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

    print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAIL"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
