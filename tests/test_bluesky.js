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
const { buildBlueskyPost, detectFacets } = require('../bluesky-core.js');

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
// F-1 自由テキスト中のURLを facet 化（日本語・改行混在でもバイト位置一致）
// ────────────────────────────────────────────────────────────
test('F-1: detectFacets が本文中URLを正しいバイト範囲で指す', function () {
  var link = 'https://al.fanza.co.jp/?lurl=x&af_id=test-001';
  var text = 'おすすめ漫画見つけた💕\n私は最初に右かな？🩷\n\n↓詳細はこちらから🎀 #PR #漫画\n\n' + link;
  var f = detectFacets(text).find(function (x) { return x.features[0].$type === 'app.bsky.richtext.facet#link'; });
  assert.ok(f, 'link facet が存在する');
  assert.strictEqual(f.features[0].uri, link);
  var bytes = enc.encode(text);
  var slice = bytes.slice(f.index.byteStart, f.index.byteEnd);
  assert.strictEqual(new TextDecoder().decode(slice), link, 'facet 範囲がリンクと一致しない');
  assert.strictEqual(f.index.byteEnd, blen(text), 'リンクは末尾にあるはず');
});

// ────────────────────────────────────────────────────────────
// F-2 末尾の句読点・閉じ括弧はリンクに含めない
// ────────────────────────────────────────────────────────────
test('F-2: 末尾の句読点はリンクに含めない', function () {
  var facets = detectFacets('詳細→https://example.com/cid=d_1/。 続きます');
  assert.strictEqual(facets.length, 1);
  assert.strictEqual(facets[0].features[0].uri, 'https://example.com/cid=d_1/');
});

// ────────────────────────────────────────────────────────────
// F-3 URLが無ければ facet なし
// ────────────────────────────────────────────────────────────
test('F-3: URLなしなら facets は空', function () {
  assert.strictEqual(detectFacets('リンクのない本文です').length, 0);
});

// ────────────────────────────────────────────────────────────
// T-1 ハッシュタグ #PR #漫画 が両方 tag facet になる（バイト範囲一致・tag値は#除く）
// ────────────────────────────────────────────────────────────
test('T-1: #PR と #漫画 が両方 tag facet（範囲一致・tag値は#なし）', function () {
  var text = 'おすすめ漫画です #PR #漫画';
  var fs = detectFacets(text).filter(function (f) { return f.features[0].$type === 'app.bsky.richtext.facet#tag'; });
  assert.strictEqual(fs.length, 2, 'タグfacetは2個');
  var bytes = enc.encode(text);
  fs.forEach(function (f) {
    var slice = new TextDecoder().decode(bytes.slice(f.index.byteStart, f.index.byteEnd));
    assert.strictEqual(slice[0], '#', '範囲は#始まり');
    assert.strictEqual(slice.slice(1), f.features[0].tag, 'tag値は#を除いた文字列と一致');
  });
  var tags = fs.map(function (f) { return f.features[0].tag; });
  assert.deepStrictEqual(tags.sort(), ['PR', '漫画']);
});

// ────────────────────────────────────────────────────────────
// T-2 日本語のみタグ #漫画 のバイト範囲がズレない（隣を巻き込まない）
// ────────────────────────────────────────────────────────────
test('T-2: 日本語タグ #漫画 のバイト範囲が正確', function () {
  var text = 'a #漫画 b';
  var f = detectFacets(text).find(function (x) { return x.features[0].$type === 'app.bsky.richtext.facet#tag'; });
  var bytes = enc.encode(text);
  assert.strictEqual(new TextDecoder().decode(bytes.slice(f.index.byteStart, f.index.byteEnd)), '#漫画');
  assert.strictEqual(f.features[0].tag, '漫画');
});

// ────────────────────────────────────────────────────────────
// T-3 先頭・末尾どちらのタグも検出／タグ無しは空
// ────────────────────────────────────────────────────────────
test('T-3: 先頭タグ・末尾タグ・タグ無し', function () {
  var head = detectFacets('#先頭 です').filter(byTag);
  assert.strictEqual(head.length, 1); assert.strictEqual(head[0].index.byteStart, 0);
  var tail = detectFacets('最後は #末尾').filter(byTag);
  assert.strictEqual(tail.length, 1); assert.strictEqual(tail[0].index.byteEnd, enc.encode('最後は #末尾').length);
  assert.strictEqual(detectFacets('タグの無い本文です').filter(byTag).length, 0);
  function byTag(f) { return f.features[0].$type === 'app.bsky.richtext.facet#tag'; }
});

// ────────────────────────────────────────────────────────────
// T-4 URLとタグ混在：両方付き byteStart昇順／URL内の#は誤検出しない
// ────────────────────────────────────────────────────────────
test('T-4: URL＋タグ混在は両方・昇順、URL内#は拾わない', function () {
  var text = '見て #PR https://example.com/a#frag #漫画';
  var fs = detectFacets(text);
  var types = fs.map(function (f) { return f.features[0].$type.replace('app.bsky.richtext.facet', ''); });
  assert.ok(types.indexOf('#link') > -1, 'linkあり');
  assert.strictEqual(fs.filter(function (f) { return f.features[0].$type.endsWith('#tag'); }).length, 2, 'タグは#PRと#漫画の2個（URL内#fragは除外）');
  for (var i = 1; i < fs.length; i++) assert.ok(fs[i].index.byteStart >= fs[i - 1].index.byteStart, 'byteStart昇順');
});

// ────────────────────────────────────────────────────────────
// F-4 composePostTextの新レイアウト(案内テンプレ文の直下にURL・URL2本)でも
//     両方のリンクfacetが正しいバイト範囲を指す(2026-07-20 レイアウト修正の回帰防止)
// ────────────────────────────────────────────────────────────
test('F-4: 案内文の直下にURL(改行1つ)が2ブロック続いても両方のfacetが正しい', function () {
  var workLink = 'https://5mgl.com/abc12';
  var saleLink = 'https://yoz2.com/def34';
  var text = '続きが気になっちゃう一冊、みつけた📚\nしかも今なら20%オフ💕\n\n' +
    '↓詳しくはこちらから🌙 #PR #漫画\n' + workLink + '\n\n' +
    '🏮 大幅割引セール中の同人祭ページ 🏮\n' + saleLink;
  var facets = detectFacets(text).filter(function (f) { return f.features[0].$type === 'app.bsky.richtext.facet#link'; });
  assert.strictEqual(facets.length, 2, 'リンクfacetは2個(作品URL・セールURL)');
  var bytes = enc.encode(text);
  var uris = facets.map(function (f) { return new TextDecoder().decode(bytes.slice(f.index.byteStart, f.index.byteEnd)); });
  assert.deepStrictEqual(uris, [workLink, saleLink], 'facetの並び・範囲がURLと一致');
  // 各facetの直前の1文字が改行であること(=案内文の"すぐ下の行"に置かれている)
  [workLink, saleLink].forEach(function (u) {
    var idx = text.indexOf(u);
    assert.strictEqual(text[idx - 1], '\n', u + ' の直前は改行1つ(すぐ上の行の直下にある)');
  });
});

// ────────────────────────────────────────────────────────────
// 結果集計
// ────────────────────────────────────────────────────────────
console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');

if (failed > 0) {
  process.exit(1);
}
