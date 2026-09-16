# -*- coding: utf-8 -*-
"""部屋の職掌の外の話題を、封筒が機構で弾かせることの回帰検査。

台帳= DEF-llm-edu-2b15d8e3a0(発注元 llm-edu/中野五月 `DISPATCH-aegis-gl-1789259768195`)
引き金= Chami msg 1548128860497780857(2026-09-12 09:31 JST・ローカルllm言語教育部門)
  「ここはローカルLLMの部門だから。ちゃんと弾かなあかんよ〜」= 炎上スタンプ(恒久対策まで行け)

★**壊れた実物**(この検査のフィクスチャはここから採った。作り話ではない):
  - msg 1548011701943930962(2026-09-12 01:45:50 JST・ローカルllm言語教育部門・Chami)
      「これなんで配送は2時になるの？難しそうな話なので質問部屋に回してヴィルシーナ解説で。」
  - msg 1548006584809168931(同 01:25:30 JST・Chami)
      「優依に送った時には<:sendms:1527369203819085864> の絵文字スタンプつけないようにしてよ、
        あれClaude専用の処理だから」
  この2本が基盤の話題のままその部屋で処理され、09-12にヴィルシーナが配送の仕組みを
  **その部屋で説明した**(止血= DISPATCH-learning-coach-1789173269975 で学習の部門へ裏共有)。

★C-053(must-fail): ソースの文字列一致だけの保険にしない= **実際に封筒を組み立てて**検査し、
  さらに `--mutate`(ガードを外した版)を同じ検査に掛けて**赤くなること**まで確かめる。

使い方=
  python scripts/llm/test_room_scope_guard.py
  python scripts/llm/test_room_scope_guard.py --mutate
"""
import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import session_relay as sr        # noqa: E402

ROOM = "llm-edu"

# ★壊れた実物の本文(上のdocstringの2本)
BROKEN = {
    "配送2時": "これなんで配送は2時になるの？難しそうな話なので質問部屋に回してヴィルシーナ解説で。",
    "sendmsの印": ("優依に送った時には<:sendms:1527369203819085864> の絵文字スタンプ"
                   "つけないようにしてよ、あれClaude専用の処理だから"),
}
# ★この部屋の持ち場(IN)= 鳴ってはいけない本文(中野五月のspecのIN側から採った)
IN_BODY = "優依とqwenだと、どっちが速い？賢さと速さの割合は8:2くらいで見たい。"

MUST = ("職掌の外", "<<WORK>>", "弾いて回せ")


def _rec(body, author="chami_fusoh", from_dept=None, msg_id="TEST-1"):
    r = {"content": body, "author": author, "msg_id": msg_id,
         "channel": "ローカルllm言語教育部門", "ts": "2026-09-13T09:40:00"}
    if from_dept:
        r["from_dept"] = from_dept
    return r


def _mutant(rec, dept):
    """直しを外した版= 職掌を見ずに常に何も足さない(事故当時の挙動)。"""
    return ""


class R(object):
    def __init__(self):
        self.ok = 0
        self.ng = []

    def check(self, cond, label):
        if cond:
            self.ok += 1
        else:
            self.ng.append(label)


def run(guard):
    r = R()

    # ⓪ 表そのものが実在して、この部屋の行が引けること(検査の前提)
    tbl = sr._room_scope_table()
    r.check(bool(tbl), "部屋の職掌.json が読めない(検査の前提が壊れている)")
    r.check(ROOM in tbl, "%s の行が表に無い" % ROOM)
    row = tbl.get(ROOM) or {}
    r.check(len(row.get("out_words") or ()) >= 5, "out_words が薄すぎる(表が空)")

    # ① 壊れた実物= 必ず鳴る(Chami便は from_dept が無いので黙る発信元を素通りする)
    for name, body in BROKEN.items():
        t = guard(_rec(body), ROOM)
        r.check(bool(t), "[%s] 壊れた実物なのに注意が出ない" % name)
        for w in MUST:
            r.check(w in t, "[%s] 注意に「%s」が無い" % (name, w))
        r.check("プラットフォームSE" in t or "イージス研究室" in t,
                "[%s] 回す先が本文に出ていない" % name)
        # ★部門はスラッグではなく日本語名で出すこと(共通規律)
        r.check("platform-se" not in t and "aegis-gl" not in t,
                "[%s] 注意にスラッグが出ている(部門は日本語名)" % name)

    # ② この部屋の持ち場(IN)の便には**1文字も足さない**
    r.check(guard(_rec(IN_BODY), ROOM) == "",
            "持ち場(ローカルLLMの賢さ・速さ)の便で誤発火した")

    # ③ C-035= 表に行が無い部屋には1文字も足さない(名指しを全部屋へ広げない)
    for other in ("aegis-gl", "hq", "hr-room", ""):
        r.check(guard(_rec(BROKEN["配送2時"]), other) == "",
                "[%s] 表に無い部屋へ広がっている(C-035)" % (other or "(空)"))

    # ④ 回す先の部門自身からの便では鳴らさない(常に誤発火する安全網は無視される)
    for src in (row.get("黙る発信元") or ()):
        r.check(guard(_rec(BROKEN["配送2時"], author="ケヴィン・デブライネ",
                           from_dept=src), ROOM) == "",
                "[from_dept=%s] 回す先自身の便で鳴った" % src)
    # ★ただし他部門からの便では鳴る(③の抑止を広げすぎていないこと)
    r.check(bool(guard(_rec(BROKEN["配送2時"], author="十王星南",
                           from_dept="copy-director"), ROOM)),
            "回す先以外の部門からの便で鳴らない(抑止が広すぎる)")

    # ⑤ fail-open= 何を渡しても例外を出さない・便を握り潰さない
    for bad in (None, {}, {"content": None}, {"content": ""}, {"content": 123}):
        try:
            r.check(guard(bad, ROOM) == "", "壊れた rec %r で空にならない" % (bad,))
        except Exception as e:                           # noqa: BLE001
            r.ng.append("壊れた rec %r で例外が出た(%s)" % (bad, e))

    # ⑥ 封筒へ実際に載ること(関数単体ではなく**配線**を見る)
    env = sr.build_envelope(_rec(BROKEN["配送2時"], msg_id="TEST-ENV"),
                            is_work=True, state="", dept=ROOM,
                            disc_full=False, disc_fp="x",
                            verdict_full=False, verdict_fp="y")
    hit = bool(guard(_rec(BROKEN["配送2時"]), ROOM))
    r.check(("職掌の外" in env) == hit, "封筒に載っていない(build_envelope の配線が切れている)")
    r.check("--- 本文ここから ---" in env and BROKEN["配送2時"] in env,
            "本文が原文のまま入っていない(封筒が本文へ手を入れた)")
    # ★便は止まらない= 封筒はどの場合も組み上がる
    env_in = sr.build_envelope(_rec(IN_BODY), is_work=True, state="", dept=ROOM,
                               disc_full=False, disc_fp="x",
                               verdict_full=False, verdict_fp="y")
    r.check(IN_BODY in env_in, "持ち場の便で封筒が壊れた(fail-open違反)")

    # ⑦ 監査= 鳴った便が後から数えられる
    log = sr.SCOPE_GUARD_LOG
    n0 = _count(log)
    guard(_rec(BROKEN["配送2時"], msg_id="TEST-AUDIT"), ROOM)
    n1 = _count(log)
    r.check(n1 > n0 if hit else n1 == n0, "監査 scope_guard.jsonl が増えない")
    if hit and n1 > n0:
        last = _last(log)
        r.check(last.get("dept") == ROOM, "監査の dept が違う")
        r.check("配送" in "".join(last.get("当たった語") or ()), "監査に当たった語が残っていない")

    # ⑧ 表を空にしたら黙る(表が正本= コードに語を埋め込んでいないことの確認)
    orig = sr._room_scope_table
    try:
        sr._room_scope_table = lambda: {}
        r.check(guard(_rec(BROKEN["配送2時"]), ROOM) == "",
                "表が空でも鳴る= 語がコードへ埋め込まれている")
    finally:
        sr._room_scope_table = orig
    return r


def _count(p):
    try:
        return sum(1 for l in io.open(p, encoding="utf-8") if l.strip())
    except Exception:                                    # noqa: BLE001
        return 0


def _last(p):
    try:
        rows = [l for l in io.open(p, encoding="utf-8") if l.strip()]
        return json.loads(rows[-1])
    except Exception:                                    # noqa: BLE001
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true",
                    help="ガードを外した版で赤くなることを確かめる(C-053 must-fail)")
    a = ap.parse_args()
    # ★本番の監査台帳を検査で汚さない= 検査中だけ書き先を別ファイルへ向ける
    sr.SCOPE_GUARD_LOG = os.path.join(sr.LOCAL, "llm", "_test_scope_guard.jsonl")
    try:
        os.remove(sr.SCOPE_GUARD_LOG)
    except OSError:
        pass
    guard = _mutant if a.mutate else sr._scope_guard_hint
    if a.mutate:
        sr._scope_guard_hint = _mutant           # ★封筒側(⑥)も変異体で見る
    r = run(guard)
    for m in r.ng:
        print("FAIL:", m)
    print("%d PASS / %d FAIL" % (r.ok, len(r.ng)))
    if a.mutate:
        ok = len(r.ng) > 0
        print("must-fail:", "OK(変異体は赤くなった)" if ok else "NG(変異体が緑=検査が何も見ていない)")
        return 0 if ok else 1
    return 0 if not r.ng else 1


if __name__ == "__main__":
    sys.exit(main())
