(function () {
  "use strict";

  const data = window.VTOMO_DATA;
  const state = { tab: "own", channel: "all", sort: "new", page: 1, pageSize: 30 };
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const nf = new Intl.NumberFormat("ja-JP");

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function number(value) {
    return value === null || value === undefined ? "--" : nf.format(Number(value) || 0);
  }

  function dateJst(value) {
    if (!value) return "日時不明";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false
    }).format(parsed);
  }

  function duration(seconds) {
    if (seconds === null || seconds === undefined) return "尺不明";
    const sec = Math.round(Number(seconds) || 0);
    const min = Math.floor(sec / 60);
    return min ? `${min}:${String(sec % 60).padStart(2, "0")}` : `${sec}秒`;
  }

  function metric(value, label) {
    return `<div class="metric"><strong class="metric-value">${esc(value)}</strong><span class="metric-label">${esc(label)}</span></div>`;
  }

  function thumbnail(video) {
    return `<a class="thumb-link" href="${esc(video.url)}" target="_blank" rel="noopener noreferrer"><img src="${esc(video.thumb)}" alt="" loading="lazy" decoding="async"></a>`;
  }

  function checkpointCell(point, hour) {
    if (!point) {
      return `<div class="checkpoint missing"><span class="checkpoint-hour">${hour}h</span><strong class="checkpoint-views">--</strong></div>`;
    }
    const drift = Number(point.drift_min || 0);
    const driftLabel = point.delayed ? `${drift >= 0 ? "+" : ""}${drift.toFixed(1)}分` : "±3分内";
    const ageLabel = point.age_h === null || point.age_h === undefined ? "実測 --" : `実測 ${Number(point.age_h).toFixed(2)}h`;
    return `<div class="checkpoint${point.delayed ? " delayed" : ""}" title="実測 ${esc(point.age_h)}h">
      <span class="checkpoint-hour">${hour}h</span>
      <strong class="checkpoint-views">${number(point.views)}</strong>
      <span class="checkpoint-age">${esc(ageLabel)}</span>
      <span class="checkpoint-delay">${esc(driftLabel)}</span>
    </div>`;
  }

  function ownCard(video) {
    const points = (data.checkpoint_hours || []).map((hour, index) => checkpointCell((video.checkpoints || [])[index], hour)).join("");
    return `<article class="video-card">
      ${thumbnail(video)}
      <div class="video-body">
        <a class="video-title" href="${esc(video.url)}" target="_blank" rel="noopener noreferrer">${esc(video.title)}</a>
        <div class="meta"><span>${esc(dateJst(video.published_at))} JST</span><span>${esc(duration(video.sec))}</span></div>
        <div class="badge-row"><span class="badge">再生 ${number(video.views)}</span><span class="badge">高評価 ${number(video.likes)}</span></div>
      </div>
      <div class="checkpoints" aria-label="投稿後の再生数">${points}</div>
    </article>`;
  }

  function subscriptionCard(video) {
    return `<article class="video-card">
      ${thumbnail(video)}
      <div class="video-body">
        <a class="video-title" href="${esc(video.url)}" target="_blank" rel="noopener noreferrer">${esc(video.title)}</a>
        <p class="channel-name">${esc(video.channel)}</p>
        <div class="meta"><span>${esc(dateJst(video.published))} JST</span><span>再生 ${number(video.views)}</span><span>${esc(duration(video.sec))}</span></div>
        <div class="badge-row"><span class="badge ${video.is_short ? "short" : "long"}">${video.is_short ? "Shorts" : "通常動画"}</span></div>
      </div>
    </article>`;
  }

  function renderOwn() {
    const own = data.own || { videos: [] };
    const videos = own.videos || [];
    const withCheckpoints = videos.filter((video) => (video.checkpoints || []).some(Boolean)).length;
    $("#ownSummary").innerHTML = [
      metric(number(videos.length), "自社動画"),
      metric(number(withCheckpoints), "初動データあり"),
      metric(number((own.api_calls || {}).estimated_quota_units), "今回API単位")
    ].join("");
    $("#ownListCount").textContent = `${nf.format(videos.length)}本`;
    $("#ownList").innerHTML = videos.length ? videos.map(ownCard).join("") : '<div class="empty-state"><b>自社動画がない。</b><span>取得バッチを実行する。</span></div>';
  }

  function filteredSubscriptions() {
    const all = (data.subscriptions || {}).videos || [];
    const selected = state.channel === "all" ? all : all.filter((video) => video.channel_id === state.channel);
    return selected.slice().sort((a, b) => state.sort === "views"
      ? (Number(b.views) || 0) - (Number(a.views) || 0)
      : String(b.published || "").localeCompare(String(a.published || "")));
  }

  function renderSubscriptions(resetPage) {
    if (resetPage) state.page = 1;
    const subs = data.subscriptions || { channels: [], videos: [] };
    const videos = filteredSubscriptions();
    const pages = Math.max(1, Math.ceil(videos.length / state.pageSize));
    state.page = Math.min(state.page, pages);
    const start = (state.page - 1) * state.pageSize;
    const shown = videos.slice(start, start + state.pageSize);
    $("#subsListCount").textContent = `${nf.format(videos.length)}本`;
    $("#subsList").innerHTML = shown.length ? shown.map(subscriptionCard).join("") : '<div class="empty-state"><b>該当動画がない。</b><span>チャンネル条件を変える。</span></div>';
    $("#subsPager").innerHTML = pages > 1 ? `<button type="button" data-page="prev" ${state.page === 1 ? "disabled" : ""}>前へ</button><span class="page-label">${state.page} / ${pages}</span><button type="button" data-page="next" ${state.page === pages ? "disabled" : ""}>次へ</button>` : "";
  }

  function setupFilters() {
    const subs = data.subscriptions || { channels: [], videos: [] };
    $("#subsAccount").textContent = subs.account || "@yoizakura_t";
    $("#channelFilter").innerHTML = '<option value="all">すべてのチャンネル</option>' + (subs.channels || []).map((channel) => `<option value="${esc(channel.channel_id)}">${esc(channel.title)}</option>`).join("");
    $("#subsSummary").innerHTML = [
      metric(number((subs.channels || []).length), "登録チャンネル"),
      metric(number((subs.videos || []).length), "取得済み動画"),
      metric(number((subs.videos || []).filter((video) => video.is_short).length), "Shorts"),
    ].join("");
  }

  function selectTab(name) {
    state.tab = name;
    $$(".tab").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.tab === name)));
    $$(".panel").forEach((panel) => {
      const active = panel.id === `panel-${name}`;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
    if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  }

  function bind() {
    $$(".tab").forEach((button) => button.addEventListener("click", () => selectTab(button.dataset.tab)));
    $("#channelFilter").addEventListener("change", (event) => { state.channel = event.target.value; renderSubscriptions(true); });
    $$(".sort-button").forEach((button) => button.addEventListener("click", () => {
      state.sort = button.dataset.sort;
      $$(".sort-button").forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      renderSubscriptions(true);
    }));
    $("#subsPager").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-page]");
      if (!button) return;
      state.page += button.dataset.page === "next" ? 1 : -1;
      renderSubscriptions(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // 動画用タグの文字列をタップでコピー(clipboard APIが使えない file:// 等は選択+execCommandで代替)。
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise((resolve, reject) => {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      area.setSelectionRange(0, text.length);
      const ok = document.execCommand("copy");
      area.remove();
      ok ? resolve() : reject(new Error("copy failed"));
    });
  }

  const tagCopy = $("#tagCopy");
  if (tagCopy) {
    let timer = 0;
    tagCopy.addEventListener("click", () => {
      copyText(tagCopy.dataset.copy).then(() => {
        tagCopy.classList.add("copied");
        $("#tagCopyState").textContent = "コピー済";
      }, () => {
        $("#tagCopyState").textContent = "失敗";
      }).finally(() => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          tagCopy.classList.remove("copied");
          $("#tagCopyState").textContent = "コピー";
        }, 1600);
      });
    });
  }

  if (!data) {
    $("#emptyState").hidden = false;
    $$(".panel").forEach((panel) => { panel.hidden = true; });
    return;
  }

  $("#updatedAt").textContent = `更新 ${dateJst(data.generated_at_jst)} JST`;
  setupFilters();
  renderOwn();
  renderSubscriptions(true);
  bind();
  selectTab(location.hash === "#subs" ? "subs" : "own");
  window.__VTOMO_STATE__ = { counts: data.counts, sources: data.sources };

  // 自社分は own_live.json を1分おきに読み直す(file:// では読めないので data.js のまま)。
  async function refreshOwnLive() {
    if (location.protocol === "file:") return;
    try {
      const response = await fetch(`data/own_live.json?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) return;
      const live = await response.json();
      if (!live || !live.own || String(live.generated_at_jst || "") <= String(data.generated_at_jst || "")) return;
      data.own = live.own;
      data.generated_at_jst = live.generated_at_jst;
      $("#updatedAt").textContent = `更新 ${dateJst(live.generated_at_jst)} JST`;
      renderOwn();
      window.__VTOMO_STATE__.live = live.generated_at_jst;
    } catch (error) {
      // 読み直しに失敗しても表示中のデータを残す。
    }
  }
  refreshOwnLive();
  setInterval(() => { if (!document.hidden) refreshOwnLive(); }, 60_000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshOwnLive(); });
}());
