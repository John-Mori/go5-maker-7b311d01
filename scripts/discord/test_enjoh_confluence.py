#!/usr/bin/env python3
"""炎上表記ゲートを**両方の合流点**で担保する検査(2026-09-02 イージス研究室)。

なぜ要るか:
  2026-09-01 に persona_send(webhook口)へゲートを入れた。だが Discordへ本文をPOSTする口は
  もう1つ在る= **Bot API の bot_send.py**。そちらは素通しのままで、absence_watchdog の
  配送失敗警報などは素の🔥のままChamiの目の前へ出ていた= 部分適用。Chamiの再指摘
  (REQ-kaizen-analyst-90ebe8bfc8)の真因はこれなので、
    (1) 実装の正本を scripts/discord/enjoh.py に1本化し
    (2) bot_send の**POST直前**でも同じゲートを通す
  ことを、ソースの字面ではなく**実行**で確かめる。

  ★外へ出る手(urlopen)だけを偽物にし、チャンネル解決・本文組み立て・ゲート・payload組成は
    本物のまま通す。Discordへは1件も出さない(本番の部屋でテストしない)。
  ★must-fail 変異を2つ同梱= この検査が「常に緑」でないことを毎回その場で示す。
    変異は**動く別の実装**へ差し替える(行を消して文法を壊すと偽の緑になる)。

★2026-09-03 修正(ルカ・モドリッチの指摘): この検査は**本番台帳を汚していた**。
  run_bot_send() は mod.LOCAL を一時ディレクトリへ向けていたが、それが効くのは bot_send 自身の
  ファイル読み(トークン/チャンネル表)だけで、送信ログは別経路= bot_send.py L47 の
  `import send_audit` が自前で書き先を決める。結果、本番の local/llm/send_audit.jsonl に
  `dept=dummy` / `channel=検査用ダミー` の行が回すたび3本積まれ(実物= 411〜413行・
  2026-09-03T10:19:53〜54)、whatis や集計が偽の送信を拾い続ける状態になっていた。
  = 検査が観測を壊していた。よってこの版では send_audit の書き先そのものを砂場へ向け、
  **回した後に本番台帳が1バイトも増えていないこと**を検査項目(E-1)として毎回機械で確かめる。

実行: python scripts/discord/test_enjoh_confluence.py (全PASSで exit 0)
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
sys.path.insert(0, HERE)

FIRE = "\U0001F525"
ENJOH = "<:enjoh:1541126866981752883>"
P = F = 0


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

# 送信ログの砂場。本番 local/llm/send_audit.jsonl の代わりにここへ書かせる。
_AUDIT_TMP = tempfile.mkdtemp(prefix="enjoh_audit_")
AUDIT_SANDBOX = os.path.join(_AUDIT_TMP, "llm", "send_audit.jsonl")
PROD_AUDIT = _sa.AUDIT
PROD_AUDIT_BEFORE = os.path.getsize(PROD_AUDIT) if os.path.exists(PROD_AUDIT) else 0
# ★検査便の受け皿(2026-09-13 追加の TEST_AUDIT)も共有の実ファイル= ここも汚さない。
PROD_TEST_AUDIT = getattr(_sa, "TEST_AUDIT", None)
PROD_TEST_BEFORE = (os.path.getsize(PROD_TEST_AUDIT)
                    if PROD_TEST_AUDIT and os.path.exists(PROD_TEST_AUDIT) else 0)

# --- A 正本(enjoh.py)の振る舞い -------------------------------------------------
# A-1 Chamiが指摘した表記そのもの。「🔥炎上 9件」→「<:enjoh:…>恒久 9件」。
real = FIRE + "炎上 9件 → 恒久対策が\"入っていない\"のは1件だけ"
out = enjoh.enjoh_backstop(real)
ok(FIRE not in out, "A-1 素の🔥が残らない")
ok(out.startswith(ENJOH + "恒久 9件"), "A-1 Chami指定の表記 <:enjoh:…>恒久 9件 になる")

# A-2 生成側が絵文字までは正しく書き、ラベルだけ「炎上」で来た便も直る(ここが今回の追加分)。
ok(enjoh.enjoh_backstop(ENJOH + "炎上 9件") == ENJOH + "恒久 9件",
   "A-2 既に<:enjoh:…>でもラベルだけの便を直す")
ok(enjoh.enjoh_backstop(FIRE + "(炎上)が9件") == ENJOH + "(恒久)が9件",
   "A-2 括弧つきラベルも直す")

# A-3 ★語としての「炎上」は壊さない= 誤発火する安全網は無視される(規律§3)。
ok(enjoh.enjoh_backstop(FIRE + "炎上した。") == ENJOH + "炎上した。",
   "A-3 動詞『炎上した』は変えない")
ok(enjoh.enjoh_backstop(ENJOH + " 先週の炎上案件の件だが") == ENJOH + " 先週の炎上案件の件だが",
   "A-3 地の文の『炎上案件』は変えない")
plain = "先週の炎上の件は片付いた。"
ok(enjoh.enjoh_backstop(plain) == plain, "A-3 絵文字が無い便は1ミリも変えない")

# A-4 コードの中は不変(規律や実装の説明で素の🔥をそのまま見せる面がある)。
inline = "規律§5は `" + FIRE + "` を地の文に置くなと言っている。"
ok(enjoh.enjoh_backstop(inline) == inline, "A-4 インラインcode内は不変")

# A-5 fail-open。
ok(enjoh.enjoh_backstop("") == "" and enjoh.enjoh_backstop(None) is None,
   "A-5 空文字/Noneで落ちない(fail-open)")


# --- B bot_send の口を実行で通す --------------------------------------------------
def run_bot_send(mod, body, audit_to=AUDIT_SANDBOX):
    """bot_send.main() を実際に走らせ、Discordへ出るはずだった payload の content を返す。

    外へ出る手だけ偽物(urlopen)。トークン/チャンネルは一時ディレクトリの偽物を読ませる
    = 本物の秘密を読まない・実チャンネルに触らない。

    ★送信ログ(send_audit)の書き先も砂場へ向ける。mod.LOCAL の差し替えでは届かない
      (send_audit は別モジュールとして自分で書き先を持つ)。audit_to=None を渡すと
      向け直さない= 汚していた頃の振る舞い。must-fail(E-2)でだけ使う。
    ★AUDIT だけでは届かない(2026-09-20 実測)。send_audit は 2026-09-13 から
      `_is_test_entry()`= 起動スクリプト名が test_ で始まる走行を **TEST_AUDIT**
      (local/llm/send_audit_test.jsonl)へ振り分ける。この検査はまさにそれに当たるので、
      AUDIT を向け直しても行は共有の send_audit_test.jsonl へ落ちていた=砂場は0行。
      書き先は**2本とも**砂場へ向ける。
    """
    tmp = tempfile.mkdtemp(prefix="enjoh_gate_")
    audit_real = _sa.AUDIT
    test_audit_real = getattr(_sa, "TEST_AUDIT", None)
    if audit_to:
        _sa.AUDIT = audit_to
        if test_audit_real is not None:
            _sa.TEST_AUDIT = audit_to
    try:
        with io.open(os.path.join(tmp, "discord_bot_token.txt"), "w", encoding="utf-8") as f:
            f.write("dummy-token-not-a-secret")
        with io.open(os.path.join(tmp, "discord_channels.json"), "w", encoding="utf-8") as f:
            json.dump([{"name": "検査用ダミー", "dept": "dummy", "id": "1"}], f)
        mod.LOCAL = tmp
        seen = {}

        class _Res:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            seen["content"] = json.loads(req.data.decode("utf-8"))["content"]
            return _Res()

        real_open = mod.urllib.request.urlopen
        argv = sys.argv
        try:
            mod.urllib.request.urlopen = fake_urlopen
            sys.argv = ["bot_send.py", "検査用ダミー", body]
            mod.main()
        finally:
            mod.urllib.request.urlopen = real_open
            sys.argv = argv
        return seen.get("content")
    finally:
        _sa.AUDIT = audit_real
        if test_audit_real is not None:
            _sa.TEST_AUDIT = test_audit_real
        shutil.rmtree(tmp, ignore_errors=True)


import bot_send  # noqa: E402

# B-1 実物の再現= absence_watchdog.py:1328 の配送失敗警報(bot_send経由・素の🔥で始まる)。
watchdog = FIRE + " **Chamiの便が3件、配送に失敗したまま放置されています**"
got = run_bot_send(bot_send, watchdog)
ok(got is not None and FIRE not in got, "B-1 bot_send経由の便に素の🔥が残らない")
ok(got is not None and got.startswith(ENJOH), "B-1 <:enjoh:…>へ置換されて出る")

# B-2 Chamiが読む面のラベルも bot_send 側で直る。
got2 = run_bot_send(bot_send, FIRE + "炎上 9件 / 恒久9件")
ok(got2 == ENJOH + "恒久 9件 / 恒久9件", "B-2 bot_send経由でもラベルが恒久になる")

# B-3 配線= main() が実際にゲートを呼ぶ形でコンパイルされている。
ok("enjoh_backstop" in bot_send.main.__code__.co_names, "B-3 bot_send.main() がゲートを呼ぶ")

# B-4 webhook側(persona_send)の配線が生きたままであること(既存の担保を壊していない)。
import persona_send as ps  # noqa: E402
# ★2026-09-09 HQ-0253= persona_send の3ゲートは apply_text_gates() 1本へ寄った。
#   main()→合流点、合流点→enjoh の両方を見る(片方だけだと切れても緑になる)。
ok("apply_text_gates" in ps.main.__code__.co_names, "B-4 persona_send.main() の配線が残っている")
ok("enjoh_backstop" in ps.apply_text_gates.__code__.co_names,
   "B-4 合流点 apply_text_gates がゲートを呼ぶ")
ok(ps.enjoh_backstop(real).startswith(ENJOH + "恒久 9件"), "B-4 persona_send側も同じ結果を返す")


# --- D 残りの合流点(全数grepで見つけた口を1本ずつ) --------------------------------
# D-1 べホップ(gemini3人部屋のbot本人)。Chamiが同席する部屋なのでここも見える面。
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "behop"))
import behop  # noqa: E402


class _BehopRes:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"id": "0"}).encode("utf-8")


_bseen = []
_breal = behop.urllib.request.urlopen
try:
    behop.urllib.request.urlopen = lambda req, timeout=None: (
        _bseen.append(json.loads(req.data.decode("utf-8"))["content"]) or _BehopRes())
    behop.dc_send("dummy-token-not-a-secret", "1", FIRE + "炎上 2件、まだ残っている")
finally:
    behop.urllib.request.urlopen = _breal
ok(_bseen and FIRE not in _bseen[0] and _bseen[0].startswith(ENJOH + "恒久 2件"),
   "D-1 behop.dc_send も同じ正規化を通る")

# D-2 画像便のキャプション(imagegen)。実投稿は webhook + 画像が要るので、ここは配線まで
#     (=main相当の関数がゲートを呼ぶ形でコンパイルされているか)を担保する。
spec = importlib.util.spec_from_file_location(
    "imagegen_generate", os.path.join(os.path.dirname(HERE), "imagegen", "generate.py"))
_gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_gen)
ok("enjoh_backstop" in _gen.discord_upload.__code__.co_names,
   "D-2 imagegen の画像便キャプションもゲートを呼ぶ")


# --- C must-fail 変異(この検査が本当に赤くなるかを毎回その場で示す) ------------------
def load_mutant(name, src_path, replace_from, replace_to):
    """元ファイルの一部を**動く別の実装**へ差し替えた版を読み込む(文法は壊さない)。"""
    src = io.open(src_path, encoding="utf-8").read()
    assert replace_from in src, f"変異の当たり所が無い: {name}"
    tmp = tempfile.mkdtemp(prefix="enjoh_mutant_")
    path = os.path.join(tmp, name + ".py")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(replace_from, replace_to))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# C-1 変異: bot_send からゲート呼び出しを外す(=2026-09-01時点の実装に戻す)。
m1 = load_mutant("bot_send_mutant", os.path.join(HERE, "bot_send.py"),
                 '    body = enjoh_backstop(body, tag="bot_send")\n',
                 '    body = body  # 変異: ゲートを通さない(旧実装)\n')
m1_got = run_bot_send(m1, watchdog)
ok(m1_got is not None and FIRE in m1_got,
   "C-1 must-fail ゲートを外すと素の🔥が出る(=B-1は本当に効いている)")

# C-2 変異: ラベル規則を「全部の炎上」へ広げる(=雑に直した版)。
m2 = load_mutant("enjoh_mutant", os.path.join(HERE, "enjoh.py"),
                 '_LABEL_RE = re.compile(r"(" + re.escape(ENJOH_EMOJI) + r"\\s*[(【]?)炎上(?=[)】\\s0-9=:、。」]|$)")',
                 '_LABEL_RE = re.compile(r"()炎上")  # 変異: 絵文字に隣接しない語まで壊す')
ok(m2.enjoh_backstop(FIRE + "炎上した。") != ENJOH + "炎上した。",
   "C-2 must-fail 規則を広げると『炎上した』が壊れる(=A-3は本当に効いている)")

# --- E 検査そのものの衛生(本番台帳を汚さない) ---------------------------------------
# E-1 ここまでで bot_send.main() を3回通した(B-1 / B-2 / C-1)。その3行は砂場に落ち、
#     本番の送信台帳は1バイトも増えていないこと。★増えていない側だけを見ると、
#     「監査そのものが止まった」場合も緑になるので、砂場に3行あることも同時に見る。
_prod_after = os.path.getsize(PROD_AUDIT) if os.path.exists(PROD_AUDIT) else 0
ok(_prod_after == PROD_AUDIT_BEFORE,
   f"E-1 本番の送信台帳が増えていない({PROD_AUDIT_BEFORE} → {_prod_after} bytes)")
_rows = []
if os.path.exists(AUDIT_SANDBOX):
    with io.open(AUDIT_SANDBOX, encoding="utf-8") as f:
        _rows = [json.loads(x) for x in f if x.strip()]
ok(len(_rows) == 3 and all(r.get("dept") == "dummy" for r in _rows),
   f"E-1 検査が出した3行は砂場に落ちている(dept=dummy / 実際は{len(_rows)}行)")
_prod_test_after = (os.path.getsize(PROD_TEST_AUDIT)
                    if PROD_TEST_AUDIT and os.path.exists(PROD_TEST_AUDIT) else 0)
ok(_prod_test_after == PROD_TEST_BEFORE,
   f"E-1 検査便の共有受け皿(send_audit_test.jsonl)も増えていない"
   f"({PROD_TEST_BEFORE} → {_prod_test_after} bytes)")

# E-2 must-fail: 書き先を向け直さない版(=2026-09-03朝まで動いていた汚す実装)を再現する。
#     ★本番では試さない= 偽の本番ファイルを一時に作って撃つ。
#     ★主張は 2026-09-20 に実測へ合わせた。2026-09-13 に send_audit が検査便ルート
#       (TEST_AUDIT)を持ったので、向け直さなくても **本番の送信台帳(AUDIT)は汚れない**=
#       行は検査便の受け皿へ落ちる。それでも砂場には1行も来ない= E-1 の「砂場に3行」は
#       run_bot_send の向け直しが本当に効いているから緑になっている、と言える。
_fake_prod = os.path.join(_AUDIT_TMP, "fake_prod_send_audit.jsonl")
_fake_test = os.path.join(_AUDIT_TMP, "fake_prod_send_audit_test.jsonl")
for _p in (_fake_prod, _fake_test):
    with io.open(_p, "w", encoding="utf-8") as f:
        f.write("")
_sandbox_before = len(_rows)
_sa.AUDIT = _fake_prod
if PROD_TEST_AUDIT is not None:
    _sa.TEST_AUDIT = _fake_test
try:
    run_bot_send(bot_send, watchdog, audit_to=None)      # ← 逃がさない旧実装の再現
finally:
    _sa.AUDIT = PROD_AUDIT
    if PROD_TEST_AUDIT is not None:
        _sa.TEST_AUDIT = PROD_TEST_AUDIT
with io.open(AUDIT_SANDBOX, encoding="utf-8") as f:
    _sandbox_after = len([x for x in f if x.strip()])
ok(_sandbox_after == _sandbox_before,
   f"E-2 must-fail 向け直さないと砂場には落ちない({_sandbox_before} → {_sandbox_after}行"
   "・E-1は本当に効いている)")
_dirty = []
if os.path.exists(_fake_test):
    with io.open(_fake_test, encoding="utf-8") as f:
        _dirty = [x for x in f if x.strip()]
with io.open(_fake_prod, encoding="utf-8") as f:
    _dirty_prod = [x for x in f if x.strip()]
ok(len(_dirty) == 1 and json.loads(_dirty[0]).get("channel") == "検査用ダミー"
   and not _dirty_prod,
   f"E-2 その1行は消えずに検査便ルートへ落ちる(受け皿{len(_dirty)}行 / "
   f"本番想定{len(_dirty_prod)}行= 2026-09-13 の二重の網)")

shutil.rmtree(_AUDIT_TMP, ignore_errors=True)

print(f"\n{P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
