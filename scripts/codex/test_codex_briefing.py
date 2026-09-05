# -*- coding: utf-8 -*-
"""codex_briefing の検査(2026-09-05 aegis-gl)。

C-053= 赤を見てから緑にする。この検査に歯が在ることは次で確かめられる:
  GO5_HQ_DIR=D:/nonexistent python scripts/codex/test_codex_briefing.py  → T2/T3 が赤
使い方: python scripts/codex/test_codex_briefing.py
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import codex_briefing as cb

ROOT = cb.ROOT
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))
    if not cond:
        fails.append(name)


# T1 芯が依頼を壊さずに包むこと(依頼本文はそのまま残る)
ask = "テスト用の依頼。ここは一字も変えるな。"
pre = cb.preamble_for(ask)
check("T1a 芯が先頭に載る", pre.startswith("■あなたへの規律"), pre[:20])
check("T1b 依頼本文が原文のまま残る", pre.endswith(ask), pre[-40:])
check("T1c 芯に §4.55 の芯が入る", "直った" in pre and "hash" in pre)
check("T1d 芯に C-003(.bak) が入る", ".bak" in pre)

# T2 全文が正本から組まれていること(写しを持っていないこと=正本が消えたら不明と書く)
full = cb.build_full()
check("T2a 共通規律の全文が入る", "## 4.55" in full and "## 5. Chamiへの接し方" in full,
      "共通規律を読めていない")
check("T2b 裁定カタログの見出しが入る", "### C-015" in full and "### C-073" in full,
      "裁定カタログを読めていない")
check("T2c 裁定カタログの本文までは入れない(300KB超を毎回渡さない)",
      len(full.encode("utf-8")) < 60000, f"{len(full.encode('utf-8'))}バイト")

# T2.5 人格の原典が**別のファイル**として組めること(2026-09-05・オタコンの発注)
per = cb.build_persona()
check("T2.5a 人格の原典2本が入る",
      "一人称=**俺**" in per or "ビッグ・ボス" in per, per[:80])
check("T2.5b 出典が2本とも読めている(不明が1つも無い)",
      "を読めなかった= 不明" not in per, "正本が欠けている")
check("T2.5c 人格は規律の袋へ混ぜない(持ち主が違う=ORG-11)",
      "ビッグ・ボス" not in full, "build_full に人格が混ざった")
check("T2.5d 芯から人格の置き場を指している",
      "local/CODEX_PERSONA.md" in cb.CORE)
# ★must-fail= 正本が読めない時に**黙って空を返さない**(推測で埋めさせない側へ倒す)。
_orig_sources = cb.PERSONA_SOURCES
cb.PERSONA_SOURCES = [("人格設定(声の型)", os.path.join(ROOT, "no", "such", "persona.md"))]
try:
    check("T2.5e must-fail: 正本が読めない時は「不明」と書く(空で通さない)",
          "を読めなかった= 不明" in cb.build_persona())
finally:
    cb.PERSONA_SOURCES = _orig_sources

# T3 worktree へ実際に置けること
with tempfile.TemporaryDirectory() as td:
    ret = cb.install(td)
    p = os.path.join(td, cb.BRIEF_REL)
    check("T3a local/ 配下へ書かれる", os.path.exists(p), p)
    check("T3b 戻り値は芯", ret == cb.CORE)
    body = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    check("T3c 置いた全文にも共通規律が入る", "## 4.55" in body)
    pp = os.path.join(td, cb.PERSONA_REL)
    check("T3d 人格も local/ 配下へ書かれる", os.path.exists(pp), pp)
    pbody = open(pp, encoding="utf-8").read() if os.path.exists(pp) else ""
    check("T3e 置いた人格に原典の中身が入る", "ネイキッド・スネーク" in pbody)

# T4 fail-open= 置けなくても芯は返る(規律の注入で本筋を止めない)
check("T4 置けない場所でも芯を返す",
      cb.install(os.path.join(ROOT, "no", "such", "dir", "\0bad")) == cb.CORE)

# T5 構造の要= 置き場が git に載らないこと
#    (HQの中身を公開repoへ乗せない/ worktree_changed が誤って「実装が残った」と言わない)
for _rel in (cb.BRIEF_REL, cb.PERSONA_REL):
    r = subprocess.run(["git", "-C", ROOT, "check-ignore", "-v", _rel.replace("\\", "/")],
                       capture_output=True, text=True, encoding="utf-8")
    check(f"T5 置き場が .gitignore 配下({_rel})",
          r.returncode == 0, r.stdout.strip() or r.stderr.strip())

print(f"\n{'全緑' if not fails else '赤 ' + str(len(fails)) + '件: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
