// tests/test_rank_core.js — Go5RankCore.mergeByVid の field-level 統合を検証(Codex監査 §8 T1/T2/T11)。
// 実行: node tests/test_rank_core.js
var RC = require('../rank-core.js');
var fail = 0;
function ok(cond, msg) { if (!cond) { console.error('  ✗ ' + msg); fail++; } else { console.log('  ✓ ' + msg); } }

// T1: ローカル不完全(shortUrl='')・シート完全 → 1件・shortUrlはシート値
(function () {
  var rows = [
    { it: { title: 'local incomplete', shortUrl: '', ytUrl: 'https://youtu.be/ABC123' }, vid: 'ABC123', yt: 'https://youtu.be/ABC123', acct: 'acc1' },
    { it: { title: 'sheet complete', shortUrl: 'https://5mgl.com/AbC12', ytUrl: 'https://youtu.be/ABC123', _fromSheet: true }, vid: 'ABC123', yt: 'https://youtu.be/ABC123', acct: 'acc1' }
  ];
  var out = RC.mergeByVid(rows, []);
  ok(out.length === 1, 'T1: 同一vidが1件へ畳まれる');
  ok(out[0].it.shortUrl === 'https://5mgl.com/AbC12', 'T1: 空のローカルshortUrlをシート値で補完');
  ok(out[0].it.title === 'local incomplete', 'T1: 非空フィールド(題名)はローカル優先を維持');
})();

// T2: ローカルとシートに異なる有効URL → 両方を clickUrls に保持(片方を捨てない)
(function () {
  var rows = [
    { it: { shortUrl: 'https://5mgl.com/LOCAL', ytUrl: 'https://youtu.be/DEF' }, vid: 'DEF', yt: 'https://youtu.be/DEF', acct: 'acc1' },
    { it: { shortUrl: 'https://5mgl.com/SHEET', ytUrl: 'https://youtu.be/DEF', _fromSheet: true }, vid: 'DEF', yt: 'https://youtu.be/DEF', acct: 'acc1' }
  ];
  var out = RC.mergeByVid(rows, []);
  ok(out.length === 1, 'T2: 1件へ');
  ok(out[0].it.shortUrl === 'https://5mgl.com/LOCAL', 'T2: 主shortUrlはローカル優先');
  ok(out[0].it.clickUrls.indexOf('https://5mgl.com/LOCAL') >= 0 && out[0].it.clickUrls.indexOf('https://5mgl.com/SHEET') >= 0, 'T2: 異なる両URLをclickUrlsに保持');
})();

// 空文字で正本を消さない: ローカル非空 → シート空 でローカルが残る
(function () {
  var rows = [
    { it: { shortUrl: 'https://5mgl.com/KEEP', ytUrl: 'https://youtu.be/G' }, vid: 'G', yt: 'https://youtu.be/G', acct: 'acc1' },
    { it: { shortUrl: '', ytUrl: 'https://youtu.be/G', _fromSheet: true }, vid: 'G', yt: 'https://youtu.be/G', acct: 'acc1' }
  ];
  var out = RC.mergeByVid(rows, []);
  ok(out[0].it.shortUrl === 'https://5mgl.com/KEEP', '空文字のシート値で正本(shortUrl)を消さない');
})();

// mergeUrls は全行の和集合(重複なし)
(function () {
  var rows = [
    { it: { mergeUrls: ['https://5mgl.com/a', 'https://5mgl.com/b'], ytUrl: 'https://youtu.be/H' }, vid: 'H', yt: 'https://youtu.be/H', acct: 'acc1' },
    { it: { mergeUrls: ['https://5mgl.com/b', 'https://5mgl.com/c'], ytUrl: 'https://youtu.be/H' }, vid: 'H', yt: 'https://youtu.be/H', acct: 'acc1' }
  ];
  var out = RC.mergeByVid(rows, []);
  ok(out[0].it.mergeUrls.length === 3, 'mergeUrls和集合=重複なく3件');
})();

// カテゴリ属性: 未設定のみ真値で補完・明示falseは上書きしない
(function () {
  var rows = [
    { it: { catA: false, ytUrl: 'https://youtu.be/I' }, vid: 'I', yt: 'https://youtu.be/I', acct: 'acc1' },
    { it: { catA: true, catB: true, ytUrl: 'https://youtu.be/I', _fromSheet: true }, vid: 'I', yt: 'https://youtu.be/I', acct: 'acc1' }
  ];
  var out = RC.mergeByVid(rows, ['catA', 'catB']);
  ok(out[0].it.catA === false, '明示false(catA)はシートのtrueで上書きしない');
  ok(out[0].it.catB === true, '未設定(catB)はシートのtrueで補完');
})();

// T11相当: 別vidは別件のまま・先勝ち順を保つ
(function () {
  var rows = [
    { it: { ytUrl: 'https://youtu.be/X1' }, vid: 'X1', yt: 'https://youtu.be/X1', acct: 'acc1' },
    { it: { ytUrl: 'https://youtu.be/X2' }, vid: 'X2', yt: 'https://youtu.be/X2', acct: 'acc2' },
    { it: { ytUrl: 'https://youtu.be/X1', _fromSheet: true }, vid: 'X1', yt: 'https://youtu.be/X1', acct: 'acc1' }
  ];
  var out = RC.mergeByVid(rows, []);
  ok(out.length === 2, 'T11: 2つの別vidは2件・重複vidは畳む');
  ok(out[0].vid === 'X1' && out[1].vid === 'X2', 'T11: 先勝ち順を保持');
})();

// vid無し行はスキップ(落とす)
(function () {
  var rows = [{ it: { ytUrl: '' }, vid: '', yt: '', acct: 'acc1' }];
  var out = RC.mergeByVid(rows, []);
  ok(out.length === 0, 'vid無し行はスキップ');
})();

if (fail) { console.error('\nFAILED: ' + fail); process.exit(1); }
console.log('\nrank-core: ALL PASS');
