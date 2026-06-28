// 永続化アダプタ（設計書 §7.8 / §12.3）
//   - 抽象アダプタ interface：load() / save(state)
//   - local（既定）：localStorage。開発用プレースホルダ。※正本にはしない方針。
//   - supabase（スタブ）：クラウドDBを唯一の正本にする本番想定。鍵は直書きしない。
// state の形： { overrides: {date->override}, slotData: {id->slot} }
//
// チャンネル分離（タスク7）：
//   各スロットに exec: { acc1: {...}, acc2: {...} } を追加。
//   実行記録（status / video_id / url / post_uri / post_url / short_url / posted_at）を
//   チャンネル別に保持する。プラン情報（title / time / role 等）は共有のまま。
//   旧形式（exec なし）は init() で自動移行（冪等）。
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

  // ---- チャンネル分離ヘルパ ----
  // 実行層フィールド（チャンネル別に保持する項目）
  const EXEC_FIELDS = ["status", "video_id", "url", "post_uri", "post_url", "short_url", "posted_at"];

  // slot の exec.{acc} を取得（なければ空オブジェクト）
  function getExec(slot, acc) {
    return (slot.exec && slot.exec[acc]) || {};
  }

  // slot の exec.{acc} を更新（他チャンネルは不変）
  function setExec(slot, acc, patch) {
    if (!slot.exec) slot.exec = {};
    slot.exec[acc] = Object.assign({}, slot.exec[acc] || {}, patch);
  }

  // 旧形式スロット（exec なし）を新形式へ変換（冪等）。
  // 旧形式のチャンネル別実行フィールドは acc1 に引き継ぐ（主な利用者が acc1 のため）。
  function migrateSlot(slot) {
    if (slot.exec) return slot; // 移行済み
    const execAcc1 = {};
    for (const f of EXEC_FIELDS) {
      if (slot[f] !== undefined) execAcc1[f] = slot[f];
    }
    // status が無い場合のデフォルト
    if (!execAcc1.status) execAcc1.status = slot.status || "未着手";
    slot.exec = { acc1: execAcc1, acc2: { status: "未着手" } };
    // 旧フラットの実行フィールドは body から除去（exec を唯一の正とする＝他chへ漏れない）。
    for (const f of EXEC_FIELDS) delete slot[f];
    return slot;
  }

  // slot をチャンネル別実行層と合成して「フラットなレンダリング用スロット」を返す。
  // これはコピーなので元の slot.exec は変化しない。
  // body には実行フィールドを残さない設計なので、acc に exec が無ければ実行値は空になる（他chの値が漏れない）。
  function flattenForAccount(slot, acc) {
    const exec = getExec(slot, acc);
    const merged = Object.assign({}, slot, exec);
    delete merged.exec; // レンダリング用フラットには exec 構造を含めない
    // exec が status を持たない場合のデフォルト
    if (!merged.status) merged.status = "未着手";
    return merged;
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
        // 旧形式スロットを新形式へ移行（冪等）
        let migrated = false;
        for (const id of Object.keys(state.slotData)) {
          const before = state.slotData[id];
          if (!before.exec) {
            state.slotData[id] = migrateSlot(Object.assign({}, before));
            migrated = true;
          }
        }
        if (migrated) await adapter.save(state);
        return state;
      },
      getOverrides() { return state.overrides; },
      getSlotData() { return state.slotData; },

      // 現在チャンネルで合成したフラットスロットマップを返す（レンダリング用）
      getSlotDataForAccount(acc) {
        const result = {};
        for (const id of Object.keys(state.slotData)) {
          result[id] = flattenForAccount(state.slotData[id], acc);
        }
        return result;
      },

      // チャンネル別実行フィールドを 1 枠だけ更新する
      async upsertExec(slotId, acc, patch) {
        const slot = state.slotData[slotId];
        if (!slot) return; // 未保存のプリスティン枠は exec 更新不要（generateRange 経由で保存される）
        setExec(slot, acc, patch);
        slot.updated_at = new Date().toISOString();
        await adapter.save(state);
      },

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

      // 編集された slot の保存。slot は「フラット形式（レンダリング用）」で渡される想定。
      // exec が付いていればそのまま保存。付いていなければ既存の exec を引き継ぐ。
      // 空き＆未編集に戻ったものは保持しない（容量節約）。
      async upsertSlot(slot, acc) {
        // フラットスロット → ストア用スロットへ変換
        // acc が指定されている場合はそのチャンネルの exec を更新する
        const existing = state.slotData[slot.id];
        let stored;
        if (slot.exec) {
          // すでに exec 構造を持っている（store 内部の slot が直接渡された場合）
          stored = { ...slot, updated_at: new Date().toISOString() };
          // exec を持つなら移行済み前提だが念のため
          if (!stored.exec) stored.exec = { acc1: { status: "未着手" }, acc2: { status: "未着手" } };
        } else {
          // フラット形式（app.js の saveEditor から来る）
          if (existing) {
            stored = { ...existing, updated_at: new Date().toISOString() };
          } else {
            // 新規（プリスティン枠を初めて保存）
            stored = { ...slot, updated_at: new Date().toISOString() };
            delete stored.exec;
          }
          // exec フィールドを確保
          if (!stored.exec) stored.exec = { acc1: { status: "未着手" }, acc2: { status: "未着手" } };
          // プラン側フィールドを上書き
          const planKeys = Object.keys(slot).filter(k =>
            !EXEC_FIELDS.includes(k) && k !== 'exec' && k !== 'id' && k !== 'updated_at'
          );
          for (const k of planKeys) stored[k] = slot[k];
          // 実行フィールドを指定チャンネルの exec へ反映
          const targetAcc = acc || 'acc1';
          if (!stored.exec[targetAcc]) stored.exec[targetAcc] = {};
          for (const f of EXEC_FIELDS) {
            if (slot[f] !== undefined) stored.exec[targetAcc][f] = slot[f];
          }
          if (!stored.exec[targetAcc].status) stored.exec[targetAcc].status = "未着手";
        }
        // body に実行フィールドを残さない（exec を唯一の正とする＝他chへ漏れない）。
        for (const f of EXEC_FIELDS) delete stored[f];
        // プリスティン判定：両チャンネルとも未着手 & プランフィールドが空
        const execAcc1 = stored.exec && stored.exec.acc1 ? stored.exec.acc1 : {};
        const execAcc2 = stored.exec && stored.exec.acc2 ? stored.exec.acc2 : {};
        const bothPristine =
          (!execAcc1.status || execAcc1.status === "未着手") &&
          !execAcc1.video_id && !execAcc1.url && !execAcc1.post_uri &&
          (!execAcc2.status || execAcc2.status === "未着手") &&
          !execAcc2.video_id && !execAcc2.url && !execAcc2.post_uri;
        const planPristine = !stored.title &&
          !stored.notes && !stored.desc_link && !stored.needs_review && !stored.verification;
        if (bothPristine && planPristine) {
          delete state.slotData[slot.id];
        } else {
          state.slotData[slot.id] = stored;
        }
        await adapter.save(state);
      },

      // 自動公開などで一括変化した slots を保存（generateRange 返り値のフラットスロット群）
      // 自動公開はチャンネル共通のため両 exec の status を更新する
      async saveSlots(slotMap) {
        for (const id of Object.keys(slotMap)) {
          const s = slotMap[id];
          const existing = state.slotData[id];
          // 自動公開チェック：status が "予約登録済" → "公開済" に変わった場合のみ保存
          const statusChanged = existing &&
            existing.exec &&
            s.status === "公開済" &&
            (
              (existing.exec.acc1 && existing.exec.acc1.status === "予約登録済") ||
              (existing.exec.acc2 && existing.exec.acc2.status === "予約登録済")
            );
          if (statusChanged) {
            // 自動公開：予約登録済の exec を公開済へ
            if (existing.exec.acc1 && existing.exec.acc1.status === "予約登録済") {
              existing.exec.acc1.status = "公開済";
            }
            if (existing.exec.acc2 && existing.exec.acc2.status === "予約登録済") {
              existing.exec.acc2.status = "公開済";
            }
            existing.updated_at = new Date().toISOString();
            state.slotData[id] = existing;
          }
          // プリスティンでない新規スロットは保存しない（既存データのみ更新）
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
