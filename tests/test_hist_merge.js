/**
 * tests/test_hist_merge.js — 投稿履歴「シート由来・表示専用マージ」の純粋関数テスト(Node)
 * 実行: node tests/test_hist_merge.js
 */
'use strict';
const assert = require('assert');
const HM = require('../hist-merge-core.js');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

test('H-1: ローカル空 → シート由来の行がすべて表示専用アイテムとして出る', function () {
  var sheet = [
    { postUri: 'at://a/1', title: '作品A', postedAt: '2026-07-20T10:00:00.000Z', shortUrl: 'https://5mgl.com/x1', youtubeUrl: 'https://youtu.be/AAA' },
    { videoId: 'acc1-20260719-0100-abcd', title: '作品B', postedAt: '2026-07-19T01:00:00.000Z', youtubeUrl: 'https://youtu.be/BBB' }
  ];
  var extra = HM.mergeSheetExtras([], sheet);
  assert.strictEqual(extra.length, 2);
  assert.ok(extra.every(function (x) { return x._fromSheet === true; }), '全件に_fromSheetバッジが付く');
  assert.strictEqual(extra[0].ytUrl, 'https://youtu.be/AAA', 'youtubeUrl→ytUrlへ変換');
  assert.strictEqual(extra[1].videoId, 'acc1-20260719-0100-abcd');
});

test('H-2: postUri一致のローカル行があれば重複させない(ローカル優先)', function () {
  var local = [{ postUri: 'at://a/1', title: 'ローカル版' }];
  var sheet = [{ postUri: 'at://a/1', title: 'シート版', postedAt: '2026-07-20T10:00:00.000Z' }];
  var extra = HM.mergeSheetExtras(local, sheet);
  assert.strictEqual(extra.length, 0, 'postUriが一致するので追加しない');
});

test('H-3: postUriが無い行はvideoId一致で重複排除', function () {
  var local = [{ videoId: 'acc2-20260718-0900-zzzz' }];
  var sheet = [{ videoId: 'acc2-20260718-0900-zzzz', title: '重複するはず' }, { videoId: 'acc2-new-0001', title: '新規' }];
  var extra = HM.mergeSheetExtras(local, sheet);
  assert.strictEqual(extra.length, 1);
  assert.strictEqual(extra[0].videoId, 'acc2-new-0001');
});

test('H-4: postUriもvideoIdも無いシート行は安全側でスキップ(重複判定不能)', function () {
  var extra = HM.mergeSheetExtras([], [{ title: '識別子なし', shortUrl: 'https://5mgl.com/x' }]);
  assert.strictEqual(extra.length, 0);
});

test('H-5: シート内自己重複(同一postUriが2行)も1件に畳む', function () {
  var sheet = [
    { postUri: 'at://a/1', title: '1回目' },
    { postUri: 'at://a/1', title: '2回目(重複)' }
  ];
  var extra = HM.mergeSheetExtras([], sheet);
  assert.strictEqual(extra.length, 1);
});

test('H-6: null/undefined/不正入力でも例外を投げず空配列', function () {
  assert.deepStrictEqual(HM.mergeSheetExtras(null, null), []);
  assert.deepStrictEqual(HM.mergeSheetExtras(undefined, undefined), []);
  assert.deepStrictEqual(HM.mergeSheetExtras([], [null, undefined, {}]), []);
});

test('H-7: シートの作品cidを表示用の作品URLへ復元する', function () {
  var item = HM._toDisplayItem({ cid: 'd_test001' });
  assert.strictEqual(item.cid, 'd_test001');
  assert.strictEqual(item.workUrl, 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_test001/');
  assert.strictEqual(HM._toDisplayItem({ cid: '12345' }).workUrl, 'https://book.dmm.com/product/12345/');
});

test('H-8: 商品URLとアフィリエイトURLから作品cidを抽出する', function () {
  assert.strictEqual(HM.workCidFromUrl('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_test001/'), 'd_test001');
  assert.strictEqual(HM.workCidFromUrl('https://book.dmm.com/product/12345/'), '12345');
  var inner = encodeURIComponent('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_test002/');
  assert.strictEqual(HM.workCidFromUrl('https://al.fanza.co.jp/?lurl=' + inner), 'd_test002');
});

test('H-9: history再読込は同一videoIdかつ編集値の反映後だけ成功と判定する', function () {
  var rows = [{ videoId: 'acc1-1', cid: 'd_old', youtubeUrl: '', workState: '旧作' }];
  var expected = { videoId: 'acc1-1', workUrl: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_new/', workState: '旧作' };
  assert.strictEqual(HM.historyHasEdit(rows, expected), false, '反映前のcidは失敗');
  rows[0].cid = 'd_new';
  assert.strictEqual(HM.historyHasEdit(rows, expected), true, '反映後のcidは成功');
  assert.strictEqual(HM.historyHasEdit([{ videoId: 'acc2-1', cid: 'd_new', workState: '旧作' }], expected), false, '別行は成功扱いしない');
});

test('H-20: cidを復元できない作品URL(FANZA動画等)は、生の作品URL列の一致で保存確認が成功する', function () {
  var vurl = 'https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=abc123movie/'; // videoaはcid抽出規則の対象外→wantCid空
  assert.strictEqual(HM.workCidFromUrl(vurl), 'abc123movie', 'videoaもcid=は拾える(この例はcid有り)');
  // 本当にcidを取れないケース＝cid=を持たないURL。生URL列の一致だけで成功しなければならない。
  var nocid = 'https://video.dmm.co.jp/av/content/?id=someid'; // cid=無し→wantCid空
  var expected = { videoId: 'acc1-9', workUrl: nocid, workState: '旧作' };
  assert.strictEqual(HM.workCidFromUrl(nocid), '', 'このURLはcidを復元できない');
  assert.strictEqual(HM.historyHasEdit([{ videoId: 'acc1-9', cid: '', workState: '旧作' }], expected), false, '生URL列が空なら失敗');
  assert.strictEqual(HM.historyHasEdit([{ videoId: 'acc1-9', cid: '', workUrl: nocid, workState: '旧作' }], expected), true, '生URL列が一致すれば成功(cid不要)');
});

test('H-21: 現行GAS(作品URL列あり)ではcid一致でも生URL未反映なら成功扱いしない(偽陽性=編集消失の根)', function () {
  // 作品cid列は投稿時からほぼ必ず埋まっている。作品URLを入れ直す編集で、POSTがシートへ届く前でも
  //   cid一致で即trueになると保持patchを早期破棄→編集が一瞬で消える(症状: 保存しても反映されず消失)。
  //   現行GASは作品URL列を常にキー(空でも '')で返すので、rawOkを必須にして偽陽性を封じる。
  var wurl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_x/';
  var expected = { videoId: 'acc1-21', workUrl: wurl, workState: '旧作' };
  // cidは既に一致・作品URL列は空('')=POST未反映 → 成功扱いしてはいけない。
  assert.strictEqual(HM.historyHasEdit([{ videoId: 'acc1-21', cid: 'd_x', workUrl: '', workState: '旧作' }], expected), false, '生URL未反映は失敗(cid一致でも早期成功しない)');
  // POSTが届いて作品URL列も一致 → 成功。
  assert.strictEqual(HM.historyHasEdit([{ videoId: 'acc1-21', cid: 'd_x', workUrl: wurl, workState: '旧作' }], expected), true, '生URL反映後は成功');
});

test('H-10: 履歴単位の使用画像があれば候補画像を混ぜない', function () {
  var got = HM.historyUsedImages(['used-1'], ['candidate-1', 'candidate-2']);
  assert.deepStrictEqual(got, ['used-1']);
});

test('H-11: 旧履歴の互換表示でも候補画像は先頭1枚だけに限定する', function () {
  var got = HM.historyUsedImages([], ['legacy-used', 'unused-candidate']);
  assert.deepStrictEqual(got, ['legacy-used']);
});

test('H-12: 使用画像を明示的に空にした履歴では旧候補画像を復活させない', function () {
  assert.deepStrictEqual(HM.historyUsedImages([], ['legacy-candidate'], true), []);
});

test('H-13: 投稿URI・短縮URLが無いシート行も動画IDで一意に識別する', function () {
  assert.strictEqual(HM.historyItemKey({ videoId: 'acc1-20260723-1200-abcd' }), 'v:acc1-20260723-1200-abcd');
});

test('H-14: 履歴キーは投稿URI→短縮URL→動画IDの優先順を守る', function () {
  assert.strictEqual(HM.historyItemKey({ postUri: 'at://post/1', shortUrl: 'https://s/1', videoId: 'vid-1' }), 'u:at://post/1');
  assert.strictEqual(HM.historyItemKey({ shortUrl: 'https://s/1', videoId: 'vid-1' }), 's:https://s/1');
});

test('H-15: シート由来行に投稿当時の価格スナップを復元する(セール)', function () {
  var it = HM._toDisplayItem({ videoId: 'v1', fanzaListPrice: '1100', fanzaPrice: '770', fanzaDiscountPct: '30', fanzaFetchedAt: '2026-07-20T00:00:00Z' });
  assert.deepStrictEqual(it.fanzaSnap, { price: 770, listPrice: 1100, discountPct: 30, at: '2026-07-20T00:00:00Z' });
});

test('H-16: 割引後priceが空欄なら当時価格スナップは付けない', function () {
  var it = HM._toDisplayItem({ videoId: 'v2', fanzaListPrice: '', fanzaPrice: '', fanzaDiscountPct: '', fanzaFetchedAt: '' });
  assert.strictEqual('fanzaSnap' in it, false);
});

test('H-17: 定価のみ(割引なし)の当時価格も復元する', function () {
  var it = HM._toDisplayItem({ videoId: 'v3', fanzaListPrice: '', fanzaPrice: '880', fanzaDiscountPct: '', fanzaFetchedAt: '' });
  assert.deepStrictEqual(it.fanzaSnap, { price: 880, listPrice: null, discountPct: 0, at: '' });
});

test('H-18: シート由来行に作品短縮URL(導線2=ピンク矢印)を復元する', function () {
  var it = HM._toDisplayItem({ videoId: 'v4', workShortUrl: 'https://5mgl.com/AbcdE' });
  assert.strictEqual(it.workShortUrl, 'https://5mgl.com/AbcdE');
  assert.strictEqual(HM._toDisplayItem({ videoId: 'v5' }).workShortUrl, '');
});

test('H-19: 作品URLはシートの生URLを優先し、cid復元できない階層でもリロードで消えない', function () {
  // FANZA動画等の cid は workUrlFromCid で復元できず空になる。シートの生 workUrl があれば必ずそちらを使う。
  var itVideo = HM._toDisplayItem({ videoId: 'v6', cid: 'ssis00123', workUrl: 'https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=ssis00123/' });
  assert.strictEqual(itVideo.workUrl, 'https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=ssis00123/');
  // 生URLが無い旧行は従来どおり cid から復元(同人)。
  assert.strictEqual(HM._toDisplayItem({ videoId: 'v7', cid: 'd_98765' }).workUrl, 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_98765/');
  // 生URLも復元可能cidも無ければ空。
  assert.strictEqual(HM._toDisplayItem({ videoId: 'v8', cid: 'ssis00999' }).workUrl, '');
});

test('H-20: 同じYouTube動画URLならvideoId/postUriが割れてもシート由来を畳む(分裂防止)', function () {
  // ローカルは背骨ID acc1-A・YT動画 yt1。シートは同じ投稿だが背骨IDが acc1-B に割れ postUriも無い。
  //   旧実装は videoId が食い違うため両方表示=「シート由来かそうでないかで分裂」(Chami報告2026-07-29)。
  var local = [{ videoId: 'acc1-A', ytUrl: 'https://youtu.be/yt1', title: '同じ投稿' }];
  var sheet = [{ videoId: 'acc1-B', youtubeUrl: 'https://youtu.be/yt1', title: '同じ投稿' }];
  assert.deepStrictEqual(HM.mergeSheetExtras(local, sheet), [], 'YT動画URLが一致=ローカルにある=シート由来を出さない');
  // 別のYT動画なら従来どおりシート由来として出る。
  var sheet2 = [{ videoId: 'acc1-C', youtubeUrl: 'https://youtu.be/yt2', title: '別投稿' }];
  assert.strictEqual(HM.mergeSheetExtras(local, sheet2).length, 1, '別YT動画は畳まない');
  // 同一シート内に同じYT動画が2行あっても1行に畳む。
  var dup = [{ videoId: 'acc1-D', youtubeUrl: 'https://youtu.be/yt3' }, { videoId: 'acc1-E', youtubeUrl: 'https://youtu.be/yt3' }];
  assert.strictEqual(HM.mergeSheetExtras([], dup).length, 1, 'シート内の同一YT動画重複も畳む');
});

// ★2026-08-12 Chami報告「MacBookに同期したら同じ投稿履歴が2つ」の一因=URL形式違いで畳めていなかった。
//   ローカルとシートで同じ動画でも youtu.be / watch?v= / shorts で文字列が違うと別物扱いになっていた。
//   ytKey_(11文字ID正規化)で揃える(idgen.youtubeId 同一仕様)。
test('H-22: ytKey は youtu.be / watch?v= / shorts / 生ID を同じ11文字IDへ正規化する', function () {
  assert.strictEqual(HM.ytKey('https://youtu.be/AAAAAAAAAAA'), 'AAAAAAAAAAA');
  assert.strictEqual(HM.ytKey('https://www.youtube.com/watch?v=AAAAAAAAAAA'), 'AAAAAAAAAAA');
  assert.strictEqual(HM.ytKey('https://www.youtube.com/shorts/AAAAAAAAAAA'), 'AAAAAAAAAAA');
  assert.strictEqual(HM.ytKey('AAAAAAAAAAA'), 'AAAAAAAAAAA');
  assert.strictEqual(HM.ytKey(''), '');
  assert.strictEqual(HM.ytKey('https://5mgl.com/xyz'), 'https://5mgl.com/xyz', '11文字IDを取れない値は生文字列で従来どおり');
});

test('H-23: URL形式が違っても同じYT動画ならシート由来を畳む(MacBook同期の2重表示・症状①)', function () {
  // ローカルは shorts 形式、シートは youtu.be 形式=同じ動画。旧実装(生URL完全一致)は畳めず2枚並んだ。
  var local = [{ videoId: 'acc1-A', ytUrl: 'https://www.youtube.com/shorts/ZZZZZZZZZZZ', title: '同じ投稿' }];
  var sheet = [{ videoId: 'acc1-B', youtubeUrl: 'https://youtu.be/ZZZZZZZZZZZ', title: '同じ投稿' }];
  assert.deepStrictEqual(HM.mergeSheetExtras(local, sheet), [], 'URL形式違いでも同一動画=1枚に畳む');
  // watch?v= 形式のシート内自己重複も畳む。
  var dup = [
    { videoId: 'acc1-D', youtubeUrl: 'https://www.youtube.com/watch?v=YYYYYYYYYYY' },
    { videoId: 'acc1-E', youtubeUrl: 'https://youtu.be/YYYYYYYYYYY' }
  ];
  assert.strictEqual(HM.mergeSheetExtras([], dup).length, 1, 'シート内の同一動画(URL形式違い)も1枚');
});

test('H-24: ローカル行のytUrlがymapから解決されて渡れば、シート分裂行を吸収する', function () {
  // 実際の呼び出し側(yt-clicks.js fetchSheetExtra_)は、ymap解決済みの ytUrl を載せた複製を渡す。
  //   ここではその複製が渡ってきた前提=ローカル行がYT動画URLを供出できればシート由来を畳める、を固定。
  var localResolved = [{ videoId: 'acc1-X', ytUrl: 'https://youtu.be/WWWWWWWWWWW', title: 'ローカル(ymap解決済)' }];
  var sheet = [{ videoId: 'acc1-Y', youtubeUrl: 'https://www.youtube.com/shorts/WWWWWWWWWWW', title: 'シート分裂行' }];
  assert.strictEqual(HM.mergeSheetExtras(localResolved, sheet).length, 0, 'ymap解決でローカルが吸収=シート由来を出さない');
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
