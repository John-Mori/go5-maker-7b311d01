# AI組織 実装設計書 v2 — Chami運用原則・ペルソナレイヤー・部門連携(イベント駆動)

> **⚠️上書き注記(2026-07-11)**: キャラクター共同作成の時期(§9のP2)は **`AI組織_実装設計書_v3_統合ロードマップ.md` で最後(Stage 7)へ変更**された(Chami方針: 部門・講師数が確定してから)。Persona受け入れ構造(§3の設計)はそのまま有効。§3.7のペルソナ健全性チェックはキャラが存在するStage 7以降の定期分析から開始と読み替える。ロードマップ全体もv3§10のStage 0〜7が正。

作成: 2026-07-11 ／ ステータス: **設計・未実装**(承認後に段階導入)
原典: `AFI_Project_個人特性配慮・部門キャラクター人格設定構想.md` / `AFI_Project_AIエージェント部門化・連携構想まとめ.md`(いずれもChami+ChatGPT・Downloads)
前提設計(v1群・本書はその上位統合): [[マルチエージェント部門制_移行設計書_v1]](部門分離) / [[継続改善制度_設計書_v1]](ログ基盤・承認ループ・§6.5に未デプロイ資産の再開手順)

---

## 0. 本書の位置づけと現状

既に構築済み(ローカル・未デプロイ)のもの: 6部門agents / 司令塔ルール(orchestration.md) / D1 `go5_kaizen`スキーマ4表 / 行動ロガー。
本書は原典2文書の**新規要素**を、その基盤に統合する実装設計を定める:

| 新規要素 | 本書の章 |
|---|---|
| Chami Operating Principles(個人特性配慮の設計原則) | §2 |
| Persona Layer(部門キャラクター・業務Roleと分離) | §3 |
| 部門連携のイベント駆動化(dept_events/dept_tasks+Dispatcher) | §4 |
| コピー修正差分の学習(copy_revisions) | §5 |
| Incident lifecycle(記憶に依存しない障害対応) | §6 |
| Skill化ループ(同じ訂正を繰り返させない) | §7 |
| 将来のメタ部門(Capability Engineer / Org Architect) | §8 |
| 統合ロードマップ(P0〜P5)と承認ゲート | §9 |

## 1. 原典への訂正・整合(実装前に認識を揃える)

| # | 原典の記述 | 実態(確定済み) | 本書での扱い |
|---|---|---|---|
| 1 | shorts-analystの担当に「成約数」 | **成約は構造的に観測不可**(コンサルのアカウント/アフィリンク経由・確定) | 分析対象から恒久除外。実測KPI=クリック/再生/販売数(市場) |
| 2 | 「視聴継続率・スワイプ率・視聴者維持率」 | YouTube Analytics API(OAuth)未実装のため取得不可 | 当面はYouTube Studio目視の手動転記のみ。自動化は将来判断 |
| 3 | 部門名 `workflow-improvement-analyst` | 既存実装は `kaizen-analyst` | **同一部門**。kaizen-analystを正式名とし原典名をエイリアスとして併記 |
| 4 | D1に events/tasks/insights を新設 | insights相当(`improvement_insights`)は構築済み | 既存 `go5_kaizen` へ `dept_events`/`dept_tasks` を追加(新DB・新Workerは作らない) |
| 5 | 部門ごとに常設セッション | Claude Codeのセッションは常駐デーモンではない | §4.4の運用設計で実現(必要になった部門から分離・共有状態はD1とdocsが持つ) |
| 6 | 「AI同士の自由会話」 | 原典自身が非推奨 | 採用しない。構造化イベント駆動のみ(重要横断課題のみ司令塔が複数部門を並列スポーンして統合) |

## 2. Chami Operating Principles(個人特性配慮レイヤー)

### 2.1 成果物: `docs/departments/00_common/chami-principles.md`(全部門必読・簡潔に1ページ)

**★公開制約(最重要)**: 本リポジトリはGitHub Pagesで公開配信されるため、`docs/`配下のmdは予測可能なURLで誰でも閲覧できる。よって**医学的背景・個人史・特性のラベルはリポジトリに一切書かない**。ファイルには一般化された設計原則のみを載せる。背景情報(自己認識・服薬・営業職時代の経験の詳細)は**Claude自動メモリ(ローカル)にのみ保持**し、全部門への浸透は「原則」の形でのみ行う。ペルソナ関連ファイルも同様に公開前提で書く。

内容構成:
1. **前文(1行のみ・特性や医療に触れない)**: 「本原則は、注意力ではなく構造でミスを防いできた実務経験(Excel書類の手入力ミスをVLOOKUP/IF化で解消した等)から導かれた設計要求である」
2. **5原則と実装対応表**:

| 原則 | 全部門への実装指示 |
|---|---|
| 入力を減らす(二度入力させない) | 新機能は常に「URL1本→自動展開」「既定値」「引き継ぎ自動化」を第一候補にする |
| 記憶に依存させない | 「前も似たことが…」で始めない。`インシデント.md`検索(§6)・decisions.md・D1ログを先に引く |
| 注意力に依存させない | 人の目視確認に頼る手順を作らない。qa-reviewerのチェックリスト(§6.2)と自動検証に落とす |
| 同じ訂正を繰り返させない | improvement_requestsの反復を検出→Skill/ルール化を提案(§7)。同じ指摘を3回受けたら仕組み化検討 |
| 壊れにくく戻せる | 変更→検証→履歴→ロールバック可能、を標準順に。切替弁(USE_D1式)・git revert・persona rollback |

3. **経験→原則テンプレ**(将来Chamiが自分史を追加する時の記録形式・原典§13準拠):
```yaml
experience: (経験した問題)
response: (取った対処)
lesson: (形成された考え方)
current_principle: (現在の設計思想への影響)
system_implications: [(AIが配慮すべき具体原則)]
```
**追記先はClaude自動メモリ側**(公開制約のため)。リポジトリの本ファイルへは、そこから導かれた一般化済みのsystem_implications(原則)だけを反映する。全部門は新規タスク着手時にこのファイルを読む(1ページ以内厳守=トークン配慮)。

### 2.2 既存資産への反映
- 各部門agent(.claude/agents/*.md)の必読リストへ `chami-principles.md` を1行追加(P1で実施)
- qa-reviewerのチェックリストに「この変更は手入力/記憶/注意力への依存を増やしていないか」を1項目追加

## 3. Persona Layer(部門キャラクター)設計

### 3.1 3層分離の原則(原典§4準拠・最重要)

```
Department Role   … 責任範囲/判断基準/Tool権限/禁止事項/成果物形式 → 既存 .claude/agents/<dept>.md が正本。ペルソナ変更で一切変えない
Persona Profile   … 名前/一人称/口調/性格/思考スタイル/Chamiとの距離感 → personas/<dept>/persona_manifest.yml(+detail.md)
Visual Profile    … デザイン/衣装/配色/立ち絵/画像参照 → personas/<dept>/visual_profile.md(将来追加・通常業務では読まない)
```

**不変条件**: ペルソナは「言い方」だけを変える。判断基準・検査基準・案の本数(コピー3案等)・証拠要求・禁止事項は Department Role に固定され、ペルソナからは変更不能。例: QAのペルソナを優しくしても検査基準は緩まない。無口キャラにしても3案+比較理由は出す。

### 3.2 ファイル構造(トークン節約の階層化・原典§10準拠)

```
docs/departments/personas/
├ INDEX.md                       … キャラ名⇔部門ID対応表(司令塔のルーティング解決用・全キャラ1行ずつ)
└ <agent名>/                     … system-engineer / product-scout / copy-director / shorts-analyst / qa-reviewer / kaizen-analyst
   ├ persona_manifest.yml        … ★通常業務時に読む唯一のペルソナ情報。10行以内厳守
   ├ persona_detail.md           … 人格の詳細。標準項目: 性格の背景/思考スタイル/Chamiとの距離感/他部門との関係/口調サンプル。人格調整/創作作業時のみ読む
   └ visual_profile.md           … 外見設定。画像生成・キャラデザイン作業時のみ読む(P3まで空でよい)
```

manifest スキーマ(例・値は仮。実キャラはChamiと共同作成=§3.5):
```yaml
persona_id: qa-01
department: qa-reviewer
version: 1
name: (Chamiと共同作成)
first_person: 私
tone: calm_strict          # 口調タグ(短語彙で)
verbosity: concise
traits: [evidence_first, ambiguity_averse, methodical]
forbidden: [検査基準の変更, 結論を演技で曖昧にする, 部門責任の逸脱]
```

### 3.3 エージェントへの組み込み方(業務ロジックを汚さない)
- 各 `.claude/agents/<dept>.md` の末尾に**1行だけ**追加(P1):
  「人格: `docs/departments/personas/<自部門>/persona_manifest.yml` があれば読み、その口調・一人称で報告する。人格は表現のみに作用し、判断・基準・成果物形式には影響させない。」
- manifest未作成の部門は従来どおり(=人格なしでも業務は完全動作)。**人格レイヤーは完全にオプショナル**
- 司令塔は報告をChamiへ中継する際、部門を `【部門名/キャラ名】` 見出しで示す(識別補助)

### 3.4 バージョニング・変更ログ・ロールバック(原典§6-7準拠)
- **persona_versions = gitで代替**: manifestの`version`欄をインクリメントしてコミット。履歴=git log、ロールバック=git revert(+version戻し)。専用テーブルは作らない(6キャラにDB版管理は過剰)
- **persona_change_log = D1**(`go5_kaizen`へ追加・変更理由と効果を構造化で残す):
```sql
CREATE TABLE IF NOT EXISTS persona_change_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  persona_id      TEXT NOT NULL,
  department      TEXT NOT NULL,
  version         INTEGER NOT NULL,
  change_summary  TEXT,             -- 何を変えたか
  change_reason   TEXT,             -- なぜ(Chamiの依頼理由)
  expected_effect TEXT,             -- 期待する効果
  observed_effect TEXT,             -- 使用感・実際の効果(後日追記)
  requested_by    TEXT DEFAULT 'Chami',
  status          TEXT NOT NULL DEFAULT 'applied'  -- applied|rolled_back|superseded
);
```
- 変更フロー: Chamiが変更依頼→司令塔がmanifest/detail編集+versionインクリメント→commit→persona_change_logへ1行→数週間後にobserved_effectを追記(kaizen-analystの定期分析に含める)
- **visual_profile.mdの変更も同一フロー**(versionインクリメント+persona_change_log記録)。外見・衣装・配色・世界観の変更も「何を/なぜ/期待効果/使用感」を残す(原典§7)

### 3.5 キャラクターの作成プロセス(創作練習を目的に含める・原典§3準拠)
目的は識別性・創作練習に加え**「AI組織とのやり取り自体を楽しくする」=継続利用の要件**(原典§5.3・§16)。将来の簡略化判断でもこの目的を切り落とさない。
初期6キャラは**Chamiとの共同作成セッション**で作る(勝手に確定しない):
1. 司令塔が部門ごとに「役割から導かれる性格の方向性」を2〜3案提示(例: QA=厳格確認主義/Scout=好奇心発見型 — 原典§5.1の対応表を出発点に)
2. Chamiが選択・調整(名前/一人称/口調/距離感) — この対話自体がキャラ設計練習
3. manifest+detailに確定→persona_change_logへversion=1として記録
4. visual_profileはP3で同様に共同作成(AIイラスト練習・ノベルゲーム素材を意識した項目立て: 立ち絵想定/表情差分/配色/衣装)

### 3.6 ルーティングとの分離(原典§9準拠)
- 内部ルーティングは常に**agent名(department_id)**で行う。キャラ名はChami向け表示のみ
- Chamiがキャラ名で依頼した場合、司令塔が `personas/INDEX.md` で部門へ解決してから委任
- dept_events/dept_tasks/insightsの記録にはpersona情報を含めない(業務データと人格の分離)

### 3.7 ペルソナ評価指標(原典§12準拠・kaizen-analystの定期分析に統合)
観測可能な形に落とす: 部門識別のしやすさ(Chami主観メモ)/Chamiによる訂正回数(improvement_requests件数)/提案採用率(insights status比)/追加説明要求回数/平均応答長/役割逸脱の有無/**人格設定修正回数**(persona_change_log件数から導出)/**Chami満足度メモ**(楽しさ・使い心地の主観記録)。結果はpersona_change_log.observed_effectとimprovement_insightsへ。「なんとなく変える」を避け、変更理由→期待効果→観測→評価のループを回す。
- **版別評価の突合手順**: 業務ログにpersona情報は含めない(§3.6)ため、評価時はpersona_change_logのversion有効期間(created_at)とimprovement_requests/insightsの時刻を突合して版別に集計する(=どの版の下で訂正が減ったかを対応付ける)
- **ペルソナ健全性チェック(原典§11のCapability Engineer機能・kaizen-analyst定期分析へ統合)**: ①ペルソナがSkill/ルール発動を妨げていないか ②口調設定がトークンを浪費していないか(manifest10行超過の検出) ③役割説明と人格説明の重複 ④短縮余地。P3の初回分析スコープに含める

## 4. 部門連携のイベント駆動化(Chamiを伝書鳩にしない)

### 4.1 D1追加テーブル(`go5_kaizen`・kaizen_schema.sqlへ追記)

```sql
-- 部門間イベント(何が起きたか。追記専用)
CREATE TABLE IF NOT EXISTS dept_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  event_type  TEXT NOT NULL,        -- 下表(4.2)の型
  source_dept TEXT NOT NULL,        -- 発生元(agent名 or 'app' or 'chami')
  entity_id   TEXT,                 -- cid / videoId / CHG-NNN / insight id 等
  summary     TEXT,
  details     TEXT,                 -- JSON(小さく)
  dispatched  INTEGER NOT NULL DEFAULT 0   -- Dispatcher処理済みフラグ
);
CREATE INDEX IF NOT EXISTS idx_devents_disp ON dept_events(dispatched, created_at);

-- 部門タスク(誰が何をするか)
CREATE TABLE IF NOT EXISTS dept_tasks (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  assigned_dept   TEXT NOT NULL,    -- agent名
  task_type       TEXT,
  entity_id       TEXT,
  priority        TEXT DEFAULT 'normal',
  status          TEXT NOT NULL DEFAULT 'open',  -- open|in_progress|blocked|done|rejected (blocked=承認/依存待ち)
  source_event_id INTEGER,          -- dept_events.id
  summary         TEXT NOT NULL,
  result          TEXT,             -- 完了時の要約(次工程がChami抜きで読める粒度)
  completed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_dtasks_dept ON dept_tasks(assigned_dept, status);
```
insightsは既存 `improvement_insights` をそのまま部門横断Insightにも使う(departmentが宛先)。

**運用規則(スキーマ横断・デプロイ前に確定)**:
- **部門識別子の正規語彙=agent名**(system-engineer等)。dept_events/dept_tasksだけでなく、既存表(improvement_requests/system_changes/improvement_insights)のdepartmentも同語彙に統一する(orchestration.mdのINSERT例も修正・P1)
- entity_idにvideoIdを入れる時は**必ずacc接頭辞付き**(acc1-/acc2-)で記録(アカウント混入防止の恒久対策をイベント層でも維持)
- improvement_insightsのevidenceは**参照ID(events.id / REQ-コード / CHG-コード)を必ず含めるJSON**とする=「要求→改修→行動変化→Insight」の因果の鎖を後半でも構造的に辿れるようにする(専用カラム追加はP2以降に判断)

### 4.2 イベント型と購読表(Dispatcherのルーティング規則・orchestration.mdへ追記する)

| event_type | 発生元 | 購読部門(→自動でdept_task化) |
|---|---|---|
| candidate.recommended | product-scout | copy-director(コピー3案作成) |
| creative.proposal_created | copy-director | (司令塔→Chami提示。タスク化なし) |
| video.generated | app(user_events) | qa-reviewer(投稿前チェック・任意) |
| post.published | app(user_events) | shorts-analyst(初動観測の予約) |
| metrics.updated | app(数字の更新操作をuser_eventsから観測) | shorts-analyst(定期分析の起点・P5自動化候補) |
| insight.created | shorts-analyst/kaizen-analyst | departmentカラムの宛先部門 |
| fix.deployed / system.changed | system-engineer(司令塔記録) | qa-reviewer(回帰確認) |
| qa.failed | qa-reviewer | system-engineer(差し戻し) |
| qa.passed | qa-reviewer | (司令塔へ報告のみ) |
| bug.detected | 全部門 | system-engineer |
| improvement.approved | Chami(司令塔が記録) | **コード変更を要するもの=system-engineer**、知見反映(docs更新提案等)のみ宛先部門(書き込み権限の原則を維持) |

原典イベント名との対応(突き合わせ用): video.posted→**post.published**(既存CustomEvent bluesky-postedと整合)/creative.created→**creative.proposal_created**/system.deployed(v1)→**fix.deployed**。原典のcandidate.addedは購読部門がなくuser_eventsの`candidate_added`で記録済みのため部門イベント化しない。

### 4.3 Dispatcherの実体(段階定義)
- **P0〜P3(当面)**: **司令塔=Dispatcher**。(a)イベントを記録した本人(司令塔)がその場で購読表に従いdept_tasksを生成 (b)セッション開始時に`dispatched=0`のイベントを掃引してタスク化(取りこぼし防止)。部門は自分宛の`status='open'`タスクを起動時に読む
- **P4**: 定期実行(スケジュールセッション)がdispatch掃引+「未処理タスク一覧」をChamiへ朝レポート
- **P5(限定自動実行)**: 影響範囲が明確な連鎖のみ自動化(candidate.recommended→copy3案 / fix.deployed→qa確認)。**自動化する連鎖は1つずつChami承認で追加**(ホワイトリスト方式・orchestration.mdに明記)

### 4.4 部門別セッションの運用設計(原典まとめ§4準拠・現実解)
- セッションは常駐しない前提で、**共有状態は全てD1(tasks/events/insights)とdocs**が持つ→どのセッションからでも同じ状態が見える=「常設」と等価
- 運用: 主要4部門(改修/選定/コピー/分析)は、司令塔セッションのコンテキストが逼迫した時 or 専門作業が続く時に**部門専用セッションを開設してよい**。開設手順(定型・orchestration.mdへ):
  1. 新セッションで宣言「○○部門として作業する」
  2. 読む順: CLAUDE.md → orchestration.md → 自部門の.claude/agents/○○.md → chami-principles.md → 自部門docs → `dept_tasks`(自部門・open)
  3. 作業→結果をdept_tasks.result+dept_eventsへ記録→終了(次のどのセッションでも続きが読める)
- qa-reviewer/kaizen-analystはスポーン型(常設不要・原典どおり)

### 4.5 部門Memory(docs/departments/ 拡充・原典まとめ§5.2をagent名ディレクトリで採用)
```
docs/departments/
├ 00_common/ … orchestration.md(既存+4.2表+4.4手順を追記。v1§Eのrules.md相当=不変条件はここへ統合済) / chami-principles.md(新設・公開制約§2.1) / glossary.md(将来)
├ system-engineer/ { known-issues.md, decisions.md }   ※architectureは既存仕様書へのリンクで代替
├ product-scout/   { selection-rules.md, price-hypotheses.md, findings.md }
├ copy-director/   { copy-rules.md, winning-patterns.md, rejected-patterns.md }
├ shorts-analyst/  { metric-definitions.md, hypotheses.md, experiments.md }
├ kaizen-analyst/  { request-patterns.md, behavior-patterns.md, improvement-findings.md }
└ personas/ …(§3.2)
```
運用規則: 各ファイルは「結論先頭・1項目=数行・古い項目は下へ」。部門は自分のdocsだけ更新可(他部門のdocsへはinsight経由で提案)。初期は空テンプレ+見出しのみ作成(P1)。

## 5. コピー修正差分の学習(copy_revisions・P2)

原典が最重視する「AI案→Chami修正」の差分蓄積。第2段階で導入:
```sql
CREATE TABLE IF NOT EXISTS copy_revisions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  field       TEXT,     -- movie_top / movie_author / bsky_text / yt_title 等
  ai_text     TEXT,     -- AI案(あれば)
  final_text  TEXT,     -- Chami確定版
  cid         TEXT,     -- 対象作品(あれば)
  source      TEXT      -- 'chat'(copy-director案の修正) | 'app'(アプリ内テンプレ編集)
);
```
- 収集経路: (a)chat=copy-directorの案をChamiが修正採用した時に司令塔が1行記録 (b)app=`copy_template_edited`イベント(kaizen-log.jsへフック追加)でbefore/after本文を送る(コピーは短文・秘密でない・meta300字制限は本表では適用外にする)
- 分析: kaizen-analyst/copy-directorが「説明型→断定型」「長→短」等の傾向を抽出し copy-rules.md へ反映提案(承認制)。**確定ルール化はChami承認後のみ**(原典§11)

## 6. Incident lifecycle(記憶に依存しない障害対応)

- 正本は既存 `インシデント.md` を維持(D1化しない=読み書きが最も簡単な場所に置く)。**構造化見出しを義務化**:
  `## INC-NN: 症状(1行) / 原因 / 対処 / 再発防止 / 教訓 / 日付`
- **義務**: system-engineer/qa-reviewerは、障害調査の着手前に必ず `インシデント.md` をgrepし、類似INCの原因と成功/失敗した対処を報告に含める(chami-principles「記憶に依存させない」の実装)
- qa-reviewerの**投稿前チェックリスト**(原典§2.3の6項目: URL一致/チャンネル一致/Drive保存/Sheets記録/短縮URL有効/重複なし)は現在のqa-reviewer.mdに**未記載**(改修後の回帰チェックのみ記載)。**P1でqa-reviewer.mdへ追記する**(§2.2の依存チェック項目と同じコミットで)

## 7. Skill化ループ(同じ訂正を繰り返させない)

```
kaizen-analystがimprovement_requests/チャット履歴から反復要求を検出(同種3回以上)
→ Skill候補としてinsightに記録(finding=反復の証拠, suggested_action=ルール文案)
→ 司令塔がChamiへ提示 → 承認 → CLAUDE.md/orchestration.md/該当agentへルール1行追加(=Skill化)
→ 以後の同種訂正回数を効果測定
```
例(既に確立済みのもの=このループの先行事例): 半角括弧ルール/デプロイ承認区分/成約を追わない。

## 8. 将来のメタ部門(今は作らない・司令塔が兼務)

| 原典の部門 | 責務 | 当面の扱い |
|---|---|---|
| Capability Engineer | Persona/プロンプトのトークン最適化・Skill発動の阻害検査 | 司令塔が兼務(P3以降、agents/docsが肥大したら分離検討) |
| Organization Architect | 部門統合/分割時のPersona影響分析・組織構造の見直し | 同上(部門数が増えたら分離) |
| Project Blueprint Architect | 他プロジェクトへの部門/Persona/原則の展開枠 | 構想のみ(本書対象外・将来のノベルゲーム制作等で再利用) |

agent乱立を避ける: 新部門の追加は「既存部門で3回以上こぼれたタスク種がある」ことを条件にする。

## 9. 統合ロードマップと承認ゲート

| Phase | 内容 | 状態 | 承認 |
|---|---|---|---|
| P0 | 部門分離+司令塔+ログ基盤(v1群) | **構築済・未デプロイ**(継続改善v1§6.5) | デプロイ承認待ち |
| P1 | 本書の骨格導入: chami-principles.md(公開制約§2.1準拠) / personas構造+INDEX / 部門docsテンプレ / orchestration.mdへ4.2表+4.4手順+正規語彙追記 / agents必読1行追加+**qa-reviewer.mdへ投稿前6項目追記** | ファイル群は未作成。**スキーマ3表はkaizen_schema.sqlへ反映済(未適用)** | ファイル追加=フロント扱い(承認不要)。**スキーマ適用はP0のD1作成と同時**(要承認・1回で済む) |
| P2 | キャラ共同作成セッション(6部門・§3.5) / copy_revisions導入 / ログ蓄積1〜2週間 | 未着手 | キャラ確定は都度Chami / copy_revisionsのchat経由=司令塔がwrangler直書き(承認不要)。**app側フック=Worker側の受け口変更を伴うため要承認**(§5) |
| P3 | kaizen-analyst初回分析→改善提案(承認制) / visual_profile共同作成(AIイラスト練習) | 未着手 | 提案は全て承認制 |
| P4 | Dispatcher定期化+**分析リズム確立**: 朝レポート(日次=未処理タスク+異常検知) / 週次=改善提案 / 月次=Chamiの操作・要求傾向の変化レビュー(原典Phase3の3層) | 未着手 | 運用開始をChami判断 |
| P5 | 限定自動実行(ホワイトリスト方式・1連鎖ずつ承認)。候補連鎖: candidate.recommended→copy3案 / fix.deployed→qa確認 / metrics.updated→analyst分析 | 未着手 | 連鎖ごとにChami承認 |

**P0+P1は同時デプロイ可能**(スキーマが1回で済む)。kaizen_schema.sqlには本書の3表を**反映済み**のため、継続改善v1§6.5の手順をそのまま実行すればv2分も一緒に適用される。

## 10. トークン節約規約(全フェーズ共通)

1. persona_manifest=10行以内。通常業務でdetail/visualを読まない
2. chami-principles.md=1ページ以内。部門docs=結論先頭・数行/項目
3. 部門はdept_tasksを「自部門・open」でフィルタして読む(全件読まない)
4. 司令塔→部門への委任時は「タスク+必要最小の文脈」だけ渡す(会話全文を渡さない)
5. イベント/タスクのdetails JSONは要点のみ(全文貼り付け禁止)

## 11. セキュリティ・分離原則(再掲+追加)

- ログ/イベント/ペルソナいずれにも秘密(鍵/パスワード/トークン/Cookie)を書かない
- Chamiの特性情報(§2.1背景)は `chami-principles.md`(リポジトリ内)にのみ記載。ログ・イベント・insightへ転記しない(設計配慮としてのみ機能させる)
- 書き込み権限は従来どおりsystem-engineerのみ。ペルソナファイルの編集は司令塔(Chami依頼時)
- Worker/GAS/D1作成のデプロイは毎回Chami承認(不変)

## 12. 未確認事項(Chami判断待ち)

1. キャラ作成の開始時期: P0/P1デプロイ後すぐか、ログが貯まってからか(§3.5は6部門×10分程度/体)
2. キャラの世界観の方向性(全員同一世界観のチームものか、独立か)→共同作成セッションの冒頭で決める
3. `chami-principles.md` の背景記述の粒度(§2.1の要約案で良いか、加筆したいか)
4. 部門専用セッションの開始時期(当面は司令塔+スポーンで足りる想定)
5. copy_revisionsのapp側フック対象(bskyText/movie top/author/YT題名のどこまで録るか)
6. 画面遷移系イベント(post_edit_opened/タブ切替等)をP2開始時に第2段階候補から昇格させるか — 原典§8.4の「画面往復検出」には遷移記録が必要で、現在の計装(操作イベントのみ)では往復分析が部分的にしか成立しない。P3の分析項目と収集イベントの対応はkaizen-analystのbehavior-patterns.mdに書く
