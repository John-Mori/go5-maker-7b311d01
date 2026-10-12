/**
 * tests/test_worker_base.js
 * 短縮URLの発行先(workerBase)の優先順を固定する回帰テスト。
 *
 *  e2e(manual-short.spec.js)は「acc3はドメイン未設定」を前提にしていたが、2026-10-11 に
 *  癒やし倉庫へ xdgh3.com が入って前提が崩れ、v988 以降 smoke が赤のままになった。
 *  「枠はあるがドメインが空のchは旧ドメインへ落とさず '' を返す(=元URLのまま)」守りは
 *  実ドメインの有無に左右されないよう、bluesky.js の実関数を抜き出してここで直接撃つ。
 *
 * 実行: node tests/test_worker_base.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'js', 'bluesky.js'), 'utf8');
const m = src.match(/function workerBase\(account\) \{[\s\S]*?\r?\n  \}\r?\n/);
assert.ok(m, 'bluesky.js から workerBase を抜き出せない');

function make(urlByAcct, store) {
  const ctx = {
    SHORT: { URL_BY_ACCT: urlByAcct, WORKER_URL: 'https://default-short.invalid' },
    localStorage: { getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null) },
    acctId: () => 'acc1',
  };
  vm.createContext(ctx);
  vm.runInContext(m[0], ctx);
  return ctx.workerBase;
}

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('PASS: ' + name); passed++; }
  catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; }
}

const DOMAINS = { acc1: 'https://5mgl.com', acc2: 'https://yoz2.com', acc3: 'https://xdgh3.com' };
const LEGACY = { short_worker_url: 'https://legacy-short.invalid' };

test('既知3chは旧共通上書きがあってもそれぞれの専用ドメイン', () => {
  const wb = make(DOMAINS, LEGACY);
  assert.strictEqual(wb('acc1'), 'https://5mgl.com');
  assert.strictEqual(wb('acc2'), 'https://yoz2.com');
  assert.strictEqual(wb('acc3'), 'https://xdgh3.com');
});

test('枠はあるがドメインが空のchは旧ドメイン/既定へ落とさず空(=元URLのまま)', () => {
  const wb = make(Object.assign({}, DOMAINS, { acc3: '' }), LEGACY);
  assert.strictEqual(wb('acc3'), '');
});

test('chごとの上書きは空なら無視、値があれば最優先', () => {
  assert.strictEqual(make(DOMAINS, { short_worker_url__acc3: '' })('acc3'), 'https://xdgh3.com');
  assert.strictEqual(make(DOMAINS, { short_worker_url__acc3: 'https://own.invalid' })('acc3'), 'https://own.invalid');
});

test('未知のchだけ旧共通上書き→既定へ落ちる', () => {
  assert.strictEqual(make(DOMAINS, LEGACY)('acc9'), 'https://legacy-short.invalid');
  assert.strictEqual(make(DOMAINS, {})('acc9'), 'https://default-short.invalid');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
