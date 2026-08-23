// tests/test_refslot_state.js — 動画生成用画像スロットの状態判定(refSlotDecide_)の真値表を固定する。
//   ★HQ 2026-08-14の作法=ソース文字列一致で固めない。本物の判定関数へ本物の入力を通して分岐を実行で確かめる。
//   本命=「家賃交渉人」型(メモあり・一括展開は完了・でもこのcidだけ未確認)が⚠でなく🔍(checking)になること
//   =同期/別タブで後から届く画像を「消えた」と誤表示しない(C-041)。
const assert = require('assert');
const { refSlotDecide_ } = require('../js/candidates.js');

let n = 0;
function t(name, got, want) {
  n++;
  assert.strictEqual(got, want, `[${name}] want=${want} got=${got}`);
  console.log(`  ok  ${name} => ${got}`);
}

// 引数順= (has, worked, idbOk, refLoaded, inMem, candidateHydrated)

// 1) 画像が在れば常に images(他の状態に優先)。
t('画像あり', refSlotDecide_(true, true, true, false, false, true), 'images');
t('画像あり(未展開でも)', refSlotDecide_(true, false, true, false, false, false), 'images');

// 2) 痕跡(コメント/メモ)も無い作品は空欄=none(⏳も⚠も出さない=触っていない作品を汚さない)。
t('痕跡なし', refSlotDecide_(false, false, true, false, false, true), 'none');
t('痕跡なし・展開前', refSlotDecide_(false, false, true, false, false, false), 'none');

// 3) ★本命:メモあり・一括展開は完了・でもこのcidは未確認(refLoaded=false・inMem=false)
//    → ⚠(missing)にせず🔍(checking)。ここが今回の誤検知の核(家賃交渉人)。
t('家賃交渉人=展開済みだが未確認', refSlotDecide_(false, true, true, false, false, true), 'checking');

// 4) メモあり・展開途中(candidateHydrated=false)=まだ何も断定しない → ⏳(loading)。
t('展開途中', refSlotDecide_(false, true, true, false, false, false), 'loading');

// 5) メモあり・このcidを実際に読んだ結果0枚(refLoaded===true) → 正当な⚠(missing)。
t('確認済みで0枚', refSlotDecide_(false, true, true, true, false, true), 'missing');
// 6) メモあり・メモリに実体がある(inMem=true)のに has=false は「画像配列が空」= R2残骸等 → この端末に実体なし=⚠が正しい。
t('メモリ有だが空配列', refSlotDecide_(false, true, true, false, true, true), 'missing');

// 7) IDB非対応端末(idbOk=false)は legacyRefOf_ が同期読み=即確定。メモあり0枚 → ⚠。
t('IDB非対応・0枚', refSlotDecide_(false, true, false, false, false, false), 'missing');

// 8) refLoaded は厳密true判定(truthyな別値で誤確定しない)。
t('refLoaded非true(0)は未確認扱い', refSlotDecide_(false, true, true, 0, false, true), 'checking');

// 引数順= (has, worked, idbOk, refLoaded, inMem, candidateHydrated, stalled)
// 9) ★永久スピナー解体: 取得が持続失敗(stalled=true)なら loading/checking の代わりに 'stalled'(⌛ タップで再試行)。
t('展開途中でも持続失敗→stalled', refSlotDecide_(false, true, true, false, false, false, true), 'stalled');
t('展開済み未確認でも持続失敗→stalled', refSlotDecide_(false, true, true, false, false, true, true), 'stalled');
// 10) ★実データ(images)と陽性確認済み(missing)は stalled より優先=失敗表示で本物を隠さない・⚠を誤上書きしない(C-041)。
t('画像あり＞stalled', refSlotDecide_(true, true, true, false, false, false, true), 'images');
t('確認済み0枚(missing)＞stalled', refSlotDecide_(false, true, true, true, false, true, true), 'missing');
t('痕跡なしは stalled でも none', refSlotDecide_(false, false, true, false, false, false, true), 'none');
// 11) 第7引数省略(既存呼び出し互換)は従来通り=stalledに落ちない。
t('stalled省略=loading', refSlotDecide_(false, true, true, false, false, false), 'loading');
t('stalled=false=loading', refSlotDecide_(false, true, true, false, false, false, false), 'loading');

console.log(`\nAll ${n} passed (refSlotDecide_).`);
