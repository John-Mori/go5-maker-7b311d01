# -*- coding: utf-8 -*-
"""受信側の集約窓(coalesce)のテスト(2026-08-08 イージス研究室)。

発注= 研究室HQ 8/4 07:29(msg_id 1533964982201356308)/ Chamiの依頼便= 1533963726984581251。
仕様= コピー部門の部屋で、Chamiが推敲を小分けに連投した時、断片ごとに走らせず、
      連投が落ち着いてから溜めた分を全部込みで**1回**返す。

★ここで固めるのは「取りこぼさないこと」= 便が消えない・二重に応答しない・他室に効かない。
  実物確認(実際に部屋へ連投して1本返る)は §4.55 に従って別途・Discordで取る。
"""
import json
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


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL += 1
        print("  NG  %s" % name)


def _tmpdb():
    return os.path.join(tempfile.mkdtemp(prefix="coalesce_"), "inbox.db")


def _body(mid, content, author="chami_fusoh"):
    return {"msg_id": mid, "author": author, "content": content, "test": True}


def _daemon(dept="copy-director", win=None):
    dm = d.Daemon(dept)
    if win is not None:
        dm.conf = dict(dm.conf)
        dm.conf["coalesce_sec"] = win
    return dm


# ============ 1) peek_ready は覗くだけ(リースも配達回数も触らない) ============
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("m1", "あ"), msg_id="m1", dept="copy-director")
q.enqueue(_body("m2", "い"), msg_id="m2", dept="copy-director")
rows = q.peek_ready(dept="copy-director")
check("peek_ready が未処理2件を返す", len(rows) == 2)
check("peek_ready の body は dict へ復元される", isinstance(rows[0]["body"], dict))
check("peek_ready は enqueued_at を返す", rows[0]["enqueued_at"] > 0)
after = q.peek_ready(dept="copy-director")
check("覗いても件数が減らない(claimしていない)", len(after) == 2)
c = q.claim(dept="copy-director", who="t")
check("覗いた後も普通に claim できる", c is not None and c["deliveries"] == 1)
check("配達回数を焼いていない(覗いただけでは増えない)", c["deliveries"] == 1)
check("peek_ready は他部門の便を返さない", q.peek_ready(dept="hq") == [])
q.close()

# ============ 2) 窓の判定 ============
db = _tmpdb()
q = LeaseQueue(db)
dm = _daemon(win=45)
q.enqueue(_body("c1", "この文どう思う"), msg_id="c1", dept="copy-director")
check("Chamiの便が来た直後は待つ(連投中とみなす)", dm._coalesce_hold(q) is True)

# 窓を過ぎた状態を作る= enqueued_at を過去へずらす
q._db.execute("UPDATE queue SET enqueued_at = enqueued_at - 60")
q._db.commit()
check("最後の便から窓(45秒)を過ぎたら待たない", dm._coalesce_hold(q) is False)

# 上限= 連投が止まらなくても走る
q._db.execute("UPDATE queue SET enqueued_at = ?", (time.time() - d.COALESCE_MAX_SEC - 1,))
q.enqueue(_body("c2", "まだ続く"), msg_id="c2", dept="copy-director")
q._db.commit()
check("上限(%d秒)を過ぎたら連投中でも走る" % d.COALESCE_MAX_SEC,
      dm._coalesce_hold(q) is False)
q.close()

# ============ 3) 集約は copy-director だけ / Chami以外は待たせない ============
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("b1", "自動巡回", author="オーケストレーション(機構)"),
          msg_id="b1", dept="copy-director")
check("Chami以外の便しか無い時は待たない(機構の便を遅らせない)",
      _daemon(win=45)._coalesce_hold(q) is False)
q.close()

db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("h1", "いま来たばかり"), msg_id="h1", dept="hq")
check("集約窓を持たない部門(研究室HQ)は待たない=従来どおり即応",
      _daemon("hq")._coalesce_hold(q) is False)
check("★他29室は既定で窓ゼロ(設定キーが無い)",
      all(not c.get("coalesce_sec") for k, c in d.DEPT_CONF.items() if k != "copy-director"))
check("コピー部門にだけ窓が入っている", d.DEPT_CONF["copy-director"].get("coalesce_sec") == 45)
q.close()

# ============ 4) 束ね方 ============
merged = d.Daemon._merge_coalesced([
    _body("f1", "この題名どう思う"), _body("f2", "あ、字数も見て"), _body("f3", "あと語尾")])
check("土台は最後の便(返信は最新の発言へ付く)", merged["msg_id"] == "f3")
check("断片が到着順に1本へつながる",
      merged["content"] == "この題名どう思う\nあ、字数も見て\nあと語尾")
check("束ねた元の便を記録する", merged["coalesced_from"] == ["f1", "f2"])
check("空の断片は落とす",
      d.Daemon._merge_coalesced([_body("g1", ""), _body("g2", "本文")])["content"] == "本文")

# ============ 5) 通し= 連投3件が1回のhandleで返り、3件とも acked ============
db = _tmpdb()
tmp = os.path.dirname(db)
os.makedirs(os.path.join(tmp, "queue"), exist_ok=True)
db = os.path.join(tmp, "queue", "inbox.db")
q = LeaseQueue(db)
old = time.time() - 120           # 窓は既に閉じている
for i, txt in enumerate(("推敲1", "推敲2", "推敲3")):
    q.enqueue(_body("k%d" % i, txt), msg_id="k%d" % i, dept="copy-director")
q._db.execute("UPDATE queue SET enqueued_at=?", (old,))
q._db.commit()
q.close()

d.LOCAL = tmp
d.PROCESSED = os.path.join(tmp, "processed.jsonl")
d.MAIN_INBOX = os.path.join(tmp, "main.jsonl")
# ★テストは本番の台帳(local/llm/request_log.jsonl)へ1行も書かない。
#   初版で書いてしまい "request_id":"k2" が本番へ1行残った(2026-08-08・自分で同じ穴を踏んだ)。
if getattr(d, "session_relay", None) is not None:
    d.session_relay.REQUEST_LOG = os.path.join(tmp, "request_log.jsonl")
seen = []
dm = _daemon(win=45)
dm.handle = lambda rec, raw: (seen.append(rec), True)[1]
n = dm.drain_queue()
check("handleは1回だけ呼ばれた(断片ごとに走らせない)", len(seen) == 1)
check("3件が1本の本文になっている",
      seen and seen[0]["content"] == "推敲1\n推敲2\n推敲3")
check("drain_queue の戻りは1便扱い", n == 1)
q = LeaseQueue(db)
st = q.stats()
check("3件とも acked= キューに未処理が残らない(取りこぼしゼロ)",
      st["ready"] == 0 and st["leased"] == 0 and st["done"] == 3 and st["dead"] == 0)
q.close()
frag = [json.loads(x) for x in open(d.PROCESSED, encoding="utf-8") if x.strip()]
check("束ねた断片も処理済み台帳へ入る(jsonl経路の二重応答を塞ぐ)",
      sorted(r["msg_id"] for r in frag) == ["k0", "k1"])

# ============ 6) Chami以外の便を引いたら束ねず、取りこぼさない ============
db2 = os.path.join(tempfile.mkdtemp(prefix="coalesce2_"), "inbox.db")
q = LeaseQueue(db2)
q.enqueue(_body("x0", "Chamiの断片"), msg_id="x0", dept="copy-director")
q.enqueue(_body("x1", "機構の便", author="オーケストレーション(機構)"),
          msg_id="x1", dept="copy-director")
q._db.execute("UPDATE queue SET enqueued_at=?", (time.time() - 120,))
q._db.commit()
dm = _daemon(win=45)
c = q.claim(dept="copy-director", who="t")
extra = dm._coalesce_take(q, c["body"] if isinstance(c["body"], dict) else {})
check("Chami以外は束ねない", extra == [])
check("引いてしまった機構の便は手元へ戻す(nackで配達回数を焼かない)",
      len(dm._claim_carry) == 1)
check("戻した便は次の周で普通に返る(消えない)",
      dm._claim_next(q)["msg_id"] == "x1")
q.close()

print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
