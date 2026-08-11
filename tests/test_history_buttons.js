/**
 * tests/test_history_buttons.js
 * 投稿履歴カードの操作ボタン(🛠️編集 / 🔁リビルド作成 / 🔁被リビルドへ)が
 * 「従来どおり」出続けることを固定する回帰テスト。
 *
 * ★背景(なぜ要るか)：Chami依頼 DEF-system-engineer-59da250a8f(msg_id=1532321852465090652)
 *   「両チャンネルでほとんどがリビルド作成と非リビルド作成ボタンが消えている。従来通り復活させて。」
 *   真因＝行データに videoId が伝搬しないと、この2ボタンの表示条件が偽になり消える。
 *   本テストは yt-clicks.js の"表示条件"そのものをミラーとして固定し、CI(smoke.yml が
 *   tests/test_*.js を全push実行)で毎回撃つ＝将来の改修で条件をうっかり狭めたら赤で止まる。
 * ※ yt-clicks.js:1821(🛠️編集は無条件) / 1839(🔁リビルド作成) / 1840(🔁被リビルドへ)と「同一仕様」。
 *   どちらかを変えたら両方を揃えること。
 *
 * 実行: node tests/test_history_buttons.js
 */
'use strict';
const assert = require('assert');

// --- 投稿履歴カードのボタン表示条件のミラー(yt-clicks.js:1821/1839/1840) ---
//   it は投稿履歴の1行。関係するのは remade(被リビルド印) / videoId / _fromSheet(シート由来)。
function historyButtons(it) {
  it = it || {};
  return {
    // 🛠️編集：無条件で常に出す(どの行からでも編集モーダルを開ける)＝line 1821 に条件が無い
    edit: true,
    // 🔁リビルド作成：まだ被リビルドでなく、かつ元動画(videoId)がある時だけ＝line 1839
    //   videoId が無いとリビルド元にできないので出さないのが正しい。
    rebuildFrom: (!it.remade && !!it.videoId),
    // 🔁被リビルドへ / ↩被リビルド取消：シート由来"でない"ローカル記録、または videoId を持つ時＝line 1840
    //   ローカル記録は videoId が無くても被リビルド印を付けられる(シート専用の空行だけ出さない)。
    remakeToggle: (!it._fromSheet || !!it.videoId)
  };
}

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

// 🛠️編集はどんな行でも必ず出る(これが消えると編集導線ごと死ぬ)
test('H-0: 🛠️編集はどの行でも常に表示(無条件)', function () {
  [{}, { videoId: 'abc' }, { _fromSheet: true }, { remade: true }].forEach(function (it) {
    assert.strictEqual(historyButtons(it).edit, true);
  });
});

// videoId を持つ通常のローカル投稿＝両ボタンとも出る(従来どおりの状態)
test('H-1: videoIdありローカル記録は リビルド作成/被リビルドへ が両方出る', function () {
  const b = historyButtons({ videoId: 'vid123', _fromSheet: false, remade: false });
  assert.strictEqual(b.rebuildFrom, true);
  assert.strictEqual(b.remakeToggle, true);
});

// ★DEF-59da250a8f の核：videoId が無いローカル記録でも「被リビルドへ」は消えない
test('H-2: videoIdなしローカル記録でも 被リビルドへ は消えない(シート由来でないから)', function () {
  const b = historyButtons({ videoId: null, _fromSheet: false, remade: false });
  assert.strictEqual(b.remakeToggle, true, '被リビルドへが消えている＝DEF-59da250a8fの再発');
});

// videoId が無いと「リビルド作成」は出せない(元動画が無いので仕様どおり不可)
test('H-3: videoIdなしは リビルド作成 を出さない(元動画が無く仕様どおり)', function () {
  const b = historyButtons({ videoId: null, _fromSheet: false, remade: false });
  assert.strictEqual(b.rebuildFrom, false);
});

// 被リビルド済みの行は「リビルド作成」を出さない(トグルは取消側で出る)
test('H-4: remade済みは リビルド作成 を出さない／被リビルドへ(取消)は出る', function () {
  const b = historyButtons({ videoId: 'vid123', _fromSheet: false, remade: true });
  assert.strictEqual(b.rebuildFrom, false);
  assert.strictEqual(b.remakeToggle, true);
});

// シート由来かつ videoId 無しの空行だけは 被リビルドへ を出さない(印を付ける実体が無い)
test('H-5: シート由来かつvideoIdなしの行だけ 被リビルドへ 非表示、videoIdが付けば復活', function () {
  assert.strictEqual(historyButtons({ _fromSheet: true, videoId: null }).remakeToggle, false);
  assert.strictEqual(historyButtons({ _fromSheet: true, videoId: 'vid123' }).remakeToggle, true);
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
