/**
 * core/movie-attrs-core.js — 動画カテゴリ自動チェックの「判定」の唯一の正本。(Go5MovieAttrsCore)
 *
 * 【解く問題】AIカテゴリの自動チェックが入らない不具合が、直しても別画面で再発した(2026-08-12 同夜5回)。
 *   真因= 同じ「AIか?」の判定式が 4 箇所にコピーされ、経路ごとに少しずつ食い違っていた：
 *     ①候補バッジ candidates.js isAiWork_(genres/floor/ai・全角ＡＩも半角化)
 *     ②候補→作成 bluesky.js applyGenres の aiHint(!!ai || genre/AI/ || floor/AI/・全角化なし)
 *     ③作品URLフェッチ bluesky.js autoApplyAttrsFromInfo_ の aiHint(!!ai || genre/AI/ のみ・floor/AI/なし)
 *     ④テスト tests/test_categories_ai.js が式を「再実装」(＝本物を検証していない=入れたが効かないの温床)
 *   ②③が違う=候補から飛んだ時とURL入力時でAI判定が別結果になり、片方でチェックが空振りしていた。
 *
 * 【対策】判定を本モジュール 1 本へ集約する。候補→作成 も 作品URLフェッチ も 候補バッジ も、必ず
 *   ここ(aiHint / resolve)を通す。テストも本物のここを直接叩く。＝2経路が式を持ち合って食い違う再発を
 *   機構で封じる(kaizen 実依頼 2026-08-13・Chami Go)。
 *
 * 依存: core/categories.js(Go5Cats)。matchText でキーワード部分一致、AI だけは開示文の少なさゆえ
 *   救済ヒント(aiHint)で補う。ブラウザ(window)と Node(module.exports)の両対応。
 */
(function (root) {
  'use strict';

  // 全角英字→半角(ＡＩ→AI)。FANZA のタグ/フロア表記ゆれで /AI/ が素通りするのを防ぐ。
  //   ★候補バッジ(candidates.js)と同一規則。以前は候補バッジだけが全角化しており、チェックボックス側は
  //   全角ＡＩを取りこぼしていた(バッジは AI・でもチェックは入らない、の食い違い)。ここで一本化する。
  function toHalfWidth(s) {
    return String(s == null ? '' : s).replace(/[Ａ-Ｚａ-ｚ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); });
  }

  // ジャンル配列に緩く「AI」を含むか(全角ＡＩも半角化して判定)。
  function looseAiFromGenres(genres) {
    return (genres || []).some(function (g) { return /AI/i.test(toHalfWidth(g)); });
  }

  // 「この作品は AI 作品か?」の唯一の判定。優先度:
  //   1) worker が FANZA 必須開示文「AI生成」から立てた明示フラグ ai(genre/floor に AI が載らない同人AI用)
  //   2) genre タグに緩く AI(AI生成/AIイラスト 等)
  //   3) floor 名に AI(「コミック・AI」等・タグに載らずフロア名でしか示されない作品)
  //   ★title は英単語 "ai"(rainy/maid)を誤検出するため判定対象にしない。
  function aiHint(input) {
    input = input || {};
    return !!input.ai || looseAiFromGenres(input.genres) || /AI/i.test(toHalfWidth(input.floor));
  }

  // カテゴリ判定に流す文字列群(ジャンル ∪ 作品名 ∪ フロア名 ∪ サービス名)。空文字は落とす。
  //   ★作品名も混ぜる=総集編は「総集編」タグが無く作品名にだけ載る作品が多いため(Chami依頼2026-08-06)。
  function composeTexts(input) {
    input = input || {};
    var genres = input.genres || [];
    return genres
      .concat(input.title ? [input.title] : [])
      .concat(input.floor ? [input.floor] : [])
      .concat(input.service ? [input.service] : []);
  }

  // 自動チェックの確定結果 {key:true, ...} を返す唯一の判定口。cats = Go5Cats。
  //   matchText でキーワード部分一致を取り、AI だけは救済ヒント(aiHint)で補って hits.ai を立てる。
  function resolve(input, cats) {
    input = input || {};
    var hits = (cats && cats.matchText) ? (cats.matchText(composeTexts(input)) || {}) : {};
    if (aiHint(input) && cats && cats.byKey && cats.byKey('ai')) hits.ai = true;
    return hits;
  }

  var API = {
    toHalfWidth: toHalfWidth,
    looseAiFromGenres: looseAiFromGenres,
    aiHint: aiHint,
    composeTexts: composeTexts,
    resolve: resolve
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  if (root) root.Go5MovieAttrsCore = API;
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
