/**
 * core/sync.js — 全端末クラウド同期エンジン。(Go5Sync)sync-worker と対で動く。
 *
 * 同期対象：
 *   ・localStorage の「設定」(Go5Keys.syncAllowed) と「候補テキスト」。(cand_items ・ cand_tabs ・ cand_hidden__ 系)
 *   ・「下書き(ドラフト)」の一覧と投稿編集。(go5_stock_meta ＝ id 単位 union / go5_stock_del ＝ 削除の墓標 /
 *     go5_draft_post_* ＝ per-id LWW)全端末でドラフトを共有する。(Chami依頼2026-07-31)
 *     ★動画本体(stock_v_)・サムネ/画像(stock_t_/stock_img_)は重いので①-Aでは同期しない。(②で運び方を決める)
 *   ・「カレンダー予定」(sch_state_v1)を日付/枠/アカウント単位で統合し、公開済みの逆戻りを防いで同期。
 *   ・IndexedDB の候補素材。(ref:/bsky:/post: ＝ 参照画像・コメント・メモ)画像は R2 に content-hash で保存し、
 *     状態には {__img:<hash>} だけ入れる。(blobを小さく保つ)
 *   ・「鍵(アプリPW等)」は passphrase で AES-GCM 暗号化した1件(__sec)としてだけ同期。(平文はクラウドに出さない)
 *
 * 同期方式：各キー last-write-wins。(per-key タイムスタンプ・スナップショット差分で変更/削除を検出)
 *   push は baseVersion 付き。衝突(他端末先行)なら再pull→マージ→再push。変更が無ければ push しない。
 *   自動＝起動時pull＋一定間隔＋タブ非表示化(離脱)時。手動ボタンもあり。
 *
 * 設定(この端末だけ・同期しない・送らない)：localStorage sync2_url / sync2_token / sync2_pass。(パスフレーズ)
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
    if (/^cand_del(__|$)/.test(k)) return true;          // 削除の墓標(候補復活の恒久対策・INC 2026-07-15)
    if (/^cand_hidden__/.test(k)) return true;           // 非表示リスト
    if (k === "cand_hide_posted") return true;
    if (/^go5_stock_meta$/.test(k)) return true;         // ドラフト一覧(id単位union・Chami依頼2026-07-31)
    if (/^go5_stock_archive$/.test(k)) return true;      // 作成履歴(投稿完了ぶん・id単位union・墓標なし・Chami依頼2026-08-03)
    if (/^go5_stock_del$/.test(k)) return true;          // ドラフト削除の墓標(端末をまたぐ削除の伝播)
    if (/^go5_draft_post_/.test(k)) return true;         // 下書きの投稿編集(per-id・LWW)
    if (Keys && Keys.syncAllowed(k)) return true;        // 本物の設定(レイアウト/本文/説明欄/af_id 等)
    return false;
  }
  // ★stock:imgs:<id> ＝ ドラフトのサムネ/プレビュー/元画像を dataURL でまとめた同期用ミラー(①-B・2026-07-31)。
  //   重い動画本体(stock_v_)は載せない=積み上がっても同期は軽いまま(実体はR2にhashで、台帳には参照だけ)。
  function isSyncIdbKey(k) { return /^(ref:|bsky:|post:|stock:imgs:)/.test(String(k)); }

  // ── 暗号(WebCrypto AES-GCM / PBKDF2)──
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
    return Promise.resolve().then(function () {          // JSON.parse も含め全て reject 経路へ(同期throwで同期全体を止めない)
      var rec = JSON.parse(recStr);
      return deriveKey(pass, unb64(rec.salt)).then(function (key) { return subtle.decrypt({ name: "AES-GCM", iv: unb64(rec.iv) }, key, unb64(rec.ct)); })
        .then(function (buf) { return JSON.parse(new TextDecoder().decode(buf)); });
    });
  }

  // ── 通信 ──
  var API_RETRY_DELAYS = [0, 500, 1200];
  function api(path, opts) {
    var c = cfg(), src = opts || {};
    var init = Object.assign({}, src, {
      mode: "cors",
      cache: "no-store",
      headers: Object.assign({ "X-Sync-Token": c.token }, src.headers || {})
    });
    function attempt(n) {
      return root.fetch(c.url + path, init).catch(function (cause) {
        if (n + 1 < API_RETRY_DELAYS.length) {
          return new Promise(function (resolve) { root.setTimeout(resolve, API_RETRY_DELAYS[n + 1]); }).then(function () { return attempt(n + 1); });
        }
        var e = new Error("同期Workerへ接続できません(3回試行)。公開URL・通信環境を確認してください");
        e.cause = cause;
        throw e;
      });
    }
    return attempt(0);
  }
  function apiErrorMessage(r, body) {
    var code = body && body.error;
    if (code === "bad_token") return "同期トークンが一致しません";
    if (code === "rate_limited") return "同期の一日上限に達しました。時間を置いて再試行してください";
    if (code === "kv_unset") return "同期Workerの保存先が未設定です";
    if (code === "too_large") return "同期データが上限を超えています";
    return "同期Workerでエラーが発生しました(" + ((r && r.status) || code || "unknown") + ")";
  }
  function readApiJson(r, allowConflict) {
    return r.json().catch(function () { return null; }).then(function (body) {
      if (allowConflict && body && body.conflict) return body;
      if (!r.ok || !body || body.ok === false) throw new Error(apiErrorMessage(r, body));
      return body;
    });
  }
  function pullState() { return api("/api/pull").then(function (r) { return readApiJson(r, false); }); }
  function pushState(map, baseVersion) {
    var body = { blob: JSON.stringify(map), updatedAt: new Date().toISOString(), device: deviceName(), baseVersion: baseVersion || 0 };
    return api("/api/push", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(function (r) { return readApiJson(r, true); });
  }

  // ── 画像(R2)：dataURL⇄content-hash ──
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

  // hash化された値 → R2 から dataURL を復元。失敗画像は空文字。(表示されないだけ)
  function downloadImagesIn(val) {
    var refs = []; (function walk(v) { if (isImgRef(v)) { refs.push(v.__img); return; } if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v === "object") for (var k in v) if (has(v, k)) walk(v[k]); })(val);
    if (!refs.length) return Promise.resolve({ val: val, failed: 0 });
    var c = cfg(), byHash = {}, uniq = {}; refs.forEach(function (h) { uniq[h] = 1; });
    return Promise.all(Object.keys(uniq).map(function (h) {
      return root.fetch(c.url + "/img/" + h).then(function (r) { return r.ok ? r.text() : ""; }).then(function (t) { byHash[h] = /^data:/.test(t) ? t : ""; }).catch(function () { byHash[h] = ""; });
    })).then(function () {
      var failed = 0;
      var out = mapVal(val, isImgRef, function (ref) { var v = byHash[ref.__img]; if (!v) failed++; return v || ""; });
      return { val: out, failed: failed };
    });
  }

  // ★取得失敗の残骸(空スロット)判定：画像レコードの画像欄が "" になっているもの。
  //   refImgSave/usedImgSave は保存前に imgs を filter(Boolean) する＝正規の保存では画像欄に "" は入らない。
  //   よって画像欄(img/imgs要素/th/prev/src)に "" があるのは「R2から本体を取れず空で書かれた残骸」だけと断定できる。
  //   (ref のテキストのみ保存＝imgs:[] は空要素を持たないので誤検知しない。prev は used では枚数=数値なので "" にならない)
  //   th/src/prev(stock:imgs のデータURL欄)の "" は残骸。imgs 配列内の "" も残骸。
  //   scalar img は imgs[0] のミラー＝imgs があればそちらが正なので、img:"" は「imgs 欄が無い」時(bsky)だけ残骸扱い。
  var IMG_FIELDS = { th: 1, src: 1, prev: 1 };
  function hasEmptyImgSlot(v) {
    if (!v || typeof v !== "object") return false;
    var bad = false;
    (function walk(x) {
      if (bad || !x || typeof x !== "object") return;
      if (Array.isArray(x)) { for (var i = 0; i < x.length; i++) { if (x[i] === "") { bad = true; return; } walk(x[i]); } return; }
      for (var k in x) {
        if (!has(x, k)) continue;
        var val = x[k];
        if (IMG_FIELDS[k] && val === "") { bad = true; return; }
        if (k === "img" && val === "" && !has(x, "imgs")) { bad = true; return; } // bsky系(imgsを持たない)のみ
        if (k === "imgs" && Array.isArray(val)) { for (var j = 0; j < val.length; j++) { if (val[j] === "") { bad = true; return; } } if (bad) return; }
        if (val && typeof val === "object") walk(val);
      }
    })(v);
    return bad;
  }

  // 画像レコードのマージ判定(純関数=テスト可能)。片側だけが「空スロット残骸」なら実体側を返す。
  // 両方実体/両方残骸/dあり/欠落は null=通常のLWWに委ねる。v=638 の自己回復ルールをここに固定。
  function preferImgRecord_(a, b) {
    if (!(a && b) || a.d || b.d) return null;
    var aBad = hasEmptyImgSlot(a.v), bBad = hasEmptyImgSlot(b.v);
    if (aBad && !bBad) return b;   // ローカルが残骸→リモート(実体)を採用し取り直す
    if (bBad && !aBad) return a;   // リモートが残骸→ローカル(実体)を守る
    return null;
  }

  // ── ローカル状態 ──
  function loadSnap() { try { return JSON.parse(LS.getItem("sync2_snap") || "{}") || {}; } catch (e) { return {}; } }
  function saveSnap(s) { try { LS.setItem("sync2_snap", JSON.stringify(s)); } catch (e) {} }
  function loadTs() { try { return JSON.parse(LS.getItem("sync2_ts") || "{}") || {}; } catch (e) { return {}; } }
  function saveTs(t) { try { LS.setItem("sync2_ts", JSON.stringify(t)); } catch (e) {} }
  function getVer() { try { return parseInt(LS.getItem("sync2_ver") || "0", 10) || 0; } catch (e) { return 0; } }
  function setVer(v) { try { LS.setItem("sync2_ver", String(v)); } catch (e) {} }
  // R2に存在が確定した画像ハッシュの記憶(端末ローカル・sync2_*なので同期対象外)。
  //   毎サイクル /api/img/has を投げ直さないためのキャッシュ。24hで期限切れ＝R2から実体が
  //   消えた場合(既知症状②)も最長1日で再検出して再アップロードできる。
  var IMGOK_TTL_MS = 24 * 3600 * 1000;
  function loadImgOk() { try { return JSON.parse(LS.getItem("sync2_imgok") || "{}") || {}; } catch (e) { return {}; } }
  function saveImgOk(o) {
    try {
      var ks = Object.keys(o);
      if (ks.length > 4000) { var t = {}; ks.slice(-3000).forEach(function (h) { t[h] = o[h]; }); o = t; } // 肥大防止
      LS.setItem("sync2_imgok", JSON.stringify(o));
    } catch (e) {}
  }

  function gatherLs() { var out = {}; try { for (var i = 0; i < LS.length; i++) { var k = LS.key(i); if (isSyncLsKey(k)) out[k] = LS.getItem(k); } } catch (e) {} return out; }

  // 鍵(秘密)＝キー単位で暗号化して同期。sync2_*(同期自身の設定＝端末ローカル)は絶対に対象外。
  var SEC_PREFIX = "sec:";
  function syncableSecret(k) { k = String(k); return !!(Keys && Keys.isSecret(k)) && !/^sync2_/.test(k); }
  // 現在の秘密を {SEC_PREFIX+key: 暗号文} に。平文が前回と同じなら暗号文を再利用。(毎回変わらないように)
  //   pass 未設定なら skip=true。(この端末では鍵を同期しない＝雲側の暗号鍵は触らない)
  function buildSecEntries(snap) {
    var c = cfg(), plain = {};
    // ★空の秘密は同期対象にしない。(空で上書き/削除誤爆を防ぐ)値がある鍵だけ。
    try { for (var i = 0; i < LS.length; i++) { var k = LS.key(i); if (syncableSecret(k)) { var v = LS.getItem(k); if (v) plain[k] = v; } } } catch (e) {}
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
  // 進捗(Chami依頼2026-07-14「同期中…が長い・進んでるか分からない」): 画像の送受信を件数で見せる。
  var _prog = { phase: "", done: 0, total: 0 };
  function setProg(phase, done, total) { _prog = { phase: phase, done: done, total: total }; }
  // 同期完了時に発火＝各タブが localStorage の新しい値を入力欄へ読み直せる(反映されない不安の解消)。
  //   pulledImg=雲から実際に取り込んだ画像レコード(ref:/bsky:/post:)の件数。候補/ドラフト画面が
  //   「後から届いた画像」で再描画すべきかを判定するために添える。0の同期(=タブ復帰の空振り等)では
  //   再描画させない=無条件反応による画面の白フラッシュを避ける(competitor.js/candidates.js が参照)。
  function fireSynced(pulled, pulledImg) { try { if (root.document) root.document.dispatchEvent(new root.CustomEvent("go5-synced", { detail: { pulled: pulled, pulledImg: pulledImg || 0 } })); } catch (e) {} }
  function status() { return { configured: configured(), busy: _busy, version: getVer(), lastError: _lastErr, lastAt: _lastAt, device: deviceName(), prog: _prog }; }

  // per-key マージ。(t 大きい方を採用)
  function mergeMaps(local, rem) {
    var out = {}, seen = {};
    Object.keys(local).forEach(function (k) { seen[k] = 1; }); Object.keys(rem).forEach(function (k) { seen[k] = 1; });
    Object.keys(seen).forEach(function (k) { var a = local[k], b = rem[k]; out[k] = (a && b) ? (((b.t || 0) > (a.t || 0)) ? b : a) : (a || b); });
    return out;
  }
  function stripT(map) { var o = {}; Object.keys(map).forEach(function (k) { var e = map[k]; o[k] = e.d ? { d: 1 } : { v: e.v }; }); return o; } // 比較用(t除去)

  // 候補リスト(cand_items / cand_items__*)は配列を1キーに持つため、whole-key LWW だと初回に別端末の
  //   候補を丸ごと消し得る。cid で union し、重複cidは newer 側を採用＝「集めた候補を失わない」。
  function isCandArrayKey(k) { return /^cand_items(__|$)/.test(String(k)); }
  // 下書き(ドラフト)一覧＝1キーに配列を持つ。候補と同じく id 単位 union で「端末をまたいだ下書きを失わない」。
  function isStockArrayKey(k) { return /^go5_stock_meta$/.test(String(k)); }
  // 作成履歴(投稿完了ぶん)＝1キーに配列。id 単位 union で端末をまたいで完了作品を失わない。
  //   ★墓標(go5_stock_del)は適用しない=完了作品は「meta から外れ archive に居る」状態が正しいので、
  //     墓標で archive からも消すと2台目で完了作品が丸ごと消える(Chami依頼2026-08-03)。復活許容はテンプレ帳と同型。
  function isStockArchiveKey(k) { return /^go5_stock_archive$/.test(String(k)); }
  function isStockDelKey(k) { return /^go5_stock_del$/.test(String(k)); }
  // 📝テンプレ帳(本文定型文・アカウント別)＝1キーに配列を持つ。候補/ドラフトと同じく union で
  //   「端末をまたいだ・空の端末で上書きした時に保存済みテンプレを失わない」(Chami依頼2026-08-02
  //   「保存した内容を消さずどの端末でも共有」)。id が無く name が実質の一意キーなので name で union。
  //   ★削除の墓標(bsky_tpl_del__acc)を持つ=🗑削除を全端末へ伝播(Chami依頼2026-08-03「前のやつ消して」)。
  //     墓標は name→削除ts。削除ts が保存時刻(at)以上なら消える／at が新しい=削除後に再保存なら残る
  //     ＝「消さずに共有」(2026-08-02)と「消したら全端末で消える」(2026-08-03)を時刻順で両立。
  function isTplBookKey(k) { return /^bsky_tpl_book(__|$)/.test(String(k)); }
  function isTplDelKey(k) { return /^bsky_tpl_del(__|$)/.test(String(k)); }
  function tplDelKeyOf(bookKey) { return String(bookKey).replace(/^bsky_tpl_book/, "bsky_tpl_del"); } // bsky_tpl_book__acc→bsky_tpl_del__acc
  // 🔥セール案内URL(名前付きリスト・アカウント別)＝1キーに配列。テンプレ帳と同型で id 単位 union＋削除墓標。
  //   whole-key LWW だと別端末で追加した分を丸ごと上書きして「たまに消える」(Chami依頼2026-08-03)。
  //   id で union して消さず、削除は bsky_discount_del__acc(id→削除ts)で全端末へ伝播。at>削除ts で再追加は残る。
  function isDiscUrlsKey(k) { return /^bsky_discount_urls(__|$)/.test(String(k)); }
  function isDiscDelKey(k) { return /^bsky_discount_del(__|$)/.test(String(k)); }
  function discDelKeyOf(urlsKey) { return String(urlsKey).replace(/^bsky_discount_urls/, "bsky_discount_del"); } // bsky_discount_urls__acc→bsky_discount_del__acc
  // 候補の投稿済み手動宣言(cand_posted_on / cand_posted_off)＝1キーに {acc:{cid:ts}} のネスト辞書を持つ。
  //   ★宣言は「作品ごと」に積み上がる=whole-key LWW だと別端末で立てた宣言を丸ごと上書きして消す。
  //   → acc・cid 単位で union し、同一cidは ts(宣言時刻)の大きい方を採る=「どの端末で立てた宣言も失わない」
  //     ＝「どこからログインしても同じ投稿済み判定」(Chami核2026-08-04)。※解除(delete)はtombstoneを持たないため
  //     別端末に宣言が残っていれば次回同期で復活しうる(宣言の消失より復活の方が実害が小さい&稀=許容)。
  function isPostedMapKey(k) { return /^cand_posted_(on|off)$/.test(String(k)); }
  function mergePostedMap(olderStr, newerStr) {
    try {
      var older = JSON.parse(olderStr || "{}"), newer = JSON.parse(newerStr || "{}");
      if (!older || typeof older !== "object" || Array.isArray(older)) older = {};
      if (!newer || typeof newer !== "object" || Array.isArray(newer)) newer = {};
      var out = {}, accs = {};
      Object.keys(older).forEach(function (a) { accs[a] = 1; }); Object.keys(newer).forEach(function (a) { accs[a] = 1; });
      Object.keys(accs).forEach(function (a) {
        var oa = (older[a] && typeof older[a] === "object") ? older[a] : {};
        var na = (newer[a] && typeof newer[a] === "object") ? newer[a] : {};
        var m = {}, cids = {};
        Object.keys(oa).forEach(function (c) { cids[c] = 1; }); Object.keys(na).forEach(function (c) { cids[c] = 1; });
        Object.keys(cids).forEach(function (c) {
          var ov = Number(oa[c]) || 0, nv = Number(na[c]) || 0;
          var v = Math.max(ov, nv); if (v > 0) m[c] = v;   // 大きい方のts=より新しい宣言を採用
        });
        if (Object.keys(m).length) out[a] = m;
      });
      return JSON.stringify(out);
    } catch (e) { return null; }
  }
  // 配列キーの id フィールド名。(候補=cid / ドラフト=id / テンプレ帳=name / セール案内=id)union/墓標の両方で使う。
  function arrIdField_(k) { return isCandArrayKey(k) ? "cid" : ((isStockArrayKey(k) || isStockArchiveKey(k) || isDiscUrlsKey(k)) ? "id" : (isTplBookKey(k) ? "name" : null)); }
  // 空とみなす値。(undefined / null / 空文字)0・false は「意味のある更新」なので空ではない。
  function isEmptyVal_(v) { return v === undefined || v === null || v === ""; }
  // ★同一cidの2レコードをフィールド単位で統合する。newer を基本に採るが、newer 側で空(欠け)の
  //   フィールドは older の非空値で補う。＝価格・discountPctなどの実更新(0含む)は尊重しつつ、
  //   「url が欠けた側で丸ごと上書きして作品URLが消える」事故を根治する(Chami依頼2026-07-30)。
  //   旧実装は byCid[key]=it の丸ごと置換で、newer に url が無いと older の url を失っていた。
  function mergeCandItem_(older, newer) {
    if (!older || typeof older !== "object") return newer;
    if (!newer || typeof newer !== "object") return older;
    var out = {}, k;
    for (k in older) { if (Object.prototype.hasOwnProperty.call(older, k)) out[k] = older[k]; }
    for (k in newer) {
      if (!Object.prototype.hasOwnProperty.call(newer, k)) continue;
      if (!isEmptyVal_(newer[k])) out[k] = newer[k];               // newerに値がある→newer優先
      else if (isEmptyVal_(out[k])) out[k] = newer[k];             // 両方空なら形だけnewerに合わせる
      // newerが空でolderに値がある→olderを保持(=作品URL等を消さない)
    }
    return out;
  }
  // id フィールドで配列を union。(候補=cid / ドラフト=id)重複はフィールド単位で統合(newer優先・空で消さない)。
  function unionByField(olderStr, newerStr, idField) {
    idField = idField || "cid";
    try {
      var older = JSON.parse(olderStr || "[]"), newer = JSON.parse(newerStr || "[]");
      if (!Array.isArray(older) || !Array.isArray(newer)) return null;
      var byId = {}, order = [], anon = 0;
      function add(arr) { arr.forEach(function (it) {
        var idv = it ? it[idField] : null;
        var key = (idv != null) ? ("k:" + idv) : ("a:" + (anon++));
        if (!(key in byId)) { order.push(key); byId[key] = it; }
        else byId[key] = mergeCandItem_(byId[key], it); // 重複id＝フィールド単位で統合(newer優先・空で消さない)
      }); }
      add(older); add(newer); // 後入れ(newer)が重複idで優先・ただし欠けたフィールドはolderを保持
      return JSON.stringify(order.map(function (k) { return byId[k]; }));
    } catch (e) { return null; }
  }
  function unionCand(olderStr, newerStr) { return unionByField(olderStr, newerStr, "cid"); }

  // カレンダー予定は1キーに全日・全枠を持つ。whole-key LWWでは、スマホの公開済みと
  // PCの古い予約状態が互いを丸ごと消すため、日付/枠/アカウント単位で統合する。
  function isScheduleStateKey(k) { return String(k) === "sch_state_v1"; }
  var SCHEDULE_STATUS_RANK = { "未着手": 0, "制作済・未予約": 1, "予約登録済": 2, "公開済": 3, "取り下げ": 4 };
  var SCHEDULE_EXEC_FIELDS = ["status", "video_id", "url", "post_uri", "post_url", "short_url", "posted_at", "exec_updated_at"];
  function recordTime_(rec) {
    var n = Date.parse(rec && rec.updated_at || "");
    return isNaN(n) ? 0 : n;
  }
  // 予定専用: newer にプロパティがあれば null/空文字も「明示的に消した値」として採用する。
  function mergeScheduleRecord_(older, newer) {
    var out = {};
    older = (older && typeof older === "object" && !Array.isArray(older)) ? older : {};
    newer = (newer && typeof newer === "object" && !Array.isArray(newer)) ? newer : {};
    Object.keys(older).forEach(function (x) { out[x] = older[x]; });
    Object.keys(newer).forEach(function (x) { out[x] = newer[x]; });
    return out;
  }
  function orderedRecords_(a, b) {
    var ta = recordTime_(a), tb = recordTime_(b);
    return ta > tb ? [b || {}, a || {}] : [a || {}, b || {}];
  }
  function mergeScheduleExec_(older, newer) {
    older = (older && typeof older === "object") ? older : {};
    newer = (newer && typeof newer === "object") ? newer : {};
    var ro = Object.prototype.hasOwnProperty.call(SCHEDULE_STATUS_RANK, older.status) ? SCHEDULE_STATUS_RANK[older.status] : -1;
    var to = Date.parse(older.exec_updated_at || ""), tn = Date.parse(newer.exec_updated_at || "");
    to = isNaN(to) ? 0 : to; tn = isNaN(tn) ? 0 : tn;
    // 新実装の明示操作(取消・取り下げを含む)は、状態の順位より更新時刻を優先する。
    if (to !== tn && (to || tn)) {
      return to > tn ? mergeScheduleRecord_(newer, older) : mergeScheduleRecord_(older, newer);
    }
    var rn = Object.prototype.hasOwnProperty.call(SCHEDULE_STATUS_RANK, newer.status) ? SCHEDULE_STATUS_RANK[newer.status] : -1;
    // 公開済み等の進んだ状態を、別端末の古い予約状態へ戻さない。
    // 取り下げは明示的な終端状態なので公開済みより優先する。
    if (ro > rn) return mergeScheduleRecord_(newer, older);
    return mergeScheduleRecord_(older, newer);
  }
  function scheduleExecMap_(slot) {
    if (slot && slot.exec && typeof slot.exec === "object") return slot.exec;
    var acc1 = {};
    SCHEDULE_EXEC_FIELDS.forEach(function (f) {
      if (slot && slot[f] !== undefined) acc1[f] = slot[f];
    });
    if (!acc1.status) acc1.status = "未着手";
    return { acc1: acc1, acc2: { status: "未着手" } };
  }
  function mergeScheduleSlot_(a, b) {
    var ord = orderedRecords_(a, b), older = ord[0], newer = ord[1];
    var out = mergeScheduleRecord_(older, newer);
    var oe = scheduleExecMap_(older), ne = scheduleExecMap_(newer);
    out.exec = {};
    SCHEDULE_EXEC_FIELDS.forEach(function (f) { delete out[f]; });
    ["acc1", "acc2"].forEach(function (acc) { out.exec[acc] = mergeScheduleExec_(oe[acc], ne[acc]); });
    Object.keys(oe).concat(Object.keys(ne)).forEach(function (acc) {
      if (acc === "acc1" || acc === "acc2" || out.exec[acc]) return;
      out.exec[acc] = mergeScheduleExec_(oe[acc], ne[acc]);
    });
    return out;
  }
  function validScheduleState_(v) {
    return v && typeof v === "object" && !Array.isArray(v)
      && (!v.overrides || (typeof v.overrides === "object" && !Array.isArray(v.overrides)))
      && (!v.slotData || (typeof v.slotData === "object" && !Array.isArray(v.slotData)));
  }
  function parseScheduleState_(str) {
    if (typeof str !== "string") return null;
    try {
      var parsed = JSON.parse(str);
      return validScheduleState_(parsed) ? parsed : null;
    } catch (e) { return null; }
  }
  function normalizedScheduleState_(v) {
    return { overrides: v.overrides || {}, slotData: v.slotData || {} };
  }
  function mergeScheduleState(olderStr, newerStr) {
      var a = parseScheduleState_(olderStr), b = parseScheduleState_(newerStr);
      if (!a && !b) return null;
      if (!a) return JSON.stringify(normalizedScheduleState_(b));
      if (!b) return JSON.stringify(normalizedScheduleState_(a));
      var out = { overrides: {}, slotData: {} };
      var ao = a.overrides || {}, bo = b.overrides || {};
      Object.keys(ao).concat(Object.keys(bo)).forEach(function (date) {
        if (Object.prototype.hasOwnProperty.call(out.overrides, date)) return;
        if (ao[date] === undefined) out.overrides[date] = bo[date];
        else if (bo[date] === undefined) out.overrides[date] = ao[date];
        else {
          var ord = orderedRecords_(ao[date], bo[date]);
          out.overrides[date] = mergeScheduleRecord_(ord[0], ord[1]);
        }
      });
      var as = a.slotData || {}, bs = b.slotData || {};
      Object.keys(as).concat(Object.keys(bs)).forEach(function (id) {
        if (Object.prototype.hasOwnProperty.call(out.slotData, id)) return;
        if (as[id] === undefined) out.slotData[id] = bs[id];
        else if (bs[id] === undefined) out.slotData[id] = as[id];
        else out.slotData[id] = mergeScheduleSlot_(as[id], bs[id]);
      });
      return JSON.stringify(out);
  }

  // 削除の墓標(トゥームストーン)：{ cid: 削除ts } を1キーに持つ。端末をまたぐと LWW では
  //   別端末の削除を丸ごと失う(＝復活)ので、cid 単位で union し ts の大きい方を採る。
  function isCandDelKey(k) { return /^cand_del(__|$)/.test(String(k)); }
  function candDelKeyOf(itemsKey) { return String(itemsKey).replace(/^cand_items/, "cand_del"); } // cand_items[__t]→cand_del[__t]
  function parseDelMap(str) { try { var m = JSON.parse(str || "{}"); return (m && typeof m === "object" && !Array.isArray(m)) ? m : {}; } catch (e) { return {}; } }
  function mergeDelMap(olderStr, newerStr) {
    try {
      var a = parseDelMap(olderStr), b = parseDelMap(newerStr), out = {};
      Object.keys(a).forEach(function (c) { out[c] = a[c]; });
      Object.keys(b).forEach(function (c) { if (!(c in out) || (b[c] || 0) > (out[c] || 0)) out[c] = b[c]; });
      return JSON.stringify(out);
    } catch (e) { return null; }
  }
  // 配列から、墓標にある id を除外。削除ts が addedAt 以上なら削除確定。addedAt が新しい＝再追加は残す。
  //   (候補=cid/addedAt / ドラフト=id/addedAt。ドラフトは復元時に addedAt=now を打つので墓標を越えて復活できる)
  function applyTombstone(arrStr, delMap, idField, addField) {
    idField = idField || "cid"; addField = addField || "addedAt";
    try {
      if (!delMap) return arrStr;
      var arr = JSON.parse(arrStr || "[]"); if (!Array.isArray(arr)) return arrStr;
      return JSON.stringify(arr.filter(function (it) {
        var c = it && it[idField]; if (c == null) return true;
        var dts = delMap[c]; if (dts == null) return true;
        return (it[addField] || 0) > dts;
      }));
    } catch (e) { return arrStr; }
  }

  function syncOnce(retry) {
    if (!configured() || (_busy && !retry)) return Promise.resolve({ ok: false, skipped: true });
    var c = cfg(); _busy = true;
    var snap = loadSnap(), ts = loadTs(), now = Date.now();
    var snapLs = snap.ls || {}, snapIdb = snap.idb || {};
    // ★初回参加(この端末が未同期)は、確立済みのクラウドを壊さないよう「既存キーは雲を採用」。
    //   候補は union で両立、この端末だけが持つキーは push する。＝新規端末が正しい設定を上書きするのを防ぐ。
    var firstSync = getVer() === 0;
    var curLs = gatherLs();
    var secInfo = { entries: {}, plain: {}, skip: true };
    var newSecPlain = {};                 // push成功時に保存する {key:平文}(remote勝ちは復号後に追記)
    // 鍵をキー単位で暗号化して curLs へ。(sec:<key>)pass無しなら付けない。
    var secStep = buildSecEntries(snap).then(function (info) {
      secInfo = info; newSecPlain = Object.assign({}, info.plain);
      Object.keys(info.entries).forEach(function (pk) { curLs[pk] = info.entries[pk]; });
    });

    // IDB を hash化(画像アップロード)
    // ★旧実装は uploadImagesIn をキー毎に呼び、その中で /api/img/has を1本ずつ投げていた。
    //   画像を持つ候補がN件あると「変更が無くても毎サイクルN本」のWorkerリクエストが飛び、
    //   go5-sync=159k req/日(無料枠10万/日を単独超過)の主因になっていた。(Chami報告2026-07-16)
    //   候補が増えるほど線形に増える構造=+163%急増の説明もつく。
    //   → 全キーのdataURLをまとめて一意化→ハッシュ化1回→has確認は「未確認ハッシュだけチャンク一括」。
    //   存在確定ハッシュは端末に24hだけ記憶(sync2_imgok)して問い合わせを省く=定常状態はほぼ0本。
    //   TTLを設けるのは、R2から画像実体が消える既知症状(②)を最長24hで再検出して再アップするため
    //   (恒久キャッシュにすると「消えたのに存在扱い」で二度と直らなくなる)。
    var curIdb = {};
    var idbStep = (Idb && Idb.available()) ? Idb.entries().then(function (all) {
      var keys = Object.keys(all).filter(isSyncIdbKey);
      if (!keys.length) return;
      var bag = []; keys.forEach(function (k) { collectDataUrls(all[k], bag); });
      var uniq = {}; bag.forEach(function (u) { uniq[u] = 1; });
      var urls = Object.keys(uniq);
      var toRef = function () { // dataURL → {__img:hash} 変換(通信なし)。失敗画像はdataURLのまま残す=データ保全
        keys.forEach(function (k) {
          curIdb[k] = mapVal(all[k], function (v) { return typeof v === "string" && /^data:/.test(v); }, function (u) { var h = hByUrl[u]; return h ? { __img: h } : u; });
        });
        setProg("", 0, 0);
      };
      var hByUrl = {};
      if (!urls.length) { keys.forEach(function (k) { curIdb[k] = all[k]; }); return; }
      setProg("画像を確認", 0, urls.length);
      return Promise.all(urls.map(function (u) { return sha256hex(u).then(function (h) { hByUrl[u] = h; }); })).then(function () {
        var okSet = loadImgOk(), tNow = Date.now(), present = {};
        var unknown = urls.filter(function (u) { var t = okSet[hByUrl[u]]; return !(t && (tNow - t) < IMGOK_TTL_MS); });
        if (!unknown.length) return;                       // 全部確認済み＝リクエスト0本
        var chunks = [], CH = 50;                          // URL長対策(hash64桁×50≒3.3KB)
        for (var i = 0; i < unknown.length; i += CH) chunks.push(unknown.slice(i, i + CH));
        return chunks.reduce(function (p, ch) {
          return p.then(function () {
            return api("/api/img/has?keys=" + ch.map(function (u) { return hByUrl[u]; }).join(","))
              .then(function (r) { return r.json(); }).catch(function () { return { present: [] }; })
              .then(function (res) { (res.present || []).forEach(function (h) { present[h] = 1; }); });
          });
        }, Promise.resolve()).then(function () {
          var toUp = unknown.filter(function (u) { return !present[hByUrl[u]]; });
          var done = 0; if (toUp.length) setProg("画像を送信", 0, toUp.length);
          return toUp.reduce(function (p, u) {
            return p.then(function () {
              return api("/api/img/" + hByUrl[u], { method: "PUT", headers: { "Content-Type": "text/plain" }, body: u })
                .then(function (r) { return r.json(); })
                .then(function (j) { if (!j || !j.ok) hByUrl[u] = null; else present[hByUrl[u]] = 1; })
                .catch(function () { hByUrl[u] = null; })
                .then(function () { setProg("画像を送信", ++done, toUp.length); });
            });
          }, Promise.resolve());
        }).then(function () {
          var okNow = loadImgOk(); // 存在が確定したものだけ記憶(失敗=nullは記憶しない→次回再挑戦)
          urls.forEach(function (u) { var h = hByUrl[u]; if (h && present[h]) okNow[h] = tNow; });
          saveImgOk(okNow);
        });
      }).catch(function (e) {
        // ★致命的な保険(B-2棚卸しで発見): ここで例外が出ると toRef に到達せず curIdb が空のままになる。
        //   空の curIdb は「IDBの全キーが削除された」と解釈され、**雲へ削除がpushされて全端末の
        //   候補画像が消える**。sha256hex(crypto.subtle)はhttps以外や古い環境で落ち得るため実在の危険。
        //   → 何が起きても curIdb は必ず埋める(hByUrlが空ならdataURLのまま=無変換で送る=データは死なない)。
        try { root.console && root.console.warn("[go5 sync] 画像のhash化に失敗。無変換で継続(削除誤爆を防止)", e); } catch (x) {}
      }).then(toRef);
    }) : Promise.resolve();

    return Promise.all([secStep, idbStep]).then(function () {
      // pass無し(skip)の端末は、雲側の sec: キーを消さない。(削除判定から除外)
      var snapLsStamp = snapLs;
      if (secInfo.skip) { snapLsStamp = {}; Object.keys(snapLs).forEach(function (k) { if (k.indexOf(SEC_PREFIX) !== 0) snapLsStamp[k] = snapLs[k]; }); }
      // 変更/削除→タイムスタンプ更新。
      function stamp(prefix, cur, snp) {
        Object.keys(cur).forEach(function (k) {
          if (ts[prefix + k + " d"]) { delete ts[prefix + k + " d"]; ts[prefix + k] = now; return; } // 復活
          if (JSON.stringify(cur[k]) !== JSON.stringify(snp[k])) ts[prefix + k] = now;
          else if (!ts[prefix + k]) ts[prefix + k] = now;
        });
        Object.keys(snp).forEach(function (k) {
          if (prefix === "ls:" && k.indexOf(SEC_PREFIX) === 0) return; // ★鍵は絶対にtombstone(削除)しない＝復号失敗端末による鍵消失を防ぐ
          if (!(k in cur) && !ts[prefix + k + " d"]) { ts[prefix + k] = now; ts[prefix + k + " d"] = 1; }
        });
      }
      stamp("ls:", curLs, snapLsStamp); stamp("idb:", curIdb, snapIdb);
      function localMap(prefix, cur, snp) {
        var m = {};
        Object.keys(cur).forEach(function (k) { m[k] = { t: ts[prefix + k] || now, v: cur[k] }; });
        Object.keys(snp).forEach(function (k) {
          if (prefix === "ls:" && k.indexOf(SEC_PREFIX) === 0) return; // 鍵の削除は送らない
          if (!(k in cur) && ts[prefix + k + " d"]) m[k] = { t: ts[prefix + k] || now, d: 1 };
        });
        return m;
      }
      var lmapLs = localMap("ls:", curLs, snapLsStamp), lmapIdb = localMap("idb:", curIdb, snapIdb);

      return pullState().then(function (res) {
        var remote = {}; if (res && res.ok && !res.empty && res.blob) { try { remote = JSON.parse(res.blob); } catch (e) {} }
        var rver = (res && res.version) || 0, rls = remote.ls || {}, ridb = remote.idb || {};
        // ★初回参加：クラウドに既にあるキーは雲を採用。(この端末の値で上書きしない)候補はunionで両立。
        if (firstSync) {
          // 配列/墓標(候補・ドラフト)は初回でも union で両立させる＝新規端末の下書きを雲で潰さない。
          Object.keys(lmapLs).forEach(function (k) { if (!isCandArrayKey(k) && !isCandDelKey(k) && !isStockArrayKey(k) && !isStockArchiveKey(k) && !isStockDelKey(k) && !isTplBookKey(k) && !isTplDelKey(k) && !isDiscUrlsKey(k) && !isDiscDelKey(k) && !isScheduleStateKey(k) && !isPostedMapKey(k) && rls[k] !== undefined) delete lmapLs[k]; });
          Object.keys(lmapIdb).forEach(function (k) { if (ridb[k] !== undefined) delete lmapIdb[k]; });
        }
        var mls = mergeMaps(lmapLs, rls), midb = mergeMaps(lmapIdb, ridb);
        // ★画像レコードは「実体あり」を「取得失敗の残骸(空スロット)」より優先する。
        //   R2未反映のタイミングで pull すると本体が空で書かれ、その空レコードの ts が新しくなって
        //   LWW で勝ち続け、サブ端末で画像が永久に表示されない事故になる(特に直近の画像=まさに未反映になりやすい)。
        //   残骸(hasEmptyImgSlot=true)は ts を無視して実体側を採用＝次の受信で R2 から取り直させる(自己回復)。
        Object.keys(midb).forEach(function (k) {
          if (!isSyncIdbKey(k)) return;
          var win = preferImgRecord_(lmapIdb[k], ridb[k]);
          if (win) midb[k] = win;
        });
        // 候補・ドラフトの配列は両側にあれば id で union。(消さない)
        Object.keys(mls).forEach(function (k) {
          var idf = arrIdField_(k);
          if (!idf) return;
          var a = lmapLs[k], b = rls[k];
          if (a && b && !a.d && !b.d) {
            var localNewer = (a.t || 0) >= (b.t || 0);
            var u = unionByField(localNewer ? b.v : a.v, localNewer ? a.v : b.v, idf);
            if (u != null) mls[k] = { t: Math.max(a.t || 0, b.t || 0), v: u };
          }
        });
        // カレンダーは日付・枠・アカウント単位で統合。スマホの公開済みをPCの古い予定で戻さない。
        Object.keys(mls).forEach(function (k) {
          if (!isScheduleStateKey(k)) return;
          var a = lmapLs[k], b = rls[k];
          // tombstone は通常のLWWに任せる。値は片側だけでも検証し、破損JSONをクラウドへ送らない。
          if ((a && a.d) || (b && b.d)) return;
          if (!a && !b) return;
          var localNewer = a && b ? (a.t || 0) >= (b.t || 0) : !!a;
          var olderValue = a && b ? (localNewer ? b.v : a.v) : null;
          var newerValue = a && b ? (localNewer ? a.v : b.v) : (a ? a.v : b.v);
          var mergedSchedule = mergeScheduleState(olderValue, newerValue);
          if (mergedSchedule != null) mls[k] = { t: Math.max(a && a.t || 0, b && b.t || 0), v: mergedSchedule };
          else delete mls[k];
        });

        // 候補の投稿済み手動宣言({acc:{cid:ts}})は acc・cid 単位で union。(別端末の宣言を丸ごと消さない)
        Object.keys(mls).forEach(function (k) {
          if (!isPostedMapKey(k)) return;
          var a = lmapLs[k], b = rls[k];
          if (a && b && !a.d && !b.d) {
            var u = mergePostedMap(a.v, b.v);
            if (u != null) mls[k] = { t: Math.max(a.t || 0, b.t || 0), v: u };
          }
        });

        // 墓標(cand_del / go5_stock_del / bsky_tpl_del)は両側にあれば id/name 単位で union。(片側の削除を失わない)
        Object.keys(mls).forEach(function (k) {
          if (!isCandDelKey(k) && !isStockDelKey(k) && !isTplDelKey(k) && !isDiscDelKey(k)) return;
          var a = lmapLs[k], b = rls[k];
          if (a && b && !a.d && !b.d) {
            var u = mergeDelMap(a.v, b.v);
            if (u != null) mls[k] = { t: Math.max(a.t || 0, b.t || 0), v: u };
          }
        });

        // マージ結果をローカルへ適用
        var applies = [], newSnapLs = {}, newSnapIdb = {};
        Object.keys(mls).forEach(function (k) {
          var e = mls[k];
          var isSec = k.indexOf(SEC_PREFIX) === 0, sk = isSec ? k.slice(SEC_PREFIX.length) : null;
          if (e.d) { if (isSec) { return; } /* ★鍵は tombstone でもローカル削除しない(既存の誤tombstoneから鍵を守る) */ newSnapLs[k] = undefined; try { if (isSyncLsKey(k)) LS.removeItem(k); } catch (x) {} return; }
          if (isSec) {
            newSnapLs[k] = e.v;
            // 自分の暗号文が採用＝復号不要。(PBKDF2の無駄打ち回避)remote勝ち(別の値)の時だけ復号して反映。
            if (secInfo.entries[k] && e.v === secInfo.entries[k]) { newSecPlain[sk] = secInfo.plain[sk]; return; }
            if (c.pass && subtle && e.v) applies.push(decryptJson(e.v, c.pass).then(function (val) {
              try { LS.setItem(sk, String(val)); } catch (x) {} newSecPlain[sk] = String(val);
            }).catch(function () { _lastErr = "鍵の復号に失敗(パスフレーズ不一致?)"; }));
            return;
          }
          // ★競合防止：この同期は curLs を「開始時点」のスナップショットで動いている。非同期処理
          //   (画像アップロード/pull/push)の間にユーザーが候補を追加/編集した場合、そのままだと
          //   古いマージ結果で上書きして「追加した直後の候補が消える／情報が古いままになる」事故になる。
          var live = LS.getItem(k), finalV = e.v;
          var idf2 = arrIdField_(k);
          if (idf2) {
            // 配列は「ライブ値」ともう一度id unionしてから書く＝進行中に増えた分を絶対に失わない。
            var u2 = unionByField(e.v, live, idf2);
            if (u2 != null) finalV = u2;
            // ★墓標を適用：削除済みid/nameをunion結果から除外し復活を防ぐ。マージ済み墓標とライブ墓標の両方を効かせる。
            //   候補/ドラフト=id/addedAt。テンプレ帳=name/at(削除後に再保存したものは at>削除ts で残る)。作成履歴は墓標を適用しない。
            if (isCandArrayKey(k) || isStockArrayKey(k)) {
              var dk = isCandArrayKey(k) ? candDelKeyOf(k) : "go5_stock_del";
              var dmerged = (mls[dk] && !mls[dk].d) ? mls[dk].v : LS.getItem(dk);
              finalV = applyTombstone(finalV, parseDelMap(mergeDelMap(dmerged || "{}", LS.getItem(dk) || "{}")), idf2, "addedAt");
            } else if (isTplBookKey(k)) {
              var tdk = tplDelKeyOf(k);
              var tdmerged = (mls[tdk] && !mls[tdk].d) ? mls[tdk].v : LS.getItem(tdk);
              finalV = applyTombstone(finalV, parseDelMap(mergeDelMap(tdmerged || "{}", LS.getItem(tdk) || "{}")), "name", "at");
            } else if (isDiscUrlsKey(k)) {
              var ddk = discDelKeyOf(k);
              var ddmerged = (mls[ddk] && !mls[ddk].d) ? mls[ddk].v : LS.getItem(ddk);
              finalV = applyTombstone(finalV, parseDelMap(mergeDelMap(ddmerged || "{}", LS.getItem(ddk) || "{}")), "id", "at");
            }
          } else if (isScheduleStateKey(k)) {
            // 同期中にカレンダーが編集されても、開始時点の値で上書きせずライブ値を再統合する。
            var sm = mergeScheduleState(e.v, live);
            if (sm != null) finalV = sm;
          } else if (isPostedMapKey(k)) {
            // 同期中に宣言が増えても、開始時点の値で上書きせずライブ値と再union。(進行中の宣言を失わない)
            var up = mergePostedMap(e.v, live);
            if (up != null) finalV = up;
          } else if (isCandDelKey(k) || isStockDelKey(k) || isTplDelKey(k) || isDiscDelKey(k)) {
            // 墓標もライブ値とunion＝同期中に増えた削除を絶対に失わない。
            var u3 = mergeDelMap(e.v, live);
            if (u3 != null) finalV = u3;
          } else if (live !== null && live !== curLs[k] && live !== e.v) {
            // 非配列キーはライブ値がこの同期開始後に変わっている＝マージ結果は古い。上書きせず次回同期に委ねる
            //   。(スナップショット/push対象もLIVE値のまま記録＝クラウドへ古い値を送らず、次回の変更検知も正しく働く)
            newSnapLs[k] = live; mls[k] = { t: now, v: live };
            return;
          }
          newSnapLs[k] = finalV; if (finalV !== e.v) mls[k] = { t: e.t, v: finalV }; // 再union分をpush対象にも反映
          try { if (LS.getItem(k) !== finalV) LS.setItem(k, finalV); } catch (x) {}
        });
        var dlKeys = Object.keys(midb).filter(function (k) { return !midb[k].d && Idb && Idb.available(); });
        var dlDone = 0; if (dlKeys.length) setProg("画像を受信", 0, dlKeys.length);
        var pulledImgReal = 0;   // 実際にIDBへ「中身が変わった画像」を書き込んだ件数=再描画の合図の真値
        Object.keys(midb).forEach(function (k) {
          var e = midb[k];
          if (e.d) { if (Idb && Idb.available()) applies.push(Idb.del(k).catch(function () {})); return; }
          newSnapIdb[k] = e.v;
          if (Idb && Idb.available()) applies.push((function (kk) {
            return Idb.get(kk).catch(function () { return undefined; }).then(function (prev) {
              return downloadImagesIn(e.v).then(function (res) {
                // ★R2から画像本体が取れなかった時、既存のローカル画像を空で潰さない(サムネ/参照画像の消失防止・INC 2026-07-15)。
                if (res.failed > 0) {
                  if (prev !== undefined && prev !== null) return; // 既存は保持(潰さない)
                  // 初回で本体が取れない＝R2未反映の可能性。空で書くと「空画像」で固定され再取得されない。
                  //   書かず・スナップにも載せない＝次回同期で midb に再登場して取り直す(自己回復)。載せると
                  //   snap有り×IDB無しで tombstone 化し雲から画像を消しかねない。
                  delete newSnapIdb[k];
                  return;
                }
                // ★中身が実際に変わった時だけ数える=候補タブの再描画はこの真値でだけ起こす。
                //   (雲と自端末スナップの恒常ズレで毎周期立つ偽シグナルを混ぜない=下記 pulledImg の説明)
                try { if (JSON.stringify(prev) !== JSON.stringify(res.val)) pulledImgReal++; } catch (x) { pulledImgReal++; }
                return Idb.set(kk, res.val);
              });
            }).catch(function () {}).then(function () { setProg("画像を受信", ++dlDone, dlKeys.length); });
          })(k));
        });

        return Promise.all(applies).then(function () {
          // 削除で undefined になった snap を落とす
          Object.keys(newSnapLs).forEach(function (k) { if (newSnapLs[k] === undefined) delete newSnapLs[k]; });
          var outState = { fmt: 2, ls: mls, idb: midb, device: deviceName(), updatedAt: new Date().toISOString() };
          var changed = JSON.stringify(stripT(mls)) !== JSON.stringify(stripT(rls)) || JSON.stringify(stripT(midb)) !== JSON.stringify(stripT(ridb));
          // クラウド側で実際に更新されたLSキー数=この端末に「反映」された設定の件数。(反映されない不安への可視化)
          var pulledLs = 0; Object.keys(mls).forEach(function (k) { if (k.indexOf(SEC_PREFIX) !== 0 && !isCandArrayKey(k) && rls[k] && (!snapLs[k] || JSON.stringify(rls[k].v) !== JSON.stringify(snapLs[k]))) pulledLs++; });
          // 雲から実際に取り込んだ画像レコード数。(サブ端末で「後から届いた候補/ドラフト画像」を再描画させる合図)
          //   ★真値=IDBへ「中身が変わった画像」を書き込んだ件数(pulledImgReal)を使う。
          //   旧実装は「雲(ridb)と前回スナップ(snapIdb)の差」で数えていたが、雲側に空スロット残骸が
          //   残る/この端末が preferImgRecord_ で毎回ローカル実体を採る作品があると、その差が永久に
          //   解消せず pulledImg>0 が毎周期(60秒)立ち続けた。→ candidates.js が go5-synced(pulledImg>0)
          //   のたびに候補タブを全再描画=「見てるだけで勝手にリロード」になる真因(Chami 2026-08-06)。
          var pulledImg = pulledImgReal;
          function persist(ver) { setVer(ver); saveTs(ts); saveSnap({ ls: newSnapLs, idb: newSnapIdb, secPlain: newSecPlain }); _busy = false; _lastErr = ""; _lastAt = Date.now(); setProg("", 0, 0); fireSynced(pulledLs, pulledImg); }
          if (!changed) { persist(rver); return { ok: true, version: rver, noChange: true, pulled: pulledLs }; }
          return pushState(outState, rver).then(function (pr) {
            if (pr && pr.ok) { persist(pr.version); return { ok: true, version: pr.version, pulled: pulledLs }; }
            if (pr && pr.conflict && !retry) { _busy = false; return syncOnce(true); } // 再pull→マージ→再push
            _busy = false; _lastErr = (pr && pr.error) || "push失敗"; setProg("", 0, 0); return { ok: false, error: _lastErr };
          });
        });
      });
    }).catch(function (e) { _busy = false; _lastErr = String((e && e.message) || e); setProg("", 0, 0); return { ok: false, error: _lastErr }; });
  }

  var _timer = null;
  // 自動同期の周期。25秒→60秒(Cloudflare無料枠10万req/日の超過対策2026-07-16: 1タブ3,456回/日→1,440回/日)。
  //   変更駆動の requestSync(デバウンス)があるので、周期を伸ばしても実変更の反映は遅れない。
  var AUTO_MS = 60000;
  function startAuto() {
    if (_timer || !configured()) return;
    syncOnce(false);
    // 非表示タブでは回さない＝裏で開きっぱなしのタブがWorkerを叩き続けるのを止める。
    //   表示に戻った瞬間に1回同期するため、体感の反映速度は落とさない。
    _timer = root.setInterval(function () {
      if (root.document && root.document.visibilityState === "hidden") return;
      syncOnce(false);
    }, AUTO_MS);
    // 復帰イベント(visibilitychange/pageshow/focus/online)は連続して撃たれる=1.5s以内はまとめて1回に。
    var _lastReturnAt = 0;
    function syncOnReturn() {
      var t = Date.now();
      if (t - _lastReturnAt < 1500) return;
      _lastReturnAt = t; syncOnce(false);
    }
    // 隠れる直前=ローカル変更を押し出す / 表示に戻った直後=最新を取り込む(裏で止めた分を即回復)
    if (root.document) root.document.addEventListener("visibilitychange", function () {
      if (root.document.visibilityState === "hidden") syncOnce(false); // 離脱時=push
      else syncOnReturn();                                            // 復帰時=pull
    });
    // ★iOS Safariはアプリ切替やタブ復帰で bfcache 復元となり visibilitychange を撃たない事がある。
    //   pageshow/focus/online でも「戻ってきた瞬間に即pull」して、相手端末で編集したドラフトの
    //   反映待ち(最悪=次の60s周期まで)を無くす(Chami依頼2026-08-03「端末間の反映が遅い」)。
    if (root.addEventListener) {
      root.addEventListener("pageshow", syncOnReturn);
      root.addEventListener("focus", syncOnReturn);
      root.addEventListener("online", syncOnReturn);
    }
  }

  // 変更駆動の即時同期。(候補追加・画像保存の直後に呼ぶ)25秒周期を待たずに反映しつつ、
  //   デバウンス(連続変更を1回に)＋最小間隔(連打・多発でsync-workerのKV上限を突かない)で保護。
  //   ・no-op時はpushしない既存仕様(syncOnceのchanged判定)と合わせ、実変更が無ければ書き込みも起きない。
  var _reqTimer = null;
  var REQ_DEBOUNCE_MS = 3000;   // これだけ変更が途切れたらまとめて1回同期
  var REQ_MIN_GAP_MS = 10000;   // 直近同期からの最小間隔(下限)
  function requestSync() {
    if (!configured() || _reqTimer) return;             // 既に予約済み＝デバウンス(追加予約しない)
    var sinceLast = Date.now() - (_lastAt || 0);
    var wait = Math.max(REQ_DEBOUNCE_MS, REQ_MIN_GAP_MS - sinceLast);
    _reqTimer = root.setTimeout(function () { _reqTimer = null; syncOnce(false); }, wait);
  }

  // 即時同期。デバウンス(3〜10秒)を待たずに今すぐpush/pullする。
  //   ドラフト作成/投稿完了/編集の直後に呼ぶ＝相手端末が「今すぐ同期」を押さなくても、
  //   アプリを開いた時の自動pullだけで最新が出るようにする(Chami依頼2026-08-03「同期押さなくても済むように」)。
  //   スマホはアプリを閉じる/裏に回すとデバウンス待ちのpushが凍って消える＝そのレースを無くす。
  //   同期中(_busy)は今の同期の完了を待てないので、短い再同期だけ予約して取りこぼしを防ぐ。
  function flushSync() {
    if (!configured()) return Promise.resolve({ ok: false, skipped: true });
    if (_reqTimer) { try { root.clearTimeout(_reqTimer); } catch (e) {} _reqTimer = null; }
    if (_busy) { requestSync(); return Promise.resolve({ ok: false, busy: true }); }
    return syncOnce(false);
  }

  // ── 動画など重いblobの on-demand R2 経路(②・2026-08-01)──
  //   周期同期レール(isSyncIdbKey)には載せない=積んでも同期は軽いまま。実体はraw-bytesのsha256でR2へ直接PUT、
  //   台帳(ドラフトメタ)には hash 文字列だけ持たせ、必要な端末が必要な時にGETで取り寄せる。
  function putBlobR2(blob) {
    if (!configured() || !blob || !subtle || !blob.arrayBuffer) return Promise.resolve("");
    return blob.arrayBuffer().then(function (buf) {
      return subtle.digest("SHA-256", buf).then(function (d) {
        var h = hex(d);
        return api("/api/img/" + h, { method: "PUT", headers: { "Content-Type": blob.type || "application/octet-stream" }, body: buf })
          .then(function (r) { return r && r.ok ? h : ""; }).catch(function () { return ""; });
      });
    }).catch(function () { return ""; });
  }
  function fetchBlobR2(hash) {
    var c = cfg();
    if (!/^https?:\/\//.test(c.url) || !/^[a-f0-9]{16,64}$/.test(String(hash || ""))) return Promise.resolve(null);
    return root.fetch(c.url + "/img/" + hash).then(function (r) { return r && r.ok ? r.blob() : null; }).catch(function () { return null; });
  }
  // ── 論理名アドレスの blob 経路(KV非依存・2026-08-01)──
  //   R2キー = sha256hex(論理名)。両端末が「同じ論理名」から同じ鍵を算出できる=
  //   ポインタ(hash)を state同期(KV)で配る必要が無い。KVが制限で詰まっても2台目が取り寄せられる。
  //   ★用途: 動画本体(名前="go5vid:"+ドラフトID)。IDは既にメタ同期で両端末が持っている。
  function putBlobR2At(name, blob) {
    if (!configured() || !blob || !subtle || !blob.arrayBuffer) return Promise.resolve("");
    return sha256hex(String(name)).then(function (key) {
      return blob.arrayBuffer().then(function (buf) {
        return api("/api/img/" + key, { method: "PUT", headers: { "Content-Type": blob.type || "application/octet-stream" }, body: buf })
          .then(function (r) { return r && r.ok ? key : ""; }).catch(function () { return ""; });
      });
    }).catch(function () { return ""; });
  }
  function fetchBlobR2At(name) {
    var c = cfg();
    if (!/^https?:\/\//.test(c.url) || !subtle) return Promise.resolve(null);
    return sha256hex(String(name)).then(function (key) {
      return root.fetch(c.url + "/img/" + key).then(function (r) { return r && r.ok ? r.blob() : null; }).catch(function () { return null; });
    }).catch(function () { return null; });
  }

  root.Go5Sync = {
    configured: configured, syncNow: function () { return syncOnce(false); }, requestSync: requestSync, flushSync: flushSync, status: status, startAuto: startAuto,
    putBlobR2: putBlobR2, fetchBlobR2: fetchBlobR2, putBlobR2At: putBlobR2At, fetchBlobR2At: fetchBlobR2At,
    setConfig: function (o) {
      try {
        if (o.url != null) LS.setItem("sync2_url", String(o.url).trim());
        if (o.token != null) LS.setItem("sync2_token", String(o.token).trim());
        if (o.pass != null) LS.setItem("sync2_pass", String(o.pass));
      } catch (e) {}
    },
    getConfig: function () { var c = cfg(); return { url: c.url, token: c.token, hasPass: !!c.pass }; },
    resetLocalSyncState: function () { ["sync2_snap", "sync2_ts", "sync2_ver"].forEach(function (k) { try { LS.removeItem(k); } catch (e) {} }); },
    // Nodeテスト/デバッグ用に純関数を公開。(副作用なし)
    _test: { unionCand: unionCand, unionByField: unionByField, mergeDelMap: mergeDelMap, applyTombstone: applyTombstone, parseDelMap: parseDelMap, candDelKeyOf: candDelKeyOf, isCandArrayKey: isCandArrayKey, isCandDelKey: isCandDelKey, isStockArrayKey: isStockArrayKey, isStockArchiveKey: isStockArchiveKey, isStockDelKey: isStockDelKey, isTplBookKey: isTplBookKey, isTplDelKey: isTplDelKey, tplDelKeyOf: tplDelKeyOf, isDiscUrlsKey: isDiscUrlsKey, isDiscDelKey: isDiscDelKey, discDelKeyOf: discDelKeyOf, isSyncLsKey: isSyncLsKey, isScheduleStateKey: isScheduleStateKey, mergeScheduleState: mergeScheduleState, arrIdField_: arrIdField_, isSyncIdbKey: isSyncIdbKey, isPostedMapKey: isPostedMapKey, mergePostedMap: mergePostedMap, hasEmptyImgSlot: hasEmptyImgSlot, preferImgRecord_: preferImgRecord_ }
  };
  if (typeof module !== "undefined" && module.exports) module.exports = root.Go5Sync;

  // ── ⚙詳細設定 UI 配線＋自動同期の起動 ──
  if (root.document) root.document.addEventListener("DOMContentLoaded", function () {
    var $ = function (id) { return root.document.getElementById(id); };
    var url = $("syncNewUrl"), tok = $("syncNewToken"), pass = $("syncNewPass"), nowBtn = $("syncNewNow"), st = $("syncNewStatus");
    var c = cfg();
    if (url) url.value = c.url; if (tok) tok.value = c.token; if (pass) pass.value = c.pass;
    function save() { root.Go5Sync.setConfig({ url: url ? url.value : "", token: tok ? tok.value : "", pass: pass ? pass.value : "" }); }
    [url, tok, pass].forEach(function (el) { if (el) { el.addEventListener("change", save); el.addEventListener("blur", save); } });
    // 進捗テキスト。busy中は画像の件数/％を出し、「本当に進んでいるか分からない」不安を解消する。
    function busyText(s) {
      var p = s.prog || {};
      if (p.total > 0) { var pct = Math.round(p.done / p.total * 100); return "🔄 同期中… " + (p.phase || "処理中") + " " + p.done + "/" + p.total + " (" + pct + "%)"; }
      return "🔄 同期中…";
    }
    function showStatus() {
      if (!st) return; var s = status();
      st.textContent = !s.configured ? "未設定(3つを入力すると自動同期します)"
        : (s.busy ? busyText(s)
          : (s.lastError ? "⚠️ " + s.lastError
            : (s.version ? "✅ 同期済み(v" + s.version + ")" : "設定OK。「今すぐ同期」で開始")));
    }
    // busy中は進捗を1秒ごとに更新(件数が動くのが見える)。
    var _pollTimer = null;
    function startStatusPoll() { if (_pollTimer) return; _pollTimer = root.setInterval(function () { if (status().busy) showStatus(); else { root.clearInterval(_pollTimer); _pollTimer = null; showStatus(); } }, 1000); }
    if (nowBtn) nowBtn.addEventListener("click", function () {
      save();
      if (!configured()) { if (st) st.textContent = "⚠️ 同期URLとトークンを入れてください"; return; }
      if (st) st.textContent = "🔄 同期中…"; startStatusPoll();
      syncOnce(false).then(function (r) {
        // ★skipped＝別の自動同期が進行中で今回のタップは走らなかっただけ。「失敗」ではない。
        //   進行中の同期の実結果(✅ or 実エラー)は startStatusPoll→showStatus が status().lastError から出す。
        //   これをしないと「起動直後にタップ→自動同期と競合→中身のない『⚠️ 失敗』」になり、実際の原因が隠れる。
        if (r && r.skipped) { if (st) st.textContent = busyText(status()); return; }
        if (st) st.textContent = r.ok
          ? ("✅ 同期しました(v" + r.version + ")" + (r.pulled ? " ・" + r.pulled + "件を反映" : ""))
          : ("⚠️ " + (r.error || "失敗(原因不明)"));
      });
    });
    // 自動同期中も進捗表示を更新。(タブを開いていれば見える)
    if (root.document) root.document.addEventListener("go5-synced", showStatus);
    var tab = $("tabSettings"); if (tab) tab.addEventListener("click", function () { root.setTimeout(showStatus, 300); });
    showStatus();
    startAuto(); // 設定済みなら自動同期を開始(起動時pull＋25秒間隔＋離脱時push)
  });
})(typeof window !== "undefined" ? window : this);
