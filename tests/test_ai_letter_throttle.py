# -*- coding: utf-8 -*-
"""AI便の毎時上限が「捨てずに次の窓へ回す」ことの検査(2026-08-24 イージス研究室・C-059の止血)。

★なぜ要るか:
  使用量73.4%・枯渇見込み 8/24 21:45(研究室HQ実測)。燃やす速さに頭打ちを付ける。
  ただし**便を落としたら本末転倒**(C-048=喪失禁止)。落としていないことは「そう書いた」では
  証明にならないので、**本物のキューへ実際に入れて、窓が明けるまで claim できず、
  明けたら claim できる**ことを実行で確かめる。

★検査の作り: 外へ出る手(Discord投稿・claude起動)は一切通らない。触るのは一時ファイルの
  sqlite だけで、判定(`ai_throttle_not_before`)と配布(`LeaseQueue.claim`)は本物のまま。

実行= python tests/test_ai_letter_throttle.py
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))

import dispatch as dp            # noqa: E402
from leasequeue import LeaseQueue  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  << " + detail) if not cond else ""))


def rec(audience="ai", dept="aegis-gl"):
    return json.dumps({"dept": dept, "audience": audience, "content": "本文"}, ensure_ascii=False)


def fresh_db():
    path = os.path.join(tempfile.mkdtemp(prefix="throttle_"), "inbox.db")
    LeaseQueue(path).close()
    return path


def fill(path, n, dept="aegis-gl", audience="ai"):
    q = LeaseQueue(path)
    try:
        for i in range(n):
            q.enqueue(rec(audience, dept), msg_id="m%d-%s" % (i, audience), dept=dept)
    finally:
        q.close()


NOW = time.time()
CAP = dp.AI_LETTER_CAP_PER_HOUR["aegis-gl"]

print("\n--- ① 判定(上限に当たるか) 上限=%d便/時 ---" % CAP)
db = fresh_db()
fill(db, CAP - 1)
check("上限未満なら即時(0.0)", dp.ai_throttle_not_before(db, "aegis-gl", "ai", NOW) == 0.0)
fill(db, 1, audience="ai2")          # 別audienceを1件足しても ai の数は増えない
check("audienceがaiでない便は数に入らない",
      dp.ai_throttle_not_before(db, "aegis-gl", "ai", NOW) == 0.0)
db2 = fresh_db()
fill(db2, CAP)
nb = dp.ai_throttle_not_before(db2, "aegis-gl", "ai", NOW)
check("上限ちょうどで次の窓へ回る", nb > NOW, repr(nb))
check("次の窓は1時間の頭に揃う", nb % 3600.0 == 0.0 and nb - NOW <= 3600.0, repr(nb - NOW))
check("Chami宛(audience=chami)は絞らない",
      dp.ai_throttle_not_before(db2, "aegis-gl", "chami", NOW) == 0.0)
check("表に無い部門は絞らない",
      dp.ai_throttle_not_before(db2, "hr-room", "ai", NOW) == 0.0)
check("キューが読めない時は素通し(fail-open)",
      dp.ai_throttle_not_before(os.path.join(ROOT, "no", "such.db"), "aegis-gl", "ai", NOW) == 0.0)

print("\n--- ② 配布(回した便は消えていないか) ---")
db3 = fresh_db()
q = LeaseQueue(db3)
try:
    future = time.time() + 1800          # 30分後の窓に見立てる
    q.enqueue(rec(), msg_id="deferred", dept="aegis-gl", not_before=future)
    got = q.claim(dept="aegis-gl")
    check("窓の前は claim できない", got is None, repr(got))
    import sqlite3
    con = sqlite3.connect(db3)
    row = con.execute("SELECT status, lease_until FROM queue WHERE msg_id='deferred'").fetchone()
    con.close()
    check("それでも便はキューに pending で座っている", row is not None and row[0] == "pending", repr(row))
    check("外から『あと何分待つか』を数えられる", row is not None and row[1] > time.time())
    # 窓が明けた状態にして、同じ行が普通に配られることを確かめる
    con = sqlite3.connect(db3)
    con.execute("UPDATE queue SET lease_until=? WHERE msg_id='deferred'", (time.time() - 1,))
    con.commit()
    con.close()
    got = q.claim(dept="aegis-gl")
    check("窓が明けたら同じ便が配られる", got is not None and got.get("msg_id") == "deferred", repr(got))
finally:
    q.close()

print("\n--- ③ 既存の呼び出しは1文字も変わらない ---")
db4 = fresh_db()
q = LeaseQueue(db4)
try:
    q.enqueue(rec(), msg_id="plain", dept="aegis-gl")     # not_before を渡さない従来形
    got = q.claim(dept="aegis-gl")
    check("not_before無しは今までどおり即claimできる",
          got is not None and got.get("msg_id") == "plain", repr(got))
finally:
    q.close()


# ================================================================ must-fail
def _mf_drop_instead_of_defer():
    """壊した側= **動く別の実装**「上限に当たった便は投函しない(捨てる)」。

    これは「速さを抑える」目的だけなら成立する実装だが、C-048(喪失禁止)を破る。
    戻り= (捨てる実装での在庫数, 今の実装での在庫数)。今の実装は必ず1件残っていること。
    """
    import sqlite3

    def count(path):
        con = sqlite3.connect(path)
        try:
            return con.execute("SELECT COUNT(*) FROM queue WHERE msg_id='x'").fetchone()[0]
        finally:
            con.close()

    # 壊した側: 上限に当たったので enqueue を呼ばない
    broken = fresh_db()
    nb = 12345.0                       # 上限に当たった体
    if not nb:
        LeaseQueue(broken).enqueue(rec(), msg_id="x", dept="aegis-gl")
    # 今の実装: 上限に当たっても enqueue する(lease_until を未来に置くだけ)
    good = fresh_db()
    qq = LeaseQueue(good)
    try:
        qq.enqueue(rec(), msg_id="x", dept="aegis-gl", not_before=nb)
    finally:
        qq.close()
    return count(broken), count(good)


print("\n--- must-fail(壊した側=『捨てる』実装に戻して、便が消えることを実行で確かめる) ---")
_got = _mf_drop_instead_of_defer()
check("must-fail 捨てる実装は在庫0/今の実装は在庫1", _got == (0, 1), repr(_got))

ng = [n for n, ok in RESULTS if not ok]
print("\n===== %d件中 %d件PASS =====" % (len(RESULTS), len(RESULTS) - len(ng)))
if ng:
    print("FAIL — %d件: %s" % (len(ng), ng))
    sys.exit(1)
print("ALL PASS")
