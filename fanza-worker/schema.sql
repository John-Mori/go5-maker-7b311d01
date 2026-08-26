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

-- 全候補プール（📚全候補タブの作品cid集合・2026-07-18）。フロントが総入れ替えでPOST、部門はこれをJOINして
-- 「全候補タブに出ている作品だけ」を読む。除外タブ(excludeFromAll)を反映済みの集合がフロントから来る。
CREATE TABLE IF NOT EXISTS candidate_pool (
  cid         TEXT PRIMARY KEY,
  updated_at  INTEGER,
  source      TEXT            -- 出所タブ 'main'(手動追加💡)|'circle'(サークル)|'list'(独立タブ)・2026-08-09
);
CREATE INDEX IF NOT EXISTS idx_candpool_cid ON candidate_pool(cid);

-- 投稿履歴ミラー（作品cid×チャンネル別のYouTube最終投稿日・2026-08-16）。
--   client localStorage go5_stock_archive の投稿完了(archiveStock_)が1件POST /posted で書く。
--   product-scout daily_pick.py が「両CHで直近3週間以内に投稿した作品を外す」ために
--   SELECT posted_at FROM posted_log WHERE cid=? AND channel=? で最終投稿日を読む(トークン無し・wrangler認証のみ)。
--   PK=(cid,channel)。UPSERTは posted_at が新しい時だけ更新(古い履歴で上書きしない)。書き込みは追加のみ・既存表に非波及。
CREATE TABLE IF NOT EXISTS posted_log (
  cid        TEXT NOT NULL,
  channel    TEXT NOT NULL,   -- 'acc1'(月詠み) | 'acc2'(宵桜艶帖)
  posted_at  TEXT NOT NULL,   -- 投稿完了時刻 ISO8601(≒YouTube投稿日)
  yt_url     TEXT,            -- YouTube URL(任意)
  updated_at TEXT,
  PRIMARY KEY (cid, channel)
);

-- Server-side catalog populated incrementally from registered makers.
-- The client receives only the requested page; candidate_pool remains the department membership index.
CREATE TABLE IF NOT EXISTS candidate_catalog (
  cid             TEXT PRIMARY KEY,
  maker_id        TEXT,
  maker_name      TEXT,
  title           TEXT,
  url             TEXT,
  released        TEXT,
  list_price      INTEGER,
  price           INTEGER,
  discount_pct    INTEGER,
  review_count    INTEGER,
  review_avg      REAL,
  thumb           TEXT,
  genres_json     TEXT,
  service         TEXT,
  floor           TEXT,
  work_type       TEXT,
  eligible        INTEGER NOT NULL DEFAULT 0,
  source          TEXT NOT NULL DEFAULT 'circle',
  discovered_at   INTEGER NOT NULL,
  refreshed_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_maker ON candidate_catalog(maker_id, eligible);
CREATE INDEX IF NOT EXISTS idx_catalog_release ON candidate_catalog(eligible, released DESC);
CREATE INDEX IF NOT EXISTS idx_catalog_review ON candidate_catalog(eligible, review_count DESC);

-- The crawl cursor is persisted so interrupted scans resume on the next Worker run.
CREATE TABLE IF NOT EXISTS candidate_catalog_makers (
  maker_id        TEXT PRIMARY KEY,
  name            TEXT,
  source_index    INTEGER NOT NULL DEFAULT 0,
  next_offset     INTEGER NOT NULL DEFAULT 1,
  status          TEXT NOT NULL DEFAULT 'pending',
  scan_started_at INTEGER,
  completed_at    INTEGER,
  last_error      TEXT,
  updated_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_jobs ON candidate_catalog_makers(status, updated_at);
-- 「一度でも投稿したサークル」は全候補へ残すための権威。明示タブを削除しても消さない。
CREATE TABLE IF NOT EXISTS posted_makers (
  maker_id       TEXT PRIMARY KEY,
  name           TEXT,
  first_posted_at TEXT,
  updated_at     INTEGER NOT NULL
);

-- 旧投稿履歴のcidを一度ずつサークル解決するための進捗台帳。
CREATE TABLE IF NOT EXISTS posted_maker_resolutions (
  cid        TEXT PRIMARY KEY,
  maker_id   TEXT,
  checked_at INTEGER NOT NULL
);