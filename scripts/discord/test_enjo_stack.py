#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔥(炎上)が台帳から消える穴を**実行で**塞いだことの検査(2026-08-14 イージス研究室)。

なぜ要るか= 2026-08-14 の巡回を台帳と突き合わせた実測=
    Chamiがスタンプを押した投稿は 14件。うち **11件は🔥と再発が両方**押されていた。
    台帳は msg_id で1件に畳むので、**先に処理した方のスタンプだけが source に残る**。
    結果 **11件中10件が「再発」として積まれ、🔥が消えていた**。
  🔥は「恒久対策まで行け」(C-038/C-040)= 再発より重い。消えれば重さが下がり、
  巡回が求める「**恒久対策が入っていない炎上の件数**」は永久に間違った数を出す。
  巡回の本文が「★3種類は別物だ。混ぜて数えるな」と言っている以上、台帳の側でも混ぜない。

やり方= 外へ出る手(台帳の書き先)だけ偽物にし、**判定と分岐は本物のまま**回す(共通規律§3)。
  差し替え点= `session_relay.set_defects_path()`。本番の `open_defects.jsonl` へは1行も書かない。

実行: python scripts/discord/test_enjo_stack.py
"""
import os
import sys
import json
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # …/5SecMovieMaker
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.path.insert(0, HERE)
import session_relay as SR              # noqa: E402
import reaction_watch as RW             # noqa: E402

results = []
GUILD = "1498341160207515678"
DEPT = "system-engineer"


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def item(msg_id, kind, content="投稿の本文"):
    """巡回が作る item の形(reaction_watch が実際に stack_open_defects へ渡す物)。"""
    return {"kind": kind, "dept": DEPT, "msg_id": str(msg_id),
            "channel_id": "1525646154933735425", "channel": "改修部門α",
            "content": content, "detected_at": "2026-08-14 08:00:02"}


def rows(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def opens(path):
    return [r for r in rows(path) if r.get("op") == "open"]


def notes(path, kind):
    return [r for r in rows(path)
            if r.get("op") == "note" and r.get("note_kind") == kind]


def run():
    tmpdir = tempfile.mkdtemp(prefix="enjostack_")
    ledger = os.path.join(tmpdir, "open_defects.jsonl")
    old = SR.set_defects_path(ledger)
    try:
        # === 1) 同じ投稿に🔥と再発。**再発を先に**渡す(実測で負けていた並び) ===
        print("\n[1] 🔥+再発が同じ投稿に付いた便(再発が先に来る並び)")
        both = [item("1537427301321670756", "saihatsu"),
                item("1537427301321670756", "enjo")]
        added, dup, why = RW.stack_open_defects(both, GUILD, dry_run=False)
        o = opens(ledger)
        check("台帳に積まれるのは1件だけ(msg_idで畳む・件数は増えない)", len(o) == 1)
        check("★source が『炎上』になる(重い方が勝つ=並べ替えが効いている)",
              o and "炎上" in str(o[0].get("source", "")))
        check("積んだ件数の戻り値は1(重複1件は added に数えない)", added == 1 and dup == 1)
        check("失敗の理由は空", why == "")
        folded = [d for d in SR.fold_defects(DEPT) if d["id"] == o[0]["id"]]
        check("★畳んだ結果が enjo=True(数える側から🔥が見える)",
              folded and folded[0].get("enjo") is True)

        # === 2) 再発だけの投稿は、重さを勝手に上げない ===
        print("\n[2] 再発だけの投稿")
        RW.stack_open_defects([item("1537444002465448066", "saihatsu")], GUILD, dry_run=False)
        d2 = [d for d in SR.fold_defects(DEPT)
              if "1537444002465448066" in d["broken"]]
        check("再発だけなら enjo=False のまま(勝手に炎上へ格上げしない)",
              d2 and d2[0].get("enjo") is False)
        check("source は『再発スタンプ』のまま", d2 and "再発" in d2[0]["source"])

        # === 3) 既に再発として積まれた古い行へ、後から🔥が来た場合(実測10件の救済) ===
        print("\n[3] 先に再発だけで積まれていた行に、後から🔥の便が来る")
        RW.stack_open_defects([item("1537453652619563100", "saihatsu")], GUILD, dry_run=False)
        d3 = [d for d in SR.fold_defects(DEPT) if "1537453652619563100" in d["broken"]]
        check("この時点では enjo=False", d3 and d3[0].get("enjo") is False)
        n0 = len(opens(ledger))
        RW.stack_open_defects([item("1537453652619563100", "enjo")], GUILD, dry_run=False)
        check("★新規IDは発行しない(件数が増えない)", len(opens(ledger)) == n0)
        check("★note(note_kind=enjo)が1行足される", len(notes(ledger, "enjo")) == 1)
        d3b = [d for d in SR.fold_defects(DEPT) if "1537453652619563100" in d["broken"]]
        check("★畳むと enjo=True へ上がる", d3b and d3b[0].get("enjo") is True)
        check("状態は未確認のまま(印を足しても閉じない・C-024)",
              d3b and d3b[0]["status"] == SR.DEFECT_OPEN)

        # === 4) 冪等= 二度流しても増えない ===
        print("\n[4] 二度流し(毎朝の巡回は同じ投稿を何度も見る)")
        n_open, n_note = len(opens(ledger)), len(notes(ledger, "enjo"))
        RW.stack_open_defects(both + [item("1537453652619563100", "enjo")],
                              GUILD, dry_run=False)
        check("open は増えない", len(opens(ledger)) == n_open)
        check("★note も増えない(印の二度押しをしない)",
              len(notes(ledger, "enjo")) == n_note)
        check("起票時から🔥だった行には note を足さない",
              SR.mark_defect_enjo(DEPT, opens(ledger)[0]["id"]) is False)

        # === 5) ゴラッソは積まない(良い知らせを不具合に混ぜない) ===
        print("\n[5] ゴラッソ")
        n_open = len(opens(ledger))
        a, _d, _w = RW.stack_open_defects([item("900000000000000001", "golazo")],
                                          GUILD, dry_run=False)
        check("ゴラッソは1件も積まれない", a == 0 and len(opens(ledger)) == n_open)

        # === 6) 起動文に🔥が出る(部屋が重さを読める) ===
        print("\n[6] 部屋の起動文")
        block = SR.defects_block(DEPT)
        check("★炎上の行に『🔥【炎上=恒久対策まで行け】』が付く",
              "🔥【炎上=恒久対策まで行け】" in block)
        check("再発だけの行には付かない",
              block.count("🔥【炎上=恒久対策まで行け】") == len(
                  [d for d in SR.fold_defects(DEPT) if d.get("enjo")]))

        # === 7) dry-run は台帳を1バイトも触らない ===
        print("\n[7] dry-run")
        before = len(rows(ledger))
        a2, d2c, w2 = RW.stack_open_defects([item("900000000000000002", "enjo")],
                                            GUILD, dry_run=True)
        check("dry-run では積まない", a2 == 0 and len(rows(ledger)) == before)
        check("dry-run の理由が返る", "dry-run" in w2)

        # === 8) 汚染の確認 ===
        print("\n[8] 汚染の確認")
        check("書き先が本番の台帳ではない",
              os.path.abspath(ledger) != os.path.abspath(SR.DEFECTS_FILE))
        check("検査中の書き込みは全部 tmp 側へ行った", len(rows(ledger)) > 0)
    finally:
        SR.set_defects_path(old)


run()

# === 9) スタンプ種別の辞書の揃い(改悪追加の回帰ガード・2026-08-23 トトリ) ===
# ★スタンプを1枚 WATCH に足して ORDERS/HEADING/KAIZEN_SECTION のどれかを忘れると、
#   巡回本文の描画が KeyError で落ちる(dept_body/kaizen_body が kind で直参照するため)。
#   ここが赤くなれば「辞書の足し忘れ」に翌朝の本番前に気づける=改悪そのものの回帰ガード。
print("\n[9] スタンプ種別の辞書の揃い(改悪追加の回帰ガード)")
for _w in RW.WATCH:
    _k = _w["kind"]
    check(f"kind='{_k}' が KIND_ORDER/ORDERS/HEADING/KAIZEN_SECTION に全て在る",
          _k in RW.KIND_ORDER and _k in RW.ORDERS
          and _k in RW.HEADING and _k in RW.KAIZEN_SECTION)
check("改悪(kaiaku) が WATCH に登録されている",
      any(w["kind"] == "kaiaku" for w in RW.WATCH))
check("改悪の絵文字IDが Chami作成の 1541110670748156014",
      next(w for w in RW.WATCH if w["kind"] == "kaiaku")["id"] == "1541110670748156014")

ok = sum(1 for _, c in results if c)
print(f"\n=== {ok}/{len(results)} PASS ===")
for name, c in results:
    if not c:
        print(f"  FAIL: {name}")
sys.exit(0 if ok == len(results) else 1)
