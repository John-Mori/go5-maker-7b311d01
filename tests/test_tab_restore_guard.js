/**
 * tests/test_tab_restore_guard.js — affiliate.js の「候補→動画生成で index.html へ来た時、保存タブへ
 *   リダイレクトしない」不変条件を固定する門。
 *
 * 背景(2026-08-16・Chami報告 msg 1538426859535204412「候補→動画生成ボタンを押すと投稿履歴に遷移する」)：
 *   候補ページ(KouhoTeian.html)の「動画生成へ」は sessionStorage['cand_to_movie_pending'] に候補を退避して
 *   index.html へ location.href で遷移する。index.html 起動時の restoreActiveTab_() が go5_active_tab を復元
 *   するが、その値が 'tabVerify'(投稿履歴)/'tabStock'(ドラフト)だと showTab がそれぞれの専用ページ
 *   (StockLists.html / Stock.html)へ location.href し、「候補→動画生成を押したら投稿履歴へ飛ぶ」になる。
 *   恒久対策(C-038)=cand_to_movie_pending がある時は復元(=リダイレクト)を止め、動画作成のまま留める。
 *
 * 検査：
 *   T-1 go5_active_tab='tabVerify' かつ cand_to_movie_pending 有り → StockLists.html へ飛ばない(留まる)。
 *   T-2 go5_active_tab='tabVerify' かつ pending 無し → 従来どおり StockLists.html へリダイレクトする
 *       (=リダイレクト自体は生きていて、T-1 はガードが効いた結果だと保証する対照実験)。
 *
 * ★実DOMは使わない。getElementById 等が返す要素は Proxy で"何を触っても壊れない"偽物にし、
 *   外へ出る手= location.href への代入だけを記録する(判定と分岐は本物のまま実行する)。
 */
'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var source = fs.readFileSync(path.join(__dirname, '..', 'js', 'affiliate.js'), 'utf8');

var fails = 0;
function ok(name) { console.log('  PASS ' + name); }
function ng(name, e) { fails++; console.log('  FAIL ' + name + ' — ' + (e && e.message || e)); }

// 何を触っても例外を出さない偽要素(値の get/set だけ本物っぽく振る舞う)。
function makeEl() {
  var store = { value: '' };
  var self;
  var handler = {
    get: function (t, prop) {
      if (prop === 'value') return store.value;
      if (prop === 'classList') return { add: function () {}, remove: function () {}, toggle: function () {}, contains: function () { return false; } };
      if (prop === 'style') return {};
      if (prop === 'hidden') return false;
      if (prop === 'scrollWidth' || prop === 'clientWidth' || prop === 'scrollLeft' || prop === 'offsetWidth') return 0;
      if (prop === 'offsetParent') return null;
      if (prop === Symbol.toPrimitive || prop === 'toString' || prop === Symbol.toStringTag) return function () { return ''; };
      return function () { return self; }; // 未知プロパティ=呼んでも自分を返す関数(連鎖に強い)
    },
    set: function (t, prop, val) { if (prop === 'value') store.value = val; return true; },
    apply: function () { return self; }
  };
  self = new Proxy(function () {}, handler);
  return self;
}

function mkStorage(seed) {
  var m = Object.assign({}, seed || {});
  return {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(m, k) ? m[k] : null; },
    setItem: function (k, v) { m[k] = String(v); },
    removeItem: function (k) { delete m[k]; }
  };
}

// 1シナリオ実行して「location.href に代入された値の列」を返す。
function run(scn) {
  var hrefLog = [];
  var el = makeEl();
  var doc = {
    readyState: 'complete',
    getElementById: function () { return el; },
    querySelector: function () { return el; },
    querySelectorAll: function () { return []; },
    addEventListener: function () {},
    createElement: function () { return el; },
    documentElement: { setAttribute: function () {}, getAttribute: function () { return null; } },
    body: el,
    head: el,
    fonts: { ready: Promise.resolve() }
  };
  var location = {};
  Object.defineProperty(location, 'href', {
    get: function () { return hrefLog.length ? hrefLog[hrefLog.length - 1] : 'index.html'; },
    set: function (v) { hrefLog.push(String(v)); }
  });
  var sandbox = {
    console: { log: function () {}, warn: function () {}, error: function () {} },
    setTimeout: function () { return 0; },
    clearTimeout: function () {},
    setInterval: function () { return 0; },
    requestAnimationFrame: undefined,
    document: doc,
    location: location,
    navigator: { clipboard: null },
    localStorage: mkStorage(scn.local),
    sessionStorage: mkStorage(scn.session),
    CustomEvent: function (t) { this.type = t; },
    matchMedia: function () { return { matches: false, addEventListener: function () {}, addListener: function () {} }; }
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.window.addEventListener = function () {};
  try { vm.runInNewContext(source, sandbox, { filename: 'affiliate.guard.js' }); }
  catch (e) { /* restoreActiveTab_ は序盤で走る=後続の配線が落ちても判定は済んでいる */ }
  return hrefLog;
}

// T-1 pending 有り → 投稿履歴へ飛ばない。
try {
  var hrefs1 = run({ local: { go5_active_tab: 'tabVerify' }, session: { cand_to_movie_pending: '{"it":{"cid":"x"}}' } });
  var jumped1 = hrefs1.some(function (h) { return /StockLists\.html|Stock\.html/.test(h); });
  assert.strictEqual(jumped1, false, 'pending 有りで専用ページへ飛んではいけない(実際: ' + JSON.stringify(hrefs1) + ')');
  ok('T-1 pending present: no redirect to 投稿履歴/ドラフト');
} catch (e) { ng('T-1 pending present', e); }

// T-2 pending 無し → 従来どおりリダイレクトする(対照)。
try {
  var hrefs2 = run({ local: { go5_active_tab: 'tabVerify' }, session: {} });
  var jumped2 = hrefs2.some(function (h) { return /StockLists\.html/.test(h); });
  assert.strictEqual(jumped2, true, 'pending 無しなら 投稿履歴へリダイレクトするはず(実際: ' + JSON.stringify(hrefs2) + ')');
  ok('T-2 no pending: redirect to 投稿履歴 still happens (control)');
} catch (e) { ng('T-2 no pending (control)', e); }

if (fails) { console.log('FAIL: ' + fails + ' 件'); process.exit(1); }
console.log('OK: test_tab_restore_guard.js 全緑');
