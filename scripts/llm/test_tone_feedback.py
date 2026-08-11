#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口調の突き返し(封筒への差し込み)の回帰テスト。

実行: python scripts/llm/test_tone_feedback.py

★2026-08-12 新設(Chamiの🔥= msg 1536785938829549718「関西弁使い出した」の恒久対策)。
  検知(tone_gate)だけでは素通りする。**直せなかった崩れが次の封筒へ返る**ことを機械が数える。
★本番の local/ は触らない= GO5_LOCAL_DIR を一時ディレクトリへ向けてから import する。
"""
import json
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_TMP = tempfile.mkdtemp(prefix="qa_tonefb_")
os.environ["GO5_LOCAL_DIR"] = _TMP          # ★import より先に(LOCAL は import 時に決まる)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_relay as sr                  # noqa: E402

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def write_audit(rows):
    os.makedirs(os.path.dirname(sr.TONE_AUDIT_FILE), exist_ok=True)
    with open(sr.TONE_AUDIT_FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if os.path.exists(sr.TONE_FEEDBACK_STATE):
        os.remove(sr.TONE_FEEDBACK_STATE)


NOW = time.strftime("%Y-%m-%dT%H:%M:%S")
OLD = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3 * 24 * 3600))


def row(**kw):
    base = {"ts": NOW, "dept": "system-engineer", "event": "tone",
            "persona": "花海咲季", "marker": "ほんま", "reason": "dialect_kansai",
            "msg_id": "1536784731872698439", "excerpt": "…"}
    base.update(kw)
    return base


def main():
    # ---- 1) 検知が在れば突き返す ----
    write_audit([row(marker="やん"), row(marker="ほんま")])
    b = sr._tone_feedback_block("system-engineer")
    check("崩れが在れば封筒へブロックが出る", "前の便で口調が崩れた" in b)
    check("同じ便の検知語を全部並べる", "「やん」" in b and "「ほんま」" in b)
    check("話者と崩れた便のmsg_idを出す",
          "花海咲季" in b and "1536784731872698439" in b)
    check("方言だと日本語で言う", "関西弁" in b)

    # ---- 2) ★同じ崩れは1回しか突き返さない(毎便の小言にしない) ----
    check("2回目は何も出ない", sr._tone_feedback_block("system-engineer") == "")

    # ---- 3) 部門を取り違えない ----
    write_audit([row(dept="copy-director", persona="早坂芽衣", marker="俺",
                     reason="first_person_mismatch", own_first_person=["私", "芽衣"])])
    check("他部門の崩れは出さない", sr._tone_feedback_block("system-engineer") == "")
    b2 = sr._tone_feedback_block("copy-director")
    check("一人称の食い違いも突き返す(方言だけではない)",
          "一人称が他人格のもの" in b2 and "私・芽衣" in b2)

    # ---- 4) 機械が直した分(tone_fix)は突き返さない ----
    write_audit([row(event="tone_fix", marker="オレ", to="あたし", reason="tone_rewrite")])
    check("機械が書き直した便は突き返さない",
          sr._tone_feedback_block("system-engineer") == "")

    # ---- 5) 古い崩れを蒸し返さない ----
    write_audit([row(ts=OLD)])
    check("24時間より古い崩れは出さない",
          sr._tone_feedback_block("system-engineer") == "")

    # ---- 6) fail-open(封筒を壊さない) ----
    write_audit([row()])
    os.remove(sr.TONE_AUDIT_FILE)
    check("監査ファイルが無くても空を返す", sr._tone_feedback_block("system-engineer") == "")
    check("部門名が空でも空を返す", sr._tone_feedback_block("") == "")
    with open(sr.TONE_AUDIT_FILE, "w", encoding="utf-8") as f:
        f.write("これはJSONではない\n{壊れた\n")
    check("壊れた行が在っても落ちない", sr._tone_feedback_block("system-engineer") == "")

    # ---- 7) 封筒に実際に入る(差し込み位置の配線が生きているか) ----
    write_audit([row(marker="や(断定)", persona="オタコン")])
    env = sr.build_envelope({"content": "本文", "msg_id": "1", "author": "chami"},
                            dept="system-engineer")
    check("build_envelope の中身に突き返しが入る", "前の便で口調が崩れた" in env)
    check("突き返しは新着本文より前に置く",
          env.index("前の便で口調が崩れた") < env.index("=== Discord新着"))
    write_audit([])
    env2 = sr.build_envelope({"content": "本文", "msg_id": "1", "author": "chami"},
                             dept="system-engineer")
    check("崩れが無い時は封筒に1文字も足さない", "前の便で口調が崩れた" not in env2)

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
