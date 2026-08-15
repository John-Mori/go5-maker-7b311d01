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

  // 記録シートは作品URLそのものではなく「作品cid」を正本として持つ。
  // URL編集後の保存確認と、シート由来行の再表示で同じ変換規則を使う。
  function workCidFromUrl(url) {
    if (!url) return '';
    var s = String(url);
    var lm = s.match(/[?&]lurl=([^&]+)/);
    if (lm) {
      try {
        var decoded = decodeURIComponent(lm[1]);
        var inner = workCidFromUrl(decoded);
        if (inner) return inner;
      } catch (e) {}
    }
    var books = s.match(/book\.dmm\.(com|co\.jp)\/product\/([^/?&#\s]+)(?:\/([^/?&#\s]+))?/);
    if (books) return books[3] || books[2];
    var cid = s.match(/cid=([^/?&\s]+)/);
    return cid ? cid[1] : '';
  }

  function workUrlFromCid(cid) {
    cid = String(cid || '').trim();
    if (!cid) return '';
    if (/^d_/.test(cid)) return 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/';
    if (/^\d+$/.test(cid)) return 'https://book.dmm.com/product/' + cid + '/';
    return '';
  }

  // POSTはGASのCORS制約で本文を読めないため、action=history の読み直し結果で保存を確認する。
  // 現在のhistory APIで確認可能な項目だけを比較し、videoIdの別行を成功扱いしない。
  function historyHasEdit(items, expected) {
    expected = expected || {};
    var wantVid = String(expected.videoId || '');
    if (!wantVid) return false;
    var row = null;
    (items || []).some(function (x) {
      if (x && String(x.videoId || '') === wantVid) { row = x; return true; }
      return false;
    });
    if (!row) return false;
    if (expected.youtubeUrl && String(row.youtubeUrl || '') !== String(expected.youtubeUrl)) return false;
    if (expected.workUrl) {
      // 生の作品URL列(GAS 2026-07-29D以降)が一致すれば成功。cidを復元できない階層(FANZA動画等)も
      // rawOk(生URL一致)で確認できる。
      // ★cid照合は「作品cid列は投稿時からほぼ必ず埋まっている」ため、作品URLを入れ直す編集では
      //   POSTがシートに届く前でも即trueになる偽陽性を生む=保持patchを早期破棄して編集が一瞬で消える
      //   (症状: 編集→保存で反映されず消失 / リロードで作品URLがまた消える)。現行GASは作品URL列を
      //   常にキーとして返す(空でも '')ため、row.workUrl===undefined=作品URL列を持たない旧GAS応答の
      //   時だけcid照合へフォールバックする。列を持つ現行GASでは rawOk を必須にして偽陽性を封じる。
      var rawOk = String(row.workUrl || '') === String(expected.workUrl);
      if (row.workUrl === undefined) {
        var wantCid = workCidFromUrl(expected.workUrl);
        var cidOk = !!wantCid && String(row.cid || '') === wantCid;
        if (!cidOk) return false;
      } else if (!rawOk) {
        return false;
      }
    }
    if (expected.workState && String(row.workState || '') !== String(expected.workState)) return false;
    return true;
  }

  // GAS(action=history)の1行 → 表示専用アイテム。render()が期待する形へ寄せる。
  //   ytUrl は yt-clicks.js の `ymap[k] || it.ytUrl` 経路にそのまま乗るキー名(youtubeUrl→ytUrl)。
  function toDisplayItem_(x) {
    var ts = 0;
    try { var t = Date.parse((x && x.postedAt) || ''); if (!isNaN(t)) ts = t; } catch (e) {}
    var cid = String((x && x.cid) || '');
    var snap = snapFromSheet_(x); // 投稿当時の価格(シートに記録あり)を復元
    var item = {
      postUri: String((x && x.postUri) || ''),
      videoId: String((x && x.videoId) || ''),
      title: String((x && x.title) || ''),
      ts: ts,
      shortUrl: String((x && x.shortUrl) || ''),
      shareUrl: String((x && x.shareUrl) || ''),
      cid: cid,
      // 作品URLはシートが持つ生URLを優先。無い旧行だけ cid から復元(FANZA動画等の cid は復元不可＝空になるため)。
      workUrl: ((x && x.workUrl) ? String(x.workUrl) : '') || workUrlFromCid(cid),
      workState: String((x && x.workState) || ''),
      ytUrl: String((x && x.youtubeUrl) || ''),
      workShortUrl: String((x && x.workShortUrl) || ''), // 導線2(作品クリック=ピンク矢印)の計測URL
      platform: (function (p) { return (p === 'x' || p === 'bsky') ? p : ''; })(String((x && x.platform) || '')), // 投稿先(X/Bsky)手動指定＝X↗/Bsky↗表示
      _fromSheet: true // 表示バッジ用: この端末の履歴には無くシートから補った行
    };
    if (snap) item.fanzaSnap = snap; // 当時価格があるときだけ付与(render は it.fanzaSnap を見て表示)
    return item;
  }

  // GAS history 行の価格列 → 当時価格スナップ {price,listPrice,discountPct,at}。
  //   割引後price(数値)が無ければ null(＝当時価格は復元しない)。listPrice/pct は数値のときだけ採用。
  function snapFromSheet_(x) {
    if (!x) return null;
    function n(v) { if (v === '' || v == null) return null; var f = Number(v); return isNaN(f) ? null : f; }
    var price = n(x.fanzaPrice);
    if (price == null) return null;
    var lp = n(x.fanzaListPrice), pct = n(x.fanzaDiscountPct);
    return { price: price, listPrice: lp, discountPct: pct != null ? pct : 0, at: String(x.fanzaFetchedAt || '') };
  }

  // YouTube URL/IDを「11文字の動画ID」へ正規化する同一性キー。★idgen.youtubeId と同一仕様。
  //   youtu.be/x ・ youtube.com/watch?v=x ・ youtube.com/shorts/x は URL文字列は違うが同じ動画=1投稿。
  //   以前は生URLの完全一致で畳んでいたため、端末や経路でURL形式が違うと同じ投稿がシート分裂行として
  //   2枚に並んだ(Chami報告2026-08-12「MacBookに同期したら同じ投稿履歴が2つ」の一因)。11文字IDに揃える。
  //   IdGen があればそれを正本に使い、モジュール単体(テスト)では同じ抽出をフォールバックで持つ。
  function ytKey_(url) {
    var s = String(url || '').trim();
    if (!s) return '';
    var id = (root && root.IdGen && root.IdGen.youtubeId) ? (root.IdGen.youtubeId(s) || '') : '';
    if (!id) {
      if (/^[A-Za-z0-9_-]{11}$/.test(s)) id = s;
      else { var m = s.match(/(?:youtu\.be\/|[?&]v=|\/shorts\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])/); id = m ? m[1] : ''; }
    }
    return id || s; // 11文字IDに正規化できない値は生文字列で従来どおり完全一致
  }

  // localItems(allItems()相当) と sheetItems(GAS action=history の items) から、
  // 「ローカルに無い行だけ」を表示専用アイテムに変換して返す。ローカルにあれば出さない。
  function mergeSheetExtras(localItems, sheetItems) {
    var haveUri = {}, haveVid = {}, haveYt = {};
    (localItems || []).forEach(function (it) {
      if (!it) return;
      if (it.postUri) haveUri[String(it.postUri)] = true;
      if (it.videoId) haveVid[String(it.videoId)] = true;
      // ★YouTube動画URLも同一性キーに使う。1動画=1投稿なので、videoId/postUriが食い違っても
      //   同じytUrlならローカルとシートは同じ投稿=二重表示させない(Chami報告2026-07-29「シート由来か
      //   そうでないかで分裂」。短縮リンク再入力で背骨IDが割れても、同じYT動画なら1枚に畳む)。
      var yt = ytKey_(it.ytUrl || it.youtubeUrl);
      if (yt) haveYt[yt] = true;
    });
    var seenUri = {}, seenVid = {}, seenYt = {};
    var extra = [];
    (sheetItems || []).forEach(function (x) {
      if (!x) return;
      var uri = String(x.postUri || '').trim();
      var vid = String(x.videoId || '').trim();
      var yt = ytKey_(x.youtubeUrl || x.ytUrl);
      // YouTube動画URL一致=ローカルに同じ投稿が既にある(または同一シート内の重複)=畳む。
      //   ★これは postUri/videoId の前に効かせる(背骨IDが割れていても同じYT動画なら1枚)。
      if (yt) {
        if (haveYt[yt] || seenYt[yt]) return;
        seenYt[yt] = true;
      }
      if (uri) {
        if (haveUri[uri] || seenUri[uri]) return; // ローカル優先 or 同一シート内の重複
        seenUri[uri] = true;
      } else if (vid) {
        if (haveVid[vid] || seenVid[vid]) return;
        seenVid[vid] = true;
      } else if (!yt) {
        return; // 一致キー(uri/vid/yt)が全く無い行は重複判定できないため安全側でスキップ
      }
      extra.push(toDisplayItem_(x));
    });
    return extra;
  }

  // 投稿履歴の「動画で使った画像」を決める。
  // 新しい履歴単位の used があればそれだけを使う。旧データは互換のため候補画像の先頭1枚だけに限定し、
  // 候補タブの2枚目以降が投稿履歴へ混ざることを防ぐ。
  function historyUsedImages(usedImages, legacyCandidateImages, usedRecordKnown) {
    var used = Array.isArray(usedImages) ? usedImages.filter(Boolean) : [];
    if (used.length) return used;
    if (usedRecordKnown) return []; // 明示的に空へした履歴。旧候補画像を復活させない
    var legacy = Array.isArray(legacyCandidateImages) ? legacyCandidateImages.filter(Boolean) : [];
    return legacy.length ? [legacy[0]] : [];
  }

  // 投稿履歴カードの同一性キー。共有され得る短縮URLより、投稿URI/背骨ID/YouTube IDを優先する。
  // 旧版は postUri→shortUrl→videoId の順だったため、セール会場URLを共有した別作品が同じDOM/編集キーに
  // なり得た。canonical は強キー優先、historyItemKeys は旧短縮キーも後方互換の読取候補として返す。
  function historyItemKeys(it) {
    if (!it) return [];
    var out = [], seen = {};
    function push(k) { k = String(k || ''); if (k && !seen[k]) { seen[k] = 1; out.push(k); } }
    if (it.manual) push(it.id || '');
    if (it.postUri) push('u:' + String(it.postUri));
    if (it.videoId) push('v:' + String(it.videoId));
    var yt = ytKey_(it.ytUrl || it.youtubeUrl || '');
    if (yt) push('y:' + yt);
    if (it.shortUrl) push('s:' + String(it.shortUrl)); // 旧行の読取互換・強キーが無い時だけcanonical
    return out;
  }

  function historyItemKey(it) {
    var keys = historyItemKeys(it);
    return keys.length ? keys[0] : '';
  }

  // verify_yt等の旧マップは shortUrl キーで保存済みのことがある。canonical変更後も値を失わない読取。
  function historyMapValue(map, it) {
    map = map || {};
    var keys = historyItemKeys(it);
    for (var i = 0; i < keys.length; i++) {
      if (Object.prototype.hasOwnProperty.call(map, keys[i])) return map[keys[i]];
    }
    return '';
  }

  // 投稿完了・アカウント移送・表示マージが同じ重複判定を使うための単一権威。
  // shortUrl一致は、両側とも投稿URI/背骨ID/YouTube IDを持たない旧い「薄い行」同士に限定する。
  function findDuplicate(arr, incoming, getYt) {
    incoming = incoming || {};
    function ytOf(x) {
      var supplied = '';
      try { supplied = typeof getYt === 'function' ? (getYt(x) || '') : ''; } catch (_) {}
      return ytKey_(supplied || (x && (x.ytUrl || x.youtubeUrl)) || '');
    }
    var inYt = ytOf(incoming);
    var inStrong = !!(incoming.postUri || incoming.videoId || inYt);
    for (var i = 0; i < (arr || []).length; i++) {
      var cur = arr[i] || {};
      if (incoming.postUri && cur.postUri && String(incoming.postUri) === String(cur.postUri)) return { index: i, matchedBy: 'postUri' };
      if (incoming.videoId && cur.videoId && String(incoming.videoId) === String(cur.videoId)) return { index: i, matchedBy: 'videoId' };
      var curYt = ytOf(cur);
      if (inYt && curYt && inYt === curYt) return { index: i, matchedBy: 'ytUrl' };
      var curStrong = !!(cur.postUri || cur.videoId || curYt);
      if (!inStrong && !curStrong && incoming.shortUrl && cur.shortUrl && String(incoming.shortUrl) === String(cur.shortUrl)) {
        return { index: i, matchedBy: 'shortUrl' };
      }
    }
    return { index: -1, matchedBy: '' };
  }

  var api = {
    mergeSheetExtras: mergeSheetExtras,
    findDuplicate: findDuplicate,
    historyItemKeys: historyItemKeys,
    historyMapValue: historyMapValue,
    historyItemKey: historyItemKey,
    historyUsedImages: historyUsedImages,
    workCidFromUrl: workCidFromUrl,
    workUrlFromCid: workUrlFromCid,
    historyHasEdit: historyHasEdit,
    ytKey: ytKey_, // YouTube同一性キー(11文字ID正規化)・テスト用に露出
    _toDisplayItem: toDisplayItem_ // テスト用に露出
  };
  if (typeof window !== 'undefined') root.HistMerge = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
