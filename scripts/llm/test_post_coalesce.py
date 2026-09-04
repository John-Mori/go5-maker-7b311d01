# -*- coding: utf-8 -*-
"""返す直前の集約(post-coalesce)のテスト(2026-08-13 イージス研究室)。

発注= 研究室HQ DISPATCH-aegis-gl-1786628907518。
なぜ作り直したか(HQ実測):
  8/8に入れた「**走る前に**45秒待つ」窓は、5日間・本番で**1回も束ねていない**。
    ・`集約窓: 連投中(N件)` 全84回のうち82回が『1件』(=束ねる相手が居ない)
    ・`state:"coalesced"` は検証便2行だけ / 上限300秒での強制実行は0回
  理由は窓が短いからではない= **Chamiの推敲の刻みが2〜5分**だ。
    コピー部門 8/8以降29組= 45秒以内 **0** / 45〜120秒 2 / 120〜300秒 8 / 300秒超 19
  だから窓を伸ばすのは損= 45→120秒で拾えるのは29便中2便、代わりに全29便が最大2分遅くなる。
→ **待つ場所を「走る前」から「返す直前」へ移した。** CLIの実行は中央値60秒(HQ実測)で、
  その60秒は今も何も返していない=**追加の遅延ゼロ**で実効の窓が 45→105秒へ伸びる。

この検査が固定する規則=
  ① `coalesce_sec` を持たない29室は**1バイトも変わらない**(覗きにすら行かない)
  ② 束ねたら**1本だけ**返す(断片ごとに返さない)+ ack と PROCESSED の控えを残す(二重応答の防止)
  ③ 束ね直しに失敗したら掴んだ便を**手元へ戻す**(消さない=INC-100のドレインの窓を作らない)
  ④ 返事が空(=配送失敗)の便では覗きに行かない
  ⑤ 束ね直しの本文が極端に短い時は**元の返事を落とさない**

実行: python scripts/llm/test_post_coalesce.py
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


def _tmpdb():
    return os.path.join(tempfile.mkdtemp(prefix="postco_"), "inbox.db")


def _body(mid, content, author="chami_fusoh"):
    return {"msg_id": mid, "author": author, "content": content, "test": True}


def _daemon(win=None, dept="copy-director"):
    dm = d.Daemon(dept)
    if win is not None:
        dm.conf = dict(dm.conf)
        dm.conf["coalesce_sec"] = win
    dm._post_coalesced, dm._post_coalesced_raw = [], []
    return dm


class _FakeRelay:
    """session_relay の差し替え。★本物のセッションは1度も呼ばない(本番の部屋でテストしない)。"""

    def __init__(self, reply, ok=True):
        self.reply, self.ok = reply, ok
        self.calls, self.records = [], []

    def relay(self, dept, rec, conf, token, **kw):
        self.calls.append(rec)
        return self.reply, self.ok

    def _record(self, mid, dept, state, ev):
        self.records.append((mid, dept, state, ev))


_orig = d.session_relay

print("[1] 続きが来ていたら1本へ束ね直す")
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("p1", "続きの便だよ"), msg_id="p1", dept="copy-director")
dm = _daemon(win=45)
dm._lease_q, dm._lease_qids = q, ["dummy"]
fake = _FakeRelay("束ね直した1本の返事" * 20)
d.session_relay = fake
out = dm._coalesce_after_run(_body("p0", "最初の便"), "p0", "最初の返事" * 20)
check("束ね直した本文を返す", out == fake.reply)
check("relayをもう一度だけ呼ぶ(連打しない)", len(fake.calls) == 1)
check("束ね直しの便に続きの本文が入っている", "続きの便だよ" in fake.calls[0]["content"])
check("『まだ送っていない』とセッションへ伝えている", "送っていない" in fake.calls[0]["content"])
check("元の便のmsg_idが coalesced_from に入る", "p0" in (fake.calls[0].get("coalesced_from") or []))
check("台帳へ coalesced を1行残す", any(r[2] == "coalesced" for r in fake.records))
check("検証便には[検証便]の印が付く(実績と試験の痕跡を混ぜない)",
      any("[検証便]" in r[3] for r in fake.records))
check("ackすべき行を控えている(1件)", len(dm._post_coalesced) == 1)
check("PROCESSED用のrawも控えている(jsonl経路の二重応答を防ぐ)",
      len(dm._post_coalesced_raw) == 1)
check("リースの張り直し対象へ足している", len(dm._lease_qids) == 2)
q.close()

print("[2] 窓を持たない29室は1バイトも変わらない(C-035)")
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("n1", "続き"), msg_id="n1", dept="copy-director")
dm = _daemon(win=0)
dm._lease_q, dm._lease_qids = q, []
fake0 = _FakeRelay("x")
d.session_relay = fake0
check("窓なしでは束ねない", dm._coalesce_after_run(_body("n0", "本便"), "n0", "元の返事") == "元の返事")
check("窓なしでは relay を呼ばない", len(fake0.calls) == 0)
check("窓なしでは便を掴まない(キューに残る)", len(q.peek_ready(dept="copy-director")) == 1)
q.close()

print("[3] 束ね直しが不成立なら、掴んだ便を手元へ戻す(消さない)")
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("f1", "続き"), msg_id="f1", dept="copy-director")
dm = _daemon(win=45)
dm._lease_q, dm._lease_qids = q, ["dummy"]
d.session_relay = _FakeRelay("", ok=False)
out = dm._coalesce_after_run(_body("f0", "本便"), "f0", "元の返事")
check("元の返事をそのまま送る(沈黙にしない=fail-open)", out == "元の返事")
check("掴んだ便は手元へ戻す", len(dm._claim_carry) == 1)
check("戻した便は次の周で普通に返る(取りこぼさない)", dm._claim_next(q)["msg_id"] == "f1")
check("答えていない便を ack 対象に入れない", not dm._post_coalesced)
check("リースの張り直し対象からも外す", "dummy" in dm._lease_qids and len(dm._lease_qids) == 1)
q.close()

print("[4] 覗きに行かない場面")
db = _tmpdb()
q = LeaseQueue(db)
dm = _daemon(win=45)
dm._lease_q, dm._lease_qids = q, []
fake2 = _FakeRelay("y")
d.session_relay = fake2
check("続きが無ければ元の返事のまま", dm._coalesce_after_run(_body("e0", "本便"), "e0", "元") == "元")
check("続きが無ければ relay を呼ばない", len(fake2.calls) == 0)
q.enqueue(_body("e1", "続き"), msg_id="e1", dept="copy-director")
check("返事が空(=配送失敗)の便では束ねない",
      dm._coalesce_after_run(_body("e0", "本便"), "e0", "") == "")
check("空返事では便を掴まない(キューに残る)", len(q.peek_ready(dept="copy-director")) == 1)
q.enqueue(_body("e2", "機構の便", author="オーケストレーション(機構)"),
          msg_id="e2", dept="copy-director")
q.close()

print("[5] 束ね直しが短すぎる時は元の返事を落とさない")
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("s1", "続き"), msg_id="s1", dept="copy-director")
dm = _daemon(win=45)
dm._lease_q, dm._lease_qids = q, ["dummy"]
d.session_relay = _FakeRelay("了解")
long_reply = "元の長い返事" * 50
out = dm._coalesce_after_run(_body("s0", "本便"), "s0", long_reply)
check("元の返事と束ね直しの両方が残る", long_reply in out and "了解" in out)
q.close()

print("[6] Chami以外の便は束ねない(手元へ戻す)")
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("g1", "機構の巡回便", author="オーケストレーション(機構)"),
          msg_id="g1", dept="copy-director")
dm = _daemon(win=45)
dm._lease_q, dm._lease_qids = q, ["dummy"]
fake3 = _FakeRelay("z")
d.session_relay = fake3
check("機構の便しか無ければ束ねない",
      dm._coalesce_after_run(_body("g0", "本便"), "g0", "元の返事") == "元の返事")
check("機構の便では relay を呼ばない", len(fake3.calls) == 0)
q.close()

print("[7] ★2026-09-04 上位室への展開が生きている(HQ DISPATCH-aegis-gl-1788502002632)")
# ★config の文字列を読むのではなく、**本物の DEPT_CONF で組んだ Daemon に実際に束ねさせる**。
#   守る規則= ①入れた室では after_run が本当に発火する ②入れていない室は覗きにすら行かない(C-035)。
# 変異= `--mutate 1` で4室の coalesce_sec を 0 へ戻す(=展開前の実装)→ ここが赤くなる。
_ROLLED = ["hr-room", "research-room", "kaizen-analyst", "aegis-gl"]
if "--mutate" in sys.argv and sys.argv[sys.argv.index("--mutate") + 1] == "1":
    for _r in _ROLLED:
        d.DEPT_CONF[_r] = dict(d.DEPT_CONF[_r], coalesce_sec=0)

for _r in _ROLLED:
    check("%s に集約窓が入っている" % _r, _daemon(dept=_r)._coalesce_win() > 0)

# ★実際に束ねるところまで通す(人事部門= 0歩目の実物が出た部屋)。
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("h1", "わりぃ、ミスった。ちゃみくんに変更だった"), msg_id="h1", dept="hr-room")
dm = _daemon(dept="hr-room")            # ★窓は差し替えない= DEPT_CONF の実値で動かす
dm._lease_q, dm._lease_qids = q, ["dummy"]
fake7 = _FakeRelay("まとめ直した1本" * 20)
d.session_relay = fake7
out7 = dm._coalesce_after_run(_body("h0", "トトリはオタコンをオタコンさんと呼ぶ"), "h0", "元の返事")
check("★人事部門で本走中に着いた訂正が1本へ束なる", len(fake7.calls) == 1 and "まとめ直した1本" in out7)
check("束ね直しの便に訂正の本文が入っている",
      bool(fake7.calls) and
      "ちゃみくんに変更だった" in str(fake7.calls[0].get("content") or ""))
q.close()

# ★入れていない室は1バイトも変わらない(C-035)= 窓0なら覗きにすら行かない。
db = _tmpdb()
q = LeaseQueue(db)
q.enqueue(_body("n1", "続きの便"), msg_id="n1", dept="past-room")
dm = _daemon(dept="past-room")
dm._lease_q, dm._lease_qids = q, ["dummy"]
fake8 = _FakeRelay("x")
d.session_relay = fake8
check("未設定の室は従来どおり(束ねない)",
      dm._coalesce_after_run(_body("n0", "本便"), "n0", "元の返事") == "元の返事")
check("未設定の室では relay を呼ばない", len(fake8.calls) == 0)
q.close()

d.session_relay = _orig
print("\n%d passed / %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
