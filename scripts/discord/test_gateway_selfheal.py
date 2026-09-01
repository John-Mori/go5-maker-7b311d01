#!/usr/bin/env python3
"""discord_gateway の沈黙死・自己回復(取りこぼし連続→張り直し)の回帰ガード。

なぜ要るか(2026-09-01 platform-se・一ノ瀬怜):
  GATEWAY_PULSE は job_pulse が45秒毎に無条件で叩くので、on_message(実受信)が死んでも
  脈だけ新鮮に見える=supervisorもwatchdogも脈監視では沈黙死を見抜けない。実測 2026-09-01、
  gateway(pid7396)が06:46に実受信停止・脈は空回りで8時間 未検知(P1「どの部屋も反応ない」)。
  唯一 REST照合の取りこぼし回収(relay_repair)だけが取り逃しを地上真実で捉えた=そこへ再起動を
  配線した。この検査が守るのは「取りこぼしが連続した時だけ・暴走せず gateway を張り直す判定」。
  ここが緑でなくなったら、また偽脈の裏で受信が黙って死んでも誰も張り直さない。

実行: python scripts/discord/test_gateway_selfheal.py
"""
import io
import os
import sys
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import absence_watchdog as aw  # noqa: E402

P = F = 0


def ok(cond, name):
    global P, F
    if cond:
        P += 1
        print("PASS", name)
    else:
        F += 1
        print("FAIL", name)


# ---- 純関数 _note_gateway_stuck: 連続・閾値・クールダウン ----
MAX = aw.GW_STUCK_STREAK_MAX
COOL = aw.GW_RESTART_COOLDOWN_SEC

# 0) 取りこぼし0は常にFalse・連続をリセットする(暇な夜を沈黙死と誤認しない)。
st = {"gw_stuck_streak": 5}
ok(aw._note_gateway_stuck(0, st, 1000.0) is False and st["gw_stuck_streak"] == 0,
   "取りこぼし0は再起動しない・連続をリセット")

# 1) 1件の取りこぼし1回では回さない(正規の再接続でも1件は起きる)。
st = {}
first = aw._note_gateway_stuck(3, st, 1000.0)
ok(first is False and st["gw_stuck_streak"] == 1,
   "取りこぼし単発では張り直さない(streak=1)")

# 2) ★核心= 閾値周期(既定2)連続で初めてTrue=張り直す。
res = False
st = {}
for i in range(MAX):
    res = aw._note_gateway_stuck(3, st, 1000.0 + i)
ok(res is True, f"{MAX}周期連続の取りこぼしで沈黙死と判定(True)")

# 3) 直後(クールダウン内)は判定してもFalse=暴走しない。
st = {}
for i in range(MAX):
    aw._note_gateway_stuck(3, st, 2000.0 + i)  # ここでTrue・gw_last_restart=2000+MAX-1
inside = aw._note_gateway_stuck(3, st, 2000.0 + MAX + 10)
ok(inside is False, "クールダウン内は再度の取りこぼしでも張り直さない")

# 4) クールダウン明けは再び回せる(直前に5000で張り直した状態から、窓明けに連続取りこぼし)。
after = {"gw_last_restart": 5000.0}
fired = False
base = 5000.0 + COOL + 1
for i in range(MAX):
    fired = aw._note_gateway_stuck(3, after, base + i)
ok(fired is True, "クールダウン明けは連続取りこぼしで再び張り直す")

# ---- 配線: check_relay_repair が2周期連続で _restart_stuck_gateway を1回だけ呼ぶ ----
calls = {"restart": 0}
orig_restart = aw._restart_stuck_gateway
orig_subrun = aw.subprocess.run


def fake_run(*a, **k):
    # relay_repair --repair の出力を差し替え(外へ出る手=subprocessだけ偽物化)。
    return types.SimpleNamespace(returncode=0, stdout="結果: 回収 3件 / 窓72h", stderr="")


aw.subprocess.run = fake_run
aw._restart_stuck_gateway = lambda state, now: calls.__setitem__("restart", calls["restart"] + 1)
try:
    state = {}
    t = 100000.0
    aw.check_relay_repair(state, dry_run=False, now_epoch=t)             # 1周期目=streak1
    ok(calls["restart"] == 0, "1周期目は張り直さない(配線)")
    t += aw.RELAY_REPAIR_GATE_SEC + 1                                    # ゲートを跨ぐ
    aw.check_relay_repair(state, dry_run=False, now_epoch=t)             # 2周期目=張り直す
    ok(calls["restart"] == 1, "2周期連続で _restart_stuck_gateway を1回だけ呼ぶ(配線)")
finally:
    aw.subprocess.run = orig_subrun
    aw._restart_stuck_gateway = orig_restart

# 7) 15分ゲート内の連呼はそもそも判定に入らない(Discord APIを殴らない=既存規律を壊さない)。
calls2 = {"n": 0}
aw.subprocess.run = fake_run
aw._restart_stuck_gateway = lambda state, now: calls2.__setitem__("n", calls2["n"] + 1)
try:
    state = {"last_relay_repair": 500000.0}
    aw.check_relay_repair(state, dry_run=False, now_epoch=500000.0 + 60)  # ゲート内=早期return
    ok(calls2["n"] == 0, "15分ゲート内は relay_repair も再起動判定も走らない")
finally:
    aw.subprocess.run = orig_subrun
    aw._restart_stuck_gateway = orig_restart

print(f"\n{P} PASS / {F} FAIL")
sys.exit(1 if F else 0)
