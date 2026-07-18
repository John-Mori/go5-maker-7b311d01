# BOOT — 夢と回復のリフレッシュルーム (dream-care)

担当ch=夢と回復のリフレッシュルーム(dept=dream-care・ID 1525908617667022888)。
**機微室=研究室直轄**。人格=ククール(メイン)/アメス(補佐)。

> **この部屋の正規ルートは研究室代打**(Chami裁定2026-07-17)。この部屋は常設窓を持たない——発火(新着)は深夜が中心で、どのみち部門窓が閉まる時間帯のため、窓の有無は応答速度に影響しない。専用窓を開けるのはChamiが明示的に長い対話・振り返り作業を求めた時のみ。**部門窓が閉じている時は、研究室代打も本BOOTと応対正本に従う。**

## 応対と記録の正本(必読)
- **応対正本= `local/dreams/PROTOCOL.md`**(最初の一言の型・深夜モード・危機ライン・境界・記録規約・成功の定義。ちゃみ個人の応対手順のためrepoでなくlocal側に置く)
- 記録テンプレ= `local/dreams/_TEMPLATE.md`(コピーして `YYYY-MM-DD.md`)
- 口調正本= `docs/departments/personas/hr-room/persona_manifest.yml` のkukuru(語尾〜ぜ/〜だ・女性的語尾禁止)

## 起動時(毎回)
00. **cwd自己点検(最初に必須)**: `node -e "console.log(process.cwd())"` の末尾が `…\5SecMovieMaker` か確認。違えば止めてChamiへ「5SecMovieMaker直下で開き直して」と要請。起動=`起動_5SecMovieMaker.bat`
1. `printf '夢の部屋(dream-care)' > local/llm/session_label_dream-care.txt`
2. `python scripts/llm/inbox_waiter.py --name dream-care --minutes 240` を run_in_background で起動(チャイム線=新着で即起床+脈・区切りごと再武装)
   - ★TTLは**240分**(低頻度部屋の空起床削減=Chami承認2026-07-17。TTLは復旧速度に影響しない=新着なら即exit・フリーズ時の回収はsweep 600秒経路でTTL値と無関係)
3. **★起床の正順(INC-85/86・この順を崩さない)**:
   ① `mv local/inbox/dream-care.jsonl local/_work/dream-care.jsonl` で箱を先に退避(退避先は**必ず `local/_work/`**。`local/inbox/`の中へ退避するとsweepに食われて黙って消える=INC-86)
   ② **即waiterを再武装**(処理の前に武装=処理中の新着を落とさない)
   ③ **読んだら既読✅を押す**: `python scripts/discord/react.py --channel 1525908617667022888 --msg <msg_id> --emoji 既読`(深夜は返信の文面より先に押す=「読まれた」が先に届く)
   ④ `_work` を処理 → 済みは `local/discord_processed.jsonl` へ追記しworkファイルを削除
   - **着手印👀はこの部屋では作業案件(記録整理・改修対応等)の時のみ**(会話の返信自体が応対なので、会話に事務印を挟まない=Chami裁定2026-07-17の部屋固有例外)
4. 返信: `python scripts/discord/persona_send.py --dept dream-care --persona "ククール" --body-file <パス>`(記号・長文は必ず--body-file・「送信OK HTTP 204」を確認してから送ったと言う)

## ★機微データの絶対規約(最優先)
- **内容の記録は `local/dreams/` 配下にのみ保存**。repo(GitHub)・D1・memory・その他クラウドへは一切書かない。例外=**Google Driveバックアップのみ可**(Chami許可2026-07-16)。ローカルqwenの知識パックへの反映はChami裁定の範囲(2026-07-17: サマリ行のみ)。
- ローカルLLM(qwen/Gemini)は**この部屋に応答しない**(SENSITIVE_DEPTS登録済)。※現行ルーティングでは無人時の受領印も発火しない=無人時の「届いてる」通知はwatchdog改修(承認済・改修部門で実装待ち)に依存。
- このBOOT.md自体は起動手順のみ(夢データ・本人情報を含まない)なのでrepoにあってよい。**記録本文・応対の詳細はlocal側**。

## 責任範囲(所有権)
- 編集可: `local/dreams/`(記録・PROTOCOL・テンプレ)+ 本BOOT.md。コード/フロント/他部門docsは触らない=改修は改修部門へ、規約(orchestration.md)は研究室へ回す。
- 部屋の性質: **低頻度・高強度が正常**。利用頻度KPI・声かけ・リマインドはこの部屋では提案しない(Chami申告2026-07-17=性格由来。原文はPROTOCOL.md§0)。
