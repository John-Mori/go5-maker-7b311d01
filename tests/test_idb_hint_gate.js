/**
 * tests/test_idb_hint_gate.js
 * Node で実行できる自己完結テスト(追加パッケージ不使用)
 * 実行: node tests/test_idb_hint_gate.js
 *
 * 対象＝js/candidates.js の shouldShowIdbHint_(failures, sinceMs, nowMs)(純関数)。
 *   「画像の読み込みに失敗しています…閉じて開き直せ」という下部案内バーを出してよいかの唯一の判定。
 * 経緯＝2026-08-18 Chami報告「案内がめちゃくちゃ出る」。旧実装は5回連続失敗(≒15秒)で即表示していたため、
 *   iOSのタブ退避や一時的メモリ圧など数秒〜十数秒で回復する接続死でも強い案内が頻発した。
 *   go5-idb-recovered による自動読み直し(閉じ直し不要)が入った今、案内は「回復せず60秒以上続く=本当の
 *   プロセス死」の時だけ出す。ここはその境界を固定する=空PASS禁止(境界を緩めるとM-2/M-3で落ちる)。
 */

'use strict';

const assert = require('assert');
const { shouldShowIdbHint_ } = require('../js/candidates.js');

let passed = 0;
let failed = 0;
function test(name, fn) {
  try { fn(); console.log('PASS: ' + name); passed++; }
  catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; }
}

const MIN = 60000; // HINT_MIN_STREAK_MS

test('G-1: 連鎖が無い(sinceMs=0)なら、失敗回数がいくつでも出さない', function () {
  assert.strictEqual(shouldShowIdbHint_(99, 0, 1000000), false);
});

test('G-2: 5回超えても60秒未満なら出さない(短い接続死=誤発火を止める・今回の本丸)', function () {
  var since = 1000000;
  assert.strictEqual(shouldShowIdbHint_(5, since, since + 15000), false, '15秒では出さない');
  assert.strictEqual(shouldShowIdbHint_(8, since, since + 59999), false, '60秒直前でも出さない');
});

test('G-3: 5回超え かつ 60秒以上続いたら出す(本当のプロセス死は案内する)', function () {
  var since = 1000000;
  assert.strictEqual(shouldShowIdbHint_(5, since, since + MIN), true, 'ちょうど60秒で出す');
  assert.strictEqual(shouldShowIdbHint_(9, since, since + 120000), true);
});

test('G-4: 60秒経っていても失敗回数が4以下なら出さない(単発ブリップ除外)', function () {
  var since = 1000000;
  assert.strictEqual(shouldShowIdbHint_(4, since, since + MIN + 5000), false);
  assert.strictEqual(shouldShowIdbHint_(1, since, since + MIN + 5000), false);
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
