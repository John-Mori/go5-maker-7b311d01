// tests/test_categories_ai.js — 候補→作成のカテゴリ自動チェック(特にAI)を「本物の判定口」で検証する。
//
//   背景(2026-08-13・kaizen実依頼/Chami Go): AIカテゴリのチェックが直しても再発した(同夜5回)。真因は
//     「AIか?」の判定式が候補バッジ/候補→作成/作品URLフェッチ/テストの4箇所にコピーされ食い違ったこと。
//     旧テストは式を「再実装」して検証していた=本物が壊れてもテストは緑=「入れたが効かない」の温床だった。
//   対策: 判定を core/movie-attrs-core.js(Go5MovieAttrsCore)へ集約。このテストは本物の resolve を直接叩き、
//     さらに「候補→作成 経路」と「動画作成タブの作品URLフェッチ経路」が同一判定に収束することを固定する。
//     実行: node tests/test_categories_ai.js
'use strict';
var fs = require('fs');
var path = require('path');
var Cats = require('../core/categories.js');
var Core = require('../core/movie-attrs-core.js'); // ★本物の判定口(runtime と同一)

var fails = 0;
function check(name, cond) { if (cond) { console.log('  ok  ' + name); } else { console.log('  NG  ' + name); fails++; } }

// 候補→作成(bluesky.js applyGenres が組む input)を本物の resolve に通す。
function jump(genres, title, floor, service, ai) {
  return Core.resolve({ genres: genres, title: title, floor: floor, service: service, ai: ai }, Cats);
}
// 動画作成タブの作品URLフェッチ(bluesky.js autoApplyAttrsFromInfo_ が組む input)を本物の resolve に通す。
function urlFetch(info) {
  return Core.resolve({ genres: info.genres || [], floor: info.floor, service: info.service, title: info.title, ai: info.ai }, Cats);
}

// ── 1) 判定ロジック(本物の resolve) ───────────────────────────────────────────
// floor が「コミック・AI」= genre にAI無し。フロア未取得でも即チェックが本来のゴール。
check('floor コミック・AI → ai', jump(['ラブコメ', '巨乳'], 'ある作品', 'コミック・AI', '同人').ai === true);
// floor の表記ゆれ(半角/全角カッコ)
check('floor コミック(AI) → ai', jump([], '作品', 'コミック(AI)', '').ai === true);
check('floor コミック（AI） → ai', jump([], '作品', 'コミック（AI）', '').ai === true);
// genre に「AI生成」= floor 未取得(空)でも genre だけで拾う
check('genre AI生成 / floor空 → ai', jump(['AI生成', '巨乳'], '作品', '', '').ai === true);
// 全角ＡＩ(表記ゆれ)も拾う=候補バッジと同一規則へ収束(以前チェックボックス側は取りこぼしていた)
check('全角 floor コミック・ＡＩ → ai', jump([], '作品', 'コミック・ＡＩ', '').ai === true);
// worker明示フラグ ai=true(genre/floor に AI が載らない同人AI)
check('明示フラグ ai=true → ai', jump(['巨乳', '制服'], '作品', '同人', '同人', true).ai === true);
// AIでない作品を誤検出しない
check('非AI(コミック/ラブコメ) → aiでない', !jump(['ラブコメ'], '作品', 'コミック', '同人').ai);
// 英題の "ai"(rainy/maid 等)を誤検出しない(title は判定対象外)
check('英題 rainy maid → aiでない', !jump(['純愛'], 'rainy day maid', 'コミック', '同人').ai);
// 他カテゴリも同時に拾える(異世界＝ジャンルタグ)
check('異世界タグ同居 → isekai も立つ', jump(['異世界', 'AI生成'], '作品', 'コミック・AI', '').isekai === true);
// 作品名の「総集編」も拾う(タグに載らない作品対策)
check('作品名 総集編 → soshu', jump([], '巨乳総集編パック', 'コミック', '').soshu === true);

// ── 2) 2経路の収束(kaizen受け入れ条件の核) ───────────────────────────────────
//   同じ作品を「候補→作成」と「作品URLフェッチ」で判定しても、AI判定が一致することを固定する。
//   ＝片方でチェックが空振りする食い違い(再発の真因)を機構で封じる。
var floorOnlyAi = { genres: ['ラブコメ', '巨乳'], title: 'ある作品', floor: 'コミック・AI', service: '同人' };
check('2経路一致(floor only AI)', jump(floorOnlyAi.genres, floorOnlyAi.title, floorOnlyAi.floor, floorOnlyAi.service).ai
  === urlFetch(floorOnlyAi).ai);
var dojinAi = { genres: ['巨乳', '制服'], title: '作品', floor: '同人', service: '同人', ai: true };
check('2経路一致(明示フラグ 同人AI)', jump(dojinAi.genres, dojinAi.title, dojinAi.floor, dojinAi.service, dojinAi.ai).ai
  === urlFetch(dojinAi).ai);

// ── 3) 配線ガード(bluesky.js の両経路が本物の core を通っているか) ─────────────────
//   判定式のインライン再実装が再び忍び込むのを防ぐ。両関数が applyAttrsInput_(=resolve集約)を通ること、
//   かつ古い分岐(setMovieAttrsFromTexts_ の直呼び)が残っていないことを固定する。
var bsky = fs.readFileSync(path.join(__dirname, '..', 'bluesky.js'), 'utf8');
check('bluesky.js が Go5MovieAttrsCore を参照', bsky.indexOf('Go5MovieAttrsCore') >= 0);
check('applyGenres が applyAttrsInput_ を通る', /applyGenres:\s*function[\s\S]{0,220}applyAttrsInput_\(/.test(bsky));
check('autoApplyAttrsFromInfo_ が applyAttrsInput_ を通る', /function autoApplyAttrsFromInfo_[\s\S]{0,400}applyAttrsInput_\(/.test(bsky));
check('旧 setMovieAttrsFromTexts_ の直呼びが無い', bsky.indexOf('setMovieAttrsFromTexts_(') < 0);

if (fails) { console.log('\nFAIL: ' + fails + '件'); process.exit(1); }
console.log('\nALL PASS (' + '17 checks' + ')');
