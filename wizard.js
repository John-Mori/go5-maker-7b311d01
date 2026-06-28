(function () {
  'use strict';

  /* =========================================================
   * wizard.js  多段ウィザード（オブザーバ型）
   * 既存フロー・既存タブを一切壊さない追加のみ実装
   * ========================================================= */

  /* ---- 状態オブジェクト ---- */
  var W = {
    account: '',
    workUrl: '',
    affLink: '',
    videoId: '',
    title: '',
    postUrl: '',
    postUri: '',
    shortUrl: '',
    ytUrl: '',
    ytId: ''
  };

  /* bskyEnable の元の値を保持 */
  var _prevBskyEnable = false;

  /* 現在ステップ（1-5）*/
  var _currentStep = 1;

  /* video-created / bluesky-posted リスナー参照（解除用） */
  var _onVideoCreated = null;
  var _onBskyPosted = null;

  /* shortUrl ポーリング用タイマー */
  var _shortUrlTimer = null;

  /* =========================================================
   * DOM 構築
   * ========================================================= */
  function buildDOM() {
    /* --- 起動ボタン --- */
    var startBtn = document.createElement('button');
    startBtn.id = 'wizStartBtn';
    startBtn.type = 'button';
    startBtn.textContent = '🪄 今から1本（ウィザードで順番に）';
    startBtn.style.cssText = [
      'display:block',
      'width:100%',
      'margin:12px 0',
      'padding:12px 16px',
      'background:#5b3f8e',
      'color:#fff',
      'border:none',
      'border-radius:10px',
      'font-size:1rem',
      'font-weight:700',
      'cursor:pointer',
      'text-align:center'
    ].join(';');
    startBtn.addEventListener('click', startWizard);

    /* slotCtxMovie の直後に挿入 */
    var slotCtx = document.getElementById('slotCtxMovie');
    if (slotCtx && slotCtx.parentNode) {
      slotCtx.parentNode.insertBefore(startBtn, slotCtx.nextSibling);
    }

    /* --- オーバーレイ --- */
    var overlay = document.createElement('div');
    overlay.id = 'wizard';
    overlay.style.cssText = [
      'position:fixed',
      'top:0',
      'left:0',
      'right:0',
      'bottom:0',
      'background:rgba(0,0,0,0.75)',
      'z-index:50',
      'display:none',
      'align-items:center',
      'justify-content:center',
      'padding:16px',
      'box-sizing:border-box'
    ].join(';');

    var card = document.createElement('div');
    card.className = 'pc-card';
    card.style.cssText = [
      'background:#1a1a2e',
      'border-radius:14px',
      'padding:20px',
      'width:100%',
      'max-width:480px',
      'max-height:90vh',
      'overflow-y:auto',
      'color:#eee',
      'box-sizing:border-box'
    ].join(';');

    /* 進捗 */
    var progress = document.createElement('div');
    progress.id = 'wizProgress';
    progress.style.cssText = 'font-size:.82rem;color:#aaa;margin-bottom:6px;';

    /* 見出し */
    var heading = document.createElement('div');
    heading.id = 'wizHeading';
    heading.className = 'pc-title';
    heading.style.cssText = 'font-size:1.1rem;font-weight:700;margin-bottom:12px;color:#d4b3ff;';

    /* 本文コンテナ */
    var body = document.createElement('div');
    body.id = 'wizBody';
    body.style.cssText = 'font-size:.95rem;line-height:1.6;';

    /* ナビゲーション */
    var nav = document.createElement('div');
    nav.id = 'wizNav';
    nav.style.cssText = 'display:flex;gap:8px;margin-top:16px;justify-content:flex-end;flex-wrap:wrap;';

    var btnBack = document.createElement('button');
    btnBack.id = 'wizBack';
    btnBack.type = 'button';
    btnBack.textContent = '◀ 戻る';
    btnBack.style.cssText = 'padding:8px 14px;border-radius:8px;border:1px solid #555;background:#333;color:#eee;cursor:pointer;font-size:.9rem;';
    btnBack.addEventListener('click', goBack);

    var btnNext = document.createElement('button');
    btnNext.id = 'wizNext';
    btnNext.type = 'button';
    btnNext.textContent = '次へ ▶';
    btnNext.style.cssText = 'padding:8px 16px;border-radius:8px;border:none;background:#5b3f8e;color:#fff;cursor:pointer;font-size:.9rem;font-weight:700;';
    btnNext.addEventListener('click', goNext);

    var btnClose = document.createElement('button');
    btnClose.id = 'wizClose';
    btnClose.type = 'button';
    btnClose.textContent = '✕ 閉じる';
    btnClose.style.cssText = 'padding:8px 14px;border-radius:8px;border:1px solid #555;background:transparent;color:#aaa;cursor:pointer;font-size:.9rem;';
    btnClose.addEventListener('click', closeWizard);

    nav.appendChild(btnBack);
    nav.appendChild(btnNext);
    nav.appendChild(btnClose);

    card.appendChild(progress);
    card.appendChild(heading);
    card.appendChild(body);
    card.appendChild(nav);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
  }

  /* =========================================================
   * ウィザード 開始 / 閉じる
   * ========================================================= */
  function startWizard() {
    /* bskyEnable を覚えて ON にする */
    var bskyEnable = document.getElementById('bskyEnable');
    if (bskyEnable) {
      _prevBskyEnable = bskyEnable.checked;
      bskyEnable.checked = true;
    }

    /* 状態リセット */
    W = { account: '', workUrl: '', affLink: '', videoId: '', title: '', postUrl: '', postUri: '', shortUrl: '', ytUrl: '', ytId: '' };
    _currentStep = 1;

    showOverlay();
    renderStep(1);
  }

  function closeWizard() {
    /* bskyEnable を元に戻す */
    var bskyEnable = document.getElementById('bskyEnable');
    if (bskyEnable) {
      bskyEnable.checked = _prevBskyEnable;
    }
    stopShortUrlPolling();
    removeListeners();
    hideOverlay();
  }

  function showOverlay() {
    var overlay = document.getElementById('wizard');
    if (overlay) overlay.style.display = 'flex';
  }

  function hideOverlay() {
    var overlay = document.getElementById('wizard');
    if (overlay) overlay.style.display = 'none';
  }

  /* =========================================================
   * ナビゲーション
   * ========================================================= */
  function goNext() {
    if (_currentStep < 5) {
      _currentStep++;
      renderStep(_currentStep);
    } else {
      closeWizard();
    }
  }

  function goBack() {
    if (_currentStep > 1) {
      _currentStep--;
      renderStep(_currentStep);
    }
  }

  /* =========================================================
   * ステップ描画
   * ========================================================= */
  function renderStep(step) {
    var progress = document.getElementById('wizProgress');
    var heading = document.getElementById('wizHeading');
    var body = document.getElementById('wizBody');
    var btnBack = document.getElementById('wizBack');
    var btnNext = document.getElementById('wizNext');
    if (!progress || !heading || !body) return;

    progress.textContent = 'ステップ ' + step + ' / 5';
    btnBack.style.display = step > 1 ? '' : 'none';

    removeListeners();
    stopShortUrlPolling();

    switch (step) {
      case 1: renderStep1(heading, body, btnNext); break;
      case 2: renderStep2(heading, body, btnNext); break;
      case 3: renderStep3(heading, body, btnNext); break;
      case 4: renderStep4(heading, body, btnNext); break;
      case 5: renderStep5(heading, body, btnNext); break;
    }
  }

  /* ---- ステップ1: 作品URL ＆ アカウント ---- */
  function renderStep1(heading, body, btnNext) {
    heading.textContent = '① 作品URL ＆ アカウント';
    btnNext.textContent = '次へ ▶';
    btnNext.disabled = true;

    var currentAccount = (typeof getCurrentAccount === 'function') ? getCurrentAccount() : '';
    W.account = currentAccount;

    body.innerHTML = '';

    /* アカウント表示 */
    var acctLabel = el('div', { style: 'margin-bottom:10px;' });
    acctLabel.appendChild(el('span', { style: 'color:#aaa;font-size:.85rem;' }, 'アカウント: '));
    var acctName = el('strong', { id: 'wizAcctName', style: 'color:#d4b3ff;' }, accountLabel(currentAccount));
    acctLabel.appendChild(acctName);
    body.appendChild(acctLabel);

    /* 切替ボタン */
    var acctRow = el('div', { style: 'display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;' });
    var btn1 = el('button', { type: 'button', style: 'padding:6px 12px;border-radius:8px;border:1px solid #5b3f8e;background:#2a1a4e;color:#d4b3ff;cursor:pointer;font-size:.85rem;' }, '月読み色恋劇場 (acc1)');
    var btn2 = el('button', { type: 'button', style: 'padding:6px 12px;border-radius:8px;border:1px solid #5b3f8e;background:#2a1a4e;color:#d4b3ff;cursor:pointer;font-size:.85rem;' }, '宵桜艶帖 (acc2)');
    btn1.addEventListener('click', function () {
      var b = document.getElementById('acctBtn1');
      if (b) b.click();
      W.account = (typeof getCurrentAccount === 'function') ? getCurrentAccount() : 'acc1';
      var nameEl = document.getElementById('wizAcctName');
      if (nameEl) nameEl.textContent = accountLabel(W.account);
    });
    btn2.addEventListener('click', function () {
      var b = document.getElementById('acctBtn2');
      if (b) b.click();
      W.account = (typeof getCurrentAccount === 'function') ? getCurrentAccount() : 'acc2';
      var nameEl = document.getElementById('wizAcctName');
      if (nameEl) nameEl.textContent = accountLabel(W.account);
    });
    acctRow.appendChild(btn1);
    acctRow.appendChild(btn2);
    body.appendChild(acctRow);

    /* 作品URL入力 */
    body.appendChild(el('label', { style: 'font-size:.85rem;color:#aaa;display:block;margin-bottom:4px;' }, '作品URL（FANZA等）'));
    var urlInput = el('input', {
      type: 'url',
      id: 'wizWorkUrl',
      placeholder: 'https://www.dmm.co.jp/…',
      style: 'width:100%;box-sizing:border-box;padding:8px;border-radius:8px;border:1px solid #555;background:#111;color:#eee;font-size:.9rem;'
    });
    if (W.workUrl) urlInput.value = W.workUrl;
    body.appendChild(urlInput);

    /* アフィリンク生成結果 */
    var affResult = el('div', { id: 'wizAffResult', style: 'margin-top:8px;font-size:.85rem;min-height:1.4em;' });
    body.appendChild(affResult);

    /* URL 入力のたびにアフィリンク確認 */
    urlInput.addEventListener('input', function () {
      var url = urlInput.value.trim();
      W.workUrl = url;

      /* #movieWorkUrl へ同期 */
      var mwu = document.getElementById('movieWorkUrl');
      if (mwu) {
        mwu.value = url;
        mwu.dispatchEvent(new Event('input', { bubbles: true }));
      }

      if (!url) {
        affResult.textContent = '';
        btnNext.disabled = true;
        return;
      }

      var afId = '';
      try { afId = localStorage.getItem('fanza_af_id') || ''; } catch (e) { /* ignore */ }

      var result = (typeof buildAffiliateLink === 'function') ? buildAffiliateLink(url, afId) : { ok: false, link: '' };
      if (result && result.ok) {
        W.affLink = result.link;
        affResult.style.color = '#7fe87f';
        affResult.textContent = '✅ アフィリンク生成OK: ' + result.link.slice(0, 60) + (result.link.length > 60 ? '…' : '');
        btnNext.disabled = false;
      } else {
        W.affLink = '';
        affResult.style.color = '#f88';
        affResult.textContent = '⚠️ URLを確認してください（FANZA商品URLを入力してください）';
        btnNext.disabled = true;
      }
    });

    /* 既存値があれば即時評価 */
    if (W.workUrl) urlInput.dispatchEvent(new Event('input'));
  }

  /* ---- ステップ2: 動画を作る ---- */
  function renderStep2(heading, body, btnNext) {
    heading.textContent = '② 動画を作る';
    btnNext.textContent = '次へ ▶';
    btnNext.disabled = true;

    body.innerHTML = '';
    body.appendChild(el('p', {}, '写真と文字を入れて「▶ 動画を作成」を押してください。'));
    body.appendChild(el('p', { style: 'font-size:.85rem;color:#aaa;' }, '動画が作成されると自動で次のステップへ進みます。'));

    /* 動画作成タブへ移動ボタン */
    var gotoBtn = el('button', {
      type: 'button',
      style: 'padding:10px 18px;border-radius:8px;border:none;background:#1e5a9e;color:#fff;cursor:pointer;font-size:.9rem;font-weight:700;margin-top:8px;'
    }, '🎬 動画作成タブへ移動');
    gotoBtn.addEventListener('click', function () {
      hideOverlay();
      var tabMovie = document.getElementById('tabMovie');
      if (tabMovie) tabMovie.click();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    body.appendChild(gotoBtn);

    /* video-created を購読 */
    _onVideoCreated = function (e) {
      var detail = (e && e.detail) || {};
      W.videoId = detail.videoId || '';
      W.title = detail.title || '';
      showOverlay();
      _currentStep = 3;
      renderStep(3);
    };
    window.addEventListener('video-created', _onVideoCreated);
  }

  /* ---- ステップ3: Bluesky投稿（自動） ---- */
  function renderStep3(heading, body, btnNext) {
    heading.textContent = '③ Bluesky 投稿（自動）';
    btnNext.textContent = '次へ（スキップ） ▶';
    btnNext.disabled = false;

    body.innerHTML = '';
    body.appendChild(el('p', {}, 'Bluesky投稿の確認ダイアログが出ます。作品URLを確認して投稿してください。'));
    body.appendChild(el('p', { style: 'font-size:.85rem;color:#aaa;' }, '投稿が完了すると自動で次のステップへ進みます。投稿しない場合は「次へ（スキップ）」を押してください。'));

    var waiting = el('div', { id: 'wizWaitPost', style: 'margin-top:10px;font-size:.85rem;color:#d4b3ff;' }, '⏳ 投稿完了を待っています…');
    body.appendChild(waiting);

    /* bluesky-posted を購読 */
    _onBskyPosted = function (e) {
      var detail = (e && e.detail) || {};
      W.postUrl = detail.post_url || '';
      W.postUri = detail.post_uri || '';

      var waitEl = document.getElementById('wizWaitPost');
      if (waitEl) waitEl.textContent = '✅ 投稿完了。短縮URLを取得中…';

      /* 短縮URLポーリング */
      pollShortUrl(function (shortUrl) {
        W.shortUrl = shortUrl;
        _currentStep = 4;
        renderStep(4);
      });
    };
    window.addEventListener('bluesky-posted', _onBskyPosted);
  }

  /* ---- ステップ4: YouTubeに上げる ---- */
  function renderStep4(heading, body, btnNext) {
    heading.textContent = '④ YouTube に上げる';
    btnNext.textContent = '次へ ▶';
    btnNext.disabled = true;

    body.innerHTML = '';

    /* YouTube 題名 */
    var ytTitleEl = document.getElementById('ytTitle');
    var titleText = (ytTitleEl && ytTitleEl.textContent) ? ytTitleEl.textContent : W.title;
    if (titleText && titleText.indexOf('動画作成') !== -1) titleText = W.title; /* デフォルトメッセージを回避 */

    body.appendChild(el('div', { style: 'font-size:.85rem;color:#aaa;margin-bottom:4px;' }, 'YouTube 題名'));
    var titleBox = el('div', { style: 'background:#111;border-radius:8px;padding:8px;margin-bottom:8px;font-size:.9rem;word-break:break-all;' }, titleText || '（題名が取得できませんでした）');
    body.appendChild(titleBox);

    var copyTitle = el('button', { type: 'button', style: copyBtnStyle() }, '📋 題名をコピー');
    copyTitle.addEventListener('click', function () {
      copyToClipboard(titleText, copyTitle);
    });
    body.appendChild(copyTitle);

    /* YouTube 説明欄 */
    var ytDescEl = document.getElementById('ytDesc');
    var descText = (ytDescEl && ytDescEl.value) ? ytDescEl.value : '';
    body.appendChild(el('div', { style: 'font-size:.85rem;color:#aaa;margin-top:14px;margin-bottom:4px;' }, 'YouTube 説明欄（短縮URL入り）'));
    var descBox = el('textarea', { rows: '6', readonly: '', style: 'width:100%;box-sizing:border-box;background:#111;border:1px solid #444;border-radius:8px;padding:8px;color:#ccc;font-size:.82rem;resize:vertical;' });
    descBox.value = descText;
    body.appendChild(descBox);

    var copyDesc = el('button', { type: 'button', style: copyBtnStyle() }, '📋 説明欄をコピー');
    copyDesc.addEventListener('click', function () {
      copyToClipboard(descText, copyDesc);
    });
    body.appendChild(copyDesc);

    body.appendChild(el('p', { style: 'font-size:.85rem;color:#aaa;margin-top:10px;' }, 'この5秒動画をYouTubeにアップし、説明欄に上を貼ってください。'));

    /* YouTube URL 入力 */
    body.appendChild(el('div', { style: 'font-size:.85rem;color:#aaa;margin-top:14px;margin-bottom:4px;' }, 'YouTubeのURL（アップ後に貼ってください）'));
    var ytUrlInput = el('input', {
      type: 'url',
      id: 'wizYtUrl',
      placeholder: 'https://youtu.be/…',
      style: 'width:100%;box-sizing:border-box;padding:8px;border-radius:8px;border:1px solid #555;background:#111;color:#eee;font-size:.9rem;'
    });
    if (W.ytUrl) ytUrlInput.value = W.ytUrl;
    body.appendChild(ytUrlInput);

    /* 記録して次へ */
    var recordBtn = el('button', {
      type: 'button',
      style: 'display:block;width:100%;margin-top:12px;padding:10px;border-radius:8px;border:none;background:#5b3f8e;color:#fff;cursor:pointer;font-size:.95rem;font-weight:700;'
    }, '記録して次へ ▶');
    recordBtn.addEventListener('click', function () {
      var url = ytUrlInput.value.trim();
      W.ytUrl = url;
      W.ytId = (url && typeof window.IdGen !== 'undefined' && typeof window.IdGen.youtubeId === 'function')
        ? (window.IdGen.youtubeId(url) || '')
        : '';
      // 検証タブ（yt-clicks.js）が再生数を出せるよう、この投稿の動画URLを保存（itemKey と同形式）。
      try {
        if (url) {
          var acc = W.account || 'acc1';
          var mk = 'verify_yt__' + acc;
          var m = JSON.parse(localStorage.getItem(mk) || '{}') || {};
          m[W.postUri ? ('u:' + W.postUri) : ('s:' + (W.shortUrl || ''))] = url;
          localStorage.setItem(mk, JSON.stringify(m));
        }
      } catch (e) {}
      recordToGas();
      _currentStep = 5;
      renderStep(5);
    });
    body.appendChild(recordBtn);

    /* スキップリンク */
    var skipLink = el('a', { href: '#', style: 'display:block;text-align:center;margin-top:8px;font-size:.85rem;color:#888;' }, 'YouTubeはあとで（スキップ）');
    skipLink.addEventListener('click', function (e) {
      e.preventDefault();
      _currentStep = 5;
      renderStep(5);
    });
    body.appendChild(skipLink);

    btnNext.disabled = true;
    btnNext.style.display = 'none';
  }

  /* ---- ステップ5: 完了 ---- */
  function renderStep5(heading, body, btnNext) {
    heading.textContent = '⑤ 完了！';
    btnNext.textContent = '✕ 閉じる';
    btnNext.disabled = false;
    btnNext.style.display = '';

    body.innerHTML = '';
    body.appendChild(el('p', { style: 'color:#7fe87f;font-weight:700;font-size:1rem;' }, '🎉 1本完成しました！'));

    var rows = [
      ['作品URL', W.workUrl],
      ['短縮URL', W.shortUrl || W.postUrl],
      ['YouTube URL', W.ytUrl]
    ];
    rows.forEach(function (row) {
      if (!row[1]) return;
      var d = el('div', { style: 'margin-top:8px;' });
      d.appendChild(el('span', { style: 'font-size:.8rem;color:#aaa;' }, row[0] + ': '));
      var a = el('a', { href: row[1], target: '_blank', rel: 'noopener', style: 'color:#c4a0ff;font-size:.85rem;word-break:break-all;' }, row[1].slice(0, 70) + (row[1].length > 70 ? '…' : ''));
      d.appendChild(a);
      body.appendChild(d);
    });

    /* 閉じるボタンのイベント（goNext が closeWizard を呼ぶ設計に合わせて btnNext を閉じるに振る） */
    /* btnNext の click は goNext() → step>5 のルートで closeWizard() を呼ぶ (_currentStep=5 → step=6 → else branch) */
    /* 実際には step===5 で goNext すると _currentStep++ で 6 になり closeWizard に入る */
  }

  /* =========================================================
   * 短縮URL ポーリング
   * ========================================================= */
  function pollShortUrl(callback) {
    stopShortUrlPolling();
    var attempts = 0;
    var max = 40; /* 40 × 250ms = 10秒 */
    _shortUrlTimer = setInterval(function () {
      attempts++;
      var el = document.getElementById('shortUrlOut');
      var text = el ? (el.textContent || '').trim() : '';
      if (text && text.indexOf('http') === 0) {
        stopShortUrlPolling();
        callback(text);
        return;
      }
      if (attempts >= max) {
        stopShortUrlPolling();
        /* タイムアウト: postUrl で代替 */
        callback(W.postUrl || '');
      }
    }, 250);
  }

  function stopShortUrlPolling() {
    if (_shortUrlTimer) {
      clearInterval(_shortUrlTimer);
      _shortUrlTimer = null;
    }
  }

  /* =========================================================
   * GAS 記録（ステップ4）
   * ========================================================= */
  function recordToGas() {
    var gasUrl = '';
    try { gasUrl = localStorage.getItem('bsky_gas_url') || ''; } catch (e) { /* ignore */ }
    if (!gasUrl) return;
    try {
      fetch(gasUrl, {
        method: 'POST',
        body: JSON.stringify({
          op: 'upsert',
          testMode: /^test-/.test(W.videoId || ''),  // テストモードはシートに残さない
          videoId: W.videoId,
          channel: W.account,
          youtube_url: W.ytUrl,
          youtube_id: W.ytId
        })
      }).catch(function () { /* 失敗は無視 */ });
    } catch (e) { /* ignore */ }
  }

  /* =========================================================
   * リスナー解除
   * ========================================================= */
  function removeListeners() {
    if (_onVideoCreated) {
      window.removeEventListener('video-created', _onVideoCreated);
      _onVideoCreated = null;
    }
    if (_onBskyPosted) {
      window.removeEventListener('bluesky-posted', _onBskyPosted);
      _onBskyPosted = null;
    }
  }

  /* =========================================================
   * ユーティリティ
   * ========================================================= */
  function accountLabel(acc) {
    if (acc === 'acc1') return '月読み色恋劇場';
    if (acc === 'acc2') return '宵桜艶帖';
    return acc || '（未設定）';
  }

  function copyBtnStyle() {
    return 'padding:6px 12px;border-radius:8px;border:1px solid #555;background:#2a2a3e;color:#ccc;cursor:pointer;font-size:.85rem;margin-top:6px;';
  }

  function copyToClipboard(text, btn) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        flashBtn(btn, 'コピーしました ✓');
      }).catch(function () {
        fallbackCopy(text, btn);
      });
    } else {
      fallbackCopy(text, btn);
    }
  }

  function fallbackCopy(text, btn) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;top:-9999px;';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      flashBtn(btn, 'コピーしました ✓');
    } catch (e) { /* ignore */ }
  }

  function flashBtn(btn, msg) {
    if (!btn) return;
    var orig = btn.textContent;
    btn.textContent = msg;
    setTimeout(function () { if (btn) btn.textContent = orig; }, 2000);
  }

  /**
   * 簡易要素生成ヘルパ
   * @param {string} tag
   * @param {Object} attrs
   * @param {string} [text]
   * @returns {HTMLElement}
   */
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === 'style') {
          e.style.cssText = attrs[k];
        } else if (k === 'readonly') {
          e.readOnly = true;
        } else {
          e.setAttribute(k, attrs[k]);
        }
      });
    }
    if (text !== undefined) e.textContent = text;
    return e;
  }

  /* =========================================================
   * 初期化
   * ========================================================= */
  function init() {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', buildDOM);
    } else {
      buildDOM();
    }
  }

  init();

}());
