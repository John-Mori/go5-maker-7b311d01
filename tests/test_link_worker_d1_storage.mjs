import assert from "node:assert/strict";
import {
  bumpClickCount, consumeDailyIssue, getClicks, getLink, listLinks, putLinkIfAbsent,
} from "../link-worker/src/storage.mjs";

class FakeStmt {
  constructor(db, sql) { this.db = db; this.sql = sql; this.args = []; }
  bind(...args) { this.args = args; return this; }
  async first() {
    const code = this.args[0];
    const row = this.db.links.get(code);
    if (this.sql.includes("SELECT url")) return row ? { url: row.url } : null;
    if (this.sql.includes("SELECT clicks")) return row ? { clicks: row.clicks } : null;
    throw new Error("unexpected first: " + this.sql);
  }
  async run() {
    const now = this.args[this.args.length - 1];
    if (this.sql.includes("CREATE TABLE IF NOT EXISTS short_click_daily")) return { meta: { changes: 0 } };
    if (this.sql.includes("INSERT INTO short_click_daily")) {
      const [code, day] = this.args;
      const key = code + "|" + day;
      this.db.daily.set(key, (this.db.daily.get(key) || 0) + 1);
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("INSERT OR IGNORE INTO short_links")) {
      const [code, url] = this.args;
      if (this.db.links.has(code)) return { meta: { changes: 0 } };
      const clicks = this.args.length === 3 ? 0 : Number(this.args[2]) || 0;
      this.db.links.set(code, { url, clicks, updated_at: now });
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("UPDATE short_links")) {
      const [code] = this.args;
      const row = this.db.links.get(code);
      if (!row) return { meta: { changes: 0 } };
      row.clicks += 1;
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("INSERT OR IGNORE INTO short_rate_limits")) {
      const [day] = this.args;
      if (this.db.rates.has(day)) return { meta: { changes: 0 } };
      this.db.rates.set(day, 0);
      return { meta: { changes: 1 } };
    }
    if (this.sql.includes("UPDATE short_rate_limits")) {
      const [day, limit] = this.args;
      const count = this.db.rates.get(day) || 0;
      if (count >= limit) return { meta: { changes: 0 } };
      this.db.rates.set(day, count + 1);
      return { meta: { changes: 1 } };
    }
    throw new Error("unexpected run: " + this.sql);
  }
  async all() {
    if (this.sql.includes("FROM short_click_daily")) {
      const [today, yesterday, weekStart] = this.args;
      const byCode = new Map();
      for (const [key, clicks] of this.db.daily) {
        const split = key.lastIndexOf("|");
        const code = key.slice(0, split), day = key.slice(split + 1);
        if (day < weekStart || day > today) continue;
        const row = byCode.get(code) || { code, today: 0, yesterday: 0, week: 0 };
        if (day === today) row.today += clicks;
        if (day === yesterday) row.yesterday += clicks;
        row.week += clicks; byCode.set(code, row);
      }
      return { results: Array.from(byCode.values()) };
    }
    if (!this.sql.includes("SELECT code,url,clicks")) throw new Error("unexpected all");
    return { results: Array.from(this.db.links, ([code, row]) => ({ code, ...row })) };
  }
}
class FakeD1 {
  constructor() { this.links = new Map(); this.rates = new Map(); this.daily = new Map(); }
  prepare(sql) { return new FakeStmt(this, sql); }
}
class FakeKv {
  constructor(values = {}) { this.values = new Map(Object.entries(values)); this.writes = 0; }
  async get(key) { return this.values.has(key) ? this.values.get(key) : null; }
  async put(key, value) { this.writes++; this.values.set(key, value); }
  async list() {
    return { keys: Array.from(this.values.keys()).filter(k => k.startsWith("u:")).map(name => ({ name })), list_complete: true };
  }
}

const db = new FakeD1();
const kv = new FakeKv({ "u:old01": "https://example.com/old", "c:old01": "7" });
const env = { LINKS_DB: db, LINKS: kv };

assert.equal(await getLink(env, "old01"), "https://example.com/old", "legacy KV URL remains readable");
assert.equal(await putLinkIfAbsent(env, "new01", "https://example.com/new"), "https://example.com/new");
assert.equal(kv.writes, 0, "new link does not write KV");
await bumpClickCount(env, "new01", "https://example.com/new");
assert.equal(await getClicks(env, "new01"), 1, "D1 click increments");
await bumpClickCount(env, "old01", "https://example.com/old");
assert.equal(await getClicks(env, "old01"), 8, "legacy click baseline migrates to D1");
assert.equal(kv.writes, 0, "click migration does not write KV");
assert.equal(await consumeDailyIssue(env, "2026-08-27", 2), true);
assert.equal(await consumeDailyIssue(env, "2026-08-27", 2), true);
assert.equal(await consumeDailyIssue(env, "2026-08-27", 2), false);
assert.equal(kv.writes, 0, "rate limiting does not write KV");
const rows = await listLinks(env);
assert.equal(rows.length, 2, "D1 and legacy KV listings are merged without duplicates");
assert.equal(rows.find(row => row.code === "new01").today, 1, "today clicks are returned per short code");
assert.equal(rows.find(row => row.code === "new01").week, 1, "rolling 7-day clicks are returned per short code");
console.log("link-worker D1 storage tests: ok");
