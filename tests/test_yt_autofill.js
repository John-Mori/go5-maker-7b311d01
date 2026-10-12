/**
 * tests/test_yt_autofill.js
 * 投稿履歴のYouTube URL自動取得(Chami 2026-10-13 msg 1559259242198737037)を固定する。
 *   ドラフトでYouTube URLを入れなくても、URL空欄行へそのchの新着(uploads)から題名＋時刻で自動結線する。
 *   曖昧(1行に複数候補・1動画に複数行)は埋めない。既に他行へ結線済みの動画は使わない。
 * yt-clicks.js の本物(ytNormTitle_〜autoFillYtUrls_)を切り出して実行する。
 * 実行: node tests/test_yt_autofill.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8');
let fails = 0;
function eq(a, b, m) { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? '  ok   ' : '  FAIL ') + m + (ok ? '' : ' got=' + JSON.stringify(a) + ' want=' + JSON.stringify(b))); if (!ok) fails++; }

const yc = read('js/yt-clicks.js');
const s = yc.indexOf('  function ytNormTitle_(s) {');
const e = yc.indexOf('  function refresh(announce, background) {');
const store = {}; const ymaps = {}; const pushed = []; const ls = {}; const fetched = [];
let uploadsJson = { items: [] };
const make = new Function('localStorage', 'fetch', 'apiKey', 'tsGet_', 'tsSet_', 'loadYtMapFor_', 'saveYtMapFor_', 'loadArrFor_', 'saveArrFor_', 'itemYt_', 'itemKey', 'ytIdOf', 'fetchChannelIds_', 'pushItemToGas_', 'titleCache',
  yc.slice(s, e) + '\nreturn { ytNormTitle_: ytNormTitle_, ytTitleHit_: ytTitleHit_, matchUploadsToRows_: matchUploadsToRows_, autoFillYtUrls_: autoFillYtUrls_ };');
const lsStub = { getItem: (k) => (k in ls ? ls[k] : null), setItem: (k, v) => { ls[k] = String(v); } };
const fetchStub = (u) => { fetched.push(u); return Promise.resolve({ json: () => Promise.resolve(uploadsJson) }); };
const ytIdOf = (u) => ((String(u || '').match(/(?:v=|shorts\/|youtu\.be\/)([\w-]{11})/) || [])[1] || '');
const M = make(lsStub, fetchStub, () => 'KEY', (k) => parseInt(ls[k] || '0', 10) || 0, (k, v) => { ls[k] = String(v); },
  (a) => (ymaps[a] = ymaps[a] || {}), (a, m) => { ymaps[a] = m; },
  (base, a) => (store[base + '__' + a] = store[base + '__' + a] || []), (base, a, arr) => { store[base + '__' + a] = arr; },
  (m, x) => (x && m[x.id]) || '', (x) => x.id, ytIdOf,
  (vids, cb) => { const o = {}; vids.forEach((v) => { o[v] = 'UCaaaaaaaaaaaaaaaaaaaaaa'; }); cb(o); },
  (it) => pushed.push(JSON.parse(JSON.stringify(it))), {});

console.log('--- 題名照合 ---');
eq(M.ytNormTitle_('ＴＥＳＴ　作品！ #shorts #漫画'), 'test作品', '全角/記号/ハッシュタグを除いて比べる');
eq(M.ytTitleHit_({ ytTitlePlan: '彼女が焦ってる理由 #shorts' }, '彼女が焦ってる理由 #漫画'), true, 'ドラフトのYouTube題名と一致');
eq(M.ytTitleHit_({ title: '実は女の子も焦ってる' }, '【漫画】実は女の子も焦ってる #shorts'), true, '④コメントがYouTube題名に含まれる');
eq(M.ytTitleHit_({ title: '焦ってる' }, '【漫画】実は女の子も焦ってる'), false, '短すぎる語(8字未満)の包含では結ばない');

console.log('--- 照合規則 ---');
const T = Date.parse('2026-10-13T00:00:00Z');
const rA = { id: 'm:1', title: '実は女の子も焦ってる話', ts: T };
const ups = [{ vid: 'AAAAAAAAAAA', title: '実は女の子も焦ってる話 #shorts', at: T + 3600e3 }, { vid: 'BBBBBBBBBBB', title: '別の作品のタイトルです', at: T }];
eq(M.matchUploadsToRows_([rA], ups, {}).map((p) => p.vid), ['AAAAAAAAAAA'], '題名一致の新着1本を結ぶ');
eq(M.matchUploadsToRows_([rA], ups, { AAAAAAAAAAA: 1 }).length, 0, '他行へ結線済みの動画は使わない');
eq(M.matchUploadsToRows_([{ id: 'm:2', title: rA.title, ts: T - 20 * 86400e3 }], ups, {}).length, 0, '時刻が10日以上離れた動画は結ばない');
eq(M.matchUploadsToRows_([rA], ups.concat([{ vid: 'CCCCCCCCCCC', title: '実は女の子も焦ってる話 後編', at: T }]), {}).length, 0, '1行に候補が複数=曖昧なので埋めない');
eq(M.matchUploadsToRows_([rA, { id: 'm:3', title: rA.title, ts: T }], ups, {}).length, 0, '1動画に行が複数=曖昧なので埋めない');

console.log('--- 自動取得の本体 ---');
store['verify_manual__acc1'] = [
  { manual: true, id: 'm:old', title: '前の作品', ts: T - 86400e3, ytUrl: 'https://youtube.com/shorts/OOOOOOOOOOO', videoId: 'acc1-1' },
  { manual: true, id: 'm:new', title: '実は女の子も焦ってる話', ts: T, videoId: 'acc1-2', autoRecorded: true },
];
ymaps.acc1 = { 'm:old': 'https://youtube.com/shorts/OOOOOOOOOOO' };
uploadsJson = { items: [
  { snippet: { title: '実は女の子も焦ってる話 #shorts', publishedAt: '2026-10-13T02:00:00Z' }, contentDetails: { videoId: 'AAAAAAAAAAA', videoPublishedAt: '2026-10-13T02:00:00Z' } },
  { snippet: { title: '前の作品', publishedAt: '2026-10-12T00:00:00Z' }, contentDetails: { videoId: 'OOOOOOOOOOO' } },
] };
M.autoFillYtUrls_('acc1', true).then((n) => {
  eq(n, 1, '空欄の1行だけ埋まる');
  const row = store['verify_manual__acc1'][1];
  eq(row.ytUrl, 'https://youtube.com/shorts/AAAAAAAAAAA', '行にYouTube URLが入る');
  eq(ymaps.acc1['m:new'], 'https://youtube.com/shorts/AAAAAAAAAAA', 'YouTube対応表にも入る=再生数計測の対象');
  eq([pushed.length, pushed[0] && pushed[0].ytUrl], [1, 'https://youtube.com/shorts/AAAAAAAAAAA'], 'シートへもupsert');
  eq(ls['yt_channel_id__acc1'], 'UCaaaaaaaaaaaaaaaaaaaaaa', 'chは既存行の動画から特定してキャッシュ');
  eq(/playlistId=UUaaaaaaaaaaaaaaaaaaaaaa&/.test(fetched[0]), true, 'そのchのuploadsプレイリストを読む');
  eq(Object.keys(row).some((k) => k.indexOf('__') === 0), false, '作業用の印を行へ残さない');
  return M.autoFillYtUrls_('acc1', false);
}).then((n2) => {
  eq([n2, fetched.length], [0, 1], '10分以内の自動再実行は通信しない');
  console.log('--- 配線 ---');
  eq(/return autoFillYtUrls_\(acct\(\), !!announce\)/.test(yc), true, '投稿履歴の更新で自動取得を走らせる');
  eq(/ytTitle: \(pd\.ytTitle \|\| ''\)\.trim\(\)/.test(read('js/stock.js')), true, 'ドラフトのYouTube題名を履歴へ渡す');
  eq(/entry\.ytTitlePlan = /.test(yc), true, '履歴行に照合用のYouTube題名を残す');
  if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
  console.log('all ok');
});
