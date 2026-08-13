#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""起票の門(C-046)を**実行で**通す検査(2026-08-14 イージス研究室)。

なぜ要るか= HQが `request_log.jsonl` で1件を頭から追跡した実測=
    Chami便「**直った**」 → 部門はちゃんと返信 → **その返信に `<<WIP>>` が付いていた**
    → `working_detected` → **依頼を1つも含まない便が REQ として起票**され、最長12日立っていた。
  生きた REQ 143件のうち **17件が依頼ですらない**。
  = 起票の中身は「元の便」なのに、引き金は「返信側の状態」という**非対称**(C-046)。

やり方= 外へ出る手(台帳の書き先・request_log への記録・ログ出力)だけ偽物にし、
  **判定と分岐は本物のまま**回す(共通規律§3)。本番の `open_defects.jsonl` /
  `request_log.jsonl` へは1行も書かない。差し替え点= `session_relay.set_defects_path()`。

実行: python scripts/llm/test_request_gate.py
"""
import os
import sys
import json
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import session_relay as SR             # noqa: E402
import dept_daemon as dd               # noqa: E402

results = []
DEPT = "aegis-gl"
ROOM = "aegis-gl"
WIP_REPLY = "別件を続けている。終わったら出す。\n<<WIP>>"


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


class RecordSpy:
    """`session_relay._record` の代役。**本番の request_log へ書かず**呼ばれた引数を控える。"""

    def __init__(self):
        self.rows = []

    def __call__(self, request_id, dept, state, evidence=""):
        self.rows.append({"msg": str(request_id), "dept": dept,
                          "state": state, "evidence": evidence})

    def states(self):
        return [r["state"] for r in self.rows]


def chami(mid, content, ts="2026-08-14T05:00:00"):
    return {"msg_id": str(mid), "author": "Chami", "content": content, "ts": ts}


def ledger_rows(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def opens(path, kind="request"):
    return [r for r in ledger_rows(path)
            if r.get("op") == "open" and r.get("kind") == kind]


def run():
    tmpdir = tempfile.mkdtemp(prefix="reqgate_")
    ledger = os.path.join(tmpdir, "open_defects.jsonl")
    old_path = SR.set_defects_path(ledger)
    old_record, old_log = SR._record, dd.log
    spy = RecordSpy()
    SR._record = spy
    dd.log = lambda dept, msg: None          # ★ログも外へ出る手=黙らせる(本番のログを汚さない)
    try:
        d = dd.Daemon(DEPT, dry_run=True)    # ★本物のインスタンス(判定は全部本物)

        # === 1) HQが追跡した実話そのもの: 「直った」+ 返信に <<WIP>> ===
        print("\n[1] 依頼を含まない便(「直った」)に <<WIP>> の返信が付いた場合")
        w = d._note_waiting(chami("1537384908530393109", "直った"), WIP_REPLY, ROOM)
        check("`<<WIP>>` は今までどおり検出される(追撃便の引き金は現状維持)", w == dd.WIP_MARKER)
        check("request_log には working_detected が1行出る",
              spy.states().count("working_detected") == 1)
        check("★台帳には1件も積まれない(これが C-046① の本体)", len(opens(ledger)) == 0)

        # === 2) 実依頼なら今までどおり積む(取りこぼしを作っていないこと) ===
        print("\n[2] 実依頼(「不要な窓は閉じといて」)")
        d._note_waiting(chami("1532957341362819243", "不要な窓は閉じといて"), WIP_REPLY, ROOM)
        rows = opens(ledger)
        check("台帳へ1件積まれる", len(rows) == 1)
        check("★close_when が1行入っている(C-046②)",
              bool(rows and str(rows[0].get("close_when") or "").strip()))
        check("symptom は元の便の中身", rows and rows[0]["symptom"] == "不要な窓は閉じといて")
        check("broken は元の便の在りか(msg_id)",
              rows and "1532957341362819243" in rows[0]["broken"])

        # === 3) 催促は新規起票しない。既存へ寄せて待ち時間を更新する(C-046③) ===
        print("\n[3] 催促(「まだ?」)が、既存の依頼が在る部屋へ来た場合")
        before = len(opens(ledger))
        d._note_waiting(chami("1533157925344772126", "まだすか、1時間経ってますけど"),
                        WIP_REPLY, ROOM)
        after = opens(ledger)
        check("★新規IDを発行しない(件数が増えない)", len(after) == before)
        notes = [r for r in ledger_rows(ledger)
                 if r.get("op") == "note" and r.get("note_kind") == "nudge"]
        check("催促は note として既存REQへ寄る", len(notes) == 1)
        check("寄せた先は既存の依頼のID", notes and notes[0]["id"] == after[0]["id"])
        check("request_log に request_nudged が残る", "request_nudged" in spy.states())
        folded = SR.open_request_list(DEPT)
        check("★畳んだ結果に催促が1件見える(=待ち時間の更新が読める)",
              folded and len(folded[0].get("nudges") or []) == 1)
        check("催促を受けても状態は未確認のまま(自動closeしない・C-024)",
              folded and folded[0]["status"] == SR.DEFECT_OPEN)
        block = SR.requests_block(DEPT)
        check("起動文の一覧に閉じる条件が載る", "★閉じる条件=" in block)
        check("起動文の一覧に催促の件数が載る", "★Chamiからの催促 1件" in block)

        # === 4) 相槌・完了報告だけの便(HQが17件と数えた型) ===
        print("\n[4] 相槌・完了報告だけの便")
        for i, (txt, why) in enumerate([("出た。OK!", "完了報告"),
                                        ("出たのでok", "完了報告+相槌"),
                                        ("進捗は?", "催促"),
                                        ("ありがとうございます", "相槌")], 1):
            n0 = len(opens(ledger))
            d._note_waiting(chami(f"90000000000000000{i}", txt), WIP_REPLY, ROOM)
            check(f"{why}「{txt}」で新規起票しない", len(opens(ledger)) == n0)

        # === 5) 相槌の後ろに実依頼が付いている便は落とさない(HQ §4の警告) ===
        print("\n[5] 相槌+実依頼(「OK。①割引が…」型)")
        n0 = len(opens(ledger))
        d._note_waiting(chami("900000000000000011", "OK。①割引が効いてないから直して"),
                        WIP_REPLY, ROOM)
        check("相槌で始まっても、依頼が在れば積む", len(opens(ledger)) == n0 + 1)
        n0 = len(opens(ledger))
        d._note_waiting(chami("900000000000000012", "①-A Go"), WIP_REPLY, ROOM)
        check("短い指示(「①-A Go」)も積む(既定は起票へ倒す)", len(opens(ledger)) == n0 + 1)

        # === 6) 既存の安全弁を壊していないこと ===
        print("\n[6] 既存の安全弁(Chami以外・追撃便・止まりの申告なし)")
        n0 = len(opens(ledger))
        other = {"msg_id": "900000000000000013", "author": "シャビ・アロンソ",
                 "content": "これを直してくれ", "ts": "2026-08-14T05:00:00"}
        d._note_waiting(other, WIP_REPLY, ROOM)
        check("Chami以外の便では積まない", len(opens(ledger)) == n0)
        s0 = len(spy.rows)
        d._note_waiting(chami("WORK-900000000000000014", "これを直して"), WIP_REPLY, ROOM)
        check("追撃便そのものには追撃しない(記録も起票もしない)",
              len(spy.rows) == s0 and len(opens(ledger)) == n0)
        d._note_waiting(chami("900000000000000015", "これを直して"), "直した。以上だ。", ROOM)
        check("返信が止まりを申告していなければ何も起きない(引き金は今までどおり)",
              len(spy.rows) == s0 and len(opens(ledger)) == n0)

        # === 7) 寄せる先が1件も無い催促は、沈黙させずに起票する ===
        print("\n[7] 未完了が0件の部屋へ催促が来た場合(倒す向き=可視化)")
        ledger2 = os.path.join(tmpdir, "empty.jsonl")
        SR.set_defects_path(ledger2)
        d._note_waiting(chami("900000000000000016", "まだ?"), WIP_REPLY, ROOM)
        rows2 = opens(ledger2)
        check("寄せる先が無い催促は起票される(黙って落とさない)", len(rows2) == 1)
        check("その起票にも close_when が入っている",
              rows2 and bool(str(rows2[0].get("close_when") or "").strip()))
        SR.set_defects_path(ledger)

        # === 8) 判定そのもの(純粋関数)。HQが「依頼ですらない」と数えた実文面 ===
        print("\n[8] classify_ask(元の便の中身だけを見る純粋関数)")
        for txt, want in [("直った", "ack"), ("出た。OK!", "ack"), ("出たのでok", "ack"),
                          ("進捗は?", "nudge"), ("まだ?", "nudge"),
                          ("まだですか、9時間寝ました", "nudge"),
                          ("不要な窓は閉じといて", "request"), ("再開して", "request"),
                          ("これも", "request"), ("OK。①割引が効いてないから直して", "request"),
                          ("ここを潰すようにして。担当は任せるよ！", "request")]:
            kind, cw = dd.classify_ask(txt)
            check(f"「{txt}」→ {want}", kind == want)
            if want != "ack":
                check(f"「{txt}」に close_when が書ける", bool(cw))
        check("本文が空の便は ack(積まない)", dd.classify_ask("")[0] == "ack")

        # === 9) 本番の台帳を1行も触っていないこと ===
        print("\n[9] 汚染の確認")
        check("差し替え先が本番の台帳ではない", os.path.abspath(ledger)
              != os.path.abspath(SR.DEFECTS_FILE))
        check("検査中の書き込みは全部 tmp 側へ行った", len(ledger_rows(ledger)) > 0)
    finally:
        SR.set_defects_path(old_path)
        SR._record = old_record
        dd.log = old_log


run()
ok = sum(1 for _, c in results if c)
print(f"\n=== {ok}/{len(results)} PASS ===")
for name, c in results:
    if not c:
        print(f"  FAIL: {name}")
sys.exit(0 if ok == len(results) else 1)
