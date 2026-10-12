/**
 * tests/test_sync_last_saved_wins.js — 「どれが親端末とか関係なく、最新に入力して保存されたものが正」。
 * 背景: Chami msg 1559250925288300635。従来の per-key t は「同期が変化を検知した時刻」で、
 *   先に保存しても後から同期した端末が勝ち、初回参加の端末は無条件に雲へ負けていた。
 * 確認: 2台(A/B)が1つの同期サーバを共有し、実際の syncNow を通して
 *   (1) Bが後に保存→Aが後から同期しても、Bの値が残る(同期順ではなく保存順)
 *   (2) 逆にAが後に保存→Aの値が勝つ
 *   (3) 初回参加の端末でも、同期設定後に保存した値が雲の古い値より新しければ勝つ
 *   (4) 初回参加の端末の「同期設定前の初期値」は従来どおり雲に負ける
 *   (5) 同期が書き込んだ値は「保存」に数えない(取り込み後に勝手に勝ち直さない)
 * 実行: node tests/test_sync_last_saved_wins.js
 */
"use strict";
var fs = require("fs"), path = require("path"), vm = require("vm");
var keysSrc = fs.readFileSync(path.join(__dirname, "..", "core", "storage-keys.js"), "utf8");
var src = fs.readFileSync(path.join(__dirname, "..", "core", "sync.js"), "utf8");
var pass = 0, fail = 0;
function ok(name, cond) { if (cond) pass++; else { fail++; console.error("✗ " + name); } }

// 1つの同期サーバ(baseVersion 付き push・衝突で conflict)。
function makeServer() {
  var st = { version: 0, blob: null };
  function resp(body) { return { ok: true, status: 200, json: function () { return Promise.resolve(body); } }; }
  return {
    st: st,
    fetch: function (url, init) {
      if (/\/api\/pull$/.test(url)) return Promise.resolve(resp(st.blob ? { ok: true, version: st.version, blob: st.blob } : { ok: true, empty: true, version: st.version }));
      if (/\/api\/push$/.test(url)) {
        var b = JSON.parse(init.body);
        if ((b.baseVersion || 0) !== st.version) return Promise.resolve(resp({ ok: false, conflict: true }));
        st.version++; st.blob = b.blob;
        return Promise.resolve(resp({ ok: true, version: st.version }));
      }
      return Promise.resolve(resp({ ok: true }));
    }
  };
}
var clock = { now: 1000000 };
function makeDevice(server, configured) {
  var root = {
    setTimeout: function () { return 0; }, clearTimeout: function () {},
    AbortController: AbortController, crypto: require("crypto").webcrypto, TextEncoder: TextEncoder,
    console: { warn: function () {}, log: function () {}, error: function () {} },
    fetch: function (u, i) { return server.fetch(u, i); }, __clock: clock
  };
  root.self = root; root.window = root; root.globalThis = root;
  var ctx = vm.createContext(root);
  // ブラウザと同じく Storage.prototype 経由で書き込む localStorage(sync.js の保存時刻フックが掛かる口)。
  vm.runInContext(
    "Date.now = function () { return __clock.now; };" +
    "function Storage() { Object.defineProperty(this, '_s', { value: {} }); }" +
    "Storage.prototype.getItem = function (k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; };" +
    "Storage.prototype.setItem = function (k, v) { this._s[k] = String(v); };" +
    "Storage.prototype.removeItem = function (k) { delete this._s[k]; };" +
    "Storage.prototype.key = function (i) { return Object.keys(this._s)[i]; };" +
    "Object.defineProperty(Storage.prototype, 'length', { get: function () { return Object.keys(this._s).length; } });" +
    "this.Storage = Storage; this.localStorage = new Storage();", ctx);
  if (configured) { root.localStorage.setItem("sync2_url", "https://sync.example"); root.localStorage.setItem("sync2_token", "t"); }
  vm.runInContext(keysSrc, ctx);
  vm.runInContext(src, ctx);
  return {
    ls: root.localStorage, S: root.Go5Sync,
    configure: function () { root.localStorage.setItem("sync2_url", "https://sync.example"); root.localStorage.setItem("sync2_token", "t"); },
    save: function (k, v) { root.localStorage.setItem(k, v); } // 画面の保存処理(saveA等)と同じ口
  };
}
function at(t) { clock.now = t; }

(async function () {
  var K = "bsky_text__acc1";

  // (1) Bが後に保存 → Aが後から同期しても Bの値が残る
  var srv = makeServer();
  var A = makeDevice(srv, true), B = makeDevice(srv, true);
  at(1000); A.save(K, "初期"); await A.S.syncNow();
  at(1100); await B.S.syncNow();
  ok("(1) 前提: Bにも初期値が届く", B.ls.getItem(K) === "初期");
  at(2000); A.save(K, "Aの古い保存");
  at(3000); B.save(K, "Bの新しい保存");
  at(3500); await B.S.syncNow();   // Bが先に同期
  at(4000); await A.S.syncNow();   // Aが後から同期(旧実装はここでAの古い値が t=4000 で勝っていた)
  ok("(1) 後に保存したBの値がAへ反映", A.ls.getItem(K) === "Bの新しい保存");
  at(4500); await B.S.syncNow();
  ok("(1) Bは自分の新しい値のまま", B.ls.getItem(K) === "Bの新しい保存");

  // (2) 逆順: Aが後に保存 → Aが勝つ(どちらが親かは関係ない)
  at(5000); B.save(K, "Bの古い保存");
  at(6000); A.save(K, "Aの新しい保存");
  at(6500); await A.S.syncNow();
  at(7000); await B.S.syncNow();
  ok("(2) 後に保存したAの値がBへ反映", B.ls.getItem(K) === "Aの新しい保存");
  at(7500); await A.S.syncNow();
  ok("(2) Aは自分の新しい値のまま", A.ls.getItem(K) === "Aの新しい保存");

  // (5) 同期の書き込みは保存に数えない: Bが取り込んだ値で勝ち直さない
  var editB = JSON.parse(B.ls.getItem("sync2_edit_at") || "{}");
  ok("(5) 取り込み(sysSet)は保存時刻を更新しない", editB[K] === 5000);

  // (3) 初回参加の端末: 同期設定後に保存した値が雲より新しければ勝つ
  var C = makeDevice(srv, false);
  at(8000); C.configure();
  at(9000); C.save(K, "Cの最新保存");
  at(9500); await C.S.syncNow();
  ok("(3) 初回参加でも最新の保存が勝つ(親端末の雲を無条件に採らない)", C.ls.getItem(K) === "Cの最新保存");
  at(9800); await A.S.syncNow();
  ok("(3) Cの最新保存が他端末へ届く", A.ls.getItem(K) === "Cの最新保存");

  // (4) 初回参加の端末の「同期設定前の初期値」は雲に負ける(新端末が正しい設定を潰さない)
  var D = makeDevice(srv, false);
  at(10000); D.save(K, "Dの初期値");
  at(10100); D.configure();
  at(10200); await D.S.syncNow();
  ok("(4) 設定前の初期値は雲の値に置き換わる", D.ls.getItem(K) === "Cの最新保存");

  console.log((fail ? "FAIL" : "OK") + " test_sync_last_saved_wins: " + pass + " pass, " + fail + " fail");
  process.exit(fail ? 1 : 0);
})().catch(function (e) { console.error(e); process.exit(1); });
