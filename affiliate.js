/**
 * affiliate.js
 * FANZAアフィリエイトリンク生成画面のUI配線
 * - アフィID永続化（localStorage: fanza_af_id）
 * - リアルタイム生成（input イベント）
 * - コピー（clipboard API + execCommand フォールバック）
 * - タブ切替（#tabMovie / #tabAffi）
 */

(function () {
  'use strict';

  /* ── タブ切替（動画作成／カレンダー／投稿／アフィリンク／検証の5タブ） ── */
  var TABS = [
    { btn: 'tabMovie',  page: 'pageMovie'    },
    { btn: 'tabCal',    page: 'pageCalendar' },
    { btn: 'tabYT',     page: 'pageYouTube'  },
    { btn: 'tabPost',   page: 'pagePost'     },
    { btn: 'tabAffi',   page: 'pageAffi'     },
    { btn: 'tabVerify', page: 'pageVerify'   }
  ];
  // カレンダーは重い(holidays等)ため、初回表示時にだけ iframe を読み込む（遅延ロード）。
  function lazyLoadCalendar() {
    var f = document.getElementById('calFrame');
    if (f && !f.getAttribute('src')) f.setAttribute('src', 'schedule/index.html?v=23');
  }
  function showTab(activeBtnId) {
    TABS.forEach(function (t) {
      var b = document.getElementById(t.btn), p = document.getElementById(t.page);
      if (!b || !p) return;
      var on = (t.btn === activeBtnId);
      p.hidden = !on;
      b.classList.toggle('active', on);
    });
    if (activeBtnId === 'tabCal') lazyLoadCalendar();
  }
  TABS.forEach(function (t) {
    var b = document.getElementById(t.btn);
    if (b) b.addEventListener('click', function () { showTab(t.btn); });
  });

  /* ── アフィID永続化 ── */
  const afIdEl = document.getElementById('afId');
  const affiUrlsEl = document.getElementById('affiUrls');
  const affiResultsEl = document.getElementById('affiResults');
  const affiWarnEl = document.getElementById('affiWarn');

  // 起動時復元（af_id は console.log に出さない）
  (function restoreAfId() {
    try {
      var saved = localStorage.getItem('fanza_af_id');
      if (saved) afIdEl.value = saved;
    } catch (e) { /* プライベートモード等 */ }
  })();

  afIdEl.addEventListener('input', function () {
    try {
      localStorage.setItem('fanza_af_id', afIdEl.value);
    } catch (e) { /* ignore */ }
    renderResults();
  });

  affiUrlsEl.addEventListener('input', function () {
    renderResults();
  });

  /* ── コピーユーティリティ ── */
  function copyText(text, btn) {
    function onSuccess() {
      var orig = btn.textContent;
      btn.textContent = '✓ コピーしました';
      setTimeout(function () { btn.textContent = orig; }, 2000);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(onSuccess).catch(function () {
        fallbackCopy(text, btn, onSuccess);
      });
    } else {
      fallbackCopy(text, btn, onSuccess);
    }
  }

  function fallbackCopy(text, btn, onSuccess) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try {
      document.execCommand('copy');
      onSuccess();
    } catch (e) { /* silent */ }
    document.body.removeChild(ta);
  }

  /* ── 結果描画 ── */
  function renderResults() {
    var afId = afIdEl.value; // af_id は console.log に出さない
    var urls = affiUrlsEl.value;

    // アフィID未入力警告
    if (!afId || !afId.trim()) {
      affiWarnEl.hidden = false;
    } else {
      affiWarnEl.hidden = true;
    }

    // 非空行を抽出
    var lines = urls.split('\n').filter(function (l) { return l.trim() !== ''; });

    if (lines.length === 0) {
      affiResultsEl.innerHTML = '';
      return;
    }

    var html = '';
    lines.forEach(function (line) {
      var result = buildAffiliateLink(line.trim(), afId);

      if (!result.ok) {
        if (result.error === 'empty') return; // 空は無視
        var msg = result.error === 'no_cid'
          ? 'cid が見つかりません'
          : 'URLが不正です（http(s):// で始まる必要があります）';
        html += '<div class="affi-result affi-error-card">'
          + '<span class="affi-error">' + escHtml(msg) + '</span>'
          + '<div class="affi-url-hint">' + escHtml(line.trim()) + '</div>'
          + '</div>';
        return;
      }

      html += '<div class="affi-result">'
        + '<div class="affi-row">'
        + '  <span class="affi-label">作品ID:</span>'
        + '  <code class="affi-cid">' + escHtml(result.cid) + '</code>'
        + '  <button class="copy-btn" data-copy="cid" data-val="' + escAttr(result.cid) + '">IDコピー</button>'
        + '</div>'
        + '<div class="affi-row affi-link-row">'
        + '  <span class="affi-label">リンク:</span>'
        + '  <code class="affi-code">' + escHtml(result.link) + '</code>'
        + '</div>'
        + '<div class="affi-row">'
        + '  <button class="copy-btn copy-btn-wide" data-copy="link" data-val="' + escAttr(result.link) + '">リンクをコピー</button>'
        + '</div>'
        + '</div>';
    });

    affiResultsEl.innerHTML = html;

    // コピーボタンにイベント付与
    affiResultsEl.querySelectorAll('.copy-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        copyText(btn.dataset.val, btn);
      });
    });
  }

  /* ── HTML エスケープ ── */
  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escAttr(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;');
  }

  // 初期描画
  renderResults();

})();
