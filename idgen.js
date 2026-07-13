/**
 * idgen.js — 安定動画ID発番 ＆ YouTube videoId 抽出(純粋関数・Nodeテスト可)
 *
 * 安定動画ID＝1作品(パイプライン1回)を串刺しする背骨のキー。
 *   形式：`{acc}-{YYYYMMDD}-{HHMM}-{rand4}`(テストは先頭に `test-`)
 *   例：`acc1-20260625-1432-k7af` / `test-acc2-20260625-1432-9zx0`
 *   - 動画“作成時”(投稿前)に発番する → Bluesky の cid/post_uri に依存しない。
 *   - Driveフォルダ名・YouTube記録・Bluesky記録・シート行キー(post_id) を同一IDで揃える。
 *
 * YouTube videoId は再生数取得(将来のタスク2)が videoId ベースのため、
 * 記録時に 11文字IDを抽出して持つ。表示用URLを短縮しても videoId は不変＝カウントに影響しない。
 */
(function () {
  'use strict';

  // base36([0-9a-z])4桁の乱数文字列。同一分内のID衝突を避ける用。
  // rng は [0,1) を返す関数。(既定 Math.random)テストで差し替え可能。
  function rand4(rng) {
    rng = rng || Math.random;
    var s = '';
    for (var i = 0; i < 4; i++) s += Math.floor(rng() * 36).toString(36);
    return s;
  }

  // Date → "YYYYMMDD-HHMM"(ローカル時刻)
  function stampOf(date) {
    var d = date || new Date();
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return '' + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) +
      '-' + p(d.getHours()) + p(d.getMinutes());
  }

  // 安定動画IDを発番。acc は 'acc1'|'acc2'。(それ以外は acc1 に正規化)
  // opts.test=true でテスト接頭辞、opts.rng でテスト用乱数注入。
  function makeVideoId(acc, date, opts) {
    opts = opts || {};
    acc = (acc === 'acc2') ? 'acc2' : 'acc1';
    var id = acc + '-' + stampOf(date) + '-' + rand4(opts.rng);
    return opts.test ? ('test-' + id) : id;
  }

  // 安定動画IDからテスト判定 / アカウント抽出。(補助)
  function isTestId(id) { return /^test-/.test(String(id || '')); }
  function accOfId(id) {
    var m = String(id || '').match(/^(?:test-)?(acc[12])-/);
    return m ? m[1] : '';
  }

  // 安定動画ID(acc-YYYYMMDD-HHMM-rand)から作成日時(ms)を復元。抽出不能なら 0。
  //   投稿日は作成直後なので、投稿履歴の ts が欠けた時(シート復元でpostedAt空・手動移動等)の
  //   フォールバックとして「投稿日」に十分使える。＝月詠み✔なのに投稿日が出ないバグの再発防止。
  function tsOfId(id) {
    var m = String(id || '').match(/-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(?:-|$)/);
    if (!m) return 0;
    var d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    var t = d.getTime();
    return isFinite(t) ? t : 0;
  }

  // YouTube の watch/shorts/youtu.be/embed/live URL から 11文字 videoId を抽出。
  // 既に 11文字IDならそのまま返す。抽出不能なら ''(da.gd等の短縮URLはここでは解決不可＝
  // 貼り付け時＝短縮前の生URLから抽出する運用)。
  function youtubeId(url) {
    url = String(url || '').trim();
    if (/^[A-Za-z0-9_-]{11}$/.test(url)) return url;
    var m = url.match(/(?:youtu\.be\/|[?&]v=|\/shorts\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])/);
    return m ? m[1] : '';
  }

  // videoId → 正規 watch URL。(API入力・人間確認用。短縮はこれを元に行う)
  function youtubeWatchUrl(id) {
    return /^[A-Za-z0-9_-]{11}$/.test(String(id || '')) ? ('https://www.youtube.com/watch?v=' + id) : '';
  }

  var api = {
    rand4: rand4,
    stampOf: stampOf,
    makeVideoId: makeVideoId,
    isTestId: isTestId,
    accOfId: accOfId,
    tsOfId: tsOfId,
    youtubeId: youtubeId,
    youtubeWatchUrl: youtubeWatchUrl
  };

  if (typeof window !== 'undefined') window.IdGen = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
