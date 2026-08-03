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
const { buildBlueskyPost, detectFacets, stripAutoBlocks, xWeightedLength, insertHookCta, stripHookCtaLines, HOOK_DEEPEN_LINE, CTA_LINE, WORK_LINK_PLACEHOLDER, fillWorkLinkPlaceholder, hasWorkLinkPlaceholder, SALE_LINK_PLACEHOLDER, fillSaleLinkPlaceholder, hasSaleLinkPlaceholder, resolvePromoTemplate } = require('../bluesky-core.js');

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
// S-1〜S-8  stripAutoBlocks(貼り付け済みの古い完成形を剥がす＝投稿本文の二重化対策)
//   再現元: Chami報告2026-07-20「プレビュー画面が当てにならない」— 本文に旧PR行＋旧セール行＋
//   旧短縮URL(da.gd)が残ったまま自動付与が走り、同じ見出しが2組出ていた。
// ────────────────────────────────────────────────────────────
test('S-1: 実際に二重化した本文 → フックだけ残る(PR行/セール行/旧URLを除去)', function () {
  var stale = 'おすすめ漫画見つけた💕\nなんと今なら50%オフのおトク作品！✨\n\n' +
    '↓詳細はこちらから🎀 #PR #漫画\n\n' +
    '⭐大幅割引セール中の同人はこちら 🎀\nhttps://da.gd/h1hRkr';
  assert.strictEqual(stripAutoBlocks(stale), 'おすすめ漫画見つけた💕\nなんと今なら50%オフのおトク作品！✨');
});
test('S-2: 独自に書いたPR風の文は残す(既知テンプレと完全一致する行だけ剥がす)', function () {
  var t = '本文\n\n↓詳細はこっち見て！ #PR\nhttps://example.com/x';
  assert.strictEqual(stripAutoBlocks(t), t, '独自文とその下のURLは保持する');
});
test('S-3: 本文中の単独URL行は消さない(テンプレ見出しの直下でない)', function () {
  var t = '本文\nhttps://example.com/keep\nおしまい';
  assert.strictEqual(stripAutoBlocks(t), t);
});
test('S-4: テンプレ直下が裸URLでなければその行は残す', function () {
  assert.strictEqual(stripAutoBlocks('↓詳細はこちらから🎀 #PR #漫画\n続きの文 https://example.com/y'),
    '続きの文 https://example.com/y');
});
test('S-5: acc2テンプレ(現行・旧)も剥がす', function () {
  assert.strictEqual(stripAutoBlocks('本文\n\n↓詳しくはこちらから🌙 #PR #漫画\nhttps://da.gd/a'), '本文');
  assert.strictEqual(stripAutoBlocks('本文\n\n↓続きはこちらから🌙 #PR #漫画\nhttps://da.gd/b'), '本文');
  assert.strictEqual(stripAutoBlocks('本文\n\n🏮 大幅割引セール中の同人祭ページ 🏮\nhttps://da.gd/c'), '本文');
});
test('S-6: 空/null/undefined → 空文字(投稿本文を壊さない)', function () {
  assert.strictEqual(stripAutoBlocks(''), '');
  assert.strictEqual(stripAutoBlocks(null), '');
  assert.strictEqual(stripAutoBlocks(undefined), '');
});
test('S-7: テンプレのみの本文 → 空文字', function () {
  assert.strictEqual(stripAutoBlocks('↓詳細はこちらから🎀 #PR #漫画'), '');
});
test('S-8: 冪等(2回かけても結果が変わらない)', function () {
  var stale = 'フック\n\n↓詳細はこちらから🎀 #PR #漫画\nhttps://da.gd/x\n\n⭐大幅割引セール中の同人はこちら 🎀\nhttps://da.gd/y';
  var once = stripAutoBlocks(stale);
  assert.strictEqual(stripAutoBlocks(once), once, '2回目で追加の変化が起きてはいけない');
  assert.strictEqual(once, 'フック');
});
// ── S-9/S-10: フック深掘り行/CTA行もstripAutoBlocksの対象に含める(2026-07-21 AD-GL指摘・INC-111と同じ経路対策) ──
//   背景: Q保存で「完成形」(フック深掘り行/CTA行を含む本文)を保存→Q読込で本文に戻す→
//   composePostTextが自動付与をもう一度足す、という二重化が起きうる。stripAutoBlocksが
//   フック深掘り行/CTA行も剥がすことで、この経路でも常に生のフック+割引行まで戻ってから組み直す。
test('S-9: フック深掘り行/CTA行(単独行)も剥がす。直下の行は消費しない', function () {
  var stale = 'フック\n' + HOOK_DEEPEN_LINE + '\n割引行\n' + CTA_LINE + '\n\n' +
    '↓詳細はこちらから🎀 #PR #漫画\nhttps://da.gd/x';
  assert.strictEqual(stripAutoBlocks(stale), 'フック\n割引行');
});
test('S-10: 独自に書いた似た文は残す(完全一致する行だけを対象にする・S-2の原則)', function () {
  var t = 'フック\n気になる展開だけど読み進めるか迷う\n本文続き';
  assert.strictEqual(stripAutoBlocks(t), t, '完全一致しない独自文は保持する');
});

// ────────────────────────────────────────────────────────────
// H-1〜H-7  insertHookCta(フックの深掘り＋CTA行・X案2・Chami承認2026-07-21)
//   挿入位置：1行目(フック)の直後に深掘り行／本文の最後にCTA行。ch共通(acc1/acc2で文言差はない)。
// ────────────────────────────────────────────────────────────
test('H-1: フック1行のみ → 深掘り行を2行目、CTA行を末尾に挿入', function () {
  assert.strictEqual(
    insertHookCta('おすすめ漫画見つけた💕'),
    'おすすめ漫画見つけた💕\n' + HOOK_DEEPEN_LINE + '\n' + CTA_LINE
  );
});
test('H-2: フック＋割引行 → 深掘り行は割引行の前、CTA行は割引行の後', function () {
  assert.strictEqual(
    insertHookCta('おすすめ漫画見つけた💕\nなんと今なら50%オフのおトク作品！✨'),
    'おすすめ漫画見つけた💕\n' + HOOK_DEEPEN_LINE + '\nなんと今なら50%オフのおトク作品！✨\n' + CTA_LINE
  );
});
test('H-3: 空文字/null/undefined → 何も足さずそのまま', function () {
  assert.strictEqual(insertHookCta(''), '');
  assert.strictEqual(insertHookCta(null), '');
  assert.strictEqual(insertHookCta(undefined), '');
});
test('H-4: acc2テンプレでも同じ位置関係(ch共通・文言分けしない)', function () {
  assert.strictEqual(
    insertHookCta('続きが気になっちゃう一冊、みつけた📚\nしかも今なら20%オフ💕'),
    '続きが気になっちゃう一冊、みつけた📚\n' + HOOK_DEEPEN_LINE + '\nしかも今なら20%オフ💕\n' + CTA_LINE
  );
});
// ── H-5: 真の冪等性(2026-07-21 AD-GL指摘で修正) ──
//   ★以前のH-5は「同じ未加工入力に2回かけて結果を比べる」誤ったテストで、
//   本来検証すべき f(f(x)) === f(x) (=1回目の出力をもう一度入力にする)ではなかった。
//   AD-GLが実測した結果、旧実装は1回目の出力を入力にするとフック行/CTA行が2行ずつになり
//   冪等ではなかった(INC-111と同じ二重化の経路)。今回の修正(insertHookCta自身が挿入前に
//   既存のフック深掘り行/CTA行を剥がす)で f(f(x)) === f(x) が成立することを確認する。
test('H-5: 真の冪等性 insertHookCta(insertHookCta(x)) === insertHookCta(x)(フック1行のみ)', function () {
  var x = 'おすすめ漫画見つけた💕';
  var once = insertHookCta(x);
  var twice = insertHookCta(once);
  assert.strictEqual(twice, once, 'f(f(x)) は f(x) と一致するはず(=行が増えてはいけない)');
});
test('H-6: 真の冪等性(フック＋割引行)', function () {
  var x = 'おすすめ漫画見つけた💕\nなんと今なら50%オフのおトク作品！✨';
  var once = insertHookCta(x);
  var twice = insertHookCta(once);
  assert.strictEqual(twice, once, 'f(f(x)) は f(x) と一致するはず(=行が増えてはいけない)');
  // フック深掘り行・CTA行がそれぞれ1個ずつであること(数えて確認)
  var lines = once.split('\n');
  assert.strictEqual(lines.filter(function (l) { return l === HOOK_DEEPEN_LINE; }).length, 1, '深掘り行は1個のみ');
  assert.strictEqual(lines.filter(function (l) { return l === CTA_LINE; }).length, 1, 'CTA行は1個のみ');
});
test('H-7: 「完成形」の本文(Q読込を想定)を入力にしても行が増えない', function () {
  // Q保存されていた「完成形」＝過去にinsertHookCtaを通した後の本文をそのまま入力にするケース。
  var complete = 'おすすめ漫画見つけた💕\n' + HOOK_DEEPEN_LINE + '\nなんと今なら50%オフのおトク作品！✨\n' + CTA_LINE;
  var result = insertHookCta(complete);
  var lines = result.split('\n');
  assert.strictEqual(lines.filter(function (l) { return l === HOOK_DEEPEN_LINE; }).length, 1, '深掘り行が2重にならない');
  assert.strictEqual(lines.filter(function (l) { return l === CTA_LINE; }).length, 1, 'CTA行が2重にならない');
  assert.strictEqual(result, complete, '既に正しい形なら見た目は変わらない');
});

// ────────────────────────────────────────────────────────────
// R-1〜R-3  bluesky.js composePostText相当のフル組み立て(stripAutoBlocks→insertHookCta→
//   PR行+リンク→セール行+リンク、の順)の回帰テスト。
//   ★INC-111と同じ経路(Q保存で完成形を保存→Q読込で本文に戻す→自動付与がもう一度足す)を
//   再現し、二重化しないことを固定する(2026-07-21 AD-GL指摘)。PR行/セール行の文言はbluesky.jsの
//   PR_LINE_()/DISCOUNT_LEAD_()と同一(ch別・1文字も変えていない)。
// ────────────────────────────────────────────────────────────
var PR_LINE = { acc1: '↓詳細はこちらから🎀 #PR #漫画', acc2: '↓詳しくはこちらから🌙 #PR #漫画' };
var DISCOUNT_LEAD = { acc1: '⭐大幅割引セール中の同人はこちら 🎀', acc2: '🏮 大幅割引セール中の同人祭ページ 🏮' };
function composePostTextLike(acc, rawCaption, link, dlink) {
  var caption = insertHookCta(stripAutoBlocks(rawCaption));
  var out = (link && caption.indexOf(link) < 0) ? (caption + '\n\n' + PR_LINE[acc] + '\n' + link) : caption;
  if (dlink && caption.indexOf(dlink) < 0) out += '\n\n' + DISCOUNT_LEAD[acc] + '\n' + dlink;
  return out;
}
test('R-1: acc1のフル組み立て(フック+深掘り+割引50%+CTA+PR行+リンク+セール行+リンク)がChami承認案2(加重251/280)と一致', function () {
  var raw = 'おすすめ漫画見つけた💕\nなんと今なら50%オフのおトク作品！✨';
  var text = composePostTextLike('acc1', raw, 'https://5mgl.com/abc12', 'https://5mgl.com/xyz89');
  assert.strictEqual(text,
    'おすすめ漫画見つけた💕\n' + HOOK_DEEPEN_LINE + '\nなんと今なら50%オフのおトク作品！✨\n' + CTA_LINE +
    '\n\n↓詳細はこちらから🎀 #PR #漫画\nhttps://5mgl.com/abc12' +
    '\n\n⭐大幅割引セール中の同人はこちら 🎀\nhttps://5mgl.com/xyz89'
  );
  assert.strictEqual(xWeightedLength(text), 251, 'Chami承認済みの目標値(案2)と一致(実測で固定)');
});
test('R-2: acc2のフル組み立て → 既存の🏮/🌙文言はそのまま・フック深掘り/CTA行も1組だけ追加される', function () {
  var raw = '続きが気になっちゃう一冊、みつけた📚\nしかも今なら20%オフ💕';
  var text = composePostTextLike('acc2', raw, 'https://yoz2.com/abc12', 'https://yoz2.com/xyz89');
  assert.strictEqual(text,
    '続きが気になっちゃう一冊、みつけた📚\n' + HOOK_DEEPEN_LINE + '\nしかも今なら20%オフ💕\n' + CTA_LINE +
    '\n\n↓詳しくはこちらから🌙 #PR #漫画\nhttps://yoz2.com/abc12' +
    '\n\n🏮 大幅割引セール中の同人祭ページ 🏮\nhttps://yoz2.com/xyz89'
  );
});
test('R-3: 「完成形」(Q読込を想定)を入力に再度フル組み立てしても二重化しない(INC-111と同じ経路の回帰防止)', function () {
  var raw = 'おすすめ漫画見つけた💕\nなんと今なら50%オフのおトク作品！✨';
  var link = 'https://5mgl.com/abc12', dlink = 'https://5mgl.com/xyz89';
  var once = composePostTextLike('acc1', raw, link, dlink);
  // Q保存→Q読込で「完成形」がそのままels.text.valueに戻ってきたケースを再現。
  var twice = composePostTextLike('acc1', once, link, dlink);
  assert.strictEqual(twice, once, '完成形を入力にしても行・見出しが増えてはいけない');
});

// ────────────────────────────────────────────────────────────
// X-1〜X-6  xWeightedLength(X投稿の加重文字数)
//   典拠: X公式 docs.x.com/fundamentals/counting-characters
//   上限=加重280 / Latin・記号=1 / CJK(日本語)・絵文字=2 / URLは長さに関わらず一律23。
//   1文字=1で数えると書ける量を約2倍に見せ、「余裕あり」表示の文がXで弾かれる。
// ────────────────────────────────────────────────────────────
test('X-1: 英数字は1文字=1', function () {
  assert.strictEqual(xWeightedLength('abc123'), 6);
});
test('X-2: 日本語は1文字=2(ひらがな/カタカナ/漢字)', function () {
  assert.strictEqual(xWeightedLength('あ'), 2);
  assert.strictEqual(xWeightedLength('ア'), 2);
  assert.strictEqual(xWeightedLength('漢'), 2);
  assert.strictEqual(xWeightedLength('あいう'), 6);
});
test('X-3: 絵文字は1つ=2(サロゲートペアを1文字として数える)', function () {
  assert.strictEqual(xWeightedLength('\u{1F495}'), 2, '💕 は2');
  assert.strictEqual(xWeightedLength('\u{1F380}'), 2, '🎀 は2');
});
test('X-4: URLは長さに関わらず一律23', function () {
  assert.strictEqual(xWeightedLength('https://5mgl.com/fCIQv'), 23);
  assert.strictEqual(xWeightedLength('https://al.fanza.co.jp/?lurl=' + 'x'.repeat(300)), 23,
    '長いアフィリンクでも23');
  assert.strictEqual(xWeightedLength('https://a.com/1 https://b.com/2'), 23 + 1 + 23, 'URL2本+間の空白');
});
test('X-5: 日本語のみなら実質127字前後が上限(+URL1本)', function () {
  var url = '\n\nhttps://5mgl.com/fCIQv';
  assert.ok(xWeightedLength('あ'.repeat(127) + url) <= 280, '127字は収まる');
  assert.ok(xWeightedLength('あ'.repeat(130) + url) > 280, '130字は超える');
});
test('X-6: 旧実装(1文字=1)との差＝過大表示の再現', function () {
  var t = 'おすすめ漫画見つけた\u{1F495}\nなんと今なら50%オフのおトク作品！✨\n\n' +
          '↓詳細はこちらから\u{1F380} #PR #漫画\nhttps://5mgl.com/fCIQv';
  function old(s) { // 修正前の xCount
    var u = (s.match(/https?:\/\/[^\s]+/g) || []);
    return Array.from(s.replace(/https?:\/\/[^\s]+/g, '')).length + u.length * 23;
  }
  assert.strictEqual(old(t), 75, '旧実装は75と表示していた');
  assert.strictEqual(xWeightedLength(t), 114, '実際のXの換算は114');
  assert.ok(xWeightedLength(t) > old(t), '旧実装は少なく見積もる=書ける量を過大に見せる');
});

// ────────────────────────────────────────────────────────────
// P-1〜P-8  紹介用短縮リンクのプレースホルダ方式(2026-07-23 Chami指定)
//   テンプレ帳に「紹介用短縮リンク」という文字を書いておくと、実際の作品短縮リンクへ
//   機械的に置換される。PR行の直下にプレースホルダがある形は「古い完成形」として
//   剥がされてはいけない(それをやると二重化する)。
// ────────────────────────────────────────────────────────────
test('P-1: PR行+プレースホルダの対は剥がされない(現行の生きたテンプレとして保持)', function () {
  var t = 'おすすめ漫画見つけた💕\nなんと今なら50%オフのおトク作品！✨\n\n' +
    '↓詳細はこちらから🎀 #PR #漫画\n' + WORK_LINK_PLACEHOLDER;
  assert.strictEqual(stripAutoBlocks(t), t, 'プレースホルダ形式はそのまま保持される');
});
test('P-2: acc2の文言(↓詳しくはこちらから🌙)でも同様に保持される', function () {
  var t = '本文\n\n↓詳しくはこちらから🌙 #PR #漫画\n' + WORK_LINK_PLACEHOLDER;
  assert.strictEqual(stripAutoBlocks(t), t);
});
test('P-3: プレースホルダを実リンクへ置換', function () {
  var t = '見出し\n' + WORK_LINK_PLACEHOLDER + '\n続き';
  assert.strictEqual(fillWorkLinkPlaceholder(t, 'https://5mgl.com/fCIQv', ''),
    '見出し\nhttps://5mgl.com/fCIQv\n続き');
});
test('P-4: 短縮リンクが未取得ならfallback(生リンク)を使う', function () {
  var t = WORK_LINK_PLACEHOLDER;
  assert.strictEqual(fillWorkLinkPlaceholder(t, '', 'https://al.fanza.co.jp/?lurl=x&af_id=y'),
    'https://al.fanza.co.jp/?lurl=x&af_id=y', '短縮が無ければ生リンクへ倒す(安全網measureWorkLink_が拾えるように)');
});
test('P-5: 短縮リンクも生リンクも無ければプレースホルダのまま(作品URL未入力時の旧仕様どおり)', function () {
  assert.strictEqual(fillWorkLinkPlaceholder(WORK_LINK_PLACEHOLDER, '', ''), WORK_LINK_PLACEHOLDER);
});
test('P-6: プレースホルダが複数出現しても全て置換', function () {
  var t = WORK_LINK_PLACEHOLDER + '\n' + WORK_LINK_PLACEHOLDER;
  assert.strictEqual(fillWorkLinkPlaceholder(t, 'https://5mgl.com/x', ''), 'https://5mgl.com/x\nhttps://5mgl.com/x');
});
test('P-7: プレースホルダを含まない本文は無変化(fillWorkLinkPlaceholder)', function () {
  assert.strictEqual(fillWorkLinkPlaceholder('普通の本文', 'https://5mgl.com/x', ''), '普通の本文');
});
test('P-8: 割引ブロック(セール行+実リンク)は従来どおり剥がされる(プレースホルダとは無関係の既存動作)', function () {
  var t = 'おすすめ漫画見つけた💕\n\n↓詳細はこちらから🎀 #PR #漫画\n' + WORK_LINK_PLACEHOLDER +
    '\n\n⭐大幅割引セール中の同人はこちら 🎀\nhttps://5mgl.com/fCIQv';
  var expected = 'おすすめ漫画見つけた💕\n\n↓詳細はこちらから🎀 #PR #漫画\n' + WORK_LINK_PLACEHOLDER;
  assert.strictEqual(stripAutoBlocks(t), expected, 'PR行+プレースホルダは残り、割引ブロックだけ剥がれる');
});

// P-9〜P-11  セール中短縮リンクのプレースホルダ方式(2026-07-31 Chami指定)
test('P-9: セールプレースホルダを短縮セールリンクへ置換', function () {
  var t = '☀️大幅割引セール中の夏の同人祭はこちら🍧\n' + SALE_LINK_PLACEHOLDER;
  assert.strictEqual(fillSaleLinkPlaceholder(t, 'https://5mgl.com/X1iAF'),
    '☀️大幅割引セール中の夏の同人祭はこちら🍧\nhttps://5mgl.com/X1iAF');
});
test('P-10: セールリンク未取得ならプレースホルダのまま(literal投稿は投稿直前の安全網が処理)', function () {
  assert.strictEqual(fillSaleLinkPlaceholder(SALE_LINK_PLACEHOLDER, ''), SALE_LINK_PLACEHOLDER);
});
test('P-11: セールプレースホルダを含まない本文は無変化', function () {
  assert.strictEqual(fillSaleLinkPlaceholder('普通の本文', 'https://5mgl.com/X1iAF'), '普通の本文');
});

// P-12〜P-24  表記ゆれ吸収(Chami報告2026-08-02「(商品紹介短縮URL)が置換されず生URLが末尾に二重化」)
//   Chamiはテンプレ帳の本文に手書きで置く=括弧付き/語順違いが混ざる。exact一致では拾えず
//   else経路で生URLが自動追記され二重化していた。正規表現で吸収し、括弧は残して中身だけ置換する。
test('P-12: 括弧付き「(商品紹介短縮URL)」を検出=作品プレースホルダ', function () {
  assert.strictEqual(hasWorkLinkPlaceholder('本文\n\n(商品紹介短縮URL)'), true);
});
test('P-13: 「(商品紹介短縮URL)」置換=括弧ごとURLへ(裸URL・Chami2026-08-03「()から置換対象」)', function () {
  assert.strictEqual(fillWorkLinkPlaceholder('本文\n\n(商品紹介短縮URL)', 'https://yoz2.com/OZX3F', ''),
    '本文\n\nhttps://yoz2.com/OZX3F');
});
test('P-14: 「(商品紹介用短縮URL)」(用あり)も括弧ごと置換', function () {
  assert.strictEqual(fillWorkLinkPlaceholder('(商品紹介用短縮URL)', 'https://yoz2.com/OZX3F', ''),
    'https://yoz2.com/OZX3F');
});
test('P-15: 既定表記「紹介用短縮リンク」も従来どおり検出・置換(後方互換)', function () {
  assert.strictEqual(hasWorkLinkPlaceholder(WORK_LINK_PLACEHOLDER), true);
  assert.strictEqual(fillWorkLinkPlaceholder(WORK_LINK_PLACEHOLDER, 'https://5mgl.com/x', ''), 'https://5mgl.com/x');
});
test('P-16: 括弧付き「(セール紹介短縮用URL)」を検出=セールプレースホルダ', function () {
  assert.strictEqual(hasSaleLinkPlaceholder('本文\n\n(セール紹介短縮用URL)'), true);
});
test('P-17: 「(セール紹介短縮用URL)」置換=括弧ごとURLへ(裸URL・Chami2026-08-03)', function () {
  assert.strictEqual(fillSaleLinkPlaceholder('(セール紹介短縮用URL)', 'https://yoz2.com/evTh1'),
    'https://yoz2.com/evTh1');
});
test('P-18: 既定表記「セール中短縮リンク」も従来どおり検出・置換(後方互換)', function () {
  assert.strictEqual(hasSaleLinkPlaceholder(SALE_LINK_PLACEHOLDER), true);
  assert.strictEqual(fillSaleLinkPlaceholder(SALE_LINK_PLACEHOLDER, 'https://5mgl.com/s'), 'https://5mgl.com/s');
});
test('P-19: ★作品置換はセール語を食わない(「セール紹介短縮用URL」を作品リンクにしない)', function () {
  // セール接頭辞の語は作品プレースホルダとして検出されない(=作品リンク置換の対象外)。括弧ごと消費する
  //   パターンでも、語そのものが一致しないので括弧を含めて丸ごと不変(食い違い置換の事故を防ぐ)。
  assert.strictEqual(hasWorkLinkPlaceholder('(セール紹介短縮用URL)'), false);
  assert.strictEqual(fillWorkLinkPlaceholder('(セール紹介短縮用URL)', 'https://yoz2.com/WORK', ''),
    '(セール紹介短縮用URL)');
});
test('P-20: ★セール置換は作品語を食わない(「商品紹介短縮URL」をセールにしない)', function () {
  assert.strictEqual(hasSaleLinkPlaceholder('(商品紹介短縮URL)'), false);
});
test('P-21: 作品・セール両方を含む本文=それぞれ正しい側だけ置換・括弧ごと裸URL(Chami報告の再現)', function () {
  var t = '続きが気になっちゃう一冊、みつけた📚\nしかも今なら50%オフ💕\n\n(商品紹介短縮URL)\n\n(セール紹介短縮用URL)';
  var afterWork = fillWorkLinkPlaceholder(t, 'https://yoz2.com/OZX3F', '');
  var afterBoth = fillSaleLinkPlaceholder(afterWork, 'https://yoz2.com/evTh1');
  assert.strictEqual(afterBoth,
    '続きが気になっちゃう一冊、みつけた📚\nしかも今なら50%オフ💕\n\nhttps://yoz2.com/OZX3F\n\nhttps://yoz2.com/evTh1');
});
test('P-22: 作品リンク未取得ならプレースホルダのまま(表記ゆれ形でも)', function () {
  assert.strictEqual(fillWorkLinkPlaceholder('(商品紹介短縮URL)', '', ''), '(商品紹介短縮URL)');
});
test('P-23: 「作品」接頭辞も許容(括弧ごと裸URL)', function () {
  assert.strictEqual(fillWorkLinkPlaceholder('(作品紹介短縮URL)', 'https://yoz2.com/W', ''), 'https://yoz2.com/W');
});
test('P-24: プレースホルダを含まない通常本文は検出されない', function () {
  assert.strictEqual(hasWorkLinkPlaceholder('続きが気になっちゃう一冊、みつけた📚'), false);
  assert.strictEqual(hasSaleLinkPlaceholder('続きが気になっちゃう一冊、みつけた📚'), false);
});
test('P-25: 括弧なしプレースホルダは従来どおり裸URLへ(後方互換)', function () {
  assert.strictEqual(fillWorkLinkPlaceholder('本文\n商品紹介短縮URL', 'https://yoz2.com/OZX3F', ''),
    '本文\nhttps://yoz2.com/OZX3F');
  assert.strictEqual(fillSaleLinkPlaceholder('セール中短縮リンク', 'https://yoz2.com/evTh1'), 'https://yoz2.com/evTh1');
});
test('P-26: ★セール見出しの直下がセールプレースホルダなら見出しを剥がさない(大幅セール文面が消える不具合)', function () {
  // stripAutoBlocks はセール見出し行(KNOWN_DISCOUNT_LEADS)を古い完成形として剥がすが、直下が
  //   生きたセールプレースホルダの時は現行テンプレ=残す。剥がすとChami報告「大幅セールの文面が消えてる」になる。
  var t = '続きが気になっちゃう一冊、みつけた📚\n\n(商品紹介短縮URL)\n\n🏮 大幅割引セール中の同人祭ページ 🏮\n(セール紹介短縮用URL)';
  assert.strictEqual(stripAutoBlocks(t), t, 'セール見出し＋直下プレースホルダは丸ごと残る');
});

// ────────────────────────────────────────────────────────────
// PR-* resolvePromoTemplate(販促テンプレ解決・Chami依頼2026-08-03①②)
//   %:/¥: 候補行の取捨・接頭辞剥がし・N%/N円/¥N 置換・%表示時の¥N行削除
// ────────────────────────────────────────────────────────────
var PROMO_BODY = '続きが気になっちゃう一冊、みつけた📚\n%:しかも今ならN%オフ💕\n¥:しかも今ならN円💕\n\n(商品紹介短縮URL)';
test('PR-1: %モード→%:行を採用(接頭辞除去)しN%を割引率へ・¥:行は行ごと削除', function () {
  assert.strictEqual(resolvePromoTemplate(PROMO_BODY, { type: 'discount', pct: 35, price: 10 }),
    '続きが気になっちゃう一冊、みつけた📚\nしかも今なら35%オフ💕\n\n(商品紹介短縮URL)');
});
test('PR-2: ¥モード→¥:行を採用しN円を実価格へ・%:行は行ごと削除', function () {
  assert.strictEqual(resolvePromoTemplate(PROMO_BODY, { type: 'price', pct: 35, price: 10 }),
    '続きが気になっちゃう一冊、みつけた📚\nしかも今なら10円💕\n\n(商品紹介短縮URL)');
});
test('PR-3: 値なしは N を据え置く(誤った数字を貼らない)', function () {
  assert.strictEqual(resolvePromoTemplate(PROMO_BODY, { type: 'discount', pct: null, price: null }),
    '続きが気になっちゃう一冊、みつけた📚\nしかも今ならN%オフ💕\n\n(商品紹介短縮URL)');
});
test('PR-4: YouTube説明欄 %モード→接頭辞なしの¥N価格行を行ごと削除(②)', function () {
  assert.strictEqual(resolvePromoTemplate('冒頭\n期間限定今だけ¥N作品をご案内！\n#PR', { type: 'discount', pct: 35, price: 10 }),
    '冒頭\n#PR');
});
test('PR-5: YouTube説明欄 ¥モード→¥Nを実価格へ(行は残す)', function () {
  assert.strictEqual(resolvePromoTemplate('冒頭\n期間限定今だけ¥N作品をご案内！\n#PR', { type: 'price', pct: 35, price: 3000 }),
    '冒頭\n期間限定今だけ¥3,000作品をご案内！\n#PR');
});
test('PR-6: 冪等(解決済みを再投入しても変わらない)', function () {
  var once = resolvePromoTemplate(PROMO_BODY, { type: 'price', pct: 35, price: 10 });
  assert.strictEqual(resolvePromoTemplate(once, { type: 'price', pct: 35, price: 10 }), once);
});
// PR-7 = 「X用テキスト欄が丸ごと空(0/280)」の再発封じ(v=586/593/603で3回直した同じ穴)。
//   候補行(%:/¥:)は片方が必ず削除されるので、素の行が1つでも在れば結果は非空でなければならない。
//   販促テンプレ解決が本文を空へ落とす経路をここで恒久的に禁止する(=空欄化はもうテストが落ちる)。
test('PR-7: 非販促行を含む本文は%/¥どちらでも空にならない(X欄空欄化の不変条件)', function () {
  var body = '続きが気になっちゃう一冊、みつけた📚\n%:しかも今ならN%オフ💕\n¥:しかも今ならN円💕';
  ['price', 'discount'].forEach(function (t) {
    var r = resolvePromoTemplate(body, { type: t, pct: 35, price: 10 });
    assert.ok(r.trim().length > 0, t + 'モードで本文が空になった');
    assert.ok(r.indexOf('続きが気になっちゃう一冊') >= 0, t + 'モードで素の行が消えた');
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
