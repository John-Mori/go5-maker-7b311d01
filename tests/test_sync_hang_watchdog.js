/**
 * tests/test_sync_hang_watchdog.js — 同期の通信が返ってこない時に「同期中」のまま固着しないこと。
 * 背景: 2026-10-12 サブ端末(iPhone16)が「同期中… 画像を確認 0/178」のまま止まった。
 *   同期本体の fetch に上限が無く、1本ハングすると _busy が立ちっぱなし→以後の同期が全部 skipped。
 * 確認: (1) fetch が abort を無視して永久に返らなくても、見張りが5分で _busy を解く/次の同期が走る
 *       (2) abort を受ける fetch なら、pull の上限で同期がエラー決着する(見張りを待たない)
 *       (3) 打ち切られた古い同期が後から返っても、新しい同期の _busy を解かない
 * 実行: node tests/test_sync_hang_watchdog.js
 */
"use strict";
var fs = require("fs"), path = require("path"), vm = require("vm");
var src = fs.readFileSync(path.join(__dirname, "..", "core", "sync.js"), "utf8");
var pass = 0, fail = 0;
function ok(name, cond) { if (cond) pass++; else { fail++; console.error("✗ " + name); } }

function makeEnv(fetchImpl) {
  var store = { sync2_url: "https://sync.example", sync2_token: "t" };
  var timers = [], seq = 0;
  var root = {
    localStorage: {
      getItem: function (k) { return k in store ? store[k] : null; },
      setItem: function (k, v) { store[k] = String(v); },
      removeItem: function (k) { delete store[k]; },
      key: function (i) { return Object.keys(store)[i]; },
      get length() { return Object.keys(store).length; }
    },
    setTimeout: function (fn, ms) { var id = ++seq; timers.push({ id: id, fn: fn, ms: ms || 0 }); return id; },
    clearTimeout: function (id) { timers = timers.filter(function (t) { return t.id !== id; }); },
    AbortController: AbortController, crypto: require("crypto").webcrypto, TextEncoder: TextEncoder,
    console: { warn: function () {}, log: function () {}, error: function () {} },
    fetch: fetchImpl
  };
  root.self = root; root.window = root;
  var ctx = vm.createContext(root);
  vm.runInContext(src, ctx);
  return {
    S: root.Go5Sync,
    // 指定msちょうどの待ち(=上限/見張り)を1つ発火。
    fire: function (minMs) {
      var t = timers.filter(function (x) { return x.ms === minMs; })[0];
      if (!t) return false;
      timers = timers.filter(function (x) { return x !== t; }); t.fn(); return true;
    },
    flushSmall: function () {
      var small = timers.filter(function (x) { return x.ms < 20000; });
      timers = timers.filter(function (x) { return x.ms >= 20000; });
      small.forEach(function (t) { t.fn(); }); return small.length;
    },
    has: function (ms) { return timers.some(function (x) { return x.ms === ms; }); }
  };
}
function tick() { return new Promise(function (r) { setImmediate(r); }); }
async function settle(env) { for (var i = 0; i < 50; i++) { await tick(); env.flushSmall(); } }

(async function () {
  // (1) abort を無視して永久に返らない fetch
  var calls = 0;
  var e1 = makeEnv(function () { calls++; return new Promise(function () {}); });
  var p1 = e1.S.syncNow(); await settle(e1);
  ok("(1) 同期開始で busy", e1.S.status().busy === true);
  ok("(1) 2本目は skipped(従来どおり)", (await e1.S.syncNow()).skipped === true);
  ok("(1) 見張り(300秒)が仕掛けられている", e1.has(300000));
  e1.fire(300000); await settle(e1);
  ok("(1) 見張り発火で busy 解除", e1.S.status().busy === false);
  ok("(1) 打ち切りの理由が画面に出る", /打ち切り/.test(e1.S.status().lastError));
  ok("(1) 進捗表示が消える", !e1.S.status().prog || !e1.S.status().prog.phase);
  var before = calls; var p1b = e1.S.syncNow(); await settle(e1);
  ok("(1) 次の同期は skipped にならず通信する", calls > before && e1.S.status().busy === true);
  void p1; void p1b;

  // (2) abort を受ける fetch(実機Safariの通常ケース): pull の上限で決着
  var e2 = makeEnv(function (url, init) {
    return new Promise(function (_, rej) {
      if (init && init.signal) init.signal.addEventListener("abort", function () { rej(new Error("aborted")); });
    });
  });
  var r2 = null; e2.S.syncNow().then(function (r) { r2 = r; }); await settle(e2);
  ok("(2) pull に上限(90秒)が付いている", e2.has(90000));
  for (var i = 0; i < 3 && e2.fire(90000); i++) await settle(e2); // 3回試行ぶん
  await settle(e2);
  ok("(2) 上限で同期がエラー決着", r2 && r2.ok === false && !!r2.error);
  ok("(2) busy 解除", e2.S.status().busy === false);

  // (3) 打ち切られた古い同期が後から返っても、新しい同期を巻き込まない
  var pend = [];
  var e3 = makeEnv(function () { return new Promise(function (res) { pend.push(res); }); });
  var old = null; e3.S.syncNow().then(function (r) { old = r; }); await settle(e3);
  e3.fire(300000); await settle(e3);
  var oldPend = pend.splice(0);
  e3.S.syncNow(); await settle(e3);
  ok("(3) 新しい同期が busy", e3.S.status().busy === true);
  // 古い同期の通信だけが遅れて(500で)返る
  oldPend.forEach(function (res) { res({ ok: false, status: 500, json: function () { return Promise.resolve(null); } }); }); await settle(e3);
  ok("(3) 新しい同期の busy は解かれない", e3.S.status().busy === true);
  ok("(3) 古い同期は stale で終わる", old && old.stale === true);

  console.log((fail ? "FAIL" : "OK") + " test_sync_hang_watchdog: " + pass + " pass, " + fail + " fail");
  process.exit(fail ? 1 : 0);
})();
