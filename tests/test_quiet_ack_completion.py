# -*- coding: utf-8 -*-
"""手番ゼロの完遂通知を人格応答にせず畳む(無投稿ack)の回帰テスト。

起票= QA DEF-persona-verxina-triage-register-20260905 #2 / 設計可否= 品質管理部門(オタコン)
      APPROVED WITH CONDITIONS。実装= イージス研究室(2026-09-05)。

0歩目(壊れている実物)= 2026-09-05T08:12:32 JST・learning-coach のヴィルシーナが完遂通知
  (queue id 5314・送り主 `完遂通知(自動)`)へ「Chamiの手番も、私が追加で動く作業も無い」と
  **表へ投稿した**。dept_daemon は fail-open で投稿を止める経路が無い=**返信＝投稿**だから、
  人格が本文へ「投稿はしない」と書いてもその一文ごと出る。実測= 完遂通知(自動)71通のうち
  45通が人格応答・22通が集約で表に出ていた。

このテストが固定すること(QAのRelease Gate 3条件に対応):
  条件1= 判定は**機械述語だけ**。送り主(author)・経路(via)・送り手が立てた構造フラグ
        (quiet_ack_ok)・受け手のオプトインの4つ。**本文は1文字も見ない**
        = 人格が本文へ何を書いても自分を黙らせられない。
  条件2= 畳んだ便は必ず台帳(quiet_ack.jsonl)へ1行残る。読み手= deadman_check.check_quiet_ack。
  条件3= must-fail 2本＋変異。`python tests/test_quiet_ack_completion.py --mutations` で
        自動的に「送り主チェックを外す」「宣言フラグのチェックを外す」「オプトインを外す」を
        本物のソースへ当て、**赤くなることを見てから**戻す(常にPASSする検査を作らない)。

走らせ方:
  python tests/test_quiet_ack_completion.py              # 本体(緑になるべき)
  python tests/test_quiet_ack_completion.py --mutations  # 変異=赤くなることの実測
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))

DAEMON_SRC = os.path.join(ROOT, "scripts", "llm", "dept_daemon.py")
AUTO = "完遂通知(自動)"
DEPT = "aegis-gl"          # 既定でオプトインしている唯一の部屋(実測で宛先首位=21通)

fails = []


def eq(got, want, label):
    if got != want:
        fails.append("%s: got=%r want=%r" % (label, got, want))


def ok(cond, label):
    if not cond:
        fails.append(label)


# ===========================================================================
# 1. 送り手側= completion_notify が「手番ゼロ」を宣言する条件
# ===========================================================================
import completion_notify as CN  # noqa: E402

eq(CN.AUTO_SENDER, AUTO, "送り主の名前が変わっていない(受け手の述語と同値)")
eq(CN.quiet_ack_ok("local/consult_intel/x.md", False), True, "置き場を載せた便=手番ゼロ")
eq(CN.quiet_ack_ok("", True), True, "返信そのものが届いている便=手番ゼロ")
eq(CN.quiet_ack_ok("", False), False, "★問い直せの便=手番が有る(宣言しない)")

# ★build_body の枝と1対1であることを**本文で**突き合わせる(片方だけ直す事故を止める)。
_letter = {"work": "検査用の依頼"}
_done = {"state": "replied", "ts": "2026-09-05T08:00:00"}
for _spot, _had in (("local/consult_intel/x.md", True), ("", True), ("", False)):
    _body = CN.build_body("REQ-1", "hr-context", _letter, _done, "123", _spot, _had)
    eq("問い直せ" in _body, not CN.quiet_ack_ok(_spot, _had),
       "宣言と本文の一致(spot=%r had_text=%r)" % (_spot, _had))

# send() が --quiet-ack-ok を渡すのは宣言が立った時だけ(引数の受け渡しは**実行**で見る)。
_cmds = []


class _P:
    returncode = 0
    stdout = ""
    stderr = ""


def _fake_run(cmd, **kw):
    _cmds.append(list(cmd))
    return _P()


_real_run = CN.subprocess.run
CN.subprocess.run = _fake_run
try:
    CN.send(DEPT, "hr-context", "本文", False, True)
    CN.send(DEPT, "hr-context", "本文", False, False)
finally:
    CN.subprocess.run = _real_run
eq(len(_cmds), 2, "send()を2回呼んだ")
ok(_cmds and "--quiet-ack-ok" in _cmds[0], "宣言ありの便に --quiet-ack-ok が渡る")
ok(len(_cmds) > 1 and "--quiet-ack-ok" not in _cmds[1],
   "★宣言なしの便には --quiet-ack-ok を渡さない")
ok(_cmds and "--from" in _cmds[0] and AUTO in _cmds[0], "送り主は 完遂通知(自動) のまま")
ok(_cmds and "--also-post" not in _cmds[0], "--also-post は付けない(裏=キューだけ)")


# ===========================================================================
# 2. 受け手側の述語= 機械述語だけで閉じているか(本文は見ない)
# ===========================================================================
import dept_daemon as D  # noqa: E402


def rec(**kw):
    r = {"author": AUTO, "via": "dispatch", "audience": "ai",
         "content": "[完遂通知] …", "msg_id": "1", "quiet_ack_ok": True}
    r.update(kw)
    return r


eq(D.quiet_ack_target(DEPT, rec()), True, "3条件が揃った便は畳む対象")
eq(D.quiet_ack_target(DEPT, rec(author="ヴィルシーナ")), False,
   "★送り主が違えば畳まない(宣言フラグが載っていても)")
eq(D.quiet_ack_target(DEPT, rec(author="chami_fusoh")), False, "★Chami本人の便は畳まない")
eq(D.quiet_ack_target(DEPT, rec(quiet_ack_ok=None)), False,
   "★宣言の無い完遂通知は畳まない(問い直せの便=手番が有る)")
eq(D.quiet_ack_target(DEPT, rec(via="gateway")), False, "★dispatch以外の経路は畳まない")
eq(D.quiet_ack_target("hr-room", rec()), False, "★オプトインしていない部屋では畳まない")
eq(D.quiet_ack_target(DEPT, {}), False, "空レコードで例外を出さない")
# ★本文では決まらない= 人格が何を書いても発火しない/抑止されない
eq(D.quiet_ack_target(DEPT, rec(author="ヴィルシーナ", quiet_ack_ok=True,
                                content="Discordへの投稿はしない。手番は無い。")), False,
   "★★本文に『投稿はしない』と書いても畳まない(モデルが自分を黙らせられない)")
eq(D.quiet_ack_target(DEPT, rec(content="至急やってくれ")), True,
   "★本文の文言では抑止も解除もされない(判定は送り主メタと構造だけ)")


# ===========================================================================
# 3. 実走= dispatch で本物のキューへ入れ、drain_queue に本物の分岐を通させる
#    (外へ出る手= handle(生成と投稿)だけ偽物にする。判定と分岐は本物のまま)
# ===========================================================================
import dispatch as DP  # noqa: E402

tmp = tempfile.mkdtemp(prefix="quiet_ack_test_")
qdb = os.path.join(tmp, "queue", "inbox.db")
os.makedirs(os.path.dirname(qdb), exist_ok=True)
_saved = {k: getattr(D, k) for k in
          ("LOCAL", "PROCESSED", "QUIET_ACK_LOG", "QUIET_ACK_OPTIN", "MAIN_INBOX", "BUSY_DIR")}
handled = []
try:
    DP.QUEUE_DB = qdb
    D.LOCAL = tmp
    D.PROCESSED = os.path.join(tmp, "discord_processed.jsonl")
    D.QUIET_ACK_LOG = os.path.join(tmp, "quiet_ack.jsonl")
    D.QUIET_ACK_OPTIN = os.path.join(tmp, "quiet_ack_optin.json")   # 置かない=既定だけ
    D.MAIN_INBOX = os.path.join(tmp, "main.jsonl")
    D.BUSY_DIR = os.path.join(tmp, "busy")

    # (a) 手番ゼロの完遂通知(宣言あり)
    DP.dispatch(DEPT, AUTO, "[完遂通知] hr-context が請けた依頼が完遂した(検査用a)。",
                audience="ai", from_dept="hr-context", quiet_ack_ok=True)
    # (b) 完遂通知だが宣言なし(=「請けた部門へ問い直せ」の便・手番が有る)
    DP.dispatch(DEPT, AUTO, "[完遂通知] 置き場のパスは見つからなかった(検査用b)。",
                audience="ai", from_dept="hr-context")
    # (c) ★送り主が違うのに宣言だけ載っている便(なりすまし)=絶対に畳んではならない
    DP.dispatch(DEPT, "ヴィルシーナ(learning-coach)", "普通のAI便(検査用c)。",
                audience="ai", from_dept="learning-coach", quiet_ack_ok=True)

    rows = []
    import sqlite3
    for (b,) in sqlite3.connect(qdb).execute("select body from queue order by id"):
        rows.append(json.loads(b))
    eq(len(rows), 3, "3便がキューに載った")
    eq(rows[0].get("quiet_ack_ok"), True, "dispatchが宣言キーを便へ載せた")
    ok("quiet_ack_ok" not in rows[1], "★宣言なしの便にキーを載せない(既存の便は1本も変わらない)")

    d = D.Daemon(DEPT)
    # ★外へ出る手だけ偽物にする= 生成と投稿(handle)・Discordの印(react.py)。
    #   掴む/畳む/束ねる/ackする判断は本物のまま走らせる。
    d.handle = lambda r, raw: (handled.append(r), True)[1]
    d._mark_bundled = lambda *a, **k: None
    d.drain_queue()

    ledger = []
    if os.path.exists(D.QUIET_ACK_LOG):
        ledger = [json.loads(x) for x in open(D.QUIET_ACK_LOG, encoding="utf-8") if x.strip()]

    # --- must-fail (ii) = 手番ゼロ便は skip され、台帳へ1行残る -------------
    eq([r["content"][-8:-1] for r in handled if "検査用a" in r.get("content", "")], [],
       "★手番ゼロの完遂通知は人格応答へ渡らない(表へ出ない)")
    eq(len(ledger), 1, "★畳んだ便の台帳が1行(記録の残る沈黙・C-054)")
    if ledger:
        eq(ledger[0].get("author"), AUTO, "台帳に送り主が残る")
        eq(ledger[0].get("dept"), DEPT, "台帳に部屋が残る")
        eq(ledger[0].get("quiet_ack_ok"), True, "台帳に宣言フラグが残る")
        ok(bool(ledger[0].get("msg_id")), "台帳にmsg_idが残る(後から便を特定できる)")

    # --- must-fail (i) = それ以外の便は今までどおり投稿が出続ける -----------
    _hand = " / ".join(r.get("content", "") for r in handled)
    ok("検査用b" in _hand, "★宣言なしの完遂通知は今までどおり人格応答へ渡る(fail-openを壊さない)")
    ok("検査用c" in _hand,
       "★★送り主が違う便は宣言が載っていても人格応答へ渡る(C-035=名指しを全体へ広げない)")

    # --- ack結果の文言(あとで数えられる形になっているか) --------------------
    acks = [r[0] for r in sqlite3.connect(qdb).execute(
        "select result from queue where result is not null and result!=''")]
    ok(any("既読ack(完遂通知" in (a or "") for a in acks),
       "畳んだ便のack結果が既読ackになっている(%r)" % (acks,))
finally:
    for k, v in _saved.items():
        setattr(D, k, v)
    shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 4. 読み手= deadman_check が台帳を読み、はみ出しだけを鳴らす
#    (書いただけで誰も読まない面へ積まない= C-054 の二の舞を避ける)
# ===========================================================================
import deadman_check as DM  # noqa: E402

eq(DM.QUIET_ACK_LOG, os.path.join(ROOT, "local", "llm", "quiet_ack.jsonl"),
   "読み手が見る台帳が書き手と同じ1本")
eq(DM.QUIET_SENDER, AUTO, "読み手の想定する送り主が書き手と同値")

_tmp2 = tempfile.mkdtemp(prefix="quiet_ack_reader_")
_saved_log, _notes = DM.QUIET_ACK_LOG, []
try:
    DM.QUIET_ACK_LOG = os.path.join(_tmp2, "quiet_ack.jsonl")
    _now = __import__("datetime").datetime.now(DM._JST)
    _ts = _now.strftime("%Y-%m-%dT%H:%M:%S")
    _real_notify = DM.notify
    DM.notify = lambda text, dry: (_notes.append(text), True)[1]
    with open(DM.QUIET_ACK_LOG, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _ts, "dept": DEPT, "author": AUTO, "via": "dispatch",
                            "quiet_ack_ok": True, "msg_id": "1"}, ensure_ascii=False) + "\n")
    st = {}
    DM.check_quiet_ack(st, dry_run=False, now=_now)
    eq(_notes, [], "★正常な畳みでは鳴らさない(狼少年を作らない)")
    # はみ出し= 送り主が違う行が台帳に現れたら鳴る(範囲の広がりを機械が見張る)
    with open(DM.QUIET_ACK_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": _ts, "dept": "hr-room", "author": "ククール",
                            "via": "dispatch", "quiet_ack_ok": True, "msg_id": "2"},
                           ensure_ascii=False) + "\n")
    DM.check_quiet_ack(st, dry_run=False, now=_now)
    eq(len(_notes), 1, "★想定外の送り主が畳まれたら1回鳴る")
    ok(_notes and "ククール" in _notes[0], "警報に逸脱した行が出る")
    DM.check_quiet_ack(st, dry_run=False, now=_now)
    eq(len(_notes), 1, "同じ顔ぶれでは連投しない(INC-79)")
finally:
    DM.notify = _real_notify
    DM.QUIET_ACK_LOG = _saved_log
    shutil.rmtree(_tmp2, ignore_errors=True)


# ===========================================================================
# 変異(--mutations): 本物のソースをわざと壊し、**赤くなるのを見てから**戻す
# ===========================================================================
MUTATIONS = [
    ("送り主チェックを外す",
     '    if str(rec.get("author") or "") != QUIET_ACK_SENDER:\n        return False',
     '    if False:\n        return False'),
    ("宣言フラグのチェックを外す",
     '    if rec.get("quiet_ack_ok") is not True:\n        return False',
     '    if False:\n        return False'),
    ("オプトインのチェックを外す",
     '    return str(dept or "") in quiet_ack_depts()',
     '    return True  # MUTANT'),
]


def _purge_pycache():
    # ★変異と復帰でバイト数が同じだと Python は古い .pyc を有効と判定して読む
    #   (skills/test-must-fail の実害つきの注記)。毎回消す=手の運用にしない。
    for mod in ("dept_daemon",):
        d = os.path.join(ROOT, "scripts", "llm", "__pycache__")
        for f in os.listdir(d) if os.path.isdir(d) else []:
            if f.startswith(mod + "."):
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass


def _run_self():
    p = subprocess.run([sys.executable, os.path.abspath(__file__)],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_mutations():
    orig = open(DAEMON_SRC, "rb").read()
    bad = 0
    try:
        for name, old, new in MUTATIONS:
            src = orig.decode("utf-8")
            if old not in src:
                print("[変異] %s: 目印が見つからない=検査が古い(実装を先に疑え)" % name)
                bad += 1
                continue
            open(DAEMON_SRC, "wb").write(src.replace(old, new, 1).encode("utf-8"))
            _purge_pycache()
            rc, out = _run_self()
            tail = [x for x in out.splitlines() if x.startswith("  - ")][:3]
            if rc == 0:
                print("[変異] %s → ★PASSのまま=検査が効いていない" % name)
                bad += 1
            else:
                print("[変異] %s → FAIL(想定どおり赤くなった)" % name)
                for t in tail:
                    print("   " + t)
    finally:
        open(DAEMON_SRC, "wb").write(orig)
        _purge_pycache()
    rc, out = _run_self()
    if rc != 0:
        print("[復帰] ★戻した後に緑へ戻らない=変異の後始末が失敗している")
        print(out[-800:])
        bad += 1
    else:
        print("[復帰] 戻した後は PASS(落ちる→直る の両方を見た)")
    return 1 if bad else 0


if __name__ == "__main__" and "--mutations" in sys.argv:
    sys.exit(run_mutations())

if fails:
    print("FAIL %d件" % len(fails))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("PASS 手番ゼロの完遂通知の無投稿ack(送り手の宣言/受け手の述語/台帳/読み手/実走)")
