-- go5_fanza D1 スキーマ (KV→D1移行 Phase1)
-- 適用: npx wrangler d1 execute go5_fanza --remote --file schema.sql
-- 冪等: IF NOT EXISTS 付きなので再実行しても安全。

-- 作品ごとのFANZA情報 (KVの ov:<cid> と sales:<cid> を統合)
CREATE TABLE IF NOT EXISTS works (
  cid         TEXT PRIMARY KEY,
  title       TEXT,
  info_json   TEXT,           -- sanitizeOverride() 済みオブジェクトのJSON文字列 (prices/images等)
  sales_n     INTEGER,        -- 実売本数 (未取得は NULL)
  scraped_at  TEXT,           -- info(ov:) のスクレイプ時刻 ISO8601
  sales_at    TEXT,           -- 販売数のスクレイプ時刻 ISO8601
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- PC取得依頼キュー (KVの req: と salesreq: を kind で統合)
CREATE TABLE IF NOT EXISTS fetch_queue (
  cid          TEXT NOT NULL,
  kind         TEXT NOT NULL,   -- 'info' | 'sales'
  src_url      TEXT,            -- Books等のスクレイプ先URL (kind='info'用)
  requested_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at   TEXT,            -- TTL相当 (info=7日 / sales=14日 を踏襲)。過ぎたら掃除
  PRIMARY KEY (cid, kind)
);
CREATE INDEX IF NOT EXISTS idx_queue_kind ON fetch_queue(kind, expires_at);

-- 追跡サークル (KVの salestrack:<makerId>)
CREATE TABLE IF NOT EXISTS tracked_makers (
  maker_id  TEXT PRIMARY KEY,
  name      TEXT,
  added_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 単発フラグ (KVの salesrun:req 等)。key単位で複数フラグを持てる
CREATE TABLE IF NOT EXISTS run_flags (
  key          TEXT PRIMARY KEY,   -- 'sales_run'
  requested_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at   TEXT
);
