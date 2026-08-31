# -*- coding: utf-8 -*-
"""単独人格部屋の**名乗りタグ漏れ**(乙)を落とす(イージス研究室 / 2026-08-31)。

場面(実物)= ローカルLLM質問部屋(llm-qa=中野五月・personas 無し)の返信の1行目が `[中野五月]`。
  `local/_daemon_reply_llm-qa.txt`(半角[]・括弧は欠けていない=甲とは別の穴)。
  Chami「名乗りが多いね、ローカルllm質問部屋も五月が最初に名乗りがちだし。やめてよ」
  (msg 1543952785106669618)/ 型と回送= 改善提案部門トトリ msg 1543954248377696258。
  根因= 名乗りを剥がす手は split_persona_blocks の中にしか無く、その split は
  `personas` を持つ部屋でしか呼ばれない= 単独人格部屋では**剥がす処理が一度も走らない**。

★C-053= 壊した側は**動く別の実装**であること。
  ここでの「別実装」= **2026-08-31より前の本物そのもの**= 単独部屋は `[(None, reply)]` で
  そのまま出す経路。それ自体は正しく動く(本文を1文字も壊さない・宛名も既定で正しい)。
  足りないのは「1行目の名乗りタグを落とす」一点だけだ。

    python tests/test_persona_tag_solo.py
"""
import io
import json
import os
import sys
import tempfile

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PJ, "scripts", "llm"))
import dept_daemon as dd                    # noqa: E402
import persona_render                       # noqa: E402

# 実際の llm-qa の形(personas は持たない=単独人格部屋)
CONF = {"persona": "中野五月"}
DEPT = "llm-qa"


def solo_old(reply, conf=CONF, dept=DEPT):
    """動く別実装= 8/31より前の本番の経路(単独部屋は素通し)。戻り値は呼び元と同じ blocks。"""
    return [(None, reply)]


def solo_new(reply, conf=CONF, dept=DEPT):
    """今の本番の経路(dept_daemon.py の呼び出し元と同じ組み立て)。"""
    return [(None, dd.strip_solo_persona_tag(
        reply, dd.solo_tag_resolver(conf, conf["persona"]), dept=dept))]


def sent_name(blocks, persona=CONF["persona"]):
    """実際にDiscordへ渡る名義(`--persona (_who or effective_persona())` と同じ式)。"""
    return [(w or persona) for w, _b in blocks]


def audit_of(fn):
    """監査の**本物の書き手**(persona_render._audit)を通し、書かれた行を読み返す。

    ★偽物にするのは**外へ出る手=書き込み先のパスだけ**。判定も分岐も本物のまま回す(§3)。
    """
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    keep = persona_render.RENDER_AUDIT
    persona_render.RENDER_AUDIT = path
    try:
        got = fn()
    finally:
        persona_render.RENDER_AUDIT = keep
    rows = []
    for ln in io.open(path, encoding="utf-8"):
        if ln.strip():
            rows.append(json.loads(ln))
    os.remove(path)
    return got, rows


def main():
    ok = []
    BROKEN = "[中野五月]\nごめん、ちゃみ。そのリンク、私からは中身を開けないんだ。"

    # 1) ★must-fail: 旧経路はタグを落とせない(本文の頭に `[中野五月]` が残る)。新経路は落ちる。
    old = solo_old(BROKEN)
    assert old == [(None, BROKEN)], "前提が崩れた(旧経路が本文を触っている): %r" % (old,)
    assert "[中野五月]" in old[0][1], "前提が崩れた(旧経路でタグが消えている): %r" % (old,)
    got, rows = audit_of(lambda: solo_new(BROKEN))
    assert "[中野五月]" not in got[0][1], "本文の頭にタグが残っている: %r" % (got[0][1],)
    assert got[0][1].startswith("ごめん、ちゃみ。"), "本文を削りすぎ/残しすぎ: %r" % (got[0][1],)
    assert sent_name(got) == ["中野五月"], "宛名が中野五月でない: %r" % (sent_name(got),)
    ok.append("[中野五月]+本文= 宛名は中野五月のまま・本文の頭からタグが消える")

    # 2) その1件が**監査に残る**(片方だけでは「便が来ていないだけ」と区別できない=C-041)
    assert [r["outcome"] for r in rows] == ["tag_solo_fixed"], \
        "落とした回数が監査に残っていない: %r" % (rows,)
    assert rows[0]["dept"] == DEPT and rows[0]["persona"] == "中野五月", \
        "監査の部門/人格が違う: %r" % (rows[0],)
    ok.append("落とした1件が tag_solo_fixed(dept/persona付き)で残る")

    # 3) 同じ行に本文が続く形も落とす(`[中野五月] 本文`)
    SAME = "[中野五月] 分かった、そこは私が見ておくね。\n続きは明日でいい?"
    got, _ = audit_of(lambda: solo_new(SAME))
    assert got[0][1].startswith("分かった、"), "同一行の本文が壊れた: %r" % (got[0][1],)
    assert got[0][1].endswith("続きは明日でいい?"), "2行目以降が落ちた: %r" % (got[0][1],)
    ok.append("`[名前] 本文`(同一行)でも本文だけが残る")

    # 4) ★回帰: 既定persona名で**ない** `[誰か]` は剥がさない(本文かもしれない=沈黙させない)
    NOISE = "[検証] まずは前提を並べる。\n次に測る。"
    got, rows = audit_of(lambda: solo_new(NOISE))
    assert got == solo_old(NOISE), "この部屋の人でないタグを勝手に剥がした: %r" % (got,)
    assert rows == [], "本文でしかない `[検証]` を監査へ書いている(騒がしい): %r" % (rows,)
    ok.append("既定persona名でない `[検証]` は剥がさない・監査にも出さない")

    # 5) ただし**他の部屋の人格名**だったら、剥がさずに漏れとして数える
    #    (persona_avatars.json に実在するキーを使う= 台帳が変われば前提も変わる)
    assert "花海咲季" in dd._avatar_keys(), \
        "前提が崩れた(persona_avatars.json に花海咲季が無い)"
    OTHER = "[花海咲季]\nこっちは終わったわよ。"
    got, rows = audit_of(lambda: solo_new(OTHER))
    assert got == solo_old(OTHER), "他人格のタグを剥がした(誰の言葉か機械には決められない): %r" % (got,)
    assert [r["outcome"] for r in rows] == ["tag_solo_leak"], \
        "残った漏れが監査に残っていない: %r" % (rows,)
    ok.append("他人格の `[花海咲季]` は剥がさず tag_solo_leak で数える")

    # 6) 敬称の揺れ(`[中野五月さん]`)も同じ1人に解決して落とす
    HON = "[中野五月さん]\nうん、それで合ってるよ。"
    got, _ = audit_of(lambda: solo_new(HON))
    assert got[0][1] == "うん、それで合ってるよ。", "敬称付きの名乗りが落ちていない: %r" % (got[0][1],)
    ok.append("敬称の揺れ `[中野五月さん]` も落とす(_name_forms を共有)")

    # 7) ★fail-open: 落とすと本文が空になる便は**1文字も触らない**(沈黙させない)
    EMPTY = "[中野五月]"
    got, rows = audit_of(lambda: solo_new(EMPTY))
    assert got == solo_old(EMPTY), "落とした結果が空なのに落とした(沈黙する): %r" % (got,)
    assert rows == [], "落としていないのに fixed を数えている: %r" % (rows,)
    ok.append("落とすと空になる便は触らない(沈黙させない)")

    # 8) ★回帰: 名簿のある部屋の解決(resolve_persona_tag)は一字も変わらない
    #    = _name_forms を切り出した副作用が無いこと(敬称落とし/愛称の優先順)
    ROSTER = {"personas": [{"persona": "ジェンティルドンナ",
                            "aliases": ("gentildonna", "ドンナ", "ドンちゃん", "ドンさん")}]}
    for src, want in (("ジェンティルドンナ", "ジェンティルドンナ"),
                      ("ドンちゃん", "ジェンティルドンナ"),      # 愛称そのものが別名(先に敬称を落とすと引けない)
                      ("ドンさん", "ジェンティルドンナ"),
                      ("GENTILDONNA", "ジェンティルドンナ"),     # 大文字小文字は無視
                      ("ドンナさん", "ジェンティルドンナ"),      # 敬称を1つ落として再試行
                      ("知らない人", None)):
        assert dd.resolve_persona_tag(ROSTER, src) == want, \
            "名簿のある部屋の解決が変わった: %r → %r" % (src, dd.resolve_persona_tag(ROSTER, src))
    ok.append("名簿のある部屋の解決(敬称・愛称・大小文字)は従来どおり")

    # 9) ★実物の形: 前置き1行 → 空行 → タグ(hr-room/platform-se の現用バッファと同じ並び)
    #    1行目だけを見る実装ではこの2室に届かない= 前置きごと落とし、前置きは監査へ残す。
    PRE = ("五月の呼び方変更=完了(入れた・確認待ち)。change_log追記済。\n"
           "\n"
           "[中野五月]\n"
           "呼び方、Chamiくんに変えといたよ。")
    got, rows = audit_of(lambda: solo_new(PRE))
    assert got[0][1] == "呼び方、Chamiくんに変えといたよ。", "前置き+タグが落ちていない: %r" % (got[0][1],)
    assert [r["outcome"] for r in rows] == ["preamble_dropped", "tag_solo_fixed"], \
        "前置きとタグの両方が監査に残っていない: %r" % (rows,)
    assert "呼び方変更" in rows[0]["detail"], "落とした前置きの中身が残っていない: %r" % (rows[0],)
    ok.append("前置き1行+空行+タグ= 前置きごと落とし、前置きは全文を監査に残す")

    # 10) ★深い位置のタグは前置きでなく**本文中の引用**= 手前の本文を消さない(漏れより重い事故)
    DEEP = ("結論から言う。\nまず1つ目。\n次に2つ目。\n最後に3つ目。\n"
            "壊れていた実物はこれだ:\n[中野五月]\nごめん、ちゃみ。")
    got, rows = audit_of(lambda: solo_new(DEEP))
    assert got == solo_old(DEEP), "引用のタグを拾って本文を丸ごと消した: %r" % (got,)
    assert rows == [], "触っていないのに監査へ書いている: %r" % (rows,)
    ok.append("深い位置のタグ(引用)は拾わない= 手前の本文を消さない")

    # 11) 前置きが在っても**この部屋の人でない**タグなら触らない(誤爆させない)
    PRE_OTHER = "着手する。\n\n[花海咲季]\nこっちは終わったわよ。"
    got, rows = audit_of(lambda: solo_new(PRE_OTHER))
    assert got == solo_old(PRE_OTHER), "他人格のタグで前置きごと消した: %r" % (got,)
    assert rows == [], "1行目がタグでないのに leak を数えている: %r" % (rows,)
    ok.append("前置きの先が他人格のタグなら1文字も触らない")

    print("\n".join("PASS  " + s for s in ok))
    print("%d/%d PASS" % (len(ok), len(ok)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
