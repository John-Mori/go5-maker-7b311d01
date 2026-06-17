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

    var title = body.title || '';
    var postUrl = body.postUrl || '';
    var affiliateUrl = body.affiliateUrl || '';

    var shortUrl = '', bitlyId = '';
    if (postUrl) {
      var r = bitlyShorten_(postUrl);
      shortUrl = r.link;
      bitlyId = r.id;
    }

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

    return jsonOut_({ ok: true, shortUrl: shortUrl, bitlyId: bitlyId });
  } catch (err) {
    return jsonOut_({ ok: false, error: String(err) });
  }
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
