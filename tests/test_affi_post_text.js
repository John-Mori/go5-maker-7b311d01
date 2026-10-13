// tests/test_affi_post_text.js — 作品紹介の定型文(即アフィのコピペ欄・Blueskyドラフトの子投稿)を本物の口で検証する。
//   Chami msg 1559480072589803612: 1行目「⇩気になった方はコチラから💕 #PR #漫画」/2行目=新作は「新作N%OFF✨️」(割引なし「新作✨️」)、
//   準新作は「準新作N%OFF✨️」「準新作✨️」(msg 1559676496841539657「準新作だけど新作表示された」)、
//   旧作は「N%OFFの話題作✨️」(割引なし「話題作✨️」)/空行/短縮リンク。
//     実行: node tests/test_affi_post_text.js
'use strict';
var fs = require('fs');
var path = require('path');
var Core = require('../core/movie-attrs-core.js');

var fails = 0;
function check(name, cond) { if (cond) { console.log('  ok  ' + name); } else { console.log('  NG  ' + name); fails++; } }

var NOW = Date.parse('2026-10-13T00:00:00');
function line(info) { return Core.affiPostText(info, 'https://xdgh3.com/abc', NOW).split('\n')[1]; }

check('新作+割引 → 新作N%OFF✨️', line({ releaseDate: '2026-10-01 10:00:00', discountPct: 30, price: 700, listPrice: 1000 }) === '新作30%OFF✨️');
check('新作・割引なし → 新作✨️', line({ releaseDate: '2026-10-01 10:00:00', discountPct: 0, price: 1000, listPrice: 1000 }) === '新作✨️');
check('準新作+割引 → 準新作N%OFF✨️(新作と出さない)', line({ releaseDate: '2026-08-20', discountPct: 50 }) === '準新作50%OFF✨️');
check('準新作・割引なし → 準新作✨️', line({ releaseDate: '2026-08-20' }) === '準新作✨️');
check('新作の境目(30日)を過ぎた31日目は準新作', line({ releaseDate: '2026-09-12' }) === '準新作✨️');
check('旧作・割引なし → 話題作✨️', line({ releaseDate: '2025-01-01' }) === '話題作✨️');
check('旧作+割引 → N%OFFの話題作✨️', line({ releaseDate: '2025-01-01', discountPct: 20, price: 800, listPrice: 1000 }) === '20%OFFの話題作✨️');
check('ドラフトのスナップ形(pct) も読む', line({ releaseDate: '2025-01-01', pct: 15 }) === '15%OFFの話題作✨️');
check('割引率があっても売価=定価なら割引扱いしない', line({ releaseDate: '2025-01-01', discountPct: 20, price: 1000, listPrice: 1000 }) === '話題作✨️');
check('作品情報なし → 話題作✨️', line(null) === '話題作✨️');
check('全文の形(1行目/2行目/空行/リンク)',
  Core.affiPostText({ releaseDate: '2026-10-01' }, 'https://xdgh3.com/abc', NOW) === '⇩気になった方はコチラから💕 #PR #漫画\n新作✨️\n\nhttps://xdgh3.com/abc');
check('リンク空なら2行だけ(Blueskyの返信側でリンクを足す)', Core.affiPostText({}, '', NOW) === '⇩気になった方はコチラから💕 #PR #漫画\n話題作✨️');

// ドラフトの子の文欄(msg 1559679396363636736「ドラフトの子の文にも反映して」=見出しの次に2行目が無かった)。
var CHILD = '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/Yi2gI';
check('子の文: 見出しの次へ準新作行を差し込む', Core.withAffiStatusLine(CHILD, { releaseDate: '2026-08-20', pct: 30 }, NOW) === '⇩気になった方はコチラから💕 #PR #漫画\n準新作30%OFF✨️\n\nhttps://xdgh3.com/Yi2gI');
var once = Core.withAffiStatusLine(CHILD, { releaseDate: '2026-10-01' }, NOW);
check('子の文: 既にある2行目は今の情報で置き換える(二重にしない)', Core.withAffiStatusLine(once, { releaseDate: '2025-01-01', pct: 20 }, NOW) === '⇩気になった方はコチラから💕 #PR #漫画\n20%OFFの話題作✨️\n\nhttps://xdgh3.com/Yi2gI');
check('子の文: 見出しが無い文は触らない(null)', Core.withAffiStatusLine('続きはこちら\nhttps://x', {}, NOW) === null);
check('子の文: Blueskyの返信文になってもリンクだけ差し替わり2行目は残る',
  (function () { var t = Core.withAffiStatusLine(CHILD, { releaseDate: '2026-08-20' }, NOW); return t.replace(/https?:\/\/\S+/g, 'https://bsky-link') === '⇩気になった方はコチラから💕 #PR #漫画\n準新作✨️\n\nhttps://bsky-link'; })());

// 配線: Blueskyドラフトの子投稿と即アフィが同じ口を通す。
var stock = fs.readFileSync(path.join(__dirname, '..', 'js', 'stock.js'), 'utf8');
var qa = fs.readFileSync(path.join(__dirname, '..', 'js', 'quick-affi.js'), 'utf8');
check('stock.js の子投稿が withAffiStatusLine を通す', /core\.withAffiStatusLine\(xv, info\)/.test(stock));
check('stock.js の子の文欄(openPostModal_)が withAffiStatusLine を通す', /acore\.withAffiStatusLine\(composedXText, meta\.priceInfo/.test(stock));
check('quick-affi.js が affiPostText を通す', /core\.affiPostText\(info, link\)/.test(qa));

if (fails) { console.log('\n' + fails + ' 件 NG'); process.exit(1); }
console.log('\nall ok');
