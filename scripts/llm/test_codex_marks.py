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
    cr.codex_answer = lambda ch, content: (True, "")   # 生成成功・worktreeなし
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


if __name__ == "__main__":
    green = run("本番(全印)")
    # C-053 変異: 着手の配線を抜くと、実装依頼ケースが ["既読"] になって割れる(=歯がある)
    mut_ok = run("変異(着手を抜く=誤り)", skip_chakusyu=True)
    if mut_ok:
        print("  ※変異が全緑=このテストは着手漏れを捕まえられていない(歯が無い)")
    else:
        print("  ※変異で実装依頼ケースが赤=ガードに歯がある(期待どおり)")
    sys.exit(0 if green else 1)
