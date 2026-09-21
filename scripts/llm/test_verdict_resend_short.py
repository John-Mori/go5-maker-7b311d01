# -*- coding: utf-8 -*-
"""圧縮直後の便で「裁定の見出し85本」が再送されないこと(床の大掃除 案1)の回帰。

発注= 研究室HQ(アロンソ監督) msg 1551430783418245215 / 監査の正本= local/llm/_fable_floor_audit_result.md 案1

★測っているもの= 本物の `session_relay.verdict_plan()` と `build_envelope()` を実行で通す。
  偽物にするのは**外へ出る手だけ**= ここは1本も呼ばない(この試験はディスクへ1バイトも書かない)。

★must-fail(壊れたら赤くなることの確認)= `--mutant <名>` で挙動を壊して rc=1 を見る。
    plan_full_on_resend  : 圧縮直後を全文化の引き金へ戻す        → 層1が落ちる
    short_without_ids    : 短文から裁定番号の一覧を落とす        → 層2が落ちる
    no_recovery          : VERDICT_FULL_EVERY の保険を殺す      → 層3が落ちる
    disc_resend_removed  : 規律側の圧縮直後の全文再送まで外す    → 層4が落ちる

使い方:
    python scripts/llm/test_verdict_resend_short.py
    python scripts/llm/test_verdict_resend_short.py --mutant plan_full_on_resend
"""
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import session_relay as sr  # noqa: E402

_PASS = []
_FAIL = []


def ok(cond, label):
    (_PASS if cond else _FAIL).append(label)
    print(("  PASS " if cond else "  FAIL ") + label)


BODY = "床の固定費を測りたい。圧縮直後の封筒に裁定の見出しが全部並んでいないか見てくれ。"


def envelope(verdict_full, ids):
    """本物の build_envelope を1回通す(規律は3行側に固定=見たいのは裁定だけ)。"""
    rec = {"content": BODY, "author": "chami_fusoh", "msg_id": "TEST-VRS",
           "channel": "テスト部屋", "ts": "2026-09-21T12:00:00"}
    return sr.build_envelope(rec, is_work=False, state="", dept="aegis-gl",
                             disc_full=False, disc_fp="x",
                             verdict_full=verdict_full, verdict_fp="y",
                             verdict_added=(), verdict_ids=ids)


def run(mutant=""):
    heads_block, table, heads = sr.verdict_parts()
    if not heads or not table:
        print("SKIP 裁定カタログが読めない(この環境では測れない)")
        return 0
    ids = sr._verdict_ids(heads)
    fp = sr.verdict_fingerprint(heads)
    seen = {"verdict_ids": list(ids), "verdict_since_full": 2}

    # --- 層1 圧縮の直後でも裁定は全文にならない(案1の本体) ---------------------------
    full_re, added_re = sr.verdict_plan(seen, heads, table, "sid-1", True)
    ok(full_re is False, "層1-1 圧縮直後(resend=True)でも裁定は全文にならない")
    full_平時, _ = sr.verdict_plan(seen, heads, table, "sid-1", False)
    ok(full_平時 is False, "層1-2 平時も全文にならない(今までどおり)")
    ok(added_re == [], "層1-3 指紋が同じなら増えた分は空")

    # --- 層2 圧縮直後の短文には「裁定番号」が実物で載る(見出し本文は載らない) --------
    short = sr._verdict_short(fp, len(heads), [], ids=ids)
    ok(all(i in short for i in ids), "層2-1 短文に裁定番号が全部載る(計%d本)" % len(ids))
    ok("裁定カタログ.md" in short, "層2-2 短文に正本のパスが載る")
    ok(len(short) < len(heads_block) / 2,
       "層2-3 短文は見出し全文の半分未満(%d字 < %d字)" % (len(short), len(heads_block)))
    # 見出し本文(番号の後ろの文)が載っていないこと= 一番長い見出しの末尾30字で見る
    longest = max(heads, key=len)
    ok(longest[-30:] not in short, "層2-4 見出しの本文は短文に載らない")
    平時短文 = sr._verdict_short(fp, len(heads), [], ids=[])
    ok(all(i not in 平時短文 for i in ids[:5]),
       "層2-5 平時(ids無し)の短文は今までと同じ=番号を載せない")

    # --- 層3 回復路が生きている(ここが死ぬと裁定が永久に届かない) --------------------
    # ★保険の周期は**定数を読まずに固定値で**測る= 定数ごと殺されたら赤くしたい
    #   (10→10億にされても「VERDICT_FULL_EVERY便目で全文」は自明に真になってしまう)。
    ok(sr.VERDICT_FULL_EVERY <= 30,
       "層3-0 全文へ戻る周期が30便以内(現在 %d)" % sr.VERDICT_FULL_EVERY)
    ok(sr.verdict_plan({"verdict_ids": list(ids), "verdict_since_full": 30},
                       heads, table, "sid-1", False)[0] is True,
       "層3-1 30便以内に1回は保険で全文へ戻る")
    ok(sr.verdict_plan({"verdict_ids": ["C-999"], "verdict_since_full": 1},
                       heads, table, "sid-1", False)[0] is True,
       "層3-2 見出しが消えた/書き換わったら全文")
    ok(sr.verdict_plan(seen, heads, table, "", False)[0] is True,
       "層3-3 新セッションは全文")
    ok(sr.verdict_plan({}, heads, table, "sid-1", False)[0] is True,
       "層3-4 渡した記録が無い部屋は全文")
    ok(sr.verdict_plan(seen, [], table, "sid-1", False)[0] is True,
       "層3-5 見出しが読めない時は安全側(全文)へ倒す")
    added = sr.verdict_plan({"verdict_ids": list(ids[:-1]), "verdict_since_full": 1},
                            heads, table, "sid-1", False)[1]
    ok(len(added) == 1 and added[0] == heads[-1],
       "層3-6 増えた1本は実物で載る(差分送付は壊れていない)")

    # --- 層4 規律の全文再送は外していない(外すのは見出しだけ) ------------------------
    #   ★区切りは `disc_full = (` から次の `_disc_why` まで= ここが規律側の判定そのもの。
    #     `)\n` で切ると理由文まで飲み込んで、条件から外されても気づけない(実測で空振りした)。
    src = io.open(sr.__file__, encoding="utf-8").read()
    m = re.search(r"disc_full = \((.*?)_disc_why", src, re.S)
    ok(bool(m) and re.search(r"or\s+_resend", m.group(1) if m else ""),
       "層4-1 disc_full の条件に圧縮直後(_resend)が残っている")
    m2 = re.search(r"\n    full = bool\((.*?)\n    return full", src, re.S)
    ok(bool(m2) and "resend" not in (m2.group(1) if m2 else "x"),
       "層4-2 verdict_plan の全文条件から resend が外れている")

    # --- 層5 封筒を実際に組んで、載る/載らないを字面で確かめる -----------------------
    env_short = envelope(False, ids)
    env_full = envelope(True, ())
    ok(longest[-30:] in env_full, "層5-1 全文便には見出しの本文が載る")
    ok(longest[-30:] not in env_short, "層5-2 圧縮直後の短文便には見出しの本文が載らない")
    ok(all(i in env_short for i in ids), "層5-3 圧縮直後の短文便に裁定番号は載る")
    ok(table[:40] in env_short and table[:40] in env_full,
       "層5-4 C-015発注先の表は**どちらの便でも**毎便フル(C-060の裁定)")
    省 = len(env_full) - len(env_short)
    ok(省 > 2000, "層5-5 圧縮直後1便あたり %d字 減る" % 省)

    # --- 層6 この試験はディスクへ1バイトも書いていない --------------------------------
    for p in ("local/llm/room_sessions.json", "local/llm/request_log.jsonl",
              "local/llm/send_audit.jsonl"):
        f = os.path.join(_HERE, "..", "..", p)
        ok(not os.path.exists(f) or os.path.getmtime(f) < _T0,
           "層6 本番の台帳へ書いていない: " + p)

    print("\n== %d PASS / %d FAIL ==" % (len(_PASS), len(_FAIL)))
    return 1 if _FAIL else 0


def apply_mutant(name):
    """★挙動をわざと壊す(must-fail の確認用)。本番コードには1バイトも触らない。"""
    if name == "plan_full_on_resend":
        real = sr.verdict_plan
        sr.verdict_plan = lambda e, h, t, s, r: ((True, []) if r else real(e, h, t, s, r))
    elif name == "short_without_ids":
        real = sr._verdict_short
        sr._verdict_short = lambda fp, n, added, ids=(): real(fp, n, added, ids=())
    elif name == "no_recovery":
        sr.VERDICT_FULL_EVERY = 10 ** 9
    elif name == "disc_resend_removed":
        global _SRC_OVERRIDE
        _SRC_OVERRIDE = True
    else:
        print("unknown mutant: " + name)
        sys.exit(2)


_SRC_OVERRIDE = False
_T0 = 0.0

if __name__ == "__main__":
    _T0 = __import__("time").time()
    mut = ""
    if "--mutant" in sys.argv:
        mut = sys.argv[sys.argv.index("--mutant") + 1]
        apply_mutant(mut)
    if _SRC_OVERRIDE:
        # 規律側の resend を外した世界を、読む文字列の側で作る(ファイルは書き換えない)
        _real_open = io.open

        def _open(p, *a, **k):
            f = _real_open(p, *a, **k)
            if str(p).endswith("session_relay.py"):
                s = f.read().replace("or _resend                           # ③", "# ③")
                f.close()
                return io.StringIO(s)
            return f
        io.open = _open
    print("== 圧縮直後の裁定見出し再送を止める(案1) %s ==" %
          (("/ mutant=" + mut) if mut else ""))
    sys.exit(run(mut))
