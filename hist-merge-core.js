/**
 * hist-merge-core.js — 投稿履歴一覧の「シート由来・表示専用マージ」の純粋関数。(Go5HistMerge)
 *
 * 【解く問題】投稿履歴一覧(yt-clicks.js)はこの端末の localStorage(short_hist__/verify_manual__)
 *   だけを描画していた。GAS(action=history)は行を丸ごと返せるのに、既存ローカル行への
 *   欠損補完(restoreYtFromSheet_)にしか使われておらず、ローカルに無い行(＝別端末で投稿した分)は
 *   一生表示されなかった。「消えた」のではなく「その端末には元々無い」が真因(Chami報告2026-07-21)。
 *
 * 【設計】表示だけをマージする。localStorage(short_hist__)へは絶対に書き戻さない。
 *   INC-112の教訓(JSON破損時に[]を返し、それを土台に上書きして履歴全消し)と同じ危険を
 *   新しい経路(このマージ)に持ち込まないため。失敗しても「表示が増えない」だけで、
 *   既存のローカル表示は無傷(read-before-write ならぬ「書かない」が最も安全)。
 *
 *   重複排除のキーは postUri を優先し、無ければ videoId。どちらも無い行(古いシート行等)は
 *   一致判定ができないため安全側でスキップする(＝重複を作るくらいなら出さない)。
 *   ローカル行が既にあるならローカル側を常に優先する(ローカルには手動編集した情報が入り得る)。
 *
 * 使い方：ブラウザでは window.HistMerge、Node(テスト)では module.exports。
 */
(function (root) {
  'use strict';

  // GAS(action=history)の1行 → 表示専用アイテム。render()が期待する形へ寄せる。
  //   ytUrl は yt-clicks.js の `ymap[k] || it.ytUrl` 経路にそのまま乗るキー名(youtubeUrl→ytUrl)。
  function toDisplayItem_(x) {
    var ts = 0;
    try { var t = Date.parse((x && x.postedAt) || ''); if (!isNaN(t)) ts = t; } catch (e) {}
    return {
      postUri: String((x && x.postUri) || ''),
      videoId: String((x && x.videoId) || ''),
      title: String((x && x.title) || ''),
      ts: ts,
      shortUrl: String((x && x.shortUrl) || ''),
      shareUrl: String((x && x.shareUrl) || ''),
      workState: String((x && x.workState) || ''),
      ytUrl: String((x && x.youtubeUrl) || ''),
      _fromSheet: true // 表示バッジ用: この端末の履歴には無くシートから補った行
    };
  }

  // localItems(allItems()相当) と sheetItems(GAS action=history の items) から、
  // 「ローカルに無い行だけ」を表示専用アイテムに変換して返す。ローカルにあれば出さない。
  function mergeSheetExtras(localItems, sheetItems) {
    var haveUri = {}, haveVid = {};
    (localItems || []).forEach(function (it) {
      if (!it) return;
      if (it.postUri) haveUri[String(it.postUri)] = true;
      if (it.videoId) haveVid[String(it.videoId)] = true;
    });
    var seenUri = {}, seenVid = {};
    var extra = [];
    (sheetItems || []).forEach(function (x) {
      if (!x) return;
      var uri = String(x.postUri || '').trim();
      var vid = String(x.videoId || '').trim();
      if (uri) {
        if (haveUri[uri] || seenUri[uri]) return; // ローカル優先 or 同一シート内の重複
        seenUri[uri] = true;
      } else if (vid) {
        if (haveVid[vid] || seenVid[vid]) return;
        seenVid[vid] = true;
      } else {
        return; // 一致キーが無い行は重複判定できないため安全側でスキップ
      }
      extra.push(toDisplayItem_(x));
    });
    return extra;
  }

  var api = {
    mergeSheetExtras: mergeSheetExtras,
    _toDisplayItem: toDisplayItem_ // テスト用に露出
  };
  if (typeof window !== 'undefined') root.HistMerge = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
