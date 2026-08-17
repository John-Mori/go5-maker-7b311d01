/**
 * persona-hub/app.js — 人格設定 一覧ビューア + 端末内エディタの配線。
 *
 * 表示データは data.js が焼き込む window.PERSONA_HUB_DATA(正本 口調ルール.json / 呼称ルール.json /
 * persona_avatars.json の派生物)。既存本体ファイル(本体の index.html/app.js/GAS/Worker)には一切依存しない。
 *
 * ★書き戻しについて(重要・正直に)= このページはGitHub Pages(静的配信)なので、ブラウザから
 *   リポジトリの正本ファイルは直接書けない。編集/削除は localStorage(この端末)に「差分」として貯め、
 *   ページ表示にはその差分を重ねて見せる。正本(常駐が読む設定)へ恒久反映するには
 *   「差分を見る → 差分をコピー」で出したJSONを人事部門へ渡す=人事が正本へ焼いて再生成する。
 *   サーバー無しで往復ゼロの自動保存にするには小さな書き戻しエンドポイント(基盤)が要る=別途。
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
  var OVERLAY_KEY = "persona_hub_overlay_v1";

  // baseline = 正本由来の生データ(不変)。personas = baseline に overlay を重ねた表示用。
  var state = { baseline: {}, personas: {}, names: [], filtered: [], selected: null, editMode: false };
  var overlay = loadOverlay();
  var els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els.list = document.getElementById("personaList");
    els.detail = document.getElementById("detailPane");
    els.count = document.getElementById("personaCount");
    els.error = document.getElementById("errorBanner");
    els.editToggle = document.getElementById("editToggle");
    els.diffBtn = document.getElementById("diffBtn");
    els.diffCount = document.getElementById("diffCount");
    els.editHint = document.getElementById("editHint");
    els.diffModal = document.getElementById("diffModal");
    els.diffText = document.getElementById("diffText");
    els.diffDeleted = document.getElementById("diffDeleted");

    wireControls();

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

  // ── overlay(差分)の入出力 ──
  function loadOverlay() {
    try {
      var raw = localStorage.getItem(OVERLAY_KEY);
      if (!raw) return { edits: {}, deleted: [] };
      var o = JSON.parse(raw);
      return { edits: (o && o.edits) || {}, deleted: (o && o.deleted) || [] };
    } catch (e) { return { edits: {}, deleted: [] }; }
  }
  function saveOverlay() {
    try { localStorage.setItem(OVERLAY_KEY, JSON.stringify(overlay)); } catch (e) {}
    updateDiffBadge();
  }
  function overlayEditCount() {
    return Object.keys(overlay.edits).length + overlay.deleted.length;
  }
  function deep(v) { return v == null ? v : JSON.parse(JSON.stringify(v)); }

  function applyOverlay() {
    var out = {};
    Object.keys(state.baseline).forEach(function (name) {
      if (overlay.deleted.indexOf(name) >= 0) return;
      var e = deep(state.baseline[name]) || {};
      var ed = overlay.edits[name];
      if (ed) {
        if (ed.口調 !== undefined) e.口調 = deep(ed.口調);
        if (ed.avatarUrls !== undefined) e.アイコン = { 枚数: ed.avatarUrls.length, url: ed.avatarUrls.slice() };
      }
      out[name] = e;
    });
    return out;
  }

  function recompute() {
    state.personas = applyOverlay();
    state.names = Object.keys(state.personas).sort(function (a, b) { return a.localeCompare(b, "ja"); });
    state.filtered = state.names.slice();
  }

  function onData(json) {
    state.baseline = (json && json.personas) || {};
    recompute();
    renderList();
    updateDiffBadge();
    if (state.selected && state.personas[state.selected]) selectPersona(state.selected);
    else if (state.filtered.length) selectPersona(state.filtered[0]);
    else els.detail.innerHTML = '<div class="detail-empty">キャラクターがいません。</div>';
  }

  function onFetchError(err) {
    els.list.innerHTML = '<li class="persona-empty">読み込みに失敗しました</li>';
    els.error.hidden = false;
    els.error.innerHTML =
      "先に <code>python scripts/hr/persona_settings_index.py</code> を実行して集約JSONを生成してください" +
      "(<code>local/persona_settings_index.json</code>)。<span class=\"error-detail\"></span>";
    try { els.error.querySelector(".error-detail").textContent = String((err && err.message) || err || ""); } catch (e) {}
  }

  // ── ヘッダのコントロール ──
  function wireControls() {
    els.editToggle.addEventListener("click", function () {
      state.editMode = !state.editMode;
      els.editToggle.classList.toggle("is-on", state.editMode);
      els.editToggle.textContent = state.editMode ? "✓ 編集モード(ON)" : "✎ 編集モード";
      els.diffBtn.hidden = !state.editMode;
      els.editHint.hidden = !state.editMode;
      document.body.classList.toggle("edit-on", state.editMode);
      renderList();
      if (state.selected) renderDetail(state.selected);
    });
    els.diffBtn.addEventListener("click", openDiff);
    document.getElementById("diffClose").addEventListener("click", function () { els.diffModal.hidden = true; });
    els.diffModal.addEventListener("click", function (ev) { if (ev.target === els.diffModal) els.diffModal.hidden = true; });
    document.getElementById("diffCopy").addEventListener("click", function () {
      copyText(els.diffText.value, null);
      var b = document.getElementById("diffCopy"); var o = b.textContent;
      b.textContent = "✓ コピーしました"; setTimeout(function () { b.textContent = o; }, 1200);
    });
    document.getElementById("diffReset").addEventListener("click", function () {
      if (!overlayEditCount()) { els.diffModal.hidden = true; return; }
      if (!window.confirm("この端末の編集/削除を全て取り消して正本の状態へ戻します。よろしいですか?")) return;
      overlay = { edits: {}, deleted: [] };
      saveOverlay();
      recompute();
      renderList();
      var name = state.selected && state.personas[state.selected] ? state.selected : (state.filtered[0] || null);
      state.selected = name;
      if (name) renderDetail(name); else els.detail.innerHTML = '<div class="detail-empty">キャラクターがいません。</div>';
      els.diffModal.hidden = true;
    });
  }

  function updateDiffBadge() {
    var n = overlayEditCount();
    els.diffCount.hidden = !n;
    els.diffCount.textContent = String(n);
  }

  function openDiff() {
    var payload = { _patch: "persona-hub", _note: "この差分を人事部門へ渡すと正本へ焼かれます", deleted: overlay.deleted.slice(), edits: overlay.edits };
    els.diffText.value = overlayEditCount() ? JSON.stringify(payload, null, 1) : "(編集はまだありません)";
    if (overlay.deleted.length) {
      els.diffDeleted.hidden = false;
      els.diffDeleted.innerHTML = "削除したキャラ: " + overlay.deleted.map(function (nm) {
        return '<span class="del-chip" data-restore="' + esc(nm) + '">' + esc(nm) + ' <b>復元</b></span>';
      }).join("");
      Array.prototype.forEach.call(els.diffDeleted.querySelectorAll(".del-chip"), function (chip) {
        chip.addEventListener("click", function () { restorePersona(chip.getAttribute("data-restore")); openDiff(); });
      });
    } else {
      els.diffDeleted.hidden = true; els.diffDeleted.innerHTML = "";
    }
    els.diffModal.hidden = false;
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
      var edited = !!overlay.edits[name];
      var active = name === state.selected ? " is-active" : "";
      var delBtn = state.editMode ? '<button class="item-del" data-del="' + esc(name) + '" title="このキャラを削除" type="button">🗑</button>' : "";
      var editedTag = edited ? '<span class="edited-tag">編集済</span>' : "";
      return "" +
        '<li class="persona-item' + active + '" data-name="' + esc(name) + '">' +
          delBtn +
          '<div class="persona-item-name">' + esc(name) + editedTag + "</div>" +
          '<div class="persona-item-dept">' + esc(dept) + "</div>" +
          '<div class="persona-item-badges">' +
            '<span class="badge badge-icon">画像 ' + iconCount + "</span>" +
            '<span class="badge ' + (hasTone ? "badge-on" : "badge-off") + '">口調 ' + (hasTone ? "設定あり" : "未設定") + "</span>" +
            '<span class="badge badge-naming">呼称 ' + namingCount + "件</span>" +
          "</div>" +
        "</li>";
    }).join("");
    Array.prototype.forEach.call(els.list.querySelectorAll(".persona-item"), function (li) {
      li.addEventListener("click", function (ev) {
        if (ev.target.closest(".item-del")) return;
        selectPersona(li.getAttribute("data-name"));
      });
    });
    Array.prototype.forEach.call(els.list.querySelectorAll(".item-del"), function (btn) {
      btn.addEventListener("click", function (ev) { ev.stopPropagation(); deletePersona(btn.getAttribute("data-del")); });
    });
  }

  function selectPersona(name) {
    state.selected = name;
    renderList();
    renderDetail(name);
  }

  // ── 削除/復元 ──
  function deletePersona(name) {
    if (!window.confirm('「' + name + '」をこの端末の一覧から削除します(正本は差分を人事部門へ渡すまで変わりません)。よろしいですか?')) return;
    if (overlay.deleted.indexOf(name) < 0) overlay.deleted.push(name);
    delete overlay.edits[name];
    saveOverlay();
    recompute();
    if (state.selected === name) state.selected = state.filtered[0] || null;
    renderList();
    if (state.selected) renderDetail(state.selected);
    else els.detail.innerHTML = '<div class="detail-empty">キャラクターがいません。</div>';
  }
  function restorePersona(name) {
    var i = overlay.deleted.indexOf(name);
    if (i >= 0) overlay.deleted.splice(i, 1);
    saveOverlay();
    recompute();
    renderList();
  }

  // ── 詳細 ──
  function renderDetail(name) {
    var e = state.personas[name];
    if (!e) { els.detail.innerHTML = '<div class="detail-empty">データがありません。</div>'; return; }
    var html = "";
    html += '<div class="detail-head"><h2>' + esc(name) + "</h2>" +
      '<div class="detail-dept">' + esc(e.所属部門 || "所属部門: 未設定") + "</div></div>";
    html += state.editMode ? renderAvatarEdit(name, e.アイコン) : renderAvatarSection(e.アイコン);
    html += state.editMode ? renderToneEdit(name, e.口調) : renderToneSection(e.口調);
    html += renderNamingToSection((e.呼称 || {}).この人をどう呼ぶか);
    html += renderNamingFromSection((e.呼称 || {}).この人が誰をどう呼ぶか);
    html += renderSourceSection(e.設定所在);
    if (state.editMode) {
      html += '<div class="edit-note">呼称ルールはテーブル構造のため、この画面では編集できません。' +
        '変更は口調・アイコンをここで直し、呼称は文章で人事部門へ伝えてください。</div>';
    }
    els.detail.innerHTML = html;
    wireCopyButtons();
    if (state.editMode) wireEditControls(name);
  }

  function normalizeUrls(u) {
    if (!u) return [];
    return Array.isArray(u) ? u.filter(Boolean) : [u];
  }

  function fmtVal(v) {
    if (v === null || v === undefined || v === "") return '<span class="val-empty">なし</span>';
    return esc(String(v));
  }

  function renderAvatarSection(icon) {
    var urls = normalizeUrls(icon && icon.url);
    var count = (icon && icon.枚数) != null ? icon.枚数 : urls.length;
    var thumbs = urls.length
      ? urls.map(function (u) { return '<img class="avatar-thumb" src="' + esc(u) + '" alt="" loading="lazy">'; }).join("")
      : '<div class="section-empty">画像なし</div>';
    return "" +
      '<section class="detail-section">' +
        '<h3 class="section-title">アイコン差分 <span class="section-count">(' + count + "枚)</span></h3>" +
        '<div class="avatar-grid">' + thumbs + "</div>" +
      "</section>";
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
    var extraKeys = Object.keys(tone).filter(function (k) { return TONE_KNOWN_KEYS.indexOf(k) < 0; });
    if (extraKeys.length) {
      body += extraKeys.map(function (k) {
        return '<div class="tone-sub-label">' + esc(k) + '</div><div class="section-raw">' + esc(JSON.stringify(tone[k])) + "</div>";
      }).join("");
    }
    return '<section class="detail-section"><h3 class="section-title">口調</h3>' +
      (body || '<div class="section-empty">項目なし</div>') + "</section>";
  }

  // ── 編集: 口調 ──
  function ensureToneDraft(name) {
    overlay.edits[name] = overlay.edits[name] || {};
    if (overlay.edits[name].口調 === undefined) {
      var cur = state.personas[name] && state.personas[name].口調;
      overlay.edits[name].口調 = cur ? deep(cur) : {};
    }
    return overlay.edits[name].口調;
  }
  function pruneEdit(name) {
    // 編集が正本と実質同じ(空)なら overlay からキーごと落とす=差分を綺麗に保つ。
    var ed = overlay.edits[name];
    if (!ed) return;
    if (ed.口調 !== undefined && ed.口調 && !Object.keys(ed.口調).length) delete ed.口調;
    if (!Object.keys(ed).length) delete overlay.edits[name];
  }

  var TONE_EDIT_FIELDS = [
    { key: "first_person", label: "一人称" },
    { key: "second_person", label: "二人称" },
    { key: "signature_tails", label: "語尾/決め台詞" },
    { key: "forbidden", label: "禁止表現", forbidden: true }
  ];

  function editChipArray(name, field, label, isForbidden) {
    var tone = state.personas[name].口調 || {};
    var arr = tone[field] || [];
    var chips = arr.map(function (v, i) {
      return '<span class="chip echip' + (isForbidden ? " chip-forbidden" : "") + '">' + esc(v) +
        '<button class="chip-x" data-field="' + field + '" data-i="' + i + '" type="button" aria-label="削除">✕</button></span>';
    }).join("");
    return '<div class="tone-sub-label">' + esc(label) + '</div>' +
      '<div class="chip-row">' + (chips || '<span class="val-empty">なし</span>') +
        '<span class="chip-add-wrap"><input class="chip-add-input" data-field="' + field + '" type="text" placeholder="追加..." />' +
        '<button class="chip-add-btn" data-field="' + field + '" type="button">＋</button></span>' +
      '</div>';
  }

  function renderToneEdit(name, tone) {
    tone = state.personas[name].口調 || {};
    var body = "";
    body += TONE_EDIT_FIELDS.map(function (f) { return editChipArray(name, f.key, f.label, f.forbidden); }).join("");
    var po = tone.plain_only === true;
    body += '<div class="tone-flag edit-flag"><label><input type="checkbox" id="plainOnly"' + (po ? " checked" : "") + "> タメ口のみ(plain_only)</label></div>";
    // forbidden_to(言い換え表)
    var ft = tone.forbidden_to || {};
    var ftRows = Object.keys(ft).map(function (k) {
      return '<div class="ft-row"><span class="chip chip-swap">' + esc(k) + " → " + esc(ft[k]) +
        '</span><button class="ft-x" data-k="' + esc(k) + '" type="button" aria-label="削除">✕</button></div>';
    }).join("");
    body += '<div class="tone-sub-label">言い換え(forbidden_to)</div><div class="ft-list">' + (ftRows || '<span class="val-empty">なし</span>') +
      '<div class="ft-add"><input id="ftFrom" type="text" placeholder="禁止語" /><span>→</span><input id="ftTo" type="text" placeholder="言い換え先" />' +
      '<button id="ftAdd" type="button">＋</button></div></div>';
    return '<section class="detail-section edit-section"><h3 class="section-title">口調(編集)</h3>' + body + "</section>";
  }

  function wireEditControls(name) {
    var d = els.detail;
    // アイコンURL
    Array.prototype.forEach.call(d.querySelectorAll(".avatar-del"), function (b) {
      b.addEventListener("click", function () {
        var arr = ensureAvatarDraft(name);
        arr.splice(parseInt(b.getAttribute("data-i"), 10), 1);
        commit(name);
      });
    });
    var avAddBtn = d.querySelector("#avAddBtn");
    if (avAddBtn) avAddBtn.addEventListener("click", function () {
      var inp = d.querySelector("#avAddInput");
      var v = (inp.value || "").trim();
      if (!v) return;
      var arr = ensureAvatarDraft(name);
      arr.push(v);
      commit(name);
    });
    // 口調チップの削除
    Array.prototype.forEach.call(d.querySelectorAll(".chip-x"), function (b) {
      b.addEventListener("click", function () {
        var t = ensureToneDraft(name);
        var f = b.getAttribute("data-field");
        var arr = t[f] || [];
        arr.splice(parseInt(b.getAttribute("data-i"), 10), 1);
        t[f] = arr;
        commit(name);
      });
    });
    // 口調チップの追加
    Array.prototype.forEach.call(d.querySelectorAll(".chip-add-btn"), function (b) {
      var f = b.getAttribute("data-field");
      var inp = d.querySelector('.chip-add-input[data-field="' + f + '"]');
      function add() {
        var v = (inp.value || "").trim();
        if (!v) return;
        var t = ensureToneDraft(name);
        t[f] = (t[f] || []).concat([v]);
        commit(name);
      }
      b.addEventListener("click", add);
      if (inp) inp.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); add(); } });
    });
    // plain_only
    var po = d.querySelector("#plainOnly");
    if (po) po.addEventListener("change", function () {
      var t = ensureToneDraft(name);
      if (po.checked) t.plain_only = true; else delete t.plain_only;
      commit(name);
    });
    // forbidden_to
    Array.prototype.forEach.call(d.querySelectorAll(".ft-x"), function (b) {
      b.addEventListener("click", function () {
        var t = ensureToneDraft(name);
        if (t.forbidden_to) delete t.forbidden_to[b.getAttribute("data-k")];
        if (t.forbidden_to && !Object.keys(t.forbidden_to).length) delete t.forbidden_to;
        commit(name);
      });
    });
    var ftAdd = d.querySelector("#ftAdd");
    if (ftAdd) ftAdd.addEventListener("click", function () {
      var from = (d.querySelector("#ftFrom").value || "").trim();
      var to = (d.querySelector("#ftTo").value || "").trim();
      if (!from || !to) return;
      var t = ensureToneDraft(name);
      t.forbidden_to = t.forbidden_to || {};
      t.forbidden_to[from] = to;
      commit(name);
    });
  }

  function commit(name) {
    pruneEdit(name);
    saveOverlay();
    recompute();
    renderList();
    renderDetail(name);
  }

  // ── 編集: アイコン ──
  function ensureAvatarDraft(name) {
    overlay.edits[name] = overlay.edits[name] || {};
    if (overlay.edits[name].avatarUrls === undefined) {
      var cur = (state.personas[name] && state.personas[name].アイコン && state.personas[name].アイコン.url) || [];
      overlay.edits[name].avatarUrls = normalizeUrls(cur);
    }
    return overlay.edits[name].avatarUrls;
  }

  function renderAvatarEdit(name, icon) {
    var urls = normalizeUrls(icon && icon.url);
    var thumbs = urls.length ? urls.map(function (u, i) {
      return '<div class="avatar-edit-item"><img class="avatar-thumb" src="' + esc(u) + '" alt="" loading="lazy">' +
        '<button class="avatar-del" data-i="' + i + '" type="button" aria-label="削除">✕</button></div>';
    }).join("") : '<div class="section-empty">画像なし</div>';
    return '<section class="detail-section edit-section"><h3 class="section-title">アイコン差分(編集) <span class="section-count">(' + urls.length + "枚)</span></h3>" +
      '<div class="avatar-grid">' + thumbs + "</div>" +
      '<div class="av-add"><input id="avAddInput" type="text" placeholder="画像URLを貼り付けて追加" /><button id="avAddBtn" type="button">＋ 追加</button></div>' +
      "</section>";
  }

  function renderRuleTable(rows, keyField) {
    var head = keyField === "speaker" ? "発言者" : "呼び方対象";
    var bodyRows = rows.map(function (r) {
      var allowed = (r.allowed || []).map(esc).join(" / ") || '<span class="val-empty">-</span>';
      var forbidden = (r.forbidden || []).map(esc).join(" / ") || '<span class="val-empty">-</span>';
      var yobisute = r.yobisute === true ? "呼び捨て" : (r.yobisute === false ? "呼び捨て禁止" : "-");
      var note = r.note ? esc(r.note) : "";
      return "<tr>" +
        "<td>" + esc(r[keyField] || "") + "</td>" +
        "<td>" + allowed + "</td>" +
        "<td>" + forbidden + "</td>" +
        "<td>" + yobisute + "</td>" +
        '<td class="rule-note">' + note + "</td>" +
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
