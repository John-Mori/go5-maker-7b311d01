/**
 * scheduler.js — 予約投稿(Phase3：client-side「開いている間」スケジューラ＋通知)
 * - reserve() で {slotId,text,imageBlob,scheduledAtMs,alt,handle,appPw,account} をキューへ
 * - 30秒ごとに tick：期限到来(pending かつ scheduledAtMs<=now)の予約を自動投稿
 * - update(id,newMs)：予約時刻変更 / postNow(id)：今すぐ投稿 / cancel(id)：取消
 * - renderTab()：⏰予約タブ(両アカウント一覧)を再描画
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


  // Treat 05:00 local time as the start of each posting day.
  function postingDayStart(nowMs) {
    var now = new Date(Number(nowMs)), start = new Date(Number(nowMs));
    start.setHours(5, 0, 0, 0);
    if (now.getTime() < start.getTime()) start.setDate(start.getDate() - 1);
    return start.getTime();
  }
  function splitRecentPosts(rows, nowMs) {
    var todayStart = postingDayStart(nowMs);
    var tomorrow = new Date(todayStart); tomorrow.setDate(tomorrow.getDate() + 1);
    var yesterday = new Date(todayStart); yesterday.setDate(yesterday.getDate() - 1);
    var out = { today: [], yesterday: [], todayStart: todayStart, tomorrowStart: tomorrow.getTime(), yesterdayStart: yesterday.getTime() };
    (Array.isArray(rows) ? rows : []).forEach(function (row) {
      var t = Number(row && row.publishedAt); if (!t) return;
      if (t >= todayStart && t < out.tomorrowStart) out.today.push(row);
      else if (t >= out.yesterdayStart && t < todayStart) out.yesterday.push(row);
    });
    return out;
  }
  function sortRecentPosts(rows, mode) {
    var key = mode === 'views' ? 'views' : (mode === 'pink' ? 'pinkClicks' : (mode === 'peak' ? 'peakViews' : 'publishedAt'));
    return (Array.isArray(rows) ? rows.slice() : []).sort(function (a, b) {
      var av = Number(a && a[key]), bv = Number(b && b[key]);
      var aOk = a && a[key] != null && !isNaN(av), bOk = b && b[key] != null && !isNaN(bv);
      if (aOk && bOk && av !== bv) return bv - av;
      if (aOk !== bOk) return aOk ? -1 : 1;
      return Number(b && b.publishedAt || 0) - Number(a && a.publishedAt || 0);
    });
  }
  function recentCounts(rows) {
    var c = { acc1: 0, acc2: 0, total: 0 };
    (Array.isArray(rows) ? rows : []).forEach(function (row) { if (row && row.account === 'acc2') c.acc2++; else c.acc1++; c.total++; });
    return c;
  }

  if (typeof window !== 'undefined') {
    var queue = [];
    var seq = 0;
    var firstUrlRe = /https?:\/\/[^\s]+/;
    // Today is expanded by default. Yesterday stays lazy until the user opens it.
    var recentOpen = { today: true, yesterday: false };
    var recentSort = 'latest';
    var recentHydrateTimer = 0;

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
    function esc(s) { return String(s || '').replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
    function findById(id) {
      for (var i = 0; i < queue.length; i++) { if (String(queue[i].id) === String(id)) return queue[i]; }
      return null;
    }


    function recentPosts_() {
      try {
        if (global.Go5History && typeof global.Go5History.recentPublishedCached === 'function') {
          var todayStart = postingDayStart(Date.now()), yesterdayStart = new Date(todayStart);
          yesterdayStart.setDate(yesterdayStart.getDate() - 1);
          return global.Go5History.recentPublishedCached({
            fromMs: yesterdayStart.getTime(), todayStart: todayStart,
            includeTodayDetails: recentOpen.today, includeYesterdayDetails: recentOpen.yesterday
          }) || [];
        }
      } catch (e) {}
      return [];
    }
    function recentCountHtml_(rows) {
      var c = recentCounts(rows);
      return '<span class="rsv-recent-count">\u6708\u8a60\u307f' + c.acc1 + '\u672c\u3000\u5bb5\u685c' + c.acc2 + '\u672c\u3000\u5408\u8a08' + c.total + '\u672c</span>';
    }
    function recentMetric_(value, pending) { return value != null ? Number(value).toLocaleString() : (pending ? '\u2026' : '\u2013'); }
    function recentRowHtml_(row) {
      var ch = row.account === 'acc2' ? '\u5bb5\u685c\u8276\u5e16' : '\u6708\u8a60\u307f';
      var cls = row.account === 'acc2' ? 'rsv-badge-acc2' : 'rsv-badge-acc1';
      var postLabel = row.postPlatform === 'x' ? 'X\u2197' : 'Bsky\u2197';
      var postCls = row.postPlatform === 'x' ? 'vlink-x' : 'vlink-bsky';
      var pinkIcon = '<img class="emico emico-cursor" src="assets/icons/ic-cursor-pink.png" alt="\u30d4\u30f3\u30af\u30af\u30ea\u30c3\u30af">';
      return '<div class="vrow rsv-recent-row" data-recent-item="' + esc(row.videoId || row.id || '') + '"><div class="vrow-body">' +
        '<div class="vrow-h"><b>' + fmt(row.publishedAt) + '</b><span class="rsv-badge ' + cls + '">' + ch + '</span></div>' +
        '<div class="vrow-title">' + esc(row.title || '(\u7121\u984c)') + '</div><div class="vmetrics">' +
        '<span title="YouTube\u518d\u751f\u6570">\u25b6 ' + recentMetric_(row.views, !!row.videoId) + '</span>' +
        '<span title="\u30d4\u30f3\u30af\u30af\u30ea\u30c3\u30af\u6570">' + pinkIcon + ' ' + recentMetric_(row.pinkClicks, !!row.hasPink) + '</span>' +
        '<span title="\u30d4\u30fc\u30af\u518d\u751f\u6570">\ud83c\udf00 \u25b6 ' + recentMetric_(row.peakViews, false) + (row.peakViews != null ? '/\u6642' : '') + '</span>' +
        '<span class="vrow-links">' +
        (row.postUrl ? '<a class="vlink ' + postCls + '" href="' + esc(row.postUrl) + '" target="_blank" rel="noopener">' + postLabel + '</a>' : '') +
        (row.ytUrl ? '<a class="vlink vlink-yt" href="' + esc(row.ytUrl) + '" target="_blank" rel="noopener">YouTube\u2197</a>' : '') +
        (row.workUrl ? '<a class="vlink vlink-work" href="' + esc(row.workUrl) + '" target="_blank" rel="noopener">\u4f5c\u54c1\u2197</a>' : '') +
        '</span></div></div></div>';
    }
    function recentSectionHtml_(kind, rows, title) {
      var opened = !!recentOpen[kind], sorted = opened ? sortRecentPosts(rows, recentSort) : [];
      return '<section class="card rsv-recent-section" data-recent-group="' + kind + '">' +
        '<button class="rsv-recent-toggle" type="button" data-recent-toggle="' + kind + '" aria-expanded="' + (opened ? 'true' : 'false') + '">' +
        '<span class="rsv-recent-title"><span aria-hidden="true">' + (opened ? '\u25bc' : '\u25b6') + '</span> ' + title + '</span>' +
        recentCountHtml_(rows) + '</button>' +
        (opened ? '<div class="rsv-recent-list">' + (sorted.length ? sorted.map(recentRowHtml_).join('') : '<div class="hint rsv-recent-empty">\u8a72\u5f53\u3059\u308bYouTube\u52d5\u753b\u306f\u3042\u308a\u307e\u305b\u3093\u3002</div>') + '</div>' : '') +
        '</section>';
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
            title: it.alt || (String(it.text).split('\n')[0] || ''),
            account: it.account || null,   // ★予約時に凍結した所属アカウント(発火時のUIに依存しない)
            meta: it.meta || null          // ★予約時に凍結した投稿メタ(作品URL/カテゴリ/作品状態/当時価格)
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

    function cancel(id) {
      var it = findById(id);
      queue = queue.filter(function (x) { return String(x.id) !== String(id); }); renderAll();
      // カレンダー連携：枠から予約していたら、その枠の「予約登録済」を解除して戻す。
      if (it && it.slotId) { try { document.dispatchEvent(new CustomEvent('bluesky-reservation-cancelled', { detail: { slotId: it.slotId, account: it.account } })); } catch (e) {} }
    }

    function update(id, newMs) {
      var it = findById(id);
      if (it) it.scheduledAtMs = newMs;
      renderAll();
    }

    function postNow(id) {
      var it = findById(id);
      if (it && it.status === 'pending') fire(it);
    }

    // ---- 投稿タブ内の予約リスト(#reserveList) ----
    function renderList() {
      var el = document.getElementById('reserveList');
      if (!el) return;
      var pend = queue.filter(function (it) { return it.status === 'pending' && it.scheduledAtMs > Date.now(); }); // 予約時刻を過ぎたら表示から消す
      if (!pend.length) { el.hidden = true; el.innerHTML = ''; return; }
      el.hidden = false;
      el.innerHTML = '<div class="rsv-title">⏰ 予約中(このタブを開いている間に自動投稿)</div>' +
        pend.map(function (it) {
          return '<div class="rsv-row"><span class="rsv-when">' + fmt(it.scheduledAtMs) + '</span>' +
            '<span class="rsv-text">' + esc((it.text || '').split('\n')[0].slice(0, 26)) + '</span>' +
            '<button type="button" data-cancel="' + it.id + '">取消</button></div>';
        }).join('');
      el.querySelectorAll('[data-cancel]').forEach(function (b) {
        b.addEventListener('click', function () { cancel(b.getAttribute('data-cancel')); });
      });
    }

    // ---- 予約タブ(#pageReserve)：両アカウント一覧 ----
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
      var pend = queue.filter(function (it) { return it.status === 'pending' && it.scheduledAtMs > Date.now(); }); // 予約時刻を過ぎたら表示から消す
      // 予約時刻の早い順。同時刻は acc1(月詠み)が先
      pend.sort(function (a, b) {
        if (a.scheduledAtMs !== b.scheduledAtMs) return a.scheduledAtMs - b.scheduledAtMs;
        var ord = { acc1: 0, acc2: 1 };
        return (ord[a.account] !== undefined ? ord[a.account] : 9) - (ord[b.account] !== undefined ? ord[b.account] : 9);
      });
      // YouTube 公開待ち。(投稿履歴のYouTube URLのうち、まだ公開されていない＝非公開/予約公開中の作品)
      var ytList = (global.YtSchedule && global.YtSchedule.list) ? (global.YtSchedule.list() || []) : [];
      ytList.sort(function (a, b) {
        var pa = a.publishAt || Infinity, pb = b.publishAt || Infinity; // 公開予定時刻の早い順、時刻不明は後ろ
        if (pa !== pb) return pa - pb;
        return (b.ts || 0) - (a.ts || 0);
      });

      // Read only locally cached posting-history data; never fetch on tab open.
      var recent = el.hidden ? { today: [], yesterday: [] } : splitRecentPosts(recentPosts_(), Date.now());

      var html = '<div style="padding:12px">';
      // ① YouTube 公開待ち
      if (ytList.length) {
        html += '<div class="card">' +
          '<div class="field-label" style="margin-bottom:4px;">🎬 YouTube 公開待ち(非公開/予約公開)</div>' +
          '<div class="hint" style="margin-bottom:12px;">投稿履歴のYouTube URLのうち、まだ公開されていない作品です。(投稿履歴を更新すると最新化・公開されると自動で消えます)予約公開の正確な時刻はYouTube側の仕様で取得できないため「公開待ち」と表示します。</div>' +
          ytList.map(function (y) {
            var label = y.account === 'acc2' ? '宵桜艶帖' : '月詠み';
            var cls = y.account === 'acc2' ? 'rsv-badge-acc2' : 'rsv-badge-acc1';
            return '<div class="rsv-tab-row">' +
              '<span class="rsv-badge ' + cls + '">' + label + '</span>' +
              '<span class="rsv-tab-when">' + (y.publishAt ? fmt(y.publishAt) : '公開待ち') + '</span>' +
              '<span class="rsv-tab-text">' + esc((y.title || '(無題)').slice(0, 28)) + '</span>' +
              '<div class="rsv-tab-btns">' +
              (y.ytUrl ? '<a class="ghost rsv-sm-btn" href="' + esc(y.ytUrl) + '" target="_blank" rel="noopener">YouTube↗</a>' : '') +
              '</div></div>';
          }).join('') +
          '</div>';
      }
      // ② Bluesky 予約投稿
      html += '<div class="card">' +
        '<div class="field-label" style="margin-bottom:8px;">⏰ 予約済み投稿一覧(Bluesky)</div>' +
        (pend.length ? pend.map(function (it) {
          var label = it.account === 'acc2' ? '宵桜艶帖' : '月詠み';
          var cls = it.account === 'acc2' ? 'rsv-badge-acc2' : 'rsv-badge-acc1';
          return '<div class="rsv-tab-row">' +
            '<span class="rsv-badge ' + cls + '">' + label + '</span>' +
            '<span class="rsv-tab-when">' + fmt(it.scheduledAtMs) + (it.slotId ? ' <span title="カレンダーの枠と連携">📅</span>' : '') + '</span>' +
            '<span class="rsv-tab-text">' + esc((it.text || '').split('\n')[0].slice(0, 28)) + '</span>' +
            '<div class="rsv-tab-btns">' +
            '<button type="button" class="ghost rsv-sm-btn" data-tchange="' + it.id + '">時刻変更</button>' +
            '<button type="button" class="ghost rsv-sm-btn" data-tnow="' + it.id + '">今すぐ投稿</button>' +
            '<button type="button" class="ghost rsv-sm-btn rsv-sm-cancel" data-tcancel="' + it.id + '">取消</button>' +
            '</div></div>';
        }).join('') : '<div class="hint">Blueskyの予約はありません。</div>') +
        '</div>';
      // Keep yesterday's row DOM absent until its disclosure button is opened.
      html += '<div class="rsv-recent-toolbar"><label for="rsvRecentSort">\u4e26\u3073\u9806</label><select id="rsvRecentSort" aria-label="\u6295\u7a3f\u52d5\u753b\u306e\u4e26\u3073\u9806">' +
        '<option value="latest"' + (recentSort === 'latest' ? ' selected' : '') + '>\u6700\u65b0\u9806</option>' +
        '<option value="views"' + (recentSort === 'views' ? ' selected' : '') + '>\u518d\u751f\u6570\u304c\u591a\u3044\u9806</option>' +
        '<option value="pink"' + (recentSort === 'pink' ? ' selected' : '') + '>\u30d4\u30f3\u30af\u30af\u30ea\u30c3\u30af\u304c\u591a\u3044\u9806</option>' +
        '<option value="peak"' + (recentSort === 'peak' ? ' selected' : '') + '>\u30d4\u30fc\u30af\u518d\u751f\u6570\u304c\u9ad8\u3044\u9806</option></select></div>' +
        recentSectionHtml_('today', recent.today, '\u672c\u65e5\u6295\u7a3f\u3057\u305f\u52d5\u753b') +
        recentSectionHtml_('yesterday', recent.yesterday, '\u6628\u65e5\u6295\u7a3f\u3057\u305f\u52d5\u753b');
      html += '</div>';
      el.innerHTML = html;
      var sortEl = document.getElementById('rsvRecentSort');
      if (sortEl) sortEl.addEventListener('change', function () { recentSort = sortEl.value || 'latest'; renderTab(); });
      el.querySelectorAll('[data-recent-toggle]').forEach(function (b) {
        b.addEventListener('click', function () {
          var kind = b.getAttribute('data-recent-toggle');
          if (kind === 'today' || kind === 'yesterday') { recentOpen[kind] = !recentOpen[kind]; renderTab(); }
        });
      });
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

    // 初期描画(予約なし状態)
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', renderTab);
    else renderTab();
    document.addEventListener('go5-hist-hydrated', function (ev) {
      var page = document.getElementById('pageReserve');
      var key = ev && ev.detail && ev.detail.key ? String(ev.detail.key) : '';
      if (!page || page.hidden || !/^(?:short_hist|verify_manual|sheet_hist_raw|verify_yt)__acc[12]$/.test(key)) return;
      clearTimeout(recentHydrateTimer);
      recentHydrateTimer = setTimeout(function () {
        var y = window.scrollY || 0;
        renderTab();
        requestAnimationFrame(function () { window.scrollTo(0, y); });
      }, 80);
    });

    global.Scheduler = {
      reserve: function (item) {
        item.id = ++seq; item.status = 'pending';
        queue.push(item); reqPerm(); renderAll();
        notify('予約しました', fmt(item.scheduledAtMs));
        // カレンダー連携：枠から予約したら、その枠を「予約登録済」に書き戻す。
        if (item.slotId) { try { document.dispatchEvent(new CustomEvent('bluesky-reserved', { detail: { slotId: item.slotId, scheduledAtMs: item.scheduledAtMs, account: item.account } })); } catch (e) {} }
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

  if (typeof module !== 'undefined' && module.exports) module.exports = {
    dueItems: dueItems, postingDayStart: postingDayStart, splitRecentPosts: splitRecentPosts,
    sortRecentPosts: sortRecentPosts, recentCounts: recentCounts
  };
})(typeof window !== 'undefined' ? window : this);
