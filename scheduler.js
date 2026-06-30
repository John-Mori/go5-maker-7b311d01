/**
 * scheduler.js — 予約投稿（Phase3：client-side「開いている間」スケジューラ＋通知）
 * - reserve() で {slotId,text,imageBlob,scheduledAtMs,alt,handle,appPw,account} をキューへ
 * - 30秒ごとに tick：期限到来(pending かつ scheduledAtMs<=now)の予約を自動投稿
 * - update(id,newMs)：予約時刻変更 / postNow(id)：今すぐ投稿 / cancel(id)：取消
 * - renderTab()：⏰予約タブ（両アカウント一覧）を再描画
 * 制約：画像Blob等は in-memory。ページを閉じる/再読込すると未投稿の予約は消える。
 * dueItems は純粋関数として Node からもテスト可能に公開。
 */
(function (global) {
  'use strict';

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
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function fmt(ms) { var d = new Date(ms); return pad(d.getMonth() + 1) + '/' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
    function esc(s) { return String(s || '').replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }
    function findById(id) {
      for (var i = 0; i < queue.length; i++) { if (String(queue[i].id) === String(id)) return queue[i]; }
      return null;
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
      }).then(renderAll);
    }

    function tick() {
      var due = dueItems(queue, Date.now());
      due.forEach(fire);
      if (due.length) renderAll();
    }

    function cancel(id) { queue = queue.filter(function (it) { return String(it.id) !== String(id); }); renderAll(); }

    function update(id, newMs) {
      var it = findById(id);
      if (it) it.scheduledAtMs = newMs;
      renderAll();
    }

    function postNow(id) {
      var it = findById(id);
      if (it && it.status === 'pending') fire(it);
    }

    // ---- 投稿タブ内の予約リスト（#reserveList） ----
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

    // ---- 予約タブ（#pageReserve）：両アカウント一覧 ----
    function showTimeDlg(item) {
      var dlg = document.getElementById('rsvTimeDlg');
      var picker = document.getElementById('rsvTimePicker');
      var okBtn = document.getElementById('rsvTimeDlgOk');
      var cancelBtn = document.getElementById('rsvTimeDlgCancel');
      if (!dlg || !picker || !okBtn || !cancelBtn) return;
      var d = new Date(item.scheduledAtMs);
      picker.value = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
      dlg.style.display = 'flex';
      function cleanup() {
        dlg.style.display = 'none';
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
      }
      function onOk() {
        var newMs = new Date(picker.value).getTime();
        if (!picker.value || isNaN(newMs)) { window.alert('正しい日時を入力してください。'); return; }
        if (newMs <= Date.now()) { window.alert('未来の時刻を指定してください。'); return; }
        if (window.confirm(new Date(newMs).toLocaleString('ja-JP') + ' に変更しますか？')) { update(item.id, newMs); cleanup(); }
      }
      function onCancel() { cleanup(); }
      okBtn.addEventListener('click', onOk);
      cancelBtn.addEventListener('click', onCancel);
    }

    function renderTab() {
      var el = document.getElementById('pageReserve');
      if (!el) return;
      var pend = queue.filter(function (it) { return it.status === 'pending'; });
      // 予約時刻の早い順。同時刻は acc1（月詠み）が先
      pend.sort(function (a, b) {
        if (a.scheduledAtMs !== b.scheduledAtMs) return a.scheduledAtMs - b.scheduledAtMs;
        var ord = { acc1: 0, acc2: 1 };
        return (ord[a.account] !== undefined ? ord[a.account] : 9) - (ord[b.account] !== undefined ? ord[b.account] : 9);
      });
      if (!pend.length) {
        el.innerHTML = '<div style="padding:32px 16px;text-align:center;color:var(--sub);">予約中の投稿はありません</div>';
        return;
      }
      el.innerHTML = '<div style="padding:12px"><div class="card">' +
        '<div class="field-label" style="margin-bottom:4px;">⏰ 予約済み投稿一覧</div>' +
        '<div class="hint" style="margin-bottom:12px;">両アカウント共通・予約時刻の早い順。このタブを閉じると予約は消えます。</div>' +
        pend.map(function (it) {
          var label = it.account === 'acc2' ? '宵桜艶帖' : '月詠み';
          var cls = it.account === 'acc2' ? 'rsv-badge-acc2' : 'rsv-badge-acc1';
          return '<div class="rsv-tab-row">' +
            '<span class="rsv-badge ' + cls + '">' + label + '</span>' +
            '<span class="rsv-tab-when">' + fmt(it.scheduledAtMs) + '</span>' +
            '<span class="rsv-tab-text">' + esc((it.text || '').split('\n')[0].slice(0, 28)) + '</span>' +
            '<div class="rsv-tab-btns">' +
            '<button type="button" class="ghost rsv-sm-btn" data-tchange="' + it.id + '">時刻変更</button>' +
            '<button type="button" class="ghost rsv-sm-btn" data-tnow="' + it.id + '">今すぐ投稿</button>' +
            '<button type="button" class="ghost rsv-sm-btn rsv-sm-cancel" data-tcancel="' + it.id + '">取消</button>' +
            '</div></div>';
        }).join('') +
        '</div></div>';
      el.querySelectorAll('[data-tcancel]').forEach(function (b) {
        b.addEventListener('click', function () {
          if (window.confirm('この予約を取り消しますか？')) cancel(b.getAttribute('data-tcancel'));
        });
      });
      el.querySelectorAll('[data-tnow]').forEach(function (b) {
        b.addEventListener('click', function () {
          var it = findById(b.getAttribute('data-tnow'));
          var when = it ? fmt(it.scheduledAtMs) : '';
          if (window.confirm(when + ' の予約をキャンセルして今すぐ投稿しますか？')) postNow(b.getAttribute('data-tnow'));
        });
      });
      el.querySelectorAll('[data-tchange]').forEach(function (b) {
        b.addEventListener('click', function () {
          var it = findById(b.getAttribute('data-tchange'));
          if (it) showTimeDlg(it);
        });
      });
    }

    function renderAll() { renderList(); renderTab(); }

    // 初期描画（予約なし状態）
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', renderTab);
    else renderTab();

    global.Scheduler = {
      reserve: function (item) {
        item.id = ++seq; item.status = 'pending';
        queue.push(item); reqPerm(); renderAll();
        notify('予約しました', fmt(item.scheduledAtMs));
        return item.id;
      },
      list: function () { return queue.slice(); },
      cancel: cancel,
      update: update,
      postNow: postNow,
      _renderTab: renderTab,
      dueItems: dueItems,
      _tick: tick
    };

    setInterval(tick, 30000);
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { dueItems: dueItems };
})(typeof window !== 'undefined' ? window : this);
