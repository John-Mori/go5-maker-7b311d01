/**
 * tests/test_idb_recovery.js — core/idb-store.js の「無言死→回復を1回だけ知らせる」不変条件を固定する門。
 *
 * 背景(2026-08-16・Chami報告「更新では直らない・閉じて開くと出る」)：iOS Safari(WebKit)は IndexedDB を
 *   プロセス単位で無言死させ、リロード(同一プロセス再利用)では治らない。この間 get() は fail-open で null を
 *   返すため画像が空表示のまま固定される。恒久対策(C-038)として idb-store に健康状態の唯一の正本を置き、
 *   「失敗→その後の成功」で go5-idb-recovered を"ちょうど1回"発火する。購読側(candidates.js/stock.js)が
 *   閉じ直さずに画像を読み直せるようにするのがこのイベントの役目=その契約を将来の改修から守る門。
 *
 * 検査：
 *   T-1 open() が失敗し続ける間、get() は null を返し isHealthy()=false・recovered は発火しない。
 *   T-2 接続が回復した最初の成功で go5-idb-recovered が"ちょうど1回"発火し isHealthy()=true になる。
 *   T-3 回復後の連続成功では二度と発火しない(状態遷移の時だけ鳴る=白フラッシュ連発を防ぐ)。
 *
 * ★実 indexedDB は使わない。healthy フラグで open の成否を切り替える偽物を vm sandbox に差し込む。
 */
'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var fails = 0;
function ok(name) { console.log('  PASS ' + name); }
function ng(name, e) { fails++; console.log('  FAIL ' + name + ' — ' + (e && e.message || e)); }

var source = fs.readFileSync(path.join(__dirname, '..', 'core', 'idb-store.js'), 'utf8');

// ── 偽の document：dispatchEvent を数え、visibilitychange 等の購読も受ける ──
var dispatched = [];
var fakeDoc = {
  hidden: false,
  _listeners: {},
  addEventListener: function (t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
  dispatchEvent: function (ev) {
    dispatched.push(ev && ev.type);
    (this._listeners[(ev && ev.type)] || []).forEach(function (f) { try { f(ev); } catch (e) {} });
    return true;
  }
};
function recoveredCount() { return dispatched.filter(function (t) { return t === 'go5-idb-recovered'; }).length; }

// ── 偽の indexedDB：healthy=false の間は open が onerror、true になると onsuccess＋即完了するTX ──
var healthy = false;
var sandbox = {
  console: console,
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  navigator: {},
  document: fakeDoc,
  CustomEvent: function (type) { this.type = type; },
  module: { exports: {} },
  exports: {},
  __GO5_IDB_TIMEOUT_MS: 15,
  IDBKeyRange: { bound: function () { return {}; } }
};
sandbox.globalThis = sandbox;
sandbox.indexedDB = {
  open: function () {
    var req = { onupgradeneeded: null, onsuccess: null, onerror: null, onblocked: null, result: null, error: null };
    if (!healthy) {
      req.error = new Error('fake-open-fail');
      setTimeout(function () { if (typeof req.onerror === 'function') req.onerror(); }, 0);
      return req;
    }
    var db = {
      objectStoreNames: { contains: function () { return true; } },
      close: function () {},
      transaction: function () {
        var t = {
          oncomplete: null, onerror: null, onabort: null, error: null,
          objectStore: function () { return { get: function () { return { result: undefined }; } }; }
        };
        setTimeout(function () { if (typeof t.oncomplete === 'function') t.oncomplete(); }, 0);
        return t;
      }
    };
    req.result = db;
    setTimeout(function () { if (typeof req.onsuccess === 'function') req.onsuccess(); }, 0);
    return req;
  }
};

vm.runInNewContext(source, sandbox, { filename: 'idb-store.recovery.js' });
var Idb = sandbox.module.exports;

(async function () {
  // T-1 死んでいる間：null に倒れ、不健康・recovered 未発火。
  try {
    var v1 = await Idb.get('stock_v_x');
    assert.strictEqual(v1, null, '死亡中の get は null');
    assert.strictEqual(Idb.isHealthy(), false, '失敗後は isHealthy()=false');
    assert.strictEqual(recoveredCount(), 0, '死亡中は recovered を出さない');
    ok('T-1 unhealthy: null, isHealthy=false, no recovered');
  } catch (e) { ng('T-1 unhealthy state', e); }

  // T-2 回復：最初の成功で recovered ちょうど1回・isHealthy()=true。
  try {
    healthy = true;
    var v2 = await Idb.get('stock_v_x');
    assert.strictEqual(v2, null, 'キー無しは null(成功・値なし)');
    assert.strictEqual(Idb.isHealthy(), true, '回復後は isHealthy()=true');
    assert.strictEqual(recoveredCount(), 1, '回復の最初の成功で recovered はちょうど1回');
    ok('T-2 recovery fires go5-idb-recovered exactly once');
  } catch (e) { ng('T-2 recovery event', e); }

  // T-3 連続成功では再発火しない(遷移した時だけ鳴る)。
  try {
    await Idb.get('stock_v_x');
    await Idb.get('stock_v_y');
    assert.strictEqual(recoveredCount(), 1, '成功継続では recovered を追加発火しない');
    ok('T-3 steady healthy: no repeated recovered');
  } catch (e) { ng('T-3 no repeat', e); }

  if (fails) { console.log('FAIL: ' + fails + ' 件'); process.exit(1); }
  console.log('OK: test_idb_recovery.js 全緑');
})();
