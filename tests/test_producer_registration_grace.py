# -*- coding: utf-8 -*-
"""producer鮮度警報「登録直後の猶予」の検査(プラットフォームSE / 2026-08-23)。

★何を守るか= producers.json へ新しく登録した瞬間、その脈ファイルはまだ無い(age is None)。
  本物の巡回が初めて回るまで stale と見え、登録直後から consecutive 回で**誤発火**する。
  それを人手で脈を1行書いて埋めるのは、鮮度が mtime しか見ない以上「人の手」と
  「本物のセンサー」を機械が区別できない=死が隠れる窓を作る(C-054)。
  → 登録の初観測(first_seen)から max_age_sec を過ぎるまでは鳴らさない機構を入れた。

★test-must-fail= 「文字列が在るか」は見ない。**本物の check_producer_freshness を実行で通す**。
  外へ出る手(Discord送信)だけ dry_run で止め、判定と分岐は本物。レジストリの**入力だけ**を
  合成行へ差し替え(本番 producers.json も本番の脈も1バイトも触らない・C-054)。
  変異(C-053)= 猶予述語を「動く別の実装=猶予なし(=旧挙動)」へ戻すと、登録直後でも鳴る
  =この検査が空PASSでないことを、文法を壊さずに証明する。

    python tests/test_producer_registration_grace.py
"""
import os
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "discord"))

import absence_watchdog as AW              # noqa: E402

NAME = "test_grace_synthetic"
MAX_AGE = 3600                             # 猶予幅=1時間ぶんの合成値
_fails = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        _fails.append(label)


def _row(path):
    """合成の登録1行。name/間隔/連続回数/宛先は検査内で完結(本番の登録には触れない)。"""
    return {"name": NAME, "path": path, "max_age_sec": MAX_AGE,
            "consecutive": 2, "alert_dept": "aegis-gl", "owner": "test", "note": ""}


def _spin(state, pulse_path, times):
    """鮮度検査を times 回まわす。★送信だけ dry_run で止め、判定と分岐は本物。
    load_producers の**入力だけ**を合成行へ差し替える(本番 producers.json は読まない)。"""
    keep = AW.load_producers
    AW.load_producers = lambda: [_row(pulse_path)]
    try:
        for _ in range(times):
            AW.check_producer_freshness(state, True)
    finally:
        AW.load_producers = keep
    return (state.get("producer_fresh") or {}).get(NAME) or {}


def _predicate_units(now):
    # 述語を直接、本物の分岐で通す(4つの出口を全部踏む)。
    ok(AW._in_registration_grace({"first_seen": now}, None, MAX_AGE, now) is True,
       "① 登録直後(脈なし・窓内)は猶予中=True")
    ok(AW._in_registration_grace({"first_seen": now - MAX_AGE - 1}, None, MAX_AGE, now) is False,
       "② 窓を過ぎたら猶予は終わる=False(永久化しない)")
    ok(AW._in_registration_grace({"first_seen": now, "pulsed": True}, None, MAX_AGE, now) is False,
       "③ 一度でも脈を見た(pulsed)ら猶予は終わる=False")
    ok(AW._in_registration_grace({}, None, MAX_AGE, now) is False,
       "④ first_seen が無い既存state=猶予せず鳴らす側へ(fail toward 鳴らす)")
    ok(AW._in_registration_grace({"first_seen": now}, 10.0, MAX_AGE, now) is False,
       "脈が現に在る(age not None)なら猶予の対象外=False")


def main():
    now = time.time()
    _predicate_units(now)

    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "not_yet_created_pulse.md")   # 脈ファイルは作らない=登録直後

        # --- 受け入れ条件1: 新規登録直後(脈なし)に consecutive 回まわしても鳴らない ---
        st = {}
        s = _spin(st, missing, 2)
        ok(s.get("down") is not True and int(s.get("consec", 0)) == 0,
           "1) 登録直後は consecutive 回まわしても鳴らない(down=False / consec=0)")
        ok(bool(s.get("first_seen")), "  first_seen が state に記録されている(猶予の起点)")

        # --- 受け入れ条件2: 登録から max_age_sec を過ぎたら鳴る(猶予は永久ではない) ---
        st2 = {"producer_fresh": {NAME: {"consec": 0, "down": False, "last_alert": 0,
                                         "first_seen": now - MAX_AGE - 100}}}
        s2 = _spin(st2, missing, 2)
        ok(s2.get("down") is True,
           "2) 登録から max_age_sec 経過後は consecutive 回で鳴る(猶予が永久化していない)")

        # --- 受け入れ条件3: 既存producer(脈が既に在る)の挙動は不変 ---
        live = os.path.join(tmp, "live_pulse.md")
        with open(live, "w", encoding="utf-8") as f:
            f.write("live\n")                       # age≈0=生きている脈
        st3 = {}
        s3 = _spin(st3, live, 2)
        ok(s3.get("down") is not True and s3.get("pulsed") is True,
           "3) 脈が在る既存producerは鳴らない・pulsed=Trueが立つ(挙動不変)")

        # --- ★must-fail(C-053): 猶予述語を「動く別の実装=猶予なし(旧挙動)」へ戻すと、
        #      登録直後でも鳴る。=猶予が実際に発火を止めていることの証明(空PASSでない) ---
        keep = AW._in_registration_grace
        AW._in_registration_grace = lambda st, age, mx, now: False   # 旧=猶予が無い実装
        try:
            stm = {}
            sm = _spin(stm, missing, 2)
            ok(sm.get("down") is True,
               "変異(猶予なし): 登録直後でも consecutive 回で鳴る(=猶予が発火を止めていた)")
        finally:
            AW._in_registration_grace = keep
        # 復元できているか(変異を跨いでも本番挙動が戻る)
        str_ = {}
        sr = _spin(str_, missing, 2)
        ok(sr.get("down") is not True,
           "変異後: 復元できている(登録直後は再び鳴らない)")

    print()
    if _fails:
        print("FAIL %d件: %s" % (len(_fails), " / ".join(_fails)))
        return 1
    print("全PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
