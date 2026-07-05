/**
 * settings-io.js — 設定の引っ越し（エクスポート / インポート）。
 *
 * 端末を変えても設定（レイアウト微調整・本文・YouTube説明欄・短縮URL履歴・各種テンプレ）を
 * まとめて書き出し／読み込みできるようにする。完全クライアントサイド（localStorage を JSON 化）。
 *
 * 書き出しは2種類：
 *   ①「鍵を除いて」＝アプリパスワード等の秘密キーを除外（共有・バックアップ向け・安全）
 *   ②「全部（鍵込み）」＝秘密も含む（自分の別端末へ完全移行する時だけ・取り扱い注意）
 * 読み込みは確認のうえ localStorage へ上書きし、リロードして反映。
 *
 * ※将来クラウド同期（Supabase 等）にする場合もこのファイルの export/import を土台にできる（今は未実装）。
 */
(function () {
  "use strict";

  // キー分類は core/storage-keys.js（Go5Keys）に一元化。未読込時のフォールバックも用意（防御的）。
  var K = (typeof window !== "undefined" && window.Go5Keys) ? window.Go5Keys : null;

  // 秘密とみなすキー（アプリパスワード・各種シークレット/トークン）。「鍵を除いて」書き出しで除外。
  function isSecretKey(k) {
    if (K) return K.isSecret(k);
    return /(app_pw|_pw__|password|secret|token|refresh|api_key)/i.test(String(k));
  }
  // クラウド同期してよいキー（＝本物の設定）。許可リスト方式（Go5Keys.syncAllowed）。
  //   ここに載らない新キーは既定で同期されない＝INC-62 型の再汚染を新キーにも作らせない（改善書 §2-4）。
  function isSyncKey(k) {
    if (K) return K.syncAllowed(k);
    // フォールバック：旧ブロックリスト相当（Go5Keys 未読込という異常時のみ）。
    k = String(k);
    if (isSecretKey(k)) return false;
    if (/^(short_hist__|verify_manual__|verify_yt__|bsky_did__|cand_)/.test(k)) return false;
    if (/^(delta_cache|peak_cache|clicks_cache|yt_meta_cache|fanza_title_cache)$/.test(k)) return false;
    if (/^acct_did_repair/.test(k) || k === "sync_device_name") return false;
    return true;
  }
  // 旧ブロックリスト時代に「同期されていたか」（反転の差分ログ＝目視用）。
  function wasLegacySynced(k) {
    if (K) return K.legacySynced(k);
    k = String(k);
    return !isSecretKey(k)
      && !/^(short_hist__|verify_manual__|verify_yt__|bsky_did__|cand_)/.test(k)
      && !/^(delta_cache|peak_cache|clicks_cache|yt_meta_cache|fanza_title_cache)$/.test(k)
      && !/^acct_did_repair/.test(k) && k !== "sync_device_name";
  }
  // 同期でこの端末へ「取り込んでよい」キー（＝設定のみ・秘密は不可）。pull の多層防御。
  function isSyncApplicable(k) { return isSyncKey(k) && !isSecretKey(k); }

  function $(id) { return document.getElementById(id); }
  function setStatus(msg, ok) {
    var color = ok === false ? "#ffb4a2" : ok === true ? "#9fd6a0" : "";
    ["cfgIoStatus", "cfgSyncStatus"].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      el.textContent = msg;
      el.style.color = color;
    });
  }

  // localStorage 全体をプレーンオブジェクト化（includeSecrets=false なら秘密キーを除外）。
  function dumpStorage(includeSecrets) {
    var out = {};
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (!k) continue;
        if (!includeSecrets && isSecretKey(k)) continue;
        out[k] = localStorage.getItem(k);
      }
    } catch (e) {}
    return out;
  }

  function stamp() {
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "-" + p(d.getHours()) + p(d.getMinutes());
  }

  function download(filename, text) {
    var blob = new Blob([text], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000);
  }

  function exportSettings(includeSecrets) {
    var data = dumpStorage(includeSecrets);
    var payload = {
      app: "go5-maker",
      kind: "settings-export",
      version: 1,
      includesSecrets: !!includeSecrets,
      exportedAt: new Date().toISOString(),
      data: data,
    };
    var fname = "go5-settings-" + (includeSecrets ? "full" : "safe") + "-" + stamp() + ".json";
    download(fname, JSON.stringify(payload, null, 2));
    var n = Object.keys(data).length;
    setStatus("📤 " + n + "件を書き出しました（" + (includeSecrets ? "鍵込み・取り扱い注意" : "鍵を除く") + "）。", true);
  }

  // data オブジェクトを localStorage へ反映して再読込。skipSecrets=true で秘密キーを無視（クラウド取得用の多層防御）。
  function applyData(data, skipSecrets, label, skipHistory) {
    var keys = Object.keys(data);
    var n = 0;
    keys.forEach(function (k) {
      if (skipSecrets && isSecretKey(k)) return;   // クラウド取得では秘密は絶対に上書きしない
      if (skipHistory && !isSyncKey(k)) return;    // クラウド取得は「設定（許可リスト）」だけ反映＝記録/履歴/下書き等は上書きしない（修復の巻き戻し防止・INC-62）
      try { localStorage.setItem(k, String(data[k])); n++; } catch (e) {}
    });
    setStatus("📥 " + n + "件を反映しました" + (label ? "（" + label + "）" : "") + "。ページを再読み込みします…", true);
    setTimeout(function () { try { location.reload(); } catch (e) {} }, 900);
  }

  function importSettings(text) {
    var obj;
    try { obj = JSON.parse(text); } catch (e) { setStatus("⚠️ ファイルを読み取れませんでした（JSONではありません）。", false); return; }
    var data = obj && obj.data && typeof obj.data === "object" ? obj.data : null;
    if (!data) { setStatus("⚠️ この設定ファイルには復元できる内容がありません。", false); return; }
    var keys = Object.keys(data);
    if (!keys.length) { setStatus("⚠️ 設定が空でした。", false); return; }
    var hasSecret = keys.some(isSecretKey);
    var msg = keys.length + "件の設定を読み込み、今の設定に上書きします。\n" +
      (hasSecret ? "（アプリパスワード等の秘密も含まれます）\n" : "") +
      "よろしいですか？（読み込み後にページを再読み込みします）";
    if (!window.confirm(msg)) { setStatus("読み込みを中止しました。", null); return; }
    applyData(data, false); // ファイル読み込みはファイル内容を尊重（鍵込みなら鍵も反映）
  }

  // ── 端末間クラウド同期（記録用GAS経由・鍵は同期しない）──────────────────────
  function gasUrl() { try { return (localStorage.getItem("bsky_gas_url") || "").trim(); } catch (e) { return ""; } }
  function deviceName() {
    var el = $("cfgSyncDevice");
    var v = el ? (el.value || "").trim() : "";
    if (!v) { try { v = (localStorage.getItem("sync_device_name") || "").trim(); } catch (e) {} }
    return v;
  }
  // （旧 isDeviceLocalKey は許可リスト方式へ反転し不要になった＝sync_device_name は isSyncKey が false を返す）

  // JSONP：GASのPOST応答はCORSで読めないため、callback付きGETで取得（キャッシュバスター cb 付き）。
  function jsonp(baseUrl, params, cb) {
    var cbName = "__go5sync_" + Date.now() + "_" + Math.floor(Math.random() * 1e6);
    var s = document.createElement("script");
    var done = false;
    function cleanup() {
      try { delete window[cbName]; } catch (e) { window[cbName] = undefined; }
      if (s.parentNode) s.parentNode.removeChild(s);
    }
    var timer = setTimeout(function () { if (done) return; done = true; cleanup(); cb(null); }, 20000);
    window[cbName] = function (data) { if (done) return; done = true; clearTimeout(timer); cleanup(); cb(data); };
    var q = Object.keys(params).map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]); }).join("&");
    s.src = baseUrl + (baseUrl.indexOf("?") >= 0 ? "&" : "?") + q + "&cb=" + Date.now() + "&callback=" + cbName;
    s.onerror = function () { if (done) return; done = true; clearTimeout(timer); cleanup(); cb(null); };
    document.body.appendChild(s);
  }

  function fmtWhen(iso) {
    if (!iso) return "";
    try {
      var d = new Date(iso), p = function (n) { return (n < 10 ? "0" : "") + n; };
      return d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
    } catch (e) { return iso; }
  }
  function setCloud(msg) { var el = $("cfgSyncCloud"); if (el) el.innerHTML = msg; }

  // クラウドの最終保存状態を表示（詳細設定を開いたとき等）。
  function refreshCloudStatus() {
    var url = gasUrl();
    if (!url) { setCloud("記録用GAS（⚙記録用URL）が未設定です。設定すると端末間同期が使えます。"); return; }
    setCloud("クラウドの状態を確認中…");
    jsonp(url, { action: "settings_meta" }, function (res) {
      if (!res || !res.ok) { setCloud("⚠️ クラウドに接続できませんでした（GAS未デプロイ/URL誤りの可能性）。"); return; }
      if (res.empty) { setCloud("クラウドにはまだ保存がありません。「クラウドに保存」で最初のスナップショットを作れます。"); return; }
      setCloud("☁️ 最終保存：<b>" + fmtWhen(res.updatedAt) + "</b>" + (res.device ? "（" + esc(res.device) + "）" : "") + " ／ " + (res.len || 0) + "文字");
    });
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]; }); }

  // 同期の「ブロックリスト→許可リスト」反転の差分をコンソールに1度だけ出す（改善書 M-1 受け入れ条件「同期差分ログ目視」）。
  //   excluded = 旧方式では同期されていたが、新方式（許可リスト）では同期されなくなるキー。
  //   ＝改善書 §2-4 が問題視した漏洩キー（movie_drafts__/sch_state_v1/view_snaps/yt_scheduled__/current_account/
  //     field_*/verify_*/移行フラグ/各種cache 等）が並ぶのが正常。想定外のキー（本物の設定）が混じっていないか目視する。
  var _diffLogged = false;
  function logSyncReversalDiff(data) {
    if (_diffLogged) return; _diffLogged = true;
    try {
      var excluded = [], added = [];
      Object.keys(data).forEach(function (k) {
        var was = wasLegacySynced(k), now = isSyncKey(k);
        if (was && !now) excluded.push(k);
        if (!was && now) added.push(k);   // 通常は空（許可リストは旧同期集合の部分集合の想定）
      });
      excluded.sort(); added.sort();
      console.log("[go5 sync反転] 許可リスト方式に反転。今回この端末で『同期されなくなる』キー（想定＝記録/下書き/キャッシュ/移行フラグ・改善書§2-4）: " + excluded.length + "件", excluded);
      if (added.length) console.warn("[go5 sync反転] 旧方式では同期されず新方式で同期されるキー（要確認）: ", added);
    } catch (e) {}
  }

  // この端末の非秘密設定をクラウドへ保存（POST）。
  function syncPush() {
    var url = gasUrl();
    if (!url) { setStatus("⚠️ 記録用GAS（⚙記録用URL）が未設定です。先に設定してください。", false); return; }
    var dev = deviceName();
    try { if (dev) localStorage.setItem("sync_device_name", dev); } catch (e) {}
    var data = dumpStorage(false); // 秘密キー除外
    // 許可リスト方式：本物の「設定」(isSyncKey)だけ送る。未登録の新キーは送らない＝INC-62 型の再汚染を新キーに作らせない。
    logSyncReversalDiff(data);     // 反転の差分（旧は同期→新は非同期になったキー）をコンソールに1度出す＝改善書 M-1「同期差分ログ目視」
    Object.keys(data).forEach(function (k) { if (!isSyncKey(k)) delete data[k]; });
    var blob = JSON.stringify(data);
    var n = Object.keys(data).length;
    setStatus("☁️⬆️ クラウドへ保存中…（" + n + "件 / " + blob.length + "文字）", null);
    fetch(url, { method: "POST", body: JSON.stringify({ op: "settings_push", blob: blob, updatedAt: new Date().toISOString(), device: dev }) })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res && res.ok) { setStatus("✅ クラウドに保存しました（" + n + "件）。別の端末で「クラウドから取得」を押すと反映されます。", true); refreshCloudStatus(); }
        else { setStatus("⚠️ 保存に失敗しました（" + ((res && res.error) || "不明") + "）。", false); }
      })
      .catch(function () { setStatus("⚠️ 保存に失敗しました（通信エラー／GAS未デプロイの可能性）。", false); });
  }

  // クラウドの非秘密設定をこの端末へ取り込む（JSONP GET→確認→上書き→再読込）。鍵は取り込まない。
  function syncPull() {
    var url = gasUrl();
    if (!url) { setStatus("⚠️ 記録用GAS（⚙記録用URL）が未設定です。先に設定してください。", false); return; }
    setStatus("☁️⬇️ クラウドから取得中…", null);
    jsonp(url, { action: "settings_pull" }, function (res) {
      if (!res || !res.ok) { setStatus("⚠️ 取得に失敗しました（GAS未デプロイ/URL誤りの可能性）。", false); return; }
      if (res.empty || !res.blob) { setStatus("クラウドにはまだ保存がありません。", false); return; }
      var data;
      try { data = JSON.parse(res.blob); } catch (e) { setStatus("⚠️ クラウドのデータを読み取れませんでした。", false); return; }
      if (!data || typeof data !== "object") { setStatus("⚠️ クラウドのデータが不正です。", false); return; }
      var n = Object.keys(data).length;
      var msg = "クラウドの設定（" + fmtWhen(res.updatedAt) + (res.device ? " / " + res.device : "") + "・" + n + "件）を、\n" +
        "この端末の設定に上書きします。\n" +
        "※アプリパスワード等の鍵はこの端末のまま維持されます（クラウドには保存されていません）。\n" +
        "よろしいですか？（取り込み後に再読み込みします）";
      if (!window.confirm(msg)) { setStatus("取得を中止しました。", null); return; }
      applyData(data, true, "クラウド取得", true); // skipSecrets=true / skipHistory=true：鍵と記録データは上書きしない
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var safeBtn = $("cfgExportSafe"), allBtn = $("cfgExportAll"), impBtn = $("cfgImportBtn"), impFile = $("cfgImportFile");
    if (safeBtn) safeBtn.addEventListener("click", function () { exportSettings(false); });
    if (allBtn) allBtn.addEventListener("click", function () {
      if (!window.confirm("アプリパスワード等の秘密も含めて書き出します。\nこのファイルの取り扱いに注意してください（自分の別端末への移行用）。\n続けますか？")) return;
      exportSettings(true);
    });
    if (impBtn && impFile) {
      impBtn.addEventListener("click", function () { impFile.click(); });
      impFile.addEventListener("change", function () {
        var f = impFile.files && impFile.files[0];
        if (!f) return;
        var reader = new FileReader();
        reader.onload = function () { importSettings(String(reader.result || "")); impFile.value = ""; };
        reader.onerror = function () { setStatus("⚠️ ファイルの読み込みに失敗しました。", false); };
        reader.readAsText(f);
      });
    }

    // ── 端末間クラウド同期の配線 ──
    var devEl = $("cfgSyncDevice");
    if (devEl) {
      try { devEl.value = localStorage.getItem("sync_device_name") || ""; } catch (e) {}
      devEl.addEventListener("input", function () { try { localStorage.setItem("sync_device_name", (devEl.value || "").trim()); } catch (e) {} });
    }
    var pushBtn = $("cfgSyncPush"), pullBtn = $("cfgSyncPull");
    if (pushBtn) pushBtn.addEventListener("click", syncPush);
    if (pullBtn) pullBtn.addEventListener("click", syncPull);
    // 詳細設定タブを開いたときにクラウドの最終保存状態を表示（存在すれば）。
    var settingsTab = $("tabSettings");
    if (settingsTab) settingsTab.addEventListener("click", function () { setTimeout(refreshCloudStatus, 300); });
    if ($("cfgSyncCloud")) refreshCloudStatus();
  });
})();
