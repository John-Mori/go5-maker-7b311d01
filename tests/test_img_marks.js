'use strict';

// 動画作成用画像の「通常/使用済み/除外」は、同じ画像を別端末でR2から再構成しても一致すること。
// js/candidates.js が実際に使う純関数を直接呼び、旧dataURL hash・R2 SHA・slotの3経路を回帰検査する。
const assert = require('assert');
global.window = global.window || {};
const C = require('../js/candidates.js');

[
  'imgHash_', 'imgSlotMarkKey_', 'imgUrlHashMarkKey_', 'imgMarkStateFromMap_',
  'imgMarkDateFromMap_', 'remapSlotMarksForImages_'
].forEach(function (name) {
  assert.strictEqual(typeof C[name], 'function', name + ' が export されていない');
});

const imgHash_ = C.imgHash_;
const H1 = '1'.repeat(64);
assert.strictEqual(imgHash_('data:image/png;base64,AAA'), imgHash_('data:image/png;base64,AAA'));
assert.notStrictEqual(imgHash_('data:image/png;base64,AAA'), imgHash_('data:image/png;base64,BBB'));
assert.strictEqual(imgHash_(null), imgHash_(''));

function filterMarked_(cid, imgs, marks, rawKeys) {
  return (imgs || []).filter(function (img, idx) {
    const state = C.imgMarkStateFromMap_(marks, cid, img, idx, rawKeys && rawKeys[idx]);
    return state !== 'used' && state !== 'excluded';
  });
}

// 旧版のdataURL文字列hashは、そのまま読み続ける。
const legacyImgs = ['img-1', 'img-2', 'img-3'];
const legacy = { cidA: {} };
legacy.cidA[imgHash_('img-1')] = 'used';
legacy.cidA[imgHash_('img-3')] = 'excluded';
assert.deepStrictEqual(filterMarked_('cidA', legacyImgs, legacy), ['img-2']);

// 使用日つきの旧オブジェクト形も状態・日付の両方を保つ。
const dated = { cidA: {} };
dated.cidA[imgHash_('img-1')] = { s: 'used', at: 1756000000000 };
assert.strictEqual(C.imgMarkStateFromMap_(dated, 'cidA', 'img-1', 0), 'used');
assert.strictEqual(C.imgMarkDateFromMap_(dated, 'cidA', 'img-1', 0), 1756000000000);

// R2再構成後にMIME/dataURL文字列が変わっても、同じslotなら除外が当たる。
const bySlot = { cidB: { '@slot:1': 'excluded' } };
assert.strictEqual(C.imgMarkStateFromMap_(bySlot, 'cidB', 'data:image/jpeg;base64,REBUILT', 1), 'excluded');
assert.strictEqual(C.imgMarkStateFromMap_(bySlot, 'cidB', 'data:image/jpeg;base64,REBUILT', 0), '');

// manifestのimmutable URLはraw-byte SHAで判定し、再試行クエリが付いても同じ画像になる。
const bySha = { cidC: {} };
bySha.cidC['@sha256:' + H1] = 'used';
const direct = 'https://sync.example.test/img/' + H1 + '?go5_retry=2';
assert.strictEqual(C.imgUrlHashMarkKey_(direct), '@sha256:' + H1);
assert.strictEqual(C.imgMarkStateFromMap_(bySha, 'cidC', direct, 9), 'used');
assert.deepStrictEqual(filterMarked_('cidC', [direct], bySha, [H1]), []);

// 複数キーに状態がある場合も、どこかに刻まれた使用日を失わない。
const multi = { cidD: { '@slot:0': 'used' } };
multi.cidD[imgHash_('same-image')] = { s: 'used', at: 1757000000000 };
assert.strictEqual(C.imgMarkDateFromMap_(multi, 'cidD', 'same-image', 0), 1757000000000);

// 並べ替え・先頭追加後もslot印が同じ画像へ追随する。SHA/旧hashは変更しない。
const inner = { '@slot:0': 'used', '@slot:2': 'excluded', ['@sha256:' + H1]: 'used', legacy: 'excluded' };
const moved = C.remapSlotMarksForImages_(inner, ['a', 'b', 'c'], ['c', 'a', 'b']);
assert.strictEqual(moved['@slot:0'], 'excluded');
assert.strictEqual(moved['@slot:1'], 'used');
assert.strictEqual(moved['@sha256:' + H1], 'used');
assert.strictEqual(moved.legacy, 'excluded');

const inserted = C.remapSlotMarksForImages_(inner, ['a', 'b', 'c'], ['new', 'a', 'b', 'c']);
assert.strictEqual(inserted['@slot:1'], 'used');
assert.strictEqual(inserted['@slot:3'], 'excluded');

const deleted = C.remapSlotMarksForImages_({ '@slot:1': 'excluded' }, ['a', 'b', 'c'], ['a', 'c']);
assert.strictEqual(Object.keys(deleted).length, 0, '削除した画像のslot印を別画像へ誤適用しない');

const duplicate = C.remapSlotMarksForImages_({ '@slot:2': 'excluded' }, ['same', 'x', 'same'], ['same', 'same', 'x']);
assert.strictEqual(duplicate['@slot:1'], 'excluded', '同一文字列の画像が複数でも出現順を保つ');

console.log('OK: image marks survive R2 reconstruction and image ordering changes');
