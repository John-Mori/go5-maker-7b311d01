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
