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
          '<button class="av-add-btn" data-act="add">＋ 画像を追加</button>' +
          '<input type="file" class="av-file" accept="image/*" hidden>' +
        "</div>" +
        '<p class="av-hint">ページ内の変更は<b>この端末の手元だけ</b>に残る(未反映)。消した/足したら「変更メモをコピー」して人事部門へ伝えれば正本へ反映する。追加した画像は、その便に元画像も添付して送る。</p>' +
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
      });
    });
    var file = sec.querySelector(".av-file");
    if (file) file.addEventListener("change", function () { handleAddFile(name, file.files && file.files[0]); });
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
      if (e.added && e.added.length) parts.push("追加 " + e.added.length + "枚 (この便に画像を添付)");
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
