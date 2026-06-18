/**
 * scheduler.js — 予約投稿（Phase3：client-side「開いている間」スケジューラ＋通知）
 * - reserve() で {slotId,text,imageBlob,scheduledAtMs,alt,handle,appPw} をキューへ
 * - 30秒ごとに tick：期限到来(pending かつ scheduledAtMs<=now)の予約を自動投稿
 * - 投稿成功で 'bluesky-posted' を発火（integration.js がスロットへ書き戻し）＋ブラウザ通知
 * 制約：画像Blob等は in-memory。ページを閉じる/再読込すると未投稿の予約は消える（無人化はPhase5のサーバーレスcronで対応）。
 * dueItems は純粋関数として Node からもテスト可能に公開。
 */
(function (global) {
  'use strict';

  // 純粋関数：期限到来した pending 予約を返す（テスト対象）
  function dueItems(queue, nowMs) {
    return (queue || []).filter(function (it) {
      return it && it.status === 'pending' && typeof it.scheduledAtMs === 'number' && it.scheduledAtMs <= nowMs;
    });
  }

  if (typeof window !== 'undefined') {
    var queue = [];
    var seq = 0;
    var firstUrlRe = /https?:\/\/[^\s]+/;

    function notify(title, body) {
      try {
        if (!('Notification' in window)) return;
        if (Notification.permission === 'granted') new Notification(title, { body: body || '' });
      } catch (e) {}
    }
    function reqPerm() {
      try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); } catch (e) {}
    }

    function fire(it) {
      it.status = 'posting';
      if (!window.BlueskyCore) { it.status = 'error'; it.error = '投稿モジュール未読込'; return Promise.resolve(); }
      return window.BlueskyCore.blueskyPostRaw({
        identifier: it.handle, appPassword: it.appPw, text: it.text, imageBlob: it.imageBlob, alt: it.alt
      }).then(function (res) {
        it.status = 'posted'; it.postUrl = res.postUrl;
        notify('予約投稿を公開しました 🦋', (it.text || '').split('\n')[0]);
        try {
          document.dispatchEvent(new CustomEvent('bluesky-posted', { detail: {
            post_uri: res.uri || '', post_url: res.postUrl || '',
            affiliate: (it.text.match(firstUrlRe) || [''])[0],
            posted_at: new Date().toISOString(), slotId: it.slotId || null,
            title: it.alt || (String(it.text).split('\n')[0] || '')
          } }));
        } catch (e) {}
      }).catch(function (e) {
        it.status = 'error'; it.error = String(e && e.message || e);
        notify('予約投稿に失敗', it.error);
      }).then(renderList);
    }

    function tick() {
      var due = dueItems(queue, Date.now());
      due.forEach(fire);
      if (due.length) renderList();
    }

    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function fmt(ms) { var d = new Date(ms); return pad(d.getMonth() + 1) + '/' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
    function esc(s) { return String(s || '').replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }

    function renderList() {
      var el = document.getElementById('reserveList');
      if (!el) return;
      var pend = queue.filter(function (it) { return it.status === 'pending'; });
      if (!pend.length) { el.hidden = true; el.innerHTML = ''; return; }
      el.hidden = false;
      el.innerHTML = '<div class="rsv-title">⏰ 予約中（このタブを開いている間に自動投稿）</div>' +
        pend.map(function (it) {
          return '<div class="rsv-row"><span class="rsv-when">' + fmt(it.scheduledAtMs) + '</span>' +
            '<span class="rsv-text">' + esc((it.text || '').split('\n')[0].slice(0, 26)) + '</span>' +
            '<button type="button" data-cancel="' + it.id + '">取消</button></div>';
        }).join('');
      el.querySelectorAll('[data-cancel]').forEach(function (b) {
        b.addEventListener('click', function () { cancel(b.getAttribute('data-cancel')); });
      });
    }
    function cancel(id) { queue = queue.filter(function (it) { return String(it.id) !== String(id); }); renderList(); }

    global.Scheduler = {
      reserve: function (item) {
        item.id = ++seq; item.status = 'pending';
        queue.push(item); reqPerm(); renderList();
        notify('予約しました', fmt(item.scheduledAtMs));
        return item.id;
      },
      list: function () { return queue.slice(); },
      cancel: cancel,
      dueItems: dueItems,
      _tick: tick   // テスト/手動発火用
    };

    setInterval(tick, 30000); // 30秒ごとに期限チェック
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { dueItems: dueItems };
})(typeof window !== 'undefined' ? window : this);
