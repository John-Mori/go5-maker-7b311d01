# -*- coding: utf-8 -*-
"""自室の回送レートが封筒へ勝手に載ることの検査(2026-09-16 イージス研究室)。

台帳= DEF-hq-2c62407ee9(2026-08-02 Chami「すぐ他に回そうとする癖があるな…構造的な問題だよ
これは」)の恒久側。2026-09-16 に再発(「いやカスミがやってよ」「回しすぎ」= ESC-local-lab-
1549786371537899664)。依頼= 研究室HQ `DISPATCH-aegis-gl-1789569348349`。
数える側= scripts/llm/relay_rate.py(HQ作・commit 2e12590)。載せる口= session_relay。

★ソースの文字列一致では見ない(C-053)= **本物の build_envelope を実行して、
  組み上がった封筒の文字列を読む**。偽物にするのは「どのログを数えるか」だけ
  (relay_rate.LOG の差し替え)で、しきい値の判定も分岐も本物のまま通す。

  python scripts/llm/test_relay_rate_note.py
  python scripts/llm/test_relay_rate_note.py --mustfail   # 足す前の版(.bak)で赤を確認
"""
import datetime
import io
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# ★書き先だけ砂場へ逃がす(口調の突き返しなどが常駐の状態を進めるため)。
#   session_relay は import 時に LOCAL を束ねるので、import より**前**に置く。
_BOX = tempfile.mkdtemp(prefix="relayrate_")
os.makedirs(os.path.join(_BOX, "llm"), exist_ok=True)
os.environ["GO5_LOCAL_DIR"] = _BOX
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import meta_strip                                 # noqa: E402
import relay_rate                                 # noqa: E402
import session_relay as sr                        # noqa: E402

BODY = "これ、カスミがやってよ。"                   # 封筒へ入れる本文(原文のまま残ること)

_fails = []


def ok(cond, name):
    print(("  OK  " if cond else "  NG  ") + name)
    if not cond:
        _fails.append(name)


def synth_log(counts, to="hq"):
    """{部屋: 件数} の合成 request_log を1本書いて、そのパスを返す。"""
    now = datetime.datetime.now() - datetime.timedelta(hours=1)
    p = os.path.join(tempfile.mkdtemp(prefix="rrlog_"), "request_log.jsonl")
    n = 0
    with io.open(p, "w", encoding="utf-8") as f:
        for room, k in counts.items():
            for i in range(k):
                n += 1
                f.write(json.dumps({
                    "request_id": "ESC-%s-DISPATCH-%s-15497863715378%05d" % (room, room, n),
                    "dept": to,
                    "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
                    "state": "queued",
                }, ensure_ascii=False) + "\n")
                # ★同じ便の state 遷移= 2行目。1件へ畳まれること(水増ししない)
                f.write(json.dumps({
                    "request_id": "ESC-%s-DISPATCH-%s-15497863715378%05d" % (room, room, n),
                    "dept": to,
                    "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
                    "state": "done",
                }, ensure_ascii=False) + "\n")
    return p


def envelope(mod, dept, log_path, state=None):
    """本物の build_envelope を1回通す。差し替えるのは**数える対象のログだけ**。"""
    st = state if state is not None else mod._state_block(64, 90709, 26224)
    real = relay_rate.LOG
    relay_rate.LOG = log_path
    try:
        rec = {"content": BODY, "author": "chami_fusoh", "msg_id": "TEST-RR",
               "channel": "テスト部屋", "ts": "2026-09-16T23:50:00"}
        return mod.build_envelope(rec, is_work=True, state=st, dept=dept,
                                  disc_full=False, disc_fp="x",
                                  verdict_full=False, verdict_fp="y"), st
    finally:
        relay_rate.LOG = real


MARK = "回送レート"


def run(mod, label):
    print("== " + label + " ==")

    # --- A しきい値(0件の部屋には1文字も出さない・境界は3件) ------------------------
    log = synth_log({"local-lab": 13, "someday-room": 2, "system-engineer": 3})
    env0, _ = envelope(mod, "aegis-gl", log)                 # 0件の部屋
    ok(MARK not in env0, "A-1 0件の部屋には1文字も出ない(HQ指定)")
    env2, _ = envelope(mod, "someday-room", log)             # 2件= しきい値の1つ下
    ok(MARK not in env2, "A-2 2件では出ない(しきい値 %d の下)" % mod.RELAY_RATE_FLOOR)
    env3, _ = envelope(mod, "system-engineer", log)          # 3件= 境界そのもの
    ok(MARK in env3, "A-3 3件で出る(境界= しきい値ちょうどは鳴る)")
    env13, st = envelope(mod, "local-lab", log)
    ok(MARK in env13, "A-4 13件の部屋では出る")

    # --- B 数字が数える側と1つも食い違わない(ORG-11= 計算の正本は relay_rate) --------
    relay_rate.LOG, real = log, relay_rate.LOG
    try:
        s = relay_rate.stats("local-lab", hours=24, path=log)
    finally:
        relay_rate.LOG = real
    ok(s["count"] == 13 and s["total_all_rooms"] == 18,
       "B-0 合成ログの読みが合う(13/18・state遷移の2行目を水増ししていない) 実測 %d/%d"
       % (s["count"], s["total_all_rooms"]))
    ok("**13件**" in env13, "B-1 自室の件数がそのまま載る")
    ok("全部屋の回送 %d件" % s["total_all_rooms"] in env13, "B-2 全部屋合計が載る")
    ok("**%.0f%%**" % s["share_pct"] in env13,
       "B-3 割合が relay_rate.stats と一致する(%.0f%%)" % s["share_pct"])
    ok("§3.8" in env13 and "上げて、結論が変わるか" in env13,
       "B-4 §3.8 の1問がそのまま載る(心がけではなく判定の言葉)")
    ok("relay_rate.py --dept local-lab" in env13,
       "B-5 自分で数え直す道が載る(数字を信じろではなく、確かめられる形)")
    ok("理由" not in env13.split(MARK, 1)[1].split("★前の便", 1)[0],
       "B-6 送り手に何かを書かせる要求をしていない(人手の入口を作らない)")

    # --- C 置き場所(封筒エコー切りに覆われること) -----------------------------------
    i_state, i_rate = env13.find(st), env13.find("★★**" + MARK)
    ok(i_state >= 0 and i_rate > i_state
       and env13[i_state + len(st):i_rate].strip() == "",
       "C-1 セッション状態の**直後**に在る(間に何も挟まらない= 毎便変わる数字は同じ場所へ)")
    echo = "了解。やっておく。\n\n" + env13[i_state:i_state + len(st) + 400]
    cut, hits = meta_strip.strip_envelope_echo(echo)
    ok(bool(hits) and MARK not in cut,
       "C-2 返信へ封筒ごとエコーされても meta_strip がこの行まで落とす(印を足さずに済む)")

    # --- D 本文と既存の封筒を壊していない ---------------------------------------------
    ok(BODY in env13 and "--- 本文ここから ---" in env13,
       "D-1 本文は原文のまま(封筒が本文へ手を入れていない)")
    # ★同じ部屋の、鳴る版と鳴らない版で比べる(部屋を変えると目的/KPI等が動いて比較にならない)
    quiet, _ = envelope(mod, "local-lab", synth_log({"someday-room": 9}))
    ok(MARK not in quiet, "D-2 同じ部屋でも自室が0件なら出ない(他室の件数で鳴らない)")
    ok(len(env13) - len(quiet) <= 220,
       "D-3 封筒が太らない(同じ部屋での差 %d字)" % (len(env13) - len(quiet)))
    ok(mod._relay_rate_block("", path=log) == "",
       "D-4 部屋名が空なら何も足さない")

    # --- E fail-open(数える側が落ちても封筒は死なない) -------------------------------
    real_stats = relay_rate.stats

    def boom(*a, **k):
        raise RuntimeError("数える側が壊れている")

    try:
        relay_rate.stats = boom
        env_b, _ = envelope(mod, "local-lab", log)
        ok(BODY in env_b and MARK not in env_b,
           "E-1 relay_rate が例外でも封筒は組み上がる(便を握り潰さない)")
    finally:
        relay_rate.stats = real_stats
    envx, _ = envelope(mod, "local-lab", os.path.join(_BOX, "no_such_log.jsonl"))
    ok(BODY in envx and MARK not in envx,
       "E-2 ログが無い環境でも封筒は組み上がる(新しい部屋・初回起動)")
    return not _fails


def mustfail():
    """足す前の版(.bak)で、この検査が本当に赤くなるかを同じ手番で示す。"""
    p = os.path.join(HERE, "session_relay.py.bak_20260916_relayrate")
    if not os.path.exists(p):
        print("SKIP: 比較用の .bak が無い= " + p)
        return False
    tmp = os.path.join(tempfile.mkdtemp(prefix="rrold_"), "session_relay_old.py")
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(io.open(p, encoding="utf-8").read())
    spec = importlib.util.spec_from_file_location("session_relay_old", tmp)
    old = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(old)
    except Exception as e:                           # noqa: BLE001
        print("  OK  足す前の版は読み込みで落ちる(= 赤): %s" % e)
        return True
    red = not hasattr(old, "_relay_rate_block")
    print(("  OK  " if red else "  NG  ")
          + ".bak には _relay_rate_block が無い= A/B が赤くなる")
    if not red:
        return False
    log = synth_log({"local-lab": 13})
    env, _ = envelope(old, "local-lab", log)
    red2 = MARK not in env
    print(("  OK  " if red2 else "  NG  ")
          + ".bak の封筒には回送レートが1文字も載らない(実行で確認)")
    return red and red2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--mustfail" in sys.argv:
        sys.exit(0 if mustfail() else 1)
    TOTAL = 16
    good = run(sr, "現物 scripts/llm/session_relay.py")
    print(("PASS 回送レートの封筒注入 %d/%d" % (TOTAL - len(_fails), TOTAL)) if good
          else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
