/**
 * tests/test_completed_post.js
 * 「投稿完了 → 投稿履歴に必ず1件載る(重複はしない)」の判定を固定する回帰テスト。
 *
 * ★背景(なぜ要るか)：yt-clicks.js の addCompletedPost_ は 2026-08-08〜09 の一晩で
 *   v=679→681→682→683 と4連続で同じ症状「投稿完了を押したのに投稿履歴に載らない」を直した。
 *   毎回、別の“黙って捨てるガード”が真因だった(URL両空でreturn / videoId発番がガードの後 / blob依存)。
 *   直したが機械の歯止めが無い=次の改修で黙って再発しうる。ここで「載せる/捨てる/重複」の3判定を
 *   純関数のミラーとして固定し、CI(smoke.yml が tests/test_*.js を全push実行)で毎回撃つ。
 * ※ yt-clicks.js:addCompletedPost_ と「同一仕様」。どちらかを変えたら両方を揃えること。
 *   2026-08-12: 戻り値を bare boolean → 理由付きオブジェクト({ok}/{ok:false,reason:'dupe'|'no-id',matchedBy,existing})へ。
 *   併せて dupe時は既存行の"空欄だけ"を非破壊バックフィル(記録の統合＝削除でない)。下に backfillRow ミラーを追加。
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

// --- 重複判定のミラー(yt-clicks.js:addCompletedPost_ の pools ループ) ---
//   同じ YouTube動画ID / 同じ背骨ID(videoId) の完了は履歴を二重にしない。
//   ★shortUrl は「投稿ごとに一意」ではない=セール会場短縮URL(5mgl.com/8dpUu 等)は同一セール中の別作品の
//   投稿が全て共有する。強キー(videoId / YouTube動画ID)がどちらかにある時に shortUrl だけで畳むと、別作品が
//   同じセール会場リンクを持つだけで dupe 扱いされ「投稿完了しても載らない＋別題名へ固定」になる
//   (Chami再発2026-08-12・実は女の子も焦ってる→先生、最低ですに固定)。両側に強キーが無い旧行同士に限定する。
function ytIdOf(u) { const m = String(u || '').match(/[?&]v=([^&]+)|shorts\/([^/?]+)/); return m ? (m[1] || m[2]) : ''; }
function isDupe(existingList, incoming) {
  const vid = incoming.ytUrl ? ytIdOf(incoming.ytUrl) : '';
  return existingList.some(function (it) {
    if (vid && ytIdOf(it.ytUrl || '') === vid) return true;
    if (incoming.videoId && it.videoId === incoming.videoId) return true;
    if (incoming.shortUrl && it.shortUrl === incoming.shortUrl
        && !vid && !incoming.videoId && !it.videoId && !ytIdOf(it.ytUrl || '')) return true;
    return false;
  });
}

// --- 重複判定の母集団のミラー(yt-clicks.js: manualOnly=手動短縮URL履歴は重複母集団から除外) ---
//   manualOnly の行は投稿履歴の一覧に出ない(allItems/displayItems_ が !manualOnly で除外)。それを重複と
//   見なすと「作成履歴に在るのに投稿履歴に永久に出ない」不可視dupeになる(Chami報告2026-08-11②
//   実は女の子も焦ってる)。一覧に出る行だけを重複判定の母集団にする。
function visibleForDupe(existingList) {
  return (existingList || []).filter(function (it) { return it && !it.manualOnly; });
}

// --- dupe時の非破壊バックフィルのミラー(yt-clicks.js: matched行の"空欄だけ"を今回値で埋める) ---
//   videoId無し既存行(手動追加/リビルド前)にYouTube/短縮URL一致で当たったら、空の videoId/ytUrl/shortUrl を
//   今回値で埋める=次回から videoId で照合が揃い「行は在るのに載らなかった」誤報が構造的に消える。
//   既に値のある欄は上書きしない(統合＝削除でない・破壊しない)。
function backfillRow(matched, incoming) {
  const out = Object.assign({}, matched);
  if (!out.videoId && incoming.videoId) out.videoId = incoming.videoId;
  if (!out.ytUrl && incoming.ytUrl) out.ytUrl = incoming.ytUrl;
  if (!out.shortUrl && incoming.shortUrl) out.shortUrl = incoming.shortUrl;
  return out;
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
test('D-2: 同じ短縮URLの再完了は重複(両側に強キーが無い旧行同士に限る)', function () {
  const list = [{ shortUrl: 'https://5mgl.com/x1' }];
  assert.strictEqual(isDupe(list, { shortUrl: 'https://5mgl.com/x1' }), true);
});
test('D-7: 別作品が同じセール会場短縮URLを共有していても、各自に背骨IDがあれば重複でない=新規で載る(実は女の子も焦ってる→先生、最低ですに固定 の根治)', function () {
  const list = [{ videoId: 'acc1-20260809-0033-wk9z', ytUrl: 'https://youtube.com/shorts/OTHER111aaa', shortUrl: 'https://5mgl.com/8dpUu', title: '先生、最低です' }];
  const incoming = { videoId: 'acc1-20260812-2119-xyz0', ytUrl: 'https://youtube.com/shorts/GT8OLSB8mtE', shortUrl: 'https://5mgl.com/8dpUu', title: '実は女の子も焦ってる' };
  assert.strictEqual(isDupe(list, incoming), false);
});
test('D-8: 強キーが片方にでも在れば shortUrl 共有で畳まない(既存に videoId・今回はYouTube IDのみ)', function () {
  const list = [{ videoId: 'acc1-OLD', shortUrl: 'https://5mgl.com/8dpUu' }];
  const incoming = { ytUrl: 'https://youtube.com/shorts/GT8OLSB8mtE', shortUrl: 'https://5mgl.com/8dpUu' };
  assert.strictEqual(isDupe(list, incoming), false);
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
test('D-5: manualOnly(手動短縮URL履歴)は重複母集団に入れない=不可視dupeで投稿履歴に永久に出ない事故の根治(実は女の子も焦ってる)', function () {
  const list = [{ videoId: 'acc1-X', manualOnly: true }, { shortUrl: 'https://5mgl.com/w', manualOnly: true }];
  // manualOnly を除くと母集団が空=重複ではない=新規で投稿履歴へ載る
  assert.strictEqual(isDupe(visibleForDupe(list), { videoId: 'acc1-X', shortUrl: 'https://5mgl.com/w' }), false);
});
test('D-6: 一覧に出る行(非manualOnly)なら従来どおり重複を弾く=二重登録はしない', function () {
  const list = [{ videoId: 'acc1-X' }, { shortUrl: 'https://5mgl.com/w', manualOnly: true }];
  assert.strictEqual(isDupe(visibleForDupe(list), { videoId: 'acc1-X' }), true);
});

// ── dupe時の非破壊バックフィル ────────────────────────────
test('B-1: videoId無しの既存行(手動追加)へYouTube URL一致で当たったら videoId を埋める(誤報の根治)', function () {
  const matched = { ytUrl: 'https://youtube.com/shorts/abc123', title: '実は女の子も焦ってる' };
  const out = backfillRow(matched, { videoId: 'acc1-20260811-1708-3yqv', ytUrl: 'https://youtube.com/shorts/abc123', shortUrl: 'https://5mgl.com/8dpUu' });
  assert.strictEqual(out.videoId, 'acc1-20260811-1708-3yqv');
  assert.strictEqual(out.shortUrl, 'https://5mgl.com/8dpUu');
});
test('B-2: 既に値のある欄は上書きしない(統合＝削除でない・破壊しない)', function () {
  const matched = { videoId: 'acc1-OLD', shortUrl: 'https://5mgl.com/keep' };
  const out = backfillRow(matched, { videoId: 'acc1-NEW', shortUrl: 'https://5mgl.com/new' });
  assert.strictEqual(out.videoId, 'acc1-OLD');
  assert.strictEqual(out.shortUrl, 'https://5mgl.com/keep');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
