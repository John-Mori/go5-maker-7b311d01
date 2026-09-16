# -*- coding: utf-8 -*-
"""回送レート計が重くなった時、**機械が**1行残すことの検査(2026-09-17 イージス研究室)。

発注= 研究室HQ `DISPATCH-aegis-gl-1789570636582`(HQ-0269)。原文=
  「`load()` の所要が閾値(例 0.5秒)を超えたら、その事実がどこかへ1行残る。
    残り先も鳴り方もそちらの裁量でいい(封筒へ出す必要は無い。むしろ出すな)」
理由= 前の版は「効いてきたら直す/その時が来たことは秒数で分かる」と書いていた=
  **人手の入口を要件にした機構**(共通規律§3)。誰も秒数を見ない=実測0件になる。

★ソースの文字列一致では見ない(C-053)= **本物の load() を実行して**判定と分岐を通す。
  偽物にするのは「どこへ書くか」(RELAY_RATE_SLOW_LOG)と「何秒で鳴るか」
  (RELAY_RATE_SLOW_SEC)だけ。閾値の比較も、書き込みも、畳みも本物のまま走る。

  python scripts/llm/test_relay_rate_slow.py
  python scripts/llm/test_relay_rate_slow.py --mustfail   # 足す前の版(.bak)で赤を確認
"""
import datetime
import importlib.util
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_BOX = tempfile.mkdtemp(prefix="rrslow_")
os.makedirs(os.path.join(_BOX, "llm"), exist_ok=True)
os.environ["GO5_LOCAL_DIR"] = _BOX               # ★書き先を砂場へ(import より前)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import relay_rate                                # noqa: E402
import session_relay as sr                       # noqa: E402

_fails = []


def ok(cond, name):
    print(("  OK  " if cond else "  NG  ") + name)
    if not cond:
        _fails.append(name)


def synth_log(n=40):
    """本物の形をした request_log を1本書く(load() に本物の仕事をさせる)。"""
    now = datetime.datetime.now() - datetime.timedelta(hours=1)
    p = os.path.join(tempfile.mkdtemp(prefix="rrslog_"), "request_log.jsonl")
    with io.open(p, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({
                "request_id": "ESC-local-lab-DISPATCH-local-lab-15497863715378%05d" % i,
                "dept": "hq", "ts": now.strftime("%Y-%m-%dT%H:%M:%S"), "state": "queued",
            }, ensure_ascii=False) + "\n")
        f.write("これは壊れた行\n")                 # 壊れた行があっても落ちないこと
    return p


def fresh_dest():
    d = os.path.join(tempfile.mkdtemp(prefix="rrslowlog_"), "relay_rate_slow.jsonl")
    os.environ["RELAY_RATE_SLOW_LOG"] = d
    return d


def read(dest):
    if not os.path.exists(dest):
        return []
    return [json.loads(x) for x in io.open(dest, encoding="utf-8").read().splitlines() if x.strip()]


def run():
    log = synth_log()

    # --- A 平時は1文字も書かない(誤発火しない安全網であること) ----------------------
    dest = fresh_dest()
    os.environ["RELAY_RATE_SLOW_SEC"] = "0.5"      # 既定と同じ閾値。実測 0.125秒 の4倍
    rows = relay_rate.load(log)
    ok(len(rows) == 40, "A-0 load() は本物の仕事をしている(ESC 40件を読んだ)")
    ok(not os.path.exists(dest), "A-1 閾値を超えていない時は記録先を作りもしない")
    ok(relay_rate.slow_last() is None, "A-2 鳴っていなければ slow_last() は None")

    # --- B 超えたら機械が1行残す(人手の入口ゼロ) -----------------------------------
    os.environ["RELAY_RATE_SLOW_SEC"] = "0"        # ★どんな実行時間でも上回る= 分岐を通す
    relay_rate.load(log)
    got = read(dest)
    ok(len(got) == 1, "B-1 閾値を超えたら1行だけ残る(実測 %d行)" % len(got))
    r = got[0] if got else {}
    ok(r.get("log") == log and r.get("log_lines") == 41,
       "B-2 どのログを何行舐めたかが行に載る(41行= 壊れた行も舐めている)")
    ok(isinstance(r.get("elapsed_sec"), float) and r.get("threshold_sec") == 0.0,
       "B-3 実測の秒数と、その時の閾値が両方載る(後から検算できる)")
    ok(r.get("dept") == "aegis-gl" and r.get("次の一手"),
       "B-4 誰の手番か・次に何をするかが行に載る(閉じ方の決まらない起票を作らない=C-046)")

    # --- C 積み上げない(1日1行へ畳む) ----------------------------------------------
    relay_rate.load(log)
    relay_rate.load(log)
    ok(len(read(dest)) == 1, "C-1 同じ日に何度超えても1行のまま(警報でログを太らせない)")

    # --- D 読まれる面へ出る(台帳=所有部門だけ・封筒には出ない) ----------------------
    led_owner = "\n".join(sr._ledger_lines("aegis-gl"))
    led_other = "\n".join(sr._ledger_lines("local-lab"))
    ok("回送レート計が重くなっている" in led_owner,
       "D-1 所有部門(aegis-gl)の台帳には出る")
    ok("回送レート計が重くなっている" not in led_other,
       "D-2 他室の台帳には1文字も出ない(直せない部屋に警報を積まない)")
    env = sr.build_envelope({"content": "本文", "author": "chami_fusoh", "msg_id": "TEST-SLOW",
                             "channel": "テスト部屋", "ts": "2026-09-17T00:30:00"},
                            is_work=True, state=sr._state_block(64, 90709, 26224),
                            dept="aegis-gl", disc_full=False, disc_fp="x",
                            verdict_full=False, verdict_fp="y")
    ok("回送レート計が重くなっている" not in env,
       "D-3 **封筒には出ない**(毎便鳴る安全網は無視される= HQ指定)")
    ok(sr._relay_rate_slow_line("aegis-gl").count("\n") <= 2,
       "D-4 台帳へ足すのは3行まで(1画面に収まらない面へ警報を積まない)")

    # --- E 直れば黙る / 壊れても本体を殺さない --------------------------------------
    old = dict(got[0]) if got else {}
    old["ts"] = (datetime.datetime.now() - datetime.timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S")
    with io.open(dest, "w", encoding="utf-8") as f:
        f.write(json.dumps(old, ensure_ascii=False) + "\n")
    ok(relay_rate.slow_last() is None and sr._relay_rate_slow_line("aegis-gl") == "",
       "E-1 8日前の1行は返さない= 費用を畳めば手で消さなくても黙る")
    with io.open(dest, "w", encoding="utf-8") as f:
        f.write("{壊れた\n")
    ok(relay_rate.slow_last() is None and sr._relay_rate_slow_line("aegis-gl") == "",
       "E-2 記録が壊れていても起動文は組み上がる(fail-open)")
    os.environ["RELAY_RATE_SLOW_LOG"] = os.path.join(_BOX, "no_such_dir", "x", "slow.jsonl")
    os.environ["RELAY_RATE_SLOW_SEC"] = "0"
    ok(len(relay_rate.load(log)) == 40,
       "E-3 記録先が無い深いパスでも load() は値を返す(見張りが本体を巻き添えにしない)")
    os.environ["RELAY_RATE_SLOW_SEC"] = "0.5"
    return not _fails


def mustfail():
    """足す前の版(.bak)で、この検査が本当に赤くなるかを同じ手番で示す。"""
    red = True
    p = os.path.join(HERE, "relay_rate.py.bak_20260917_slowload")
    if not os.path.exists(p):
        print("SKIP: 比較用の .bak が無い= " + p)
        return False
    tmp = os.path.join(tempfile.mkdtemp(prefix="rrold_"), "relay_rate_old.py")
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(io.open(p, encoding="utf-8").read())
    spec = importlib.util.spec_from_file_location("relay_rate_old", tmp)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    for fn in ("note_slow", "slow_last", "slow_log_path"):
        has = hasattr(old, fn)
        print(("  NG  " if has else "  OK  ") + ".bak に %s が無い= B/D/E が赤" % fn)
        red = red and not has
    dest = fresh_dest()
    os.environ["RELAY_RATE_SLOW_SEC"] = "0"
    old.load(synth_log())
    made = os.path.exists(dest)
    print(("  NG  " if made else "  OK  ") + ".bak は閾値0でも1行も残さない(実行で確認)")
    return red and not made


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--mustfail" in sys.argv:
        sys.exit(0 if mustfail() else 1)
    TOTAL = 15
    good = run()
    print(("PASS 回送レート計の費用の見張り %d/%d" % (TOTAL - len(_fails), TOTAL)) if good
          else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
