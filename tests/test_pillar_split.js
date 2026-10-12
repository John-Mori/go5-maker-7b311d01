/**
 * ドラフト投稿一続き化(柱分け)のテスト(2026-10-12・三笘依頼 msg 1559038546835415082・A=1/B=1暫定)。
 *
 * 固定すること:
 *   - 切替は stock.js の PILLAR_SPLIT 1箇所。acc3 だけON、他chは従来どおり。
 *   - 柱分け時のX親文/Bluesky親文は「作品リンクを含む行」を外す(リンクは返信側)。
 *   - 柱(シート「柱」列)は Bluesky親URL/X投稿URL の有無から x / bsky / both。
 *   - Bluesky返信の作品リンクはX側と別コード(宛先に #go5=bsky を付けて短縮)。
 *   - 新しい列・送信キーが GAS / yt-clicks に揃っている(片側だけだと無言で空欄になる)。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8').replace(/\r\n/g, '\n');

let fails = 0;
function eq(got, want, label) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) console.log(`  PASS ${label}`);
  else { console.log(`  FAIL ${label}: got=${g} want=${w}`); fails++; }
}

const stock = read('js/stock.js');
// 実装そのものを切り出して評価する(写しを持たない=実装変更に追従)。
const a = stock.indexOf('  var PILLAR_SPLIT = ');
const b = stock.indexOf('  function loadDraftPost_(');
if (a < 0 || b < 0) { console.log('  FAIL 切替/ヘルパの位置が見つからない'); process.exit(1); }
const pa = stock.indexOf('  function pillarOf_(');
const pb = stock.indexOf('  // 柱分けUIの表示切替');
const window = { BlueskyCore: { hasWorkLinkPlaceholder: (s) => /\{作品リンク\}/.test(s) } };
// eslint-disable-next-line no-new-func
const api = new Function('window', stock.slice(a, b) + stock.slice(pa, pb) +
  '\nreturn { PILLAR_SPLIT, pillarSplitOn_, workLinkTokens_, stripWorkLinks_, pillarOf_ };')(window);

console.log('--- 切替は1箇所・acc3だけ ---');
eq(api.pillarSplitOn_({ account: 'acc3' }), true, 'acc3 -> 柱分け');
eq(api.pillarSplitOn_({ account: 'acc1' }), false, 'acc1 -> 従来');
eq(api.pillarSplitOn_({}), false, 'account無し(=acc1) -> 従来');
eq(api.pillarSplitOn_(null), false, 'meta無し -> 従来');
eq((stock.match(/var PILLAR_SPLIT = /g) || []).length, 1, 'PILLAR_SPLIT の定義は1箇所');

console.log('--- 親文から作品リンク行を外す ---');
const meta = { affiliateUrl: 'https://al.fanza.co.jp/?lurl=x&af_id=A', workUrl: '' };
const pd = { workShareUrl: 'https://xdgh3.com/r2/abc', workShortUrl: 'https://xdgh3.com/abc' };
const tk = api.workLinkTokens_(meta, pd);
eq(tk, ['https://xdgh3.com/r2/abc', 'https://xdgh3.com/abc', 'https://al.fanza.co.jp/?lurl=x&af_id=A'], 'トークン=共有/短縮/アフィ(空と重複は除く)');
eq(api.stripWorkLinks_('一言目\n\n▼作品はこちら https://xdgh3.com/r2/abc\n\n#タグ', tk), '一言目\n\n#タグ', '短縮リンク行を外し空行を詰める');
eq(api.stripWorkLinks_('本文\nhttps://al.fanza.co.jp/?lurl=x&af_id=A', tk), '本文', '生アフィリンク行も外す');
eq(api.stripWorkLinks_('本文\n{作品リンク}', tk), '本文', '未展開プレースホルダ行も外す');
eq(api.stripWorkLinks_('本文だけ', tk), '本文だけ', 'リンク無し本文はそのまま');

console.log('--- 柱(x/bsky/both) ---');
eq(api.pillarOf_({}), '', '両方無し -> 空(列を書かない)');
eq(api.pillarOf_({ xPostUrl: 'https://x.com/a/status/1' }), 'x', 'Xだけ -> x');
eq(api.pillarOf_({ bskyParentUrl: 'https://bsky.app/profile/a/post/1' }), 'bsky', 'Blueskyだけ -> bsky');
eq(api.pillarOf_({ xPostUrl: 'https://x.com/a/status/1', bskyParentUrl: 'https://bsky.app/p' }), 'both', '両方 -> both');
eq(api.pillarOf_({ xPostUrl: '   ' }), '', '空白だけのX URL -> 空');

console.log('--- 配線(片側だけの変更で無言の空欄にしない) ---');
const gas = read('gas/コード.gs');
['X投稿URL', 'Bluesky親URL', 'Bluesky返信URL', 'Bluesky作品短縮URL', '柱'].forEach((h) => {
  eq(gas.indexOf("'" + h + "'") >= 0, true, `GAS 列 ${h}`);
});
const yt = read('js/yt-clicks.js');
['x_post_url', 'bsky_parent_url', 'bsky_reply_url', 'bsky_work_short_url', 'pillar'].forEach((k) => {
  eq(yt.indexOf('payload.' + k) >= 0 && gas.indexOf('body.' + k) >= 0, true, `送信キー ${k} が yt-clicks と GAS の両方にある`);
});
const bs = read('js/bluesky.js');
eq(/#go5=bsky/.test(bs), true, 'Bluesky返信リンクは #go5=bsky で別コード(B=1)');
eq(/window\.Go5DraftBskyThread = draftBskyThread_/.test(bs), true, 'Go5DraftBskyThread を公開');
eq(/console\.(log|warn|error)\([^)]*appPw/.test(bs), false, 'アプリパスワードをconsoleへ出さない');
eq(/if \(ev && ev\.detail && ev\.detail\.draft\) return;/.test(bs), true, 'ドラフト作成時のBluesky自動投稿ガードは残っている');

console.log(fails ? `\n${fails} FAIL` : '\nALL PASS');
process.exit(fails ? 1 : 0);
