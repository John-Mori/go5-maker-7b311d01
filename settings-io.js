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

  // 秘密とみなすキー（アプリパスワード・各種シークレット/トークン）。「鍵を除いて」書き出しで除外。
  function isSecretKey(k) {
    return /(app_pw|_pw__|password|secret|token|refresh|api_key)/i.test(String(k));
  }

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
  function applyData(data, skipSecrets, label) {
    var keys = Object.keys(data);
    var n = 0;
    keys.forEach(function (k) {
      if (skipSecrets && isSecretKey(k)) return;   // クラウド取得では秘密は絶対に上書きしない
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
  // 端末固有・同期しないキー（他端末に混ぜたくないもの）。
  function isDeviceLocalKey(k) { return k === "sync_device_name"; }

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

  // この端末の非秘密設定をクラウドへ保存（POST）。
  function syncPush() {
    var url = gasUrl();
    if (!url) { setStatus("⚠️ 記録用GAS（⚙記録用URL）が未設定です。先に設定してください。", false); return; }
    var dev = deviceName();
    try { if (dev) localStorage.setItem("sync_device_name", dev); } catch (e) {}
    var data = dumpStorage(false); // 秘密キー除外
    Object.keys(data).forEach(function (k) { if (isDeviceLocalKey(k)) delete data[k]; }); // 端末固有キーは送らない
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
      applyData(data, true, "クラウド取得"); // skipSecrets=true：鍵は絶対に上書きしない
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
