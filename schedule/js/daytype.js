// day-type 分類器（設計書 §7.3 / §7.4）
// 休み判定の優先順位：個別日上書き ＞ 長期休暇レンジ ＞ 祝日CSV ＞ 週末。
window.SCH = window.SCH || {};
(function (SCH) {
  // ---- 日付ユーティリティ（JST前提。日本にDSTは無いのでUTC基準で安全に加算） ----
  function parseYMD(s) {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  }
  function fmtYMD(dt) {
    const y = dt.getUTCFullYear();
    const m = String(dt.getUTCMonth() + 1).padStart(2, "0");
    const d = String(dt.getUTCDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }
  function addDays(s, n) {
    const dt = parseYMD(s);
    dt.setUTCDate(dt.getUTCDate() + n);
    return fmtYMD(dt);
  }
  function weekdayIndex(s) {
    // 0=日 ... 6=土
    return parseYMD(s).getUTCDay();
  }
  const WEEKDAY_JP = ["日", "月", "火", "水", "木", "金", "土"];

  // ---- 祝日インデックス（holidays.js の window.__HOLIDAYS__ から構築） ----
  function buildHolidayMap() {
    const map = {};
    const src = (window.__HOLIDAYS__ && window.__HOLIDAYS__.holidays) || [];
    for (const h of src) map[h.date] = h.name;
    return map;
  }
  const holidayMap = buildHolidayMap();
  function holidayName(s) {
    return holidayMap[s] || null;
  }
  function isHoliday(s) {
    return !!holidayMap[s];
  }
  function isWeekend(s) {
    const w = weekdayIndex(s);
    return w === 0 || w === 6;
  }

  // ---- 長期休暇レンジ（年末年始・お盆。±伸縮は config 側のstart/end編集で対応） ----
  // start/end は "MM-DD"。年末年始は年をまたぐ（12-29〜01-03）。
  function withinMonthDayRange(s, startMD, endMD) {
    const md = s.slice(5); // "MM-DD"
    if (startMD <= endMD) {
      return md >= startMD && md <= endMD;
    }
    // 年またぎ（例 12-29 〜 01-03）
    return md >= startMD || md <= endMD;
  }
  // その日が属する長期休暇タグ（config レンジから算出）。無ければ null。
  function computedLongVacTag(s, config) {
    const lv = config.longVac;
    for (const key of Object.keys(lv)) {
      const r = lv[key];
      if (withinMonthDayRange(s, r.start, r.end)) return r.tag;
    }
    return null;
  }

  // ---- 個別日上書き（day_overrides。{date: {force_day_off, long_vac_tag_override, note}}） ----
  function getOverride(overrides, s) {
    return (overrides && overrides[s]) || null;
  }

  // 有効な long_vac_tag（上書き優先。'none' は明示的にタグ無し）
  function effectiveLongVacTag(s, config, overrides) {
    const ov = getOverride(overrides, s);
    if (ov && ov.long_vac_tag_override != null) {
      return ov.long_vac_tag_override === "none" ? null : ov.long_vac_tag_override;
    }
    return computedLongVacTag(s, config);
  }

  // ---- 休み判定（§7.3）。優先順位：override > 長期休暇レンジ > 祝日 > 週末 ----
  function isDayOff(s, config, overrides) {
    const ov = getOverride(overrides, s);
    if (ov && ov.force_day_off != null) return ov.force_day_off; // 個別上書き最優先
    if (effectiveLongVacTag(s, config, overrides)) return true;   // 長期休暇レンジ
    if (isHoliday(s)) return true;                                // 祝日CSV
    if (isWeekend(s)) return true;                                // 週末
    return false;
  }

  // ---- day-type 決定（D-1 / D / D+1 依存） ----
  function classify(s, config, overrides) {
    const today = isDayOff(s, config, overrides);
    const tomorrow = isDayOff(addDays(s, 1), config, overrides);
    const yesterday = isDayOff(addDays(s, -1), config, overrides);

    if (!today && !tomorrow) return "平日型";
    if (!today && tomorrow) return "休前日型";       // 金曜寄せ（祝前日含む）
    if (today && !tomorrow) return "最終日型";
    if (today && tomorrow && !yesterday) return "連休初日型";
    return "連休中日型"; // today && tomorrow && yesterday
  }

  // ---- 1日分の day_meta を構築（§7.3 出力） ----
  function dayMeta(s, config, overrides) {
    const w = weekdayIndex(s);
    return {
      date: s,
      weekday: WEEKDAY_JP[w],
      weekdayIndex: w,
      isDayOff: isDayOff(s, config, overrides),
      isHoliday: isHoliday(s),
      holidayName: holidayName(s),
      dayType: classify(s, config, overrides),
      longVacTag: effectiveLongVacTag(s, config, overrides),
      hasOverride: !!getOverride(overrides, s),
    };
  }

  SCH.dt = {
    parseYMD, fmtYMD, addDays, weekdayIndex, WEEKDAY_JP,
    isWeekend, isHoliday, holidayName,
    computedLongVacTag, effectiveLongVacTag,
    isDayOff, classify, dayMeta,
  };
})(window.SCH);
