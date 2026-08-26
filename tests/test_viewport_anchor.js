const assert = require('assert');
const Viewport = require('../core/viewport-anchor.js');

function node(key, top, height = 100) {
  return {
    key,
    top,
    height,
    getAttribute(name) { return name === 'data-id' ? this.key : ''; },
    getBoundingClientRect() { return { top: this.top, bottom: this.top + this.height }; }
  };
}
function container(nodes) { return { querySelectorAll() { return nodes; } }; }

const above = node('above', -160, 100);
const visible = node('visible', -20, 120);
const below = node('below', 150, 100);
const root = container([above, visible, below]);
const snap = Viewport.capture(root, '.row', 'data-id');
assert.strictEqual(snap.key, 'visible', '画面上端へ最も近い可視行を基準にする');
assert.strictEqual(snap.top, -20);
visible.top = 75;
assert.strictEqual(Viewport.delta(root, snap), 95, '再描画後の位置差を返す');
let moved = 0;
assert.strictEqual(Viewport.restore(root, snap, (dy) => { moved += dy; visible.top -= dy; }), true);
assert.strictEqual(moved, 95, '位置差だけスクロール補正する');
assert.strictEqual(Viewport.delta(root, snap), 0, '補正後は元の画面位置へ戻る');
const missing = container([node('other', 10)]);
assert.strictEqual(Viewport.restore(missing, snap, () => { throw new Error('呼ばれない'); }), false,
  '同じ行が無いタブ切替ではスクロールしない');
const fs = require('fs');
const path = require('path');
const repo = path.join(__dirname, '..');
const candidates = fs.readFileSync(path.join(repo, 'js/candidates.js'), 'utf8');
const history = fs.readFileSync(path.join(repo, 'js/yt-clicks.js'), 'utf8');
const css = fs.readFileSync(path.join(repo, 'style.css'), 'utf8');
assert(candidates.includes("Go5Viewport.capture(page, '.cand-card[data-cid]', 'data-cid')"),
  '候補一覧の再描画が共通アンカーを使う');
assert(history.includes("Go5Viewport.capture(list, '.vrow[data-hist-anchor]', 'data-hist-anchor')"),
  '投稿履歴の再描画が共通アンカーを使う');
assert(history.includes('data-hist-anchor="' + "' + esc(k) + '"), '投稿履歴カードへ安定IDを付ける');
assert(css.includes('.cand-refimg-ph{width:100%;aspect-ratio:3/4;'), '候補の読込札が画像枠を先に予約する');
assert(css.includes('.cand-refimg-thumb{width:100%;aspect-ratio:3/4;'), '候補実画像も同じ比率を使う');
console.log('viewport-anchor tests: ok');
