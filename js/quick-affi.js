/**
 * quick-affi.js — アカウント帯「癒やし倉庫」の右の「即アフィ」ボタンとモーダル(Chami msg 1559417034813608007)。
 * 作品URLを入れたら、アフィリンク化→今のチャンネルのドメインで短縮リンク発行→アフィチェック表示までを1画面で済ませる。
 * 中身(アフィ化・短縮・転送先のaf_id照合)は bluesky.js の window.Go5IssueAffShort=AFIリンクタブの単体短縮と同じ芯。
 * bluesky.js を読まないページ(候補/分析)では、StockLists.html へ移って開き直す(sessionStorage の印で引き継ぐ)。
 *   index.html は前回のタブ復元で Stock/StockLists へ飛び直すことがあり、印を食ったまま離れるので行き先にしない。
 */
(function () {
  'use strict';

  var FLAG = 'go5_quick_affi_open';
  var anchor = document.getElementById('acctBtn3');
  if (!anchor || document.getElementById('quickAffiBtn')) return;

  var btn = document.createElement('button');
  btn.id = 'quickAffiBtn';
  btn.type = 'button';
  btn.className = 'acct-btn quick-affi-btn';
  btn.textContent = '即アフィ';
  anchor.insertAdjacentElement('afterend', btn);

  var modal = null, els = {}, lastIssued = '', busy = false, autoTimer = null;

  function build_() {
    modal = document.createElement('div');
    modal.id = 'quickAffiModal';
    modal.className = 'qa-overlay';
    modal.hidden = true;
    modal.innerHTML =
      '<div class="qa-card" role="dialog" aria-modal="true" aria-labelledby="qaTitle">' +
        '<div class="qa-head"><span id="qaTitle">即アフィ</span><button type="button" class="qa-x" aria-label="閉じる">✕</button></div>' +
        '<div class="qa-body">' +
          '<label class="qa-label" for="qaUrl">作品URL</label>' +
          '<div class="qa-row"><input id="qaUrl" type="text" inputmode="url" autocomplete="off" placeholder="https://...(DMM/FANZAの作品URL)">' +
            '<button type="button" class="qa-mini" data-act="paste">貼り付け</button></div>' +
          '<div class="qa-domain"></div>' +
          '<button type="button" class="qa-go">アフィリンク＋短縮リンクを作る</button>' +
          '<div class="qa-result" hidden>' +
            '<label class="qa-label" for="qaOut">短縮リンク</label>' +
            '<div class="qa-row"><input id="qaOut" type="text" readonly>' +
              '<button type="button" class="qa-mini" data-act="copy">コピー</button></div>' +
            '<div class="qa-dest"></div>' +
            '<div class="manual-aff-status" hidden></div>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(modal);
    els.url = modal.querySelector('#qaUrl');
    els.out = modal.querySelector('#qaOut');
    els.go = modal.querySelector('.qa-go');
    els.result = modal.querySelector('.qa-result');
    els.dest = modal.querySelector('.qa-dest');
    els.status = modal.querySelector('.manual-aff-status');
    els.domain = modal.querySelector('.qa-domain');
    els.copy = modal.querySelector('[data-act="copy"]');

    modal.addEventListener('click', function (e) { if (e.target === modal) close_(); });
    modal.querySelector('.qa-x').addEventListener('click', close_);
    els.go.addEventListener('click', function () { issue_(true); });
    els.url.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); issue_(true); } });
    // URLを入れたら即作る(手入力の途中で走らないよう、http(s)で始まる値が0.5秒止まってから)。
    els.url.addEventListener('input', function () {
      clearTimeout(autoTimer);
      if (/^https?:\/\/\S+\.\S+/.test(els.url.value.trim())) autoTimer = setTimeout(function () { issue_(false); }, 500);
    });
    modal.querySelector('[data-act="paste"]').addEventListener('click', function () {
      if (!navigator.clipboard || !navigator.clipboard.readText) { els.url.focus(); return; }
      navigator.clipboard.readText().then(function (t) {
        els.url.value = String(t || '').trim();
        issue_(false);
      }, function () { els.url.focus(); });
    });
    els.copy.addEventListener('click', function () {
      var v = els.out.value;
      if (!v) return;
      var done = function () { els.copy.textContent = '✓ コピー'; setTimeout(function () { els.copy.textContent = 'コピー'; }, 1400); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(v).then(done, function () { legacyCopy_(v); done(); });
      else { legacyCopy_(v); done(); }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && modal && !modal.hidden) close_(); });
  }

  function legacyCopy_(v) {
    els.out.focus(); els.out.select();
    try { document.execCommand('copy'); } catch (e) {}
  }

  function status_(kind, message) {
    var el = els.status;
    if (!message) { el.hidden = true; el.textContent = ''; el.className = 'manual-aff-status'; return; }
    el.hidden = false;
    el.className = 'manual-aff-status ' + (kind === 'ok' ? 'is-ok' : (kind === 'off' ? 'is-off' : 'is-ng'));
    el.textContent = '';
    var title = document.createElement('b'), value = document.createElement('span');
    title.textContent = 'アフィチェック';
    value.textContent = (kind === 'ok' ? '✅ ' : (kind === 'off' ? '− ' : '⚠️ ')) + message;
    el.appendChild(title); el.appendChild(value);
  }

  function issue_(force) {
    var url = els.url.value.trim();
    if (busy || !url) return;
    if (!force && url === lastIssued) return;
    clearTimeout(autoTimer);
    busy = true;
    var label = els.go.textContent;
    els.go.disabled = true; els.go.textContent = '作成中…';
    els.out.value = ''; els.dest.textContent = ''; status_('', '');
    window.Go5IssueAffShort(url, '', true).then(function (r) {
      els.result.hidden = false;
      els.out.value = r.url || '';
      els.out.placeholder = r.url ? '' : '発行できませんでした';
      els.copy.disabled = !r.url;
      // 発行できなかった理由は欄の中に収まらないので、転送先の行に全文で出す。
      els.dest.textContent = (r.url ? '' : r.out + (r.dest ? ' / ' : '')) + (r.dest ? '転送先: ' + r.dest : '');
      if (r.aff) status_(r.aff, r.affMsg);
      if (r.issued) lastIssued = url;
    }).then(function () {
      busy = false; els.go.disabled = false; els.go.textContent = label;
    });
  }

  function open_() {
    if (!modal) build_();
    var base = '';
    try { base = (window.Go5Short && window.Go5Short.base && window.Go5Short.base()) || ''; } catch (e) {}
    els.domain.textContent = '発行ドメイン: ' + (base ? base.replace(/^https?:\/\//, '').replace(/\/+$/, '') : '未設定(短縮せず元のURLのまま)');
    modal.hidden = false;
    setTimeout(function () { try { els.url.focus(); } catch (e) {} }, 30);
  }
  function close_() { if (modal) modal.hidden = true; }

  btn.addEventListener('click', function () {
    if (typeof window.Go5IssueAffShort === 'function') { open_(); return; }
    try { sessionStorage.setItem(FLAG, '1'); } catch (e) {}
    location.href = 'StockLists.html';
  });

  var want = '';
  try { want = sessionStorage.getItem(FLAG) || ''; } catch (e) {}
  if (want && typeof window.Go5IssueAffShort === 'function') {
    try { sessionStorage.removeItem(FLAG); } catch (e) {}
    open_();
  }
}());
