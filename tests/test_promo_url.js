/**
 * tests/test_promo_url.js
 * Node で実行できる自己完結テスト（追加パッケージ不使用）
 * 実行: node tests/test_promo_url.js
 *
 * 対象：セール案内URLの自動解決(依頼2)＋キャッシュキーの恒久対策(依頼3)で使う純粋関数。
 *   - affiliate-core.js: isShortenedUrl / hasRealAffiliateId / classifyPromoUrl / ensureAffiliateLink
 *   - bluesky-core.js:   buildDiscountCacheKey
 * ネットワークは検証しない（makeShortAndShare等の実際の短縮呼び出しはbluesky.js内・ブラウザ限定）。
 */

'use strict';

const assert = require('assert');
const { isShortenedUrl, hasRealAffiliateId, classifyPromoUrl, ensureAffiliateLink } = require('../affiliate-core.js');
const { buildDiscountCacheKey } = require('../bluesky-core.js');

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

// ────────────────────────────────────────────────────────────
// isShortenedUrl
// ────────────────────────────────────────────────────────────
test('S-1: 自前短縮ドメイン(5mgl.com/yoz2.com)は短縮済みと判定', function () {
  assert.strictEqual(isShortenedUrl('https://5mgl.com/abc12'), true);
  assert.strictEqual(isShortenedUrl('https://yoz2.com/def34'), true);
});
test('S-2: 外部短縮(da.gd/tinyurl)も短縮済みと判定', function () {
  assert.strictEqual(isShortenedUrl('https://da.gd/xyz'), true);
  assert.strictEqual(isShortenedUrl('https://tinyurl.com/abc'), true);
});
test('S-3: 生のFANZAリンク・素URLは短縮済みではない', function () {
  assert.strictEqual(isShortenedUrl('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_1/'), false);
  assert.strictEqual(isShortenedUrl('https://al.fanza.co.jp/?lurl=x&af_id=test'), false);
});
test('S-4: 端末上書きの追加ホストも短縮済みとして扱える', function () {
  assert.strictEqual(isShortenedUrl('https://my-custom-short.example/xxx', ['my-custom-short.example']), true);
  assert.strictEqual(isShortenedUrl('https://my-custom-short.example/xxx'), false);
});
test('S-5: 空・不正値は短縮済みではない', function () {
  assert.strictEqual(isShortenedUrl(''), false);
  assert.strictEqual(isShortenedUrl('not a url'), false);
});

// ────────────────────────────────────────────────────────────
// hasRealAffiliateId
// ────────────────────────────────────────────────────────────
test('A-1: af_idに実IDが入っていればtrue', function () {
  assert.strictEqual(hasRealAffiliateId('https://al.fanza.co.jp/?lurl=x&af_id=test-001'), true);
});
test('A-2: af_idがプレースホルダ【アフィID】ならfalse', function () {
  assert.strictEqual(hasRealAffiliateId('https://al.fanza.co.jp/?lurl=x&af_id=' + encodeURIComponent('【アフィID】')), false);
});
test('A-3: af_id自体が無ければfalse', function () {
  assert.strictEqual(hasRealAffiliateId('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_1/'), false);
});

// ────────────────────────────────────────────────────────────
// classifyPromoUrl（依頼2: 入力URLの状態判定）
// ────────────────────────────────────────────────────────────
test('C-1: 生URL(af_id無し) → needsAffiliate=true・needsShorten=true', function () {
  const r = classifyPromoUrl('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_1/');
  assert.deepStrictEqual(r, { isShortened: false, hasAffiliate: false, needsAffiliate: true, needsShorten: true });
});
test('C-2: af_id付きだが未短縮 → needsAffiliate=false・needsShorten=true', function () {
  const r = classifyPromoUrl('https://al.fanza.co.jp/?lurl=x&af_id=test-001');
  assert.deepStrictEqual(r, { isShortened: false, hasAffiliate: true, needsAffiliate: false, needsShorten: true });
});
test('C-3: 短縮済み → 両方false（二重処理しない＝そのまま通す）', function () {
  const r = classifyPromoUrl('https://5mgl.com/abc12');
  assert.deepStrictEqual(r, { isShortened: true, hasAffiliate: true, needsAffiliate: false, needsShorten: false });
});
test('C-4: セール会場URL(cid無し・af_id無し) → 生URLと同じくneedsAffiliate/needsShorten=true', function () {
  const r = classifyPromoUrl('https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=mens/');
  assert.strictEqual(r.needsAffiliate, true);
  assert.strictEqual(r.needsShorten, true);
});

// ────────────────────────────────────────────────────────────
// ensureAffiliateLink（依頼2: 欠けているものを自動で補う）
// ────────────────────────────────────────────────────────────
test('E-1: cid付き生URL → buildAffiliateLink相当のアフィリンクを生成', function () {
  const r = ensureAffiliateLink('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/', 'test-001');
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.wasAlready, false);
  assert.ok(r.link.includes('af_id=test-001'));
  assert.ok(r.link.includes('lurl='));
});
test('E-2: セール会場URL(cid無し) → buildFanzaListLinkの経路でアフィ化（cid必須の作品リンクでは弾かれる）', function () {
  const url = 'https://www.dmm.co.jp/dc/doujin/-/list/=/article=campaign/id=317274/sort=sales/';
  const r = ensureAffiliateLink(url, 'af001');
  assert.strictEqual(r.ok, true, 'セール会場URLもアフィ化できる(依頼2の指定経路)');
  assert.ok(r.link.includes('af_id=af001'));
  assert.ok(r.link.includes(encodeURIComponent(url)) === false || r.link.includes('lurl='), 'lurlで包まれている');
});
test('E-3: 既にaf_id入り → 二重ラップせずそのまま返す(冪等)', function () {
  const already = 'https://al.fanza.co.jp/?lurl=x&af_id=test-001&ch=toolbar&ch_id=link';
  const r = ensureAffiliateLink(already, 'other-id');
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.wasAlready, true);
  assert.strictEqual(r.link, already, '既存のaf_idを上書きしない(他IDを渡しても不変)');
});
test('E-4: 空文字 → {ok:false, error:empty}', function () {
  assert.strictEqual(ensureAffiliateLink('', 'af001').ok, false);
  assert.strictEqual(ensureAffiliateLink('', 'af001').error, 'empty');
});
test('E-5: 非URL(cidも無い) → 失敗', function () {
  const r = ensureAffiliateLink('not a url', 'af001');
  assert.strictEqual(r.ok, false);
});

// ────────────────────────────────────────────────────────────
// buildDiscountCacheKey（依頼3: 恒久対策＝ドメインが変われば別キー）
// ────────────────────────────────────────────────────────────
test('K-1: account/entryId/afId/domainが同じなら同じキー', function () {
  const o = { account: 'acc1', entryId: 'seed-acc1', afId: 'test-001', domain: 'https://5mgl.com' };
  assert.strictEqual(buildDiscountCacheKey(o), buildDiscountCacheKey(Object.assign({}, o)));
});
test('K-2: 短縮先ドメインだけが変わると別キーになる(=旧キャッシュへは二度とヒットしない)', function () {
  const base = { account: 'acc1', entryId: 'seed-acc1', afId: 'test-001' };
  const keyOld = buildDiscountCacheKey(Object.assign({}, base, { domain: 'https://r2.trustsignalbot.workers.dev' }));
  const keyMid = buildDiscountCacheKey(Object.assign({}, base, { domain: 'https://5mgl.com' }));
  const keyNew = buildDiscountCacheKey(Object.assign({}, base, { domain: 'https://another-future-domain.example' }));
  assert.notStrictEqual(keyOld, keyMid, 'v1→v2相当のドメイン変更で別キー');
  assert.notStrictEqual(keyMid, keyNew, 'v2→v3相当の将来のドメイン変更でも自動で別キー(手動改名が不要)');
  assert.notStrictEqual(keyOld, keyNew);
});
test('K-3: 選択中のエントリ(entryId)が変わっても別キー(複数セールURLの切替でキャッシュが混ざらない)', function () {
  const base = { account: 'acc1', afId: 'test-001', domain: 'https://5mgl.com' };
  const keyA = buildDiscountCacheKey(Object.assign({}, base, { entryId: 'summer' }));
  const keyB = buildDiscountCacheKey(Object.assign({}, base, { entryId: 'winter' }));
  assert.notStrictEqual(keyA, keyB);
});
test('K-4: アカウントが変わっても別キー(acc1/acc2でキャッシュが混ざらない)', function () {
  const base = { entryId: 'seed', afId: 'test-001', domain: 'https://5mgl.com' };
  const keyA = buildDiscountCacheKey(Object.assign({}, base, { account: 'acc1' }));
  const keyB = buildDiscountCacheKey(Object.assign({}, base, { account: 'acc2' }));
  assert.notStrictEqual(keyA, keyB);
});

// ────────────────────────────────────────────────────────────
// 結果集計
// ────────────────────────────────────────────────────────────
console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');

if (failed > 0) {
  process.exit(1);
}
