---
name: context-budget-audit
description: Claude/Discord組織運営でcontext肥大、週間利用量、部門間往復、retryループ、memory汚染の原因をメタデータと実行回数から診断する時だけ使う。通常のコード量見積り、性能測定、秘密ファイル調査には使わない。
---

# Claude/Discord context予算監査

組織境界は [README](../../../README.md) と [CLAUDE](../../../CLAUDE.md)、runtimeの場所は [layout.json](../../../config/layout.json) から解決する。この監査では会話やpromptの中身を読まず、まず発生量の構造を特定する。

## 収集してよいもの

- ファイル名、パス、byte数、更新時刻、件数、保管階層
- process数、起動時刻、再起動回数、Scheduled Taskの間隔
- queue件数、delivery回数、retry回数、fan-out先の数、成功/失敗/429などの集計
- skill数、各skillの配置先と参照数、project memoryのファイル数と合計byte数
- payloadを除いたmessage ID、相関ID、時刻、部門、状態遷移

本文、prompt、添付、memory本文、token/credential/cookie/passphrase、環境変数の値は読まない。既存の集計ツールがpayloadを伏せることを確認してから使う。秘密らしい対象は `sensitive-boundary` の範囲として切り離す。

## 診断

1. 時間窓を固定し、入口メッセージ数を基準にする。
2. `入口 × 部門fan-out × retry/delivery × 再送・監視回数`を段階別に集計し、増幅点を示す。
3. 正常な定期処理、ユーザー操作、障害retry、重複配送、部門同士の自動応答を分ける。
4. context側は、自動読込ファイル数・byte数、毎便注入、必要時読込を分ける。大きいだけで不要と断定せず、参照と責務を確認する。
5. 週間利用率だけから原因を推測しない。観測できた便数、再試行、fan-out、context byte数で説明する。

## 改善

依頼に実装が含まれる場合も、既存機能を消さずに増幅だけを抑える。

- message/correlation IDによる冪等化
- bounded retry、指数backoff、circuit breaker、429時の停止条件
- 同じ状態を再通知しないdebounce/coalescing
- 部門間自動返信のhop上限と自己返信禁止
- 常時注入を薄い索引へ替え、詳細を部門・機能ごとのskillまたは参照へ分離
- memory整理は削除ではなく、manifest付きの復元可能な退避を優先

変更前後を同じ時間窓と集計定義で比較する。古いsessionは既に読み込んだcontextを保持するため、memory整理の効果確認は新しいsessionで行う。
