/**
 * tests/test_hist_store.js — core/hist-store.js(Go5Hist)の不変条件を「実行で」固定する。
 *
 * ★test-must-fail: LS と IDB にモックを差し込み、ハイドレート/read/write/union/200件上限/CACHE削除を
 *   本物のロジックで通す(外へ出る手=IDB/LSだけ偽物、判定と分岐は本物)。union やコアレスを壊すと落ちる。
 *
 * 実行: node tests/test_hist_store.js
 */
'use strict';

var assert = require('assert');
var path = require('path');

// ── 偽 localStorage(Map裏打ち・同期) ───────────────────────────────────
function makeLS() {
  var m = {};
  return {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(m, k) ? m[k] : null; },
    setItem: function (k, v) { m[k] = String(v); },
    removeItem: function (k) { delete m[k]; },
    _dump: function () { return m; }
  };
}

// ── 偽 Go5Idb(メモリ・非同期・getResultは{ok,value}) ───────────────────
function makeIdb() {
  var store = {};
  return {
    _store: store,
    available: function () { return true; },
    getResult: function (key) {
      return Promise.resolve(
        Object.prototype.hasOwnProperty.call(store, key)
          ? { ok: true, value: store[key] }
          : { ok: true, value: null }
      );
    },
    set: function (key, val) { store[key] = JSON.parse(JSON.stringify(val)); return Promise.resolve(true); },
    del: function (key) { delete store[key]; return Promise.resolve(true); }
  };
}

function freshModule() {
  delete require.cache[require.resolve(path.join(__dirname, '..', 'core', 'hist-store.js'))];
  return require(path.join(__dirname, '..', 'core', 'hist-store.js'));
}

function waitHydrated(Hist, keys, timeoutMs) {
  return new Promise(function (resolve, reject) {
    var t0 = Date.now();
    (function poll() {
      var allDone = keys.every(function (k) {
        var s = Hist.state(k);
        return s === 'hydrated' || s === 'degraded';
      });
      if (allDone) return resolve();
      if (Date.now() - t0 > (timeoutMs || 2000)) return reject(new Error('hydrate timeout'));
      setTimeout(poll, 5);
    })();
  });
}
function tick(ms) { return new Promise(function (r) { setTimeout(r, ms || 10); }); }

var pass = 0;
function ok(cond, msg) { assert.ok(cond, msg); pass++; }

(async function () {
  // ===== 1. classify(純関数・登録キー分類) =====================================
  {
    global.localStorage = makeLS();
    global.Go5Idb = makeIdb();
    var Hist = freshModule();
    ok(Hist.classify('short_hist__acc1') === 'array', 'classify array');
    ok(Hist.classify('verify_manual__acc2') === 'array', 'classify array acc2');
    ok(Hist.classify('verify_yt__acc1') === 'map', 'classify map');
    ok(Hist.classify('sheet_hist_raw__acc2') === 'cache', 'classify cache');
    ok(Hist.classify('some_other_key') === null, 'classify passthrough=null');
    await waitHydrated(Hist, Hist.keys(), 2000);
  }

  // ===== 2. 非破壊union: LSにA・IDBにB → readで両方(少ない方に消えない) ==========
  {
    var LS = makeLS();
    var IDB = makeIdb();
    var A = { id: 'a1', manual: true, ts: 100 };
    var B = { id: 'b1', manual: true, ts: 200 };
    LS.setItem('short_hist__acc1', JSON.stringify([A]));
    IDB._store['hist:short_hist__acc1'] = { v: 1, rev: 5, items: [B] };
    global.localStorage = LS;
    global.Go5Idb = IDB;
    var Hist = freshModule();
    await waitHydrated(Hist, ['short_hist__acc1'], 2000);
    await tick(20);
    var got = Hist.read('short_hist__acc1');
    var ids = got.map(function (x) { return x.id; }).sort();
    ok(ids.length === 2 && ids[0] === 'a1' && ids[1] === 'b1', 'union keeps both LS+IDB items (got=' + JSON.stringify(ids) + ')');
    // ts降順で並ぶ(B=200が先頭)
    ok(got[0].id === 'b1', 'union ordered by ts desc');
    // 書き戻しでLSにも両方載る(後追いコピー)
    var lsBack = JSON.parse(LS.getItem('short_hist__acc1'));
    ok(lsBack.length === 2, 'LS after-copy has both after hydrate');
  }

  // ===== 3. write: ミラー即時反映＋LS/IDB両方へ・receipt形 ======================
  {
    var LS = makeLS();
    var IDB = makeIdb();
    global.localStorage = LS;
    global.Go5Idb = IDB;
    var Hist = freshModule();
    await waitHydrated(Hist, ['short_hist__acc1'], 2000);
    var C = { id: 'c1', manual: true, ts: 300 };
    var receipt = Hist.write('short_hist__acc1', [C]);
    ok(receipt && receipt.lsOk === true, 'write receipt.lsOk true');
    ok(receipt && receipt.idb && typeof receipt.idb.then === 'function', 'write receipt.idb is thenable');
    ok(Hist.read('short_hist__acc1').some(function (x) { return x.id === 'c1'; }), 'write reflected in mirror read immediately');
    var landed = await receipt.idb;
    ok(landed === true, 'write receipt.idb resolves true (IDB landed)');
    ok(IDB._store['hist:short_hist__acc1'] && IDB._store['hist:short_hist__acc1'].items.some(function (x) { return x.id === 'c1'; }), 'IDB persisted the write');
    ok(JSON.parse(LS.getItem('short_hist__acc1')).some(function (x) { return x.id === 'c1'; }), 'LS after-copy persisted the write');
  }

  // ===== 4. 200件上限(ARRAYのみ・先頭が最新) ==================================
  {
    var LS = makeLS();
    var IDB = makeIdb();
    global.localStorage = LS;
    global.Go5Idb = IDB;
    var Hist = freshModule();
    await waitHydrated(Hist, ['short_hist__acc1'], 2000);
    var big = [];
    for (var i = 0; i < 250; i++) big.push({ id: 'x' + i, manual: true, ts: 10000 - i });
    var r = Hist.write('short_hist__acc1', big);
    await r.idb;
    ok(Hist.read('short_hist__acc1').length === 200, '200-cap on ARRAY (got ' + Hist.read('short_hist__acc1').length + ')');
    ok(Hist.read('short_hist__acc1')[0].id === 'x0', 'head is newest after cap');
  }

  // ===== 5. MAP union(verify_yt) =============================================
  {
    var LS = makeLS();
    var IDB = makeIdb();
    LS.setItem('verify_yt__acc1', JSON.stringify({ k1: 'https://a' }));
    IDB._store['hist:verify_yt__acc1'] = { v: 1, rev: 3, map: { k2: 'https://b' } };
    global.localStorage = LS;
    global.Go5Idb = IDB;
    var Hist = freshModule();
    await waitHydrated(Hist, ['verify_yt__acc1'], 2000);
    await tick(20);
    var m = Hist.read('verify_yt__acc1');
    ok(m && m.k1 === 'https://a' && m.k2 === 'https://b', 'map union keeps both keys');
  }

  // ===== 6. CACHE(sheet_hist_raw)はIDB専属＝IDB着地後にLSから消える =============
  {
    var LS = makeLS();
    var IDB = makeIdb();
    LS.setItem('sheet_hist_raw__acc1', JSON.stringify([{ a: 1 }]));
    global.localStorage = LS;
    global.Go5Idb = IDB;
    var Hist = freshModule();
    await waitHydrated(Hist, ['sheet_hist_raw__acc1'], 2000);
    await tick(30);
    ok(LS.getItem('sheet_hist_raw__acc1') === null, 'CACHE LS key deleted after IDB migration (quota解放)');
    ok(IDB._store['hist:sheet_hist_raw__acc1'] != null, 'CACHE persisted to IDB');
  }

  // ===== 7. IDB不可用でもdegradeして壊れない(LSだけで動く) =====================
  {
    var LS = makeLS();
    LS.setItem('short_hist__acc1', JSON.stringify([{ id: 'z1', manual: true, ts: 1 }]));
    global.localStorage = LS;
    global.Go5Idb = { available: function () { return false; } }; // set/getResult無し=idbUsable false
    var Hist = freshModule();
    await waitHydrated(Hist, ['short_hist__acc1'], 2000);
    ok(Hist.read('short_hist__acc1').some(function (x) { return x.id === 'z1'; }), 'degraded mode still reads LS');
    var rc = Hist.write('short_hist__acc1', [{ id: 'z2', manual: true, ts: 2 }]);
    ok(rc.lsOk === true, 'degraded write still lands in LS');
    var idbLanded = await rc.idb;
    ok(idbLanded === false, 'degraded write idb resolves false (no IDB)');
  }

  console.log('test_hist_store: ' + pass + ' assertions PASS');
})().catch(function (e) {
  console.error('test_hist_store FAILED:', e && e.stack || e);
  process.exit(1);
});
