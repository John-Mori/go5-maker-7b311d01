/**
 * theme-settings.js — 「詳細設定」タブ：編集ボタン（Qセーブ/Qロード/リセット/元に戻す）の色を
 * 色コードでカスタマイズし、アプリ全体（どの画面でも）に反映する。
 *
 * 仕組み：色は CSS カスタムプロパティ（:root の --qbtn-*）として適用するため、
 * 同じクラス（.qbtn-save 等）のボタンが置かれている画面すべてに一度で反映される。
 * 値は localStorage（全アカウント共通・グローバル）に保存し、起動時に自動適用。
 * 完全クライアントサイド。
 */
(function () {
  "use strict";

  var COLORS = [
    { key: "save",  varName: "--qbtn-save",  ls: "btn_color_save",  def: "#2563eb", text: "colorSave",  pick: "pickSave",  sw: "swSave"  },
    { key: "load",  varName: "--qbtn-load",  ls: "btn_color_load",  def: "#16a34a", text: "colorLoad",  pick: "pickLoad",  sw: "swLoad"  },
    { key: "reset", varName: "--qbtn-reset", ls: "btn_color_reset", def: "#d97706", text: "colorReset", pick: "pickReset", sw: "swReset" },
    { key: "undo",  varName: "--qbtn-undo",  ls: "btn_color_undo",  def: "#546e7a", text: "colorUndo",  pick: "pickUndo",  sw: "swUndo"  },
    { key: "redo",  varName: "--qbtn-redo",  ls: "btn_color_redo",  def: "#0891b2", text: "colorRedo",  pick: "pickRedo",  sw: "swRedo"  },
  ];

  function $(id) { return document.getElementById(id); }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function remove(k) { try { localStorage.removeItem(k); } catch (e) {} }

  // 色コードの妥当性チェック（16進・rgb()・CSS色名すべて）。ブラウザに解釈させる。
  function isValidColor(c) {
    c = String(c || "").trim();
    if (!c) return false;
    var s = new Option().style;
    s.color = "";
    s.color = c;
    return s.color !== "";
  }
  // 入力テキスト（#hex / 色名）を #rrggbb に正規化（color ピッカー同期用）。失敗なら null。
  function toHex(c) {
    if (!isValidColor(c)) return null;
    var ctx = toHex._ctx || (toHex._ctx = document.createElement("canvas").getContext("2d"));
    ctx.fillStyle = "#000";
    ctx.fillStyle = c;            // 無効なら前の #000 のまま
    var v = ctx.fillStyle;        // ブラウザが #rrggbb か rgba(...) を返す
    if (/^#[0-9a-f]{6}$/i.test(v)) return v;
    var m = v.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
    if (m) {
      var h = function (n) { return ("0" + parseInt(n, 10).toString(16)).slice(-2); };
      return "#" + h(m[1]) + h(m[2]) + h(m[3]);
    }
    return null;
  }

  // 現在の有効値（保存 > 既定）。
  function curVal(c) { var v = load(c.ls); return (v != null && v !== "") ? v : c.def; }

  // :root に CSS 変数を適用（＝アプリ全体のボタン色が変わる）。
  function applyRootVar(c, val) {
    try { document.documentElement.style.setProperty(c.varName, val); } catch (e) {}
  }

  // 起動時：保存済み（or 既定）を :root へ適用。入力UIが無くても動く。
  function applyAllFromStore() {
    COLORS.forEach(function (c) { applyRootVar(c, curVal(c)); });
  }
  applyAllFromStore();

  // 入力UI（詳細設定タブ）の配線。
  function setupUI() {
    if (!$("colorApply")) return; // 詳細設定タブが無いページ（post.html等）では何もしない

    function paintSwatch(c, val) { var el = $(c.sw); if (el) el.style.background = val; }

    // 1色ぶんの「仮表示」（保存はしない・:root と入力欄/見本に反映）。
    function previewOne(c, val) {
      applyRootVar(c, val);
      paintSwatch(c, val);
      var hex = toHex(val);
      if (hex) { var p = $(c.pick); if (p) p.value = hex; }
    }

    // 入力欄/ピッカーに現在値を流し込む。
    function fillInputs() {
      COLORS.forEach(function (c) {
        var v = curVal(c);
        var t = $(c.text); if (t) t.value = v;
        var hex = toHex(v); var p = $(c.pick); if (p && hex) p.value = hex;
        paintSwatch(c, v);
      });
    }

    function status(msg, ok) {
      var el = $("colorStatus");
      if (!el) return;
      el.textContent = msg;
      el.style.color = ok === false ? "#ffb4a2" : ok === true ? "#9fd6a0" : "";
    }

    COLORS.forEach(function (c) {
      var t = $(c.text), p = $(c.pick);
      if (t) t.addEventListener("input", function () {
        var v = t.value.trim();
        if (isValidColor(v)) { previewOne(c, v); status("「反映する」を押すと保存されます。", null); }
      });
      if (p) p.addEventListener("input", function () {
        var v = p.value;
        if (t) t.value = v;
        previewOne(c, v);
        status("「反映する」を押すと保存されます。", null);
      });
    });

    // 反映＝現在の入力値を検証して保存＋適用。
    $("colorApply").addEventListener("click", function () {
      var bad = [];
      COLORS.forEach(function (c) {
        var t = $(c.text);
        var v = t ? t.value.trim() : curVal(c);
        if (!isValidColor(v)) { bad.push(c.key); return; }
        save(c.ls, v);
        applyRootVar(c, v);
        paintSwatch(c, v);
      });
      if (bad.length) status("⚠️ 色コードが正しくありません（" + bad.join(", ") + "）。例：#2563eb / red", false);
      else status("✅ 反映しました。アプリ全体のボタン色に保存されました。", true);
    });

    // 既定の色に戻す＝保存を消して既定値へ（保存も既定で確定）。
    var resetBtn = $("colorResetDefault");
    if (resetBtn) resetBtn.addEventListener("click", function () {
      COLORS.forEach(function (c) { remove(c.ls); applyRootVar(c, c.def); });
      fillInputs();
      status("既定の色に戻しました。", true);
    });

    fillInputs();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setupUI);
  else setupUI();
})();

// ---- アカウント別背景色（account-changed CustomEvent 連動）----
(function () {
  var ACCOUNT_BG = { acc1: '#3B2E5C', acc2: '#3D1830' }; // acc1=月詠み＝上品な紫 / acc2=宵桜＝ワイン
  function applyAccountBg(id) {
    document.documentElement.style.setProperty('--app-bg', ACCOUNT_BG[id] || ACCOUNT_BG.acc1);
  }
  document.addEventListener('account-changed', function (e) {
    applyAccountBg(e.detail && e.detail.id);
  });
  var initId = 'acc1';
  try { initId = localStorage.getItem('current_account') || 'acc1'; } catch (e) {}
  applyAccountBg(initId);
}());
