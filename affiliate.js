/**
 * affiliate.js
 * FANZAアフィリエイトリンク生成画面のUI配線
 * - アフィID永続化(localStorage: fanza_af_id)
 * - リアルタイム生成(input イベント)
 * - コピー(clipboard API + execCommand フォールバック)
 * - タブ切替(#tabMovie / #tabAffi)
 */

(function () {
  'use strict';

  /* ── タブ切替(動画作成／カレンダー／投稿／アフィリンク／検証の5タブ) ── */
  var TABS = [
    { btn: 'rankBtn',    page: 'pageRank'    },
    { btn: 'tabCand',    page: 'pageCand'    },
    { btn: 'tabVerify', page: 'pageVerify'   },
    { btn: 'analyzeBtn', page: 'pageAnalyze' },
    { btn: 'tabMovie',  page: 'pageMovie'    },
    { btn: 'tabStock',  page: 'pageStock'    },
    { btn: 'reserveBtn', page: 'pageReserve' },
    { btn: 'calBtn',    page: 'pageCalendar' },
    { btn: 'tabYT',     page: 'pageYouTube'  },
    { btn: 'tabPost',   page: 'pagePost'     },
    { btn: 'tabAffi',   page: 'pageAffi'     },
    { btn: 'tabSettings', page: 'pageSettings' }
  ];
  // アカウント帯のボタン(⏰予約 / 📅カレンダー / 📊分析 / 🏆ランキング)は「タブ」ではなく“上に重ねて
  //   開く”オーバーレイ扱い。もう一度同じボタンを押すと直前の作業タブへ戻る(予約/カレンダー=Chami
  //   2026-07-31 / ランキングをタブから帯へ移設=Chami 2026-08-02)。タブバーには置かない。
  var OVERLAY_BTNS = { reserveBtn: 1, calBtn: 1, analyzeBtn: 1, rankBtn: 1 };
  var currentTab = 'tabMovie';          // いま前面に出している btn id
  var prevWorkTab = 'tabMovie';         // オーバーレイを開く直前の“作業タブ”(戻り先)
  // カレンダーは重い(holidays等)ため、初回表示時にだけ iframe を読み込む。(遅延ロード)
  function lazyLoadCalendar() {
    var f = document.getElementById('calFrame');
    if (f && !f.getAttribute('src')) f.setAttribute('src', 'schedule/index.html?v=30');
  }
  function showTab(activeBtnId) {
    TABS.forEach(function (t) {
      var b = document.getElementById(t.btn), p = document.getElementById(t.page);
      if (!b || !p) return;
      var on = (t.btn === activeBtnId);
      p.hidden = !on;
      b.classList.toggle('active', on);
    });
    currentTab = activeBtnId;
    // 現在タブをCSSへ通知。(ランキングタブだけクリーム背景＋金文字にするフック)
    document.documentElement.setAttribute('data-tab', activeBtnId);
    // リロード/再アクセス時に前回の“作業タブ”を復元するため保存。
    //   ★オーバーレイ(予約/カレンダー)は作業の上に重ねるだけなので復元対象にしない
    //   (再アクセス時は下の作業タブへ戻す)。
    if (!OVERLAY_BTNS[activeBtnId]) { try { localStorage.setItem('go5_active_tab', activeBtnId); } catch (e) {} }
    if (activeBtnId === 'calBtn') {
      lazyLoadCalendar();
      // iframeは再ロードされないため、開くたびに「表示された」と伝えて今日へ寄せさせる。
      // 初回はロード直後でリスナ未装着なので iframe 側の初回スクロールが担う。表示反映を待って rAF で送る。
      var cf = document.getElementById('calFrame');
      if (cf && cf.contentWindow) requestAnimationFrame(function () {
        cf.contentWindow.postMessage({ target: 'sch-calendar', type: 'show' }, '*');
      });
    }
    if (activeBtnId === 'rankBtn'    && window.YtRank)   window.YtRank.renderRank();
    if (activeBtnId === 'tabCand'    && window.Go5Cand)  window.Go5Cand.render();
    if (activeBtnId === 'reserveBtn' && window.Scheduler) window.Scheduler._renderTab();
    if (activeBtnId === 'tabStock'   && window.Go5Stock)  window.Go5Stock.render();
    // 選んだタブをタブバーの中央へ寄せる(タブ選択のたび・Chami 2026-07-31)。オーバーレイ
    //   (予約/カレンダー)はタブバーに無いので centerTab_ 側の早期returnで何もしない。
    centerTab_(activeBtnId);
  }
  TABS.forEach(function (t) {
    var b = document.getElementById(t.btn);
    if (!b) return;
    b.addEventListener('click', function () {
      if (OVERLAY_BTNS[t.btn]) {
        // 開いているボタンをもう一度押した＝直前の作業タブへ戻す(トグル)。
        if (currentTab === t.btn) { showTab(prevWorkTab || 'tabMovie'); return; }
        // これから重ねる＝下にある作業タブを戻り先として覚える(オーバーレイ同士の切替では上書きしない)。
        if (!OVERLAY_BTNS[currentTab]) prevWorkTab = currentTab;
      }
      showTab(t.btn);
    });
  });
  // 前回表示していたタブを復元。(リロード/再アクセスで動画作成に強制的に戻らないように)
  //   全モジュール(YtRank/Go5Cand/Scheduler等)が定義された後に実行したいので DOMContentLoaded を待つ
  //   。(このスクリプトより後に読まれる candidates.js 等の render を確実に呼ぶため)
  // 対象タブをタブバー(横スクロール)の中央へ寄せる。scrollIntoView は祖先ごとスクロールして
  //   ヘッダーが画面外へ飛ぶため使わず、.tabbar の scrollLeft だけを動かす(Chami 2026-07-29)。
  function centerTab_(btnId) {
    var b = document.getElementById(btnId);
    if (!b) return;
    var bar = (b.closest && b.closest('.tabbar')) || b.parentNode;
    if (!bar || bar.scrollWidth <= bar.clientWidth) return; // 全タブが収まっていれば動かさない(PC等)
    var barRect = bar.getBoundingClientRect();
    var bRect = b.getBoundingClientRect();
    var delta = (bRect.left - barRect.left) + b.offsetWidth / 2 - bar.clientWidth / 2;
    bar.scrollLeft += delta;
  }
  function restoreActiveTab_() {
    var saved = '';
    try { saved = localStorage.getItem('go5_active_tab') || ''; } catch (e) {}
    // ★オーバーレイ(予約/カレンダー)は復元対象にしない＝再アクセス時は下の作業タブへ戻す。
    var ok = saved && !OVERLAY_BTNS[saved] && TABS.some(function (t) { return t.btn === saved; }) && document.getElementById(saved);
    var activeId;
    if (ok && saved !== 'tabMovie') {
      showTab(saved); activeId = saved; // 保存タブへ復元(既定=動画作成なら showTab しない)
    } else {
      // 保存が無い/不正＝HTMLの active(既定=動画作成)をCSSへ反映するだけ。
      var active = TABS.filter(function (t) { var b = document.getElementById(t.btn); return b && b.classList.contains('active'); })[0];
      activeId = active ? active.btn : 'tabMovie';
      document.documentElement.setAttribute('data-tab', activeId);
    }
    // アクセス時に該当タブをタブバー中央へ(Chami 2026-07-29)。アイコン画像やフォントで幅が
    //   後から変わるため、rAF(初回レイアウト後)と load(画像確定後)の二段で寄せ直す。
    var recenter = function () { centerTab_(activeId); };
    if (window.requestAnimationFrame) window.requestAnimationFrame(recenter); else recenter();
    try { window.addEventListener('load', recenter, { once: true }); } catch (e) { window.addEventListener('load', recenter); }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', restoreActiveTab_);
  else restoreActiveTab_();

  /* ── アフィID永続化 ── */
  const afIdEl = document.getElementById('afId');
  const affiUrlsEl = document.getElementById('affiUrls');
  const affiResultsEl = document.getElementById('affiResults');
  const affiWarnEl = document.getElementById('affiWarn');

  // 起動時復元(af_id は console.log に出さない)
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

        // 作品ID(cid)が取れないURL＝セール会場・キャンペーン・一覧ページ等。
        // 作品リンクは作れないが、一覧ラッパ(buildFanzaListLink)で会場URLをそのまま
        // アフィ化できる。(cid不要／他人のアフィリンクや計測パラメータは normalizeWorkUrl で除去)
        if (result.error === 'no_cid') {
          var listRes = buildFanzaListLink(line.trim(), afId);
          if (listRes.ok) {
            html += '<div class="affi-result">'
              + '<div class="affi-row">'
              + '  <span class="affi-label">種別:</span>'
              + '  <code class="affi-cid">会場/一覧リンク</code>'
              + '</div>'
              + '<div class="affi-row affi-link-row">'
              + '  <span class="affi-label">リンク:</span>'
              + '  <a class="affi-code" href="' + escAttr(listRes.link) + '" target="_blank" rel="noopener">' + escHtml(listRes.link) + '</a>'
              + '</div>'
              + '<div class="affi-row">'
              + '  <button class="copy-btn copy-btn-wide" data-copy="link" data-val="' + escAttr(listRes.link) + '">リンクをコピー</button>'
              + '</div>'
              + '</div>';
            return;
          }
        }

        // ここに来るのは bad_url、または no_cid かつ一覧ラッパも失敗(＝http(s)でない等)。
        var msg = 'URLが不正です(http(s):// で始まる必要があります)';
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
        + '  <a class="affi-code" href="' + escAttr(result.link) + '" target="_blank" rel="noopener">' + escHtml(result.link) + '</a>'
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
