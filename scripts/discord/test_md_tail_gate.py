#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""末尾マークダウン片ゲートの回帰ガード(2026-09-20・イージス研究室/C-038・C-053)。

守る不具合= Chami 便 msg 1551230317585760277「語尾に余計なやつ付いてるんだよね、恒久改善して」。
実物= msg 1551223793593360465(花海咲季)の末尾 `…組み込むわよ。``(空バッククォート)。

★ソースの文字列一致で「入っている」を確かめない= **本物の `apply_text_gates` を実行で通す**。
  偽物にするのは**外へ出る手**だけ(監査台帳の書き先・D-2のLLM往復)。判定は本物のまま。
★本文は手打ちしない= 受け入れ条件の実物は `local/llm/send_audit.jsonl` の**実際に投稿された
  本文**から引く(壊れた便・legit便の両方)。手で作った文字列は壊れ方を再現しない。
★本番の台帳へ1バイトも書かない= TONE_AUDIT を一時ファイルへ向け、前後で mtime/size を比較する。

使い方:
  python scripts/discord/test_md_tail_gate.py
  python scripts/discord/test_md_tail_gate.py --mutant off       # ゲート未配線へ戻す
  python scripts/discord/test_md_tail_gate.py --mutant greedy    # 末尾の柵を無条件に剥ぐ
  python scripts/discord/test_md_tail_gate.py --mutant survivor  # 「マスク後に生き残った柵だけ削る」旧案
いずれの変異体でも rc=1(赤)になること= この検査が本当に見張っている証拠。
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, os.path.join(ROOT, "scripts", "llm")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MUTANT = ""
if "--mutant" in sys.argv:
    MUTANT = sys.argv[sys.argv.index("--mutant") + 1]

import md_tail                                     # noqa: E402
import persona_send as ps                          # noqa: E402

SEND_AUDIT = os.path.join(ROOT, "local", "llm", "send_audit.jsonl")
PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}" + (f"\n       {extra}" if extra else ""))


def body_of(msg_id):
    """実際に投稿された本文を送信台帳から引く(手打ちしない)。"""
    with open(SEND_AUDIT, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or msg_id not in ln:
                continue
            try:
                row = json.loads(ln)
            except Exception:
                continue
            if str(row.get("msg_id")) == msg_id and row.get("body"):
                return row["body"]
    return None


# ---- 本番台帳の「前」を先に控える(検査が本番へ書いていないことを実測で示す)----------
def _stat(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


PROD = {p: _stat(p) for p in (
    os.path.join(ROOT, "local", "llm", "tone_audit.jsonl"),
    os.path.join(ROOT, "local", "llm", "send_audit.jsonl"),
    os.path.join(ROOT, "local", "llm", "english_audit.jsonl"),
)}

# ---- 外へ出る手だけを偽物にする ------------------------------------------------
TMPDIR = tempfile.mkdtemp(prefix="mdtail_")
ps.TONE_AUDIT = os.path.join(TMPDIR, "tone_audit.jsonl")     # 監査の書き先=検査用
try:
    import tone_rewrite                                       # D-2のLLM往復を止める
    tone_rewrite.rewrite_once = (lambda *a, **k:
                                 {"ok": False, "why": "検査=外へ出さない", "text": ""})
except Exception:
    pass

# ---- 変異体(must-fail) --------------------------------------------------------
if MUTANT == "off":
    ps._md_tail_gate = lambda body, tag="", quiet=False: body
elif MUTANT == "greedy":
    ps._md_tail_gate = (lambda body, tag="", quiet=False:
                        str(body or "").rstrip().rstrip("`").rstrip())
elif MUTANT == "survivor":
    _real_mask = md_tail._mask

    def _old_rule(body):
        """旧案= 「マスク後に生き残った柵だけ削る」。空インラインコードは潰れて素通りする。"""
        s = str(body or "")
        if "`" not in s:
            return None
        m = md_tail._TAIL_RE.search(s)
        if not m:
            return None
        k = m.start()
        masked = _real_mask(s)
        if masked is None or len(masked) != len(s):
            return None
        return k if "`" in masked[k:] else None

    md_tail.find_stray_tail = _old_rule

GATE_KW = dict(persona="ケヴィン・デブライネ", dept="aegis-gl", audit=True)


def gated(body):
    return ps.apply_text_gates(body, **GATE_KW)


print("== 層1= 受け入れ条件6件を apply_text_gates の実走で通す ==")

# 1. 句点直後の空バッククォート(Chamiが指した実物 msg 1551223793593360465)
b1 = body_of("1551223793593360465")
check("実物を台帳から引けた(手打ちしていない)", bool(b1), "send_audit に body が無い")
if b1:
    o1 = gated(b1)
    check("★条件1 末尾の空バッククォートが消える 実測=%r→%r" % (b1[-14:], o1[-14:]),
          o1.rstrip().endswith("組み込むわよ。") and "`" not in o1[-3:])
    check("条件1の裏 本文は末尾以外1文字も変わらない",
          o1 == b1[:len(o1)] and b1[len(o1):].strip("`\r\n\t ") == "")

# 2. 末尾の孤立フェンス(実物 msg 1546699715985543188)
b2 = body_of("1546699715985543188")
check("実物を台帳から引けた(孤立フェンス便)", bool(b2))
if b2:
    o2 = gated(b2)
    check("★条件2 孤立フェンス行が消える 実測=%r→%r" % (b2[-12:], o2[-12:]),
          not o2.rstrip().endswith("`") and o2.rstrip().endswith("なくていい。"))
    check("条件2の裏 本文中の他のバッククォートは残る 実測 前=%d 後=%d"
          % (b2.count("`"), o2.count("`")),
          o2.count("`") == b2.count("`") - 3)

# 3. 中身あり inline closer で終わる便(実物 msg 1545443526781829180)
b3 = body_of("1545443526781829180")
check("実物を台帳から引けた(--list 便)", bool(b3))
if b3:
    check("★条件3 `… --list` で終わる便は不変", gated(b3) == b3,
          "末尾=%r" % (gated(b3)[-30:],))

# 4. 正規コードブロックで終わる便(実物 msg 1549655140233908327)
b4 = body_of("1549655140233908327")
check("実物を台帳から引けた(正規コードブロック便)", bool(b4))
if b4:
    check("★条件4 開き+中身+閉じ柵は閉じを残す(不変)", gated(b4) == b4,
          "末尾=%r" % (gated(b4)[-30:],))

# 5. 本文中間に単体 ` を含む正常文(末尾は日本語)
b5 = "`local/llm/send_audit.jsonl` を数えた。末尾は普通の文で終わる。"
check("★条件5 中間のバッククォートは落とさない(不変)", gated(b5) == b5,
      "実測=%r" % (gated(b5),))

# 6. 空本文/バッククォート皆無
check("★条件6a 空本文は不変", gated("") == "")
check("★条件6b バッククォート皆無の本文は不変",
      gated("普通の返信だ。片は付いていない。") == "普通の返信だ。片は付いていない。")

print("== 層2= 削りすぎ(C-056)の実測= 送信台帳の全便へ当てて変化した件数を数える ==")
rows = []
with open(SEND_AUDIT, encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if not ln:
            continue
        try:
            row = json.loads(ln)
        except Exception:
            continue
        if row.get("body"):
            rows.append(row)
changed = [r for r in rows if md_tail.strip_stray_tail(r["body"])[1]]
tail_bq = [r for r in rows if r["body"].rstrip().endswith("`")]
check("台帳の実便を読めた(%d便・うち末尾バッククォート %d便)" % (len(rows), len(tail_bq)),
      len(rows) > 2000 and len(tail_bq) > 0)
check("★変化するのは末尾がバッククォートの便だけ 実測=%d件" % (len(changed),),
      all(r["body"].rstrip().endswith("`") for r in changed))
# ★件数(12/29)は台帳が伸びれば動く= 固定値で縛らない。2026-09-20 に**実物で選り分けた**
#   msg_id の帰属だけを縛る(stray は必ず削る / legit は必ず残す)。
STRAY_IDS = {"1545906113789169844", "1546699715985543188", "1546800242530455633",
             "1546878172317089873", "1546885973969739857", "1546930445630054543",
             "1548166592117084201", "1549651824397778945", "1549987337298124871",
             "1549995531848392776", "1551223793593360465", "1551232174592757841"}
LEGIT_IDS = {"1545443526781829180", "1545470045185122426", "1545637677708353546",
             "1545692297344196648", "1545917537693343855", "1547775887125123123",
             "1548495777293275230", "1549341207526645764", "1549525420309872833",
             "1549594051626663988", "1549655140233908327", "1549900069598138583",
             "1549948588447240334", "1550003432235077724", "1550240984322019429",
             "1550247368249577473", "1551150685607821412"}
_changed_ids = {str(r.get("msg_id")) for r in changed}
_miss = sorted(STRAY_IDS - _changed_ids)
check("★stray の実物%d件は全部削る 実測=残り%r" % (len(STRAY_IDS), _miss), not _miss)
_hurt = sorted(LEGIT_IDS & _changed_ids)
check("★legit の実物%d件は1件も削らない(C-056) 実測=削った%r" % (len(LEGIT_IDS), _hurt), not _hurt)
check("削った便に `--list`(中身あり closer)が1件も入っていない",
      not any("--list`" in r["body"].rstrip()[-20:] for r in changed))

print("== 層3= 配線= 合流点と bot_send の両方が正本を呼ぶ ==")
check("apply_text_gates が末尾ゲートを呼ぶ", "_md_tail_gate" in ps.apply_text_gates.__code__.co_names)
check("末尾ゲートは3ゲートの後ろ・_audit_structure の前",
      (list(ps.apply_text_gates.__code__.co_names).index("_md_tail_gate")
       > list(ps.apply_text_gates.__code__.co_names).index("_homo_gate"))
      and (list(ps.apply_text_gates.__code__.co_names).index("_md_tail_gate")
           < list(ps.apply_text_gates.__code__.co_names).index("_audit_structure")))
# ★bot_send は実走させない= main() がHTTPを撃つ口そのものだから(本番の部屋へ投げない)。
#   ここは「同じ正本を呼ぶ配線が在るか」だけを見る(炎上/同形異字ゲートの既存検査と同じ型)。
import bot_send as bs                               # noqa: E402
check("bot_send も同じ正本を呼ぶ(口が2つ在る・部分適用にしない)",
      "trailing_md_backstop" in bs.main.__code__.co_names
      and bs.trailing_md_backstop is md_tail.trailing_md_backstop)

print("== 層4= fail-open= lang_gate が読めない時は素通し(送信を殺さない) ==")
_real = md_tail._mask
md_tail._mask = lambda text: None
try:
    check("★マスク不能なら本文は不変(fail-open)",
          md_tail.trailing_md_backstop("片が付いた本文。``", quiet=True) == "片が付いた本文。``")
finally:
    md_tail._mask = _real
check("★削ると白紙になる本文は削らない(空便を投げない)",
      md_tail.trailing_md_backstop("```", quiet=True) == "```")

print("== 層5= 本番の台帳へ1バイトも書いていない(mtime+size の前後比較) ==")
for _p, _before in PROD.items():
    check("不変 %s 実測=%r" % (os.path.basename(_p), _stat(_p)), _stat(_p) == _before)
check("監査の書き先は検査用へ逃がしてある", ps.TONE_AUDIT.startswith(TMPDIR))
shutil.rmtree(TMPDIR, ignore_errors=True)

print(f"\n結果: {PASS} PASS / {FAIL} FAIL" + (f"  (mutant={MUTANT})" if MUTANT else ""))
sys.exit(1 if FAIL else 0)
