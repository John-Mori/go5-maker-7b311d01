// 「登録しましたと出てやはり保存されない=処置をしたという嘘」(Chami 2026-08-24)の根治=
//   保存表示を耐久化の実物で出し分ける durableVerdict_ の回帰テスト。
//   ★核心は「LSもIDBも書けていない(fail)を必ず fail と言い切る」=ここを甘くすると嘘表示が復活する。
//     素朴実装(常に 'ok' を返す/lsOkだけ見て idb を無視する)は下のいずれかで赤くなる=must-fail を満たす。
var assert = require('assert');
var C = require('../js/candidates.js');
var f = C.durableVerdict_;
assert.strictEqual(typeof f, 'function', 'durableVerdict_ が export されていない');

var n = 0, ok = 0;
function t(name, got, want) { n++; try { assert.strictEqual(got, want); ok++; } catch (e) { console.log('FAIL: ' + name + ' → ' + got + ' (期待 ' + want + ')'); } }

// localStorageに書けた=最短で耐久(IDBの状態に関わらず 'ls')
t('LS成功は ls', f(true, false), 'ls');
t('LS成功はIDB有無に関わらず ls', f(true, true), 'ls');

// LS失敗でもIDBミラーに cid を確認できた=耐久('idb')
t('LS失敗+IDBに実在は idb', f(false, true), 'idb');

// ★LSもIDBも無い=本当に保存できていない。ここを 'ok'/'ls'/'idb' にしたら嘘表示が復活する
t('LS失敗+IDBに無しは fail', f(false, false), 'fail');

console.log('durableVerdict_: ' + ok + '/' + n + (ok === n ? ' PASS' : ' FAIL'));
process.exit(ok === n ? 0 : 1);
