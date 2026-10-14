/**
 * tests/test_sync_save_kicks.js — 「保存したらすぐ同期」(Chami msg 1559251833242001409)。
 * 背景: v1006 の保存時刻フックは記録だけで同期を起動せず、本文・説明欄・field_* 等の通常の保存は
 *   60秒周期か「タブを隠す」まで雲へ出なかった。
 * 確認(実際の sync.js を vm で2台動かし、タイマーを手で進める):
 *   (1) 同期対象キーの保存で同期が3〜10秒後に1本だけ予約される(打鍵の連続は1本にまとまる)
 *   (2) 予約が発火すると雲へ出て、相手端末の次の取り込みで届く
 *   (3) 同期自身の書き込み・同期対象外キーの書き込みでは予約しない(同期の連鎖を作らない)
 *   (4) 予約が同期中に当たって skipped になっても予約し直す(取りこぼさない)
 * 実行: node tests/test_sync_save_kicks.js
 */
"use strict";
var fs = require("fs"), path = require("path"), vm = require("vm");
var keysSrc = fs.readFileSync(path.join(__dirname, "..", "core", "storage-keys.js"), "utf8");
var src = fs.readFileSync(path.join(__dirname, "..", "core", "sync.js"), "utf8");
var pass = 0, fail = 0;
function ok(name, cond) { if (cond) pass++; else { fail++; console.error("✗ " + name); } }

function makeServer() {
  var st = { version: 0, blob: null, hold: null };
  function resp(body) { return { ok: true, status: 200, json: function () { return Promise.resolve(body); } }; }
  return {
    st: st,
    fetch: function (url, init) {
      if (st.hold) { var h = st.hold; st.hold = null; return h; } // 同期中(_busy)を作るための未解決の通信(最初の1本だけ)
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
function makeDevice(server) {
  var timers = [], seq = 0;
  var root = {
    setTimeout: function (fn, ms) { var id = ++seq; timers.push({ id: id, fn: fn, ms: ms }); return id; },
    clearTimeout: function (id) { for (var i = 0; i < timers.length; i++) if (timers[i].id === id) { timers.splice(i, 1); return; } },
    AbortController: AbortController, crypto: require("crypto").webcrypto, TextEncoder: TextEncoder,
    console: { warn: function () {}, log: function () {}, error: function () {} },
    fetch: function (u, i) { return server.fetch(u, i); }, __clock: clock
  };
  root.self = root; root.window = root; root.globalThis = root;
  var ctx = vm.createContext(root);
  vm.runInContext(
    "Date.now = function () { return __clock.now; };" +
    "function Storage() { Object.defineProperty(this, '_s', { value: {} }); }" +
    "Storage.prototype.getItem = function (k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; };" +
    "Storage.prototype.setItem = function (k, v) { this._s[k] = String(v); };" +
    "Storage.prototype.removeItem = function (k) { delete this._s[k]; };" +
    "Storage.prototype.key = function (i) { return Object.keys(this._s)[i]; };" +
    "Object.defineProperty(Storage.prototype, 'length', { get: function () { return Object.keys(this._s).length; } });" +
    "this.Storage = Storage; this.localStorage = new Storage();", ctx);
  root.localStorage.setItem("sync2_url", "https://sync.example"); root.localStorage.setItem("sync2_token", "t");
  vm.runInContext(keysSrc, ctx);
  vm.runInContext(src, ctx);
  // 保存の予約は3〜10秒。通信timeoutやドラフトの45秒見張りを予約本数に数えない。
  function kicks() { return timers.filter(function (t) { return t.ms >= 3000 && t.ms <= 10000; }); }
  return {
    ls: root.localStorage, S: root.Go5Sync, kicks: kicks,
    save: function (k, v) { root.localStorage.setItem(k, v); },
    fire: async function () {
      var ks = kicks(); ks.forEach(function (t) { root.clearTimeout(t.id); });
      for (var i = 0; i < ks.length; i++) ks[i].fn();
      for (var j = 0; j < 30; j++) await new Promise(function (r) { setImmediate(r); });
    }
  };
}
function at(t) { clock.now = t; }

(async function () {
  var K = "bsky_text__acc1";
  var srv = makeServer();
  var A = makeDevice(srv), B = makeDevice(srv);
  at(1000); await A.S.syncNow(); await B.S.syncNow();
  A.kicks().length = 0;

  // (1) 保存で予約が1本・3〜10秒後。打鍵の連続でも1本。
  at(100000);
  A.save(K, "あ");
  var k1 = A.kicks();
  ok("(1) 保存で同期が予約される", k1.length === 1);
  ok("(1) 予約は3〜10秒後", k1.length === 1 && k1[0].ms >= 3000 && k1[0].ms <= 10000);
  for (var i = 0; i < 50; i++) A.save(K, "あいうえお".slice(0, (i % 5) + 1) + i);
  ok("(1) 打鍵の連続は1本にまとまる", A.kicks().length === 1);
  A.save(K, "最新の本文");

  // (2) 発火で雲へ出る → Bの取り込みで届く
  var v0 = srv.st.version;
  at(105000); await A.fire();
  ok("(2) 予約の発火で雲へ出る", srv.st.version === v0 + 1);
  at(106000); await B.S.syncNow();
  ok("(2) 相手端末へ届く", B.ls.getItem(K) === "最新の本文");

  // (3) 同期の取り込み・同期対象外キーでは予約しない
  ok("(3) 取り込み(sysSet)では予約しない", B.kicks().length === 0);
  A.save("sync2_dummy_meta", "x");
  ok("(3) 同期対象外キーでは予約しない", A.kicks().length === 0);
  at(107000); A.save(K, "最新の本文");
  ok("(3) 同じ値の書き直しでは予約しない", A.kicks().length === 0);

  // (4) 予約が同期中に当たっても予約し直す
  var release;
  srv.st.hold = new Promise(function (r) { release = r; });
  at(200000); var running = A.S.syncNow();   // 同期中のまま止める
  A.save(K, "同期中の保存");
  ok("(4) 同期中の保存でも予約される", A.kicks().length === 1);
  at(210000); await A.fire();
  ok("(4) 同期中で skipped → 予約し直す", A.kicks().length === 1);
  release({ ok: true, status: 200, json: function () { return Promise.resolve({ ok: true, version: srv.st.version, blob: srv.st.blob }); } });
  try { await running; } catch (e) {}
  at(220000); await A.fire();
  // Bは(2)で受け取っただけの値を持つ。従来は受け取ったキーに t が無く、次の同期で t=今 と見なして
  //   Aの新しい保存を古い値で巻き戻していた(受け取り側の巻き戻し)。
  at(221000); await B.S.syncNow();
  ok("(4) 相手へ届く(受け取っただけの古い値で巻き戻さない)", B.ls.getItem(K) === "同期中の保存");
  at(222000); await A.S.syncNow();
  ok("(4) 保存した端末も最新のまま", A.ls.getItem(K) === "同期中の保存");

  console.log((fail ? "FAIL" : "OK") + " test_sync_save_kicks: " + pass + " pass, " + fail + " fail");
  process.exit(fail ? 1 : 0);
})().catch(function (e) { console.error(e); process.exit(1); });
