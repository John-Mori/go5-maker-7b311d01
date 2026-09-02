# -*- coding: utf-8 -*-
"""ベホップ `ask_pro` の**一過性の失敗に対する再試行**の検査。

なぜ要るか(2026-09-03 イージス研究室・実測):
  `local/llm/gemini_usage.jsonl` 581件のうち **331件が失敗**。内訳は
  HTTP 503 = 266 / HTTP 429 = 36 / TimeoutError = 24。
  503は**全件 gemini-flash-latest**= モデルが無いのでも枠が尽きたのでもなく、
  **その瞬間だけ混んでいた**という意味だ。ところが `ask_pro` はこれを
  `error:HTTP 503` として1回で諦め、呼び側(comp_frames)は
  「視覚失敗(...)スキップ」でそのフレームを**永久に捨てて**いた(実測257件)。
  2026-08-28 は OK 0 / NG 14 = **丸一日ぶん全部落ちた**。
  ★共有の `ask()` は既に5xxで粘る(下の段へ降りる)。粘っていないのは
    「降格しない専用経路」である `ask_pro` だけ= ここだけ穴が空いていた。

★この検査が守る不変条件:
  ①一過性の失敗(5xx / タイムアウト / 切断)は**同じ段で**再試行する
  ②**429は再試行しない**= 割当は待っても回復しない。即 "quota" を返して
    呼び側のキー切替(comp_frames のホイミンへの切替)を1秒も遅らせない
  ③404/400 も再試行しない(モデルが無い・要求が不正=何度やっても同じ)
  ④再試行は**有界**(無限に粘って日次ジョブを止めない)
  ⑤戻り値の契約を変えない= ("text","ok") / (None,"quota") / (None,"error:...")
  ⑥使用量の記録は**1回の仕事につき1行**(再試行で失敗件数を水増ししない)。
    ただし成功しても**途中で何が落ちたかは err に残す**(2026-08-18 の ask() と同じ作法)

走らせ方= python scripts/behop/test_behop_retry.py
"""
import io
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import behop  # noqa: E402

_ok = 0
_ng = 0


def chk(label, cond):
    global _ok, _ng
    if cond:
        _ok += 1
        print("  PASS", label)
    else:
        _ng += 1
        print("  FAIL", label)


def http(code):
    return urllib.error.HTTPError("https://x", code, "e", None, io.BytesIO(b""))


class Fake(object):
    """_gen_once の身代わり。渡された筋書きを順に返す(例外なら投げる)。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, key, model, payload):
        self.calls += 1
        r = self.script.pop(0) if self.script else "最後まで来た"
        if isinstance(r, Exception):
            raise r
        return r


def run(script):
    """ask_pro を1回まわし、(戻り値, 叩いた回数, 記録された行) を返す。
    ★本番の記録(local/llm/gemini_usage.jsonl)と sleep は必ず差し替える=
      検査が本物のログを汚さない・待ち時間を実際には使わない。"""
    fake = Fake(script)
    logged = []
    orig = (behop._gen_once, behop._usage, behop.time.sleep)
    behop._gen_once = fake
    behop._usage = lambda *a, **k: logged.append((a, k))
    behop.time.sleep = lambda s: None
    try:
        res = behop.ask_pro("KEY", "prompt", (), "gemini-flash-latest", tag="test")
    finally:
        behop._gen_once, behop._usage, behop.time.sleep = orig
    return res, fake.calls, logged


def main():
    print("== ①一過性の失敗は同じ段で再試行して拾い直す ==")
    (text, status), calls, log = run([http(503), "見えた"])
    chk("503が1回なら2回目で成功する", status == "ok" and text == "見えた")
    chk("同じ段を叩き直している(2回)", calls == 2)
    (text, status), calls, _ = run([http(503), http(503), "見えた"])
    chk("503が2回続いても拾える", status == "ok" and calls == 3)
    (text, status), calls, _ = run([TimeoutError("timed out"), "見えた"])
    chk("TimeoutError も再試行する(実測24件)", status == "ok" and calls == 2)

    print("== ②429は再試行しない(待っても割当は戻らない・キー切替を遅らせない) ==")
    (text, status), calls, _ = run([http(429), "来てはいけない"])
    chk("429は即 quota", status == "quota" and text is None)
    chk("429で叩き直さない(1回だけ)", calls == 1)

    print("== ③恒久的な失敗も再試行しない ==")
    for code in (404, 400):
        (_, status), calls, _ = run([http(code), "来てはいけない"])
        chk("HTTP %d は1回で諦める" % code, calls == 1 and status == "error:HTTP %d" % code)

    print("== ④再試行は有界(日次ジョブを止めない) ==")
    (text, status), calls, _ = run([http(503)] * 20)
    chk("全部503でも有限回で降りる", calls <= 1 + behop.PRO_RETRY)
    chk("最後は失敗として返す", text is None and status.startswith("error:"))

    print("== ⑤戻り値の契約を変えていない ==")
    (text, status), _, _ = run(["一発で見えた"])
    chk("成功は (text, 'ok')", status == "ok" and text == "一発で見えた")
    (text, status), _, _ = run([KeyError("parts")])
    chk("応答形式が想定外は error: で返る",
        text is None and status == "error:応答形式が想定外")

    print("== ⑥記録は1仕事1行・途中の失敗は err に残す ==")
    _, _, log = run([http(503), "見えた"])
    chk("再試行しても記録は1行(失敗件数を水増ししない)", len(log) == 1)
    args = log[0][0]
    chk("成功として記録される", True in args)
    trail = " ".join(str(a) for a in args)
    chk("途中の503が err に残る(静かに消さない)", "503" in trail)
    _, _, log = run([http(503)] * 20)
    chk("全滅時も記録は1行", len(log) == 1)

    print("\n== %d/%d PASS ==" % (_ok, _ok + _ng))
    return 1 if _ng else 0


if __name__ == "__main__":
    sys.exit(main())
