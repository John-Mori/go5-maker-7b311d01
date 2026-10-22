// 短縮クリックの1件ずつの記録(short_click_log)を固定する(Chami 2026-10-22「利益が出ん。なんで?」の切り分け用)。
//   ①判定ごと(bot/self/noua/counted)に1行ずつ残る ②IPは保存しない ③既存の累計・日別の数え方は変わらない
//   ④記録が壊れてもリダイレクトは返る。実行: node tests/test_link_worker_click_log.mjs
import assert from "node:assert/strict";
import worker from "../link-worker/src/index.js";
import { logClick, CLICK_LOG_KEEP_DAYS } from "../link-worker/src/storage.mjs";

class Stmt {
  constructor(db, sql) { this.db = db; this.sql = sql; this.args = []; }
  bind(...a) { this.args = a; return this; }
  async first() {
    const row = this.db.links.get(this.args[0]);
    if (this.sql.includes("SELECT url")) return row ? { url: row.url } : null;
    if (this.sql.includes("SELECT clicks")) return row ? { clicks: row.clicks } : null;
    throw new Error("first: " + this.sql);
  }
  async run() {
    if (this.db.failLog && this.sql.includes("short_click_log")) throw new Error("d1 down");
    if (/CREATE (TABLE|INDEX)/.test(this.sql)) return { meta: { changes: 0 } };
    if (this.sql.includes("INSERT INTO short_click_log")) {
      const [ts, code, verdict, ua, referer, country, asn, host] = this.args;
      this.db.log.push({ ts, code, verdict, ua, referer, country, asn, host }); return { meta: { changes: 1 } };
    }
    if (this.sql.includes("DELETE FROM short_click_log")) {
      const before = this.db.log.length; this.db.log = this.db.log.filter(r => r.ts >= this.args[0]);
      return { meta: { changes: before - this.db.log.length } };
    }
    if (this.sql.includes("INSERT INTO short_click_daily")) { this.db.daily++; return { meta: { changes: 1 } }; }
    if (this.sql.includes("UPDATE short_links")) { this.db.links.get(this.args[0]).clicks++; return { meta: { changes: 1 } }; }
    throw new Error("run: " + this.sql);
  }
}
class D1 {
  constructor() { this.links = new Map([["abcde", { url: "https://www.dmm.co.jp/x", clicks: 0 }]]); this.log = []; this.daily = 0; }
  prepare(sql) { return new Stmt(this, sql); }
  async batch(stmts) { return Promise.all(stmts.map(s => s.run())); }
}
async function hit(env, { ua, cookie, nc, referer, cf } = {}) {
  const headers = {};
  if (ua !== undefined) headers["User-Agent"] = ua;
  if (cookie) headers["Cookie"] = cookie;
  if (referer) headers["Referer"] = referer;
  const req = new Request("https://5mgl.com/abcde" + (nc ? "?nc=1" : ""), { headers });
  if (cf) Object.defineProperty(req, "cf", { value: cf });
  const waits = [];
  const res = await worker.fetch(req, env, { waitUntil: p => waits.push(p) });
  await Promise.all(waits);
  return res;
}

const db = new D1(); const env = { LINKS_DB: db };
const iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1";
let r = await hit(env, { ua: iphone, referer: "https://bsky.app/", cf: { country: "JP", asn: 2516 } });
assert.equal(r.status, 302, "人は302");
assert.equal(db.links.get("abcde").clicks, 1, "人は累計+1(従来どおり)");
assert.equal(db.daily, 1, "人は日別+1(従来どおり)");
assert.deepEqual([db.log[0].verdict, db.log[0].ua, db.log[0].referer, db.log[0].country, db.log[0].asn, db.log[0].host],
  ["counted", iphone, "https://bsky.app/", "JP", 2516, "5mgl.com"], "人のクリックは UA・リファラ・国・ASN 付きで1行");
assert.match(db.log[0].ts, /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/, "時刻はJSTの年月日 時分秒");
assert.equal(Object.keys(db.log[0]).some(k => /ip/i.test(k)), false, "IPの列は無い");

r = await hit(env, { ua: "Twitterbot/1.0", cf: { country: "US", asn: 13414 } });
assert.equal(r.status, 200, "既知botは302にしない");
assert.equal(db.links.get("abcde").clicks, 1, "botは数えない(従来どおり)");
assert.equal(db.log[1].verdict, "bot", "弾いたbotも記録に残る");

await hit(env, { ua: iphone, cookie: "go5nc=1" });
assert.equal(db.log[2].verdict, "self", "自分の端末は self");
await hit(env, { ua: iphone, nc: true });
assert.equal(db.log[3].verdict, "self", "?nc=1 も self");
assert.equal(db.links.get("abcde").clicks, 1, "self は数えない(従来どおり)");

r = await hit(env, { ua: "" });
assert.equal(r.status, 302, "UA無しは302(従来どおり)");
assert.equal(db.log[4].verdict, "noua", "UA無しは noua として見分けられる");

db.failLog = true;
r = await hit(env, { ua: iphone });
assert.equal(r.status, 302, "記録が壊れてもリダイレクトは返る");
assert.equal(db.links.get("abcde").clicks, 3, "記録が壊れても累計は数える");
db.failLog = false;
const before = db.log.length;
db.log.unshift({ ts: "2000-01-01 00:00:00", code: "old", verdict: "counted" });
await logClick(env, { code: "abcde", verdict: "counted", ua: "x" }, Date.now(), () => 0);
assert.equal(db.log.some(r => r.code === "old"), false, CLICK_LOG_KEEP_DAYS + "日より古い行は掃除される");
assert.equal(db.log.length, before + 1, "新しい行は消さない");
console.log("link-worker click log tests: ok");
