# -*- coding: utf-8 -*-
"""束ねた便への進捗印(既読✅/着手👀)の検査(2026-08-18 イージス研究室)。

塞いだ穴= REQ-aegis-gl-13fcea00f4「1528653749747191882 1番困る部類の出来事。反応がない。」
  handle() は**自分が受け取った1件**にしか印を押さない。連投は2経路で束ねられ、
  束ねられた側は handle() を通らない=**答えは返るのに、Chamiの画面では無印**。
  Chamiは最後に書いた便を見ているので、そこが無印だと「反応がない」に見える。
  実測(2026-08-18 23:02・`scripts/discord/audit_marks.py` で Discord を直読み)=
  直近48時間のChami便127件のうち生存の合図が無いのは5件、**全部この穴**だった。

この検査が固定する規則=
  ① 返す直前に掴んだ続きの便へ、**relayへ入る前に**印を押す(relayは中央値60秒=その間が無音だった)
  ② 押すのは (msg_id × 既読/着手) の全部で、**土台の便は押し直さない**(handle()が押している)
  ③ 検証便(test:true)とdry-runでは**Discordへ触らない**(本番の部屋でテストしない)
  ④ ★変異検査= 印を押す実装を無効化したら、この検査は**必ず落ちる**(空PASSでない証明)

★本物のセッションもDiscordも1度も呼ばない= 外へ出る手(subprocess)だけ偽物にし、
  判定と分岐(誰を束ねたか・押すかどうか)は本物のまま通す。

実行: python scripts/llm/test_bundle_marks.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
import dept_daemon as d           # noqa: E402
from leasequeue import LeaseQueue  # noqa: E402

PASS = 0
FAIL = 0


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
        """(msg_id, 印) の一覧へ畳む。"""
        out = []
        for c in self.calls:
            if "react.py" not in " ".join(c):
                continue
            m = c[c.index("--msg") + 1] if "--msg" in c else ""
            e = c[c.index("--emoji") + 1] if "--emoji" in c else ""
            out.append((m, e))
        return out


class _FakeRelay:
    def __init__(self, reply, ok=True):
        self.reply, self.ok = reply, ok
        self.calls, self.records = [], []
        self.marks_at_relay = None      # relayへ入った時点で押されていた印(順序の検査)

    def relay(self, dept, rec, conf, token, **kw):
        self.calls.append(rec)
        self.marks_at_relay = list(FAKE.marks())
        return self.reply, self.ok

    def _record(self, mid, dept, state, ev):
        self.records.append((mid, dept, state, ev))


def _body(mid, content, author="chami_fusoh", test=False):
    b = {"msg_id": mid, "author": author, "content": content,
         "channel": "タイトル文相談及び創造-三笘さん•芽衣"}
    if test:
        b["test"] = True
    return b


def _daemon(win=45, dept="copy-director"):
    dm = d.Daemon(dept)
    dm.conf = dict(dm.conf)
    dm.conf["coalesce_sec"] = win
    dm._post_coalesced, dm._post_coalesced_raw = [], []
    return dm


def _tmpdb():
    return os.path.join(tempfile.mkdtemp(prefix="marks_"), "inbox.db")


_orig_relay, _orig_sub = d.session_relay, d.subprocess
FAKE = _FakeSub()
d.subprocess = FAKE

print("[1] 返す直前に掴んだ続きの便へ、relayの前に印を押す")
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("c1", "続きの便だよ"), msg_id="c1", dept="copy-director")
q.enqueue(_body("c2", "もう1件"), msg_id="c2", dept="copy-director")
dm = _daemon()
dm._lease_q, dm._lease_qids = q, ["dummy"]
fake = _FakeRelay("束ね直した1本の返事" * 20)
d.session_relay = fake
FAKE.calls = []
dm._coalesce_after_run(_body("c0", "最初の便"), "c0", "最初の返事" * 20)
got = FAKE.marks()
check("掴んだ2件へ既読を押す", ("c1", "既読") in got and ("c2", "既読") in got)
check("掴んだ2件へ着手を押す", ("c1", "着手") in got and ("c2", "着手") in got)
check("土台の便は押し直さない(handle()が押している)", not any(m == "c0" for m, _ in got))
check("★relayへ入る前に押し終えている(60秒の無音を作らない)",
      fake.marks_at_relay is not None and len(fake.marks_at_relay) == 4)
check("正しい部屋へ押している",
      all("タイトル文相談及び創造-三笘さん•芽衣" in " ".join(c)
          for c in FAKE.calls if "react.py" in " ".join(c)))
q.close()

print("[2] 検証便(test:true)ではDiscordへ触らない(本番の部屋を汚さない)")
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("t1", "続き", test=True), msg_id="t1", dept="copy-director")
dm = _daemon()
dm._lease_q, dm._lease_qids = q, ["dummy"]
d.session_relay = _FakeRelay("束ね直した返事" * 20)
FAKE.calls = []
dm._coalesce_after_run(_body("t0", "本便", test=True), "t0", "元の返事" * 20)
check("検証便では1回も押さない", FAKE.marks() == [])
q.close()

print("[3] _mark_bundled 単体(dry-run/空入力/上限)")
dm = _daemon()
dm.dry_run = True
FAKE.calls = []
dm._mark_bundled("ch", ["x1"], "dry")
check("dry-runでは押さない", FAKE.marks() == [])
dm.dry_run = False
FAKE.calls = []
dm._mark_bundled("", ["x1"], "部屋不明")
check("部屋が分からなければ押さない", FAKE.marks() == [])
FAKE.calls = []
dm._mark_bundled("ch", [None, "", "  "], "空")
check("空のmsg_idは押さない", FAKE.marks() == [])
FAKE.calls = []
dm._mark_bundled("ch", ["a", "b"], "通常")
check("2件×2印=4回押す", len(FAKE.marks()) == 4)

print("[4] ★変異検査= 印の実装を無効化したら[1]は落ちる(空PASSでない証明)")
_keep = d.Daemon._mark_bundled
d.Daemon._mark_bundled = lambda self, ch, ids, why: None
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("m1", "続き"), msg_id="m1", dept="copy-director")
dm = _daemon()
dm._lease_q, dm._lease_qids = q, ["dummy"]
d.session_relay = _FakeRelay("束ね直した返事" * 20)
FAKE.calls = []
dm._coalesce_after_run(_body("m0", "本便"), "m0", "元の返事" * 20)
check("無効化すると印が0件になる(=[1]は本物の変化を見ている)", FAKE.marks() == [])
d.Daemon._mark_bundled = _keep
q.close()

d.session_relay, d.subprocess = _orig_relay, _orig_sub
print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
