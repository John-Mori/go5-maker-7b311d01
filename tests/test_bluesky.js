/**
 * tests/test_bluesky.js
 * Node で実行できる自己完結テスト（追加パッケージ不使用）
 * 実行: node tests/test_bluesky.js
 *
 * 対象は純粋関数 buildBlueskyPost のみ（ネットワークは検証しない）。
 * 特に facet の index が「UTF-8 バイトオフセット」で正しいかを確認する。
 */

'use strict';

const assert = require('assert');
const { buildBlueskyPost } = require('../bluesky-core.js');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log('PASS: ' + name);
    passed++;
  } catch (e) {
    console.log('FAIL: ' + name);
    console.log('      ' + e.message);
    failed++;
  }
}

const enc = new TextEncoder();
const blen = (s) => enc.encode(s).length;

// ────────────────────────────────────────────────────────────
// B-1 固定文＋提携文＋リンク → 並びと facet
// ────────────────────────────────────────────────────────────
test('B-1: 固定文＋提携文＋リンクが正しい順序で連結される', function () {
  const r = buildBlueskyPost({
    words: '新作できました！',
    disclosure: '※アフィリエイト広告を利用しています',
    link: 'https://al.fanza.co.jp/?lurl=x&af_id=test-001'
  });
  assert.strictEqual(
    r.text,
    '新作できました！\n\n※アフィリエイト広告を利用しています\nhttps://al.fanza.co.jp/?lurl=x&af_id=test-001'
  );
});

// ────────────────────────────────────────────────────────────
// B-2 facet のバイトオフセットがリンク文字列と一致する（日本語混在）
// ────────────────────────────────────────────────────────────
test('B-2: facet の byteStart/byteEnd が UTF-8 バイト基準でリンクを指す', function () {
  const link = 'https://al.fanza.co.jp/?lurl=x&af_id=test-001';
  const r = buildBlueskyPost({
    words: '新作できました！',
    disclosure: '※アフィリエイト広告を利用しています',
    link: link
  });
  assert.strictEqual(r.facets.length, 1, 'facet は1個');
  const f = r.facets[0];
  assert.strictEqual(f.features[0]['$type'], 'app.bsky.richtext.facet#link');
  assert.strictEqual(f.features[0].uri, link);

  // text 全体をバイト列にしたとき、[byteStart, byteEnd) がちょうど link と一致するはず
  const bytes = enc.encode(r.text);
  const slice = bytes.slice(f.index.byteStart, f.index.byteEnd);
  assert.strictEqual(new TextDecoder().decode(slice), link, 'facet 範囲がリンクと一致しない');
  assert.strictEqual(f.index.byteEnd - f.index.byteStart, blen(link), 'facet のバイト長がリンクと一致しない');
  assert.strictEqual(f.index.byteEnd, blen(r.text), 'リンクは末尾にあるはず');
});

// ────────────────────────────────────────────────────────────
// B-3 リンクなし → facet 空
// ────────────────────────────────────────────────────────────
test('B-3: リンク未指定なら facets は空・本文のみ', function () {
  const r = buildBlueskyPost({ words: 'こんにちは', disclosure: '' });
  assert.strictEqual(r.text, 'こんにちは');
  assert.strictEqual(r.facets.length, 0);
});

// ────────────────────────────────────────────────────────────
// B-4 リンクのみ → 本文はリンク1行、facet は先頭から
// ────────────────────────────────────────────────────────────
test('B-4: 固定文も提携文も空・リンクのみ → facet は byteStart=0', function () {
  const link = 'https://example.com/cid=d_1/';
  const r = buildBlueskyPost({ link: link });
  assert.strictEqual(r.text, link);
  assert.strictEqual(r.facets[0].index.byteStart, 0);
  assert.strictEqual(r.facets[0].index.byteEnd, blen(link));
});

// ────────────────────────────────────────────────────────────
// B-5 前後の空白は trim される / 全部空でも落ちない
// ────────────────────────────────────────────────────────────
test('B-5: 入力の前後空白は trim、全空入力でも例外を投げない', function () {
  const r = buildBlueskyPost({ words: '  やあ  ', disclosure: '  ', link: '  ' });
  assert.strictEqual(r.text, 'やあ');
  assert.strictEqual(r.facets.length, 0);

  const empty = buildBlueskyPost({});
  assert.strictEqual(empty.text, '');
  assert.strictEqual(empty.facets.length, 0);
});

// ────────────────────────────────────────────────────────────
// 結果集計
// ────────────────────────────────────────────────────────────
console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');

if (failed > 0) {
  process.exit(1);
}
