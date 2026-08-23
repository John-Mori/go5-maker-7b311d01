# -*- coding: utf-8 -*-
"""手1(研究室HQ 2026-08-23)の述語 routine_producer_model の検査。

★何を守るか= 「朝の定型producer便だけ Sonnet・Chami/🔥/炎上/インシデントは Opus のまま」。
  この分岐が静かに壊れると、①朝の節約が効かない(全部Opus)か、②Chamiや🔥の便まで
  安いモデルへ落ちる(品質事故)。どちらも実物が出るまで気づけない=ここで実行で通す。

★test-must-fail= 述語の**本物の分岐**を走らせ、判定を1つ壊すと必ず落ちることを確かめる
  (下の t_mutation)。外へ出る手は無い(純関数)ので偽装するものが無い。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dept_daemon as D          # noqa: E402

SE = "self (scheduled daily review)"
KAIZEN = "自動(毎朝8:10の改修α集計)"
EMOJI = "絵文字監視(毎朝8時の自動巡回)"

_fails = []


def ok(cond, label):
    print(("PASS" if cond else "FAIL") + " " + label)
    if not cond:
        _fails.append(label)


def t_producers_downgrade():
    ok(D.routine_producer_model({"author": SE, "content": "前日の振り返り"}) == "sonnet",
       "se_daily_review → sonnet")
    ok(D.routine_producer_model({"author": KAIZEN, "content": "24h集計"}) == "sonnet",
       "kaizen_daily_0810 → sonnet")
    ok(D.routine_producer_model({"author": EMOJI, "content": "再発スタンプ 3件"}) == "sonnet",
       "絵文字監視(再発のみ) → sonnet")


def t_keep_opus():
    # 🔥/炎上/インシデントを含む便は落とさない(C-040)。
    ok(D.routine_producer_model({"author": EMOJI,
                                 "content": "🔥【炎上=恒久対策まで行け】ここで英語のみ"}) is None,
       "絵文字監視でも🔥を含めば Opus のまま")
    ok(D.routine_producer_model({"author": EMOJI, "content": "炎上の対応をして"}) is None,
       "「炎上」を含めば Opus のまま")
    # Chamiの便は対象外。
    ok(D.routine_producer_model({"author": "Chami", "content": "これ直して"}) is None,
       "Chami便 → None")
    # 定型producer以外(通常の部門便・別の自動便)は対象外。
    ok(D.routine_producer_model({"author": "シャビ・アロンソ(研究室HQ)",
                                 "content": "手を入れてくれ"}) is None,
       "研究室HQ便 → None(定型producerでない)")
    ok(D.routine_producer_model({"author": "自動(毎朝5時の別便)", "content": "x"}) is None,
       "似た名前の別producer → None(完全一致でない)")
    ok(D.routine_producer_model({}) is None, "空rec → None(判定不能=落とさない)")


def t_mutation():
    # ★空PASSでないことの証明= author判定を無効化すると、非producer便が sonnet に化ける。
    saved = D._ROUTINE_PRODUCER_AUTHORS
    try:
        # 全 author を対象にしてしまう壊し方(=分岐が効いていれば非producerがsonnetになる)。
        D._ROUTINE_PRODUCER_AUTHORS = frozenset({"シャビ・アロンソ(研究室HQ)"})
        mutated = D.routine_producer_model(
            {"author": "シャビ・アロンソ(研究室HQ)", "content": "手を入れてくれ"})
        ok(mutated == "sonnet",
           "mutation: author判定を壊すと非producerが sonnet 化する(=判定は生きている)")
    finally:
        D._ROUTINE_PRODUCER_AUTHORS = saved
    # 元に戻ったことを確認。
    ok(D.routine_producer_model({"author": "シャビ・アロンソ(研究室HQ)",
                                 "content": "x"}) is None,
       "mutation後: 復元できている")


def main():
    t_producers_downgrade()
    t_keep_opus()
    t_mutation()
    print()
    if _fails:
        print("★FAIL %d件: %s" % (len(_fails), ", ".join(_fails)))
        return 1
    print("全PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
