#!/usr/bin/env python3
"""日齢の見張り(C-070)が、**ブロックで開閉する台帳**を正しく閉じ扱いにするか。

★0歩目= 壊れている実物(2026-09-18・AD研究室が実測で返してきた)
  `00_AI-HQ/status/hq_open_items.md:984-989`
    984 `## 2026-09-15 01:02 提案決定→軍議エコー(経路B) = 入れた(確認待ち) [teian-echo:read-fail]`
    988 `<!-- teian-echo:read-fail RESOLVED 2026-09-15 01:12 -->`
    989 `- ✅ … 復旧: 1周を正常に完了(連続失敗カウンタを畳んだ)。(platform-se)`
  **10分で閉じていた**のに 3.2日の滞留として鳴り、しかも持ち主(次行の `platform-se`)を
  見出しの機能名から「軍議」と当てた= **閉じた仕事を、持っていない部門へ督促する**便。
  書き手 `scripts/_daemons/teian_echo_poll.py` は**追記のみ**で見出しに触らない設計(C-003)なので、
  打ち消し線 `~~…~~` だけを見る読み手側では**構造上いつまでも開いて見える**。

★ここで見るのは「文字列が在るか」ではない= **台帳を差し替えて scan()/run() を実行で通す**。
  外へ出る手(dispatch.py)だけ偽物にし、判定と分岐は本物のまま回して**実際に鳴った便**を集める。
★must-fail(C-053)= 「壊した側」は行を消さず**動く別の実装**(印を無視する旧版)へ差し替える。

走らせ方= `python tests/test_pending_age_block_state.py`
"""
import io
import os
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
# A= 閉じたブロック(OPEN → RESOLVED)          … 鳴ってはいけない
# B= 開いたままのブロック(OPEN だけ)          … 鳴らないといけない(fail-open)
# C= 札を持たない普通の行                      … 従来どおり鳴らないといけない
# D= 一度閉じて**また開いた**ブロック          … 下に RESOLVED が無いので鳴らないといけない
# E= 札を**本文で引用しただけ**の普通の行      … 鳴らないといけない(2026-09-18 の実害)
#    ★閉じ判定を「行のどこかに札の形が在るか」で書いた初版は、この行を飲み込んだ。
#      実物= hq_open_items.md:35(この穴を直した時の追記そのものが札を引用していた)=
#      **自分の案件が台帳から消える**。飲み込む側は見出しの形(`#`+行末の札)で縛る。
# ★ラベル(CASE-x)は**見出し行そのもの**へ置く= scan() が返すのは見出し1行だけで、
#   ブロックの本文行は返り値に入らない(最初これを本文へ書いて偽のFAILを3つ作った)。
LEDGER = """# 検査用の台帳(本物と同じ形)

- [ ] **入れた(確認待ち)= CASE-E 本文で札 `[teian-echo:read-fail]` を引用した普通の行(所有=platform-se) ★2026-09-03**

## 2026-09-01 01:02 CASE-A 提案決定→軍議エコー = 入れた(確認待ち) [teian-echo:read-fail]
<!-- teian-echo:read-fail OPEN 2026-09-01 01:02 -->
- GASの読み取り口が3回連続で読めない(理由=http-404)。(自動: teian_echo_poll / platform-se)

<!-- teian-echo:read-fail RESOLVED 2026-09-01 01:12 -->
- ✅ 2026-09-01 01:12 復旧: 1周を正常に完了(連続失敗カウンタを畳んだ)。(platform-se)

## 2026-09-02 02:00 CASE-B 提案決定→軍議エコー = 入れた(確認待ち) [teian-echo:send-fail]
<!-- teian-echo:send-fail OPEN 2026-09-02 02:00 -->
- 配達先が落ちたまま。(自動: teian_echo_poll / platform-se)

- [ ] **入れた(確認待ち)= CASE-C 普通の行(所有=platform-se) ★2026-09-03**

## 2026-09-04 04:00 CASE-D 提案決定→軍議エコー = 入れた(確認待ち) [teian-echo:read-fail]
<!-- teian-echo:read-fail OPEN 2026-09-04 04:00 -->
- 同じ札がもう一度開いた。(自動: teian_echo_poll / platform-se)
"""


def build(tmp):
    path = os.path.join(tmp, "hq_open_items.md")
    io.open(path, "w", encoding="utf-8", newline="\n").write(LEDGER)
    return path


def heads(items):
    """拾われた見出しを A/B/C/D の記号だけにして並べる(比較しやすくする)。"""
    out = []
    for it in items:
        for k in ("A", "B", "C", "D", "E"):
            if ("CASE-" + k) in it["head"]:
                out.append(k)
                break
    return sorted(set(out))


def t_scan(path, alias):
    now = datetime(2026, 9, 18, tzinfo=PA.JST)
    got = heads(PA.scan(now, files=[path], alias=alias))
    return [
        ("閉じたブロック(A)は拾わない", "A" not in got, "got=%s" % got),
        ("開いたままのブロック(B)は拾う", "B" in got),
        ("札を持たない普通の行(C)は拾う", "C" in got),
        ("同じ札が再び開いた(D)は拾う", "D" in got),
        ("札を本文で引用しただけの行(E)は飲み込まない", "E" in got),
    ]


def t_run(path, alias):
    """判定と便の組み立てまで本物で回し、**実際に鳴った便の本文**を見る。"""
    now = datetime(2026, 9, 18, tzinfo=PA.JST)
    sent = []

    def fake_sender(dept, title, body, dry):
        sent.append((dept, title + "\n" + body))
        return True

    state = os.path.join(os.path.dirname(path), "state.json")
    PA.run(now, dry=False, sender=fake_sender, state_path=state, files=[path], save=False)
    text = "\n".join(b for _, b in sent)
    return [
        ("便が1本以上出る(見張り自体は生きている)", bool(sent), "便=%d本" % len(sent)),
        ("閉じたブロック(A)は便に載らない", "CASE-A" not in text),
        ("開いたままのブロック(B)は便に載る", "CASE-B" in text),
        ("札を持たない行(C)も便に載る", "CASE-C" in text),
        ("札を引用しただけの行(E)も便に載る", "CASE-E" in text),
    ]


# ---------------------------------------------------------------- must-fail(動く別の実装)
def broken_block_closed(text, no, marks):
    """★壊した側= 印を「同じ行の中に在るか」で見る旧来型の読み方。

    もっともらしい(実際、打ち消し線はこの読み方で効いている)が、書き手はブロックの**下**へ
    追記するので同じ行には決して現れない= 閉じたブロックを永久に開いていると読む。
    """
    return "RESOLVED" in text


def loose_block_closed(text, no, marks):
    """★壊した側その2= 札を「行のどこかに在るか」で見る初版(見出しの形で縛らない)。

    閉じたブロックは正しく落とせるので一見通る。落ちるのは**札を本文で引用した普通の行**
    ひとつだけ= 2026-09-18 に本番で実際に消えた形(hq_open_items.md:35)。
    """
    for tag in PA.BLOCK_TAG.findall(text):
        if marks.get(tag, 0) > no:
            return True
    return False


def main():
    alias = PA.dept_aliases()
    tmp = tempfile.mkdtemp(prefix="pa_block_")
    path = build(tmp)

    print("■ scan()= 台帳を差し替えて実行で通す")
    for r in t_scan(path, alias):
        ok(*r)
    print("■ run()= 判定と便の組み立てまで本物(外へ出る口だけ偽物)")
    for r in t_run(path, alias):
        ok(*r)

    print("■ must-fail= 印を行内だけで見る旧来型へ差し替えると、Aが落ちること")
    real, PA.block_closed = PA.block_closed, broken_block_closed
    try:
        bad = [r[0] for r in t_scan(path, alias) if not r[1]]
        ok("壊した実装では検査が赤くなる(常にPASSする検査ではない)", bool(bad),
           "落ちた項目=%d / %s" % (len(bad), " , ".join(bad)))
    finally:
        PA.block_closed = real

    print("■ must-fail その2= 札を行のどこかで見る初版へ差し替えると、Eだけが落ちること")
    real, PA.block_closed = PA.block_closed, loose_block_closed
    try:
        bad = [r[0] for r in t_scan(path, alias) if not r[1]]
        ok("初版では引用行(E)が消える(この検査は本番の実害を再現している)",
           bad == ["札を本文で引用しただけの行(E)は飲み込まない"],
           "落ちた項目=%d / %s" % (len(bad), " , ".join(bad)))
    finally:
        PA.block_closed = real

    print("\n%s  (%d FAIL)" % ("ALL PASS" if not FAILS else "FAILED: " + ", ".join(FAILS),
                               len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
