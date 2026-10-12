/**
 * tests/test_bsky_child_text.js
 * Blueskyの子(返信)が、ドラフトの「子の文(返信)」を空行ごとそのまま使い、リンクだけBluesky用へ差し替えること
 * (Chami 2026-10-13 msg 1559290199324762212「子の投稿文が違う・一行空白も入れて」)。
 * js/bluesky.js の本物の bskyReplyTextOf_ / countGraphemes を抜き出して実行する。
 * 実行: node tests/test_bsky_child_text.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'js/bluesky.js'), 'utf8').replace(/\r\n/g, '\n');
function grab(name) {
  const i = src.indexOf('  function ' + name + '(');
  if (i < 0) throw new Error('not found: ' + name);
  const j = src.indexOf('\n  }\n', i);
  return src.slice(i, j + 4);
}
const make = new Function(
  "var BSKY_REPLY_TEXT = '続きはこちら';\n" + grab('countGraphemes') + '\n' + grab('bskyReplyTextOf_') + '\nreturn bskyReplyTextOf_;'
);
const f = make();

let fails = 0;
function eq(a, b, m) { const ok = a === b; console.log((ok ? '  ok   ' : '  FAIL ') + m + (ok ? '' : ' got=' + JSON.stringify(a) + ' want=' + JSON.stringify(b))); if (!ok) fails++; }

const BS = 'https://xdgh3.com/QNcxU';
const child = '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/P51lB';
eq(f(child, BS), '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/QNcxU', '子の文そのまま・空行も残し・リンクだけBluesky用');
eq(f(child.replace(/\n/g, '\r\n'), BS), '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/QNcxU', 'CRLFでも同じ');
eq(f('  ' + child + '\n\n', BS), '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/QNcxU', '前後の余白だけ落とす');
eq(f('⇩気になった方はコチラから💕 #PR #漫画', BS), '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/QNcxU', 'URLが無ければ空行を挟んで末尾へ');
eq(f('', BS), '続きはこちら\nhttps://xdgh3.com/QNcxU', '子の文が空なら従来文');
eq(f(undefined, BS), '続きはこちら\nhttps://xdgh3.com/QNcxU', '子の文が渡らなければ従来文');
eq(f('あ'.repeat(290) + '\n\nhttps://x.example/a', BS), '続きはこちら\nhttps://xdgh3.com/QNcxU', '300字超なら従来文(投稿失敗を避ける)');

console.log('--- 配線 ---');
eq(/out\.replyText = bskyReplyTextOf_\(o\.childText, link\);/.test(src), true, 'ドラフト一続きの返信文は子の文から作る');
const st = fs.readFileSync(path.join(__dirname, '..', 'js/stock.js'), 'utf8');
eq(/draftId: meta\.id, childText: String\(\(\$\('draftXText'\) \|\| \{\}\)\.value \|\| ''\)/.test(st), true, '投稿モードは子の文の欄を渡す');
if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
console.log('all ok');
