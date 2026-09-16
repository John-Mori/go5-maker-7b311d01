#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_chami_identity — 「Chami判定の正本が1本か」を**実物の呼ばれ方で**確かめる検査。

★何を守る検査か(2026-09-16・研究室HQ 宿題1):
  同じ値の写しが3箇所に散っていた。ユーザ名かIDが変わった日に**直し忘れた1箇所が黙って誤判定**する。
  HQの注文は「**1箇所直せば済む**形にしたい」。だからこの検査の本体は T5 =
  **正本の値だけを書き換えて、3つの持ち場が全部それに従うことを実際に動かして見る**。
  文字列一致(ソースに import が在るか)では確かめない= それは配線の絵であって、呼ばれた証拠ではない。

★使い方
  python scripts/_common/test_chami_identity.py                 … 実物を検査(exit 0 で合格)
  python scripts/_common/test_chami_identity.py --aw <path> --rw <path> --cx <path>
                                                                … 差し替えた実装を検査(must-fail用)

★must-fail(C-053): local/_work/mustfail_chami_identity/ に
  「写しを手元へ戻しただけの、今日は正しく動く別実装」を置いて同じ検査を通し、**exit 1** になることを見る。
"""
import io
import os
import sys
import importlib.util

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import chami_identity  # noqa: E402

FAKE_ID = "999000111222333444"
FAKE_NAME = ("chami_renamed",)

FAILS = []
CHECKS = [0]


def ok(cond, label):
    CHECKS[0] += 1
    if cond:
        print(f"  PASS {label}")
    else:
        print(f"  FAIL {label}")
        FAILS.append(label)


def call(mod, func_name, *a):
    """持ち場のモジュールの関数を呼ぶ。関数ごと無い実装でも**落とさず** False を返す。

    ★must-fail の差し替え実装では関数が存在しない=そこで例外を投げると、後ろの検査が
      走らないまま「赤」になる。それでは**どこが赤いのか**が残らない。赤の理由を名前で残す。
    """
    f = getattr(mod, func_name, None)
    if f is None:
        return None
    return f(*a)


def load(path, name):
    """ファイルのパスから実物のモジュールを読み込む(must-fail の差し替えを同じ道で通すため)。"""
    # ★差し替え実装を別の場所へ置いても、実物と同じ隣人(scripts/llm・scripts/discord)を
    #   引けるようにしておく。ここを通さないと import 失敗で赤くなり、**判定の赤と区別が付かない**。
    for d in ("_common", "discord", "llm"):
        p = os.path.join(ROOT, "scripts", d)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    args = sys.argv[1:]
    paths = {
        "aw": os.path.join(ROOT, "scripts", "discord", "absence_watchdog.py"),
        "rw": os.path.join(ROOT, "scripts", "discord", "reaction_watch.py"),
        "cx": os.path.join(ROOT, "scripts", "llm", "codex_responder.py"),
    }
    for i, a in enumerate(args):
        key = a.lstrip("-")
        if key in paths and i + 1 < len(args):
            paths[key] = args[i + 1]
    for k, v in paths.items():
        print(f"対象 {k} = {v}")
    print()

    # ---- T1 正本の値そのもの --------------------------------------------------
    print("T1 正本の値(ここだけを直せば全部に効く、の『ここ』)")
    ok(chami_identity.CHAMI_USER_ID.isdigit(), "CHAMI_USER_ID が数値IDの文字列")
    ok(isinstance(chami_identity.CHAMI_USERNAMES, tuple) and
       all(n == n.lower() for n in chami_identity.CHAMI_USERNAMES),
       "CHAMI_USERNAMES は小文字で持っている(突き合わせも小文字)")

    # ---- T2 3つの入口の形をすべて吸収する -------------------------------------
    print("T2 入口の形が違っても同じ答えを返す")
    cid = chami_identity.CHAMI_USER_ID
    cname = chami_identity.CHAMI_USERNAMES[0]
    ok(chami_identity.from_chami({"author": cname, "author_id": cid}) is True,
       "① キューの便(author が文字列)")
    ok(chami_identity.from_chami({"author": {"id": cid, "username": cname}}) is True,
       "② Discord APIの投稿(author が辞書)")
    ok(chami_identity.is_chami_user({"id": cid, "username": cname}) is True,
       "③ Discord APIの人(リアクションを押した人)")
    ok(chami_identity.from_chami({"author": "otacon", "author_id": "123"}) is False,
       "他人(AI)の便は本人ではない")
    ok(chami_identity.from_chami({}) is False, "author も author_id も無い便は本人ではない")
    ok(chami_identity.from_chami(None) is False, "辞書ですらない入力で落ちない")
    ok(chami_identity.is_chami_user(None) is False, "人が None でも落ちない")
    ok(chami_identity.from_chami({"author": "  " + cname.upper() + " "}) is True,
       "大文字・前後の空白でも本人と読む")

    # ---- T3 ID が主・名前が従 --------------------------------------------------
    print("T3 名前は変わるがIDは変わらない= IDが主")
    ok(chami_identity.from_chami({"author": "別名にした", "author_id": cid}) is True,
       "名前が変わっていてもIDが一致すれば本人")
    ok(chami_identity.from_chami({"author": cname, "author_id": ""}) is True,
       "IDが載っていない便でも名前で拾える(取りこぼさない)")

    # ---- T4 3つの持ち場が引いているのが**この関数そのもの**か ------------------
    print("T4 一本化の実物(呼ばれる関数が正本と同一のオブジェクトか)")
    aw = load(paths["aw"], "t_absence_watchdog")
    rw = load(paths["rw"], "t_reaction_watch")
    cx = load(paths["cx"], "t_codex_responder")
    ok(getattr(aw, "is_chami_user", None) is chami_identity.is_chami_user,
       "absence_watchdog が呼ぶ is_chami_user は正本と同一")
    ok(getattr(rw, "is_chami_user", None) is chami_identity.is_chami_user,
       "reaction_watch が呼ぶ is_chami_user は正本と同一")
    ok(getattr(cx, "from_chami", None) is chami_identity.from_chami,
       "codex_responder が呼ぶ from_chami は正本と同一")
    for tag, mod in (("absence_watchdog", aw), ("reaction_watch", rw), ("codex_responder", cx)):
        for const in ("CHAMI_USERNAMES", "CHAMI_USER_ID"):
            got = getattr(mod, const, None)
            ok(got is None or got is getattr(chami_identity, const),
               f"{tag} に {const} の写しが無い(在るなら正本と同一物)")

    # ---- T5 本体= 正本の値だけ書き換えて、3つの持ち場が全部従うか --------------
    print("T5 『1箇所直せば済む』を実際に動かして見る(正本の値だけを差し替える)")
    old_id, old_names = chami_identity.CHAMI_USER_ID, chami_identity.CHAMI_USERNAMES
    now = 1_760_000_000.0
    ts = "2026-09-16T00:00:00+00:00"
    import datetime as _dt
    ts = _dt.datetime.fromtimestamp(now - 7200, _dt.timezone.utc).isoformat()
    old_msgs = [{"id": "100", "content": "ボス、これ見て", "timestamp": ts,
                 "author": {"id": old_id, "username": old_names[0]}}]
    new_msgs = [{"id": "100", "content": "ボス、これ見て", "timestamp": ts,
                 "author": {"id": FAKE_ID, "username": FAKE_NAME[0]}}]

    def waiting(msgs):
        """absence_watchdog が『Chamiが待っている』と読むか。関数ごと無い実装では None。"""
        v = call(aw, "unanswered_verdict", msgs, now, 1)
        return None if v is None else v[0]

    ok(waiting(old_msgs) is True,
       "差し替え前: absence_watchdog は旧IDの便を『Chamiが待っている』と読む")
    ok(call(rw, "is_chami_user", {"id": old_id, "username": old_names[0]}) is True,
       "差し替え前: reaction_watch は旧IDの印を本人が押したと読む")
    ok(call(cx, "from_chami", {"author": old_names[0], "author_id": old_id}) is True,
       "差し替え前: codex_responder は旧IDの便を本人と読む")
    ok(call(aw, "answered_since", old_msgs, "50") is False,
       "差し替え前: Chami自身の催促は返事に数えない")

    chami_identity.CHAMI_USER_ID = FAKE_ID
    chami_identity.CHAMI_USERNAMES = FAKE_NAME
    try:
        ok(waiting(new_msgs) is True,
           "差し替え後: absence_watchdog が新しい値に従う(1箇所直すだけで効いた)")
        ok(waiting(old_msgs) is False,
           "差し替え後: absence_watchdog は旧IDをもう本人と読まない")
        ok(call(aw, "answered_since", new_msgs, "50") is False,
           "差し替え後: answered_since も新しい値に従う")
        ok(call(rw, "is_chami_user", {"id": FAKE_ID, "username": FAKE_NAME[0]}) is True,
           "差し替え後: reaction_watch が新しい値に従う")
        ok(call(rw, "is_chami_user", {"id": old_id, "username": old_names[0]}) is False,
           "差し替え後: reaction_watch は旧IDをもう本人と読まない")
        ok(call(cx, "from_chami", {"author": FAKE_NAME[0], "author_id": FAKE_ID}) is True,
           "差し替え後: codex_responder が新しい値に従う")
        ok(call(cx, "from_chami", {"author": old_names[0], "author_id": old_id}) is False,
           "差し替え後: codex_responder は旧IDをもう本人と読まない")
    finally:
        chami_identity.CHAMI_USER_ID = old_id
        chami_identity.CHAMI_USERNAMES = old_names

    ok(chami_identity.CHAMI_USER_ID == old_id, "検査の後始末: 正本の値を元へ戻した")

    print()
    print(f"検査 {CHECKS[0]}件 / 失敗 {len(FAILS)}件")
    for f in FAILS:
        print(f"  × {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
