// 永続化アダプタ（設計書 §7.8 / §12.3）
//   - 抽象アダプタ interface：load() / save(state)
//   - local（既定）：localStorage。開発用プレースホルダ。※正本にはしない方針。
//   - supabase（スタブ）：クラウドDBを唯一の正本にする本番想定。鍵は直書きしない。
// state の形： { overrides: {date->override}, slotData: {id->slot} }
window.SCH = window.SCH || {};
(function (SCH) {
  const LS_KEY = "sch_state_v1";

  // ---- アダプタ実装 ----
  const localAdapter = {
    name: "local",
    async load() {
      try {
        const raw = localStorage.getItem(LS_KEY);
        return raw ? JSON.parse(raw) : { overrides: {}, slotData: {} };
      } catch (e) {
        console.warn("[store/local] load 失敗", e);
        return { overrides: {}, slotData: {} };
      }
    },
    async save(state) {
      localStorage.setItem(LS_KEY, JSON.stringify(state));
    },
  };

  // Supabase アダプタ（依存パッケージ不要・PostgREST REST + Auth）。
  // クラウドを唯一の正本にし、全端末がHTTPSで読み書き → 同期処理不要（§7.8）。
  // 事前に schedule/schema.sql を実行し、config.persistence.supabase に url/anonKey を設定。
  // anonキーは公開前提のため RLS で保護（認証済みのみ read/write）。
  // ※ 本実装はライブDB未検証。初回セットアップ時に docs/SUPABASE_SETUP.md で確認すること。
  const supabaseAdapter = (function () {
    const SESSION_KEY = "sb_session_v1";
    function cfg() { return SCH.config.persistence.supabase; }

    function loadSession() {
      try { return JSON.parse(localStorage.getItem(SESSION_KEY) || "null"); } catch { return null; }
    }
    function saveSession(s) { localStorage.setItem(SESSION_KEY, JSON.stringify(s)); }
    function clearSession() { localStorage.removeItem(SESSION_KEY); }

    // 認証トークン取得（無効/期限切れなら email+password を促してログイン）
    async function getToken() {
      const c = cfg();
      if (!c.url || !c.anonKey) throw new Error("[store/supabase] config.persistence.supabase.url / anonKey 未設定");
      let s = loadSession();
      if (s && s.access_token && s.expires_at && s.expires_at * 1000 > Date.now() + 60000) {
        return s.access_token;
      }
      const email = window.prompt("Supabase ログイン Email");
      const password = email ? window.prompt("パスワード") : null;
      if (!email || !password) throw new Error("[store/supabase] ログインがキャンセルされました");
      const res = await fetch(`${c.url}/auth/v1/token?grant_type=password`, {
        method: "POST",
        headers: { "Content-Type": "application/json", apikey: c.anonKey },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) { clearSession(); throw new Error(`[store/supabase] 認証失敗 (${res.status})`); }
      const j = await res.json();
      const session = { access_token: j.access_token, expires_at: j.expires_at };
      saveSession(session);
      return session.access_token;
    }

    async function headers(extra) {
      const c = cfg();
      const token = await getToken();
      return Object.assign({
        apikey: c.anonKey,
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      }, extra || {});
    }

    // 直近に把握しているDB上のキー（差分DELETE用）
    let knownSlotIds = new Set();
    let knownOverrideDates = new Set();

    // slot/override → DBカラムへの射影（余分なフィールドは送らない）
    const SLOT_COLS = ["id", "date", "slot_index", "scheduled_at", "day_type", "role", "genre",
      "peak", "verify_flag", "alt_hypothesis", "time", "title", "video_id", "url", "desc_link",
      "sns_funnel", "notes", "status", "needs_review", "created_at", "updated_at"];
    function slotRow(s) {
      const r = {};
      for (const k of SLOT_COLS) if (s[k] !== undefined) r[k] = s[k];
      return r;
    }
    function overrideRow(o) {
      return {
        date: o.date,
        force_day_off: o.force_day_off ?? null,
        long_vac_tag_override: o.long_vac_tag_override ?? null,
        note: o.note ?? null,
        updated_at: o.updated_at || new Date().toISOString(),
      };
    }

    async function getAll(table) {
      const c = cfg();
      const res = await fetch(`${c.url}/rest/v1/${table}?select=*`, { headers: await headers() });
      if (!res.ok) throw new Error(`[store/supabase] ${table} 取得失敗 (${res.status})`);
      return res.json();
    }
    async function upsert(table, rows) {
      if (!rows.length) return;
      const c = cfg();
      const res = await fetch(`${c.url}/rest/v1/${table}`, {
        method: "POST",
        headers: await headers({ Prefer: "resolution=merge-duplicates,return=minimal" }),
        body: JSON.stringify(rows),
      });
      if (!res.ok) throw new Error(`[store/supabase] ${table} upsert失敗 (${res.status})`);
    }
    async function deleteByKeys(table, keyCol, keys) {
      if (!keys.length) return;
      const c = cfg();
      const list = keys.map((k) => `"${k}"`).join(",");
      const res = await fetch(`${c.url}/rest/v1/${table}?${keyCol}=in.(${list})`, {
        method: "DELETE", headers: await headers({ Prefer: "return=minimal" }),
      });
      if (!res.ok) throw new Error(`[store/supabase] ${table} 削除失敗 (${res.status})`);
    }

    return {
      name: "supabase",
      async load() {
        const [overrideRows, slotRows] = await Promise.all([getAll("day_overrides"), getAll("slots")]);
        const overrides = {}, slotData = {};
        for (const o of overrideRows) overrides[o.date] = o;
        for (const s of slotRows) slotData[s.id] = s;
        knownOverrideDates = new Set(Object.keys(overrides));
        knownSlotIds = new Set(Object.keys(slotData));
        return { overrides, slotData };
      },
      async save(state) {
        const overrides = state.overrides || {}, slotData = state.slotData || {};
        // upsert（現状の全行）
        await upsert("day_overrides", Object.values(overrides).map(overrideRow));
        await upsert("slots", Object.values(slotData).map(slotRow));
        // 差分DELETE（前回把握キー − 今回キー）
        const curOv = new Set(Object.keys(overrides)), curSl = new Set(Object.keys(slotData));
        const delOv = [...knownOverrideDates].filter((k) => !curOv.has(k));
        const delSl = [...knownSlotIds].filter((k) => !curSl.has(k));
        await deleteByKeys("day_overrides", "date", delOv);
        await deleteByKeys("slots", "id", delSl);
        knownOverrideDates = curOv; knownSlotIds = curSl;
      },
    };
  })();

  function pickAdapter() {
    const name = (SCH.config.persistence && SCH.config.persistence.adapter) || "local";
    if (name === "supabase") return supabaseAdapter;
    return localAdapter;
  }

  // ---- ストア本体 ----
  function createStore() {
    const adapter = pickAdapter();
    let state = { overrides: {}, slotData: {} };

    return {
      adapterName: adapter.name,
      async init() {
        state = await adapter.load();
        state.overrides = state.overrides || {};
        state.slotData = state.slotData || {};
        return state;
      },
      getOverrides() { return state.overrides; },
      getSlotData() { return state.slotData; },

      // day_overrides の upsert（§7.4）。patch=null でクリア。
      async setOverride(date, patch) {
        if (patch == null) {
          delete state.overrides[date];
        } else {
          const cur = state.overrides[date] || { date };
          state.overrides[date] = { ...cur, ...patch, date, updated_at: new Date().toISOString() };
        }
        await adapter.save(state);
      },

      // 編集された slot の保存。空き＆未編集に戻ったものは保持しない（容量節約）。
      async upsertSlot(slot) {
        const pristine = slot.status === "未着手" && !slot.title && !slot.video_id &&
          !slot.notes && !slot.url && !slot.desc_link && !slot.needs_review && !slot.verification;
        if (pristine) {
          delete state.slotData[slot.id];
        } else {
          state.slotData[slot.id] = { ...slot, updated_at: new Date().toISOString() };
        }
        await adapter.save(state);
      },

      // 自動公開などで一括変化した slots を保存
      async saveSlots(slotMap) {
        for (const id of Object.keys(slotMap)) {
          const s = slotMap[id];
          const pristine = s.status === "未着手" && !s.title && !s.video_id &&
            !s.notes && !s.url && !s.desc_link && !s.needs_review && !s.verification;
          if (!pristine) state.slotData[id] = s;
        }
        await adapter.save(state);
      },

      async exportJSON() {
        return JSON.stringify(state, null, 2);
      },
      async importJSON(json) {
        state = JSON.parse(json);
        state.overrides = state.overrides || {};
        state.slotData = state.slotData || {};
        await adapter.save(state);
      },
    };
  }

  SCH.createStore = createStore;
})(window.SCH);
