# -*- coding: utf-8 -*-
"""replied_recheck の『不着を請けた部門へ鳴らす』止血の回帰テスト。

★なぜ本物の送信経路を差し替えてまで通すか=
  「発火しない安全網は検証されない」。登録しただけの通知は、鳴らないまま何ヶ月も
  正しいふりをする。だからここでは **notify の枝を実際に通す**。差し替えるのは
  dispatch.py を叩く最後の一手(subprocess.run)だけで、宛先の決定・本文の組み立て・
  台帳への冪等記帳は**本物のコード**を走らせる。

★must-fail(C-053)= D-1/D-2。壊し方は構文破壊ではなく、
  「通知を呼ばない main」「台帳より先に鳴らす main」という**動く別実装**を食わせて、
  検査が赤くなることを確かめる。赤くならない検査は検査ではない。

  python scripts/_daemons/test_replied_missing_notify.py
"""
import ast
import io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replied_recheck as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "scripts", "_daemons", "replied_recheck.py")

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))


class Stub:
    """dispatch.py の代わり。呼ばれた引数を全部覚える。"""

    def __init__(self, rc=0, boom=False):
        self.rc, self.boom, self.calls = rc, boom, []

    def __call__(self, argv, **kw):
        if self.boom:
            raise OSError("stubbed send failure")
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.rc, stdout="", stderr="")

    def arg(self, i, flag):
        av = self.calls[i]
        return av[av.index(flag) + 1] if flag in av else None

    def body(self, i):
        p = self.arg(i, "--body-file")
        with open(p, encoding="utf-8") as f:
            return f.read()


def run_notify(rows, rc=0, boom=False, dry_run=False, processed=None, head=None):
    """本物の notify_missing を、台帳・送信口・部門長判定だけ差し替えて通す。

    ★部門長判定を差し替えるのは Discord API を叩くからで、宛先の決定そのものは本物。
    """
    stub = Stub(rc=rc, boom=boom)
    tmp = tempfile.mkdtemp(prefix="misslog_")
    log = os.path.join(tmp, "request_log.jsonl")
    proc = os.path.join(tmp, "processed.jsonl")
    with open(proc, "w", encoding="utf-8") as f:
        for r in (processed or []):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    keep = (R.REQUEST_LOG, R.PROCESSED, R.LOCAL, subprocess.run, R.head_of)
    R.REQUEST_LOG, R.PROCESSED, R.LOCAL = log, proc, tmp
    R.head_of = lambda d: head
    subprocess.run = stub
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        done = R.notify_missing(rows, dry_run=dry_run)
    finally:
        sys.stdout = old
        R.REQUEST_LOG, R.PROCESSED, R.LOCAL, subprocess.run, R.head_of = keep
    written = []
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            written = [json.loads(x) for x in f if x.strip()]
    return stub, done, written, buf.getvalue()


ROW = {"ts": "2026-09-05T12:14:56", "request_id": "1545622548035928146",
       "dept": "system-engineer", "state": "replied_missing",
       "evidence": "後追いでも見つからない(全22室×最大500件走査) ★これは本物の不着"}

print("== A 実物: 宛先は請けた部門・発注元は元の便から引く ==")
stub, done, written, _ = run_notify(
    [ROW], processed=[{"msg_id": "1545622548035928146", "author": "chami_fusoh",
                       "from_dept": None, "channel": "5chシステム改修部門α-se-オタコン•咲季"}])
ok("A-1 送信は1件だけ", len(stub.calls) == 1, f"実測={len(stub.calls)}")
ok("A-2 部門長がいなければ宛先=請けた部門", stub.arg(0, "--dept") == "system-engineer",
   str(stub.arg(0, "--dept")))
ok("A-3 発注元(hq)を名乗る", stub.arg(0, "--from-dept") == "hq")
ok("A-4 AI宛て宣言(C-050)", stub.arg(0, "--audience") == "ai")
ok("A-5 実依頼なので表投稿(C-023)", "--work" in stub.calls[0])
body = stub.body(0)
ok("A-6 本文に request_id", "1545622548035928146" in body)
ok("A-7 人発の便だと本文で分かる", "chami_fusoh" in body and "人発" in body, body.split("\n")[2])
ok("A-8 元の部屋を本文に載せる", "5chシステム改修部門α" in body)
ok("A-9 根拠(判定文)を落とさない", "本物の不着" in body)

print("\n== B 冪等: 通知した事実だけを追記する ==")
ok("B-1 missing_notified を1行", len(written) == 1 and written[0]["state"] == "missing_notified",
   str([w.get("state") for w in written]))
ok("B-2 request_id を保つ", written and written[0]["request_id"] == ROW["request_id"])
ok("B-3 既存の replied_missing 行は書き換えない",
   all(w["state"] != "replied_missing" for w in written))
ok("B-4 返り値と記帳が一致", len(done) == len(written))
ok("B-5 二度目は RESOLVED で弾かれる=判定自体が再走しない",
   "replied_missing" in R.RESOLVED)

print("\n== C 失敗しても台帳を汚さない・落ちない ==")
stub, done, written, out = run_notify([ROW], rc=1,
                                      processed=[{"msg_id": "x", "author": "a"}])
ok("C-1 送信失敗なら通知済みにしない", written == [] and done == [], str(written))
ok("C-2 失敗はログに出る", "[通知失敗]" in out, out.strip()[:60])
stub, done, written, out = run_notify([ROW], boom=True)
ok("C-3 例外でも落ちない(fail-open)", done == [], str(done))
ok("C-4 例外もログに出る", "OSError" in out, out.strip()[:60])
_s, _d, _w, out = run_notify([{"ts": "t", "request_id": "r", "dept": "", "evidence": ""}])
ok("C-5 請けた部門が無い行は送らず記録する", _s.calls == [] and "[通知不能]" in out)
_s, _d, _w, out = run_notify([ROW], dry_run=True)
ok("C-6 --dry-run では1通も出ない", _s.calls == [] and _w == [] and "dry-run" in out)
ok("C-7 空リストなら何もしない", run_notify([])[0].calls == [])

print("\n== E 3階梯: 部門長がいるなら部門長へ渡す(直接出すと dispatch に弾かれる) ==")
stub, done, written, _ = run_notify([ROW], head="research-room",
                                    processed=[{"msg_id": ROW["request_id"],
                                                "author": "chami_fusoh", "from_dept": None,
                                                "channel": "5chシステム改修部門α-se-オタコン•咲季"}])
ok("E-1 宛先=部門長", stub.arg(0, "--dept") == "research-room", str(stub.arg(0, "--dept")))
b = stub.body(0)
ok("E-2 誰の返信かを本文で名指す", "system-engineer" in b)
ok("E-3 手渡しを頼む一行が入る", "3階梯" in b and "手渡し" in b)
ok("E-4 台帳には請けた部門と宛先の両方", written and written[0]["dept"] == "system-engineer"
   and "to_dept=research-room" in written[0]["evidence"], str(written and written[0]["evidence"]))
ok("E-5 --work の要約にも請けた部門", "system-engineer" in (stub.arg(0, "--work") or ""))

print("\n== F 実物の記帳から発注元を引けるか(本番の discord_processed) ==")
real = R.letters_of(["1545622548035928146"]).get("1545622548035928146") or {}
ok("F-1 実物の便を引けた", bool(real), str(real)[:80])
ok("F-2 Chami本人の便=from_dept が空", real.get("from_dept") == "", repr(real.get("from_dept")))
ok("F-3 author が残っている", bool(real.get("author")), str(real.get("author")))

print("\n== D 配線: main が『台帳へ書いた後に』鳴らすこと(must-fail付き) ==")


def wired(src):
    """main() の中で、台帳追記より後に notify_missing を呼んでいるか。"""
    fn = next((n for n in ast.parse(src).body
               if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    if fn is None:
        return False
    writes = [n.lineno for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "write"]
    calls = [n.lineno for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "notify_missing"]
    real = [c for c in calls if c > min(writes or [10 ** 9])]
    return bool(writes) and bool(real)


real_src = open(SRC, encoding="utf-8").read()
ok("D-0 実物の main は配線済み", wired(real_src))
BROKEN_1 = ("def main():\n"
            "    out = []\n"
            "    with open(REQUEST_LOG, 'a') as f:\n"
            "        f.write('x')\n"
            "    return 0\n")
BROKEN_2 = ("def main():\n"
            "    out = []\n"
            "    notify_missing(out)\n"
            "    with open(REQUEST_LOG, 'a') as f:\n"
            "        f.write('x')\n"
            "    return 0\n")
ok("D-1 must-fail: 鳴らさない main を赤にできる", wired(BROKEN_1) is False)
ok("D-2 must-fail: 台帳より先に鳴らす main を赤にできる", wired(BROKEN_2) is False)
ok("D-3 --no-notify の逃げ道がある", '"--no-notify"' in real_src)

print(f"\n== {len(PASS)} PASS / {len(FAIL)} FAIL ==")
if FAIL:
    for n in FAIL:
        print("  ! " + n)
sys.exit(1 if FAIL else 0)
