# 世界のAIエージェント基盤調査 — ファイル管理・コンテキスト・データ整理の恒久解決案

策定: 2026-07-17 / データ整理部門(田中琴葉) / 状態: **調査完了 / C1・C2・D=実装済(2026-07-18) / A=既存実装あり / B=改名枠で保留**
調査方法: 4領域×並列調査(記憶システム/メッセージ基盤/git隔離/データ管理・軽量モデル委譲)+研究室(琴葉)による統合。星数・活動状況は2026-07-17〜18時点の実測。「推測」は本文中に明記。
発端: Chami「現在のファイル管理、コンテキスト、データ整理運用に抱える問題を恒久的に解決できる方法を、有用なAIエージェントの仕組みを公開している世界中のGitHubから探して、改善案や新たな案をまとめて」(2026-07-17)
方針: **実装はしない**(本書は調査と提案のみ)。姉妹文書: `データ保管設計_コンテキストとログの正本.md` / `データ蓄積とローカルLLM学習_改善設計書.md`

---

## 1. 解きたい問題の台帳(全てこのプロジェクトで実際に起きた事実)

世界の解を評価する前に、**うちで本当に起きた問題**を並べる。解の良し悪しは「この台帳の何番を恒久的に消すか」で測る。

### P1: メッセージ基盤(受信箱)の脆さ

| # | 事実 | 現在の対処(=暫定) |
|---|---|---|
| P1-1 | **在席判定のレース**: 脈ファイルの鮮度で不在を判定するが、脈は待機中しか打たれない。処理中の部門が「不在」扱いになり箱をsweepに奪われた(data-orgで4連続・learning-coachでも再現) | 起床の正順(退避→再武装)の規約化+`RESIDENT_FRESH_SEC` 90→600秒。**運用規律頼み** |
| P1-2 | **in-flight喪失**: 箱をドレインしてから処理完了までの間に落ちると無言で消える(INC-100) | `local/_work/` へのmv退避。**mv後に落ちれば結局消える** |
| P1-3 | **台帳分裂**: 処理済み台帳が2本(`discord_processed.jsonl`/`discord_inbox_processed.jsonl`)。二重回答が実際に発生(INC-87・同一msg_idが2件記録) | 転送前の台帳突合を義務化+corpusでの重複排除。**書く側は未統一** |
| P1-4 | **ack無し**: 「読んだ」「処理した」の確認応答が仕組みに無い。着手印は人(AI)が手で押す | 進捗印3段の規約化。**押し忘れは検出されない** |

### P2: 並行セッションとgitの衝突

| # | 事実 | 現在の対処(=暫定) |
|---|---|---|
| P2-1 | **インデックス相乗り**(INC-91): 作業ツリー1つ=索引1つ。他セッションのcommitに自分のステージが黙って同乗(2回実発生・全セッションが経験) | パス限定コミットの義務化 |
| P2-2 | **HEAD/rebase状態も共有**: 他人の `pull --rebase` 中は全セッションのファイルが「消えたように見える」(実発生・本部門が踏んだ)。autostashが他人のWIPを退避してINC-99 | **対処なし**(気づいて止まる、しかない) |
| P2-3 | **push=Pages即公開**: 壊れた中間状態が公開される経路が常時開いている | 慎重さ頼み |
| P2-4 | **所有権が不明**: どの未コミット変更が誰の書きかけか分からず、pull不能が常態化 | 交通整理待ち |

### P3: データのため方

| # | 事実 | 現在の対処(=暫定) |
|---|---|---|
| P3-1 | **ローテーション皆無**: 全ログ・全台帳が追記のみで無限成長 | 未対処(月次アーカイブは提案止まり) |
| P3-2 | **スキーマが暗黙**: jsonlの型はファイルごとに暗黙。`ts='t'` の不正行が実在し並び順を壊した(実測) | corpus側でts検証。**元の書き手は無検証のまま** |
| P3-3 | **機微一覧のドリフト**: 同じdenylistを3ファイルに写して3通りに食い違い(future-roomは1箇所のみ) | corpus側は許可リスト方式。**3ファイルの統一は未着手** |
| P3-4 | **設定・一覧の重複**: 部屋一覧・チャンネル対応・人格台帳などが複数箇所に散在 | 都度手動同期 |

### P4: コンテキスト(AIの記憶)

| # | 事実 | 現在の対処(=暫定) |
|---|---|---|
| P4-1 | **全注入の限界**: 知識パック(16〜40KB)を毎回システムプロンプトへ全注入。増えるほど遅く薄くなる(qwen3:8b・8GB VRAM・55秒/回) | 上限40KB+間引き。**検索(RAG)ではない** |
| P4-2 | **記憶モデルが未分化**: 発言・教訓・FAQ・設計が「1枚のmd」に平置き。エピソード記憶/意味記憶/手続き記憶の区別が無い | 層化(5層)まで |
| P4-3 | **Claudeセッション側の記憶も属人的**: memory dirはcwd絶対パスに紐づき、改名で迷子になる。セッション間の知識共有はDiscord経由の人力 | 改名台本で引っ越し予定 |
| P4-4 | **採点→学習の閉ループが未運用**: 道具は完成(grade.py)だが採点者が未定。good率が出ない | 承認待ち |

---

## 2. 調査結果(GitHub横断・4領域)

> **(調査エージェント4本の結果がここに合流する。合流前のこの版では空欄。)**

### 2.1 エージェント記憶システム(P4系) — 調査完了

| プロジェクト | 星 | ライセンス | 記憶モデルの核 | 8GB VRAMローカル適性 |
|---|---|---|---|---|
| [mem0](https://github.com/mem0ai/mem0) | 61.1k | Apache-2.0 | Vector+Graph+KV。新事実を既存記憶と比較し**ADD/UPDATE/DELETE/NOOP**をLLMが判定=矛盾解消が設計されている | ○(Ollama+Chroma/Qdrantで完全オフライン可) |
| [LangMem](https://github.com/langchain-ai/langmem) | 1.6k | MIT | **CoALA分類(episodic/semantic/procedural)を明示採用**。会話後にバックグラウンドで反省(reflection)→記憶抽出→振る舞いルール更新 | ○(ストレージ/LLM非依存の軽量ライブラリ) |
| [MIRIX](https://github.com/Mirix-AI/MIRIX) | 3.6k | Apache-2.0 | **6ストア分類**(Core/Episodic/Semantic/Procedural/Resource/KnowledgeVault) | ○だがマルチエージェント構成は過剰 |
| [Letta(旧MemGPT)](https://github.com/letta-ai/letta) | 23.8k | Apache-2.0 | Core/Recall/Archivalの3層+self-editing memory | △(公式が小型モデルでの不安定を警告) |
| [Graphiti](https://github.com/getzep/graphiti)(Zep) | 28.9k | Apache-2.0 | 時間的知識グラフ(**事実にvalidity window**=いつ真になりいつ覆されたか) | △(小型モデルの構造化出力精度に公式懸念) |
| [cognee](https://github.com/topoteretes/cognee) | 28.0k | Apache-2.0 | ECLパイプライン | △(公式推奨は32B以上) |
| MemoryBank(AAAI論文実装) | 439 | MIT・**停止** | **Ebbinghaus忘却曲線 R=e^(-t/S)**・想起で記憶強度が増す | 理論原型としてのみ |
| [basic-memory](https://github.com/basicmachines-co/basic-memory) | 3.5k | **AGPL-3.0** | Markdown+wikilink+SQLiteインデックス(=うちのknowledge.md方式の発展形) | ○ |

**核心**: フレームワーク丸ごと導入(Letta/Graphiti/cognee)は、**いずれも公式自身が「小型ローカルモデルでの精度」に懸念を明記**しており、qwen3:8b運用とは相性リスクが高い。一方で「設計だけ借りる」価値は非常に高い:
- **分類**: LangMem/MIRIXの episodic(発言コーパス=もう有る)/semantic(FAQ・教訓=もう有る)/procedural(振る舞いルール=knowledge.mdの00_persona層=もう有る)——**うちのL1実装は偶然この分類に沿っており、方向は正しかった**。足りないのは名前と境界の明示だけ。
- **矛盾解消**: mem0のADD/UPDATE/DELETE/NOOP判定。現状のcorpusは追記のみ=Chamiが意見を変えた時に古い発言と新しい発言が並存する。この判定を「日次の反省バッチ」として足すのが次の一手。
- **忘却**: MemoryBankの忘却曲線(想起されない記憶は減衰)。40_recent の間引きを「新しい順」から「参照される順」へ進化させる理論的裏付け。

### 2.2 マルチエージェントのメッセージ基盤(P1系) — 調査完了

**発見の核心: P1の4問題は全て「ack・リース(可視性タイムアウト)・冪等キーを持つ永続キュー」の不在という1つの原因のクラス。** 世界はこれをとうに解いている(AWS SQSモデル)。

| プロジェクト | 星 | 状態 | うちへの適合 |
|---|---|---|---|
| [goqite](https://github.com/maragudk/goqite)(Go) | 531 | 活発 | **設計が本命**。SQLite1ファイルでSQS型(受信=一定時間不可視化/削除=ack/received回数でDLQ)。Go実装なので設計だけ借りてPythonで書く |
| [huey](https://github.com/coleifer/huey) | 6,000 | 非常に活発 | Pythonネイティブ・SQLiteバックエンド。ただしジョブキュー志向で「部門別メールボックス」への変換が要る |
| [litequeue](https://github.com/litements/litequeue) | 228 | 停滞(17ヶ月) | 依存ゼロで参考になるが、リース失効監視が未実装=そのままでは(a)を解けない |
| [LangGraph](https://github.com/langchain-ai/langgraph) checkpointer | 37,500 | 非常に活発 | レイヤー違い(1エージェント内の実行状態の再開)。将来の長時間タスク再開に転用価値 |
| [AutoGen](https://github.com/microsoft/autogen) | 55,200 | **メンテナンスモード** | 既定ランタイムはメッセージ揮発。新規に賭けない |
| Redis Streams / NATS JetStream | — | 成熟 | ack/リース/DLQ全部ネイティブだが**サーバー常駐が必要**=1台のWindows PCという制約に反し不採用 |
| claude-flow(ruvnet) | 53,400(自称) | — | 信頼性主張が一次ソースのみで第三者検証なし。過剰に重い |

**推奨(最小変更で消失耐性化)**: jsonl受信箱をSQLite1テーブルへ置換し、goqite方式を約100行で自作。
`messages(id PRIMARY KEY, dept, body, visible_at, received_count, status)`
- 受信=`visible_at=now+リース秒`へUPDATE(箱を空にしない) → 処理 → 完了=DELETE(=ack)
- **P1-1が消える**: 在席判定そのものが不要になる(脈≠在席の推測をやめ、リース失効=自動再配達)
- **P1-2が消える**: 受信〜処理の間もメッセージはテーブルに実在。クラッシュしてもリース失効後に再配達
- **P1-3が消える**: キューからのDELETEと処理済み記録が**同一トランザクション**=台帳分裂が構造的に不可能
- **P1-4が消える**: `id PRIMARY KEY` が重複排除そのもの。received_count>3でdead_letter化+Discord通知(無限リトライの安全弁)

### 2.3 並行コーディングエージェントのgit隔離(P2系) — 調査完了

**発見の核心: git worktree は各ツリーが独自のindexとHEADを持つ**(共有は objects/refs/config のみ)。つまり「セッション1つ=worktree1つ」にした時点で、**P2-1(index相乗り)・P2-2(rebase巻き添え)・P2-4(WIP衝突)は原理的に起きなくなる**。世界の並行エージェントツールは全てこの上に建っている。

| プロジェクト | 星 | 状態 | うちへの適合 |
|---|---|---|---|
| **Claude Code公式 `--worktree`**([docs](https://code.claude.com/docs/en/worktrees)) | 製品機能 | 継続更新 | **本命・ツール追加ゼロ**。`claude --worktree <名>` で `.claude/worktrees/<名>/` に隔離セッション。Windows固有挙動(ジャンクション削除)まで公式文書化済。実行中は `git worktree lock` 自動 |
| [claude-squad](https://github.com/smtg-ai/claude-squad) | 8,132 | 活発 | tmux必須=**Windowsネイティブ不可** |
| [vibe-kanban](https://github.com/BloopAI/vibe-kanban) | 27,426 | 活発 | Windowsパス不具合が既知(Issue #1598・8.3短縮パス)。常駐には時期尚早 |
| [container-use](https://github.com/dagger/container-use)(Dagger) | 3,914 | 活発 | **Docker前提**=方針と相反 |
| [sculptor](https://github.com/imbue-ai/sculptor)(Imbue) | 200 | 活発 | Windows版が配布されていない |
| [crystal](https://github.com/stravu/crystal) | 3,098 | 活発 | Electron GUI。Windows動作は未実証(推測) |
| [gwq](https://github.com/d-kuro/gwq) | 453 | 活発 | worktree管理CLI(Go製)。補助として有望だがWindows実証は要手元検証 |

**推奨レイアウト(第1候補・ツール追加ゼロ)**:
```
D:\SougouStartFolder\go5-maker\                 ← main。integrator(統合・push専任)だけがここで作業
D:\SougouStartFolder\go5-maker\.claude\worktrees\
    ├─ chat-A\      ← 対話セッションA(claude --worktree chat-A)
    ├─ chat-B\      ← 対話セッションB
    └─ (daemon用)   ← 常駐はmainの読み取り専用運用でも可
```
- **pushはintegrator役の1セッションだけ**(P2-3対策)。他は自ブランチまで。pre-push hookは全worktreeで共有される(git仕様)ため、テスト全PASSゲートを1箇所で強制できる。
- 常駐デーモンの正本は1箇所に置き、対話セッションのworktreeに触れさせない。
- 注意: cwd規約(「go5-maker直下」)とmemory dir(cwd絶対パス紐づけ)の再定義が必要=**改名(②下準備)と同じ枠で設計するのが自然**。

### 2.4 ローカルファーストのデータ/ログ管理(P3系) — 調査完了

| 用途 | 最有力 | 根拠 |
|---|---|---|
| jsonl→SQLite集約 | [sqlite-utils](https://github.com/simonw/sqlite-utils)(2.1k・活発) | 型推論+CLI一発。Windowsで素直に動く |
| jsonl直接クエリ・保持期間 | [DuckDB](https://github.com/duckdb/duckdb)(39.5k・毎日更新) | `read_json('*.jsonl')`でETL不要。保持期間はSQLの`WHERE ts >`で書ける |
| ローテーション | Python標準 `TimedRotatingFileHandler` / 複数プロセス書き込みは [concurrent-log-handler](https://github.com/Preston-Landers/concurrent-log-handler)(380・活発) | **Windowsのファイルロック配慮が明記された数少ない実装**。うちの4常駐構成に合致 |
| スキーマ検証 | [jsonschema](https://github.com/python-jsonschema/jsonschema)(5.0k・活発) | `format: date-time` で `ts='t'` のような壊れ値を書き込み時に弾ける |
| Notion一方向push | [notion-sdk-py](https://github.com/ramnes/notion-sdk-py)(2.2k・前日push) + **自前薄スクリプト** | **既製のmd→Notion同期ツールに「維持されていて実績十分」なものは存在しない**(全て小規模かstale。md2notionはアーカイブ済・notion-pyは内部API依存でレガシー)。SDK+自前30行が最も保守しやすい |

**核心**: **「jsonlが悪い」のではなく「運用(検証・ローテーション・重複排除)が無い」から起きている。** よって**jsonlを正本のまま維持**し、SQLite/DuckDBは導出インデックスに留めるのが正解(SQLite全面移行は「壊れたバイナリDB1個」という新しい単一障害点をrobocopyバックアップ運用に持ち込む)。分裂台帳はDuckDBの`ROW_NUMBER() OVER (PARTITION BY msg_id)`一発で正しい1本に書き戻せる。イベントソーシングFW([pyeventsourcing](https://github.com/pyeventsourcing/eventsourcing))は概念だけ借りて導入はしない(この規模には過剰)。
パターン語彙: hot/warm/cold階層(直近jsonl=hot・月次でSQLite集約=cold・Drive=オフサイト)、log compaction(同一キーの最新だけ残す)。

---

## 3. 提案(恒久解4本・調査の結論)

4領域の調査が同じ結論に収束した: **フレームワークの輸入ではなく、世界で検証済みの「設計」を4つ借りて、うちの既存資産(jsonl/md/Python/タスクスケジューラ)の上に薄く実装する。** 大規模FWは(a)小型ローカルモデルとの相性に公式警告があり(記憶系)、(b)サーバー常駐が要り(キュー系)、(c)Windows対応が欠け(git系)、いずれも制約と衝突する。

### 恒久解A: 受信箱をSQLiteメールボックス化(SQS型リース) — **P1-1〜P1-4を全部消す**

- 借りる設計: [goqite](https://github.com/maragudk/goqite)(SQS型・SQLite1ファイル)。Pythonで約100行の自作。
- `messages(id PRIMARY KEY, dept, body, visible_at, received_count, status)` 1テーブル。受信=リース(不可視化)・完了=DELETE(ack)・リース失効=自動再配達・received_count>3=dead_letter+Discord通知。
- **在席判定(脈ファイル)と退避運用(mv→_work)が丸ごと不要になる**。今日の規約(起床の正順・INC-85/86)は暫定対処であり、これが恒久解。
- 処理済み記録はDELETEと**同一トランザクション**=台帳分裂(INC-87)が構造的に不可能。
- 影響範囲: inbox_poller(書き込み側)・inbox_waiter(見張り側)・各部門BOOT。**移行はデュアルライト期間を設ける**(旧jsonlと並行書き込み→検証→切替)。

### 恒久解B: セッション毎worktree+統合役 — **P2-1〜P2-4を全部消す**

- 借りる設計: Claude Code公式 `--worktree`(**ツール追加ゼロ・Windows挙動が公式文書化済**)。worktreeは索引もHEADも独立=index相乗り(INC-91)もrebase巻き添えも原理的に消滅。
- pushは統合役(integrator)1セッションのみ+pre-push hookでテスト全PASSゲート(hookは全worktree共有=1箇所で強制)。Pages即公開の怖さ(P2-3)もここで塞がる。
- **前提**: cwd規約とmemory dir(cwd絶対パス紐づけ)の再設計が要る=**改名(②下準備)と同じ枠で一緒にやるのが正しい**。単独で前倒しすると住所の書き換えを二度やることになる。

### 恒久解C: 書き込み時検証+hot/cold階層 — **P3-1〜P3-2を消す**

- C1(最小・即効): jsonl追記の共通ヘルパー1関数([jsonschema](https://github.com/python-jsonschema/jsonschema)で1行検証してから追記)。`ts='t'` のような壊れ行を**入口で**弾く。既存の書き手を順次このヘルパーへ寄せる。
- C2: ローテーション=月次でDuckDB/`sqlite-utils`により古い行をSQLiteへ集約(cold)→jsonlはhotだけ残す。ログは`concurrent-log-handler`(常駐の共有ログ)へ。削除はしない(既定方針)。
- C3(one-shot): 分裂台帳はDuckDBのcompactionクエリで正しい1本へ書き戻し(恒久解Aが入るまでの繋ぎ)。
- 機微一覧の3ファイル統一(P3-3)は既にシステム改修部門の枠(許可リスト方式のregistry化)として報告済み。

### 恒久解D: 記憶モデルの明文化と進化 — **P4-1〜P4-4の次の一手**

- **L1実装(コーパス/教訓/knowledge層化)は世界の分類(episodic/semantic/procedural)と偶然一致していた。方向は正しい。乗り換え不要。**
- 借りる設計3つ(いずれも既存ファイル構造のまま足せる):
  1. **mem0のADD/UPDATE/DELETE/NOOP**: 日次の「反省バッチ」として、新発言が既存の教訓・事実と矛盾したら更新/廃止を判定(Chamiが意見を変えた時に古い方針が残り続ける問題の恒久解)
  2. **LangMemのreflection構成**: 採点(L2)→反省→記憶更新、を「会話後のバックグラウンド処理」として型化(=いまの grade.py→build_knowledge.py の流れの理論的裏付け。設計変更不要)
  3. **MemoryBankの忘却曲線**: 40_recentの間引きを「新しい順」から「参照・想起される順」へ(将来)
- RAG化(P4-1の本丸)は全注入が40KB上限を恒常的に叩くようになってから。埋め込み検索の土台は sqlite-vec 系(ローカル完結)を第一候補に。

### 優先順位と実施の単位

| 順 | 恒久解 | 消える問題 | 状態(2026-07-18) |
|---|---|---|---|
| 1 | C1 書き込み時検証 | P3-2 | **✅実装済**(`scripts/lib/jsonl_store.py`・8/8テスト・build_corpusに適用し壊れ行4件を実排除) |
| 2 | A SQLiteメールボックス | P1全部 | **正本=`scripts/queue/leasequeue.py`**(研究室/QA共同所有・30/30テスト・DLQ実装済[max_deliveries=5超でdead隔離]・Gatewayシャドウがenqueue中)。3系統が独立実装され同設計に収束→統合済(研究室裁定2026-07-18)。data-orgは作らない=二重実装回避 |
| 3 | B worktree分離 | P2全部 | **除外**(Chami指示「改名作業のやつ以外」。改名②下準備と同枠) |
| 4 | C2 ローテーション | P3-1 | **✅実装済(安全版)**(`scripts/maintenance/archive_old.py`・日次生成物のみ・常駐ログ/共有台帳は改修とAの領分) |
| 5 | D 反省バッチ(mem0型) | P4-2/P4-3 | **✅実装済(第一版)**(`scripts/llm/reflect.py`・ルールベース・自動変更なし・85件検出)。LLM判定の第二版はL2採点後 |
| 6 | D RAG化 | P4-1 | 未着手。知識パックが40KB上限を恒常的に叩いてから |

### 実装メモ(2026-07-18・Chami指示「改名以外を実装」)

- **恒久解A(バス)は既に存在した**: 本日3系統が並行実装され(研究室go5bus / QA leasequeue / 人事bus.py)、**正本は `scripts/queue/leasequeue.py` に一本化**(研究室裁定2026-07-18)。私が最初に検証した `scripts/bus/bus.py` は人事の独立検証プロトタイプ(役目完了)で、**正本ではなかった**——検証対象を取り違えたので origin/main で正本を確認し訂正(「push済みと言う前にgrep」の自分版)。正本にはDLQ(max_deliveries=5超でdead隔離+dead_letters()一覧)が実装済みで、私が提案したDLQ懸念は正本側で既に解消。**3系統が独立に同設計へ収束した事実は「方向が正しい」ことの強い裏付け**(私の世界調査§3提案Aとも一致=4例目)。data-org箱をパイロット部門第1号にする(横取り事故4連の当事者=検証に最適・研究室裁定)。C1のjsonl_store検証はenqueue時の本文検証へ流用予定(統合レビュー)。
- **C1が実運用で効いた**: `ts='t'`/空の壊れ行4件がコーパスから構造的に排除(644件・壊れ0)。
- **C2の発見**: 肥大トップは画像(design-refs/promo-ref/persona_visuals・最大2.7MB)。**ログ・台帳は1MB未満でローテーション不急**。容量対策の本丸はログではなく画像整理かもしれない(別途)。
- **Dの第一版はLLMを使わない**: 日次でqwen[55秒/回]を回すコストと8GBモデルの判定精度への公式懸念(§2.1)を踏まえ、まずルールベースで当たりを付ける。1件目がdream-care規約変更を正しく捉えた。

## 4. やらないこと(確定)

- **実装**(Chami指示: 「実装はまだしなくて良い」。本書は調査と提案のみ)
- 大規模フレームワークの丸ごと導入: Letta/Graphiti/cognee(小型モデル精度に公式警告)・Redis/NATS(サーバー常駐)・claude-squad(tmux)・container-use(Docker)・sculptor(Windows未配布)・AutoGen(メンテモード)・claude-flow(信頼性主張が未検証)
- jsonl→SQLite全面移行(バックアップ運用に新しい単一障害点を持ち込む。SQLiteは導出インデックスとメールボックスのみ)
- 既製md→Notion同期ツールの採用(維持されている実績十分なものが存在しない。SDK+自前薄スクリプトが正)
- 正本のNotion移動 / 機微・秘密のクラウド送出(Drive例外のみ)
- 「流行っているから」での選定。**評価軸は §1 の台帳の何番を消すか、だけ**
