// 投稿モードの投稿画像が「開いてもなかなか出ない」の番犬(Chami msg 1561074852478062743「すぐ表示して欲しい」)。
// stock.js の本物の resolveSrcImageBlob_ を切り出して実行する。外へ出る手(IDB・R2)だけ偽物にし、判定と分岐は本物のまま。
//   T-1 IDBが無言で固まっても、雲(R2)の元画像が3秒以内に返る(旧=IDB待ちで永久に出ない)
//   T-2 取り出し中に同じidを2回呼んでもR2は1回だけ・2回目以降はメモリから即返る
//   T-3 IDBに元画像があればR2は引かない
//   T-4 R2から取った元画像は手元IDBへ戻す(次に開く時は即出る)
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(process.env.STOCK_JS || path.join(__dirname, '..', 'js', 'stock.js'), 'utf8');
function cut(startMark, endMark) {
  const a = src.indexOf(startMark); assert(a >= 0, 'not found: ' + startMark);
  const b = src.indexOf(endMark, a); assert(b > a, 'not found: ' + endMark);
  return src.slice(a, b);
}
const race = cut('  function raceWithFallback_(', '  // 手元IDBが返事をしない時に雲(R2)を並走させるまでの猶予。');
const resolve = cut('  function resolveSrcImageBlob_(', '\n  }\n') + '\n  }\n';
const pre = src.indexOf('var SRC_IDB_HEAD_START_MS') >= 0
  ? cut('  var SRC_IDB_HEAD_START_MS', '  function resolveSrcImageBlob_(')
  : '';

function makeEnv(store, r2) {
  const ctx = { console, setTimeout, clearTimeout, Promise,
    durlToBlob_: function () { return Promise.resolve({ size: 9, from: 'mirror' }); },
    idb: function () { return store; },
    window: { Go5Sync: { fetchBlobR2At: r2 } } };
  ctx.Go5Sync = ctx.window.Go5Sync;
  vm.createContext(ctx);
  vm.runInContext(race + pre + resolve + '\nthis.resolveSrcImageBlob_ = resolveSrcImageBlob_;', ctx);
  return ctx;
}
function within(p, ms) {
  return Promise.race([p, new Promise(function (_, rej) { setTimeout(function () { rej(new Error('timeout ' + ms + 'ms')); }, ms); })]);
}

(async function () {
  // T-1/T-2: IDBが固まる端末
  let r2Calls = 0;
  const hung = { get: function () { return new Promise(function () {}); }, set: function () { return Promise.resolve(); } };
  const env1 = makeEnv(hung, function () { r2Calls++; return Promise.resolve({ size: 100, from: 'r2' }); });
  const t0 = Date.now();
  const [b1, b2] = await within(Promise.all([env1.resolveSrcImageBlob_('d1'), env1.resolveSrcImageBlob_('d1')]), 3000);
  assert.strictEqual(b1 && b1.from, 'r2', 'IDBが固まってもR2の元画像が返る');
  assert.strictEqual(b2, b1);
  assert.strictEqual(r2Calls, 1, '取り出し中の同じidはR2を1回だけ');
  const t1 = Date.now();
  const b3 = await env1.resolveSrcImageBlob_('d1');
  assert.strictEqual(b3, b1); assert(Date.now() - t1 < 50, '2回目はメモリから即');
  assert.strictEqual(r2Calls, 1);
  console.log('  PASS T-1/T-2 (' + (t1 - t0) + 'ms)');

  // T-3: IDBに元画像あり
  let r2b = 0;
  const local = { get: function (k) { return Promise.resolve(k.indexOf('stock_img_') === 0 ? { size: 5, from: 'idb' } : null); }, set: function () { return Promise.resolve(); } };
  const env3 = makeEnv(local, function () { r2b++; return Promise.resolve({ size: 1, from: 'r2' }); });
  const b4 = await within(env3.resolveSrcImageBlob_('d3'), 1000);
  assert.strictEqual(b4.from, 'idb'); assert.strictEqual(r2b, 0, '手元にあればR2を引かない');
  console.log('  PASS T-3');

  // T-4: IDBは空(退避済み)=R2から取ったら手元へ戻す
  const wrote = {};
  const empty = { get: function (k) { return Promise.resolve(wrote[k] || null); }, set: function (k, v) { wrote[k] = v; return Promise.resolve(); } };
  const env4 = makeEnv(empty, function () { return Promise.resolve({ size: 7, from: 'r2' }); });
  const b5 = await within(env4.resolveSrcImageBlob_('d4'), 1000);
  assert.strictEqual(b5.from, 'r2');
  await new Promise(function (r) { setTimeout(r, 20); });
  assert.strictEqual(wrote['stock_img_d4'], b5, 'R2の元画像を手元IDBへ戻す');
  console.log('  PASS T-4');
  console.log('test_draft_img_fast: OK');
})().catch(function (e) { console.error('test_draft_img_fast: FAIL', e.message); process.exit(1); });
