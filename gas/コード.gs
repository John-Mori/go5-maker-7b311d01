/**
 * コード.gs — 5秒動画メーカー：投稿記録＆Bitlyクリック集計（Google Apps Script Web App）
 *
 * 役割：
 *   1) クライアント（bluesky.js）から {title, postUrl, affiliateUrl, secret} を受け取る（doPost）
 *   2) Bitly で postUrl を短縮（＝クリック集計の対象。アフィリンクには一切触れない）
 *   3) スプレッドシートに1行追記：題名（動画タイトル）／各URL／クリック数
 *   4) refreshClicks()（1時間ごとの時間トリガー）で Bitly のクリック数を取得して更新
 *
 * セットアップは同フォルダ「セットアップ手順.md」を参照。
 * スクリプトプロパティ：
 *   BITLY_TOKEN  （必須）Bitly のアクセストークン
 *   SHARED_SECRET（任意）クライアントの「共有シークレット」と一致させると、他人のPOSTを弾ける
 *   SHEET_ID     （任意）記録先スプレッドシートID。未設定ならこのスクリプトに紐づくシートを使用
 */

var SHEET_NAME = '記録';
var HEADERS = ['記録日時', '題名(動画タイトル)', 'アフィリンク', '投稿URL', '短縮URL(投稿)', 'Bitly_ID', 'クリック数', 'クリック更新日時'];
// 列番号（1始まり）
var COL = { date: 1, title: 2, affiliate: 3, postUrl: 4, shortUrl: 5, bitlyId: 6, clicks: 7, clicksAt: 8 };

function prop_(k) { return PropertiesService.getScriptProperties().getProperty(k); }

function getSheet_() {
  var sheetId = prop_('SHEET_ID');
  var ss = sheetId ? SpreadsheetApp.openById(sheetId) : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('スプレッドシートが見つかりません（SHEET_ID を設定するか、シートにバインドして実行してください）');
  var sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
  if (sh.getLastRow() === 0) sh.appendRow(HEADERS);
  return sh;
}

function jsonOut_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// 動作確認用（ブラウザでURLを開くと {ok:true} が返る）
function doGet() {
  return jsonOut_({ ok: true, service: 'go5-maker recorder' });
}

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');

    var need = prop_('SHARED_SECRET');
    if (need && body.secret !== need) return jsonOut_({ ok: false, error: 'bad_secret' });

    // Phase5：無人予約投稿の登録（type='reserve'）
    if (body.type === 'reserve') return handleReserve_(body);

    var r = recordPost_(body.title || '', body.postUrl || '', body.affiliateUrl || '');
    return jsonOut_({ ok: true, shortUrl: r.shortUrl, bitlyId: r.bitlyId });
  } catch (err) {
    return jsonOut_({ ok: false, error: String(err) });
  }
}

// 1投稿を「記録」シートに追記（Bitly短縮は失敗しても投稿記録は残す）。doPost・予約投稿の両方から使用。
function recordPost_(title, postUrl, affiliateUrl) {
  var shortUrl = '', bitlyId = '';
  if (postUrl) { try { var r = bitlyShorten_(postUrl); shortUrl = r.link; bitlyId = r.id; } catch (e) {} }
  var sh = getSheet_();
  var row = [];
  row[COL.date - 1] = new Date();
  row[COL.title - 1] = title;
  row[COL.affiliate - 1] = affiliateUrl;
  row[COL.postUrl - 1] = postUrl;
  row[COL.shortUrl - 1] = shortUrl;
  row[COL.bitlyId - 1] = bitlyId;
  row[COL.clicks - 1] = 0;
  row[COL.clicksAt - 1] = '';
  sh.appendRow(row);
  return { shortUrl: shortUrl, bitlyId: bitlyId };
}

// ---- Bitly ----
function bitlyShorten_(longUrl) {
  var token = prop_('BITLY_TOKEN');
  if (!token) throw new Error('BITLY_TOKEN が未設定です');
  var res = UrlFetchApp.fetch('https://api-ssl.bitly.com/v4/shorten', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token },
    payload: JSON.stringify({ long_url: longUrl }),
    muteHttpExceptions: true
  });
  var data = JSON.parse(res.getContentText() || '{}');
  if (res.getResponseCode() >= 300) throw new Error('Bitly短縮に失敗: ' + (data.message || res.getResponseCode()));
  return { link: data.link, id: data.id }; // id 例: "bit.ly/3xxxxxx"
}

function bitlyClicks_(bitlinkId) {
  var token = prop_('BITLY_TOKEN');
  // units=-1 で全期間の合計クリック数を取得
  var url = 'https://api-ssl.bitly.com/v4/bitlinks/' + encodeURIComponent(bitlinkId) + '/clicks/summary?unit=day&units=-1';
  var res = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + token }, muteHttpExceptions: true });
  if (res.getResponseCode() >= 300) return null;
  var data = JSON.parse(res.getContentText() || '{}');
  return (typeof data.total_clicks === 'number') ? data.total_clicks : null;
}

// ---- クリック数の定期更新（時間トリガーから実行） ----
function refreshClicks() {
  var sh = getSheet_();
  var last = sh.getLastRow();
  if (last < 2) return;
  var ids = sh.getRange(2, COL.bitlyId, last - 1, 1).getValues();
  for (var i = 0; i < ids.length; i++) {
    var id = ids[i][0];
    if (!id) continue;
    var c = bitlyClicks_(id);
    if (c !== null) {
      sh.getRange(i + 2, COL.clicks).setValue(c);
      sh.getRange(i + 2, COL.clicksAt).setValue(new Date());
    }
    Utilities.sleep(200); // レート制限よけ
  }
}

// ---- 初回に1度だけ実行：クリック数を1時間ごとに自動更新するトリガーを登録 ----
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'refreshClicks') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('refreshClicks').timeBased().everyHours(1).create();
}

// ============================================================
// Phase5：無人予約投稿（タブを閉じても、時間トリガーが自動投稿）
//   追加プロパティ：BSKY_HANDLE（例 yourname.bsky.social）／BSKY_APP_PW（アプリパスワード）
//   画像は base64 で受け取り Google ドライブに一時保存→投稿時に取得→投稿後にゴミ箱へ。
// ============================================================
var RES_SHEET = '予約';
var RES_HEADERS = ['予約ID', '予約日時', '本文', '画像fileId', 'slot_id', 'ステータス', '結果URI', '結果URL', '投稿日時', 'エラー'];
var RCOL = { id: 1, when: 2, text: 3, img: 4, slot: 5, status: 6, uri: 7, url: 8, postedAt: 9, error: 10 };

function getResSheet_() {
  var sheetId = prop_('SHEET_ID');
  var ss = sheetId ? SpreadsheetApp.openById(sheetId) : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('スプレッドシートが見つかりません');
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
  var type = m ? m[1] : 'image/jpeg';
  var data = m ? m[2] : dataUrl;
  return Utilities.newBlob(Utilities.base64Decode(data), type);
}

// 予約を登録（クライアントの「無人で予約」から呼ばれる）
function handleReserve_(body) {
  var sh = getResSheet_();
  var imgId = '';
  if (body.image) {
    var blob = dataUrlToBlob_(body.image).setName('rsv_' + new Date().getTime() + '.jpg');
    imgId = getDriveFolder_().createFile(blob).getId();
  }
  var id = Utilities.getUuid();
  var row = [];
  row[RCOL.id - 1] = id;
  row[RCOL.when - 1] = body.scheduled_at || '';
  row[RCOL.text - 1] = body.text || '';
  row[RCOL.img - 1] = imgId;
  row[RCOL.slot - 1] = body.slot_id || '';
  row[RCOL.status - 1] = 'pending';
  row[RCOL.uri - 1] = ''; row[RCOL.url - 1] = ''; row[RCOL.postedAt - 1] = ''; row[RCOL.error - 1] = '';
  sh.appendRow(row);
  return jsonOut_({ ok: true, id: id });
}

// 時間トリガーで実行：期限到来(pending かつ 予約日時<=now)を自動投稿
function runReservations() {
  var sh = getResSheet_();
  var last = sh.getLastRow();
  if (last < 2) return;
  var rows = sh.getRange(2, 1, last - 1, RES_HEADERS.length).getValues();
  var now = new Date();
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][RCOL.status - 1] !== 'pending') continue;
    var when = new Date(rows[i][RCOL.when - 1]);
    if (isNaN(when.getTime()) || when > now) continue;
    sh.getRange(i + 2, RCOL.status).setValue('posting'); SpreadsheetApp.flush(); // 二重投稿防止
    try {
      var imgId = rows[i][RCOL.img - 1];
      var blob = imgId ? DriveApp.getFileById(imgId).getBlob() : null;
      var text = rows[i][RCOL.text - 1];
      var res = bskyPost_(text, blob);
      sh.getRange(i + 2, RCOL.status).setValue('posted');
      sh.getRange(i + 2, RCOL.uri).setValue(res.uri);
      sh.getRange(i + 2, RCOL.url).setValue(res.postUrl);
      sh.getRange(i + 2, RCOL.postedAt).setValue(new Date());
      // 「記録」シートにも残す（必ず記録・検証できるように）
      try { recordPost_((String(text).split('\n')[0] || ''), res.postUrl, (String(text).match(/https?:\/\/[^\s]+/) || [''])[0]); } catch (e) {}
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

// 本文中の URL（#link）とハッシュタグ（#tag）の facet（index は UTF-8 バイトオフセット）
function byteLen_(s) { return Utilities.newBlob(String(s)).getBytes().length; }
function detectFacets_(text) {
  text = String(text || '');
  var facets = [], used = [], m;

  var ure = /https?:\/\/[^\s]+/g;
  while ((m = ure.exec(text))) {
    var url = m[0].replace(/[.,;:!?。、！？）)】」』]+$/, '');
    var s = m.index, e = s + url.length;
    used.push([s, e]);
    facets.push({
      index: { byteStart: byteLen_(text.slice(0, s)), byteEnd: byteLen_(text.slice(0, e)) },
      features: [{ '$type': 'app.bsky.richtext.facet#link', uri: url }]
    });
  }

  var tre = /(^|\s)(#[^\s#]+)/g, t;
  while ((t = tre.exec(text))) {
    var hash = t[2].replace(/[.,;:!?。、！？）)】」』]+$/, '');
    if (hash.length < 2) continue;
    var ts = t.index + t[1].length, te = ts + hash.length;
    var overlap = used.some(function (r) { return ts < r[1] && te > r[0]; });
    if (overlap) continue;
    facets.push({
      index: { byteStart: byteLen_(text.slice(0, ts)), byteEnd: byteLen_(text.slice(0, te)) },
      features: [{ '$type': 'app.bsky.richtext.facet#tag', tag: hash.slice(1) }]
    });
  }

  facets.sort(function (a, b) { return a.index.byteStart - b.index.byteStart; });
  return facets;
}

// 初回に1度だけ実行：予約を5分ごとに自動投稿するトリガーを登録
function setupReservationTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runReservations') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runReservations').timeBased().everyMinutes(5).create();
}
