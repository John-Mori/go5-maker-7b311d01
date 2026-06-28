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
    var el = $("cfgIoStatus");
    if (!el) return;
    el.textContent = msg;
    el.style.color = ok === false ? "#ffb4a2" : ok === true ? "#9fd6a0" : "";
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
    var n = 0;
    keys.forEach(function (k) {
      try { localStorage.setItem(k, String(data[k])); n++; } catch (e) {}
    });
    setStatus("📥 " + n + "件を読み込みました。ページを再読み込みします…", true);
    setTimeout(function () { try { location.reload(); } catch (e) {} }, 900);
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
  });
})();
