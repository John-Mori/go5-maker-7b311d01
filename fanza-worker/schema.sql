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

-- 市場全体巡回スナップショット (Market Crawl・Worker cronが毎朝保存)
--   サークル追跡とは別軸で「同人フロア(digital_doujin)のランキング上位+新着」を日次でスナップショット。
--   works表とは独立(母集団の意味を変えない=候補タブ/追跡サークル/実売取得に波及ゼロ)。
--   1日約200行(rank上位100 + 新着100)。90日より前は保存処理末尾のDELETEで自動掃除(容量対策)。
--   product-scoutは読み取りSELECTのみで市場候補を提案に含める(書き込みはcron/手動巡回だけ)。
CREATE TABLE IF NOT EXISTS market_snapshot (
  day           TEXT,       -- 取得日 YYYY-MM-DD(JST)
  cid           TEXT,       -- content_id
  rank          INTEGER,    -- sort=rank での順位(1..100)。新着枠のみで拾った作品は NULL
  title         TEXT,
  price         INTEGER,    -- 割引後価格
  list_price    INTEGER,    -- 定価
  discount_pct  INTEGER,    -- 割引率(%)
  review_count  INTEGER,    -- レビュー件数(API標準装備)
  review_avg    REAL,       -- レビュー平均(API標準装備)
  genres        TEXT,       -- ジャンル名の JSON 配列文字列
  maker_name    TEXT,       -- サークル/メーカー名
  thumb         TEXT,       -- サムネURL
  released      TEXT,       -- 発売日
  PRIMARY KEY (day, cid)
);
CREATE INDEX IF NOT EXISTS idx_market_day ON market_snapshot(day);
