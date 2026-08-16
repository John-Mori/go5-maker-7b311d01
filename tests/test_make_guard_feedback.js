/**
 * tests/test_make_guard_feedback.js — app.js make() の「入口ガードで止める時は、押されたボタン自身にも
 *   必ず反応(ラベル点滅)を返す」不変条件を固定する門。
 *
 * 背景(2026-08-16・Chami報告 msg 1538456137446334494「動画が生成されない/直ってない」):
 *   候補→動画生成へ の画像ハンドオフが失敗すると fgImg=null のまま make() へ入り、写真未選択ガード
 *   (app.js の `if(!fgImg)…return`)で早期returnする。従来はここで #status に一言出すだけで、
 *   押したボタン(📦ドラフトで作成 / 今すぐ作成)は無反応=Chamiには「押しても何も起きない」に見えた。
 *   恒久対策(C-038)= 入口ガードを guardStop_() に集約し、status に加えて押されたボタンを flashBtn で
 *   一時ラベル化する=「ガードで止まる=無反応」というクラス全体を根絶する。
 *
 * ★ソースの文字列一致では検査しない。実際の app.js を vm で読み込み、本物の make() を
 *   window.__go5RequestMake() から呼び、fgImg=null の状態で「押されたボタンの textContent が
 *   変わる(=反応が返る)」ことを実行で確かめる。外へ出る手(canvas描画/フォント/録画)は偽物にし、
 *   判定と分岐(どのボタンを・どう反応させるか)は本物のまま通す。
 *
 * 検査:
 *   T-1 今すぐ作成(__go5DraftPending 無し)で写真未選択 → makeBtn のラベルが「⚠ 写真が必要」へ変わる。
 *   T-2 ドラフトで作成(__go5DraftPending 有り)で写真未選択 → draftMakeBtn のラベルが変わる。
 *   T-3 対照: status にもメッセージが出る(ガード自体は生きている)。
 */
'use strict';

var assert = require('assert');
var fs = require('fs');
var path = require('path');
var vm = require('vm');

var source = fs.readFileSync(path.join(__dirname, '..', 'js', 'app.js'), 'utf8');

var fails = 0;
function ok(name) { console.log('  PASS ' + name); }
function ng(name, e) { fails++; console.log('  FAIL ' + name + ' — ' + (e && e.message || e)); }

// id ごとに同じ偽要素を返す(els.makeBtn === getElementById('makeBtn') を成立させ、点滅を観測できる)。
function makeCtx2d() {
  return new Proxy({}, { get: function () { return function () { return makeCtx2d(); }; } });
}
function makeEl(id) {
  var store = { textContent: '', value: '', disabled: false, checked: false, hidden: false, width: 1080, height: 1920, id: id || '' };
  var dataset = {};
  var self;
  var handler = {
    get: function (t, prop) {
      if (prop in store) return store[prop];
      if (prop === 'dataset') return dataset;
      if (prop === 'classList') return { add: function () {}, remove: function () {}, toggle: function () {}, contains: function () { return false; } };
      if (prop === 'style') return {};
      if (prop === 'files') return [];
      if (prop === 'getContext') return function () { return makeCtx2d(); };
      if (prop === Symbol.toPrimitive || prop === 'toString' || prop === Symbol.toStringTag) return function () { return ''; };
      // 未知プロパティ=呼んでも自分を返す関数(メソッド連鎖・イベント配線に強い)
      return function () { return self; };
    },
    set: function (t, prop, val) { store[prop] = val; return true; }
  };
  self = new Proxy(function () {}, handler);
  return self;
}

function run(scn) {
  var els = {};
  function getEl(id) { if (!els[id]) els[id] = makeEl(id); return els[id]; }

  var doc = {
    readyState: 'complete',
    getElementById: getEl,
    querySelector: function () { return getEl('_q'); },
    querySelectorAll: function () { return []; },
    addEventListener: function () {},
    removeEventListener: function () {},
    createElement: function (tag) { return makeEl(tag); },
    documentElement: { setAttribute: function () {}, getAttribute: function () { return null; }, classList: { add: function () {}, remove: function () {} } },
    body: makeEl('body'), head: makeEl('head'),
    dispatchEvent: function () { return true; },
    fonts: { ready: Promise.resolve(), load: function () { return Promise.resolve(); } }
  };
  var sandbox = {
    console: { log: function () {}, warn: function () {}, error: function () {} },
    setTimeout: function () { return 0; }, clearTimeout: function () {},
    setInterval: function () { return 0; }, clearInterval: function () {},
    requestAnimationFrame: function (cb) { return 0; },
    performance: { now: function () { return 0; } },
    document: doc,
    location: { href: 'index.html' },
    navigator: { clipboard: null },
    localStorage: { getItem: function () { return null; }, setItem: function () {}, removeItem: function () {} },
    sessionStorage: { getItem: function () { return null; }, setItem: function () {}, removeItem: function () {} },
    CustomEvent: function (t, o) { this.type = t; this.detail = o && o.detail; },
    Event: function (t) { this.type = t; },
    Image: function () { return makeEl('img'); },
    Blob: function () { return { size: 0 }; },
    URL: { createObjectURL: function () { return 'blob:x'; }, revokeObjectURL: function () {} },
    MediaRecorder: function () { return makeEl('rec'); },
    matchMedia: function () { return { matches: false, addEventListener: function () {}, addListener: function () {} }; },
    getComputedStyle: function () { return {}; }
  };
  sandbox.MediaRecorder.isTypeSupported = function () { return true; };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.window.addEventListener = function () {};

  try { vm.runInNewContext(source, sandbox, { filename: 'app.guard.js' }); }
  catch (e) { /* 末尾の描画系initが落ちても __go5RequestMake は既に代入済み(make定義直後) */ }

  if (typeof sandbox.window.__go5RequestMake !== 'function') throw new Error('__go5RequestMake が未定義=app.jsが早すぎる段で落ちた');
  if (scn.draft) sandbox.window.__go5DraftPending = true;
  try { sandbox.window.__go5RequestMake(); } catch (e) {} // G1 は最初の await より前=同期部分で反応が確定する
  return { makeBtn: els['makeBtn'], draftMakeBtn: els['draftMakeBtn'], status: els['status'] };
}

// T-1 今すぐ作成・写真未選択 → makeBtn が反応する。
try {
  var r1 = run({ draft: false });
  assert.ok(r1.makeBtn, 'makeBtn 要素が生成されている');
  assert.strictEqual(r1.makeBtn.textContent, '⚠ 写真が必要', '押したボタン(makeBtn)が反応ラベルへ変わる(実際: ' + JSON.stringify(r1.makeBtn.textContent) + ')');
  ok('T-1 今すぐ作成: makeBtn が無反応で終わらない');
} catch (e) { ng('T-1 今すぐ作成', e); }

// T-2 ドラフトで作成・写真未選択 → draftMakeBtn が反応する。
try {
  var r2 = run({ draft: true });
  assert.ok(r2.draftMakeBtn, 'draftMakeBtn 要素が生成されている');
  assert.strictEqual(r2.draftMakeBtn.textContent, '⚠ 写真が必要', '押したボタン(draftMakeBtn)が反応ラベルへ変わる(実際: ' + JSON.stringify(r2.draftMakeBtn.textContent) + ')');
  ok('T-2 ドラフトで作成: draftMakeBtn が無反応で終わらない');
} catch (e) { ng('T-2 ドラフトで作成', e); }

// T-3 対照: ガード自体は生きている(status にも理由が出る)。
try {
  var r3 = run({ draft: false });
  assert.ok(/写真/.test(r3.status.textContent || ''), 'status に写真未選択の理由が出る(実際: ' + JSON.stringify(r3.status && r3.status.textContent) + ')');
  ok('T-3 対照: status にも理由が出る(ガードは生きている)');
} catch (e) { ng('T-3 status 対照', e); }

if (fails) { console.log('FAIL: ' + fails + ' 件'); process.exit(1); }
console.log('OK: test_make_guard_feedback.js 全緑');
