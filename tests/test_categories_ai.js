// tests/test_categories_ai.js — 候補→作成のカテゴリ自動チェック(特にAI)の純粋ロジック検証。
//   AIは FANZA の genre タグに載らず「コミック・AI」等の floor 名でしか示されない作品がある。
//   候補が floor を保持し、applyGenres が floor も判定に混ぜれば、FANZA再取得を待たず即チェックできる——
//   ここではその判定ロジック(bluesky.js applyGenres と同一式)を Go5Cats.matchText に通して確かめる。
//   実行: node tests/test_categories_ai.js
var Cats = require('../core/categories.js');

// bluesky.js の setMovieAttrsFromTexts_ / applyGenres と同一の合成式を再現する。
function looseAiFromGenres_(genres) { return (genres || []).some(function (g) { return /AI/i.test(String(g || '')); }); }
function attrsForJump(genres, title, floor, service, ai) {
  var texts = (genres || []).concat(title ? [title] : []).concat(floor ? [floor] : []).concat(service ? [service] : []);
  var hits = Cats.matchText(texts) || {};
  // ★ai(第5引数)=候補/workerが持つ明示フラグ。同人AIは genre にも floor 名にも「AI」が載らない作品があり、
  //   フラグを最優先で見ないとAIカテゴリが空振りする(bluesky.js applyGenres / setMovieAttrsFromTexts_ と同一式)。
  if ((!!ai || looseAiFromGenres_(genres) || /AI/i.test(String(floor || ''))) && Cats.byKey('ai')) hits.ai = true;
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
// 7) ★実測 d_748630 型：genre=巨乳/制服…、floor=同人 でAIの手掛かりゼロ。明示フラグ ai=true でだけ拾える。
//    (workerがページのFANZA開示文「AI生成」から立てるフラグ。これが今回の穴＝カテゴリのAIが空振りしていた真因)
check('明示フラグ ai=true(genre/floorにAI無し) → ai', attrsForJump(['巨乳', '制服', '中出し'], 'メス堕ち母娘', '同人', 'FANZA同人', true).ai === true);
check('明示フラグ無し・genre/floorにAI無し → aiでない(誤検出しない)', !attrsForJump(['巨乳', '制服', '中出し'], 'メス堕ち母娘', '同人', 'FANZA同人', false).ai);

if (fails) { console.log('\nFAIL: ' + fails + '件'); process.exit(1); }
console.log('\nALL PASS (9 checks)');
