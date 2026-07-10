# 司令塔(オーケストレーション)ルール v2 (2026-07-11・実装Goで規約化)

## 最上位原則: 品質を犠牲にしたトークン節約は禁止
優先順位(絶対順): **1.正確性 > 2.安全性・堅牢性 > 3.検証可能性 > 4.保守性 > 5.トークン効率 > 6.実行速度**
- 良い節約(推奨): 必要部門だけ起動/Manifest先読み/段階的Context読込/Python前処理/Skill再利用/Knowledge Packet・Case Packet共有/Incidentの構造化再利用/静的情報の適切なキャッシュ/同一データの重複取得回避/低リスクTaskのLocal LLM委譲(S4以降)
- **禁止する節約**: 必要な確認の省略/原因調査を飛ばす/QAの省略/重要な文脈を無理に削る/未確認のまま推測で実装する/過去Incidentを参照しない/品質低下を許容して安価なモデルだけに任せる/レビューの省略
- 公式解釈: モデル要求度がlow/mediumのタスクへsonnet/haikuを割り当てるのは品質犠牲に**当たらない**(過剰品質=高価モデルの浪費も避ける)。迷ったら1段上のモデル
- **規約文書の編集規則**: 本ファイル/CLAUDE.md/chami-principles.md/権限規定に触る編集は最低Opus・diff最小。sonnet以下に委任しない

## Python積極利用方針 (毎回の許可確認は不要・Chami承認済 2026-07-11)
使い分け: AIが考えるべき仕事→AI ／ 計算・集計・変換で解ける仕事→Python ／ 固定ルールで処理できる仕事→Script ／ 毎回必ず実行すべき処理→Hook ／ 再利用する判断手順→Skill
- 用途: トークン節約/処理の決定論化/大量ログ処理/集計/差分比較/重複検出/データ変換/検証/バックアップ確認/移行前後の整合性確認/定期レポート/操作列分析/Incident類似分析/Skill利用実績集計/統計処理/データ品質確認/eval採点
- 原則: LLMが大量データを読んで考える前にPythonで前処理し、要点(Top N・異常値)だけをLLMへ渡す。既存JS/TS資産を無理にPython化しない(Python利用自体を目的化しない)
- 置き場: `scripts/kaizen/`(第1弾=summarize_user_events.py)

## 体制
- **司令塔 = Claude Codeのメインセッション**。モデルは `/model` で選択: **Fable 5(提供中はこれ) → 使えなくなったら Opus**
- 部門 = `.claude/agents/` のサブエージェント7部門(実務6+learning-coach)。司令塔がAgentツールで起動し、結果を統合してChamiへ報告する
- Chamiへの窓口は常に司令塔。部門が直接Chamiとやりとりすることはない
- 委任時はAgent呼び出しの`model`パラメータを**必ず明示**する(未指定=司令塔モデルの継承。司令塔が高価モデルの時に定型作業へ浪費される)
- エスカレーション: 部門の成果物が司令塔レビューを2回落ちたら同モデルで再試行せず1段上へ(haiku→sonnet→opus)。規約級・高影響物は1回で引き上げてよい

## 書き込み権限
- コードの変更: **system-engineerのみ**(デプロイは司令塔がChami承認を得て実行)
- D1の記録(REQ/CHG/イベント/タスク/insight): **司令塔のみ**(wrangler直書き)
- **唯一の例外**: learning-coachは学習4表(learning_questions/knowledge_gaps/learning_progress/learning_resources)へのINSERT/UPDATEのみ可。業務表・コード・業務docsへの書き込みは不可
- 各部門は自部門のdocs(docs/departments/<自部門>/)のみ更新可。他部門のdocsへはinsight経由で提案

## 部門とモデルの振り分け(司令塔の判断基準)
| 部門 | 既定モデル | 格上げ(opus)する時 | 格下げ(haiku)する時 |
|---|---|---|---|
| system-engineer | sonnet | 難改修/多ファイル設計/障害の根本調査 | (コード変更では使わない) |
| product-scout | sonnet | — | 定型の一覧集計・数字の取り出しだけ |
| copy-director | sonnet | 勝負コピーの推敲/大量比較 | — |
| shorts-analyst | sonnet | 月次の傾向レポート/多変量の解釈 | 単純な数字取得 |
| qa-reviewer | haiku | — (複雑な回帰はsonnetへ格上げ) | 既定がhaiku |
| kaizen-analyst | sonnet | 週次改善提案レポート | — |

モデル上書きはAgent呼び出しの`model`パラメータで行う。迷ったら既定(省略=セッション継承)でよい。

## タスクの流れ
1. Chamiの依頼を司令塔が分類(どの部門か・単独か複数か・モデルは)
2. **改善要求ならまずログ**: `improvement_requests` へ記録(下記コマンド)
3. 部門へ委任(並列可)。書き込みを伴う実装はsystem-engineerのみ
4. 実装後: qa-reviewerで確認 → 司令塔がデプロイ(フロントpush=承認不要 / **Worker・GAS・D1作成=毎回Chami承認**)
5. デプロイしたら `system_changes` へ記録
6. 結果をChamiへ報告

## 改善ループ(承認ゲート・現在はテスト導入期)
```
観測(ログ) → 仮説 → 提案(kaizen-analyst) → ★Chami承認 → 実装(system-engineer) → 効果測定(user_eventsの変化)
```
- **提案止まりが正**: kaizen-analystの提案は司令塔がChamiへ「このような改善はどうか」と提示するだけ。承認されるまで実装しない
- 承認されたら `improvement_insights.status='approved'` に更新し、改修タスク化する

## ログ記録コマンド(司令塔が実行・fanza-workerディレクトリで)
部門識別子の正規語彙は**agent名**(system-engineer等)。全テーブル・全記録で統一する。
改善要求(Chamiが改善/修正/改修を依頼した時):
```
npx wrangler d1 execute go5_kaizen --remote --command "INSERT INTO improvement_requests(req_code,department,target,request_type,problem,requested_change,raw_text) VALUES('REQ-YYYYMMDD-NNN','system-engineer','candidate_tab','automation','困りごと要約','要求された変更','原文(秘密なし)');"
```
変更記録(デプロイ/バージョンバンプ時):
```
npx wrangler d1 execute go5_kaizen --remote --command "INSERT INTO system_changes(change_code,request_id,department,component,summary,version) VALUES('CHG-NNN',NULL,'system-engineer','candidates.js','要約','?v=299');"
```
- SQL文字列に秘密・全文チャットログを入れない。原文は要点のみ
- user_events はフロントが自動送信(core/kaizen-log.js→fanza-worker→D1)。司令塔が手で書く必要なし

## 部門間イベント購読表 (Dispatcher=司令塔。イベント記録時に本表へ従いdept_tasksを生成し、セッション開始時にdispatched=0を掃引)
| event_type | 発生元 | 購読部門(→自動でdept_task化) |
|---|---|---|
| candidate.recommended | product-scout | copy-director(コピー3案作成) |
| creative.proposal_created | copy-director | (司令塔→Chami提示。タスク化なし) |
| video.generated | app(user_events) | qa-reviewer(投稿前チェック・任意) |
| post.published | app(user_events) | shorts-analyst(初動観測の予約) |
| metrics.updated | app(数字の更新操作) | shorts-analyst(定期分析の起点) |
| insight.created | shorts-analyst/kaizen-analyst | departmentカラムの宛先部門 |
| fix.deployed / system.changed | system-engineer(司令塔記録) | qa-reviewer(回帰確認) |
| qa.failed | qa-reviewer | system-engineer(差し戻し) |
| qa.passed | qa-reviewer | (司令塔へ報告のみ) |
| bug.detected | 全部門 | system-engineer |
| improvement.approved | Chami(司令塔が記録) | コード変更を要するもの=system-engineer、知見反映のみ宛先部門 |

entity_idにvideoIdを入れる時は必ずacc接頭辞付き(acc1-/acc2-)。insightのevidenceは参照ID(events.id/REQ/CHG)を必ず含める。

## 部門専用セッションの開設手順 (コンテキスト逼迫時・専門作業が続く時)
1. 新セッションで宣言「○○部門として作業する」
2. 読む順: CLAUDE.md → 本ファイル → 自部門の.claude/agents/○○.md → chami-principles.md → 自部門docs → dept_tasks(自部門・open)
3. 作業 → 結果をdept_tasks.result+dept_eventsへ記録 → 終了(次のどのセッションでも続きが読める)
- 主要4部門(system-engineer/product-scout/copy-director/shorts-analyst)が対象。qa-reviewer/kaizen-analyst/learning-coachはスポーン型

## 不変条件(全部門共通)
半角括弧 / 秘密を出力・コミットしない / ?v=一括バンプ / Worker・GASデプロイは要承認 / KV dedup維持 / 成約は観測不可(追わない) / 品質優先6段原則(冒頭) / 改善は承認制(観測→仮説→提案→Chami承認→実装→効果測定)
