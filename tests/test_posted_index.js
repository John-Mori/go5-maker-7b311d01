/**
 * tests/test_posted_index.js — buildPostedIndex_ の3層合成を検証する(Nodeで実行)。
 * 設計書_投稿済み判定の権威ソース化_2026-07-31 S1。
 *
 * buildPostedIndex_(authorityItems, localItems, account, offMap, fetchedAt, cidFromUrl)
 *   authorityItems: GASシート由来 [{c,w,v,t}] or 空/null(未取得)
 *   localItems: 端末ローカル履歴 [{cid,workCid,workUrl,videoId,account,ts}]
 *   account: 'acc1'|'acc2'
 *   offMap: {cid:ts}(このchでは投稿していない宣言)
 *   fetchedAt: 権威キャッシュの取得時刻(ms)
 *   cidFromUrl: 作品URL→cid の再計算関数(このテストでは URL=cid の恒等で代用)
 */
'use strict';
var assert = require('assert');
var mod = require('../candidates.js');
var buildPostedIndex_ = mod.buildPostedIndex_;

// このテストでは workUrl/w を「そのまま cid」とみなす恒等関数で再計算を代用する(実装は buildAffiliateLink 依存で別途検証済)。
var idUrl = function (u) { return String(u || ''); };

var pass = 0;
function ok(name, cond) { assert.ok(cond, name); pass++; console.log('  PASS ' + name); }

// 1. 権威のみ(localItems空)で、authority の cid が索引に載る。
(function () {
  var auth = [{ c: 'cidA', w: '', v: 'acc1-20260731-1200', t: '2026-07-31' }];
  var map = buildPostedIndex_(auth, [], 'acc1', {}, 1000, idUrl);
  ok('1: 権威のみ→authorityのcidが載る', !!map['cidA']);
  ok('1: 権威アイテムに t/ts が入る(postedTsOf_用)', map['cidA'].t === '2026-07-31' && map['cidA'].ts > 0);
})();

// 2. ローカル無印(account無・videoId prefix無)は、authority が有るとき索引に載らない(fail-closed)。
(function () {
  var auth = [{ c: 'cidA', w: '', v: 'acc1-20260731-1200', t: '2026-07-31' }];
  var local = [{ cid: 'cidNAKED', workUrl: '', videoId: '', account: '', ts: 500 }]; // ts<fetchedAt・所有スタンプ無し
  var map = buildPostedIndex_(auth, local, 'acc1', {}, 1000, idUrl);
  ok('2: 権威ありで無印ローカルは載らない(fail-closed)', !map['cidNAKED']);
  ok('2: 権威のcidは載ったまま', !!map['cidA']);
})();

// 3. authority 無し(未取得)なら、ローカル無印も従来どおり載る(fail-open)。
(function () {
  var local = [{ cid: 'cidNAKED', workUrl: '', videoId: '', account: '', ts: 500 }];
  var mapNull = buildPostedIndex_(null, local, 'acc1', {}, 0, idUrl);
  var mapEmpty = buildPostedIndex_([], local, 'acc1', {}, 0, idUrl);
  ok('3: authority=null→無印ローカルが載る(fail-open)', !!mapNull['cidNAKED']);
  ok('3: authority=[]→無印ローカルが載る(fail-open)', !!mapEmpty['cidNAKED']);
})();

// 4. 直近投稿(local の ts>fetchedAt)は authority に無くても即載る。
(function () {
  var auth = [{ c: 'cidOLD', w: '', v: 'acc1-20260101-0000', t: '2026-01-01' }];
  var local = [{ cid: 'cidNEW', workUrl: '', videoId: '', account: '', ts: 2000 }]; // ts>fetchedAt(1000)
  var map = buildPostedIndex_(auth, local, 'acc1', {}, 1000, idUrl);
  ok('4: 直近投稿(ts>fetchedAt)は権威に無くても載る', !!map['cidNEW']);
})();

// 5. offMap にあるキーは索引から除外。
(function () {
  var auth = [{ c: 'cidA', w: '', v: 'acc1-20260731-1200', t: '2026-07-31' }];
  var local = [{ cid: 'cidNEW', workUrl: '', videoId: '', account: 'acc1', ts: 2000 }]; // account一致=所有陽性
  var map = buildPostedIndex_(auth, local, 'acc1', { cidA: 111, cidNEW: 222 }, 1000, idUrl);
  ok('5: offMapのキー(権威側)は除外', !map['cidA']);
  ok('5: offMapのキー(ローカル側)も除外', !map['cidNEW']);
})();

// 補: 別chの背骨IDを持つローカルは、権威なし(fail-open)でも所有ガードで除外される(既存挙動維持)。
(function () {
  var local = [{ cid: 'cidX', workUrl: '', videoId: 'acc2-20260731-1200', account: '', ts: 500 }];
  var map = buildPostedIndex_(null, local, 'acc1', {}, 0, idUrl);
  ok('補: 別ch背骨IDのローカルは acc1索引から除外(所有ガード)', !map['cidX']);
})();

console.log('\nALL PASS (' + pass + ' checks)');
