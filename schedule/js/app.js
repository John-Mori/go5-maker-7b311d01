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
  // 枠ピックモード：ドラフト投稿モードの「公開枠を選ぶ」から enter-pick で入る。
  //   ONの間は編集モーダルに「この枠を公開枠に選ぶ」ボタンを出し、押すと slot-picked を親へ返す。
  let pickMode = (function () { try { return /[?&]pick=1(?:&|$)/.test(location.search); } catch (e) { return false; } })();
  // ピック対象チャンネル：ドラフトの投稿先(acc1/acc2)。指定時はそのchの枠だけを表示する(Chami依頼2026-08-05)。
  let pickAcc = (function () { try { var m = /[?&]acc=(acc1|acc2)/.exec(location.search); return m ? m[1] : null; } catch (e) { return null; } })();
  if (pickMode && typeof document !== "undefined" && document.body) { try { document.body.classList.add("pick-mode"); } catch (e) {} }

  // 現在チャンネルを取得（localStorage から。acc1/acc2）。ピックモードでは投稿先ch(pickAcc)を優先。
  function curAcc() {
    if (pickMode && pickAcc) return pickAcc;
    try { return localStorage.getItem('current_account') || 'acc1'; } catch (e) { return 'acc1'; }
  }

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

  // 今日カードを先頭へ寄せる(指示書v0.1 §8)。scrollIntoView は使わない
  // (祖先まで巻き込みページ全体が動いてヘッダ・タブが画面外へ飛ぶため)。範囲外なら何もしない。
  const TOP_GAP = 8;                   // 今日カードの上に残す余白(px)
  function calScroller() {
    const cal = document.getElementById("calendar");
    if (cal && cal.scrollHeight > cal.clientHeight + 4) return cal; // 本体が独自にスクロールする時
    return document.scrollingElement || document.documentElement;    // それ以外はドキュメント側
  }
  // sticky なヘッダの高さ。ドキュメントスクロール時はヘッダが今日カードの上に浮くので、その分だけ下げて着地させる。
  function stickyHeaderH() {
    const h = document.querySelector(".app-header");
    if (!h) return 0;
    if (getComputedStyle(h).position !== "sticky") return 0;
    return h.getBoundingClientRect().height || 0;
  }
  function scrollToToday(smooth) {
    const slab = calScroller();
    const el = document.querySelector(".day.is-today");
    if (!el) return false;                                           // 今日が表示範囲外→先頭に飛ばさない
    const winScroll = (slab === document.scrollingElement || slab === document.documentElement);
    const slabTop = winScroll ? 0 : slab.getBoundingClientRect().top;
    const cur = winScroll ? (window.pageYOffset || 0) : slab.scrollTop;
    const headerH = winScroll ? stickyHeaderH() : 0;                 // 浮くヘッダに今日が潜らないよう補正
    const target = el.getBoundingClientRect().top - slabTop + cur - TOP_GAP - headerH;
    const max = slab.scrollHeight - slab.clientHeight;
    slab.scrollTo({ top: Math.max(0, Math.min(target, max)), behavior: smooth ? "smooth" : "auto" });
    return true;
  }
  // 初回の今日スクロールは「カレンダーが実際に表示された時」に撃つ。
  // (iframe が display:none の間に boot が走ると採寸が 0 で不発になり、表示後は今週の頭=月曜のまま=今日が下にずれる)
  function scheduleFirstScroll() {
    let done = false;
    let io = null;
    function fire() {
      if (done) return;
      const cal = document.getElementById("calendar");
      if (!cal || cal.clientHeight < 40) return;                     // まだ採寸できない(非表示)
      if (!document.querySelector(".day.is-today")) return;          // 今日が範囲外
      done = true;
      scrollToToday(false);
      if (io) io.disconnect();
    }
    requestAnimationFrame(fire);                                     // 既に表示済みなら即
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver(function (es) {
        if (es.some(function (e) { return e.isIntersecting; })) requestAnimationFrame(fire);
      });
      io.observe(document.getElementById("calendar"));
    }
    window.addEventListener("pageshow", function () { requestAnimationFrame(fire); });
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
    const acc = curAcc();                 // ヘッダ・タブ用。カレンダー本体は両ch同時＝アカウント非連動(指示書v0.1 §1)
    const { genStart, genEnd } = genWindow();
    // 両チャンネルを1画面へ統合。左=月詠み(acc1)固定・右=宵桜(acc2)固定。優先度・尺は両者同一、時刻のみ20分ずれ。
    const r1 = gen.generateRange(genStart, genEnd, master, config, overrides, store.getSlotDataForAccount("acc1"));
    const r2 = gen.generateRange(genStart, genEnd, master, config, overrides, store.getSlotDataForAccount("acc2"));
    const result = acc === "acc2" ? r2 : r1;   // 保存は現行タブの結果のみ(既存の永続化挙動を保つ)
    lastRender = { slots: result.slots, dayMetas: r1.dayMetas, review: result.review, slots1: r1.slots, slots2: r2.slots };
    await store.saveSlots(result.slots, acc);  // 自動公開は判定したチャンネルだけを更新
    render(lastRender);
    autoSyncVisible();   // ④ 表示中の未公開枠を、同日・同時刻の投稿履歴と自動同期
  }

  // "HH:MM" に分を加算(generator の shiftTime_ と同一仕様＝24時以降も許容)
  function addMin(hhmm, min) {
    if (!min) return hhmm;
    const p = String(hhmm).split(":");
    const total = Number(p[0]) * 60 + Number(p[1]) + min;
    const nh = Math.floor(total / 60), nm = ((total % 60) + 60) % 60;
    return nh + ":" + String(nm).padStart(2, "0");
  }

  // base時刻ごとの個別オフセット(config.accountOffsetByTime)があればそれを、無ければ既定(accountOffsetMin)を返す。
  function acctOffAt(cfg, acc, baseTime) {
    const byTime = (cfg.accountOffsetByTime || {})[acc];
    if (byTime && typeof byTime[baseTime] === "number") return byTime[baseTime];
    const m = cfg.accountOffsetMin || {};
    return (typeof m[acc] === "number") ? m[acc] : 0;
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
    const acc = curAcc();
    const offMin = (config.accountOffsetMin && typeof config.accountOffsetMin[acc] === 'number') ? config.accountOffsetMin[acc] : 0;
    const accLabel = offMin > 0 ? `${acc} / 時刻オフセット +${offMin}分` : `${acc}`;
    document.getElementById("status-bar").innerHTML =
      `<span>表示: ${ds} 〜 ${dt.addDays(ds, config.displayWeeks * 7 - 1)}（${config.displayWeeks}週）</span>` +
      `<span class="muted">保存先: ${store.adapterName}</span>` +
      `<span class="muted">現在: ${accLabel}</span>` +
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
        grid.appendChild(renderDay(date, metaByDate[date], result));
      }
      weekEl.appendChild(grid);
      root.appendChild(weekEl);
    }
  }

  function renderDay(date, meta, ctx) {
    const cell = document.createElement("div");
    cell.className = "day " + (meta ? dayTypeClass(meta) : "");
    if (meta && meta.date === todayJST()) { cell.classList.add("is-today"); cell.setAttribute("data-today", "1"); }
    if (meta && meta.longVacTag) cell.classList.add("has-longvac");

    const md = date.slice(5).replace("-", "/");
    const head = document.createElement("div");
    head.className = "day-head";
    head.innerHTML =
      `<span class="day-md ${meta && (meta.isHoliday || meta.weekdayIndex === 0) ? "holiday-num" : ""} ${meta && meta.weekdayIndex === 6 ? "sat-num" : ""}">${md}</span>` +
      `<span class="day-wd">(${meta ? meta.weekday : ""})</span>` +
      // 型変更は普段は畳み、この「編集」で下からボトムシートを出す(§Chami 2026-07-29)。型表示の左に配置。
      (meta ? `<button class="day-type-edit" type="button" title="平日/休日型を編集">編集</button>` : "") +
      `<span class="day-type-badge">${meta ? meta.dayType : ""}</span>`;
    cell.appendChild(head);
    if (meta) {
      const eb = head.querySelector(".day-type-edit");
      if (eb) eb.addEventListener("click", () => openTypeSheet(date, meta));
    }

    const tags = document.createElement("div");
    tags.className = "day-tags";
    if (meta && meta.holidayName) tags.innerHTML += `<span class="tag tag-holiday">${meta.holidayName}</span>`;
    if (meta && meta.longVacTag) {
      const label = meta.longVacTag === "obon" ? "お盆" : meta.longVacTag === "newyear" ? "年末年始" : meta.longVacTag;
      tags.innerHTML += `<span class="tag tag-longvac">${label}</span>`;
    }
    if (meta && meta.hasOverride) tags.innerHTML += `<span class="tag tag-override">上書き</span>`;
    cell.appendChild(tags);

    // 型変更ボタン(休みにする 等)は day-head の「編集」→ ボトムシートへ移設。カード内には常設しない(コンパクト化)。

    // 6枠＝1日6行を維持。1行に月詠み(左)・宵桜(右)を同時表示(指示書v0.1 §3)。優先度はch非依存(roleで決まる)
    const slotWrap = document.createElement("div");
    slotWrap.className = "slots";
    const dayslots1 = [];
    for (let idx = 0; idx < config.slotsPerDay; idx++) {
      const s1 = ctx.slots1[gen.slotId(date, idx)];
      if (s1) dayslots1.push(s1);
    }
    assignPriorities(dayslots1);
    dayslots1.forEach((s1) => slotWrap.appendChild(renderPairRow(s1, ctx.slots2[s1.id])));
    cell.appendChild(slotWrap);
    return cell;
  }

  // その日の枠を重要度で並べ、優先度1〜5を割り当てる（表示順は時刻のまま／1＝その日の本命）
  function assignPriorities(arr) {
    const weight = { "本命": 6, "準本命": 5, "通常": 4, "テスト": 3, "昼補助": 2, "深夜補助": 1 };
    const ranked = arr.slice().sort((a, b) => (weight[b.role] || 0) - (weight[a.role] || 0));
    ranked.forEach((s, i) => { s._priority = Math.min(i + 1, 5); });
  }

  // 1スロット＝1ペア行：[優先度バー][月詠み 時刻 状態][宵桜 時刻 状態][優先度ラベル](指示書v0.1 §3)
  function renderPairRow(s1, s2) {
    const el = document.createElement("div");
    const pri = (s1 && s1._priority) || 5;
    el.className = "slot pr-" + pri;
    if (pri === 1) el.classList.add("top");
    if (s1 && s1.needs_review) el.classList.add("needs-review");

    // 素の時刻(テンプレ生時刻=base)→左右へ各chのオフセットを当てる。ch差を1行に並置。
    // base_time があれば直接使う(オフセットが時刻ごとに異なるため逆算では復元不能)。無い旧枠は従来どおりフラットに逆算。
    const off = config.accountOffsetMin || {};
    const curOff = (typeof off[curAcc()] === "number") ? off[curAcc()] : 0;
    const base = (s1 && s1.base_time) ? s1.base_time : addMin(s1.time, -curOff);
    const st1 = (s1 && s1.status) || "未着手";
    const st2 = (s2 && s2.status) || "未着手";
    if (st1 === "公開済" && st2 === "公開済") el.classList.add("cleared"); // 両ch済＝行ごと沈める

    // ピックモード(投稿先chを渡された時)は、そのchの列だけを出す(Chami依頼2026-08-05)。
    const cell1 = chanCell("月詠み", addMin(base, acctOffAt(config, "acc1", base)), st1);
    const cell2 = chanCell("宵桜", addMin(base, acctOffAt(config, "acc2", base)), st2);
    const cells = (pickMode && pickAcc === "acc2") ? cell2
      : (pickMode && pickAcc === "acc1") ? cell1
      : (cell1 + cell2);
    el.innerHTML =
      `<span class="bar"></span>` +
      cells +
      `<span class="prio">${pri === 1 ? '<span class="star"></span>本命' : "優先度" + pri}` +
      ((s1 && s1.needs_review) ? ' <span class="slot-review" title="要確認">!</span>' : "") + `</span>`;
    // 編集は現行タブのスロットに対して(従来どおり＝アクティブなアカウントの exec を編集)
    el.addEventListener("click", () => openEditor(lastRender.slots[s1.id] || s1));
    return el;
  }

  // 片チャンネルのセル：バッジ(38px固定・無彩色)＋時刻＋状態マーク。公開済=done、それ以外=pending
  function chanCell(name, time, status) {
    const done = status === "公開済";
    return `<span class="cell ${done ? "done" : "pending"}">` +
      `<span class="acc">${name}</span>` +
      `<span class="time">${time}</span>` +
      `<span class="st">${done ? '<span class="done-mark">済</span>' : ''}<span class="mk"></span></span>` +
      `</span>`;
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

  // 型変更ボトムシート：day-head の「編集」から下からせり上がる。5アクションを対象日に束ねる(§Chami 2026-07-29)。
  const TYPE_ACTIONS = [
    { act: "off", label: "休みにする" },
    { act: "weekday", label: "平日にする" },
    { act: "follow", label: "自動に戻す" },
    { act: "obon", label: "お盆" },
    { act: "newyear", label: "年末年始" },
  ];
  function openTypeSheet(date, meta) {
    const sheet = document.getElementById("typesheet");
    if (!sheet) return;
    const md = date.slice(5).replace("-", "/");
    document.getElementById("typesheet-title").textContent =
      `${md}（${meta ? meta.weekday : ""}）の型を変更` + (meta ? ` — 現在: ${meta.dayType}` : "");
    const body = document.getElementById("typesheet-body");
    body.innerHTML = "";
    TYPE_ACTIONS.forEach((a) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = a.label;
      b.addEventListener("click", async () => { closeTypeSheet(); await onDayAction(date, meta, a.act); });
      body.appendChild(b);
    });
    sheet.classList.add("open");
  }
  function closeTypeSheet() {
    const sheet = document.getElementById("typesheet");
    if (sheet) sheet.classList.remove("open");
  }

  // 統合アプリ（iframe）内で動いているか
  const inFrame = (function () { try { return window.parent && window.parent !== window; } catch (e) { return false; } })();
  // スロットを親（統合アプリ）へ渡すための最小ペイロード
  function slotPayload(s) {
    return {
      id: s.id, date: s.date, slot_index: s.slot_index, day_type: s.day_type,
      role: s.role, genre: s.genre, time: s.time, scheduled_at: s.scheduled_at,
      title: s.title || "", url: s.url || "", status: s.status
    };
  }
  function sendToParent(type, s) {
    try { window.parent.postMessage({ source: "sch-calendar", type: type, slot: slotPayload(s) }, "*"); } catch (e) {}
  }

  // ---- スロット編集モーダル ----
  function openEditor(s) {
    editingId = s.id;
    const acc = curAcc();
    // s はフラット（現チャンネルの exec が合成済み）なのでそのまま使う
    const m = document.getElementById("modal");
    const accNames = { acc1: "月詠み色恋劇場", acc2: "宵桜艶帖" };
    const accDisplayName = accNames[acc] || acc;
    m.querySelector(".modal-body").innerHTML = `
      <h3>${s.date}（${s.day_type}） ${s.time} / ${s.role}</h3>
      <div class="ch-badge">チャンネル: <strong>${accDisplayName}</strong>（${acc}）の実行記録を編集</div>
      ${inFrame && pickMode ? `<div class="integ-actions">
        <button type="button" id="integ-pick">🗓️ この枠を公開枠に選ぶ</button>
        <div class="integ-hint">ドラフトの公開予約枠にこの日時を結びつけます。</div>
      </div>` : ""}
      ${inFrame && !pickMode ? `<div class="link-hist-box">
        <div class="link-hist-head">投稿履歴と紐づける</div>
        <select id="link-hist"><option value="">${escapeHtml(s.date)} の投稿履歴を読み込み中…</option></select>
        <button type="button" id="link-apply" disabled>この投稿を紐づける</button>
        <div class="link-hist-hint">同じ日・同じチャンネルの投稿履歴から選んで、この枠へ結びつけます。時刻が合致する投稿は自動で同期されます。</div>
      </div>` : ""}
      ${s.needs_review ? `<div class="warn">要確認：day-type変更でテンプレと差異あり。時刻は自動変更していません。</div>` : ""}
      ${s.verify_flag ? `<div class="info">検証対象枠。${s.alt_hypothesis ? "対立仮説: " + escapeHtml(s.alt_hypothesis) : ""}</div>` : ""}
      <label>ステータス（${accDisplayName}）
        <select id="f-status">${config.statusEnum.map((x) => `<option ${x === s.status ? "selected" : ""}>${x}</option>`).join("")}</select>
      </label>
      <label>タイトル（共通プラン）<input id="f-title" value="${escapeAttr(s.title)}"></label>
      <label>動画ID（${accDisplayName}）<input id="f-video" value="${escapeAttr(s.video_id)}"></label>
      <label>URL（${accDisplayName}）<input id="f-url" value="${escapeAttr(s.url)}"></label>
      <label>メモ（共通プラン）<textarea id="f-notes">${escapeHtml(s.notes)}</textarea></label>
      <div class="muted">公開予定: ${s.scheduled_at}</div>
      ${renderVerificationSection(s)}
    `;
    m.classList.add("open");
    if (inFrame) {
      const pk = document.getElementById("integ-pick");
      if (pk) pk.addEventListener("click", () => { sendToParent("slot-picked", s); closeEditor(); });
      // 投稿履歴と紐づける(③)：この枠の日付の投稿履歴を親へ要求。応答は onDayPosts で受ける。
      if (!pickMode) requestDayPosts(s);
    }
  }

  // ---- 投稿履歴の紐づけ(③④・Chami 2026-08-06) ----
  // 親(本体アプリ)は同一オリジンだが、投稿履歴の「投稿時刻の解決」ロジックが重いので、
  //   iframeで生データを読み直さず親の Go5History.postsForDay へ postMessage で問い合わせる。
  let linkReqSeq = 0;
  const autoLinkedIds = {};   // 一度自動同期した枠(ループ・過剰再送の防止)
  // ★実投稿は予定時刻ちょうどに乗らない(手動投稿は数分〜十数分ずれる)。分ぴったり一致だけだと
  //   昼枠のように投稿済みでも◯のまま自動反映されない(Chami 2026-08-06)。予定時刻から±この幅(分)以内で
  //   最も近い未公開枠へ寄せる。枠間隔(昼→夕は数時間・深夜は約60分)より狭く取り、隣枠への誤爆を防ぐ。
  const LINK_WINDOW_MIN = 45;
  // "HH:MM"(0詰め有無を問わず)を分に直して比較する。generatorのtimeは"9:00"、投稿時刻は"09:00"のことがある。
  function hhmmToMin(t) {
    const m = /(\d{1,2}):(\d{2})/.exec(String(t || ""));
    return m ? (Number(m[1]) * 60 + Number(m[2])) : NaN;
  }
  function requestDayPosts(s) {
    linkReqSeq++;
    const reqId = "modal:" + linkReqSeq;
    try { window.parent.postMessage({ source: "sch-calendar", type: "req-day-posts", dates: [s.date], reqId: reqId, slotId: s.id }, "*"); } catch (e) {}
  }
  // 親からの投稿履歴応答。postsByDate[日付]=[{hhmm,title,url,videoId,timeMs}]。
  function onDayPosts(d) {
    const byDate = d.postsByDate || {};
    // 自動同期(④)：表示中の枠のうち、投稿時刻に最も近い未公開枠(±LINK_WINDOW_MIN)へ黙って紐づける。
    //   投稿を古い順に処理し、1枠につき1投稿だけ(usedで二重紐づけを防ぐ)。分ぴったりでなくても寄る。
    if (String(d.reqId || "").indexOf("auto:") === 0) {
      Object.keys(byDate).forEach(function (date) {
        const slots = (lastRender && lastRender.slots) || {};
        const cand = [];
        Object.keys(slots).forEach(function (id) {
          const s = slots[id];
          if (!s || s.date !== date || s.status === "公開済" || autoLinkedIds[id]) return;
          const sm = hhmmToMin(s.time);
          if (!isNaN(sm)) cand.push({ s: s, min: sm });
        });
        if (!cand.length) return;
        const used = {};
        (byDate[date] || []).slice().sort(function (a, b) { return hhmmToMin(a.hhmm) - hhmmToMin(b.hhmm); })
          .forEach(function (p) {
            const pm = hhmmToMin(p.hhmm);
            if (isNaN(pm)) return;
            let best = null, bestD = Infinity;
            cand.forEach(function (c) {
              if (used[c.s.id]) return;
              const dd = Math.abs(c.min - pm);
              if (dd < bestD) { bestD = dd; best = c; }
            });
            if (best && bestD <= LINK_WINDOW_MIN) { used[best.s.id] = true; autoLinkedIds[best.s.id] = true; applyLink(best.s, p); }
          });
      });
      return;
    }
    // モーダル用(③)：開いている枠のドロップダウンを埋める＋時刻一致は自動紐づけ。
    if (!editingId) return;
    const s = (lastRender && lastRender.slots[editingId]) || null;
    if (!s) return;
    const posts = byDate[s.date] || [];
    const sel = document.getElementById("link-hist");
    const btn = document.getElementById("link-apply");
    if (!sel) return;
    if (!posts.length) {
      sel.innerHTML = `<option value="">${escapeHtml(s.date)} の投稿履歴はありません</option>`;
      if (btn) btn.disabled = true;
      return;
    }
    // 分ぴったり優先、無ければ±LINK_WINDOW_MIN内で最も近い投稿を自動候補にする。
    const sMin = hhmmToMin(s.time);
    let auto = posts.filter(function (p) { return hhmmToMin(p.hhmm) === sMin; })[0];
    if (!auto) {
      let bestD = Infinity;
      posts.forEach(function (p) {
        const dd = Math.abs(hhmmToMin(p.hhmm) - sMin);
        if (dd < bestD && dd <= LINK_WINDOW_MIN) { bestD = dd; auto = p; }
      });
    }
    if (auto && s.status !== "公開済") { applyLink(s, auto); return; }   // ④ 時刻一致(近傍含む)は自動同期
    sel.innerHTML = posts.map(function (p, i) {
      return `<option value="${i}">${escapeHtml(p.hhmm + "  " + p.title)}</option>`;
    }).join("");
    if (auto) sel.value = String(posts.indexOf(auto));
    if (btn) {
      btn.disabled = false;
      btn.onclick = function () { const p = posts[parseInt(sel.value, 10) || 0]; if (p) applyLink(s, p); };
    }
  }
  // 枠へ投稿を結びつける＝現チャンネルの実行記録を「公開済」＋題名/URLで更新する。
  //   未保存のプリスティン枠は upsertExec が空振りするので、writeback と同じく upsertSlot で種ごと保存する。
  function applyLink(s, post) {
    const acc = curAcc();
    const patch = {
      status: "公開済",
      title: post.title || s.title || "",
      url: post.url || "",
      post_url: post.url || "",
      video_id: post.videoId || s.video_id || "",
      posted_at: post.timeMs ? new Date(post.timeMs).toISOString() : ""
    };
    const stored = store.getSlotData()[s.id];
    const p = stored
      ? store.upsertExec(s.id, acc, patch)
      : store.upsertSlot(Object.assign({}, s, patch, { needs_review: false }), acc);
    Promise.resolve(p).then(function () { if (editingId === s.id) closeEditor(); return recomputeAndRender(); });
  }
  // 表示中の枠に対する自動同期パス(④)。描画のたびに現チャンネルの未公開枠の日付をまとめて問い合わせる。
  function autoSyncVisible() {
    if (!inFrame || pickMode || !lastRender) return;
    const slots = lastRender.slots || {};
    const dateSet = {};
    Object.keys(slots).forEach(function (id) {
      const s = slots[id];
      if (!s || !s.time || s.status === "公開済" || autoLinkedIds[id]) return;
      if (s.date) dateSet[s.date] = true;
    });
    const dates = Object.keys(dateSet);
    if (!dates.length) return;
    linkReqSeq++;
    try { window.parent.postMessage({ source: "sch-calendar", type: "req-day-posts", dates: dates, reqId: "auto:" + linkReqSeq }, "*"); } catch (e) {}
  }

  // 親（統合アプリ）からの書き戻し：投稿成功後に status/URL等を現在チャンネルの実行層のみ反映
  function handleParentMessage(ev) {
    const d = ev.data;
    if (!d || d.target !== "sch-calendar") return;
    // 親がカレンダータブを表示した合図。iframeは再ロードされないので、開くたびに今日へ寄せる。
    if (d.type === "show") { requestAnimationFrame(function () { scrollToToday(false); }); return; }
    if (d.type === "enter-pick") {
      pickMode = true;
      if (d.acc === "acc1" || d.acc === "acc2") pickAcc = d.acc;   // 投稿先chを受け取り、その列だけに絞る
      try { document.body.classList.add("pick-mode"); } catch (e) {}
      if (editingId) closeEditor();
      recomputeAndRender();                                        // ch絞り込みを反映して再描画
      requestAnimationFrame(function () { scrollToToday(false); });
      return;
    }
    if (d.type === "exit-pick") { pickMode = false; try { document.body.classList.remove("pick-mode"); } catch (e) {} if (editingId) closeEditor(); return; }
    if (d.type === "day-posts") { onDayPosts(d); return; }
    if (d.type === "recompute") { recomputeAndRender(); return; }
    if (d.type === "sync-refresh") {
      store.init()
        .then(recomputeAndRender)
        .catch(function (e) { console.warn("[schedule] 同期後の再読込に失敗", e); });
      return;
    }
    if (d.type !== "slot-writeback") return;
    const acc = (d.account === "acc1" || d.account === "acc2") ? d.account : curAcc();
    // メッセージに明示された実行値だけを書き戻す。他chの表示用コピーを混ぜない。
    const patch = {};
    ["status", "url", "video_id", "post_uri", "post_url", "short_url", "posted_at"].forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(d, key)) patch[key] = d[key];
    });
    const stored = store.getSlotData()[d.id];
    if (stored) {
      store.upsertExec(d.id, acc, patch).then(recomputeAndRender);
    } else {
      const sourceMap = lastRender && (acc === "acc2" ? lastRender.slots2 : lastRender.slots1);
      const source = sourceMap && sourceMap[d.id];
      if (!source) return;
      // 未保存の自動生成枠だけ、対象ch自身の表示値を種にして新規保存する。
      store.upsertSlot(Object.assign({}, source, patch, { needs_review: false }), acc).then(recomputeAndRender);
    }
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
    const acc = curAcc();
    const g = (id) => document.getElementById(id).value;
    // プラン側フィールド（共通）
    s.title = g("f-title");
    s.notes = g("f-notes");
    // ジャンル/概要欄リンク/SNS導線 はUIから削除（テンプレ値を保持・編集不可）
    s.needs_review = false; // ユーザー確認済み
    captureVerification(s);
    if (!s.created_at) s.created_at = new Date().toISOString();
    // 実行側フィールド（チャンネル別）：フラットスロットに反映してから upsertSlot へ
    s.status = g("f-status");
    s.video_id = g("f-video");
    s.url = g("f-url");
    await store.upsertSlot(s, acc);
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
    var todayBtn = document.getElementById("nav-today-center");
    if (todayBtn) todayBtn.addEventListener("click", async () => {
      weekOffset = 0;
      await recomputeAndRender();
      requestAnimationFrame(function () { scrollToToday(true); });  // 手動の「今日へ」は smooth
    });
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
    var tsc = document.getElementById("typesheet-close");
    if (tsc) tsc.addEventListener("click", closeTypeSheet);
    var ts = document.getElementById("typesheet");
    if (ts) ts.addEventListener("click", function (e) { if (e.target === ts) closeTypeSheet(); }); // 背景タップで閉じる
    if (inFrame) window.addEventListener("message", handleParentMessage);

    await recomputeAndRender();
    scheduleFirstScroll();  // 初回遷移のみ・カレンダーが実際に表示された時に撃つ・auto(§8)
  }

  document.addEventListener("DOMContentLoaded", boot);
})(window.SCH);
