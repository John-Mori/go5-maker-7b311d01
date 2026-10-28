/**
 * tests/test_autodraft.js
 * 無人ドラフト自動作成の口 js/autodraft.js(β-5b・設計_無人ドラフト自動作成_20261024.md §4)の単体テスト。
 *   受入: 写真が入らない/同期が未設定の時は make() を呼ばずに {ok:false, reason} を返す。
 *   加えて: 自分からは動かない(URLパラメータ無し)・同じ日同じcidは作り直さない・make() に auto を渡す。
 *
 * 実行: node tests/test_autodraft.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'js', 'autodraft.js'), 'utf8');

let passed = 0, failed = 0;
const pending = [];
function test(name, fn) {
  pending.push(Promise.resolve().then(fn).then(
    () => { console.log('PASS: ' + name); passed++; },
    (e) => { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; }
  ));
}

// ページ側の最小の偽物。make() は呼ばれたら video-created を出し、saveStock_ の代わりにメタを1行書く。
function makeEnv(opt) {
  opt = opt || {};
  const els = {};
  ['author', 'top', 'movieWorkUrl', 'movieGoal', 'movieCmtType', 'status'].forEach((id) => {
    els[id] = { value: '', textContent: '', dispatchEvent() {} };
  });
  els.testMode = { checked: true, dispatchEvent() {} };
  const store = {};
  const listeners = {};
  const calls = { make: [], setFg: 0 };
  const win = {};
  const doc = {
    getElementById: (id) => els[id] || null,
    addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    removeEventListener: (t, f) => { listeners[t] = (listeners[t] || []).filter((x) => x !== f); },
  };
  Object.assign(win, {
    getCurrentAccount: () => opt.account || 'acc3',
    Go5Sync: { configured: () => opt.configured !== false, hasBlobR2At: () => Promise.resolve(opt.cloud !== false) },
    Go5NewMovieReset() { els.movieGoal.value = ''; els.movieCmtType.value = ''; },
    Go5ClearForeground: () => 7,
    Go5SetForegroundFileReady: () => { calls.setFg++; return Promise.resolve({ ok: opt.photoOk !== false, reason: opt.photoOk === false ? 'decode' : '' }); },
    __go5RequestMake: async (o) => {
      calls.make.push(o);
      if (opt.makeStops) { els.status.textContent = '先に写真を選んでください。'; return; }
      const detail = { videoId: 'v1', draft: o.draft, auto: o.auto, autoAlt: o.autoAlt, srcMark: win.__go5MovieSrcMark };
      (listeners['video-created'] || []).forEach((f) => f({ detail }));
      const ts = Date.now();
      const list = JSON.parse(store.go5_stock_meta || '[]');
      list.unshift({ id: 'stk' + ts, ts, videoId: 'v1', videoBytes: 1234, videoReadyAt: ts, srcMark: detail.srcMark, auto: detail.auto });
      store.go5_stock_meta = JSON.stringify(list);
    },
  });
  const ctx = {
    window: win, document: doc, console,
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
    Event: function (t) { this.type = t; },
    File: function (parts, name, o) { this.name = name; this.type = o && o.type; },
    Uint8Array, atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    setTimeout, Promise, Date, JSON, Number, String,
  };
  if (opt.seedMeta) store.go5_stock_meta = JSON.stringify(opt.seedMeta);
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  return { win, els, calls, store };
}
const SPEC = { cid: 'd_123', date: '20261029', rank: 1, title: '題名A', circle: 'サークル', workUrl: 'https://example.invalid/w',
  image: { b64: Buffer.from('jpegbytes').toString('base64'), type: 'image/jpeg' }, altTitles: ['題名B'], hookNote: 'n', waitMs: 3000 };

test('A-1: 版を公開し、読み込んだだけでは make() を呼ばない', () => {
  const e = makeEnv();
  assert.strictEqual(e.win.FivesecAutoDraft.version, 1);
  assert.strictEqual(e.calls.make.length, 0);
  assert.ok(!/URLSearchParams|location\.search|location\.hash/.test(SRC), 'URLパラメータを読んでいる');
});
test('A-2: 同期が未設定なら sync_unconfigured で止まり、make() を呼ばない', async () => {
  const e = makeEnv({ configured: false });
  const r = await e.win.FivesecAutoDraft.run(SPEC);
  assert.deepStrictEqual([r.ok, r.reason], [false, 'sync_unconfigured']);
  assert.strictEqual(e.calls.make.length, 0);
});
test('A-3: 画像が無ければ no_image、写真の読込が失敗すれば photo で止まる(fgImg 無しで作らない)', async () => {
  const e1 = makeEnv();
  const r1 = await e1.win.FivesecAutoDraft.run(Object.assign({}, SPEC, { image: null }));
  assert.deepStrictEqual([r1.ok, r1.reason], [false, 'no_image']);
  const e2 = makeEnv({ photoOk: false });
  const r2 = await e2.win.FivesecAutoDraft.run(SPEC);
  assert.deepStrictEqual([r2.ok, r2.reason], [false, 'photo']);
  assert.strictEqual(e1.calls.make.length + e2.calls.make.length, 0);
});
test('A-4: make() が入口ガードで戻ったら make_stopped と status の文を返す', async () => {
  const e = makeEnv({ makeStops: true });
  const r = await e.win.FivesecAutoDraft.run(SPEC);
  assert.deepStrictEqual([r.ok, r.reason], [false, 'make_stopped']);
  assert.ok(/写真/.test(r.detail));
});
test('A-5: acc3 以外では作らない', async () => {
  const r = await makeEnv({ account: 'acc1' }).win.FivesecAutoDraft.run(SPEC);
  assert.deepStrictEqual([r.ok, r.reason], [false, 'account']);
});
test('A-6: 正常系は ドラフト作成+auto/autoAlt を make() へ渡し、id と cloud を返す', async () => {
  const e = makeEnv();
  const r = await e.win.FivesecAutoDraft.run(SPEC);
  assert.strictEqual(r.ok, true, JSON.stringify(r));
  assert.ok(/^stk\d+$/.test(r.id));
  assert.strictEqual(r.cloud, true);
  assert.strictEqual(e.calls.make[0].draft, true);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(e.calls.make[0].auto)), { date: '20261029', rank: 1 });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(e.calls.make[0].autoAlt.titles)), ['題名B']);
  assert.strictEqual(e.els.top.value, '題名A');
  assert.strictEqual(e.els.movieGoal.value, '成約');
  assert.strictEqual(e.els.movieCmtType.value, '⑥自己投影(成約)');
  assert.strictEqual(e.els.testMode.checked, false, '無人便が testMode のまま作っている');
  const meta = JSON.parse(e.store.go5_stock_meta)[0];
  assert.strictEqual(meta.srcMark.cid, 'd_123');
});
test('A-7: 同じ日・同じcidが着地済みなら作り直さず dup で返す(4本目を増やさない)', async () => {
  const e = makeEnv({ seedMeta: [{ id: 'stk1', ts: 1, videoId: 'v0', videoReadyAt: 2, srcMark: { cid: 'd_123', hash: 'h' }, auto: { date: '20261029', rank: 1 } }] });
  const r = await e.win.FivesecAutoDraft.run(SPEC);
  assert.deepStrictEqual([r.ok, r.dup, r.id], [true, true, 'stk1']);
  assert.strictEqual(e.calls.make.length, 0);
});
test('A-8: stock.js の saveStock_ は auto/autoAlt を evDetail から受け取り、app.js は opts から通す', () => {
  const stock = fs.readFileSync(path.join(__dirname, '..', 'js', 'stock.js'), 'utf8');
  const app = fs.readFileSync(path.join(__dirname, '..', 'js', 'app.js'), 'utf8');
  assert.ok(/auto: \(evDetail\.auto && evDetail\.auto\.date\)/.test(stock));
  assert.ok(/autoAlt: \(evDetail\.auto && evDetail\.autoAlt\)/.test(stock));
  assert.ok(/auto: \(opts && opts\.auto\) \|\| null, autoAlt: \(opts && opts\.autoAlt\) \|\| null/.test(app));
});

Promise.all(pending).then(() => {
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
});
