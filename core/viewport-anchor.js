/*
 * Go5Viewport — 一覧の再描画前後で「見ていたカード」の画面上の位置を保つ。
 *
 * innerHTML による一覧交換や遅着画像で上側の高さが変わっても、安定IDを持つ
 * 可視カードを基準に差分だけスクロール補正する。位置そのものを保存するだけの
 * 小さな共通部品にし、候補/投稿履歴が別々の補正ロジックを持たないようにする。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.Go5Viewport = api;
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  function nodes_(container, selector) {
    if (!container || !container.querySelectorAll || !selector) return [];
    try { return Array.prototype.slice.call(container.querySelectorAll(selector)); }
    catch (e) { return []; }
  }

  function capture(container, selector, keyAttr) {
    keyAttr = keyAttr || 'data-anchor';
    var nodes = nodes_(container, selector);
    var chosen = null;
    for (var i = 0; i < nodes.length; i++) {
      var rect = nodes[i].getBoundingClientRect ? nodes[i].getBoundingClientRect() : null;
      if (!rect) continue;
      if (rect.bottom > 0) { chosen = { el: nodes[i], rect: rect }; break; }
    }
    if (!chosen) return null;
    var key = chosen.el.getAttribute ? chosen.el.getAttribute(keyAttr) : '';
    if (!key) return null;
    return { selector: selector, keyAttr: keyAttr, key: String(key), top: chosen.rect.top };
  }

  function find_(container, snap) {
    if (!snap) return null;
    var nodes = nodes_(container, snap.selector);
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].getAttribute && String(nodes[i].getAttribute(snap.keyAttr) || '') === snap.key) return nodes[i];
    }
    return null;
  }

  function delta(container, snap) {
    var el = find_(container, snap);
    if (!el || !el.getBoundingClientRect) return null;
    return el.getBoundingClientRect().top - snap.top;
  }

  function restore(container, snap, scrollByFn, options) {
    if (!snap) return false;
    var fn = scrollByFn;
    if (!fn && typeof window !== 'undefined' && window.scrollBy) fn = function (dy) { window.scrollBy(0, dy); };
    if (!fn) return false;
    var apply = function () {
      var dy = delta(container, snap);
      if (dy == null) return false;
      if (Math.abs(dy) > 0.5) fn(dy);
      return true;
    };
    var ok = apply();
    if (ok && (!options || options.repeat !== false) && typeof window !== 'undefined' && window.requestAnimationFrame) window.requestAnimationFrame(function () { apply(); });
    return ok;
  }

  return { capture: capture, delta: delta, restore: restore };
});
