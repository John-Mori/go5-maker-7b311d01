const assert = require('assert');
const R = require('../core/regen-identity.js');

const items = [
  { id: 'stk-old', account: 'acc2', videoId: 'acc2-20260729-old', title: '社内一お堅い先輩の週末は？', workUrl: 'https://example.test/?cid=d_695975', ts: 1 },
  { id: 'stk-new', account: 'acc2', videoId: 'acc2-20260729-new', title: '社内一お堅い先輩の週末は？', srcMark: { cid: 'd_695975' }, ts: 2 },
  { id: 'stk-wrong-account', account: 'acc1', videoId: 'rygCPI3Blyc', title: '社内一お堅い先輩の週末は？', ts: 3 },
];

let got = R.resolve({ account: 'acc2', videoId: 'rygCPI3Blyc', title: '社内一お堅い先輩の週末は？', cid: 'd_695975' }, items);
assert.strictEqual(got.meta.id, 'stk-new', '旧YouTube IDが外れても、同一ch＋CIDから最新の内部IDを回収する');
assert.strictEqual(got.matchBy, 'cid');

got = R.resolve({ account: 'acc2', videoId: 'unknown0000', title: '社内一お堅い先輩の週末は?' }, items);
assert.strictEqual(got.meta.id, 'stk-new', '全角/半角の疑問符差をNFKC化して題名から回収する');
assert.strictEqual(got.matchBy, 'account_title');

got = R.resolve({ account: 'acc1', videoId: 'rygCPI3Blyc', title: '社内一お堅い先輩の週末は？' }, items);
assert.strictEqual(got.meta.id, 'stk-wrong-account', 'videoId完全一致は同一チャンネル内だけで採る');

got = R.resolve({ account: 'acc2', videoId: 'rygCPI3Blyc', title: '存在しない題名' }, [{ id: 'other', account: 'acc1', title: '存在しない題名' }]);
assert.strictEqual(got.meta, null, '別チャンネルへは倒さない');

assert.strictEqual(R.isLegacyYouTubeId('rygCPI3Blyc'), true);
assert.strictEqual(R.isLegacyYouTubeId('acc2-20260729-new'), false);

console.log('All regen identity tests passed.');
