# -*- coding: utf-8 -*-
"""絵文字一覧(手2でファイル化した全部屋一覧)の**脈**の検査(イージス研究室 / 2026-08-23)。

★何を守るか= 「一覧が来ない」を**沈黙で終わらせない**こと。
  手2で、改善提案部門への一覧は dispatch(=部門を起こす)から**ファイル**へ替わった。
  配達だった頃は届かなければ足跡が残ったが、ファイルは**無いのが正常な日と区別できない**。
  実際 `if not items:` の枝は書かずに返っていたので、
    ・新しいスタンプが0件の朝
    ・絵文字監視そのものが死んだ朝
  の両方が、改善提案部門の便では**同じ「無し」**になっていた。これは静かな死だ。
  → ①0件でも必ず書く(`write_kaizen_digest`)②`producers.json` へ登録して鮮度で見張る。

★test-must-fail= ここは「文字列が在るか」を見ない。**実物のファイルを実際に書き、実際に読み、
  実際に鮮度警報へ通す**。外へ出る手(Discordへの送信)だけ dry_run で止め、判定と分岐は本物。
  変異(mtimeを3日前へ倒す / 書けない先を渡す)で**必ず落ちる側**も同じ経路で通す。

    python tests/test_emoji_digest_pulse.py
"""
import io
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))

import reaction_watch as RW              # noqa: E402  (書く側)
import run_kaizen_daily_repair as RK     # noqa: E402  (読む側)
import absence_watchdog as AW            # noqa: E402  (死を鳴らす側)

NAME = "reaction_watch_digest"
MARK = "検査の種(test_emoji_digest_pulse)"
_fails = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        _fails.append(label)


def freshness(state):
    """鮮度検査を1回まわす。★送信だけ dry_run で止め、判定は本物。"""
    AW.check_producer_freshness(state, True)
    return (state.get("producer_fresh") or {}).get(NAME) or {}


def main():
    # --- 登録が実際に読めているか(ここが読めないと以下は全部 空PASS になる) ---
    rows = [p for p in AW.load_producers() if p["name"] == NAME]
    ok(len(rows) == 1, "producers.json に %s が1行だけ登録されている" % NAME)
    if not rows:
        return 1
    row = rows[0]
    ok(row["path"].endswith("reaction_watch_kaizen_digest.md"),
       "登録の path が絵文字一覧を指している")
    ok(os.path.abspath(RW.KAIZEN_DIGEST).lower().endswith(row["path"].replace("/", os.sep).lower()),
       "書く側(reaction_watch)と登録の path が同じ物を指している")

    # --- ① 書く: 0件の朝でも本物の関数で実ファイルが出来る ---
    body = "%s / 実際に書けることを確かめるために書いた種であって、巡回の結果ではない。" % MARK
    ok(RW.write_kaizen_digest(body, 0, False) is True, "write_kaizen_digest が True を返す(書けた)")
    ok(os.path.exists(RW.KAIZEN_DIGEST), "実ファイルが出来ている: %s" % RW.KAIZEN_DIGEST)

    # --- ② 読む: 改善提案部門の側が本日ぶんとして拾える ---
    got = RK.read_todays_emoji_digest()
    ok(bool(got) and MARK in got, "読む側(run_kaizen_daily_repair)が本日ぶんとして拾う")

    # --- ③ 生きている間は鳴らない(誤発火する安全網は無視される・規律§3) ---
    st = {}
    s = freshness(st)
    ok(s.get("down") is not True and int(s.get("consec", 0)) == 0,
       "新しいうちは鳴らない(consec=0 / down=False)")

    # --- ④ ★must-fail: 3日前へ倒すと、読む側は捏造せず None・鮮度は連続2回で鳴る ---
    old = time.time() - 3 * 86400
    os.utime(RW.KAIZEN_DIGEST, (old, old))
    ok(RK.read_todays_emoji_digest() is None, "変異(3日前): 読む側は古い一覧を今日の物にしない")
    s = freshness(st)
    ok(s.get("down") is not True and int(s.get("consec", 0)) == 1,
       "変異(3日前): 1回目は鳴らない(C-041 一度の観測を状態の代理にしない)")
    s = freshness(st)
    ok(s.get("down") is True, "変異(3日前): 2回連続で鳴る(=この警報は実際に発火できる)")

    # --- ⑤ 復旧すれば✅が出て状態が戻る(直ったのに黙っている、を作らない) ---
    now = time.time()
    os.utime(RW.KAIZEN_DIGEST, (now, now))
    s = freshness(st)
    ok(s.get("down") is False, "更新が戻れば✅で状態も戻る")

    # --- ⑥ ★must-fail: 書けない先を渡すと False(=台帳ゲートが生きている) ---
    keep = RW.KAIZEN_DIGEST
    try:
        RW.KAIZEN_DIGEST = os.path.join(ROOT, "local", "_work",
                                        "存在しない\x00不正な名前", "digest.md")
        ok(RW.write_kaizen_digest("x", 1, False) is False,
           "変異(書けない先): False を返す= 台帳へ書かず次回拾い直す枝が生きている")
    finally:
        RW.KAIZEN_DIGEST = keep

    # --- 後始末= 脈を生きた状態で置いていく(登録した直後に無いと、明日の朝まで誤発火する) ---
    RW.write_kaizen_digest(
        "%s / 2026-08-23 に脈を起こすために書いた種。明日の朝8時の巡回が本物で上書きする。"
        % MARK, 0, False)
    ok(os.path.exists(RW.KAIZEN_DIGEST), "検査の後、脈は生きたまま残っている")

    print()
    if _fails:
        print("FAIL %d件: %s" % (len(_fails), " / ".join(_fails)))
        return 1
    print("全PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
