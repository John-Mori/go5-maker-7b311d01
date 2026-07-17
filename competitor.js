/* competitor.js — 競合チャンネル監視の登録UI(2026-07-17 Chami依頼)。
 *   同ジャンルの競合YouTubeチャンネルを登録→localStorageに保存(同期対応)。
 *   チャンネル名はYouTube Data API v3で自動取得(既存の yt_api_key を流用)。
 *   実際の監視(直近動画・再生数をスプレッドシートへ毎日記録)はGAS側で行う(別途)。
 *   このファイルは登録・一覧・削除の自己完結UIのみ(GAS不要)。
 * 保存形式: localStorage 'competitor_channels' = [{input, channelId, name, addedAt}]
 *   ★同期対象(core/storage-keys.js の SYNC_EXACT に登録済=PCで登録→スマホでも見える)。
 */
(function () {
  'use strict';
  var U = window.Go5Util || {};
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  var KEY = 'competitor_channels';
  function load() { try { var a = JSON.parse(localStorage.getItem(KEY) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
  function save(a) { try { localStorage.setItem(KEY, JSON.stringify(a)); } catch (e) {} }
  function apiKey() { try { return (localStorage.getItem('yt_api_key') || '').trim(); } catch (e) { return ''; } }

  // 入力(URL/@ハンドル/UCID)からYT APIの検索パラメータを組む。
  //   ・/channel/UC… → id=UC…(1ユニット)  ・@handle → forHandle(1ユニット)
  //   ・/c/name・/user/name・素の名前 → forUsername→ダメなら search(100ユニット)にフォールバック
  function parseInput(raw) {
    var s = String(raw || '').trim();
    if (!s) return null;
    var m;
    if ((m = s.match(/youtube\.com\/channel\/(UC[0-9A-Za-z_-]{20,})/))) return { by: 'id', v: m[1] };
    if ((m = s.match(/youtube\.com\/@([0-9A-Za-z._-]+)/))) return { by: 'handle', v: m[1] };
    if ((m = s.match(/youtube\.com\/(?:c|user)\/([0-9A-Za-z._-]+)/))) return { by: 'user', v: m[1] };
    if (/^UC[0-9A-Za-z_-]{20,}$/.test(s)) return { by: 'id', v: s };
    if (/^@?[0-9A-Za-z._-]+$/.test(s)) return { by: 'handle', v: s.replace(/^@/, '') };
    return { by: 'search', v: s };
  }
  function ytGet(params) {
    var key = apiKey();
    if (!key) return Promise.reject(new Error('no_key'));
    var url = 'https://www.googleapis.com/youtube/v3/' + params + '&key=' + encodeURIComponent(key);
    return fetch(url).then(function (r) { return r.json(); });
  }
  // 入力 → {channelId, name}。失敗時はrejectでメッセージ。
  function resolve(input) {
    var p = parseInput(input);
    if (!p) return Promise.reject(new Error('empty'));
    function fromItems(j) {
      var it = j && j.items && j.items[0];
      if (it && it.id) return { channelId: (typeof it.id === 'string' ? it.id : (it.id.channelId || it.snippet && it.snippet.channelId)), name: (it.snippet && it.snippet.title) || '' };
      return null;
    }
    if (p.by === 'id') return ytGet('channels?part=snippet&id=' + encodeURIComponent(p.v)).then(function (j) { var r = fromItems(j); if (!r) throw new Error('not_found'); return r; });
    if (p.by === 'handle') return ytGet('channels?part=snippet&forHandle=@' + encodeURIComponent(p.v)).then(function (j) { var r = fromItems(j); if (r) return r; return resolveSearch(p.v); });
    if (p.by === 'user') return ytGet('channels?part=snippet&forUsername=' + encodeURIComponent(p.v)).then(function (j) { var r = fromItems(j); if (r) return r; return resolveSearch(p.v); });
    return resolveSearch(p.v);
  }
  // 最後の手段: search(100ユニット)。チャンネルを1件引く。
  function resolveSearch(q) {
    return ytGet('search?part=snippet&type=channel&maxResults=1&q=' + encodeURIComponent(q)).then(function (j) {
      var it = j && j.items && j.items[0];
      if (it && it.snippet && (it.id && it.id.channelId)) return { channelId: it.id.channelId, name: it.snippet.title || '' };
      throw new Error('not_found');
    });
  }

  function status(msg, isErr) { var el = $('compStatus'); if (el) { el.textContent = msg || ''; el.style.color = isErr ? '#dc465a' : 'var(--sub)'; } }
  // ISO日時 → 表示用の日付(YYYY-MM-DD)。パース失敗時は原文。
  function fmtDate(iso) {
    var s = String(iso || ''); if (!s) return '(不明)';
    var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? (m[1] + '-' + m[2] + '-' + m[3]) : s;
  }
  // チャンネル別の分析詳細(クリックで展開)。監視データ(伸び・投稿時刻・タイトル傾向)はβのGAS稼働後に充填。
  function detailHtml(c) {
    return '<div class="cd-row"><span class="cd-k">登録入力</span>' + esc(c.input || '') + '</div>' +
      '<div class="cd-row"><span class="cd-k">チャンネルID</span>' + esc(c.channelId || '(未取得・APIキー設定で埋まる)') + '</div>' +
      '<div class="cd-row"><span class="cd-k">追加日</span>' + esc(fmtDate(c.addedAt)) + '</div>' +
      '<div class="cd-soon">📊 このチャンネルの分析(前日の投稿本数・投稿時刻・再生の伸び・タイトル傾向)は、監視バックエンド(GAS)の稼働後にここへ表示されます。今は登録のみです。</div>';
  }
  function render() {
    var el = $('compList'); if (!el) return;
    var arr = load();
    if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:4px 2px;">まだ登録がありません。上に競合のチャンネルURLか@ハンドルを貼って「＋ 登録」してください。</p>'; return; }
    // 登録した順に上から並べる(load()＝保存配列の順＝登録順)。
    el.innerHTML = arr.map(function (c, i) {
      var url = c.channelId ? 'https://www.youtube.com/channel/' + esc(c.channelId) : (/^https?:/.test(c.input || '') ? esc(c.input) : '');
      return '<div class="comp-entry">' +
        '<div class="comp-item" data-i="' + i + '">' +
          '<div class="comp-item-main" data-toggle="' + i + '" title="クリックで分析詳細を開閉">' +
            '<div class="comp-name">' + esc(c.name || '(名称未取得)') + '</div>' +
            (url ? '<a class="comp-link" href="' + url + '" target="_blank" rel="noopener">' + esc(c.channelId || c.input || '') + ' ↗</a>'
                 : '<span class="comp-link">' + esc(c.input || '') + '</span>') +
          '</div>' +
          '<button class="comp-del" type="button" data-i="' + i + '" title="この競合を削除">✕</button>' +
        '</div>' +
        '<div class="comp-detail" data-detail="' + i + '" hidden>' + detailHtml(c) + '</div>' +
      '</div>';
    }).join('');
    // 削除(リンク遷移や展開に巻き込まれないよう stopPropagation)
    el.querySelectorAll('.comp-del').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var i = parseInt(b.getAttribute('data-i'), 10);
        var a = load(); if (i >= 0 && i < a.length) { a.splice(i, 1); save(a); render(); }
      });
    });
    // チャンネル名の行をクリック→そのチャンネルの分析詳細を開閉(リンク↗のクリックは除外)
    el.querySelectorAll('.comp-item-main').forEach(function (m) {
      m.addEventListener('click', function (e) {
        if (e.target && e.target.closest && e.target.closest('a.comp-link')) return; // ↗リンクは通常遷移
        var i = m.getAttribute('data-toggle');
        var item = m.parentNode, detail = el.querySelector('.comp-detail[data-detail="' + i + '"]');
        if (!detail) return;
        var willOpen = detail.hasAttribute('hidden');
        if (willOpen) { detail.removeAttribute('hidden'); item.classList.add('open'); }
        else { detail.setAttribute('hidden', ''); item.classList.remove('open'); }
      });
    });
  }

  function add() {
    var inp = $('compInput'); if (!inp) return;
    var raw = (inp.value || '').trim();
    if (!raw) { status('チャンネルのURLか@ハンドルを入れてください。', true); return; }
    var arr = load();
    // 既に同じ入力があれば弾く(重複登録防止)
    if (arr.some(function (c) { return (c.input || '') === raw; })) { status('もう登録されています。', true); return; }
    if (!apiKey()) {
      // キーが無くても登録自体はできる(名称は後で取得)。入力をそのまま保存。
      arr.push({ input: raw, channelId: '', name: '', addedAt: new Date().toISOString() });
      save(arr); inp.value = ''; render();
      status('登録しました。(チャンネル名は⚙️詳細設定でYouTube APIキーを入れると取得できます)');
      return;
    }
    status('チャンネルを確認中…');
    resolve(raw).then(function (r) {
      // 解決したchannelIdの重複も弾く
      if (r.channelId && arr.some(function (c) { return c.channelId === r.channelId; })) { status('そのチャンネルはもう登録されています。', true); return; }
      arr.push({ input: raw, channelId: r.channelId || '', name: r.name || '', addedAt: new Date().toISOString() });
      save(arr); inp.value = ''; render();
      status('登録しました：' + (r.name || r.channelId || raw));
    }).catch(function (e) {
      var msg = (e && e.message) === 'no_key' ? 'YouTube APIキーが未設定です(⚙️詳細設定)。'
        : (e && e.message) === 'not_found' ? 'チャンネルが見つかりませんでした。URLか@ハンドルを確認してください。'
        : 'チャンネルの確認に失敗しました。ネット接続かAPIキーを確認してください。';
      status(msg, true);
    });
  }

  function wire() {
    var b = $('compAdd'); if (b) b.addEventListener('click', add);
    var inp = $('compInput'); if (inp) inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add(); } });
    render();
    // 同期で他端末から更新が入ったら再描画(存在すれば購読)
    try { document.addEventListener('go5-synced', render); } catch (e) {}
    try { document.addEventListener('account-changed', render); } catch (e) {}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire);
  else wire();

  // 監視(GAS)側が使う: 登録チャンネルのID一覧を外へ公開。
  try { window.Go5Competitors = { list: load, channelIds: function () { return load().map(function (c) { return c.channelId; }).filter(Boolean); } }; } catch (e) {}
})();
