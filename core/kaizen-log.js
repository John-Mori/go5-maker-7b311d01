/**
 * kaizen-log.js — 継続改善制度の行動ログ (第1段階=記録のみ)
 *
 * 「業務上意味のある操作」だけを D1(go5_kaizen) へ送る軽量ロガー。
 *   ・送信はバッチ(30秒ごと or 20件たまったら or タブ離脱時)＝リクエスト数を増やさない
 *   ・失敗は静かに諦める。(本業を絶対に邪魔しない)キュー上限100で古いものから捨てる
 *   ・秘密/個人情報は送らない(screen/action/objectId=cid等/小さなmetaのみ)
 *   ・無効化: localStorage kaizen_log_off = '1'
 *
 * 使い方: Go5Kaizen.log(screen, action, objectType, objectId, meta)
 *   例: Go5Kaizen.log('candidates', 'candidate_added', 'work', cid, {added:3})
 * 既存のDOMイベント(video-created / bluesky-posted / account-changed)は自動で購読する。
 */
(function (root) {
  "use strict";
  var QUEUE_MAX = 100, FLUSH_MS = 30000, FLUSH_N = 20, BODY_MAX = 50;
  var _q = [], _timer = null, _sid = null;

  function off() { try { return localStorage.getItem("kaizen_log_off") === "1"; } catch (e) { return false; } }
  function cfg() {
    try {
      return {
        url: (localStorage.getItem("fanza_worker_url") || "").trim().replace(/\/+$/, ""),
        sec: (localStorage.getItem("fanza_shared_secret") || "").trim()
      };
    } catch (e) { return { url: "", sec: "" }; }
  }
  function sid() {
    if (_sid) return _sid;
    var s = ""; var chars = "abcdefghijklmnopqrstuvwxyz0123456789";
    for (var i = 0; i < 10; i++) s += chars.charAt(Math.floor(Math.random() * chars.length));
    return (_sid = s);
  }
  function deviceType() { try { return /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent) ? "phone" : "pc"; } catch (e) { return "pc"; } }
  function clip(s, n) { s = String(s == null ? "" : s); return s.length > n ? s.slice(0, n) : s; }

  function log(screen, action, objectType, objectId, meta) {
    if (off()) return;
    if (!action) return;
    var m = "";
    try { if (meta != null) { m = JSON.stringify(meta); if (m.length > 300) m = ""; } } catch (e) { m = ""; }
    _q.push({
      screen: clip(screen, 40), action: clip(action, 64),
      objectType: clip(objectType, 32), objectId: clip(objectId, 80),
      meta: m, deviceType: deviceType(), sessionId: sid()
    });
    if (_q.length > QUEUE_MAX) _q.splice(0, _q.length - QUEUE_MAX); // 古い方から捨てる
    if (_q.length >= FLUSH_N) flush();
    else if (!_timer) _timer = root.setTimeout(flush, FLUSH_MS);
  }

  function flush() {
    if (_timer) { root.clearTimeout(_timer); _timer = null; }
    if (!_q.length || off()) return;
    var c = cfg(); if (!c.url || !c.sec) return; // worker未設定の端末では送らない(キューは保持)
    var batch = _q.splice(0, BODY_MAX);
    try {
      fetch(c.url + "/api/kaizen-event", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Shared-Secret": c.sec },
        body: JSON.stringify({ events: batch }),
        keepalive: true // タブ離脱時でも送信を完了させる
      }).catch(function () {}); // 失敗は静かに(次回のイベントに相乗りしない=リクエスト数を抑える)
    } catch (e) {}
    if (_q.length && !_timer) _timer = root.setTimeout(flush, FLUSH_MS);
  }

  // ── 既存DOMイベントの自動購読(コード側の追加フック不要ぶん) ──
  if (root.document) {
    root.document.addEventListener("video-created", function (e) {
      var d = (e && e.detail) || {};
      log("movie", "video_generated", "video", d.videoId || "", { account: d.account || "", test: !!d.test });
    });
    root.document.addEventListener("bluesky-posted", function (e) {
      var d = (e && e.detail) || {};
      log("bluesky", "bsky_posted", "post", d.post_uri || "", { account: d.account || "" });
    });
    var _loadedAt = Date.now();
    root.document.addEventListener("account-changed", function () {
      // ページ読み込み直後のaccount-changedは初期化イベント(実際の切替操作ではない)なので記録しない。
      //   記録粒度規約: 「意味のある操作」だけを残す。(orchestration.md)
      if (Date.now() - _loadedAt < 5000) return;
      log("app", "account_switched", "", "", null);
    });
    root.document.addEventListener("visibilitychange", function () {
      if (root.document.visibilityState === "hidden") flush();
    });
  }

  root.Go5Kaizen = { log: log, flush: flush };
})(typeof window !== "undefined" ? window : this);
