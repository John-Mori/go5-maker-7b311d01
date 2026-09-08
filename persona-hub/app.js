/**
 * persona-hub/app.js — 人格設定 一覧ビューアの配線。
 *
 * データは data.js(window.PERSONA_HUB_DATA・正本の派生物)優先、無ければ local/persona_settings_index.json
 * を fetch。★正本(persona_avatars.json / R2)へは書かない=差分の追加/削除は「手元(localStorage)だけ」の
 * スクラッチパッド。Chamiが変更メモを人事部門へ伝え、人事部門が正本へ反映する運用(静的ページの制約)。
 * 既存本体ファイル(index.html/app.js/GAS/Worker)には一切依存しない新規追加ページ。
 * core/util.js の esc は既存のまま流用(読むだけ・改変なし)。copyText は失敗を握り潰して成功に
 * 見えるため使わない=ページ内 copyTextChecked(成否Promise+フォールバック)で置き換え。
 */
(function () {
  "use strict";

  var Util = window.Go5Util || {};
  var esc = Util.esc || function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };
  // コピーの成否を返す(Promise<boolean>)。★Util.copyText は失敗をcatchで握り潰し成功に見える=
  // 「コピーしたのに前と一緒」の真因なので使わない。clipboard API が失敗(非フォーカス/権限/非secure文脈)
  // したら一時textarea+execCommand('copy')へフォールバック。それも駄目なら false を返す(呼び元で手動案内)。
  function copyTextChecked(text) {
    var s = String(text == null ? "" : text);
    function fallbackCopy() {
      try {
        var ta = document.createElement("textarea");
        ta.value = s;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        ta.style.top = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, s.length);
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        return !!ok;
      } catch (e) { return false; }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(s).then(
        function () { return true; },
        function () { return fallbackCopy(); }
      );
    }
    return Promise.resolve(fallbackCopy());
  }

  var DATA_URL = "../local/persona_settings_index.json";

  // 直接アップロード(ページから正本へ)。go5-sync Worker に PUT /api/img → POST /api/persona/enqueue。
  // ★トークンはページに埋めない=Chamiがこの端末のlocalStorageへ1回だけ入れる(埋めると誰でも書けてしまう・デブライネ制約)。
  var SYNC_BASE = "https://go5-sync.trustsignalbot.workers.dev";
  var TOKEN_KEY = "go5_sync_token_v1";

  // 折り畳みの開閉状態(この端末だけ・見た目の好み)。既定=全開。閉じたsectionのタイトルだけ覚える。
  var COLLAPSE_KEY = "persona_hub_collapsed_v1";

  var state = { personas: {}, names: [], filtered: [], selected: null };
  var els = {};

  document.addEventListener("DOMContentLoaded", init);

  // 折り畳みの開閉状態(この端末だけ)。閉じた section のタイトルを集合で覚える=次に開いた時も閉じたまま。
  function loadCollapsed() {
    try { return JSON.parse(localStorage.getItem(COLLAPSE_KEY)) || {}; } catch (e) { return {}; }
  }
  function saveCollapsed(map) {
    try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify(map)); } catch (e) {}
  }
  function shortId(url) {
    var s = String(url || "").split("?")[0];
    var seg = s.split("/").pop() || s;
    return seg.slice(-6) || seg;
  }
  function init() {
    els.list = document.getElementById("personaList");
    els.detail = document.getElementById("detailPane");
    els.count = document.getElementById("personaCount");
    els.error = document.getElementById("errorBanner");
    els.footer = document.getElementById("hubFooter");

    // 公開ページ(GitHub Pages)では data.js が window.PERSONA_HUB_DATA を焼き込んでいる。
    // local/ はgitignore配下でPagesに配信されないため、まず埋め込みを使い、無い時だけ
    // fetch へフォールバック(=ローカルの python -m http.server で開いた時用)。
    if (window.PERSONA_HUB_DATA && window.PERSONA_HUB_DATA.personas) {
      onData(window.PERSONA_HUB_DATA);
      return;
    }
    fetch(DATA_URL, { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(onData)
      .catch(onFetchError);
  }

  function onData(json) {
    state.personas = (json && json.personas) || {};
    state.meta = (json && json._meta) || {};
    state.names = Object.keys(state.personas).sort(function (a, b) { return a.localeCompare(b, "ja"); });
    state.filtered = state.names.slice();
    renderList();
    renderFooter();
    if (state.filtered.length) selectPersona(state.filtered[0]);
  }

  function onFetchError(err) {
    els.list.innerHTML = '<li class="persona-empty">読み込みに失敗しました</li>';
    els.error.hidden = false;
    els.error.innerHTML =
      "先に <code>python scripts/hr/persona_settings_index.py</code> を実行して集約JSONを生成してください" +
      "(<code>local/persona_settings_index.json</code>)。<span class=\"error-detail\"></span>";
    try { els.error.querySelector(".error-detail").textContent = String((err && err.message) || err || ""); } catch (e) {}
  }

  // ── 一覧 ──
  function renderList() {
    els.count.textContent = state.filtered.length + " / " + state.names.length + " 件";
    if (!state.filtered.length) {
      els.list.innerHTML = '<li class="persona-empty">該当するキャラクターがいません</li>';
      return;
    }
    els.list.innerHTML = state.filtered.map(function (name) {
      var e = state.personas[name] || {};
      var dept = e.所属部門 || "所属部門: 未設定";
      var iconCount = (e.アイコン && e.アイコン.枚数) || 0;
      var hasTone = !!e.口調;
      var toWhom = ((e.呼称 || {}).この人をどう呼ぶか || {}).自分を対象にした個別ルール || [];
      var fromWhom = (e.呼称 || {}).この人が誰をどう呼ぶか || [];
      var namingCount = toWhom.length + fromWhom.length;
      var active = name === state.selected ? " is-active" : "";
      return "" +
        '<li class="persona-item' + active + '" data-name="' + esc(name) + '">' +
          '<div class="persona-item-name">' + esc(name) + "</div>" +
          '<div class="persona-item-dept">' + esc(dept) + "</div>" +
          '<div class="persona-item-badges">' +
            '<span class="badge badge-icon">画像 ' + iconCount + "</span>" +
            '<span class="badge ' + (hasTone ? "badge-on" : "badge-off") + '">口調 ' + (hasTone ? "設定あり" : "未設定") + "</span>" +
            '<span class="badge badge-naming">呼称 ' + namingCount + "件</span>" +
          "</div>" +
        "</li>";
    }).join("");
    Array.prototype.forEach.call(els.list.querySelectorAll(".persona-item"), function (li) {
      li.addEventListener("click", function () { selectPersona(li.getAttribute("data-name")); });
    });
  }

  function selectPersona(name) {
    state.selected = name;
    renderList();
    renderDetail(name);
  }

  // ── 詳細 ──
  function renderDetail(name) {
    var e = state.personas[name];
    if (!e) { els.detail.innerHTML = '<div class="detail-empty">データがありません。</div>'; return; }
    var html = "";
    html += '<div class="detail-head"><h2>' + esc(name) + "</h2>" +
      '<div class="detail-dept">' + esc(e.所属部門 || "所属部門: 未設定") + "</div></div>";
    html += renderAvatarSection(e.アイコン, name);
    html += renderToneSection(e.口調);
    html += renderNamingToSection((e.呼称 || {}).この人をどう呼ぶか);
    html += renderNamingFromSection((e.呼称 || {}).この人が誰をどう呼ぶか);
    // ⑥ 設定所在の各キャラ表示は廃止=まとめ置き場をページ下部に1回だけ出す(renderFooter)。
    els.detail.innerHTML = html;
    wireCopyButtons();
    wireAvatarButtons(name);
    wireSectionToggles();
    wireThumbZoom();
  }

  // ── ⑤ section の開閉(開けるだけでなく閉じられるように)──
  // 各 .detail-section のタイトル(.section-toggle)クリックで .is-collapsed をトグル。
  // 閉じた状態はタイトル文言をキーに localStorage へ覚える=次に別キャラを開いても好みが残る。
  function applyCollapsedState(sec) {
    var map = loadCollapsed();
    var key = sec.getAttribute("data-sec") || "";
    sec.classList.toggle("is-collapsed", !!map[key]);
  }
  function toggleSection(sec) {
    var map = loadCollapsed();
    var key = sec.getAttribute("data-sec") || "";
    var nowCollapsed = !sec.classList.contains("is-collapsed");
    sec.classList.toggle("is-collapsed", nowCollapsed);
    if (nowCollapsed) map[key] = 1; else delete map[key];
    saveCollapsed(map);
  }
  function wireSectionToggles() {
    Array.prototype.forEach.call(els.detail.querySelectorAll(".detail-section"), function (sec) {
      applyCollapsedState(sec);
      var t = sec.querySelector(".section-toggle");
      if (!t) return;
      t.addEventListener("click", function () { toggleSection(sec); });
      t.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " " || ev.key === "Spacebar") {
          ev.preventDefault(); toggleSection(sec);
        }
      });
    });
  }

  // ── 画像ズーム(ライトボックス) ──
  // サムネ(.avatar-thumb)をクリック→原寸オーバーレイ。ホイール/ダブルクリックで拡大、
  // 拡大中はドラッグで移動、背景クリック/×/Escで閉じる。正本には一切触れない表示専用。
  var lb = null;

  function ensureLightbox() {
    if (lb) return lb;
    var ov = document.createElement("div");
    ov.className = "lb-overlay";
    ov.innerHTML =
      '<button class="lb-close" type="button" aria-label="閉じる">×</button>' +
      '<div class="lb-stage"><img class="lb-img" alt=""></div>' +
      '<div class="lb-cap"></div>';
    document.body.appendChild(ov);
    lb = {
      ov: ov,
      stage: ov.querySelector(".lb-stage"),
      img: ov.querySelector(".lb-img"),
      cap: ov.querySelector(".lb-cap"),
      close: ov.querySelector(".lb-close"),
      scale: 1, tx: 0, ty: 0,
      drag: null
    };
    lb.close.addEventListener("click", closeLightbox);
    ov.addEventListener("wheel", onLbWheel, { passive: false });
    ov.addEventListener("dblclick", function () { setZoom(lb.scale > 1 ? 1 : 2.5); });
    lb.stage.addEventListener("pointerdown", onLbDown);
    lb.stage.addEventListener("pointermove", onLbMove);
    lb.stage.addEventListener("pointerup", onLbUp);
    lb.stage.addEventListener("pointercancel", onLbUp);
    return lb;
  }

  function applyLb() {
    lb.img.style.transform =
      "translate(-50%,-50%) translate(" + lb.tx + "px," + lb.ty + "px) scale(" + lb.scale + ")";
    lb.stage.classList.toggle("is-zoomed", lb.scale > 1);
  }

  function setZoom(s) {
    lb.scale = Math.max(1, Math.min(6, s));
    if (lb.scale <= 1) { lb.tx = 0; lb.ty = 0; }
    applyLb();
  }

  function openLightbox(url, label) {
    ensureLightbox();
    lb.img.src = url;
    lb.cap.innerHTML = label ? "<b>" + esc(label) + "</b>" : "";
    lb.scale = 1; lb.tx = 0; lb.ty = 0; applyLb();
    lb.ov.classList.add("is-open");
    document.addEventListener("keydown", onLbKey);
  }

  function closeLightbox() {
    if (!lb) return;
    lb.ov.classList.remove("is-open");
    lb.img.src = "";
    document.removeEventListener("keydown", onLbKey);
  }

  function onLbKey(e) {
    if (e.key === "Escape") closeLightbox();
    else if (e.key === "+" || e.key === "=") setZoom(lb.scale + 0.5);
    else if (e.key === "-") setZoom(lb.scale - 0.5);
  }

  function onLbWheel(e) {
    e.preventDefault();
    setZoom(lb.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15));
  }

  function onLbDown(e) {
    lb.drag = { x: e.clientX, y: e.clientY, tx: lb.tx, ty: lb.ty, moved: false, zoomed: lb.scale > 1 };
    if (lb.scale > 1) { lb.stage.classList.add("is-panning"); lb.stage.setPointerCapture(e.pointerId); }
  }

  function onLbMove(e) {
    if (!lb.drag) return;
    var dx = e.clientX - lb.drag.x, dy = e.clientY - lb.drag.y;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) lb.drag.moved = true;
    if (lb.drag.zoomed) { lb.tx = lb.drag.tx + dx; lb.ty = lb.drag.ty + dy; applyLb(); }
  }

  function onLbUp(e) {
    lb.stage.classList.remove("is-panning");
    var d = lb.drag; lb.drag = null;
    if (!d) return;
    if (!d.moved) {
      // 動かさずクリック=拡大していなければ背景で閉じる/画像でズームイン
      if (e.target === lb.img && lb.scale <= 1) setZoom(2.5);
      else if (e.target !== lb.img) closeLightbox();
    }
  }

  function wireThumbZoom() {
    Array.prototype.forEach.call(els.detail.querySelectorAll(".avatar-thumb"), function (img) {
      img.addEventListener("click", function () {
        var cell = img.closest ? img.closest(".av-cell") : null;
        var idNode = cell && cell.querySelector(".av-id");
        openLightbox(img.getAttribute("src"), idNode ? idNode.textContent : "");
      });
    });
  }

  function normalizeUrls(u) {
    if (!u) return [];
    return Array.isArray(u) ? u.filter(Boolean) : [u];
  }

  function fmtVal(v) {
    if (v === null || v === undefined || v === "") return '<span class="val-empty">なし</span>';
    return esc(String(v));
  }

  // ⑤ 折り畳めるsection見出し。タイトルクリックで開閉(右端の▾で状態表示)。
  function sectionTitle(title, countText) {
    return '<h3 class="section-title section-toggle" role="button" tabindex="0" aria-label="' +
        esc(title) + 'を開閉">' +
      esc(title) +
      (countText ? ' <span class="section-count">' + esc(countText) + "</span>" : "") +
      '<span class="sec-caret" aria-hidden="true">▾</span>' +
    "</h3>";
  }

  // ★読み取り専用の一覧に戻した(Chami ①④=手元の変更/手元メモは不要)。正本(persona_avatars.json / R2)へ
  //   足すのは「直接アップロード」だけ=削除/並び替え/手元メモのスクラッチパッドは廃止。画像は全部そのまま出す。
  function renderAvatarSection(icon, name) {
    var urls = normalizeUrls(icon && icon.url);
    var count = urls.length;
    var cells = urls.map(function (u, i) {
      return '<div class="av-cell" data-url="' + esc(u) + '">' +
        '<img class="avatar-thumb" src="' + esc(u) + '" alt="" loading="lazy">' +
        '<span class="av-label">#' + (i + 1) + ' <span class="av-id">' + esc(shortId(u)) + "</span></span>" +
      "</div>";
    });
    var body = cells.length ? cells.join("") : '<div class="section-empty">画像なし</div>';
    return "" +
      '<section class="detail-section av-section" data-name="' + esc(name) + '" data-sec="アイコン差分">' +
        sectionTitle("アイコン差分", "(" + count + "枚)") +
        '<div class="section-body">' +
          '<div class="avatar-grid av-grid">' + body + "</div>" +
          '<div class="av-actions">' +
            '<button class="av-add-btn av-up-btn" data-act="upload">⬆ 直接アップロード(正本へ)</button>' +
            '<input type="file" class="av-file-up" accept="image/*" hidden>' +
          "</div>" +
          '<div class="av-upmsg" hidden></div>' +
          '<p class="av-hint"><b>Discord添付は不要。</b>「直接アップロード」を押して画像を選ぶだけで正本へ入る(書き込みトークンはページ下部で1回だけ設定する=ページには埋め込まない)。取り込み常駐が動けば数十秒で台帳に反映される。<br>ネット越しが使えない時の別口=取り込みフォルダ <code>local/persona_inbox/&lt;キャラ名&gt;/</code> に置いて <code>scripts/hr/ingest_persona_images.py</code>。サムネはクリックで拡大できる。</p>' +
        "</div>" +
      "</section>";
  }

  // ── アイコンの直接アップロードだけを配線(①④=手元メモ/削除/並び替えは廃止・読み取り専用)。
  //   トークン設定はページ下部(renderFooter)へ移した(③)。ここでは未設定なら下部設定を促して中止する。
  function wireAvatarButtons(name) {
    var sec = els.detail.querySelector(".av-section");
    if (!sec) return;
    Array.prototype.forEach.call(sec.querySelectorAll("[data-act]"), function (btn) {
      btn.addEventListener("click", function () {
        var act = btn.getAttribute("data-act");
        if (act === "upload") {
          if (!getSyncToken() && !setSyncToken()) { setUploadMsg("トークン未設定=中止した(ページ下部で1回だけ設定が要る)。", true); return; }
          var fu = sec.querySelector(".av-file-up"); if (fu) fu.click();
        }
      });
    });
    var fileUp = sec.querySelector(".av-file-up");
    if (fileUp) fileUp.addEventListener("change", function () { directUpload(name, fileUp.files && fileUp.files[0]); fileUp.value = ""; });
  }

  // ── 範囲トリミング(画像を編集)。追加/直接アップロードの前に、適用する矩形をChamiが厳密に選ぶ。
  //   スクショ準拠: 三分割グリッド+四隅ハンドルの切り抜き枠、左右回転(90度)、リセット、キャンセル/適用。
  //   done(null)=キャンセル、done({dataUrl,file,blob})=適用。正本には触れない(結果を既存の追加/送信経路へ渡すだけ)。
  var OUT_MAX = 512; // 出力の長辺上限(アイコン用途=これ以上は不要・localStorage肥大も防ぐ)
  function openCropper(file, done) {
    if (!file || !window.FileReader || !document.createElement("canvas").getContext) {
      done && done(null); return;
    }
    var img = new Image();
    var objUrl = null;
    try { objUrl = URL.createObjectURL(file); } catch (e) {}
    img.onerror = function () { cleanup(); alert("画像を読み込めなかった。別の画像で試して。"); done && done(null); };
    img.onload = function () { build(); };
    img.src = objUrl || "";

    var rot = 0;               // 0/90/180/270
    var base = null;           // 回転適用後の作業キャンバス(切り抜きの元)
    var scale = 1;             // 表示px / base px
    var crop = null;           // 表示px系の {x,y,w,h}(stage原点)
    var overlay, stage, cv, frame, gridWrap;
    var MIN = 24;              // 枠の最小表示サイズ(px)

    function cleanup() {
      if (objUrl) { try { URL.revokeObjectURL(objUrl); } catch (e) {} objUrl = null; }
      if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.removeEventListener("keydown", onKey, true);
    }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); cleanup(); done && done(null); }
    }

    function buildBase() {
      var sw = img.naturalWidth, sh = img.naturalHeight;
      var swap = (rot === 90 || rot === 270);
      var bw = swap ? sh : sw, bh = swap ? sw : sh;
      base = document.createElement("canvas");
      base.width = bw; base.height = bh;
      var g = base.getContext("2d");
      g.save();
      g.translate(bw / 2, bh / 2);
      g.rotate(rot * Math.PI / 180);
      g.drawImage(img, -sw / 2, -sh / 2);
      g.restore();
    }

    function layout() {
      // stageの実表示幅からscaleを決め、canvasを等倍表示する
      var maxW = stage.clientWidth || 320;
      scale = maxW / base.width;
      var dispW = base.width * scale, dispH = base.height * scale;
      cv.width = base.width; cv.height = base.height;
      cv.style.width = dispW + "px"; cv.style.height = dispH + "px";
      cv.getContext("2d").drawImage(base, 0, 0);
      stage.style.height = dispH + "px";
    }
    function defaultCrop() {
      var dispW = base.width * scale, dispH = base.height * scale;
      var s = Math.min(dispW, dispH) * 0.86;
      crop = { x: (dispW - s) / 2, y: (dispH - s) / 2, w: s, h: s };
    }
    function drawFrame() {
      frame.style.left = crop.x + "px";
      frame.style.top = crop.y + "px";
      frame.style.width = crop.w + "px";
      frame.style.height = crop.h + "px";
    }
    function clampCrop() {
      var dispW = base.width * scale, dispH = base.height * scale;
      if (crop.w < MIN) crop.w = MIN;
      if (crop.h < MIN) crop.h = MIN;
      if (crop.w > dispW) crop.w = dispW;
      if (crop.h > dispH) crop.h = dispH;
      if (crop.x < 0) crop.x = 0;
      if (crop.y < 0) crop.y = 0;
      if (crop.x + crop.w > dispW) crop.x = dispW - crop.w;
      if (crop.y + crop.h > dispH) crop.y = dispH - crop.h;
    }
    function rerender() { layout(); defaultCrop(); clampCrop(); drawFrame(); }

    function apply() {
      var sx = Math.round(crop.x / scale), sy = Math.round(crop.y / scale);
      var sw = Math.round(crop.w / scale), sh = Math.round(crop.h / scale);
      sw = Math.max(1, Math.min(sw, base.width - sx));
      sh = Math.max(1, Math.min(sh, base.height - sy));
      var ow = sw, oh = sh, long = Math.max(sw, sh);
      if (long > OUT_MAX) { var k = OUT_MAX / long; ow = Math.round(sw * k); oh = Math.round(sh * k); }
      var out = document.createElement("canvas");
      out.width = ow; out.height = oh;
      out.getContext("2d").drawImage(base, sx, sy, sw, sh, 0, 0, ow, oh);
      var hasAlpha = /png|webp|gif/i.test(file.type || "");
      var mime = hasAlpha ? "image/png" : "image/jpeg";
      var dataUrl = out.toDataURL(mime, 0.92);
      var baseName = (file.name || "icon").replace(/\.[^.]+$/, "");
      var outName = baseName + (hasAlpha ? ".png" : ".jpg");
      function finish(blob) {
        var f = blob;
        try { f = new File([blob], outName, { type: mime }); } catch (e) { try { blob.name = outName; } catch (e2) {} }
        cleanup();
        done && done({ dataUrl: dataUrl, file: f, blob: blob });
      }
      if (out.toBlob) out.toBlob(function (b) { finish(b || dataUrlToBlob(dataUrl, mime)); }, mime, 0.92);
      else finish(dataUrlToBlob(dataUrl, mime));
    }

    function build() {
      buildBase();
      overlay = document.createElement("div");
      overlay.className = "cropper-overlay";
      overlay.innerHTML =
        '<div class="cropper-dialog" role="dialog" aria-label="画像を編集">' +
          '<div class="cropper-title">画像を編集</div>' +
          '<div class="cropper-stage"><canvas class="cropper-cv"></canvas>' +
            '<div class="cropper-frame">' +
              '<div class="cropper-grid"></div>' +
              '<span class="cropper-h cropper-h-nw" data-h="nw"></span>' +
              '<span class="cropper-h cropper-h-ne" data-h="ne"></span>' +
              '<span class="cropper-h cropper-h-sw" data-h="sw"></span>' +
              '<span class="cropper-h cropper-h-se" data-h="se"></span>' +
            '</div>' +
          '</div>' +
          '<div class="cropper-bar">' +
            '<button class="cropper-btn cropper-cancel" data-c="cancel">キャンセル</button>' +
            '<button class="cropper-btn cropper-icon" data-c="rleft" title="左に回転" aria-label="左に回転">⟲</button>' +
            '<button class="cropper-btn cropper-icon" data-c="reset" title="リセット" aria-label="リセット">⭯</button>' +
            '<button class="cropper-btn cropper-icon" data-c="rright" title="右に回転" aria-label="右に回転">⟳</button>' +
            '<button class="cropper-btn cropper-apply" data-c="apply">適用</button>' +
          '</div>' +
        '</div>';
      document.body.appendChild(overlay);
      stage = overlay.querySelector(".cropper-stage");
      cv = overlay.querySelector(".cropper-cv");
      frame = overlay.querySelector(".cropper-frame");
      gridWrap = overlay.querySelector(".cropper-grid");

      rerender();
      window.addEventListener("resize", rerender);
      document.addEventListener("keydown", onKey, true);

      overlay.addEventListener("click", function (e) {
        var b = e.target.closest ? e.target.closest("[data-c]") : null;
        if (!b) { if (e.target === overlay) { /* 背景クリックでは閉じない=誤操作防止 */ } return; }
        var c = b.getAttribute("data-c");
        if (c === "cancel") { window.removeEventListener("resize", rerender); cleanup(); done && done(null); }
        else if (c === "apply") { window.removeEventListener("resize", rerender); apply(); }
        else if (c === "reset") { rot = 0; buildBase(); rerender(); }
        else if (c === "rleft") { rot = (rot + 270) % 360; buildBase(); rerender(); }
        else if (c === "rright") { rot = (rot + 90) % 360; buildBase(); rerender(); }
      });

      wireFrame();
    }

    function wireFrame() {
      var drag = null; // {mode:'move'|'nw'|'ne'|'sw'|'se', px,py, start:{...}}
      function pt(e) {
        var r = stage.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
      }
      function start(e, mode) {
        e.preventDefault();
        drag = { mode: mode, p: pt(e), start: { x: crop.x, y: crop.y, w: crop.w, h: crop.h } };
        try { e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId); } catch (err) {}
      }
      function move(e) {
        if (!drag) return;
        var p = pt(e), dx = p.x - drag.p.x, dy = p.y - drag.p.y, s = drag.start;
        if (drag.mode === "move") { crop.x = s.x + dx; crop.y = s.y + dy; }
        else {
          var x1 = s.x, y1 = s.y, x2 = s.x + s.w, y2 = s.y + s.h;
          if (drag.mode === "nw") { x1 = s.x + dx; y1 = s.y + dy; }
          else if (drag.mode === "ne") { x2 = s.x + s.w + dx; y1 = s.y + dy; }
          else if (drag.mode === "sw") { x1 = s.x + dx; y2 = s.y + s.h + dy; }
          else if (drag.mode === "se") { x2 = s.x + s.w + dx; y2 = s.y + s.h + dy; }
          crop.x = Math.min(x1, x2); crop.y = Math.min(y1, y2);
          crop.w = Math.abs(x2 - x1); crop.h = Math.abs(y2 - y1);
        }
        clampCrop(); drawFrame();
      }
      function end() { drag = null; }
      frame.addEventListener("pointerdown", function (e) {
        var h = e.target.getAttribute && e.target.getAttribute("data-h");
        start(e, h || "move");
      });
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", end);
      window.addEventListener("pointercancel", end);
      // overlayを閉じたらリスナーも落とす(cleanupで要素は消えるが window 側は明示解除)
      var origCleanup = cleanup;
      cleanup = function () {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        window.removeEventListener("pointercancel", end);
        window.removeEventListener("resize", rerender);
        origCleanup();
      };
    }
  }
  function dataUrlToBlob(dataUrl, mime) {
    var parts = dataUrl.split(",");
    var bin = atob(parts[1] || "");
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime || "application/octet-stream" });
  }

  // ── 直接アップロード(ページ→正本)。PUT /api/img(先)→ POST /api/persona/enqueue ──
  function getSyncToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  }
  function setSyncToken() {
    var v = window.prompt("go5-sync の書き込みトークン(SYNC_TOKEN)を貼り付け。\nこの端末のブラウザにだけ保存され、ページには埋め込まれない。\n(空で消去)", "");
    if (v === null) return false; // キャンセル
    v = (v || "").trim();
    try { if (v) localStorage.setItem(TOKEN_KEY, v); else localStorage.removeItem(TOKEN_KEY); } catch (e) {}
    return !!v;
  }
  function sha256hex(buf) {
    return crypto.subtle.digest("SHA-256", buf).then(function (d) {
      return Array.prototype.map.call(new Uint8Array(d), function (b) {
        return ("0" + b.toString(16)).slice(-2);
      }).join("");
    });
  }
  function setUploadMsg(text, isErr) {
    var sec = els.detail.querySelector(".av-section");
    if (!sec) return;
    var m = sec.querySelector(".av-upmsg");
    if (!m) return;
    m.hidden = false;
    m.textContent = text;
    m.className = "av-upmsg" + (isErr ? " is-err" : "");
  }
  function directUpload(name, file) {
    if (!file) return;
    // ★正本へ送る前に範囲トリミング(Chami msg1546525688914251846)。切り出した矩形だけをアップロードする。
    openCropper(file, function (res) {
      if (!res) { setUploadMsg("トリミングを取り消した=送信しなかった。", false); return; }
      uploadBlob(name, res.file);
    });
  }
  function uploadBlob(name, file) {
    if (!file) return;
    var token = getSyncToken();
    if (!token) { if (!setSyncToken()) { setUploadMsg("トークン未設定=中止した。", true); return; } token = getSyncToken(); }
    setUploadMsg("アップロード中… " + (file.name || "image"), false);
    file.arrayBuffer().then(function (buf) {
      return sha256hex(buf).then(function (sha) {
        // ★画像PUTが先(でないと enqueue が key_not_uploaded=409 で弾かれる)。
        return fetch(SYNC_BASE + "/api/img/" + sha, {
          method: "PUT",
          headers: { "X-Sync-Token": token, "Content-Type": file.type || "application/octet-stream" },
          body: buf
        }).then(function (r) {
          if (!r.ok) throw new Error("画像PUT失敗 HTTP " + r.status);
          return fetch(SYNC_BASE + "/api/persona/enqueue", {
            method: "POST",
            headers: { "X-Sync-Token": token, "Content-Type": "application/json" },
            body: JSON.stringify({ persona: name, key: sha, ct: file.type || "" })
          });
        }).then(function (r2) {
          return r2.json().catch(function () { return {}; }).then(function (j) {
            if (!r2.ok || !j.ok) throw new Error("投函失敗 HTTP " + r2.status + (j && j.error ? " " + j.error : ""));
            var id = sha.slice(-6);
            if (j.deduped) setUploadMsg("既に登録済みの画像だった(重複スキップ)。id …" + id, false);
            else setUploadMsg("投函できた(確認待ち)。取り込み常駐が動けば数十秒で台帳に反映される。id …" + id + (j.line ? " / 行" + j.line : ""), false);
          });
        });
      });
    }).catch(function (err) {
      setUploadMsg("失敗: " + String((err && err.message) || err) + "(トークン誤り/常駐未起動/通信不可の可能性)。", true);
    });
  }

  // ── ページ下部(③トークン設定 + ⑥まとめ置き場フォルダ)。各キャラの中からは外し、ここに1回だけ出す。
  function renderFooter() {
    if (!els.footer) return;
    var meta = state.meta || {};
    var src = meta._sources || {};
    // ⑥ 各キャラの「設定所在」は廃止。設定はここ1か所にまとまっている、という置き場フォルダだけを出す。
    var folderRows = [
      ["アイコン差分", src.アイコン],
      ["口調ルール", src.口調],
      ["呼称ルール", src.呼称],
      ["原典(character file)", src.原典]
    ].map(function (pair) {
      var v = pair[1];
      var content = v
        ? '<code class="path-code copyable" data-copy="' + esc(v) + '" title="クリックでコピー">' + esc(v) + "</code>"
        : '<span class="val-empty">無し</span>';
      return '<div class="source-row"><span class="source-k">' + esc(pair[0]) + "</span>" + content + "</div>";
    }).join("");

    var hasToken = !!getSyncToken();
    els.footer.innerHTML =
      '<section class="footer-section">' +
        '<h3 class="footer-title">設定のまとめ置き場</h3>' +
        '<p class="footer-note">各キャラの設定は下記のフォルダ/ファイルに集約されている(このページはそこから作った読み取り専用ビュー)。</p>' +
        '<div class="source-list">' + folderRows + "</div>" +
      "</section>" +
      '<section class="footer-section">' +
        '<h3 class="footer-title">書き込みトークン設定</h3>' +
        '<p class="footer-note">「直接アップロード」で正本へ画像を送るための go5-sync トークンを、この端末のブラウザにだけ保存する(ページには埋め込まない)。' +
          '現在: <span class="token-state ' + (hasToken ? "is-on" : "is-off") + '">' + (hasToken ? "設定済" : "未設定") + "</span></p>" +
        '<div class="footer-btns">' +
          '<button class="footer-btn" data-fact="settoken">🔑 トークンを設定/更新</button>' +
          (hasToken ? '<button class="footer-btn footer-btn-sub" data-fact="cleartoken">消去</button>' : "") +
        "</div>" +
      "</section>";
    wireFooter();
    wireCopyButtons(els.footer);
  }

  function wireFooter() {
    if (!els.footer) return;
    Array.prototype.forEach.call(els.footer.querySelectorAll("[data-fact]"), function (btn) {
      btn.addEventListener("click", function () {
        var fact = btn.getAttribute("data-fact");
        if (fact === "settoken") { setSyncToken(); renderFooter(); }
        else if (fact === "cleartoken") {
          try { localStorage.removeItem(TOKEN_KEY); } catch (e) {}
          renderFooter();
        }
      });
    });
  }

  var TONE_KNOWN_KEYS = ["first_person", "second_person", "signature_tails", "plain_only", "forbidden", "forbidden_to"];

  function toneRow(label, arr, isForbidden) {
    return '<div class="tone-sub-label">' + esc(label) + '</div><div class="chip-row">' +
      arr.map(function (v) {
        return '<span class="chip' + (isForbidden ? " chip-forbidden" : "") + '">' + esc(v) + "</span>";
      }).join("") +
      "</div>";
  }

  function renderToneSection(tone) {
    if (!tone) {
      return '<section class="detail-section" data-sec="口調">' + sectionTitle("口調", "") +
        '<div class="section-body"><div class="section-empty">口調ルール未登録</div></div></section>';
    }
    var body = "";
    if (tone.first_person && tone.first_person.length) body += toneRow("一人称", tone.first_person);
    if (tone.second_person && tone.second_person.length) body += toneRow("二人称", tone.second_person);
    if (tone.signature_tails && tone.signature_tails.length) body += toneRow("語尾/決め台詞", tone.signature_tails);
    if (typeof tone.plain_only === "boolean") {
      body += '<div class="tone-flag">タメ口のみ(plain_only): ' + (tone.plain_only ? "はい" : "いいえ") + "</div>";
    }
    if (tone.forbidden && tone.forbidden.length) body += toneRow("禁止表現", tone.forbidden, true);
    if (tone.forbidden_to && Object.keys(tone.forbidden_to).length) {
      body += '<div class="tone-sub-label">言い換え(forbidden_to)</div><div class="chip-row">' +
        Object.keys(tone.forbidden_to).map(function (k) {
          return '<span class="chip chip-swap">' + esc(k) + " → " + esc(tone.forbidden_to[k]) + "</span>";
        }).join("") + "</div>";
    }
    // 未知キーは取りこぼさず生値で列挙する(集約JSON側の項目追加に追従)。
    var extraKeys = Object.keys(tone).filter(function (k) { return TONE_KNOWN_KEYS.indexOf(k) < 0; });
    if (extraKeys.length) {
      body += extraKeys.map(function (k) {
        return '<div class="tone-sub-label">' + esc(k) + '</div><div class="section-raw">' + esc(JSON.stringify(tone[k])) + "</div>";
      }).join("");
    }
    return '<section class="detail-section" data-sec="口調">' + sectionTitle("口調", "") +
      '<div class="section-body">' + (body || '<div class="section-empty">項目なし</div>') + "</div></section>";
  }

  function renderRuleTable(rows, keyField) {
    var head = keyField === "speaker" ? "発言者" : "呼び方対象";
    var bodyRows = rows.map(function (r) {
      var allowed = (r.allowed || []).map(esc).join(" / ") || '<span class="val-empty">-</span>';
      var forbidden = (r.forbidden || []).map(esc).join(" / ") || '<span class="val-empty">-</span>';
      var yobisute = r.yobisute === true ? "呼び捨て" : (r.yobisute === false ? "呼び捨て禁止" : "-");
      var note = r.note ? esc(r.note) : "";
      // data-label= スマホで表が縦潰れするのを防ぐため、各セルへ見出しを持たせて
      // (CSS側で thead を隠し、セルの上に見出しを出す=1文字ずつ改行される縦長を解消)。
      return "<tr>" +
        '<td data-label="' + esc(head) + '">' + esc(r[keyField] || "") + "</td>" +
        '<td data-label="許可">' + allowed + "</td>" +
        '<td data-label="禁止">' + forbidden + "</td>" +
        '<td data-label="呼び捨て">' + yobisute + "</td>" +
        '<td class="rule-note" data-label="備考">' + note + "</td>" +
      "</tr>";
    }).join("");
    return '<table class="rule-table"><thead><tr><th>' + head + "</th><th>許可</th><th>禁止</th><th>呼び捨て</th><th>備考</th></tr></thead>" +
      "<tbody>" + bodyRows + "</tbody></table>";
  }

  function renderNamingToSection(toWhom) {
    toWhom = toWhom || {};
    var honorific = toWhom["敬称必須(honorific_required)"];
    var chamiEx = toWhom["Chami宛の例外"];
    var rules = toWhom["自分を対象にした個別ルール"] || [];
    // ⑤ 呼称は見出しに件数を出し、折り畳めるように(見やすさ)。
    var html = '<section class="detail-section naming-section" data-sec="呼称: この人をどう呼ぶか">' +
      sectionTitle("呼称: この人をどう呼ぶか", "(" + rules.length + "件)") + '<div class="section-body">';
    html += '<div class="naming-meta">' +
      '<div><span class="meta-k">敬称必須</span>' + fmtVal(honorific) + "</div>" +
      '<div><span class="meta-k">Chami宛の例外</span>' + fmtVal(chamiEx) + "</div>" +
    "</div>";
    html += rules.length ? renderRuleTable(rules, "speaker") : '<div class="section-empty">個別ルールなし</div>';
    html += "</div></section>";
    return html;
  }

  function renderNamingFromSection(fromWhom) {
    fromWhom = fromWhom || [];
    var html = '<section class="detail-section naming-section" data-sec="呼称: この人が誰をどう呼ぶか">' +
      sectionTitle("呼称: この人が誰をどう呼ぶか", "(" + fromWhom.length + "件)") + '<div class="section-body">';
    html += fromWhom.length ? renderRuleTable(fromWhom, "target") : '<div class="section-empty">個別ルールなし</div>';
    html += "</div></section>";
    return html;
  }

  // 設定所在の各キャラ表示は廃止(⑥)。まとめ置き場はページ下部 renderFooter に1回だけ出す。

  function wireCopyButtons(root) {
    root = root || els.detail;
    Array.prototype.forEach.call(root.querySelectorAll(".copyable"), function (node) {
      node.addEventListener("click", function () {
        var orig = node.textContent;
        copyTextChecked(node.getAttribute("data-copy") || node.textContent).then(function (ok) {
          node.textContent = ok ? "✓ コピーしました" : "✗ コピー失敗(手動で選択して)";
          setTimeout(function () { node.textContent = orig; }, ok ? 1000 : 2000);
        });
      });
    });
  }
})();
