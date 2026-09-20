# -*- coding: utf-8 -*-
"""ボス(Codex)の送信印が新カスタム Send_MS_Boss で撃たれ、旧 uptsukiyomi は**読む側だけ**に
残っていることの検査(2026-09-20 イージス研究室)。

発注= 改善提案部門(トトリ)msg 1551220560619503711。芯=
  【Chami直命】msg 1551219293058768959
  「これ、ボスに送った時の送信スタンプね。今まで <:uptsukiyomi:1522060098355069139> だったから
    これからはこれに置き換えて」→ 新規カスタム <:Send_MS_Boss:1551218921170927649>。
意味・種別の正本= `00_AI-HQ/docs/departments/kaizen-analyst/絵文字管理台帳.md` §A.1(送信Codex列)。
当室は配線だけ(C-015)。uptsukiyomi は §E「月詠みアップ済」の本来意味へ戻る。

受け入れ条件(依頼原文)
  (a) Codex宛便で Send_MS_Boss が付く
  (b) 実名を改称されてもID直撃で当たり、📮へ落ちない
  (c) 読み側(audit_marks)が旧 uptsukiyomi を「Codex送信印」として認識し続ける
      = 2026-09-05〜09-20 の過去便が一斉に「生存印なし」へ落ちない

★ソースの文字列一致では見ない(C-053)= **本物の resolve_emoji / sent_mark_for を実行して**
  返り値を読む。偽物にするのは「外へ出る手」= react.api(Discordへの GET)だけ。
  gateway は import せず compile()/exec() で読む(__pycache__ の偽PASS対策)。

  python scripts/discord/test_send_ms_boss.py
  python scripts/discord/test_send_ms_boss.py --mutant old        # 既定を uptsukiyomi のまま
  python scripts/discord/test_send_ms_boss.py --mutant nameonly   # 名前照合だけへ戻す
  python scripts/discord/test_send_ms_boss.py --mutant noretired  # 退役棚を空にする
終了コード: 0=全PASS / 1=FAILあり / 2=変異が当たらなかった(試験自体が無効)
"""
import json
import os
import sys
import tempfile
import types
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # scripts/
GW_SRC = os.path.join(ROOT, "queue", "discord_gateway.py")
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import react                                        # noqa: E402

_fails = []
_ran = []          # ★合計は数えた実物で出す(手で TOTAL を書くとズレる)

BOSS_NAME = "Send_MS_Boss"
BOSS_ID = "1551218921170927649"
OLD_NAME = "uptsukiyomi"                            # 2026-09-05〜09-20 の Codex送信印(退役)
OLD_ID = "1522060098355069139"
CLAUDE_NAME = "sendms"                              # Claude側の送信印(触らない)
CLAUDE_ID = "1527369203819085864"
GID = "1525646154933735424"
CID = "1525646154933735425"
MAILBOX = "\U0001F4EE"                              # 📮= 落ちてはいけない退避先

GUILD_EMOJIS = [
    {"name": "chakusyu", "id": "1527252032308908172"},
    {"name": "kidoku", "id": "1527252197597777971"},
    {"name": CLAUDE_NAME, "id": CLAUDE_ID},
    {"name": OLD_NAME, "id": OLD_ID},               # ★ギルドには残る(§E の本来意味で使う)
    {"name": "Chakusyu_Boss", "id": "1551192017495785492"},
    {"name": BOSS_NAME, "id": BOSS_ID},             # ★Chamiが2026-09-20に作った新素材
]

# --- gateway 側の変異(実ファイルは書き換えない=常駐へ触れない) --------------------
GW_MUTATIONS = {
    # 名前照合だけへ戻す= ①ID一致を外し、引けない時は📮へ落とす旧形
    "nameonly": [
        ('        for e in emojis:                 # ①ID一致(実名を改称されても当たる)\n'
         '            if eid and str(getattr(e, "id", "")) == str(eid):\n'
         '                return e\n',
         '        # MUTANT ①ID一致を外した(実名照合だけ)\n'),
        ('        return f"{name}:{eid}" if eid else name',
         '        return SENT_MARK_FALLBACK  # MUTANT ID直撃をやめて📮へ'),
    ],
}


def ok(cond, name):
    print(("  OK  " if cond else "  NG  ") + name)
    _ran.append(name)
    if not cond:
        _fails.append(name)


def fake_api(emojis=GUILD_EMOJIS, guild_ok=True):
    """外へ出る手だけを差し替える。呼ばれた経路は calls に残して後で読む。"""
    calls = []

    def _api(path, token, method="GET", timeout=20, tries=3):
        calls.append((method, path))
        if path.startswith("/channels/") and "/messages/" not in path:
            return {"guild_id": GID} if guild_ok else None
        if path.endswith("/emojis"):
            return emojis
        return None
    return _api, calls


# --- gateway(押下点その2)を import せずに読む -------------------------------------
class FakeEmoji:
    def __init__(self, name, eid):
        self.name, self.id = name, eid

    def __repr__(self):
        return "<:%s:%s>" % (self.name, self.id)


class FakeGuild:
    def __init__(self, emojis):
        self.emojis = emojis


def load_gateway(tmp, mutant=None):
    src = open(GW_SRC, encoding="utf-8").read()
    for old, new in GW_MUTATIONS.get(mutant or "", []):
        if src.count(old) != 1:
            print("変異 '%s' が当たらない (一致 %d件)。試験が古い=無効。" % (mutant, src.count(old)))
            sys.exit(2)
        src = src.replace(old, new, 1)
    loc = os.path.join(tmp, "local")
    os.makedirs(os.path.join(loc, "queue"), exist_ok=True)
    json.dump({"gateway_jobs": "0", "gateway_jobs_depts": ""},
              open(os.path.join(loc, "queue", "cutover.json"), "w", encoding="utf-8"))
    json.dump([], open(os.path.join(loc, "discord_channels.json"), "w", encoding="utf-8"))
    open(os.path.join(loc, "discord_bot_token.txt"), "w", encoding="utf-8").write("DUMMY")
    os.environ["GO5_LOCAL_DIR"] = loc
    mod = types.ModuleType("dg_under_test")
    mod.__file__ = GW_SRC                            # HERE/ROOT を本物と同じに解決させる
    exec(compile(src, GW_SRC, "exec"), mod.__dict__)
    return mod


def run(gw):
    # --- A 受け入れ条件(a)= Codexの送信は Send_MS_Boss を撃つ(押下点1= react.py) -----
    react.api, calls = fake_api()
    got = react.resolve_emoji("tok", CID, "送信", codex=True)
    ok(got == f"{BOSS_NAME}:{BOSS_ID}",
       "A-1 受け入れ条件(a)= codex=True の送信は %s:%s(実測 %s)" % (BOSS_NAME, BOSS_ID, got))
    ok(("GET", f"/guilds/{GID}/emojis") in calls,
       "A-2 実名照合の経路を本当に通っている(ギルド絵文字を引きに行った)")
    ok(OLD_NAME not in got, "A-3 旧印(uptsukiyomi)は返り値に1文字も残っていない")
    ok(urllib.parse.quote(got) == f"{BOSS_NAME}%3A{BOSS_ID}",
       "A-4 main() が撃つ形へURL化できる= <:%s:%s> のリアクションになる" % (BOSS_NAME, BOSS_ID))

    # --- B 受け入れ条件(b)= 実名を改称されてもID直撃・📮へ落ちない --------------------
    renamed = [{"name": "zzz_renamed", "id": BOSS_ID}]      # idは不変・実名だけ変わった現物
    react.api, _ = fake_api(emojis=renamed)
    got = react.resolve_emoji("tok", CID, "送信", codex=True)
    ok(got == f"{BOSS_NAME}:{BOSS_ID}",
       "B-1 受け入れ条件(b)= 実名を改称されてもIDで custom を撃つ(実測 %s)" % got)
    react.api, _ = fake_api(emojis=[])                      # ギルドに1件も引けない状況
    got = react.resolve_emoji("tok", CID, "送信", codex=True)
    ok(got == f"{BOSS_NAME}:{BOSS_ID}",
       "B-2 実名照合が0件でもIDで custom を撃つ(実測 %s)" % got)
    ok(MAILBOX not in got and OLD_NAME not in got, "B-3 📮へも旧印へも落ちていない")
    react.api, _ = fake_api(guild_ok=False)                 # チャンネルすら引けない(API全落ち)
    got = react.resolve_emoji("tok", CID, "送信", codex=True)
    ok(got == f"{BOSS_NAME}:{BOSS_ID}",
       "B-4 API全落ちでもIDで custom を撃つ=unicodeへ劣化しない(実測 %s)" % got)

    # --- C 回帰= Claude側の送信印は1文字も動かない ------------------------------------
    react.api, _ = fake_api()
    got = react.resolve_emoji("tok", CID, "送信", codex=False)
    ok(got == f"{CLAUDE_NAME}:{CLAUDE_ID}",
       "C-1 codex=False の送信は sendms:%s のまま(実測 %s)" % (CLAUDE_ID, got))
    ok(BOSS_NAME not in got, "C-2 Claude側へ Send_MS_Boss が漏れていない")
    ok(react.resolve_emoji("tok", CID, "着手", codex=True) == "Chakusyu_Boss:1551192017495785492",
       "C-3 着手(Codex)は Chakusyu_Boss のまま=送信の差し替えが他印へ漏れていない")
    ok(react.resolve_emoji("tok", CID, "既読", codex=True) == "‼️",
       "C-4 既読(Codex)は ‼️ のまま")
    ok(set(react.CODEX_OVERRIDE) == {"送信", "既読", "着手"},
       "C-5 差し替えるのは3印だけ=印を増やしていない(実測 %s)" % sorted(react.CODEX_OVERRIDE))

    # --- D 押下点その2= gateway の配達時(sent_mark_for)。同じ答を出すこと -------------
    guild = FakeGuild([FakeEmoji("kidoku", 1), FakeEmoji(CLAUDE_NAME, int(CLAUDE_ID)),
                       FakeEmoji(OLD_NAME, int(OLD_ID)), FakeEmoji(BOSS_NAME, int(BOSS_ID))])
    got = gw.sent_mark_for(guild, "codex")
    ok(getattr(got, "name", "") == BOSS_NAME,
       "D-1 受け入れ条件(a)= dept=codex の配達は %s(実測 %r)" % (BOSS_NAME, got))
    ok(getattr(got, "name", "") != OLD_NAME, "D-2 旧印(uptsukiyomi)はもう押されない")

    ren = FakeEmoji("zzz_renamed", int(BOSS_ID))
    got = gw.sent_mark_for(FakeGuild([ren]), "codex")
    ok(got is ren, "D-3 受け入れ条件(b)= 実名を改称されてもID一致で同じ絵文字を撃つ(実測 %r)" % (got,))

    got = gw.sent_mark_for(FakeGuild([]), "codex")
    ok(got == f"{BOSS_NAME}:{BOSS_ID}",
       "D-4 ギルドを1件も引けなくてもID直撃で custom を撃つ(実測 %r)" % (got,))
    ok(got != MAILBOX, "D-5 📮へ落ちない(Codex便にClaudeの退避印を出さない)")

    got = gw.sent_mark_for(FakeGuild([FakeEmoji(OLD_NAME, int(OLD_ID))]), "codex")
    ok(getattr(got, "name", got) != OLD_NAME,
       "D-6 鯖に旧印が残っていても拾い直さない(実測 %r)" % (got,))

    got = gw.sent_mark_for(guild, "aegis-gl")
    ok(getattr(got, "name", "") == CLAUDE_NAME,
       "D-7 回帰= Codex以外の便は sendms のまま(実測 %r)" % (got,))

    # --- E 受け入れ条件(c)= 読む側は旧印を「送信」として読み続ける ---------------------
    #   ★差し替えた瞬間、過去の@ボス便に付いた uptsukiyomi を audit_marks が読めなくなると
    #     2026-09-09 の「生存印なし」誤報9件と同じ形が戻る(A1を測る唯一の器)。
    import audit_marks as am                         # noqa: E402
    am.MARKS = am._build_marks()                     # ★変異を入れた時も本物の組み立てを通す
    past = {"reactions": [{"emoji": {"name": OLD_NAME, "id": OLD_ID}}]}
    now = {"reactions": [{"emoji": {"name": BOSS_NAME, "id": BOSS_ID}}]}
    other = {"reactions": [{"emoji": {"name": "kaiaku", "id": "1541110670748156014"}}]}
    ok("送信" in am.marks_on(past),
       "E-1 受け入れ条件(c)= 旧 uptsukiyomi の過去便を「送信」と読む(実測 %s)"
       % (sorted(am.marks_on(past)) or "なし"))
    ok("送信" in am.marks_on(now),
       "E-2 新 Send_MS_Boss の便も「送信」と読む(実測 %s)" % (sorted(am.marks_on(now)) or "なし"))
    ok("送信" not in am.marks_on(other),
       "E-3 無関係な印を送信と読まない(誤報の逆=取りこぼしの逆も見る)")
    ok(BOSS_NAME in am.MARKS["送信"] and OLD_NAME in am.MARKS["送信"],
       "E-4 送信の別名に新旧が両方入っている(実測 %s)" % (am.MARKS["送信"],))
    ok(react.CODEX_RETIRED.get("送信") == [(OLD_NAME, OLD_ID)],
       "E-5 退役棚に旧印が畳まれている=消さずに退避(C-003)(実測 %s)"
       % (react.CODEX_RETIRED.get("送信"),))

    return not _fails


def mutate(which):
    """★動く別の実装へ変異させて赤を実測する(C-053)。gateway側は load_gateway が担う。"""
    if which == "old":                              # 既定を uptsukiyomi のまま=差し替え忘れ
        react.CODEX_OVERRIDE["送信"] = (OLD_NAME, OLD_ID)
    elif which == "nameonly":                       # 名前照合だけへ戻す(IDアンカーを捨てる)
        react.CODEX_OVERRIDE["送信"] = (BOSS_NAME, None)
    elif which == "noretired":                      # 退役棚を空にする=過去便が読めなくなる
        react.CODEX_RETIRED = {}
    else:
        print("未知の変異体: " + which)
        sys.exit(2)
    print("★変異体 '%s' で同じ検査を流す(赤になるのが正しい)" % which)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mut = None
    if "--mutant" in sys.argv:
        mut = sys.argv[sys.argv.index("--mutant") + 1]
        mutate(mut)
    tmp = tempfile.mkdtemp(prefix="sendmsboss_")
    try:
        good = run(load_gateway(tmp, mut))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print(("PASS ボスの送信印=Send_MS_Boss %d/%d" % (len(_ran) - len(_fails), len(_ran)))
          if good else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
