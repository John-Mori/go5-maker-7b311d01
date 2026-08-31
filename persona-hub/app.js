/**
 * persona-hub/app.js — 人格設定 一覧ビューアの配線。
 *
 * データは data.js(window.PERSONA_HUB_DATA・正本の派生物)優先、無ければ local/persona_settings_index.json
 * を fetch。★正本(persona_avatars.json / R2)へは書かない=差分の追加/削除は「手元(localStorage)だけ」の
 * スクラッチパッド。Chamiが変更メモを人事部門へ伝え、人事部門が正本へ反映する運用(静的ページの制約)。
 * 既存本体ファイル(index.html/app.js/GAS/Worker)には一切依存しない新規追加ページ。
 * core/util.js の esc/copyText は既存のまま流用(読むだけ・改変なし)。
 */
(function () {
  "use strict";

  var Util = window.Go5Util || {};
  var esc = Util.esc || function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };
  var copyText = Util.copyText || function (text) {
    try { navigator.clipboard.writeText(String(text == null ? "" : text)); } catch (e) {}
  };

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
    var has = (e.removed && e.removed.length) || (e.added && e.added.length);
    if (has) { state.edits[name] = e; } else { delete state.edits[name]; }
    saveEdits();
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

    var cells = urls.map(function (u, i) {
      var rm = removedSet[u];
      return '<div class="av-cell' + (rm ? " is-removed" : "") + '">' +
        '<img class="avatar-thumb" src="' + esc(u) + '" alt="" loading="lazy">' +
        '<span class="av-label">#' + (i + 1) + ' <span class="av-id">' + esc(shortId(u)) + "</span></span>" +
        (rm
          ? '<span class="av-tag av-tag-del">削除予定</span><button class="av-btn av-undo" data-act="undo-remove" data-url="' + esc(u) + '">↩ 戻す</button>'
          : '<button class="av-btn av-del" data-act="remove" data-url="' + esc(u) + '">🗑 削除</button>') +
      "</div>";
    });
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
        '<div class="av-actions">' +
          '<button class="av-add-btn av-up-btn" data-act="upload">⬆ 直接アップロード(正本へ)</button>' +
          '<button class="av-add-btn av-add-local" data-act="add">＋ 手元メモに追加</button>' +
          '<button class="av-token-btn" data-act="settoken">🔑 トークン' + (getSyncToken() ? "設定済" : "未設定") + '</button>' +
          '<input type="file" class="av-file" accept="image/*" hidden>' +
          '<input type="file" class="av-file-up" accept="image/*" hidden>' +
        "</div>" +
        '<div class="av-upmsg" hidden></div>' +
        '<p class="av-hint"><b>Discord添付は不要。</b>「直接アップロード」を押して画像を選ぶだけで正本へ入る(この端末に書き込みトークンを1回だけ設定する=🔑ボタン。ページには埋め込まない)。取り込み常駐が動けば数十秒で台帳に反映される。<br>ネット越しが使えない時の別口=取り込みフォルダ <code>local/persona_inbox/&lt;キャラ名&gt;/</code> に置いて <code>scripts/hr/ingest_persona_images.py</code>。「手元メモに追加」はこの端末だけの下書き(未反映)。サムネはクリックで拡大できる。</p>' +
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
      });
    });
    var file = sec.querySelector(".av-file");
    if (file) file.addEventListener("change", function () { handleAddFile(name, file.files && file.files[0]); });
    var fileUp = sec.querySelector(".av-file-up");
    if (fileUp) fileUp.addEventListener("change", function () { directUpload(name, fileUp.files && fileUp.files[0]); fileUp.value = ""; });
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

  function handleAddFile(name, file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      var ed = personaEdits(name); ed.added = ed.added || []; ed.removed = ed.removed || [];
      state.addSeq += 1;
      ed.added.push({ id: "local-" + state.addSeq, name: file.name || "image", dataUrl: String(reader.result || "") });
      setPersonaEdits(name, ed);
      refreshAfterEdit(name);
    };
    reader.readAsDataURL(file);
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
    names.forEach(function (n) { var e = state.edits[n]; total += ((e.removed || []).length) + ((e.added || []).length); });
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

  function copyChangeMemo() {
    var lines = ["【人格ハブ 手元の変更(正本へ反映して)】"];
    Object.keys(state.edits).sort(function (a, b) { return a.localeCompare(b, "ja"); }).forEach(function (n) {
      var e = state.edits[n];
      var urls = normalizeUrls(((state.personas[n] || {}).アイコン || {}).url);
      var parts = [];
      (e.removed || []).forEach(function (u) {
        var i = urls.indexOf(u);
        parts.push("削除 #" + (i >= 0 ? i + 1 : "?") + " (id " + shortId(u) + ")");
      });
      if (e.added && e.added.length) parts.push("追加 " + e.added.length + "枚 (画像は local/persona_inbox/" + n + "/ に置く=Discord添付は不要)");
      if (parts.length) lines.push("■" + n + ": " + parts.join(" / "));
    });
    copyText(lines.join("\n"));
    var b = els.editBar.querySelector(".eb-copy");
    if (b) { var o = b.textContent; b.textContent = "✓ コピーした"; setTimeout(function () { b.textContent = o; }, 1200); }
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
        copyText(node.getAttribute("data-copy") || node.textContent, null);
        var orig = node.textContent;
        node.textContent = "✓ コピーしました";
        setTimeout(function () { node.textContent = orig; }, 1000);
      });
    });
  }
})();
