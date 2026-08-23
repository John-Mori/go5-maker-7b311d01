/**
 * core/img-diag.js — 画像表示不良の恒久調査(Phase1=診断計測層)。(Go5ImgDiag)
 *
 * 目的：候補ページ/投稿履歴の画像がiPhone/iOS Safariで「初回に出ない・リロードで出る・
 *   画像が増えるほど悪化」する不良を、まず計測できるようにする。挙動は一切変えない。
 *   push() でリングバッファ(最大300件)に積むだけ(consoleへは出さない・非同期処理も足さない)。
 *   `?imgdiag=1` を付けた時だけ画面右下に「コピー」ボタンを出し、dump() の全文をコピーできる。
 *
 * 使い方(呼び出し側)：window.Go5ImgDiag && Go5ImgDiag.push('ev_name', {key: val});
 *   例外安全(try/catchで包む)。呼び出し元のロジックには一切影響しない。
 */
(function () {
  'use strict';

  if (typeof window === 'undefined') return; // Node/module環境はここで終わり(DOM無し)
  var root = window;

  if (root.Go5ImgDiag) return; // 既に定義済みなら再定義しない

  var MAX = 300;
  var buf = [];
  var t0 = 0;

  function push(ev, data) {
    try {
      if (!t0) t0 = Date.now();
      var row = { t: Date.now(), ev: String(ev || '') };
      if (data && typeof data === 'object') {
        for (var k in data) { if (Object.prototype.hasOwnProperty.call(data, k)) row[k] = data[k]; }
      }
      buf.push(row);
      if (buf.length > MAX) buf.shift();
    } catch (e) {}
  }

  function summarize_() {
    var hydrate = 0, timeout = 0, r2fallback = 0, stalled = 0;
    for (var i = 0; i < buf.length; i++) {
      var r = buf[i];
      if (r.ev === 'hydrate_start') hydrate++;
      if (r.ev === 'idb_read_timeout') timeout++;
      if (r.ev === 'r2_start') r2fallback++;
      if (r.ev === 'stalled') stalled++;
    }
    return 'hydrate回数=' + hydrate + ' timeout回数=' + timeout + ' r2fallback回数=' + r2fallback + ' stalled件数=' + stalled;
  }

  function dump() {
    try {
      var lines = [];
      lines.push('=== 画像診断ダンプ(' + new Date().toISOString() + ') ===');
      lines.push(summarize_());
      lines.push('---');
      var base = buf.length ? buf[0].t : Date.now();
      for (var i = 0; i < buf.length; i++) {
        var r = buf[i];
        var rel = r.t - base;
        var parts = ['+' + rel + 'ms', r.ev];
        for (var k in r) {
          if (k === 't' || k === 'ev') continue;
          if (!Object.prototype.hasOwnProperty.call(r, k)) continue;
          parts.push(k + '=' + r[k]);
        }
        lines.push(parts.join(' '));
      }
      return lines.join('\n');
    } catch (e) {
      return '(dump失敗: ' + (e && e.message) + ')';
    }
  }

  var API = { push: push, dump: dump };
  root.Go5ImgDiag = API;

  // ── ?imgdiag=1 の時だけ、コピー用の小さいボタンを出す ──────────────────
  function initButton_() {
    try {
      var qs = String((root.location && root.location.search) || '');
      if (!/[?&]imgdiag=1(&|$)/.test(qs)) return;
      if (!root.document || !root.document.body) return;
      var btn = root.document.createElement('button');
      btn.type = 'button';
      btn.textContent = '📋 画像診断をコピー';
      btn.style.cssText = 'position:fixed;right:8px;bottom:8px;z-index:100000;background:#0e1422;color:#e8eef7;border:1px solid #2bb3c0;border-radius:10px;padding:8px 12px;font-size:12px;line-height:1.4;box-shadow:0 4px 16px rgba(0,0,0,.4);cursor:pointer;';
      btn.addEventListener('click', function () {
        var text = dump();
        var done = function () {
          var orig = btn.textContent;
          btn.textContent = 'コピーしました';
          setTimeout(function () { btn.textContent = orig; }, 1500);
        };
        try {
          if (root.navigator && root.navigator.clipboard && root.navigator.clipboard.writeText) {
            root.navigator.clipboard.writeText(text).then(done, function () { fallbackCopy_(text, done); });
          } else {
            fallbackCopy_(text, done);
          }
        } catch (e) { fallbackCopy_(text, done); }
      });
      root.document.body.appendChild(btn);
    } catch (e) {}
  }

  function fallbackCopy_(text, done) {
    try {
      var ta = root.document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;';
      root.document.body.appendChild(ta);
      ta.select();
      root.document.execCommand('copy');
      root.document.body.removeChild(ta);
      done();
    } catch (e) {}
  }

  if (root.document) {
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', initButton_);
    else initButton_();
  }
})();
