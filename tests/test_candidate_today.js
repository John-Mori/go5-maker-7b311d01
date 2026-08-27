'use strict';
const assert = require('assert');
const Cand = require('../js/candidates.js');
const Sync = require('../core/sync.js')._test;

assert.strictEqual(Cand.candidateTodayDay_(Date.UTC(2026, 7, 27, 14, 59, 59)), '2026-08-27');
assert.strictEqual(Cand.candidateTodayDay_(Date.UTC(2026, 7, 27, 15, 0, 0)), '2026-08-28');
const day = '2026-08-28';
assert.strictEqual(Cand.candidateTodayChecked_({ A: { day, checked: true } }, 'A', day), true);
assert.strictEqual(Cand.candidateTodayChecked_({ A: { day: '2026-08-27', checked: true } }, 'A', day), false);
assert.strictEqual(Cand.candidateTodayChecked_({ A: { day, checked: false } }, 'A', day), false);

const pc = JSON.stringify({ A: { day, checked: true, at: 10, item: { cid: 'A', title: 'PC' } }, B: { day, checked: true, at: 30 } });
const phone = JSON.stringify({ A: { day, checked: false, at: 20 }, C: { day, checked: true, at: 40, item: { cid: 'C' } } });
const merged = JSON.parse(Sync.mergeCandToday_(pc, phone));
assert.strictEqual(merged.A.checked, false, '同じ作品は新しい解除を採る');
assert.strictEqual(merged.B.checked, true, 'PCだけの作品を保持する');
assert.strictEqual(merged.C.checked, true, 'スマホだけの作品を保持する');
assert.strictEqual(Sync.isSyncLsKey('cand_today_v1'), true, '今日印は端末間同期する');
console.log('PASS: candidate 今日印の日付境界 / cid単位同期');