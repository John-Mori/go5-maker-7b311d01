/**
 * tests/test_bsky_desc_child_short.js
 * ドラフトの投稿ボタンでBlueskyへ出した後、YouTube説明欄の「(ブルスカ短縮リンク)」の行を
 * 子(返信)投稿の短縮リンクへ置き換える(Chami 2026-10-13 msg 1559267964866535467)。
 * stock.js の setDescUrlSlot_ の本物を、DOMだけ偽物にして実行する。
 * 実行: node tests/test_bsky_desc_child_short.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8').replace(/\r\n/g, '\n');
let fails = 0;
function eq(a, b, m) { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? '  ok   ' : '  FAIL ') + m + (ok ? '' : ' got=' + JSON.stringify(a) + ' want=' + JSON.stringify(b))); if (!ok) fails++; }

const st = read('js/stock.js');
const s1 = st.indexOf('  function bskyDescShortOf_(');
const e1 = st.indexOf('\n', st.indexOf('  function isBskyShortPhLine_(') + 10);
const helpers = st.slice(s1, st.indexOf('  }\n', e1) + 4);
const s2 = st.indexOf('  function setDescUrlSlot_(url) {');
const e2 = st.indexOf('  // 貼り付けたX投稿リンクを link-worker で短縮して');
const slotSrc = st.slice(s2, e2);

function mk(desc) {
  const els = { draftYtDescUrlLink: { style: {}, dataset: {}, removeAttribute() {} }, draftYtDescText: { value: desc } };
  const f = new Function('$', 'window', 'isOurShort_', 'fitDescRow_', 'requestAnimationFrame', helpers + slotSrc + '\nreturn { setDescUrlSlot_, bskyDescShortOf_ };');
  const M = f((id) => els[id], {}, () => true, () => {}, undefined);
  return { M, ta: els.draftYtDescText, lk: els.draftYtDescUrlLink };
}

console.log('--- 説明欄の(ブルスカ短縮リンク)を子の短縮リンクへ ---');
const tpl = '(ブルスカ短縮リンク)\n\n↑ URLを長押し&リンクを開く ↑\nこちらからアクセスしてね💕';
let t = mk(tpl);
t.M.setDescUrlSlot_('https://xdgh3.com/Child1');
eq(t.ta.value, 'https://xdgh3.com/Child1\n\n↑ URLを長押し&リンクを開く ↑\nこちらからアクセスしてね💕', '目印の行がそのまま子の短縮リンクになる(上に足さない)');
eq(t.lk.dataset.url, 'https://xdgh3.com/Child1', '説明欄の横の短縮リンク表示も子');
t.M.setDescUrlSlot_('https://xdgh3.com/Child1');
eq(t.ta.value.split('xdgh3.com/Child1').length - 1, 1, 'もう一度開いても二重に入らない');

t = mk('↑ 案内\n(ブルスカ短縮URL)\n【感想】');
t.M.setDescUrlSlot_('https://xdgh3.com/C2');
eq(t.ta.value, '↑ 案内\nhttps://xdgh3.com/C2\n【感想】', '途中の行・URL表記の目印も同じく置換');

t = mk('説明だけ');
t.M.setDescUrlSlot_('https://xdgh3.com/X');
eq(t.ta.value, 'https://xdgh3.com/X\n\n説明だけ', '目印が無い説明欄は従来どおり最上段');

eq(t.M.bskyDescShortOf_({ bskyParentShortUrl: 'P', bskyReplyShortUrl: 'C' }), 'C', '説明欄に入れるのは子の短縮');
eq(t.M.bskyDescShortOf_({ bskyParentShortUrl: 'P' }), 'P', '子の短縮が無い旧ドラフトは親');

console.log('--- 配線 ---');
const bs = read('js/bluesky.js');
eq(/makeShortAndShare\(out\.replyUrl, \{ account: acc \}\)/.test(bs), true, '投稿後に子のURLを短縮する');
eq(/setDescUrlSlot_\(r\.replyShortUrl \|\| r\.replyUrl/.test(st), true, '投稿ボタンの後は子の短縮を説明欄へ');
eq(/bskyReplyShortUrl: r\.replyShortUrl/.test(st) && /'bskyReplyShortUrl'\]/.test(st), true, '子の短縮をドラフトに保存し、保存し直しでも消さない');
eq(/Go5MakeShort\(reply\.postUrl, \{ account: job\.acc \}\)/.test(st), true, '後から出し直した子も短縮して説明欄へ');
eq(/isBskyShortPh_\(lt\)/.test(bs), true, '🧵一括投稿の説明欄でも(ブルスカ短縮リンク)を目印として扱う');
if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
console.log('all ok');
