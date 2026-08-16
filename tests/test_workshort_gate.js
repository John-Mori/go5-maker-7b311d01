/**
 * tests/test_workshort_gate.js — 投稿完了(ドラフト→投稿履歴)の「導線2 作品計測用短縮URLの発番着地を
 *   短時間だけ待ってから記録する」ゲートを固定する。
 *
 * 背景(REQ-65c7897f2f 再発2026-08-16「作品クリック計測用の短縮URLが空欄のまま」):
 *   発番(mintDraftWorkShort_)は非同期(link-worker往復)。投稿完了 handleCompleteOk_ は
 *   go5_draft_post_<id>.workShortUrl を同期で1回読むだけなので、発番着地前に完了を押すと欄が空で確定した。
 *   恒久対策= waitWorkShortSettle_ が着地を最大2.5秒だけ待つ。その判断を workshort-gate-core.js に切り出し。
 *
 * ★ソース文字列一致ではなく、本物の Go5WorkShortGate.step を require して実行で確かめる。
 *   T-5/T-6 は本番と同じ tick ループ(setTimeout をここでは仮想クロックで駆動)に本物の step を通し、
 *   「着地したら記録・取れなければ上限で記録」という分岐を実際に走らせる。外へ出る手(時計・localStorage)だけ偽物。
 */
'use strict';
var assert = require('assert');
var Gate = require('../js/workshort-gate-core.js');

var fails = 0;
function ok(name) { console.log('  PASS ' + name); }
function ng(name, e) { fails++; console.log('  FAIL ' + name + ' — ' + (e && e.message || e)); }

var META_WITH_AFF = { id: 'd1', affiliateUrl: 'https://al.fanza.co.jp/?lurl=x&af_id=y' };
var META_WITH_WORK = { id: 'd2', workUrl: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=abc/' };
var META_NO_URL = { id: 'd3' };

// --- 純粋判定 ---
try {
  assert.strictEqual(Gate.step({ workShortUrl: 'https://5mgl.com/abc' }, META_WITH_AFF, 0, 2500), 'record', '着地済みは即record');
  ok('T-1 workShortUrl 着地済み → record');
} catch (e) { ng('T-1', e); }

try {
  assert.strictEqual(Gate.step({}, META_WITH_AFF, 0, 2500), 'wait', '未着地+発番対象あり → wait');
  assert.strictEqual(Gate.step({ workShortUrl: '   ' }, META_WITH_WORK, 100, 2500), 'wait', '空白だけは未着地扱い=wait');
  ok('T-2 未着地+作品URL/アフィリンクあり → wait');
} catch (e) { ng('T-2', e); }

try {
  assert.strictEqual(Gate.step({}, META_NO_URL, 0, 2500), 'record', '発番対象が無ければ待たない');
  ok('T-3 発番対象なし → record(待っても永遠に来ない)');
} catch (e) { ng('T-3', e); }

try {
  assert.strictEqual(Gate.step({}, META_WITH_AFF, 2500, 2500), 'record', '上限到達は record');
  assert.strictEqual(Gate.step({}, META_WITH_AFF, 9999, 2500), 'record', '上限超過も record');
  ok('T-4 上限到達/超過 → record(完了をブロックしない・フォールスルー)');
} catch (e) { ng('T-4', e); }

// --- 本物の tick ループ(仮想クロック)で分岐を実行 ---
//   本番 stock.js の waitWorkShortSettle_ と同じ構造：step()==='record' になるまで 200ms 間隔で再評価。
//   ここでは setTimeout / Date.now / localStorage を仮想化し、本物の Gate.step を通す。
function driveWait(opts) {
  var now = 0;
  var timers = []; // { at, fn }
  function setT(fn, ms) { timers.push({ at: now + ms, fn: fn }); }
  var store = opts.store; // { workShortUrl?: string } を landAt で書き換える
  var doneAt = null, doneVal = null;
  var t0 = now;
  (function tick_() {
    // 本番と同じ：現在の保存データで本物の step を評価
    if (Gate.step(store, opts.meta, now - t0, opts.maxMs) === 'record') {
      doneAt = now; doneVal = String(store.workShortUrl || '');
      return;
    }
    setT(tick_, 200);
  })();
  // 仮想クロックを進める：予定タイマーと「着地イベント(landAt)」を時系列で処理
  var guard = 0;
  while (doneAt === null && guard++ < 1000) {
    var next = timers.shift();
    if (!next) break;
    now = next.at;
    if (opts.landAt != null && now >= opts.landAt && !store.workShortUrl) {
      store.workShortUrl = opts.landValue; // link-worker から着地したことにする
    }
    next.fn();
  }
  return { doneAt: doneAt, doneVal: doneVal };
}

try {
  // 発番が 600ms で着地 → 着地後・上限前に、値付きで記録される
  var r5 = driveWait({ store: {}, meta: META_WITH_AFF, maxMs: 2500, landAt: 600, landValue: 'https://5mgl.com/xyz' });
  assert.ok(r5.doneAt !== null, '記録された');
  assert.ok(r5.doneAt >= 600, '着地(600ms)より前に記録していない(実際: ' + r5.doneAt + 'ms)');
  assert.ok(r5.doneAt < 2500, '上限より前に記録した(実際: ' + r5.doneAt + 'ms)');
  assert.strictEqual(r5.doneVal, 'https://5mgl.com/xyz', '記録時に短縮URLが入っている');
  ok('T-5 発番が間に合う: 着地を待って値付きで記録');
} catch (e) { ng('T-5 着地待ち', e); }

try {
  // 発番が最後まで来ない → 上限(2500ms)で空のまま記録(完了はブロックされない=従来挙動へフォールスルー)
  var r6 = driveWait({ store: {}, meta: META_WITH_AFF, maxMs: 2500, landAt: null });
  assert.ok(r6.doneAt !== null, '上限で必ず記録される(完了が永久に止まらない)');
  assert.ok(r6.doneAt >= 2500, '上限まで待ってから記録(実際: ' + r6.doneAt + 'ms)');
  assert.strictEqual(r6.doneVal, '', '取れなければ空のまま(従来どおり)＝自己修復(yt-clicks)へ委ねる');
  ok('T-6 発番が来ない: 上限でフォールスルー(完了はブロックしない)');
} catch (e) { ng('T-6 上限フォールスルー', e); }

if (fails) { console.log('FAIL: ' + fails + ' 件'); process.exit(1); }
console.log('OK: test_workshort_gate.js 全緑');
