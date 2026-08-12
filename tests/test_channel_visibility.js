/**
 * tests/test_channel_visibility.js
 * 他チャンネル除外(filterOtherChannelFor_ / otherKeys_ / existsInStore_)の「相手ストア実在判定」が、
 * manualOnly=true の手動短縮URL台帳行を"実在の証拠"にしない、を固定する回帰テスト。
 *
 * ★背景(なぜ要るか)：Chami報告2026-08-12②「復元→投稿完了しても投稿履歴に載らない」の再発。
 *   v=738 は addCompletedPost_ の重複判定の母集団から manualOnly を抜いたが、表示の他ch除外フィルタ側
 *   (otherKeys_/existsInStore_)は short_hist を manualOnly込みで読んでいた。すると:
 *     ・その行は自分のタブでは「相手chストアに実在」とされ隠される
 *     ・相手タブにも manualOnly は一覧表示されない(!manualOnly で除外)
 *   =どのタブにも出ないのに"存在"扱い=不可視dupe。復元→完了が addCompletedPost_ でこの隠れ行に一致し
 *   dupeで新規行を作らず「載らない」。台帳行(manualOnly)は"実在の証拠"にしてはいけない(v=738と同型)。
 * ※ yt-clicks.js:280-298(otherKeys_/existsInStore_ の manualOnlyフィルタ)と「同一仕様」。
 *   どちらかを変えたら両方を揃えること。
 *
 * 実行: node tests/test_channel_visibility.js
 */
'use strict';
const assert = require('assert');

// --- otherKeys_/existsInStore_ の "相手ストア実在判定" ミラー(yt-clicks.js:280-298) ---
//   相手chストア = short_hist(★manualOnlyは除外) + verify_manual。videoId/shortUrl/postUri/ytId一致で実在。
function ytId_(u) { // idgen.youtubeId と同一仕様の11文字ID抽出
  u = String(u || '').trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(u)) return u;
  var m = u.match(/(?:youtu\.be\/|[?&]v=|\/shorts\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])/);
  return m ? m[1] : '';
}
function otherKeys(shortHist, verifyManual) {
  var set = { vid: {}, su: {}, pu: {}, yid: {} };
  (shortHist || []).filter(function (x) { return x && !x.manualOnly; }) // ★台帳行は実在の証拠にしない
    .concat(verifyManual || []).forEach(function (x) {
      if (!x) return;
      if (x.videoId) set.vid[String(x.videoId)] = 1;
      if (x.shortUrl) set.su[String(x.shortUrl)] = 1;
      if (x.postUri) set.pu[String(x.postUri)] = 1;
      var y = ytId_(x.ytUrl || ''); if (y) set.yid[y] = 1;
    });
  return set;
}
function existsInStore(it, set) {
  if (it.videoId && set.vid[String(it.videoId)]) return true;
  if (it.shortUrl && set.su[String(it.shortUrl)]) return true;
  if (it.postUri && set.pu[String(it.postUri)]) return true;
  var y = ytId_(it.ytUrl || ''); if (y && set.yid[y]) return true;
  return false;
}

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

// ★症状②の核：相手ストアに manualOnly 台帳行しか無い時、それを"実在"にしない=隠さない/dupe扱いしない
test('V-0: 相手ストアの一致行が manualOnly 台帳行だけなら「実在」と見なさない', function () {
  var other = otherKeys([{ shortUrl: 'https://yoz2.com/aa', manualOnly: true }], []);
  var it = { shortUrl: 'https://yoz2.com/aa', videoId: 'acc1-X' };
  assert.strictEqual(existsInStore(it, other), false, 'manualOnly台帳行を実在の証拠にしてはいけない(不可視dupeの根)');
});

test('V-1: 相手ストアに一覧表示される実行(非manualOnly)が居れば従来どおり実在=true', function () {
  var other = otherKeys([{ shortUrl: 'https://yoz2.com/aa' }], []);
  assert.strictEqual(existsInStore({ shortUrl: 'https://yoz2.com/aa' }, other), true);
});

test('V-2: verify_manual 側の一致は manualOnly の有無に関係なく実在(こちらは一覧に出る)', function () {
  var other = otherKeys([], [{ videoId: 'acc2-1' }]);
  assert.strictEqual(existsInStore({ videoId: 'acc2-1' }, other), true);
});

test('V-3: videoId一致でも証拠が short_hist の manualOnly 行だけなら実在にしない', function () {
  var other = otherKeys([{ videoId: 'acc2-9', manualOnly: true }], []);
  assert.strictEqual(existsInStore({ videoId: 'acc2-9' }, other), false);
});

test('V-4: YouTube動画IDはURL形式が違っても一致判定する(非manualOnly実行がある時)', function () {
  var other = otherKeys([{ ytUrl: 'https://youtu.be/AAAAAAAAAAA' }], []);
  assert.strictEqual(existsInStore({ ytUrl: 'https://www.youtube.com/shorts/AAAAAAAAAAA' }, other), true);
});

test('V-5: 相手ストアが空なら常に実在しない(fail-open=自分のタブに出す)', function () {
  var other = otherKeys([], []);
  assert.strictEqual(existsInStore({ videoId: 'acc1-1', shortUrl: 'https://5mgl.com/x' }, other), false);
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
