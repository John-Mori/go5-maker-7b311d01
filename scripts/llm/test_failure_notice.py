# -*- coding: utf-8 -*-
"""suppress_failure_notice() の全分岐を回す(dept_daemon の失敗終端報告の可否)。

なぜ要るか= この述語は「Chamiに無音のまま止まって見せない」ための可用性判定だ。
  実物(2026-08-23 Chami「改修αが30分以上動かなくて止まってる？」)= 打ち切りが
  何度も無音で再配達され、Chamiには何十分も沈黙が続いていた。判定を1文字間違えると
  「また黙る」か「連投で履歴が汚れる」のどちらかに戻るので、全分岐を機械で固定する。

★must-fail= 述語を「timeoutでも一般失敗と同じ(3回目まで伏せる)」に戻した変異体で
  同じ表明が**落ちる**ことを確認する(常にPASSする空検査ではない)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_daemon as dd

FAIL = []


def _ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAIL.append(msg)


def _spec():
    """(kind, delivery_count) -> 伏せるべきか。テスト対象の期待仕様。"""
    return [
        # timeout= 部屋へは一切出さない(常に伏せる。Chami「削除で」2026-08-23)。
        (("timeout", 1), True, "timeout・配達1回目= 伏せる(確定情報ゼロで意味がない)"),
        (("timeout", 3), True, "timeout・配達3回目= 伏せる"),
        (("timeout", None), True, "timeout・配達数不明でも= 伏せる"),
        # 一般の配送失敗= 再配達3回目で初めて出す(1・2回目は伏せる)。
        (("", 1), True,  "一般失敗・配達1回目= 伏せる"),
        (("", 2), True,  "一般失敗・配達2回目= 伏せる"),
        (("", 3), False, "一般失敗・配達3回目= 出す(もう後が無い)"),
        (("auth", 1), True, "auth失敗・配達1回目= 伏せる(timeout以外の一般失敗と同じ)"),
        (("", None), False, "一般失敗・配達数不明= 出す側へ倒す"),
    ]


def _touched_spec():
    """(touched入力, 期待するsubstantive件数, 期待する報告が空か, ラベル)。"""
    codever = ["~local\\_daemon_codever\\dept_hr-room.txt",
               "~local\\_daemon_codever\\dept_platform-se.txt"]
    busy = ["~local\\llm\\busy\\gunji.json"]
    churn_only = codever + busy + ["~local\\persona_avatars.json",
                                   "~local\\llm\\room_sessions.json"]
    real = ["scripts/llm/daily_report.py"] + codever
    return [
        ([], 0, True, "touched空= 報告は空(黙る)"),
        (churn_only, 0, True, "churnだけ(codever/busy/脈)= 実体0=黙る"),
        (real, 1, False, "実体1件+churn混在= 実体だけ拾って報告する"),
        (["app.js", "app.js"], 1, False, "重複は1件に畳む"),
        # ★2026-09-03 Chami「人間がちゃんと読めるような通知じゃないといらん」の実物。
        #   work_audit 08:47:40 / goods-afi / msg 1544850931529555989 から churn を
        #   落とした後に残っていた10件= **全部が機械の副産物**だった(=本来は黙るべき便)。
        (REAL_20260903_BYPRODUCTS, 0, True,
         "実物(09-03 グッズサイト)= .pyc/.bak/キャッシュ/状態だけ= 実体0=黙る"),
        (REAL_20260903_BYPRODUCTS + ["scripts/llm/dept_daemon.py"], 1, False,
         "副産物に本物が1件混ざれば、本物だけを名指しする"),
    ]


# Chamiが「読めない」と言った通知の元データ(work_audit の touched から churn を除いた残り)。
REAL_20260903_BYPRODUCTS = [
    "scripts/llm/__pycache__/transcribe.cpython-312.pyc",
    "scripts/llm/tone_gate.py.bak_20260903_forbiddenall",
    "~local\\llm\\_room_cache_802d2f8d-0f00-4b16-9b41-08fd6781ea8d.txt",
    "scripts/llm/__pycache__/local_responder.cpython-312.pyc",
    "~local\\_daily_report_body.txt",
    "~local\\_state\\envelope_naming_watch.json",
    "~local\\_state\\naming_drift_watch.json",
    "~local\\llm\\_room_cache_6f58ba35-af40-4fa3-bdf6-0b33ef664ba0.txt",
    "~local\\persona_queue_cursor.json",
    "~local\\office\\_summary.txt",
]


def main():
    for (kind, dl), want, label in _spec():
        got = dd.suppress_failure_notice(kind, dl)
        _ok(got == want, f"{label} → suppress={got}")

    # ★must-fail: timeoutを一般失敗と同一視する変異体(_dl<3で伏せる=3回目は出す)なら、
    #   「timeout・配達3回目= 伏せる」の期待が壊れるはず(変異体は出してしまう)。
    def mutant(kind, delivery_count):
        if delivery_count is None:
            return False
        return delivery_count < 3     # ← timeoutを部屋へ出さない特別扱いを消した壊れた版
    _ok(mutant("timeout", 3) is False
        and dd.suppress_failure_notice("timeout", 3) is True,
        "must-fail: timeout特別扱いを消した変異体は配達3回目に誤って出す(本物は伏せる)")

    # --- 打ち切りの"確定結果": substantive_touched / format_timeout_result ---
    for touched, n_want, empty_want, label in _touched_spec():
        subst = dd.substantive_touched(touched)
        _ok(len(subst) == n_want, f"{label} → substantive={subst}")
        line = dd.format_timeout_result(touched)
        _ok((line == "") is empty_want,
            f"{label} → report_empty={line == ''}")
    # 実体があれば触ったファイル名が本文に載る(確定事実を名指しする)。
    _ok("daily_report.py" in dd.format_timeout_result(["scripts/llm/daily_report.py"]),
        "実体変更のファイル名が確定結果の本文に載る")

    # --- 人間が読める文面か(2026-09-03 Chami指摘の受け入れ条件) ---
    many = ["scripts/a.py", "scripts/b.py", "scripts/c.py", "scripts/d.py", "scripts/e.py"]
    line_many = dd.format_timeout_result(many)
    _ok("時間切れ" in line_many and "途中" in line_many,
        "文面に『何が起きたか(時間切れ)』と『今どういう状態か(途中)』が入る")
    # ★既定(deliveries不明)でも「読み手の次の一手」は必ず入る。2026-09-13 以降その一手は
    #   「言い直せ」ではなく「常駐が続きをやる/出てこなければ言え」= 機構どおりの予告だ。
    _ok("常駐が続きをやって別便で報告する" in line_many and "出てこなければ" in line_many,
        f"文面に読み手の次の一手が入る → {line_many[-50:]}")

    # --- ★末尾の一手は deliveries で決まる(2026-09-13・Chami msg 1548401051043106888) ---
    # 実測が根拠= この通知が出た26本は queue/inbox.db で**26本とも done / deliveries=2**。
    #   打ち切り時点の deliveries は 1(2なら timeout_should_dead が dead にしている)。
    #   つまり旧文面「続きが要るならもう一度言ってくれ」は26/26で**不要な指示**だった。
    #   ここは「次に何が起きるか」を機構どおりに書けているかだけを見る。
    _d1 = dd.format_timeout_result(many, 1)          # ← 実物26本と同じ場面
    _ok("もう一度配達" in _d1 and "言い直す必要はない" in _d1
        and "続きが要るならもう一度言ってくれ" not in _d1,
        f"deliveries=1(まだ走る)→ 自動で拾い直すと書き、人に頼まない → {_d1[-60:]}")
    _d2 = dd.format_timeout_result(many, dd.TIMEOUT_MAX_DELIVERIES)
    _ok("続きが要るならもう一度言ってくれ" in _d2 and "dead-letter" in _d2
        and "言い直す必要はない" not in _d2,
        f"deliveries=上限(次は走らない)→ ここで初めて人へ頼む → {_d2[-60:]}")
    _d0 = dd.format_timeout_result(many, None)
    _ok("出てこなければ" in _d0,
        f"deliveries不明→ 断定しない(両方の目を書く) → {_d0[-60:]}")
    # ★予告と実際の挙動が同じ deliveries から出ていること= 通知が嘘をつかない不変条件。
    for _dv in (0, 1, 2, 3, 5):
        _will_dead = dd.timeout_should_dead("timeout", None, _dv)
        _says_dead = "dead-letter" in dd.format_timeout_result(many, _dv)
        _ok(_will_dead is _says_dead,
            f"deliveries={_dv}: 予告(dead-letterと書く={_says_dead})と実際(dead={_will_dead})が一致")

    _ok(line_many.count("scripts/") == 3 and "ほか2件" in line_many,
        f"名指しは3件まで+残りは件数で畳む → {line_many}")
    _ok("\\" not in dd.format_timeout_result(["~local\\llm\\change_log.jsonl"]),
        "パスの区切りは / に揃える(Windowsの \\ を本文へ出さない)")
    _hq = dd.format_timeout_result(["~..\\00_AI-HQ\\departments\\hr\\characters\\ames.md"])
    _ok("00_AI-HQ/departments/hr/characters/ames.md" in _hq and ".." not in _hq,
        f"リポジトリ外を指す ../ は本文から落とす → {_hq}")

    # ★must-fail: 副産物除去を消した変異体(churn除去だけの旧実装)なら、Chamiが「読めない」と
    #   言った実物の入力で報告が**非空**になる(=あの通知がそのまま復活する)。
    def mutant_byproduct(touched):
        seen, out = set(), []
        for p in (touched or []):
            if dd._is_churn_path(p):           # ← 副産物の判定だけ抜いた壊れた版(旧実装)
                continue
            key = str(p).replace("\\", "/").lstrip("~")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(str(p).lstrip("~"))
        return out
    # ★9件= 本番の通知は「計10件」だったが、その1件(persona_queue_cursor.json)は
    #   同じ改修で churn 側へ移した。残り9件を落とすのは副産物の判定だけが担う。
    _ok(len(mutant_byproduct(REAL_20260903_BYPRODUCTS)) == 9
        and dd.substantive_touched(REAL_20260903_BYPRODUCTS) == [],
        "must-fail: 副産物除去を消した変異体は実物9件を報告してしまう(本物は黙る)")

    # ★must-fail: 末尾を deliveries に依らず固定した変異体(= 2026-09-13 より前の実装)は、
    #   「次は走らない」場面でも「まだ走る」場面でも同じ事を言う= 予告と挙動が必ずずれる。
    def mutant_fixed_tail(touched, deliveries=None):
        return "時間切れで打ち切った。……続きが要るならもう一度言ってくれ。"   # ← 旧実装の末尾
    _mis = [d for d in (0, 1, 2, 3, 5)
            if dd.timeout_should_dead("timeout", None, d)
            is not ("dead-letter" in mutant_fixed_tail(many, d))]
    _ok(len(_mis) > 0 and all(
            dd.timeout_should_dead("timeout", None, d)
            is ("dead-letter" in dd.format_timeout_result(many, d))
            for d in (0, 1, 2, 3, 5)),
        f"must-fail: 末尾固定の変異体は deliveries={_mis} で予告と挙動がずれる(本物は全部一致)")

    # pick_timeout_touched: msg_id一致かつ打ち切り監査(rc==-1 / hard timeout)だけ拾う。
    entries = [
        {"msg_id": "M1", "rc": 0, "stdout_tail": "success", "touched": ["a.py"]},
        {"msg_id": "M2", "rc": -1, "stdout_tail": "hard timeout(強制終了)", "touched": ["b.py"]},
        {"msg_id": "M1", "rc": -1, "stdout_tail": "hard timeout(強制終了)", "touched": ["c.py"]},
        {"msg_id": "M1", "rc": -1, "stdout_tail": "hard timeout(強制終了)", "touched": ["d.py"]},
    ]
    _ok(dd.pick_timeout_touched(entries, "M1") == ["d.py"],
        "pick: M1の打ち切り監査を最新1件だけ拾う(成功rc=0は無視)")
    _ok(dd.pick_timeout_touched(entries, "M2") == ["b.py"], "pick: 別msg_idは混ぜない")
    _ok(dd.pick_timeout_touched(entries, "M9") == [], "pick: 該当なしは空")

    # ★must-fail: churnを落とさない変異体(そのまま返す)なら、churnだけの入力でも
    #   「実体あり」と誤判定して報告が非空になる=「churnだけ=黙る」の期待が壊れる。
    churn_only = ["~local\\_daemon_codever\\dept_hr-room.txt", "~local\\llm\\busy\\gunji.json"]
    def mutant_touched(touched):
        return [str(p).lstrip("~") for p in (touched or [])]   # ← churn除去を消した壊れた版
    _ok(len(mutant_touched(churn_only)) > 0
        and dd.substantive_touched(churn_only) == [],
        "must-fail: churn除去を消した変異体はchurnだけでも実体ありと誤る(本物は空)")

    # ================================================================
    # 打ち切りの確定結果を**表へ出すか裏だけに残すか**(2026-09-17)
    #   実物= Chami msg 1549968841197748421(品質管理部門)「これめっちゃ多くない?改善できない?」
    #   引用されたのは msg 1549967529835761705(09-17 11:17:36・研究室hq)=
    #   末尾が「★あんたが言い直す必要はない。」の mid-flight枝そのもの。
    #   実測(local/llm/send_audit.jsonl・09-13の文面改訂以降)= 17本
    #     = mid-flight 16 / dead-letter 1。16本は本文自身が手番ゼロだと宣言していた。
    # ================================================================
    print("\n-- 打ち切り通知の表/裏(timeout_result_should_post) --")
    _ok(dd.timeout_result_should_post(None) is True,
        "deliveries不明= 出す側へ倒す(fail-open。判定不能を沈黙の理由にしない)")
    _ok(dd.timeout_result_should_post(0) is False, "deliveries=0(まだ走る)= 表へ出さない")
    _ok(dd.timeout_result_should_post(1) is False,
        "deliveries=1(実物16本と同じ場面)= 表へ出さない")
    _ok(dd.timeout_result_should_post(dd.TIMEOUT_MAX_DELIVERIES) is True,
        "deliveries=上限(次は走らない)= 出す(本文の一手が本物の手番)")
    _ok(dd.timeout_result_should_post(5) is True, "deliveries=上限超= 出す")
    _ok(dd.timeout_result_should_post("x") is True, "壊れた値= 出す側へ倒す")

    # ★不変条件= 「表へ出す」と「dead-letterとして本文に書く」は**同じ deliveries で同じ答え**。
    #   これが崩れると「言い直す必要はないと書いてある文が表に出る」= 今回の苦情そのものへ戻る。
    for _dv in (0, 1, 2, 3, 5):
        _ok(dd.timeout_result_should_post(_dv)
            is dd.timeout_should_dead("timeout", None, _dv),
            f"deliveries={_dv}: 表へ出す判定と dead判定が一致(本文と挙動がずれない)")

    # --- 本物の Daemon._timeout_notice を回す(偽物はデータ源2つだけ・判定と分岐は本物) ---
    class _Stub(object):
        """_timeout_notice が触る物だけを持つ最小の器。

        ★偽物にするのは `_delivery_count`(queueを読む手)と `_timeout_result_line`
          (work_auditを読む手)の**2つだけ**。振り分けの判定・分岐は本物が走る
          (手順_must-fail検査「外へ出る手だけ偽物にし、判定と分岐は本物のまま呼ぶ」)。
        """
        def __init__(self, dl, line="時間切れで打ち切った。……"):
            self._dl, self._line, self.dept = dl, line, "aegis-gl"

        def _delivery_count(self, msg_id):
            return self._dl

        def _timeout_result_line(self, msg_id, deliveries=dd._DL_AUTO):
            # ★呼び側が deliveries を渡してきているか(queueを2回読んでいないか)も見る。
            self.passed_deliveries = deliveries
            return self._line

    _notice = dd.Daemon._timeout_notice            # 本物の実装をそのまま借りる

    _s = _Stub(1)
    _post, _quiet = _notice(_s, "M-midflight")
    _ok(_post == "" and _quiet != "",
        "mid-flight(deliveries=1)= 表は空・裏に残る(部屋へ1文字も出ない)")
    _ok(_s.passed_deliveries == 1,
        "deliveries は1回だけ読んで本文生成へ渡す(2箇所で別々に数えない)")

    _s = _Stub(dd.TIMEOUT_MAX_DELIVERIES)
    _post, _quiet = _notice(_s, "M-dead")
    _ok(_post != "" and _quiet == "", "dead-letter(deliveries=上限)= 表へ出す(本当の手番)")

    _s = _Stub(None)
    _post, _quiet = _notice(_s, "M-unknown")
    _ok(_post != "" and _quiet == "", "deliveries不明= 表へ出す(黙るより出す)")

    _s = _Stub(1, line="")
    _post, _quiet = _notice(_s, "M-empty")
    _ok(_post == "" and _quiet == "",
        "確定した成果が無い(本文が空)= 表も裏も空= 何もしない")

    # ★must-fail: 振り分けを消した変異体(=今日の朝までの実装。結果があれば必ず表へ出す)は、
    #   mid-flight の場面で**部屋へ出てしまう**。本物が黙る同じ入力で落ちることを見る。
    def mutant_always_post(obj, msg_id):
        line = obj._timeout_result_line(str(msg_id), obj._delivery_count(str(msg_id)))
        return (line, "") if line else ("", "")    # ← 旧実装: 表/裏の振り分けが無い
    _m = _Stub(1)
    _mpost, _mquiet = mutant_always_post(_m, "M-midflight")
    _r = _Stub(1)
    _rpost, _rquiet = _notice(_r, "M-midflight")
    _ok(_mpost != "" and _rpost == "" and _rquiet != "",
        "must-fail: 振り分け無しの変異体は mid-flight を表へ出す(本物は裏へ回す)")

    print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAIL"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
