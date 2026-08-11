/**
 * tests/test_drive_save_settle.js
 * 「☁️ 保存中…」が永久に固着しない=Drive保存ボタンは必ず終端へ落ちる、を固定する回帰テスト。
 *
 * ★背景(なぜ要るか)：Chami報告2026-08-11①「いつまで経っても保存中」。真因は stock.js の
 *   Drive保存が、動画blobをR2から取り寄せる所(resolveVideoBlob_)で相手が無応答だと await が返らず、
 *   onDone が呼ばれずボタンが「☁️ 保存中…」+disabled のまま固まっていた(=fail-openの逆=沈黙)。
 *   v=738で ①resolveVideoBlob_ に45秒タイムアウト ②ボタンに90秒ウォッチドッグ を入れて機構で塞いだ。
 *   直したが機械の歯止めが無いと次の改修で黙って再発しうる。ここで stk-drive の"終端保証"の状態機械を
 *   純関数のミラーとして固定し、CI(smoke.yml が tests/test_*.js を全push実行)で毎回撃つ。
 * ※ stock.js:1489-1502(stk-drive クリックハンドラの _settled/_finish/_wd)と「同一仕様」。
 *   どちらかを変えたら両方を揃えること。
 *
 * 実行: node tests/test_drive_save_settle.js
 */
'use strict';
const assert = require('assert');

// --- stk-drive の"終端保証"状態機械のミラー(stock.js:1490-1502) ---
//   押した瞬間に「保存中…」+disabled にし、_finish が呼ばれるまで待つ。_finish は最初の1回だけ効き、
//   ①onDone(ok)(正常終了) ②ウォッチドッグ(90秒・中で何が詰まっても必ず戻す) のどちらから来ても
//   ボタンを enabled に戻す。二度目以降は _settled で無視=表示が二重に飛ばない。
function armDriveSave(btn) {
  const _orig = btn.textContent;
  btn.textContent = '☁️ 保存中…';
  btn.disabled = true;
  let _settled = false;
  function _finish(ok, errText) {
    if (_settled) return;      // ★二重確定を弾く=遅れて来た onDone で表示が飛ばない
    _settled = true;
    btn.disabled = false;      // ★どの経路でも必ず押せる状態へ戻す=固着の根治
    btn.textContent = ok ? '✅ 保存済み' : (errText || _orig);
  }
  return {
    onDone: function (ok) { _finish(ok); },                        // 実コードは clearTimeout(_wd) してから呼ぶ
    fireWatchdog: function () { _finish(false, '⏱ 中断(再度お試しください)'); },
    settled: function () { return _settled; }
  };
}

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

// 押した瞬間は「保存中…」+押せない、が起点(ここから必ず抜けられることを以下で保証する)
test('E-0: 押下直後は 保存中…/disabled(状態を見せる起点)', function () {
  const btn = { textContent: 'Drive保存', disabled: false };
  armDriveSave(btn);
  assert.strictEqual(btn.textContent, '☁️ 保存中…');
  assert.strictEqual(btn.disabled, true);
});

test('E-1: 正常終了(onDone true)で 保存済み・押せる状態へ戻る=固着しない', function () {
  const btn = { textContent: 'Drive保存', disabled: false };
  const c = armDriveSave(btn);
  c.onDone(true);
  assert.strictEqual(btn.disabled, false);
  assert.strictEqual(btn.textContent, '✅ 保存済み');
});

test('E-2: 失敗(onDone false)は元ラベルへ戻り再試行できる=押せる', function () {
  const btn = { textContent: 'Drive保存', disabled: false };
  const c = armDriveSave(btn);
  c.onDone(false);
  assert.strictEqual(btn.disabled, false);
  assert.strictEqual(btn.textContent, 'Drive保存');
});

// ★これが①の根治。onDone が永久に来ない(R2無応答等)でも、ウォッチドッグで必ず戻す。
test('E-3: onDone が来なくてもウォッチドッグで 保存中… を脱出=永久固着の根治', function () {
  const btn = { textContent: 'Drive保存', disabled: false };
  const c = armDriveSave(btn);
  c.fireWatchdog();                                   // onDone は一度も呼ばれない
  assert.strictEqual(btn.disabled, false);            // ★押せる状態に戻っている
  assert.notStrictEqual(btn.textContent, '☁️ 保存中…'); // ★保存中…のまま固まっていない
  assert.strictEqual(btn.textContent, '⏱ 中断(再度お試しください)');
});

test('E-4: ウォッチドッグ後に遅れて onDone が来ても表示は二重に飛ばない(_settled)', function () {
  const btn = { textContent: 'Drive保存', disabled: false };
  const c = armDriveSave(btn);
  c.fireWatchdog();
  c.onDone(true);                                     // 遅延到着=無視されるべき
  assert.strictEqual(btn.textContent, '⏱ 中断(再度お試しください)');
});

test('E-5: どの終端経路を通っても「保存中…かつdisabled」で残らない(固着の不在)', function () {
  ['onDoneTrue', 'onDoneFalse', 'watchdog'].forEach(function (path) {
    const btn = { textContent: 'Drive保存', disabled: false };
    const c = armDriveSave(btn);
    if (path === 'onDoneTrue') c.onDone(true);
    else if (path === 'onDoneFalse') c.onDone(false);
    else c.fireWatchdog();
    assert.ok(!(btn.textContent === '☁️ 保存中…' && btn.disabled === true),
      path + ' で 保存中…+disabled のまま固着している');
    assert.strictEqual(c.settled(), true);
  });
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
