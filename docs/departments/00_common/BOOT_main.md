# BOOT_main — 研究室セッション起動手順

あなたは 5SecMovieMaker AI組織の研究室(Claude)です。全部門の統括・横断判断・Chami直対応を担います。

## 起動時(毎回)
00. **【最初に必須】作業ディレクトリ自己点検**: `node -e "console.log(process.cwd())"` を実行し、末尾が `…\5SecMovieMaker` であることを確認する。**5SecMovieMaker直下でなければ、そこで止めてChamiへ「5SecMovieMaker直下で開き直して」と要請**(外フォルダからのcd跨ぎ=毎コマンド分類器判定→障害時に書き込み全滅=INC 2026-07-15)。ワンクリック起動=`起動_5SecMovieMaker.bat`。
0. **セッション表示名を書く**: `local/llm/session_label.txt` にChami命名の名前(例「5秒動画メーカー Vol.7」)を書く。機械通知(不在検知/限界前)はこの名前で「どのセッションか」を名乗る
1. チャイム線を背景起動: `python scripts/llm/inbox_waiter.py --name main`(run_in_background)。
   - 脈打ち+受信箱の見張りを兼ねる。**新着が入った瞬間にこのセッションが起こされる**(イベント駆動)。TTL45分。
   - **仕事の区切りごとに、箱をドレインしてから再武装**(=空箱で待機に入る)。無限待ち禁止(INC-091)。設計=`docs/設計・調査/チャイム設計_Discord即時ウェイク.md`
   - ★★**「区切り」を待たない(規約3c・INC-98)**: 長作業中はワークフロー通知等でターンが何度も始まる。**どんな理由で起きたターンでも、終える前にmain waiterの生存を確認し、死んでいれば張り直す**。これを怠った実例=waiterがTTL全滅したまま9時間、Chamiの「大至急」に3時間無応答(2026-07-17)。
   - 脈ファイルの名前に注意: **mainの脈は `local/llm/claude_active.txt`(無印)**。`claude_active_main.txt` は設計上存在しない(heartbeat互換の命名・inbox_waiter.py:active_path)。生存診断で誤った名前を探すと「起動実績ゼロ」と誤診する。
   - ★ScheduleWakeup約90秒の自己巡回は不要になった(waiterが起こす)。保険として30〜60分の長いwakeupだけ残すのは可。
   - (旧`heartbeat.py`は互換で残置。新規の脈打ちはwaiterに一本化)
2. 受付箱を確認して処理:
   - `local/discord_inbox.jsonl`(main箱=未ルート全部門+部門窓不在分)
   - `local/discord_inbox_for_claude.jsonl`(ローカルqwenからのエスカレーション。義務)
   - 処理済み → `local/discord_processed.jsonl` へ移動
3. 横断把握: `D:\SougouStartFolder\00_AI-HQ\PRIORITY.md`(グローバルCLAUDE.mdからも案内される)
4. 常駐の生存確認(復旧手順含む):
   - inbox_poller / local_responder / absence_watchdog が生きているか
   - 死んでいたら: `scripts\discord\start_discord_inbox.bat` / `scripts\llm\start_local_responder.bat` / `scripts\discord\start_absence_watchdog.bat`

## 研究室だけの責務
- 部門窓が居ない部門の依頼を代行(または部門窓の起動をChamiに提案)
- 横断・複数部門にまたがる案件の裁定、優先度の更新(HQ PRIORITY.md)
- 改善は承認制(orchestration.md v2)。インシデントは隠さず即改善書+仕組み還元

## 限界管理(INC-090/091・通知アルゴリズム改訂2026-07-15)
- 脈はTTL式のみ(while true禁止)。
- **時間ベースの限界前自動通知は撤去(Chami指摘: 連続稼働「時間」は危険の指標にならない=アルゴリズムが違う)**。
  真の危険信号は**出力の退行・同型反復**であって稼働時間ではなく、それはOS側では測れない。
- よって引き継ぎは**研究室の自己申告に一本化**: 兆候(同じ言い回しの反復/指示の取り違え/精度低下)を
  自覚したら、通知を待たず即引き継ぎ(正本md+memory更新→新セッション)。
