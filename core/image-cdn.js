/**
 * core/image-cdn.js — 候補/投稿履歴の画像を「確定済みURL」で即表示する共通層。
 *
 * 画像本体は sync-worker の公開 /img/<sha256> (R2・immutable)へ raw bytes で置き、
 * localStorage には小さなURL台帳だけを持つ。表示時にIndexedDBを走査・dataURLへ変換してから
 * srcを決める旧経路と分離し、台帳があれば初回DOM生成からブラウザ/CDNへ直接取りに行ける。
 * IndexedDB/dataURLは編集・オフライン・旧データ復旧用として残し、唯一コピーを消さない。
 */
(function (root) {
  "use strict";

  var KEY = "go5_image_manifest_v1";
  var HASH_RE = /^[a-f0-9]{64}$/;
  var _cacheRaw = null, _cacheMap = {};
  var _jobs = Object.create(null);
  var _queue = [], _active = 0, MAX_ACTIVE = 2;
  var _syncTimer = null;

  function storage_() { return root && root.localStorage; }
  function read_() {
    var raw = "";
    try { raw = (storage_() && storage_().getItem(KEY)) || ""; } catch (e) { raw = ""; }
    if (raw === _cacheRaw) return _cacheMap;
    var map = {};
    try {
      var parsed = JSON.parse(raw || "{}");
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) map = parsed;
    } catch (e) {}
    _cacheRaw = raw; _cacheMap = map;
    return map;
  }
  function recId_(kind, id) { return String(kind || "") + ":" + String(id || ""); }
  function validRec_(rec) {
    if (!rec || typeof rec !== "object" || Array.isArray(rec) || !Array.isArray(rec.keys)) return null;
    var keys = rec.keys.map(function (h) { return String(h || "").toLowerCase(); }).filter(function (h) { return HASH_RE.test(h); });
    if (keys.length !== rec.keys.length) return null;
    return { keys: keys, prev: Math.max(0, Number(rec.prev) | 0), at: Math.max(0, Number(rec.at) || 0) };
  }
  function record_(kind, id) { return validRec_(read_()[recId_(kind, id)]); }
  function workerBase_() {
    try {
      var c = root.Go5Sync && root.Go5Sync.getConfig && root.Go5Sync.getConfig();
      return c && /^https?:\/\//.test(c.url || "") ? String(c.url).replace(/\/+$/, "") : "";
    } catch (e) { return ""; }
  }
  function urlsForRec_(rec, base) {
    rec = validRec_(rec); base = String(base || "").replace(/\/+$/, "");
    if (!rec || !base) return [];
    return rec.keys.map(function (h) { return base + "/img/" + h; });
  }
  function urls_(kind, id) { return urlsForRec_(record_(kind, id), workerBase_()); }
  function known_(kind, id) { return Object.prototype.hasOwnProperty.call(read_(), recId_(kind, id)) && !!record_(kind, id); }
  function prev_(kind, id) { var r = record_(kind, id); return r ? r.prev : 0; }

  function emit_(ids, source) {
    try {
      if (root.document) root.document.dispatchEvent(new root.CustomEvent("go5-image-manifest-changed", {
        detail: { ids: (ids || []).slice(), source: source || "local" }
      }));
    } catch (e) {}
  }
  function scheduleSync_() {
    if (_syncTimer || !root.setTimeout) return;
    _syncTimer = root.setTimeout(function () {
      _syncTimer = null;
      try {
        if (root.Go5Sync && root.Go5Sync.syncImageManifestNow) root.Go5Sync.syncImageManifestNow();
        else if (root.Go5Sync && root.Go5Sync.flushSync) root.Go5Sync.flushSync();
        else if (root.Go5Sync && root.Go5Sync.requestSync) root.Go5Sync.requestSync();
      } catch (e) {}
    }, 80);
  }
  function commitMap_(map, ids, source, pushNow) {
    var raw = JSON.stringify(map || "{}"), ls = storage_();
    if (!ls) return false;
    function attempt_() { try { ls.setItem(KEY, raw); return true; } catch (e) { return false; } }
    var ok = attempt_();
    // localStorage????????/???????????????????????????????
    // ??????????????Go5Keys.isPurgeable=false???????????
    if (!ok && root.Go5Keys && root.Go5Keys.isPurgeable) {
      var victims = [];
      try {
        for (var i = 0; i < ls.length; i++) {
          var k = ls.key(i); if (k && k !== KEY && root.Go5Keys.isPurgeable(k)) victims.push(k);
        }
      } catch (e) {}
      for (var j = 0; j < victims.length && !ok; j++) {
        try { ls.removeItem(victims[j]); } catch (e) {}
        ok = attempt_();
      }
    }
    if (!ok) return false;
    _cacheRaw = null; _cacheMap = {};
    emit_(ids || [], source || "local");
    if (pushNow) scheduleSync_();
    return true;
  }
  function acceptRaw_(raw, source) {
    var parsed;
    try { parsed = JSON.parse(String(raw || "{}")); } catch (e) { return false; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return false;
    var clean = {};
    Object.keys(parsed).forEach(function (id) { var r = validRec_(parsed[id]); if (r) clean[id] = r; });
    return commitMap_(clean, Object.keys(clean), source || "sync", false);
  }
  function writeRecord_(kind, id, keys, opts) {
    var rid = recId_(kind, id), at = Math.max(1, Number(opts && opts.at) || Date.now());
    var map;
    try {
      map = JSON.parse((storage_() && storage_().getItem(KEY)) || "{}");
      if (!map || typeof map !== "object" || Array.isArray(map)) map = {};
    } catch (e) { map = {}; }
    var old = validRec_(map[rid]);
    if (old && old.at > at) return old; // 遅い旧ジョブが新しい画像台帳を巻き戻さない。
    var rec = { keys: (keys || []).slice(), prev: Math.max(0, Number(opts && opts.prev) | 0), at: at };
    map[rid] = rec;
    return commitMap_(map, [rid], "local", true) ? rec : null;
  }

  function dataUrlBlob_(src) {
    try {
      var m = /^data:([^;,]*?)(;base64)?,([\s\S]*)$/.exec(String(src || ""));
      if (!m) return null;
      var raw = m[2] ? root.atob(m[3]) : decodeURIComponent(m[3]);
      var bytes = new Uint8Array(raw.length);
      for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
      return new root.Blob([bytes], { type: m[1] || "image/jpeg" });
    } catch (e) { return null; }
  }
  function hashFromDirectUrl_(src) {
    var base = workerBase_(); if (!base) return "";
    var prefix = base + "/img/", s = String(src || "");
    if (s.indexOf(prefix) !== 0) return "";
    var h = s.slice(prefix.length).split(/[?#]/)[0].toLowerCase();
    return HASH_RE.test(h) ? h : "";
  }
  function fetchBlob_(src) {
    var direct = dataUrlBlob_(src); if (direct) return Promise.resolve(direct);
    if (root.Blob && src instanceof root.Blob) return Promise.resolve(src);
    if (!/^https?:\/\//.test(String(src || "")) || !root.fetch) return Promise.resolve(null);
    var ctl = root.AbortController ? new root.AbortController() : null;
    var timer = ctl && root.setTimeout ? root.setTimeout(function () { try { ctl.abort(); } catch (e) {} }, 30000) : null;
    return root.fetch(String(src), { cache: "force-cache", signal: ctl ? ctl.signal : undefined }).then(function (r) {
      if (timer) root.clearTimeout(timer);
      return r && r.ok ? r.blob() : null;
    }, function () { if (timer) root.clearTimeout(timer); return null; });
  }
  function enqueue_(fn) {
    return new Promise(function (resolve) { _queue.push({ fn: fn, resolve: resolve }); pump_(); });
  }
  function pump_() {
    while (_active < MAX_ACTIVE && _queue.length) {
      var task = _queue.shift(); _active++;
      (function (t) {
        Promise.resolve().then(t.fn).then(function (v) { t.resolve(v); }, function () { t.resolve(""); }).then(function () { _active--; pump_(); });
      }(task));
    }
  }
  function uploadOne_(src) {
    var h = hashFromDirectUrl_(src); if (h) return Promise.resolve(h);
    return fetchBlob_(src).then(function (blob) {
      if (!blob || !root.Go5Sync || !root.Go5Sync.putBlobR2) return "";
      return root.Go5Sync.putBlobR2(blob).then(function (key) { key = String(key || "").toLowerCase(); return HASH_RE.test(key) ? key : ""; }, function () { return ""; });
    });
  }
  function mirror_(kind, id, images, opts) {
    kind = String(kind || ""); id = String(id || ""); images = (images || []).filter(Boolean);
    if (!/^(ref|used|post|bsky)$/.test(kind) || !id) return Promise.resolve(null);
    if (!images.length) return Promise.resolve(writeRecord_(kind, id, [], opts)); // 明示削除も新しいatで伝播。
    var jid = recId_(kind, id);
    if (_jobs[jid]) return _jobs[jid];
    var job = Promise.all(images.map(function (src) { return enqueue_(function () { return uploadOne_(src); }); })).then(function (keys) {
      if (keys.length !== images.length || keys.some(function (h) { return !HASH_RE.test(h); })) return null;
      return writeRecord_(kind, id, keys, opts);
    }).catch(function () { return null; });
    _jobs[jid] = job.then(function (r) { delete _jobs[jid]; return r; }, function () { delete _jobs[jid]; return null; });
    return _jobs[jid];
  }
  // 旧dataURLを閲覧時に漸進移行。新規保存は mirror()を必ず呼び、同枚数の差替えも更新する。
  function ensure_(kind, id, images, opts) {
    images = (images || []).filter(Boolean);
    if (!images.length) return Promise.resolve(record_(kind, id));
    var rec = record_(kind, id), at = Math.max(0, Number(opts && opts.at) || 0), prev = Math.max(0, Number(opts && opts.prev) | 0);
    if (rec && rec.keys.length === images.length && rec.at >= at && rec.prev === prev) return Promise.resolve(rec);
    return mirror_(kind, id, images, opts);
  }
  // local record とURL台帳の更新時刻を比較し、描画に使う列を同期的に選ぶ。
  function pick_(kind, id, localImages, localAt, localKnown) {
    localImages = (localImages || []).filter(Boolean);
    var rec = record_(kind, id), lat = Math.max(0, Number(localAt) || 0);
    if (rec && rec.at > lat) return urlsForRec_(rec, workerBase_());
    if (localKnown || localImages.length) {
      if (localImages.length) ensure_(kind, id, localImages, { at: lat, prev: kind === "used" ? prev_(kind, id) : 0 });
      return localImages;
    }
    return rec ? urlsForRec_(rec, workerBase_()) : [];
  }

  var API = {
    key: KEY, record: record_, known: known_, urls: urls_, prevCount: prev_, pick: pick_, mirror: mirror_, ensure: ensure_, acceptRaw: acceptRaw_,
    refresh: function () { _cacheRaw = null; var before = _cacheMap; var after = read_(); return before !== after; },
    _test: { validRec: validRec_, recId: recId_, urlsForRec: urlsForRec_, hashFromDirectUrl: hashFromDirectUrl_ }
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.Go5ImageCdn = API;

  if (root && root.addEventListener) {
    root.addEventListener("storage", function (e) { if (e && e.key === KEY) { _cacheRaw = null; emit_([], "storage"); } });
    // 全同期/高速台帳同期で同じlocalStorageキーが書き換わった時も、現在ページだけ差分更新する。
    if (root.document) root.document.addEventListener("go5-synced", function () {
      var oldRaw = _cacheRaw; _cacheRaw = null; read_(); if (oldRaw != null && oldRaw !== _cacheRaw) emit_([], "sync");
    });
    // IDB全走査を待たない高速レールで、ページ起動直後に最新URL台帳だけ先取りする。
    if (root.setTimeout) root.setTimeout(function () {
      try { if (root.Go5Sync && root.Go5Sync.syncImageManifestNow) root.Go5Sync.syncImageManifestNow(); } catch (e) {}
    }, 0);
  }
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
