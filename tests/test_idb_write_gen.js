/**
 * tests/test_idb_write_gen.js — core/idb-store.js の書き込み印(writeGen)の不変条件。
 *   同期はこの印が前回の全読みから変わっていない時だけ前回の読取結果を使い回す(core/sync.js idbStep)。
 *   印が書き込みで進まないと「中身が変わったのに同期されない」になるため、ここで固定する。
 * 検査:
 *   W-1 set/del は成否に関わらず印を進める(失敗した書込も途中まで反映され得るので使い回させない)
 *   W-2 get/getResult は印を進めない(読むだけで全読みに戻らない)
 *   W-3 他タブの書き込み(localStorage の sync2_idb_wgen が変わる)でも印が変わる
 *   W-4 localStorage が読めない環境では毎回違う印=使い回さない
 */
'use strict';
var assert = require('assert');
var path = require('path');

global.indexedDB = {
  open: function () {
    var req = { onupgradeneeded: null, onsuccess: null, onerror: null, onblocked: null, result: null, error: new Error('fake-open-fail') };
    setTimeout(function () { if (typeof req.onerror === 'function') req.onerror(); }, 0);
    return req;
  }
};
if (typeof global.navigator === 'undefined') global.navigator = {};
var lsStore = {}, lsBroken = false;
global.localStorage = {
  getItem: function (k) { if (lsBroken) throw new Error('ls-broken'); return k in lsStore ? lsStore[k] : null; },
  setItem: function (k, v) { if (lsBroken) throw new Error('ls-broken'); lsStore[k] = String(v); },
  removeItem: function (k) { delete lsStore[k]; }
};

var Idb = require(path.join(__dirname, '..', 'core', 'idb-store.js'));

(async function () {
  assert.strictEqual(typeof Idb.writeGen, 'function', 'Go5Idb.writeGen が公開されている');
  var g0 = Idb.writeGen();
  await Idb.get('ref:a'); await Idb.getResult('ref:a');
  assert.strictEqual(Idb.writeGen(), g0, 'W-2 読むだけでは印は進まない');

  var p = Idb.set('ref:a', { v: 1 });
  var gDuring = Idb.writeGen();
  assert.notStrictEqual(gDuring, g0, 'W-1 set を呼んだ瞬間に印が進む');
  await p.catch(function () {});
  assert.notStrictEqual(Idb.writeGen(), gDuring, 'W-1 set の決着(失敗でも)で印がもう一度進む');

  var g1 = Idb.writeGen();
  await Idb.del('ref:a').catch(function () {});
  assert.notStrictEqual(Idb.writeGen(), g1, 'W-1 del でも印が進む');

  var g2 = Idb.writeGen();
  lsStore.sync2_idb_wgen = 'other-tab-' + Date.now();
  assert.notStrictEqual(Idb.writeGen(), g2, 'W-3 他タブの書き込み印でも変わる');

  lsBroken = true;
  assert.notStrictEqual(Idb.writeGen(), Idb.writeGen(), 'W-4 localStorage が読めない時は毎回違う印');
  lsBroken = false;

  console.log('OK test_idb_write_gen: writeGen moves on every write, not on reads, and across tabs');
})().catch(function (e) { console.error('FAIL: ' + (e && e.stack || e)); process.exit(1); });
