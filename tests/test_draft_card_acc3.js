/**
 * tests/test_draft_card_acc3.js
 * ドラフトカードの3点を固定する回帰テスト(Chami報告2026-10-11 msg1558832193441234974
 * 「ドラフトモードで準備中のまま。表示が月詠みになってる 全部直して。」)。
 *
 *  ① ch表示名：旧 `acc === 'acc2' ? '宵桜艶帖' : '月詠み'` の二択で acc3(癒やし倉庫)が「月詠み」と出た。
 *     → 正本 Go5Acct.labelOf へ寄せた。二択が js/ に戻ってきたら落とす。
 *  ② DLの「⬇ 準備中…」固着：手元IDB(番犬8秒×張り直しで最大30秒前後)→雲R2(最大45秒)の直列が DL番犬60秒を超えた。
 *     → raceWithFallback_ でIDBが答えない間にR2を並走させる。stock.js の実関数を抜き出して直接撃つ。
 *  ③ クリーム地で題が読めない：acc3 だけカードの色を上書きする CSS がある。
 *
 * 実行: node tests/test_draft_card_acc3.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

let passed = 0, failed = 0;
const pending = [];
function test(name, fn) {
  pending.push(Promise.resolve().then(fn).then(
    () => { console.log('PASS: ' + name); passed++; },
    (e) => { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; }
  ));
}

// ── ① ch表示名 ──
const Acct = require('../core/account.js');
test('L-1: labelOf は acc3 を「癒やし倉庫」と返す(月詠みを騙らない)', () => {
  assert.strictEqual(Acct.labelOf('acc3'), '癒やし倉庫');
  assert.strictEqual(Acct.labelOf('acc1'), '月詠み');
  assert.strictEqual(Acct.labelOf('acc2'), '宵桜艶帖');
});
test('L-2: 未知のIDは空文字(別chの名前を出さない)', () => {
  assert.strictEqual(Acct.labelOf('acc9'), '');
});
test('L-3: js/ に acc2/月詠み の二択ラベルが残っていない', () => {
  const bad = /=== *'acc2'\)? *\? *'宵桜艶帖' *: *'月詠み'/;
  const hits = fs.readdirSync(path.join(ROOT, 'js')).filter((f) => f.endsWith('.js'))
    .filter((f) => bad.test(read('js/' + f)));
  assert.deepStrictEqual(hits, []);
});
test('L-4: ドラフト/保存中/作成履歴カードは acctLabel_ を通す', () => {
  const src = read('js/stock.js');
  assert.strictEqual((src.match(/var acctLabel = acctLabel_\(meta\.account\);/g) || []).length, 3);
});

// ── ② IDB/R2 の並走 ──
function extractFn(src, name) {
  const start = src.indexOf('function ' + name + '(');
  assert.ok(start >= 0, name + ' が見つからない');
  let i = src.indexOf('{', start), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) break;
  }
  return src.slice(start, i + 1);
}
const raceWithFallback_ = new Function(extractFn(read('js/stock.js'), 'raceWithFallback_') + '; return raceWithFallback_;')();
const usable = (v) => !!v;
const never = () => new Promise(() => {});
const later = (ms, v) => () => new Promise((r) => setTimeout(() => r(v), ms));

test('R-1: IDBが無言で固まっても猶予後にR2の値が返る(準備中で止まらない)', async () => {
  const t0 = Date.now();
  const v = await raceWithFallback_(never, later(10, 'r2'), 30, usable);
  assert.strictEqual(v, 'r2');
  assert.ok(Date.now() - t0 < 500);
});
test('R-2: IDBが猶予内に返せばR2を呼ばない', async () => {
  let r2 = 0;
  const v = await raceWithFallback_(later(5, 'idb'), () => { r2++; return 'r2'; }, 50, usable);
  assert.strictEqual(v, 'idb');
  await new Promise((r) => setTimeout(r, 80));
  assert.strictEqual(r2, 0);
});
test('R-3: IDBが空(null)なら猶予を待たず即R2', async () => {
  const t0 = Date.now();
  const v = await raceWithFallback_(later(1, null), later(5, 'r2'), 10000, usable);
  assert.strictEqual(v, 'r2');
  assert.ok(Date.now() - t0 < 500);
});
test('R-4: IDBのrejectもR2へ倒す(fail-open)', async () => {
  const v = await raceWithFallback_(() => Promise.reject(new Error('idb-timeout')), later(5, 'r2'), 10000, usable);
  assert.strictEqual(v, 'r2');
});
test('R-5: 両方とも無ければ null で終わる(番犬待ちにならない)', async () => {
  const v = await raceWithFallback_(later(1, null), later(5, null), 10000, usable);
  assert.strictEqual(v, null);
});
test('R-6: 猶予0(IDBが病んでいる)は最初から並走、遅いIDBでも先に来たR2を採る', async () => {
  const v = await raceWithFallback_(later(200, 'idb'), later(5, 'r2'), 0, usable);
  assert.strictEqual(v, 'r2');
});
test('R-7: R2が先に null でも、後から来たIDBの値を採る', async () => {
  const v = await raceWithFallback_(later(40, 'idb'), later(1, null), 0, usable);
  assert.strictEqual(v, 'idb');
});
test('R-8: resolveVideoBlob_ とサムネはこの並走を通る', () => {
  const src = read('js/stock.js');
  assert.ok(/function resolveVideoBlob_[\s\S]{0,1500}raceWithFallback_\(/.test(src));
  assert.ok(/raceWithFallback_\(function \(\) \{ return thumbFromIdb_\(m\); \}/.test(src));
});

// ── ③ acc3 の色 ──
test('C-1: acc3 だけカードの題/副行/DLボタンを読める色へ上書きする', () => {
  const css = read('style.css');
  assert.ok(/html\[data-account="acc3"\] \.stk-row \.stk-title\{color:var\(--ink\) !important;\}/.test(css));
  assert.ok(/html\[data-account="acc3"\] \.stk-row \.stk-meta\{/.test(css));
  assert.ok(/html\[data-account="acc3"\] \.stk-row \.stk-dl,/.test(css));
  assert.ok(!/^\.stk-row \.stk-title/m.test(css), 'acc3以外のカード色は変えない');
});

Promise.all(pending).then(() => {
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
});
