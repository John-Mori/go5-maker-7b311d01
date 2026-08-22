#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C-050= 部門間の返信は「表は要点・裏に全文」。その判定と、削ってよい条件の検査。

なぜ要るか(2026-08-23・イージス研究室):
  Chami原文=「研究室HQと各研究室の長すぎるやり取りは裏で組んでくれればいいよ、実際自分読んでないし」。
  HQは dispatch(実依頼の表投稿)を front_digest で塞いだが、実測すると**それは表の16%**しかない:
    直近72時間の実チャンネル= bot/webhook発 216件 133,241字 / 【実依頼】は 15件 21,427字。
    残り84%は **部門の返信そのもの**(dept_daemon → persona_send)。
  ★実依頼と違い返信には**裏の完本が無い**=切ったら字が消える。だから
    「先に全文をファイルへ落としてから削る」が唯一許される形で、この検査はそこを固定する。

★must-fail 内蔵: 判定・切り詰め・fail-open を壊した版を同じ検査へ通し、**落ちること**を実証する。
"""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "llm"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import dept_daemon as dd  # noqa: E402

fails = []


def check(name, got, want):
    ok = (got == want)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        fails.append(name)


LIM = dd.REPLY_FRONT_LIMIT
LONG = "あ" * (LIM + 700)
SHORT = "短い返信だ。"

# ── 1. 誰の便か= 削ってよいのは他部門からの便への返信だけ ────────────
print("=== 1. 削ってよい便かの判定(is_interdept_letter) ===")
check("dispatch便は他部門から", dd.is_interdept_letter({"via": "dispatch"}), True)
check("Chamiの発言は削らない", dd.is_interdept_letter({"via": "gateway"}), False)
check("viaが無い便は削らない", dd.is_interdept_letter({"author": "chami"}), False)
check("recがNoneでも落ちない", dd.is_interdept_letter(None), False)
check("recが文字列でも落ちない", dd.is_interdept_letter("dispatch"), False)

# ── 1.5 ★宛先で見る= 削ってよいのは「AI同士の便だと差出人が宣言した便」だけ ─────
#   実物= 8/22の振り返り(1,646字)が author「定刻トリガー(朝5時)」(実物の値)・via=dispatch だったため
#   表から削られ、Chamiが「区切ってでも全文表示してよ」と言った(msg 1540819913097351218)。
#   ★2026-08-23 恒久(イージス研究室)= 止血は**差出人の名前**で当てていたが、名前の一覧に
#     当たらない新しいトリガーが出れば同じ事故が起きる。判定を**差出人の宣言**へ移した
#     (`dispatch.py --audience ai|chami`)。宣言が無ければ削らない(fail-open)。
#     名前当て(CHAMI_FACING_AUTHOR_HINTS)は**削らない側の保険**としてだけ残る=下で別に検査する。
print("=== 1.5 宛先の宣言で見る(may_trim_front) ===")
_REAL = {"via": "dispatch", "author": "ケヴィン・デ・ブライネ(イージス研究室)", "audience": "ai"}
_UNDECL = {"via": "dispatch", "author": "ケヴィン・デ・ブライネ(イージス研究室)"}
_TRIG = {"via": "dispatch", "author": "定刻トリガー(朝5時)", "audience": "chami"}
check("AI同士だと宣言した便は削ってよい", dd.may_trim_front(_REAL), True)
check("★宣言の無い便は削らない(fail-open)", dd.may_trim_front(_UNDECL), False)
check("★Chami向けと宣言した便は削らない", dd.may_trim_front(_TRIG), False)
check("宣言aiと差出人が矛盾したら削らない",
      dd.may_trim_front({"via": "dispatch", "author": "定刻トリガー(朝5時)", "audience": "ai"}), False)
check("front_fullが立っていれば削らない",
      dd.may_trim_front({"via": "dispatch", "author": "アメス", "front_full": True, "audience": "ai"}), False)
check("Chamiの発言は元々削らない", dd.may_trim_front({"via": "gateway", "audience": "ai"}), False)
check("recがNoneでも落ちない", dd.may_trim_front(None), False)
check("宣言の綴り違いは宣言なし扱い",
      dd.may_trim_front({"via": "dispatch", "author": "x", "audience": "AI同士"}), False)
# ★名前当ては「削らない側の保険」としてだけ生きている(消していないことをここで固定する)
print("=== 1.5b 名前当ては削らない側の保険としてだけ残す(is_chami_facing_letter) ===")
check("巡回・監視の名前はChami向けと見なす",
      dd.is_chami_facing_letter({"via": "dispatch", "author": "欠席監視(毎朝8時の自動巡回)"}), True)
check("scheduledの名前もChami向けと見なす",
      dd.is_chami_facing_letter({"via": "dispatch", "author": "self (scheduled daily review)"}), True)
check("宣言chamiは名前に関係なくChami向け",
      dd.is_chami_facing_letter({"via": "dispatch", "author": "アメス", "audience": "chami"}), True)
# ★must-fail= 差出人だけを見る旧版(is_interdept_letter)は、宣言の無い便を削ってしまう
check("must-fail: 旧版は宣言の無い便を削る", dd.is_interdept_letter(_UNDECL), True)
check("must-fail: 旧版は定刻トリガーの便を削る",
      dd.is_interdept_letter({"via": "dispatch", "author": "定刻トリガー(朝5時)"}), True)

# ── 2. 表へ出す形 ────────────────────────────────────────────────
print("=== 2. 表へ出す本文(reply_front_digest・純粋関数) ===")
check("短い返信はそのまま", dd.reply_front_digest(SHORT, "local/llm/thread/x.md"), SHORT)
check("ちょうどlimitはそのまま", dd.reply_front_digest("あ" * LIM, "p.md"), "あ" * LIM)
_d = dd.reply_front_digest(LONG, "local/llm/thread/aegis-gl/1_0.md")
check("長い返信は丸ごと載らない", LONG in _d, False)
check("表は小さい", len(_d) < LIM + 120, True)
check("全文の在りかを書く", "local/llm/thread/aegis-gl/1_0.md" in _d, True)
check("何字を裏へ回したか書く", f"{len(LONG) - LIM}字は裏" in _d, True)
# ★在りかが無い(裏に完本が作れなかった)時は**削らない**= 字を消さない
check("在りか空なら削らない", dd.reply_front_digest(LONG, ""), LONG)
check("在りかNoneなら削らない", dd.reply_front_digest(LONG, None), LONG)

# ── 3. 裏の完本を実際に書く ─────────────────────────────────────
print("=== 3. 裏(ファイル)へ全文が残るか ===")
_tmp = tempfile.mkdtemp(prefix="c050_")
_orig_dir = dd.REPLY_THREAD_DIR
try:
    dd.REPLY_THREAD_DIR = _tmp
    p = dd.write_reply_full("aegis-gl", "1540778224659988543", 0, LONG)
    check("パスを返す", bool(p), True)
    _abs = (p if os.path.isabs(p) else os.path.join(dd.ROOT, p)) if p else ""
    check("ファイルが実在する", os.path.exists(_abs), True)
    check("全文が1字も欠けていない",
          io.open(_abs, encoding="utf-8").read() == LONG, True)
    # 危ない msg_id でもディレクトリを飛び出さない(区切り文字は潰れて1個のファイル名になる)
    p2 = dd.write_reply_full("aegis-gl", "../../etc/passwd", 1, "x")
    check("危ないidでも書けている", bool(p2), True)
    _abs2 = os.path.realpath(p2 if os.path.isabs(p2) else os.path.join(dd.ROOT, p2))
    check("msg_idでスレッド置き場の外へ出ない",
          _abs2.startswith(os.path.realpath(_tmp)), True)
    check("区切り文字が名前に残っていない",
          ("/" in os.path.basename(_abs2)) or ("\\" in os.path.basename(_abs2)), False)

    # ★fail-open= 裏へ書けない時は "" を返す(呼び側が削らない側へ倒せる)
    dd.REPLY_THREAD_DIR = os.path.join(_tmp, "file_in_the_way", "sub")
    io.open(os.path.join(_tmp, "file_in_the_way"), "w", encoding="utf-8").write("x")
    check("書けない時は空を返す(fail-open)", dd.write_reply_full("d", "m", 0, "x"), "")
finally:
    dd.REPLY_THREAD_DIR = _orig_dir
    shutil.rmtree(_tmp, ignore_errors=True)

# ── 4. 合成= 送信合流点と同じ式を、本物のまま通す ───────────────────
print("=== 4. 合流点と同じ判定式(外へ出る手だけ持たない) ===")


def decide(rec, part, thread_dir, digest=None, gate=None, writer=None, failopen=True):
    """dept_daemon.py の送信ループと**同じ順序・同じ条件**。外へ出るのはファイル1本だけ。

    failopen=False は **must-fail 用**= 裏へ書けていないのに削る版(本物には無い枝)。
    """
    gate = gate or dd.may_trim_front
    digest = digest or dd.reply_front_digest
    writer = writer or dd.write_reply_full
    if gate(rec) and len((part or "").strip()) > dd.REPLY_FRONT_LIMIT:
        _o = dd.REPLY_THREAD_DIR
        dd.REPLY_THREAD_DIR = thread_dir
        try:
            full = writer("aegis-gl", "m1", 0, part)
        finally:
            dd.REPLY_THREAD_DIR = _o
        if full or not failopen:
            return digest(part, full)
    return part


_t2 = tempfile.mkdtemp(prefix="c050b_")
_AI = {"via": "dispatch", "audience": "ai"}          # AI同士だと差出人が宣言した便
try:
    out_hq = decide(_AI, LONG, _t2)
    check("他部門への長い返信は削られる", LONG in out_hq, False)
    check("その時も在りかが付く", "全文=" in out_hq, True)
    out_chami = decide({"via": "gateway"}, LONG, _t2)
    check("★Chamiへの長い返信は1字も削らない", out_chami, LONG)
    out_short = decide(_AI, SHORT, _t2)
    check("他部門でも短ければそのまま", out_short, SHORT)
    # ★恒久の核= 宣言の無い便は、合流点でも1字も削られない(2026-08-23)
    out_undecl = decide({"via": "dispatch", "author": "定刻トリガー(朝5時)"}, LONG, _t2)
    check("★宣言の無い便は合流点でも削られない", out_undecl, LONG)

    # ★must-fail A: 「Chamiかどうか」の門を壊す=全部削る版
    broken_all = decide({"via": "gateway"}, LONG, _t2, gate=lambda r: True)
    check("mustfail_門を壊すとChamiの返信まで削れる", LONG in broken_all, False)
    # ★must-fail A2: 宣言を見ない旧版の門に戻すと、宣言の無い便が削られる(8/22の事故の再現)
    broken_old = decide({"via": "dispatch", "author": "定刻トリガー(朝5時)"}, LONG, _t2,
                        gate=dd.is_interdept_letter)
    check("mustfail_旧版の門なら定刻トリガーの便が削れる", LONG in broken_old, False)
    # ★must-fail B: 切り詰めを外す=丸ごと表へ出る版
    broken_cut = decide(_AI, LONG, _t2, digest=lambda t, p, limit=LIM: t)
    check("mustfail_切り詰めを外すと丸ごと出る", LONG in broken_cut, True)
    # ★fail-open が効いている実証= 裏へ書けない時は、本物は**削らない**
    keep = decide(_AI, LONG, _t2, writer=lambda *a, **k: "")
    check("裏へ書けなければ削らない(fail-open)", keep, LONG)
    # ★must-fail C: その fail-open の枝を潰すと、裏無しで字が消えることを実証する
    broken_open = decide(_AI, LONG, _t2, failopen=False,
                         writer=lambda *a, **k: "",
                         digest=lambda t, p, limit=LIM: t[:limit])
    check("mustfail_fail-openを潰すと裏無しで字が消える", len(broken_open) < len(LONG), True)
    # ★戻っていることの実証(壊した版を持ち越していない)
    check("mustfail_後始末= 本物は元どおり", decide({"via": "gateway"}, LONG, _t2), LONG)
finally:
    shutil.rmtree(_t2, ignore_errors=True)

if __name__ == "__main__":
    print(f"\nFAIL — {len(fails)}件: {fails}" if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)
