# -*- coding: utf-8 -*-
"""未完了の依頼の追撃便(REQF-)が「配達までの間に閉じた依頼」を運ばないことの回帰テスト。

事故(2026-08-24 実測): REQ-aegis-gl-3529df3516 は
  22:46:56 投函 → **22:50:28 に閉じ** → 22:51:42 に配達 → 22:58 に本走。
`_post_waiting_followup` は投函の瞬間には台帳を読み直しているが、便はqueueで待つので
その写しは配達時には古い。結果、**既に閉じた依頼を催促するためだけに部屋の1便**を燃やした。
ログに残る REQF- の claim 18件中2件が同型(kaizen-analyst 2026-08-17T01:37 も同じ)。

恒久策= `Daemon._refresh_request_followup()`(掴んだ瞬間にもう一度台帳を読む)。
  台帳が空 → ""(配らない) / 中身が変わった → 作り直した本文 / それ以外 → None(そのまま配る)。

★must-fail を2本入れてある(C-053)= 「動く別の実装」を同じ入力へ通し、**赤くなること**を見る。
  常にPASSする検査は無いのと同じ。
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts", "llm"))
import dept_daemon as D  # noqa: E402

fails = []


def eq(got, want, label):
    if got != want:
        fails.append("%s: got=%r want=%r" % (label, got, want))


# --- 台帳の代わり(open_request_list を差し替える。外へ出る手だけ偽物・判定は本物) ---
class _FakeRelay:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    def open_request_list(self, dept):
        self.calls += 1
        if isinstance(self.items, Exception):
            raise self.items
        return list(self.items)


def _daemon(items):
    """_refresh_request_followup だけを本物のまま呼べる最小の器を作る。"""
    d = D.Daemon.__new__(D.Daemon)
    d.dept = "aegis-gl"
    d.conf = {"session_relay": True}
    return d, _FakeRelay(items)


def _run(items, rec, mid, fn=None):
    d, fake = _daemon(items)
    old = D.session_relay
    D.session_relay = fake
    try:
        return (fn or D.Daemon._refresh_request_followup)(d, rec, mid)
    finally:
        D.session_relay = old


OPEN_A = {"id": "REQ-aegis-gl-AAAA", "symptom": "全部任せた",
          "broken": "msg_id=1541434864287617044 / 部屋=イージス研究室",
          "noticed_at": "2026-08-24T13:11:50"}
OPEN_B = {"id": "REQ-aegis-gl-BBBB", "symptom": "ここ直して",
          "broken": "msg_id=999 / 部屋=イージス研究室",
          "noticed_at": "2026-08-24T14:00:00"}

REQF_MID = D.REQUEST_PREFIX + "aegis-gl-REQ-aegis-gl-AAAA"
STALE_BODY = D.request_followup_text([OPEN_A], D.REQUEST_FOLLOWUP_SEC)


def _reqf(content):
    return {"msg_id": REQF_MID, "via": "request_followup", "dept": "aegis-gl",
            "author": "オーケストレーション(機構)", "content": content}


# --- 1. 事故そのもの: 投函後に全部閉じた → 配らない ---
eq(_run([], _reqf(STALE_BODY), REQF_MID), "",
   "★事故の再現: 台帳が空になった追撃便は配らない(空振りの1便を燃やさない)")

# --- 2. まだ残っている依頼が在る → 落とさず、今の台帳の姿へ作り直す ---
got = _run([OPEN_B], _reqf(STALE_BODY), REQF_MID)
eq(isinstance(got, str) and got != "", True, "残りが在れば配る(催促を黙って落とさない)")
eq("REQ-aegis-gl-AAAA" in (got or ""), False, "★閉じた依頼の番号は本文から消えていること")
eq("REQ-aegis-gl-BBBB" in (got or ""), True, "★残っている依頼はちゃんと載っていること")

# --- 3. 台帳が動いていない → None(1バイトも触らない) ---
eq(_run([OPEN_A], _reqf(STALE_BODY), REQF_MID), None,
   "台帳が投函時と同じなら本文を作り直さない")

# --- 4. 追撃便**以外**は絶対に落とさない(Chamiの便を消したら最悪の事故) ---
chami = {"msg_id": "1541434864287617044", "author": "chami_fusoh", "content": "全部任せた"}
eq(_run([], chami, chami["msg_id"]), None, "★Chamiの普通の便は台帳が空でも触らない")
eq(_run([], {"msg_id": REQF_MID, "via": "dispatch", "content": "x"}, REQF_MID), None,
   "接頭辞だけ一致して via が違う便は触らない(二重で確かめる)")
eq(_run([], {"msg_id": "WAIT-aegis-gl-1", "via": "waiting_followup", "content": "x"},
        "WAIT-aegis-gl-1"), None, "待ちの追撃便(WAIT-)はこの判定の対象外")

# --- 5. fail-open: 台帳が読めない時は従来どおり配る ---
eq(_run(RuntimeError("台帳が壊れている"), _reqf(STALE_BODY), REQF_MID), None,
   "★fail-open: 台帳を読めなければ配る(沈黙が最悪の事故)")

# --- 6. relay を使わない部屋では何もしない ---
_d, _f = _daemon([])
_d.conf = {}
_old = D.session_relay
D.session_relay = _f
try:
    eq(D.Daemon._refresh_request_followup(_d, _reqf(STALE_BODY), REQF_MID), None,
       "session_relay を使わない部屋は従来どおり")
    eq(_f.calls, 0, "その部屋では台帳を読みにも行かない")
finally:
    D.session_relay = _old


# ============================================================================
# must-fail(C-053)= 「動く別の実装」を同じ入力へ通し、**上の検査が赤くなる**ことを見る。
# ============================================================================
def _mf_shot_id_only(self, rec, mid):
    """別実装A= 投函時の写しを信じ、msg_id が指す依頼が台帳に無ければ丸ごと捨てる。
    (台帳を1回しか見ないので、残っている依頼ごと捨ててしまう= 検査2で赤くなるはず)
    """
    if not str(mid or "").startswith(D.REQUEST_PREFIX):
        return None
    if rec.get("via") != "request_followup":
        return None
    try:
        items = D.session_relay.open_request_list(self.dept)
    except Exception:
        return None
    head = str(mid).split("-", 2)[-1]
    return None if any(str(i.get("id")) == head for i in items) else ""


def _mf_fail_closed(self, rec, mid):
    """別実装B= 台帳が読めない時に「分からないから配らない」と倒す(fail-closed)。
    (検査5で赤くなるはず= 催促が黙って消える)
    """
    if not str(mid or "").startswith(D.REQUEST_PREFIX):
        return None
    if rec.get("via") != "request_followup":
        return None
    try:
        items = D.session_relay.open_request_list(self.dept)
    except Exception:
        return ""
    if not items:
        return ""
    fresh = D.request_followup_text(items, D.REQUEST_FOLLOWUP_SEC)
    return None if fresh == str(rec.get("content") or "") else fresh


mf = []
if _run([OPEN_B], _reqf(STALE_BODY), REQF_MID, fn=_mf_shot_id_only) != "":
    mf.append("別実装A(msg_idだけ見る)が検査2で赤くならなかった=検査がザル")
if _run(RuntimeError("x"), _reqf(STALE_BODY), REQF_MID, fn=_mf_fail_closed) is None:
    mf.append("別実装B(fail-closed)が検査5で赤くならなかった=検査がザル")
fails.extend(mf)

if fails:
    print("FAIL " + str(len(fails)) + "件")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("PASS 追撃便(REQF-)は配達の直前に台帳と突き合わせ直す"
      "(空振りは配らない / 残りは作り直す / 追撃便以外とfail-openは従来どおり・must-fail 2本)")
