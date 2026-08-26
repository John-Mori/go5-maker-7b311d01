/*
 * core/regen-identity.js — 投稿履歴からドラフト実体を引き直す単一権威。
 *
 * 古い投稿履歴には、現在のドラフトIDではなく11文字のYouTube IDだけが
 * videoId欄へ残っているものがある。その値をそのままIDB/R2キーに使うと、
 * 元データが別の内部IDで保存されているため必ず空振りする。
 *
 * 解決順:
 *   1. videoId完全一致
 *   2. 同一チャンネル＋作品CID一致
 *   3. 同一チャンネル＋題名一致(複数なら最新)
 * チャンネルが指定された時は、別チャンネルの同題名へは絶対に倒さない。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.Go5RegenIdentity = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  function normText(v) {
    var s = String(v == null ? '' : v).trim().replace(/\s+/g, ' ');
    try { return s.normalize('NFKC'); } catch (e) { return s; }
  }

  // 動画・Driveデータ用の題名。YouTube題名の末尾へ付けた、空白区切りの
  // #タグ群だけを全て外す。タグ名は運用で変わるため固定リストにしない。
  // 「C#入門」のように作品名の途中へ現れる # は、直前が空白でないので保持する。
  function cleanTitle(v) {
    var s = String(v == null ? '' : v).trim().replace(/\s+/g, ' ');
    return s.replace(/(?:^|\s)#[^\s#]+(?:\s*#[^\s#]+)*\s*$/, '').trim();
  }

  function cidFromValue(v) {
    var s = String(v == null ? '' : v);
    var m = s.match(/[?&]cid=([^&#\s]+)/i);
    if (!m) return '';
    try { return decodeURIComponent(m[1]).toLowerCase(); } catch (e) { return String(m[1]).toLowerCase(); }
  }

  function cidOf(x) {
    if (!x) return '';
    var direct = x.cid || (x.srcMark && x.srcMark.cid) || '';
    if (direct) return normText(direct).toLowerCase();
    return cidFromValue(x.workUrl || x.affiliateUrl || x.workShortUrl || '');
  }

  function sameAccount(item, account) {
    if (!account) return true;
    return String((item && item.account) || '') === account;
  }

  function newest(items) {
    if (!items || !items.length) return null;
    return items.slice().sort(function (a, b) {
      return ((b && (b.ts || b.addedAt || b.videoReadyAt)) || 0) - ((a && (a.ts || a.addedAt || a.videoReadyAt)) || 0);
    })[0] || null;
  }

  function result(meta, matchBy, candidates) {
    return { meta: meta || null, matchBy: matchBy || '', candidates: candidates ? candidates.length : 0 };
  }

  function resolve(locator, items) {
    locator = locator || {};
    items = (items || []).filter(function (x) { return !!(x && x.id); });
    var account = String(locator.account || '');
    var scoped = items.filter(function (x) { return sameAccount(x, account); });
    var videoId = String(locator.videoId || '');
    var title = normText(cleanTitle(locator.title || ''));
    var cid = cidOf(locator);
    var matches;

    if (videoId) {
      matches = scoped.filter(function (x) { return String(x.videoId || '') === videoId; });
      if (matches.length) return result(newest(matches), 'videoId', matches);
    }
    if (cid) {
      matches = scoped.filter(function (x) { return cidOf(x) === cid; });
      if (matches.length) return result(newest(matches), 'cid', matches);
    }
    if (title) {
      matches = scoped.filter(function (x) { return normText(cleanTitle(x.title || '')) === title; });
      if (matches.length) return result(newest(matches), 'account_title', matches);
    }
    return result(null, '', []);
  }

  function isLegacyYouTubeId(v) {
    return /^[A-Za-z0-9_-]{11}$/.test(String(v || ''));
  }

  return {
    resolve: resolve,
    cidOf: cidOf,
    normText: normText,
    cleanTitle: cleanTitle,
    isLegacyYouTubeId: isLegacyYouTubeId,
  };
});
