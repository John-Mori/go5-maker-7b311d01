// カレンダーUI（設計書 §7.9）：5週ローリング・自動公開・長期休暇トグル・要確認バッジ
window.SCH = window.SCH || {};
(function (SCH) {
  const dt = SCH.dt;
  const gen = SCH.gen;
  const config = SCH.config;
  const master = window.__SCHEDULE_MASTER__;
  const vplan = window.__VERIFICATION_PLAN__ || null; // 4週間検証計画（任意）

  // 検証モードのKPI入力に出す主要KPI（残りはCSV出力時に空欄で補完）
  const VERIFY_KEY_KPIS = ["viewed_rate", "avg_view_sec", "retention", "product_page_rate", "ext_ctr", "cvr"];
  const VARIANTS = ["", "早夜系", "深夜系", "A", "B"];

  let store = null;
  let weekOffset = 0;       // 表示の前後移動（週単位）
  let verificationMode = false;
  let lastRender = null;    // { slots, dayMetas }
  let editingId = null;

  // ---- 日付（JST） ----
  function todayJST() {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    }).format(new Date());
  }
  function mondayOf(s) {
    const w = dt.weekdayIndex(s);     // 0=日..6=土
    const delta = w === 0 ? -6 : 1 - w;
    return dt.addDays(s, delta);
  }

  // ---- 描画範囲・生成範囲 ----
  function displayStart() {
    return dt.addDays(mondayOf(todayJST()), weekOffset * 7);
  }
  function genWindow() {
    const baseMon = mondayOf(todayJST());
    const ds = displayStart();
    const genStart = ds < baseMon ? ds : baseMon;
    const farEnd = dt.addDays(baseMon, config.generateWeeksAhead * 7 - 1);
    const dispEnd = dt.addDays(ds, config.displayWeeks * 7 - 1);
    const genEnd = farEnd > dispEnd ? farEnd : dispEnd;
    return { genStart, genEnd };
  }

  // ---- 中核：生成→保存→描画 ----
  async function recomputeAndRender() {
    const overrides = store.getOverrides();
    const existing = store.getSlotData();
    const { genStart, genEnd } = genWindow();
    const result = gen.generateRange(genStart, genEnd, master, config, overrides, existing);
    lastRender = result;
    await store.saveSlots(result.slots); // 自動公開・要確認などの変化を永続化
    render(result);
  }

  function dayTypeClass(meta) {
    return {
      "平日型": "dt-weekday", "休前日型": "dt-eve",
      "連休初日型": "dt-runstart", "連休中日型": "dt-runmid", "最終日型": "dt-last",
    }[meta.dayType] || "dt-weekday";
  }

  function render(result) {
    const root = document.getElementById("calendar");
    root.innerHTML = "";
    document.body.classList.toggle("verify-mode", verificationMode);

    const ds = displayStart();
    const metaByDate = {};
    for (const m of result.dayMetas) metaByDate[m.date] = m;

    // ヘッダ情報
    const reviewCount = result.review.length;
    document.getElementById("status-bar").innerHTML =
      `<span>表示: ${ds} 〜 ${dt.addDays(ds, config.displayWeeks * 7 - 1)}（${config.displayWeeks}週）</span>` +
      `<span class="muted">保存先: ${store.adapterName}</span>` +
      (verificationMode ? `<span class="badge-verify">🧪 検証モード（検枠でKPI記録可）</span>` : "") +
      (reviewCount ? `<span class="badge-review">要確認 ${reviewCount}</span>` : "");

    for (let wk = 0; wk < config.displayWeeks; wk++) {
      const weekStart = dt.addDays(ds, wk * 7);
      const weekEl = document.createElement("div");
      weekEl.className = "week";

      const wh = document.createElement("div");
      wh.className = "week-head";
      wh.textContent = `${weekStart} 〜 ${dt.addDays(weekStart, 6)}`;
      weekEl.appendChild(wh);

      const grid = document.createElement("div");
      grid.className = "week-grid";
      for (let i = 0; i < 7; i++) {
        const date = dt.addDays(weekStart, i);
        grid.appendChild(renderDay(date, metaByDate[date], result.slots));
      }
      weekEl.appendChild(grid);
      root.appendChild(weekEl);
    }
  }

  function renderDay(date, meta, slots) {
    const cell = document.createElement("div");
    cell.className = "day " + (meta ? dayTypeClass(meta) : "");
    if (meta && meta.date === todayJST()) cell.classList.add("is-today");
    if (meta && meta.longVacTag) cell.classList.add("has-longvac");

    const md = date.slice(5).replace("-", "/");
    const head = document.createElement("div");
    head.className = "day-head";
    head.innerHTML =
      `<span class="day-md ${meta && (meta.isHoliday || meta.weekdayIndex === 0) ? "holiday-num" : ""} ${meta && meta.weekdayIndex === 6 ? "sat-num" : ""}">${md}</span>` +
      `<span class="day-wd">(${meta ? meta.weekday : ""})</span>` +
      `<span class="day-type-badge">${meta ? meta.dayType : ""}</span>`;
    cell.appendChild(head);

    const tags = document.createElement("div");
    tags.className = "day-tags";
    if (meta && meta.holidayName) tags.innerHTML += `<span class="tag tag-holiday">${meta.holidayName}</span>`;
    if (meta && meta.longVacTag) {
      const label = meta.longVacTag === "obon" ? "お盆" : meta.longVacTag === "newyear" ? "年末年始" : meta.longVacTag;
      tags.innerHTML += `<span class="tag tag-longvac">${label}</span>`;
    }
    if (meta && meta.hasOverride) tags.innerHTML += `<span class="tag tag-override">上書き</span>`;
    cell.appendChild(tags);

    // 長期休暇/休日トグル（ボタン一つ・§7.4）
    const ctrl = document.createElement("div");
    ctrl.className = "day-ctrl";
    ctrl.innerHTML =
      `<button data-act="off" title="休みにする">＋休</button>` +
      `<button data-act="weekday" title="平日化（祝日でも可・警告）">平日</button>` +
      `<button data-act="follow" title="自動判定に従う">自動</button>` +
      `<button data-act="obon" title="お盆タグ">盆</button>` +
      `<button data-act="newyear" title="年末年始タグ">正</button>`;
    ctrl.querySelectorAll("button").forEach((b) => {
      b.addEventListener("click", () => onDayAction(date, meta, b.dataset.act));
    });
    cell.appendChild(ctrl);

    // 6枠
    const slotWrap = document.createElement("div");
    slotWrap.className = "slots";
    for (let idx = 0; idx < config.slotsPerDay; idx++) {
      const s = slots[gen.slotId(date, idx)];
      if (s) slotWrap.appendChild(renderSlot(s));
    }
    cell.appendChild(slotWrap);
    return cell;
  }

  function renderSlot(s) {
    const el = document.createElement("div");
    el.className = `slot role-${s.role}`;
    if (s.role === "本命") el.classList.add("is-peak");
    if (s.needs_review) el.classList.add("needs-review");
    if (s.verify_flag) el.classList.add("has-verify");
    if (s.verification && s.verification.variant) el.classList.add("has-variant");
    el.classList.add("st-" + statusClass(s.status));

    const time = s.time; // "24:00" はそのまま表示（深夜枠＝翌日0時の意味）
    const variant = s.verification && s.verification.variant;
    el.innerHTML =
      `<div class="slot-row1"><span class="slot-time">${time}</span>` +
      `<span class="slot-role">${s.role}</span>` +
      (s.verify_flag ? `<span class="slot-verify" title="検証対象">検</span>` : "") +
      (variant ? `<span class="slot-variant" title="検証の変種">${variant}</span>` : "") +
      (s.needs_review ? `<span class="slot-review" title="要確認">!</span>` : "") +
      `</div>` +
      `<div class="slot-row2">${s.title ? escapeHtml(s.title) : `<span class="muted">${escapeHtml(s.genre)}</span>`}</div>` +
      `<div class="slot-row3"><span class="status-dot st-${statusClass(s.status)}"></span>${s.status}</div>`;
    el.addEventListener("click", () => openEditor(s));
    return el;
  }

  function statusClass(st) {
    return { "未着手": "todo", "制作済・未予約": "made", "予約登録済": "scheduled", "公開済": "published", "取り下げ": "dropped" }[st] || "todo";
  }

  // ---- 日アクション（休/平日/自動/お盆/正月） ----
  async function onDayAction(date, meta, act) {
    if (act === "off") {
      await store.setOverride(date, { force_day_off: true });
    } else if (act === "weekday") {
      if (meta && meta.isHoliday &&
        !confirm(`${date} は法定祝日（${meta.holidayName}）です。平日化しますか？`)) return;
      await store.setOverride(date, { force_day_off: false });
    } else if (act === "follow") {
      await store.setOverride(date, { force_day_off: null, long_vac_tag_override: null });
    } else if (act === "obon") {
      await store.setOverride(date, { long_vac_tag_override: "obon", force_day_off: true });
    } else if (act === "newyear") {
      await store.setOverride(date, { long_vac_tag_override: "newyear", force_day_off: true });
    }
    await recomputeAndRender(); // 近傍連動カスケード（§7.5）
  }

  // ---- スロット編集モーダル ----
  function openEditor(s) {
    editingId = s.id;
    const m = document.getElementById("modal");
    m.querySelector(".modal-body").innerHTML = `
      <h3>${s.date}（${s.day_type}） ${s.time} / ${s.role}</h3>
      ${s.needs_review ? `<div class="warn">要確認：day-type変更でテンプレと差異あり。時刻は自動変更していません。</div>` : ""}
      ${s.verify_flag ? `<div class="info">検証対象枠。${s.alt_hypothesis ? "対立仮説: " + escapeHtml(s.alt_hypothesis) : ""}</div>` : ""}
      <label>ステータス
        <select id="f-status">${config.statusEnum.map((x) => `<option ${x === s.status ? "selected" : ""}>${x}</option>`).join("")}</select>
      </label>
      <label>タイトル<input id="f-title" value="${escapeAttr(s.title)}"></label>
      <label>動画ID<input id="f-video" value="${escapeAttr(s.video_id)}"></label>
      <label>URL<input id="f-url" value="${escapeAttr(s.url)}"></label>
      <label>ジャンル<input id="f-genre" value="${escapeAttr(s.genre)}"></label>
      <label>概要欄リンク<input id="f-desc" value="${escapeAttr(s.desc_link)}"></label>
      <label>SNS導線<input id="f-sns" value="${escapeAttr(s.sns_funnel)}"></label>
      <label>メモ<textarea id="f-notes">${escapeHtml(s.notes)}</textarea></label>
      <div class="muted">公開予定: ${s.scheduled_at}</div>
      ${renderVerificationSection(s)}
    `;
    m.classList.add("open");
  }

  // 検証セクション（verify_flag枠 or 検証モード時に表示）
  function renderVerificationSection(s) {
    if (!s.verify_flag && !verificationMode) return "";
    const v = s.verification || {};
    const meas = v.measurements || {};
    const points = (vplan && vplan.measurement_points) || ["1h", "3h", "6h", "24h", "48h"];
    const kpiLabel = (k) => {
      const found = vplan && vplan.kpis && vplan.kpis.find((x) => x.key === k);
      return found ? found.label.replace(/（.*?）/g, "") : k;
    };
    const head = `<th>計測</th>` + VERIFY_KEY_KPIS.map((k) => `<th title="${k}">${kpiLabel(k)}</th>`).join("");
    const rows = points.map((p) => {
      const mp = meas[p] || {};
      const cells = VERIFY_KEY_KPIS.map((k) =>
        `<td><input class="vk" data-pt="${p}" data-k="${k}" value="${escapeAttr(mp[k] || "")}"></td>`).join("");
      return `<tr><th>${p}</th>${cells}</tr>`;
    }).join("");
    return `
      <fieldset class="verify-box">
        <legend>🧪 検証（${s.verify_flag ? "検証対象枠" : "任意記録"}）</legend>
        <div class="verify-row">
          <label>変種<select id="v-variant">${VARIANTS.map((x) =>
            `<option value="${x}" ${x === (v.variant || "") ? "selected" : ""}>${x || "（なし）"}</option>`).join("")}</select></label>
          <label>週<input id="v-week" type="number" min="1" max="4" value="${escapeAttr(v.week || "")}" style="width:60px"></label>
        </div>
        <table class="verify-grid"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>
        <div class="muted">空欄可。CSV出力時は全列(${(vplan && vplan.log_columns ? vplan.log_columns.length : 0)}列)へ展開。閾値: Viewed率≥60%/平均視聴≥9秒/維持≥70%。</div>
      </fieldset>`;
  }

  async function saveEditor() {
    if (!editingId) return;
    const s = lastRender.slots[editingId];
    if (!s) return;
    const g = (id) => document.getElementById(id).value;
    s.status = g("f-status");
    s.title = g("f-title");
    s.video_id = g("f-video");
    s.url = g("f-url");
    s.genre = g("f-genre");
    s.desc_link = g("f-desc");
    s.sns_funnel = g("f-sns");
    s.notes = g("f-notes");
    s.needs_review = false; // ユーザー確認済み
    captureVerification(s);
    if (!s.created_at) s.created_at = new Date().toISOString();
    await store.upsertSlot(s);
    closeEditor();
    await recomputeAndRender();
  }
  function closeEditor() {
    editingId = null;
    document.getElementById("modal").classList.remove("open");
  }

  // 編集モーダルの検証入力を slot.verification へ取り込む
  function captureVerification(s) {
    const variantEl = document.getElementById("v-variant");
    if (!variantEl) return; // 検証セクション非表示
    const measurements = {};
    document.querySelectorAll(".vk").forEach((inp) => {
      const val = inp.value.trim();
      if (!val) return;
      const pt = inp.dataset.pt, k = inp.dataset.k;
      (measurements[pt] = measurements[pt] || {})[k] = val;
    });
    const variant = variantEl.value;
    const week = document.getElementById("v-week").value;
    if (!variant && !week && !Object.keys(measurements).length) {
      delete s.verification;
    } else {
      s.verification = { variant, week, measurements };
    }
  }

  // 検証ログCSV出力（verification_plan の log_columns に展開）
  function exportVerificationCSV() {
    const cols = (vplan && vplan.log_columns) || [];
    const rows = [];
    const slots = (lastRender && lastRender.slots) || {};
    for (const id of Object.keys(slots)) {
      const s = slots[id];
      if (!s.verification) continue;
      const v = s.verification;
      const points = Object.keys(v.measurements || {});
      const emit = points.length ? points : ["—"];
      for (const pt of emit) {
        const mp = (v.measurements && v.measurements[pt]) || {};
        const base = {
          log_id: `${s.date}_${s.slot_index}_${v.variant || "x"}`,
          video_id: s.video_id || "", slot_id: s.id, date: s.date, day_type: s.day_type,
          role: s.role, genre: s.genre || "", variant: v.variant || "", publish_time: s.time,
          week: v.week || "", measured_at: pt === "—" ? "" : pt, note: s.notes || "",
        };
        rows.push(cols.map((c) => csvCell(base[c] !== undefined ? base[c] : (mp[c] || ""))).join(","));
      }
    }
    const csv = cols.join(",") + "\n" + rows.join("\n") + "\n";
    downloadText(csv, "verification_log.csv", "text/csv");
    if (!rows.length) alert("検証データのある枠がありません。枠を開いて『変種』やKPIを入力してください。");
  }
  function csvCell(v) {
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
  function downloadText(text, filename, mime) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: mime }));
    a.download = filename;
    a.click();
  }

  // ---- ユーティリティ ----
  function escapeHtml(s) {
    return String(s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }
  function escapeAttr(s) {
    return String(s || "").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  // ---- 起動 ----
  async function boot() {
    if (!master) { document.getElementById("calendar").textContent = "schedule_master 読み込み失敗"; return; }
    store = SCH.createStore();
    await store.init();

    document.getElementById("nav-prev").addEventListener("click", () => { weekOffset--; recomputeAndRender(); });
    document.getElementById("nav-next").addEventListener("click", () => { weekOffset++; recomputeAndRender(); });
    document.getElementById("nav-today").addEventListener("click", () => { weekOffset = 0; recomputeAndRender(); });
    document.getElementById("btn-verify").addEventListener("click", (e) => {
      verificationMode = !verificationMode;
      e.target.classList.toggle("active", verificationMode);
      recomputeAndRender();
    });
    document.getElementById("btn-verify-csv").addEventListener("click", exportVerificationCSV);
    document.getElementById("btn-export").addEventListener("click", async () => {
      const blob = new Blob([await store.exportJSON()], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "schedule_backup.json";
      a.click();
    });
    document.getElementById("modal-save").addEventListener("click", saveEditor);
    document.getElementById("modal-close").addEventListener("click", closeEditor);

    await recomputeAndRender();
  }

  document.addEventListener("DOMContentLoaded", boot);
})(window.SCH);
