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
var vm = require('vm');
var Cats = require('../core/categories.js');
var Core = require('../core/movie-attrs-core.js'); // ★本物の判定口(runtime と同一)

var fails = 0, checks = 0;
function check(name, cond) { checks++; if (cond) { console.log('  ok  ' + name); } else { console.log('  NG  ' + name); fails++; } }

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
var bsky = fs.readFileSync(path.join(__dirname, '..', 'js', 'bluesky.js'), 'utf8');
check('bluesky.js が Go5MovieAttrsCore を参照', bsky.indexOf('Go5MovieAttrsCore') >= 0);
check('applyGenres が applyAttrsInput_ を通る', /applyGenres:\s*function[\s\S]{0,420}applyAttrsInput_\(/.test(bsky));
check('autoApplyAttrsFromInfo_ が applyAttrsInput_ を通る', /function autoApplyAttrsFromInfo_[\s\S]{0,900}applyAttrsInput_\(/.test(bsky));
check('旧 setMovieAttrsFromTexts_ の直呼びが無い', bsky.indexOf('setMovieAttrsFromTexts_(') < 0);

// ── 4) 実際の適用コードを実行する(REQ-3babd19ddb / 2026-10-15 タグ消失) ──
// 旧版は正規表現で「AIだけ保護する分岐」の存在を見ていた。他タグの消失/別タブの空振りは検出できない。
// 判定・適用は本物を実行し、DOMとlocalStorageだけを置き換える。実画面の確認はe2e/draft-sync-tagsも担う。
var attrsSource = bsky.slice(bsky.indexOf('  function resolveAttrs_('), bsky.indexOf('  // 新規作成の起点('));
var sharedStorage = {};
function tab() {
  var els = {}, listeners = {};
  Cats.visible().forEach(function (c) { els[Cats.elId(c.key)] = { checked: false }; });
  var sandbox = {
    window: { Go5Cats: Cats, Go5MovieAttrsCore: Core },
    document: { addEventListener: function (name, cb) { listeners[name] = cb; } },
    $: function (id) { return els[id]; }, movieCatList_: function () { return Cats.visible(); },
    save: function (k, v) { sharedStorage[k] = v; }, load: function (k) { return sharedStorage[k] || ''; }
  };
  vm.runInNewContext(attrsSource + '\nglobalThis.applyInfo = autoApplyAttrsFromInfo_;', sandbox);
  return { api: sandbox.window.Go5MovieAttrs, info: sandbox.applyInfo,
    checked: function (key) { return els[Cats.elId(key)].checked; },
    manual: function (key, value) {
      els[Cats.elId(key)].checked = value;
      listeners.change({ target: { checked: value, getAttribute: function () { return key; } } });
    },
    repaint: function () { listeners['go5-categories-rendered'](); }
  };
}
var first = tab(), second = tab();
first.api.applyGenres(['ハーレム'], 'd_tags', '総集編', '', '', true);
first.info({ cid: 'd_tags', title: '部分情報', genres: [], ai: false, partial: true });
check('部分情報でも候補のAI/ハーレム/総集編を保持', first.checked('ai') && first.checked('harem') && first.checked('soshu'));
first.info({ cid: 'd_tags', ai: false, aiChecked: true, aiRule: 1 });
check('旧規則の確定falseでも既知のAIを消さない', first.checked('ai'));
second.info({ cid: 'd_tags', genres: ['ハーレム'] });
check('他タブが同じcidを適用していてもチェックする', second.checked('harem'));
second.info({ cid: 'd_tags', ai: true });
check('遅着AIの肯定情報を取り込む', second.checked('ai'));
second.manual('ai', false);
second.info({ cid: 'd_tags', ai: true });
second.repaint();
check('後着情報/再描画でも手動OFFを保持', !second.checked('ai'));
second.info({ cid: 'd_next', genres: ['異世界'] });
check('別作品には前のタグと手動指定を引き継がない', !second.checked('harem') && !second.checked('ai') && second.checked('isekai'));
second.api.restore({ harem: true, ai: false }, 'd_restore');
second.info({ cid: 'd_restore', ai: true });
check('再作成は保存されたタグ選択を保持', second.checked('harem') && !second.checked('ai'));

// ── 5) 判定規則の版(aiRule): 旧規則の確定falseを「非AI」と見なさない(2026-10-15 Chami報告①) ──
//   旧worker は開示文「AI生成」だけで判定し、開示文を書かないAI作品(実測 d_709161)を ai:false/aiChecked:true で
//   確定していた。その古い false でAIチェックを外す/候補を凍結する穴を版で封じる。
check('今の規則の確定false → 非AI確定', Core.aiVerifiedFalse({ ai: false, aiChecked: true, aiRule: Core.AI_RULE }) === true);
check('旧規則(aiRule無し)の確定false → 未確認', Core.aiVerifiedFalse({ ai: false, aiChecked: true }) === false);
check('旧規則(aiRule=1)の確定false → 未確認', Core.aiVerifiedFalse({ ai: false, aiChecked: true, aiRule: 1 }) === false);
check('未検証 → 未確認', Core.aiVerifiedFalse({ ai: false, aiChecked: false, aiRule: Core.AI_RULE }) === false);
check('AI → 非AI確定ではない', Core.aiVerifiedFalse({ ai: true, aiChecked: true, aiRule: Core.AI_RULE }) === false);
var cands = fs.readFileSync(path.join(__dirname, '..', 'js', 'candidates.js'), 'utf8');
check('候補のAI再確認が旧規則の確定を再確認する', /function aiRecheck_[\s\S]{0,900}aiVerifiedFalse_\(it\)/.test(cands));
// worker の判定規則の版がフロントの版と一致している(ずれると全件が永久に未確認扱い/旧falseを信じる)
var worker = fs.readFileSync(path.join(__dirname, '..', 'fanza-worker', 'src', 'index.js'), 'utf8');
var wm = worker.match(/const AI_RULE = (\d+);/);
check('worker AI_RULE とフロント AI_RULE が一致', !!wm && Number(wm[1]) === Core.AI_RULE);
// worker の本物の aiFromHtml_ を取り出して叩く(実測ページの信号を模した最小HTML)。
var fsrc = worker.match(/function aiFromHtml_\([\s\S]*?\n\}/);
var aiFromHtml = fsrc ? new Function(fsrc[0] + '\nreturn aiFromHtml_;')() : function () { return null; };
var nav = new Array(44 + 1).join('<a href="/x">コミック・AI</a>');
check('worker: 開示文「AI生成」→ AI', aiFromHtml('<p>本作品はAI生成画像を使用</p>', true) === true);
check('worker: 開示文なし+AI棚リンク多数(d_709161型)→ AI', aiFromHtml('<div>' + nav + '</div>', true) === true);
check('worker: exclude_ai=0 → AI', aiFromHtml('<a href="/list/?exclude_ai=0">', true) === true);
check('worker: 通常同人(信号なし)→ 非AI', aiFromHtml('<a>コミック</a><a>CG</a>', true) === false);
check('worker: 一般書籍は構造信号を見ない', aiFromHtml('<div>' + nav + '</div>', false) === false);

if (fails) { console.log('\nFAIL: ' + fails + '件'); process.exit(1); }
console.log('\nALL PASS (' + checks + ' checks)');
