#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地の文の裸バッククォート・ゲートの回帰ガード(2026-09-21・イージス研究室)。

起点= Chami 便 msg 1551266364231000136「余計なコードブロックいらんて」。
壊れていた実物= msg 1551239290879475896(デブライネ)= Discord 上で**14区間・722字**の
日本語がコード扱いになっていた便。

★ソースの文字列一致で確かめない= 本物の `persona_send.apply_text_gates` を実走させる。
  偽物にするのは**外へ出る手**だけ(監査台帳の書き先・D-2のLLM往復)。判定は本物のまま。
★本文は手打ちしない= 受け入れ条件の実物は `local/llm/send_audit.jsonl` の**実際に投稿された
  本文**から引く(壊れた便・legit便の両方)。手打ちは fail-open の陰性対照だけに使う。
★本番の台帳へ1バイトも書かない= TONE_AUDIT を一時ファイルへ向け、前後で mtime/size を比較する。

使い方:
  python scripts/discord/test_md_ticks_gate.py
  python scripts/discord/test_md_ticks_gate.py --mutant off        # ゲート未配線へ戻す
  python scripts/discord/test_md_ticks_gate.py --mutant greedy     # 柵を無条件に逃がす
  python scripts/discord/test_md_ticks_gate.py --mutant nofence    # コードブロックの保護を外す
  python scripts/discord/test_md_ticks_gate.py --mutant quoteonly  # 引用符の中だけ見る(旧案)
いずれの変異体でも rc=1(赤)になること= この検査が本当に見張っている証拠。
"""

import json
import os
import re
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

import md_ticks                                    # noqa: E402
import persona_send as ps                          # noqa: E402

SEND_AUDIT = os.path.join(ROOT, "local", "llm", "send_audit.jsonl")
BROKEN_MSG = "1551239290879475896"                 # Chamiが「余計なコードブロック」と指した便
JP = re.compile(r"[ぁ-んァ-ヶ一-龥]")
PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}" + (f"\n       {extra}" if extra else ""))


def rows():
    out = []
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
                out.append(row)
    return out


def body_of(msg_id, all_rows):
    for row in all_rows:
        if str(row.get("msg_id")) == msg_id:
            return row["body"]
    return None


def swallowed(text):
    """コード扱いになる区間の合計字数(Discord と同じ読み方=読み取り専用の道具)。"""
    return sum(len(c) for _, _, c in md_ticks.code_spans(text))


# ---- 本番台帳の「前」を先に控える ----------------------------------------------
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
TMPDIR = tempfile.mkdtemp(prefix="mdticks_")
ps.TONE_AUDIT = os.path.join(TMPDIR, "tone_audit.jsonl")     # 監査の書き先=検査用
try:
    import tone_rewrite                                       # D-2のLLM往復を止める
    tone_rewrite.rewrite_once = (lambda *a, **k:
                                 {"ok": False, "why": "検査=外へ出さない", "text": ""})
except Exception:
    pass

# ---- 変異体(must-fail) --------------------------------------------------------
if MUTANT == "off":
    ps._md_ticks_gate = lambda body, tag="", quiet=False: body
elif MUTANT == "greedy":
    md_ticks.find_literal_runs = (lambda body:
                                  [(m.start(), m.end())
                                   for m in md_ticks._RUN_RE.finditer(str(body or ""))])
elif MUTANT == "nofence":
    md_ticks._fence_spans = lambda text: []
elif MUTANT == "quoteonly":
    md_ticks._INLINE_WS = ""                      # 旧案= 引用符でくるまれた柵しか見ない

GATE_KW = dict(persona="ケヴィン・デブライネ", dept="aegis-gl", audit=True)


def gated(body):
    return ps.apply_text_gates(body, **GATE_KW)


ROWS = rows()

print("== 層1= 壊れていた実物(msg %s)を apply_text_gates の実走で通す ==" % BROKEN_MSG)
b = body_of(BROKEN_MSG, ROWS)
check("実物を台帳から引けた(手打ちしていない)", bool(b), "send_audit に body が無い")
if b:
    before = md_ticks.code_spans(b)
    check("★壊れ方の再現= ゲート前は %d区間・%d字がコード扱い" % (len(before), swallowed(b)),
          swallowed(b) > 700 and any(len(c) > 150 for _, _, c in before))
    o = gated(b)
    after = md_ticks.code_spans(o)
    long_ones = [c for _, _, c in after if len(c) > 40 or "\n" in c]
    check("★条件1 地の文を飲む塊が1つも残らない 実測=%d字→%d字 / 最長%d字"
          % (swallowed(b), swallowed(o), max([len(c) for _, _, c in after] or [0])),
          not long_ones, repr(long_ones[:1]))
    check("★条件2 コード片の中身は元の意図どおり(実測=%r…)"
          % ([c for _, _, c in after][:3],),
          [c for _, _, c in after][:2] == ["11474a8", "mask(全文)[:k]"])
    check("★条件3 見える文字は1字も減らない(消さずに逃がす)",
          o.replace("\\`", "`") == b, "本文が改変されている")
    check("条件4 逃がしたのは3か所(柵6本)だけ 実測=%d本" % (o.count("\\`"),),
          md_ticks.escape_literal_ticks(b)[1] == 3 and o.count("\\`") == 6)
    check("条件5 逃がした先は「```」「``」と孤立柵",
          "「\\`\\`\\`」" in o and "「\\`\\`」" in o and " \\` " in o)

print("== 層2= 台帳の実便%d件を通して、悪化する便が1件も無い ==" % len(ROWS))
worse, better, touched = [], [], []
for r in ROWS:
    out, n = md_ticks.escape_literal_ticks(r["body"])
    if out == r["body"]:
        continue
    touched.append(r.get("msg_id"))
    d = md_ticks.prose_swallowed(out) - md_ticks.prose_swallowed(r["body"])
    (worse if d > 0 else better).append(r.get("msg_id"))
check("★地の文を飲む量が増えた便=0 実測=%r" % (worse[:3],), not worse)
check("★総コード扱い量も増やさない 実測=%d便で増" %
      (len([i for i in touched
            if swallowed(md_ticks.escape_literal_ticks(
                body_of(i, ROWS))[0]) > swallowed(body_of(i, ROWS))]),),
      not [i for i in touched
           if swallowed(md_ticks.escape_literal_ticks(body_of(i, ROWS))[0])
           > swallowed(body_of(i, ROWS))])
check("★手を入れる便は在る(何もしないゲートではない) 実測=%d便" % (len(touched),), len(touched) > 0)


def _fence_bodies(text):
    sp = md_ticks._fence_spans(text) or []
    return [text[a:b] for a, b in sp]


fenced = [r for r in ROWS if _fence_bodies(r["body"])]
kept = [r for r in fenced
        if _fence_bodies(md_ticks.escape_literal_ticks(r["body"])[0]) != _fence_bodies(r["body"])]
check("★正規コードブロックを含む実便%d件で、ブロックの中身が1字も変わらない 実測=崩れ%d件"
      % (len(fenced), len(kept)), not kept, repr([r.get("msg_id") for r in kept][:3]))

print("== 層3= 配線= 合流点と bot_send の両方が正本を呼ぶ ==")
names = list(ps.apply_text_gates.__code__.co_names)
check("apply_text_gates が裸柵ゲートを呼ぶ", "_md_ticks_gate" in names)
check("裸柵ゲートは末尾ゲートの後ろ・_audit_structure の前",
      names.index("_md_ticks_gate") > names.index("_md_tail_gate")
      and names.index("_md_ticks_gate") < names.index("_audit_structure"))
import bot_send as bs                               # noqa: E402
check("bot_send も同じ正本を呼ぶ(口が2つ在る・部分適用にしない)",
      "literal_tick_backstop" in bs.main.__code__.co_names
      and bs.literal_tick_backstop is md_ticks.literal_tick_backstop)

print("== 層4= 触らない側(陰性対照)と fail-open ==")
_fence = "説明だよ。\n```python\nx = ' ` '\n```\nここまで。"
check("★正規コードブロックの中身は触らない",
      md_ticks.escape_literal_ticks(_fence)[1] == 0)
check("★行頭/行末に接する柵は触らない(開き柵・閉じ柵の可能性)",
      md_ticks.escape_literal_ticks("前の行\n```\nあと\n```\n")[1] == 0)
check("★中身のあるインラインコードは触らない",
      md_ticks.escape_literal_ticks("`--list` と `11474a8` を見る。")[1] == 0)
check("★既に逃がしてある柵を二重に逃がさない",
      md_ticks.escape_literal_ticks("型は 「\\`\\`\\`」 だった。")[1] == 0)
_real = md_ticks._fence_re
md_ticks._fence_re = lambda: None
try:
    check("★lang_gate が読めない時は本文不変(fail-open)",
          md_ticks.literal_tick_backstop("中間の ` は触らない。", quiet=True)
          == "中間の ` は触らない。")
finally:
    md_ticks._fence_re = _real

print("== 層6= 配線した後に実際に出た便で、地の文を飲む塊が1つも無い(生きた見張り) ==")
# ★改悪スタンプ(Chami msg 1551266364231000136)の④= 「次の変更で壊れたら赤くなる検査」。
#   層1〜4はコードの振る舞いを見る= 配線を外されても層3で赤くなる。ここはその外側で、
#   **本番へ実際に出た便**を見る= ゲートを迂回する新しいOUT口が生えた時にも赤くなる。
WIRED_AT = "2026-09-21T01:33:46"                   # 配線 commit 1eedfde の時刻(JST)
_after = [r for r in ROWS if str(r.get("ts", "")) >= WIRED_AT]
_swal = [(r.get("msg_id"), md_ticks.prose_swallowed(r["body"])) for r in _after]
_swal = [x for x in _swal if x[1] > 0]
check("★配線後の実便%d件に、地の文を飲む便は0件" % len(_after), not _swal, repr(_swal[:3]))
check("見張りが空回りしていない(配線後の実便が台帳に在る)", len(_after) > 0,
      "配線後の便がまだ1件も無い= この層はまだ何も見ていない")

print("== 層5= 本番の台帳へ1バイトも書いていない(mtime+size の前後比較) ==")
for _p, _before in PROD.items():
    check("不変 %s 実測=%r" % (os.path.basename(_p), _stat(_p)), _stat(_p) == _before)
check("監査の書き先は検査用へ逃がしてある", ps.TONE_AUDIT.startswith(TMPDIR))
shutil.rmtree(TMPDIR, ignore_errors=True)

print("\n== 結果 == PASS=%d FAIL=%d%s" % (PASS, FAIL, (" MUTANT=" + MUTANT) if MUTANT else ""))
sys.exit(1 if FAIL else 0)
