// 5ch台本エディタ(止血版) — 一覧取得→編集→保存。
// このファイルは 5ch-daihon/ に閉じており、5秒動画メーカー本体(index.html/app.js/core/js)とは無関係。

// ★Workerのカスタムドメイン/workers.dev をここに置き換える(Chami手番)。
// 例: "https://go5-5ch-daihon.<subdomain>.workers.dev" または独自ドメイン。
const API_BASE = "https://REPLACE-ME.workers.dev";

const els = {
  projectSelect: document.getElementById("project-select"),
  projectStatus: document.getElementById("project-status"),
  cutsList: document.getElementById("cuts-list"),
  cardTemplate: document.getElementById("cut-card-template"),
};

init();

async function init() {
  await loadProjects();
  els.projectSelect.addEventListener("change", () => {
    const key = els.projectSelect.value;
    if (key) loadCutlist(key);
  });
}

async function loadProjects() {
  setStatus(els.projectStatus, "読み込み中...", "");
  try {
    const r = await fetch(API_BASE + "/api/projects", { credentials: "include" });
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || ("http_" + r.status));
    renderProjectOptions(j.projects || []);
    setStatus(els.projectStatus, (j.projects || []).length + "件", "ok");
  } catch (e) {
    els.projectSelect.innerHTML = '<option value="">読み込み失敗</option>';
    setStatus(els.projectStatus, "取得失敗: " + e.message, "error");
  }
}

function renderProjectOptions(keys) {
  els.projectSelect.innerHTML = "";
  if (!keys.length) {
    els.projectSelect.innerHTML = '<option value="">(プロジェクトがありません)</option>';
    return;
  }
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "選択してください";
  els.projectSelect.appendChild(placeholder);
  for (const key of keys) {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = projectLabel(key);
    els.projectSelect.appendChild(opt);
  }
}

// "projects/holodri_noel/cutlist.yaml" → "holodri_noel"(表示用の短い名前)。
function projectLabel(key) {
  const parts = String(key).split("/");
  return parts.length >= 2 ? parts[1] : key;
}

async function loadCutlist(key) {
  els.cutsList.innerHTML = '<p class="empty-note">読み込み中...</p>';
  try {
    const r = await fetch(API_BASE + "/api/cutlist?key=" + encodeURIComponent(key), { credentials: "include" });
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || ("http_" + r.status));
    renderCuts(key, j.cuts || []);
  } catch (e) {
    els.cutsList.innerHTML = '<p class="empty-note">取得失敗: ' + escapeHtml(e.message) + "</p>";
  }
}

function renderCuts(key, cuts) {
  els.cutsList.innerHTML = "";
  if (!cuts.length) {
    els.cutsList.innerHTML = '<p class="empty-note">コマがありません。</p>';
    return;
  }
  for (const cut of cuts) {
    els.cutsList.appendChild(buildCutCard(key, cut));
  }
}

function buildCutCard(key, cut) {
  const node = els.cardTemplate.content.cloneNode(true);
  const card = node.querySelector(".cut-card");

  card.querySelector(".cut-card__id").textContent = cut.cut_id || "(cut_id不明)";
  card.querySelector(".cut-card__image").textContent = fileNameOf(cut.image_file);
  card.querySelector(".cut-card__badge--phase").textContent = cut.phase || "-";
  card.querySelector(".cut-card__badge--type").textContent = cut.cut_type || "-";

  for (const fieldEl of card.querySelectorAll(".cut-field")) {
    const field = fieldEl.getAttribute("data-field");
    const textarea = fieldEl.querySelector("textarea");
    const btn = fieldEl.querySelector(".btn-save");
    const status = fieldEl.querySelector(".save-status");
    textarea.value = cut[field] || "";

    btn.addEventListener("click", async () => {
      btn.disabled = true;
      setStatus(status, "保存中...", "");
      try {
        await saveField(key, cut.cut_id, field, textarea.value);
        setStatus(status, "保存しました", "ok");
      } catch (e) {
        setStatus(status, "保存失敗: " + e.message, "error");
      } finally {
        btn.disabled = false;
      }
    });
  }

  return node;
}

async function saveField(key, cutId, field, value) {
  const r = await fetch(API_BASE + "/api/cutlist?key=" + encodeURIComponent(key), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cut_id: cutId, field, value }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.ok) throw new Error((j && j.error) || ("http_" + r.status));
  return j;
}

function fileNameOf(path) {
  const s = String(path || "");
  const parts = s.split(/[\\/]/);
  return parts[parts.length - 1] || s;
}

function setStatus(el, text, kind) {
  el.textContent = text;
  el.className = el.className.replace(/\s*status-text--\w+/g, "").replace(/\s*save-status--\w+/g, "");
  if (kind === "ok") el.classList.add(el.classList.contains("status-text") ? "status-text--ok" : "save-status--ok");
  if (kind === "error") el.classList.add(el.classList.contains("status-text") ? "status-text--error" : "save-status--error");
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
