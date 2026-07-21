/**
 * core/account.js — アカウント解決の一元化。(Go5Acct)M-1。(改善書 §7)
 *
 * これまで現在アカウント('acc1'/'acc2')の取得が3方式に分裂していた：
 *   (a) window.getCurrentAccount()(app.js が正本を定義)
 *   (b) localStorage.getItem('current_account') 直読み(yt-clicks / theme-settings / schedule)
 *   (c) 各ファイルの acctId()/acct() ラッパ
 * → 本モジュールを唯一の入口にする。**'current_account' 直読みと 'acc1' フォールバックは
 *    ここ1箇所だけ**にするのが規約(他所での直読みは段階的に current() へ寄せる)。
 *
 * 正本の優先順：app.js の window.getCurrentAccount()(クロージャの生きた値)→
 *   無ければ localStorage 'current_account' → 無ければ 'acc1'。
 */
(function (root) {
  "use strict";

  var FALLBACK = "acc1";

  function readLS(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  // 現在アカウント。(唯一の入口)
  function current() {
    try {
      if (root && typeof root.getCurrentAccount === "function") {
        var a = root.getCurrentAccount();
        if (a) return a;
      }
    } catch (e) {}
    return readLS("current_account") || FALLBACK;
  }

  // アカウント別ストレージキー。(base + '__' + acc)acc 省略で現在アカウント。
  // 既存の app.js lsk() / bluesky.js pk() と同一規約。
  function key(base, acc) { return base + "__" + (acc || current()); }

  // Bluesky ハンドル。(@ 抜き)acc 省略で現在アカウント。
  function handleOf(acc) { return (readLS("bsky_handle__" + (acc || current())) || "").trim().replace(/^@/, ""); }

  // ── X(Twitter)アカウント(2026-07-21 Chami開設・確定値) ──────────────
  //   ★台帳の正本は local/consult_intel/🐧さん情報.md。ここはコードから参照するための写し。
  //     食い違いに気づいたら台帳を正とすること(第2の台帳を作らない=ORG-11)。
  //   ★acc1/acc2 の対応は Bluesky・YouTube と同じ並び(月詠み=acc1 / 宵桜=acc2)。
  //     Xへの自動投稿はしない(コピペ手動運用)。この値は「どちらへ出す文面か」の表示に使う。
  var X_ACCOUNTS = {
    acc1: { handle: "nox_raptus",      name: "夜半の耽読🌙コミック厳選", ch: "月詠み色恋劇場" },
    acc2: { handle: "nightowlbkshelf", name: "眠れぬ夜の書架めぐり",     ch: "宵桜艶帖" }
  };
  // Xハンドル。(@ 抜き)未定義アカウントは空文字＝呼び出し側で「未設定」を出せる。
  function xHandleOf(acc) { var a = X_ACCOUNTS[acc || current()]; return a ? a.handle : ""; }
  // X表示名。(プロフィール名)
  function xNameOf(acc) { var a = X_ACCOUNTS[acc || current()]; return a ? a.name : ""; }
  // Bluesky DID。(投稿アカウントの確定情報・記録の背骨)
  function didOf(acc) { return (readLS("bsky_did__" + (acc || current())) || "").trim(); }
  // DID を保存。(did: 形式のみ・アカウント必須)
  function setDid(acc, did) {
    if (acc && /^did:/.test(did || "")) { try { localStorage.setItem("bsky_did__" + acc, did); } catch (e) {} }
  }

  // アカウント切替の購読。(app.js が document に 'account-changed' を dispatch)
  function onChange(cb) {
    if (typeof document === "undefined" || typeof cb !== "function") return;
    document.addEventListener("account-changed", function (e) {
      try { cb((e && e.detail && e.detail.id) || current()); } catch (err) {}
    });
  }

  var API = { current: current, key: key, handleOf: handleOf, didOf: didOf, setDid: setDid, onChange: onChange, FALLBACK: FALLBACK,
              X_ACCOUNTS: X_ACCOUNTS, xHandleOf: xHandleOf, xNameOf: xNameOf };

  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.Go5Acct = API;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
