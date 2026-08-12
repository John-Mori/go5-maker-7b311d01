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
      // ★オープンの番犬(2026-08-13)：iOS Safari は indexedDB.open() が onsuccess/onerror/onblocked を
      //   一切発火せず無言で固まることがある(バックグラウンド化・メモリ圧)。この時 open() の Promise が
      //   永久に settle せず、withStore の TX番犬は open().then の後=一生張られない。呼び出し側
      //   (候補モーダルの ensureRefLoaded_ →「⏳ 読み込み中…」)が永久に固まる真因はこの穴。TX番犬と同じ
      //   時間で reject へ倒し、キャッシュを捨てて次回オープンをやり直せるようにする(fail-open・§3 可用性)。
      var settled = false, wd = null;
      function done(fn) { if (settled) return; settled = true; if (wd) { try { clearTimeout(wd); } catch (e) {} wd = null; } fn(); }
      try { wd = setTimeout(function () { if (_dbP === thisP) _dbP = null; done(function () { reject(new Error("idb-open-timeout")); }); }, TX_TIMEOUT_MS); } catch (e) {}
      var req;
      try { req = indexedDB.open(DB, VER); } catch (e) { done(function () { reject(e); }); return; }
      req.onupgradeneeded = function () { try { if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE); } catch (e) {} };
      req.onsuccess = function () {
        var db = req.result;
        // 別タブがバージョンを上げた時は自分から閉じてキャッシュを捨てる(次回アクセスで再オープン)。
        try { db.onversionchange = function () { try { db.close(); } catch (e) {} if (_dbP === thisP) _dbP = null; }; } catch (e) {}
        // ブラウザが接続を閉じた(iOS Safari のメモリ圧・バックグラウンド)時もキャッシュを捨てる。
        try { db.onclose = function () { if (_dbP === thisP) _dbP = null; }; } catch (e) {}
        done(function () { resolve(db); });
      };
      req.onerror = function () { if (_dbP === thisP) _dbP = null; done(function () { reject(req.error || new Error("idb-open-failed")); }); };
      req.onblocked = function () { if (_dbP === thisP) _dbP = null; done(function () { reject(new Error("idb-blocked")); }); };
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

  // ★無応答トランザクションの番犬(2026-08-13)：iOS Safari は db.transaction() が throw せず「生きている
  //   接続」に見えても、その直後の transaction が oncomplete/onerror/onabort を一切発火せず無言で固まることが
  //   ある(バックグラウンド化・メモリ圧で接続が in-flight のまま死ぬ)。この時 withStore の Promise は永久に
  //   settle せず、await している呼び出し側(候補モーダルの ensureRefLoaded_ →「⏳ 読み込み中…」)が固まる。
  //   Chami報告2026-08-13「候補タブでコメントやメモが読み込まれない・五分五分」の真因はこれ。isClosingErr の
  //   throw 経路(→再オープン)では拾えない=throwしない無言ハングだから。一定時間で reject に倒し、キャッシュを
  //   捨てて次回は接続を張り直す(fail-open=固まるより「読めなかった」と喋る側へ倒す・§3 可用性)。
  var TX_TIMEOUT_MS = 8000; // 単一キーの get/set/del は本来ミリ秒級。8秒は「明らかに死んでいる」判定の安全域。
  // トランザクション1つで fn(store) を実行し、oncomplete で解決。(get は req.result を返す)
  //   retry=true の初回のみ、transaction 生成が「閉じかけ」で throw したら再オープンして1回だけやり直す。
  function withStore(mode, fn, retry) {
    if (retry === undefined) retry = true;
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var settled = false, wd = null;
        function finish(cb) { if (settled) return; settled = true; if (wd) { try { clearTimeout(wd); } catch (e) {} wd = null; } cb(); }
        try {
          wd = setTimeout(function () {
            _dbP = null; // 無応答=死んだ接続とみなしキャッシュを捨てる(次回アクセスで再オープン)。
            // ★番犬で落ちたら1回だけ接続を張り直して再試行する(2026-08-13・Chami報告「ドラフト保存が
            //   idb-timeoutで失敗」「候補の読込が五分五分」)。iOS Safariはメモリ圧・バックグラウンド化で
            //   transaction が無言で死ぬ=張り直せば通ることが多い。旧実装は即rejectで一発勝負だった。
            //   retry=false の2周目まで死んだ時だけ idb-timeout を投げる(fail-open・§3 可用性)。
            if (retry) finish(function () { resolve(withStore(mode, fn, false)); });
            else finish(function () { reject(new Error("idb-timeout")); });
          }, TX_TIMEOUT_MS);
        } catch (e) {}
        var t, req;
        try { t = db.transaction(STORE, mode); }
        catch (e) {
          if (retry && isClosingErr(e)) { _dbP = null; finish(function () { resolve(withStore(mode, fn, false)); }); return; }
          finish(function () { reject(e); }); return;
        }
        var st = t.objectStore(STORE);
        try { req = fn(st); } catch (e) { finish(function () { reject(e); }); return; }
        t.oncomplete = function () { finish(function () { resolve(req ? req.result : undefined); }); };
        t.onerror = function () { finish(function () { reject(t.error || new Error("idb-tx-error")); }); };
        t.onabort = function () { finish(function () { reject(t.error || new Error("idb-abort")); }); };
      });
    }, function (openErr) {
      // ★open() 自体が番犬(idb-open-timeout)や onblocked で落ちた時も1回だけ張り直す。
      //   iOS Safari は indexedDB.open() が無言で固まることがあり、これも「五分五分」ハングの一経路。
      if (retry) return withStore(mode, fn, false);
      throw openErr;
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

  // 指定した接頭辞のキーだけを読む。候補ページが起動時に全KV(ドラフト動画Blobを含む)を
  // 展開してiOS Safariを圧迫しないため、IDBKeyRangeで対象範囲そのものを絞る。
  function entriesPrefix(prefix, retry) {
    if (retry === undefined) retry = true;
    prefix = String(prefix || "");
    if (!prefix) return Promise.resolve({});
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var out = {}, t, st, c, range;
        try {
          t = db.transaction(STORE, "readonly");
          st = t.objectStore(STORE);
          range = IDBKeyRange.bound(prefix, prefix + "\uffff", false, false);
          c = st.openCursor(range);
        } catch (e) {
          if (retry && isClosingErr(e)) { _dbP = null; resolve(entriesPrefix(prefix, false)); return; }
          reject(e); return;
        }
        c.onsuccess = function () { var cur = c.result; if (cur) { out[cur.key] = cur.value; cur.continue(); } else resolve(out); };
        c.onerror = function () { reject(c.error || new Error("idb-prefix-cursor-error")); };
        t.onerror = function () { reject(t.error || new Error("idb-prefix-tx-error")); };
        t.onabort = function () { reject(t.error || new Error("idb-prefix-abort")); };
      });
    });
  }

  // 複数prefixは1範囲ずつ逐次取得する。大画像が多いiPhoneで同時に複数cursorを走らせず、
  // 呼び出し側には従来entries()と同じ {key:value} で返す。
  function entriesByPrefixes(prefixes) {
    var uniq = [], seen = {};
    (prefixes || []).forEach(function (p) { p = String(p || ""); if (p && !seen[p]) { seen[p] = true; uniq.push(p); } });
    var out = {}, chain = Promise.resolve();
    uniq.forEach(function (p) {
      chain = chain.then(function () { return entriesPrefix(p); }).then(function (part) {
        Object.keys(part || {}).forEach(function (k) { out[k] = part[k]; });
      });
    });
    return chain.then(function () { return out; });
  }
  // ★恒久対策(2026-08-11 Chami「候補の画像・コメント・メモが消えた」の再発クラス／C-038)：
  //   iOS Safari は「7日間サイトに触れないと script-writable storage(IndexedDB/localStorage)を全消去」する
  //   (ITPのstorage cap)。これで保存した動画生成用画像・コメント・メモが一斉に消える=今回の症状。
  //   navigator.storage.persist() で永続化を要求すると、この自動退避の対象から外れる(付与はブラウザのヒューリスティック)。
  //   完全に非破壊(feature-detect＋try/catch・既存APIは不変)。既に付与済みなら二重要求しない。
  function requestPersist() {
    try {
      if (!navigator.storage || !navigator.storage.persist) return;
      navigator.storage.persisted().then(function (already) {
        if (already) return;
        navigator.storage.persist().catch(function () {});
      }).catch(function () {});
    } catch (e) {}
  }
  try { requestPersist(); } catch (e) {}

  var API = { available: available, get: get, set: set, del: del, entries: entries, entriesPrefix: entriesPrefix, entriesByPrefixes: entriesByPrefixes, requestPersist: requestPersist };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.Go5Idb = API;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
