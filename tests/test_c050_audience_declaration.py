#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C-050の恒久= **便を出す側が宛先(誰が読む本文か)を宣言する**。その配線の検査。

なぜ要るか(2026-08-23・研究室HQ→イージス研究室 回送 DISPATCH-aegis-gl-1787431376034):
  止血までの判定は受け手(dept_daemon)が**差出人の名前の文字列**を見て当てていた
  (「トリガー」「巡回」「監視」…を含むか)。当て推量なので、名前がその一覧に当たらない
  新しいトリガーが増えれば**またChamiの字が消える**。実際に消した実物=
  8/22の振り返り1,646字(author「定刻トリガー(朝5時)」・via=dispatch)。
  Chami原文=「わざわざそっちに全文読みにいかないから、区切ってでも全文表示してよ」。

  → 判定の材料を「名前」から「宣言」へ移した(`dispatch.py --audience ai|chami`)。
    削ってよいのは「**AI同士の便だと差出人が言い切った便**」だけ。宣言が無ければ削らない。

★この検査が固定するのは3つ:
  ①宣言の組み立て(純粋関数)
  ②**本物の dispatch() を通した便**を、**本物の dept_daemon の門**に通した往復
    (外へ出る手= キューDBは使い捨ての実物 / Discord投稿だけ偽物)
  ③**便を出す側(producer)が全部宣言しているか**= 新しい producer が増えたら落ちる
★must-fail 内蔵。
"""
import io
import json
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import dispatch as dp        # noqa: E402
import dept_daemon as dd     # noqa: E402

fails = []


def check(name, got, want):
    ok = (got == want)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        fails.append(name)


# ── 1. 宣言の組み立て(純粋関数) ──────────────────────────────────
print("=== 1. 宛先の宣言(dispatch.audience_fields) ===")
check("aiは そのまま載る", dp.audience_fields("ai"), {"audience": "ai"})
check("chamiは front_full も立てる",
      dp.audience_fields("chami"), {"audience": "chami", "front_full": True})
check("大文字・空白は正規化", dp.audience_fields("  AI "), {"audience": "ai"})
check("宣言なしは空(keyは載る)", dp.audience_fields(""), {"audience": ""})
check("Noneでも落ちない", dp.audience_fields(None), {"audience": ""})
# ★知らない語を「ai」に丸めない= 綴り違いで勝手に削り始めないため
check("知らない語は宣言なし扱い", dp.audience_fields("AI同士"), {"audience": ""})
check("知らない語は宣言なし扱い(chami風)", dp.audience_fields("chami-facing"), {"audience": ""})

# ── 2. 往復= 本物の dispatch() が載せた便を、本物の門に通す ────────────
print("=== 2. 便を出す→受け手の門へ(本物のまま。Discord投稿だけ偽物) ===")
_tmp = tempfile.mkdtemp(prefix="c050aud_")
_orig_db, _orig_post = dp.QUEUE_DB, dp.post_work_to_channel
_posted = []
try:
    dp.QUEUE_DB = os.path.join(_tmp, "inbox.db")
    dp.post_work_to_channel = lambda *a, **k: _posted.append(a) or ""   # 外へ出る手だけ止める

    _mids = set()

    def sent(audience, work=""):
        """本物の dispatch() を通し、**キューへ実際に入った便**を読み戻す。

        ★2026-08-24 検査側の回避を外した(イージス研究室)。以前はここで id 衝突
          (`DISPATCH-<dept>-<ミリ秒>` が同じミリ秒で被る)を**検査側がリトライして**
          避けていた。本体が衝突を `-2` で逃がすようになった(dispatch.enqueue_unique)ので
          **1回出して1回読む**に戻す。回避を残すと、次に同じ穴が開いても**ここが赤くならない**。
          衝突そのものの検査本体= tests/test_dispatch_id_collision.py。
        """
        ok, mid = dp.dispatch("hq", "検査(イージス研究室)", "本文" * 400,
                              audience=audience, work=work)
        if not ok:
            return None
        if mid in _mids:
            return None        # ★同じidが2度返る=本体の衝突逃がしが壊れている(ここで赤くする)
        _mids.add(mid)
        con = sqlite3.connect(dp.QUEUE_DB)
        row = con.execute("SELECT body FROM queue WHERE msg_id=?", (mid,)).fetchone()
        con.close()
        return json.loads(row[0]) if row else None

    _ai, _ch, _no = sent("ai"), sent("chami"), sent("")
    check("便が実際にキューへ入る", bool(_ai and _ch and _no), True)
    check("ai宣言が便に載る", _ai.get("audience"), "ai")
    check("chami宣言が便に載る", _ch.get("audience"), "chami")
    check("chami宣言は front_full も立つ(受け手の旧版でも守れる)", _ch.get("front_full"), True)
    check("宣言なしでも key は載る(後から数えられる)", "audience" in _no, True)
    check("宣言なしの値は空", _no.get("audience"), "")

    # ★核心= 受け手の本物の門(dept_daemon.may_trim_front)へ、そのまま通す
    check("★ai宣言の便への返信は削ってよい", dd.may_trim_front(_ai), True)
    check("★chami宣言の便への返信は削らない", dd.may_trim_front(_ch), False)
    check("★宣言なしの便への返信は削らない(fail-open)", dd.may_trim_front(_no), False)
    # ★must-fail= 宣言を見ない旧版の門なら、宣言なしの便まで削ってしまう
    check("mustfail_旧版の門は宣言なしの便を削る", dd.is_interdept_letter(_no), True)
    # ★must-fail= 宣言の載せ忘れ(rec から audience を抜く)は「削らない」側へ落ちる
    _stripped = {k: v for k, v in _ai.items() if k != "audience"}
    check("mustfail_宣言を抜くと削られなくなる", dd.may_trim_front(_stripped), False)

    # 実依頼(--work)の経路でも宣言は落ちない
    _w = sent("ai", work="検査の実依頼")
    check("実依頼でも宣言が載る", _w.get("audience"), "ai")
    check("実依頼の表投稿は呼ばれている", len(_posted) >= 1, True)
finally:
    dp.QUEUE_DB, dp.post_work_to_channel = _orig_db, _orig_post
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)

# ── 3. 便を出す側が全部宣言しているか(producerの全数) ────────────────
#   ★これが無いと「機構は入ったが誰も使っていない」で静かに元へ戻る。
#   新しい producer が増えたら**この検査が落ちて**登録を強制する(登録=下の表に1行足す)。
print("=== 3. 便を出す側(producer)の全数 ===")

# file → (種別, 期待する宣言 or 理由)
#   "declare" = **本番の便を出す**。その源に --audience / audience= が要る
#   "mention" = 文中で名前を出しているだけ(dispatch を呼ばない)
#   "test"    = 検査。★宣言は要らない。代わりに**本番のキューへ出さないこと**が要件
#               (§3「本番の部屋でテストしない」)= QUEUE_DB を使い捨てへ向け、
#               表投稿(post_work_to_channel)を偽物へ差し替えていること。
#
# ★数え方の決着(2026-08-24 イージス研究室・研究室HQ msg DISPATCH-aegis-gl-1787498595898)=
#   HQの指摘「tests/ まで数えて検査に宣言を要求している」は当たっていた。ただし
#   **tests/ を数えるのをやめる**のではなく、**tests/ に課す義務を変える**方へ倒した。
#   理由= 検査が本番のキューへ便を出す事故(=Chamiの部屋にゴミが届く)は実際に起こりうる。
#   数えるのをやめると、その事故は**この網から永久に見えなくなる**。
#   ★もう1つ直した= 未登録のファイルへ既定で "declare" を当てて
#   「宣言している: <file>」まで赤くしていた= **1つの原因で2つ赤が出る**。
#   未登録は「未登録」の1本だけ鳴らす(義務は、登録して種別が決まってから課す)。
PRODUCERS = {
    "scripts/llm/daily_reflection_trigger.py": ("declare", "chami"),   # 朝5時の振り返り=Chamiが読む
    "scripts/discord/reaction_watch.py":       ("declare", "chami"),   # Chamiの印(再発/炎上)
    "scripts/report/se_daily_review.ps1":      ("declare", "chami"),   # 毎朝の振り返り
    "scripts/report/kaizen_round.ps1":         ("declare", "chami"),   # PDCAラウンド
    "scripts/_daemons/run_kaizen_daily_repair.py": ("declare", "chami"),
    "scripts/llm/context_watch.py":            ("declare", "ai"),      # 文脈量の見張り=AI同士
    "scripts/llm/quota_alarm.py":              ("declare", "ai"),      # 残量の警報=AI同士
    "scripts/_daemons/envelope_naming_watch.py": ("declare", "ai"),    # 封筒の名前の見張り=AI同士
    "scripts/_daemons/teian_echo_poll.py":     ("declare", "ai"),      # 提案シート→軍議の機械エコー
    "scripts/llm/dispatch.py":                 ("mention", "本体"),
    "scripts/llm/dept_daemon.py":              ("mention", "部門プロンプトの案内文"),
    "scripts/queue/dlq_tool.py":               ("mention", "docstringで作法を書いているだけ"),
    "tests/test_dept_request_visibility.py":   ("mention", "この経路の別の検査"),
    "tests/test_c050_reply_digest.py":         ("mention", "受け手側(門と切り詰め)の検査"),
    "tests/test_dispatch_addressee.py":        ("mention", "宛先ズレ警告の純粋関数の検査(dispatchは呼ばない)"),
    "tests/test_c050_audience_declaration.py": ("test", "この検査そのもの(本物のdispatchを使い捨てDBへ通す)"),
    "tests/test_dispatch_id_collision.py":     ("test", "id衝突の検査(時計を止めて使い捨てDBへ2本通す)"),
}
_PAT = re.compile(r"dispatch\.py|dispatch\.dispatch\(")
found = []
for base, _dirs, files in os.walk(ROOT):
    rel_dir = os.path.relpath(base, ROOT).replace("\\", "/")
    if rel_dir.startswith(("scripts", "tests")) is False:
        continue
    if "__pycache__" in rel_dir:
        continue
    for fn in files:
        if not fn.endswith((".py", ".ps1", ".bat")) or ".bak" in fn:
            continue
        rel = (rel_dir + "/" + fn).lstrip("./")
        try:
            src = io.open(os.path.join(base, fn), encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        if _PAT.search(src):
            found.append((rel, src))

def audit_producers(registry, files):
    """種別ごとの義務を当てて、問題の一覧を返す(空=問題なし)。

    ★関数にしてあるのは、下の must-fail が **「動く別の実装」へ差し替えて**
      赤くなることを確かめるため(C-053)。行を消して文法を壊すのは偽の緑だ。
    """
    bad = []
    for rel, src in files:
        if rel not in registry:
            bad.append("未登録: " + rel)          # 種別が決まるまで義務は課さない
            continue
        kind, want = registry[rel]
        if kind == "mention":
            continue
        if kind == "declare":
            if not (("--audience" in src) or ("audience=" in src)):
                bad.append("宣言が無い: " + rel)
            elif want and not ((f'"{want}"' in src) or (f"--audience {want}" in src)):
                bad.append(f"宣言の中身が {want} でない: " + rel)
        elif kind == "test":
            # 検査に課すのは宣言ではなく「本番のキューへ出さないこと」
            if "dispatch.dispatch(" in src or "dp.dispatch(" in src:
                if "QUEUE_DB" not in src:
                    bad.append("検査が本番のキューへ出しうる(QUEUE_DBを差し替えていない): " + rel)
                if "post_work_to_channel" not in src:
                    bad.append("検査が本番の部屋へ表投稿しうる: " + rel)
        else:
            bad.append("種別が不明(%s): %s" % (kind, rel))
    return sorted(bad)


check("producerを1本も見失っていない", len(found) >= len(PRODUCERS), True)
check("★全producerが種別どおりの義務を満たしている", audit_producers(PRODUCERS, found), [])

# ★must-fail①= 宣言を消した「動く写し」を混ぜると、その1本だけ赤くなる
_ref = "scripts/llm/daily_reflection_trigger.py"
_broken = io.open(os.path.join(ROOT, _ref), encoding="utf-8").read() \
    .replace('audience="chami"', "").replace("--audience", "")
check("mustfail_宣言を消した写しは検査に落ちる",
      audit_producers(PRODUCERS, [(_ref, _broken)]), ["宣言が無い: " + _ref])

# ★must-fail②= 登録から外すと「未登録」で鳴る(新しいproducerが黙って増えない)
_less = {k: v for k, v in PRODUCERS.items() if k != _ref}
check("mustfail_登録から外すと未登録で鳴る",
      audit_producers(_less, [(_ref, "audience=\"chami\"")]), ["未登録: " + _ref])

# ★must-fail③= **動く別の実装**= 「全部 mention 扱い」の版(=何も義務を課さない)。
#   これに差し替えると①が緑になる= ①の緑が本当に義務を見ている証明になる。
_all_mention = {k: ("mention", "") for k in PRODUCERS}
check("mustfail_全部mention扱いの実装に差し替えると、宣言を消しても通ってしまう",
      audit_producers(_all_mention, [(_ref, _broken)]), [])

# ★検査に課した義務そのものの実証= 本番のキューへ出す写しは赤くなる
_self = "tests/test_c050_audience_declaration.py"
check("mustfail_検査がQUEUE_DBを差し替えずdispatchすると赤くなる",
      audit_producers(PRODUCERS, [(_self, "dp.dispatch('hq', 'x', 'y')")]),
      ["検査が本番のキューへ出しうる(QUEUE_DBを差し替えていない): " + _self,
       "検査が本番の部屋へ表投稿しうる: " + _self])

if __name__ == "__main__":
    print(f"\nFAIL — {len(fails)}件: {fails}" if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)
