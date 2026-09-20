# -*- coding: utf-8 -*-
"""ボス(Codex)の着手印が新カスタム Chakusyu_Boss で撃たれることの検査(2026-09-20 イージス研究室)。

発注= 改善提案部門 `DISPATCH-aegis-gl-1789903692537`。原文の芯=
  「CODEX_OVERRIDE の着手を 🐍 → <:Chakusyu_Boss:1551192017495785492> へ差し替え」
  「対象は『着手』の Codex分岐だけ。既読‼️/送信uptsukiyomi と Claude側の chakusyu は触らない」
意味・種別の正本= `00_AI-HQ/docs/departments/kaizen-analyst/絵文字管理台帳.md` §A.1(着手Codex列)。
当室は配線だけ(C-015)。

★ソースの文字列一致では見ない(C-053)= **本物の resolve_emoji を実行して**返り値を読む。
  偽物にするのは「外へ出る手」= react.api(Discordへの GET)だけ。
  分岐(codex/名前/ID経路/fail-open)は全部本物を通す。

  python scripts/discord/test_react_codex_chakusyu.py
  python scripts/discord/test_react_codex_chakusyu.py --mutant snake   # 🐍へ戻すと赤になる
"""
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import react                                        # noqa: E402

_fails = []
_ran = []          # ★合計は数えた実物で出す(手で TOTAL を書くとズレる)

BOSS_NAME = "Chakusyu_Boss"
BOSS_ID = "1551192017495785492"
CLAUDE_ID = "1527252032308908172"                   # Claude側の着手 chakusyu(触らない)
GID = "1525646154933735424"
CID = "1525646154933735425"

# ギルドに実在する絵文字一式(GET /guilds/<gid>/emojis の返しと同じ形)。
GUILD_EMOJIS = [
    {"name": "chakusyu", "id": CLAUDE_ID},
    {"name": "kidoku", "id": "1527252197597777971"},
    {"name": "sendms", "id": "1527369203819085864"},
    {"name": "uptsukiyomi", "id": "1522060098355069139"},
    {"name": "saihatsu", "id": "1531748428827201772"},
    {"name": "kaiaku", "id": "1541110670748156014"},
    {"name": BOSS_NAME, "id": BOSS_ID},             # ★Chamiが2026-09-20に作った新素材
    {"name": "Send_MS_Boss", "id": "1551218921170927649"},   # ★同日夜に作った送信印(Codex専用)
]


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


def run():
    # --- A 受け入れ条件1= Codexの着手は Chakusyu_Boss を撃つ --------------------------
    react.api, calls = fake_api()
    got = react.resolve_emoji("tok", CID, "着手", codex=True)
    ok(got == f"{BOSS_NAME}:{BOSS_ID}",
       "A-1 受け入れ条件1= codex=True の着手は %s:%s(実測 %s)" % (BOSS_NAME, BOSS_ID, got))
    ok(("GET", f"/guilds/{GID}/emojis") in calls,
       "A-2 実名照合の経路を本当に通っている(ギルド絵文字を引きに行った)")
    ok("🐍" not in got, "A-3 🐍(unicode代用)は1文字も残っていない")
    ok(urllib.parse.quote(got) == f"{BOSS_NAME}%3A{BOSS_ID}",
       "A-4 main() が撃つ形へURL化できる= <:%s:%s> のリアクションになる" % (BOSS_NAME, BOSS_ID))

    # --- B ID経路(実名照合が外れても劣化しない= sendms/uptsukiyomi と同型) ------------
    react.api, _ = fake_api(emojis=[])              # ギルドに1件も引けない状況
    got = react.resolve_emoji("tok", CID, "着手", codex=True)
    ok(got == f"{BOSS_NAME}:{BOSS_ID}",
       "B-1 実名照合が0件でもIDで custom を撃つ(実測 %s)" % got)
    react.api, _ = fake_api(guild_ok=False)         # チャンネルすら引けない(API全落ち)
    got = react.resolve_emoji("tok", CID, "着手", codex=True)
    ok(got == f"{BOSS_NAME}:{BOSS_ID}",
       "B-2 API全落ちでもIDで custom を撃つ=unicodeへ劣化しない(実測 %s)" % got)

    # --- C 受け入れ条件2= Claude側の着手は従来どおり(回帰) ---------------------------
    react.api, _ = fake_api()
    got = react.resolve_emoji("tok", CID, "着手", codex=False)
    ok(got == f"chakusyu:{CLAUDE_ID}",
       "C-1 受け入れ条件2= codex=False の着手は chakusyu:%s のまま(実測 %s)" % (CLAUDE_ID, got))
    ok(BOSS_NAME not in got, "C-2 Claude側へ Chakusyu_Boss が漏れていない")
    react.api, _ = fake_api(emojis=[])
    ok(react.resolve_emoji("tok", CID, "着手", codex=False) == f"chakusyu:{CLAUDE_ID}",
       "C-3 照合0件でも Claude側はID経路で chakusyu のまま")

    # --- D 触っていない印(既読/送信/他)が1文字も変わっていない ------------------------
    react.api, _ = fake_api()
    ok(react.resolve_emoji("tok", CID, "既読", codex=True) == "‼️",
       "D-1 Codexの既読は ‼️ のまま(unicode直撃)")
    ok(react.resolve_emoji("tok", CID, "送信", codex=True) == "Send_MS_Boss:1551218921170927649",
       "D-2 Codexの送信は Send_MS_Boss(2026-09-20 に uptsukiyomi から差し替え)")
    ok(react.resolve_emoji("tok", CID, "既読", codex=False) == "kidoku:1527252197597777971",
       "D-3 Claudeの既読は kidoku のまま")
    ok(react.resolve_emoji("tok", CID, "送信", codex=False) == "sendms:1527369203819085864",
       "D-4 Claudeの送信は sendms のまま")
    ok(react.resolve_emoji("tok", CID, "再発", codex=True) == "saihatsu:1531748428827201772",
       "D-5 再発は Codex受信でも共通(C-035=3印以外へ広げない)")
    ok(react.resolve_emoji("tok", CID, "改悪", codex=True) == "kaiaku:1541110670748156014",
       "D-6 改悪は Codex受信でも共通")
    ok(react.resolve_emoji("tok", CID, "即答", codex=True) == "💬",
       "D-7 即答はギルド素材が無いので fail-open の💬のまま(Codexでも同じ)")
    ok(set(react.CODEX_OVERRIDE) == {"送信", "既読", "着手"},
       "D-8 差し替えるのは3印だけ=印を増やしていない(実測 %s)" % sorted(react.CODEX_OVERRIDE))

    # --- E 巡回側(reaction_watch)への波及 ----------------------------------------------
    #   ★machine_marks() が読むのは react.ALIAS と react.FALLBACK だけ=CODEX_OVERRIDE は読まない。
    #     よって新名 Chakusyu_Boss は機械印の集合へ入らない(既存の鳴り方を増やさない)。
    #   ★既存衝突 ['saihatsu','kaiaku'] は react.ALIAS へ再発/改悪が入った 2026-09-04 以来のもので、
    #     この差し替えとは無関係(main() は警告だけ出して巡回を止めない=2026-09-09の判断)。
    import reaction_watch as rw                     # noqa: E402
    marks = rw.machine_marks()
    conf = rw.watch_conflicts(marks)
    ok(BOSS_NAME not in marks,
       "E-1 Chakusyu_Boss は機械印の集合へ入らない(machine_marks は CODEX_OVERRIDE を読まない)")
    ok(BOSS_NAME not in conf,
       "E-2 Chakusyu_Boss は WATCH と衝突しない(実測の既存衝突= %s)" % (conf or "なし"))
    ok("chakusyu" in marks and "着手" in marks,
       "E-3 従来の着手(chakusyu/着手)は機械印のまま=巡回の除外が壊れていない")

    return not _fails


def mutate(which):
    """★動く別の実装へ変異させて赤を実測する(C-053)。"""
    if which == "snake":                            # 受け入れ条件3= この行を🐍へ戻す
        react.CODEX_OVERRIDE["着手"] = ("🐍", None)
    elif which == "claude":                         # Claude側まで巻き込んで潰した場合
        react.EMOJI_ID["着手"] = BOSS_ID
        react.EMOJI_NAME["着手"] = BOSS_NAME
        react.ALIAS["着手"] = [BOSS_NAME]
    elif which == "noid":                           # id を落として unicode 扱いにした場合
        react.CODEX_OVERRIDE["着手"] = (BOSS_NAME, None)
    else:
        print("未知の変異体: " + which)
        sys.exit(2)
    print("★変異体 '%s' で同じ検査を流す(赤になるのが正しい)" % which)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--mutant" in sys.argv:
        mutate(sys.argv[sys.argv.index("--mutant") + 1])
    good = run()
    print(("PASS ボスの着手印=Chakusyu_Boss %d/%d" % (len(_ran) - len(_fails), len(_ran)))
          if good else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
