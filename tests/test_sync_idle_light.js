/**
 * tests/test_sync_idle_light.js — 何も変わっていない同期サイクルが、画像の取り直し・全画像ハッシュ・
 *   IDB全読みを繰り返さないこと。かつ、本当に変わった時(他端末の変更/この端末の保存/削除/読取失敗)は
 *   従来どおり確実に同期されること。
 * 背景: 20秒ごとの同期が無変更時も「全画像レコードをR2から取り直して比較」「全dataURLをSHA-256」
 *   「同期対象prefixのIDB全読み」をしていた＝システム全体が重い主因(Chami 2026-10-20)。
 * 実行: node tests/test_sync_idle_light.js
 */
"use strict";
var fs = require("fs"), path = require("path"), vm = require("vm");
var root_ = path.join(__dirname, "..");
var syncSrc = fs.readFileSync(path.join(root_, "core", "sync.js"), "utf8");
var pass = 0, fail = 0;
function ok(name, cond) { if (cond) { pass++; } else { fail++; console.error("✗ " + name); } }
function clone(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
function img(n) { return "data:image/png;base64," + Buffer.from("img-" + n + "-" + "x".repeat(2000)).toString("base64"); }

// 雲(同期Worker+R2)。端末をまたいで共有する。
function makeCloud() {
  return { blob: null, version: 0, r2: {}, calls: { pull: 0, push: 0, has: 0, put: 0, imgGet: 0 } };
}

// 1端末ぶんの環境。idbWrites を Go5Idb 経由で行う(実アプリと同じ入口)。
function makeDevice(cloud, opts) {
  opts = opts || {};
  var store = { sync2_url: "https://sync.example", sync2_token: "t" };
  var idb = {}, idbCalls = { scan: 0, get: 0, set: 0, del: 0 }, digests = { n: 0 };
  var failScanPrefix = null;
  function res(body, status) {
    return { ok: (status || 200) < 400, status: status || 200, json: function () { return Promise.resolve(clone(body)); }, text: function () { return Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)); } };
  }
  function fetchImpl(url, init) {
    var u = String(url).replace("https://sync.example", ""), m = (init && init.method) || "GET";
    if (u === "/api/pull") { cloud.calls.pull++; return Promise.resolve(res(cloud.blob ? { ok: true, blob: cloud.blob, version: cloud.version } : { ok: true, empty: true, version: cloud.version })); }
    if (u === "/api/push") {
      cloud.calls.push++;
      var b = JSON.parse(init.body);
      if ((b.baseVersion || 0) !== cloud.version) return Promise.resolve(res({ ok: false, conflict: true }));
      cloud.blob = b.blob; cloud.version++;
      return Promise.resolve(res({ ok: true, version: cloud.version }));
    }
    if (u.indexOf("/api/img/has") === 0) {
      cloud.calls.has++;
      var keys = decodeURIComponent(u.split("keys=")[1] || "").split(",");
      return Promise.resolve(res({ ok: true, present: keys.filter(function (h) { return h in cloud.r2; }) }));
    }
    if (u.indexOf("/api/img/") === 0 && m === "PUT") { cloud.calls.put++; cloud.r2[u.slice(9)] = init.body; return Promise.resolve(res({ ok: true })); }
    if (u.indexOf("/img/") === 0) { cloud.calls.imgGet++; var h = u.slice(5); return Promise.resolve(h in cloud.r2 ? res(cloud.r2[h]) : res("", 404)); }
    return Promise.resolve(res({ ok: true }));
  }
  var webcrypto = require("crypto").webcrypto;
  var countingSubtle = Object.create(webcrypto.subtle);
  countingSubtle.digest = function (a, d) { digests.n++; return webcrypto.subtle.digest(a, d); };
  var root = {
    localStorage: {
      getItem: function (k) { return k in store ? store[k] : null; },
      setItem: function (k, v) { store[k] = String(v); },
      removeItem: function (k) { delete store[k]; },
      key: function (i) { return Object.keys(store)[i]; },
      get length() { return Object.keys(store).length; }
    },
    // 短い待ち(再試行の間隔等)だけ即時化。見張り(5分)・通信上限(20秒〜)は発火させない=テストが偶然打ち切られない。
    setTimeout: function (fn, ms) { return (ms || 0) >= 20000 ? 0 : setTimeout(fn, Math.min(ms || 0, 5)); },
    clearTimeout: function (id) { if (id) clearTimeout(id); },
    setInterval: function () { return 0; }, clearInterval: function () {},
    AbortController: AbortController, TextEncoder: TextEncoder, TextDecoder: TextDecoder,
    crypto: { subtle: countingSubtle, getRandomValues: function (a) { return webcrypto.getRandomValues(a); } },
    btoa: function (s) { return Buffer.from(s, "binary").toString("base64"); },
    atob: function (s) { return Buffer.from(s, "base64").toString("binary"); },
    console: { warn: function () {}, log: function () {}, error: function () {} },
    fetch: fetchImpl, CustomEvent: function (t, d) { this.type = t; this.detail = d && d.detail; }
  };
  root.self = root; root.window = root; root.globalThis = root;
  // node に IndexedDB は無いので、Go5Idb と同じAPI契約の最小実装を置く。書き込み印は実体(core/idb-store.js)と
  // 同じく set/del でだけ進む(実体側の規則は tests/test_idb_write_gen.js で固定)。
  var gen = (function () { var n = 0; return { bump: function () { n++; }, read: function () { return String(n); } }; })();
  root.Go5Idb = {
    available: function () { return true; },
    get: function (k) { idbCalls.get++; return Promise.resolve(k in idb ? clone(idb[k]) : null); },
    getResult: function (k) { return Promise.resolve({ ok: true, value: k in idb ? clone(idb[k]) : null }); },
    set: function (k, v) { idbCalls.set++; gen.bump(); idb[k] = clone(v); return Promise.resolve(); },
    del: function (k) { idbCalls.del++; gen.bump(); delete idb[k]; return Promise.resolve(); },
    writeGen: function () { return gen.read(); },
    entriesByPrefixesSettled: function (prefixes) {
      idbCalls.scan++;
      var out = {}, failed = [];
      prefixes.forEach(function (p) {
        if (p === failScanPrefix) { failed.push({ prefix: p, error: new Error("forced") }); return; }
        Object.keys(idb).forEach(function (k) { if (k.indexOf(p) === 0) out[k] = clone(idb[k]); });
      });
      return Promise.resolve({ entries: out, failed: failed });
    }
  };
  var clock = { ms: 0 }; root.__clock = clock;
  var ctx = vm.createContext(root);
  vm.runInContext("Date.now = (function (n) { return function () { return n() + __clock.ms; }; })(Date.now);", ctx);
  vm.runInContext(syncSrc, ctx);
  return {
    S: root.Go5Sync, idb: idb, idbCalls: idbCalls, digests: digests, store: store,
    // 他タブ/他実装が Go5Idb を通さず書いた想定(世代が進まない)。
    rawIdbSet: function (k, v) { idb[k] = clone(v); },
    write: function (k, v) { return root.Go5Idb.set(k, v); },
    remove: function (k) { return root.Go5Idb.del(k); },
    failScan: function (p) { failScanPrefix = p; },
    advance: function (ms) { clock.ms += ms; },
    snapshot: function () { return { scan: idbCalls.scan, get: idbCalls.get, set: idbCalls.set, digest: digests.n }; }
  };
}
function cloudCalls(c) { return Object.assign({}, c.calls); }
function diff(a, b) { var o = {}; Object.keys(b).forEach(function (k) { o[k] = b[k] - (a[k] || 0); }); return o; }

(async function () {
  var N = 30;
  var cloud = makeCloud();
  var A = makeDevice(cloud), B = makeDevice(cloud);
  for (var i = 0; i < N; i++) await A.write("ref:w" + i, { at: 1000 + i, imgs: [img(i)], img: img(i) });
  await A.write("bsky:p0", { img: img("b0") });

  var r1 = await A.S.syncNow();
  ok("初回: A がpushできる " + JSON.stringify(r1), r1 && r1.ok);
  ok("初回: 画像がR2へ上がる", Object.keys(cloud.r2).length === N + 1);
  var r2 = await B.S.syncNow();
  ok("初回: B が受け取れる", r2 && r2.ok);
  ok("初回: B のIDBへ画像が着地", B.idb["ref:w3"] && B.idb["ref:w3"].img === img(3));

  // ── 無変更サイクル: 取り直し0・ハッシュ0 ──
  await A.S.syncNow(); await B.S.syncNow(); // 収束
  var a0 = A.snapshot(), c0 = cloudCalls(cloud);
  var r3 = await A.S.syncNow();
  var a1 = A.snapshot(), c1 = cloudCalls(cloud), da = diff(a0, a1), dc = diff(c0, c1);
  ok("無変更: noChange で終わる", r3 && r3.ok && r3.noChange);
  ok("無変更: R2から画像を取り直さない(実測 " + dc.imgGet + " 本)", dc.imgGet === 0);
  ok("無変更: 画像のSHA-256を計算し直さない(実測 " + da.digest + " 回)", da.digest === 0);
  ok("無変更: IDBの1件読み(get)を全キーぶん回さない(実測 " + da.get + " 回)", da.get === 0);
  ok("無変更: IDBへ書かない", da.set === 0);
  ok("無変更: 画像prefixのIDB全読みをしない(実測 " + da.scan + " 回)", da.scan === 0);
  ok("無変更: has確認もpushもしない", dc.has === 0 && dc.push === 0 && dc.put === 0);
  var b0 = B.snapshot(), cb0 = cloudCalls(cloud);
  var r4 = await B.S.syncNow();
  var db_ = diff(b0, B.snapshot()), dcb = diff(cb0, cloudCalls(cloud));
  ok("無変更(受信側B): noChange", r4 && r4.ok && r4.noChange);
  ok("無変更(受信側B): R2から取り直さない(実測 " + dcb.imgGet + " 本)", dcb.imgGet === 0);
  ok("無変更(受信側B): SHA-256し直さない(実測 " + db_.digest + " 回)", db_.digest === 0);

  // ── 他端末の変更は必ず届く ──
  await A.write("ref:w5", { at: 9000, imgs: [img("w5new")], img: img("w5new") });
  var ra = await A.S.syncNow();
  ok("A の保存が push される", ra && ra.ok && !ra.noChange);
  var cb1 = cloudCalls(cloud);
  var rb = await B.S.syncNow();
  ok("B が受信成功", rb && rb.ok);
  ok("B のIDBへ新画像が着地", B.idb["ref:w5"] && B.idb["ref:w5"].img === img("w5new"));
  ok("B の受信は変わった1件ぶんだけ取りに行く(実測 " + diff(cb1, cloudCalls(cloud)).imgGet + " 本)", diff(cb1, cloudCalls(cloud)).imgGet === 1);

  // ── 新規追加・削除も届く ──
  await B.write("used:u1", { imgs: [img("u1")] });
  await B.S.syncNow(); await A.S.syncNow();
  ok("B の新規画像が A へ届く", A.idb["used:u1"] && A.idb["used:u1"].imgs[0] === img("u1"));
  await A.remove("ref:w7");
  await A.S.syncNow(); await B.S.syncNow();
  ok("A の削除が B へ届く", !("ref:w7" in B.idb));

  // ── 書き込み印の外の書き込み(想定外の経路)も、5分ごとの全読みで必ず拾う ──
  await A.S.syncNow(); // 自分の受信書込で印が進んだ後の全読み→以後は使い回し状態
  A.rawIdbSet("ref:w9", { at: 9500, imgs: [img("w9raw")], img: img("w9raw") });
  var aScan0 = A.snapshot().scan;
  await A.S.syncNow();
  ok("印の外の書き込みは5分以内なら使い回し(全読みしない)", A.snapshot().scan === aScan0);
  A.advance(5 * 60000 + 1000);
  await A.S.syncNow(); await B.S.syncNow();
  ok("5分経過で全読みに戻る", A.snapshot().scan === aScan0 + 1);
  ok("印の外の書き込みも全読みで拾って B へ届く", B.idb["ref:w9"] && B.idb["ref:w9"].img === img("w9raw"));

  // ── R2から取れなかった画像は次の無変更サイクルでも取り直し続ける(自己回復を殺さない) ──
  var C = makeDevice(cloud);
  var savedR2 = cloud.r2[Object.keys(cloud.r2)[0]], firstHash = Object.keys(cloud.r2)[0];
  delete cloud.r2[firstHash];
  await C.S.syncNow();
  var missingKeys = Object.keys(C.idb).length;
  cloud.r2[firstHash] = savedR2;
  var cc0 = cloudCalls(cloud);
  await C.S.syncNow();
  ok("取得失敗した画像は次サイクルで取り直す", diff(cc0, cloudCalls(cloud)).imgGet >= 1);
  ok("取り直しで全件そろう", Object.keys(C.idb).length > missingKeys && Object.keys(C.idb).length === Object.keys(A.idb).length);

  // ── 読取失敗prefixがあるサイクルでも削除を誤爆しない ──
  B.failScan("bsky:");
  var before = cloud.blob;
  await B.S.syncNow();
  var st = JSON.parse(cloud.blob);
  ok("読取失敗prefixのキーを雲から消さない", st.idb["bsky:p0"] && !st.idb["bsky:p0"].d);
  B.failScan(null); void before;

  // ── ローカルで消えた画像(IDBから欠落)は雲から戻す ──
  delete B.idb["ref:w2"]; // 端末側の欠落(容量退避等)
  B.S._test.forceFullIdbRescan_ && B.S._test.forceFullIdbRescan_();
  await B.S.syncNow();
  var st2 = JSON.parse(cloud.blob);
  ok("欠落は削除として扱われ、従来どおり墓標になる(既存挙動の維持)", st2.idb["ref:w2"] && st2.idb["ref:w2"].d === 1);

  console.log((fail ? "FAIL" : "OK") + " test_sync_idle_light: " + pass + " pass, " + fail + " fail");
  process.exit(fail ? 1 : 0);
})().catch(function (e) { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
