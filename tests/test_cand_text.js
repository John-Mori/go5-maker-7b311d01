'use strict';
// 候補テキストの正本 cand_text(同期LS)の read/write と、sync.js の cid 単位フィールドマージを固定する。
// 狙い: 「保存済みのコメント/メモ/X URL が初回描画で空に見える」INC-127/129/132 の恒久対策=
//       テキストを非同期IDBでなく同期LSに持つ設計が、保存/削除/別端末マージで壊れないことを回帰で守る。
var assert = require('assert');
var fs = require('fs');
var source = fs.readFileSync(require.resolve('../js/candidates.js'), 'utf8');
assert.strictEqual((source.match(/function candTextSave_\s*\(/g) || []).length, 1,
  'candTextSave_ は1定義だけにする(後勝ちの重複定義で改善版を上書きしない)');

// --- localStorage シム(Node には無いので最小実装)---
var store = {};
global.localStorage = {
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
  setItem: function (k, v) { store[k] = String(v); },
  removeItem: function (k) { delete store[k]; }
};

var cand = require('../js/candidates.js');
var save = cand.candTextSave_, of = cand.candTextOf_, nonEmpty = cand.candTextNonEmpty_;

// (1) 保存→同期読みで即戻る(空文字は空文字として保持・at が付く)
assert.strictEqual(save('d_1', { comment: 'こんにちは', twitterUrl: 'https://x.com/a' }), true);
var r1 = of('d_1');
assert.strictEqual(r1.comment, 'こんにちは');
assert.strictEqual(r1.twitterUrl, 'https://x.com/a');
assert.strictEqual(r1.memo, '');
assert.ok(r1.at > 0, 'at スタンプが付く');

// (2) urls2 配列は trim + 空落とし、先頭が twitterUrl2 に入る
assert.strictEqual(save('d_2', { urls2: [' https://x.com/b ', '', 'https://x.com/c'] }), true);
var r2 = of('d_2');
assert.deepStrictEqual(r2.urls2, ['https://x.com/b', 'https://x.com/c']);
assert.strictEqual(r2.twitterUrl2, 'https://x.com/b');

// (3) 全項目空=削除(マップから cid ごと消える・無い cid の空保存は no-op で true)
assert.strictEqual(save('d_1', { comment: '', memo: '', twitterUrl: '', twitterUrl2: '', urls2: [] }), true);
assert.strictEqual(of('d_1'), null);
assert.strictEqual(save('missing', {}), true); // 元々無い=何もせず成功

// (4) candTextNonEmpty_ の判定
assert.strictEqual(nonEmpty(null), false);
assert.strictEqual(nonEmpty({ comment: '', memo: '', twitterUrl: '', twitterUrl2: '', urls2: [] }), false);
assert.strictEqual(nonEmpty({ comment: 'x' }), true);
assert.strictEqual(nonEmpty({ urls2: ['u'] }), true);

// --- sync.js の cid 単位マージ純関数 ---
var sync = require('../core/sync.js');
var m = sync._test.mergeCandText_;

// (a) at の新しい側を優先しつつ、(b) 新側で空(欠け)のフィールドは旧側の非空で補う
var older = JSON.stringify({ d_x: { comment: '旧コメント', twitterUrl: 'https://x/old', at: 100 } });
var newer = JSON.stringify({ d_x: { comment: '新コメント', twitterUrl: '', at: 200 } });
var merged = JSON.parse(m(older, newer));
assert.strictEqual(merged.d_x.comment, '新コメント', 'at新側のコメントを採る');
assert.strictEqual(merged.d_x.twitterUrl, 'https://x/old', '新側で空のURLは旧側の非空で補う=消さない');
assert.strictEqual(merged.d_x.at, 200);

// (c) 片側にしか無い cid は保持(集めたテキストを失わない)
var A = JSON.stringify({ d_a: { comment: 'A', at: 10 } });
var B = JSON.stringify({ d_b: { comment: 'B', at: 20 } });
var mAB = JSON.parse(m(A, B));
assert.strictEqual(mAB.d_a.comment, 'A');
assert.strictEqual(mAB.d_b.comment, 'B');

// (d) 空マップ同士・不正JSONでも落ちない
assert.deepStrictEqual(JSON.parse(m('{}', '{}')), {});
assert.strictEqual(m('壊れたJSON', '{}'), null); // パース不能は null(呼び出し側が採用しない)

console.log('PASS: cand_text 同期LS read/write と cid 単位フィールドマージ');
