#!/usr/bin/env python3
"""日齢の見張り(C-070)が **同じ札を二度鳴らさない / 閉じた件を鳴らさない** か。

★0歩目= 壊れている実物(2026-09-20 04:00 の便・シャビ・アロンソが数え直して返してきた)
  ① 「7日超過5件」と出たが**実体は3件**= 現行台帳とアーカイブに同じ行の写しが在り、
     `scan()` が両方拾って便へ二重に載せていた(`decide()` の重複抑止は `fired` ストアを
     見るだけなので、**同じ1回の走行の中では効かない**)。
  ② `HQ-0271` は同じアーカイブの643行に `★解決` が在り、現行台帳の29行も `- [x]` なのに、
     503行だけを見て 3.2日の滞留として鳴っていた= 閉じ判定の口3つ(`- [x]` /
     `[ns:key] RESOLVED` 札 / 打ち消し線)が**どれもファイルを跨がない**うえ、
     ②の札と台帳ID `HQ-xxxx` は別体系で、09アーカイブに RESOLVED 印は0件だった。

★直す側の選択(C-038)= アーカイブへ `<!-- HQ-xxxx RESOLVED -->` を後付けして回るのではなく、
  **人が既に書いている書式(`- [x]` と 見出しの `★解決`)を機械が読めるようにする**。
  書き手を増やさないので、次に人が閉じた時も何もしなくて済む。

★ここで見るのは「文字列が在るか」ではない= **台帳を2枚(現行+アーカイブ)差し替えて
  scan() を実行で通す**。
★must-fail(C-053)= 壊した側は行を消さず**動く別の実装**へ差し替える。3本置いた=
  位置を捨てた閉じ判定 / 子番号を読まない `ITEM_ID` / 見出しで縛らない `★解決`。

走らせ方= `python tests/test_pending_age_dup_close.py`
"""
import io
import os
import re
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import pending_age_watch as PA          # noqa: E402

FAILS = []


def ok(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- 台帳の実物を組む
# F= 現行とアーカイブに**同じ札で二重**に載っている   … 1件だけ・**現行側**を残す
# G= アーカイブで開いたまま / 現行で `- [x]`          … 鳴ってはいけない(跨いで読む)
# H= アーカイブの中で見出し `★解決` が後から出る      … 鳴ってはいけない(HQ-0271 の形)
# I= 子番号 -A だけが閉じ、-C は開いたまま            … **-C は鳴らないといけない**
# J= 同じIDが**別案件で再利用**された(閉じ→再び開く) … 後の方は鳴らないといけない
# K= 本文で「★解決したはず」と触れただけの行が在る    … 元の行は鳴らないといけない
CURRENT = """# 検査用の現行台帳(本物と同じ形)

- [ ] **CASE-F HQ-9001 入れた(確認待ち)= 現行とアーカイブの両方に在る行(所有=platform-se) ★2026-09-05**
- [x] **CASE-G HQ-9002 ★解決= 現行で閉じた(アーカイブ側は開いたままの写しが残っている)**
- [x] **CASE-I HQ-9004-A ★解決= 閉じたのは**子番号Aだけ**(親でも -C でもない)**
- [ ] **CASE-K HQ-9006 入れた(確認待ち)= 本文で解決に触れた行が後ろに在る(所有=platform-se) ★2026-09-05**
- 追記: CASE-K の件は HQ-9006 が★解決したはずだと聞いている(未確認)。
"""

ARCHIVE = """# 検査用のアーカイブ(2026-09)

- [ ] **CASE-F HQ-9001 入れた(確認待ち)= 現行へ写した後もアーカイブに残っている行(所有=platform-se) ★2026-09-05**

- [ ] **CASE-G HQ-9002 入れた(確認待ち)= 閉じたのは現行側なのでここだけ見ると開いて見える(所有=platform-se) ★2026-09-05**

## CASE-H HQ-9003 @2026-09-05 入れた(確認待ち)= アーカイブの中で後から閉じた(所有=platform-se)
- 実装を入れた。確認はまだ。

## CASE-H HQ-9003 ★解決 2026-09-06 実物を見た(platform-se)
- 壊れていたのと同じ場面で直っているのを確認した。

## CASE-I HQ-9004-A @2026-09-05 入れた(確認待ち)= 子番号A(所有=platform-se)
## CASE-I HQ-9004-C @2026-09-05 入れた(確認待ち)= 子番号C(所有=platform-se)

## CASE-J HQ-9005 @2026-09-02 入れた(確認待ち)= 最初の案件(所有=platform-se)
- [x] CASE-J HQ-9005 ★解決 2026-09-03 最初の案件は閉じた(platform-se)

## CASE-J2 HQ-9005 @2026-09-10 入れた(確認待ち)= **同じ番号を別案件で使い直した**(所有=platform-se)
- こちらはまだ開いている。上の閉じは無関係だ。
"""


def build(tmp):
    cur = os.path.join(tmp, "hq_open_items.md")
    arc = os.path.join(tmp, "hq_open_items_2026-09.md")
    io.open(cur, "w", encoding="utf-8", newline="\n").write(CURRENT)
    io.open(arc, "w", encoding="utf-8", newline="\n").write(ARCHIVE)
    return [cur, arc]          # ★ledger_files() と同じ並び= 現行が先頭(=一番新しい)


def picked(items):
    """拾われた行を CASE 記号 → `台帳ID @ ファイル:行` の一覧にする(行番号は直書きしない)。"""
    out = {}
    for it in items:
        m = re.search(r"CASE-([A-Z]\d?)", it["head"])
        if m:
            out.setdefault(m.group(1), []).append(
                "%s@%s:%s" % (it["key"], it["file"], it["line"]))
    return out


def t_scan(files, alias):
    now = datetime(2026, 9, 20, tzinfo=PA.JST)
    got = picked(PA.scan(now, files=files, alias=alias))
    f, i = got.get("F", []), got.get("I", [])
    return [
        ("二重に載った行(F)は1件に畳む", len(f) == 1, "got=%s" % f),
        ("畳んだ後に残るのは**現行側**の行(F)",
         bool(f) and "@hq_open_items.md:" in f[0], "got=%s" % f),
        ("現行で閉じた行(G)はアーカイブ側も鳴らさない", "G" not in got, "got=%s" % got.get("G")),
        ("アーカイブ内で見出し★解決が後から出た行(H)は鳴らさない",
         "H" not in got, "got=%s" % got.get("H")),
        ("子番号Aの閉じで -C まで黙らせない(I)",
         len(i) == 1 and i[0].startswith("HQ-9004-C@"), "got=%s" % i),
        ("同じ番号を使い直した後の案件(J2)は鳴らす",
         "J2" in got and "J" not in got, "got=%s" % {k: got.get(k) for k in ("J", "J2")}),
        ("本文で解決に触れただけでは閉じない(K)", "K" in got, "got=%s" % got.get("K")),
    ]


# ---------------------------------------------------------------- must-fail(動く別の実装)
def flat_closed_keys(files, rank, _real=PA.closed_keys):
    """★壊した側その1= 閉じた証拠の**位置を捨てて**「そのIDは一度でも閉じたか」で見る版。

    素直で短く、F/G/H は正しく落とせる。落ちるのは**同じ番号を別案件で使い直した行**=
    実測で09アーカイブに在った形(HQ-0221 が516行で閉じ、550行で別件として開き直している)。
    位置を捨てると、生きている案件が古い閉じの巻き添えで黙る(§3= 沈黙は最悪の事故)。
    """
    out = {}
    for key, ev in _real(files, rank).items():
        # 位置を無視する= どの保留行から見ても「後ろに在る」証拠として振る舞わせる
        out[key] = [(10 ** 9, 10 ** 9, "flat")] + ev
    return out


NO_CHILD = re.compile(r"\b((?:HQ|ORG|INC)-\d{2,5})\b")


def parent_item_id(text):
    """★壊した側その2= 子番号(-A/-C)を読まない旧 `ITEM_ID` の版。

    台帳IDは親番号までだと思い込むと、`HQ-9004-A` の閉じが `HQ-9004-C` の閉じに見える。
    実測(2026-09-20)= 現行+アーカイブに子番号は10種在り、素朴な key 一致案はこれで
    HQ-0206 と HQ-0213 を誤って沈黙させた。
    """
    m = PA.ITEM_ID_COL.search(text) or NO_CHILD.search(text)
    return m.group(1) if m else ""


LOOSE_SOLVED = re.compile(r"★\s*解決")


def loose_solved_head(text):
    """★壊した側その3= `★解決` を**行のどこかで**見る版(見出しの形で縛らない)。

    閉じた件は正しく落とせるので一見通る。落ちるのは**本文で解決に触れただけの行**=
    09アーカイブ:662 に実在する形。触れた誰かの伝聞で、生きている案件が消える。
    """
    return LOOSE_SOLVED.search(text)


def main():
    alias = PA.dept_aliases()
    tmp = tempfile.mkdtemp(prefix="pa_dup_")
    files = build(tmp)

    print("■ scan()= 現行+アーカイブの2枚を差し替えて実行で通す")
    for r in t_scan(files, alias):
        ok(*r)

    print("■ must-fail その1= 閉じた証拠の位置を捨てると、使い回した番号(J2)が消えること")
    real, PA.closed_keys = PA.closed_keys, flat_closed_keys
    try:
        bad = [r[0] for r in t_scan(files, alias) if not r[1]]
        ok("位置を捨てた実装では J2 が黙る",
           bad == ["同じ番号を使い直した後の案件(J2)は鳴らす"],
           "落ちた項目=%d / %s" % (len(bad), " , ".join(bad)))
    finally:
        PA.closed_keys = real

    print("■ must-fail その2= 子番号を読まない ITEM_ID にすると、-C が巻き添えで消えること")
    real, PA.item_id = PA.item_id, parent_item_id
    try:
        bad = [r[0] for r in t_scan(files, alias) if not r[1]]
        ok("親番号までしか読まない実装では -C が黙る",
           "子番号Aの閉じで -C まで黙らせない(I)" in bad,
           "落ちた項目=%d / %s" % (len(bad), " , ".join(bad)))
    finally:
        PA.item_id = real

    print("■ must-fail その3= ★解決を行のどこかで見ると、本文で触れただけの行(K)が消えること")
    real, PA.SOLVED_HEAD = PA.SOLVED_HEAD, type("M", (), {"match": staticmethod(loose_solved_head)})
    try:
        bad = [r[0] for r in t_scan(files, alias) if not r[1]]
        ok("見出しで縛らない実装では K が消える",
           bad == ["本文で解決に触れただけでは閉じない(K)"],
           "落ちた項目=%d / %s" % (len(bad), " , ".join(bad)))
    finally:
        PA.SOLVED_HEAD = real

    print("■ must-fail その4= 畳む工程を外すと、二重に載った行(F)が2件に戻ること")
    real, PA.fold = PA.fold, lambda items: items      # 04:00の便が出していた数え方そのもの
    try:
        bad = [r[0] for r in t_scan(files, alias) if not r[1]]
        ok("畳まない実装では F が2件になる", bad == ["二重に載った行(F)は1件に畳む"],
           "落ちた項目=%d / %s" % (len(bad), " , ".join(bad)))
    finally:
        PA.fold = real

    print("\n%s  (%d FAIL)" % ("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS),
                               len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
