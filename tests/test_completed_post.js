/**
 * tests/test_completed_post.js
 * 「投稿完了 → 投稿履歴に必ず1件載る(重複はしない)」の判定を固定する回帰テスト。
 *
 * ★背景(なぜ要るか)：yt-clicks.js の addCompletedPost_ は 2026-08-08〜09 の一晩で
 *   v=679→681→682→683 と4連続で同じ症状「投稿完了を押したのに投稿履歴に載らない」を直した。
 *   毎回、別の“黙って捨てるガード”が真因だった(URL両空でreturn / videoId発番がガードの後 / blob依存)。
 *   直したが機械の歯止めが無い=次の改修で黙って再発しうる。ここで「載せる/捨てる/重複」の3判定を
 *   純関数のミラーとして固定し、CI(smoke.yml が tests/test_*.js を全push実行)で毎回撃つ。
 * ※ yt-clicks.js:addCompletedPost_(2192〜2206)と「同一仕様」。どちらかを変えたら両方を揃えること。
 *
 * 実行: node tests/test_completed_post.js
 */
'use strict';
const assert = require('assert');

// --- addCompletedPost_ の“載せる/捨てる”判定のミラー(yt-clicks.js:2192-2194) ---
//   投稿完了は明示確定操作なので、YouTube URL も計測短縮URL もまだ無くても載せる。
//   背骨ID(videoId)は opts に無ければ IdGen で発番するので、IdGen が居れば実質いつも載る。
//   本当に載せないのは「識別子が1つも無い(URL両空 かつ videoId 発番もできない)」時だけ。
function shouldRecordCompleted(ytUrl, shortUrl, vidId, hasIdGen) {
  const y = (ytUrl || '').trim();
  const s = (shortUrl || '').trim();
  let v = (vidId || '').trim();
  if (!v && hasIdGen) v = 'acc1-20260101-0000-mint'; // IdGen 発番のスタブ(空でなくなる=載る)
  if (!y && !s && !v) return false; // 発番もできない時だけ従来どおり載せない
  return true;
}

// --- 重複判定のミラー(yt-clicks.js:2199-2205) ---
//   同じ YouTube動画ID / 同じ短縮URL / 同じ背骨ID(videoId) の完了は履歴を二重にしない。
function ytIdOf(u) { const m = String(u || '').match(/[?&]v=([^&]+)|shorts\/([^/?]+)/); return m ? (m[1] || m[2]) : ''; }
function isDupe(existingList, incoming) {
  const vid = incoming.ytUrl ? ytIdOf(incoming.ytUrl) : '';
  return existingList.some(function (it) {
    if (vid && ytIdOf(it.ytUrl || '') === vid) return true;
    if (incoming.shortUrl && it.shortUrl === incoming.shortUrl) return true;
    if (incoming.videoId && it.videoId === incoming.videoId) return true;
    return false;
  });
}

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

// ── 載せる/捨てる ──────────────────────────────────────────
test('C-1: URL両空でも videoId があれば載せる(v=682の根治=これが4連続再発の核)', function () {
  assert.strictEqual(shouldRecordCompleted('', '', 'acc2-20260808-2200-ab12', false), true);
});
test('C-2: URL両空でも IdGen が居れば発番して載せる(videoId未伝搬のドラフト)', function () {
  assert.strictEqual(shouldRecordCompleted('', '', '', true), true);
});
test('C-3: 識別子ゼロ(URL両空 かつ IdGen不在)の時だけ載せない=従来動作は維持', function () {
  assert.strictEqual(shouldRecordCompleted('', '', '', false), false);
});
test('C-4: YouTube URL があれば当然載せる', function () {
  assert.strictEqual(shouldRecordCompleted('https://youtube.com/shorts/abc123', '', '', false), true);
});
test('C-5: 短縮URLだけでも載せる(X先行で YouTube URL がまだ無い場面)', function () {
  assert.strictEqual(shouldRecordCompleted('', 'https://5mgl.com/x1', '', false), true);
});

// ── 重複はしない ───────────────────────────────────────────
test('D-1: 同じ背骨ID(videoId)の再完了は重複=二重に載せない(短縮リンク手動再入力で履歴2つ問題の核)', function () {
  const list = [{ videoId: 'acc1-20260808-2200-zz99' }];
  assert.strictEqual(isDupe(list, { videoId: 'acc1-20260808-2200-zz99' }), true);
});
test('D-2: 同じ短縮URLの再完了は重複', function () {
  const list = [{ shortUrl: 'https://5mgl.com/x1' }];
  assert.strictEqual(isDupe(list, { shortUrl: 'https://5mgl.com/x1' }), true);
});
// ※ URL形式違い(shorts/ vs ?v=)の同一ID判定は本体 yt-clicks.js:ytIdOf の守備範囲。
//   ここのミラーは簡易版なので同形式で重複を担保する(下)。
test('D-3: 同形式の同一YouTube IDは重複', function () {
  const list = [{ ytUrl: 'https://www.youtube.com/shorts/abc123' }];
  assert.strictEqual(isDupe(list, { ytUrl: 'https://www.youtube.com/shorts/abc123' }), true);
});
test('D-4: 別の背骨ID/別URLなら重複ではない=ちゃんと新規で載る', function () {
  const list = [{ videoId: 'acc1-A', shortUrl: 'https://5mgl.com/a' }];
  assert.strictEqual(isDupe(list, { videoId: 'acc1-B', shortUrl: 'https://5mgl.com/b' }), false);
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
