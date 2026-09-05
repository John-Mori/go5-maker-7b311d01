# -*- coding: utf-8 -*-
"""test_codex_marks — Codex受付が Claude同様の進捗印(既読/着手/即答)を正しい節目で押すか実行で通す。

Chami依頼2026-09-05「Claud同様に既読と着手のスタンプに意味を把握して適応できるように」の受け入れ線=
  ・どの便もまず **既読**(掴んで読んだ)
  ・重い実装へ回す便は **着手**(codex_run を起こす直前)
  ・司令塔へ回して即返信で完結する便(機微部屋 / テキスト無し)は **即答**(着手は押さない)
Discordには触らない= codex_responder.mark を記録器へ、外向きの副作用(codex_answer/notify/escalate/log)を無害化する。
must-fail(C-053)= 着手の配線を抜くと「重い実装なのに着手が付かない」を機械が赤で捕まえる、も確かめる。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codex_responder as cr  # noqa: E402


def drive(rec, *, skip_chakusyu=False):
    """handle() を1通ぶん走らせ、押された印の並びを返す。Discord・生成は全て無害化する。"""
    calls = []
    orig = {k: getattr(cr, k) for k in
            ("mark", "codex_answer", "notify_room", "escalate", "append_line", "log")}
    cr.mark = lambda ch, mid, kind: (None if skip_chakusyu and kind == "着手"
                                     else calls.append(kind))
    cr.codex_answer = lambda ch, content: (True, "", "")   # 生成成功・worktreeなし・理由なし
    cr.notify_room = lambda ch, text: None
    cr.escalate = lambda ch, raw, note="": None
    cr.append_line = lambda path, line: None
    cr.log = lambda r: None
    try:
        cr.handle(rec, "{}")
    finally:
        for k, v in orig.items():
            setattr(cr, k, v)
    return calls


CASES = [
    # (rec, 期待する印の並び, 狙い)
    ({"content": "重い実装をして", "channel": "aegis-gl", "msg_id": "1",
      "dept": "codex"}, ["既読", "着手"], "実装依頼=既読→着手"),
    ({"content": "秘密の相談", "channel": "dream-care", "msg_id": "2",
      "dept": "dream-care"}, ["既読", "即答"], "機微部屋=既読→即答(着手なし)"),
    ({"content": "   ", "channel": "aegis-gl", "msg_id": "3",
      "dept": "codex"}, ["既読", "即答"], "テキスト無し=既読→即答(着手なし)"),
]


def run(label, skip_chakusyu=False):
    ok = True
    print(f"--- {label} ---")
    for rec, want, why in CASES:
        got = drive(rec, skip_chakusyu=skip_chakusyu)
        mark = "PASS" if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"  [{mark}] want={want} got={got}  {why}")
    return ok


def drive_fail(reason):
    """生成失敗(reason付き)で handle() を1通走らせ、部屋へ出た文面を返す。Discord・生成は無害化。

    ケヴィン発注(b)の受け入れ= 橋(Codex回線)の不通系 reason では『橋が落ちている』と分かる文面、
    依頼の中身に起因する失敗では従来文、を機械が選ぶこと。ここで実行で通す(§3=文字列一致だけにしない)。
    """
    posted = {"text": None}
    orig = {k: getattr(cr, k) for k in
            ("mark", "codex_answer", "notify_room", "escalate", "append_line", "log")}
    cr.mark = lambda ch, mid, kind: None
    cr.codex_answer = lambda ch, content: (False, "", reason)   # 生成失敗・理由=reason
    cr.notify_room = lambda ch, text: posted.__setitem__("text", text)
    cr.escalate = lambda ch, raw, note="": None
    cr.append_line = lambda path, line: None
    cr.log = lambda r: None
    try:
        cr.handle({"content": "重い実装をして", "channel": "aegis-gl", "msg_id": "9",
                   "dept": "codex"}, "{}")
    finally:
        for k, v in orig.items():
            setattr(cr, k, v)
    return posted["text"] or ""


def run_bridge_down():
    """(b)の受け入れ線を実行で通す。橋不通=橋文面 / 依頼起因=従来文。"""
    ok = True
    print("--- (b) 失敗文面の出し分け ---")
    # 橋(回線)の不通系= 版数切れ/認証断/config壊れ/timeout → 橋が落ちていると分かる文面
    for reason in ("not supported", "401", "Error loading config", "timeout"):
        text = drive_fail(reason)
        good = ("橋" in text and "依頼の中身の問題ではありません" in text)
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] reason={reason!r} → {text[:40]!r}")
    # 依頼の中身に起因する失敗(バケツ外)= 従来の受付箱回送文(橋のせいにしない)
    text = drive_fail("")
    generic = ("うまく処理できなかった" in text and "橋" not in text)
    ok = ok and generic
    print(f"  [{'PASS' if generic else 'FAIL'}] reason=''(不明) → {text[:40]!r}")
    return ok


if __name__ == "__main__":
    green = run("本番(全印)")
    # C-053 変異: 着手の配線を抜くと、実装依頼ケースが ["既読"] になって割れる(=歯がある)
    mut_ok = run("変異(着手を抜く=誤り)", skip_chakusyu=True)
    if mut_ok:
        print("  ※変異が全緑=このテストは着手漏れを捕まえられていない(歯が無い)")
    else:
        print("  ※変異で実装依頼ケースが赤=ガードに歯がある(期待どおり)")
    bd = run_bridge_down()      # (b) 橋不通の文面出し分け
    sys.exit(0 if (green and bd) else 1)
