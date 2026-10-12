/**
 * tests/test_desc_click_measure.js
 * 概要欄(導線1)とBluesky子の作品クリックが投稿履歴で数えられること
 * (Chami 2026-10-13 msg 1559338789447409784「概要欄クリックが計測ないよ」)。
 * js/yt-clicks.js の本物の codeOf / treeLinksFor_ / rowTreesOf_ を抜き出して実行する。
 * 実行: node tests/test_desc_click_measure.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'js/yt-clicks.js'), 'utf8').replace(/\r\n/g, '\n');
const st = fs.readFileSync(path.join(__dirname, '..', 'js/stock.js'), 'utf8').replace(/\r\n/g, '\n');
function grab(name) {
  const i = src.indexOf('  function ' + name + '(');
  if (i < 0) throw new Error('not found: ' + name);
  const j = src.indexOf('\n  }', i);
  return src.slice(i, j + 4);
}
let store = {};
const window = { Go5Short: { ourBase: (u) => { const m = /^(?:https?:\/\/)?(xdgh3\.com|5mgl\.com)\//.exec(String(u || '')); return m ? 'https://' + m[1] : ''; } } };
const make = new Function('window', 'treeStoreLoad_', 'treeIdentity_', 'normalizeTreeLinks_',
  grab('codeOf') + '\n' + grab('treeLinksFor_') + '\n' + grab('rowTreesOf_') + '\nreturn { codeOf: codeOf, rowTreesOf_: rowTreesOf_ };');
const f = make(window, () => store, () => 'acc3|v:x', (t) => (Array.isArray(t) ? t : []));

let fails = 0;
function eq(a, b, m) { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? '  ok   ' : '  FAIL ') + m + (ok ? '' : ' got=' + JSON.stringify(a) + ' want=' + JSON.stringify(b))); if (!ok) fails++; }

const it = { bskyWorkShortUrl: 'https://xdgh3.com/ozI9H', bskyReplyUrl: 'https://bsky.app/profile/a/post/b' };
eq(f.rowTreesOf_(it, 'acc3').map((t) => [t.name, f.codeOf(t.shortUrl)]), [['Bluesky子', 'ozI9H']], 'Bluesky子の作品リンクを自動で行に出す');
store = { 'acc3|v:x': { trees: [{ name: 'ツリー1', shortUrl: 'xdgh3.com/ozI9H' }] } };
eq(f.rowTreesOf_(it, 'acc3').length, 1, '同じコードを手入力ツリーで持っていれば二重に出さない');
store = {};
eq(f.rowTreesOf_({ bskyWorkShortUrl: 'https://al.fanza.co.jp/x' }, 'acc3').length, 0, '自前短縮でなければ出さない(計測できない)');
eq(f.rowTreesOf_({}, 'acc3').length, 0, 'Bluesky子が無い行は従来どおり');

console.log('--- 配線 ---');
eq(/histOptsOf_\(meta, meta\.youtubeUrl \|\| '', bskyDescShortOf_\(pd0\), pd0\)/.test(st), true, 'Bluesky投稿時の自動記録で説明欄の短縮を導線1として渡す');
eq(/setDescUrlSlot_\(su\); saveDraftPost_\(\); \}\n\s+if \(meta\) autoRecordBskyHistory_\(meta\);/.test(st), true, '子を出し直した後も短縮を行へ書き戻す');
eq(/matched\.clickUrls = _cu;/.test(src), true, '説明欄の短縮が差し替わったら clickUrls で合算');
eq(/function treeRowsHtml_\(it, account\) \{\n\s+var trees = rowTreesOf_\(it, account\);/.test(src), true, '行の表示はBluesky子込み');
eq(/rowTreesOf_\(it, chForItem_\(it\)\)\.forEach/.test(src), true, '集計対象もBluesky子込み');
eq(/fetchAllClicks_\(!!force \|\| fresh\.length > 0\)/.test(src), true, '未取得コードは1回だけ取り直す(「…」張り付き対策)');
if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
console.log('all ok');
