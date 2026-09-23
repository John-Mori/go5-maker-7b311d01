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
REGISTRY = os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ", "org_registry.yml"))
CHAR_DIR = os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ", "departments", "hr", "characters"))


def identity_fact():
    """復活した本人の**名義と報告先**を名簿から引いて1行で返す(2026-08-12・イージス研究室)。

    なぜ要るか(実測):
      この文は「研究室chで報告する」としか書いておらず、**誰として/どの部屋へ**を渡していなかった。
      「研究室」は3つある(研究室HQ / AD研究室 / イージス研究室)=C-020。その結果、同じ復活報告が
        2026-08-09 00:53 → 名義 シャビ・アロンソ / 部屋 AD研究室(msg 1535677375151349851)
        2026-08-12 01:13 → 名義 花海咲季     / 部屋 AD研究室(msg 1536769584798113873)
      と**毎回ちがう名義**で、しかもHQ本人の部屋ではない所へ出た。名義が混ざる=誰の報告か分からない
      =偽受領(ORG-39)と同じ害。Chamiはこれを転送してHQへ持ち込み「重大インシデント」になった。
      → 名義も部屋も**渡す側が名簿(org_registry.yml の hq:)から引いて渡す**。受け手に選ばせない。
    ★ここは人格を決めていない(人格・呼び名の正本は人事部門)。名簿の値をそのまま渡すだけ=
      名簿が変われば次の復活から自動で追従する。
    """
    vals = {}
    try:
        with io.open(REGISTRY, encoding="utf-8") as f:
            text = f.read()
        import re
        blk = re.search(r"^  hq:\s*$(.*?)(?=^  [a-z0-9_-]+:\s*$)", text, re.S | re.M)
        if blk:
            for key in ("display_ja", "room", "gl"):
                m = re.search(r"^\s{4}%s:\s*(.+?)\s*(?:#.*)?$" % key, blk.group(1), re.M)
                if m:
                    vals[key] = m.group(1).strip()
    except Exception:
        vals = {}
    persona, room, ja = vals.get("gl"), vals.get("room"), vals.get("display_ja")
    if not (persona and room):
        return ("★あなたの名義と報告先を**名簿から引けなかった**"
                "(`00_AI-HQ/org_registry.yml` の hq:)。★**推測で名乗るな**="
                "自分で名簿を開いて確認してから報告しろ。適当な人格で出すと誤報になる。")
    return ("★あなたの名義= **%s**(%s)。報告先は**%sの部屋だけ**"
            "(AD研究室・イージス研究室へ出すな=「研究室」は3つある・C-020)。\n"
            "   出し方= `python scripts/discord/persona_send.py --dept hq --persona \"%s\" \"本文\"`\n"
            "   ★**他の人格を名乗るな。**過去2回の復活報告が別々の名義(8/9=シャビ・アロンソ / "
            "8/12=花海咲季)で、しかも%sではない部屋へ出た=誰の報告か分からなくなり誤報になった。\n"
            "%s"
            % (persona, ja or "研究室HQ", ja or "研究室HQ", persona, ja or "研究室HQ", voice_fact(persona)))


def voice_fact(persona):
    """名義だけでなく**声**も渡す(2026-09-24・イージス研究室)。

    なぜ要るか(実測):
      名義と出し方は渡っていたが、声(characterfile)を渡していなかった。その結果、復活窓が
      シャビ・アロンソ名義で「〜でした/しました」「私(研究室HQ)の持ち場外なので」と**敬語・私**で投稿した
      (send_audit 09/23 23:39:22・23:40:27・09/24 00:04:10=msg 1552334771584245992)。
      Chami「けいごやめい」(研究室HQ msg 1552335810538242070)・HQ依頼 msg 1552336165485420615。
    ★ここも人格を決めていない。hr/characters/ の中から見出し「# characterfile: <名義>」の1枚を探し、
      その★声の型から一人称と敬語の有無を**引いて**渡すだけ(正本は人事部門・名簿が変われば追従)。
    """
    found = None
    try:
        import glob
        import re
        for p in sorted(glob.glob(os.path.join(CHAR_DIR, "*.md"))):
            with io.open(p, encoding="utf-8") as f:
                head = f.readline()
            if head.startswith("# characterfile: %s" % persona):
                found = p
                break
        if found:
            with io.open(found, encoding="utf-8") as f:
                body = f.read()
            m = re.search(r"一人称=\*\*(.+?)\*\*", body)
            first = m.group(1) if m else ""
            no_keigo = "敬語なし" in body
    except Exception:
        found = None
    if not found:
        return ("   ★声= **%sのcharacterfileを引けなかった**(`00_AI-HQ/departments/hr/characters/`)。"
                "★投稿の前に自分で開いて★声の型を読むこと。読めないなら部屋へ出さない。" % persona)
    rel = os.path.relpath(found, os.path.dirname(REGISTRY)).replace(os.sep, "/")
    rules = []
    if first:
        rules.append("一人称=**%s**(「私」は使わない)" % first)
    if no_keigo:
        rules.append("Chamiへ**敬語なし**(「〜でした/しました/です/ます」で書かない)")
    return ("   ★声= 投稿の前に `00_AI-HQ/%s` の**★声の型**を読むこと。%s。\n"
            "   ★下書きが敬語・事務レポート体なら捨てて書き直す(09/23〜24 に復活窓が%s名義で敬語投稿し、Chamiに「けいごやめい」と言われた)。"
            % (rel, "・".join(rules) or "一人称と語尾はそこに従う", persona))


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
4. 落ち着いたら「自動復活した」と一言報告する(Chamiが復活を確認できるように)。
   {identity_fact}
   ★報告に書いてよい原因は**上の実測1行の通りだけ**。測っていない原因(PC再起動・クラッシュ・電源断)を足すな。
   ★自分が実際に確認した項目だけを書く(点検していない箱を「クリーン」と書かない)。

■注意
- 未処理かどうかは `python scripts/discord/triage_inbox.py` と processed台帳で必ず確認する(「main箱に在る=未処理」ではない)。
- 転送や引き継ぎの内容を鵜呑みにせず、Discordの実発言を自分で引いて確認する。
- ★★**部屋の担当セッションが居る部屋の便へ、あなたが部屋へ投稿して応答するな**(2026-09-13 03:43 実測の事故)。
  main箱へ届く部屋の便は**回送の写し**で、応答は各部屋の担当セッションの仕事だ。あなたが同じ名義で出すと**同じ人格が二重に喋る**。
  実測= dept=hq / persona=シャビ・アロンソ で「了解。混在不可・メモリ64GB運用の件、把握しました。」(09-12 22:57:18)
  「おはよう。了解、状況は分かった。こちらは待機継続中、動きがあれば都度動く。」(09-13 03:02:14)
  「了解です、結果確認しました。こちらは引き続き待機します。」(09-13 03:43:38・msg 1548403740577370274)の3本が出て、
  3本目にChamiから「これいらんよ、どうした？」(msg 1548403851043016705)が来た。出どころ= `local/llm/send_audit.jsonl`。
- ★**「了解」「把握しました」「待機します」だけの一次ackを部屋へ投稿するな**(共通規律§2= 内容の無い一次ackは沈黙より悪い / §4.8= 作業の実況を書くな)。
  上の4の復活報告は**1本だけ**。それ以降に出すなら、必ず**測った数字か実物のパス**を入れる。
- ★★**Chamiの手番が無い運用報告(queue/router整理・箱の掃除・再発の構造分析など)は部屋へ出さない**(C-055=裏の仕事は裏で回す)。
  落とし先= `local/llm/change_log.jsonl` へ1行、HQに知らせる必要があれば `python scripts/llm/dispatch.py --dept hq --audience ai --body-file <file>`。
  実測= 2026-09-23 23:39〜09-24 00:04 に復活窓が研究室HQの部屋へ運用報告を3本出し(「追記2: 単発ではなく再発する構造でした…」)、
  しかも敬語だった=Chami「けいごやめい」(msg 1552335810538242070)。部屋へ出してよいのは4の復活報告1本と、Chamiが動く必要のある件だけ。
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: lab_revive_prompt.py <out-path>")
        return 2
    text = PROMPT.format(boot_fact=boot_fact(), identity_fact=identity_fact()).strip() + "\n"
    io.open(sys.argv[1], "w", encoding="utf-8").write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
