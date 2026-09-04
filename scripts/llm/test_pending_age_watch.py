# -*- coding: utf-8 -*-
"""日齢の見張り(C-070)のテスト(2026-09-05 イージス研究室)。

発注= 研究室HQ `DISPATCH-aegis-gl-1788503402548`(裁定 C-070・00_AI-HQ commit `ecce186`)。

★must-fail の作り(docs/departments/00_common/skills/test-must-fail)=
  - **入力を差し替える**= 本物の台帳ではなく、日齢が既知の合成台帳を1枚書いて食わせる。
  - **判断は本物**= scan / parse_line / decide / 状態の焼き込みは production のコードをそのまま通す。
  - **偽物は外向きの手だけ**= dispatch.py の起動(=部屋への投函)だけを差し替える。
  - **壊れた側は動く別実装**(C-053)= 「増分だけを見る見張り」を同じ入力に当てる。
    それが**滞留を見逃す**ことを赤で見せてから、本実装が緑になるのを見る。

  python scripts/llm/test_pending_age_watch.py
"""
import io
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pending_age_watch as P      # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % name)
    else:
        FAIL += 1
        print("  NG  %s" % name)


NOW = datetime(2026, 9, 5, 12, 0, tzinfo=P.JST)
BASE = "2026-08-20"     # 合成台帳用の基準日(本番の BASELINE_DEFAULT とは別物)


def d(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d")


def ledger():
    """日齢が既知の合成台帳。★本番の台帳は読まない(本番の部屋でテストしない)。"""
    lines = [
        "# 合成台帳(テスト専用)",
        # 鳴るべき= 5日・持ち主は札の直後
        "- [ ] **★%s ゲートの実装= 入れた(確認待ち)・改修部門β**  … `HQ-9001` @2026-09" % d(5),
        # 鳴るべき= 9日・7日超 → 依頼元(発注=)の部屋へ
        "- [ ] **★%s 台帳の壊れ行= 入れた(確認待ち)・イージス研究室** (発注= 人事部門)  … `HQ-9002`" % d(9),
        # 鳴らない= まだ1日
        "- [ ] **★%s 呼称ゲート= 入れた(確認待ち)・改修部門α**  … `HQ-9003`" % d(1),
        # 鳴らない= 基準日より前(在庫)。数には入る
        "- [ ] **★%s 古い在庫= 入れた(確認待ち)・改修部門α**  … `HQ-9004`" % d(40),
        # 鳴らない= 閉じ済み
        "- [x] **★%s 閉じた件= 入れた(確認待ち)・改修部門α**  … `HQ-9005`" % d(8),
        # 鳴らない= 日付が読めない(日齢不明として数だけ)
        "- [ ] **いつのものか書いていない= 入れた(確認待ち)・改修部門α**  … `HQ-9006`",
        # 鳴らない= その語について喋っているだけ(棚卸しの起票)
        "- [ ] **★%s 「入れた(確認待ち)」の在庫を棚卸しする= 未着手**  … `HQ-9007`" % d(9),
        # ★印が無く行内に日付だけ在る= 拾えないと146行中100行が落ちる
        "- [入れた(確認待ち)] 英文ダンプゲート(%s) プラットフォームSE : 実装まで" % d(6),
    ]
    path = os.path.join(tempfile.mkdtemp(prefix="pendage_"), "hq_open_items.md")
    io.open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return path


class Spy(object):
    """外向きの手だけの偽物= 部屋へは出さないが、誰に何を出すかは本物と同じ。"""

    def __init__(self):
        self.sent = []

    def __call__(self, dept, title, body, dry):
        self.sent.append({"dept": dept, "title": title, "body": body})
        return True

    def depts(self):
        return sorted(x["dept"] for x in self.sent)

    def keys(self):
        return sorted(k for k in ("HQ-9001", "HQ-9002", "HQ-9003", "HQ-9004",
                                  "HQ-9005", "HQ-9006", "HQ-9007")
                      if any(k in x["body"] for x in self.sent))


def broken_increment_watch(items, seen_count):
    """★壊れた側(動く別実装)= 「件数が増えた時だけ鳴らす」旧来型の見張り。

    C-070 が塞ごうとしている穴そのもの= **増えなければ、何日腐っていても黙る**。
    """
    if len(items) > seen_count:
        return [i for i in items[seen_count:]]
    return []


def main():
    path = ledger()
    live = {"system-engineer", "system-engineer-b", "aegis-gl", "hr-room", "hq", "platform-se"}

    print("\n[1] 読み取り= 合成台帳から何行拾えるか")
    items = P.scan(NOW, files=[path])
    st = P.summarize(items, BASE)
    check("対象は6行(閉じ済みと『語について喋る行』を除く)", st["total"] == 6)
    check("日付が読めたのは5行", st["dated"] == 5)
    check("日齢不明は1行(推定で埋めない)", st["unknown"] == 1)
    check("★印なしの行も日付を拾えている(by_line>=1)", st["by_line"] >= 1)
    by = {i["key"]: i for i in items}
    check("HQ-9005(- [x])は拾わない", "HQ-9005" not in by)
    check("HQ-9007(語について喋る行)は拾わない", "HQ-9007" not in by)
    check("HQ-9001の持ち主= 札の直後の改修部門β", by["HQ-9001"]["dept"] == "system-engineer-b")
    check("HQ-9002の依頼元= 発注=の後ろの人事部門", by["HQ-9002"]["req"] == "hr-room")
    # 日付は00:00で読む= NOWが昼なら5.5日。丸めずに「5日台」で見る(数字を盛らない)
    check("HQ-9001の日齢は5日台", 5.0 <= by["HQ-9001"]["age"] < 6.0)

    print("\n[2] ★壊れた側= 増分だけを見る見張りに、同じ入力を食わせる")
    # 台帳は1行も増えていない(= 昨日と同じ7行)。滞留は5日と9日で進んでいる。
    missed = broken_increment_watch(items, seen_count=len(items))
    check("増分型は1件も鳴らせない(=これが塞ぐ穴)", missed == [])
    check("★だが実際には3日超が3件ある(増分型はそれを見逃している)",
          len([i for i in items if i["age"] and i["age"] > P.AGE_REMIND
               and i["date"] >= BASE]) == 3)

    print("\n[3] 本実装= 経過時間で鳴らす(dispatchの起動だけ偽物)")
    state = os.path.join(tempfile.mkdtemp(prefix="pendst_"), "state.json")
    P.write_json(state, {"baseline": BASE, "fired": {}})
    spy = Spy()
    n = P.run(NOW, dry=False, sender=spy, state_path=state, files=[path])
    check("便が出た", n > 0)
    check("HQ-9001(5日)が鳴った", "HQ-9001" in spy.keys())
    check("HQ-9002(9日)が鳴った", "HQ-9002" in spy.keys())
    check("HQ-9003(1日)は鳴らない", "HQ-9003" not in spy.keys())
    check("HQ-9004(在庫)は鳴らない", "HQ-9004" not in spy.keys())
    check("HQ-9006(日齢不明)は鳴らない", "HQ-9006" not in spy.keys())
    check("3日の督促は所有部門(改修部門β)へ行った", "system-engineer-b" in spy.depts())
    check("7日は依頼元(人事部門)の部屋へ行った", "hr-room" in spy.depts())
    check("★日齢不明の件数は本文に出ている",
          any("日齢不明 1件" in x["body"] for x in spy.sent))
    check("★在庫を鳴らしていないことも本文に出ている",
          any("在庫)は数えたが鳴らしていない" in x["body"] or "件(在庫)" in x["body"]
              for x in spy.sent))

    print("\n[4] 二度鳴きしない= 状態に焼けているか")
    spy2 = Spy()
    n2 = P.run(NOW, dry=False, sender=spy2, state_path=state, files=[path])
    check("同じ日にもう一度回しても0本", n2 == 0 and spy2.sent == [])
    fired = (P.read_json(state) or {}).get("fired") or {}
    check("HQ-9001にd3の印", (fired.get("HQ-9001") or {}).get("d3"))
    check("HQ-9002にd7の印", (fired.get("HQ-9002") or {}).get("d7"))

    print("\n[5] 部屋が無い部門へは投げない(偽の受領を作らない)")
    d3, d7 = P.decide(items, BASE, {}, live=live - {"system-engineer-b"})
    check("部屋の無い改修部門βの分は研究室HQが受ける",
          "system-engineer-b" not in d3 and "hq" in d3)

    print("\n[6] 日を跨いで3日→7日へ上がる")
    later = NOW + timedelta(days=5)          # HQ-9001 が10日になる日
    spy3 = Spy()
    P.run(later, dry=False, sender=spy3, state_path=state, files=[path])
    check("d3を鳴らし済みでも7日超で改めて鳴る", "HQ-9001" in spy3.keys())

    print("\n[7] ★HQ指定の物差し(★印だけ)で読むと落ちる行が在る")
    # 壊れた側= 「★YYYY-MM-DD だけを日付と認める」実装。動くが、台帳の実物では取りこぼす。
    star_only = P.ANY_DATE
    P.ANY_DATE = P.re.compile(r"(?!)")       # 絶対に当たらない= 素の日付を捨てる読み手
    try:
        narrow = P.summarize(P.scan(NOW, files=[path]), BASE)
    finally:
        P.ANY_DATE = star_only
    check("★印だけだと日齢不明が増える(1行 → 2行)", narrow["unknown"] == 2)
    check("行内の日付も読む本実装なら不明は1行", st["unknown"] == 1)

    print("\n== ok %d / NG %d ==" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
