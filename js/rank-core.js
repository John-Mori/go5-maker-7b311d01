/**
 * rank-core.js — ランキングの「同一YouTube動画を1件へ field-level 統合」する純粋関数。(Go5RankCore)
 *
 * 【解く問題(真因1)】ランキングは channelItemsFor_ が返す「ローカル履歴＋シート由来行」を
 *   vid(YouTube動画ID)で重複排除していたが、先に出た行(=ローカル)を丸ごと残し、後ろのシート行を
 *   丸ごと捨てていた。ローカル行の shortUrl が空でも、shortUrl を持つ完全なシート行が失われ、
 *   「投稿履歴では出るクリックがランキングに出ない」非対称が残った(Codex監査 2026-08-03・真因1)。
 *
 * 【設計】whole-record 優先をやめ、field ごとに合成する。
 *   - 先頭行(ローカル優先=既存の表示を壊さない)を土台にする。
 *   - 空欄(null/'')だけを後続行(多くはシート由来の完全行)で補完する。★空文字で正本を消さない。
 *   - クリック計測URLは1本選ばず、全候補を clickUrls/workClickUrls に集合として保持する
 *     (postClicks_ が code 単位で重複なく合算する。Codex §6.2/§6.3)。
 *   - mergeUrls(合算)は全行の和集合。
 *   - カテゴリ属性は「未設定(undefined/null)なら真値で補完」だけ=明示 false は上書きしない。
 *
 * 使い方：ブラウザでは window.Go5RankCore、Node(テスト)では module.exports。
 */
(function (root) {
  'use strict';

  // 空欄だけを後続行で補完してよい文字列フィールド(★空文字で正本を消さない)。
  var FILL_KEYS = ['shortUrl', 'workShortUrl', 'shareUrl', 'workShareUrl',
    'postUri', 'postUrl', 'workUrl', 'ytUrl', 'title', 'workState', 'price', 'thumbUrl'];

  function isEmpty(v) { return v == null || v === ''; }
  function pushUniq(arr, v) { if (v && arr.indexOf(v) === -1) arr.push(v); }

  /**
   * rows: [{ it, vid, yt, acct }] を先勝ち順(ローカル→シート)で受け、同一 vid を1件へ畳む。
   * attrKeys: カテゴリ属性キー(ATTR_DEFS.map(a=>a.key))。空でも可。
   * 返り値: 同形の配列(it は統合済みクローン。vid/yt/acct は先頭行のもの)。
   */
  function mergeByVid(rows, attrKeys) {
    attrKeys = attrKeys || [];
    var order = [], byVid = {};
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (!row || !row.vid) continue;
      var it = row.it || {};
      if (!byVid[row.vid]) {
        var canon = {};
        for (var p in it) if (Object.prototype.hasOwnProperty.call(it, p)) canon[p] = it[p];
        canon.clickUrls = []; pushUniq(canon.clickUrls, it.shortUrl);
        canon.workClickUrls = []; pushUniq(canon.workClickUrls, it.workShortUrl);
        canon.mergeUrls = Array.isArray(it.mergeUrls) ? it.mergeUrls.slice() : [];
        var wrap = { it: canon, vid: row.vid, yt: row.yt, acct: row.acct };
        byVid[row.vid] = wrap; order.push(wrap);
      } else {
        var w = byVid[row.vid], c = w.it;
        for (var k = 0; k < FILL_KEYS.length; k++) {
          var key = FILL_KEYS[k];
          if (isEmpty(c[key]) && !isEmpty(it[key])) c[key] = it[key];
        }
        if (isEmpty(w.yt) && !isEmpty(row.yt)) w.yt = row.yt;
        if (!c.ts && it.ts) c.ts = it.ts;
        for (var a = 0; a < attrKeys.length; a++) {
          var ak = attrKeys[a];
          if (c[ak] == null && it[ak]) c[ak] = it[ak]; // 未設定のみ補完・明示falseは触らない
        }
        pushUniq(c.clickUrls, it.shortUrl);
        pushUniq(c.workClickUrls, it.workShortUrl);
        if (Array.isArray(it.mergeUrls)) for (var m = 0; m < it.mergeUrls.length; m++) pushUniq(c.mergeUrls, it.mergeUrls[m]);
      }
    }
    return order;
  }

  /**
   * バケット窓(30分/1時間…)の値を、ローカル観測(snap)とGASサーバー記録(gtp)から1組で選ぶ。
   *
   * 【解く問題(真因4=Chami「60分計測なのに78分になる」2026-08-02)】
   *   フロントの captureSnaps_ は許容窓が広く(目標分+50%)、アプリを78分時点で初めて開くと
   *   「1時間」バケットに ageMin=78 で固定されていた。表示は「ローカル優先→GAS補完」だったため、
   *   GAS側が [目標, 目標+9分] の厳しい窓で 66分の記録を持っていても、緩いローカルの78分が勝っていた。
   *
   * 【設計】v/c/age を別々に混ぜず、「記録時刻が目標分に最も近い側」を主に、欠けた指標だけ他方で補完する。
   *   - age は主(=目標に近い方)の値を使う → 表示される「◯分後」が目標へ寄る。
   *   - 導線2(w)はローカルのみ観測なので snap から取る。
   *   - 同点(距離が同じ)はローカル据え置き=既存挙動を壊さない。
   * snap: {v,c,w,ageMin} | null  gtp: {v,c,age} | null  targetMin: バケット目標分(例60)
   */
  function pickBucketRec(snap, gtp, targetMin) {
    var s = snap ? { v: (snap.v == null ? null : snap.v), c: (snap.c == null ? null : snap.c), w: (snap.w == null ? null : snap.w), age: (snap.ageMin == null ? null : snap.ageMin) } : null;
    // ★導線2(ピンク矢印=w)もGAS時点記録から採る(2026-08-08)。従来は w:null 固定でローカル観測のみに
    //   していたため、公開1時間時点にアプリを開いていない投稿はピンク矢印バケットが永久に空だった
    //   (Chami「ピンクのクリックがちゃんと集計されてない」)。GASが再生数/導線1と同様に w を毎時スナップ
    //   するようにした(gas/コード.gs)ので、v/c と同じく「目標分に近い側→無ければ他方」で採る。
    var g = gtp ? { v: (gtp.v == null ? null : gtp.v), c: (gtp.c == null ? null : gtp.c), w: (gtp.w == null ? null : gtp.w), age: (gtp.age == null ? null : gtp.age) } : null;
    if (!s && !g) return { v: null, c: null, w: null, age: null };
    if (!s) return g;
    if (!g) return s;
    var ds = (s.age == null) ? Infinity : Math.abs(s.age - targetMin);
    var dg = (g.age == null) ? Infinity : Math.abs(g.age - targetMin);
    var primary = (dg < ds) ? g : s;              // より目標分に近い側を主に(同点はローカル)
    var other = (primary === g) ? s : g;
    return {
      v: primary.v != null ? primary.v : other.v,
      c: primary.c != null ? primary.c : other.c,
      w: primary.w != null ? primary.w : other.w, // 導線2(ピンク矢印)=近い側→無ければ他方(GAS/ローカル両対応)
      age: primary.age != null ? primary.age : other.age
    };
  }

  var api = { mergeByVid: mergeByVid, pickBucketRec: pickBucketRec };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Go5RankCore = api;
})(typeof window !== 'undefined' ? window : this);
