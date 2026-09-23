# -*- coding: utf-8 -*-
"""_jev_downgrade_ok の判定ログ(local/jev/decisions.jsonl)を実行で検査する。

発注= 研究室HQ 1552312311186853922(デブライネ経由)。
★C-053/§3= 外へ出る手(jev_client.ask)だけ偽物にし、判定と分岐は本物のまま実行で通す。
  ソース文字列一致では検査にならない=入力を差し替えて本物の経路を4通り走らせる。
検査:
  1. safe高確信 → (True,"jev_ok")     ・行= choice=safe conf min_conf reason=jev_ok
  2. safe低確信 → (False,"jev_low_confidence")
  3. unsafe     → (False,"jev_unsafe")
  4. 例外       → (False,"jev_error")  ・choice/confidence は null
  すべてで decisions.jsonl に1行・返り値が元のまま。
  must-fail= 追記呼び出しを外した版では**1行も出ない**(=このログが load-bearing)。
"""
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as dd  # noqa: E402

_fails = 0
_passes = 0


def _check(cond, msg):
    global _fails, _passes
    if cond:
        _passes += 1
        print("PASS", msg)
    else:
        _fails += 1
        print("FAIL", msg)


def _install_fake_ask(answers=None, raises=False):
    """sys.modules へ偽 jev_client を差し込む(dd 内の `import jev_client` が拾う)。"""
    fake = types.ModuleType("jev_client")

    def ask(content, question):
        if raises:
            raise RuntimeError("boom")
        return answers

    fake.ask = ask
    sys.modules["jev_client"] = fake


def _read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def _run_case(answers, raises, min_conf=0.7):
    """1件だけ本物の _jev_downgrade_ok を回し、(返り値, 追記された行) を返す。"""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.close()
    old_path = dd.JEV_DECISIONS
    old_minconf = dd._jev_min_confidence
    try:
        dd.JEV_DECISIONS = tmp.name
        dd._jev_min_confidence = lambda: min_conf
        _install_fake_ask(answers=answers, raises=raises)
        rec = {"msg_id": "TEST-jev-1", "content": "この作業便のテキスト本文"}
        ret = dd._jev_downgrade_ok("platform-se", rec)
        rows = _read_lines(tmp.name)
        return ret, rows
    finally:
        dd.JEV_DECISIONS = old_path
        dd._jev_min_confidence = old_minconf
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def main():
    # 1. safe高確信 → jev_ok
    ret, rows = _run_case({"downgrade_safety": {"choice": "safe", "confidence": 0.9}}, False)
    _check(ret == (True, "jev_ok"), "safe高確信=返り値 (True, jev_ok) のまま")
    _check(len(rows) == 1, "safe高確信=1行だけ追記")
    if rows:
        r = rows[0]
        _check(r["reason"] == "jev_ok", "safe高確信=reason=jev_ok")
        _check(r["choice"] == "safe", "safe高確信=choice=safe")
        _check(abs(r["confidence"] - 0.9) < 1e-9, "safe高確信=confidence=0.9")
        _check(abs(r["min_conf"] - 0.7) < 1e-9, "safe高確信=min_conf=0.7(その時のしきい値)")
        _check(r["msg_id"] == "TEST-jev-1", "safe高確信=msg_id を残す")
        _check(r["head"] and r["head"] in "この作業便のテキスト本文", "safe高確信=本文先頭を残す")
        _check("ts" in r and r["ts"], "safe高確信=ts を残す")

    # 2. safe低確信 → jev_low_confidence
    ret, rows = _run_case({"downgrade_safety": {"choice": "safe", "confidence": 0.5}}, False)
    _check(ret == (False, "jev_low_confidence"), "safe低確信=返り値 (False, jev_low_confidence)")
    _check(len(rows) == 1 and rows[0]["reason"] == "jev_low_confidence", "safe低確信=1行 reason=jev_low_confidence")
    if rows:
        _check(abs(rows[0]["confidence"] - 0.5) < 1e-9 and abs(rows[0]["min_conf"] - 0.7) < 1e-9,
               "safe低確信=confidence=0.5 < min_conf=0.7 を残す")

    # 3. unsafe → jev_unsafe
    ret, rows = _run_case({"downgrade_safety": {"choice": "unsafe", "confidence": 0.9}}, False)
    _check(ret == (False, "jev_unsafe"), "unsafe=返り値 (False, jev_unsafe)")
    _check(len(rows) == 1 and rows[0]["reason"] == "jev_unsafe", "unsafe=1行 reason=jev_unsafe")
    if rows:
        _check(rows[0]["choice"] == "unsafe" and rows[0]["min_conf"] is not None,
               "unsafe=choice=unsafe・min_conf も残す(厳しすぎ判定の仕分け材料)")

    # 4. 例外 → jev_error(choice/confidence は null)
    ret, rows = _run_case(None, True)
    _check(ret == (False, "jev_error"), "例外=返り値 (False, jev_error)")
    _check(len(rows) == 1 and rows[0]["reason"] == "jev_error", "例外=1行 reason=jev_error")
    if rows:
        _check(rows[0]["choice"] is None and rows[0]["confidence"] is None,
               "例外=choice/confidence は null")

    # must-fail: 追記を外した版では1行も出ない(=このログが load-bearing)
    _mustfail_no_append()

    print("\n%d PASS / %d FAIL" % (_passes, _fails))
    sys.exit(1 if _fails else 0)


def _jev_downgrade_ok_noappend(dept, rec):
    """_jev_log_decision を1つも呼ばない偽実装(判定は本物と同じ)。must-fail用。"""
    content = str((rec or {}).get("content") or "").strip()
    try:
        sys.path.insert(0, os.path.join(dd.LOCAL, "jev"))
        import jev_client  # noqa: E402
    except Exception:
        return (False, "jev_error")
    try:
        if not content:
            return (False, "jev_error")
        answers = jev_client.ask(content[:4000], dd._JEV_DOWNGRADE_QUESTION)
        if not answers:
            return (False, "jev_error")
        a = answers.get("downgrade_safety") or {}
        choice = str(a.get("choice") or "")
        conf = float(a.get("confidence") or 0)
        if choice != "safe":
            return (False, "jev_unsafe")
        if conf < dd._jev_min_confidence():
            return (False, "jev_low_confidence")
        return (True, "jev_ok")
    except Exception:
        return (False, "jev_error")


def _mustfail_no_append():
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    tmp.close()
    old_path = dd.JEV_DECISIONS
    old_minconf = dd._jev_min_confidence
    try:
        dd.JEV_DECISIONS = tmp.name
        dd._jev_min_confidence = lambda: 0.7
        _install_fake_ask(answers={"downgrade_safety": {"choice": "safe", "confidence": 0.9}})
        rec = {"msg_id": "TEST-jev-1", "content": "この作業便のテキスト本文"}
        ret = _jev_downgrade_ok_noappend("platform-se", rec)
        rows = _read_lines(tmp.name)
        _check(ret == (True, "jev_ok"), "[must-fail]偽実装も判定は同じ(=判定は本物のまま)")
        _check(len(rows) == 0,
               "[must-fail]追記を外した版では0行=このログが本物の load-bearing 差分")
    finally:
        dd.JEV_DECISIONS = old_path
        dd._jev_min_confidence = old_minconf
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


if __name__ == "__main__":
    main()
