/**
 * tests/test_bsky_auto_history.js
 * Bluesky投稿時の投稿履歴自動記録(Chami 2026-10-13 msg 1559255858628534303)を固定する。
 *   ①ドラフトのBluesky親+返信が成功した時点で addCompletedPost(autoRecorded) が1件載せる。
 *   ②後の投稿完了(同じ背骨ID・YouTube URL付き)は新規行を作らず、同じ行へYouTube URL等を追記し、
 *     「重複で弾かれました」確認を出さない(autoRecorded+videoId一致のdupeは追記扱い)。
 *   ③手動🧵ツールは子(リプ)投稿を notifyPosted に通す=単独投稿と同じ histAdd 経路で載る。
 * addCompletedPost_ は yt-clicks.js の本物を切り出して実行する。
 * 実行: node tests/test_bsky_auto_history.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const HistMerge = require('../js/hist-merge-core.js');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8');
let fails = 0;
function eq(a, b, m) { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? '  ok   ' : '  FAIL ') + m + (ok ? '' : ' got=' + JSON.stringify(a) + ' want=' + JSON.stringify(b))); if (!ok) fails++; }

const yc = read('js/yt-clicks.js');
const s = yc.indexOf('  function addCompletedPost_(opts) {');
const e = yc.indexOf('  // localStorage を直読みして id を持つ entry');
const store = {}; const ymaps = {}; const pushed = [];
const make = new Function('window', 'acct', 'loadArrFor_', 'saveArrFor_', 'loadYtMapFor_', 'saveYtMapFor_', 'ytIdOf', 'itemYt_', 'pushItemToGas_', 'refresh', 'attrDefs_', 'lsHasEntry_', 'attemptPendingWorkShortMint_', 'pokeSnapshotNow_',
  yc.slice(s, e) + '\nreturn addCompletedPost_;');
const win = { HistMerge: HistMerge, IdGen: { makeVideoId: () => 'acc1-20261013-0230-zzzz' }, Go5Short: { ourBase: (u) => /^https?:\/\/(5mgl\.com|yoz2\.com)\//.test(u) } };
const add = make(win, () => 'acc1',
  (base, acc) => (store[base + acc] = store[base + acc] || []),
  (base, acc, arr) => { store[base + acc] = arr; return { idb: Promise.resolve(true) }; },
  (acc) => (ymaps[acc] = ymaps[acc] || {}), (acc, m) => { ymaps[acc] = m; },
  (u) => ((String(u).match(/(?:v=|shorts\/|youtu\.be\/)([\w-]{11})/) || [])[1] || ''),
  (ymap, x) => (x && (ymap[x.id] || x.ytUrl)) || '',
  (it) => pushed.push(JSON.parse(JSON.stringify(it))), () => {}, () => [], () => true, () => {}, () => {});

console.log('--- ①Bluesky投稿時の自動記録 ---');
const r1 = add({ account: 'acc1', videoId: 'acc1-20261013-0200-abcd', title: 'テスト作品', workUrl: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_1/', bskyParentUrl: 'https://bsky.app/profile/a/post/p1', bskyReplyUrl: 'https://bsky.app/profile/a/post/r1', bskyWorkShortUrl: 'https://5mgl.com/w1', pillar: 'bsky', autoRecorded: true });
eq(r1.ok, true, '自動記録は新規1件として載る');
eq(store.verify_manualacc1.length, 1, '投稿履歴(verify_manual)に1件');
eq(store.verify_manualacc1[0].autoRecorded, true, '自動記録の印が付く');
eq(store.verify_manualacc1[0].bskyReplyUrl, 'https://bsky.app/profile/a/post/r1', 'Bluesky返信URLが載る');
eq(pushed.length, 1, 'シートへ初回upsert');

console.log('--- ②後の投稿完了は同じ行へ追記(確認ダイアログ無し) ---');
const r2 = add({ account: 'acc1', videoId: 'acc1-20261013-0200-abcd', ytUrl: 'https://youtube.com/shorts/AAAAAAAAAAA', title: 'テスト作品', xPostUrl: 'https://x.com/a/status/1', pillar: 'both' });
eq([r2.reason, r2.matchedBy, r2.autoRecorded], ['dupe', 'videoId', true], '同じ背骨IDの自動記録行に当たる(autoRecorded=true)');
eq(store.verify_manualacc1.length, 1, '新規行は作らない(二重行なし)');
const row = store.verify_manualacc1[0];
eq(row.ytUrl, 'https://youtube.com/shorts/AAAAAAAAAAA', 'YouTube URLが追記される');
eq(row.xPostUrl, 'https://x.com/a/status/1', 'X投稿URLが追記される');
eq(row.pillar, 'bsky', '既に入っている柱は上書きしない(空欄だけ)');
eq('autoRecorded' in row, false, '投稿完了で通常の行に確定');
eq(ymaps.acc1[row.id], 'https://youtube.com/shorts/AAAAAAAAAAA', 'YouTube対応表(ymap)にも入る=再生数計測の対象');
eq(pushed.length, 2, '背骨ID一致の追記はシートへも送る');
eq(pushed[1].ytUrl, 'https://youtube.com/shorts/AAAAAAAAAAA', 'シートへ送る行にYouTube URL');
const r3 = add({ account: 'acc1', videoId: 'acc1-20261013-0200-abcd', ytUrl: 'https://youtube.com/shorts/AAAAAAAAAAA' });
eq([r3.reason, r3.autoRecorded], ['dupe', false], '確定後の二度押しは従来どおりdupe(確認ダイアログの対象)');

console.log('--- stock.js の配線 ---');
const st = read('js/stock.js');
eq(/var hr = autoRecordBskyHistory_\(meta, fresh\);/.test(st), true, 'Bluesky投稿成功後に自動記録を呼ぶ');
eq(/opts\.autoRecorded = true;/.test(st), true, '自動記録は autoRecorded を付けて渡す');
eq(/_res\.reason === 'dupe' && _res\.autoRecorded && _res\.matchedBy === 'videoId'\) \{/.test(st), true, '自動記録行への投稿完了は確認ダイアログを出さない');
eq(/var _hpOpts = histOptsOf_\(meta, ytUrl, shortUrl, pd\);/.test(st), true, '投稿完了と自動記録は同じ引数組み立てを使う');

console.log('--- 手動🧵ツール ---');
const bs = read('js/bluesky.js');
const tS = bs.indexOf('if (els.threadPostBtn) {');
const tB = bs.slice(tS, bs.indexOf('\n  }', tS));
eq(/notifyPosted\(res\.reply, parentText \+ '\\n' \+ replyUrl,/.test(tB), true, '子(リプ)投稿を notifyPosted に通す=投稿履歴へ記録');

if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
console.log('all ok');
