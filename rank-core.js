/**
 * rank-core.js — ランキングの「同一YouTube動画を1件へ field-level 統合」する純粋関数。(Go5RankCore)
 *
 * 【解く問題(真因1)】ランキングは channelItemsFor_ が返す「ローカル履歴＋シート由来行」を
 *   vid(YouTube動画ID)で重複排除していたが、先に出た行(=ローカル)を丸ごと残し、後ろのシート行を
 *   丸ごと捨てていた。ローカル行の shortUrl が空でも、shortUrl を持つ完全なシート行が失われ、
 *   「投稿履歴では出るクリックがランキングに出ない」非対称が残った(Codex監査 2026-08-03・真因1)。
 *
 * 【設計】whole-record 優先をやめ、field ごとに合成する。
 *   - 先頭行(ローカル優先=既存の表示を壊さない)を土台にする。
 *   - 空欄(null/'')だけを後続行(多くはシート由来の完全行)で補完する。★空文字で正本を消さない。
 *   - クリック計測URLは1本選ばず、全候補を clickUrls/workClickUrls に集合として保持する
 *     (postClicks_ が code 単位で重複なく合算する。Codex §6.2/§6.3)。
 *   - mergeUrls(合算)は全行の和集合。
 *   - カテゴリ属性は「未設定(undefined/null)なら真値で補完」だけ=明示 false は上書きしない。
 *
 * 使い方：ブラウザでは window.Go5RankCore、Node(テスト)では module.exports。
 */
(function (root) {
  'use strict';

  // 空欄だけを後続行で補完してよい文字列フィールド(★空文字で正本を消さない)。
  var FILL_KEYS = ['shortUrl', 'workShortUrl', 'shareUrl', 'workShareUrl',
    'postUri', 'postUrl', 'workUrl', 'ytUrl', 'title', 'workState', 'price', 'thumbUrl'];

  function isEmpty(v) { return v == null || v === ''; }
  function pushUniq(arr, v) { if (v && arr.indexOf(v) === -1) arr.push(v); }

  /**
   * rows: [{ it, vid, yt, acct }] を先勝ち順(ローカル→シート)で受け、同一 vid を1件へ畳む。
   * attrKeys: カテゴリ属性キー(ATTR_DEFS.map(a=>a.key))。空でも可。
   * 返り値: 同形の配列(it は統合済みクローン。vid/yt/acct は先頭行のもの)。
   */
  function mergeByVid(rows, attrKeys) {
    attrKeys = attrKeys || [];
    var order = [], byVid = {};
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!row || !row.vid) continue;
      var it = row.it || {};
      if (!byVid[row.vid]) {
        var canon = {};
        for (var p in it) if (Object.prototype.hasOwnProperty.call(it, p)) canon[p] = it[p];
        canon.clickUrls = []; pushUniq(canon.clickUrls, it.shortUrl);
        canon.workClickUrls = []; pushUniq(canon.workClickUrls, it.workShortUrl);
        canon.mergeUrls = Array.isArray(it.mergeUrls) ? it.mergeUrls.slice() : [];
        var wrap = { it: canon, vid: row.vid, yt: row.yt, acct: row.acct };
        byVid[row.vid] = wrap; order.push(wrap);
      } else {
        var w = byVid[row.vid], c = w.it;
        for (var k = 0; k < FILL_KEYS.length; k++) {
          var key = FILL_KEYS[k];
          if (isEmpty(c[key]) && !isEmpty(it[key])) c[key] = it[key];
        }
        if (isEmpty(w.yt) && !isEmpty(row.yt)) w.yt = row.yt;
        if (!c.ts && it.ts) c.ts = it.ts;
        for (var a = 0; a < attrKeys.length; a++) {
          var ak = attrKeys[a];
          if (c[ak] == null && it[ak]) c[ak] = it[ak]; // 未設定のみ補完・明示falseは触らない
        }
        pushUniq(c.clickUrls, it.shortUrl);
        pushUniq(c.workClickUrls, it.workShortUrl);
        if (Array.isArray(it.mergeUrls)) for (var m = 0; m < it.mergeUrls.length; m++) pushUniq(c.mergeUrls, it.mergeUrls[m]);
      }
    }
    return order;
  }

  var api = { mergeByVid: mergeByVid };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Go5RankCore = api;
})(typeof window !== 'undefined' ? window : this);
