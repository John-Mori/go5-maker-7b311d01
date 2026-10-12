/**
 * tests/test_bsky_reply_delay.js
 * 親→子リプライの間隔を3〜10秒に固定する(Chami 2026-10-13 msg 1559260340318109789「子のリプライもっと早くして3〜10秒でいい」)。
 * 実行: node tests/test_bsky_reply_delay.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8');
let fails = 0;
function t(m, ok) { console.log((ok ? '  ok   ' : '  FAIL ') + m); if (!ok) fails++; }
const core = read('js/bluesky-core.js');
t('既定の下限は3秒', /\? o\.delayMinMs : 3000;/.test(core));
t('既定の上限は10秒', /\? o\.delayMaxMs : 10000;/.test(core));
t('ドラフトの確認文は3〜10秒', /3〜10秒あけて返信に作品リンク/.test(read('js/stock.js')));
t('旧「数十秒」「1分以内」の案内が残っていない', !/数十秒あけて返信|秒数\(1分以内\)/.test(read('js/stock.js') + read('js/bluesky.js') + read('index.html')));
if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
console.log('all ok');
