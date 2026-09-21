# -*- coding: utf-8 -*-
"""名乗り前の「英語の作業前置き」切り落とし(meta_strip.strip_preamble_leak)の回帰。

発注= 改善提案部門(トトリ) msg 1551430845766836227 / 出所= Chami msg 1551429691251101828
自室の OPEN= DEF-english-dump-mixed-lang-20260906(送信側の保険)

★測っているもの= 本物の `meta_strip.strip_preamble_leak` を実行で通す。
  本文は手打ちせず、**送信台帳 local/llm/send_audit.jsonl の実便**から引く(層2)。
  この試験はディスクへ1バイトも書かない。

★must-fail= `--mutant <名>` で挙動を壊して rc=1 を見る。
    two_words   : 英単語2語で切る(ゆるめる)     → 層3(誤爆)が落ちる
    no_guard    : 沈黙・フェンスの歯止めを外す   → 層4が落ちる
    always_cut  : 英語判定を捨てて常に1行切る    → 層1-2 / 層3 が落ちる

使い方:
    python scripts/llm/test_preamble_leak.py
    python scripts/llm/test_preamble_leak.py --mutant two_words
"""
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
import meta_strip as ms  # noqa: E402

_PASS = []
_FAIL = []
AUDIT = os.path.join(_ROOT, "local", "llm", "send_audit.jsonl")
検体 = "1551390481165058160"          # トトリのPDCA報告便(Chamiが指した実物)


def ok(cond, label):
    (_PASS if cond else _FAIL).append(label)
    print(("  PASS " if cond else "  FAIL ") + label)


def audit_bodies():
    """送信台帳の実便(本文付き)を全部返す= 誤爆は手打ちでなく実物で測る。"""
    out = []
    if not os.path.exists(AUDIT):
        return out
    with io.open(AUDIT, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:                    # noqa: BLE001
                continue
            b = r.get("body")
            if isinstance(b, str) and b.strip():
                out.append((str(r.get("msg_id", "")), str(r.get("persona", "")), b))
    return out


def run():
    # --- 層1 壊れた実物(検体)が実際に切れる ----------------------------------------
    rows = audit_bodies()
    本体 = next((b for mid, _p, b in rows if mid == 検体), None)
    if 本体 is None:
        print("SKIP 検体 %s が送信台帳に無い(この環境では測れない)" % 検体)
        return 0
    cut, hits = ms.strip_preamble_leak(本体)
    ok(bool(hits), "層1-1 検体 msg %s の前置きが切れる" % 検体)
    ok("Wiring confirmed correct" not in cut.splitlines()[0] if cut else False,
       "層1-2 切った後の1行目に英語の作業ノートが残らない")
    ok(len(cut.strip()) > 0 and len(cut) < len(本体), "層1-3 本文は残る(沈黙にならない)")
    ok(本体.replace(hits[0]["line"], "", 1).strip()[:40] in cut,
       "層1-4 前置きの後ろの本文は1文字も削れていない")

    # --- 層2 既存の検知器では**当たらない**ことを実物で示す(ここが新設の理由) --------
    ok(ms.detect_narration_leak(本体) is None,
       "層2-1 detect_narration_leak は検体を素通しする(3条件ANDの③で落ちる)")
    ok(any(w in 本体 for w in ms._VOICE_WORDS),
       "層2-2 素通しの理由= 声の痕跡が在る(_MACHINE_WORDS を足しても止まらない)")

    # --- 層3 台帳3,000便超の実物で誤爆が増えていないこと ------------------------------
    hit_rows = [(mid, p, ms.strip_preamble_leak(b)[1]) for mid, p, b in rows]
    hit_rows = [(mid, p, h) for mid, p, h in hit_rows if h]
    ok(len(rows) > 2000, "層3-0 母集団が実物(%d便)" % len(rows))
    ok(len(hit_rows) <= max(6, len(rows) // 400),
       "層3-1 当たりは台帳の0.25%%以内(%d便中 %d件)" % (len(rows), len(hit_rows)))
    ok(any(mid == 検体 for mid, _p, _h in hit_rows), "層3-2 その中に検体が入っている")
    # 2語版が誤爆した実物= ジェンティルドンナ「Release Gate は **APPROVED(直った)**。」
    ok(ms.strip_preamble_leak("Release Gate は **APPROVED(直った)**。\n次へ行く。")[1] == [],
       "層3-3 英語2語+日本語の正常便を切らない(3語に絞った理由)")
    ok(ms.strip_preamble_leak("[アメス]\nNow the reply と言いたくなるけどね。")[1] == [],
       "層3-4 1行目が名乗りなら触らない")
    ok(ms.strip_preamble_leak("OK。入れた。")[1] == [], "層3-5 英単語1語の日本語便を切らない")

    # --- 層4 歯止め(切って沈黙にしない / フェンスを跨がない / 日本語で止まる) ---------
    ok(ms.strip_preamble_leak("Now the room reply.")[1] == [],
       "層4-1 前置きしか無い便は切らない(沈黙を作らない)")
    ok(ms.strip_preamble_leak("Now the room reply.\n   \n\t")[1] == [],
       "層4-2 残りが空白だけでも切らない")
    ok(ms.strip_preamble_leak("```\nNow the room reply.\n```\n[トトリ]\n本文")[1] == [],
       "層4-3 コードフェンスの中は切らない")
    c4, h4 = ms.strip_preamble_leak("Now the ledger and commit.\n本文の1行目。\nNow again.")
    ok(len(h4) == 1 and c4.startswith("本文の1行目。") and "Now again." in c4,
       "層4-4 日本語が挟まったら手前で止まる(後ろの行は触らない)")
    for bad in (None, "", 12345, [], {"a": 1}):
        r = ms.strip_preamble_leak(bad)
        ok(isinstance(r, tuple) and len(r) == 2, "層4-5 壊れた入力でも例外を投げない: %r" % (bad,))

    # --- 層4.5 本文がまるごと前置きの形は「切る」ではなく「作り直し」へ回す -----------
    #   実物= デブライネ 09-05 msg 1545536969449144450 / アメス 09-15 msg 1549148706014503123
    only = [(mid, p) for mid, p, b in rows if ms.detect_preamble_only(b)]
    ok(any(mid == "1545536969449144450" for mid, _p in only),
       "層4.5-1 本文が前置きだけの実便を検知する(デブライネ 09-05)")
    ok(any(mid == "1549148706014503123" for mid, _p in only),
       "層4.5-2 本文が前置きだけの実便を検知する(アメス 09-15)")
    ok(len(only) <= max(6, len(rows) // 400),
       "層4.5-3 検知は台帳の0.25%%以内(%d便中 %d件)" % (len(rows), len(only)))
    ok(ms.detect_preamble_only(本体) is None,
       "層4.5-4 切れば直る便(検体)は作り直しへ回さない=二重処理しない")
    ok(ms.detect_preamble_only("[アメス]\nNow the reply.") is None,
       "層4.5-5 名乗りが在れば触らない")

    # --- 層5 名乗りが在る形でも、名乗りの手前だけを切る -------------------------------
    c5, h5 = ms.strip_preamble_leak("Now the room reply as De Bruyne.\n\n[ケヴィン・デブライネ]\n受けた。")
    ok(c5.startswith("[ケヴィン・デブライネ]") and len(h5) == 1,
       "層5-1 名乗りの手前で切り、名乗りから始まる")
    ok("受けた。" in c5, "層5-2 名乗りの後ろは1文字も削れていない")

    # --- 層7 常駐の関門(narration_gate)が新しい引き金を実際に拾う ---------------------
    #   ★純関数を単体で通すだけでは「配線した」ことにならない= 本物の関門を1回通す。
    try:
        import dept_daemon as dd                  # noqa: E402
        前置きだけ = "Now the remaining sections (header, 1, 3, 5, 6, 7, 8):"
        out, inf = dd.narration_gate(前置きだけ, regen=lambda: "[アメス]\nはい、これが本文よ。")
        ok(inf.get("hit1") is True and inf.get("reason") == "preamble_only",
           "層7-1 本文まるごと前置きを narration_gate が拾う")
        ok(inf.get("regenerated") is True and out.startswith("[アメス]"),
           "層7-2 1回だけ作り直して差し替わる")
        out2, inf2 = dd.narration_gate(前置きだけ, regen=None)
        ok(inf2.get("warned") is True and 前置きだけ in out2,
           "層7-3 作り直せない経路では警告付きで送る(沈黙にしない)")
        out3, inf3 = dd.narration_gate("[トトリ]\n受けた。今から見る。", regen=lambda: "x")
        ok(inf3.get("hit1") is False and out3.startswith("[トトリ]"),
           "層7-4 正常便は素通し(関門を足しても通常経路は変わらない)")
    except ImportError as e:                      # noqa: F841
        print("  SKIP 層7 dept_daemon を読めない(この環境では測れない)")

    # --- 層6 この試験はディスクへ1バイトも書いていない --------------------------------
    for p in ("local/llm/send_audit.jsonl", "local/llm/meta_audit.jsonl"):
        f = os.path.join(_ROOT, p)
        ok(not os.path.exists(f) or os.path.getmtime(f) < _T0,
           "層6 本番の台帳へ書いていない: " + p)

    print("\n当たった実便(%d件):" % len(hit_rows))
    for mid, p, h in hit_rows:
        print("  %-20s %-18s %s" % (mid, p[:18], h[0]["line"][:60]))
    print("\n== %d PASS / %d FAIL ==" % (len(_PASS), len(_FAIL)))
    return 1 if _FAIL else 0


def apply_mutant(name):
    """★挙動をわざと壊す(must-fail の確認用)。本番コードには1バイトも触らない。"""
    import re
    if name == "two_words":
        ms._PREAMBLE_EN_RE = re.compile(r"^[ \t　]*(?:[A-Za-z][A-Za-z'’\-]*\s+){1,}[A-Za-z][A-Za-z'’\-]*")
    elif name == "no_guard":
        def loose(text):
            s = str(text or "")
            lines = s.splitlines()
            if not lines or not ms._PREAMBLE_EN_RE.match(lines[0]):
                return s, []
            return "\n".join(lines[1:]), [{"marker": "preamble_leak", "line": lines[0]}]
        ms.strip_preamble_leak = loose
    elif name == "always_cut":
        def always(text):
            s = str(text or "")
            lines = s.splitlines()
            if len(lines) < 2:
                return s, []
            return "\n".join(lines[1:]), [{"marker": "preamble_leak", "line": lines[0]}]
        ms.strip_preamble_leak = always
    else:
        print("unknown mutant: " + name)
        sys.exit(2)


_T0 = 0.0

if __name__ == "__main__":
    _T0 = __import__("time").time()
    mut = ""
    if "--mutant" in sys.argv:
        mut = sys.argv[sys.argv.index("--mutant") + 1]
        apply_mutant(mut)
    print("== 名乗り前の英語作業前置きの切り落とし %s ==" % (("/ mutant=" + mut) if mut else ""))
    sys.exit(run())
