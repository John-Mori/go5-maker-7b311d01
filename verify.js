/**
 * verify.js — Phase4 Bluesky検証ダッシュボードのUI配線。
 * 共有ストア(sch_state_v1)の「公開済」投稿を一覧し、Bluesky公開APIで いいね/リポスト/返信 を取得。
 * Bitlyクリック(slot.click_count)＋FANZA成約(手入力・localStorage)を併記し day-type 別に集計。
 * 注意：クリック実数はFANZA管理画面が正。(ここは到達/反応の代理指標)
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  if (!$('pageVerify')) return;

  var FANZA_KEY = 'verify_fanza';
  var eng = {};   // uri -> {like,repost,reply,quote}

  function loadFanza() { try { return JSON.parse(localStorage.getItem(FANZA_KEY) || '{}'); } catch (e) { return {}; } }
  function saveFanza(m) { try { localStorage.setItem(FANZA_KEY, JSON.stringify(m)); } catch (e) {} }
  function readState() { try { return JSON.parse(localStorage.getItem('sch_state_v1') || 'null'); } catch (e) { return null; } }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function setStatus(m) { var e = $('verifyStatus'); if (e) e.textContent = m || ''; }

  function slots() { return window.VerifyCore ? window.VerifyCore.postedSlotsFromState(readState()) : []; }

  function render() {
    var list = $('verifyList');
    var ss = slots();
    if (!ss.length) {
      list.innerHTML = '<p class="hint">まだ公開済みの投稿がありません。📅カレンダーの枠から投稿すると、ここに集計されます。</p>';
      $('verifySummary').innerHTML = '';
      return;
    }
    var fanza = loadFanza();
    list.innerHTML = ss.map(function (s) {
      var e = eng[s.post_uri];
      return '<div class="vrow">' +
        '<div class="vrow-h"><b>' + esc(s.date) + '</b> ' + esc(s.time || '') +
        ' <span class="vrole">' + esc(s.role || '') + '</span> <span class="vgenre">' + esc(s.genre || '') + '</span></div>' +
        '<div class="vmetrics">' +
        '<span title="いいね">♡ ' + (e ? e.like : '–') + '</span>' +
        '<span title="リポスト">🔁 ' + (e ? e.repost : '–') + '</span>' +
        '<span title="返信">💬 ' + (e ? e.reply : '–') + '</span>' +
        '<span title="Bitlyクリック">🔗 ' + (s.click_count != null ? s.click_count : '–') + '</span>' +
        '<label class="vfanza">FANZA成約 <input type="number" min="0" inputmode="numeric" data-fanza="' + esc(s.id) + '" value="' + esc(fanza[s.id] != null ? fanza[s.id] : '') + '"></label>' +
        (s.post_url ? '<a class="vlink" href="' + esc(s.post_url) + '" target="_blank" rel="noopener">投稿↗</a>' : '') +
        '</div></div>';
    }).join('');
    list.querySelectorAll('[data-fanza]').forEach(function (inp) {
      inp.addEventListener('change', function () { var m = loadFanza(); m[inp.getAttribute('data-fanza')] = inp.value; saveFanza(m); renderSummary(ss); });
    });
    renderSummary(ss);
  }

  function renderSummary(ss) {
    var fanza = loadFanza();
    var by = {};
    ss.forEach(function (s) {
      var k = s.day_type || '不明';
      var b = by[k] || (by[k] = { n: 0, like: 0, repost: 0, reply: 0, click: 0, fanza: 0 });
      var e = eng[s.post_uri] || {};
      b.n++; b.like += e.like || 0; b.repost += e.repost || 0; b.reply += e.reply || 0;
      b.click += (s.click_count || 0); b.fanza += Number(fanza[s.id] || 0);
    });
    var keys = Object.keys(by);
    if (!keys.length) { $('verifySummary').innerHTML = ''; return; }
    var rows = keys.map(function (k) {
      var b = by[k];
      return '<tr><td>' + esc(k) + '</td><td>' + b.n + '</td><td>' + b.like + '</td><td>' + b.repost + '</td><td>' + b.reply + '</td><td>' + b.click + '</td><td>' + b.fanza + '</td></tr>';
    }).join('');
    $('verifySummary').innerHTML =
      '<table class="vsum"><thead><tr><th>day-type</th><th>件数</th><th>♡</th><th>🔁</th><th>💬</th><th>🔗</th><th>FANZA</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function refresh() {
    var ss = slots();
    var uris = ss.map(function (s) { return s.post_uri; }).filter(Boolean);
    if (!uris.length) { render(); return; }
    setStatus('エンゲージメント取得中…');
    var chunks = [];
    for (var i = 0; i < uris.length; i += 25) chunks.push(uris.slice(i, i + 25));
    Promise.all(chunks.map(function (c) {
      return fetch(window.VerifyCore.buildGetPostsUrl(c)).then(function (r) { return r.json(); }).then(function (j) {
        var m = window.VerifyCore.parseEngagement(j);
        Object.keys(m).forEach(function (u) { eng[u] = m[u]; });
      }).catch(function () {});
    })).then(function () { setStatus(''); render(); }, function () { setStatus('取得に失敗しました'); render(); });
  }

  var tabBtn = $('tabVerify');
  if (tabBtn) tabBtn.addEventListener('click', function () { render(); refresh(); });
  var rb = $('verifyRefresh');
  if (rb) rb.addEventListener('click', refresh);
})();
