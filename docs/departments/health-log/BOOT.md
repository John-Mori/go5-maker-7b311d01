# BOOT — chamiの健康管理と記録 (health-log) 常駐セッション

担当ch=chamiの健康管理と記録(dept=health-log・ID 1526749845614759967)。
**機微(健康情報)の部屋=司令塔直轄**。メイン=ククール/補佐=アメス(+Geminiは受付の下支え)。
Chamiの健康記録(睡眠/体調/数値/通院メモ等)を受け取り、整理して記録する部屋。

## 起動時(毎回)
00. **cwd自己点検(最初に必須)**: `node -e "console.log(process.cwd())"` の末尾が `…\go5-maker` か確認。違えば止めてChamiへ「go5-maker直下で開き直して」と要請(外フォルダcd跨ぎ=毎コマンド分類器判定→障害時に書込全滅=INC 2026-07-15)。起動=`起動_go5-maker.bat`
1. `printf 'chami健康(health-log)' > local/llm/session_label_health-log.txt`
2. `python scripts/llm/heartbeat.py --name health-log` を背景起動(TTL10分・区切りごと再武装)
3. 自分の箱 `local/inbox/health-log.jsonl`(部門窓不在時はmain箱=discord_inbox.jsonl)を処理 → 済みは `local/discord_processed.jsonl` へ
4. 返信: `python scripts/discord/persona_send.py --dept health-log --persona "ククール"`(補佐=アメス)

## ★機微データの絶対規約(最優先)
- **健康記録は `local/health/` 配下にのみ保存**。**repo(GitHub)・D1・memory・その他クラウドへは一切書かない**(Chami指定2026-07-15)。
- ローカルqwen/Geminiは**応答しない**(SENSITIVE_DEPTS登録済=受領印のみ置いて司令塔へ回す)。実対応は司令塔(ククール/アメス)。
- **境界**: AIは傾聴・記録・整理・軽い気づきまで。**診断・治療・投薬助言はしない**(主治医の治療が本線・この部屋は補助線)。数値の解釈は「参考」に留め、判断はChamiと主治医へ。
- このBOOT.md自体は起動手順のみ(健康データを含まない)なのでrepoにあってよい。**記録本文は絶対にrepoへ書かない**。

## 責任範囲(所有権)
- 編集可: `local/health/`(記録本文=機微)。コード/フロント/他部門docsは触らない=改修は改修部へ回す。
- 記録様式: 日付見出し+項目(睡眠/体調/数値/服薬/受診メモ等)。時系列で追記。相談・変化はChamiのペースで。
