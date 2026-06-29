/**
 * snapshot.gs — YouTubeショート 経過時間別 再生数スナップショット記録
 *
 * 同一 GAS プロジェクト内の コード.gs と連携（openSS_ / prop_ / headerMap_ / CH_SHEETS を共用）。
 * 新規追加スクリプトプロパティ：YOUTUBE_API_KEY（GAS の Script Properties に設定・コードには書かない）。
 *
 * 仕組み：
 *   1) seedNewVideos_()  — 記録_ch1/ch2 の「YouTube動画URL」を走査し、
 *                          未追跡動画を「再生数_管理」へ登録。
 *   2) snapshotViews()   — 30分トリガー。経過時間ティアに応じたインターバルで
 *                          再生数を取得し「再生数_スナップショット」へ追記、
 *                          「再生数_管理」を更新。
 *   3) setupSnapshotTrigger() — 初回1回だけ実行し 30分トリガーを登録する。
 *
 * ティア定義（YouTube投稿からの経過時間）：
 *   0〜6h   → 30分ごと   … 公開直後の急成長フェーズ
 *   6〜24h  → 2時間ごと  … 当日の伸び把握
 *   1〜7d   → 6時間ごと  … 週内の継続伸び
 *   7〜28d  → 24時間ごと … 長期テール期
 *   28d 超  → 記録終了（status='done'）
 *
 * スクリプトプロパティ（Script Properties に設定）：
 *   YOUTUBE_API_KEY — YouTube Data API v3 キー（GAS 側専用・リファラー制限なし・コード直書き禁止）
 *   SHEET_ID        — 記録先スプレッドシートID（コード.gs と共用）
 *
 * 新規シート（初回実行時に自動作成）：
 *   再生数_スナップショット  — 時刻別スナップショット（追記のみ・削除しない）
 *   再生数_管理             — 動画ごとの追跡状態管理
 */

// ---- 定数 ----

var SNAP_SHEET_NAME_ = '再生数_スナップショット';
var MGMT_SHEET_NAME_ = '再生数_管理';

var SNAP_HEADERS_ = [
  'internal_id', 'youtube_id', 'channel', 'published_at',
  'snapshot_at', 'elapsed_min', 'elapsed_bucket', 'view_count', 'view_delta'
];
var MGMT_HEADERS_ = [
  'internal_id', 'youtube_id', 'channel', 'published_at',
  'status', 'first_seen', 'last_snapshot_at', 'last_view_count'
];

// 経過時間ティア（elapsed_min = YouTube 投稿からの経過分数）
var TIERS_ = [
  { maxElapsed: 360,   interval: 30,   label: '0-6h'  },  // 0〜6h → 30分
  { maxElapsed: 1440,  interval: 120,  label: '6-24h' },  // 6〜24h → 2時間
  { maxElapsed: 10080, interval: 360,  label: '1-7d'  },  // 1〜7日 → 6時間
  { maxElapsed: 40320, interval: 1440, label: '7-28d' },  // 7〜28日 → 24時間
];
var DONE_ELAPSED_MIN_ = 40320; // 28日 = 40320分

// ---- 汎用ヘルパー ----

function getOrCreateSnapSheet_(ss, name, headers) {
  var sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); sh.appendRow(headers); }
  else if (sh.getLastRow() === 0) { sh.appendRow(headers); }
  return sh;
}

// YouTube URL から 11文字の動画ID を抽出。
// 対応形式: youtu.be/<id> / watch?v=<id> / shorts/<id>
function youtubeIdFromUrl_(url) {
  if (!url) return '';
  var m = String(url).match(/(?:youtu\.be\/|[?&]v=|\/shorts\/)([0-9A-Za-z_-]{11})/);
  return m ? m[1] : '';
}

// 経過分数からティアのサンプリング間隔（分）を返す。
function getRequiredInterval_(elapsedMin) {
  if (elapsedMin == null || elapsedMin < 0) return TIERS_[0].interval;
  for (var i = 0; i < TIERS_.length; i++) {
    if (elapsedMin <= TIERS_[i].maxElapsed) return TIERS_[i].interval;
  }
  return TIERS_[TIERS_.length - 1].interval;
}

// 経過分数からバケットラベルを返す。
function getBucket_(elapsedMin) {
  if (elapsedMin == null || elapsedMin < 0) return 'unknown';
  for (var i = 0; i < TIERS_.length; i++) {
    if (elapsedMin <= TIERS_[i].maxElapsed) return TIERS_[i].label;
  }
  return '28d+';
}

// ---- YouTube Data API v3 呼び出し ----

// 動画 ID 配列（最大50件）→ { [videoId]: { views: number, published: ms } }
// YOUTUBE_API_KEY は prop_() でのみ取得（コードへの直書き厳禁）。
function fetchYtVideos_(ids, key) {
  if (!ids.length || !key) return {};
  var url = 'https://www.googleapis.com/youtube/v3/videos'
    + '?part=snippet,statistics&id=' + ids.join(',')
    + '&key=' + encodeURIComponent(key);
  try {
    var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (res.getResponseCode() >= 300) {
      Logger.log('fetchYtVideos_: HTTP ' + res.getResponseCode());
      return {};
    }
    var d = JSON.parse(res.getContentText() || '{}');
    var out = {};
    ((d && d.items) || []).forEach(function (item) {
      if (!item || !item.id) return;
      var rec = {};
      if (item.statistics) rec.views = parseInt(item.statistics.viewCount || '0', 10);
      if (item.snippet && item.snippet.publishedAt) {
        var t = Date.parse(item.snippet.publishedAt);
        if (!isNaN(t)) rec.published = t;
      }
      out[item.id] = rec;
    });
    return out;
  } catch (e) {
    Logger.log('fetchYtVideos_ 例外: ' + e);
    return {};
  }
}

// ---- 記録シートの「投稿日時」をYouTube公開日時で補完 ----

// ytDataMap = { [youtubeId]: { views: number, published: ms } }
// YouTube動画URLが一致し、かつ「投稿日時」が空の行にのみ書き込む（上書きしない）。
function updateSrcPublishedAt_(ss, ytDataMap) {
  if (!ss || !ytDataMap) return;
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh);
    var ytCol = map['YouTube動画URL'], dtCol = map['投稿日時'];
    if (!ytCol || !dtCol) return;
    var last = sh.getLastRow(); if (last < 2) return;
    var rows = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
    for (var i = 0; i < rows.length; i++) {
      var ytUrl = String(rows[i][ytCol - 1] || '').trim();
      if (!ytUrl) continue;
      var vid = youtubeIdFromUrl_(ytUrl);
      if (!vid || !ytDataMap[vid] || !ytDataMap[vid].published) continue;
      var existing = rows[i][dtCol - 1];
      if (existing !== '' && existing !== null && existing !== undefined) continue;
      sh.getRange(i + 2, dtCol).setValue(new Date(ytDataMap[vid].published));
    }
  });
}

// ---- シード：記録シートの新動画を管理シートへ登録 ----

function seedNewVideos_() {
  var ss = openSS_();
  var mgmt = getOrCreateSnapSheet_(ss, MGMT_SHEET_NAME_, MGMT_HEADERS_);

  // 既に管理シートにある youtube_id を集合で保持（重複登録を防ぐ）。
  var existing = {};
  if (mgmt.getLastRow() >= 2) {
    var mmap = headerMap_(mgmt);
    var yc = mmap['youtube_id'];
    if (yc) {
      mgmt.getRange(2, yc, mgmt.getLastRow() - 1, 1).getValues()
        .forEach(function (r) { if (r[0]) existing[String(r[0])] = true; });
    }
  }

  var newRows = [];
  // CH_SHEETS = ['記録_ch1','記録_ch2']（コード.gs で定義）
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh), last = sh.getLastRow();
    if (last < 2) return;
    var ytCol = map['YouTube動画URL'], pidCol = map['post_id'];
    if (!ytCol || !pidCol) return;
    var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
    var ch = (name === '記録_ch2') ? 'acc2' : 'acc1';
    vals.forEach(function (row) {
      var ytUrl = String(row[ytCol - 1] || '').trim();
      var pid   = String(row[pidCol - 1] || '').trim();
      if (!ytUrl) return;
      var vid = youtubeIdFromUrl_(ytUrl);
      if (!vid || existing[vid]) return;
      existing[vid] = true; // 同一ループ内の重複も防ぐ
      // MGMT_HEADERS_ 順: internal_id / youtube_id / channel / published_at / status / first_seen / last_snapshot_at / last_view_count
      newRows.push([pid, vid, ch, '', 'active', '', '', '']);
    });
  });

  if (newRows.length) {
    mgmt.getRange(mgmt.getLastRow() + 1, 1, newRows.length, MGMT_HEADERS_.length)
      .setValues(newRows);
    Logger.log('seedNewVideos_: ' + newRows.length + ' 件を再生数_管理へ追加。');
  }
}

// ---- メイン：30分トリガーから呼ばれる ----

function snapshotViews() {
  // まず記録シートから新動画を拾い上げる。
  seedNewVideos_();

  var ss   = openSS_();
  var mgmt = getOrCreateSnapSheet_(ss, MGMT_SHEET_NAME_, MGMT_HEADERS_);
  var snap = getOrCreateSnapSheet_(ss, SNAP_SHEET_NAME_, SNAP_HEADERS_);

  if (mgmt.getLastRow() < 2) {
    Logger.log('snapshotViews: 管理シートにデータなし。');
    return;
  }

  var mmap  = headerMap_(mgmt);
  var now   = new Date(), nowMs = now.getTime();
  var last  = mgmt.getLastRow();
  var rows  = mgmt.getRange(2, 1, last - 1, MGMT_HEADERS_.length).getValues();

  // 今回スナップが必要な動画を選択する。
  var toFetch = [];
  for (var i = 0; i < rows.length; i++) {
    var row    = rows[i];
    var status = String(row[mmap['status'] - 1] || '');
    var ytId   = String(row[mmap['youtube_id'] - 1] || '').trim();
    if (status === 'done' || !ytId) continue;

    var pubRaw   = row[mmap['published_at'] - 1];
    var lastSnap = row[mmap['last_snapshot_at'] - 1];

    var pubMs      = pubRaw ? new Date(pubRaw).getTime() : null;
    var elapsedMin = pubMs != null ? (nowMs - pubMs) / 60000 : null;

    // 経過 28日超 → done に更新してスキップ
    if (elapsedMin != null && elapsedMin > DONE_ELAPSED_MIN_) {
      mgmt.getRange(i + 2, mmap['status']).setValue('done');
      continue;
    }

    // 前回スナップからの経過 < 必要インターバル → スキップ
    if (lastSnap) {
      var minsSince = (nowMs - new Date(lastSnap).getTime()) / 60000;
      if (minsSince < getRequiredInterval_(elapsedMin)) continue;
    }

    toFetch.push({ rowIdx: i, ytId: ytId, row: row });
  }

  if (!toFetch.length) {
    Logger.log('snapshotViews: 今回のスナップ対象なし。');
    return;
  }

  var ytKey = prop_('YOUTUBE_API_KEY');
  if (!ytKey) {
    Logger.log('snapshotViews: YOUTUBE_API_KEY が未設定。Script Properties → YOUTUBE_API_KEY を追加してください。');
    return;
  }

  // 重複排除して YouTube API をバッチ呼び出し（50件ずつ）。
  var uniqIds = [];
  toFetch.forEach(function (item) {
    if (uniqIds.indexOf(item.ytId) === -1) uniqIds.push(item.ytId);
  });
  var ytData = {};
  for (var b = 0; b < uniqIds.length; b += 50) {
    var data = fetchYtVideos_(uniqIds.slice(b, b + 50), ytKey);
    Object.keys(data).forEach(function (id) { ytData[id] = data[id]; });
    if (b + 50 < uniqIds.length) Utilities.sleep(200);
  }

  // YouTube公開日時が取れた動画について、記録シートの「投稿日時」列を補完（空の場合のみ）。
  updateSrcPublishedAt_(ss, ytData);

  // スナップショット行を組み立て、管理シートを更新。
  var snapRows = [];
  toFetch.forEach(function (item) {
    var d = ytData[item.ytId];
    if (!d) return; // 削除済み・非公開などで API が返さなかった場合はスキップ

    var rowIdx     = item.rowIdx;
    var internalId = String(item.row[mmap['internal_id'] - 1] || '');
    var channel    = String(item.row[mmap['channel'] - 1] || '');
    var lastViews  = item.row[mmap['last_view_count'] - 1];

    var pubMs2   = typeof d.published === 'number' ? d.published : null;
    var pubDate  = pubMs2 ? new Date(pubMs2) : null;
    var elMin    = pubMs2 ? (nowMs - pubMs2) / 60000 : null;
    var bucket   = getBucket_(elMin);
    var viewCount = typeof d.views === 'number' ? d.views : 0;
    var viewDelta = (typeof lastViews === 'number' && lastViews >= 0)
      ? (viewCount - lastViews) : '';

    // SNAP_HEADERS_ 順:
    // internal_id / youtube_id / channel / published_at / snapshot_at / elapsed_min / elapsed_bucket / view_count / view_delta
    snapRows.push([
      internalId, item.ytId, channel, pubDate || '',
      now, elMin != null ? Math.round(elMin) : '', bucket,
      viewCount, viewDelta
    ]);

    // 管理シート更新（値があるものだけ更新し、既存データを空で潰さない）。
    var newStatus = (elMin != null && elMin > DONE_ELAPSED_MIN_) ? 'done' : 'active';
    var r = rowIdx + 2;
    if (pubDate && !item.row[mmap['published_at'] - 1]) {
      mgmt.getRange(r, mmap['published_at']).setValue(pubDate);
    }
    if (!item.row[mmap['first_seen'] - 1]) {
      mgmt.getRange(r, mmap['first_seen']).setValue(now);
    }
    mgmt.getRange(r, mmap['last_snapshot_at']).setValue(now);
    mgmt.getRange(r, mmap['last_view_count']).setValue(viewCount);
    mgmt.getRange(r, mmap['status']).setValue(newStatus);
  });

  if (snapRows.length) {
    snap.getRange(snap.getLastRow() + 1, 1, snapRows.length, SNAP_HEADERS_.length)
      .setValues(snapRows);
    Logger.log('snapshotViews: ' + snapRows.length + ' 件スナップショット完了。');
  }
}

// ---- トリガー管理 ----

// 初回1回だけ実行する。snapshotViews を 30分ごとに自動起動するトリガーを登録。
function setupSnapshotTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'snapshotViews') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('snapshotViews').timeBased().everyMinutes(30).create();
  Logger.log('snapshotViews トリガーを 30分ごとに登録しました。');
}

// 追跡を停止したいときに手動実行する。
function deleteSnapshotTrigger() {
  var count = 0;
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'snapshotViews') { ScriptApp.deleteTrigger(t); count++; }
  });
  Logger.log(count + ' 件の snapshotViews トリガーを削除しました。');
}
