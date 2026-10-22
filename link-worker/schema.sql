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

-- 1クリックずつの記録(UA・リファラ・国・ASN・判定)。IPは保存しない。30日より古い行はWorkerが時々掃除する。
-- verdict: bot=既知クローラ(空HTMLで弾いた) / self=自分の端末(数えない) / noua=UA無しで302(現行は数えている) / counted=人として数えた
CREATE TABLE IF NOT EXISTS short_click_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  code TEXT NOT NULL,
  verdict TEXT NOT NULL,
  ua TEXT,
  referer TEXT,
  country TEXT,
  asn INTEGER,
  host TEXT
);
CREATE INDEX IF NOT EXISTS idx_short_click_log_ts ON short_click_log(ts);
