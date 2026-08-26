const assert = require('assert');
const fs = require('fs');
const path = require('path');

const repo = path.join(__dirname, '..');
const history = fs.readFileSync(path.join(repo, 'js/yt-clicks.js'), 'utf8');
const viewport = fs.readFileSync(path.join(repo, 'core/viewport-anchor.js'), 'utf8');
const stock = fs.readFileSync(path.join(repo, 'StockLists.html'), 'utf8');
const css = fs.readFileSync(path.join(repo, 'style.css'), 'utf8');

const imageHandler = history.match(/document\.addEventListener\('go5-images-hydrated',[\s\S]*?\n  \}\);/);
assert(imageHandler, '画像ハイドレートの購読がある');
assert(imageHandler[0].includes('patchHistoryImages_()'), '画像到着時は該当画像だけを差分更新する');
assert(!imageHandler[0].includes('render();'), '画像到着時に投稿履歴全体を再生成しない');

const patch = history.slice(history.indexOf('  function patchHistoryImages_() {'), history.indexOf('\n\n  function render() {'));
assert(patch.includes("querySelectorAll('.vrow[data-hist-usedkey]')"), '表示中カードを安定キーで更新する');
assert(patch.includes('window.Go5Cand.ensureHistoryImages(rows.map'), '差分更新側から表示中作品の個別取得を必ず開始する');
assert(patch.includes("Go5ImgDiag.push('hist_render'"), '従来の画像診断契約を維持する');
assert(patch.includes('if (!data.thumb) return;'), '一過性の空読みで既存画像を消さない');
assert(!patch.includes('innerHTML'), '差分更新で一覧DOMを交換しない');
assert(history.includes('data-hist-usedkey="\' + esc(pKey) + \'"'), '履歴カードへ画像用安定キーを刻む');
assert(history.includes("window.addEventListener('touchmove', markHistUserScroll_, { passive: true })"), 'iPhoneの指操作を検出する');
assert(history.includes('_histIdleRenderT = setTimeout(renderWhenHistIdle_, wait + 60)'), '背景再描画をスクロール停止後へまとめる');
assert(history.includes('restore(list, viewportSnap, null, { repeat: false })'), '履歴では次フレームの二重スクロール補正を止める');
assert(viewport.includes("options.repeat !== false"), '共通アンカーは二重補正を無効化できる');
assert(stock.includes('window.Go5Verify.patchImages'), '候補画像供給スクリプト到着時も全体再描画しない');
assert(css.includes('@media(max-width:700px){.vrow{content-visibility:visible;contain-intrinsic-size:none;}}'),
  'iPhoneでは仮高さからの遅延レイアウト補正を無効化する');

console.log('history render stability tests: ok');