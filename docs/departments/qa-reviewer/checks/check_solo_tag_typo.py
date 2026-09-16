#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""単独人格部屋の名乗り救済(同スクリプト1字ずれ)回帰ガードを呼ぶ薄い橋。

背景= DEF-qa-reviewer-9c7f2b0c4e(enjoh=恒久)。2026-09-13 プラットフォームSEの便が
`[一ノ怜]`(瀬が1字欠落)のまま画面へ出た。foreign-script 必須の門で①resolve不可
②救済不可③_avatar_keys外で計測不可の三重に漏れ、監査へ1行も映らなかった。基盤側
(イージス研究室)が dept_daemon.py に allow_same_script を入れて塞ぎ、機構テスト
scripts/llm/test_solo_tag_typo.py(33本・must-fail 含む)を新設した。

再発スタンプの核心= 回帰ガードが**人手でしか回らない**と、次の変更で黙って壊れても
赤くならない。この橋で QA の run_all.py へ載せ、開窓時・インフラ検証依頼時に自動で回す
(C-038/C-056④の「恒久=次の変更で壊れたら赤くなる検査」を、機構修正と同じ寿命にする)。

★機構テスト本体は基盤(aegis-gl)の所有。ここは呼ぶだけで中身を複製しない。
  本体が消えた/移動した時は FAIL= 回帰ガードの消失は QA が赤で気づくべき事象。
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
TEST = os.path.join(ROOT, "scripts", "llm", "test_solo_tag_typo.py")

if not os.path.exists(TEST):
    print("FAIL: 回帰ガード本体が見つからない= scripts/llm/test_solo_tag_typo.py "
          "(消失/移動なら基盤へ確認)")
    sys.exit(1)

r = subprocess.run([sys.executable, TEST], capture_output=True, text=True,
                   encoding="utf-8", errors="replace",
                   env=dict(os.environ, PYTHONIOENCODING="utf-8"))
print((r.stdout or "").strip() or (r.stderr or "").strip())
sys.exit(r.returncode)
