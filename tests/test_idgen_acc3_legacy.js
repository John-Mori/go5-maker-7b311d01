// 癒やし倉庫(acc3)の背骨ID発番と、発番バグ期間の acc1-… 読み替え(Chami msg 1559887734418702349)。
const assert = require('assert');
const IdGen = require('../js/idgen.js');
const d = new Date(2026, 9, 16, 9, 30);
assert.ok(/^acc3-20261016-0930-/.test(IdGen.makeVideoId('acc3', d)), 'acc3 は acc3- で発番');
assert.ok(/^acc2-/.test(IdGen.makeVideoId('acc2', d)));
assert.ok(/^acc1-/.test(IdGen.makeVideoId('xxx', d)), '不明は acc1');
// 旧ID窓(2026-10-10〜15)の acc1-… は acc3
['acc1-20261012-0930-dr40', 'acc1-20261013-0238-hgas', 'acc1-20261014-0628-jues', 'test-acc1-20261015-0000-aaaa', 'acc1-20261010-0000-aaaa']
  .forEach(id => assert.strictEqual(IdGen.accOfId(id), 'acc3', id));
// 窓の外は従来どおり
assert.strictEqual(IdGen.accOfId('acc1-20260901-1200-abcd'), 'acc1');
assert.strictEqual(IdGen.accOfId('acc1-20261016-1200-abcd'), 'acc1');
assert.strictEqual(IdGen.accOfId('acc1-20261009-2359-abcd'), 'acc1');
assert.strictEqual(IdGen.accOfId('acc2-20261012-1200-abcd'), 'acc2');
assert.strictEqual(IdGen.accOfId('acc3-20261016-1200-abcd'), 'acc3');
assert.strictEqual(IdGen.accOfId(''), '');
// GAS 側 chOfPid_ と規則が一致すること
const src = require('fs').readFileSync(require('path').join(__dirname, '../gas/コード.gs'), 'utf8');
const m = src.match(/function chOfPid_\(pid\) \{[\s\S]*?\r?\n\}/);
assert.ok(m, 'chOfPid_ がある');
const chOfPid_ = new Function(m[0] + '; return chOfPid_;')();
['acc1-20261012-0930-dr40', 'acc1-20260901-1200-abcd', 'acc2-20261012-1200-abcd', 'acc3-20261016-1200-abcd', 'test-acc1-20261011-0000-x', '', 'foo']
  .forEach(id => assert.strictEqual(chOfPid_(id), IdGen.accOfId(id), id));
console.log('test_idgen_acc3_legacy: ok');
