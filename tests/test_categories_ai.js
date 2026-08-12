// tests/test_categories_ai.js — 候補→作成のカテゴリ自動チェック(特にAI)の純粋ロジック検証。
//   AIは FANZA の genre タグに載らず「コミック・AI」等の floor 名でしか示されない作品がある。
//   候補が floor を保持し、applyGenres が floor も判定に混ぜれば、FANZA再取得を待たず即チェックできる——
//   ここではその判定ロジック(bluesky.js applyGenres と同一式)を Go5Cats.matchText に通して確かめる。
//   実行: node tests/test_categories_ai.js
var Cats = require('../core/categories.js');

// bluesky.js の setMovieAttrsFromTexts_ / applyGenres と同一の合成式を再現する。
function looseAiFromGenres_(genres) { return (genres || []).some(function (g) { return /AI/i.test(String(g || '')); }); }
function attrsForJump(genres, title, floor, service) {
  var texts = (genres || []).concat(title ? [title] : []).concat(floor ? [floor] : []).concat(service ? [service] : []);
  var hits = Cats.matchText(texts) || {};
  if ((looseAiFromGenres_(genres) || /AI/i.test(String(floor || ''))) && Cats.byKey('ai')) hits.ai = true;
  return hits;
}

var fails = 0;
function check(name, cond) { if (cond) { console.log('  ok  ' + name); } else { console.log('  NG  ' + name); fails++; } }

// 1) floor が「コミック・AI」= genre にAI無し。フロア未取得でも即チェックが本来のゴール。
check('floor コミック・AI → ai', attrsForJump(['ラブコメ', '巨乳'], 'ある作品', 'コミック・AI', '同人').ai === true);
// 2) floor の表記ゆれ(半角/全角カッコ)
check('floor コミック(AI) → ai', attrsForJump([], '作品', 'コミック(AI)', '').ai === true);
check('floor コミック（AI） → ai', attrsForJump([], '作品', 'コミック（AI）', '').ai === true);
// 3) genre に「AI生成」= floor 未取得(空)でも genre だけで拾う(候補バッジと同じ緩い規則)
check('genre AI生成 / floor空 → ai', attrsForJump(['AI生成', '巨乳'], '作品', '', '').ai === true);
// 4) AIでない作品を誤検出しない
check('非AI(コミック/ラブコメ) → aiでない', !attrsForJump(['ラブコメ'], '作品', 'コミック', '同人').ai);
// 5) 英題の "ai"(rainy/maid 等)を誤検出しない(title は aiHint 対象外、matchTextのAIキーワードも特定表記のみ)
check('英題 rainy maid → aiでない', !attrsForJump(['純愛'], 'rainy day maid', 'コミック', '同人').ai);
// 6) 他カテゴリも同時に拾える(異世界＝ジャンルタグ)
check('異世界タグ同居 → isekai も立つ', attrsForJump(['異世界', 'AI生成'], '作品', 'コミック・AI', '').isekai === true);

if (fails) { console.log('\nFAIL: ' + fails + '件'); process.exit(1); }
console.log('\nALL PASS (7 checks)');
