-- link-worker: D1 primary storage (legacy KV remains read-only compatible).
CREATE TABLE IF NOT EXISTS short_links (
  code TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  clicks INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS short_rate_limits (
  day TEXT PRIMARY KEY,
  count INTEGER NOT NULL DEFAULT 0
);

-- JST日別のクリック数。累計(short_links.clicks)とは分離し、今日/昨日/直近7日を再計算できるようにする。
CREATE TABLE IF NOT EXISTS short_click_daily (
  code TEXT NOT NULL,
  day TEXT NOT NULL,
  clicks INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(code, day)
);
