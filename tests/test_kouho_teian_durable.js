'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const read = function (name) { return fs.readFileSync(path.join(root, name), 'utf8'); };

const html = read('KouhoTeian.html');
const cand = read('js/candidates.js');
const bump = read('scripts/bump.mjs');

// インラインJSを実際に構文解析する。静的文字列検査だけで緑になる門にしない。
Array.from(html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi), function (m) { return m[1]; })
  .filter(function (src) { return src.trim(); })
  .forEach(function (src, idx) {
    assert.doesNotThrow(function () { new Function(src); }, 'inline script syntax #' + idx);
  });

// 投稿提案も単一の版管理へ入り、ページ内資産は全て同じ版を指す。
assert.ok(/const TARGETS = \[[^\]]*"KouhoTeian\.html"/.test(bump), 'KouhoTeian.html must be a bump target');
const versions = Array.from(html.matchAll(/\?v=(\d+)/g), function (m) { return Number(m[1]); });
assert.ok(versions.length >= 3, 'proposal page must version its own assets');
assert.strictEqual(new Set(versions).size, 1, 'proposal page asset versions must be identical');
assert.ok(html.includes('id="buildBadge"'));
assert.ok(html.includes("probe.searchParams.set('_go5_build_check'"));
assert.ok(html.includes("fetch(probe.toString(),{cache:'no-store'})"));
assert.ok(html.includes('location.replace(next.toString())'));
assert.ok(cand.includes("return 'KouhoTeian.html' + (v ? ('?v=' + v) : '')"), 'navigation must carry the active build version');

// 周期同期を読み込まず、必要な設定読取と画像manifestの1回pullだけを内製する。
assert.ok(!/<script[^>]+src=["']core\/sync\.js/i.test(html), 'proposal page must not load core/sync.js');
assert.ok(html.includes('<script src="core/image-cdn.js?v='));
assert.ok(html.indexOf('root.Go5Sync = { getConfig:function()') < html.indexOf('core/image-cdn.js?v='));
assert.ok(html.includes("fetch(c.url+'/api/pull'"));
assert.ok(html.includes('remoteManifestFromPull_'));
assert.ok(html.includes("Go5ImageCdn.acceptRaw(JSON.stringify(merged),'teian-pull')"));
assert.ok(html.includes("source:'manifest'"));
const loadRefBody = html.slice(html.indexOf('function loadRefMap_(){'), html.indexOf('// ---- 旧go5refマーカー'));
assert.ok(loadRefBody.indexOf('applyManifestToRef_(map)') < loadRefBody.indexOf("Go5Idb.entriesByPrefixes(['ref:'])"),
  'manifest URLs must be applied before the IndexedDB scan starts');
assert.ok(loadRefBody.includes('return Promise.resolve(map)'), 'manifest map must return without waiting for IndexedDB');

// named go5refは復旧線として失敗理由を分け、マーカーを消さず再試行する。
['config_missing', 'crypto_unavailable', 'r2_missing', 'http_error', 'timeout', 'network', 'decode'].forEach(function (reason) {
  assert.ok(html.includes(reason), 'missing go5ref diagnostic: ' + reason);
});
assert.ok(html.includes('scheduleR2Retry_'));
assert.ok(html.includes('var delays=[3000,10000,30000,60000]'));

// 除外判定は両ページで SHA -> slot -> 旧hash の3段を持ち、IDBの古い値による復活を防ぐ。
['@sha256:', '@slot:', 'cand_img_marks_at'].forEach(function (token) {
  assert.ok(html.includes(token), 'proposal missing mark identity: ' + token);
  assert.ok(cand.includes(token), 'candidate page missing mark identity: ' + token);
});
assert.ok(cand.includes('{ __v: 2, at: at, map: map }'));
assert.ok(cand.includes('remapSlotMarksForImages_'));

// 投稿提案へ出すのは、未使用・未除外の動画生成用画像が1枚以上ある作品だけ。
// 未加工一覧(rawImgs/rawKeys)は捨てず、提案画面の3択から通常へ戻す経路も保つ。
const renderBody = html.slice(html.indexOf('function render(){'), html.indexOf('// グループ切替'));
assert.ok(renderBody.includes('if(hasUsableRef_(c.cid)) ready.push(c)'), 'proposal visibility must require a usable image');
assert.ok(renderBody.includes("if(!hasUsableRef_(cid)) return"), 'library merge must require a usable image');
assert.ok(html.includes('rawImgs:rawImgs') && html.includes('rawKeys:rawKeys'), 'proposal must preserve the unfiltered image list');
assert.ok(html.includes('slots:f.slots'), 'visible image must retain its original slot identity');
assert.ok(html.includes('openRefMarkModal_'));
['value=""', 'value="used"', 'value="excluded"'].forEach(function (value) {
  assert.ok(html.includes(value), 'proposal image modal missing radio ' + value);
});
assert.ok(html.includes("LS.setItem(K_IMGMARKS,JSON.stringify(map))"), 'proposal mark must update the candidate-page LS source');
assert.ok(html.includes("Go5Idb.set('meta:imgmarks',{__v:2,at:at,map:map})"), 'proposal mark must update the durable IDB mirror');
assert.ok(html.includes('idb.at>nowAt'), 'a late old IDB read must not roll back a radio change');
assert.ok(cand.includes("window.addEventListener('storage'"), 'an open candidate page must follow proposal mark changes');

// 当日top20外の投稿画像あり作品もPC側visionを通したready_libraryから④コメントを合流する。
assert.ok(html.includes('var READYLIB = {}'));
assert.ok(html.includes('(DATA.ready_library||[]).forEach'));
assert.ok(html.includes('comments:(remote.comments||[])'));
assert.ok(html.includes('(j.ready_library&&j.ready_library.length)'));

console.log('OK: KouhoTeian cache, image manifest, go5ref recovery and image marks are guarded');
