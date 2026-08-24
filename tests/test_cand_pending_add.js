// 候補追加の耐久キュー退避判定 shouldDeferCandAdd_ の回帰テスト。
//   Chami 2026-08-24「絶対に保存して裏でやって閉じさせてくれ。ページを閉じても止まるな」への恒久対策。
//   退避してよいのは「展開未了で重複cidへ画像を足す=破壊マージの一点」だけ。ここを広げると旧「展開待ちで
//   保存できない」バグへ、狭めると重複cidの既存画像喪失へ戻る。両方向の後退をこの検査が捕まえる。
var assert = require('assert');
var C = require('../js/candidates.js');
var f = C.shouldDeferCandAdd_;
assert.strictEqual(typeof f, 'function', 'shouldDeferCandAdd_ が export されていない');

var n = 0, ok = 0;
function t(name, got, want) { n++; try { assert.strictEqual(got, want); ok++; } catch (e) { console.log('FAIL: ' + name + ' → ' + got + ' (期待 ' + want + ')'); } }

// 退避する唯一のケース: IDB有効・展開未了・FANZA有効・新規画像あり・重複cidあり
t('全条件そろい=退避', f(true, false, true, 2, true), true);

// 1つでも欠けたら退避しない(=待たずに即保存する)
t('展開済み=退避しない', f(true, true, true, 2, true), false);
t('IDB無効=退避しない', f(false, false, true, 2, true), false);
t('FANZA無効(X単独等)=退避しない', f(true, false, false, 2, true), false);
t('新規画像なし(テキストのみ)=退避しない', f(true, false, true, 0, true), false);
t('新規cid(重複なし)=退避しない', f(true, false, true, 2, false), false);

// 型の揺れに強い(0/undefined/null を偽として扱う)
t('newImgCount=0は偽', f(true, false, true, 0, true), false);
t('undefined混入も偽側へ倒す', f(undefined, false, true, 2, true), false);

console.log('shouldDeferCandAdd_: ' + ok + '/' + n + (ok === n ? ' PASS' : ' FAIL'));
process.exit(ok === n ? 0 : 1);
