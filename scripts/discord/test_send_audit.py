# -*- coding: utf-8 -*-
"""OUT口の共通送信ログ(send_audit)と bot_send の書式統一の回帰ガード。

規律(docs/departments/00_common/skills/test-must-fail/SKILL.md):
  - 偽物にするのは**外へ出る手**だけ= DiscordへのHTTPと、ログの書き先(GO5_LOCAL_DIR)。
    本文の組み立て・フラグ判定・分岐・ログの中身は**本物を実行する**。
  - `.pyc` の偽PASSを避けるため、検査対象は毎回**ソースから読み直して exec** する。
  - 最後に must-fail= 実装を「動く別の実装」へ変異させ、この検査が**落ちる**ことを確かめる。

実行: python scripts/discord/test_send_audit.py
"""
import ast
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.join(HERE, "bot_send.py")
PERSONA = os.path.join(HERE, "persona_send.py")

TMP = tempfile.mkdtemp(prefix="sendaudit_")
os.environ["GO5_LOCAL_DIR"] = os.path.join(TMP, "local")   # ★書き先だけ temp へ
os.makedirs(os.path.join(TMP, "local", "llm"), exist_ok=True)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FAIL = []
AUDIT = os.path.join(TMP, "local", "llm", "send_audit.jsonl")

# ★偽のトークンとチャンネル表(本番のtempへは触らない・本物の解決処理をそのまま通すため)
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
    def __init__(self, status=204, payload=None):
        self.status = status
        self._p = json.dumps(payload or {}).encode("utf-8")

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(status=204, payload=None, boom=None):
    calls = []

    def _f(req, timeout=None):
        calls.append(req)
        if boom:
            raise boom
        return _Resp(status, payload)
    _f.calls = calls
    return _f


def load_bot(path=BOT, name="bot_under_test"):
    """bot_send をソースから読んで exec し、外へ出る手だけ差し替える。"""
    src = open(path, encoding="utf-8").read()
    mod = type(sys)(name)
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    mod.LOCAL = os.path.join(TMP, "local")          # トークン/チャンネル表も temp から
    return mod


def run_bot(mod, argv, urlopen):
    """本物の main() を回す。戻り値= (exit_code, 標準出力)"""
    old_argv, old_open = sys.argv, mod.urllib.request.urlopen
    old_stdout = sys.stdout
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
        sys.argv, mod.urllib.request.urlopen = old_argv, old_open
        sys.stdout = old_stdout
    return code, buf.getvalue()


# ---------------------------------------------------------------- T1 send_audit 単体
def t1():
    print("T1 送信ログの正本(send_audit)")
    import send_audit
    clear()
    send_audit.record("bot_send", body="あ\nい", status="204", channel="総合-受付",
                      dept="hq", persona="アメス", msg_id="123")
    r = rows()
    ok(len(r) == 1, "1行だけ書く", str(len(r)))
    if not r:
        return
    need = {"ts", "event", "via", "channel_id", "channel", "dept", "persona", "status",
            "chars", "head", "msg_id", "pid", "ppid", "origin", "argv"}
    ok(need <= set(r[0]), "必要な列が揃っている", str(sorted(need - set(r[0]))))
    ok(r[0]["head"] == "あ⏎い" and r[0]["chars"] == 3, "本文の頭と字数(改行は⏎)", r[0]["head"])
    ok(r[0]["via"] == "bot_send" and r[0]["event"] == "send", "既定は event=send")
    # fail-open= 書けない場所を指しても例外を投げない(送信を殺さない)
    try:
        send_audit.record("bot_send", body="x", path=os.path.join(TMP, "nul\0dir", "a.jsonl"))
        ok(True, "fail-open= 書けなくても例外を出さない")
    except Exception as e:
        ok(False, "fail-open= 書けなくても例外を出さない", type(e).__name__)
    # 呼び出し元の名乗り(任意)が乗る
    clear()
    os.environ["GO5_SEND_ORIGIN"] = "dept_daemon:aegis-gl"
    send_audit.record("persona_send", body="y")
    ok(rows()[0]["origin"] == "dept_daemon:aegis-gl", "GO5_SEND_ORIGIN が乗る")
    del os.environ["GO5_SEND_ORIGIN"]


# ---------------------------------------------------------------- T2 bot_send(実行)
def t2(mod):
    print("T2 bot_send= 本文の組み立てとログ(main を実行)")
    # 事故と同じ引数。★昔はこれで "--body-file /proc/self/fd/0" が本文としてPOSTされた。
    clear()
    f = fake_urlopen()
    src = os.path.join(TMP, "honbun.txt")
    open(src, "w", encoding="utf-8").write("ファイルから来た本文だ\n")
    code, out = run_bot(mod, ["--dept", "aegis-gl", "--body-file", src], f)
    ok(code == 0 and len(f.calls) == 1, "--body-file を解釈して送る", "exit=%s" % code)
    posted = json.loads(f.calls[0].data.decode("utf-8"))["content"] if f.calls else ""
    ok(posted == "ファイルから来た本文だ", "本文はファイルの中身(フラグ文字列ではない)", posted)
    r = rows()
    ok(len(r) == 1 and r[0]["status"] == "204" and r[0]["dept"] == "aegis-gl",
       "送信ログが1行残る(status/dept込み)", json.dumps(r[0], ensure_ascii=False)[:110] if r else "0行")

    # 存在しないファイルを指したら、黙って本文にせず落とす
    clear()
    f = fake_urlopen()
    code, out = run_bot(mod, ["--dept", "aegis-gl", "--body-file", os.path.join(TMP, "no_such")], f)
    ok(code == 1 and not f.calls, "読めない本文ファイルは送信に到達しない", "exit=%s" % code)

    # 未対応フラグは今も止める(止血は生きている)+ 止めたことも記録する
    clear()
    f = fake_urlopen()
    code, out = run_bot(mod, ["--dept", "aegis-gl", "--persona", "アメス"], f)
    ok(code == 4 and not f.calls, "未対応フラグは exit 4 で送信に到達しない", "exit=%s" % code)
    r = rows()
    ok(len(r) == 1 and r[0]["event"] == "blocked" and "--persona" in r[0]["status"],
       "止めた便も台帳に残る(event=blocked)", json.dumps(r[0], ensure_ascii=False)[:110] if r else "0行")

    # 標準入力から「--body-file …」が流れてきた= 渡し方を間違えた便(事故と同じ形)。止める。
    clear()
    f = fake_urlopen()
    old = sys.stdin
    sys.stdin = io.StringIO("--body-file /proc/self/fd/0")
    try:
        code, out = run_bot(mod, ["--dept", "aegis-gl"], f)
    finally:
        sys.stdin = old
    r = rows()
    ok(code == 4 and not f.calls and r and r[0]["event"] == "blocked",
       "標準入力から来たフラグ文字列も止める", "exit=%s" % code)

    # 誤発火しない= 普通の本文
    for text in ["通常の本文 -- ダッシュを含む", "--- 見出し", "本文"]:
        clear()
        f = fake_urlopen()
        code, out = run_bot(mod, ["--dept", "aegis-gl", text], f)
        ok(code == 0 and len(f.calls) == 1, "誤発火しない: %s" % text[:16], "exit=%s" % code)

    # 標準入力の経路も生きている
    clear()
    f = fake_urlopen()
    old = sys.stdin
    sys.stdin = io.StringIO("パイプから来た本文")
    try:
        code, out = run_bot(mod, ["--dept", "aegis-gl"], f)
    finally:
        sys.stdin = old
    posted = json.loads(f.calls[0].data.decode("utf-8"))["content"] if f.calls else ""
    ok(code == 0 and posted == "パイプから来た本文", "標準入力の経路は壊れていない", posted)

    # 送信失敗も残す
    clear()
    f = fake_urlopen(boom=RuntimeError("boom"))
    code, out = run_bot(mod, ["--dept", "aegis-gl", "失敗する便"], f)
    r = rows()
    ok(code == 3 and r and r[0]["status"] == "ERR:RuntimeError",
       "送信失敗も status=ERR:… で残る", (r[0]["status"] if r else "0行"))


# ---------------------------------------------------------------- T3 persona_send(実行)
def extract_post(src_path=PERSONA, src_text=None):
    """persona_send.main() の中の入れ子関数 post を**そのまま**取り出す。"""
    src = src_text if src_text is not None else open(src_path, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "post":
            return node
    return None


def t3():
    print("T3 persona_send= webhook口の post() を実行")
    fn = extract_post()
    ok(fn is not None, "persona_send に post() が在る")
    if fn is None:
        return
    import send_audit
    import urllib.request as _u

    def make_ns(urlopen):
        fake_mod = type(sys)("urllib_fake")
        fake_req = type(sys)("request_fake")
        fake_req.Request = _u.Request
        fake_req.urlopen = urlopen
        fake_mod.request = fake_req
        return {"urllib": fake_mod, "json": json, "hook_url": "https://example.invalid/hook",
                "ch": {"id": "999", "name": "イージス研究室", "dept": "aegis-gl"},
                "persona": "ケヴィン・デブライネ",
                "_audit_send": lambda **kw: send_audit.record("persona_send", **kw)}

    # 成功(msg_idつき)
    clear()
    f = fake_urlopen(status=200, payload={"id": "1544669455995637771"})
    ns = make_ns(f)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), PERSONA, "exec"), ns)
    # ★2026-09-03 post() から want_id 引数が消えた(全便で wait=true=msg_idを必ず拾う)。
    #   その回帰ガードは test_send_msgid_record.py 側。ここは台帳の列だけを見る。
    st, mid = ns["post"]({"content": "webhookから出た本文", "username": "ケヴィン・デブライネ"})
    r = rows()
    ok(st == 200 and mid == "1544669455995637771", "post は (status, msg_id) を返す", str((st, mid)))
    ok(len(r) == 1 and r[0]["via"] == "persona_send" and r[0]["msg_id"] == mid
       and r[0]["persona"] == "ケヴィン・デブライネ" and r[0]["head"] == "webhookから出た本文",
       "webhook側も同じ台帳へ1行", json.dumps(r[0], ensure_ascii=False)[:120] if r else "0行")

    # embed(素の色モード)でも本文を拾う
    clear()
    f = fake_urlopen()
    ns = make_ns(f)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), PERSONA, "exec"), ns)
    ns["post"]({"embeds": [{"description": "色つきの本文"}]})
    r = rows()
    ok(r and r[0]["head"] == "色つきの本文", "embed経路の本文も記録する", (r[0]["head"] if r else "0行"))

    # 失敗= 記録した上で例外はそのまま上へ返す(呼び出し元の再試行を変えない)
    clear()
    f = fake_urlopen(boom=RuntimeError("boom"))
    ns = make_ns(f)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), PERSONA, "exec"), ns)
    raised = False
    try:
        ns["post"]({"content": "落ちる便"})
    except RuntimeError:
        raised = True
    r = rows()
    ok(raised, "例外は握り潰さず上へ投げ直す")
    ok(r and r[0]["status"] == "ERR:RuntimeError", "失敗も台帳に残る",
       (r[0]["status"] if r else "0行"))


# ---------------------------------------------------------------- must-fail
def must_fail():
    print("MUST-FAIL 実装を『動く別の実装』へ変異させて、この検査が落ちるか")
    # M1= bot_send の本文組み立てを**事故当時の実装**へ戻す(残り引数の連結)。動くが事故を再現する。
    src = open(BOT, encoding="utf-8").read()
    anchor = "    explicit = bool(rest) and rest[0] in (\"--body-file\", \"--body\")"
    if anchor not in src:
        ok(False, "M1 変異点が見つからない(検査自体が古い)")
    else:
        head, tail = src.split(anchor, 1)
        rest_of = tail.split("\n    if not body:", 1)[1]
        mut_src = head + "    explicit = True\n" \
                         "    body = \" \".join(rest) if rest else sys.stdin.read().strip()\n" \
                         "    if not body:" + rest_of
        mut = os.path.join(HERE, "_mutant_bot_send.py")      # 実物と同じ場所(相対importのため)
        open(mut, "w", encoding="utf-8").write(mut_src)
        try:
            m = load_bot(mut, "bot_mutant")
            clear()
            f = fake_urlopen()
            src_f = os.path.join(TMP, "honbun.txt")
            code, out = run_bot(m, ["--dept", "aegis-gl", "--body-file", src_f], f)
            posted = json.loads(f.calls[0].data.decode("utf-8"))["content"] if f.calls else ""
            ok(posted != "ファイルから来た本文だ",
               "M1 旧実装へ戻すと T2 の期待(本文=ファイルの中身)が満たせない", posted[:60])
        finally:
            os.remove(mut)
            for p in (mut + "c",):
                if os.path.exists(p):
                    os.remove(p)

    # M2= persona_send の post から**失敗時の記録だけ**落とす(成功だけ記録する実装。動く)。
    psrc = open(PERSONA, encoding="utf-8").read()
    a2 = "            _audit_send(body=_sent, status=\"ERR:\" + type(e).__name__,"
    if a2 not in psrc:
        ok(False, "M2 変異点が見つからない(検査自体が古い)")
        return
    i = psrc.index(a2)
    j = psrc.index("            raise ", i)
    mut2 = psrc[:i] + psrc[j:]
    fn = extract_post(src_text=mut2)
    if fn is None:
        ok(False, "M2 変異後の post を取り出せない")
        return
    import send_audit
    import urllib.request as _u
    clear()
    f = fake_urlopen(boom=RuntimeError("boom"))
    fake_mod = type(sys)("urllib_fake")
    fake_req = type(sys)("request_fake")
    fake_req.Request, fake_req.urlopen = _u.Request, f
    fake_mod.request = fake_req
    ns = {"urllib": fake_mod, "json": json, "hook_url": "https://example.invalid/hook",
          "ch": {"id": "999", "name": "イージス研究室", "dept": "aegis-gl"},
          "persona": "ケヴィン・デブライネ",
          "_audit_send": lambda **kw: send_audit.record("persona_send", **kw)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), PERSONA, "exec"), ns)
    try:
        ns["post"]({"content": "落ちる便"})
    except RuntimeError:
        pass
    ok(not rows(), "M2 失敗時の記録を落とすと T3 の期待(失敗も残る)が満たせない",
       "%d行" % len(rows()))


if __name__ == "__main__":
    try:
        t1()
        t2(load_bot())
        t3()
        must_fail()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("\n結果: %s (失敗 %d件)" % ("PASS" if not FAIL else "FAIL", len(FAIL)))
    for f_ in FAIL:
        print("  - " + f_)
    sys.exit(1 if FAIL else 0)
