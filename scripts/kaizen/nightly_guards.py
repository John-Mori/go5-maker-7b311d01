#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夜間門番(改善提案部門・自室 / C-019 の自動化・C-038)。

go5_sla_nightly(scripts/kaizen/sla_nightly.ps1)から毎晩呼ばれ、自室の
読み取り専用の検査を回す。**壊れている時だけ喋る**(正常な晩は静か=ログのみ)。

回す門番(いずれも直さない・検査のみ)=
  ①台帳壊れ検査 ledger_integrity.py = local/llm/*.jsonl の二重エンコード/不正JSON
  ②版ずれ先読み vermix_foresight.py = bump対象外の?v=保持HTML(載せ忘れ)/枯れ

★増分でなく「今その状態か」で鳴らす(C-041 / 持続する不具合を見逃さない)=
  載せ忘れが数日直らなければ、毎晩鳴らし続けるのが正しい(黙らせない)。

出口= persona_send.py(sla_report.py と同じ自動投稿経路。webhookは未設定のため使わない)。
異常が出ても**終了コードは0**(夜間チェーンを巻き込まない。合図は"投稿"であって"失敗"ではない)。

★載せ替え(C-042)= このスクリプトはTaskSchedulerが毎晩freshに起動するps1から
  fresh起動される=常駐ではない。編集した.pyは次の晩そのまま読まれる(再武装不要)。
"""
import os
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")  # BOM/日本語をcp932コンソールへ出して落ちるのを防ぐ
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PY = sys.executable


def guards():
    """(門番名, 実行argv) の定義。argv無指定=各ツールの本番既定で走る。"""
    return [
        ("台帳壊れ検査", [PY, os.path.join(HERE, "ledger_integrity.py")]),
        ("版ずれ先読み", [PY, os.path.join(HERE, "vermix_foresight.py")]),
    ]


def run_guards(gs):
    """各門番を実行し [(名前, returncode, 出力)] を返す。returncode!=0 = 要手当て。"""
    results = []
    for name, argv in gs:
        p = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        results.append((name, p.returncode, (p.stdout or "") + (p.stderr or "")))
    return results


def alert(failures):
    """壊れている門番だけ kaizen-analyst/トトリ 名義で自室へ push(sla_reportと同じ経路)。"""
    lines = ["夜間門番が異常を検出した(要手当て)。実物を見て直すこと:", ""]
    for name, out in failures:
        lines.append(f"■{name}")
        lines.append(out.strip()[:800])
        lines.append("")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as f:
        f.write("\n".join(lines))
        bpath = f.name
    try:
        subprocess.run([PY, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
                        "--dept", "kaizen-analyst", "--persona", "トトリ",
                        "--body-file", bpath])
    finally:
        try:
            os.unlink(bpath)
        except OSError:
            pass


def main():
    results = run_guards(guards())
    for name, rc, out in results:
        print(f"[{name}] rc={rc}")
        print(out.rstrip())
    failures = [(n, o) for n, rc, o in results if rc != 0]
    if failures:
        print(f"--- 要手当て {len(failures)}門 → 自室へ通知 ---")
        alert(failures)
    else:
        print("--- 全門クリーン(通知なし) ---")
    sys.exit(0)  # 異常でもチェーンは巻き込まない(合図は投稿)


if __name__ == "__main__":
    main()
