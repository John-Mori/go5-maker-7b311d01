#!/usr/bin/env python3
"""回帰: 封筒(dispatch)の合流点で炎上表記が正規化されることを、**本物の dispatch() を回して**確かめる。

■何を守る試験か(2026-09-07 イージス研究室 / 発注 DISPATCH-aegis-gl-1788739848001)
  発注の受け入れ条件= 「次回の自動巡回digestの受信contentに素の🔥が0件 / gate通しの回帰1本追加PASS」。
  この1本がその回帰。★材料は作り話ではなく、**実際に漏れていた物と同じ経路**で作る=
  reaction_watch.dept_body() が吐く本物のdigest本文を、本物の dispatch.dispatch() へ渡す。

■実測で分かっていること(発注の前提の訂正)
  enjoh_backstop を呼んでいるのは persona_send / bot_send / codex_run / behop / imagegen の**5口だけ**。
  dispatch は1度も通っていなかった(=発注の「dispatch経由には効いている」は誤り)。
  部門記憶の受信content 2026-09-02〜09-07 で、素の🔥を載せた DISPATCH/ESC封筒は **22通**
  (digest見出し12通 + 各室が自分で書いた地の文10通)。→ producerを1つずつ直しても終わらない(C-064)。

■偽物にする手(§3= 本物の分岐を回し、外へ出る手だけ偽る)
  - LeaseQueue      … 本番のキューDBへ書かない(投函本文だけ捕まえる)
  - post_work_to_channel … persona_send のサブプロセス=実POSTを止める(表投稿の本文だけ捕まえる)
  - ai_throttle_not_before … 本番DBの読みを止める
  これ以外(呼称ゲート・rec組み立て・msg_id採番・enjoh_gate_pass 本体)は全部**本物**が走る。

■must-fail(C-053)
  「ゲートの行を消した dispatch.py」を**同じディレクトリに置いて**回し、この試験が落ちることを確かめる。
  同じ場所に置くのは ROOT を __file__ から解いているから= tmpへ置くと偽の緑になる。

使い方: python scripts/llm/test_dispatch_enjoh_gate.py
"""
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
FIRE = "\U0001F525"
ENJOH = "<:enjoh:1541126866981752883>"

for p in (HERE, os.path.join(ROOT, "scripts", "discord")):
    if p not in sys.path:
        sys.path.insert(0, p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FAILS = []


def check(name, cond, detail=""):
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f"  … {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)
    return cond


# ---- 材料: 本物の巡回digest本文 --------------------------------------------------
def real_digest_body():
    """reaction_watch の**本物の**組み立てで、炎上1件のdigest本文を作る。"""
    import reaction_watch as rw
    item = {
        "kind": "enjo",
        "emoji": FIRE, "by_chami": True, "by": ["Chami"],
        "channel": "🛡️イージス研究室", "dept": "aegis-gl",
        "channel_id": "1", "msg_id": "2",
        "author": "ケヴィン・デブライネ", "posted_at": "2026-09-06T08:00:00",
        "detected_at": "2026-09-07T08:00:00",
        "content": "本文サンプル。",
    }
    return rw.dept_body("aegis-gl", [item], "g")


# ---- 偽の手 ----------------------------------------------------------------------
class FakeQueue:
    """本番キューDBの代わり。enqueue された本文をそのまま溜める。"""
    rows = []

    def __init__(self, path):
        self.path = path

    def enqueue(self, body, msg_id=None, dept=None, not_before=None):
        FakeQueue.rows.append({"body": body, "msg_id": msg_id, "dept": dept})
        return True

    def close(self):
        pass


def install_fake_queue():
    m = types.ModuleType("leasequeue")
    m.LeaseQueue = FakeQueue
    sys.modules["leasequeue"] = m


def run_dispatch(mod, body, work="", already_gated=True):
    """本物の dispatch() を1回回し、(投函された本文, 表投稿の本文) を返す。"""
    FakeQueue.rows = []
    posted = {}

    def fake_post(dept, persona, post_body, timeout=90):
        posted["body"] = post_body
        return "999"

    orig_post = mod.post_work_to_channel
    orig_thr = mod.ai_throttle_not_before
    mod.post_work_to_channel = fake_post
    mod.ai_throttle_not_before = lambda *a, **k: 0.0
    buf = io.StringIO()
    orig_out = sys.stdout
    try:
        sys.stdout = buf
        ok, mid = mod.dispatch("aegis-gl", "ケヴィン・デブライネ(イージス研究室GL)", body,
                               work=work, audience="ai", already_gated=already_gated)
    finally:
        sys.stdout = orig_out
        mod.post_work_to_channel = orig_post
        mod.ai_throttle_not_before = orig_thr
    assert ok, f"dispatch が投函に失敗した: {buf.getvalue()}"
    import json
    rec = json.loads(FakeQueue.rows[-1]["body"])
    return rec["content"], posted.get("body", "")


# ---- 本体 --------------------------------------------------------------------------
def run_suite(mod, label, expect_pass=True):
    print(f"\n=== {label} ===")
    before = len(FAILS)
    digest = real_digest_body()

    # E-0 材料そのものの確認= 発注の直し所1(reaction_watch.py:549)が入っており、
    #     それでも**本文にはまだ素の🔥が残る**(Chami原文の引用WHY等)= 恒久側が要る証拠。
    check("E-0 digest見出しが <:enjoh:…> になっている(直し所1)", ENJOH in digest)
    check("E-0 それでも digest 本文には素の🔥が残っている(=見出しだけでは0件にならない)",
          FIRE in digest, f"残 {digest.count(FIRE)}件")

    # E-1 キューへ投函される本文(=各部屋の受信content)に素の🔥が0件。
    content, _ = run_dispatch(mod, digest)
    check("E-1 投函された受信contentに素の🔥が0件", FIRE not in content,
          f"残 {content.count(FIRE)}件")
    check("E-1 消したのではなく <:enjoh:…> へ置き換えている", content.count(ENJOH) >= digest.count(FIRE))

    # E-2 --work の表投稿の本文にも効く(出口が2つあるので両方見る)。
    content2, post_body = run_dispatch(mod, digest, work="digestの確認")
    check("E-2 表投稿の本文にも素の🔥が0件", post_body and FIRE not in post_body)
    check("E-2 同時に投函本文も0件", FIRE not in content2)

    # E-3 already_gated=False(dispatch() を直に呼ぶ経路)でも効く。
    content3, _ = run_dispatch(mod, digest, already_gated=False)
    check("E-3 already_gated=False でも素の🔥が0件", FIRE not in content3)

    # E-4 コードの中の🔥は触らない(規律や実装の説明で素の印を見せたい場面がある)。
    code = "封筒の本文だ。日本語をここに二十字以上入れておく必要がある。\n```\nemoji = \"🔥\"\n```\n以上。"
    c4, _ = run_dispatch(mod, code)
    check("E-4 コードブロック内の🔥はそのまま", FIRE in c4 and ENJOH not in c4)

    # E-5 封筒の情報を消さない= フィラー行スクラブを封筒へ当てていないこと。
    #     `dispatch` のような識別子だけの行は封筒に普通に出る。消したら依頼が壊れる。
    env = ("■真因= ゲートを呼んでいない口がある。日本語の地の文をここに二十字以上置く。\n"
           "\n"
           "dispatch\n"
           "\n"
           "■直し所= 合流点へ1本。🔥\n")
    c5, _ = run_dispatch(mod, env)
    check("E-5 孤立した識別子行 `dispatch` を消していない", "\ndispatch\n" in c5)
    check("E-5 それでも🔥は正規化されている", FIRE not in c5 and ENJOH in c5)

    # E-6 対象が無い便は1ミリも変えない。
    plain = "対象の無い普通の便だ。日本語の地の文をここに二十字以上入れておく。\n\n■以上。"
    c6, _ = run_dispatch(mod, plain)
    check("E-6 🔥の無い便は素通し(1文字も変わらない)", c6 == plain)

    got = (len(FAILS) == before)
    if expect_pass:
        return got
    if got:
        print("  ★must-fail が通ってしまった= この試験は穴を検出できていない")
        return False
    print("  ★must-fail は期待どおり落ちた(=この試験は本当に穴を見ている)")
    del FAILS[before:]
    return True


def make_mutant():
    """ゲートの行を抜いた dispatch.py を**同じディレクトリに**作る(C-053)。"""
    src = open(os.path.join(HERE, "dispatch.py"), encoding="utf-8").read()
    line = "    body = enjoh_gate_pass(body, dept)\n"
    assert line in src, "ゲートの呼び出し行が見つからない(実物が変わった?)"
    dst = os.path.join(HERE, "_mutant_dispatch_no_enjoh.py")
    open(dst, "w", encoding="utf-8").write(src.replace(line, "    # (mutant) ゲートを外した\n"))
    return dst


def main():
    install_fake_queue()
    import dispatch as real
    ok = run_suite(real, "本物 scripts/llm/dispatch.py", expect_pass=True)

    mutant_path = make_mutant()
    try:
        import importlib
        mut = importlib.import_module("_mutant_dispatch_no_enjoh")
        ok = run_suite(mut, "must-fail: ゲートの行を抜いた実装", expect_pass=False) and ok
    finally:
        try:
            os.remove(mutant_path)
        except OSError:
            pass
        for d in ("__pycache__",):
            f = os.path.join(HERE, d, "_mutant_dispatch_no_enjoh.cpython-*.pyc")
            import glob
            for g in glob.glob(f):
                try:
                    os.remove(g)
                except OSError:
                    pass

    print("\n" + ("ALL PASS" if ok and not FAILS else f"FAIL: {FAILS}"))
    return 0 if (ok and not FAILS) else 1


if __name__ == "__main__":
    sys.exit(main())
