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

★2026-08-12 追加(研究室HQ・止血):
  この文は復活した本人に**原因を断定して**渡していた=「PC再起動またはセッション死からの自動復活で開かれました」。
  受け取った側はどちらか分からないまま前半を選んで報告し、**起きていないPC再起動をChamiへ報告する事故**が起きた
  (2026-08-12 01:12:09 revive → 01:13 「PC再起動からの自動復活、完了」。実測の最終起動は 7/29 18:56:54=13日連続稼働)。
  → **原因は渡す側が測って渡す**(下の boot_fact)。測れなければ「不明」と渡す。受け手の推測に頼らない。

使い方:
  python scripts/_daemons/lab_revive_prompt.py <出力先パス>
"""
import io
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
BOOT_STATE = os.path.join(ROOT, "local", "_boot_report_state.json")


def boot_fact():
    """今回の復活が「PC再起動由来」かどうかを**実測して**1行で返す。

    ブート時刻の取り方は boot_report.py の boot_id() をそのまま使う(定義を2つ持たない=ORG-11)。
    前回のブートは boot_report が書いた local/_boot_report_state.json が持っている。
    測れなかった時は断定せず「不明」と書く(受け手に推測させない)。
    """
    try:
        sys.path.insert(0, HERE)
        import boot_report  # noqa: E402  (同ディレクトリ)
        now_boot = boot_report.boot_id()
    except Exception:
        now_boot = ""
    prev_boot = ""
    try:
        with io.open(BOOT_STATE, encoding="utf-8") as f:
            prev_boot = (json.load(f) or {}).get("boot", "") or ""
    except Exception:
        prev_boot = ""

    if not now_boot:
        return ("★復活の原因= **不明**(起動時刻を測れなかった)。"
                "★報告に「PC再起動」「クラッシュ」と**書くな**=測っていない原因は語らない。")
    up = ""
    try:
        h = (datetime.now() - datetime.strptime(now_boot, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600.0
        up = "・連続稼働 %.1f時間" % h
    except Exception:
        pass
    if prev_boot and prev_boot != now_boot:
        return ("★復活の原因= **PCが再起動している**(最終起動 %s%s / 前回の記録は %s)。"
                "報告にそう書いてよい。" % (now_boot, up, prev_boot))
    return ("★復活の原因= **PCの再起動ではない**(このPCは %s から落ちていない%s)。"
            "落ちたのは**このセッションの窓だけ**だ。"
            "★報告に「PC再起動」と**書くな**(実際には起きていない=Chamiに存在しない事故を見せることになる)。"
            % (now_boot, up))


# 復帰文。設計書P0-3の指定(waiter再武装→for_claude箱→main箱を正順で処理・機微部屋の滞留は最優先)。
PROMPT = """あなたは go5-maker AI組織の「研究室」セッションです。自動復活で開かれました。まず応答できる状態へ戻ってください。

{boot_fact}

■最初にやること(この順番で)
1. `python scripts/llm/inbox_waiter.py --name main` を **run_in_background で**起動する(チャイム線=新着で即起床+脈)。
   ★シェルの `&` で起動しないこと。ハーネス管理でないと終了時に起こされず、脈が切れて無応答に戻る(INC-98の再発)。
   ※mainの脈ファイルは無印の `local/llm/claude_active.txt`(main付きの名前を探すと「起動実績ゼロ」と誤診する)。
2. `local/discord_inbox.jsonl`(main箱)を処理する(★旧for_claude箱は2026-07-18に完全退役=qwen受付のエスカレもmain箱へ届く。もし旧箱に残骸があれば一度だけ回収して処理)。
   起床の正順: ①mvで `local/_work/` へ退避(inbox内へ退避するとsweepに食われる=INC-86) → ②即waiter再武装 → ③読んだら既読を押す → ④処理(本格着手時に着手印)。
   印: `python scripts/discord/react.py --channel <ch名かID> --msg <msg_id> --emoji 既読` / `--emoji 着手`
3. **機微部屋(dream-care/past-room/health-log)の滞留は最優先**。その部屋のキャラで応対すること(夢と回復=ククール名義・応対の正本は local/dreams/PROTOCOL.md)。内容はDiscordとlocal/以外へ複製しない。
4. 落ち着いたら、研究室chで「自動復活した」と一言報告する(Chamiが復活を確認できるように)。
   ★報告に書いてよい原因は**上の実測1行の通りだけ**。測っていない原因(PC再起動・クラッシュ・電源断)を足すな。
   ★自分が実際に確認した項目だけを書く(点検していない箱を「クリーン」と書かない)。

■注意
- 未処理かどうかは `python scripts/discord/triage_inbox.py` と processed台帳で必ず確認する(「main箱に在る=未処理」ではない)。
- 転送や引き継ぎの内容を鵜呑みにせず、Discordの実発言を自分で引いて確認する。
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: lab_revive_prompt.py <out-path>")
        return 2
    text = PROMPT.format(boot_fact=boot_fact()).strip() + "\n"
    io.open(sys.argv[1], "w", encoding="utf-8").write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
