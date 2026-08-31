/**
 * core/img-diag.js — 画像表示不良の恒久調査(Phase1=診断計測層)。(Go5ImgDiag)
 *
 * 目的：候補ページ/投稿履歴の画像がiPhone/iOS Safariで「初回に出ない・リロードで出る・
 *   画像が増えるほど悪化」する不良を、まず計測できるようにする。挙動は一切変えない。
 *   push() でリングバッファ(最大300件)に積むだけ(consoleへは出さない・非同期処理も足さない)。
 *   `?imgdiag=1` を付けた時だけ画面右下に「コピー」ボタンを出し、dump() の全文をコピーできる。
 *
 * 使い方(呼び出し側)：window.Go5ImgDiag && Go5ImgDiag.push('ev_name', {key: val});
 *   例外安全(try/catchで包む)。呼び出し元のロジックには一切影響しない。
 */
(function () {
  'use strict';

  if (typeof window === 'undefined') return; // Node/module環境はここで終わり(DOM無し)
  var root = window;

  if (root.Go5ImgDiag) return; // 既に定義済みなら再定義しない

  var MAX = 300;
  var buf = [];
  var t0 = 0;

  // ★前のセッションの記録をリロード越しに保つ(Chami「ダメです」2026-08-24の芯)。
  //   画像不良は「初回は出ない・リロードで出る」ため、Chamiがリロードした瞬間に
  //   in-memoryのbufが消え、失敗したセッションの証拠が取れなかった=診断できない。
  //   pagehide/バックグラウンド化の直前にlocalStorageへ退避し、次回起動時に prev として
  //   復元する。dump()は prev(前セッション)＋現セッションの両方を出す。挙動は変えない。
  var PERSIST_KEY = 'go5_imgdiag_prev';
  var prev = [];               // 前セッションの記録(復元済み)
  var _persistTimer = null;

  function loadPrev_() {
    try {
      var raw = root.localStorage && root.localStorage.getItem(PERSIST_KEY);
      if (!raw) return;
      var arr = JSON.parse(raw);
      if (Array.isArray(arr)) prev = arr.slice(-MAX);
    } catch (e) {}
  }

  function persist_() {
    try {
      if (!root.localStorage) return;
      if (!buf.length) return;
      root.localStorage.setItem(PERSIST_KEY, JSON.stringify(buf.slice(-MAX)));
    } catch (e) {}
  }

  function schedulePersist_() {
    try {
      if (_persistTimer) return;
      _persistTimer = setTimeout(function () { _persistTimer = null; persist_(); }, 800);
    } catch (e) {}
  }

  function push(ev, data) {
    try {
      if (!t0) t0 = Date.now();
      var row = { t: Date.now(), ev: String(ev || '') };
      if (data && typeof data === 'object') {
        for (var k in data) { if (Object.prototype.hasOwnProperty.call(data, k)) row[k] = data[k]; }
      }
      buf.push(row);
      if (buf.length > MAX) buf.shift();
      schedulePersist_();
    } catch (e) {}
  }

  // ★単一の判定(cid単位の最終状態)を記帳する。トトリ(改善提案部門)提案・2026-08-31=
  //   これまで img-diag は hydrate/timeout/stalled の「回数」しか出せず、Chamiが実機ログを
  //   コピーしても「どの作品が・どのprefixで詰まっているか」が分からなかった(再発のたびに切り分け直し)。
  //   呼び側(refSlotState_ 等)が返す判定 state をそのまま1つの真実として持つ=img-diag は再分類しない。
  //   ★データ安全(添付Phase2書 §データ安全性)= stalled/loading を confirmed_missing へ昇格させない。
  //     missing は呼び側(refSlotDecide_)が陽性確認(idbOk && refLoaded/inMem)した時だけ渡してくる値を
  //     そのまま映すだけ。ここで「読めない→無い」を作らない(C-041)。画像実体の削除も一切しない。
  var verdicts = Object.create(null);        // cid -> { state, prefix, t, first, n }
  var VMAX = 2000;                            // cid数の暴走を一応抑える(通常は候補数=数百)
  function verdict(cid, state, prefix) {
    try {
      if (!cid) return;
      cid = String(cid); state = String(state || '');
      var cur = verdicts[cid];
      if (cur && cur.state === state && cur.prefix === (prefix || cur.prefix)) {
        cur.t = Date.now(); return;            // 同じ判定の再描画=churnさせない(タイムラインも汚さない)
      }
      var keys = Object.keys(verdicts);
      if (!cur && keys.length >= VMAX) { delete verdicts[keys[0]]; } // 古いものから1件落とす(実体は触らない)
      verdicts[cid] = { state: state, prefix: prefix || (cur && cur.prefix) || '', t: Date.now(), first: (cur && cur.first) || Date.now(), n: ((cur && cur.n) || 0) + 1 };
      push('verdict', { cid: cid, state: state, prefix: prefix || '' }); // 状態が変わった瞬間だけ時系列にも残す
    } catch (e) {}
  }
  // 未解決(まだ画像が出ていない)判定を集計する。stalled と missing は絶対に混ぜない。
  function verdictSummary_() {
    var pend = [], stall = [], miss = 0, ok = 0, none = 0, other = 0, total = 0;
    for (var cid in verdicts) {
      if (!Object.prototype.hasOwnProperty.call(verdicts, cid)) continue;
      var v = verdicts[cid]; total++;
      var s = v.state;
      if (s === 'images') ok++;
      else if (s === 'stalled') stall.push(cid + (v.prefix ? '(' + v.prefix + ')' : ''));
      else if (s === 'loading' || s === 'checking') pend.push(cid + ':' + s + (v.prefix ? '(' + v.prefix + ')' : ''));
      else if (s === 'missing') miss++;         // 陽性確認済みの0枚(=正当な画像なし)。詰まりではない
      else if (s === 'none') none++;
      else other++;
    }
    return { pend: pend, stall: stall, miss: miss, ok: ok, none: none, other: other, total: total };
  }

  function summarize_() {
    var rows = (prev || []).concat(buf); // 前セッション込みで集計(本命は"出てない"前セッション)
    var hydrate = 0, timeout = 0, r2fallback = 0, stalled = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r) continue;
      if (r.ev === 'hydrate_start') hydrate++;
      if (r.ev === 'idb_read_timeout') timeout++;
      if (r.ev === 'r2_start') r2fallback++;
      if (r.ev === 'stalled') stalled++;
    }
    return 'hydrate回数=' + hydrate + ' timeout回数=' + timeout + ' r2fallback回数=' + r2fallback + ' stalled件数=' + stalled;
  }

  function dumpRows_(rows, label) {
    var lines = [];
    lines.push('--- ' + label + '(' + rows.length + '件) ---');
    var base = rows.length ? rows[0].t : Date.now();
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || typeof r !== 'object') continue;
      var rel = r.t - base;
      var parts = ['+' + rel + 'ms', r.ev];
      for (var k in r) {
        if (k === 't' || k === 'ev') continue;
        if (!Object.prototype.hasOwnProperty.call(r, k)) continue;
        parts.push(k + '=' + r[k]);
      }
      lines.push(parts.join(' '));
    }
    return lines;
  }

  function dump() {
    try {
      var lines = [];
      lines.push('=== 画像診断ダンプ(' + new Date().toISOString() + ') ===');
      lines.push(summarize_());
      // ★cid単位の判定サマリ(トトリ提案・2026-08-31)= どの作品が今まさに詰まっているかを一望する。
      //   pend(読込中/確認中)と stall(20秒超えの操作可能待ち)は"まだ出ていない"側。
      //   miss は陽性確認済みの正当な0枚=詰まりではない(混同しない)。
      var vs = verdictSummary_();
      lines.push('判定: 表示OK=' + vs.ok + ' 未出=' + (vs.pend.length + vs.stall.length) + '(読込中/確認中=' + vs.pend.length + ' 詰まり(stalled)=' + vs.stall.length + ') 確認済0枚(missing)=' + vs.miss + ' 画像なし(none)=' + vs.none + ' cid総数=' + vs.total);
      if (vs.stall.length) lines.push('  詰まりcid(stalled): ' + vs.stall.join(', '));
      if (vs.pend.length) lines.push('  読込中cid: ' + vs.pend.join(', '));
      // 前セッション(リロード前の"出てない"画面)があれば先に出す=これが本命の証拠。
      if (prev && prev.length) lines = lines.concat(dumpRows_(prev, '前セッション(リロード前)'));
      lines = lines.concat(dumpRows_(buf, '今のセッション'));
      return lines.join('\n');
    } catch (e) {
      return '(dump失敗: ' + (e && e.message) + ')';
    }
  }

  var API = { push: push, verdict: verdict, dump: dump };
  root.Go5ImgDiag = API;

  // 起動時に前セッションの記録を復元し、離脱直前(リロード/バックグラウンド化)に退避する。
  loadPrev_();
  try {
    root.addEventListener('pagehide', persist_);
    root.addEventListener('visibilitychange', function () {
      if (root.document && root.document.visibilityState === 'hidden') persist_();
    });
  } catch (e) {}

  // ── ?imgdiag=1 の時だけ、コピー用の小さいボタンを出す ──────────────────
  function initButton_() {
    try {
      var qs = String((root.location && root.location.search) || '');
      if (!/[?&]imgdiag=1(&|$)/.test(qs)) return;
      if (!root.document || !root.document.body) return;
      var btn = root.document.createElement('button');
      btn.type = 'button';
      btn.textContent = '📋 画像診断をコピー(リロード前も記録)';
      // ★bottomを持ち上げる=iPhone Safariのボトムツールバーやページのボタンでbottomがpx小さいと隠れて
      //   「どこにあんの?」になる(Chami 2026-08-24)。safe-area＋十分な余白＋大きめ・目立つ配色で必ず見える所へ。
      btn.style.cssText = 'position:fixed;left:50%;transform:translateX(-50%);bottom:calc(env(safe-area-inset-bottom, 0px) + 96px);z-index:2147483647;background:#2bb3c0;color:#062028;border:2px solid #0e1422;border-radius:24px;padding:12px 18px;font-size:15px;font-weight:700;line-height:1.4;box-shadow:0 6px 20px rgba(0,0,0,.5);cursor:pointer;';
      btn.addEventListener('click', function () {
        var text = dump();
        var done = function () {
          var orig = btn.textContent;
          btn.textContent = 'コピーしました';
          setTimeout(function () { btn.textContent = orig; }, 1500);
        };
        try {
          if (root.navigator && root.navigator.clipboard && root.navigator.clipboard.writeText) {
            root.navigator.clipboard.writeText(text).then(done, function () { fallbackCopy_(text, done); });
          } else {
            fallbackCopy_(text, done);
          }
        } catch (e) { fallbackCopy_(text, done); }
      });
      root.document.body.appendChild(btn);
    } catch (e) {}
  }

  function fallbackCopy_(text, done) {
    try {
      var ta = root.document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;';
      root.document.body.appendChild(ta);
      ta.select();
      root.document.execCommand('copy');
      root.document.body.removeChild(ta);
      done();
    } catch (e) {}
  }

  if (root.document) {
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', initButton_);
    else initButton_();
  }
})();
