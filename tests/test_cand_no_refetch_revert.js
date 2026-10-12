/**
 * tests/test_cand_no_refetch_revert.js
 * 1回取得できた候補が、同期の古い配列で「⏳ 取得中です…」へ戻らないこと(Chami 2026-10-13 msg 1559268529344217088)。
 * core/sync.js の本物(unionByField / applyFastCandidateMerged_)を、localStorageだけ偽物にして実行する。
 * 実行: node tests/test_cand_no_refetch_revert.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

class MemoryStorage {
  constructor() { this.map = new Map(); }
  get length() { return this.map.size; }
  key(i) { return Array.from(this.map.keys())[i] || null; }
  getItem(k) { return this.map.has(String(k)) ? this.map.get(String(k)) : null; }
  setItem(k, v) { this.map.set(String(k), String(v)); }
  removeItem(k) { this.map.delete(String(k)); }
}
global.localStorage = new MemoryStorage();
global.window = { localStorage: global.localStorage, setTimeout, clearTimeout }; // sync.jsのrootをこの偽物にする
require('../core/sync.js');
const S = global.window.Go5Sync._test;
const localStorage = global.localStorage;

let fails = 0;
function eq(a, b, m) { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? '  ok   ' : '  FAIL ') + m + (ok ? '' : ' got=' + JSON.stringify(a) + ' want=' + JSON.stringify(b))); if (!ok) fails++; }

const PH = { cid: 'd_1', url: 'u', title: '(タイトル未取得)', addedAt: 1, _fetching: true };
const FULL = { cid: 'd_1', url: 'u', title: 'これが娘の最後の姿', thumb: 'https://t/1.jpg', price: 880, addedAt: 1 };

console.log('--- 題名のunion ---');
let m = JSON.parse(S.unionByField(JSON.stringify([FULL]), JSON.stringify([PH]), 'cid'))[0];
eq(m.title, FULL.title, '取得中プレースホルダがnewerでも、本物の題名を上書きしない');
eq(m.thumb, FULL.thumb, 'サムネも残る');
eq('_fetching' in m, false, '本物の題名が揃ったら取得中フラグは外れる');
m = JSON.parse(S.unionByField(JSON.stringify([PH]), JSON.stringify([FULL]), 'cid'))[0];
eq([m.title, '_fetching' in m], [FULL.title, false], '逆向き(本物がnewer)も本物');
m = JSON.parse(S.unionByField(JSON.stringify([PH]), JSON.stringify([PH]), 'cid'))[0];
eq([m.title, m._fetching], ['(タイトル未取得)', true], '両方プレースホルダなら取得中のまま(本当に取得中)');

console.log('--- 高速レールの書き戻し ---');
const K = 'cand_items';
// 同期開始時: LSはプレースホルダ。pull中にput()が本物を書いた。雲から届いたmergedは古いプレースホルダ。
const startLs = { [K]: JSON.stringify([PH]) };
localStorage.setItem(K, JSON.stringify([FULL]));
S.applyFastCandidateMerged_({ [K]: JSON.stringify([PH]) }, startLs);
let after = JSON.parse(localStorage.getItem(K))[0];
eq(after.title, FULL.title, 'pull中に取得完了した候補を、古い配列で取得中へ巻き戻さない');
eq(after.price, 880, '価格も残る');

// pull中にLSが変わっていなければ雲の内容をそのまま採る(従来どおり)
const REMOTE = { cid: 'd_1', url: 'u', title: '雲の新しい題名', addedAt: 1 };
localStorage.setItem(K, JSON.stringify([FULL]));
S.applyFastCandidateMerged_({ [K]: JSON.stringify([REMOTE]) }, { [K]: JSON.stringify([FULL]) });
eq(JSON.parse(localStorage.getItem(K))[0].title, '雲の新しい題名', 'LS未変更なら雲から届いた更新を採る');

console.log('--- 配線 ---');
const sy = fs.readFileSync(path.join(__dirname, '..', 'core/sync.js'), 'utf8');
eq(/applyFastCandidateMerged_\(merged\.mergedLs, startLs\)/.test(sy), true, '高速レールは開始時のLSを渡す');
const cd = fs.readFileSync(path.join(__dirname, '..', 'js/candidates.js'), 'utf8').replace(/\r\n/g, '\n');
eq(/var keepInfo = !info && it\.title && it\.title !== '\(タイトル未取得\)';\n\s*if \(!keepInfo\) \{/.test(cd), true, '取得失敗でも本物の題名がある候補は中身を消さない');
eq(/if \(it\._fetching\) \{ delete it\._fetching; changed = true; \}/.test(cd), true, '自動再取得で埋まったら取得中フラグを外す');
if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
console.log('all ok');
