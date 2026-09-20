#!/usr/bin/env python3
"""audit_marks の印表が react.py から**引かれている**ことの回帰ガード。

なぜ要るか(2026-09-09 イージス研究室 第55世代):
  audit_marks は「Chamiの便に生存の合図が付いたか」をDiscordのreactionから直読みする唯一の器で、
  A1(配下の無警報滞留 0件)はこれで測る。ところが印表を react.py から**書き写して**持っていたため、
  2026-09-05に入った CODEX_OVERRIDE(@ボス便だけ 送信→uptsukiyomi / 既読→‼️ / 着手→🐍)を
  この器だけが知らないまま残った。実測 2026-09-09 11:37 JST、goods-afi/manga-shorts/otacon-radio の
  Chami便34通のうち**9通が「生存印なし」と誤報**= 全部 uptsukiyomi/‼️/🐍 が実際に付いている @ボス便。
  誤報は「掴まれず沈黙した依頼」を水増しし、逆に本物の滞留をノイズへ埋める。
  ここが緑でなくなったら、また押す側に印が増えた日に測る側だけ置き去りになる。

実行: python scripts/discord/test_audit_marks_codex.py
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit_marks as AM  # noqa: E402
import react as RE  # noqa: E402

P = F = 0


def ok(cond, name):
    global P, F
    if cond:
        P += 1
        print("PASS", name)
    else:
        F += 1
        print("FAIL", name)


def msg(*names):
    """Discord APIが返す形のメッセージ(reactionsのemoji.nameだけが判定に効く)。"""
    return {"id": "x", "reactions": [{"emoji": {"name": n}} for n in names]}


ALIVE = {"既読", "着手", "即答"}

# ---- ① 実物の再現: @ボス便に実際に付いていた並び(2026-09-09 実測) ----
# 1546345439224406097(goods-afi) / 1546933213572763748(manga-shorts) の現物の並び。
g = AM.marks_on(msg("sendms", "‼️", "🐍", "uptsukiyomi"))
ok(g == {"送信", "既読", "着手"}, "Codex印(sendms+‼️+🐍+uptsukiyomi)を3印として読む")
ok(bool(ALIVE & g), "★同じ便を『生存印なし』と誤報しない(誤報9件の再発ガード)")

g = AM.marks_on(msg("uptsukiyomi", "‼️", "🐍"))
ok(g == {"送信", "既読", "着手"}, "サーバー印が1つも無いCodex便でも3印そろって読める")

# 異体字セレクタの揺れ(‼ / ‼️)はどちらも既読として拾う。
ok("既読" in AM.marks_on(msg("‼")), "‼(VS16なし)も既読として拾う")

# ---- ② 従来のClaude印を壊していない ----
ok(AM.marks_on(msg("sendms", "kidoku", "chakusyu")) == {"送信", "既読", "着手"},
   "サーバー絵文字(sendms/kidoku/chakusyu)は従来どおり")
ok(AM.marks_on(msg("📮", "✅", "👀", "💬")) == {"送信", "既読", "着手", "即答"},
   "Unicode代用(📮✅👀💬)も従来どおり")

# ---- ③ 本物の無印は無印のまま(誤って生存扱いしない=器を甘くしていない) ----
g = AM.marks_on(msg("sendms"))
ok(g == {"送信"} and not (ALIVE & g), "送信だけの便は生存印なしのまま(届いたが無人)")
ok(AM.marks_on(msg()) == set(), "reactionsが空の便は無印のまま")
ok(AM.marks_on(msg("enjoh", "saihatsu", "golazo")) == set(),
   "炎上/再発/ゴラッソは進捗印ではない(生存の合図に数えない)")

# ---- ④ ★核心: 表を写経していない= react.py が正で、こちらは引いているだけ ----
for label, (name, _id) in RE.CODEX_OVERRIDE.items():
    ok(name in AM.MARKS.get(label, ()),
       f"react.CODEX_OVERRIDE['{label}']={name} を MARKS が持っている")
for label, aliases in RE.ALIAS.items():
    if label in AM.MARKS:
        ok(all(x in AM.MARKS[label] for x in aliases),
           f"react.ALIAS['{label}'] を MARKS が持っている")

# 押す側に印が増えたら、写経ではなく**自動で**追随することを実行で示す。
orig = dict(RE.CODEX_OVERRIDE)
try:
    RE.CODEX_OVERRIDE["着手"] = ("🦎", None)      # 押す側だけを差し替える
    rebuilt = AM._build_marks()
    ok("🦎" in rebuilt["着手"], "★押す側(react)の差し替えに測る側が自動追随する(ORG-11)")
finally:
    RE.CODEX_OVERRIDE.clear()
    RE.CODEX_OVERRIDE.update(orig)
ok(AM._build_marks() == AM.MARKS, "後始末: 表を元へ戻した")

# ---- ④b 引退した印も同じ印として畳む(2026-09-20 着手 🐍 → Chakusyu_Boss へ差し替え) ----
#   差し替えた日より前の@ボス便には🐍が付いたまま残る。押す側が新印になっても、
#   読む側が古い印を落とした瞬間に過去便が一斉に「着手なし」へ落ちる=誤報9件と同じ形が戻る。
for label, olds in getattr(RE, "CODEX_RETIRED", {}).items():
    for _name, _id in olds:
        ok(_name in AM.MARKS.get(label, ()),
           f"引退印 {label}={_name} も MARKS が持っている(過去便を読み落とさない)")
ok("Chakusyu_Boss" in AM.MARKS.get("着手", ()),
   "新印 Chakusyu_Boss を MARKS が持っている(2026-09-20 差し替え)")
ok(AM.marks_on(msg("uptsukiyomi", "‼️", "Chakusyu_Boss")) == {"送信", "既読", "着手"},
   "新印で押された@ボス便も3印そろって読める")


def build_without_retired():
    """★動く別の実装= 引退表を畳まない版(差し替えの前に audit_marks が持っていた形)。"""
    out = {}
    for label in ("送信", "既読", "着手", "即答"):
        names = set(RE.ALIAS.get(label) or [label])
        names.add(label)
        fb = RE.FALLBACK.get(label)
        if fb:
            names.add(fb)
        ov = RE.CODEX_OVERRIDE.get(label)
        if ov and ov[0]:
            names.add(ov[0])
            names.add(ov[0].replace("️", ""))
        out[label] = tuple(sorted(n for n in names if n))
    return out


ok("🐍" not in build_without_retired()["着手"],
   "MUST-FAIL: 引退表を畳まない版は🐍を着手として読めない(差し替えた日に過去便が落ちる形)")

# ---- ⑤ MUST-FAIL: 「Codex印を知らない実装」= 事故当時の写経版(動く別実装) ----
#      C-053= 変異は壊した実装ではなく**動く別の実装**へ当てる。これが赤にならないなら
#      この検査は誤報を捕まえられていない=検査自体が無意味。
LEGACY = {                                   # 2026-09-09 11:37 まで audit_marks に在った表
    "送信": ("sendms", "送信", "📮"),
    "既読": ("kidoku", "既読", "✅"),
    "着手": ("chakusyu", "着手", "👀"),
    "即答": ("sokutou", "即答", "💬"),
}


def marks_on_legacy(m):
    got = set()
    for r in (m.get("reactions") or []):
        name = str(((r.get("emoji") or {}).get("name")) or "")
        for label, aliases in LEGACY.items():
            if name in aliases:
                got.add(label)
    return got


boss = msg("sendms", "‼️", "🐍", "uptsukiyomi")
ok(not (ALIVE & marks_on_legacy(boss)),
   "MUST-FAIL: 写経版は同じ便を『生存印なし』と誤報する(この差が事故そのもの)")
ok(bool(ALIVE & AM.marks_on(boss)) and not (ALIVE & marks_on_legacy(boss)),
   "★現行と写経版で結論が割れる= この検査は誤報を検出できている")

print(f"\n{P} PASS / {F} FAIL")
sys.exit(1 if F else 0)
