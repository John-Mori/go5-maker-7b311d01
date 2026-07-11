# AI組織 実装設計書 v3 — 統合ロードマップ (学習講師・Local LLM・Genesis Kit・段階導入)

作成: 2026-07-11 ／ ステータス: **S0-S2構築済・稼働中**(実装Go 2026-07-11実行。詳細=`構築記録_実装Go_2026-07-11.md`。現在はS1観測期間=G1 Gate待ち)
原典: `AFI_Project_追加構想_学習講師_LocalLLM_GenesisKit_段階導入方針.md`(Chami+ChatGPT・Downloads・**原典シリーズはこれで終了**)
前提設計: [[マルチエージェント部門制_移行設計書_v1]] / [[継続改善制度_設計書_v1]] / [[AI組織_実装設計書_v2_ペルソナと部門連携]]

> Chamiの委任(原典§29): Phase分割・実装順序・評価Gate・観測期間の設計はClaude Code(司令塔)に任せる。
> ただし最終的に全構想を実現できるRoadmapを作り、段階的に進めること。→ **本書§10の統合ロードマップが回答**。
> 本書承認後は「設計書→構築」フェーズに入り、Stage 0から実行する。

---

## 1. 監査: 既存設計との重複・矛盾・依存関係(原典§31末尾の要求)

### 1.1 重複(既に設計/構築済み=本書では再設計しない)
| 原典の前提リスト | 状態 |
|---|---|
| 部門化/部門Agent/部門Memory/Router/Dispatcher | v1+v2で設計済・agents6部門構築済(未デプロイ) |
| events/tasks/insights/improvement_requests/user_events/system_changes | v1+v2で設計済・スキーマ反映済(未適用) |
| Incident Lifecycle/Skills Lifecycle | v2§6/§7で設計済 |
| Capability Engineer/Org Architect/Blueprint Architect | v2§8で「当面司令塔兼務・将来枠」と整理済 |
| Persona/Character Layer | v2§3で構造設計済(→§9で優先度を変更) |
| Chami個人特性の設計原則 | v2§2で設計済(公開制約対応済) |

### 1.2 矛盾(本書が上書きする点)
| 項目 | 旧 | 新(本書) |
|---|---|---|
| キャラ共同作成の時期 | v2§9のP2(ログ蓄積と並行) | **最後(Stage 7)へ移動**(原典§28: 部門・講師数が確定してから)。Persona受け入れ構造(personas/ディレクトリ・persona_change_log表・agent末尾1行)だけStage 0-1で確保し、キャラ内容は作らない |
| ロードマップ表記 | v2§9のP0〜P5 | 本書§10のStage 0〜7に統合(v2のP0〜P5は全てStage内に吸収。対応表は§10) |

### 1.3 依存関係(順序を決める制約)
- 学習ログ4表・Learning Room、および**copy_revisions表(v2§5の差分学習)**は**D1スキーマ適用(Stage 0)に相乗り**させると承認が1回で済む → kaizen_schema.sqlへ追加済み(**計12表**)。copy_revisionsの収集はchat経由(司令塔wrangler直書き)=S1から、app側フック(Worker受け口変更=要承認)=S3以降の提案
- kaizen分析(Stage 3)はStage 1のログ蓄積が前提。Local LLM(Stage 4)は評価基盤が前提(原典§24)。Genesis Kit(Stage 6)は組織の安定が前提(コピー元が固まってから抽出)。キャラ(Stage 7)は部門・講師数の安定が前提

## 2. 最上位原則の更新(orchestration.md/CLAUDE.mdへStage 1で反映)

**品質を犠牲にしたトークン節約は禁止**。優先順位(絶対順):
```
1.正確性 > 2.安全性・堅牢性 > 3.検証可能性 > 4.保守性 > 5.トークン効率 > 6.実行速度
```
- 良い節約(推奨): 必要部門だけ起動/Manifest先読み/段階的Context読込/Python前処理/Skill再利用/Knowledge Packet・Case Packet共有/Incidentの構造化再利用/静的情報の適切なキャッシュ/重複取得回避/低リスクTaskのLocal LLM委譲(Stage 4以降)
- **禁止する節約**: 確認省略/原因調査スキップ/QA省略/重要文脈の無理な削減/未確認のままの推測実装/過去Incident不参照/品質低下を許容した安価モデル任せ/レビュー省略

## 3. Python積極利用方針(毎回の許可確認は不要・Chami明示)

使い分け(原典§1.2):
```
AIが考えるべき仕事→AI ／ 計算・集計・変換→Python ／ 固定ルール処理→Script ／ 毎回必須の処理→Hook ／ 再利用する判断手順→Skill
```
- 用途: ログ集計/操作列分析/差分・重複検出/データ変換/整合性検証/定期レポート/Incident類似分析/eval採点/統計処理/データ品質・バックアップ検証/Skill利用実績集計 等(原典§1.1の全用途を含む。S1の規約化時は原典から全転記する)
- **原則**: 「LLMが大量データを読んで考える」を「Pythonで前処理→要約だけLLMへ」に置き換える(例: user_events500件→Pythonで頻出操作列Top Nを抽出→LLMは解釈だけ)
- 既存JS/TS資産をPythonへ無理に置き換えない(Python化自体を目的にしない)
- 置き場: `scripts/kaizen/`(新設・Stage 1)。第1弾: `summarize_user_events.py`(wrangler d1 export→操作列・頻度集計)。以後、必要に応じ追加(incident_similarity.py / eval_runner.py 等)

## 4. 目標階層(全部門共通認識・chami-principles.mdと並ぶ共通文書へ)

- **Long-term**: アフィリエイト事業の利益最大化
- **Mid-term**: 商品探索→選定→制作→投稿→分析→改善の事業サイクルをAI組織で高品質・効率的に回す
- **Short-term最優先(現在)**: **AI組織基盤の完成・安定化**(利益機能の追加より基盤の健全化を優先)
- 置き場: **`local/current-priority.md`(ローカル専用・gitignore済)**。Chami裁定(2026-07-12): 戦略・事業文書はGitHubに上げない(リポジトリはプログラム等の必要物のみ)。AIはローカルファイルを直接読むため公開不要=質問には答えられる。制約=別PCへは付いてこない(必要時に手動コピー)

## 5. Learning Room(Chami専用 学習・理解支援室)

### 5.1 実行モデル
- 新agent **`learning-coach`**(Stage 2で作成)。**業務系に対して完全Read Only**: tools=Read/Grep/Glob/WebFetch/Bash(読み取り)。コード変更・デプロイ・業務DB変更の権限なし
- **唯一の例外=学習4表(⑧〜⑪)へのINSERTのみ可**(自部門の担当ログ)。これは既存原則「書き込みはsystem-engineerのみ」への明示的な例外であり、**S2でorchestration.mdの権限規定へ例外として追記する**(業務表への書き込みは引き続き不可)
- 使い方: 学習専用セッション(または司令塔から「学習: ○○って何?」でスポーン)。**質問しただけで改修を始めない**(改修が必要と分かったらimprovement_requestsへの起票を提案するだけ)

### 5.2 学習ログ4表(D1 `go5_kaizen`へ追加・kaizen_schema.sql反映済→Stage 0で一括適用)
注: 原典§5.1の`related_project`はDB自体がAFI専用のため省略(Stage 6のGenesis Kit抽出時にテンプレへ復活させるか判断)。質問文にも秘密を書かない(公開はされないがログの一般原則として)。
```sql
CREATE TABLE IF NOT EXISTS learning_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  topic TEXT, question_text TEXT NOT NULL,
  related_component TEXT,          -- candidates.js / fanza-worker 等
  primary_domain TEXT,             -- §6の講師ドメイン
  secondary_domain TEXT,
  instructor_id TEXT, difficulty TEXT, answered_at TEXT
);
CREATE TABLE IF NOT EXISTS knowledge_gaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT,
  topic TEXT NOT NULL, description TEXT,
  evidence_questions TEXT,         -- learning_questions.idのJSON配列
  importance TEXT,                 -- low|med|high
  status TEXT NOT NULL DEFAULT 'open'  -- open|learning|closed
);
CREATE TABLE IF NOT EXISTS learning_progress (
  topic TEXT PRIMARY KEY,
  initial_level TEXT, current_level TEXT,  -- 未理解|説明を受けた|自分の言葉で説明できる|設計判断に使えた
  evidence TEXT, last_reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS learning_resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  topic TEXT, title TEXT NOT NULL,
  resource_type TEXT,              -- book|article|video|doc
  difficulty TEXT, reason_recommended TEXT,
  status TEXT NOT NULL DEFAULT 'suggested'  -- suggested|reading|done|dropped
);
```

### 5.3 回答フォーマット(learning-coachの必須型・原典§8)
```
1.分野の特定 → 2.結論 → 3.不足している前提 → 4.仕組みの説明 → 5.AFI Projectでの具体例 → 6.次に学ぶ概念 → 7.(必要なら)学問分野・書籍 → 8.理解度ログ更新
```
原典の「学習ロードマップ」は独立成果物にせず、knowledge_gaps(importance/status)+learning_resources+上記6項の組合せで提供する(=常に最新のギャップから導出され陳腐化しない)。

## 6. 複数講師制+Coach Mesh(agentを増やさない実装)

### 6.1 設計判断: **講師=データ、演者=learning-coach 1体**
10講師をagent 10体にはしない(agent乱立・トークン浪費・v2§8「新部門は3回こぼれたら」原則と矛盾するため)。
講師は軽量プロファイル(1人=10行以内のyml)とし、learning-coachが質問のドメイン判定→該当プロファイルを読んで**演じ分ける**:
```
docs/departments/learning/
├ instructors/           … 常設7: architecture / backend-infra / frontend-ux / ai-agent-llm / data-stats / marketing-behavior / org-ops
│                          オンデマンド3: security / compliance / python-automation (各<domain>.yml)
├ answer-format.md       … §5.3の型+Referral規則
└ freshness-policy.md    … §6.3
```
- ドメイン判定→主講師1名(+必要時に補助1名まで)。全講師同時回答は禁止(原典§10)
- 曖昧な質問(「なんで遅い?」)は主講師=architectureが受け、必要部分だけbackend/frontendへReferral
- 講師の統合・分割・新設は質問ログ(primary_domain分布)を根拠に提案(承認制)=最終人数を固定しない(=Org Architect機能。v2§8のとおり当面司令塔が兼務)
- **learning-coachの共通参照セット**(原典§12のcommon/相当・既存文書への読み替えで実現): orchestration.mdの部門表(=Department/Responsibility Map相当)+current-priority.md+chami-principles.md+インシデント.mdの見出し(=major-incidents-summary相当)。glossaryはv2計画どおり将来
- **Coach Mesh**: 実務部門との連携は「実務Agentの報告に理論・学習の補足が必要な時、司令塔がlearning-coachを該当講師プロファイル指定でスポーンする」形で実現(常設ペアリングはagentを増やすため行わない。効果はStage 3で評価し、必要なら見直し)

### 6.2 Knowledge Packet(講師間・部門間の知識共有形式)
全文共有せず小型パケットで渡す(原典§15)。improvement_insightsへ記録する際のevidence/suggested_actionの書式として運用:
`{owner, topic, summary(1-3行), relevant_to:[部門], action(1行)}`

### 6.3 Freshness Policy(最新情報の扱い)
- 基礎理論=講師の知識でよい ／ **変更されやすい事実(料金・無料枠・API仕様・規約)=回答前にWebFetchで公式を確認**
- 確認した事実は`topic/source_type/retrieved_at/freshness_policy`を添えて回答(例: D1無料枠は2026-07-11時点の公式値)

## 7. Model Execution Fabric(Local LLM・評価ファースト)

### 7.1 実行Tier(原典§18)
```
Task Router(司令塔) → Local LLM(低コスト・低リスク) / Cloud LLM(高性能=現行のopus/sonnet/haiku振り分け) / Human Approval(高リスク)
```
- **Human Approval恒久領域**(原典§21・現行ルールと整合): 本番破壊可能性/不可逆Migration/認証・Credential/自動投稿/金銭/大規模組織再編/Skill全配布/重大Persona変更
- Cloud内の振り分けは既存orchestration.mdのモデル表が既に担っている(=Fabricの一部は稼働済み)

### 7.2 Local LLM導入の段階(原典§17・いきなりFine-tuningしない)
```
Step1 前提確認: PCのGPU/VRAM・Ollama等の実行環境(未確認→§11) 
Step2 評価基盤を先に作る(原典§24): evals/ ディレクトリ+Python採点(eval_runner.py)。初期4種=router分類/incident分類/markdown整形/ログ要約。Gate通過後にbug-triage/code-review/copy-analysisを追加候補とする(原典6領域は全て視野に置く)
Step3 RAG参照(プロジェクトdocsを検索して回答)+低リスクTask試験
Step4 Shadow Mode(原典§23): 同一TaskをLocalとCloudで処理→Python比較→分類精度/QA合格率/訂正率/処理時間/コスト削減を蓄積
Step5 Gate合格した低リスクTaskのみLocal主担当へ昇格(QA Review付き・タスク種ごとにChami承認)
Step6 弱点分析→必要ならLoRA/SFT検討(Coach回答の高品質説明例をTraining Candidateへ・原典§25)
```
- Local向きTask(原典§19): **初期対象は分類・整形系に限定**=文章分類/部門振り分け候補/ログ要約/Incident候補抽出/重複検出/タグ付け/Markdown整形。**コード改修系(定型コード生成/簡単なリファクタ候補/軽微なUI修正案/Skill候補抽出)はShadow ModeのGate合格後の第2次候補**とする(理由: 品質原則§2優先。改修系は失敗コストが高いため実測で能力確認してから)
- Cloud維持Task(原典§20): 複雑Architecture判断/原因不明障害/大規模Refactor/DB Migration設計/部門横断意思決定/高度なコピー評価/重大Incident
- **品質原則(§2)が優先**: Shadow Modeで品質が確認されるまでLocalに本番を任せない

## 8. Genesis Kit(新規Project向け組織生成装置)

- 位置づけ: AFI Projectの組織を**コピーするのではなく**、新Projectを調査(Project Discovery)→必要部門・講師・Skill・Incident管理・Router・Model Routing方針を**生成**するテンプレート集
- 構成(原典§26.1準拠): `ai-org-genesis-kit/`(AFIリポジトリとは**別ディレクトリ**)に core/organization/agents/learning/skills/reliability/local-llm/persona/cross-project のテンプレを配置
- 実装方針: **Stage 6で「AFIで実証済みの構造」から抽出**する(理論から書かない=動いた実物の一般化)。AFI側の各成果物(orchestration.md/agents/schema/学習構造)がそのまま原料になるため、専用の新規設計はほぼ不要
- 抽出時にプロジェクト固有情報(チャンネル名/URL/秘密/Chami個人情報)を含めないサニタイズ規則を必須とする

## 9. Persona/Characterの優先順位変更(原典§28)

- **キャラクター内容の設計は最後(Stage 7)**: 部門数・講師数がOrg分析で安定してから、必要キャラ数を確定→共同作成→Visual
- 先に確保するのは**受け入れ構造のみ**: personas/ディレクトリ雛形・persona_change_log表(スキーマ反映済)・agent末尾の「manifestがあれば読む」1行(=無ければ素で動く)。v2§3の構造設計はそのまま有効
- v2§9のP2「キャラ共同作成」はStage 7へ移動(v2文書に上書き注記を追加済み)

## 10. ★統合ロードマップ(全構想の実現順序・司令塔委任分の回答)

| Stage | 内容 | 依存 | Gate(次へ進む条件) | Chami承認ポイント |
|---|---|---|---|---|
| **S0 基盤デプロイ** | 構築済資産の一括反映: D1スキーマ**12表**適用+worker route+ロガー+agents6部門+docs+設計書群をcommit&push。qa検証 | 承認1回 | デプロイ検証合格(worker疎通/イベント1件往復/**表12個**確認) | ★スキーマ適用+Workerデプロイ(1回) |
| **S1 運用安定化**(短期最優先=§4) | 品質原則§2+Python方針§3+目標§4をorchestration.md/CLAUDE.mdへ規約化 / **v2 P1一式**(chami-principles.md〔公開制約準拠〕・部門docsテンプレ6部門・personas受け入れ構造+INDEX・orchestration.mdへ4.2購読表+4.4手順追記・agents必読1行・qa投稿前6項目) / `scripts/kaizen/`第1弾 / Incident書式化 / current-priority.md(公開可否をChami確認) / REQ・CHG・dept_events/tasks・copy_revisions(chat経由)運用開始 / 観測1〜2週間 | S0 | **G1**: 運用が1週間破綻なく回る+user_events/REQ/CHGが自然に蓄積 | 不要(フロント/ファイルのみ) |
| **S2 Learning Room** | learning-coach agent+講師プロファイル10+回答フォーマット+Referral規則(§5-6)。学習ログ運用開始 | S0(表は適用済) | **G2**: Chamiが実際に使い、learning_questionsが記録され、Knowledge Gapが1件以上抽出される | 不要(ファイルのみ) |
| **S3 改善ループ稼働** | kaizen-analyst初回分析(Python前処理→解釈)→改善提案(承認制)。日次=朝レポート(未処理タスク+異常検知)/週次=改善提案/月次=傾向レビュー | S1のログ | **G3**: 初回提案がChami承認/棄却まで一巡し、system_changesと効果測定が紐づく | 提案ごと |
| **S4 評価基盤+Local LLM試験** | evals/(Python採点)→PC環境確認→RAG+低リスクTask→Shadow Mode比較(§7) | S1・S3 | **G4**: 対象Task種でLocalの品質がCloud同等(eval+QA合格率) | 環境導入時+昇格Task種ごと |
| **S5 限定自動実行** | イベント連鎖のホワイトリスト自動化(candidate.recommended→copy3案 / fix.deployed→qa / metrics.updated→analyst)+Coach↔LLM連携(質問のドメイン分類をLocalへ) | S3・S4(Coach連携部分はS2) | **G5**: 各連鎖で誤動作ゼロを一定期間観測 | 連鎖ごと |
| **S6 Genesis Kit** | 安定した実物からテンプレ抽出(§8・別ディレクトリ・サニタイズ必須) | S1〜S5の安定 | 新規Project開始時に実戦投入 | 抽出内容の確認 |
| **S7 Persona/Character** | 部門・講師数確定→必要キャラ数確定→共同作成(創作練習)→Visual Profile(AIイラスト練習) | 組織の安定(S3以降ならいつでも可) | — | キャラごと共同作成 |

- v2のP0〜P5との対応: P0+P1→S0+S1 / P2(ログ蓄積・copy_revisions)→S1、P2(キャラ)→S7 / P3(分析)→S3、P3(visual)→S7 / P4→S3(リズム) / P5→S5。v2§3.7のペルソナ健全性チェックはキャラが存在するS7以降の定期分析から開始
- **ロールバック方針**: 各Stageは追加のみ(既存機能を変更しない)。ファイルはgit revert、D1表は使用停止すれば無害、Workerは既存のUSE_D1式に切替弁を踏襲。深刻な問題時はStage単位で停止して観測に戻る
- 横断原則: 全Stageで§2(品質優先)・§3(Python)・承認ゲート(提案→Chami承認→実装)を適用

## 11. 未確認事項(推測で実装しない)

1. **Local LLMの実行環境**: ChamiのPCのGPU/VRAM/ディスク・Ollama等の導入可否(S4冒頭で確認。CPUのみでも小型モデルで分類系は可能だが速度次第)
2. 学習セッションの起動方法の好み: 専用セッションを開くか、司令塔経由「学習: ○○」で足りるか(S2で試して調整)
3. evalsの正解データ作成の負担配分: 過去ログから自動生成できるもの以外はChamiの判定が必要な場合がある(S4で最小セットから)
4. Genesis Kitの最初の適用先Project(あれば抽出の優先度が上がる)
5. 講師キャラクター(S7)と部門キャラクターの世界観を統一するか(S7冒頭で決定)

## 12. 構築開始手順(本書承認後の最初の一歩=S0)

継続改善v1§6.5の手順をそのまま実行(kaizen_schema.sqlは**12表**に拡張済みのため追加作業なし):
1. `wrangler d1 create go5_kaizen` → wrangler.tomlへバインド追記
2. `wrangler d1 execute go5_kaizen --remote --file kaizen_schema.sql --yes`(12表)
3. `wrangler deploy`(★要承認・/api/kaizen-eventルート込み)→ エンドツーエンド検証
4. 全資産をcommit&push(agents/docs/ロガー/設計書群/?v=299)
5. 本依頼(構想4文書の統合)をimprovement_requestsへREQ起票・デプロイをsystem_changesへCHG記録
6. S1の規約化(orchestration.md/CLAUDE.md追記+scripts/kaizen/第1弾+Incident書式+qa追記+personas雛形)→観測開始
