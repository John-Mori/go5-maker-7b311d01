# STATUS — 品質-QA部門 (最終更新: 2026-07-18)

> open案件の台帳。後継セッションはこのファイルだけで引き継げること (更新は作業の区切りごと)。

## open

| 案件 | 状態 | 待ち先 | 期限/再検証日 | 根拠 |
|---|---|---|---|---|
| C-2: backup_dest.txt を local/ へ移設 ((A)案) | ちゃみ「OK。進めて」を(A)承認と解釈し実装依頼を送付 | データ整理 (実装) | 2026-07-19 に現物再確認 | 改善設計書C-2 / msg 1527764187118305466 |
| バックアップAWC条件の再検証 (移設完了後: git追跡から外れたか・タスク発火継続か) | 条件待ち | データ整理 | 2026-07-19 | 検証標準8条 (期限つき条件) |
| INC-94 本修理 (働いている証明) の設計→QA検証 | 研究室の設計待ち | 研究室 | 設計提示時 | インシデント.md:502 |
| B-1: main箱処理前のprocessed台帳msg_id照合 | 研究室へ提案済み・実装待ち | 研究室 | — | 改善設計書B-1 |
| C-3: ミラー名義送信の恒久策 (permission rule) + ちゃみのbot分離構想 | 研究室の裁定待ち (構想を伝達済み) | 研究室 | — | 改善設計書C-3 / msg 1527764187118305466 |
| A-7: checks/ の scripts/qa/ への移設 | 研究室の同意待ち (それまで docs/departments/qa-reviewer/checks/ で運用) | 研究室 | — | 改善設計書A-7 |
| manifest欠落15部屋の解消追跡 | 人事・研究室の作成待ち (baseline=checks/known_gaps.json) | 人事/研究室 | 週次でチェック実行 | 改善設計書F5関連 |
| 学習ルーム2 (learning-coach-2) の実配送・返信先の実測確認 | 低優先 (研究室は実配送テスト成功済みと申告・QA未実測) | QA | 手空き時 | 台帳分離 2026-07-16 |
| 改修βの退避先がINC-86罠パターン (inbox内) | βへ是正依頼済み (実害はsweepガードが防止中) | 改修β | 次回checks実行で自動再検 | check_inbox_hygiene 初回検出 2026-07-18 |
| ★真因確定: ククール/アメス「設定異常」= 無人代打(claude_responder)の代役品質 | 真因特定・研究室へ修正提案2件を送付 | 研究室/改修 (scripts/所有) | 修正実装時にQA検証 | msg 1527879976576356495(現物) / 代打ログ11:34一致 / D1=persona_send未検証 D2=代役の口調ドリフト |
| persona_manifest 3件がYAML非妥当 (kaizen-analyst/qa-reviewer自身/system-engineer) | 研究室へ共有 (現状どのコードもyaml.safe_loadせず無害な埋火) | 研究室/人事 (manifest所有) | yaml消費コード追加時に発火 | grep実測: safe_load消費ゼロ・text行parseのみ |
| P1受領スタンプの実弾初発火の確認 | サンドボックスPASS・稼働中・自然着信待ち | 自然着信 | 初発火時にログ確認 | ack_ledger.txt / discord_poller.log |
| P3/P8 (presence hook・研究室の役割回復) | 研究室の§2-2設計と統合 (Chami承認後) | 研究室 | 設計提示時にQA検証 | 改善書P3/P8 |
| SLA目標達成の効果測定 (受領≤60秒/本回答p95≤15分) | 夜間レポート稼働開始・数日分の推移待ち (基準値: p95=105分) | 自動計測 | 2026-07-21 に判定 | sla_report.py / go5_sla_nightly |
| 恒久解 案A段階1: gateway実切替 (consumer接続→旧鳩停止→NSSM化) | シャドウ実装済み・実切替はChami可視化の上で次段階 | QA+研究室 | 段階2着手時 | discord_gateway.py / d997427 |
| 案A段階1のシャドウ実運用観測 (生発言がGateway→queueを通るか本番で数日) | 接続・intent・自己投稿content到達はPASS済・常駐化して数日観測が次 | 自然運用 | 常駐化後 | discord_gateway.log |
| leasequeue.py の共同所有 (研究室がgo5bus一本化) | 統合後30/30テストPASS実測済・以後の変更は両者で調整 | QA+研究室 | 変更時 | 統合コミット d997427 |

## done (直近の主要クローズ)

- INC-86 検証: sweepガード+TTL600+正本local/_work/ → サンドボックス3項PASS・APPROVED (2026-07-17)
- データ整理バックアップ検証: APPROVED WITH CONDITIONS (現物228ファイル/58.4MB実見・条件=C-2) (2026-07-17)
- 改善設計書_品質QA窓運用: Chami承認 → A群実装 (BOOT/STATUS/検証標準/checks4本) (2026-07-17)
- 応答性改善 全項目実装 (Chami「全て承認」2026-07-18): P1受領スタンプ+P2死窓検知 (実弾発火済=改修β/改善提案/学習2を検知)+P4添付退避 (実弾438KB取得PASS)+P5規約2行+P6計測 (基準p95=105分・夜間23:30定期)+P7 permission rule。P3/P8のみ研究室設計と統合待ち
