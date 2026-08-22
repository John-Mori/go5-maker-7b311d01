// ============================================================
// YouTube競合サーチ (分析部・コピー部の観測基盤)  2026-07-18 改修β
// 設計書: docs/設計・調査/設計書_YouTube競合サーチ.md
//
// 方針: 既存の記録スプレッドシート(openSS_ = SHEET_ID・Chami呼称「AFI動画アナリティクス分析」)へ
//   「競合_」接頭辞のタブを追加する。既存タブ(記録_ch1/ch2/集計/設定/Holidays)には一切触れない。
//   APIキーは既存 ytApiKey_() (YT_API_KEY)を再利用=新規発行不要。費用ゼロ(無料クォータ内)。
//
// 規約(設計書§7): 公開メタデータのみ/映像・サムネ取得なし/干渉なし(観測専用)/
//   競合実名はシート内のみ(このコード・ログ・commitに競合名/IDを書かない)/YT_API_KEY非露出。
//
// クォータ会計: キー単位で既存のviews記録と共有するため、当日消費をprop COMP_QUOTA_<date>に
//   積み、上限(COMP_QUOTA_CAP)超で自主停止して既存記録を巻き込まない。
// ============================================================

var COMP_CH_SHEET   = '競合_チャンネル';
// Bluesky/X/訴求メモ = Chamiが競合と一緒に共有する横断情報(どこで・どう訴求しているか)。分析部の外部リンク経路分析の材料。
var COMP_CH_HEADERS = ['channel_id', 'チャンネル名', 'URL', '登録者数', '総再生数', '動画数', '状態', '発見経路', 'uploads', '追加日', '最終更新', 'Bluesky', 'X', '訴求メモ'];
var COMP_VID_SHEET   = '競合_動画';
// 焼き込み文字/コマ要約/フレーム取得日 = PC側の代表フレーム取得(4.5秒付近1枚)＋Gemini vision の格納先(2026-07-29 追加)。
//   ★この3列だけ「公開メタデータのみ/映像取得なし」の原則の例外=Chami指示(分析部アーモンドアイ経由 msg 1531767096482988065)。
//   取得は全編DLせず --download-sections で4.5秒付近の一瞬のみ。IDはシート内のみ(このコードに競合IDを書かない)。
var COMP_VID_HEADERS = ['video_id', 'channel_id', 'タイトル', '公開日時', '長さ秒', 'isShort', '初回取得日', '焼き込み文字', 'コマ要約', 'フレーム取得日'];
var COMP_DAILY_SHEET   = '競合_日次';
var COMP_DAILY_HEADERS = ['日付', 'video_id', 'channel_id', '再生数', '高評価', 'コメント数'];
var COMP_WEEKLY_SHEET   = '競合_週次';
var COMP_WEEKLY_HEADERS = ['集計日', '種別', '対象', '値1', '値2', '値3'];
var COMP_SEARCHLOG_SHEET   = '競合_検索ログ';
var COMP_SEARCHLOG_HEADERS = ['日付', 'クエリ', 'ヒット数', 'candidate化数'];
// コミュニティ投稿は公式APIに窓口が無い=自動収集不可(2026-07-18確認)。人が見て手で貯める観察タブ。
// 背景: Chamiがアダアフィのコンサルから「コミュニティ投稿での訴求が効果高い」と教わった戦略仮説の受け皿。
var COMP_COMMUNITY_SHEET   = '競合_コミュニティ観察';
var COMP_COMMUNITY_HEADERS = ['記録日', 'チャンネル名', '投稿URL', '内容メモ', '効果メモ(反応/推移)', '記録者'];

var COMP_WINDOW_DAYS = 30;    // 追跡窓(この日数を過ぎた動画は日次スナップの対象外)
var COMP_QUOTA_CAP   = 2000;  // 競合ジョブの当日クォータ自主停止しきい値(標準10,000の20%)
var COMP_SHORT_MAX_SEC = 180; // isShort推定の上限(APIに公式フラグが無いためのヒューリスティック)

// ---- タブ確保(getSheetByName || insertSheet・ヘッダ初期化)。既存タブは触らない ----
function compSheet_(name, headers) {
  var ss = openSS_();
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) sh.appendRow(headers);
  return sh;
}

// ---- クォータ会計: 当日消費に units を足す。上限超なら false(=以降のAPIを打たない) ----
function compQuotaAdd_(units) {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var key = 'COMP_QUOTA_' + Utilities.formatDate(new Date(), tz, 'yyyyMMdd');
  var cur = parseInt(prop_(key) || '0', 10) || 0;
  if (cur >= COMP_QUOTA_CAP) return false;
  PropertiesService.getScriptProperties().setProperty(key, String(cur + units));
  return true;
}

// ---- ISO8601 duration(PT#H#M#S) → 秒 ----
function parseIsoDuration_(iso) {
  var m = String(iso || '').match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!m) return 0;
  return (parseInt(m[1] || '0', 10) * 3600) + (parseInt(m[2] || '0', 10) * 60) + parseInt(m[3] || '0', 10);
}

// ---- channels.list(snippet+statistics+contentDetails): id[] → {id:{name,subs,hiddenSubs,views,videos,uploads}} ----
function ytChannels_(ids) {
  var key = ytApiKey_(), out = {};
  if (!key || !ids.length) return out;
  for (var i = 0; i < ids.length; i += 50) {
    if (!compQuotaAdd_(1)) break;
    var batch = ids.slice(i, i + 50);
    try {
      var u = 'https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&id=' + batch.join(',') + '&key=' + encodeURIComponent(key);
      var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
      if (res.getResponseCode() >= 300) continue;
      var d = JSON.parse(res.getContentText() || '{}');
      (d.items || []).forEach(function (it) {
        var sn = it.snippet || {}, st = it.statistics || {}, cd = it.contentDetails || {};
        out[it.id] = {
          name: sn.title || '',
          subs: st.subscriberCount != null ? parseInt(st.subscriberCount, 10) : null,
          hiddenSubs: st.hiddenSubscriberCount === true,
          views: st.viewCount != null ? parseInt(st.viewCount, 10) : null,
          videos: st.videoCount != null ? parseInt(st.videoCount, 10) : null,
          uploads: (cd.relatedPlaylists && cd.relatedPlaylists.uploads) || ''
        };
      });
    } catch (e) {}
    Utilities.sleep(120);
  }
  return out;
}

// ---- playlistItems.list: uploadsプレイリスト → 直近の {videoId, publishedAt}[] ----
function ytPlaylistItems_(playlistId, maxItems) {
  var key = ytApiKey_(), out = [];
  if (!key || !playlistId) return out;
  var pageToken = '', got = 0, guard = 0;
  do {
    if (!compQuotaAdd_(1)) break;
    if (++guard > 10) break;
    try {
      var u = 'https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId=' +
        encodeURIComponent(playlistId) + (pageToken ? '&pageToken=' + pageToken : '') + '&key=' + encodeURIComponent(key);
      var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
      if (res.getResponseCode() >= 300) break;
      var d = JSON.parse(res.getContentText() || '{}');
      (d.items || []).forEach(function (it) {
        var cd = it.contentDetails || {};
        if (cd.videoId) out.push({ videoId: cd.videoId, publishedAt: cd.videoPublishedAt || '' });
      });
      got += (d.items || []).length;
      pageToken = d.nextPageToken || '';
    } catch (e) { break; }
    Utilities.sleep(120);
  } while (pageToken && got < (maxItems || 50));
  return out;
}

// ---- videos.list(snippet+contentDetails): id[] → {id:{title,publishedAt,durationSec,channelId}} ----
function ytVideosMeta_(ids) {
  var key = ytApiKey_(), out = {};
  if (!key || !ids.length) return out;
  for (var i = 0; i < ids.length; i += 50) {
    if (!compQuotaAdd_(1)) break;
    var batch = ids.slice(i, i + 50);
    try {
      var u = 'https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails&id=' + batch.join(',') + '&key=' + encodeURIComponent(key);
      var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
      if (res.getResponseCode() >= 300) continue;
      var d = JSON.parse(res.getContentText() || '{}');
      (d.items || []).forEach(function (it) {
        var sn = it.snippet || {}, cd = it.contentDetails || {};
        out[it.id] = {
          title: sn.title || '', publishedAt: sn.publishedAt || '',
          durationSec: parseIsoDuration_(cd.duration), channelId: sn.channelId || ''
        };
      });
    } catch (e) {}
    Utilities.sleep(120);
  }
  return out;
}

// ---- videos.list(statistics): id[] → {id:{views,likes,comments}} ----
function ytVideosStats_(ids) {
  var key = ytApiKey_(), out = {};
  if (!key || !ids.length) return out;
  for (var i = 0; i < ids.length; i += 50) {
    if (!compQuotaAdd_(1)) break;
    var batch = ids.slice(i, i + 50);
    try {
      var u = 'https://www.googleapis.com/youtube/v3/videos?part=statistics&id=' + batch.join(',') + '&key=' + encodeURIComponent(key);
      var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
      if (res.getResponseCode() >= 300) continue;
      var d = JSON.parse(res.getContentText() || '{}');
      (d.items || []).forEach(function (it) {
        var st = it.statistics || {};
        out[it.id] = {
          views: st.viewCount != null ? parseInt(st.viewCount, 10) : null,
          likes: st.likeCount != null ? parseInt(st.likeCount, 10) : null,
          comments: st.commentCount != null ? parseInt(st.commentCount, 10) : null
        };
      });
    } catch (e) {}
    Utilities.sleep(120);
  }
  return out;
}

// ---- チャンネルURL/ハンドルから channel_id を解決(UC…は直接抽出・@handleはforHandle・他はsearch) ----
function compResolveChannelId_(url) {
  url = String(url || '').trim();
  var m = url.match(/\/channel\/(UC[0-9A-Za-z_-]{20,})/);
  if (m) return m[1];
  var key = ytApiKey_();
  if (!key) return '';
  var handle = '';
  var hm = url.match(/\/@([0-9A-Za-z_.-]+)/) || url.match(/^@?([0-9A-Za-z_.-]+)$/);
  if (hm) handle = hm[1];
  try {
    if (handle) {
      if (!compQuotaAdd_(1)) return '';
      var u = 'https://www.googleapis.com/youtube/v3/channels?part=id&forHandle=@' + encodeURIComponent(handle) + '&key=' + encodeURIComponent(key);
      var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
      if (res.getResponseCode() < 300) {
        var d = JSON.parse(res.getContentText() || '{}');
        if (d.items && d.items[0] && d.items[0].id) return d.items[0].id;
      }
    }
    // フォールバック: /c/ や /user/ の旧式URL → search(100 units)
    var q = (url.match(/\/(?:c|user)\/([^\/?#]+)/) || [])[1] || handle;
    if (q && compQuotaAdd_(100)) {
      var su = 'https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&maxResults=1&q=' + encodeURIComponent(q) + '&key=' + encodeURIComponent(key);
      var sres = UrlFetchApp.fetch(su, { muteHttpExceptions: true });
      if (sres.getResponseCode() < 300) {
        var sd = JSON.parse(sres.getContentText() || '{}');
        if (sd.items && sd.items[0] && sd.items[0].snippet) return sd.items[0].snippet.channelId || '';
      }
    }
  } catch (e) {}
  return '';
}

// ---- 台帳読込: watch対象の行(未解決URLはchannel_idを解決して書き戻す) ----
function compWatchChannels_() {
  var sh = compSheet_(COMP_CH_SHEET, COMP_CH_HEADERS);
  var last = sh.getLastRow(); if (last < 2) return [];
  var map = headerMap_(sh);
  var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var out = [];
  vals.forEach(function (row, i) {
    var status = String(row[map['状態'] - 1] || '').trim() || 'watch';
    if (status !== 'watch') return;
    var cid = String(row[map['channel_id'] - 1] || '').trim();
    var url = String(row[map['URL'] - 1] || '').trim();
    if (!cid && url) {                         // Chamiが貼ったURLだけの行 → IDを解決して書き戻す
      cid = compResolveChannelId_(url);
      if (cid) {
        sh.getRange(i + 2, map['channel_id']).setValue(cid);
        if (!row[map['追加日'] - 1]) sh.getRange(i + 2, map['追加日']).setValue(today);
        if (map['発見経路'] && !row[map['発見経路'] - 1]) sh.getRange(i + 2, map['発見経路']).setValue('seed');
      }
    }
    if (cid) out.push({ rowIndex: i + 2, channelId: cid, uploads: String(row[map['uploads'] - 1] || '').trim() });
  });
  return out;
}

// ---- 動画台帳を upsert(video_id主キー・新規のみ追記)。既存video_idのSetを返す ----
function compUpsertVideos_(records) {
  var sh = compSheet_(COMP_VID_SHEET, COMP_VID_HEADERS);
  var last = sh.getLastRow();
  var seen = {};
  if (last >= 2) {
    var ex = sh.getRange(2, 1, last - 1, 1).getValues();
    ex.forEach(function (r) { if (r[0]) seen[r[0]] = true; });
  }
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var rows = [];
  records.forEach(function (v) {
    if (!v.video_id || seen[v.video_id]) return;
    seen[v.video_id] = true;
    var isShort = (v.durationSec != null && v.durationSec > 0 && v.durationSec <= COMP_SHORT_MAX_SEC) ? 'yes' : 'no';
    var row = [v.video_id, v.channel_id, v.title || '', v.publishedAt || '', v.durationSec || 0, isShort, today];
    while (row.length < COMP_VID_HEADERS.length) row.push('');  // 焼き込み文字/コマ要約/フレーム取得日は後からPC側が埋める
    rows.push(row);
  });
  if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, COMP_VID_HEADERS.length).setValues(rows);
  return seen;
}

// ---- 競合_チャンネルの見出しに不足列を追記(既存タブへ後から列を足す・冪等) ----
function compMigrateChannelHeaders_() {
  var sh = compSheet_(COMP_CH_SHEET, COMP_CH_HEADERS);
  var lastCol = Math.max(1, sh.getLastColumn());
  var have = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(function (x) { return String(x); });
  var missing = COMP_CH_HEADERS.filter(function (h) { return have.indexOf(h) < 0; });
  if (missing.length) sh.getRange(1, lastCol + 1, 1, missing.length).setValues([missing]);
  return { ok: true, added: missing };
}

// ---- 競合_動画の見出しに不足列を追記(焼き込み文字/コマ要約/フレーム取得日 を後付け・冪等) ----
function compMigrateVideoHeaders_() {
  var sh = compSheet_(COMP_VID_SHEET, COMP_VID_HEADERS);
  var lastCol = Math.max(1, sh.getLastColumn());
  var have = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(function (x) { return String(x); });
  var missing = COMP_VID_HEADERS.filter(function (h) { return have.indexOf(h) < 0; });
  if (missing.length) sh.getRange(1, lastCol + 1, 1, missing.length).setValues([missing]);
  return { ok: true, added: missing };
}

// ---- 全タブを確保(手動記録タブ=競合_コミュニティ観察 を含む)。冪等・doGetから呼ぶ ----
function compEnsureTabs_() {
  compSheet_(COMP_CH_SHEET, COMP_CH_HEADERS);
  compMigrateChannelHeaders_();  // 既存タブへBluesky/X/訴求メモ列を後付け
  compSheet_(COMP_VID_SHEET, COMP_VID_HEADERS);
  compMigrateVideoHeaders_();    // 既存タブへ焼き込み文字/コマ要約/フレーム取得日 を後付け
  compSheet_(COMP_DAILY_SHEET, COMP_DAILY_HEADERS);
  compSheet_(COMP_WEEKLY_SHEET, COMP_WEEKLY_HEADERS);
  compSheet_(COMP_SEARCHLOG_SHEET, COMP_SEARCHLOG_HEADERS);
  compSheet_(COMP_COMMUNITY_SHEET, COMP_COMMUNITY_HEADERS);
  return { ok: true, tabs: [COMP_CH_SHEET, COMP_VID_SHEET, COMP_DAILY_SHEET, COMP_WEEKLY_SHEET, COMP_SEARCHLOG_SHEET, COMP_COMMUNITY_SHEET] };
}

// ============================================================
// 代表フレーム取得(PC側スクレイパとの受け渡し)  2026-07-29
//   PCが comp_frame_pending で未取得のShortを引き、yt-dlpで4.5秒付近1枚を抜き、
//   Gemini(ベホップ)で 焼き込み文字/コマ要約 を起こして comp_frame_write で書き戻す。
//   GAS側は台帳の読み書きのみ(映像取得・OCRはPC側)。
// ============================================================

// ---- 未取得の代表フレーム対象を返す(Shortのみ・追跡窓内・焼き込み文字が空の行)。read-only ----
function compFramePending_(limit) {
  limit = Math.min(Math.max(parseInt(limit || '20', 10) || 20, 1), 100);
  compMigrateVideoHeaders_();
  var cutoff = new Date().getTime() - COMP_WINDOW_DAYS * 86400000;
  var sh = compSheet_(COMP_VID_SHEET, COMP_VID_HEADERS);
  var map = headerMap_(sh);
  var last = sh.getLastRow();
  var out = [];
  if (last >= 2) {
    var vv = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
    for (var i = 0; i < vv.length && out.length < limit; i++) {
      var r = vv[i];
      var vid = String(r[map['video_id'] - 1] || '').trim(); if (!vid) continue;
      if (String(r[map['isShort'] - 1] || '').trim() !== 'yes') continue;   // 縦型フックの観測が目的=Shortのみ
      var done = String(r[map['焼き込み文字'] - 1] || '').trim() || String(r[map['フレーム取得日'] - 1] || '').trim();
      if (done) continue;                                                   // 取得済みは飛ばす(冪等)
      var pub = r[map['公開日時'] - 1];
      var t = pub ? new Date(pub).getTime() : 0;
      if (t && t < cutoff) continue;                                        // 追跡窓の外は対象外
      out.push({
        videoId: vid,
        channelId: String(r[map['channel_id'] - 1] || '').trim(),
        title: r[map['タイトル'] - 1] || '',
        durationSec: Number(r[map['長さ秒'] - 1] || 0) || 0
      });
    }
  }
  return { ok: true, count: out.length, pending: out };
}

// ---- 代表フレームの結果を書き戻す(video_id一致の既存行へ追記のみ。新規行は作らない) ----
function compFrameWriteback_(items) {
  if (!items || !items.length) return { ok: true, written: 0 };
  compMigrateVideoHeaders_();
  var sh = compSheet_(COMP_VID_SHEET, COMP_VID_HEADERS);
  var map = headerMap_(sh);
  var last = sh.getLastRow();
  if (last < 2) return { ok: true, written: 0, note: 'no_rows' };
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var idCol = sh.getRange(2, map['video_id'], last - 1, 1).getValues();
  var rowOf = {};
  idCol.forEach(function (r, i) { var v = String(r[0] || '').trim(); if (v) rowOf[v] = i + 2; });
  var written = 0;
  items.forEach(function (it) {
    var vid = String(it.videoId || '').trim(); if (!vid) return;
    var ri = rowOf[vid]; if (!ri) return;
    if (it.frameText != null) sh.getRange(ri, map['焼き込み文字']).setValue(String(it.frameText));
    if (it.panelDesc != null) sh.getRange(ri, map['コマ要約']).setValue(String(it.panelDesc));
    sh.getRange(ri, map['フレーム取得日']).setValue(today);
    written++;
  });
  return { ok: true, written: written };
}

// ---- シード登録: URLをwatch行として台帳へ追加(channel_id重複はスキップ)。doGetから呼ぶ ----
//   Chamiが(A)「改修βに登録してもらう」を選んだ時の受け口。競合名/URLはシート内のみ(コード・commitに書かない)。
// ---- 1チャンネル分の統計(登録者数/総再生数/動画数/uploads/チャンネル名/最終更新)を即取得して埋める ----
//   既存の日次ジョブ runCompetitorDaily と同じ ytChannels_ を使う(欄の埋め方も同一)。API失敗時は何もしない。
function compFillChannelStats_(sh, map, rowIndex, cid, fallbackName, today) {
  var s = (ytChannels_([cid]) || {})[cid];
  if (!s) return false;
  if (s.name) sh.getRange(rowIndex, map['チャンネル名']).setValue(s.name);
  else if (fallbackName) sh.getRange(rowIndex, map['チャンネル名']).setValue(String(fallbackName));
  if (s.hiddenSubs) sh.getRange(rowIndex, map['登録者数']).setValue('');
  else if (s.subs != null) sh.getRange(rowIndex, map['登録者数']).setValue(s.subs);
  if (s.views != null) sh.getRange(rowIndex, map['総再生数']).setValue(s.views);
  if (s.videos != null) sh.getRange(rowIndex, map['動画数']).setValue(s.videos);
  if (s.uploads) sh.getRange(rowIndex, map['uploads']).setValue(s.uploads);
  sh.getRange(rowIndex, map['最終更新']).setValue(today);
  return true;
}

function compAddSeed_(url, name, bluesky, x, note) {
  url = String(url || '').trim();
  if (!url) return { ok: false, reason: 'no_url' };
  compMigrateChannelHeaders_();  // Bluesky/X/訴求メモ列を確保してから書く
  var m = url.match(/\/channel\/(UC[0-9A-Za-z_-]{20,})/);
  var cid = m ? m[1] : compResolveChannelId_(url);
  if (!cid) return { ok: false, reason: 'unresolved', url: url };
  var sh = compSheet_(COMP_CH_SHEET, COMP_CH_HEADERS);
  var map = headerMap_(sh);
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  // 追記する横断情報(空でない分だけ後で書く)
  var setExtra = function (rowIndex) {
    if (bluesky && map['Bluesky']) sh.getRange(rowIndex, map['Bluesky']).setValue(String(bluesky));
    if (x && map['X']) sh.getRange(rowIndex, map['X']).setValue(String(x));
    if (note && map['訴求メモ']) sh.getRange(rowIndex, map['訴求メモ']).setValue(String(note));
  };
  var last = sh.getLastRow();
  if (last >= 2) {
    var ex = sh.getRange(2, map['channel_id'], last - 1, 1).getValues();
    for (var i = 0; i < ex.length; i++) {
      if (String(ex[i][0]).trim() === cid) {
        var ri = i + 2;
        if (String(sh.getRange(ri, map['状態']).getValue()).trim() !== 'watch') sh.getRange(ri, map['状態']).setValue('watch');
        setExtra(ri);  // 既存行にも横断情報を補完
        // 既存行でも統計が未取得(登録者数も総再生数も空)なら、この場で埋める(日次ジョブを待たない)
        var filled = false;
        if (!String(sh.getRange(ri, map['登録者数']).getValue()).trim() && !String(sh.getRange(ri, map['総再生数']).getValue()).trim()) {
          filled = compFillChannelStats_(sh, map, ri, cid, name, today);
        }
        return { ok: true, channel_id: cid, added: false, note: 'already_exists', filled: filled };
      }
    }
  }
  // 新規行: 先にYouTube統計を取得し、欄を埋めた状態で1行書く(Chami指示=登録時にデータ取得して欄を埋める)。
  var s = (ytChannels_([cid]) || {})[cid] || null;
  var row = [];
  for (var c = 0; c < COMP_CH_HEADERS.length; c++) row.push('');
  row[map['channel_id'] - 1] = cid;
  row[map['チャンネル名'] - 1] = (s && s.name) || String(name || '');
  row[map['URL'] - 1] = url;
  row[map['状態'] - 1] = 'watch';
  row[map['発見経路'] - 1] = 'seed';
  row[map['追加日'] - 1] = today;
  if (s) {
    if (!s.hiddenSubs && s.subs != null) row[map['登録者数'] - 1] = s.subs;
    if (s.views != null) row[map['総再生数'] - 1] = s.views;
    if (s.videos != null) row[map['動画数'] - 1] = s.videos;
    if (s.uploads) row[map['uploads'] - 1] = s.uploads;
    row[map['最終更新'] - 1] = today;
  }
  if (bluesky && map['Bluesky']) row[map['Bluesky'] - 1] = String(bluesky);
  if (x && map['X']) row[map['X'] - 1] = String(x);
  if (note && map['訴求メモ']) row[map['訴求メモ'] - 1] = String(note);
  sh.getRange(sh.getLastRow() + 1, 1, 1, COMP_CH_HEADERS.length).setValues([row]);
  return { ok: true, channel_id: cid, added: true, filled: !!s };
}

// ============================================================
// 日次ジョブ: チャンネル統計更新 → 新着動画の取り込み → 追跡窓内の統計スナップ
// ============================================================
function runCompetitorDaily() {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var watch = compWatchChannels_();
  if (!watch.length) { Logger.log('競合日次: watch対象0件(シードURL未登録)'); return { ok: true, channels: 0, note: 'no_watch' }; }

  // ★実行の時間予算(2026-08-23恒久対策・競合_日次の凍結を根治)。
  //   GASの1実行は約6分で強制終了する。旧構成は ①チャンネル統計更新→②新着discovery(watch数ぶんのplaylist取得)→
  //   ③meta→④統計スナップappend の順で、追跡窓の動画が増えるにつれ④の手前で6分に達して殺され、競合_日次シートへ
  //   1行も書けないまま2026-08-18で凍結していた(実測: comp_daily_now が361秒=GoogleのタイムアウトHTMLを返す。
  //   PC側の日次集計は毎朝"成功"に見えるが同じ8/18を再集計しているだけ=silent green)。
  //   対策=最優先の「既存の追跡窓動画の統計スナップ→日次append」を先頭へ移し、必ず先に済ませる。
  //   チャンネル統計更新・新着discovery は"充実"(無くてもその日の日次は成立)なので時間予算内の best-effort に後置する。
  var RUN_T0 = Date.now();
  var BUDGET_MS = 240000; // 充実処理は通算4分で打ち切り=残り2分で確実に終える(appendは既に先頭で完了済み)
  var cutoff = new Date().getTime() - COMP_WINDOW_DAYS * 86400000;

  // 1) 【最優先・必ず先に実行】追跡窓内の"既存"動画(台帳に載っている分)の統計をスナップ→日次append。
  //    windowVids は動画台帳(前回までのdiscoveryで蓄積済み)から読む=当日discovery(下の3)に依存しない。
  //    ※当日公開の新着はこの時点では台帳に無いので翌日から対象化(速度は2点必要なので初日欠測は影響なし)。
  var vidSh = compSheet_(COMP_VID_SHEET, COMP_VID_HEADERS);
  var vMap = headerMap_(vidSh);
  var vlast = vidSh.getLastRow();
  var windowVids = [], vChan = {};
  if (vlast >= 2) {
    var vv = vidSh.getRange(2, 1, vlast - 1, vidSh.getLastColumn()).getValues();
    vv.forEach(function (r) {
      var vid = r[vMap['video_id'] - 1]; if (!vid) return;
      var pub = r[vMap['公開日時'] - 1];
      var t = pub ? new Date(pub).getTime() : 0;
      if (t && t >= cutoff) { windowVids.push(vid); vChan[vid] = r[vMap['channel_id'] - 1] || ''; }
    });
  }
  var st = ytVideosStats_(windowVids);
  var dailySh = compSheet_(COMP_DAILY_SHEET, COMP_DAILY_HEADERS);
  var drows = [];
  windowVids.forEach(function (vid) {
    var s = st[vid]; if (!s) return;
    drows.push([today, vid, vChan[vid] || '', s.views == null ? '' : s.views, s.likes == null ? '' : s.likes, s.comments == null ? '' : s.comments]);
  });
  if (drows.length) dailySh.getRange(dailySh.getLastRow() + 1, 1, drows.length, COMP_DAILY_HEADERS.length).setValues(drows);
  var snapped = drows.length;

  // 2) 【充実・予算内】チャンネル統計を更新し uploads を確保。snapped==0(YT空)なら以降は無駄なので打ち切る。
  var chSh = compSheet_(COMP_CH_SHEET, COMP_CH_HEADERS);
  var chMap = headerMap_(chSh);
  if (snapped && Date.now() - RUN_T0 < BUDGET_MS) {
    var ids = watch.map(function (w) { return w.channelId; });
    var stats = ytChannels_(ids);
    watch.forEach(function (w) {
      var s = stats[w.channelId]; if (!s) return;
      if (s.name) chSh.getRange(w.rowIndex, chMap['チャンネル名']).setValue(s.name);
      if (s.hiddenSubs) chSh.getRange(w.rowIndex, chMap['登録者数']).setValue('');
      else if (s.subs != null) chSh.getRange(w.rowIndex, chMap['登録者数']).setValue(s.subs);
      if (s.views != null) chSh.getRange(w.rowIndex, chMap['総再生数']).setValue(s.views);
      if (s.videos != null) chSh.getRange(w.rowIndex, chMap['動画数']).setValue(s.videos);
      if (s.uploads) { chSh.getRange(w.rowIndex, chMap['uploads']).setValue(s.uploads); w.uploads = s.uploads; }
      chSh.getRange(w.rowIndex, chMap['最終更新']).setValue(today);
    });
  }

  // 3) 【充実・予算内】各チャンネルの新着動画(追跡窓内)を台帳へ(次回スナップから対象化)。
  var newVideos = 0;
  if (snapped && Date.now() - RUN_T0 < BUDGET_MS) {
    var newVideoIds = [];
    watch.forEach(function (w) {
      if (!w.uploads || Date.now() - RUN_T0 >= BUDGET_MS) return;
      var items = ytPlaylistItems_(w.uploads, 50);
      items.forEach(function (it) {
        var tt = it.publishedAt ? new Date(it.publishedAt).getTime() : 0;
        if (tt && tt >= cutoff) newVideoIds.push({ videoId: it.videoId, channelId: w.channelId });
      });
    });
    var metaIds = newVideoIds.map(function (x) { return x.videoId; });
    var meta = ytVideosMeta_(metaIds);
    var chOf = {}; newVideoIds.forEach(function (x) { chOf[x.videoId] = x.channelId; });
    var vrecords = [];
    Object.keys(meta).forEach(function (vid) {
      var m = meta[vid];
      vrecords.push({ video_id: vid, channel_id: m.channelId || chOf[vid] || '', title: m.title, publishedAt: m.publishedAt, durationSec: m.durationSec });
    });
    compUpsertVideos_(vrecords);
    newVideos = vrecords.length;
  }

  // 4) 日曜は週次サマリを再計算(予算内のみ)
  if (new Date().getDay() === 0 && Date.now() - RUN_T0 < BUDGET_MS) compWeeklySummary_();

  // ★snapped==0(=YT統計が全空=urlfetch日次上限/APIキー/quota切れ)は「緑を返しながら書いていない」状態。
  //   握り潰さず ok:false で返す=呼び出し口(comp_daily_now)や実行ログで可視化する(C-041/モドリッチ依頼2026-08-23)。
  return { ok: snapped > 0, channels: watch.length, newVideos: newVideos, snapped: snapped,
           windowVids: windowVids.length, elapsedMs: Date.now() - RUN_T0,
           note: snapped ? '' : 'snapped_zero: YT統計が空(urlfetch日次上限/APIキー/quota要確認)' };
}

// ============================================================
// 週次ジョブ: 検索で競合候補を発見(candidate止まり・自動watch化しない)
// ============================================================
function runCompetitorDiscovery() {
  var key = ytApiKey_();
  if (!key) return { ok: false, error: 'no_api_key' };
  var queries = [];
  try { queries = JSON.parse(prop_('COMP_QUERIES') || '[]'); } catch (e) { queries = []; }
  if (!queries.length) return { ok: true, note: 'no_queries', hits: 0 };

  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var chSh = compSheet_(COMP_CH_SHEET, COMP_CH_HEADERS);
  var chMap = headerMap_(chSh);
  // 既知channel_idの集合(重複candidateを作らない)
  var known = {};
  var clast = chSh.getLastRow();
  if (clast >= 2) chSh.getRange(2, chMap['channel_id'], clast - 1, 1).getValues().forEach(function (r) { if (r[0]) known[r[0]] = true; });

  var logSh = compSheet_(COMP_SEARCHLOG_SHEET, COMP_SEARCHLOG_HEADERS);
  var addedRows = [], logRows = [];
  queries.forEach(function (q) {
    if (!compQuotaAdd_(100)) return;
    var hits = 0, cand = 0;
    try {
      var u = 'https://www.googleapis.com/youtube/v3/search?part=snippet&type=channel&maxResults=10&q=' + encodeURIComponent(q) + '&key=' + encodeURIComponent(key);
      var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
      if (res.getResponseCode() < 300) {
        var d = JSON.parse(res.getContentText() || '{}');
        (d.items || []).forEach(function (it) {
          var cid = it.snippet && it.snippet.channelId; if (!cid) return;
          hits++;
          if (known[cid]) return;
          known[cid] = true; cand++;
          addedRows.push([cid, (it.snippet.title || ''), 'https://www.youtube.com/channel/' + cid, '', '', '', 'candidate', 'search:' + q, '', today, '']);
        });
      }
    } catch (e) {}
    logRows.push([today, q, hits, cand]);
    Utilities.sleep(150);
  });
  if (addedRows.length) chSh.getRange(chSh.getLastRow() + 1, 1, addedRows.length, COMP_CH_HEADERS.length).setValues(addedRows);
  if (logRows.length) logSh.getRange(logSh.getLastRow() + 1, 1, logRows.length, COMP_SEARCHLOG_HEADERS.length).setValues(logRows);
  return { ok: true, queries: queries.length, candidates: addedRows.length };
}

// ============================================================
// 週次サマリの再計算(競合_週次を書き直す)
// ============================================================
function compWeeklySummary_() {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');

  // 日次スナップから video_id ごとの直近2点(速度=日次差分)を作る
  var dSh = compSheet_(COMP_DAILY_SHEET, COMP_DAILY_HEADERS);
  var dlast = dSh.getLastRow();
  var speed = {};   // vid -> {views, prevViews, chan}
  if (dlast >= 2) {
    var dv = dSh.getRange(2, 1, dlast - 1, COMP_DAILY_HEADERS.length).getValues();
    dv.forEach(function (r) {
      var vid = r[1]; if (!vid) return;
      var views = r[3] === '' ? null : Number(r[3]);
      if (views == null) return;
      if (!speed[vid]) speed[vid] = { chan: r[2] || '', views: views, prevViews: null };
      else { speed[vid].prevViews = speed[vid].views; speed[vid].views = views; } // 時系列昇順前提=最後の2点が最新
    });
  }

  // 動画メタ(タイトル・isShort)
  var vSh = compSheet_(COMP_VID_SHEET, COMP_VID_HEADERS);
  var vMap = headerMap_(vSh);
  var vlast = vSh.getLastRow();
  var title = {}, pubHour = {};
  if (vlast >= 2) {
    var vv = vSh.getRange(2, 1, vlast - 1, vSh.getLastColumn()).getValues();
    vv.forEach(function (r) {
      var vid = r[vMap['video_id'] - 1]; if (!vid) return;
      title[vid] = r[vMap['タイトル'] - 1] || '';
      var pub = r[vMap['公開日時'] - 1];
      if (pub) pubHour[vid] = Number(Utilities.formatDate(new Date(pub), tz, 'H'));
    });
  }

  // 速度トップ10
  var arr = [];
  Object.keys(speed).forEach(function (vid) {
    var s = speed[vid];
    var v = (s.prevViews != null) ? (s.views - s.prevViews) : null;   // 1日の伸び
    if (v == null) return;
    arr.push({ vid: vid, chan: s.chan, spd: v, title: title[vid] || '' });
  });
  arr.sort(function (a, b) { return b.spd - a.spd; });
  var top = arr.slice(0, 10);

  // タイトル特徴(全対象動画・母集団の傾向)
  var titles = arr.map(function (x) { return x.title; }).filter(function (t) { return t; });
  var feat = compTitleFeatures_(titles);

  // 投稿時刻分布
  var hourHist = {};
  Object.keys(pubHour).forEach(function (vid) { var h = pubHour[vid]; hourHist[h] = (hourHist[h] || 0) + 1; });

  // 書き直し(既存タブをクリアして再出力)
  var wSh = compSheet_(COMP_WEEKLY_SHEET, COMP_WEEKLY_HEADERS);
  wSh.clearContents();
  wSh.appendRow(COMP_WEEKLY_HEADERS);
  var rows = [];
  top.forEach(function (t, i) { rows.push([today, '速度top', '#' + (i + 1), t.spd, t.title, t.chan]); });
  rows.push([today, 'タイトル特徴', '平均文字数', feat.avgLen, '', '']);
  rows.push([today, 'タイトル特徴', '【】使用率%', feat.bracketPct, '', '']);
  rows.push([today, 'タイトル特徴', '数字使用率%', feat.digitPct, '', '']);
  rows.push([today, 'タイトル特徴', '絵文字使用率%', feat.emojiPct, '', '']);
  Object.keys(hourHist).sort(function (a, b) { return Number(a) - Number(b); }).forEach(function (h) {
    rows.push([today, '投稿時刻', h + '時', hourHist[h], '', '']);
  });
  if (rows.length) wSh.getRange(wSh.getLastRow() + 1, 1, rows.length, COMP_WEEKLY_HEADERS.length).setValues(rows);
  return { ok: true, top: top.length };
}

// ---- タイトル群の特徴集計(平均文字数・【】率・数字率・絵文字率) ----
function compTitleFeatures_(titles) {
  var n = titles.length || 1;
  var sumLen = 0, bracket = 0, digit = 0, emoji = 0;
  // 絵文字の近似検出: 矢印/記号/装飾記号ブロック + サロゲート上位(絵文字の大半はastral面)
  var emojiRe = /[←-⇿☀-➿\uD83C-\uDBFF]/;
  titles.forEach(function (t) {
    sumLen += t.length;
    if (/[【】\[\]]/.test(t)) bracket++;
    if (/[0-9０-９]/.test(t)) digit++;
    if (emojiRe.test(t)) emoji++;
  });
  var pct = function (x) { return Math.round(x / n * 1000) / 10; };
  return { avgLen: Math.round(sumLen / n * 10) / 10, bracketPct: pct(bracket), digitPct: pct(digit), emojiPct: pct(emoji) };
}

// ============================================================
// 部門への受け渡し(doGetから呼ぶ・JSON)
// ============================================================
// 分析部向け: 週次サマリ相当のダイジェスト
function compDigest_() {
  var wSh = compSheet_(COMP_WEEKLY_SHEET, COMP_WEEKLY_HEADERS);
  var last = wSh.getLastRow();
  var items = last >= 2 ? wSh.getRange(2, 1, last - 1, COMP_WEEKLY_HEADERS.length).getValues() : [];
  var chSh = compSheet_(COMP_CH_SHEET, COMP_CH_HEADERS);
  var chMap = headerMap_(chSh);
  var clast = chSh.getLastRow();
  var watch = 0, candidate = 0;
  if (clast >= 2) chSh.getRange(2, chMap['状態'], clast - 1, 1).getValues().forEach(function (r) {
    var s = String(r[0] || '').trim(); if (s === 'watch') watch++; else if (s === 'candidate') candidate++;
  });
  return { ok: true, headers: COMP_WEEKLY_HEADERS, weekly: items, watchChannels: watch, candidateChannels: candidate };
}

// 日付値(Date/文字列)を日次キーへ正規化。同日複数スナップは後勝ちで1日にまとめる。
function compDayKey_(value, tz) {
  if (Object.prototype.toString.call(value) === '[object Date]' && !isNaN(value.getTime())) {
    return Utilities.formatDate(value, tz, 'yyyy-MM-dd');
  }
  var s = String(value == null ? '' : value).trim();
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return m[1] + '-' + m[2] + '-' + m[3];
  var d = new Date(value);
  return isNaN(d.getTime()) ? '' : Utilities.formatDate(d, tz, 'yyyy-MM-dd');
}
function compDaysBetween_(fromDay, toDay) {
  var a = new Date(fromDay + 'T00:00:00Z').getTime();
  var b = new Date(toDay + 'T00:00:00Z').getTime();
  if (!isFinite(a) || !isFinite(b) || b <= a) return 1;
  return Math.max(1, Math.round((b - a) / 86400000));
}

// コピー部向け: 速度順のタイトルコーパス(特徴タグつき)。既存フィールドを維持し、画面用のチャンネル・再生情報を加算する。
function compTitles_(days, top) {
  days = Math.min(Math.max(parseInt(days || '30', 10) || 30, 1), 90);
  top = Math.min(Math.max(parseInt(top || '50', 10) || 50, 1), 200);
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var cutoff = new Date().getTime() - days * 86400000;

  // 動画メタ
  var vSh = compSheet_(COMP_VID_SHEET, COMP_VID_HEADERS);
  var vMap = headerMap_(vSh);
  var vlast = vSh.getLastRow();
  var meta = {};
  if (vlast >= 2) {
    var vv = vSh.getRange(2, 1, vlast - 1, vSh.getLastColumn()).getValues();
    vv.forEach(function (r) {
      var vid = String(r[vMap['video_id'] - 1] || '').trim(); if (!vid) return;
      var pub = r[vMap['公開日時'] - 1];
      var t = pub ? new Date(pub).getTime() : 0;
      if (t && t >= cutoff) meta[vid] = {
        videoId: vid,
        channelId: String(r[vMap['channel_id'] - 1] || '').trim(),
        title: r[vMap['タイトル'] - 1] || '',
        isShort: r[vMap['isShort'] - 1] || '',
        publishedAt: pub,
        frameText: r[vMap['焼き込み文字'] - 1] || '',   // 代表フレームの焼き込み文字(未取得なら空)
        panelDesc: r[vMap['コマ要約'] - 1] || '',       // コマ画像の中身の要約(未取得なら空)
        frameAt: r[vMap['フレーム取得日'] - 1] || ''
      };
    });
  }

  // チャンネル名・登録者数。登録者数非公開/未取得はnullのまま返す。
  var chSh = compSheet_(COMP_CH_SHEET, COMP_CH_HEADERS);
  var chMap = headerMap_(chSh);
  var chlast = chSh.getLastRow();
  var channels = {};
  if (chlast >= 2) {
    var cv = chSh.getRange(2, 1, chlast - 1, chSh.getLastColumn()).getValues();
    cv.forEach(function (r) {
      var cid = String(r[chMap['channel_id'] - 1] || '').trim(); if (!cid) return;
      var rawSubs = r[chMap['登録者数'] - 1];
      var subs = rawSubs === '' || rawSubs == null ? null : Number(rawSubs);
      channels[cid] = {
        name: String(r[chMap['チャンネル名'] - 1] || ''),
        subscriberCount: isFinite(subs) ? subs : null
      };
    });
  }

  // video_id×暦日へ正規化。同日再実行はその日の最終値だけを使い、欠測日は経過日数で割って1日平均へ直す。
  var dSh = compSheet_(COMP_DAILY_SHEET, COMP_DAILY_HEADERS);
  var dlast = dSh.getLastRow();
  var daily = {};
  if (dlast >= 2) {
    var dv = dSh.getRange(2, 1, dlast - 1, COMP_DAILY_HEADERS.length).getValues();
    dv.forEach(function (r) {
      var vid = String(r[1] || '').trim(); if (!vid || !meta[vid]) return;
      var views = r[3] === '' || r[3] == null ? null : Number(r[3]);
      var day = compDayKey_(r[0], tz);
      if (views == null || !isFinite(views) || !day) return;
      if (!daily[vid]) daily[vid] = {};
      daily[vid][day] = views;
    });
  }

  var out = [];
  Object.keys(meta).forEach(function (vid) {
    var m = meta[vid], c = channels[m.channelId] || {};
    var byDay = daily[vid] || {};
    var dayKeys = Object.keys(byDay).sort();
    var lastDay = dayKeys.length ? dayKeys[dayKeys.length - 1] : '';
    var prevDay = dayKeys.length >= 2 ? dayKeys[dayKeys.length - 2] : '';
    var measurementDays = prevDay ? compDaysBetween_(prevDay, lastDay) : null;
    var totalViews = lastDay ? byDay[lastDay] : null;
    var speed = prevDay ? Math.round((byDay[lastDay] - byDay[prevDay]) / measurementDays) : null;
    out.push({
      title: m.title,
      isShort: m.isShort,
      speed: speed,
      features: compTitleFeatures_([m.title]),
      videoId: m.videoId,
      channelId: m.channelId,
      channelName: c.name || '',
      subscriberCount: c.subscriberCount == null ? null : c.subscriberCount,
      totalViews: totalViews,
      publishedAt: m.publishedAt,
      measurementDays: measurementDays,
      snapshotDate: lastDay,
      frameText: m.frameText,
      panelDesc: m.panelDesc,
      frameAt: m.frameAt
    });
  });
  out.sort(function (a, b) {
    var aHas = typeof a.speed === 'number', bHas = typeof b.speed === 'number';
    if (aHas !== bHas) return bHas ? 1 : -1;
    if (aHas && a.speed !== b.speed) return b.speed - a.speed;
    var av = typeof a.totalViews === 'number' ? a.totalViews : -1;
    var bv = typeof b.totalViews === 'number' ? b.totalViews : -1;
    return (bv - av) || String(a.videoId).localeCompare(String(b.videoId));
  });
  return { ok: true, days: days, count: Math.min(out.length, top), titles: out.slice(0, top) };
}
