// 投稿履歴画像の prefix 別ハイドレート・ゲート canReadHistPrefix_ の回帰テスト。
//   Chami報告2026-08-24「投稿履歴ページも動画投稿プレビューが全然表示されない」の恒久対策(改悪=回帰ガード)。
//   真因: used:(本命91件)/ post:(通常0件) を1つのグローバル完了フラグ(_hydrated)で守っていたため、
//   post: が先に完了して _hydrated を立てると、cold iOSで used: が一度timeoutした後の再試行が握り潰され、
//   used: が二度と読まれず「プレビューが全然出ない」に固定していた。ゲートを prefix 別 done に分けた。
//   ここが再びグローバル1本(=post:完了で used: を止める)へ広がったら、この検査が赤くなる。
var assert = require('assert');
var C = require('../js/candidates.js');
var f = C.canReadHistPrefix_;
assert.strictEqual(typeof f, 'function', 'canReadHistPrefix_ が export されていない');

var n = 0, ok = 0;
function t(name, got, want) { n++; try { assert.strictEqual(got, want); ok++; } catch (e) { console.log('FAIL: ' + name + ' → ' + got + ' (期待 ' + want + ')'); } }

// ★核心: post: が done でも used: は読めなければならない(post:先勝ちで本命を止めない)。
t('post:完了は used: を止めない', f('used:', { 'post:': true }, {}, true), true);

// 自分の prefix が done なら読まない(二重読み防止)
t('used: が done なら読まない', f('used:', { 'used:': true }, {}, true), false);
t('post: が done なら読まない', f('post:', { 'post:': true }, {}, true), false);

// 自分の prefix が in-flight なら読まない(多重発火防止)
t('used: が実行中なら読まない', f('used:', {}, { 'used:': true }, true), false);
// 別 prefix が in-flight でも自分は読める
t('post: 実行中でも used: は読める', f('used:', {}, { 'post:': true }, true), true);

// IDB無効なら読まない
t('IDB無効は読まない', f('used:', {}, {}, false), false);

// 何も無い初期状態は読める
t('初期状態は読める', f('used:', {}, {}, true), true);
t('post: 初期状態も読める', f('post:', {}, {}, true), true);

console.log('canReadHistPrefix_: ' + ok + '/' + n + (ok === n ? ' PASS' : ' FAIL'));
process.exit(ok === n ? 0 : 1);
