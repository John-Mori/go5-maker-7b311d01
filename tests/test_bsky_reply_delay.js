/**
 * tests/test_bsky_reply_delay.js
 * 親→子リプライの間隔を3〜7秒(ミリ秒単位の乱数)にする(Chami 2026-11-10 msg 1569446443834408980「10秒は長いから3〜7秒に・3.35秒みたいなランダム性」。旧3〜10秒=2026-10-13)。
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
t('既定の上限は7秒', /\? o\.delayMaxMs : 7000;/.test(core));
t('乱数はミリ秒単位(秒へ丸めない)', /var delayMs = Math\.round\(delayMin \+ Math\.random\(\) \* Math\.max\(0, delayMax - delayMin\)\);/.test(core));
const bs = read('js/bluesky.js');
t('予約(無人)も3〜7秒・ミリ秒単位', /delay_ms: 3000 \+ Math\.floor\(Math\.random\(\) \* 4001\)/.test(bs));
t('10秒の案内が残っていない', !/3〜10秒/.test(read('js/stock.js') + bs + read('index.html')));
t('ドラフトの確認文は3〜7秒', /3〜7秒あけて返信に作品リンク/.test(read('js/stock.js')));
t('旧「数十秒」「1分以内」の案内が残っていない', !/数十秒あけて返信|秒数\(1分以内\)/.test(read('js/stock.js') + read('js/bluesky.js') + read('index.html')));
if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
console.log('all ok');
