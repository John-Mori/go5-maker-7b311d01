/**
 * quick-affi.js — アカウント帯「癒やし倉庫」の右の「即アフィ」ボタンとモーダル(Chami msg 1559417034813608007)。
 * 作品URLを入れたら、アフィリンク化→今のチャンネルのドメインで短縮リンク発行→アフィチェック表示までを1画面で済ませる。
 * 中身(アフィ化・短縮・転送先のaf_id照合)は bluesky.js の window.Go5IssueAffShort=AFIリンクタブの単体短縮と同じ芯。
 * 発行後は定型文(⇩気になった方は…/新作N%OFF✨️ 等+短縮リンク)を丸ごとコピペできる欄にも出す(Chami msg 1559480072589803612)。
 *   文面の正本は core/movie-attrs-core.js の affiPostText。割引と発売日は window.Go5FreshWorkInfo で取り直す。
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
            '<label class="qa-label qa-post-label" for="qaPost">投稿文(まるごとコピー)</label>' +
            '<textarea id="qaPost" class="qa-post" rows="4" readonly></textarea>' +
            '<div class="qa-post-note"></div>' +
            '<button type="button" class="qa-mini qa-post-copy" data-act="copyPost">投稿文をコピー</button>' +
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
    els.post = modal.querySelector('#qaPost');
    els.postNote = modal.querySelector('.qa-post-note');
    els.postCopy = modal.querySelector('[data-act="copyPost"]');

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
    els.copy.addEventListener('click', function () { copy_(els.out, els.copy); });
    els.postCopy.addEventListener('click', function () { copy_(els.post, els.postCopy); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && modal && !modal.hidden) close_(); });
  }

  function copy_(field, button) {
    var v = field.value, label = button.textContent;
    if (!v) return;
    var done = function () { button.textContent = '✓ コピー'; setTimeout(function () { button.textContent = label; }, 1400); };
    var legacy = function () { field.focus(); field.select(); try { document.execCommand('copy'); } catch (e) {} done(); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(v).then(done, legacy);
    else legacy();
  }

  // 定型文の2行目(新作/話題作・N%OFF)は作品情報しだい。取れなかった時は「話題作✨️」で出し、取れなかったことを添える。
  function post_(link, info) {
    var core = window.Go5MovieAttrsCore;
    els.post.value = (link && core && core.affiPostText) ? core.affiPostText(info, link) : '';
    els.postCopy.disabled = !els.post.value;
    els.postNote.textContent = !link ? '' : (info ? '' : '作品情報(発売日/割引)を取れなかったので「話題作✨️」で出しています。');
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
    els.out.value = ''; els.dest.textContent = ''; status_('', ''); post_('', null);
    var infoP = window.Go5FreshWorkInfo ? window.Go5FreshWorkInfo(url).catch(function () { return null; }) : Promise.resolve(null);
    Promise.all([window.Go5IssueAffShort(url, '', true), infoP]).then(function (got) {
      var r = got[0];
      els.result.hidden = false;
      els.out.value = r.url || '';
      els.out.placeholder = r.url ? '' : '発行できませんでした';
      els.copy.disabled = !r.url;
      // 発行できなかった理由は欄の中に収まらないので、転送先の行に全文で出す。
      els.dest.textContent = (r.url ? '' : r.out + (r.dest ? ' / ' : '')) + (r.dest ? '転送先: ' + r.dest : '');
      if (r.aff) status_(r.aff, r.affMsg);
      post_(r.url || '', got[1]);
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
