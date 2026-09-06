#!/usr/bin/env python3
"""test_quota_alarm_rearm — 見張りの「再武装(rearm)」の判定を、**実行で**通す検査。

★共通規律§3= ソースの文字列一致は検査ではない。**判定と分岐は本物のまま回し、外へ出る手だけ偽物にする**。
  ここで偽物にするのは3つだけ:
    ・`window_total`   = 課金台帳の読み(入力を差し替えるため)
    ・`subprocess.run` = dispatch.py の起動(= 外へ出る手)
    ・`datetime.now`   = 時計
  reasons の組み立て・rearm の3条件・quiet-hours・台帳への書き込みは**本物のコード**が走る。

★材料は実物だ= `local/llm/quota_burn.jsonl` の 2026-09-05〜09-07(14巡回すべて alarm=True・
  累計比 2.43→3.97→3.06 で一度も 1.30 を割らず、同時刻の直近6時間は 0.30倍= 鎮火済み)。

  python scripts/llm/test_quota_alarm_rearm.py
"""
import json
import os
import shutil
import sys
import tempfile
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# watch_triggers は課金の見張りとは無関係の相乗り。検査では動かさない(本物は try/except で守られている)
sys.modules.setdefault("watch_triggers", types.ModuleType("watch_triggers"))
sys.modules["watch_triggers"].run = lambda dry=False: None
sys.modules["watch_triggers"].SEND_DRY = False


def load(modname, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(modname, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


class Scenario:
    """1回の巡回を丸ごと作る。cum_*/rate_* は『重み付き換算, 便数』。"""

    def __init__(self, mod, now, week_start, cum, prev_cum, rate, prev_rate):
        self.mod, self.now, self.week_start = mod, now, week_start
        self.cum, self.prev_cum, self.rate, self.prev_rate = cum, prev_cum, rate, prev_rate
        self.sent = []

    def install(self, tmp, rate_window=6.0):
        m = self.mod
        now, ws = self.now, self.week_start
        prev_ws = ws - timedelta(days=7)
        elapsed = (now - ws).total_seconds() / 3600.0
        keys = {
            (ws, now): self.cum,
            (prev_ws, prev_ws + timedelta(hours=elapsed)): self.prev_cum,
            (prev_ws, ws): self.prev_cum,
            (now - timedelta(hours=rate_window), now): self.rate,
            (now - timedelta(days=7) - timedelta(hours=rate_window),
             now - timedelta(days=7)): self.prev_rate,
        }

        def window_total(start, end):
            v = keys.get((start, end))
            if v is None:
                raise AssertionError("検査が想定していない窓が引かれた: %s 〜 %s" % (start, end))
            return v

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        m.window_total = window_total
        m.by_dept = lambda s, e, top=5: [("aegis-gl", 41.0)]
        m.datetime = FakeDT
        m.qb.last_reset = lambda n: ws
        m.STAMP = os.path.join(tmp, "_stamp.json")
        m.LEDGER = os.path.join(tmp, "llm", "quota_burn.jsonl")
        m.CALIB = os.path.join(tmp, "_calib.json")
        m.LOCAL = tmp

        sent = self.sent

        def fake_run(cmd, **kw):
            sent.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        m.subprocess.run = fake_run
        return m

    def run(self, tmp, argv=()):
        m = self.install(tmp)
        old = sys.argv
        sys.argv = ["quota_alarm.py"] + list(argv)
        try:
            m.main()
        finally:
            sys.argv = old
        return len(self.sent) > 0


JST = None
FAIL = []


def check(name, got, want):
    ok = got == want
    print("  %s %s (投函= %s / 期待= %s)" % ("PASS" if ok else "**FAIL**", name, got, want))
    if not ok:
        FAIL.append(name)


def stamp(path, ts, week_start, weighted, kinds):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ts": ts.isoformat(), "week_start": week_start.isoformat(),
                   "weighted": weighted, "kinds": kinds, "reasons": ["x"]}, f)


def suite(mod, label):
    global JST
    JST = mod.JST
    ws = datetime(2026, 9, 5, 3, 0, tzinfo=JST)
    now = datetime(2026, 9, 7, 4, 0, tzinfo=JST)
    # 実物の形= 累計は 3.06倍(345.6M / 113.1M)だが、直近6時間は 0.30倍で鎮火済み
    burst = dict(cum=(345621606.0, 7247), prev_cum=(113108670.0, 2290),
                 rate=(3141988.0, 72), prev_rate=(10442891.0, 238))
    print("\n== %s ==" % label)
    r = []

    def one(name, want, mutate=None, argv=(), st=None):
        tmp = tempfile.mkdtemp()
        try:
            kw = dict(burst)
            if mutate:
                kw.update(mutate)
            s = Scenario(mod, kw.pop("now", now), kw.pop("ws", ws), **kw)
            if st:
                os.makedirs(tmp, exist_ok=True)
                stamp(os.path.join(tmp, "_stamp.json"), *st)
            got = s.run(tmp, argv)
            check(name, got, want)
            r.append((name, got))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # T1 ★本命= 昨日と同じ話(週も同じ・今は鎮火・累計も伸びていない)→ 鳴らし直さない
    one("T1 burst済み+前回26時間前+同じ週+同じ理由 → 黙る", False,
        st=(now - timedelta(hours=26), ws, 340000000, ["cumulative"]))
    # T2 今も速い(直近6時間が閾値超え)→ 打てる手が効く場面なので必ず鳴る
    one("T2 今も速い(rate 2.0倍) → 鳴る", True,
        mutate=dict(rate=(20885782.0, 400)),
        st=(now - timedelta(hours=26), ws, 340000000, ["cumulative"]))
    # T3 累計が前回の警報から1.30倍まで伸びた → 話が変わったので鳴る
    one("T3 累計が前回比1.30倍へ伸びた → 鳴る", True,
        st=(now - timedelta(hours=26), ws, 200000000, ["cumulative"]))
    # T4 週が替わった(前回の警報は先週の話)→ 鳴る
    one("T4 週が替わった → 鳴る", True,
        st=(now - timedelta(hours=26), ws - timedelta(days=7), 340000000, ["cumulative"]))
    # T5 quiet-hours の下限は残っている
    one("T5 前回2時間前 → quiet-hours で黙る", False,
        st=(now - timedelta(hours=2), ws, 100, ["cumulative"]))
    # T6 そもそも閾値を超えていない → 鳴らない
    one("T6 累計も今の速さも閾値未満 → 鳴らない", False,
        mutate=dict(cum=(100000000.0, 2000)),
        st=(now - timedelta(hours=26), ws, 340000000, ["cumulative"]))
    # T7 前回の記録が無い(初回)→ 鳴る
    one("T7 stamp が無い(初回) → 鳴る", True)
    return r


def main():
    real = load("qa_real", os.path.join(HERE, "quota_alarm.py"))
    suite(real, "本物 scripts/llm/quota_alarm.py")

    # ★must-fail(C-053)= **壊した側は本物と同じディレクトリへ置く**(ROOT解決が変わると偽の緑が出る)。
    #   rearm を消して時計だけに戻した実装では、T1 が**鳴ってしまう**= 赤くなること自体が正しい。
    mut = os.path.join(HERE, "_mutant_quota_alarm_norearm.py")
    src = open(os.path.join(HERE, "quota_alarm.py"), encoding="utf-8").read()
    old = "        elif last.get(\"week_start\") == start.isoformat():"
    assert old in src, "変異点が見つからない= 本物の構造が変わっている。検査を直せ"
    mutant_src = src.replace(old, "        elif False:")
    with open(mut, "w", encoding="utf-8") as f:
        f.write(mutant_src)
    try:
        m = load("qa_mut", mut)
        print("\n== ★must-fail: rearm を消した変異体(T1 が鳴れば検査は生きている) ==")
        tmp = tempfile.mkdtemp()
        try:
            ws = datetime(2026, 9, 5, 3, 0, tzinfo=m.JST)
            now = datetime(2026, 9, 7, 4, 0, tzinfo=m.JST)
            s = Scenario(m, now, ws, cum=(345621606.0, 7247), prev_cum=(113108670.0, 2290),
                         rate=(3141988.0, 72), prev_rate=(10442891.0, 238))
            stamp(os.path.join(tmp, "_stamp.json"), now - timedelta(hours=26), ws,
                  340000000, ["cumulative"])
            got = s.run(tmp)
            ok = got is True
            print("  %s 変異体の T1 は鳴った= %s(期待 True)"
                  % ("PASS" if ok else "**FAIL**", got))
            if not ok:
                FAIL.append("must-fail 変異体が鳴らなかった= 検査が弱い")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        if os.path.exists(mut):
            os.remove(mut)

    print("\n==== %s ====" % ("全部PASS" if not FAIL else "FAIL %d件: %s" % (len(FAIL), FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
