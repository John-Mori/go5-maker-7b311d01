/**
 * integration.js — スケジュール(📅カレンダー iframe) と 本体(動画作成/投稿) の橋渡し（Phase2 一気通貫）
 * - iframe からの「🎬作る / 🦋投稿」メッセージ → 該当タブへ切替＋対象スロットを表示
 * - 投稿成功イベント(bluesky-posted) → iframe のスロットへ status/URL を書き戻し
 * 同一オリジン前提。スロットの正本は iframe 側(localStorage 共有)に置き、本体は文脈表示と書き戻しのみ行う。
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var activeSlot = null;

  function fmtSlot(s) {
    return (s.date || '') + ' ' + (s.time || '') + '　' + (s.role || '');
  }
  function setBanner(text, done) {
    ['slotCtxMovie', 'slotCtxPost'].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      if (text) {
        el.innerHTML = (done ? '✅ ' : '🎯 対象スロット：') + '<b>' + text + '</b>' +
          (done ? '' : ' <button type="button" class="slot-ctx-clear" aria-label="解除">×</button>');
        el.hidden = false;
        var x = el.querySelector('.slot-ctx-clear');
        if (x) x.addEventListener('click', clearSlot);
      } else { el.hidden = true; el.innerHTML = ''; }
    });
  }
  function clearSlot() { activeSlot = null; window.__activeSlot__ = null; setBanner(''); }

  // ISO/日時文字列 → <input type="datetime-local"> 用 "YYYY-MM-DDTHH:MM"
  function toLocalInput(s) {
    if (!s) return '';
    var d = new Date(String(s).replace(' ', 'T'));
    if (isNaN(d.getTime())) return '';
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + 'T' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  // iframe → 親
  window.addEventListener('message', function (ev) {
    var d = ev.data;
    if (!d || d.source !== 'sch-calendar' || !d.slot) return;
    if (d.type === 'slot-create' || d.type === 'slot-post') {
      activeSlot = d.slot;
      window.__activeSlot__ = d.slot;          // 他モジュールから参照可能に
      setBanner(fmtSlot(d.slot), false);
      var tabId = (d.type === 'slot-create') ? 'tabMovie' : 'tabPost';
      var b = $(tabId);
      if (b) b.click();                        // affiliate.js の showTab が発火
      // 予約時刻に枠の予定時刻をプリフィル
      var sa = $('postSchedAt');
      if (sa && d.slot.scheduled_at) { var v = toLocalInput(d.slot.scheduled_at); if (v) sa.value = v; }
      try { window.scrollTo(0, 0); } catch (e) {}
    }
  });

  // 投稿成功（即時/単独/予約）→ iframe のスロットへ書き戻し
  document.addEventListener('bluesky-posted', function (e) {
    var d = (e && e.detail) || {};
    var slotId = d.slotId || (activeSlot && activeSlot.id);  // 予約はdetail.slotId、手動はactiveSlot
    if (!slotId) return;
    var f = $('calFrame');
    if (f && f.contentWindow) {
      f.contentWindow.postMessage({
        target: 'sch-calendar', type: 'slot-writeback',
        id: slotId, status: '公開済',
        post_uri: d.post_uri || '', post_url: d.post_url || '',
        short_url: d.short_url || '', url: d.affiliate || d.post_url || '',
        posted_at: d.posted_at || ''
      }, '*');
    }
    if (activeSlot && activeSlot.id === slotId) {
      setBanner((activeSlot.date || '') + ' を「公開済」に更新しました', true);
      activeSlot = null; window.__activeSlot__ = null;
      setTimeout(function () { setBanner(''); }, 5000);
    }
  });
})();
