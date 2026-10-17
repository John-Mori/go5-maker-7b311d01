// 投稿履歴の「再生数・クリック数」でセールが2行に出ない番犬
// (Chami msg 1561077304300540106「セールが同じやつ二つ被ってるから片方消して」=秋セールが同じ数字で2行出ていた)。
// yt-clicks.js の本物の saleEntries_ を切り出して実行する。localStorage・アカウント・短縮コード読みだけ偽物。
//   S-1 同じURL(http/https・末尾/違い)の2件は1行・記載開始は古い方
//   S-2 URLが違っても短縮コードが共通なら1行(コードは合算)
//   S-3 別のセールは別の行のまま・JrziR(既定ページ共通の歴史コード)だけの一致では束ねない
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(process.env.YTC_JS || path.join(__dirname, '..', 'js', 'yt-clicks.js'), 'utf8').replace(/\r\n/g, '\n');
const a = src.indexOf('  function saleEntries_() {');
const b = src.indexOf('\n  }\n', a);
assert(a >= 0 && b > a, 'saleEntries_ not found');
const fn = src.slice(a, b) + '\n  }\n';

function run(urls, cache) {
  const store = { 'bsky_discount_urls__acc3': JSON.stringify(urls), 'bsky_discount_link_cache': JSON.stringify(cache || {}) };
  const ctx = {
    localStorage: { getItem: (k) => (k in store ? store[k] : null) },
    acct: () => 'acc3',
    codeOf: (u) => { const m = String(u).match(/^https?:\/\/s\.test\/(\w+)$/); return m ? m[1] : ''; },
  };
  vm.createContext(ctx);
  vm.runInContext(fn + '\nthis.saleEntries_ = saleEntries_;', ctx);
  return ctx.saleEntries_();
}

let r = run([
  { id: 'dnew', name: '秋セール', url: 'https://x.test/aki/', at: 200 },
  { id: 'dold', name: '秋セール', url: 'http://x.test/aki', at: 100 },
], { 'acc3|dnew|af|d': 'https://s.test/AAA', 'acc3|dold|af|d': 'https://s.test/AAA' });
assert.strictEqual(r.length, 1, 'S-1 同じURLは1行');
assert.strictEqual(r[0].id, 'dold'); assert.strictEqual(r[0].at, 100);
assert.deepStrictEqual(Array.from(r[0].codes), ['AAA']);
console.log('  PASS S-1');

r = run([
  { id: 'd1', name: '秋セール', url: 'https://x.test/aki?af_id=1', at: 100 },
  { id: 'd2', name: '秋セール', url: 'https://x.test/aki?af_id=2', at: 150 },
], { 'acc3|d1|af|d': 'https://s.test/AAA', 'acc3|d2|af|d': 'https://s.test/AAA', 'acc3|d2|af2|d': 'https://s.test/BBB' });
assert.strictEqual(r.length, 1, 'S-2 短縮コード共通は1行');
assert.deepStrictEqual(Array.from(r[0].codes).sort(), ['AAA', 'BBB']);
console.log('  PASS S-2');

r = run([
  { id: 'g1', name: '既定', url: 'https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=mens/', at: 100 },
  { id: 'g2', name: '女性向け', url: 'https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=female/', at: 120 },
  { id: 'w1', name: '冬セール', url: 'https://x.test/fuyu', at: 300 },
], { 'acc3|w1|af|d': 'https://s.test/CCC' });
assert.strictEqual(r.length, 3, 'S-3 別のセールは別の行');
console.log('  PASS S-3');
console.log('test_sale_stats_dedupe: OK');
