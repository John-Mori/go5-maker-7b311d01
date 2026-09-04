#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部門名の逆引きが台帳の `aliases`(通称)を見るかの試験(2026-09-05・イージス研究室)。

引き金= 研究室HQ便 DISPATCH-aegis-gl-1788556091239 ①(C-073)。
  Chamiが口で与えた通称「動画制作部門」(2026-09-03T06:36:24 msg 1544822097572921374)を
  どの実装も解決できず、ad研究室が「その部門は存在しない」と誤断した。HQは台帳へ
  `depts.manga-shorts.aliases: [動画制作部門]` を入れた(00_AI-HQ commit 9b21070)が、
  **それを読む実装が無かった**= データだけで効いていなかった。

★この試験が固定する事実:
  (1) `dept_slug("動画制作部門")` が manga-shorts を返す(緑)。
  (2) **同じ台帳・同じ入力**で、display_ja だけを見る動く実装(=修正前の
      `pending_age_watch.dept_aliases`・.bak から実物を読み込む)は解決できない(赤)。
  (3) display_ja / スラッグ / 未知語の扱いは変えていない。
  (4) 同じ通称を2部門が名乗ったら**解決しない**(曖昧なまま1つへ倒さない)。
  (5) 台帳が読めなくても例外を出さない(fail-safe)。
  (6) 見張り(pending_age_watch)の側にも通称が届いている= 配線が生きている。

★正解の日本語名をここに書かない= 名前は動く。台帳から取って突き合わせる。
"""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # 5SecMovieMaker
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))

import dept_names as dn                                             # noqa: E402
import pending_age_watch as paw                                     # noqa: E402

PASS = FAIL = 0


def ok(cond, name, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [NG] {name}" + (f"  … {detail}" if detail else ""))


print("=== 部門名の逆引き(aliases)試験 ===")

# 台帳から実物を取る(値を手書きしない)。
import yaml                                                          # noqa: E402
with open(dn.REGISTRY, encoding="utf-8") as f:
    DEPTS = (yaml.safe_load(f) or {}).get("depts") or {}
# ★2026-09-05 研究室HQ追記(止血)= 変更前の実装は EXTRA_ALIASES を自前で持っていて
#   「改修α」等は**台帳が無くても**引けていた。台帳の先頭の通称をそのまま題材にすると、
#   [3]の対照(赤)が「旧実装でも引けてしまう」で崩れる(9/5にHQが通称を5部門ぶん足して
#   実際に崩れた)。題材は**旧実装が持っていない通称**を優先して選ぶ。無ければ先頭。
BAK = os.path.join(ROOT, "scripts", "llm", "pending_age_watch.py.bak_20260905_aliases")
old = None
try:
    ldr = importlib.machinery.SourceFileLoader("paw_old", BAK)
    old = importlib.util.module_from_spec(importlib.util.spec_from_loader("paw_old", ldr))
    ldr.exec_module(old)
except Exception as e:                                              # noqa: BLE001
    print(f"  (.bak を読めない: {e})")
OLD_MAP = old.dept_aliases() if old is not None else {}

TARGET = None
FALLBACK = None
for _slug, _v in DEPTS.items():
    for _a in ((_v or {}).get("aliases") or ()):
        _cand = (_slug, str(_a), (_v or {}).get("display_ja"))
        if FALLBACK is None:
            FALLBACK = _cand
        if str(_a) not in OLD_MAP:
            TARGET = _cand
            break
    if TARGET:
        break
TARGET = TARGET or FALLBACK

print("\n[1] 台帳に通称が在ること(前提)")
ok(TARGET is not None, "★台帳に aliases を持つ部門が在る", dn.REGISTRY)
if TARGET is None:
    print("\n=== 前提が無いので中断 ===")
    sys.exit(1)
SLUG, ALIAS, JA = TARGET
print(f"      実物= {ALIAS} → {SLUG} (display_ja={JA})")

print("\n[2] ★緑= 通称が解決できる")
ok(dn.dept_slug(ALIAS) == SLUG, "★aliases からスラッグを引ける", repr(dn.dept_slug(ALIAS)))

print("\n[3] ★赤= display_ja だけ見る動く実装は、同じ入力で解決できない(C-053)")
if old is not None:
    om = OLD_MAP
    ok(ALIAS not in om,
       "★変更前の実装は同じ台帳・同じ通称を持っていない(これが穴だった)",
       repr(om.get(ALIAS)))
    ok(JA in om, "★変更前でも display_ja は引けていた(壊れていたのは通称だけ)", repr(om.get(JA)))
else:
    ok(False, "★.bak が読めない(赤を作れない)", BAK)

print("\n[4] 従来の引き方を壊していない")
ok(dn.dept_slug(JA) == SLUG, "display_ja からも引ける", repr(dn.dept_slug(JA)))
ok(dn.dept_slug(SLUG) == SLUG, "スラッグはそのまま通る", repr(dn.dept_slug(SLUG)))
ok(dn.dept_slug("しらない部門です") == "", "★未知は空を返す(スラッグを捏造しない)",
   repr(dn.dept_slug("しらない部門です")))
ok(dn.dept_slug("") == "" and dn.dept_slug(None) == "", "空・Noneでも落ちない")
ok(dn.dept_ja(SLUG) == JA, "順引き(dept_ja)は変わっていない", repr(dn.dept_ja(SLUG)))

print("\n[5] 曖昧な通称は解決しない")
TMP = tempfile.mkdtemp(prefix="alias_")
amb = os.path.join(TMP, "org_registry.yml")
with open(amb, "w", encoding="utf-8") as f:
    f.write("depts:\n"
            "  aaa:\n    display_ja: 甲部門\n    aliases: [かぶる通称, 甲だけの通称]\n"
            "  bbb:\n    display_ja: 乙部門\n    aliases: [かぶる通称]\n")
_orig = dn.REGISTRY
dn.REGISTRY, dn._cache["mtime"] = amb, None
try:
    ok(dn.dept_slug("かぶる通称") == "",
       "★2部門が名乗る通称は解決しない(居ない相手に預けない)", repr(dn.dept_slug("かぶる通称")))
    ok(dn.dept_slug("甲だけの通称") == "aaa",
       "曖昧でない通称は同じ台帳で引ける(全部止めてはいない)", repr(dn.dept_slug("甲だけの通称")))
    ok("かぶる通称" not in dn.dept_alias_map() and "甲だけの通称" in dn.dept_alias_map(),
       "dept_alias_map も曖昧な通称を出さない")
finally:
    dn.REGISTRY, dn._cache["mtime"] = _orig, None

print("\n[6] fail-safe(台帳が読めない)")
dn.REGISTRY, dn._cache["mtime"] = os.path.join(TMP, "nonexistent.yml"), None
try:
    ok(dn.dept_slug(ALIAS) == "", "台帳が無くても例外を出さず空を返す")
    ok(dn.dept_ja("main") == "司令塔", "台帳外の受け皿(EXTRA_JA)は台帳無しでも引ける")
finally:
    dn.REGISTRY, dn._cache["mtime"] = _orig, None

print("\n[7] 見張り(pending_age_watch)への配線")
m = paw.dept_aliases()
ok(m.get(ALIAS) == SLUG, "★台帳の通称が日齢見張りの当て方にも入っている", repr(m.get(ALIAS)))
ok(m.get(JA) == SLUG, "display_ja も今までどおり入っている", repr(m.get(JA)))

import shutil                                                        # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n=== {PASS}/{PASS + FAIL} PASS ===")
sys.exit(1 if FAIL else 0)
