/**
 * tests/test_bsky_child_text.js
 * Blueskyの子(返信)が、ドラフトの「子の文(返信)」を空行ごとそのまま使い、リンクだけBluesky用へ差し替えること
 * (Chami 2026-10-13 msg 1559290199324762212「子の投稿文が違う・一行空白も入れて」)。
 * js/bluesky.js の本物の bskyReplyTextOf_ / countGraphemes を抜き出して実行する。
 * 実行: node tests/test_bsky_child_text.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'js/bluesky.js'), 'utf8').replace(/\r\n/g, '\n');
function grab(name) {
  const i = src.indexOf('  function ' + name + '(');
  if (i < 0) throw new Error('not found: ' + name);
  const j = src.indexOf('\n  }\n', i);
  return src.slice(i, j + 4);
}
const make = new Function(
  "var BSKY_REPLY_TEXT = '続きはこちら';\n" + grab('countGraphemes') + '\n' + grab('bskyReplyTextOf_') + '\nreturn bskyReplyTextOf_;'
);
const f = make();

let fails = 0;
function eq(a, b, m) { const ok = a === b; console.log((ok ? '  ok   ' : '  FAIL ') + m + (ok ? '' : ' got=' + JSON.stringify(a) + ' want=' + JSON.stringify(b))); if (!ok) fails++; }

const BS = 'https://xdgh3.com/QNcxU';
const child = '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/P51lB';
eq(f(child, BS), '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/QNcxU', '子の文そのまま・空行も残し・リンクだけBluesky用');
eq(f(child.replace(/\n/g, '\r\n'), BS), '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/QNcxU', 'CRLFでも同じ');
eq(f('  ' + child + '\n\n', BS), '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/QNcxU', '前後の余白だけ落とす');
eq(f('⇩気になった方はコチラから💕 #PR #漫画', BS), '⇩気になった方はコチラから💕 #PR #漫画\n\nhttps://xdgh3.com/QNcxU', 'URLが無ければ空行を挟んで末尾へ');
eq(f('', BS), '続きはこちら\nhttps://xdgh3.com/QNcxU', '子の文が空なら従来文');
eq(f(undefined, BS), '続きはこちら\nhttps://xdgh3.com/QNcxU', '子の文が渡らなければ従来文');
eq(f('あ'.repeat(290) + '\n\nhttps://x.example/a', BS), '続きはこちら\nhttps://xdgh3.com/QNcxU', '300字超なら従来文(投稿失敗を避ける)');
// 2026-10-21 インシデント(msg 1562248434251997204): 2本目以降のURLまで作品リンクにして同じ短縮URLが2回出た。
eq(f('見出し\nhttps://al.fanza.co.jp/?lurl=work\n\nhttps://al.fanza.co.jp/?lurl=sale', BS), '見出し\nhttps://xdgh3.com/QNcxU\n\nhttps://al.fanza.co.jp/?lurl=sale', '作品リンクへ差し替えるのは最初のURLだけ');

console.log('--- 🦋投稿本文(テンプレ)どおりの返信(2026-10-21 インシデント) ---');
const Core = require(path.join(__dirname, '..', 'js/bluesky-core.js'));
const makeBody = new Function('window', 'saleLink',
  "var BSKY_REPLY_TEXT = '続きはこちら';\n" +
  ['countGraphemes', 'stripAutoBlocks_', 'stripAutoBlocksSafe_', 'hasWorkPH_', 'hasSalePH_', 'fillWorkPH_', 'fillSalePH_', 'bskyReplyFromBody_', 'dupLinkIn_'].map(grab).join('\n') +
  // セール短縮の取得(ネット)だけ差し替える。埋め方/消し方は本物と同じ(取れなければプレースホルダ語を消す)。
  "\nfunction finalizeSalePlaceholder_(s) { return Promise.resolve(hasSalePH_(s) ? (saleLink ? fillSalePH_(s, saleLink) : fillSalePH_(s, '\\u0000').split('\\u0000').join('')) : s); }" +
  '\nreturn { body: bskyReplyFromBody_, dup: dupLinkIn_ };'
);
const TPL = '⇩気になった方はコチラから💕 #PR #漫画\n(商品紹介用短縮URL)\n\n⇩オータムセール🌰最大99%OFF！\n(セール用短縮URL)';
const WORK = 'https://xdgh3.com/Vb3y9', SALE = 'https://xdgh3.com/S4le1';
const g = makeBody({ BlueskyCore: Core }, SALE);
const tasks = [
  g.body(TPL, WORK).then((t) => eq(t, '⇩気になった方はコチラから💕 #PR #漫画\n' + WORK + '\n\n⇩オータムセール🌰最大99%OFF！\n' + SALE, 'テンプレどおり=作品短縮・セール行・セール短縮(足す行なし)')),
  g.body(TPL.replace(/\n/g, '\r\n'), WORK).then((t) => eq(t.indexOf('⇩オータムセール🌰最大99%OFF！\n' + SALE) > 0, true, 'CRLFの本文でもセール行が残る')),
  g.body(TPL, WORK).then((t) => eq(g.dup(t), '', 'テンプレどおりの返信に同じURLは無い')),
  g.body('⇩気になった方はコチラから💕 #PR #漫画\nhttps://x.example/a', WORK).then((t) => eq(t, '', '作品プレースホルダの無い本文は""=子の文へ倒す')),
  g.body('', WORK).then((t) => eq(t, '', '本文が空なら""')),
];
eq(g.dup('a\nxdgh3.com/Vb3y9\n\nhttps://xdgh3.com/Vb3y9'), 'https://xdgh3.com/Vb3y9', '番犬: https有無違いでも同じURLの2回を見つける');
eq(g.dup('a\n' + WORK + '\n' + SALE), '', '番犬: 別URLは通す');

console.log('--- 配線 ---');
eq(/return bskyReplyFromBody_\(o\.bskyBody, link\)/.test(src) && /out\.replyText = t \|\| bskyReplyTextOf_\(o\.childText, link\);/.test(src), true, 'ドラフト一続きの返信文は🦋投稿本文から作り、無い時だけ子の文');
eq(/if \(dupLinkIn_\(out\.replyText\)\) throw new Error\('dup-link'\)/.test(src), true, '同じURLが2回入る返信は親ごと出さない');
const st = fs.readFileSync(path.join(__dirname, '..', 'js/stock.js'), 'utf8');
// 2026-10-13 Chami msg 1559480072589803612: 子の文は定型文へ。msg 1559679396363636736 以降は子の文欄の2行目を差し替えて使う(見出しが無い時だけ affiPostText)。
eq(/draftId: meta\.id, childText: childText, bskyBody: bskyBody \}/.test(st) && /core\.withAffiStatusLine\(xv, info\)/.test(st), true, '投稿モードは子の文欄(控え)と🦋投稿本文を渡す');
eq(/var bskyBody = applyPromo_\(masterBody_\(meta\), meta, true\);/.test(st), true, '🦋投稿本文=そのchの投稿本文(masterBody_)・セール案内行は残す');
// 返信の固定画像(2026-10-21 差し替え msg 1562261269606826154)=実在し、Bluesky blob上限(~950KB)以下。
const imgSrc = (src.match(/var BSKY_REPLY_IMG_SRC = '([^']+)'/) || [])[1] || '';
const imgPath = path.join(__dirname, '..', imgSrc);
eq(imgSrc === 'assets/bsky-reply-continue-2.jpg' && fs.existsSync(imgPath) && fs.statSync(imgPath).size < 950 * 1024, true, '返信画像=差し替え後の画像・950KB以下');
const SL = '⇩オータムセール🌰最大99%OFF！';
eq(Core.resolvePromoTemplate(TPL, { noPromo: true, keepSaleLines: true }).indexOf(SL) > 0, true, '癒やし倉庫(noPromo)でもBluesky返信はセール案内行を残す');
eq(Core.resolvePromoTemplate(TPL, { noPromo: true }).indexOf(SL), -1, 'keepSaleLinesなし(YouTube説明欄等)はnoPromoで%OFF行を外す');
// 2026-10-21 Chami msg 1562266602194337793「2」: X用の子の文欄にもセール行を戻す(v1066の除去を外した)。
eq(/function composeXForModal_[\s\S]*?return applyPromo_\(base, meta, true\);/.test(st) && !/dropSaleLines_/.test(st), true, 'Xの子の文もセール案内行を残す(dropSaleLines_へ戻さない)');
eq(Core.resolvePromoTemplate('見出し\n今だけN%OFF', { noPromo: true, keepSaleLines: true }), '見出し', '作品の割引率(N%)の行はBluesky返信でも外す');
Promise.all(tasks).then(() => {
  if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
  console.log('all ok');
});
