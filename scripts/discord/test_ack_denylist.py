#!/usr/bin/env python3
"""定型ack denylist を**Discordへ本文を出す全ての口**で担保する検査(2026-09-10 イージス研究室)。

なぜ要るか(実物):
  2026-09-10 02:56 🚬無線通信-オタコン に
    「受け取った。処理を開始する。完了結果は保存してから返す。」
  が出た。Chami=「このやり取りいらない」→ その後もう一度「効いてません」(再発)。
  真因の1つ(codex_responder.notify_room の定型テキスト)は 09-10 09:36 に撤去済。
  だが**撤去は1箇所の守り**で、次の実装が同じ文を書けば戻る(送信印で前に一度やられている)。
  発注= 改善提案部門トトリの上申「合流点に"定型ack denylist"を置いて、既知の定型句を
  空便扱いで落とす形を提案。実装は基盤の持ち場だから、そこへ渡すね。」

  ★今の空便ガードは「空・タグだけ・英字1語」しか落とさない。この一次ackは日本語20字超の
    "意味は空だけど文としては非空"だから素通りする= 機械に落ちていなかった規律
    (共通規律§2「内容の無い一次ackは沈黙より悪い」)を、判定として置いたのが今回。

★この検査が担保すること:
  ①判定の正本は enjoh.ack_only_reason **1本だけ**(写しを持たない・ORG-11)
  ②その1本を、本文を出す口が**全部**引いている(炎上表記ゲートの部分適用事故を繰り返さない)
    = persona_send(webhook) / bot_send(Bot API) / codex_run(Codex席) / behop / dept_daemon
  ③落とした便は台帳に blocked として残る(黙って消えた便を後から辿れる)
  ④中身の在る便は1文字も削らずに出る(誤って黙らせる方が事故として重い= 規律§3)
★外へ出る手(urlopen / webhook解決)だけ偽物。判定と分岐は本物のまま実行で通す。
★must-fail 変異を2つ同梱= 「落とせない側」と「落としすぎる側」の両方を実際に作り、
  この検査が常に緑ではないことを毎回その場で示す(C-053= 動く別の実装。行は消さない)。
★本番の送信台帳(local/llm/send_audit.jsonl)を1バイトも増やさないことを E で機械確認する
  (2026-09-03 に検査そのものが台帳を汚していた事故の再発防止)。

実行: python scripts/discord/test_ack_denylist.py (全PASSで exit 0)
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

P = F = 0

# 炎上の実物そのもの(msg 1547305004069560351 が指した便の本文)。
ARSON = "受け取った。処理を開始する。完了結果は保存してから返す。"
# 中身の在る便= 1文字も削ってはいけない側。1文目はackだが2文目に実物が在る。
KEEP = "受け取った。ログの末尾は local/_teian_daily.log:2026-09-10 だ。"


def ok(cond, name):
    global P, F
    if cond:
        P += 1
        print("PASS", name)
    else:
        F += 1
        print("FAIL", name)


import enjoh  # noqa: E402
import send_audit as _sa  # noqa: E402

_AUDIT_TMP = tempfile.mkdtemp(prefix="ackdeny_audit_")
AUDIT_SANDBOX = os.path.join(_AUDIT_TMP, "llm", "send_audit.jsonl")
PROD_AUDIT = _sa.AUDIT
PROD_AUDIT_BEFORE = os.path.getsize(PROD_AUDIT) if os.path.exists(PROD_AUDIT) else 0


def audit_rows():
    if not os.path.exists(AUDIT_SANDBOX):
        return []
    with io.open(AUDIT_SANDBOX, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


# --- A 正本(enjoh.ack_only_reason)の判定 -------------------------------------------
ok(bool(enjoh.ack_only_reason(ARSON)), "A-1 炎上の実物を『定型ackだけ』と判定する")
ok(enjoh.ack_only_reason(KEEP) == "", "A-2 中身が1文でも在れば落とさない(部分一致で判定しない)")
ok(enjoh.ack_only_reason("") == "" and enjoh.ack_only_reason(None) == "",
   "A-3 空本文はここでは落とさない(空の判定は各口の持ち場・二重に持たない)")
ok(enjoh.ack_only_reason("受け取った。" * 40) == "",
   "A-4 %d字を超える本文は見ない= 黙らせない側へ倒す" % enjoh.ACK_MAX_CHARS)

# --- A' 裏便への表ack(2026-09-17 カスミ便 DISPATCH-aegis-gl-1789632009829)-------------
#   本番で12回出ていた実物。旧版の判定は**通していた**= ここが must-fail の芯。
URA_ACK = "受領。本対応は担当セッションへ引き継ぎます。"
ok(bool(enjoh.ack_only_reason(URA_ACK)),
   "A'-1 本番で12回出た『受領。本対応は担当セッションへ引き継ぎます。』を落とす")
for _t in ("承知いたしました。確認のうえ対応します。", "了解いたしました。引き続き待機します。",
           "受領。担当へ引き継ぎます。"):
    ok(bool(enjoh.ack_only_reason(_t)), "A'-2 同義形も落とす= %s" % _t)
# ★巻き添えを作らない側の検算(実測: 送信2,402件を新旧で通して、新たに落ちたのは上の12件だけ)。
for _t in ("受領。ログの末尾は 09-17 17:03 だ。",
           "了解いたしました。port 18841 で常駐が上がっています。",
           "担当セッションへ引き継ぎます。引き継ぎ先は platform-se(一ノ瀬怜)。"):
    ok(enjoh.ack_only_reason(_t) == "", "A'-3 中身が1文でも在れば送る= %s" % _t)


# --- B bot_send(Bot API口)を実行で通す ---------------------------------------------
def run_bot_send(mod, body, ack_gate=None):
    """bot_send.main() を実際に走らせる。戻り= (POSTされた本文 or None, 終了コード or None)。

    外へ出る手だけ偽物(urlopen)。トークン/チャンネル表は一時ディレクトリの偽物を読ませる
    = 本物の秘密を読まない・実チャンネルに触らない。送信ログは砂場へ逃がす。
    ack_gate を渡すとその口が引いているゲートだけ差し替える(must-fail 用)。
    """
    tmp = tempfile.mkdtemp(prefix="ackdeny_bot_")
    audit_real, taudit_real = _sa.AUDIT, _sa.TEST_AUDIT
    gate_real = getattr(mod, "ack_backstop", None)
    _sa.AUDIT = AUDIT_SANDBOX
    # ★2026-09-17 検査便の行き先(send_audit.TEST_AUDIT・2026-09-13新設)も砂場へ寄せる。
    #   これを付けないと、止めた1行は本番でも砂場でもなく local/llm/send_audit_test.jsonl へ
    #   落ちる= B-2/C-2/E-2 が「ゲートは効いているのに赤」になる(実測で踏んだ)。
    _sa.TEST_AUDIT = AUDIT_SANDBOX
    try:
        with io.open(os.path.join(tmp, "discord_bot_token.txt"), "w", encoding="utf-8") as f:
            f.write("dummy-token-not-a-secret")
        with io.open(os.path.join(tmp, "discord_channels.json"), "w", encoding="utf-8") as f:
            json.dump([{"name": "検査用ダミー", "dept": "dummy", "id": "1"}], f)
        mod.LOCAL = tmp
        if ack_gate is not None:
            mod.ack_backstop = ack_gate
        seen = {}

        class _Res:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"id": "0"}).encode("utf-8")

        def fake_urlopen(req, timeout=None):
            seen["content"] = json.loads(req.data.decode("utf-8"))["content"]
            return _Res()

        real_open = mod.urllib.request.urlopen
        argv, code = sys.argv, None
        try:
            mod.urllib.request.urlopen = fake_urlopen
            sys.argv = ["bot_send.py", "検査用ダミー", body]
            mod.main()
        except SystemExit as e:
            code = e.code
        finally:
            mod.urllib.request.urlopen = real_open
            sys.argv = argv
        return seen.get("content"), code
    finally:
        _sa.AUDIT, _sa.TEST_AUDIT = audit_real, taudit_real
        if ack_gate is not None and gate_real is not None:
            mod.ack_backstop = gate_real
        shutil.rmtree(tmp, ignore_errors=True)


import bot_send  # noqa: E402

_n0 = len(audit_rows())
_got, _code = run_bot_send(bot_send, ARSON)
ok(_got is None, "B-1 bot_send は炎上の実物を**1通も出さない**(urlopenを叩かない)")
ok(_code == 4, "B-1 終了コード4(既存の blocked と同じ形)= 呼び出し元が黙って成功と誤らない")
_rows = audit_rows()[_n0:]
ok(len(_rows) == 1 and _rows[0].get("event") == "blocked"
   and _rows[0].get("status") == "ack_only",
   "B-2 止めた便が台帳に blocked/ack_only で残る(黙って消さない)")
ok(_rows and ARSON[:20] in str(_rows[0].get("body", "") + _rows[0].get("head", "")),
   "B-2 台帳の本文から、何を止めたのかが読める")

_got2, _code2 = run_bot_send(bot_send, KEEP)
ok(_got2 == KEEP, "B-3 中身の在る便は1文字も削らずに出る(誤って黙らせない)")
ok(_code2 is None, "B-3 正常終了(ゲートが余計な非0を作らない)")


# --- C persona_send(webhook口)を実行で通す ------------------------------------------
import persona_send as ps  # noqa: E402


def run_persona_send(body, persona="アメス", ack_gate=None):
    """persona_send.main() を実行。外へ出る手= webhook解決と urlopen だけ偽物。"""
    tmp = tempfile.mkdtemp(prefix="ackdeny_ps_")
    audit_real, local_real = _sa.AUDIT, ps.LOCAL
    taudit_real = _sa.TEST_AUDIT
    hook_real = ps.ensure_persona_webhook
    gate_real = ps._ack_gate
    _sa.AUDIT = AUDIT_SANDBOX
    _sa.TEST_AUDIT = AUDIT_SANDBOX       # ★2026-09-17 検査便の行き先も砂場へ(上の run_bot_send と同じ理由)
    try:
        with io.open(os.path.join(tmp, "discord_bot_token.txt"), "w", encoding="utf-8") as f:
            f.write("dummy-token-not-a-secret")
        with io.open(os.path.join(tmp, "discord_channels.json"), "w", encoding="utf-8") as f:
            json.dump([{"name": "検査用ダミー", "dept": "dummy", "id": "1"}], f)
        ps.LOCAL = tmp
        ps.ensure_persona_webhook = lambda *a, **k: "https://example.invalid/webhook-dummy"
        if ack_gate is not None:
            ps._ack_gate = ack_gate
        seen = {}

        class _Res:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"id": "0"}).encode("utf-8")

        def fake_urlopen(req, timeout=None):
            pl = json.loads(req.data.decode("utf-8"))
            seen.setdefault("posts", []).append(
                pl.get("content") or "".join(str((e or {}).get("description", ""))
                                             for e in (pl.get("embeds") or [])))
            return _Res()

        real_open = ps.urllib.request.urlopen
        argv, code = sys.argv, None
        try:
            ps.urllib.request.urlopen = fake_urlopen
            sys.argv = ["persona_send.py", "--channel", "検査用ダミー",
                        "--persona", persona, "--body", body]
            ps.main()
        except SystemExit as e:
            code = e.code
        finally:
            ps.urllib.request.urlopen = real_open
            sys.argv = argv
        return seen.get("posts", []), code
    finally:
        _sa.AUDIT, ps.LOCAL = audit_real, local_real
        _sa.TEST_AUDIT = taudit_real
        ps.ensure_persona_webhook = hook_real
        if ack_gate is not None:
            ps._ack_gate = gate_real
        shutil.rmtree(tmp, ignore_errors=True)


_n0 = len(audit_rows())
_posts, _code = run_persona_send(ARSON)
ok(_posts == [], "C-1 persona_send も炎上の実物を1通も出さない")
ok(_code == 4, "C-1 終了コード4(english_backstop の blocked と同じ形)")
_rows = audit_rows()[_n0:]
ok(len(_rows) == 1 and _rows[0].get("event") == "blocked"
   and _rows[0].get("status") == "ack_only" and _rows[0].get("persona") == "アメス",
   "C-2 止めた便が誰の名義だったかまで台帳に残る")

_posts2, _ = run_persona_send("[アメス] 受け取った。処理を開始する。")
ok(_posts2 == [], "C-3 名乗り `[アメス]` を剥がした残りが定型ackだけなら止める")

_posts3, _code3 = run_persona_send(KEEP)
ok(len(_posts3) == 1 and KEEP in _posts3[0],
   "C-4 中身の在る便はそのまま出る(1通・本文を削らない)")
ok(_code3 is None, "C-4 正常終了")

# C-5 配線= main() が実際にゲートを呼ぶ形でコンパイルされている(呼び出しが外されたら赤)。
ok("_ack_gate" in ps.main.__code__.co_names, "C-5 persona_send.main() がackゲートを呼ぶ")
ok("ack_backstop" in bot_send.main.__code__.co_names, "C-5 bot_send.main() がackゲートを呼ぶ")
ok(ps._ack_gate is enjoh.ack_backstop and bot_send.ack_backstop is enjoh.ack_backstop,
   "C-5 両方の口が引いているのは正本 enjoh.ack_backstop そのもの(写しを持たない)")


# --- D 残りの口(Codex席・behop・部屋の常駐) ------------------------------------------
sys.path.insert(0, os.path.join(ROOT, "scripts", "codex"))
import codex_run  # noqa: E402

ok(codex_run.prepare_discord_chunks(ARSON) == [],
   "D-1 Codex席の唯一の出口が空リストを返す= 1通も出さない(★炎上の真因経路)")
_ck = codex_run.prepare_discord_chunks(KEEP)
ok(len(_ck) == 1 and KEEP in _ck[0], "D-1 中身の在る便はチャンクになって出る")

_cseen = []
_creal = codex_run.urllib.request.urlopen
try:
    codex_run.urllib.request.urlopen = lambda req, timeout=None: (
        _cseen.append(1) or (_ for _ in ()).throw(AssertionError("送ってはいけない便を送った")))
    _res = codex_run.dc_send_result("dummy-token-not-a-secret", "1", ARSON)
finally:
    codex_run.urllib.request.urlopen = _creal
ok(not _cseen and _res.get("sent_count") == 0,
   "D-2 dc_send も1通も出さない(notify_room→dc_send の経路が実際に止まる)")
ok(_res.get("ok") is True,
   "D-2 呼び出し元は失敗扱いにしない(再送ループを作らない= 沈黙で正しく終わる)")

sys.path.insert(0, os.path.join(ROOT, "scripts", "behop"))
import behop  # noqa: E402


class _BRes:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"id": "0"}).encode("utf-8")


def run_behop(text):
    seen = []
    real = behop.urllib.request.urlopen
    try:
        behop.urllib.request.urlopen = lambda req, timeout=None: (
            seen.append(json.loads(req.data.decode("utf-8"))["content"]) or _BRes())
        r = behop.dc_send("dummy-token-not-a-secret", "1", text)
    finally:
        behop.urllib.request.urlopen = real
    return seen, r


_bseen, _br = run_behop(ARSON)
ok(_bseen == [] and _br is True, "D-3 behop も1通も出さない(呼び出し元は失敗扱いにしない)")
_bseen2, _ = run_behop(KEEP)
ok(len(_bseen2) == 1 and KEEP in _bseen2[0], "D-3 behop も中身の在る便は出す")

sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
import dept_daemon as dd  # noqa: E402

ok(dd._ack_judge() is enjoh.ack_only_reason,
   "D-4 部屋の常駐(dept_daemon)も同じ正本を引く")
ok(dd.sendable_blocks([("オタコン", ARSON)], lambda n: n) == []
   and dd.sendable_blocks([("オタコン", KEEP)], lambda n: n) == [("オタコン", KEEP)],
   "D-4 常駐の空便ガードでも 止める/出す が同じ向きに揃う")

# D-5 imagegen は**当てない**。あの口の成果物は画像で、キャプションが定型ackでも画像は届ける
#     べきものだから= 消す方が事故として重い。忘れているのではなく、当てない判断だと残す。
spec = importlib.util.spec_from_file_location(
    "imagegen_generate", os.path.join(ROOT, "scripts", "imagegen", "generate.py"))
_gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_gen)
ok("ack_backstop" not in _gen.discord_upload.__code__.co_names,
   "D-5 画像便(imagegen)には当てない= 画像を消さない(判断として明示)")


# --- MF must-fail 変異(落とせない側 / 落としすぎる側の両方) --------------------------
def load_mutant(name, src_path, replace_from, replace_to):
    """元ファイルの一部を**動く別の実装**へ差し替えた版を読む(文法は壊さない= 偽の緑を作らない)。"""
    src = io.open(src_path, encoding="utf-8").read()
    assert replace_from in src, f"変異の当たり所が無い: {name}"
    tmp = tempfile.mkdtemp(prefix="ackdeny_mutant_")
    path = os.path.join(tmp, name + ".py")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(replace_from, replace_to))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# MF-1 落とせない側= Codex席のゲートを外した版(=09-10 09:36 に本文だけ撤去した状態と同じ守り)。
m1 = load_mutant("codex_run_mutant", os.path.join(ROOT, "scripts", "codex", "codex_run.py"),
                 "        if ack_backstop(text, tag=\"codex\"):\n            return []",
                 "        if False:  # 変異: ackゲートを通さない(撤去だけの守り)\n            return []")
ok(m1.prepare_discord_chunks(ARSON) != []
   and codex_run.prepare_discord_chunks(ARSON) == [],
   "MF-1 ゲートを外すと炎上の実物がまた出る(=D-1は本当に効いている)")

# MF-2 落としすぎる側= 判定を「1文でも句に当たれば落とす」へ広げた版。中身の在る返事を黙らせる。
m2 = load_mutant("enjoh_mutant", os.path.join(HERE, "enjoh.py"),
                 "        if not units or not all(u in _ACK_PHRASES for u in units):",
                 "        if not units or not any(u in _ACK_PHRASES for u in units):")
_posts_m, _ = run_persona_send(KEEP, ack_gate=m2.ack_backstop)
ok(_posts_m == [] and len(run_persona_send(KEEP)[0]) == 1,
   "MF-2 判定を広げると中身の在る返事まで黙る(=C-4は本当に効いている)")


# --- E 検査そのものの衛生(本番台帳を汚さない) -----------------------------------------
_prod_after = os.path.getsize(PROD_AUDIT) if os.path.exists(PROD_AUDIT) else 0
ok(_prod_after == PROD_AUDIT_BEFORE,
   f"E-1 本番の送信台帳が1バイトも増えていない({PROD_AUDIT_BEFORE} → {_prod_after} bytes)")
_all = audit_rows()
ok(len(_all) >= 4 and all(r.get("dept") in ("dummy", "") for r in _all),
   f"E-2 検査が出した行は砂場に落ちている({len(_all)}行・本番の部門名を含まない)")
ok(any(r.get("event") == "blocked" and r.get("status") == "ack_only" for r in _all),
   "E-2 砂場に blocked/ack_only が在る(=監査そのものが止まって緑になっていない)")

shutil.rmtree(_AUDIT_TMP, ignore_errors=True)

print(f"\n{P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
