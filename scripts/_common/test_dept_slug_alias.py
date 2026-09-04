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
import io
import os
import shutil
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

print("\n[8] ★コード側の表(EXTRA_ALIASES)を退役させて、1件も落としていないか(HQ-0241)")
# 撤去した実物を .bak から読む= 「12件あった」を手書きしない(消えた表の実物と突き合わせる)。
RETIRED = os.path.join(ROOT, "scripts", "llm",
                       "pending_age_watch.py.bak_20260905_0700_extra_aliases")
retired_map = {}
try:
    _l = importlib.machinery.SourceFileLoader("paw_retired", RETIRED)
    _m = importlib.util.module_from_spec(importlib.util.spec_from_loader("paw_retired", _l))
    _l.exec_module(_m)
    retired_map = dict(getattr(_m, "EXTRA_ALIASES", {}))
except Exception as e:                                              # noqa: BLE001
    print(f"  (撤去前の .bak を読めない: {e})")
ok(bool(retired_map), "★撤去前のコード側の表を実物で取れた", RETIRED)
scan = dn.dept_scan_map()
lost = {k: v for k, v in retired_map.items() if dn.dept_slug(k) != v}
ok(not lost, f"★退役した通称 {len(retired_map)}件すべてが台帳経由で同じスラッグへ引ける", repr(lost))
lost_scan = {k: v for k, v in retired_map.items() if scan.get(k) != v}
ok(not lost_scan, "★走査側の表(dept_scan_map)にも同じ字面が残っている", repr(lost_scan))
ok(not hasattr(paw, "EXTRA_ALIASES"),
   "★見張り側にコードの表が残っていない(二重管理の再発を止める)")
ok(paw.dept_aliases() == scan, "★見張りの表は dept_scan_map そのもの(判定を2本持たない・ORG-11)")

print("\n[9] 大小・全半角の揺れ(`ad研究室`)と、走査側へ漏らさないこと")
# ★Chamiは 2026-09-05 までに `ad研究室` と小文字で3回書いている(正式表記は AD研究室)。
FORMAL = "AD研究室"
WOBBLE = dn.dept_slug(FORMAL)
ok(bool(WOBBLE), "前提= 正式表記が引ける", repr(WOBBLE))
for _v in ("ad研究室", "Ad研究室", "ａｄ研究室", " AD研究室 "):
    ok(dn.dept_slug(_v) == WOBBLE, f"★揺れを吸って同じ部門へ引ける: {_v}", repr(dn.dept_slug(_v)))
ok(scan.get("ad研究室") == WOBBLE, "走査側にも小文字の変種が入っている(和名は変種を作る)",
   repr(scan.get("ad研究室")))
# ★変種を**足す**のは和名だけ。純ASCIIの短い名前(`hq` / `HQ`)に変種を足すと、
#   台帳本文の字面を走査が拾って持ち主を奪う(実測= 見張りが読む4,474行に小文字hqが260回)。
#   台帳が自分で名乗っている字面(スラッグ・display_ja・通称)はそのまま残す= ここでは
#   「台帳に無いのに増えている純ASCIIの鍵」だけを禁じる。
declared = set(DEPTS) | {(v or {}).get("display_ja") for v in DEPTS.values()} \
           | set(dn.dept_alias_map()) | set(dn.EXTRA_JA)
generated = [k for k in scan if k not in declared]
ok(all(not k.isascii() for k in generated),
   "★増やした変種に純ASCIIの鍵は無い(走査で語を奪わせない)",
   repr([k for k in generated if k.isascii()]))
ok(dn.dept_slug("hq") == "hq" and dn.dept_slug("HQ") == "hq",
   "それでも引き当て(dept_slug)は大小どちらでも通る(吸うのは引く側だけ)")

# ★走査の語境界= 台帳本文に埋もれた `hq` を持ち主と読まない(実測で持ち主を1件奪っていた)。
LINE = "- [ ] 入れた(確認待ち) 00_AI-HQ/status/hq_open_items.md を直す ★2026-09-01 改修α"
ok(paw._find_name(LINE, "hq") < 0, "★語の途中の `hq`(ファイル名)は走査が拾わない",
   repr(paw._find_name(LINE, "hq")))
ok(paw._find_name("所有= hq / 依頼元= 研究室HQ", "hq") >= 0,
   "語として立っている `hq` は今までどおり拾う")
ok(paw._leftmost(LINE, scan)[1] == "system-engineer",
   "★同じ行の持ち主は 改修α 側になる", repr(paw._leftmost(LINE, scan)))
# ★赤(C-053)= 同じ行・同じ表で、語境界を持たない**動く実装**(撤去前の .bak)は取り違える。
if retired_map:
    _old_hit = _m._leftmost(LINE, retired_map)
    ok(_old_hit and _old_hit[1] == "hq",
       "★変更前の実装は同じ行をパス内の字面で研究室HQへ倒していた(これが穴だった)",
       repr(_old_hit))

print("\n[10] ★走査の規則と引き当ての規則が割れないこと(HQ-0241 便2・研究室HQの本丸)")
# HQ指摘= `_leftmost` は部分一致・`dept_slug` は完全一致で、同じ語でも呼び出し元で答えが割れていた
#   (例= `所有=改修α` が _leftmost では system-engineer、dept_slug では空)。
# ★規則そのものは1本にできない(走査は「行の中から探す」・引き当ては「渡された名前を解く」)。
#   揃えるべきは**答え**= 走査が当てた字面は、引き当てに渡しても必ず同じスラッグになること。
split = {k: (v, dn.dept_slug(k)) for k, v in scan.items() if dn.dept_slug(k) != v}
ok(not split, f"★走査表 {len(scan)}件すべてで dept_slug が同じ答えを返す", repr(split))
ok(dn.dept_slug("改修α") == "system-engineer",
   "★HQが挙げた実例 `改修α` は今はどちらでも引ける", repr(dn.dept_slug("改修α")))
_ow = paw.parse_line("- [ ] 入れた(確認待ち・所有=改修α) 何かの行 ★2026-09-01", scan)[2]
ok(_ow == "改修α" or _ow == "system-engineer", "★`所有=改修α` の札が同じスラッグへ落ちる", repr(_ow))

print("\n[11] ★取り消した札(打ち消し線)を確認待ちとして数えないこと")
# 実測= この見張り自身が hq_open_items.md:731(04:2x に閉じた行)を4.3日の未確認として鳴らしていた。
CLOSED = "  - **▼2026-09-01 16:2x ★呼称ゲートC= ~~入れた(確認待ち)~~ → 2026-09-05 04:2x 直った。**"
OPEN = "  - [ ] **★2026-09-01 呼称ゲートC= 入れた(確認待ち)**。"
TMPD = tempfile.mkdtemp(prefix="struck_")
led = os.path.join(TMPD, "hq_open_items.md")
io.open(led, "w", encoding="utf-8").write(CLOSED + "\n" + OPEN + "\n")
from datetime import datetime                                        # noqa: E402
_now = datetime(2026, 9, 5, 12, 0, tzinfo=paw.JST)
got = paw.scan(_now, files=[led], alias=scan)
ok(len(got) == 1, "★閉じた札は数えず、開いている札だけ残る", repr([g["line"] for g in got]))
ok(got and got[0]["line"] == 2, "残ったのは打ち消し線の無い方", repr(got))
ok(paw.PENDING.search(CLOSED) is not None,
   "(対照)札の字面そのものは在る= 落としているのは打ち消し線の判定だけ")
shutil.rmtree(TMPD, ignore_errors=True)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n=== {PASS}/{PASS + FAIL} PASS ===")
sys.exit(1 if FAIL else 0)
