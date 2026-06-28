/**
 * persist-fields.js — 入力欄の自動保存・自動復元（汎用）。
 *
 * 目的：ユーザーが入力した内容を全部 localStorage に覚えさせ、
 * どの端末・どのタイミングでアクセスしても「前回と全く同じ」状態で開けるようにする。
 *
 * 方式：id を持つ input/textarea/select を走査し、入力のたびに `field_<id>` キーで保存、
 * 起動時に復元する。復元後は input/change を発火して依存UI（プレビュー等）も更新する。
 *
 * ただし、次のものは対象外（他モジュールが既に管理している／一時的／秘密／ファイル）：
 *   - アカウント別や独自保存を持つ欄（Bluesky本文・作品URL・ハンドル・GAS URL・YouTube説明欄・
 *     アフィID・割引セレクト・ボタン色など）→ 二重管理による競合を避ける
 *   - 送信後に消す一時入力（手動短縮の入力・予約日時）、確認モーダル内の欄
 *   - ファイル選択（保存不可）・パスワード（秘密はここで平文保存しない）・カラーピッカー
 *
 * これらの“対象外”も多くは各モジュール側で既に localStorage 保存されているため、
 * 結果として「入力したものは基本ぜんぶ覚えている」状態になる。完全クライアントサイド。
 */
(function () {
  "use strict";

  // 他モジュール管理・一時的・モーダル系（id 一致で除外）。
  var EXCLUDE = {
    // bluesky.js（アカウント別に保存・テンプレ追従あり）
    bskyEnable: 1, testMode: 1, bskyUnattended: 1, movieWorkUrl: 1, bskyWorkUrl: 1,
    ytTags: 1, ytDesc: 1, bskyText: 1, bskyHandle: 1, bskyAppPw: 1, bskyGasUrl: 1,
    // affiliate.js（afId は fanza_af_id で保存済み）／割引セレクト（アカウント切替でリセット運用）
    afId: 1, discountSel: 1, discountSel2: 1, discountSelPc: 1,
    // theme-settings.js（ボタン色）
    colorSave: 1, colorLoad: 1, colorReset: 1, colorUndo: 1,
    pickSave: 1, pickLoad: 1, pickReset: 1, pickUndo: 1,
    // 一時的（送信後クリア）・モーダル・予約日時・フィルタ
    manualTitle: 1, manualUrl: 1, pcWorkUrl: 1, pcText: 1, postSchedAt: 1, histShowDiscarded: 1
  };

  var PREFIX = "field_";
  function key(id) { return PREFIX + id; }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  // 保存対象か判定（ファイル/パスワード/カラー/ボタン等は除外）。
  function persistable(el) {
    if (!el || !el.id || EXCLUDE[el.id]) return false;
    var tag = el.tagName;
    if (tag === "TEXTAREA" || tag === "SELECT") return true;
    if (tag === "INPUT") {
      var t = (el.type || "text").toLowerCase();
      return !(t === "file" || t === "password" || t === "color" || t === "hidden" ||
        t === "button" || t === "submit" || t === "reset" || t === "image");
    }
    return false;
  }

  function fields() {
    var out = [], nodes = document.querySelectorAll("input[id], textarea[id], select[id]");
    for (var i = 0; i < nodes.length; i++) { if (persistable(nodes[i])) out.push(nodes[i]); }
    return out;
  }

  function valOf(el) { return (el.type === "checkbox" || el.type === "radio") ? (el.checked ? "1" : "0") : el.value; }
  function setVal(el, v) {
    if (el.type === "checkbox" || el.type === "radio") el.checked = (v === "1");
    else el.value = v;
  }

  function restoreAndWire() {
    fields().forEach(function (el) {
      var k = key(el.id);
      var saved = load(k);
      if (saved != null) {
        setVal(el, saved);
        // 依存UI（プレビュー・アフィリンク生成など）を更新するため入力イベントを発火。
        try { el.dispatchEvent(new Event("input", { bubbles: true })); } catch (e) {}
        try { el.dispatchEvent(new Event("change", { bubbles: true })); } catch (e) {}
      }
      var onChange = function () { save(k, valOf(el)); };
      el.addEventListener("input", onChange);
      el.addEventListener("change", onChange);
    });
  }

  // body 末尾で読み込まれる前提（app.js 等の初期化＝既定値投入の後に復元したい）。
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", restoreAndWire);
  else restoreAndWire();
})();
