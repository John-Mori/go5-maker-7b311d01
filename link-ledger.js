/**
 * link-ledger.js — 🔗 短縮リンク台帳 (検証タブ)
 *
 * link-worker(/api/list)から「このワーカーが払い出した全短縮リンク+クリック数」を取得して一覧表示。
 * 手動で作った短縮も含め全部ここで見える=「どこに記録されてるか分からない」の解消。
 * 種別は飛び先URLから自動判定: 🏮セール会場 / 🛒FANZA作品 / 🦋Bluesky投稿(導線1) / ▶YouTube / その他。
 * 読み取りのみ(KV write 0)。認証は既存のGo5Short.SHARED_SECRET(端末のlocalStorage同期済み)。
 */
(function () {
  'use strict';
  var box = document.getElementById('linkLedger');
  if (!box) return;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function num(n) { try { return Number(n).toLocaleString('ja-JP'); } catch (e) { return String(n); } }
  function kindOf(url) {
    var u = String(url || '');
    if (/campaign=gain/.test(u)) return ['🏮', 'セール会場'];
    if (/al\.fanza\.co\.jp|dmm\.co\.jp|dmm\.com/.test(u)) return ['🛒', 'FANZA作品(導線2)'];
    if (/bsky\.app|bsky\.social/.test(u)) return ['🦋', 'Bsky投稿(導線1)'];
    if (/youtu\.be|youtube\.com/.test(u)) return ['▶', 'YouTube'];
    return ['🔗', 'その他'];
  }
  function cfg() {
    var w = (window.Go5Short && window.Go5Short.WORKER_URL || '').replace(/\/+$/, '');
    var s = (window.Go5Short && window.Go5Short.SHARED_SECRET) || '';
    return { w: w, s: s };
  }

  var btn = document.getElementById('linkLedgerLoad');
  var out = document.getElementById('linkLedgerList');
  if (btn) btn.addEventListener('click', function () {
    var c = cfg();
    if (!c.w || !c.s) { out.innerHTML = '<p class="hint">短縮ワーカーの設定(共有シークレット)が未設定です。</p>'; return; }
    btn.disabled = true; btn.textContent = '読み込み中…';
    fetch(c.w + '/api/list?secret=' + encodeURIComponent(c.s))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) { out.innerHTML = '<p class="hint">取得に失敗しました' + (j && j.error ? '(' + esc(j.error) + ')' : '') + '。</p>'; return; }
        if (!j.links.length) { out.innerHTML = '<p class="hint">短縮リンクはまだありません。</p>'; return; }
        var total = j.links.reduce(function (a, x) { return a + (x.clicks || 0); }, 0);
        var rows = j.links.map(function (l) {
          var kind = kindOf(l.url);
          var short = c.w + '/' + l.code;
          return '<tr>' +
            '<td class="llk-kind" title="' + esc(kind[1]) + '">' + kind[0] + '</td>' +
            '<td class="llk-clicks"><b>' + num(l.clicks) + '</b></td>' +
            '<td class="llk-code"><a href="' + esc(short) + '?nc=1" target="_blank" rel="noopener" title="開く(自分のクリックは計測されない)">' + esc(l.code) + '</a></td>' +
            '<td class="llk-url"><a href="' + esc(l.url) + '" target="_blank" rel="noopener">' + esc(l.url.length > 70 ? l.url.slice(0, 70) + '…' : l.url) + '</a></td>' +
            '</tr>';
        }).join('');
        out.innerHTML =
          '<p class="hint">全' + j.total + '件・合計クリック ' + num(total) + '。クリック数順。コードのリンクは ?nc=1 付き=開いても計測されません。</p>' +
          '<div style="overflow-x:auto;"><table class="llk-table"><thead><tr><th></th><th>クリック</th><th>コード</th><th>飛び先</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
      })
      .catch(function () { out.innerHTML = '<p class="hint">通信に失敗しました。</p>'; })
      .then(function () { btn.disabled = false; btn.textContent = '🔄 読み込む'; });
  });
})();
