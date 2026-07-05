/**
 * core/idb-store.js — IndexedDB の小さなKVストア（Go5Idb）。
 *
 * 目的：候補の保存画像（dataURL・大きい）を localStorage（iOS Safariは1サイト約5MB固定）から
 *   IndexedDB（容量は端末の空きに応じて数百MB〜）へ逃がし、「保存容量が不足」で保存できない問題を解く。
 *
 * 単一DB `go5store`・単一オブジェクトストア `kv`（キー=文字列・値=任意）。Promiseベース。
 * 非対応/オープン失敗時は available() が false になり、呼び出し側が localStorage へフォールバックする。
 */
(function (root) {
  "use strict";

  var DB = "go5store", STORE = "kv", VER = 1;
  var _dbP = null;

  function hasIdb() { try { return typeof indexedDB !== "undefined" && !!indexedDB; } catch (e) { return false; } }
  function available() { return hasIdb(); }

  function open() {
    if (_dbP) return _dbP;
    _dbP = new Promise(function (resolve, reject) {
      if (!hasIdb()) { reject(new Error("no-indexeddb")); return; }
      var req;
      try { req = indexedDB.open(DB, VER); } catch (e) { reject(e); return; }
      req.onupgradeneeded = function () { try { if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE); } catch (e) {} };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error || new Error("idb-open-failed")); };
      req.onblocked = function () { reject(new Error("idb-blocked")); };
    });
    return _dbP;
  }

  // トランザクション1つで fn(store) を実行し、oncomplete で解決（get は req.result を返す）。
  function withStore(mode, fn) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var t, req;
        try { t = db.transaction(STORE, mode); } catch (e) { reject(e); return; }
        var st = t.objectStore(STORE);
        try { req = fn(st); } catch (e) { reject(e); return; }
        t.oncomplete = function () { resolve(req ? req.result : undefined); };
        t.onerror = function () { reject(t.error || new Error("idb-tx-error")); };
        t.onabort = function () { reject(t.error || new Error("idb-abort")); };
      });
    });
  }

  function get(key) { return withStore("readonly", function (st) { return st.get(key); }); }
  function set(key, val) { return withStore("readwrite", function (st) { return st.put(val, key); }); }
  function del(key) { return withStore("readwrite", function (st) { return st.delete(key); }); }

  // 全エントリを {key: value} で返す（起動時のハイドレート用）。
  function entries() {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var out = {}, t, st, c;
        try { t = db.transaction(STORE, "readonly"); st = t.objectStore(STORE); c = st.openCursor(); }
        catch (e) { reject(e); return; }
        c.onsuccess = function () { var cur = c.result; if (cur) { out[cur.key] = cur.value; cur.continue(); } else resolve(out); };
        c.onerror = function () { reject(c.error || new Error("idb-cursor-error")); };
      });
    });
  }

  var API = { available: available, get: get, set: set, del: del, entries: entries };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.Go5Idb = API;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
