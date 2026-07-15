# Discord送信・巡回の信頼性ルール (2026-07-15 Chami指摘で策定・全セッション必読)

> Chamiは **Claude Code本体のchatペインを見ない**。実体はすべてDiscordに出す([[report-via-discord]])。
> だが「chatで返信文を書いたのに実際にはDiscordへ届いていない」「依頼を巡回漏れで無視する」が繰り返し起きた。
> その2つの根本問題と対策を以下に固定する。**司令塔・全部門セッションはこれを徹底する。**

## 根本問題A: 送信が実際には失敗しているのに「送った」と誤認する
### 原因
- `persona_send.py` を **heredoc(`"$(cat <<'EOF' … EOF)"`)や複数コマンド連結**で呼ぶと、ツールコールの記法が崩れて(malformed)**実行自体が飛ぶ**ことがある。その時「送信OK … HTTP 204」が返らないのに、司令塔が送った気になって次へ進む → Chamiには何も届かない。
- 1つのBashに複数の `persona_send` を詰めると、1つ壊れると全部飛ぶ。

### 対策(必須)
1. **長文・複数行・日本語の本文は `--body-file <path>` で送る**(2026-07-15追加)。本文をWriteでファイルに書き、`python scripts/discord/persona_send.py --dept <slug> --persona "<名>" --body-file <path>` で送る。→ heredoc/shellクオートの崩れを**根絶**。
2. **1ツールコール=1送信**。複数の返信を1つのBashにまとめない(1つの崩れで全滅を防ぐ)。
3. **送信後に必ず `送信OK … (HTTP 204)` を目視確認**。返っていなければ**再送**する。**確認できるまで「送った」と報告しない**。
4. 疑わしい時・状態不明時は **Discord API(bot token)で該当chの最新メッセージを取得**し、自分の返信がChami発言の**後**に在るかで照合する(下記スニペット)。

## 根本問題B: 受付箱の巡回漏れで依頼を無視する
### 原因
- 司令塔は"呼ばれた時"しかmain箱を見ない。別作業中は全部屋の返事が一斉に遅れる。
- main箱をまとめてアーカイブする際、処理中に届いた新着(別の行)を**読まずにアーカイブ**して取りこぼす。

### 対策(必須)
1. **自動巡回ループ**(ScheduleWakeup 90秒/idle時600秒)でmain箱を定期確認→未処理を即返信([[auto-poll-responsiveness]])。
2. **アーカイブは処理した msg_id だけを消す**(箱全体を盲目的に消さない)。または処理直前に箱を再読して、処理済み以外(新着)は残す。
3. **各巡回の最後にDiscord APIで主要アクティブchの最新を照合**し、「BOT(自分)の返信より後にUSER(Chami)発言が在る」chがあれば未返信として拾う。main箱の取りこぼしをAPI照合で補償する。

## 照合スニペット(bot tokenで該当chの最新を見る)
```python
import sys, json, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
token=open("local/discord_bot_token.txt",encoding="utf-8").read().strip()
cid="<channel_id>"
req=urllib.request.Request(f"https://discord.com/api/v10/channels/{cid}/messages?limit=3",
    headers={"Authorization":"Bot "+token,"User-Agent":"go5 (personal)"})
for m in json.loads(urllib.request.urlopen(req,timeout=20).read()):
    bot = bool(m.get("webhook_id") or m.get("author",{}).get("bot"))
    print(("BOT" if bot else "USR"), m.get("timestamp","")[11:19], (m.get("content","") or "(添付)")[:50])
# 最新(先頭)が USR = 未返信の可能性。BOT = 返信済み。
```

## 一言まとめ
**長文は --body-file / 1コール1送信 / HTTP 204を確認してから「送った」と言う / 巡回ごとにAPIで未返信を照合。**
これを守れば「届いてない」「無視された」は起きない。
