/**
 * core/idb-store.js — IndexedDB の小さなKVストア。(Go5Idb)
 *
 * 目的：候補の保存画像(dataURL・大きい)を localStorage(iOS Safariは1サイト約5MB固定)から
 *   IndexedDB(容量は端末の空きに応じて数百MB〜)へ逃がし、「保存容量が不足」で保存できない問題を解く。
 *
 * 単一DB `go5store`・単一オブジェクトストア `kv`。(キー=文字列・値=任意)Promiseベース。
 * 非対応/オープン失敗時は available() が false になり、呼び出し側が localStorage へフォールバックする。
 *
 * ★接続の張り直し(2026-08-05)：開いた接続 db は _dbP に1つだけキャッシュするが、ブラウザ側の都合
 *   (iOS Safari のメモリ圧・タブのバックグラウンド化、別タブのバージョン変更)で接続が閉じられると、
 *   キャッシュした古い接続に db.transaction() を張った瞬間に
 *   「Failed to execute 'transaction' on 'IDBDatabase': The database connection is closing.」で落ちる。
 *   これで動画blobの読み出しが全滅→動画DL不可→投稿完了不可になっていた(サブ端末・Chami報告)。
 *   対策＝ onversionchange / onclose でキャッシュを捨て、transaction 生成が「閉じかけ」で throw したら
 *   キャッシュを捨てて1回だけ再オープンして張り直す(冪等・既存APIは不変)。
 */
(function (root) {
  "use strict";

  var DB = "go5store", STORE = "kv", VER = 1;
  var _dbP = null;

  function hasIdb() { try { return typeof indexedDB !== "undefined" && !!indexedDB; } catch (e) { return false; } }
  function available() { return hasIdb(); }

  function open() {
    if (_dbP) return _dbP;
    var thisP = _dbP = new Promise(function (resolve, reject) {
      if (!hasIdb()) { reject(new Error("no-indexeddb")); return; }
      var req;
      try { req = indexedDB.open(DB, VER); } catch (e) { reject(e); return; }
      req.onupgradeneeded = function () { try { if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE); } catch (e) {} };
      req.onsuccess = function () {
        var db = req.result;
        // 別タブがバージョンを上げた時は自分から閉じてキャッシュを捨てる(次回アクセスで再オープン)。
        try { db.onversionchange = function () { try { db.close(); } catch (e) {} if (_dbP === thisP) _dbP = null; }; } catch (e) {}
        // ブラウザが接続を閉じた(iOS Safari のメモリ圧・バックグラウンド)時もキャッシュを捨てる。
        try { db.onclose = function () { if (_dbP === thisP) _dbP = null; }; } catch (e) {}
        resolve(db);
      };
      req.onerror = function () { if (_dbP === thisP) _dbP = null; reject(req.error || new Error("idb-open-failed")); };
      req.onblocked = function () { if (_dbP === thisP) _dbP = null; reject(new Error("idb-blocked")); };
    });
    // オープンが失敗で終わったらキャッシュを残さない(次回やり直せるように)。
    thisP.catch(function () { if (_dbP === thisP) _dbP = null; });
    return _dbP;
  }

  // 接続が閉じかけで transaction 生成に失敗した時=キャッシュを捨てて張り直す(1回だけ)対象のエラーか。
  function isClosingErr(e) {
    var n = e && (e.name || ""), m = String((e && e.message) || e);
    return n === "InvalidStateError" || /closing|closed|not allowed in the current state/i.test(m);
  }

  // トランザクション1つで fn(store) を実行し、oncomplete で解決。(get は req.result を返す)
  //   retry=true の初回のみ、transaction 生成が「閉じかけ」で throw したら再オープンして1回だけやり直す。
  function withStore(mode, fn, retry) {
    if (retry === undefined) retry = true;
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var t, req;
        try { t = db.transaction(STORE, mode); }
        catch (e) {
          if (retry && isClosingErr(e)) { _dbP = null; resolve(withStore(mode, fn, false)); return; }
          reject(e); return;
        }
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

  // 全エントリを {key: value} で返す。(起動時のハイドレート用)閉じかけなら1回だけ再オープンして張り直す。
  function entries(retry) {
    if (retry === undefined) retry = true;
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var out = {}, t, st, c;
        try { t = db.transaction(STORE, "readonly"); st = t.objectStore(STORE); c = st.openCursor(); }
        catch (e) {
          if (retry && isClosingErr(e)) { _dbP = null; resolve(entries(false)); return; }
          reject(e); return;
        }
        c.onsuccess = function () { var cur = c.result; if (cur) { out[cur.key] = cur.value; cur.continue(); } else resolve(out); };
        c.onerror = function () { reject(c.error || new Error("idb-cursor-error")); };
      });
    });
  }

  var API = { available: available, get: get, set: set, del: del, entries: entries };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.Go5Idb = API;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
