# -*- coding: utf-8 -*-
"""走行中の既読(live mark)の検査(2026-09-03 イージス研究室・発注= 研究室HQ)。

塞いだ穴= Chami msg 1545000257274773574
  「1件処理完了するまで次の便が読まれないので、何か挿入、補足したくても処理が
    終わってから補足を読むという非効率なことを解消したい」
  `coalesce_sec`(返す直前の覗き)で**補足はその便の返事に合流する**ようになったが、
  合流するのは本走が終わってからだ= 重い便が10分走れば、開始10秒後に書いた補足は
  10分間**無印のまま画面に残る**= Chamiには「読まれていない」に見える。

この検査が固定する規則=
  ① 本走の最中に届いたChamiの便へ、**走り終わるのを待たずに**既読を押す
  ② 押すのは既読だけ(着手は「いまそれをやっている」の意味= `_mark_bundled` が後で押す)
  ③ ★★**claimしない**= 覗いた便は pending のまま残る(ドレインの窓 INC-100 を作らない)
  ④ 他部門の便・別の部屋・検証便には押さない/同じ便を二度は狙わない
  ⑤ 止める合図で確実に止まる(次の便の処理中に前の見張りが押し続けない)
  ⑥ `live_mark_sec` を持たない部屋では見張りそのものが立たない(C-035・他30室は1バイト差なし)
  ⑦ ★変異検査= 押す実装を無効化したら①は必ず落ちる(空PASSでない証明)

★Discordもセッションも1度も呼ばない= 外へ出る手(subprocess)だけ偽物にし、
  覗く先は**本物の LeaseQueue**(一時DB)を使う=判定と並行動作は本物のまま通す。

実行: python scripts/llm/test_live_mark.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
import dept_daemon as d           # noqa: E402
from leasequeue import LeaseQueue  # noqa: E402

PASS = 0
FAIL = 0
CH = "研究室HQコーチングルーム"
TICK = 0.2                        # 検査用の覗き間隔(本番は20秒)
# ★2026-09-06(aegis-gl)検体の msg_id を `1545000000000000001` 形式へ揃えた。
#   旧検体は "m0" "a4" のような短い符丁で、**本番に存在しない形**だった。
#   `_live_mark_loop` が「Discordのmessage IDでない便(配達ID)には押さない」を持ったので、
#   符丁のままでは全部が弾かれて検査が空PASSになる= 検体を実物の形へ寄せた。
#   下の [7] が、その弾く側を測っている。


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL += 1
        print("  NG  %s" % name)


class _Proc:
    returncode = 0


class _FakeSub:
    """dept_daemon から見える `subprocess` の差し替え(react.py を実際には起動しない)。"""

    def __init__(self):
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append(list(cmd))
        return _Proc()

    def marks(self):
        out = []
        for c in self.calls:
            if "react.py" not in " ".join(c):
                continue
            m = c[c.index("--msg") + 1] if "--msg" in c else ""
            e = c[c.index("--emoji") + 1] if "--emoji" in c else ""
            out.append((m, e))
        return out


def _body(mid, content="補足だけど", author="chami_fusoh", ch=CH, test=False, dept=None):
    b = {"msg_id": mid, "author": author, "content": content, "channel": ch}
    if test:
        b["test"] = True
    if dept:
        b["dept"] = dept        # ★2026-09-16 「生成依頼」便の判定が部屋の札を見るので足せる形に
    return b


def _daemon(win=TICK, dept="hq"):
    dm = d.Daemon(dept)
    dm.conf = dict(dm.conf)
    dm.conf["live_mark_sec"] = win
    dm.dry_run = False
    return dm


def _q():
    """本物の LeaseQueue を一時の LOCAL 配下に置く(見張りは LOCAL/queue/inbox.db を見る)。"""
    loc = tempfile.mkdtemp(prefix="livemark_")
    d.LOCAL = loc
    return LeaseQueue(os.path.join(loc, "queue", "inbox.db"))


def _until(fn, sec=4.0):
    """条件が満たされるまで待つ(最大sec秒)。時間で決め打ちしない=遅いPCで揺れない。"""
    t0 = time.time()
    while time.time() - t0 < sec:
        if fn():
            return True
        time.sleep(0.05)
    return False


_orig_sub, _orig_local = d.subprocess, d.LOCAL
FAKE = _FakeSub()
d.subprocess = FAKE

print("[1] 本走の最中に届いたChamiの便へ、走り終わるのを待たずに既読を押す")
q = _q()
dm = _daemon()
FAKE.calls = []
stop = dm._start_live_mark(_body("1545000000000000001", "本便"))          # ← 本走が始まった(土台の便=m0)
check("見張りが立つ", stop is not None)
q.enqueue(_body("1545000000000000002", "やっぱりこうして"), msg_id="1545000000000000002", dept="hq")   # 走行中に届いた補足
got = _until(lambda: ("1545000000000000002", "既読") in FAKE.marks())
check("★走行中(本走を止めていない)に既読が付いた", got)
check("着手は押さない(まだ着手していない・_mark_bundledが後で押す)",
      not any(m == "1545000000000000002" and e == "着手" for m, e in FAKE.marks()))
check("土台の便は押し直さない(handle()が押している)",
      not any(m == "1545000000000000001" for m, _ in FAKE.marks()))
check("★claimしていない= 便はpendingのまま残る(ドレインの窓を作らない)",
      [r["msg_id"] for r in q.peek_ready(dept="hq")] == ["1545000000000000002"])
n1 = len(FAKE.marks())
time.sleep(TICK * 3)
check("同じ便を二度は狙わない", len(FAKE.marks()) == n1)
stop.set()
q.close()

print("[2] 他部門の便・別の部屋・検証便には押さない")
q = _q()
dm = _daemon()
FAKE.calls = []
stop = dm._start_live_mark(_body("1545000000000000003", "本便"))
q.enqueue(_body("1545000000000000004", "AIの便", author="シャビ・アロンソ"), msg_id="1545000000000000004", dept="hq")
q.enqueue(_body("1545000000000000005", "別の部屋", ch="ad研究室"), msg_id="1545000000000000005", dept="hq")
q.enqueue(_body("1545000000000000006", "検証便", test=True), msg_id="1545000000000000006", dept="hq")
q.enqueue(_body("1545000000000000007", "これは押す"), msg_id="1545000000000000007", dept="hq")
got = _until(lambda: ("1545000000000000007", "既読") in FAKE.marks())
check("Chamiの便には押す(この検査が空でない証明)", got)
check("他部門(AI)の便には押さない", not any(m == "1545000000000000004" for m, _ in FAKE.marks()))
check("別の部屋の便には押さない", not any(m == "1545000000000000005" for m, _ in FAKE.marks()))
check("検証便には押さない(本番の部屋を汚さない)", not any(m == "1545000000000000006" for m, _ in FAKE.marks()))
stop.set()
q.close()

# ★2026-09-16 Chami直令(hq msg 1549650439178428447)=「生成依頼 から始まった時は画像生成
#   だから、Claud送信用の各種スタンプを押さないで」。走行中の既読もその口の1つ(C-064)。
#   LoRA部屋の絵を描くのは優依のローカル経路= Claudeの印は「乗っていない経路に乗った」嘘になる。
print("[2b] 「生成依頼」便には走行中の既読も押さない")
_IMG = "imagegen-fusoh-v0"
q = _q()
dm = _daemon(dept=_IMG)
FAKE.calls = []
stop = dm._start_live_mark(_body("1545000000000000101", "本便", dept=_IMG))
q.enqueue(_body("1545000000000000102", "生成依頼 銀髪ロング 制服", dept=_IMG),
          msg_id="1545000000000000102", dept=_IMG)
q.enqueue(_body("1545000000000000103", "この絵いいね", dept=_IMG),
          msg_id="1545000000000000103", dept=_IMG)
got = _until(lambda: ("1545000000000000103", "既読") in FAKE.marks())
check("同じ部屋の雑談には押す(この検査が空でない証明)", got)
check("★「生成依頼」で始まる便には押さない",
      not any(m == "1545000000000000102" for m, _ in FAKE.marks()))
stop.set()
q.close()

print("[3] 止める合図で確実に止まる(次の便へ持ち越さない)")
q = _q()
dm = _daemon()
FAKE.calls = []
stop = dm._start_live_mark(_body("1545000000000000008", "本便"))
stop.set()
time.sleep(TICK * 2)
q.enqueue(_body("1545000000000000009", "止めた後に来た便"), msg_id="1545000000000000009", dept="hq")
time.sleep(TICK * 4)
check("止めた後は1回も押さない", FAKE.marks() == [])
q.close()

print("[4] 立てない条件(C-035・他30室は1バイト差なし)")
dm = _daemon(win=0)
check("live_mark_secが無い部屋では見張りが立たない", dm._start_live_mark(_body("1545000000000000010")) is None)
dm = _daemon()
dm.dry_run = True
check("dry-runでは立たない", dm._start_live_mark(_body("1545000000000000011")) is None)
dm = _daemon()
check("検証便では立たない", dm._start_live_mark(_body("1545000000000000012", test=True)) is None)
dm = _daemon()
check("部屋が分からなければ立たない", dm._start_live_mark(_body("1545000000000000013", ch="")) is None)

print("[5] 受信箱が読めなくても本走を巻き込まない(fail-open)")
q = _q()
dm = _daemon()
d.LOCAL = os.path.join(tempfile.mkdtemp(prefix="livemark_none_"), "無い")   # DBが無い場所
FAKE.calls = []
stop = dm._start_live_mark(_body("1545000000000000014", "本便"))
time.sleep(TICK * 3)
check("見張りは落ちずに黙っている(印は0件)", FAKE.marks() == [])
stop.set()
q.close()

print("[6] ★変異検査= 押す実装を無効化したら[1]は落ちる(空PASSでない証明)")
_keep = d.subprocess.run
d.subprocess.run = lambda cmd, **kw: _Proc()        # 呼ばれても記録しない=押した痕跡が消える
q = _q()
dm = _daemon()
FAKE.calls = []
stop = dm._start_live_mark(_body("1545000000000000015", "本便"))
q.enqueue(_body("1545000000000000016", "補足"), msg_id="1545000000000000016", dept="hq")
time.sleep(TICK * 4)
check("無効化すると印が0件になる(=[1]は本物の変化を見ている)", FAKE.marks() == [])
stop.set()
d.subprocess.run = _keep
q.close()

print("[7] ★Discordのmessage IDでない便(配達ID)には押さない")
#   実測(2026-09-06・全 dept_daemon_*.log)= 押した36件のうち1件だけ rc=1 で、その msg_id が
#   `ESC-hr-context-1545568554550689962` だった。転送・上申の便は `_is_from_chami` が真を
#   返すが、この ID は Discord に存在しない=react.py が必ず失敗する。
ESC = "ESC-hr-context-1545568554550689962"
q = _q()
dm = _daemon()
FAKE.calls = []
stop = dm._start_live_mark(_body("1545000000000000017", "本便"))
q.enqueue(_body(ESC, "上申の転送"), msg_id=ESC, dept="hq")
q.enqueue(_body("1545000000000000018", "これは押す"), msg_id="1545000000000000018", dept="hq")
got = _until(lambda: ("1545000000000000018", "既読") in FAKE.marks())
check("数字のmsg_idには押す(この検査が空PASSでない証明の対)", got)
check("★配達ID(ESC-...)には押さない= 失敗すると分かっている口を叩かない",
      not any(m == ESC for m, _ in FAKE.marks()))
check("弾いても本走は巻き込まない(見張りは生きている)", not stop.is_set())
stop.set()
q.close()

d.subprocess, d.LOCAL = _orig_sub, _orig_local
print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
