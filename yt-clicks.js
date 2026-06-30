/**
 * yt-clicks.js — 検証タブの「再生数・クリック数（投稿別）」一覧。
 *
 * 投稿ごとに：
 *   ・短縮URLのクリック数 … link-worker /api/stats（go5-short）から取得（共有シークレットで読み取り）。
 *   ・YouTube動画の再生数・投稿日時・タイトル … YouTube Data API v3（端末内のAPIキー）から取得。
 *
 * 行の見出し日時は「YouTubeに投稿した時刻（snippet.publishedAt）」を表示する（動画の作成時刻ではない）。
 * 並び順：YouTube投稿日時が新しいものほど上。YouTube URL未入力＝投稿日時不明のものは末尾へ。
 *
 * データ源：
 *   ・端末内の短縮URL履歴 short_hist__<acct>（bluesky.js が投稿のたびに記録）
 *   ・手動追加分 verify_manual__<acct>（このタブの「手動で追加」）
 *   ・各行のYouTube動画URL verify_yt__<acct>（行ごとに入力・ウィザードが自動プリフィル）
 * 完全クライアントサイド。APIキーはこの端末内だけに保存（リポジトリには置かない）。
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  if (!$('ytClickList')) return;

  function acct() { try { return localStorage.getItem('current_account') || 'acc1'; } catch (e) { return 'acc1'; } }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  var COMMON_TAGS = ['#マンガ紹介', '#漫画', '#アニメ', '#anime'];
  function stripCommonTags(t) {
    var r = String(t || '');
    COMMON_TAGS.forEach(function (tag) { r = r.split(tag).join(''); });
    return r.replace(/\s+/g, ' ').trim();
  }
  function missingCommonTags(t) { return COMMON_TAGS.some(function (tag) { return String(t || '').indexOf(tag) < 0; }); }
  function histKey() { return 'short_hist__' + acct(); }
  function manualKey() { return 'verify_manual__' + acct(); }
  function ytMapKey() { return 'verify_yt__' + acct(); }
  function loadArr(k) { try { var a = JSON.parse(localStorage.getItem(k) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
  function saveArr(k, a) { try { localStorage.setItem(k, JSON.stringify(a)); } catch (e) {} }
  function loadHist() { return loadArr(histKey()); }
  function loadManual() { return loadArr(manualKey()); }
  function loadYtMap() { try { return JSON.parse(localStorage.getItem(ytMapKey()) || '{}') || {}; } catch (e) { return {}; } }
  function saveYtMap(m) { try { localStorage.setItem(ytMapKey(), JSON.stringify(m)); } catch (e) {} }
  function apiKey() { try { return (localStorage.getItem('yt_api_key') || '').trim(); } catch (e) { return ''; } }
  function itemKey(it) { if (it.manual) return it.id; return it.postUri ? ('u:' + it.postUri) : ('s:' + (it.shortUrl || '')); }
  function num(n) { try { return Number(n).toLocaleString(); } catch (e) { return String(n); } }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  function setStatus(m) { var e = $('ytClickStatus'); if (e) e.textContent = m || ''; }
  function ytIdOf(url) { return (url && window.IdGen && window.IdGen.youtubeId) ? (window.IdGen.youtubeId(url) || '') : ''; }

  // 表示する全アイテム（履歴＋手動追加）を結合。manualOnly=true の手動短縮URL履歴は除外。
  function allItems() { return loadHist().filter(function (it) { return !it.manualOnly; }).concat(loadManual()); }

  // 投稿時刻(ts)等から背骨ID(videoId)を生成。idgen があれば流用、無ければ同形式で自前生成。
  function genVideoId(ts) {
    var d = (ts && ts > 0) ? new Date(ts) : new Date();
    if (window.IdGen && window.IdGen.makeVideoId) { try { return window.IdGen.makeVideoId(acct(), d); } catch (e) {} }
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    var stamp = '' + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '-' + p(d.getHours()) + p(d.getMinutes());
    var r = ''; for (var i = 0; i < 4; i++) r += Math.floor(Math.random() * 36).toString(36);
    return acct() + '-' + stamp + '-' + r;
  }
  // この履歴を正とし、IDが未付与のアイテムへ背骨IDを付与・永続化（投稿履歴=スプレッドシートの行キー）。
  function ensureIds() {
    var hist = loadHist(), c1 = false;
    hist.forEach(function (it) { if (!it.videoId) { it.videoId = genVideoId(it.ts); c1 = true; } });
    if (c1) saveArr(histKey(), hist);
    var man = loadManual(), c2 = false;
    man.forEach(function (it) { if (!it.videoId) { it.videoId = genVideoId(it.ts); c2 = true; } });
    if (c2) saveArr(manualKey(), man);
  }

  // 短縮URLから go5-short のコードを抽出（自前ワーカーの払い出しURLのみ対象）。
  function codeOf(shortUrl) {
    var w = (window.Go5Short && window.Go5Short.WORKER_URL) || '';
    if (!w || !shortUrl) return '';
    var base = w.replace(/\/+$/, '');
    if (shortUrl.indexOf(base + '/') !== 0) return '';
    var rest = shortUrl.slice(base.length + 1).split(/[/?#]/)[0];
    return /^[0-9A-Za-z]+$/.test(rest) ? rest : '';
  }
  function fetchClicks(code) {
    var w = window.Go5Short; if (!w || !code) return Promise.resolve(null);
    var u = w.WORKER_URL.replace(/\/+$/, '') + '/api/stats?code=' + encodeURIComponent(code) + '&secret=' + encodeURIComponent(w.SHARED_SECRET);
    return fetch(u).then(function (r) { return r.json(); }).then(function (j) { return (j && j.ok && typeof j.clicks === 'number') ? j.clicks : null; }).catch(function () { return null; });
  }
  // 複数の動画ID → {views, publishedAt(ms), title}（videos.list は parts に関わらず1回1ユニット・最大50件）。
  function fetchVideos(ids) {
    var key = apiKey();
    var uniq = ids.filter(function (v, i, a) { return v && a.indexOf(v) === i; });
    if (!key || !uniq.length) return Promise.resolve({});
    var url = 'https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id=' + uniq.slice(0, 50).join(',') + '&key=' + encodeURIComponent(key);
    return fetch(url).then(function (r) { return r.json(); }).then(function (j) {
      var out = {};
      ((j && j.items) || []).forEach(function (it) {
        if (!it || !it.id) return;
        var rec = {};
        if (it.statistics) rec.views = parseInt(it.statistics.viewCount || '0', 10);
        if (it.snippet) { rec.title = it.snippet.title || ''; var t = Date.parse(it.snippet.publishedAt || ''); if (!isNaN(t)) rec.published = t; }
        out[it.id] = rec;
      });
      if (j && j.error) out.__error = (j.error.message || 'YouTube APIエラー');
      return out;
    }).catch(function () { return {}; });
  }

  var clicksCache = {};    // code -> clicks
  var viewsCache = {};     // videoId -> views
  var publishedCache = {}; // videoId -> publishedAt(ms)
  var titleCache = {};     // videoId -> YouTubeタイトル
  var lastErr = '';

  // 並び替え用：YouTube投稿日時(known)があればそれ、無ければ末尾グループへ。
  function sortItems(items, ymap) {
    var arr = items.map(function (it, i) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var hasUrl = !!vid;
      var pub = (vid && (vid in publishedCache)) ? publishedCache[vid] : null;
      var group = hasUrl ? 1 : 0;
      var t = (pub != null) ? pub : (it.ts || 0);
      return { it: it, i: i, group: group, t: t };
    });
    arr.sort(function (a, b) {
      if (a.group !== b.group) return a.group - b.group;
      if (b.t !== a.t) return b.t - a.t;
      return a.i - b.i;
    });
    return arr.map(function (x) { return x.it; });
  }

  // ── モーダル ──────────────────────────────────────────────────────────────
  var _saveCb = null;

  function injectModal_() {
    if ($('veditOverlay')) return;
    var d = document.createElement('div');
    d.id = 'veditOverlay';
    d.className = 'vedit-overlay';
    d.hidden = true;
    d.innerHTML =
      '<div class="vedit-modal">' +
        '<p class="vedit-title" id="veditTitle">URL を編集</p>' +
        '<p class="vedit-error" id="veditError" hidden></p>' +
        '<label class="vedit-field">YouTube URL' +
          '<input id="veditYt" type="url" inputmode="url" autocomplete="off" placeholder="https://youtu.be/…（省略可）">' +
        '</label>' +
        '<label class="vedit-field">Bluesky 投稿URL' +
          '<input id="veditBsky" type="url" inputmode="url" autocomplete="off" placeholder="https://bsky.app/… または短縮URL（省略可）">' +
        '</label>' +
        '<label class="vedit-field">作品URL（DMM/FANZAの商品ページURL）' +
          '<input id="veditWork" type="url" inputmode="url" autocomplete="off" placeholder="https://www.dmm.co.jp/…（省略可）">' +
        '</label>' +
        '<label class="vedit-chara">' +
          '<input id="veditChara" type="checkbox">' +
          '<span>キャラ（アニメ・ゲーム等の実在キャラの二次創作）</span>' +
        '</label>' +
        '<div class="vedit-actions">' +
          '<button id="veditCancel" type="button">キャンセル</button>' +
          '<button id="veditSave" type="button">保存</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(d);
    $('veditCancel').addEventListener('click', closeModal_);
    d.addEventListener('click', function (e) { if (e.target === d) closeModal_(); });
    $('veditSave').addEventListener('click', function () {
      if (typeof _saveCb !== 'function') return;
      var cb = _saveCb;
      _saveCb = null;
      cb(
        ($('veditYt').value || '').trim(),
        ($('veditBsky').value || '').trim(),
        ($('veditWork').value || '').trim(),
        !!($('veditChara') && $('veditChara').checked)
      );
      var o = $('veditOverlay');
      if (o && !o.hidden) _saveCb = cb;
    });
  }

  function closeModal_() {
    var o = $('veditOverlay'); if (o) o.hidden = true;
    _saveCb = null;
  }

  function openModal_(title, ytVal, bskyVal, workVal, charaVal, onSave) {
    injectModal_();
    $('veditTitle').textContent = title;
    $('veditYt').value = ytVal || '';
    $('veditBsky').value = bskyVal || '';
    $('veditWork').value = workVal || '';
    if ($('veditChara')) $('veditChara').checked = !!charaVal;
    var errEl = $('veditError'); if (errEl) { errEl.textContent = ''; errEl.hidden = true; }
    $('veditOverlay').hidden = false;
    setTimeout(function () { var el = $('veditYt'); if (el) el.focus(); }, 50);
    _saveCb = onSave;
  }

  function showModalErr_(msg) {
    var el = $('veditError'); if (!el) return;
    el.textContent = msg; el.hidden = false;
  }

  // Bluesky URLをアイテムに保存（go5-short → shortUrl、その他 → postUrl）。
  function saveBskyToItem_(item, bskyUrl) {
    var w = (window.Go5Short && window.Go5Short.WORKER_URL) ? window.Go5Short.WORKER_URL.replace(/\/+$/, '') : '';
    var isGo5 = w && bskyUrl && bskyUrl.indexOf(w) === 0;
    if (bskyUrl) {
      if (isGo5) { item.shortUrl = bskyUrl; delete item.postUrl; }
      else { item.postUrl = bskyUrl; }
    } else {
      // 空白のとき：手動アイテムは両方消す、履歴アイテムは postUrl だけ消す（shortUrl はクリック計測に必要）
      if (item.manual) delete item.shortUrl;
      delete item.postUrl;
    }
  }

  // 編集保存：YouTube URL（ytMap）と Bluesky URL・作品URL・キャラ属性（アイテム）を一括更新。
  function saveEdit_(k, it, ytUrl, bskyUrl, workUrl, chara) {
    // YouTube URL
    var ymap = loadYtMap();
    if (ytUrl) ymap[k] = ytUrl; else delete ymap[k];
    saveYtMap(ymap);
    var saved = null;
    // Bluesky URL と 作品URL・キャラ（アイテムを直接書き換え）
    if (it.manual) {
      var manual = loadManual();
      for (var i = 0; i < manual.length; i++) {
        if (itemKey(manual[i]) !== k) continue;
        saveBskyToItem_(manual[i], bskyUrl);
        if (workUrl) manual[i].workUrl = workUrl; else delete manual[i].workUrl;
        if (chara) manual[i].chara = true; else delete manual[i].chara;
        saved = manual[i];
        break;
      }
      saveArr(manualKey(), manual);
    } else {
      var hist = loadHist();
      for (var j = 0; j < hist.length; j++) {
        if (itemKey(hist[j]) !== k) continue;
        saveBskyToItem_(hist[j], bskyUrl);
        if (workUrl) hist[j].workUrl = workUrl; else delete hist[j].workUrl;
        if (chara) hist[j].chara = true; else delete hist[j].chara;
        saved = hist[j];
        break;
      }
      saveArr(histKey(), hist);
    }
    if (saved) pushItemToGas_(saved, !!chara); // スプレッドシートのキャラ列等へ反映（GAS設定時のみ）
    refresh();
  }

  // 履歴アイテム1件をスプレッドシート（GAS）へ upsert 送信。post_id=背骨ID(videoId)で同一行を更新。
  // 投稿日時を上書きしないよう postUrl は送らない（既存行のキャラ列だけ更新する用途）。
  function pushItemToGas_(it, chara) {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl || !it || !it.videoId) return;
    var payload = {
      op: 'upsert',
      channel: acct(),
      videoId: it.videoId,           // post_id（upsertキー）
      title: it.title || '',
      postUri: it.postUri || '',
      workUrl: it.workUrl || '',
      shortUrl: it.shortUrl || '',
      chara: !!chara                  // キャラ列：○ / 空
    };
    try { fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) }).catch(function () {}); } catch (e) {}
  }

  // ── render ──────────────────────────────────────────────────────────────
  function render() {
    var list = $('ytClickList');
    var rawItems = allItems();
    var ymap = loadYtMap();
    if (!rawItems.length) {
      list.innerHTML = '<p class="hint">まだ投稿の記録がありません（投稿して短縮URLが出ると、ここに集まります）。「➕ 手動で追加」からYouTube動画を直接登録もできます。表示中アカウント：' + esc(acct()) + '</p>';
      return;
    }
    var items = sortItems(rawItems, ymap);
    list.innerHTML = items.map(function (it) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var code = codeOf(it.shortUrl || '');
      var clicks = code && (code in clicksCache) ? clicksCache[code] : null;
      var views = vid && (vid in viewsCache) ? viewsCache[vid] : null;
      var pub = vid && (vid in publishedCache) ? publishedCache[vid] : null;
      var dateHtml = pub != null
        ? '<b>' + esc(fmtTs(pub)) + '</b>'
        : (vid ? '<b class="vdate-pending">…</b>' : '<b class="vdate-unknown">投稿日時不明</b>');
      var rawTitle = (vid && titleCache[vid]) || it.title || (it.manual ? '(手動追加)' : '(無題)');
      var dispTitle = esc(stripCommonTags(rawTitle));
      var tagWarn = !it.manual && vid && (vid in titleCache) && missingCommonTags(rawTitle);
      var titleHtml = tagWarn
        ? '<span style="color:#dc465a;font-weight:700;">' + dispTitle + ' #タグ忘れ</span>'
        : dispTitle;
      var bskyHref = it.shortUrl || it.postUrl || '';
      return '<div class="vrow">' +
        '<div class="vrow-h">' + dateHtml + ' ' + titleHtml +
          (it.videoId ? ' <span class="vtag vtag-id">' + esc(it.videoId) + '</span>' : '') +
          (it.chara ? ' <span class="vtag vtag-chara">キャラ</span>' : '') +
        '</div>' +
        (it.workUrl ? '<div class="fanza-name-row" data-fanza-url="' + esc(it.workUrl) + '" style="display:none;"></div>' : '') +
        '<div class="vmetrics">' +
          '<span title="YouTube再生数">▶ ' + (views != null ? num(views) : (vid ? '…' : '–')) + '</span>' +
          '<span title="Bsky投稿クリック数">🔗 ' + (clicks != null ? num(clicks) : (code ? '…' : '–')) + '</span>' +
          '<button class="vedit-btn" type="button" data-k="' + esc(k) + '">🛠️編集</button>' +
          (bskyHref ? '<a class="vlink vlink-bsky" href="' + esc(bskyHref) + '" target="_blank" rel="noopener">Bsky投稿↗</a>' : '') +
          (yt ? '<a class="vlink vlink-yt" href="' + esc(yt) + '" target="_blank" rel="noopener">YouTube↗</a>' : '') +
          (it.workUrl ? '<a class="vlink vlink-work" href="' + esc(it.workUrl) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
        '</div>' +
        '<div class="vrow-foot">' +
          '<span class="vyt-lbl">YouTube<br>URL</span>' +
          '<input class="vyt-inp" type="url" inputmode="url" placeholder="https://youtu.be/…" data-k="' + esc(k) + '" value="' + esc(yt) + '">' +
          '<button class="vdel" type="button" data-k="' + esc(k) + '" title="この記録を消去">🗑</button>' +
        '</div>' +
        '</div>';
    }).join('');
    fillFanzaNames();

    // YouTube URL 直接入力
    list.querySelectorAll('input[data-k]').forEach(function (inp) {
      inp.addEventListener('change', function () {
        var m = loadYtMap(); var v = inp.value.trim();
        if (v) m[inp.getAttribute('data-k')] = v; else delete m[inp.getAttribute('data-k')];
        saveYtMap(m); refresh();
      });
    });

    // 削除
    list.querySelectorAll('.vdel').forEach(function (b) {
      b.addEventListener('click', function () { deleteItem(b.getAttribute('data-k')); });
    });

    // 編集モーダル
    list.querySelectorAll('.vedit-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-k');
        var rawItems = allItems(), ymap = loadYtMap();
        var it = null;
        for (var i = 0; i < rawItems.length; i++) { if (itemKey(rawItems[i]) === k) { it = rawItems[i]; break; } }
        if (!it) return;
        var ytCur = ymap[k] || it.ytUrl || '';
        var bskyCur = it.shortUrl || it.postUrl || '';
        var workCur = it.workUrl || '';
        openModal_('URL を編集', ytCur, bskyCur, workCur, !!it.chara, function (ytUrl, bskyUrl, workUrl, chara) {
          closeModal_();
          saveEdit_(k, it, ytUrl, bskyUrl, workUrl, chara);
        });
      });
    });
  }

  // 1件削除（確認ダイアログ）。手動追加分は verify_manual から、投稿履歴は short_hist から除去。
  function deleteItem(k) {
    var rawItems = allItems(), ymap = loadYtMap();
    var target = null;
    for (var i = 0; i < rawItems.length; i++) { if (itemKey(rawItems[i]) === k) { target = rawItems[i]; break; } }
    if (!target) return;
    var vid = ytIdOf(ymap[k] || target.ytUrl || '');
    var title = (vid && titleCache[vid]) || target.title || (target.manual ? '(手動追加)' : '(無題)');
    if (!window.confirm('「' + title + '」を本当に消去しますか？\n（この記録を一覧から削除します。取り消せません）')) return;
    if (target.manual) {
      saveArr(manualKey(), loadManual().filter(function (x) { return itemKey(x) !== k; }));
    } else {
      saveArr(histKey(), loadHist().filter(function (x) { return itemKey(x) !== k; }));
    }
    if (ymap[k] != null) { delete ymap[k]; saveYtMap(ymap); }
    refresh();
  }

  // YouTube動画を手動で追加（モーダルで YouTube URL + Bluesky URL + 作品URL を一括入力）。
  function addManual() {
    // 作品URLをアフィリンクタブの②から自動取得（なければ bsky_work_url を使用）
    var autoWorkUrl = '';
    try {
      var afEl = document.getElementById('affiUrls');
      var afRaw = afEl ? afEl.value : (localStorage.getItem('field_affiUrls') || '');
      autoWorkUrl = afRaw.trim().split('\n').map(function (l) { return l.trim(); }).filter(Boolean)[0] || '';
      if (!autoWorkUrl) {
        var acctId = (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1');
        autoWorkUrl = localStorage.getItem('bsky_work_url__' + acctId) || '';
      }
    } catch (e) {}
    openModal_('YouTube動画を追加', '', '', autoWorkUrl, false, function (ytUrl, bskyUrl, workUrl, chara) {
      if (!ytUrl) { showModalErr_('YouTube URLを入力してください。'); return; }
      var vid = ytIdOf(ytUrl);
      if (!vid) {
        showModalErr_('YouTubeのURLを認識できませんでした。\nhttps://youtu.be/… か https://www.youtube.com/watch?v=… 形式を貼ってください。');
        return;
      }
      closeModal_();
      var id = 'm:' + new Date().getTime();
      var entry = { manual: true, id: id, ts: 0 };
      saveBskyToItem_(entry, bskyUrl);
      if (workUrl) entry.workUrl = workUrl;
      if (chara) entry.chara = true;
      saveArr(manualKey(), loadManual().concat([entry]));
      var m = loadYtMap(); m[id] = ytUrl; saveYtMap(m);
      refresh();
    });
  }

  // クリック数(開封数)・YouTube視聴回数/投稿日時/題名をAPIから取得しキャッシュへ。Promiseを返す。
  function fetchData_(items, ymap) {
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); }).filter(Boolean);
    var vids = items.map(function (it) { var k = itemKey(it); return ytIdOf(ymap[k] || it.ytUrl || ''); }).filter(Boolean);
    if (!codes.length && !vids.length) return Promise.resolve(false);
    var jobs = [];
    codes.forEach(function (code) { jobs.push(fetchClicks(code).then(function (c) { if (c != null) clicksCache[code] = c; })); });
    if (vids.length) jobs.push(fetchVideos(vids).then(function (m) {
      lastErr = m.__error || ''; delete m.__error;
      Object.keys(m).forEach(function (id) {
        var rec = m[id] || {};
        if (rec.views != null) viewsCache[id] = rec.views;
        if (rec.published != null) publishedCache[id] = rec.published;
        if (rec.title) titleCache[id] = rec.title;
      });
    }));
    return Promise.all(jobs).then(function () { return true; });
  }

  function refresh() {
    ensureIds(); // IDが無いアイテムへ背骨IDを付与（履歴=スプレッドシートの正キー）
    render();
    var items = allItems(); var ymap = loadYtMap();
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); }).filter(Boolean);
    var vids = items.map(function (it) { var k = itemKey(it); return ytIdOf(ymap[k] || it.ytUrl || ''); }).filter(Boolean);
    if (!codes.length && !vids.length) { setStatus(apiKey() ? '' : '※YouTube再生数・投稿日時は⚙️詳細設定でAPIキーを設定し、各行にYouTube URLを入れると表示されます'); return; }
    setStatus('取得中…');
    fetchData_(items, ymap).then(function () {
      setStatus(lastErr ? ('⚠️ ' + lastErr) : (!apiKey() && vids.length ? '※再生数・投稿日時の表示には⚙️詳細設定のAPIキーが必要です' : ''));
      render();
    });
  }

  // この投稿履歴を正として、全アイテムを記録シート(GAS)へ一括 upsert 同期する。
  // ID・投稿日時(ts)・キャラ属性も送り、シート側で post_id 一致行を更新＋日付降順ソート。
  function syncSheet() {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl) { setStatus('⚠️ 記録用GASのURLが未設定です（⚙️詳細設定で設定してください）'); return; }
    ensureIds();
    var btn = $('ytSyncSheet'); if (btn) btn.disabled = true;
    setStatus('最新の再生数・クリック数を取得中…');
    // まずYouTube題名・視聴回数・開封数を最新取得してから送る（取れたぶんだけ反映）。
    fetchData_(allItems(), loadYtMap()).then(function () { sendSync_(gasUrl, btn); });
  }
  function sendSync_(gasUrl, btn) {
    var ymap = loadYtMap();
    var items = allItems().map(function (it) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var code = codeOf(it.shortUrl || '');
      // 投稿日時：実投稿時刻(ts)を最優先。無ければYouTube公開日時を使う（→朝ばかり/今日になる問題を解消）。
      var pubMs = (vid && publishedCache[vid] != null) ? publishedCache[vid] : null;
      var postedMs = (it.ts && it.ts > 0) ? it.ts : pubMs;
      return {
        videoId: it.videoId || '',
        title: it.title || '',                                          // 題名(コメント)＝アプリの④コメント
        ytTitle: (vid && titleCache[vid]) || '',                        // YouTube動画の実題名（取得済みのみ）
        views: (vid && viewsCache[vid] != null) ? viewsCache[vid] : '', // YouTube視聴回数（取得済みのみ）
        clicks: (code && clicksCache[code] != null) ? clicksCache[code] : '', // 短縮URLクリック数（取得済みのみ）
        postUri: it.postUri || '',
        postUrl: it.postUrl || '',
        shortUrl: it.shortUrl || '',
        workUrl: it.workUrl || '',
        youtubeUrl: yt,
        chara: !!it.chara,
        postedAt: postedMs ? new Date(postedMs).toISOString() : ''
      };
    }).filter(function (r) { return r.videoId; });
    if (!items.length) { setStatus('同期する履歴がありません'); if (btn) btn.disabled = false; return; }
    setStatus('スプレッドシートへ同期中… (' + items.length + '件)');
    fetch(gasUrl, { method: 'POST', body: JSON.stringify({ op: 'sync_history', channel: acct(), items: items }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.ok) setStatus('✅ スプレッドシートへ同期しました（' + (j.synced != null ? j.synced : items.length) + '件）');
        else setStatus('⚠️ 同期に失敗しました' + (j && j.error ? '：' + j.error : ''));
      })
      .catch(function () {
        // GASのCORS応答は読めないことがあるが、送信自体は届いている（記録は実行される）。
        setStatus('📤 同期リクエストを送信しました（' + items.length + '件）。数秒後にスプレッドシートをご確認ください。');
      })
      .then(function () { if (btn) btn.disabled = false; });
  }

  var tab = $('tabVerify'); if (tab) tab.addEventListener('click', refresh);
  var rb = $('ytClickRefresh'); if (rb) rb.addEventListener('click', refresh);
  var ab = $('ytAddManual'); if (ab) ab.addEventListener('click', addManual);
  var sb = $('ytSyncSheet'); if (sb) sb.addEventListener('click', syncSheet);
  document.addEventListener('account-changed', function () { render(); });

  // 詳細設定タブの YouTube APIキー入力：端末内に保存・復元（秘密扱い）。
  var keyEl = $('ytApiKey');
  if (keyEl) {
    try { keyEl.value = localStorage.getItem('yt_api_key') || ''; } catch (e) {}
    keyEl.addEventListener('input', function () { try { localStorage.setItem('yt_api_key', keyEl.value.trim()); } catch (e) {} });
  }

  // ── FANZA 商品名 キャッシュ＆DOM埋め込み ────────────────────────────────────
  // FANZA同人ページは未ログインだとログイン/年齢確認ページが返り、その og:title が
  // 「ログイン - FANZA」等になる。これを商品名として表示しないための判定。
  function isBadFanzaTitle(t) {
    var s = String(t || '').trim();
    if (!s) return true;
    if (s.indexOf('ログイン') >= 0) return true;
    if (s.toLowerCase().indexOf('login') >= 0) return true;
    if (s.indexOf('年齢確認') >= 0) return true;
    if (s.indexOf('エラー') >= 0) return true;
    if (s === 'FANZA' || s === 'DMM') return true;
    return false;
  }
  function fanzaNameCacheLoad() {
    try { return JSON.parse(localStorage.getItem('fanza_title_cache') || '{}'); } catch (e) { return {}; }
  }
  function fanzaNameCacheSave(c) {
    try { localStorage.setItem('fanza_title_cache', JSON.stringify(c)); } catch (e) {}
  }
  // 既存キャッシュから不正タイトル（ログイン/エラーページ等）を一掃する。変更があれば保存。
  function purgeBadFanzaCache() {
    var c = fanzaNameCacheLoad();
    var changed = false;
    Object.keys(c).forEach(function (url) {
      if (!c[url] || isBadFanzaTitle(c[url].title)) { delete c[url]; changed = true; }
    });
    if (changed) fanzaNameCacheSave(c);
  }
  // data-fanza-url が一致する現在の DOM 要素を全て更新（DOM 再描画後も正しく反映される）
  function setFanzaEls(fanzaUrl, title) {
    var ok = title && !isBadFanzaTitle(title);
    document.querySelectorAll('[data-fanza-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-url') !== fanzaUrl) return;
      if (ok) { el.textContent = title; el.style.display = ''; }
      else { el.textContent = ''; el.style.display = 'none'; }
    });
  }

  function fillFanzaNames() {
    var targets = document.querySelectorAll('[data-fanza-url]');
    if (!targets.length) return;
    if (typeof window.FanzaCore === 'undefined' || typeof window.buildAffiliateLink === 'undefined') return;
    var workerUrl = '';
    var sharedSecret = '';
    try { workerUrl = localStorage.getItem('fanza_worker_url') || ''; } catch (e) {}
    try { sharedSecret = localStorage.getItem('fanza_shared_secret') || ''; } catch (e) {}
    if (!workerUrl) return;
    purgeBadFanzaCache(); // 旧版で混入したログイン/エラータイトルを先に掃除
    var cache = fanzaNameCacheLoad();
    var now = new Date().getTime();
    var DAY = 86400000;
    // 同一 URL の重複フェッチを防ぐ
    var fetching = {};
    targets.forEach(function (nameEl) {
      var url = nameEl.getAttribute('data-fanza-url');
      if (!url) return;
      var cached = cache[url];
      if (cached && cached.title && !isBadFanzaTitle(cached.title) && (now - (cached.fetchedAt || 0)) < DAY) {
        nameEl.textContent = cached.title;
        nameEl.style.display = '';
        return;
      }
      if (fetching[url]) return;
      var res = window.buildAffiliateLink(url, '');
      if (!res || !res.ok || !res.cid) return;
      fetching[url] = true;
      // 取得中インジケータ表示（DOM 再描画で消えても再描画後に上書きされるので問題なし）
      nameEl.textContent = '…';
      nameEl.style.display = '';
      var capturedUrl = url;
      window.FanzaCore.fetchFanzaInfo(res.cid, workerUrl, sharedSecret).then(function (info) {
        // タイトル無し・ログイン/エラーページのタイトルは商品名として扱わない（キャッシュもしない）
        if (!info || !info.title || isBadFanzaTitle(info.title)) { setFanzaEls(capturedUrl, ''); return; }
        var c = fanzaNameCacheLoad();
        c[capturedUrl] = { title: info.title, fetchedAt: now };
        fanzaNameCacheSave(c);
        setFanzaEls(capturedUrl, info.title);
      }).catch(function () { setFanzaEls(capturedUrl, ''); });
    });
  }

  // ── ランキングタブ（両アカウント合算・再生数順）──────────────────────────────
  function renderRank() {
    var el = $('pageRank');
    if (!el) return;

    // 両アカウントからアイテムとYouTube URLを収集
    var combined = [];
    ['acc1', 'acc2'].forEach(function (a) {
      var ymap;
      try { ymap = JSON.parse(localStorage.getItem('verify_yt__' + a) || '{}') || {}; } catch (e) { ymap = {}; }
      var items = loadArr('short_hist__' + a).concat(loadArr('verify_manual__' + a));
      items.forEach(function (it) {
        var k = itemKey(it);
        var yt = ymap[k] || it.ytUrl || '';
        var vid = ytIdOf(yt);
        if (!vid) return;
        combined.push({ it: it, vid: vid, yt: yt, acct: a });
      });
    });

    // vid で重複排除（同じ動画が両アカウントに存在する場合、先に出た方のみ）
    var seen = {};
    var uniq = combined.filter(function (x) {
      if (seen[x.vid]) return false;
      seen[x.vid] = true;
      return true;
    });

    if (!uniq.length) {
      el.innerHTML = '<p class="hint">YouTube URLが設定された動画がありません。<br>🧪 検証タブで各行にYouTube URLを入力すると表示されます。</p>';
      return;
    }

    var ACCT_NAME = { acc1: '月詠み', acc2: '宵桜' };
    function fmtTsFull(ts) {
      if (!ts) return '';
      try {
        var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; };
        return d.getFullYear() + '/' + p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
      } catch (e) { return ''; }
    }

    function doRender() {
      var rows = uniq.map(function (x) {
        var it = x.it;
        return {
          vid: x.vid,
          yt: x.yt,
          acct: x.acct,
          title: titleCache[x.vid] || it.title || (it.manual ? '(手動追加)' : '(無題)'),
          views: (x.vid in viewsCache) ? viewsCache[x.vid] : null,
          ts: it.ts || (publishedCache[x.vid] || 0),
          bskyHref: it.shortUrl || it.postUrl || '',
          workUrl: it.workUrl || ''
        };
      });
      rows.sort(function (a, b) {
        if (a.views === null && b.views === null) return 0;
        if (a.views === null) return 1;
        if (b.views === null) return -1;
        return b.views - a.views;
      });
      el.innerHTML = '<div class="rank-list">' +
        rows.map(function (r, i) {
          var rank = i + 1;
          var topCls = rank <= 3 ? ' rank-top' + rank : '';
          var dispTitle = esc(stripCommonTags(r.title));
          var dateStr = fmtTsFull(r.ts);
          var acctLabel = ACCT_NAME[r.acct] || r.acct;
          return '<div class="rank-row' + topCls + '">' +
            '<span class="rank-num">' + rank + '</span>' +
            '<div class="rank-info">' +
              (dateStr ? '<div class="rank-date">' + esc(dateStr) + '</div>' : '') +
              '<div class="rank-title-row">' +
                '<span class="rank-acct rank-acct-' + esc(r.acct) + '">' + esc(acctLabel) + '</span>' +
                '<div class="rank-title">' +
                  (r.yt ? '<a class="rank-title-link" href="' + esc(r.yt) + '" target="_blank" rel="noopener">' + dispTitle + ' ↗</a>' : dispTitle) +
                '</div>' +
              '</div>' +
              (r.workUrl ? '<div class="fanza-name-row" data-fanza-url="' + esc(r.workUrl) + '" style="display:none;"></div>' : '') +
              '<div class="rank-metrics">' +
                '<span>▶ ' + (r.views != null ? num(r.views) : (apiKey() ? '…' : '–')) + '</span>' +
                (r.bskyHref ? '<a class="vlink" href="' + esc(r.bskyHref) + '" target="_blank" rel="noopener">Bsky↗</a>' : '') +
                (r.workUrl ? '<a class="vlink vlink-work" href="' + esc(r.workUrl) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
              '</div>' +
            '</div>' +
          '</div>';
        }).join('') +
      '</div>';
      fillFanzaNames();
    }

    // キャッシュにない vid だけ API フェッチ（最大 50 件ずつ）
    var missing = uniq.map(function (x) { return x.vid; }).filter(function (v) { return !(v in viewsCache); });
    if (missing.length) {
      el.innerHTML = '<p style="color:var(--sub);font-size:13px;padding:8px 14px;">再生数を取得中…</p>';
      // 50件ずつバッチに分割して並列フェッチ
      var batches = [];
      for (var i = 0; i < missing.length; i += 50) { batches.push(missing.slice(i, i + 50)); }
      Promise.all(batches.map(function (b) { return fetchVideos(b); })).then(function (results) {
        results.forEach(function (m) {
          var err = m.__error || ''; delete m.__error;
          if (err && !lastErr) lastErr = err;
          Object.keys(m).forEach(function (id) {
            var rec = m[id] || {};
            if (rec.views != null) viewsCache[id] = rec.views;
            if (rec.published != null) publishedCache[id] = rec.published;
            if (rec.title) titleCache[id] = rec.title;
          });
        });
        doRender();
      });
    } else {
      doRender();
    }
  }
  try { window.YtRank = { renderRank: renderRank }; } catch (e) {}
})();
