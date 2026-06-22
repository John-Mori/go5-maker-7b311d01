// slots 生成・再計算カスケード・自動公開（設計書 §7.5 / §7.6 / §7.7）
window.SCH = window.SCH || {};
(function (SCH) {
  const dt = SCH.dt;

  function slotId(date, slotIndex) {
    return `${date}#${slotIndex}`;
  }

  // アカウント別オフセットのヘルパ
  function curAccount_() { try { return localStorage.getItem('current_account') || 'acc1'; } catch (e) { return 'acc1'; } }
  function accOffsetMin_(config) { var m = (config && config.accountOffsetMin) || {}; var v = m[curAccount_()]; return (typeof v === 'number') ? v : 0; }
  function shiftTime_(time, min) {
    if (!min) return time;
    var p = String(time).split(':'); var total = Number(p[0]) * 60 + Number(p[1]) + min;
    var nh = Math.floor(total / 60), nm = ((total % 60) + 60) % 60;
    return nh + ':' + String(nm).padStart(2, '0');
  }

  // "HH:MM"（24:00=翌日0時を許容）→ +09:00 付き ISO 文字列
  function computeScheduledAt(date, time) {
    let [h, m] = time.split(":").map(Number);
    let d = date;
    if (h >= 24) {
      d = dt.addDays(date, Math.floor(h / 24));
      h = h % 24;
    }
    return `${d}T${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:00+09:00`;
  }

  // 自動公開（§7.6）：予約登録済 かつ scheduled_at<=now → 公開済
  function applyAutoPublish(slot) {
    if (slot.status === "予約登録済" && slot.scheduled_at) {
      if (new Date(slot.scheduled_at).getTime() <= Date.now()) {
        slot.status = "公開済";
      }
    }
    return slot;
  }

  // テンプレ枠から「自動更新してよいフィールド」を作る
  function templateFields(date, tslot, dayType, config) {
    var off = accOffsetMin_(config);
    var t = shiftTime_(tslot.time, off);
    return {
      scheduled_at: computeScheduledAt(date, t),
      time: t,
      day_type: dayType,
      role: tslot.role,
      genre: tslot.genre_hint,
      peak: tslot.peak,
      verify_flag: tslot.verify_flag,
      alt_hypothesis: tslot.alt_hypothesis,
    };
  }

  function emptyUserFields() {
    return {
      title: "", video_id: "", url: "", desc_link: "", sns_funnel: "", notes: "",
      status: "未着手", needs_review: false,
    };
  }

  // 1枠を生成 or マージ（§7.5 データ保全）
  //  - 既存が無い／空き枠（autoUpdatableStatuses）：新テンプレを反映
  //  - 予約登録済/公開済：時刻・role を変えず、テンプレと差異があれば needs_review=true
  function mergeSlot(date, tslot, dayType, existing, config) {
    const id = slotId(date, tslot.slot_index);
    const tpl = templateFields(date, tslot, dayType, config);

    if (!existing) {
      return applyAutoPublish({ id, date, slot_index: tslot.slot_index, ...tpl, ...emptyUserFields(),
        created_at: null, updated_at: null });
    }

    const userFields = {
      title: existing.title || "", video_id: existing.video_id || "", url: existing.url || "",
      desc_link: existing.desc_link || "", sns_funnel: existing.sns_funnel || "",
      notes: existing.notes || "", status: existing.status || "未着手",
      created_at: existing.created_at || null,
    };
    // 検証データ（variant/週/KPI計測）はテンプレ再生成でも保持する（§7.5データ保全）
    if (existing.verification) userFields.verification = existing.verification;

    const isProtected = config.protectConfirmedSlots &&
      !config.autoUpdatableStatuses.includes(userFields.status);

    if (isProtected) {
      // 確定枠：時刻・role を保持。テンプレと差異があれば要確認フラグのみ。
      const changed =
        existing.time !== tpl.time || existing.role !== tpl.role || existing.day_type !== tpl.day_type;
      return applyAutoPublish({
        id, date, slot_index: tslot.slot_index,
        scheduled_at: existing.scheduled_at, time: existing.time, day_type: tpl.day_type,
        role: existing.role, genre: existing.genre, peak: existing.peak,
        verify_flag: existing.verify_flag, alt_hypothesis: existing.alt_hypothesis,
        ...userFields, needs_review: changed || !!existing.needs_review,
      });
    }

    // 空き枠：新テンプレを反映しつつユーザー内容は保持（破棄しない）
    return applyAutoPublish({
      id, date, slot_index: tslot.slot_index, ...tpl, ...userFields, needs_review: false,
    });
  }

  // 指定範囲を生成/再計算（冪等）。classify が D-1/D/D+1 を見るため、
  // 範囲を丸ごと再生成すれば近傍連動カスケードが自動的に満たされる（§7.5）。
  // 返り値：{ slots: {id->slot}, dayMetas: [...], review: [要確認slot...] }
  function generateRange(startDate, endDate, master, config, overrides, existingById) {
    existingById = existingById || {};
    const slots = {};
    const dayMetas = [];
    const review = [];

    let d = startDate;
    let guard = 0;
    while (d <= endDate && guard < 1000) {
      const meta = dt.dayMeta(d, config, overrides);
      dayMetas.push(meta);
      const template = master.templates[meta.dayType];
      if (template) {
        for (const tslot of template.slots) {
          const id = slotId(d, tslot.slot_index);
          const merged = mergeSlot(d, tslot, meta.dayType, existingById[id], config);
          slots[id] = merged;
          if (merged.needs_review) review.push(merged);
        }
      }
      d = dt.addDays(d, 1);
      guard++;
    }
    return { slots, dayMetas, review };
  }

  SCH.gen = { slotId, computeScheduledAt, applyAutoPublish, generateRange };
})(window.SCH);
