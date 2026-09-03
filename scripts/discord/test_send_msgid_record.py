# -*- coding: utf-8 -*-
"""OUT口が msg_id を台帳へ残すことの回帰ガード(2026-09-03・AD研究室モドリッチ経由の依頼)。

何を守るか:
  webhook直投稿口(persona_send)は wait=true を付けない限り Discord が **HTTP 204・本文なし**
  を返すため msg_id が取れず、send_audit に msg_id="" で残っていた(実測 406便中336便=82.8%)。
  bot_send は Bot API が投稿したメッセージのJSONを返しているのに r.read() を呼ばず捨てていた。
  この穴のせいで whatis.py が「この便は誰が何のために出したのか」を機械で辿れず、
  Chami が 16:57 に指した便が3台帳のどれにも無かった。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 偽物にするのは**外へ出る手**だけ= DiscordへのHTTPと、子プロセス起動と、ログの書き先。
    URLの組み立て・応答の解釈・成功判定の分岐は**本物を実行する**。
  - `.pyc` の偽PASSを避けるため、検査対象は毎回**ソースから読み直して exec** する。
  - 最後に must-fail= 実装を「動く別の実装」(=変更前の実装)へ戻し、この検査が**落ちる**ことを確かめる。

★C-064: 出口の挙動(204→200)を変えたので、stdoutを見て成否を決めている呼び出し元
  3本(broadcast / office_daily / winupdate_message)も同じ検査で実行して通す。

実行: python scripts/discord/test_send_msgid_record.py
"""
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PERSONA = os.path.join(HERE, "persona_send.py")
BOT = os.path.join(HERE, "bot_send.py")
BROADCAST = os.path.join(HERE, "broadcast.py")
WHATIS = os.path.join(HERE, "whatis.py")
OFFICE = os.path.join(ROOT, "scripts", "office", "office_daily.py")
WINUPD = os.path.join(ROOT, "scripts", "_daemons", "winupdate_message.py")

TMP = tempfile.mkdtemp(prefix="msgid_")
os.environ["GO5_LOCAL_DIR"] = os.path.join(TMP, "local")   # ★書き先だけ temp へ
os.makedirs(os.path.join(TMP, "local", "llm"), exist_ok=True)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FAIL = []
AUDIT = os.path.join(TMP, "local", "llm", "send_audit.jsonl")
MSGID = "1544877233817129003"       # モドリッチの便(=この依頼そのもの)を検体に使う

with open(os.path.join(TMP, "local", "discord_bot_token.txt"), "w", encoding="utf-8") as _f:
    _f.write("DUMMY_NOT_A_TOKEN\n")
with open(os.path.join(TMP, "local", "discord_channels.json"), "w", encoding="utf-8") as _f:
    json.dump([{"name": "イージス研究室", "dept": "aegis-gl", "id": "999000111"}], _f)


def ok(cond, name, detail=""):
    print(("  OK   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def rows():
    if not os.path.exists(AUDIT):
        return []
    return [json.loads(l) for l in open(AUDIT, encoding="utf-8") if l.strip()]


def clear():
    if os.path.exists(AUDIT):
        os.remove(AUDIT)


# ---------------------------------------------------------------- 偽のHTTP(外へ出る手だけ)
class _Resp:
    def __init__(self, status=200, payload=None, raw=None):
        self.status = status
        self._p = raw if raw is not None else json.dumps(payload or {}).encode("utf-8")

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(status=200, payload=None, raw=None):
    calls = []

    def _f(req, timeout=None):
        calls.append(req)
        return _Resp(status, payload, raw)
    _f.calls = calls
    return _f


def load_module(path, name, run=True, src_text=None):
    """ソースから読み直して exec する(.pycの偽PASSを避ける)。"""
    src = src_text if src_text is not None else open(path, encoding="utf-8").read()
    mod = type(sys)(name)
    mod.__file__ = path
    if run:
        exec(compile(src, path, "exec"), mod.__dict__)
    return mod


def extract_func(path, fname, src_text=None):
    """モジュール内(入れ子含む)の関数定義を**そのまま**取り出す。"""
    src = src_text if src_text is not None else open(path, encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == fname:
            return node
    return None


def post_ns(urlopen, persona="ケヴィン・デブライネ"):
    import send_audit
    import urllib.request as _u
    fake_mod = type(sys)("urllib_fake")
    fake_req = type(sys)("request_fake")
    fake_req.Request, fake_req.urlopen = _u.Request, urlopen
    fake_mod.request = fake_req
    return {"urllib": fake_mod, "json": json, "hook_url": "https://example.invalid/hook",
            "ch": {"id": "999000111", "name": "イージス研究室", "dept": "aegis-gl"},
            "persona": persona,
            "_audit_send": lambda **kw: send_audit.record("persona_send", **kw)}


def run_post(payload, urlopen, persona="ケヴィン・デブライネ", src_text=None):
    fn = extract_func(PERSONA, "post", src_text=src_text)
    if fn is None:
        return None
    ns = post_ns(urlopen, persona)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), PERSONA, "exec"), ns)
    return ns["post"](payload)


# ---------------------------------------------------------------- T1 persona_send(webhook口)
def t1(src_text=None, quiet=False):
    if not quiet:
        print("T1 persona_send= 普通の人格名義でも msg_id を残す")
    clear()
    f = fake_urlopen(status=200, payload={"id": MSGID})
    res = run_post({"content": "イージス研究室からの返信", "username": "ケヴィン・デブライネ"},
                   f, src_text=src_text)
    if res is None:
        ok(False, "persona_send に post() が在る")
        return
    st, mid = res
    url = f.calls[0].full_url if f.calls else ""
    r = rows()
    cond_url = url.endswith("?wait=true")
    cond_mid = (mid == MSGID) and bool(r) and r[0].get("msg_id") == MSGID
    if quiet:
        return cond_url and cond_mid
    ok(cond_url, "mirror名義でなくても wait=true を付ける(=Discordがidを返す条件)", url)
    ok(st == 200, "成功時のHTTPは200になる(204ではない)", str(st))
    ok(cond_mid, "台帳の msg_id に実IDが入る", json.dumps(r[0], ensure_ascii=False)[:120] if r else "0行")
    ok(bool(r) and r[0]["via"] == "persona_send" and r[0]["dept"] == "aegis-gl",
       "via/deptも従来どおり残る")

    # ミラー名義でも従来どおり(退行していない)
    clear()
    f = fake_urlopen(status=200, payload={"id": "1234567890123456789"})
    st, mid = run_post({"content": "ミラー便"}, f, persona="Chami(from Claude)")
    ok(mid == "1234567890123456789", "ミラー名義の取得は壊れていない", mid)

    # ★応答がJSONでない/idが無い時でも、送信を落とさない(記録のために言葉を失わない)
    clear()
    f = fake_urlopen(status=204, raw=b"")
    try:
        st, mid = run_post({"content": "本文なし応答"}, f)
        ok(st == 204 and mid == "", "idが読めなくても例外にしない(送信は成功のまま)", repr(mid))
        ok(len(rows()) == 1, "その場合も台帳には1行残る")
    except Exception as e:                                  # noqa: BLE001
        ok(False, "idが読めなくても例外にしない(送信は成功のまま)", type(e).__name__)


# ---------------------------------------------------------------- T2 bot_send(Bot API口)
def run_bot(mod, argv, urlopen):
    old_argv, old_open, old_stdout = sys.argv, mod.urllib.request.urlopen, sys.stdout
    buf = io.StringIO()
    sys.argv = ["bot_send.py"] + argv
    mod.urllib.request.urlopen = urlopen
    sys.stdout = buf
    code = 0
    try:
        mod.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    finally:
        sys.argv, mod.urllib.request.urlopen, sys.stdout = old_argv, old_open, old_stdout
    return code, buf.getvalue()


def t2(src_text=None, quiet=False):
    if not quiet:
        print("T2 bot_send= 返ってきたメッセージJSONから msg_id を拾う")
    mod = load_module(BOT, "bot_under_test", src_text=src_text)
    mod.LOCAL = os.path.join(TMP, "local")
    clear()
    f = fake_urlopen(status=200, payload={"id": MSGID, "content": "x"})
    code, out = run_bot(mod, ["--dept", "aegis-gl", "bot口からの便"], f)
    r = rows()
    cond = bool(r) and r[0].get("msg_id") == MSGID
    if quiet:
        return code == 0 and cond
    ok(code == 0 and len(f.calls) == 1, "送信そのものは従来どおり通る", "exit=%s" % code)
    ok(cond, "台帳の msg_id に実IDが入る", json.dumps(r[0], ensure_ascii=False)[:120] if r else "0行")
    ok(("msg=" + MSGID) in out, "stdoutにも msg= を出す(呼び出し元が拾えるように)", out.strip()[:90])

    # 応答が壊れていても送信は成功のまま(fail-open)
    clear()
    f = fake_urlopen(status=200, raw=b"<html>rate limited</html>")
    code, out = run_bot(mod, ["--dept", "aegis-gl", "壊れた応答"], f)
    ok(code == 0 and rows() and rows()[0]["msg_id"] == "",
       "JSONで無くても落ちない(msg_idは空のまま記録)", "exit=%s" % code)


# ---------------------------------------------------------------- T3 呼び出し元3本(C-064)
OK_OUT = "送信OK → イージス研究室 as オタコン (HTTP 200) msg=%s\n" % MSGID
NG_OUT = "送信失敗: HTTPError\n"


def fake_run(stdout, rc=0):
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, rc, stdout, "")
    return _run


def call_broadcast(stdout, rc=0, src_text=None):
    mod = load_module(BROADCAST, "broadcast_under_test", src_text=src_text)
    mod.subprocess.run = fake_run(stdout, rc)
    mod.time.sleep = lambda *a, **k: None
    mod.DEPTS = ["hq"]
    body = os.path.join(TMP, "body.txt")
    open(body, "w", encoding="utf-8").write("本文")
    old_argv, old_stdout = sys.argv, sys.stdout
    buf = io.StringIO()
    sys.argv, sys.stdout = ["broadcast.py", "--body-file", body], buf
    try:
        mod.main()
    except SystemExit:
        pass
    finally:
        sys.argv, sys.stdout = old_argv, old_stdout
    return buf.getvalue()


def call_office(stdout, rc=0, src_text=None):
    fn = extract_func(OFFICE, "send", src_text=src_text)
    if fn is None:
        return None
    ns = {"os": os, "sys": sys, "subprocess": type(sys)("sp"),
          "SCRATCH": os.path.join(TMP, "office", "_summary.txt"),
          "ROOT": ROOT, "SEND_DEPT": "report-notify", "SEND_PERSONA": "メタルギアMk.II",
          "print": lambda *a, **k: None}
    ns["subprocess"].run = fake_run(stdout, rc)
    ns["subprocess"].TimeoutExpired = subprocess.TimeoutExpired
    exec(compile(ast.Module(body=[fn], type_ignores=[]), OFFICE, "exec"), ns)
    return ns["send"]("日次サマリ本文")


def call_winupdate(stdout, rc=0, src_text=None):
    mod = load_module(WINUPD, "winupd_under_test", src_text=src_text)
    mod.ROOT = TMP
    mod.subprocess.run = fake_run(stdout, rc)
    titles = os.path.join(TMP, "titles.txt")
    open(titles, "w", encoding="utf-8").write("2026-09 累積更新プログラム\n")
    old_argv, old_stdout = sys.argv, sys.stdout
    sys.argv, sys.stdout = ["winupdate_message.py", "1", titles], io.StringIO()
    try:
        return mod.main()
    finally:
        sys.argv, sys.stdout = old_argv, old_stdout


def t3(src_office=None, src_bc=None, src_wu=None, quiet=False):
    if not quiet:
        print("T3 呼び出し元= 200になっても『送った』と判定できる(C-064)")
    bc = call_broadcast(OK_OUT, src_text=src_bc)
    of = call_office(OK_OUT, src_text=src_office)
    wu = call_winupdate(OK_OUT, src_text=src_wu)
    conds = [("[OK] hq" in bc and "[NG]" not in bc), of is True, wu == 0]
    if quiet:
        return all(conds)
    ok(conds[0], "broadcast= HTTP 200 を成功として数える", bc.strip().splitlines()[-1][:70] if bc else "")
    ok(conds[1], "office_daily= HTTP 200 を成功として数える", str(of))
    ok(conds[2], "winupdate_message= HTTP 200 で終了コード0", str(wu))

    # 失敗は失敗のまま(緩めていない)
    bc = call_broadcast(NG_OUT, rc=3, src_text=src_bc)
    of = call_office(NG_OUT, rc=3, src_text=src_office)
    wu = call_winupdate(NG_OUT, rc=3, src_text=src_wu)
    ok("[NG]" in bc, "broadcast= 送信失敗は失敗のまま")
    ok(of is False, "office_daily= 送信失敗は失敗のまま", str(of))
    ok(wu == 1, "winupdate_message= 送信失敗は終了コード1", str(wu))


# ---------------------------------------------------------------- T4 記録→照会の一本通し
def t4():
    print("T4 記録した msg_id を whatis.py が解決できる(これが依頼の目的)")
    clear()
    f = fake_urlopen(status=200, payload={"id": MSGID})
    run_post({"content": "[ケヴィン・デブライネ] 承知した。基盤側で入れる。"}, f)
    w = load_module(WHATIS, "whatis_under_test", run=False)
    src = open(WHATIS, encoding="utf-8").read().replace(
        'sys.stdout.reconfigure(encoding="utf-8")', "pass")   # ★外へ出る手だけ無効化
    exec(compile(src, WHATIS, "exec"), w.__dict__)
    w.ROOT = TMP                                             # ★台帳の読み先だけ temp へ
    hits = w.scan(MSGID)
    ok(bool(hits), "台帳に当たる(=『これ何?』に機械で答えられる)", "%d件" % len(hits))
    if hits:
        label, d = hits[0]
        ok(label == "send_audit" and d.get("dept") == "aegis-gl"
           and d.get("persona") == "ケヴィン・デブライネ",
           "部門と人格まで引ける", "%s/%s/%s" % (label, d.get("dept"), d.get("persona")))
    ok(not w.scan("1111111111111111111"), "無関係なIDには当たらない(誤ヒットしない)")


# ---------------------------------------------------------------- must-fail
def must_fail():
    print("MUST-FAIL 変更前の実装(=動く別の実装)へ戻して、この検査が落ちるか")
    # M1= persona_send の url を「mirror/--print-id の時だけ wait=true」へ戻す
    psrc = open(PERSONA, encoding="utf-8").read()
    a1 = '        url = hook_url + "?wait=true"'
    if a1 not in psrc:
        ok(False, "M1 変異点が見つからない(検査自体が古い)")
    else:
        mut = psrc.replace(a1, '        url = hook_url + ("?wait=true" if False else "")')
        ok(t1(src_text=mut, quiet=True) is False,
           "M1 wait=true を条件付きに戻すと T1(msg_idが残る)が満たせない")

    # M2= bot_send から応答本文の読み取りだけ落とす(送信は成功する=動く実装)
    bsrc = open(BOT, encoding="utf-8").read()
    a2 = '                mid = str((json.loads(r.read().decode("utf-8")) or {}).get("id", "") or "")'
    if a2 not in bsrc:
        ok(False, "M2 変異点が見つからない(検査自体が古い)")
    else:
        ok(t2(src_text=bsrc.replace(a2, '                mid = ""'), quiet=True) is False,
           "M2 応答を読まない実装へ戻すと T2(msg_idが残る)が満たせない")

    # M3= 呼び出し元3本を「204でなければ失敗」へ戻す(旧実装。200では全便が失敗扱いになる)
    old_bc = open(BROADCAST, encoding="utf-8").read().replace(
        'if r.returncode == 0 and "送信OK" in tail:', 'if r.returncode == 0 and "204" in tail:')
    old_of = open(OFFICE, encoding="utf-8").read().replace(
        'okd = r.returncode == 0 and "送信OK" in out', 'okd = r.returncode == 0 and "204" in out')
    old_wu = open(WINUPD, encoding="utf-8").read().replace(
        'return 0 if ("送信OK" in out and r.returncode == 0) else 1',
        'return 0 if "HTTP 204" in out else 1')
    ok(t3(src_office=old_of, src_bc=old_bc, src_wu=old_wu, quiet=True) is False,
       "M3 旧判定(204固定)へ戻すと T3(200を成功と数える)が満たせない")


if __name__ == "__main__":
    try:
        t1()
        t2()
        t3()
        t4()
        must_fail()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f_ in FAIL:
        print("  - " + f_)
    sys.exit(1 if FAIL else 0)
