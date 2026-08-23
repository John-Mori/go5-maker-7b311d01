// LS満杯時の回収判定 reclaimClassify_ の喪失安全性を検査(Fable5診断2026-08-24)。
// ★must-fail: reclaimClassify_ が無い/雑に「全部evict」する実装では必ず赤くなる3ケースを含む。
var assert = require('assert');
global.window = global.window || {};
var C = require('../js/candidates.js');
var cls = C.reclaimClassify_;
assert.strictEqual(typeof cls, 'function', 'reclaimClassify_ が export されていない');

var n = 0, ok = 0;
function eq(actual, expected, msg) { n++; if (actual === expected) { ok++; } else { console.error('NG:', msg, '=>', actual, '!==', expected); } }

// 1) base64画像・IDB未確認・R2未設定 → sole-copyの可能性=消してはいけない(keep)。「全部消す」実装で赤。
eq(cls({ imgs: ['data:image/jpeg;base64,AAAA'], at: 1 }, false, false), 'keep', 'base64/IDB不明/R2無 は保護');
// 2) R2マーカー → R2実体への道標=消したら到達不能(keep)。refHasImageData を先に見る実装だと誤ってevictする。
eq(cls({ __r2n: 2, at: 1 }, true, true), 'keep', 'R2マーカーは常に保護');
// 3) base64画像・IDB耐久確認済み → 死荷重=退去してよい(evict)。
eq(cls({ img: 'data:image/jpeg;base64,AAAA', at: 1 }, true, false), 'evict', 'IDBに耐久コピー在りは退去可');
// 4) 読めない/画像なし → 誰も読めない=失うものが無い(evict)。
eq(cls(null, undefined, false), 'evict', 'null は退去可');
eq(cls({ comment: 'x' }, false, false), 'evict', '画像なしrecは退去可');
// 5) base64画像・IDB未確認だがR2設定済み → R2へ退避して縮小できる(toR2・少なくとも keep=保護ではない)。
eq(cls({ imgs: ['data:image/jpeg;base64,AAAA'] }, false, true), 'toR2', 'R2設定済みは退避経路');

console.log('reclaimClassify_: ' + ok + '/' + n + ' PASS');
if (ok !== n) { process.exit(1); }
