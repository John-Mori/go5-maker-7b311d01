// 「複数画像がない=投稿できない」候補の非表示判定 noMaterialHideDecide_ の回帰テスト。
//   Chami依頼2026-08-24「投稿できる状態だとしても素材がないから投稿できないので非表示に」。
//   5秒動画は複数の写真を並べて作る=動画生成用の画像(ref)が2枚未満の作品は動画化=投稿ができない。
//   ★核心は fail-open= n===0 でも state が未確定(loading/checking/stalled)なら隠さない。
//     画像が「まだ読めていないだけ」の作品を消すと「画像あるのに消えた」の再発(C-041)になる。
//     素朴実装(return n < 2)は loading/checking/stalled を隠してしまう=このテストが赤くなる。
var assert = require('assert');
var C = require('../js/candidates.js');
var f = C.noMaterialHideDecide_;
assert.strictEqual(typeof f, 'function', 'noMaterialHideDecide_ が export されていない');

var n = 0, ok = 0;
function t(name, got, want) { n++; try { assert.strictEqual(got, want); ok++; } catch (e) { console.log('FAIL: ' + name + ' → ' + got + ' (期待 ' + want + ')'); } }

// 複数(2枚以上)あり=投稿できる=隠さない
t('2枚は隠さない', f(2, 'images'), false);
t('3枚は隠さない', f(3, 'images'), false);

// 1枚のみ=複数画像なし=隠す(枚数は確定している)
t('1枚は隠す', f(1, 'images'), true);

// 確定0枚(読んで0=missing / 未着手=none)は隠す
t('missing(確定0枚)は隠す', f(0, 'missing'), true);
t('none(未着手)は隠す', f(0, 'none'), true);

// ★fail-open: 0枚でも未確定(まだ読込中/確認中/読込失敗)なら隠さない
t('loading(読込中)は隠さない', f(0, 'loading'), false);
t('checking(確認中)は隠さない', f(0, 'checking'), false);
t('stalled(読込失敗)は隠さない', f(0, 'stalled'), false); // C-041: 読込失敗を「消えた」扱いにしない

// ★v=919 回帰ガード(Chami 2026-08-24「登録しましたが出て候補一覧に残らない」)=
//   今セッションで追加したばかり(justAdded=true)は、確定0枚/1枚でも隠さない。
//   素朴実装(justAdded を見ない)は下の2件で赤くなる=これから素材を付ける候補が追加直後に消える。
t('justAdded は確定0枚でも隠さない', f(0, 'missing', true), false);
t('justAdded は1枚でも隠さない', f(1, 'images', true), false);

console.log('noMaterialHideDecide_: ' + ok + '/' + n + (ok === n ? ' PASS' : ' FAIL'));
process.exit(ok === n ? 0 : 1);
