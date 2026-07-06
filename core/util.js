/**
 * core/util.js — 共通ユーティリティ（Go5Util）。M-1（改善書 §7）。
 *
 * これまで各ファイルに重複していた小ヘルパ（$ / esc / fmtTs / yen / num /
 * lsGet / lsSet / jsonp / copyText）を1系統に統一する土台。特に esc は
 * **必ず " をエスケープする安全版**に統一する（旧 bluesky.js:456 / scheduler.js:35 /
 * api-diag.js:10 は " を落としていた＝属性文脈で危険だった）。
 *
 * 使い方：ブラウザでは window.Go5Util、Node（テスト）では module.exports。
 * 既存の各ファイルはこのモジュールに段階的に寄せる（一括置換は M-2 の神ファイル分割で実施）。
 */
(function (root) {
  "use strict";

  var hasDoc = (typeof document !== "undefined");
  var hasLS = (function () { try { return typeof localStorage !== "undefined"; } catch (e) { return false; } })();

  // getElementById ショートハンド。
  function $(id) { return hasDoc ? document.getElementById(id) : null; }

  // HTML エスケープ（&, <, >, " を必ず処理する安全版・1系統）。属性値・テキスト双方に安全。
  var ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return ESC_MAP[c]; });
  }

  // タイムスタンプ整形 "M/D HH:mm"（月日ゼロ埋め・秒なし）。既存 yt-clicks / bluesky の主流仕様。
  function fmtTs(ts) {
    try {
      var d = new Date(ts), p = function (n) { return (n < 10 ? "0" : "") + n; };
      return p(d.getMonth() + 1) + "/" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
    } catch (e) { return ""; }
  }

  // ISO 等 → "YYYY/M/D HH:mm"（settings-io の fmtWhen 相当・クラウド最終保存表示など）。
  function fmtWhen(iso) {
    if (!iso) return "";
    try {
      var d = new Date(iso), p = function (n) { return (n < 10 ? "0" : "") + n; };
      return d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
    } catch (e) { return String(iso); }
  }

  // 金額表示（¥1,234・null/NaN は —）。
  function yen(n) { return (n != null && !isNaN(n)) ? "¥" + Number(n).toLocaleString("ja-JP") : "—"; }
  // 数値のロケール整形（失敗時は素の文字列）。
  function num(n) { try { return Number(n).toLocaleString(); } catch (e) { return String(n); } }

  // 投稿タグ（YouTube題名の末尾に付ける定型ハッシュタグ）。動画に焼く題名テキスト・保存ファイル名・
  // 投稿履歴カードの題名表示では非表示にする（YouTube題名にはそのまま残す＝タグ本来の目的）。
  var POST_TAGS = ['#マンガ紹介', '#漫画', '#アニメ', '#anime', '#animeedit', '#shorts'];
  // 定型タグを題名から除去。★トークン単位で消す＝'#anime' が '#animeedit' の一部を誤って割って
  //   'edit' が残る旧バグ（substring置換）を根絶。ハッシュタグ境界(前=行頭/空白, 後=空白/行末/別の#)で判定。
  function stripPostTags(t) {
    var r = String(t == null ? '' : t);
    POST_TAGS.slice().sort(function (a, b) { return b.length - a.length; }).forEach(function (tag) {
      var e = tag.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      r = r.replace(new RegExp('(^|\\s)' + e + '(?=\\s|$|#)', 'g'), '$1');
    });
    return r.replace(/\s+/g, ' ').trim();
  }

  // localStorage（JSON）読み書き。def は「JSON文字列」を渡す既存 candidates.js 仕様を踏襲。
  function lsGet(k, def) {
    try { return JSON.parse((hasLS ? localStorage.getItem(k) : null) || def); }
    catch (e) { try { return JSON.parse(def); } catch (e2) { return null; } }
  }
  function lsSet(k, v) { try { if (hasLS) localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }

  // JSONP：GAS の POST 応答は CORS で読めないため callback 付き GET で取得（cb キャッシュバスタ付き）。
  // settings-io.js:126 版を正とする（20秒タイムアウト・確実な cleanup）。
  function jsonp(baseUrl, params, cb) {
    if (!hasDoc) { cb(null); return; }
    var seq = (jsonp._seq = (jsonp._seq || 0) + 1);
    var cbName = "__go5jsonp_" + new Date().getTime() + "_" + seq;
    var s = document.createElement("script");
    var done = false;
    function cleanup() {
      try { delete window[cbName]; } catch (e) { window[cbName] = undefined; }
      if (s.parentNode) s.parentNode.removeChild(s);
    }
    var timer = setTimeout(function () { if (done) return; done = true; cleanup(); cb(null); }, 20000);
    window[cbName] = function (data) { if (done) return; done = true; clearTimeout(timer); cleanup(); cb(data); };
    var q = Object.keys(params || {}).map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]); }).join("&");
    s.src = baseUrl + (baseUrl.indexOf("?") >= 0 ? "&" : "?") + q + "&cb=" + new Date().getTime() + "&callback=" + cbName;
    s.onerror = function () { if (done) return; done = true; clearTimeout(timer); cleanup(); cb(null); };
    document.body.appendChild(s);
  }

  // クリップボードへコピー（navigator.clipboard → 失敗時は execCommand フォールバック）。
  // btn を渡すと一時的にラベルを「✓ コピー」に変える。成功可否の Promise を返す。
  function copyText(text, btn) {
    var orig = btn ? btn.textContent : null;
    function flash(ok) {
      if (!btn) return;
      btn.textContent = ok ? "✓ コピー" : "コピー失敗";
      setTimeout(function () { if (btn) btn.textContent = orig; }, 1200);
    }
    function fallback() {
      try {
        var ta = document.createElement("textarea");
        ta.value = String(text == null ? "" : text);
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute"; ta.style.left = "-9999px";
        document.body.appendChild(ta); ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        flash(ok); return Promise.resolve(ok);
      } catch (e) { flash(false); return Promise.resolve(false); }
    }
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(String(text == null ? "" : text))
          .then(function () { flash(true); return true; })
          .catch(function () { return fallback(); });
      }
    } catch (e) {}
    return fallback();
  }

  var API = { $: $, esc: esc, fmtTs: fmtTs, fmtWhen: fmtWhen, yen: yen, num: num, lsGet: lsGet, lsSet: lsSet, jsonp: jsonp, copyText: copyText, POST_TAGS: POST_TAGS, stripPostTags: stripPostTags };

  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.Go5Util = API;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
