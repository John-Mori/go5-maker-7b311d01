/**
 * コード.gs — 5秒動画メーカー：投稿記録＆クリック/反応集計（Google Apps Script Web App）
 *
 * 役割：
 *   1) クライアント(bluesky.js)から {op,videoId,channel,title,postUrl,affiliateUrl,workUrl,hashtags,postUri,shortUrl,testMode} を受け取る(doPost)
 *   2) videoId(背骨ID)をキーに「記録_ch1 / 記録_ch2」へ upsert（重複行を作らない・列名マッピング）。
 *      短縮URLはフロント生成(da.gd/link-worker)を優先、無い経路のみ GAS が da.gd で短縮。
 *   3) refreshEngagement()（毎時）で Bluesky反応(いいね/リポスト/返信)を更新
 *   4) Phase5：無人予約投稿（runReservations / 5分トリガー）
 *   ※ Bitly は全廃（無料枠オーバーの主因かつ冗長＝共有されず計測不能）。クリック計測は link-worker(KV) に一本化する方針。
 *      テンプレの 'Bitly_ID'/'Bitlyクリック' 列は当面温存（未使用。将来 link-worker クリックへ転用可）。
 *
 * 前提：記録先スプレッドシートは「動画記録分析テンプレート.xlsx」を取り込んだもの
 *   （記録_ch1 / 記録_ch2 / 集計 / 設定、名前付き範囲 Holidays を含む）。
 * スクリプトプロパティ：
 *   SHEET_ID（記録先スプレッドシートID・必須）／ BSKY_HANDLE / BSKY_APP_PW（無人予約に使用）
 *   ※ BITLY_TOKEN は不要（Bitly全廃）。設定が残っていても未使用。
 *   ※ SHARED_SECRET は設定しないこと（現クライアントは送らないため、設定すると弾かれる）
 */

// 記録シートの列ヘッダー（テンプレートと完全一致・この順序）。新規作成時のヘッダーにも使う。
var HEADERS40 = [
  'post_id','投稿日時','曜日','day-type','時間帯スロット','特別期間(手動)','ジャンル','題名(コメント)',
  'サムネ/フック種別(A/B)','CTA・リンク提示方法','Blueskyラベル','作品cid','YouTube動画URL','短縮URL',
  'インプレッション','インプCTR%','視聴回数','平均視聴維持率%','いいね','リポスト','返信','フォロー増','開封数',
  'FANZA発生成約','FANZA確定成約','発生報酬¥','確定報酬¥','承認率%','リンククリック率%','CVR発生%','CVR確定%',
  'EPC発生¥','EPC確定¥','RPM(¥/1000再生)','post_uri','クリック更新日時','反応更新日時'
];
var CH_SHEETS = ['月詠み','宵桜艶帖'];
// 再デプロイ確認用バージョン（中身を変えたら上げる）。<exec URL>?ping=1 で確認できる。
var GAS_VERSION = '2026-06-29B（シート名変更: 記録_ch1→月詠み / 記録_ch2→宵桜艶帖）';

function prop_(k) { return PropertiesService.getScriptProperties().getProperty(k); }
function jsonOut_(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }
function openSS_() {
  var id = prop_('SHEET_ID');
  var ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('スプレッドシートが見つかりません（SHEET_ID を設定してください）');
  return ss;
}
function sheetName_(channel) { return (channel === 'acc2') ? '宵桜艶帖' : '月詠み'; }
function getChannelSheet_(channel) {
  var ss = openSS_(); var name = sheetName_(channel);
  var sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); sh.appendRow(HEADERS40); }
  else if (sh.getLastRow() === 0) { sh.appendRow(HEADERS40); }
  return sh;
}
function headerMap_(sh) {
  var h = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0], m = {};
  for (var i = 0; i < h.length; i++) { if (h[i] !== '' && h[i] != null) m[h[i]] = i + 1; }
  return m;
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  // ★再デプロイ確認用：<exec URL>?ping=1 を開くと、今“動いている”コードのバージョンが見える。
  //   再デプロイが成功していれば下の GAS_VERSION が返る。古い値や別物なら未反映。
  if (p.ping) {
    return jsonOut_({ ok: true, version: GAS_VERSION, now: new Date().toISOString(),
      bitly: 'removed', features: ['upsert', 'testMode', 'da.gd', 'link-worker-clicks'] });
  }
  // JSONP：ブラウザはGASのPOST応答をCORSで読めないため、callback 付きGETで取得する。
  if (p.callback) {
    var out;
    try {
      var ch = p.channel || 'acc1';
      if (p.action === 'history') out = { ok: true, items: historyItems_(ch, parseInt(p.limit || '40', 10)) };
      else if (p.action === 'delete') out = { ok: true, deleted: deleteRecord_(ch, p.postUri || '', p.short || '') };
      else out = { ok: true, shortUrl: p.postUri ? lookupShortByUri_(ch, p.postUri) : '' }; // 既定＝action=short
    } catch (err) { out = { ok: false, error: String(err) }; }
    return ContentService.createTextOutput(p.callback + '(' + JSON.stringify(out) + ')')
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
  return jsonOut_({ ok: true, service: 'go5-maker recorder v2 (2ch)' });
}
// 指定 post_uri の行から短縮URLを返す（読み取りのみ）。
function lookupShortByUri_(channel, postUri) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return '';
  var uc = map['post_uri'], sc = map['短縮URL']; if (!uc || !sc) return '';
  var uris = sh.getRange(2, uc, last - 1, 1).getValues();
  for (var i = uris.length - 1; i >= 0; i--) {  // 新しい順に探す
    if (String(uris[i][0]) === String(postUri)) return String(sh.getRange(i + 2, sc).getValue() || '');
  }
  return '';
}
// チャンネル別の投稿履歴（新しい順・読み取りのみ）。
function historyItems_(channel, limit) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return [];
  var dCol = map['投稿日時'], tCol = map['題名(コメント)'], sCol = map['短縮URL'], uCol = map['post_uri'];
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
  var items = [];
  for (var i = 0; i < vals.length; i++) {
    var row = vals[i];
    var d = dCol ? row[dCol - 1] : '', uri = uCol ? row[uCol - 1] : '', short = sCol ? row[sCol - 1] : '';
    if (!d && !uri && !short) continue; // 空行スキップ
    var ds = '';
    try { if (d) ds = Utilities.formatDate(new Date(d), tz, 'MM/dd HH:mm'); } catch (e) {}
    items.push({
      postUri: String(uri || ''), title: String(tCol ? row[tCol - 1] : ''),
      date: ds, shortUrl: String(short || ''), postUrl: ''
    });
  }
  items.reverse(); // 新しい順
  return items.slice(0, limit > 0 ? limit : 40);
}
// 1件削除（行の内容をクリア＝再利用可。行は詰めない＝集計の整合を保つ）。post_uri優先、無ければ短縮URLで一致。
function deleteRecord_(channel, postUri, short) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return 0;
  var col = postUri ? map['post_uri'] : map['短縮URL'];
  var want = postUri || short; if (!col || !want) return 0;
  var vals = sh.getRange(2, col, last - 1, 1).getValues(), cleared = 0;
  for (var i = 0; i < vals.length; i++) {
    if (String(vals[i][0]) === String(want)) { sh.getRange(i + 2, 1, 1, sh.getLastColumn()).clearContent(); cleared++; }
  }
  return cleared;
}

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var need = prop_('SHARED_SECRET');
    if (need && body.secret !== need) return jsonOut_({ ok: false, error: 'bad_secret' });
    if (body.type === 'reserve') return handleReserve_(body);
    // テストモード：シートには一切書かない（Bluesky実投稿はフロント側で実施）。
    if (body.testMode === true || body.testMode === 'true') return jsonOut_({ ok: true, testMode: true });
    var r = writeRecord_(body.channel || 'acc1', {
      videoId: body.videoId || '',   // 背骨ID。あれば post_id に採用＋同ID行へ upsert（重複行を作らない）
      title: body.title || '', postUrl: body.postUrl || '', affiliateUrl: body.affiliateUrl || '',
      workUrl: body.workUrl || '', hashtags: body.hashtags || '', postUri: body.postUri || '',
      youtubeUrl: body.youtube_url || ''   // ウィザードのYouTube手動ゲートから（同IDの行へ後追いupsert）
    });
    return jsonOut_({ ok: true, shortUrl: r.shortUrl, row: r.row });
  } catch (err) {
    return jsonOut_({ ok: false, error: String(err) });
  }
}

// cid 抽出（作品URL の cid= か、アフィリンクの lurl をデコードして cid=）
function extractCid_(url) {
  if (!url) return '';
  var m = String(url).match(/cid=([^/?&\s]+)/);
  if (m) return m[1];
  var lm = String(url).match(/[?&]lurl=([^&]+)/);
  if (lm) { try { var c = decodeURIComponent(lm[1]).match(/cid=([^/?&\s]+)/); if (c) return c[1]; } catch (e) {} }
  return '';
}
function extractHashtags_(t) { var m = String(t || '').match(/#[^\s#]+/g); return m ? m.join(' ') : ''; }

// 1始まり列番号 → Excel列文字（A/B/.../Z/AA/AB/...）。動的に列参照を組み立てるために使う。
function columnLetter_(n) {
  if (!n || n < 1) return '';
  var s = '';
  while (n > 0) { n--; s = String.fromCharCode(65 + n % 26) + s; n = Math.floor(n / 26); }
  return s;
}

// 計算列の数式（行番号 r に合わせる）。列文字は headerMap_ から動的に取得するため列の増減に強い。
function setComputed_(sh, map, r) {
  function set(h, f) { if (map[h]) sh.getRange(r, map[h]).setFormula(f); }
  set('曜日', '=IF($B' + r + '="","",CHOOSE(WEEKDAY($B' + r + '),"日","月","火","水","木","金","土"))');
  set('day-type', '=IF($B' + r + '="","",IF(OR(WEEKDAY($B' + r + ',2)>=6,COUNTIF(Holidays,INT($B' + r + '))>0),"土日祝",IF(OR(WEEKDAY($B' + r + '+1,2)>=6,COUNTIF(Holidays,INT($B' + r + ')+1)>0),"休前日","平日")))');
  set('時間帯スロット', '=IF($B' + r + '="","",IF(HOUR($B' + r + ')<5,"深夜",IF(HOUR($B' + r + ')<11,"朝",IF(HOUR($B' + r + ')<15,"昼",IF(HOUR($B' + r + ')<19,"夕","夜")))))');
  var cClick  = columnLetter_(map['開封数'] || map['Bitlyクリック']); // 開封数（旧称Bitlyクリック）
  var cViews  = columnLetter_(map['視聴回数']);
  var cFhap   = columnLetter_(map['FANZA発生成約']);
  var cFok    = columnLetter_(map['FANZA確定成約']);
  var cRhap   = columnLetter_(map['発生報酬¥']);
  var cRok    = columnLetter_(map['確定報酬¥']);
  if (cFok && cFhap)    set('承認率%',        '=IFERROR(' + cFok   + r + '/' + cFhap  + r + ',"")');
  if (cClick && cViews) set('リンククリック率%','=IFERROR(' + cClick + r + '/' + cViews + r + ',"")');
  if (cFhap && cClick)  set('CVR発生%',        '=IFERROR(' + cFhap  + r + '/' + cClick + r + ',"")');
  if (cFok && cClick)   set('CVR確定%',        '=IFERROR(' + cFok   + r + '/' + cClick + r + ',"")');
  if (cRhap && cClick)  set('EPC発生¥',        '=IFERROR(' + cRhap  + r + '/' + cClick + r + ',"")');
  if (cRok && cClick)   set('EPC確定¥',        '=IFERROR(' + cRok   + r + '/' + cClick + r + ',"")');
  if (cRok && cViews)   set('RPM(¥/1000再生)', '=IFERROR(' + cRok   + r + '/' + cViews + r + '*1000,"")');
}

// 純粋関数：post_id 列の値配列(2行目以降)と videoId から upsert 先の行番号(2始まり)を返す。
// 一致が無ければ 0。videoId 空なら 0（=従来の空行再利用/追記へ）。
// ※ tests/test_record_upsert.js に同一ロジックのミラーあり（変更時は両方を揃える）。
function upsertRowOf_(postIdCol, videoId) {
  if (!videoId) return 0;
  for (var j = 0; j < postIdCol.length; j++) { if (String(postIdCol[j]) === String(videoId)) return j + 2; }
  return 0;
}

// 1投稿を記録（短縮失敗でも記録は残す）。doPost・無人予約の両方から使用。
// videoId（背骨ID）があれば post_id をそれにし、同ID行へ upsert（重複行を作らない・変更フィールドのみ更新）。
// videoId 無し＝完全に従来動作（後方互換）。
function writeRecord_(channel, f) {
  // 短縮URL：フロントが生成済みなら優先（da.gd/link-worker＝実際に共有するURL）。
  // 無い経路（無人予約・旧クライアント）だけ GAS が da.gd で短縮（1投稿1回・トークン不要・軽量）。
  // ※Bitlyは無料枠オーバーの主因かつ冗長（共有されず計測不能）なため全廃。
  var shortUrl = f.shortUrl || '';
  if (!shortUrl && f.postUrl) shortUrl = daGdShorten_(f.postUrl);
  var sh = getChannelSheet_(channel);
  var map = headerMap_(sh);
  var dcol = map['投稿日時'] || 2;
  var pidc = map['post_id'] || 1;
  var last = sh.getLastRow();
  var now = new Date();
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';

  // 行キー：videoId があればそれ、無ければ従来の時刻ベース。
  var pid = f.videoId || (channel + '-' + Utilities.formatDate(now, tz, 'yyyyMMdd-HHmm'));

  // upsert：同一 videoId の既存行を探す。
  var target = 0;
  if (f.videoId && last >= 2) {
    target = upsertRowOf_(sh.getRange(2, pidc, last - 1, 1).getValues().map(function (r) { return r[0]; }), f.videoId);
  }
  var isNewRow = false;
  if (!target) {
    // 従来通り：空の投稿日時行を再利用、無ければ末尾に追加。
    if (last >= 2) {
      var vals = sh.getRange(2, dcol, last - 1, 1).getValues();
      for (var i = 0; i < vals.length; i++) { if (vals[i][0] === '' || vals[i][0] === null) { target = i + 2; break; } }
    }
    if (!target) { target = last + 1; }
    isNewRow = true;
  }

  setComputed_(sh, map, target); // テンプレ既存行は同じ式で上書き＝無害。新規行にも式を付与。
  function put(h, v) { if (map[h]) sh.getRange(target, map[h]).setValue(v); }
  // upsert更新時に既存値を空で潰さないよう、値があるものだけ書く。
  function putIf(h, v) { if (map[h] && v !== '' && v !== null && v !== undefined) sh.getRange(target, map[h]).setValue(v); }

  put('post_id', pid);
  // 投稿日時は「新規行」か「投稿URLを伴う記録」の時だけ。YouTube URLだけの後追いupsertでは上書きしない。
  if (isNewRow || f.postUrl) put('投稿日時', now);
  putIf('題名(コメント)', f.title || '');
  putIf('作品cid', extractCid_(f.workUrl || f.affiliateUrl || ''));
  putIf('短縮URL', shortUrl);
  putIf('YouTube動画URL', f.youtubeUrl || '');
  putIf('post_uri', f.postUri || '');
  // カウンタは新規行のみ0初期化（upsert更新で既存のいいね数等を0で潰さない）。
  if (isNewRow) { put('いいね', 0); put('リポスト', 0); put('返信', 0); }
  return { shortUrl: shortUrl, row: target };
}

// ---- 短縮URL（da.gd・トークン不要・1投稿1回だけ。失敗時は空＝長いURLのまま記録） ----
//   ※Bitlyは全廃（無料枠オーバーの主因かつ冗長）。クリック計測は link-worker(KV) 側に一本化する方針。
function daGdShorten_(longUrl) {
  if (!longUrl) return '';
  try {
    var res = UrlFetchApp.fetch('https://da.gd/s?url=' + encodeURIComponent(longUrl), { muteHttpExceptions: true });
    if (res.getResponseCode() >= 300) return '';
    var t = String(res.getContentText() || '').trim();
    return /^https?:\/\//.test(t) ? t : '';
  } catch (e) { return ''; }
}

// ---- link-worker 開封数の取り込み（①計測の見える化） ----
//   YT説明欄に貼る短縮URL（go5-short/<code>）の「開かれた回数」を /api/stats から取得し、
//   テンプレ列「Bitlyクリック」（＝今後は link-worker の開封数の意味）に毎時反映する。
//   ※列名はテンプレ互換のため変えない（意味だけ Bitly→開封数 に変更）。
var SHORT_WORKER_URL = 'https://go5-short.trustsignalbot.workers.dev';
function shortSecret_() { return prop_('SHORT_SHARED_SECRET') || 'daremogamewoubawareteikukimihakanpekidekyukyokunoidol'; }
// go5-short のURLから末尾コードを抽出（別ホスト＝da.gd等なら ''）。
function codeFromShort_(url) {
  var m = String(url || '').match(/^https?:\/\/[^/]*go5-short[^/]*\/([0-9A-Za-z]+)/);
  return m ? m[1] : '';
}
function workerClicks_(code) {
  if (!code) return null;
  try {
    var u = SHORT_WORKER_URL.replace(/\/+$/, '') + '/api/stats?code=' + encodeURIComponent(code) + '&secret=' + encodeURIComponent(shortSecret_());
    var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
    if (res.getResponseCode() >= 300) return null;
    var d = JSON.parse(res.getContentText() || '{}');
    return (d && d.ok && typeof d.clicks === 'number') ? d.clicks : null;
  } catch (e) { return null; }
}
// 毎時：直近200行のうち短縮URLが go5-short のものだけ開封数を更新（軽量・クォータ安全）。
function refreshClicks() {
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow();
    var clickCol = map['開封数'] || map['Bitlyクリック']; // 新列名「開封数」、既存シートは旧名で互換
    if (last < 2 || !map['短縮URL'] || !clickCol) return;
    var start = Math.max(2, last - 199), n = last - start + 1;
    var urls = sh.getRange(start, map['短縮URL'], n, 1).getValues();
    for (var i = 0; i < urls.length; i++) {
      var code = codeFromShort_(urls[i][0]); if (!code) continue;
      var c = workerClicks_(code);
      if (c !== null) {
        sh.getRange(start + i, clickCol).setValue(c);
        if (map['クリック更新日時']) sh.getRange(start + i, map['クリック更新日時']).setValue(new Date());
      }
      Utilities.sleep(100);
    }
  });
}

// ---- Bluesky反応(いいね/リポスト/返信)の定期更新（毎時トリガー）。公開API getPosts を25件ずつ ----
function refreshEngagement() {
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow();
    if (last < 2 || !map['post_uri']) return;
    var uris = sh.getRange(2, map['post_uri'], last - 1, 1).getValues();
    var pending = [];
    for (var i = 0; i < uris.length; i++) { var u = uris[i][0]; if (u) pending.push({ row: i + 2, uri: String(u) }); }
    for (var b = 0; b < pending.length; b += 25) {
      var slice = pending.slice(b, b + 25);
      var q = slice.map(function (x) { return 'uris=' + encodeURIComponent(x.uri); }).join('&');
      try {
        var res = UrlFetchApp.fetch('https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts?' + q, { muteHttpExceptions: true });
        if (res.getResponseCode() >= 300) continue;
        var data = JSON.parse(res.getContentText() || '{}'); var byUri = {};
        (data.posts || []).forEach(function (p) { byUri[p.uri] = p; });
        slice.forEach(function (x) {
          var p = byUri[x.uri]; if (!p) return;
          if (map['いいね']) sh.getRange(x.row, map['いいね']).setValue(p.likeCount || 0);
          if (map['リポスト']) sh.getRange(x.row, map['リポスト']).setValue(p.repostCount || 0);
          if (map['返信']) sh.getRange(x.row, map['返信']).setValue(p.replyCount || 0);
          if (map['反応更新日時']) sh.getRange(x.row, map['反応更新日時']).setValue(new Date());
        });
      } catch (e) {}
      Utilities.sleep(200);
    }
  });
}

// 初回1回：毎時トリガーを登録。
//   refreshClicks＝link-worker 開封数の取り込み（旧Bitly版とは別物・同名で再利用）。
//   refreshEngagement＝Bluesky反応(いいね/リポスト/返信)。
//   再実行で既存トリガーを掃除してから貼り直す（旧Bitly版 refreshClicks も消える）。
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var f = t.getHandlerFunction();
    if (f === 'refreshClicks' || f === 'refreshEngagement') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('refreshClicks').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('refreshEngagement').timeBased().everyHours(1).create();
}

// ============================================================
// Phase5：無人予約投稿（タブを閉じても、時間トリガーが自動投稿）
//   追加プロパティ：BSKY_HANDLE / BSKY_APP_PW。画像は base64→ドライブ一時保存→投稿後ゴミ箱。
// ============================================================
var RES_SHEET = '予約';
var RES_HEADERS = ['予約ID', '予約日時', '本文', '画像fileId', 'slot_id', 'ステータス', '結果URI', '結果URL', '投稿日時', 'エラー', 'channel'];
var RCOL = { id: 1, when: 2, text: 3, img: 4, slot: 5, status: 6, uri: 7, url: 8, postedAt: 9, error: 10, channel: 11 };

function getResSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName(RES_SHEET) || ss.insertSheet(RES_SHEET);
  if (sh.getLastRow() === 0) sh.appendRow(RES_HEADERS);
  return sh;
}
function getDriveFolder_() {
  var name = 'go5-reservations';
  var it = DriveApp.getFoldersByName(name);
  return it.hasNext() ? it.next() : DriveApp.createFolder(name);
}
function dataUrlToBlob_(dataUrl) {
  var m = String(dataUrl).match(/^data:([^;]+);base64,(.*)$/);
  var type = m ? m[1] : 'image/jpeg', data = m ? m[2] : dataUrl;
  return Utilities.newBlob(Utilities.base64Decode(data), type);
}
function handleReserve_(body) {
  var sh = getResSheet_(); var imgId = '';
  if (body.image) {
    var blob = dataUrlToBlob_(body.image).setName('rsv_' + new Date().getTime() + '.jpg');
    imgId = getDriveFolder_().createFile(blob).getId();
  }
  var id = Utilities.getUuid(), row = [];
  row[RCOL.id - 1] = id; row[RCOL.when - 1] = body.scheduled_at || ''; row[RCOL.text - 1] = body.text || '';
  row[RCOL.img - 1] = imgId; row[RCOL.slot - 1] = body.slot_id || ''; row[RCOL.status - 1] = 'pending';
  row[RCOL.uri - 1] = ''; row[RCOL.url - 1] = ''; row[RCOL.postedAt - 1] = ''; row[RCOL.error - 1] = '';
  row[RCOL.channel - 1] = body.channel || 'acc1';
  sh.appendRow(row);
  return jsonOut_({ ok: true, id: id });
}
function runReservations() {
  var sh = getResSheet_(); var last = sh.getLastRow(); if (last < 2) return;
  var rows = sh.getRange(2, 1, last - 1, RES_HEADERS.length).getValues();
  var now = new Date();
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][RCOL.status - 1] !== 'pending') continue;
    var when = new Date(rows[i][RCOL.when - 1]);
    if (isNaN(when.getTime()) || when > now) continue;
    sh.getRange(i + 2, RCOL.status).setValue('posting'); SpreadsheetApp.flush();
    try {
      var imgId = rows[i][RCOL.img - 1];
      var blob = imgId ? DriveApp.getFileById(imgId).getBlob() : null;
      var text = rows[i][RCOL.text - 1];
      var ch = rows[i][RCOL.channel - 1] || 'acc1';
      var res = bskyPost_(text, blob);
      sh.getRange(i + 2, RCOL.status).setValue('posted');
      sh.getRange(i + 2, RCOL.uri).setValue(res.uri);
      sh.getRange(i + 2, RCOL.url).setValue(res.postUrl);
      sh.getRange(i + 2, RCOL.postedAt).setValue(new Date());
      try {
        writeRecord_(ch, {
          title: (String(text).split('\n')[0] || ''), postUrl: res.postUrl,
          affiliateUrl: (String(text).match(/https?:\/\/[^\s]+/) || [''])[0],
          workUrl: '', hashtags: extractHashtags_(text), postUri: res.uri
        });
      } catch (e) {}
      if (imgId) { try { DriveApp.getFileById(imgId).setTrashed(true); } catch (e) {} }
    } catch (err) {
      sh.getRange(i + 2, RCOL.status).setValue('error');
      sh.getRange(i + 2, RCOL.error).setValue(String(err));
    }
    Utilities.sleep(300);
  }
}

// Bluesky 投稿（サーバー側＝GASのアプリパスワードで投稿）
function bskyPost_(text, imageBlob) {
  var handle = prop_('BSKY_HANDLE'), pw = prop_('BSKY_APP_PW');
  if (!handle || !pw) throw new Error('BSKY_HANDLE / BSKY_APP_PW 未設定');
  var svc = 'https://bsky.social';
  var s = JSON.parse(UrlFetchApp.fetch(svc + '/xrpc/com.atproto.server.createSession', {
    method: 'post', contentType: 'application/json',
    payload: JSON.stringify({ identifier: String(handle).replace(/^@/, ''), password: pw }), muteHttpExceptions: true
  }).getContentText());
  if (!s.accessJwt) throw new Error('Blueskyログイン失敗');
  var embed = null;
  if (imageBlob) {
    var up = JSON.parse(UrlFetchApp.fetch(svc + '/xrpc/com.atproto.repo.uploadBlob', {
      method: 'post', contentType: imageBlob.getContentType() || 'image/jpeg',
      headers: { Authorization: 'Bearer ' + s.accessJwt }, payload: imageBlob.getBytes(), muteHttpExceptions: true
    }).getContentText());
    if (up.blob) embed = { '$type': 'app.bsky.embed.images', images: [{ alt: (String(text).split('\n')[0] || ''), image: up.blob }] };
  }
  var record = { '$type': 'app.bsky.feed.post', text: text, createdAt: new Date().toISOString(), langs: ['ja'] };
  var facets = detectFacets_(text);
  if (facets.length) record.facets = facets;
  if (embed) record.embed = embed;
  var res = JSON.parse(UrlFetchApp.fetch(svc + '/xrpc/com.atproto.repo.createRecord', {
    method: 'post', contentType: 'application/json', headers: { Authorization: 'Bearer ' + s.accessJwt },
    payload: JSON.stringify({ repo: s.did, collection: 'app.bsky.feed.post', record: record }), muteHttpExceptions: true
  }).getContentText());
  var rkey = String(res.uri || '').split('/').pop();
  return { uri: res.uri || '', postUrl: (s.handle && rkey) ? ('https://bsky.app/profile/' + s.handle + '/post/' + rkey) : '' };
}

// 本文中の URL(#link) とハッシュタグ(#tag) の facet（index は UTF-8 バイトオフセット）
function byteLen_(s) { return Utilities.newBlob(String(s)).getBytes().length; }
function detectFacets_(text) {
  text = String(text || ''); var facets = [], used = [], m;
  var ure = /https?:\/\/[^\s]+/g;
  while ((m = ure.exec(text))) {
    var url = m[0].replace(/[.,;:!?。、！？）)】」』]+$/, '');
    var s = m.index, e = s + url.length; used.push([s, e]);
    facets.push({ index: { byteStart: byteLen_(text.slice(0, s)), byteEnd: byteLen_(text.slice(0, e)) },
      features: [{ '$type': 'app.bsky.richtext.facet#link', uri: url }] });
  }
  var tre = /(^|\s)(#[^\s#]+)/g, t;
  while ((t = tre.exec(text))) {
    var hash = t[2].replace(/[.,;:!?。、！？）)】」』]+$/, '');
    if (hash.length < 2) continue;
    var ts = t.index + t[1].length, te = ts + hash.length;
    if (used.some(function (r) { return ts < r[1] && te > r[0]; })) continue;
    facets.push({ index: { byteStart: byteLen_(text.slice(0, ts)), byteEnd: byteLen_(text.slice(0, te)) },
      features: [{ '$type': 'app.bsky.richtext.facet#tag', tag: hash.slice(1) }] });
  }
  facets.sort(function (a, b) { return a.index.byteStart - b.index.byteStart; });
  return facets;
}

// 初回1回：予約を5分ごとに自動投稿するトリガーを登録
function setupReservationTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runReservations') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runReservations').timeBased().everyMinutes(5).create();
}
