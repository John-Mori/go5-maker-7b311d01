# -*- coding: utf-8 -*-
"""投函経路(dispatch)の口調ゲートDと、口調監査の突合キー audit_id の回帰ガード。

起票= AD研究室(モドリッチ) msg 1549614905580068977(2026-09-16)。
  ③「ピン済なのに今日10:22の実便で漏れた。msg_id `DISPATCH-research-room-1789521766461` で
     監査を引くとヒット0行だ。**直せなかったのではない。呼ばれていない。**」
  ④「tone_fix 173行のうち24行に msg_id が無い= 監査の13.9%が照合できない。
     **記録が在ることと、検証できることは別だ。**」

★この検査が押さえている**本当の落とし穴**は T2 だ=
  合流点にゲートを足しても、`already_gated=True` の枝の中へ置けば実運用(CLI)では
  **一度も鳴らない**。main() は全部門を already_gated=True で回すからだ。
  「配線した」と「呼ばれている」は別物で、③はまさにその差で起きた。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 偽物にするのは**外へ出る手**だけ(キューDB)。判定・分岐は本物をそのまま実行する。
  - 検査対象は毎回ソースから読み直して exec(.pyc の偽PASSを踏まない)。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が落ちるか確かめる。

実行: python scripts/llm/test_dispatch_tone_gate.py
"""
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DISPATCH = os.path.join(HERE, "dispatch.py")
PERSONA_SEND_PY = os.path.join(ROOT, "scripts", "discord", "persona_send.py")

FAIL = []

# ★オタコンの「俺→僕」= 3層(otacon.md / 口調ルール.json / tone_gate.py)とも揃っていて、
#   それでも 9/16 10:22 の実便で素通しになった組み合わせ。実物と同じ型を使う。
BODY = ("[オタコン]\n"
        "俺が見た限り、封筒の出口は3つある。\n"
        "俺の見立てでは、ここが合流点だ。\n")


def ok(cond, name, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def load(path, name):
    """★ソースから読んで exec= .pyc の偽PASSを踏まない。"""
    src = open(path, encoding="utf-8").read()
    mod = type(sys)(name)
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


# ---------------------------------------------------------------- 投函の実走
RUNNER = r'''
import io,sys,os,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding="utf-8",errors="replace")
sys.path.insert(0, r"{here}")
src=open(r"{disp}",encoding="utf-8").read()
m=type(sys)("dispatch_under_test"); m.__file__=r"{disp}"
exec(compile(src,r"{disp}","exec"), m.__dict__)
m.HERE=r"{here}"                       # 変異コピーからでも兄弟モジュールを見つける
m.QUEUE_DB=r"{qdb}"                    # ★外へ出る手= キューを temp へ
ok,mid=m.dispatch("aegis-gl","オタコン(AD研究室)",{body!r},False,{dry},
                  "",'ai',"research-room",already_gated=True)
print(json.dumps({{"ok":ok,"mid":mid}},ensure_ascii=False))
'''


def run_dispatch(tmp, tag, dispatch_path=None, dry=False):
    """本物の dispatch() を already_gated=True(=実運用と同じ形)で実行する。"""
    disp = dispatch_path or DISPATCH
    local = os.path.join(tmp, tag, "local")
    os.makedirs(os.path.join(local, "llm"), exist_ok=True)
    os.makedirs(os.path.join(local, "queue"), exist_ok=True)
    qdb = os.path.join(local, "queue", "inbox.db")
    code = RUNNER.format(here=HERE, disp=disp, qdb=qdb, body=BODY, dry=bool(dry))
    env = dict(os.environ, GO5_LOCAL_DIR=local)
    p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    rows = []
    if os.path.exists(qdb):
        try:
            con = sqlite3.connect(qdb)
            rows = [r[0] for r in con.execute("select body from queue order by id").fetchall()]
            con.close()
        except Exception as e:                           # noqa: BLE001
            rows = ["<<db read error: %s>>" % e]
    audit = os.path.join(local, "llm", "tone_audit.jsonl")
    arows = ([json.loads(l) for l in open(audit, encoding="utf-8")]
             if os.path.exists(audit) else [])
    return p, rows, arows


# ---------------------------------------------------------------- T1/T2 本体
def t1(tmp):
    print("T1 投函経路がゲートDを**呼んでいる**(③= 呼ばれていなかった件)")
    p, rows, arows = run_dispatch(tmp, "real")
    ok(bool(rows), "キューへ投函できた(本物の enqueue を実行)",
       (p.stdout or "")[-160:] + (p.stderr or "")[-160:])
    hit = [r for r in arows if r.get("source") == "dispatch"]
    ok(bool(hit), "★口調監査へ source=dispatch の行が残る(0行なら『呼ばれていない』)",
       "%d行" % len(arows))
    ok(any(str(r.get("msg_id", "")).startswith("DISPATCH-aegis-gl-") for r in hit),
       "★行が msg_id=DISPATCH-… を持つ(④= 後から実便へ突き合わせられる)",
       str(hit[0].get("msg_id")) if hit else "")
    ok(all(r.get("body_sha1") for r in hit),
       "同報を畳むための body_sha1 が載っている",
       str(hit[0].get("body_sha1")) if hit else "")
    ok(any(r.get("event") == "tone_fix_skipped" and r.get("marker") == "俺" for r in hit),
       "『俺』を拾って event=tone_fix_skipped で残す(直さず数える)")
    if rows:
        content = json.loads(rows[-1]).get("content", "")
        ok("俺が見た限り" in content,
           "★本文は**書き換えていない**= 封筒の引用を壊さない(警告のみ・§4.55)",
           content.split("\n")[1][:24] if "\n" in content else content[:24])


def t2(tmp):
    """★③が起きた形そのもの= 配線は在るのに実運用の枝では鳴らない、を禁じる。"""
    print("T2 already_gated=True(=main() が実際に渡す形)でも鳴る")
    src = open(DISPATCH, encoding="utf-8").read()
    body = src.split("def dispatch(", 1)[-1]
    # dispatch() の中で、ゲートDの呼び出しが `if not already_gated:` ブロックの**外**に在るか。
    # 行頭インデントで見る= ブロックの中なら8空白、外なら4空白。
    lines = [ln for ln in body.splitlines() if "tone_gate_pass(" in ln and "def " not in ln]
    ok(bool(lines), "dispatch() 内にゲートDの呼び出しが在る")
    ok(all(len(ln) - len(ln.lstrip()) == 4 for ln in lines),
       "★呼び出しが `if not already_gated:` の外(インデント4)に在る",
       repr([len(ln) - len(ln.lstrip()) for ln in lines]))
    _p, _rows, arows = run_dispatch(tmp, "gated")
    ok(len([r for r in arows if r.get("source") == "dispatch"]) > 0,
       "★実走でも already_gated=True で行が残る(旧配線ならここが0行)",
       "%d行" % len(arows))


def t3(tmp):
    print("T3 dry-run= 数えるが台帳へは書かない(出ていない便で分布を汚さない)")
    p, rows, arows = run_dispatch(tmp, "dry", dry=True)
    ok(not rows, "dry-run では投函しない")
    ok(len(arows) == 0, "dry-run では台帳へ1行も書かない", "実測%d行" % len(arows))
    ok("口調ゲートD" in (p.stdout or ""), "それでも件数は画面に出る(確認できる)",
       (p.stdout or "").strip().splitlines()[-2:][0][:60] if p.stdout else "")


def t4():
    print("T4 fail-open= ゲートが転んでも便は止めない")
    mod = load(DISPATCH, "dispatch_tone_failopen")
    mod.HERE = HERE
    boom = type(sys)("output_gates")

    def _raise(*a, **k):
        raise RuntimeError("boom")
    boom.apply_tone_gate_only = _raise
    sys.modules["output_gates"] = boom
    try:
        fix, warn = mod.tone_gate_pass("オタコン(AD研究室)", "research-room", BODY)
    finally:
        sys.modules.pop("output_gates", None)
    ok((fix, warn) == (0, 0), "例外でも (0,0) を返して先へ進む")


# ------------------------------------------------- T5 突合キー audit_id(④)
def t5(tmp):
    print("T5 audit_id= ゲート時に鍵を発行し、投稿後に実msg_idへ繋ぐ(④)")
    d = os.path.join(ROOT, "scripts", "discord")
    if d not in sys.path:
        sys.path.insert(0, d)
    ps = load(PERSONA_SEND_PY, "persona_send_under_test")
    ps.TONE_AUDIT = os.path.join(tmp, "t5_tone_audit.jsonl")     # 本番の台帳を汚さない
    out = ps.apply_text_gates(BODY, persona="オタコン", dept="research-room")
    rows = [json.loads(l) for l in open(ps.TONE_AUDIT, encoding="utf-8")]
    ok(bool(rows), "ゲート通過で監査行が出る", "%d行" % len(rows))
    aid = ps._AUDIT_ID
    ok(bool(aid), "audit_id が発行されている", str(aid))
    ok(all(r.get("audit_id") == aid for r in rows),
       "★3つの監査(口調/書き直し/構造)が**同じ**audit_id を載せる",
       str(sorted({r.get("event") for r in rows})))
    ok(any(r.get("event") == "tone_structure" for r in rows), "構造監査の行も出ている")
    ok("俺" not in out or True, "(本文の扱いはゲートDの既存仕様のまま= ここでは問わない)")
    # 投稿成功の後に来る行
    ps._audit_link("1549999999999999999", channel="test", persona="オタコン",
                   dept="research-room")
    rows = [json.loads(l) for l in open(ps.TONE_AUDIT, encoding="utf-8")]
    link = [r for r in rows if r.get("event") == "audit_link"]
    ok(len(link) == 1 and link[0].get("audit_id") == aid,
       "★audit_link 1行で audit_id ↔ 実msg_id が繋がる",
       str(link[0].get("msg_id")) if link else "")
    # ★投稿できなかった便を繋がない= msg_id が空なら書かない
    n_before = len(rows)
    ps._audit_link("", channel="test")
    n_after = len(open(ps.TONE_AUDIT, encoding="utf-8").read().splitlines())
    ok(n_after == n_before, "msg_idが空なら繋がない(出ていない便に鍵を打たない)")
    # ★突合の再現(audit=False)では鍵を作り直さない= 直前の実便の鍵を踏み潰さない
    ps.apply_text_gates(BODY, persona="オタコン", dept="research-room", audit=False)
    ok(ps._AUDIT_ID == aid, "audit=False は audit_id を発行しない(再現で鍵がズレない)")
    return ps.TONE_AUDIT, aid


# ------------------------------------------------- T6 一覧オプション(⑤)
def t6(tmp):
    print("T6 --leaks= 軸③(他人格の一人称)の便を人格名付きで一覧する(⑤)")
    rep = load(os.path.join(HERE, "tone_structure_report.py"), "report_under_test")
    audit = os.path.join(tmp, "t6_tone_audit.jsonl")
    rows = [
        {"ts": "2026-09-16T10:22:00", "event": "tone_structure", "persona": "オタコン",
         "audit_id": "PS-1-0001", "other_first_person": {"あたし": 2},
         "other_first_person_total": 2, "other_names_total": 0},
        {"ts": "2026-09-16T10:23:00", "event": "tone_structure", "persona": "花海咲季",
         "msg_id": "1549490190299697224", "other_first_person": {},
         "other_first_person_total": 0, "other_names_total": 3},
        {"ts": "2026-09-16T10:24:00", "event": "audit_link",
         "audit_id": "PS-1-0001", "msg_id": "1549888888888888888"},
    ]
    with open(audit, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rep.TONE_AUDIT = audit
    links = rep._audit_links()
    ok(links.get("PS-1-0001") == ["1549888888888888888"], "audit_link を辞書に引ける")
    buf = io.StringIO()
    old, sys.stdout = sys.stdout, buf
    try:
        rep._leaks("test", [r for r in rows if r.get("event") == "tone_structure"], links)
    finally:
        sys.stdout = old
    out = buf.getvalue()
    ok("オタコン" in out, "★人格名が出る(機械が切り、人事部門が読む)")
    ok("あたし×2" in out, "混入した一人称と件数が出る")
    ok("1549888888888888888" in out,
       "★msg_id を持たない行も audit_id 経由で実便へ繋がって出る(④と⑤が噛み合う)")
    ok("花海咲季" not in out.split("(参考")[0],
       "混入0の便は一覧に出さない(名前の言及だけで赤くしない)")
    ok("1/2" in out, "母数つきで件数が出る", out.splitlines()[1][:50])


# ---------------------------------------------------------------- must-fail
def must_fail(tmp):
    """★変異体は **scripts/llm の中**へ置く= ROOT/台帳/ルールを __file__ から組むため。"""
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    src = open(DISPATCH, encoding="utf-8").read()
    # 変異①= ゲートDの呼び出しを `if not already_gated:` の中へ戻す(=③が起きた配線・動きはする)
    call = "    _tfix, _twarn = tone_gate_pass(sender, from_dept, body, msg_id=synthetic,\n" \
           "                                   write=not dry_run)"
    anchor = "    if not already_gated:\n"
    if call not in src or anchor not in src:
        ok(False, "変異①の変異点が見つからない(検査が古い)")
        return
    mut = os.path.join(HERE, "_mutant_dispatch_tone_tmp.py")
    try:
        m1 = src.replace(call, "", 1).replace(
            anchor,
            anchor + "        _tfix, _twarn = tone_gate_pass(sender, from_dept, body,"
                     " msg_id=synthetic, write=not dry_run)\n", 1)
        open(mut, "w", encoding="utf-8").write(m1)
        _p, _rows, arows = run_dispatch(tmp, "mut1", mut)
        ok(len([r for r in arows if r.get("source") == "dispatch"]) == 0,
           "変異①(already_gated の中へ戻す)= T1/T2 が落ちる(0行になる)",
           "台帳%d行" % len(arows))
        # 変異②= msg_id を渡さない(=④の「記録は在るが照合できない」状態)
        m2 = src.replace("msg_id=synthetic,\n                                   write=not dry_run",
                         'msg_id="",\n                                   write=not dry_run', 1)
        ok(m2 != src, "変異②の変異点が在る")
        open(mut, "w", encoding="utf-8").write(m2)
        _p, _rows, arows2 = run_dispatch(tmp, "mut2", mut)
        hit2 = [r for r in arows2 if r.get("source") == "dispatch"]
        ok(bool(hit2) and not any(str(r.get("msg_id", "")) for r in hit2),
           "変異②(msg_idを空に)= 行は残るが T1 の突合が落ちる",
           "%d行すべて msg_id 空" % len(hit2))
    finally:
        try:
            os.remove(mut)
        except OSError:
            pass
    # 変異③= persona_send が audit_id を載せない(=2026-09-16 以前の実装)
    pssrc = open(PERSONA_SEND_PY, encoding="utf-8").read()
    a3 = '                    "audit_id": _AUDIT_ID,        # ★投稿後の audit_link 行と繋ぐ鍵'
    if a3 not in pssrc:
        ok(False, "変異③の変異点が見つからない(検査が古い)")
        return
    mut3 = os.path.join(os.path.dirname(PERSONA_SEND_PY), "_mutant_persona_send_tmp.py")
    try:
        open(mut3, "w", encoding="utf-8").write(pssrc.replace(a3, "", 1))
        ps3 = load(mut3, "persona_send_mutant")
        ps3.TONE_AUDIT = os.path.join(tmp, "mut3_tone_audit.jsonl")
        ps3.apply_text_gates(BODY, persona="オタコン", dept="research-room")
        rows3 = [json.loads(l) for l in open(ps3.TONE_AUDIT, encoding="utf-8")]
        ok(any(r.get("event") == "tone_fix" and not r.get("audit_id") for r in rows3),
           "変異③(audit_idを載せない)= T5 が落ちる(鍵の無い行に戻る)",
           "%d行" % len(rows3))
    finally:
        try:
            os.remove(mut3)
        except OSError:
            pass


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="tonegate_")
    try:
        t1(tmp)
        t2(tmp)
        t3(tmp)
        t4()
        t5(tmp)
        t6(tmp)
        must_fail(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f in FAIL:
        print("  - " + f)
    sys.exit(1 if FAIL else 0)
