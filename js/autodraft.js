// js/autodraft.js — 無人ドラフト自動作成の口(β-5b・設計_無人ドラフト自動作成_20261024.md §2)。
//   PCの専用Chrome(起動係 scripts/_daemons/fivesec_autodraft.py)が Playwright で
//   window.FivesecAutoDraft.run(spec) を呼び、既存の make()→saveStock_ をそのまま走らせる。
//   ★関数を定義するだけで自分からは動かない。URLパラメータも読まない=公開ページに新しい入口を作らない。
//   入力手順は candidates.js transferToMovie_ を踏襲する(#author/#top/#movieWorkUrl へ input+change)。
//
//   spec = { cid, date:'YYYYMMDD', rank, title, circle, workUrl, goal?, cmtType?,
//            image:{ b64, type, name }, altTitles?:[..], hookNote?, test?, allowNoSync?, waitMs? }
//   戻り値 = { ok:true, id, videoId, bytes, cloud } / { ok:false, reason, detail? }
(function () {
  'use strict';
  var VERSION = 1;
  var DEFAULT_GOAL = '成約';
  var DEFAULT_CMT_TYPE = '⑥自己投影(成約)';
  var running = false;

  function $(id) { return document.getElementById(id); }
  // candidates.js の imgHash_ と同じ式=srcMark.hash が候補側の「使用済み」印と同じ鍵になる
  function imgHash_(s) { s = String(s || ''); var h = 5381, i = s.length; while (i) { h = ((h * 33) ^ s.charCodeAt(--i)) >>> 0; } return h.toString(36); }
  function setVal_(id, val) {
    var el = $(id);
    if (!el || val == null) return false;
    el.value = val;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return el.value === val;
  }
  function sleep_(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function metaList_() { try { return JSON.parse(localStorage.getItem('go5_stock_meta') || '[]') || []; } catch (e) { return []; } }
  function findLanded_(cid, date, since) {
    return metaList_().filter(function (m) {
      return m && m.videoReadyAt && m.srcMark && String(m.srcMark.cid) === cid &&
        (since ? m.ts >= since : (m.auto && String(m.auto.date) === date));
    })[0] || null;
  }
  function syncConfigured_() { var S = window.Go5Sync; return !!(S && S.configured && S.configured()); }
  function cloudHas_(id, until) {
    var S = window.Go5Sync;
    if (!syncConfigured_() || !S.hasBlobR2At) return Promise.resolve(false);
    var once = function () {
      return Promise.resolve().then(function () { return S.hasBlobR2At('go5vid:' + id); }).then(function (v) { return !!v; }, function () { return false; });
    };
    var loop = function () {
      return once().then(function (v) {
        if (v || Date.now() >= until) return v;
        return sleep_(2000).then(loop);
      });
    };
    return loop();
  }
  function done_(meta, extra) {
    var out = { ok: true, id: meta.id, videoId: meta.videoId || '', bytes: meta.videoBytes || 0 };
    for (var k in extra) out[k] = extra[k];
    return out;
  }

  async function run(spec) {
    spec = spec || {};
    var cid = String(spec.cid || '');
    var date = String(spec.date || '');
    if (!cid || !date || !spec.title) return { ok: false, reason: 'spec', detail: 'cid/date/title が必要' };
    if (!spec.image || !spec.image.b64) return { ok: false, reason: 'no_image' };
    if (running) return { ok: false, reason: 'busy' };
    if (!syncConfigured_() && !spec.allowNoSync) return { ok: false, reason: 'sync_unconfigured' };
    var acct = (typeof window.getCurrentAccount === 'function') ? window.getCurrentAccount() : '';
    if (acct !== 'acc3') return { ok: false, reason: 'account', detail: acct };
    if (typeof window.__go5RequestMake !== 'function' || !window.Go5SetForegroundFileReady) return { ok: false, reason: 'app_not_ready' };
    var waitMs = Number(spec.waitMs) > 0 ? Number(spec.waitMs) : 90000;

    // 二重生成の3つ目の柵(台帳・_making に加えて): 同じ日・同じcidのドラフトが既に着地していれば作らない
    var already = findLanded_(cid, date, 0);
    if (already) return done_(already, { dup: true, cloud: await cloudHas_(already.id, Date.now() + 10000) });

    running = true;
    try {
      if (window.Go5NewMovieReset) window.Go5NewMovieReset();
      var test = $('testMode');
      if (test && test.checked !== !!spec.test) { test.checked = !!spec.test; test.dispatchEvent(new Event('change', { bubbles: true })); }
      setVal_('author', spec.circle || '');
      setVal_('top', String(spec.title));
      if (spec.workUrl) setVal_('movieWorkUrl', String(spec.workUrl));
      if (!setVal_('movieGoal', spec.goal || DEFAULT_GOAL)) return { ok: false, reason: 'goal', detail: spec.goal || DEFAULT_GOAL };
      if (!setVal_('movieCmtType', spec.cmtType || DEFAULT_CMT_TYPE)) return { ok: false, reason: 'cmt_type', detail: spec.cmtType || DEFAULT_CMT_TYPE };

      var type = spec.image.type || 'image/jpeg';
      var dataUrl = 'data:' + type + ';base64,' + spec.image.b64;
      var bin = atob(spec.image.b64), bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      var file = new File([bytes], spec.image.name || 'autodraft.jpg', { type: type });
      var seq = window.Go5ClearForeground ? window.Go5ClearForeground() : null;
      var receipt = await window.Go5SetForegroundFileReady(file, seq, { origin: 'candidate' });
      if (!receipt || !receipt.ok) return { ok: false, reason: 'photo', detail: receipt && receipt.reason };
      window.__go5MovieSrcMark = { cid: cid, hash: imgHash_(dataUrl) };

      var auto = { date: date, rank: Number(spec.rank) || 0 };
      var autoAlt = { titles: (spec.altTitles || []).map(String), hookNote: String(spec.hookNote || '') };
      var created = null;
      var onCreated = function (ev) { created = (ev && ev.detail) || {}; };
      document.addEventListener('video-created', onCreated);
      var t0 = Date.now();
      try { await window.__go5RequestMake({ draft: true, auto: auto, autoAlt: autoAlt }); }
      finally { document.removeEventListener('video-created', onCreated); }
      // make() は入口ガードで止まると例外ではなく status に理由を出して戻る=それを理由として返す
      if (!created) { var st = $('status'); return { ok: false, reason: 'make_stopped', detail: st ? st.textContent.trim().slice(0, 160) : '' }; }

      var until = t0 + waitMs, landed = null;
      while (!(landed = findLanded_(cid, date, t0)) && Date.now() < until) await sleep_(1000);
      if (!landed) return { ok: false, reason: 'not_landed', videoId: created.videoId || '' };
      return done_(landed, { cloud: await cloudHas_(landed.id, Math.max(until, Date.now() + 10000)) });
    } catch (e) {
      return { ok: false, reason: 'error', detail: String((e && e.message) || e).slice(0, 200) };
    } finally {
      running = false;
    }
  }

  window.FivesecAutoDraft = { version: VERSION, run: run };
})();
