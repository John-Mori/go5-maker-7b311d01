-- go5_kaizen D1 スキーマ (継続改善制度・第1段階=記録基盤)
-- 適用: fanza-worker/ で npx wrangler d1 execute go5_kaizen --remote --file kaizen_schema.sql
-- 冪等: IF NOT EXISTS 付き。

-- 部門識別子の正規語彙(全表共通): agent名を使う。
--   system-engineer / product-scout / copy-director / shorts-analyst / qa-reviewer / kaizen-analyst

-- ① Chamiの改善要求(原文+構造化)。司令塔がwrangler d1 executeで記録。
CREATE TABLE IF NOT EXISTS improvement_requests (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  req_code         TEXT UNIQUE,                       -- REQ-YYYYMMDD-NNN
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  department       TEXT,                              -- agent名(カンマ区切り可)
  target           TEXT,                              -- candidate_tab / bluesky_post 等
  request_type     TEXT,                              -- automation / ui_workflow_reduction / bugfix / feature 等
  problem          TEXT,                              -- 困りごと(要約)
  requested_change TEXT,                              -- 要求された変更(要約)
  underlying_need  TEXT,                              -- 根底のニーズ(操作数削減 等)
  raw_text         TEXT,                              -- 原文(秘密なし・要点のみ)
  status           TEXT NOT NULL DEFAULT 'proposed',  -- proposed|approved|implemented|rejected|superseded
  priority         TEXT
);

-- ② 意味のある操作イベント。フロント(core/kaizen-log.js)→fanza-worker /api/kaizen-event→ここ。
CREATE TABLE IF NOT EXISTS user_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  device_type TEXT,          -- pc | phone
  session_id  TEXT,          -- タブ単位のランダムID(個人特定情報ではない)
  screen      TEXT,          -- candidates / movie / bluesky / verify 等
  action      TEXT,          -- candidate_added / video_generated / bsky_posted 等
  object_type TEXT,          -- work / video / post 等
  object_id   TEXT,          -- cid / videoId 等
  metadata    TEXT           -- JSON(小さく・秘密なし)
);
CREATE INDEX IF NOT EXISTS idx_uev_action_ts ON user_events(action, created_at);
CREATE INDEX IF NOT EXISTS idx_uev_ts ON user_events(created_at);

-- ③ 何をいつどのバージョンで変えたか。司令塔がデプロイ/バンプ時に記録。
CREATE TABLE IF NOT EXISTS system_changes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  change_code TEXT UNIQUE,                       -- CHG-NNN
  request_id  INTEGER,                           -- improvement_requests.id (無関係ならNULL)
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  department  TEXT,
  component   TEXT,                              -- candidates.js / fanza-worker 等
  summary     TEXT,
  version     TEXT,                              -- ?v=299 / Worker Version ID 等
  status      TEXT NOT NULL DEFAULT 'deployed'   -- deployed|reverted
);

-- ④ ログ分析から得た観測/仮説/提案(kaizen-analystが作り、Chami承認で進む)。
--    部門横断Insight(分析部→選定部/コピー部への還元等)にも同表を使う(department=宛先)。
CREATE TABLE IF NOT EXISTS improvement_insights (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  department       TEXT,                              -- 提案の宛先部門
  finding          TEXT NOT NULL,                     -- 観測(事実)
  evidence         TEXT,                              -- 根拠(件数・期間・クエリ)
  confidence       TEXT,                              -- low|med|high
  suggested_action TEXT,                              -- 提案
  status           TEXT NOT NULL DEFAULT 'proposed'   -- proposed|approved|rejected|implemented|measured
);

-- ⑤ 部門間イベント(何が起きたか。追記専用)。設計=AI組織_実装設計書_v2 §4。
CREATE TABLE IF NOT EXISTS dept_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  event_type  TEXT NOT NULL,        -- candidate.recommended / fix.deployed / qa.passed 等
  source_dept TEXT NOT NULL,        -- 発生元(agent名 or 'app' or 'chami')
  entity_id   TEXT,                 -- cid / videoId / CHG-NNN 等
  summary     TEXT,
  details     TEXT,                 -- JSON(小さく)
  dispatched  INTEGER NOT NULL DEFAULT 0   -- Dispatcher(司令塔)処理済みフラグ
);
CREATE INDEX IF NOT EXISTS idx_devents_disp ON dept_events(dispatched, created_at);

-- ⑥ 部門タスク(誰が何をするか。部門はassigned_dept+openで自分の分だけ読む)。
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

-- ⑦ ペルソナ変更ログ(人格は表現のみ・業務Roleと分離。設計=AI組織_実装設計書_v2 §3.4)。
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

-- ⑧〜⑪ Learning Room(Chami専用 学習・理解支援室。設計=AI組織_実装設計書_v3 §5)。
CREATE TABLE IF NOT EXISTS learning_questions (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  topic            TEXT,
  question_text    TEXT NOT NULL,
  related_component TEXT,           -- candidates.js / fanza-worker 等
  primary_domain   TEXT,            -- architecture/backend-infra/frontend-ux/ai-agent-llm/data-stats/marketing-behavior/org-ops/security/compliance/python-automation
  secondary_domain TEXT,
  instructor_id    TEXT,
  difficulty       TEXT,
  answered_at      TEXT
);
CREATE TABLE IF NOT EXISTS knowledge_gaps (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT,
  topic              TEXT NOT NULL,
  description        TEXT,
  evidence_questions TEXT,          -- learning_questions.id のJSON配列
  importance         TEXT,          -- low|med|high
  status             TEXT NOT NULL DEFAULT 'open'  -- open|learning|closed
);
CREATE TABLE IF NOT EXISTS learning_progress (
  topic            TEXT PRIMARY KEY,
  initial_level    TEXT,
  current_level    TEXT,            -- 未理解|説明を受けた|自分の言葉で説明できる|設計判断に使えた
  evidence         TEXT,
  last_reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS learning_resources (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  topic              TEXT,
  title              TEXT NOT NULL,
  resource_type      TEXT,          -- book|article|video|doc
  difficulty         TEXT,
  reason_recommended TEXT,
  status             TEXT NOT NULL DEFAULT 'suggested'  -- suggested|reading|done|dropped
);

-- ⑫ コピー修正差分(AI案→Chami確定版の蓄積=コピー部の個人適応の原料。設計=v2§5)。
--    chat経由(司令塔がwrangler直書き)はS1から。app側フック(Worker受け口変更=要承認)はS3以降の提案。
CREATE TABLE IF NOT EXISTS copy_revisions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  field       TEXT,     -- movie_top / movie_author / bsky_text / yt_title 等
  ai_text     TEXT,     -- AI案(あれば)
  final_text  TEXT,     -- Chami確定版
  cid         TEXT,     -- 対象作品(あれば)
  source      TEXT      -- 'chat'(copy-director案の修正) | 'app'(アプリ内テンプレ編集)
);
