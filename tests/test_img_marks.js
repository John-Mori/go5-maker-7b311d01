// 機能①: 動画作成用画像モーダルの「通常/使用済み/除外」マーク機能の純ロジックを検査。
// - imgHash_(js/candidates.js からexport・KouhoTeian.htmlに同一実装を置く=2ファイル一致必須)の決定性/非衝突。
// - filterMarked_(KouhoTeian.htmlの絞り込みロジックと同じ形をここに複製してテストする=
//   HTMLファイルはNodeからrequireできないため。ロジックはimgHash_のみに依存する薄いfilterなので複製が正確)。
// ★must-fail検証(C-053): 下の「must-fail検証メモ」参照。imgHash_を「常に同じ値を返す」mutantに
//   差し替えて手動実行し、テストが赤くなることを確認済み。commitはmutant無しの正しい版。
var assert = require('assert');
global.window = global.window || {};
var C = require('../js/candidates.js');
var imgHash_ = C.imgHash_;
assert.strictEqual(typeof imgHash_, 'function', 'imgHash_ が export されていない');

var n = 0, ok = 0;
function eq(actual, expected, msg) { n++; if (actual === expected) { ok++; } else { console.error('NG:', msg, '=>', JSON.stringify(actual), '!==', JSON.stringify(expected)); } }

// ---- imgHash_ の決定性・非衝突 ----
eq(imgHash_('data:image/png;base64,AAA'), imgHash_('data:image/png;base64,AAA'), '同じ文字列は同じハッシュ(決定的)');
var hA = imgHash_('data:image/png;base64,AAA');
var hB = imgHash_('data:image/png;base64,BBB');
var hC = imgHash_('data:image/jpeg;base64,CCCCCCCC');
n++; if (hA !== hB && hB !== hC && hA !== hC) { ok++; } else { console.error('NG: 異なる文字列で衝突(代表ケース)', hA, hB, hC); }
eq(imgHash_(''), imgHash_(''), '空文字も決定的');
eq(imgHash_(null), imgHash_(''), 'null は空文字と同じ扱い');

// ---- filterMarked_ 相当(KouhoTeian.htmlの絞り込みロジックの複製。imgHash_ と markState_ に依存) ----
//   マーク値は文字列 "used"|"excluded" or {s,at}(使用日つき)の2形。markState_ で正規化してから判定する
//   (js/candidates.js の mkState_ / KouhoTeian.html の markState_ と一致必須)。
function markState_(v) { return (v && typeof v === 'object') ? String(v.s || '') : String(v || ''); }
function filterMarked_(cid, imgs, marksMap) {
  var m = (marksMap[cid]) || {};
  return (imgs || []).filter(function (im) { var st = markState_(m[imgHash_(im)]); return st !== 'used' && st !== 'excluded'; });
}

var imgs = ['img-1', 'img-2', 'img-3'];
var marks = {};
marks['cidA'] = {};
marks['cidA'][imgHash_('img-1')] = 'used';
marks['cidA'][imgHash_('img-3')] = 'excluded';

var filtered = filterMarked_('cidA', imgs, marks);
eq(filtered.length, 1, 'used/excludedの2枚が除外され通常の1枚が残る');
eq(filtered[0], 'img-2', '残るのは通常の1枚');

// ---- 使用日つき(オブジェクト形 {s,at})でも状態判定は同じ=正規化が効く ----
var marksObj = { cidA: {} };
marksObj.cidA[imgHash_('img-1')] = { s: 'used', at: 1756000000000 };   // 使用済み+使用日
marksObj.cidA[imgHash_('img-2')] = { s: 'excluded' };                  // 除外(atなし)
var filteredObj = filterMarked_('cidA', imgs, marksObj);
eq(filteredObj.length, 1, 'オブジェクト形でもused/excludedは除外(残1)');
eq(filteredObj[0], 'img-3', 'オブジェクト形で残るのは未マークのimg-3');
eq(markState_({ s: 'used', at: 123 }), 'used', 'markState_はオブジェクト形の状態を取り出す');
eq(markState_('used'), 'used', 'markState_は文字列形をそのまま返す');
eq(markState_(undefined), '', 'markState_はundefinedを空文字に');

// 通常(マーク無し)のcidはそのまま全部残る
var filtered2 = filterMarked_('cidB', imgs, marks);
eq(filtered2.length, 3, 'マークが無いcidは全て残る');

// 全除外なら空配列になる
var marksAll = { cidA: {} };
imgs.forEach(function (im) { marksAll.cidA[imgHash_(im)] = 'excluded'; });
var filtered3 = filterMarked_('cidA', imgs, marksAll);
eq(filtered3.length, 0, '全除外なら空配列');

console.log('img_marks: ' + ok + '/' + n + ' PASS');
if (ok !== n) { process.exit(1); }

/* ── must-fail 検証メモ(C-053・手動確認済み・commitはこの版=mutant無し) ──
 * imgHash_ を「常に同じ値を返す」別実装(mutant)に一時的に差し替えて手動実行した:
 *   function imgHash_mutant(s) { return 'x'; }
 * 結果: 全ての画像が同一ハッシュ'x'を持つため、
 *   marks['cidA']['x'] は最後に代入した値('excluded')で上書きされ、
 *   filterMarked_('cidA', imgs, marks) は3枚とも 'excluded' 扱いになり空配列を返した。
 *   => 「used/excludedの2枚が除外され通常の1枚が残る」(length===1を期待)が length===0 になり赤(NG)。
 * → imgHash_ の非衝突性がこのテストの合格に必要であることを確認できた(must-fail構造が機能している)。
 *
 * ── must-fail 検証(markState_・C-053・手動確認済み) ──
 * markState_ を正規化しない mutant( function markState_mut(v){ return v; } )に差し替えて手動実行した:
 *   マーク値がオブジェクト形 {s:'used'} / {s:'excluded'} の時、st は文字列 'used'/'excluded' に正規化されず
 *   オブジェクトのままになり、st!=='used' && st!=='excluded' が常に真 → 1枚も除外されず filtered.length===3。
 *   => 「オブジェクト形でもused/excludedは除外(残1)」(length===1を期待)が length===3 になり赤(NG)。
 * → 使用日つき({s,at})の状態正規化がこのテストの合格に必要であることを確認できた。
 */
