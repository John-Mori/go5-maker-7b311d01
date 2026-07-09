/**
 * core/sync.js — 全端末クラウド同期エンジン（Go5Sync）。sync-worker と対で動く。
 *
 * 同期対象：
 *   ・localStorage の「設定」(Go5Keys.syncAllowed) と「候補テキスト」(cand_items ・ cand_tabs ・ cand_hidden__ 系)。
 *   ・IndexedDB の候補素材（ref:/bsky:/post: ＝ 参照画像・コメント・メモ）。画像は R2 に content-hash で保存し、
 *     状態には {__img:<hash>} だけ入れる（blobを小さく保つ）。
 *   ・「鍵(アプリPW等)」は passphrase で AES-GCM 暗号化した1件(__sec)としてだけ同期（平文はクラウドに出さない）。
 *
 * 同期方式：各キー last-write-wins（per-key タイムスタンプ・スナップショット差分で変更/削除を検出）。
 *   push は baseVersion 付き。衝突(他端末先行)なら再pull→マージ→再push。変更が無ければ push しない。
 *   自動＝起動時pull＋一定間隔＋タブ非表示化(離脱)時。手動ボタンもあり。
 *
 * 設定(この端末だけ・同期しない・送らない)：localStorage sync2_url / sync2_token / sync2_pass(パスフレーズ)。
 */
(function (root) {
  "use strict";
  var LS = root.localStorage;
  var Keys = root.Go5Keys;
  var Idb = root.Go5Idb;

  function cfg() {
    var g = function (k) { try { return (LS.getItem(k) || "").trim(); } catch (e) { return ""; } };
    return { url: g("sync2_url").replace(/\/+$/, ""), token: g("sync2_token"), pass: g("sync2_pass") };
  }
  function configured() { var c = cfg(); return /^https?:\/\//.test(c.url) && !!c.token; }
  function deviceName() { try { return (LS.getItem("sync_device_name") || "").trim() || "device"; } catch (e) { return "device"; } }

  function isSyncLsKey(k) {
    k = String(k);
    if (/^sync2_/.test(k)) return false;                 // 同期自身の設定/内部状態は同期しない
    if (Keys && Keys.isSecret(k)) return false;          // 秘密は __sec(暗号化)経由でのみ
    if (/^cand_(items|tabs)(__|$)/.test(k)) return true; // 候補リスト・タブ・独立タブのアイテム
    if (/^cand_hidden__/.test(k)) return true;           // 非表示リスト
    if (k === "cand_hide_posted") return true;
    if (Keys && Keys.syncAllowed(k)) return true;        // 本物の設定（レイアウト/本文/説明欄/af_id 等）
    return false;
  }
  function isSyncIdbKey(k) { return /^(ref:|bsky:|post:)/.test(String(k)); }

  // ── 暗号（WebCrypto AES-GCM / PBKDF2）──
  var subtle = (root.crypto && root.crypto.subtle) || null;
  function u8(str) { return new TextEncoder().encode(str); }
  function b64(buf) { var b = new Uint8Array(buf), s = ""; for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]); return root.btoa(s); }
  function unb64(str) { var s = root.atob(str), a = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; }
  function hex(buf) { var b = new Uint8Array(buf), s = ""; for (var i = 0; i < b.length; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16); return s; }
  function sha256hex(str) { return subtle.digest("SHA-256", u8(str)).then(hex); }
  function deriveKey(pass, salt) {
    return subtle.importKey("raw", u8(pass), "PBKDF2", false, ["deriveKey"]).then(function (base) {
      return subtle.deriveKey({ name: "PBKDF2", salt: salt, iterations: 150000, hash: "SHA-256" }, base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    });
  }
  function encryptJson(obj, pass) {
    var salt = root.crypto.getRandomValues(new Uint8Array(16)), iv = root.crypto.getRandomValues(new Uint8Array(12));
    return deriveKey(pass, salt).then(function (key) { return subtle.encrypt({ name: "AES-GCM", iv: iv }, key, u8(JSON.stringify(obj))); })
      .then(function (ct) { return JSON.stringify({ salt: b64(salt), iv: b64(iv), ct: b64(ct) }); });
  }
  function decryptJson(recStr, pass) {
    var rec = JSON.parse(recStr);
    return deriveKey(pass, unb64(rec.salt)).then(function (key) { return subtle.decrypt({ name: "AES-GCM", iv: unb64(rec.iv) }, key, unb64(rec.ct)); })
      .then(function (buf) { return JSON.parse(new TextDecoder().decode(buf)); });
  }

  // ── 通信 ──
  function api(path, opts) {
    var c = cfg(); opts = opts || {};
    opts.headers = Object.assign({ "X-Sync-Token": c.token }, opts.headers || {});
    return root.fetch(c.url + path, opts);
  }
  function pullState() { return api("/api/pull").then(function (r) { return r.json(); }); }
  function pushState(map, baseVersion) {
    var body = { blob: JSON.stringify(map), updatedAt: new Date().toISOString(), device: deviceName(), baseVersion: baseVersion || 0 };
    return api("/api/push", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return r.json(); });
  }

  // ── 画像（R2）：dataURL⇄content-hash ──
  function collectDataUrls(val, bag) {
    if (typeof val === "string") { if (/^data:/.test(val)) bag.push(val); return; }
    if (Array.isArray(val)) { val.forEach(function (x) { collectDataUrls(x, bag); }); return; }
    if (val && typeof val === "object") for (var k in val) if (has(val, k)) collectDataUrls(val[k], bag);
  }
  function mapVal(val, isLeaf, fn) {
    if (isLeaf(val)) return fn(val);
    if (Array.isArray(val)) return val.map(function (x) { return mapVal(x, isLeaf, fn); });
    if (val && typeof val === "object") { var o = {}; for (var k in val) if (has(val, k)) o[k] = mapVal(val[k], isLeaf, fn); return o; }
    return val;
  }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function isImgRef(v) { return v && typeof v === "object" && !Array.isArray(v) && typeof v.__img === "string"; }

  // IDB値(dataURL入り) → hash化。未アップロード画像を R2 へ。失敗画像は dataURL のまま残す（データ保全）。
  function uploadImagesIn(val) {
    var urls = []; collectDataUrls(val, urls);
    if (!urls.length) return Promise.resolve(val);
    var uniq = {}; urls.forEach(function (u) { uniq[u] = 1; }); urls = Object.keys(uniq);
    var hByUrl = {};
    return Promise.all(urls.map(function (u) { return sha256hex(u).then(function (h) { hByUrl[u] = h; }); })).then(function () {
      var keys = urls.map(function (u) { return hByUrl[u]; });
      return api("/api/img/has?keys=" + keys.join(",")).then(function (r) { return r.json(); }).catch(function () { return { present: [] }; });
    }).then(function (hasRes) {
      var present = {}; (hasRes.present || []).forEach(function (k) { present[k] = 1; });
      var toUp = urls.filter(function (u) { return !present[hByUrl[u]]; });
      return Promise.all(toUp.map(function (u) {
        return api("/api/img/" + hByUrl[u], { method: "PUT", headers: { "Content-Type": "text/plain" }, body: u })
          .then(function (r) { return r.json(); }).then(function (j) { if (!j || !j.ok) hByUrl[u] = null; }).catch(function () { hByUrl[u] = null; });
      }));
    }).then(function () {
      return mapVal(val, function (v) { return typeof v === "string" && /^data:/.test(v); }, function (u) { var h = hByUrl[u]; return h ? { __img: h } : u; });
    });
  }
  // hash化された値 → R2 から dataURL を復元。失敗画像は空文字（表示されないだけ）。
  function downloadImagesIn(val) {
    var refs = []; (function walk(v) { if (isImgRef(v)) { refs.push(v.__img); return; } if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v === "object") for (var k in v) if (has(v, k)) walk(v[k]); })(val);
    if (!refs.length) return Promise.resolve(val);
    var c = cfg(), byHash = {}, uniq = {}; refs.forEach(function (h) { uniq[h] = 1; });
    return Promise.all(Object.keys(uniq).map(function (h) {
      return root.fetch(c.url + "/img/" + h).then(function (r) { return r.ok ? r.text() : ""; }).then(function (t) { byHash[h] = /^data:/.test(t) ? t : ""; }).catch(function () { byHash[h] = ""; });
    })).then(function () {
      return mapVal(val, isImgRef, function (ref) { return byHash[ref.__img] || ""; });
    });
  }

  // ── ローカル状態 ──
  function loadSnap() { try { return JSON.parse(LS.getItem("sync2_snap") || "{}") || {}; } catch (e) { return {}; } }
  function saveSnap(s) { try { LS.setItem("sync2_snap", JSON.stringify(s)); } catch (e) {} }
  function loadTs() { try { return JSON.parse(LS.getItem("sync2_ts") || "{}") || {}; } catch (e) { return {}; } }
  function saveTs(t) { try { LS.setItem("sync2_ts", JSON.stringify(t)); } catch (e) {} }
  function getVer() { try { return parseInt(LS.getItem("sync2_ver") || "0", 10) || 0; } catch (e) { return 0; } }
  function setVer(v) { try { LS.setItem("sync2_ver", String(v)); } catch (e) {} }

  function gatherLs() { var out = {}; try { for (var i = 0; i < LS.length; i++) { var k = LS.key(i); if (isSyncLsKey(k)) out[k] = LS.getItem(k); } } catch (e) {} return out; }

  // 鍵(秘密)＝キー単位で暗号化して同期。sync2_*(同期自身の設定＝端末ローカル)は絶対に対象外。
  var SEC_PREFIX = "sec:";
  function syncableSecret(k) { k = String(k); return !!(Keys && Keys.isSecret(k)) && !/^sync2_/.test(k); }
  // 現在の秘密を {SEC_PREFIX+key: 暗号文} に。平文が前回と同じなら暗号文を再利用（毎回変わらないように）。
  //   pass 未設定なら skip=true（この端末では鍵を同期しない＝雲側の暗号鍵は触らない）。
  function buildSecEntries(snap) {
    var c = cfg(), plain = {};
    try { for (var i = 0; i < LS.length; i++) { var k = LS.key(i); if (syncableSecret(k)) plain[k] = LS.getItem(k); } } catch (e) {}
    if (!c.pass || !subtle) return Promise.resolve({ entries: {}, plain: {}, skip: true });
    var snapPlain = (snap && snap.secPlain) || {}, snapLs = (snap && snap.ls) || {}, entries = {}, jobs = [];
    Object.keys(plain).forEach(function (sk) {
      var pk = SEC_PREFIX + sk;
      if (plain[sk] === snapPlain[sk] && snapLs[pk]) entries[pk] = snapLs[pk];               // 再利用
      else jobs.push(encryptJson(plain[sk], c.pass).then(function (ct) { entries[pk] = ct; })); // 変更あり＝再暗号化
    });
    return Promise.all(jobs).then(function () { return { entries: entries, plain: plain, skip: false }; });
  }

  var _busy = false, _lastErr = "", _lastAt = 0;
  function status() { return { configured: configured(), busy: _busy, version: getVer(), lastError: _lastErr, lastAt: _lastAt, device: deviceName() }; }

  // per-key マージ（t 大きい方を採用）。
  function mergeMaps(local, rem) {
    var out = {}, seen = {};
    Object.keys(local).forEach(function (k) { seen[k] = 1; }); Object.keys(rem).forEach(function (k) { seen[k] = 1; });
    Object.keys(seen).forEach(function (k) { var a = local[k], b = rem[k]; out[k] = (a && b) ? (((b.t || 0) > (a.t || 0)) ? b : a) : (a || b); });
    return out;
  }
  function stripT(map) { var o = {}; Object.keys(map).forEach(function (k) { var e = map[k]; o[k] = e.d ? { d: 1 } : { v: e.v }; }); return o; } // 比較用（t除去）

  // 候補リスト(cand_items / cand_items__*)は配列を1キーに持つため、whole-key LWW だと初回に別端末の
  //   候補を丸ごと消し得る。cid で union し、重複cidは newer 側を採用＝「集めた候補を失わない」。
  function isCandArrayKey(k) { return /^cand_items(__|$)/.test(String(k)); }
  function unionCand(olderStr, newerStr) {
    try {
      var older = JSON.parse(olderStr || "[]"), newer = JSON.parse(newerStr || "[]");
      if (!Array.isArray(older) || !Array.isArray(newer)) return null;
      var byCid = {}, order = [], anon = 0;
      function add(arr) { arr.forEach(function (it) { var key = (it && it.cid != null) ? ("c:" + it.cid) : ("a:" + (anon++)); if (!(key in byCid)) order.push(key); byCid[key] = it; }); }
      add(older); add(newer); // 後入れ(newer)が重複cidを上書き＝newer優先
      return JSON.stringify(order.map(function (k) { return byCid[k]; }));
    } catch (e) { return null; }
  }

  function syncOnce(retry) {
    if (!configured() || (_busy && !retry)) return Promise.resolve({ ok: false, skipped: true });
    var c = cfg(); _busy = true;
    var snap = loadSnap(), ts = loadTs(), now = Date.now();
    var snapLs = snap.ls || {}, snapIdb = snap.idb || {};
    var curLs = gatherLs();
    var secInfo = { entries: {}, plain: {}, skip: true };
    var newSecPlain = {};                 // push成功時に保存する {key:平文}（remote勝ちは復号後に追記）
    // 鍵をキー単位で暗号化して curLs へ（sec:<key>）。pass無しなら付けない。
    var secStep = buildSecEntries(snap).then(function (info) {
      secInfo = info; newSecPlain = Object.assign({}, info.plain);
      Object.keys(info.entries).forEach(function (pk) { curLs[pk] = info.entries[pk]; });
    });

    // IDB を hash化（画像アップロード）
    var curIdb = {};
    var idbStep = (Idb && Idb.available()) ? Idb.entries().then(function (all) {
      return Object.keys(all).filter(isSyncIdbKey).reduce(function (p, k) {
        return p.then(function () { return uploadImagesIn(all[k]).then(function (hv) { curIdb[k] = hv; }); });
      }, Promise.resolve());
    }) : Promise.resolve();

    return Promise.all([secStep, idbStep]).then(function () {
      // pass無し(skip)の端末は、雲側の sec: キーを消さない（削除判定から除外）。
      var snapLsStamp = snapLs;
      if (secInfo.skip) { snapLsStamp = {}; Object.keys(snapLs).forEach(function (k) { if (k.indexOf(SEC_PREFIX) !== 0) snapLsStamp[k] = snapLs[k]; }); }
      // 変更/削除→タイムスタンプ更新。
      function stamp(prefix, cur, snp) {
        Object.keys(cur).forEach(function (k) {
          if (ts[prefix + k + " d"]) { delete ts[prefix + k + " d"]; ts[prefix + k] = now; return; } // 復活
          if (JSON.stringify(cur[k]) !== JSON.stringify(snp[k])) ts[prefix + k] = now;
          else if (!ts[prefix + k]) ts[prefix + k] = now;
        });
        Object.keys(snp).forEach(function (k) { if (!(k in cur) && !ts[prefix + k + " d"]) { ts[prefix + k] = now; ts[prefix + k + " d"] = 1; } });
      }
      stamp("ls:", curLs, snapLsStamp); stamp("idb:", curIdb, snapIdb);
      function localMap(prefix, cur, snp) {
        var m = {};
        Object.keys(cur).forEach(function (k) { m[k] = { t: ts[prefix + k] || now, v: cur[k] }; });
        Object.keys(snp).forEach(function (k) { if (!(k in cur) && ts[prefix + k + " d"]) m[k] = { t: ts[prefix + k] || now, d: 1 }; });
        return m;
      }
      var lmapLs = localMap("ls:", curLs, snapLsStamp), lmapIdb = localMap("idb:", curIdb, snapIdb);

      return pullState().then(function (res) {
        var remote = {}; if (res && res.ok && !res.empty && res.blob) { try { remote = JSON.parse(res.blob); } catch (e) {} }
        var rver = (res && res.version) || 0, rls = remote.ls || {}, ridb = remote.idb || {};
        var mls = mergeMaps(lmapLs, rls), midb = mergeMaps(lmapIdb, ridb);
        // 候補リストは両側にあれば cid で union（消さない）。
        Object.keys(mls).forEach(function (k) {
          if (!isCandArrayKey(k)) return;
          var a = lmapLs[k], b = rls[k];
          if (a && b && !a.d && !b.d) {
            var localNewer = (a.t || 0) >= (b.t || 0);
            var u = unionCand(localNewer ? b.v : a.v, localNewer ? a.v : b.v);
            if (u != null) mls[k] = { t: Math.max(a.t || 0, b.t || 0), v: u };
          }
        });

        // マージ結果をローカルへ適用
        var applies = [], newSnapLs = {}, newSnapIdb = {};
        Object.keys(mls).forEach(function (k) {
          var e = mls[k];
          var isSec = k.indexOf(SEC_PREFIX) === 0, sk = isSec ? k.slice(SEC_PREFIX.length) : null;
          if (e.d) { newSnapLs[k] = undefined; try { if (isSec) { LS.removeItem(sk); delete newSecPlain[sk]; } else if (isSyncLsKey(k)) LS.removeItem(k); } catch (x) {} return; }
          newSnapLs[k] = e.v;
          if (isSec) {
            // 自分の暗号文が採用＝復号不要（PBKDF2の無駄打ち回避）。remote勝ち(別の値)の時だけ復号して反映。
            if (secInfo.entries[k] && e.v === secInfo.entries[k]) { newSecPlain[sk] = secInfo.plain[sk]; return; }
            if (c.pass && subtle && e.v) applies.push(decryptJson(e.v, c.pass).then(function (val) {
              try { LS.setItem(sk, String(val)); } catch (x) {} newSecPlain[sk] = String(val);
            }).catch(function () { _lastErr = "鍵の復号に失敗（パスフレーズ不一致?）"; }));
            return;
          }
          try { if (LS.getItem(k) !== e.v) LS.setItem(k, e.v); } catch (x) {}
        });
        Object.keys(midb).forEach(function (k) {
          var e = midb[k];
          if (e.d) { if (Idb && Idb.available()) applies.push(Idb.del(k).catch(function () {})); return; }
          newSnapIdb[k] = e.v;
          if (Idb && Idb.available()) applies.push(downloadImagesIn(e.v).then(function (rebuilt) { return Idb.set(k, rebuilt); }).catch(function () {}));
        });

        return Promise.all(applies).then(function () {
          // 削除で undefined になった snap を落とす
          Object.keys(newSnapLs).forEach(function (k) { if (newSnapLs[k] === undefined) delete newSnapLs[k]; });
          var outState = { fmt: 2, ls: mls, idb: midb, device: deviceName(), updatedAt: new Date().toISOString() };
          var changed = JSON.stringify(stripT(mls)) !== JSON.stringify(stripT(rls)) || JSON.stringify(stripT(midb)) !== JSON.stringify(stripT(ridb));
          function persist(ver) { setVer(ver); saveTs(ts); saveSnap({ ls: newSnapLs, idb: newSnapIdb, secPlain: newSecPlain }); _busy = false; _lastErr = ""; _lastAt = Date.now(); }
          if (!changed) { persist(rver); return { ok: true, version: rver, noChange: true }; }
          return pushState(outState, rver).then(function (pr) {
            if (pr && pr.ok) { persist(pr.version); return { ok: true, version: pr.version }; }
            if (pr && pr.conflict && !retry) { _busy = false; return syncOnce(true); } // 再pull→マージ→再push
            _busy = false; _lastErr = (pr && pr.error) || "push失敗"; return { ok: false, error: _lastErr };
          });
        });
      });
    }).catch(function (e) { _busy = false; _lastErr = String((e && e.message) || e); return { ok: false, error: _lastErr }; });
  }

  var _timer = null;
  function startAuto() {
    if (_timer || !configured()) return;
    syncOnce(false);
    _timer = root.setInterval(function () { syncOnce(false); }, 25000);
    if (root.document) root.document.addEventListener("visibilitychange", function () { if (root.document.visibilityState === "hidden") syncOnce(false); });
  }

  root.Go5Sync = {
    configured: configured, syncNow: function () { return syncOnce(false); }, status: status, startAuto: startAuto,
    setConfig: function (o) {
      try {
        if (o.url != null) LS.setItem("sync2_url", String(o.url).trim());
        if (o.token != null) LS.setItem("sync2_token", String(o.token).trim());
        if (o.pass != null) LS.setItem("sync2_pass", String(o.pass));
      } catch (e) {}
    },
    getConfig: function () { var c = cfg(); return { url: c.url, token: c.token, hasPass: !!c.pass }; },
    resetLocalSyncState: function () { ["sync2_snap", "sync2_ts", "sync2_ver"].forEach(function (k) { try { LS.removeItem(k); } catch (e) {} }); }
  };

  // ── ⚙詳細設定 UI 配線＋自動同期の起動 ──
  if (root.document) root.document.addEventListener("DOMContentLoaded", function () {
    var $ = function (id) { return root.document.getElementById(id); };
    var url = $("syncNewUrl"), tok = $("syncNewToken"), pass = $("syncNewPass"), nowBtn = $("syncNewNow"), st = $("syncNewStatus");
    var c = cfg();
    if (url) url.value = c.url; if (tok) tok.value = c.token; if (pass) pass.value = c.pass;
    function save() { root.Go5Sync.setConfig({ url: url ? url.value : "", token: tok ? tok.value : "", pass: pass ? pass.value : "" }); }
    [url, tok, pass].forEach(function (el) { if (el) { el.addEventListener("change", save); el.addEventListener("blur", save); } });
    function showStatus() { if (!st) return; var s = status(); st.textContent = !s.configured ? "未設定（3つを入力すると自動同期します）" : (s.busy ? "同期中…" : (s.lastError ? "⚠️ " + s.lastError : (s.version ? "✅ 同期済み（v" + s.version + "）" : "設定OK。「今すぐ同期」で開始"))); }
    if (nowBtn) nowBtn.addEventListener("click", function () {
      save();
      if (!configured()) { if (st) st.textContent = "⚠️ 同期URLとトークンを入れてください"; return; }
      if (st) st.textContent = "🔄 同期中…";
      syncOnce(false).then(function (r) { if (st) st.textContent = r.ok ? ("✅ 同期しました（v" + r.version + "）") : ("⚠️ " + (r.error || "失敗")); });
    });
    var tab = $("tabSettings"); if (tab) tab.addEventListener("click", function () { root.setTimeout(showStatus, 300); });
    showStatus();
    startAuto(); // 設定済みなら自動同期を開始（起動時pull＋25秒間隔＋離脱時push）
  });
})(typeof window !== "undefined" ? window : this);
