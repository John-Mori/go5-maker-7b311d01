// core/operation-gate.js — 非同期UIを「処理中」のまま残さない単一終端権威。(Go5OperationGate)
//
// 保存・同期・取得などの非同期処理は、正常/失敗/タイムアウト/遅着が競合する。
// 呼び元ごとに settled フラグと番犬を複製すると、片方だけ直って再発するため、
// 最初の終端だけを採用してボタンを必ず操作可能へ戻す責務をここへ集約する。
(function (root) {
  'use strict';

  function armButton(button, opts) {
    opts = opts || {};
    if (!button) return null;

    var setTimer = opts.setTimeoutFn || root.setTimeout;
    var clearTimer = opts.clearTimeoutFn || root.clearTimeout;
    var original = opts.originalLabel != null ? String(opts.originalLabel) : String(button.textContent || '');
    var pending = opts.pendingLabel || '処理中…';
    var success = opts.successLabel || original;
    var timeout = opts.timeoutLabel || '⏱ 中断(再度お試しください)';
    var timeoutMs = Number(opts.timeoutMs || 0);
    var restoreDelayMs = Number(opts.restoreDelayMs || 0);
    var settled = false;
    var watchdog = null;

    button.textContent = pending;
    button.disabled = true;

    function finish(ok, label, reason) {
      if (settled) return false;
      settled = true;
      if (watchdog != null && clearTimer) clearTimer(watchdog);
      button.disabled = false;
      button.textContent = label || (ok ? success : original);
      if (ok && restoreDelayMs > 0 && setTimer) {
        setTimer(function () {
          if (button.textContent === success) button.textContent = original;
        }, restoreDelayMs);
      }
      if (typeof opts.onSettle === 'function') {
        try { opts.onSettle(!!ok, reason || (ok ? 'success' : 'failure')); } catch (_) {}
      }
      return true;
    }

    if (timeoutMs > 0 && setTimer) {
      watchdog = setTimer(function () { finish(false, timeout, 'timeout'); }, timeoutMs);
    }

    return {
      finish: function (ok, label) { return finish(!!ok, label, ok ? 'success' : 'failure'); },
      succeed: function (label) { return finish(true, label, 'success'); },
      fail: function (label) { return finish(false, label, 'failure'); },
      timedOut: function () { return finish(false, timeout, 'timeout'); },
      isSettled: function () { return settled; },
      originalLabel: original
    };
  }

  var api = { armButton: armButton };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Go5OperationGate = api;
})(typeof window !== 'undefined' ? window : this);
