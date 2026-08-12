/**
 * tests/test_idb_failopen.js — core/idb-store.js の「読み取りは源で fail-open」不変条件を固定する門。
 *
 * 背景(2026-08-13・改修α毎朝の振り返り)：直近24hの改修で「iOS Safari の IndexedDB が無言で死ぬ
 *   (idb-timeout / open-timeout / 接続閉じ)」→ get() の reject が可視エラーへ直行する再発が
 *   経路ごとに5件出た(resolveVideoBlob_『動画データの取得に失敗しました』・候補読込ハング 等)。
 *   恒久対策(C-038)として get() を源で null へ倒した。この不変条件が将来の改修で崩れないよう門で守る。
 *
 * 検査：
 *   T-1 open() が失敗し続ける環境でも Go5Idb.get() は reject せず null を返す(読み取り fail-open)。
 *   T-2 同じ環境で Go5Idb.set() は reject する(書き込みの失敗は握り潰さない=保存再試行のため)。
 *
 * ★実 indexedDB は使わない。open() の request が次tickで onerror を撃つ偽物を差し込み、
 *   8秒の番犬を待たずに reject 経路を高速に踏ませる(open失敗はwithStoreが1回だけ張り直して再failする)。
 */
'use strict';

var assert = require('assert');
var path = require('path');

// ── 偽の indexedDB：open() は必ず失敗する(onerror を次tickで撃つ)。set/get どちらも open で詰まる ──
global.indexedDB = {
  open: function () {
    var req = { onupgradeneeded: null, onsuccess: null, onerror: null, onblocked: null, result: null, error: new Error('fake-open-fail') };
    setTimeout(function () { if (typeof req.onerror === 'function') req.onerror(); }, 0);
    return req;
  }
};

// requestPersist() は navigator を触るが未定義なら try/catch で無害に抜ける。念のため空で与える。
if (typeof global.navigator === 'undefined') global.navigator = {};

var Idb = require(path.join(__dirname, '..', 'core', 'idb-store.js'));

var fails = 0;
function ok(name) { console.log('  PASS ' + name); }
function ng(name, e) { fails++; console.log('  FAIL ' + name + ' — ' + (e && e.message || e)); }

(async function () {
  // T-1 get() は open が失敗し続けても null に倒れる(reject しない)。
  try {
    var v = await Idb.get('stock_v_anything');
    assert.strictEqual(v, null, 'get() は失敗時 null を返すべき(reject 禁止)');
    ok('T-1 get() fails open to null');
  } catch (e) { ng('T-1 get() fails open to null', e); }

  // T-2 set() は失敗時にちゃんと reject する(握り潰さない)。
  try {
    var rejected = false;
    try { await Idb.set('stock_v_anything', {}); }
    catch (e) { rejected = true; }
    assert.strictEqual(rejected, true, 'set() は失敗時 reject すべき(保存の再試行が回るように)');
    ok('T-2 set() still rejects on failure');
  } catch (e) { ng('T-2 set() still rejects on failure', e); }

  if (fails) { console.log('FAIL: ' + fails + ' 件'); process.exit(1); }
  console.log('OK: test_idb_failopen.js 全緑');
})();
