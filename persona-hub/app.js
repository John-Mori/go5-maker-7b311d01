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
  // 手元編集(スクラッチパッド)。★静的ページは正本(persona_avatars.json / R2)へ書けないので、
  // ここでの追加/削除は「この端末の手元だけ」に残す(未反映)。Chamiが内容を人事部門へ伝えたら
  // 人事部門が正本へ反映する=そのための"差分に名前(#1/#2/id)を付けて指せる化"と変更メモが役目。
  var EDIT_KEY = "persona_hub_edits_v1";

  // 直接アップロード(ページから正本へ)。go5-sync Worker に PUT /api/img → POST /api/persona/enqueue。
  // ★トークンはページに埋めない=Chamiがこの端末のlocalStorageへ1回だけ入れる(埋めると誰でも書けてしまう・デブライネ制約)。
  var SYNC_BASE = "https://go5-sync.trustsignalbot.workers.dev";
  var TOKEN_KEY = "go5_sync_token_v1";

  var state = { personas: {}, names: [], filtered: [], selected: null, edits: {}, addSeq: 0 };
  var els = {};

  document.addEventListener("DOMContentLoaded", init);

  function loadEdits() {
    try { return JSON.parse(localStorage.getItem(EDIT_KEY)) || {}; } catch (e) { return {}; }
  }
  function saveEdits() {
    try { localStorage.setItem(EDIT_KEY, JSON.stringify(state.edits)); } catch (e) {}
  }
  function personaEdits(name) {
    var e = state.edits[name];
    return e || { removed: [], added: [] };
  }
  function setPersonaEdits(name, e) {
    // order は後付けフィールド(並び替え・不具合C)。旧スキーマ(removed/addedのみ)の保存分は
    // order 無しで読まれるが、参照側が常に (ed.order || []) で受けるので後方互換。
    var has = (e.removed && e.removed.length) || (e.added && e.added.length) || (e.order && e.order.length);
    if (has) { state.edits[name] = e; } else { delete state.edits[name]; }
    saveEdits();
  }
  function shortId(url) {
    var s = String(url || "").split("?")[0];
    var seg = s.split("/").pop() || s;
    return seg.slice(-6) || seg;
  }
  function currentUrls(name) {
    return normalizeUrls(((state.personas[name] || {}).アイコン || {}).url);
  }
  // 保存済みの並び順(order)を現行URL群へ適用する。order内で現存するURLを記録順に先へ、
  // orderに無い現行URL(=データ再生成で増えた分)を自然順で後ろへ。死んだURLは黙って落ちる。
  function applyOrder(urls, order) {
    var seen = {};
    var out = [];
    (order || []).forEach(function (u) {
      if (urls.indexOf(u) >= 0 && !seen[u]) { seen[u] = 1; out.push(u); }
    });
    urls.forEach(function (u) { if (!seen[u]) { seen[u] = 1; out.push(u); } });
    return out;
  }
  // 実効的な並び替えがあるか。自然順と同じなら null(=メモに載せない・件数にも数えない)。
  function reorderInfo(name) {
    var urls = currentUrls(name);
    var order = personaEdits(name).order || [];
    if (!order.length || urls.length < 2) return null;
    var eff = applyOrder(urls, order);
    for (var i = 0; i < urls.length; i++) {
      if (eff[i] !== urls[i]) return eff;
    }
    return null;
  }
  // 削除指定を現行データと突き合わせて棚卸し(不具合B)。live=現行画像に居る削除指定、
  // stale=もう存在しない亡霊(data.js再生成でURLが変わった等)。staleは黙ってメモに出さない。
  function splitRemoved(name) {
    var urls = currentUrls(name);
    var live = [], stale = [];
    (personaEdits(name).removed || []).forEach(function (u) {
      (urls.indexOf(u) >= 0 ? live : stale).push(u);
    });
    return { live: live, stale: stale };
  }
  // データ読込時の棚卸し。並び順(order)は表示上の好みなので、現行URLだけに刈り込み、
  // 自然順と一致するなら無効化する(applyOrderが生存分の相対順を保つ=それ自体が救済)。
  // ★removed の亡霊はここで自動削除しない=画面で警告し、メモでは「未解決」枠に出す(Chamiが判断)。
  function reconcileEdits() {
    Object.keys(state.edits).forEach(function (n) {
      if (!state.personas[n]) return; // データに居ない人格の分は触らない(メモの未解決枠行き)
      var e = state.edits[n];
      if (e.order && e.order.length) {
        var urls = currentUrls(n);
        var eff = applyOrder(urls, e.order);
        var changed = false;
        for (var i = 0; i < urls.length; i++) {
          if (eff[i] !== urls[i]) { changed = true; break; }
        }
        e.order = changed ? eff : [];
        setPersonaEdits(n, e);
      }
    });
  }

  function init() {
    els.list = document.getElementById("personaList");
    els.detail = document.getElementById("detailPane");
    els.count = document.getElementById("personaCount");
    els.error = document.getElementById("errorBanner");
    els.editBar = document.getElementById("editBar");
    state.edits = loadEdits();

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
    state.names = Object.keys(state.personas).sort(function (a, b) { return a.localeCompare(b, "ja"); });
    state.filtered = state.names.slice();
    reconcileEdits();
    renderList();
    renderEditBar();
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
      var hasEdit = !!state.edits[name];
      return "" +
        '<li class="persona-item' + active + '" data-name="' + esc(name) + '">' +
          '<div class="persona-item-name">' + esc(name) + "</div>" +
          '<div class="persona-item-dept">' + esc(dept) + "</div>" +
          '<div class="persona-item-badges">' +
            '<span class="badge badge-icon">画像 ' + iconCount + "</span>" +
            '<span class="badge ' + (hasTone ? "badge-on" : "badge-off") + '">口調 ' + (hasTone ? "設定あり" : "未設定") + "</span>" +
            '<span class="badge badge-naming">呼称 ' + namingCount + "件</span>" +
            (hasEdit ? '<span class="badge badge-edit">未反映</span>' : "") +
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
    html += renderSourceSection(e.設定所在);
    els.detail.innerHTML = html;
    wireCopyButtons();
    wireAvatarButtons(name);
    wireAvatarDrag(name);
    wireThumbZoom();
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

  function renderAvatarSection(icon, name) {
    var urls = normalizeUrls(icon && icon.url);
    var count = urls.length;
    var ed = personaEdits(name);
    var removedSet = {};
    (ed.removed || []).forEach(function (u) { removedSet[u] = 1; });
    var ordered = applyOrder(urls, ed.order || []);   // 手元の並び替えを適用した表示順
    var reordered = !!reorderInfo(name);
    var sp = splitRemoved(name);                       // stale=現行画像に無い亡霊の削除指定

    // ★削除したものは表から消す(Chami msg1546525688914251846)。ordered から removed を除いた
    //   「適用後に残る」ものだけを本体グリッドへ出す。削除指定は下の av-removed 帯へ畳んで戻せる。
    // #番号は現行正本での自然順(並び替えても番号は動かさない=人事部門がidで指せるように)。
    var visible = ordered.filter(function (u) { return !removedSet[u]; });
    var cells = visible.map(function (u) {
      var i = urls.indexOf(u);
      return '<div class="av-cell" data-url="' + esc(u) + '">' +
        '<span class="av-drag" draggable="true" title="ドラッグで並び替え(手元メモ)">⠿</span>' +
        '<img class="avatar-thumb" src="' + esc(u) + '" alt="" loading="lazy">' +
        '<span class="av-label">#' + (i + 1) + ' <span class="av-id">' + esc(shortId(u)) + "</span></span>" +
        '<button class="av-btn av-del" data-act="remove" data-url="' + esc(u) + '">🗑 削除</button>' +
      "</div>";
    });
    // 削除指定(現行画像に在るもの)は本体グリッドから外し、畳んだ「削除予定」帯で戻せるようにする。
    var removedHtml = "";
    if (sp.live.length) {
      removedHtml = '<div class="av-removed">' +
        '<div class="av-removed-head">削除予定 ' + sp.live.length + '件(反映すると正本から消える・戻せる)</div>' +
        '<div class="av-removed-list">' +
          sp.live.map(function (u) {
            return '<span class="av-removed-chip">#' + (urls.indexOf(u) + 1) +
              ' <span class="av-id">' + esc(shortId(u)) + '</span>' +
              '<button class="av-btn av-undo" data-act="undo-remove" data-url="' + esc(u) + '">↩ 戻す</button></span>';
          }).join("") +
        '</div></div>';
    }

    // 亡霊の削除指定(不具合B)=現行画像のどれも指していない。黙って出さず、ここで明示して選ばせる。
    var staleHtml = "";
    if (sp.stale.length) {
      staleHtml = '<div class="av-stale">' +
        '<div class="av-stale-head">⚠ この削除指定は現在の画像に無い(データが更新された)。変更メモには「未解決(要再確認)」として載る。</div>' +
        sp.stale.map(function (u) {
          return '<div class="av-stale-row"><span class="av-id">id ' + esc(shortId(u)) + '</span>' +
            '<button class="av-btn av-undo" data-act="undo-remove" data-url="' + esc(u) + '">この指定を消す</button></div>';
        }).join("") +
      "</div>";
    }
    var added = (ed.added || []).map(function (a) {
      return '<div class="av-cell is-added">' +
        '<img class="avatar-thumb" src="' + esc(a.dataUrl) + '" alt="" loading="lazy">' +
        '<span class="av-label">追加 <span class="av-id">' + esc(a.name || "") + "</span></span>" +
        '<span class="av-tag av-tag-add">追加予定</span><button class="av-btn av-undo" data-act="undo-add" data-id="' + esc(a.id) + '">↩ 取消</button>' +
      "</div>";
    });
    var body = (cells.length || added.length) ? cells.concat(added).join("") : '<div class="section-empty">画像なし</div>';
    return "" +
      '<section class="detail-section av-section" data-name="' + esc(name) + '">' +
        '<h3 class="section-title">アイコン差分 <span class="section-count">(' + count + "枚)</span></h3>" +
        '<div class="avatar-grid av-grid">' + body + "</div>" +
        removedHtml +
        staleHtml +
        '<div class="av-actions">' +
          '<button class="av-add-btn av-up-btn" data-act="upload">⬆ 直接アップロード(正本へ)</button>' +
          '<button class="av-add-btn av-add-local" data-act="add">＋ 手元メモに追加</button>' +
          '<button class="av-token-btn" data-act="settoken">🔑 トークン' + (getSyncToken() ? "設定済" : "未設定") + '</button>' +
          (reordered ? '<button class="av-btn av-undo av-order-reset" data-act="reset-order">↩ 並び替えを戻す</button>' : "") +
          '<input type="file" class="av-file" accept="image/*" hidden>' +
          '<input type="file" class="av-file-up" accept="image/*" hidden>' +
        "</div>" +
        '<div class="av-upmsg" hidden></div>' +
        '<p class="av-hint"><b>Discord添付は不要。</b>「直接アップロード」を押して画像を選ぶだけで正本へ入る(この端末に書き込みトークンを1回だけ設定する=🔑ボタン。ページには埋め込まない)。取り込み常駐が動けば数十秒で台帳に反映される。<br>ネット越しが使えない時の別口=取り込みフォルダ <code>local/persona_inbox/&lt;キャラ名&gt;/</code> に置いて <code>scripts/hr/ingest_persona_images.py</code>。「手元メモに追加」はこの端末だけの下書き(未反映)。サムネはクリックで拡大できる。<br>並び順は左の ⠿ をドラッグで変えられる(これも手元メモ=変更メモで人事部門へ伝わる。正本には書かない)。</p>' +
      "</section>";
  }

  // ── 手元編集(差分の追加/削除・localStorageスクラッチパッド) ──
  function wireAvatarButtons(name) {
    var sec = els.detail.querySelector(".av-section");
    if (!sec) return;
    Array.prototype.forEach.call(sec.querySelectorAll("[data-act]"), function (btn) {
      btn.addEventListener("click", function () {
        var act = btn.getAttribute("data-act");
        if (act === "remove") markRemove(name, btn.getAttribute("data-url"), true);
        else if (act === "undo-remove") markRemove(name, btn.getAttribute("data-url"), false);
        else if (act === "undo-add") undoAdd(name, btn.getAttribute("data-id"));
        else if (act === "add") { var f = sec.querySelector(".av-file"); if (f) f.click(); }
        else if (act === "upload") {
          if (!getSyncToken() && !setSyncToken()) { setUploadMsg("トークン未設定=中止した(🔑で1回だけ設定が要る)。", true); return; }
          var fu = sec.querySelector(".av-file-up"); if (fu) fu.click();
        }
        else if (act === "settoken") { setSyncToken(); if (state.selected) renderDetail(state.selected); }
        else if (act === "reset-order") {
          var edo = personaEdits(name); edo.order = [];
          setPersonaEdits(name, edo);
          refreshAfterEdit(name);
        }
      });
    });
    var file = sec.querySelector(".av-file");
    if (file) file.addEventListener("change", function () { handleAddFile(name, file.files && file.files[0]); file.value = ""; });
    var fileUp = sec.querySelector(".av-file-up");
    if (fileUp) fileUp.addEventListener("change", function () { directUpload(name, fileUp.files && fileUp.files[0]); fileUp.value = ""; });
  }

  // ── アイコンの並び替え(ドラッグ・不具合C) ──
  // .av-cell 内の ⠿ ハンドルだけを draggable にする=サムネのクリック(ライトボックス拡大)と衝突しない。
  // 並び順は localStorage(edits.order=URL配列)に貯め、変更メモへ載せる(★正本には書かない)。
  // renderDetail のたびに innerHTML ごと作り直す=リスナーは常に新要素へ付くので二重登録は起きない。
  function wireAvatarDrag(name) {
    var sec = els.detail.querySelector(".av-section");
    if (!sec) return;
    var grid = sec.querySelector(".av-grid");
    if (!grid) return;
    var cells = Array.prototype.slice.call(grid.querySelectorAll(".av-cell[data-url]"));
    if (cells.length < 2) return; // 1枚以下は並び替え不能
    var dragUrl = null;

    function clearDropMarks() {
      cells.forEach(function (c) { c.classList.remove("is-drop-before", "is-drop-after"); });
    }
    function endDrag() {
      dragUrl = null;
      clearDropMarks();
      cells.forEach(function (c) { c.classList.remove("is-dragging"); });
    }
    cells.forEach(function (cell) {
      var handle = cell.querySelector(".av-drag");
      if (handle) {
        handle.addEventListener("dragstart", function (e) {
          dragUrl = cell.getAttribute("data-url");
          cell.classList.add("is-dragging");
          // Firefoxは setData 無しだとドラッグ自体が始まらない
          try { e.dataTransfer.setData("text/plain", dragUrl); e.dataTransfer.effectAllowed = "move"; } catch (err) {}
        });
        handle.addEventListener("dragend", endDrag);
      }
      cell.addEventListener("dragover", function (e) {
        if (!dragUrl || dragUrl === cell.getAttribute("data-url")) return;
        e.preventDefault(); // drop を許可
        try { e.dataTransfer.dropEffect = "move"; } catch (err) {}
        var r = cell.getBoundingClientRect();
        var before = e.clientY < r.top + r.height / 2;
        clearDropMarks();
        cell.classList.add(before ? "is-drop-before" : "is-drop-after");
      });
      cell.addEventListener("dragleave", function () {
        cell.classList.remove("is-drop-before", "is-drop-after");
      });
      cell.addEventListener("drop", function (e) {
        if (!dragUrl) return;
        e.preventDefault();
        var target = cell.getAttribute("data-url");
        if (target === dragUrl) { endDrag(); return; }
        var r = cell.getBoundingClientRect();
        var before = e.clientY < r.top + r.height / 2;
        // 今画面に出ている順(=applyOrder適用済み)から新しい順を組む
        var disp = cells.map(function (c) { return c.getAttribute("data-url"); });
        disp.splice(disp.indexOf(dragUrl), 1);
        var to = disp.indexOf(target);
        disp.splice(before ? to : to + 1, 0, dragUrl);
        endDrag();
        applyReorder(name, disp);
      });
    });
  }

  function applyReorder(name, dispOrder) {
    var urls = currentUrls(name);
    var same = dispOrder.length === urls.length;
    if (same) {
      for (var i = 0; i < urls.length; i++) {
        if (dispOrder[i] !== urls[i]) { same = false; break; }
      }
    }
    var ed = personaEdits(name);
    ed.removed = ed.removed || []; ed.added = ed.added || [];
    ed.order = same ? [] : dispOrder.slice(); // 自然順へ戻したら並び替え指定ごと消す
    setPersonaEdits(name, ed);
    refreshAfterEdit(name);
  }

  function markRemove(name, url, on) {
    if (!url) return;
    var ed = personaEdits(name); ed.removed = ed.removed || []; ed.added = ed.added || [];
    var i = ed.removed.indexOf(url);
    if (on && i < 0) ed.removed.push(url);
    if (!on && i >= 0) ed.removed.splice(i, 1);
    setPersonaEdits(name, ed);
    refreshAfterEdit(name);
  }

  function undoAdd(name, id) {
    var ed = personaEdits(name); ed.added = (ed.added || []).filter(function (a) { return a.id !== id; });
    setPersonaEdits(name, ed);
    refreshAfterEdit(name);
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

  function handleAddFile(name, file) {
    if (!file) return;
    // ★追加前に範囲トリミング(Chami msg1546525688914251846)。適用した矩形だけを手元メモへ入れる。
    openCropper(file, function (res) {
      if (!res) return; // キャンセル
      var ed = personaEdits(name); ed.added = ed.added || []; ed.removed = ed.removed || [];
      state.addSeq += 1;
      ed.added.push({ id: "local-" + state.addSeq, name: file.name || "image", dataUrl: res.dataUrl });
      setPersonaEdits(name, ed);
      refreshAfterEdit(name);
    });
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

  function refreshAfterEdit(name) {
    renderList();
    renderEditBar();
    if (state.selected) renderDetail(state.selected);
  }

  function renderEditBar() {
    if (!els.editBar) return;
    var names = Object.keys(state.edits);
    var total = 0;
    names.forEach(function (n) {
      var e = state.edits[n];
      total += ((e.removed || []).length) + ((e.added || []).length) + (reorderInfo(n) ? 1 : 0);
    });
    if (!total) { els.editBar.hidden = true; els.editBar.innerHTML = ""; return; }
    els.editBar.hidden = false;
    els.editBar.innerHTML =
      '<div class="edit-bar-head">手元の変更 ' + total + "件 <span class=\"edit-bar-sub\">(未反映)</span></div>" +
      '<div class="edit-bar-btns">' +
        '<button class="eb-btn eb-copy">変更メモをコピー</button>' +
        '<button class="eb-btn eb-reset">全部取り消す</button>' +
      "</div>";
    els.editBar.querySelector(".eb-copy").addEventListener("click", copyChangeMemo);
    els.editBar.querySelector(".eb-reset").addEventListener("click", resetEdits);
  }

  function buildChangeMemo() {
    var lines = ["【人格ハブ 手元の変更(正本へ反映して)】"];
    var unresolved = [];
    Object.keys(state.edits).sort(function (a, b) { return a.localeCompare(b, "ja"); }).forEach(function (n) {
      var e = state.edits[n];
      var urls = currentUrls(n);
      var parts = [];
      // 削除は現行データに解決できたものだけを #番号+id で出す(不具合B)。
      // 解決できない亡霊(data.js再生成でURLが変わった等)は黙って出さず、末尾の未解決枠へ。
      var sp = splitRemoved(n);
      sp.live.forEach(function (u) {
        parts.push("削除 #" + (urls.indexOf(u) + 1) + " (id " + shortId(u) + ")");
      });
      sp.stale.forEach(function (u) {
        unresolved.push("■" + n + ": 削除指定 (id " + shortId(u) + ") … 現行データに該当画像なし(データ更新で消えた可能性)");
      });
      if (e.added && e.added.length) parts.push("追加 " + e.added.length + "枚 (画像は local/persona_inbox/" + n + "/ に置く=Discord添付は不要)");
      var eff = reorderInfo(n);
      if (eff) {
        parts.push("並び替え(新しい順・#は現行の番号): " + eff.map(function (u) {
          return "#" + (urls.indexOf(u) + 1) + "(id " + shortId(u) + ")";
        }).join(" → "));
      }
      if (parts.length) lines.push("■" + n + ": " + parts.join(" / "));
    });
    if (unresolved.length) {
      lines.push("");
      lines.push("【未解決(要再確認)=現行画像に一致しない指定。このまま反映しないこと】");
      unresolved.forEach(function (l) { lines.push(l); });
    }
    return lines.join("\n");
  }

  function copyChangeMemo() {
    var memo = buildChangeMemo();
    // ★成功した時だけ「✓ コピーした」を出す(不具合A)。失敗を成功に見せると
    // Chamiが古いクリップボード内容を貼る=「前と一緒」事故になる。
    copyTextChecked(memo).then(function (ok) {
      var b = els.editBar && els.editBar.querySelector(".eb-copy"); // 再描画後でも生きている方を取る
      if (ok) {
        var manual = els.editBar && els.editBar.querySelector(".eb-manual");
        if (manual) manual.parentNode.removeChild(manual);
        if (b) { b.textContent = "✓ コピーした"; setTimeout(function () { b.textContent = "変更メモをコピー"; }, 1200); }
      } else {
        if (b) { b.textContent = "✗ コピー失敗(下の本文を手動で)"; setTimeout(function () { b.textContent = "変更メモをコピー"; }, 3000); }
        showManualMemo(memo);
      }
    });
  }

  // 自動コピーが全滅した時の最後の砦=メモ本文を選択可能なtextareaで出す。黙って成功を装わない。
  function showManualMemo(text) {
    if (!els.editBar) return;
    var old = els.editBar.querySelector(".eb-manual");
    if (old) old.parentNode.removeChild(old);
    var d = document.createElement("div");
    d.className = "eb-manual";
    d.innerHTML =
      '<div class="eb-manual-msg">自動コピーに失敗した(権限/非フォーカス等)。下の本文を全選択して手動でコピーして(Ctrl+C / 長押し→コピー):</div>' +
      '<textarea class="eb-manual-ta" readonly rows="8"></textarea>';
    els.editBar.appendChild(d);
    var ta = d.querySelector(".eb-manual-ta");
    ta.value = text; // innerHTMLでなくvalueに入れる=エスケープ不要で安全
    ta.addEventListener("focus", function () { ta.select(); });
    ta.focus();
    ta.select();
  }

  function resetEdits() {
    state.edits = {};
    saveEdits();
    renderList();
    renderEditBar();
    if (state.selected) renderDetail(state.selected);
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
      return '<section class="detail-section"><h3 class="section-title">口調</h3>' +
        '<div class="section-empty">口調ルール未登録</div></section>';
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
    return '<section class="detail-section"><h3 class="section-title">口調</h3>' +
      (body || '<div class="section-empty">項目なし</div>') + "</section>";
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
    var html = '<section class="detail-section"><h3 class="section-title">呼称: この人をどう呼ぶか</h3>';
    html += '<div class="naming-meta">' +
      '<div><span class="meta-k">敬称必須</span>' + fmtVal(honorific) + "</div>" +
      '<div><span class="meta-k">Chami宛の例外</span>' + fmtVal(chamiEx) + "</div>" +
    "</div>";
    html += rules.length ? renderRuleTable(rules, "speaker") : '<div class="section-empty">個別ルールなし</div>';
    html += "</section>";
    return html;
  }

  function renderNamingFromSection(fromWhom) {
    fromWhom = fromWhom || [];
    var html = '<section class="detail-section"><h3 class="section-title">呼称: この人が誰をどう呼ぶか</h3>';
    html += fromWhom.length ? renderRuleTable(fromWhom, "target") : '<div class="section-empty">個別ルールなし</div>';
    html += "</section>";
    return html;
  }

  var SOURCE_LABELS = {
    原典_characterfile: "原典(character file)",
    口調ルール: "口調ルール",
    呼称ルール: "呼称ルール",
    アイコン差分: "アイコン差分",
    スプライト: "スプライト",
    文脈: "文脈"
  };

  function renderSourceSection(src) {
    src = src || {};
    var rows = Object.keys(SOURCE_LABELS).map(function (k) {
      var v = src[k];
      var content = v
        ? '<code class="path-code copyable" data-copy="' + esc(v) + '" title="クリックでコピー">' + esc(v) + "</code>"
        : '<span class="val-empty">無し</span>';
      return '<div class="source-row"><span class="source-k">' + esc(SOURCE_LABELS[k]) + "</span>" + content + "</div>";
    }).join("");
    return '<section class="detail-section"><h3 class="section-title">設定所在</h3><div class="source-list">' + rows + "</div></section>";
  }

  function wireCopyButtons() {
    Array.prototype.forEach.call(els.detail.querySelectorAll(".copyable"), function (node) {
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
