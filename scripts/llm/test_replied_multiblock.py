# -*- coding: utf-8 -*-
"""1件の返信が人格ごとのブロックに割れた時、着地msg_idを**全部**記帳することの回帰ガード
(HQ-0242・2026-09-05・イージス研究室)。

何を守るか:
  hq の部屋は1件の返信が シャビ・アロンソ + アメス の2ブロックで出る。
  `dept_daemon` は `_last_sent`(=最後のブロック)しか `verify_replied` へ渡しておらず、
  台帳に残る着地msg_idは**短い方の相槌1通だけ**になっていた。本文を読み返す側
  (`completion_notify`・C-071)は答えの本文に辿り着けない。
  実物3件(HQが request_log / send_audit で裏取り)=
    06:09:01 1,207字 / 06:09:02 141字 ← 後者が `replied`
    06:10:41   502字 / 06:10:42  79字
    06:46:13 1,370字 / 06:46:14 116字
  台帳全体の実測= 送信台帳で本文を引けた `replied` 346行中53行が多ブロック。
  実在するパスは**兄弟の投稿側に9本・記帳された側に0本**。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 偽物にするのは**外へ出る手**だけ= DiscordへのHTTP GET と、トークン/チャンネル表の読み先。
    突合・分岐・evidenceの組み立ては**本物を実行する**。
  - 最後に must-fail= 変更前の呼び方(=others を渡さない)へ戻し、この検査が**落ちる**ことを確かめる。

★ok の判定は変えていないことも同時に守る= 兄弟が引けなくても `replied_unverified` へ
  落とさない(fail-open・ORG-42「確認できない≠届いていない」)。

実行: python scripts/llm/test_replied_multiblock.py
"""
import ast
import io
import json
import os
import shutil
import sys
import tempfile

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
DAEMON = os.path.join(HERE, "dept_daemon.py")

TMP = tempfile.mkdtemp(prefix="hq0242_")
os.environ["GO5_LOCAL_DIR"] = os.path.join(TMP, "local")
os.makedirs(os.path.join(TMP, "local", "llm"), exist_ok=True)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))

import dept_daemon as dd            # noqa: E402
import completion_notify as cn      # noqa: E402

FAIL = []
CH = "研究室HQ"
CID = "999000222"
MID_LONG = "1545541223740346520"    # アロンソ 1,207字(実物のid)
MID_SHORT = "1545541229025169438"   # アメス   141字(実物のid・これだけが記帳されていた)

# ★外へ出る手だけ偽物にする= トークンとチャンネル表の読み先を temp へ寄せる。
dd.LOCAL = os.path.join(TMP, "local")
with open(os.path.join(dd.LOCAL, "discord_bot_token.txt"), "w", encoding="utf-8") as _f:
    _f.write("DUMMY_NOT_A_TOKEN\n")
with open(os.path.join(dd.LOCAL, "discord_channels.json"), "w", encoding="utf-8") as _f:
    json.dump([{"name": CH, "dept": "hq", "id": CID}], _f, ensure_ascii=False)

# 実物と同じ形= 長い答え(置き場のパスを含む)+ 1秒後の短い相槌
BLOCK_LONG = ("[シャビ・アロンソ] HQ-0242の実測を置いた。3件とも `salvaged` を経ていない。\n"
              "置き場= `docs/設計・調査/イージス研究室_引き継ぎ退避_20260905.md` の §P-9。\n"
              "読む順は §P-9a → §P-9b でいい。")
BLOCK_SHORT = "[アメス] アンタは何もしなくていいわよ。こっちで見ておくから。"


def ok(cond, name, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def with_messages(msgs, fn):
    """Discordの直近取得だけ偽物にして、`verify_replied` を本物のまま走らせる。"""
    import urllib.request as u
    real = u.urlopen
    calls = []

    def _fake(req, timeout=None):
        calls.append(getattr(req, "full_url", ""))
        return _Resp(msgs)
    u.urlopen = _fake
    try:
        return fn(), calls
    finally:
        u.urlopen = real


def msg(mid, content):
    return {"id": mid, "content": content}


ROOM = [msg("1545541230000000000", "(誰かの雑談)"),
        msg(MID_SHORT, BLOCK_SHORT),
        msg(MID_LONG, BLOCK_LONG)]


# ---------------------------------------------------------------- W 書く側(dept_daemon)
def w_multiblock(others=(BLOCK_LONG,), msgs=None, quiet=False):
    (res, _c) = with_messages(ROOM if msgs is None else msgs,
                              lambda: dd.verify_replied(CH, BLOCK_SHORT, others))
    return res


def t_writer():
    print("W 書く側= 同じ返信の他ブロックの着地msg_idも evidence に残す")
    okd, ev = w_multiblock()
    ok(okd is True, "W-1 ok の判定は従来どおり(最後のブロックが実在すれば replied)")
    ids = cn.landed_ids(ev)
    ok(ids == [MID_LONG, MID_SHORT],
       "W-2 ★兄弟(長い答え)と最終通の両方が evidence に載る", " / ".join(ids))
    ok("他ブロック1通も実在確認" in ev, "W-3 何通拾ったかが evidence の言葉にも残る", ev[-40:])

    # 兄弟がDiscord側で引けない= 拾えないだけ。ok は落とさない(fail-open・ORG-42)
    okd, ev = w_multiblock(msgs=[msg(MID_SHORT, BLOCK_SHORT)])
    ok(okd is True and cn.landed_ids(ev) == [MID_SHORT],
       "W-4 兄弟が引けなくても replied のまま(確認を厳しくして黙らせない)", ev[:60])

    # 同じ文面のブロックを2つ渡しても、同じidを2回並べない
    okd, ev = w_multiblock(others=(BLOCK_LONG, BLOCK_LONG))
    ok(cn.landed_ids(ev) == [MID_LONG, MID_SHORT], "W-5 同じidは重複させない",
       " / ".join(cn.landed_ids(ev)))

    # 旧い呼び方(others 無し)でも落ちない= 1本のまま通る(後方互換)
    okd, ev = w_multiblock(others=())
    ok(okd is True and cn.landed_ids(ev) == [MID_SHORT],
       "W-6 others を渡さない呼び方も従来どおり動く(後方互換)")

    # 最終ブロックが見つからない時は従来どおり ok=False(判定を緩めていない)
    okd, ev = w_multiblock(msgs=[msg(MID_LONG, BLOCK_LONG)])
    ok(okd is False and "見当たらない" in ev,
       "W-7 最終ブロックが実在しなければ従来どおり ok=False", ev[:50])

    # APIは1回しか叩かない= 確認で配送を遅らせない
    (_r, calls) = with_messages(ROOM, lambda: dd.verify_replied(CH, BLOCK_SHORT, (BLOCK_LONG,)))
    ok(len(calls) == 1, "W-8 兄弟のためにAPIを叩き直さない(取得は1回)", "%d回" % len(calls))


# ---------------------------------------------------------------- R 読む側の継ぎ目
def t_reader_seam():
    print("R 読む側= 書いた evidence をそのまま全部の本文として引ける")
    okd, ev = w_multiblock()
    ok(cn.landed_msg(ev) == "%s,%s" % (MID_LONG, MID_SHORT),
       "R-1 landed_msg は台帳の字面のまま返す(カンマ連結)", cn.landed_msg(ev))
    ok(cn.landed_ids("discord_msg=7001 部屋=どこか") == ["7001"],
       "R-2 1本だけの古い行もそのまま通る")
    ok(cn.landed_ids("state=replied 記録なし") == [],
       "R-3 着地不明(`-`)は id として拾わない", str(cn.landed_ids("state=replied 記録なし")))


# ------------------------------------------------ S ブロック自体が更に複数通へ割れる場合
# ★2026-09-05 追補(モドリッチ申し送り・研究室HQ経由 DISPATCH-aegis-gl-1788563771724)。
#   `_verify_siblings` は各ブロックの**最終片1通**しか突合していなかった。
#   人格ブロックが `split_body` で2通以上へ割れると、**中間の通が台帳に載らない**=
#   本文を読み返す側(completion_notify・C-071)がその通を読めない。
SIB_LONG = ("[シャビ・アロンソ] 置き場= `docs/設計・調査/イージス研究室_長文.md`。\n"
            + ("あ" * 1500) + "\n\n" + ("い" * 1500) + "\n\n締め= §P-9b まで読め。")
OWN_LONG = ("[アメス] " + ("う" * 1500) + "\n\n" + ("え" * 1200) + "\n\nここが最終片よ。")


def _old_style_ids(msgs, others):
    """★must-fail 用= 直す前の突合(ブロックごとに**最終片だけ**見る)を、動く形で書き戻したもの。

    C-053= 「壊した側」は本物を壊さず、別の動く実装として置く。
    """
    out, seen = [], set()
    for txt in others or ():
        part, _n = dd._split_like_persona_send(txt)
        n = dd._norm_for_match(part)
        h, t = n[:dd.REPLIED_HEAD_CHARS], n[-dd.REPLIED_TAIL_CHARS:]
        if not h:
            continue
        for m in msgs or []:
            c = dd._norm_for_match(m.get("content"))
            if c and h in c and t in c:
                mid = str(m.get("id", ""))
                if mid and mid not in seen:
                    seen.add(mid)
                    out.append(mid)
                break
    return out


def _room_for(sib_text, own_text):
    """兄弟ブロックと自分のブロックを、送信側と同じ切り方で1通ずつ部屋へ並べる。"""
    sib = dd._split_parts_like_persona_send(sib_text)
    own = dd._split_parts_like_persona_send(own_text)
    room, ids = [], []
    base = 1545590000000000000
    for i, p in enumerate(sib + own):
        mid = str(base + i)
        ids.append(mid)
        room.append(msg(mid, p))
    return room, ids, len(sib), len(own)


def t_sibling_split():
    print("S ブロックが更に複数通へ割れても、中間の通まで記帳する")
    room, ids, nsib, nown = _room_for(SIB_LONG, BLOCK_SHORT)
    ok(nsib >= 2, "S-0 前提= 兄弟ブロックが実際に複数通へ割れている", "%d通" % nsib)
    (okd, ev) = with_messages(room, lambda: dd.verify_replied(CH, BLOCK_SHORT, (SIB_LONG,)))[0]
    got = cn.landed_ids(ev)
    ok(okd is True, "S-1 ok の判定は動かない(最終片が実在すれば replied)")
    ok(got == ids, "S-2 ★兄弟の**全通**が投稿順で載る", "期待%d通 / 実際%d通" % (len(ids), len(got)))

    print("S' 自分(最後のブロック)が割れた時も、最終片より前の通を落とさない")
    room2, ids2, _ns, no2 = _room_for(SIB_LONG, OWN_LONG)
    ok(no2 >= 2, "S'-0 前提= 自分のブロックも複数通へ割れている", "%d通" % no2)
    (okd2, ev2) = with_messages(room2, lambda: dd.verify_replied(CH, OWN_LONG, (SIB_LONG,)))[0]
    got2 = cn.landed_ids(ev2)
    ok(okd2 is True, "S'-1 ok の判定は動かない")
    ok(got2 == ids2, "S'-2 ★自分の前半の通も載る", "期待%d通 / 実際%d通" % (len(ids2), len(got2)))

    print("S'' MUST-FAIL 直す前の突合(最終片だけ)へ戻すと中間の通が消えるか")
    old = _old_style_ids(room, (SIB_LONG,))
    ok(len(old) < nsib, "S''-1 旧実装は兄弟の最終片1通しか拾えない",
       "旧%d通 / 実際は%d通ある" % (len(old), nsib))
    ok(any(i not in old for i in ids[:nsib]),
       "S''-2 旧実装では中間の通が台帳から落ちる(C-071が読めない形)")


# ---------------------------------------------------------------- 配線(呼び出し側)
def t_wiring():
    print("配線= 送信ループが他ブロックを渡している(構文木で確認)")
    tree = ast.parse(open(DAEMON, encoding="utf-8").read())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "verify_replied"]
    ok(bool(calls) and all(len(c.args) >= 3 for c in calls),
       "★呼び出しは3引数(最後のブロック+他のブロック)", "%d箇所" % len(calls))
    appends = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "append"
               and getattr(getattr(n.func, "value", None), "id", "") == "_sent_parts"]
    ok(bool(appends), "★送ったブロックを1通ずつ貯めている(_sent_parts)")


# ---------------------------------------------------------------- must-fail
def must_fail():
    print("MUST-FAIL 変更前の呼び方(=最後の1通しか渡さない)へ戻すと落ちるか")
    okd, ev = w_multiblock(others=())
    ok(okd is True and cn.landed_ids(ev) != [MID_LONG, MID_SHORT],
       "M1 others を渡さない旧実装では W-2(両方載る)を満たせない", " / ".join(cn.landed_ids(ev)))
    # 旧実装の evidence を読む側へ通すと、答えの本文(=置き場のパス)に辿り着けない
    ok(cn.landed_ids(ev) == [MID_SHORT],
       "M2 旧実装が残すのは短い相槌の1通だけ= C-071 が空振りしていた形", MID_SHORT)


if __name__ == "__main__":
    try:
        t_writer()
        t_reader_seam()
        t_sibling_split()
        t_wiring()
        must_fail()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f_ in FAIL:
        print("  - " + f_)
    sys.exit(1 if FAIL else 0)
