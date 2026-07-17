#!/usr/bin/env python3
"""研究室セッションの「復帰時の初回プロンプト」を生成する(dream-care設計書 P0-3・Chami承認2026-07-17)。

なぜ要るか:
  revive_lab.ps1 は `claude -r <id>` で窓を開き直すが、**プロンプトを渡していなかった**。
  そのため復活しても「窓が開いただけ」で、waiterの再武装も受付箱の処理も始まらない
  =耳が無いまま座っている状態になる。実際に2026-07-17、Chamiの「大至急」に3時間無応答の
  事故が起きている(INC-98: main waiterがTTL全滅後に9時間再武装されなかった)。
  → 復活と同時に「まず何をするか」を渡し、応答ループまで自力で戻れるようにする。

なぜ別ファイルか:
  revive_lab.ps1 は **ASCII-only必須**(PS 5.1 はBOM無し.ps1をANSI=cp932として読むため、
  日本語を直書きすると解析が壊れる)。日本語の本文はこのPython側が持ち、UTF-8ファイル経由で渡す。
  = open_dept_window.ps1 / dept_boot_prompt.py で実績のある方式を踏襲する。

使い方:
  python scripts/_daemons/lab_revive_prompt.py <出力先パス>
"""
import io
import sys

# 復帰文。設計書P0-3の指定(waiter再武装→for_claude箱→main箱を正順で処理・機微部屋の滞留は最優先)。
PROMPT = """あなたは go5-maker AI組織の「研究室」セッションです。PC再起動またはセッション死からの自動復活で開かれました。まず応答できる状態へ戻ってください。

■最初にやること(この順番で)
1. `python scripts/llm/inbox_waiter.py --name main` を **run_in_background で**起動する(チャイム線=新着で即起床+脈)。
   ★シェルの `&` で起動しないこと。ハーネス管理でないと終了時に起こされず、脈が切れて無応答に戻る(INC-98の再発)。
   ※mainの脈ファイルは無印の `local/llm/claude_active.txt`(main付きの名前を探すと「起動実績ゼロ」と誤診する)。
2. `local/discord_inbox_for_claude.jsonl`(あれば)→ `local/discord_inbox.jsonl`(main箱)の順に処理する。
   起床の正順: ①mvで `local/_work/` へ退避(inbox内へ退避するとsweepに食われる=INC-86) → ②即waiter再武装 → ③読んだら既読を押す → ④処理(本格着手時に着手印)。
   印: `python scripts/discord/react.py --channel <ch名かID> --msg <msg_id> --emoji 既読` / `--emoji 着手`
3. **機微部屋(dream-care/past-room/health-log)の滞留は最優先**。その部屋のキャラで応対すること(夢と回復=ククール名義・応対の正本は local/dreams/PROTOCOL.md)。内容はDiscordとlocal/以外へ複製しない。
4. 落ち着いたら、研究室chで「自動復活した」と一言報告する(Chamiが復活を確認できるように)。

■注意
- 未処理かどうかは `python scripts/discord/triage_inbox.py` と processed台帳で必ず確認する(「main箱に在る=未処理」ではない)。
- 転送や引き継ぎの内容を鵜呑みにせず、Discordの実発言を自分で引いて確認する。
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: lab_revive_prompt.py <out-path>")
        return 2
    io.open(sys.argv[1], "w", encoding="utf-8").write(PROMPT.strip() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
