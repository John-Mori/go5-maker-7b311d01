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
def run_bot_send(mod, body):
    """bot_send.main() を実際に走らせ、Discordへ出るはずだった payload の content を返す。

    外へ出る手だけ偽物(urlopen)。トークン/チャンネルは一時ディレクトリの偽物を読ませる
    = 本物の秘密を読まない・実チャンネルに触らない。
    """
    tmp = tempfile.mkdtemp(prefix="enjoh_gate_")
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
ok("enjoh_backstop" in ps.main.__code__.co_names, "B-4 persona_send.main() の配線が残っている")
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

print(f"\n{P} PASS / {F} FAIL")
sys.exit(0 if F == 0 else 1)
