#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""discord_gateway の送信印(<:sendms:>)を**実行で**通す回帰試験 (2026-09-02 イージス研究室)。

★なぜ要るか (DEF-kaizen-analyst-917843c10e)
  2026-09-01、Chamiの画面から送信印が全部屋で消えた。押すコードは壊れていない。
  gatewayの on_message が沈黙し、便が relay_repair の回収経路だけで queue に入り、
  **その経路に印を押す口が無かった**のが真因だった(回収側は 00_AI-HQ 97c27c9 で塞ぎ、
  回帰試験 00_AI-HQ/scripts/test_relay_repair_sendmark.py が守っている)。
  だが**gateway 側の口には試験が1本も無い**。durability 系の改修で
  `await m.add_reaction(emoji)` が消えても・except に握り潰されても、
  誰も落ちない=また「反応はあるのに印だけ付かない」で気づくことになる。ここを塞ぐ。

★方針 (docs/departments/00_common/skills/test-must-fail)
  外へ出る手 (add_reaction) **だけ**偽物にし、判定・分岐・ゲート・fail-open は本物のまま
  on_message を実行で通す。ソース文字列一致では「別の呼び出し口が漏れる」型を捕まえられない。
  ACTIVE_JOBS / JOBS_DEPTS も差し替えず、一時 local/ の cutover.json から本物の経路で読ませる。

★__pycache__ の偽PASS対策= このファイルは discord_gateway.py を import せず
  compile()/exec() で読む。.pyc を一切掴まないので、変異と復帰でサイズが同じでも嘘をつかない。

使い方:
  python scripts/queue/test_gateway_sendmark.py              # 本物のソースで検査
  python scripts/queue/test_gateway_sendmark.py --mutate main    # 人間便の印を殺す→赤になるはず
  python scripts/queue/test_gateway_sendmark.py --mutate mirror  # ミラー便の印を殺す
  python scripts/queue/test_gateway_sendmark.py --mutate failopen  # 握り潰しを外す
  python scripts/queue/test_gateway_sendmark.py --mutate sendmsid  # Claude印のID照合を殺す
  python scripts/queue/test_gateway_sendmark.py --mutate sendmsanchor  # ID直撃を殺す
終了コード: 0=全PASS / 1=FAILあり / 2=変異が当たらなかった(試験自体が無効)
"""
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import types
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
GW_SRC = os.path.join(HERE, "discord_gateway.py")

CH_ID = "900000000000000001"      # 台帳に載っている部屋
CH_OUT = "900000000000000002"     # 台帳外の部屋 (押してはいけない)
CH_YUI = "900000000000000003"     # 優依の自室 (llm-growth)= 印を押してはいけない部屋
CH_IMG = "900000000000000004"     # LoRA画像部屋 (imagegen-fusoh-v0)= 「生成依頼」便だけ押さない

# --- 変異 (must-fail 用。実ファイルは書き換えない=常駐へ触れない) ------------------
MUTATIONS = {
    # 人間便の印を殺す
    "main": ('                await m.add_reaction(emoji)\n'
             '            except Exception as e:\n'
             '                log(f"送信印失敗',
             '                pass  # MUTANT\n'
             '            except Exception as e:\n'
             '                log(f"送信印失敗'),
    # Chamiミラー便の印を殺す
    "mirror": ('                    await m.add_reaction(emoji)\n'
               '                except Exception as e:\n'
               '                    log(f"ミラー送信印失敗',
               '                    pass  # MUTANT\n'
               '                except Exception as e:\n'
               '                    log(f"ミラー送信印失敗'),
    # 印が押せない時に配達ごと巻き添えにする (fail-open を壊す)
    "failopen": ('            except Exception as e:\n'
                 '                log(f"送信印失敗(配達は継続): {type(e).__name__}")',
                 '            except Exception:\n'
                 '                raise  # MUTANT'),
    # Codexの撃ち分けを殺す (2026-09-07 追加。再発時にここが赤くなる)
    # ★2026-09-16 引数が1つ増えた(content)ので狙いを「dept を渡す所」だけへ縮めた=
    #   以後も引数が増減して当たらなくなることがない。
    "codex": ('sent_mark_for(m.guild, rec["dept"], ',
              'sent_mark_for(m.guild, "",  # MUTANT\n                                      '),
    # ミラー便のCodex判定を殺す
    "codexmirror": ('and is_codex_mentioned(m.content or ""))\n'
                    '                              else str((chan_map.get(str(m.channel.id))',
                    'and False)  # MUTANT\n'
                    '                              else str((chan_map.get(str(m.channel.id))'),
    # ★2026-09-12 追加: 優依の部屋を「押さない側」から外す(=Claude印が優依へ付く再発)
    # ★2026-09-16 表の**中身**まで一致させていたので、imagetag が足された日に変異が当たらなく
    #   なっていた(実測: `--mutate yui` が「一致 0件」で rc=2)。must-fail の見張りが黙る型だ。
    #   → 変数名の頭だけを狙う= 部屋が増減しても当たり続ける(残りは MUTANT のコメントへ落ちる)。
    "yui": ('NO_SENT_MARK_DEPTS = ("llm-growth"',
            'NO_SENT_MARK_DEPTS = ()  # MUTANT ("llm-growth"'),
    # ミラー便だけ押さない判定を殺す (押下点が2つある型の再発。C-064=OUT口は全数同時)
    "yuimirror": ('                    if emoji is None:\n'
                  '                        return          # ★押さない部屋',
                  '                    if False:\n'
                  '                        return          # MUTANT ★押さない部屋'),
    # ★2026-09-16 追加: 「生成依頼」便の非押下を殺す(Chami直令 msg 1549650439178428447)
    "cue": ('    if _local_pipeline_order(dept, content):',
            '    if False:  # MUTANT'),
    # 生便の押下点が本文を渡さなくなる(dept しか見ない旧形へ戻る型の再発)
    "cuebody": ('emoji = sent_mark_for(m.guild, rec["dept"], rec.get("content") or "")',
                'emoji = sent_mark_for(m.guild, rec["dept"])  # MUTANT'),
    # ミラー便の押下点が本文を渡さなくなる (押下点が2つある型の再発。C-064)
    "cuemirror": ('emoji = sent_mark_for(m.guild, _mdept, m.content or "")',
                  'emoji = sent_mark_for(m.guild, _mdept)  # MUTANT'),
    # ★2026-09-20 追加: Claude印のID照合を殺す(実名照合だけへ戻る型=改称でまた📮へ落ちる)
    "sendmsid": ('        if eid and str(getattr(e, "id", "")) == str(eid):\n'
                 '            return e',
                 '        if False:  # MUTANT\n'
                 '            return e'),
    # ギルドを1件も引けない時のID直撃を殺す(照合が全滅した瞬間に📮へ落ちる旧形)
    "sendmsanchor": ('    if eid:                              # ③',
                     '    if False:  # MUTANT ③'),
}

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (name, extra))


# --- 偽物は「外へ出る手」だけ ------------------------------------------------------
class FakeEmoji:
    def __init__(self, name, eid):
        self.name, self.id = name, eid

    def __str__(self):
        return "<:%s:%s>" % (self.name, self.id)


class FakeAuthor:
    def __init__(self, name, uid, bot=False):
        self.name, self.id, self.bot = name, uid, bot


class FakeChannel:
    def __init__(self, cid, name):
        self.id, self.name = cid, name


class FakeGuild:
    def __init__(self, emojis):
        self.emojis = emojis


class FakeMsg:
    """discord.Message のうち on_message が実際に触る面だけ持つ。"""

    def __init__(self, mid, content, author, channel, guild,
                 webhook_id=None, boom=None):
        self.id = int(mid)
        self.content = content
        self.author = author
        self.channel = channel
        self.guild = guild
        self.webhook_id = webhook_id
        self.attachments = []
        self.reference = None
        self.created_at = datetime.now(timezone.utc)
        self.boom = boom
        self.pushed = []            # ★実際に渡った値をここへ集める

    async def add_reaction(self, emoji):
        self.pushed.append(emoji)
        if self.boom:
            raise self.boom


def load_gateway(tmp, mutate=None):
    """discord_gateway.py を一時 local/ 向けに読み込む (import しない=.pyc を掴まない)。"""
    src = open(GW_SRC, encoding="utf-8").read()
    if mutate:
        old, new = MUTATIONS[mutate]
        if src.count(old) != 1:
            print("変異 '%s' が当たらない (一致 %d件)。試験が古い=無効。"
                  % (mutate, src.count(old)))
            sys.exit(2)
        src = src.replace(old, new, 1)
        print("### 変異 '%s' を入れて走らせる (赤になるのが正しい) ###" % mutate)
    os.environ["GO5_LOCAL_DIR"] = os.path.join(tmp, "local")
    mod = types.ModuleType("dg_under_test")
    mod.__file__ = GW_SRC            # HERE/ROOT を本物と同じに解決させる
    exec(compile(src, GW_SRC, "exec"), mod.__dict__)
    return mod


def build_local(tmp):
    loc = os.path.join(tmp, "local")
    os.makedirs(os.path.join(loc, "queue"), exist_ok=True)
    # ★ゲートも本物の経路で読ませる (ACTIVE_JOBS を手で True にしない)
    json.dump({"gateway_jobs": "1", "gateway_jobs_depts": ""},
              open(os.path.join(loc, "queue", "cutover.json"), "w", encoding="utf-8"))
    json.dump([{"id": CH_ID, "name": "イージス研究室", "dept": "aegis-gl"},
               {"id": CH_YUI, "name": "ローカルllm成長進捗", "dept": "llm-growth"},
               {"id": CH_IMG, "name": "画像生成-fusoh-v0", "dept": "imagegen-fusoh-v0"}],
              open(os.path.join(loc, "discord_channels.json"), "w", encoding="utf-8"))
    open(os.path.join(loc, "discord_bot_token.txt"), "w", encoding="utf-8").write("DUMMY")
    # ★@ボス召喚を本物の経路で有効にする (2026-09-07)。手でフラグ変数を立てない=
    #   _codex_summon_on() が実ファイルを見る本来の判定のまま [6] を回すため。
    #   [1]〜[5] の本文には名指しが無いので、この札があっても既存の判定は1つも動かない。
    open(os.path.join(loc, "codex_enabled.txt"), "w", encoding="utf-8").write("1")
    return loc


def get_on_message(mod):
    """run_gateway() を接続直前まで走らせ、登録された on_message を取り出す。

    client.run を差し替えるだけ= ハンドラの登録も分岐も本物のまま。
    """
    import discord
    real_run = discord.Client.run
    holder = []
    discord.Client.run = lambda self, *a, **k: holder.append(self)
    try:
        rc = mod.run_gateway()
    finally:
        discord.Client.run = real_run
    if rc or not holder:
        print("run_gateway が接続前に落ちた (rc=%s)。試験が無効。" % rc)
        sys.exit(2)
    return getattr(holder[0], "on_message", None)


def queued(loc):
    con = sqlite3.connect(os.path.join(loc, "queue", "inbox.db"))
    rows = [str(r[0]) for r in con.execute("select msg_id from queue")]
    con.close()
    return rows


def queued_dept(loc, mid):
    """その便がどのdeptで入ったか。送信印の撃ち分けは**この札**を見て決まる(2026-09-07)。"""
    con = sqlite3.connect(os.path.join(loc, "queue", "inbox.db"))
    r = con.execute("select dept from queue where msg_id=?", (str(mid),)).fetchone()
    con.close()
    return str(r[0]) if r else ""


def main(argv):
    mutate = None
    if "--mutate" in argv:
        mutate = argv[argv.index("--mutate") + 1]
        if mutate not in MUTATIONS:
            print("変異名: %s" % " / ".join(MUTATIONS))
            return 2

    tmp = tempfile.mkdtemp(prefix="gw_sendmark_")
    try:
        loc = build_local(tmp)
        mod = load_gateway(tmp, mutate)
        check("0 cutover.jsonから本物の経路でjobsがONになっている", mod.ACTIVE_JOBS is True)
        on_message = get_on_message(mod)
        if on_message is None:
            print("on_message が登録されていない。試験が無効。")
            return 2

        sendms = FakeEmoji("sendms", 1527369203819085864)
        guild = FakeGuild([FakeEmoji("kidoku", 1), sendms, FakeEmoji("chakusyu", 2)])
        ch = FakeChannel(int(CH_ID), "イージス研究室")
        chami = FakeAuthor("chami", 111)

        # ---- [1] 人間の便: 届いた印が実際に押される ----
        print("[1] Chamiの生便 (gateway受信)")
        m = FakeMsg(1, "テスト便", chami, ch, guild)
        asyncio.run(on_message(m))
        check("1 add_reaction が1回呼ばれた", len(m.pushed) == 1, "-> %r" % (m.pushed,))
        check("1 渡ったのは guild の sendms そのもの", m.pushed[:1] == [sendms])
        check("1 便は queue に入っている", "1" in queued(loc))

        # ---- [2] Chamiミラー便 (webhook): 印だけ押す・enqueueしない ----
        print("[2] Chamiミラー便 (webhook)")
        mm = FakeMsg(2, "ミラー", FakeAuthor("Chami(main)", 222, bot=True), ch, guild,
                     webhook_id=777)
        asyncio.run(on_message(mm))
        check("2 ミラーにも印が押される", mm.pushed[:1] == [sendms], "-> %r" % (mm.pushed,))
        check("2 ミラーは queue に入れない", "2" not in queued(loc))

        # ---- [3] 押してはいけない相手 ----
        print("[3] 押さない側")
        mb = FakeMsg(3, "他のbotの発言", FakeAuthor("SomeBot", 333, bot=True), ch, guild)
        asyncio.run(on_message(mb))
        check("3 ただのbot発言には押さない", mb.pushed == [] and "3" not in queued(loc))

        mo = FakeMsg(4, "台帳外", chami, FakeChannel(int(CH_OUT), "よその部屋"), guild)
        asyncio.run(on_message(mo))
        check("3 台帳外chには押さない", mo.pushed == [] and "4" not in queued(loc))

        # ---- [4] 絵文字が見つからない時の退避 ----
        print("[4] 絵文字の解決")
        old_name = FakeEmoji("送信", 999)
        m5 = FakeMsg(5, "旧名だけある鯖", chami, ch, FakeGuild([old_name]))
        asyncio.run(on_message(m5))
        check("4 sendmsが無ければ旧名『送信』へ", m5.pushed[:1] == [old_name])

        # ★2026-09-20 改訂(DISPATCH-aegis-gl-1789904135462)= ギルドの実名照合が全滅しても
        #   📮へは落ちない。送信印は確定IDを持つので Codex印と同じくID直撃で custom を撃つ。
        #   旧期待値は「どちらも無ければ📮」だったが、その形のままだと**実名を変えただけで
        #   印が消える**(実物= sendms → Send_MS 改称で全部屋が📮になった)。
        m6 = FakeMsg(6, "カスタム絵文字が無い鯖", chami, ch, FakeGuild([]))
        asyncio.run(on_message(m6))
        check("4 実名が1つも引けなくてもIDアンカーで撃つ",
              m6.pushed[:1] == ["sendms:1527369203819085864"], "-> %r" % (m6.pushed,))
        check("4 引けない時も📮へは落ちない", "\U0001F4EE" not in m6.pushed)

        # 📮が残るのは「**IDもギルド実名も無い印**」だけ= 送信印からIDを抜いて実行で示す。
        _keep_id = dict(mod._REACT_ID)
        try:
            mod._REACT_ID = {}
            m6b = FakeMsg(61, "IDも実名も無い鯖", chami, ch, FakeGuild([]))
            asyncio.run(on_message(m6b))
            check("4 IDもギルド実名も無い時だけ📮へ退避",
                  m6b.pushed[:1] == ["\U0001F4EE"], "-> %r" % (m6b.pushed,))
        finally:
            mod._REACT_ID = _keep_id
        check("4 後始末: 送信印のIDを戻した",
              mod._REACT_ID.get("送信") == "1527369203819085864")

        # ---- [5] fail-open: 押せなくても配達は死なない ----
        print("[5] 押せない時 (fail-open)")
        m7 = FakeMsg(7, "権限が無い部屋", chami, ch, guild,
                     boom=RuntimeError("Missing Permissions"))
        try:
            asyncio.run(on_message(m7))
            check("5 add_reactionが落ちても例外を外に出さない", True)
        except Exception as e:
            check("5 add_reactionが落ちても例外を外に出さない", False,
                  "-> %s が受信経路の外へ出た" % type(e).__name__)
        check("5 印が押せなくても便は queue に入っている", "7" in queued(loc))

        # ---- [6] Codex宛の配達= 送信印は Send_MS_Boss(Codex印) ----
        # ★研究室HQ 配線依頼 msg 1546348202960093225 の回帰。壊れた実物は
        #   「送信=sendms(Claude印) と 既読=‼️/着手=🐍(Codex印) が同じ1通に同居」。
        #   ここは判定(is_codex_mentioned→route_codex_summon→dept)を全部本物で回し、
        #   add_reaction に**実際に渡った値**だけを見る(ソース文字列一致では捕まらない型)。
        # ★2026-09-20 差し替え= Codex送信印 uptsukiyomi → Send_MS_Boss
        #   (Chami直命 msg 1551219293058768959 / 発注 改善提案部門 msg 1551220560619503711)。
        #   uptsukiyomi は §E「月詠みアップ済」の本来意味へ戻った=ここで撃ったら回帰。
        print("[6] Codex宛の配達 (@ボス召喚)")
        boss_ms = FakeEmoji("Send_MS_Boss", 1551219696743878756)  # ★作り直し後の生きたID
        upt = FakeEmoji("uptsukiyomi", 1522060098355069139)      # 旧印(押さなくなった側)
        gc = FakeGuild([FakeEmoji("kidoku", 1), sendms, FakeEmoji("chakusyu", 2), upt, boss_ms])
        m8 = FakeMsg(8, "@ボス これ見てくれ", chami, ch, gc)
        asyncio.run(on_message(m8))
        check("6 送信印は Send_MS_Boss(Codex印)", m8.pushed[:1] == [boss_ms], "-> %r" % (m8.pushed,))
        check("6 旧印(uptsukiyomi)はもう押されていない", upt not in m8.pushed)
        check("6 Claude印(sendms)は押されていない", sendms not in m8.pushed)
        check("6 便は dept=codex で queue に入っている", queued_dept(loc, "8") == "codex",
              "-> %r" % (queued_dept(loc, "8"),))

        # 召喚されていない普通の便は今までどおり sendms (撃ち分けが逆流していないこと)
        m9 = FakeMsg(9, "ボスの話をしただけの便", chami, ch, gc)
        asyncio.run(on_message(m9))
        check("6 名指しでない便は従来どおり sendms", m9.pushed[:1] == [sendms],
              "-> %r" % (m9.pushed,))

        # ギルドに Send_MS_Boss が無くても Claude印へは落ちない (react.pyのIDアンカーと同じ)
        m10 = FakeMsg(10, "@スネーク たのむ", chami, ch, FakeGuild([sendms]))
        asyncio.run(on_message(m10))
        check("6 Send_MS_Bossが引けなくてもIDアンカーで撃つ",
              m10.pushed[:1] == ["Send_MS_Boss:1551219696743878756"], "-> %r" % (m10.pushed,))
        check("6 引けない時もsendms/📮へは落ちない",
              sendms not in m10.pushed and "\U0001F4EE" not in m10.pushed)

        # Chamiミラー便も同じ判定 (押下点が2つあるので両方見る)
        mmc = FakeMsg(11, "@ボス 確認して", FakeAuthor("Chami(main)", 222, bot=True), ch, gc,
                      webhook_id=777)
        asyncio.run(on_message(mmc))
        check("6 ミラー便のCodex召喚にも Send_MS_Boss", mmc.pushed[:1] == [boss_ms],
              "-> %r" % (mmc.pushed,))

        # ---- [7] 優依の部屋= 送信印を押さない (Chami直接指示 2026-09-12) ----
        # ★原文=「優依に送った時には <:sendms:…> の絵文字スタンプつけないようにしてよ、
        #   あれClaude専用の処理だから」(llm-edu msg 1548006584809168931 01:25:30)。
        #   sendms は「司令塔の処理系に乗った」印で、優依はその処理系に乗らない=
        #   押すと**乗っていない経路に乗った印**という嘘が Chami の画面に残る。
        #   押下点は2つ(生便・Chamiミラー)。C-064=OUT口は全数同時に見る。
        print("[7] 優依の部屋 (llm-growth)= 印を押さない")
        chy = FakeChannel(int(CH_YUI), "ローカルllm成長進捗")
        m12 = FakeMsg(12, "優依、元気?", chami, chy, guild)
        asyncio.run(on_message(m12))
        check("7 優依への生便には印を押さない", m12.pushed == [], "-> %r" % (m12.pushed,))
        check("7 印は押さなくても便は queue に入っている", "12" in queued(loc))
        check("7 便は dept=llm-growth で入っている", queued_dept(loc, "12") == "llm-growth",
              "-> %r" % (queued_dept(loc, "12"),))

        m13 = FakeMsg(13, "優依へのミラー", FakeAuthor("Chami(main)", 222, bot=True), chy, guild,
                      webhook_id=777)
        asyncio.run(on_message(m13))
        check("7 優依へのミラー便にも印を押さない", m13.pushed == [], "-> %r" % (m13.pushed,))

        # 他の部屋は今までどおり= 「押さない」が全部屋へ漏れていないこと (C-035)
        m14 = FakeMsg(14, "こっちは普通の部屋", chami, ch, guild)
        asyncio.run(on_message(m14))
        check("7 他の部屋は従来どおり sendms", m14.pushed[:1] == [sendms], "-> %r" % (m14.pushed,))
        m15 = FakeMsg(15, "他部屋のミラー", FakeAuthor("Chami(main)", 222, bot=True), ch, guild,
                      webhook_id=777)
        asyncio.run(on_message(m15))
        check("7 他の部屋のミラーも従来どおり sendms", m15.pushed[:1] == [sendms],
              "-> %r" % (m15.pushed,))

        # ---- [8] 「生成依頼」便= 印を押さない (Chami直接指示 2026-09-16) ----
        # ★原文=「生成依頼 から始まった時は画像生成だから、Claud送信用の各種スタンプを
        #   押さないで」(hq msg 1549650439178428447)。LoRA部屋の絵を描くのは優依の
        #   ローカル経路で、Claudeはその処理系に乗らない= [7]と同じ嘘になる。
        #   ★違いは**部屋ごとではなく便ごと**だという点。同じ部屋の雑談には従来どおり押す。
        print("[8] 「生成依頼」便 (LoRA部屋)= 印を押さない")
        chi = FakeChannel(int(CH_IMG), "画像生成-fusoh-v0")
        m16 = FakeMsg(16, "生成依頼 銀髪ロング 制服 桜", chami, chi, guild)
        asyncio.run(on_message(m16))
        check("8 「生成依頼」で始まる便には印を押さない", m16.pushed == [], "-> %r" % (m16.pushed,))
        check("8 印は押さなくても便は queue に入っている", "16" in queued(loc))
        check("8 便は dept=imagegen-fusoh-v0 で入っている",
              queued_dept(loc, "16") == "imagegen-fusoh-v0", "-> %r" % (queued_dept(loc, "16"),))

        m17 = FakeMsg(17, "生成依頼\n\n猫耳", FakeAuthor("Chami(main)", 222, bot=True), chi, guild,
                      webhook_id=777)
        asyncio.run(on_message(m17))
        check("8 ミラー便の「生成依頼」にも押さない", m17.pushed == [], "-> %r" % (m17.pushed,))

        # 同じ部屋の雑談は従来どおり押す (「部屋ごと」へ広がっていないこと)
        m18 = FakeMsg(18, "この絵いいね", chami, chi, guild)
        asyncio.run(on_message(m18))
        check("8 同じ部屋でも雑談には従来どおり sendms", m18.pushed[:1] == [sendms],
              "-> %r" % (m18.pushed,))

        # 合図の要らない部屋へ漏れていないこと (C-035)
        m19 = FakeMsg(19, "生成依頼 これは画像部屋ではない", chami, ch, guild)
        asyncio.run(on_message(m19))
        check("8 LoRA部屋以外では合図語があっても従来どおり sendms",
              m19.pushed[:1] == [sendms], "-> %r" % (m19.pushed,))

        # ---- [9] ギルド実名の改称に耐える (2026-09-20 DISPATCH-aegis-gl-1789904135462) ----
        # ★壊れた実物= Chamiがギルド絵文字の実名を sendms → Send_MS へ改称した
        #   (id 1527369203819085864 は不変)。Claude印だけ実名照合しか持たず📮へ落ちた
        #   (msg 1551193260301746318「なんで<:Send_MS:>じゃないんや」)。Codex印はID照合を
        #   持っていたので無傷= **非対称そのものが不具合**。ここはその非対称の再発を止める。
        print("[9] ギルド実名の改称 (sendms → Send_MS)")
        newname = FakeEmoji("Send_MS", 1527369203819085864)      # 実名だけ変わった現物
        gr = FakeGuild([FakeEmoji("kidoku", 1), newname, FakeEmoji("chakusyu", 2)])
        m20 = FakeMsg(20, "改称後の鯖", chami, ch, gr)
        asyncio.run(on_message(m20))
        check("9 実名がSend_MSでもID一致で送信印を撃つ", m20.pushed[:1] == [newname],
              "-> %r" % (m20.pushed,))
        check("9 改称では📮へ落ちない", "\U0001F4EE" not in m20.pushed)

        m21 = FakeMsg(21, "改称後のミラー", FakeAuthor("Chami(main)", 222, bot=True), ch, gr,
                      webhook_id=777)
        asyncio.run(on_message(m21))
        check("9 ミラー便も改称に耐える", m21.pushed[:1] == [newname], "-> %r" % (m21.pushed,))

        # 実名を**もう一度**別名へ変えても、IDが在る限り撃てる(改名を追いかける運用を作らない)
        another = FakeEmoji("zzz_whatever", 1527369203819085864)
        m22 = FakeMsg(22, "また改称された鯖", chami, ch, FakeGuild([another]))
        asyncio.run(on_message(m22))
        check("9 さらに改名してもIDが在れば撃てる", m22.pushed[:1] == [another],
              "-> %r" % (m22.pushed,))

        # 改称耐性がCodex側を侵していないこと(ID一致の枝を足しただけ=撃ち分けは不変)
        m23 = FakeMsg(23, "@ボス 改称後に召喚", chami, ch,
                      FakeGuild([newname, FakeEmoji("Send_MS_Boss", 1551219696743878756)]))
        asyncio.run(on_message(m23))
        check("9 Codex便は改称後も Send_MS_Boss のまま",
              bool(m23.pushed) and getattr(m23.pushed[0], "name", "") == "Send_MS_Boss",
              "-> %r" % (m23.pushed,))
        check("9 Codex便にClaude印(Send_MS)は混ざらない", newname not in m23.pushed)

        print("\n%d PASS / %d FAIL" % (PASS, FAIL))
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
