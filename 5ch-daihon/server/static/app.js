// 5ch台本エディタ(ローカル版) — Flaskサーバー(同一オリジン)向け。
// public/app.js(止血版)を土台に、画像選択・voice_reading/voice_char/voice_role・YMMP生成を追加。

const els = {
  projectSelect: document.getElementById("project-select"),
  projectStatus: document.getElementById("project-status"),
  btnGenerate: document.getElementById("btn-generate"),
  cutsList: document.getElementById("cuts-list"),
  cardTemplate: document.getElementById("cut-card-template"),
  genResult: document.getElementById("generate-result"),
  genSummary: document.getElementById("generate-summary"),
  genPath: document.getElementById("generate-path"),
  genStdout: document.getElementById("generate-stdout"),
  genStderr: document.getElementById("generate-stderr"),
  validateLog: document.getElementById("validate-log"),
};

let currentProject = null; // /api/project/<name> の応答をそのまま保持

init();

async function init() {
  await loadProjects();
  els.projectSelect.addEventListener("change", () => {
    const key = els.projectSelect.value;
    if (key) loadProject(key);
  });
  els.btnGenerate.addEventListener("click", onGenerate);
}

async function loadProjects() {
  setStatus(els.projectStatus, "読み込み中...", "");
  try {
    const r = await fetch("/api/projects");
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || ("http_" + r.status));
    renderProjectOptions(j.projects || []);
    setStatus(els.projectStatus, (j.projects || []).length + "件", "ok");
  } catch (e) {
    els.projectSelect.innerHTML = '<option value="">読み込み失敗</option>';
    setStatus(els.projectStatus, "取得失敗: " + e.message, "error");
  }
}

function renderProjectOptions(projects) {
  els.projectSelect.innerHTML = "";
  if (!projects.length) {
    els.projectSelect.innerHTML = '<option value="">(プロジェクトがありません)</option>';
    return;
  }
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "選択してください";
  els.projectSelect.appendChild(placeholder);
  for (const p of projects) {
    const opt = document.createElement("option");
    opt.value = p.name;
    opt.textContent = p.name;
    els.projectSelect.appendChild(opt);
  }
}

async function loadProject(name) {
  els.cutsList.innerHTML = '<p class="empty-note">読み込み中...</p>';
  els.btnGenerate.disabled = true;
  els.genResult.classList.add("generate-result--hidden");
  try {
    const r = await fetch("/api/project/" + encodeURIComponent(name));
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || ("http_" + r.status));
    currentProject = j;
    renderCuts(name, j.cuts || []);
    els.btnGenerate.disabled = false;
  } catch (e) {
    els.cutsList.innerHTML = '<p class="empty-note">取得失敗: ' + escapeHtml(e.message) + "</p>";
  }
}

function renderCuts(name, cuts) {
  els.cutsList.innerHTML = "";
  if (!cuts.length) {
    els.cutsList.innerHTML = '<p class="empty-note">コマがありません。</p>';
    return;
  }
  for (const cut of cuts) {
    els.cutsList.appendChild(buildCutCard(name, cut));
  }
}

function buildCutCard(name, cut) {
  const node = els.cardTemplate.content.cloneNode(true);
  const card = node.querySelector(".cut-card");
  const images = (currentProject && currentProject.images) || [];
  const voiceChars = (currentProject && currentProject.voice_char_options) || [];
  const voiceRoles = (currentProject && currentProject.voice_role_options) || [];

  card.querySelector(".cut-card__id").textContent = cut.cut_id || "(cut_id不明)";
  card.querySelector(".cut-card__badge--phase").textContent = cut.phase || "-";
  card.querySelector(".cut-card__badge--type").textContent = cut.cut_type || "-";

  // 画像選択
  const imgSelect = card.querySelector(".cut-image-select");
  const imgPreview = card.querySelector(".cut-image-preview");
  imgSelect.innerHTML = "";
  const noneOpt = document.createElement("option");
  noneOpt.value = "";
  noneOpt.textContent = "(未選択)";
  imgSelect.appendChild(noneOpt);
  for (const img of images) {
    const opt = document.createElement("option");
    opt.value = img;
    opt.textContent = img;
    imgSelect.appendChild(opt);
  }
  const currentImageRel = fileNameFromAbs(cut.image_file, images);
  imgSelect.value = currentImageRel || "";
  updateImagePreview(imgPreview, name, imgSelect.value);
  imgSelect.addEventListener("change", () => updateImagePreview(imgPreview, name, imgSelect.value));

  // caption/narration/reaction/voice_reading テキスト欄
  for (const fieldEl of card.querySelectorAll(".cut-field[data-field]")) {
    const field = fieldEl.getAttribute("data-field");
    const textarea = fieldEl.querySelector("textarea");
    textarea.value = cut[field] || "";
  }

  // voice_char / voice_role
  const charSelect = card.querySelector(".cut-voice-char");
  charSelect.innerHTML = '<option value="">(未指定)</option>';
  for (const c of voiceChars) {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c;
    charSelect.appendChild(opt);
  }
  charSelect.value = cut.voice_char || "";

  const roleSelect = card.querySelector(".cut-voice-role");
  roleSelect.innerHTML = '<option value="">(未指定)</option>';
  for (const rname of voiceRoles) {
    const opt = document.createElement("option");
    opt.value = rname;
    opt.textContent = rname;
    roleSelect.appendChild(opt);
  }
  roleSelect.value = cut.voice_role || "";

  const status = card.querySelector(".save-status");
  const btn = card.querySelector(".btn-save");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    setStatus(status, "保存中...", "");
    try {
      const payload = { cut_id: cut.cut_id };
      for (const fieldEl of card.querySelectorAll(".cut-field[data-field]")) {
        const field = fieldEl.getAttribute("data-field");
        payload[field] = fieldEl.querySelector("textarea").value;
      }
      payload.voice_char = charSelect.value;
      payload.voice_role = roleSelect.value;
      payload.image_file = imgSelect.value;
      await saveCut(name, payload);
      setStatus(status, "保存しました", "ok");
    } catch (e) {
      setStatus(status, "保存失敗: " + e.message, "error");
    } finally {
      btn.disabled = false;
    }
  });

  return node;
}

function updateImagePreview(imgEl, projectName, relPath) {
  if (!relPath) {
    imgEl.style.display = "none";
    imgEl.src = "";
    return;
  }
  imgEl.style.display = "block";
  imgEl.src = "/api/image?project=" + encodeURIComponent(projectName) + "&file=" + encodeURIComponent(relPath);
}

async function saveCut(name, payload) {
  const r = await fetch("/api/project/" + encodeURIComponent(name), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cuts: [payload] }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.ok) throw new Error((j && (j.error || (j.details && j.details.join(", ")))) || ("http_" + r.status));
  return j;
}

async function onGenerate() {
  if (!currentProject) return;
  const name = currentProject.name;
  els.btnGenerate.disabled = true;
  els.genResult.classList.remove("generate-result--hidden");
  els.genSummary.textContent = "生成中... (VOICEVOX合成が有効な型は時間がかかります)";
  els.genSummary.className = "generate-summary";
  els.genPath.textContent = "";
  els.genStdout.textContent = "";
  els.genStderr.textContent = "";
  els.validateLog.textContent = "";
  try {
    const r = await fetch("/api/generate/" + encodeURIComponent(name), { method: "POST" });
    const j = await r.json();
    const gen = j.generator || {};
    els.genStdout.textContent = gen.stdout || "";
    els.genStderr.textContent = gen.stderr || "";
    if (j.validate) {
      els.validateLog.textContent =
        "returncode=" + j.validate.returncode + "\n" +
        (j.validate.stdout || "") + "\n" + (j.validate.stderr || "");
    } else {
      els.validateLog.textContent = "(検査は実行されませんでした。生成に失敗した可能性があります)";
    }
    els.genPath.textContent = j.ymmp_path
      ? ("出力先: " + j.ymmp_path + (j.ymmp_exists ? " (存在確認OK)" : " (ファイルが見つかりません)"))
      : "出力先を特定できませんでした";
    if (j.ok) {
      els.genSummary.textContent = "生成に成功しました";
      els.genSummary.className = "generate-summary generate-summary--ok";
    } else {
      els.genSummary.textContent = "生成に失敗しました(returncode=" + gen.returncode + ")。ログを確認してください";
      els.genSummary.className = "generate-summary generate-summary--error";
    }
  } catch (e) {
    els.genSummary.textContent = "リクエスト失敗: " + e.message;
    els.genSummary.className = "generate-summary generate-summary--error";
  } finally {
    els.btnGenerate.disabled = false;
  }
}

// 画像の絶対パス(cut.image_file)から、assets一覧(相対パス)に対応するものを見つける。
function fileNameFromAbs(absPath, images) {
  const s = String(absPath || "");
  if (!s) return "";
  const norm = s.replace(/\\/g, "/").toLowerCase();
  for (const rel of images) {
    if (norm.endsWith(rel.toLowerCase())) return rel;
  }
  return "";
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
