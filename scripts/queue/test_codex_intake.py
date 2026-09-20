#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex便の取り込みの回帰ガード(2026-09-20・イージス研究室/C-038・C-053)。

守る不具合= Chami msg 1551232720326369301「ボス(Codex)の内容って届いてないよね？
  ちゃんと認識できるようにならない？Claude側の既読とかは要らんからさ」
  / 人事部門ククール便 msg 1551235369209430038(真因の特定)。
実物(2026-09-20 実測)= 人事部門(hr-room)でボスが返した4通
  1551231965599105066 / 1551231970518896682 / 1551232953277882392 / 1551232956989972523 は
  **1通もキューに無い**。同じ部屋の同じ時間帯のChami便 1551232720326369301 は入っている。
  受信入口の `if m.author.bot or m.webhook_id: ... return` がボスの回答ごと捨てていた。

★ソースの文字列一致で「入っている」を確かめない= **本物の handle_message を実行で通す**。
  偽物にするのは**外へ出る手**だけ(キューDB・gatewayログ・脈・送信印)。判定は本物のまま。
★便の中身は手打ちしない= 実際にボスが投稿した本文を `local/llm/codex_outbox/*.json` の
  chunks/message_ids から引く(chunk[i] がそのまま message_ids[i] として投稿された本文)。
★本番へ1バイトも書かない= local/queue/inbox.db と gatewayログの mtime/size を前後で比較する。

使い方:
  python scripts/queue/test_codex_intake.py
  python scripts/queue/test_codex_intake.py --mutant off         # 旧実装(bot一括除外)へ戻す
  python scripts/queue/test_codex_intake.py --mutant allbots     # bot全開放(素朴な直し方)
  python scripts/queue/test_codex_intake.py --mutant summonloop  # Codex便も@ボス召喚判定へ通す
  python scripts/queue/test_codex_intake.py --mutant codexroom   # Codex専用部屋のガードを外す
いずれの変異体でも rc=1(赤)になること= この検査が本当に見張っている証拠。
"""

import asyncio
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
for _p in (HERE, os.path.join(ROOT, "scripts", "llm")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MUTANT = ""
if "--mutant" in sys.argv:
    MUTANT = sys.argv[sys.argv.index("--mutant") + 1]

# ---- 変異体(must-fail)= **ソースを差し替えて本物として読み込む** ------------------
#   monkeypatch では届かない場所(入口の条件・召喚分岐)を変えるため、コピーへ1行だけ
#   当てて import する。コピーは scripts/queue/ の中に置く(HERE/ROOT が本物と同じに
#   なる=依存の解決が本番と1文字も変わらない)。走り終わったら必ず消す。
GW_SRC = os.path.join(HERE, "discord_gateway.py")
MUTATIONS = {
    "off": [("    if (m.author.bot or m.webhook_id) and not from_codex:",
             "    if (m.author.bot or m.webhook_id):")],
    "allbots": [("    if not is_codex_author(author_id, author_name):",
                 "    if False:"),
                ("    if self_id is not None and str(author_id or \"\") == str(self_id):",
                 "    if False:")],
    "summonloop": [("    elif _codex_summon_on() and rec.get(\"dept\") != \"codex\"",
                    "    if _codex_summon_on() and rec.get(\"dept\") != \"codex\"")],
    "codexroom": [("    if str(dept or \"\") == \"codex\":", "    if False:")],
}
if MUTANT and MUTANT not in MUTATIONS:
    print(f"知らない変異体: {MUTANT}")
    sys.exit(2)

_COPY = os.path.join(HERE, "_gw_under_test_tmp.py")


def load_gateway():
    src = io.open(GW_SRC, encoding="utf-8").read()
    for a, b in MUTATIONS.get(MUTANT, []):
        if a not in src:
            print(f"変異の当て先が見つからない(検査の前提が崩れている): {a!r}")
            sys.exit(2)
        src = src.replace(a, b, 1)
    io.open(_COPY, "w", encoding="utf-8", newline="").write(src)
    spec = importlib.util.spec_from_file_location("_gw_under_test_tmp", _COPY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}" + (f"\n       {extra}" if extra else ""))


def _stat(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


# ---- 偽のDiscordオブジェクト(外へ出る手だけが偽物。判定は本物) ------------------
class FakeAuthor(object):
    def __init__(self, name, id_, bot=False):
        self.name = name
        self.id = id_
        self.bot = bot


class FakeChannel(object):
    def __init__(self, id_, name):
        self.id = id_
        self.name = name

    async def fetch_message(self, _mid):        # 引用の再取得は起きない前提
        raise RuntimeError("検査では外へ出ない")


class FakeMessage(object):
    def __init__(self, msg_id, content, author, channel, webhook_id=None):
        self.id = msg_id
        self.content = content
        self.created_at = None
        self.author = author
        self.attachments = []
        self.channel = channel
        self.webhook_id = webhook_id
        self.guild = None
        self.reference = None
        self.reactions_pressed = []

    async def add_reaction(self, emoji):
        self.reactions_pressed.append(emoji)


def main():
    global PASS, FAIL
    dg = load_gateway()
    import codex_trigger

    # ---- 本番の「前」を控える(検査が本番へ書いていないことを実測で示す)------------
    PROD = {p: _stat(p) for p in (dg.QUEUE_DB, dg.LOG_FILE)}

    # ---- 砂場 ------------------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="codex_intake_")
    sandbox_db = os.path.join(tmp, "inbox.db")
    dg.LOCAL = tmp                      # 優依並走の写し等、実行時に組む書き先を全部砂場へ
    dg.LOG_FILE = os.path.join(tmp, "gateway.log")
    dg._touch_pulse = lambda: None      # 脈(共有ファイル)は外へ出る手=止める
    dg.ACTIVE_JOBS = False              # 既定は副作用なし(送信印の分はKで明示的に立てる)
    dg._codex_summon_on = lambda: True  # @ボス召喚= 札の有無に依存させない(判定本体を見る)
    q = dg.LeaseQueue(sandbox_db)

    def rows():
        con = sqlite3.connect(sandbox_db)
        try:
            return [dict(msg_id=r[0], dept=r[1], body=json.loads(r[2]))
                    for r in con.execute("select msg_id,dept,body from queue")]
        finally:
            con.close()

    def run(m, chan_map, self_id):
        asyncio.run(dg.handle_message(m, chan_map, q, self_id=self_id))

    # ---- 実物を引く ------------------------------------------------------------
    prod_map = dg.load_channel_map()            # 本番の部屋台帳(読むだけ)
    ob = json.load(io.open(os.path.join(
        ROOT, "local", "llm", "codex_outbox", "1551230948731920454.json"), encoding="utf-8"))
    ch_id = str(ob["channel_id"])
    real_dept = str((prod_map.get(ch_id) or {}).get("dept", ""))
    real_name = str((prod_map.get(ch_id) or {}).get("name", ""))
    codex_msg_id = str(ob["message_ids"][0])
    codex_body = str(ob["chunks"][0])
    codex_ids = codex_trigger.codex_bot_ids()
    codex_id = int(list(codex_ids)[0]) if codex_ids else 0
    SELF_ID = 1519999999999999999                # このgatewayのbot(= 自分)

    print(f"\n[実物] 部屋={real_name}({ch_id}) dept={real_dept} / "
          f"落ちていたボスの投稿 msg={codex_msg_id} {len(codex_body)}字 / "
          f"codex bot id={codex_id or '(台帳なし)'}")
    chan_map = {ch_id: {"id": ch_id, "name": real_name, "dept": real_dept}}

    check("前提: Codex bot の id 台帳が生きている", bool(codex_id),
          "local/discord_codex_bot_id.txt が空= 識別が username 退避のみになる")
    check("前提: 落ちていた便の部屋が台帳にある(dept解決できる)", bool(real_dept),
          f"chan_map に {ch_id} が無い")

    # A: 実物のCodex便が便になる ------------------------------------------------
    m = FakeMessage(int(codex_msg_id), codex_body,
                    FakeAuthor("Codex_SnakeBot", codex_id, bot=True),
                    FakeChannel(int(ch_id), real_name))
    run(m, chan_map, SELF_ID)
    r = [x for x in rows() if x["msg_id"] == codex_msg_id]
    check("A 実際に落ちていたボスの投稿がenqueueされる", len(r) == 1,
          f"rows={rows()}")
    if r:
        check("A2 deptは元の部屋のまま(部屋を乗っ取らない)", r[0]["dept"] == real_dept,
              f"dept={r[0]['dept']} 期待={real_dept}")
        check("A3 便に from_codex が載る(拾う側がボスの回答だと分かる)",
              r[0]["body"].get("from_codex") is True, f"body keys={list(r[0]['body'])}")
        check("A4 本文が無改変で載る",
              r[0]["body"].get("content") == codex_body)
        check("A5 差出人はCodex本人", r[0]["body"].get("author") == "Codex_SnakeBot")

    # B: ボスの回答に「@ボス」が書かれていても codex へ戻さない(ループしない) ----
    before = len(rows())
    m = FakeMessage(900000000000000001,
                    "対応した。続きは @ボス に投げ直してくれ。",
                    FakeAuthor("Codex_SnakeBot", codex_id, bot=True),
                    FakeChannel(int(ch_id), real_name))
    run(m, chan_map, SELF_ID)
    r = [x for x in rows() if x["msg_id"] == "900000000000000001"]
    check("B ボスの回答は@ボス召喚へ戻らない(自分の回答に自分で答える輪を作らない)",
          len(r) == 1 and r[0]["dept"] == real_dept,
          f"r={r}")

    # C: 自分(このgatewayのbot)の投稿は取り込まない ------------------------------
    before = len(rows())
    m = FakeMessage(900000000000000002, "自分の返信",
                    FakeAuthor("go5-bot", SELF_ID, bot=True),
                    FakeChannel(int(ch_id), real_name))
    run(m, chan_map, SELF_ID)
    check("C 自分の投稿は便にしない(自分で自分を起こさない)", len(rows()) == before,
          f"{before} → {len(rows())}")

    # D: Codex以外のbotは今までどおり捨てる(bot全開放にしない) -------------------
    before = len(rows())
    m = FakeMessage(900000000000000003, "定時の自動通知です",
                    FakeAuthor("Behop_Bot", 1530000000000000001, bot=True),
                    FakeChannel(int(ch_id), real_name))
    run(m, chan_map, SELF_ID)
    check("D Codex以外のbotは便にしない(開けたのはボスの1口だけ)", len(rows()) == before,
          f"{before} → {len(rows())}")

    # E: Chamiミラー(webhook)は従来どおり enqueue しない -------------------------
    before = len(rows())
    m = FakeMessage(900000000000000004, "ミラーされたChami便",
                    FakeAuthor("Chami(研究室)", 1530000000000000002, bot=False),
                    FakeChannel(int(ch_id), real_name), webhook_id=123456789)
    run(m, chan_map, SELF_ID)
    check("E Chamiミラー(webhook)は従来どおり便にしない", len(rows()) == before,
          f"{before} → {len(rows())}")

    # G: Codexを名乗るwebhookは取り込まない(本人はbot tokenで投稿する) -----------
    before = len(rows())
    m = FakeMessage(900000000000000005, "ボスの名を騙る便",
                    FakeAuthor("Codex_SnakeBot", codex_id, bot=False),
                    FakeChannel(int(ch_id), real_name), webhook_id=987654321)
    run(m, chan_map, SELF_ID)
    check("G Codex名義のwebhookは便にしない(名義だけでは通さない)", len(rows()) == before,
          f"{before} → {len(rows())}")

    # F: Codex専用部屋でのCodexの発言は取り込まない(responderが自分に答える輪) ---
    before = len(rows())
    codex_room = {"9001": {"id": "9001", "name": "ボスの部屋", "dept": "codex"}}
    m = FakeMessage(900000000000000006, "自室での回答",
                    FakeAuthor("Codex_SnakeBot", codex_id, bot=True),
                    FakeChannel(9001, "ボスの部屋"))
    run(m, codex_room, SELF_ID)
    check("F Codex専用部屋のボスの発言は便にしない(responderが自分の回答に答える輪)",
          len(rows()) == before, f"{before} → {len(rows())}")

    # H: 人の発言は1バイトも変わらない(回帰ゼロ) ---------------------------------
    m = FakeMessage(900000000000000007, "これは普通のChami便",
                    FakeAuthor("chami_fusoh", 490925528367497227, bot=False),
                    FakeChannel(int(ch_id), real_name))
    run(m, chan_map, SELF_ID)
    r = [x for x in rows() if x["msg_id"] == "900000000000000007"]
    check("H 人の発言は従来どおり便になる", len(r) == 1)
    if r:
        check("H2 人の便に from_codex を足さない(従来と同じ形)",
              "from_codex" not in r[0]["body"], f"body={list(r[0]['body'])}")

    # I: 人の@ボス召喚(往路)は無傷 ----------------------------------------------
    m = FakeMessage(900000000000000008, "@ボス これ見てくれ",
                    FakeAuthor("chami_fusoh", 490925528367497227, bot=False),
                    FakeChannel(int(ch_id), real_name))
    run(m, chan_map, SELF_ID)
    r = [x for x in rows() if x["msg_id"] == "900000000000000008"]
    check("I 人の@ボス召喚は今までどおり codex へ付け替わる(往路は無傷)",
          len(r) == 1 and r[0]["dept"] == "codex", f"r={r}")

    # J: 台帳外の部屋のCodex発言は従来どおり破棄 ---------------------------------
    before = len(rows())
    m = FakeMessage(900000000000000009, "台帳外の部屋での回答",
                    FakeAuthor("Codex_SnakeBot", codex_id, bot=True),
                    FakeChannel(9999, "知らない部屋"))
    run(m, chan_map, SELF_ID)
    check("J 台帳に無い部屋は従来どおり破棄(受信対象を広げない)", len(rows()) == before,
          f"{before} → {len(rows())}")

    # K: Codex便に印を押さない(Chami=「Claude側の既読とかは要らん」) -------------
    dg.ACTIVE_JOBS = True
    dg.sent_mark_for = lambda *a, **k: "\U0001F4EE"      # 絵文字の引き当ては外へ出る手
    m = FakeMessage(900000000000000010, "印の検査(ボス)",
                    FakeAuthor("Codex_SnakeBot", codex_id, bot=True),
                    FakeChannel(int(ch_id), real_name))
    run(m, chan_map, SELF_ID)
    check("K Codex便には印を押さない(足したのは配線であって既読ではない)",
          m.reactions_pressed == [], f"押した={m.reactions_pressed}")
    m2 = FakeMessage(900000000000000011, "印の検査(人)",
                     FakeAuthor("chami_fusoh", 490925528367497227, bot=False),
                     FakeChannel(int(ch_id), real_name))
    run(m2, chan_map, SELF_ID)
    check("K2 人の便の送信印は今までどおり押す(印の配線は壊していない)",
          m2.reactions_pressed == ["\U0001F4EE"], f"押した={m2.reactions_pressed}")
    dg.ACTIVE_JOBS = False

    # ---- 本番が1バイトも動いていないこと ---------------------------------------
    for p, before_st in PROD.items():
        check(f"Z 本番の実ファイルが不変({os.path.basename(p)})", _stat(p) == before_st,
              f"{before_st} → {_stat(p)}")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n結果: {PASS} PASS / {FAIL} FAIL" + (f"  (mutant={MUTANT})" if MUTANT else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        for _ext in ("", "c"):
            try:
                os.remove(_COPY + _ext)
            except OSError:
                pass
        shutil.rmtree(os.path.join(HERE, "__pycache__"), ignore_errors=True)
    sys.exit(rc)
