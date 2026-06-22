/**
 * コード.gs — 5秒動画メーカー：投稿記録＆クリック/反応集計（Google Apps Script Web App）
 *
 * 役割：
 *   1) クライアント(bluesky.js)から {channel,title,postUrl,affiliateUrl,workUrl,hashtags,postUri} を受け取る(doPost)
 *   2) Bitly で postUrl を短縮（=クリック集計対象。アフィリンクには触れない）
 *   3) チャンネル別シート「記録_ch1 / 記録_ch2」へ列名マッピングで1行自動記入
 *   4) refreshClicks()（毎時）で Bitly クリック数、refreshEngagement()（毎時）で Bluesky反応(いいね/リポスト/返信)を更新
 *   5) Phase5：無人予約投稿（runReservations / 5分トリガー）
 *
 * 前提：記録先スプレッドシートは「動画記録分析テンプレート.xlsx」を取り込んだもの
 *   （記録_ch1 / 記録_ch2 / 集計 / 設定、名前付き範囲 Holidays を含む）。
 * スクリプトプロパティ：
 *   BITLY_TOKEN  （短縮URLを使うなら必須）／ SHEET_ID（記録先スプレッドシートID・必須）
 *   BSKY_HANDLE / BSKY_APP_PW（無人予約に使用）
 *   ※ SHARED_SECRET は設定しないこと（現クライアントは送らないため、設定すると弾かれる）
 */

// 記録シートの列ヘッダー（テンプレートと完全一致・この順序）。新規作成時のヘッダーにも使う。
var HEADERS40 = [
  'post_id','投稿日時','曜日','day-type','時間帯スロット','特別期間(手動)','ジャンル','題名(コメント)','ハッシュタグ',
  'サムネ/フック種別(A/B)','CTA・リンク提示方法','Blueskyラベル','作品cid','YouTube動画URL','Bluesky投稿URL','短縮URL',
  'インプレッション','インプCTR%','視聴回数','平均視聴維持率%','いいね','リポスト','返信','フォロー増','Bitlyクリック',
  'FANZA発生成約','FANZA確定成約','発生報酬¥','確定報酬¥','承認率%','リンククリック率%','CVR発生%','CVR確定%',
  'EPC発生¥','EPC確定¥','RPM(¥/1000再生)','Bitly_ID','post_uri','クリック更新日時','反応更新日時'
];
var CH_SHEETS = ['記録_ch1','記録_ch2'];

function prop_(k) { return PropertiesService.getScriptProperties().getProperty(k); }
function jsonOut_(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }
function openSS_() {
  var id = prop_('SHEET_ID');
  var ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('スプレッドシートが見つかりません（SHEET_ID を設定してください）');
  return ss;
}
function sheetName_(channel) { return (channel === 'acc2') ? '記録_ch2' : '記録_ch1'; }
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

function doGet() { return jsonOut_({ ok: true, service: 'go5-maker recorder v2 (2ch)' }); }

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var need = prop_('SHARED_SECRET');
    if (need && body.secret !== need) return jsonOut_({ ok: false, error: 'bad_secret' });
    if (body.type === 'reserve') return handleReserve_(body);
    var r = writeRecord_(body.channel || 'acc1', {
      title: body.title || '', postUrl: body.postUrl || '', affiliateUrl: body.affiliateUrl || '',
      workUrl: body.workUrl || '', hashtags: body.hashtags || '', postUri: body.postUri || ''
    });
    return jsonOut_({ ok: true, shortUrl: r.shortUrl, bitlyId: r.bitlyId });
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

// 計算列の数式（テンプレートと同一・行番号 r に合わせる）。固定の列文字は HEADERS40 の順序前提。
function setComputed_(sh, map, r) {
  function set(h, f) { if (map[h]) sh.getRange(r, map[h]).setFormula(f); }
  set('曜日', '=IF($B' + r + '="","",CHOOSE(WEEKDAY($B' + r + '),"日","月","火","水","木","金","土"))');
  set('day-type', '=IF($B' + r + '="","",IF(OR(WEEKDAY($B' + r + ',2)>=6,COUNTIF(Holidays,INT($B' + r + '))>0),"土日祝",IF(OR(WEEKDAY($B' + r + '+1,2)>=6,COUNTIF(Holidays,INT($B' + r + ')+1)>0),"休前日","平日")))');
  set('時間帯スロット', '=IF($B' + r + '="","",IF(HOUR($B' + r + ')<5,"深夜",IF(HOUR($B' + r + ')<11,"朝",IF(HOUR($B' + r + ')<15,"昼",IF(HOUR($B' + r + ')<19,"夕","夜")))))');
  set('承認率%', '=IFERROR(AA' + r + '/Z' + r + ',"")');
  set('リンククリック率%', '=IFERROR(Y' + r + '/S' + r + ',"")');
  set('CVR発生%', '=IFERROR(Z' + r + '/Y' + r + ',"")');
  set('CVR確定%', '=IFERROR(AA' + r + '/Y' + r + ',"")');
  set('EPC発生¥', '=IFERROR(AB' + r + '/Y' + r + ',"")');
  set('EPC確定¥', '=IFERROR(AC' + r + '/Y' + r + ',"")');
  set('RPM(¥/1000再生)', '=IFERROR(AC' + r + '/S' + r + '*1000,"")');
}

// 1投稿を記録（Bitly短縮は失敗しても記録は残す）。doPost・無人予約の両方から使用。
function writeRecord_(channel, f) {
  var shortUrl = '', bitlyId = '';
  if (f.postUrl) { try { var b = bitlyShorten_(f.postUrl); shortUrl = b.link; bitlyId = b.id; } catch (e) {} }
  var sh = getChannelSheet_(channel);
  var map = headerMap_(sh);
  var dcol = map['投稿日時'] || 2;
  var last = sh.getLastRow();
  var target = 0;
  if (last >= 2) {
    var vals = sh.getRange(2, dcol, last - 1, 1).getValues();
    for (var i = 0; i < vals.length; i++) { if (vals[i][0] === '' || vals[i][0] === null) { target = i + 2; break; } }
  }
  if (!target) target = last + 1;
  setComputed_(sh, map, target); // テンプレ既存行は同じ式で上書き＝無害。新規行にも式を付与。
  var now = new Date();
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  function put(h, v) { if (map[h]) sh.getRange(target, map[h]).setValue(v); }
  put('post_id', channel + '-' + Utilities.formatDate(now, tz, 'yyyyMMdd-HHmm'));
  put('投稿日時', now);
  put('題名(コメント)', f.title || '');
  put('ハッシュタグ', f.hashtags || extractHashtags_(f.title));
  put('作品cid', extractCid_(f.workUrl || f.affiliateUrl || ''));
  put('Bluesky投稿URL', f.postUrl || '');
  put('短縮URL', shortUrl);
  put('いいね', 0); put('リポスト', 0); put('返信', 0); put('Bitlyクリック', 0);
  put('Bitly_ID', bitlyId);
  put('post_uri', f.postUri || '');
  return { shortUrl: shortUrl, bitlyId: bitlyId };
}

// ---- Bitly ----
function bitlyShorten_(longUrl) {
  var token = prop_('BITLY_TOKEN');
  if (!token) throw new Error('BITLY_TOKEN が未設定です');
  var res = UrlFetchApp.fetch('https://api-ssl.bitly.com/v4/shorten', {
    method: 'post', contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + token },
    payload: JSON.stringify({ long_url: longUrl }), muteHttpExceptions: true
  });
  var data = JSON.parse(res.getContentText() || '{}');
  if (res.getResponseCode() >= 300) throw new Error('Bitly短縮に失敗: ' + (data.message || res.getResponseCode()));
  return { link: data.link, id: data.id };
}
function bitlyClicks_(bitlinkId) {
  var token = prop_('BITLY_TOKEN'); if (!token) return null;
  var url = 'https://api-ssl.bitly.com/v4/bitlinks/' + encodeURIComponent(bitlinkId) + '/clicks/summary?unit=day&units=-1';
  var res = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + token }, muteHttpExceptions: true });
  if (res.getResponseCode() >= 300) return null;
  var data = JSON.parse(res.getContentText() || '{}');
  return (typeof data.total_clicks === 'number') ? data.total_clicks : null;
}

// ---- クリック数の定期更新（毎時トリガー）。直近250件のみ＝実行時間/レート対策（古い投稿はほぼ頭打ち） ----
function refreshClicks() {
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow();
    if (last < 2 || !map['Bitly_ID'] || !map['Bitlyクリック']) return;
    var start = Math.max(2, last - 249), n = last - start + 1;
    var ids = sh.getRange(start, map['Bitly_ID'], n, 1).getValues();
    for (var i = 0; i < ids.length; i++) {
      var id = ids[i][0]; if (!id) continue;
      var c = bitlyClicks_(id);
      if (c !== null) {
        sh.getRange(start + i, map['Bitlyクリック']).setValue(c);
        if (map['クリック更新日時']) sh.getRange(start + i, map['クリック更新日時']).setValue(new Date());
      }
      Utilities.sleep(200);
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

// 初回1回：クリック/反応を毎時更新するトリガーを登録
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
