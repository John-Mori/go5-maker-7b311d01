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

const taggedLocator = { account: 'acc2', videoId: 'unknown0000', title: '社内一お堅い先輩の週末は？ #1コマ #漫画 #shorts' };
got = R.resolve(taggedLocator, items);
assert.strictEqual(got.meta.id, 'stk-new', '固定リストにない旧YouTubeタグ込み題名でも、タグなしドラフトmetaへ照合する');
assert.strictEqual(got.matchBy, 'account_title');
assert.strictEqual(taggedLocator.title, '社内一お堅い先輩の週末は？ #1コマ #漫画 #shorts', '旧履歴の原文は変更しない');

got = R.resolve({ account: 'acc1', videoId: 'rygCPI3Blyc', title: '社内一お堅い先輩の週末は？' }, items);
assert.strictEqual(got.meta.id, 'stk-wrong-account', 'videoId完全一致は同一チャンネル内だけで採る');

got = R.resolve({ account: 'acc2', videoId: 'rygCPI3Blyc', title: '存在しない題名' }, [{ id: 'other', account: 'acc1', title: '存在しない題名' }]);
assert.strictEqual(got.meta, null, '別チャンネルへは倒さない');

assert.strictEqual(R.isLegacyYouTubeId('rygCPI3Blyc'), true);
assert.strictEqual(R.isLegacyYouTubeId('acc2-20260729-new'), false);

assert.strictEqual(R.cleanTitle('隣人のお姉さんの誘い、強すぎ #1コマ #漫画 #shorts'), '隣人のお姉さんの誘い、強すぎ');
assert.strictEqual(R.cleanTitle('放課後は立場が逆転します　#独自タグ　#PR'), '放課後は立場が逆転します', '全角空白区切りの未知タグも除く');
assert.strictEqual(R.cleanTitle('社内一お堅い先輩の週末は？ #shorts'), '社内一お堅い先輩の週末は？', '保存題名の全角記号は現行規則どおり維持する');
assert.strictEqual(R.cleanTitle('作品 #漫画#PR'), '作品', '空白なしで連結した末尾タグ群も全て除く');
assert.strictEqual(R.cleanTitle('C#入門'), 'C#入門', '題名内部の#は保持する');
assert.strictEqual(R.cleanTitle('#漫画 #shorts'), '', 'タグだけの旧題名もDrive用には空へ落とす');
assert.strictEqual(R.cleanTitle('推し#1の話 #shorts'), '推し#1の話', '題名内部の#を保持しつつ末尾タグだけ除く');
assert.strictEqual(R.cleanTitle('作品 #タグ 後日談'), '作品 #タグ 後日談', '末尾タグ群でない本文中の#語は除去しない');

console.log('All regen identity tests passed.');
