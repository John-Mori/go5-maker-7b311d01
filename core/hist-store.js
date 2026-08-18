/**
 * core/hist-store.js — 投稿履歴系キーの読み書きを一元化する層。(Go5Hist)
 *
 * 【解く問題】投稿完了を押すと稀に「投稿履歴をこの端末へ保存できませんでした。空き容量を…」が出て
 *   投稿履歴に載らない(炎上・再発多数)。真因＝投稿履歴を localStorage(iOS Safari 約5MB上限)へ保存して
 *   おり、満杯になると setItem が QuotaExceeded で失敗→persist-failed で投稿完了を中断していた。
 *   → 候補画像の INC-69 と同型の「メモリミラー＋起動ハイドレート＋write-through」で、正本を IndexedDB
 *   (数百MB)へ引っ越す。localStorage は後追いの best-effort コピーとして書き続ける(退役させない)。
 *
 * 【正本と冪等性(壊すと分析の元データが消える)】
 *   1. 既存データを1件も失わない。移行は非破壊・冪等。LSとIDBは itemKey / map キーで union マージ＝
 *      少ない方に消えない。壊れたLSは上書き前に <key>__broken_bak へ生退避。
 *   2. 同期リーダ(read)は同期のまま・署名不変。呼び出し元は receipt を無視するだけで無改修で動く。
 *   3. persist は「LSに載った or IDBに載った」なら成功。両方失敗時だけ従来どおり失敗(ドラフト残置)。
 *   4. 200件slice上限と「先頭が最新・溢れは最古を落とす」(INC-131)を ARRAY 系で全層維持。
 *   5. IDB available()=false / タイムアウト端末では従来どおり LS だけで動く(degrade するが壊れない)。
 *
 * 【キー分類(レジストリ)】acc は ['acc1','acc2'] 固定・両方を起動時に全ハイドレート。
 *   - ARRAY: short_hist__acc*, verify_manual__acc* … ミラー正本＋IDB＋LS後追いコピー(200件)。LSキー永久保持
 *   - MAP  : verify_yt__acc*                       … 同上(map union)。LSキー永久保持
 *   - CACHE: sheet_hist_raw__acc*                  … IDB専属。初回移行後にLSキー削除(quota解放)。喪失してもGAS再取得可
 *   - その他: read/write に来たら LS 素通し(パススルー)＝汎用キーでも壊れない
 *
 * 【データ形式】
 *   IDB: キー `hist:<lsキー名>` / 値 = {v:1, rev:<Date.now()>, items:[...]}(MAPは map:{...})
 *   LS : 現行のまま生配列/生オブジェクトJSON(互換)。加えて版数台帳 `go5_hist_revs` = {"<lsキー>":rev} を1キー。
 *
 * 使い方：ブラウザでは window.Go5Hist、Node(テスト)では module.exports。
 */
(function (root) {
  "use strict";

  var hasLS = (function () { try { return typeof localStorage !== "undefined"; } catch (e) { return false; } })();
  function lsGetRaw(k) { try { return hasLS ? localStorage.getItem(k) : null; } catch (e) { return null; } }
  function lsSetRaw(k, v) { try { if (hasLS) { localStorage.setItem(k, v); return true; } } catch (e) {} return false; }
  function lsDel(k) { try { if (hasLS) localStorage.removeItem(k); } catch (e) {} }

  var REVS_KEY = "go5_hist_revs";
  var ACCTS = ["acc1", "acc2"];
  var BASES = ["short_hist", "verify_manual", "verify_yt", "sheet_hist_raw"];

  // ── キー分類 ─────────────────────────────────────────────────────────
  function classify(k) {
    k = String(k);
    if (/^(short_hist|verify_manual)__acc[0-9]+$/.test(k)) return "array";
    if (/^verify_yt__acc[0-9]+$/.test(k)) return "map";
    if (/^sheet_hist_raw__acc[0-9]+$/.test(k)) return "cache";
    return null; // 未登録=パススルー
  }
  function isRegistered(k) { return classify(k) !== null; }
  function isMapKey(k) { return classify(k) === "map"; }
  function isCacheKey(k) { return classify(k) === "cache"; }
  // 減少罠の監視対象=消失が報告されているキーだけ(他キーの正常削除に反応しない)。
  function watched_(k) { return /^(short_hist__|verify_manual__)/.test(String(k)); }

  var REG = [];
  BASES.forEach(function (b) { ACCTS.forEach(function (a) { REG.push(b + "__" + a); }); });

  // ── 状態 ─────────────────────────────────────────────────────────────
  var _mem = {};      // lsキー -> 配列/マップ(正本・ハイドレート後有効)
  var _state = {};    // lsキー -> 'pre'|'hydrated'|'degraded'
  var _writeQ = {};   // lsキー -> {value, rev, isMap, waiters:[resolve...]}(IDB書きコアレス待ち行列)
  var _idbBusy = {};  // lsキー -> IDB set 実行中(直列化)
  var _revs = {};     // go5_hist_revs のメモリ像
  var _hydFails = {}; // 再ハイドレートのバックオフ回数
  var _rehydTimer = {}; // 再ハイドレートの予約タイマ
  REG.forEach(function (k) { _state[k] = "pre"; });

  // ── 小道具 ───────────────────────────────────────────────────────────
  function deepClone(v) { try { return JSON.parse(JSON.stringify(v == null ? (Array.isArray(v) ? [] : {}) : v)); } catch (e) { return Array.isArray(v) ? [] : {}; } }
  function sameJson(a, b) { try { return JSON.stringify(a) === JSON.stringify(b); } catch (e) { return false; } }
  function tsOf_(it) { return Number((it && it.ts) || 0) || 0; }
  function Idb() { return root && root.Go5Idb; }
  function idbUsable() {
    var d = Idb();
    return !!(d && typeof d.available === "function" && d.available() && typeof d.set === "function" && typeof d.getResult === "function");
  }
  // 履歴アイテムの同一性キー。正本は HistMerge.historyItemKey。(Node/未ロード時は同等のフォールバック)
  function itemKeyOf(it) {
    if (!it) return "";
    var HM = root && root.HistMerge;
    if (HM && typeof HM.historyItemKey === "function") { try { return HM.historyItemKey(it) || ""; } catch (e) {} }
    if (it.manual && it.id) return String(it.id);
    if (it.postUri) return "u:" + String(it.postUri);
    if (it.videoId) return "v:" + String(it.videoId);
    if (it.ytUrl || it.youtubeUrl) return "y:" + String(it.ytUrl || it.youtubeUrl);
    if (it.shortUrl) return "s:" + String(it.shortUrl);
    return it.id ? String(it.id) : "";
  }

  // ── union(非破壊・冪等) ──────────────────────────────────────────────
  //   base の順序を維持し、other にしか無い行だけを ts 降順位置へ挿入する。少ない方に消えない。
  function insertByTs_(arr, item) {
    var ts = tsOf_(item);
    for (var i = 0; i < arr.length; i++) { if (tsOf_(arr[i]) < ts) { arr.splice(i, 0, item); return; } }
    arr.push(item);
  }
  function unionArrays(baseArr, otherArr) {
    var out = Array.isArray(baseArr) ? baseArr.slice() : [];
    var others = Array.isArray(otherArr) ? otherArr : [];
    var seen = {};
    out.forEach(function (it) { var kk = itemKeyOf(it); if (kk) seen[kk] = 1; });
    others.forEach(function (it) {
      var kk = itemKeyOf(it);
      if (!kk) return;               // 実データは必ずキーを持つ。キー無しは冪等維持のため取り込まない
      if (!seen[kk]) { seen[kk] = 1; insertByTs_(out, it); }
    });
    return out;
  }
  // base が衝突キーの勝者。base の値を優先し、other にしか無いキーだけ足す。
  function unionMaps(baseMap, otherMap) {
    var out = {};
    Object.keys(baseMap || {}).forEach(function (kk) { out[kk] = baseMap[kk]; });
    Object.keys(otherMap || {}).forEach(function (kk) { if (!Object.prototype.hasOwnProperty.call(out, kk)) out[kk] = otherMap[kk]; });
    return out;
  }

  // ── 版数台帳 ─────────────────────────────────────────────────────────
  function loadRevs_() { try { _revs = JSON.parse(lsGetRaw(REVS_KEY) || "{}") || {}; } catch (e) { _revs = {}; } }
  function persistRevs_() { try { lsSetRaw(REVS_KEY, JSON.stringify(_revs)); } catch (e) {} }

  // ── LS の生読み(ハイドレート用)：空/不在/破損を区別する ───────────────
  function backupBrokenLs_(k, raw) {
    var bak = k + "__broken_bak";
    if (lsGetRaw(bak) == null) { lsSetRaw(bak, raw); } // 初回のみ生退避(以後の上書きで自己修復)
  }
  function readLsForHydrate_(k) {
    var isMap = isMapKey(k), empty = isMap ? {} : [];
    var raw = lsGetRaw(k);
    if (raw == null || raw === "") return { value: empty };
    var v = null, broken = false;
    try { v = JSON.parse(raw); } catch (e) { broken = true; }
    if (!broken) {
      if (isMap) { if (v && typeof v === "object" && !Array.isArray(v)) return { value: v }; broken = true; }
      else { if (Array.isArray(v)) return { value: v }; broken = true; }
    }
    // 生文字列が非空なのに JSON/型が壊れている＝初回のみ __broken_bak へ生退避し、以後は空扱い(自己修復)。
    backupBrokenLs_(k, raw);
    return { value: isMap ? {} : [], broken: true };
  }

  // ── IDB 書き込みキュー(コアレス＋ハイドレート完了まで直列化) ───────────
  function enqueueIdb(k, value, rev, isMap) {
    if (!idbUsable()) return Promise.resolve(false);
    return new Promise(function (resolve) {
      var q = _writeQ[k];
      if (q) { q.value = value; q.rev = rev; q.isMap = isMap; q.waiters.push(resolve); }
      else { _writeQ[k] = { value: value, rev: rev, isMap: isMap, waiters: [resolve] }; }
      flushIdb_(k);
    });
  }
  function flushIdb_(k) {
    var q = _writeQ[k];
    if (!q) return;
    if (_idbBusy[k]) return;              // set 実行中=完了後に再度ドレイン
    if (_state[k] === "pre") return;      // ハイドレート未了=丸ごと書きで IDB専用行を潰さないよう待つ
    if (!idbUsable()) { delete _writeQ[k]; q.waiters.forEach(function (r) { r(false); }); return; }
    delete _writeQ[k];
    _idbBusy[k] = true;
    var payload = q.isMap ? { v: 1, rev: q.rev, map: q.value } : { v: 1, rev: q.rev, items: q.value };
    Idb().set("hist:" + k, payload).then(function () {
      q.waiters.forEach(function (r) { r(true); });
      if (isCacheKey(k)) lsDel(k); // CACHE は IDB set の resolve確認後に LS を削除(quota解放)
    }, function () {
      q.waiters.forEach(function (r) { r(false); });
    }).then(function () {
      _idbBusy[k] = false;
      flushIdb_(k);                       // 待ち中に来た書きをドレイン
    });
  }

  // ── ハイドレート(キーごと・冪等) ─────────────────────────────────────
  function degradeKey_(k) {
    _state[k] = "degraded"; // IDB不可用=LSだけで動く。read は LS を見る・write は LS のみ
    flushIdb_(k);           // キューに積まれていた分を false 解決(IDB不可用)
  }
  function scheduleRehydrate_(k) {
    if (_state[k] === "hydrated") return;
    _hydFails[k] = (_hydFails[k] || 0) + 1;
    if (_rehydTimer[k]) return;
    var delay = Math.min(15000, 1000 * Math.pow(2, Math.min(4, Math.max(0, _hydFails[k] - 1))));
    try {
      _rehydTimer[k] = setTimeout(function () { _rehydTimer[k] = null; hydrateKey_(k); }, delay);
    } catch (e) {}
  }
  function hydrateKey_(k) {
    if (_state[k] === "hydrated") return;
    if (!idbUsable()) { degradeKey_(k); return; }
    var d = Idb();
    d.getResult("hist:" + k).then(function (r) {
      // ★読み失敗(ok:false)と不在(value:null)を厳密に区別する。読み失敗を「不在」と解釈して
      //   LSだけでIDBを上書きしない。pre のまま指数バックオフ＋go5-idb-recovered で再起動する。
      if (!r || r.ok === false) { scheduleRehydrate_(k); return; }
      commitHydrate_(k, r.value);
    }, function () { scheduleRehydrate_(k); });
  }
  function commitHydrate_(k, idbVal) {
    if (_state[k] === "hydrated") return;
    var isMap = isMapKey(k);
    var ls = readLsForHydrate_(k);
    var revLs = Number(_revs[k]) || 0;
    var mem, changed;
    if (idbVal == null) {
      // 初回移行：IDB不在→ mem=LS。IDBへ書き戻す。
      mem = isMap ? (ls.value || {}) : (ls.value || []);
      changed = true;
    } else {
      var revIdb = Number(idbVal.rev) || 0;
      if (isMap) {
        var idbMap = idbVal.map || {};
        mem = (revIdb >= revLs) ? unionMaps(idbMap, ls.value) : unionMaps(ls.value, idbMap);
        changed = !sameJson(mem, idbMap);
      } else {
        var idbItems = idbVal.items || [];
        mem = (revIdb >= revLs) ? unionArrays(idbItems, ls.value) : unionArrays(ls.value, idbItems);
        changed = !sameJson(mem, idbItems);
      }
      // 壊れたLSを退避した端末は、IDB正本を書き戻す時に LS も治す。
      if (ls.broken) changed = changed || true;
    }
    // 200件上限(ARRAY のみ)。先頭が最新・溢れは最古を落とす(INC-131)。
    if (!isMap && classify(k) === "array" && Array.isArray(mem)) mem = mem.slice(0, 200);

    _mem[k] = mem;
    _state[k] = "hydrated";

    var rev;
    if (changed) {
      rev = Date.now();
      _revs[k] = rev; persistRevs_();
      // LS 後追いコピー(CACHE 以外は永久保持)。
      if (!isCacheKey(k)) lsSetRaw(k, JSON.stringify(mem));
      // IDB へ書き戻し(直接set)＝この間はキュー流しを止め、user書きに潰されない/潰さない。
      if (idbUsable()) {
        _idbBusy[k] = true;
        var payload = isMap ? { v: 1, rev: rev, map: mem } : { v: 1, rev: rev, items: mem };
        Idb().set("hist:" + k, payload).then(function () {
          if (isCacheKey(k)) lsDel(k);
        }, function () {}).then(function () {
          _idbBusy[k] = false;
          flushIdb_(k);
        });
      } else {
        flushIdb_(k);
      }
    } else {
      rev = Number(idbVal.rev) || 0;
      _revs[k] = rev; persistRevs_();
      if (!isCacheKey(k)) lsSetRaw(k, JSON.stringify(mem));
      else lsDel(k); // IDB既に正本を保持=CACHE の LS コピーは削除してよい(quota解放)
      flushIdb_(k);
    }
    dispatchHydrated_(k);
  }
  function dispatchHydrated_(k) {
    try {
      if (root && root.document && typeof root.document.dispatchEvent === "function" && typeof root.CustomEvent === "function") {
        root.document.dispatchEvent(new root.CustomEvent("go5-hist-hydrated", { detail: { key: k } }));
      }
    } catch (e) {}
  }

  // ── 公開API：read(同期リーダ) ────────────────────────────────────────
  function read(k) {
    k = String(k);
    var isMap = isMapKey(k);
    if (isRegistered(k) && _state[k] === "hydrated") return deepClone(_mem[k]);
    // pre / degraded / 未登録 → 現行どおり LS を JSON.parse(初回描画が空白にならない)。
    var raw = lsGetRaw(k);
    if (raw == null || raw === "") return isMap ? {} : [];
    try {
      var v = JSON.parse(raw);
      if (isMap) return (v && typeof v === "object" && !Array.isArray(v)) ? v : {};
      return Array.isArray(v) ? v : [];
    } catch (e) { return isMap ? {} : []; }
  }

  // ── 公開API：write(二重化) → receipt {lsOk:boolean, idb:Promise<boolean>} ─
  function write(k, value) {
    k = String(k);
    var cls = classify(k);
    var isMap = (cls === "map");
    var registered = (cls !== null);

    // 1. 減少罠：件数が減るなら証拠採取(watched な ARRAY のみ)。証拠採取本体は yt-clicks の Go5HistLoss。
    try {
      if (!isMap && watched_(k) && Array.isArray(value)) {
        var before = read(k);
        if (before && before.length && value.length < before.length) {
          if (root.Go5HistLoss && typeof root.Go5HistLoss.record === "function") root.Go5HistLoss.record(k, before, value);
        }
      }
    } catch (e) {}

    // 2. 200件上限(ARRAY のみ・INC-131)。MAP/CACHE は切らない。
    var stored = value;
    if (cls === "array" && Array.isArray(value)) stored = value.slice(0, 200);

    // 3. ミラー更新(hydrated時のみ・deepClone で参照汚染を防ぐ)。
    if (registered && _state[k] === "hydrated") _mem[k] = deepClone(stored);

    // 4. LS 後追いコピー(CACHE 以外)。CACHE は IDB専属だが、IDB不可用の時だけ LS へ退避(再取得可)。
    var lsOk = false;
    if (cls === "cache") {
      if (!idbUsable()) lsOk = lsSetRaw(k, JSON.stringify(stored));
    } else {
      lsOk = lsSetRaw(k, JSON.stringify(stored));
    }

    // 版数台帳更新(登録キーのみ)。
    var rev = Date.now();
    if (registered) { _revs[k] = rev; persistRevs_(); }

    // 5+6. IDB へコアレス投入。receipt.idb はこのキューの決着 Promise(不可用/未登録は即 false)。
    var idbP = registered ? enqueueIdb(k, stored, rev, isMap) : Promise.resolve(false);
    return { lsOk: lsOk, idb: idbP };
  }

  // ── 起動ハイドレート＋マルチタブ/回復購読 ────────────────────────────
  function hydrateAll() { REG.forEach(function (k) { hydrateKey_(k); }); }

  loadRevs_();
  hydrateAll();

  try {
    if (root && typeof root.addEventListener === "function") {
      // 他タブの書き(全書き手が LS 後追いコピーを書くので必ず発火)を hydrated なら mem へ採用。
      root.addEventListener("storage", function (ev) {
        try {
          var k = ev && ev.key;
          if (!k || !isRegistered(k) || _state[k] !== "hydrated") return;
          if (isCacheKey(k)) return; // CACHE は LS を持たない
          var nv = ev.newValue;
          if (nv == null || nv === "") return;
          var parsed = JSON.parse(nv);
          if (isMapKey(k)) { if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) _mem[k] = parsed; }
          else if (Array.isArray(parsed)) { _mem[k] = classify(k) === "array" ? parsed.slice(0, 200) : parsed; }
        } catch (e) {}
      });
    }
    if (root && root.document && typeof root.document.addEventListener === "function") {
      // IDB が無言死から回復した合図で、未ハイドレートキーを今すぐ読み直す(candidates.js と同型)。
      root.document.addEventListener("go5-idb-recovered", function () {
        REG.forEach(function (k) {
          if (_state[k] === "hydrated") return;
          _hydFails[k] = 0;
          if (_rehydTimer[k]) { try { clearTimeout(_rehydTimer[k]); } catch (e) {} _rehydTimer[k] = null; }
          hydrateKey_(k);
        });
      });
    }
  } catch (e) {}

  var API = {
    read: read,
    write: write,
    available: function () { return idbUsable(); },
    classify: classify,
    keys: function () { return REG.slice(); },
    state: function (k) { return _state[String(k)]; }
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.Go5Hist = API;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
