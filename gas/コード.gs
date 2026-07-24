/**
 * コード.gs — 5秒動画メーカー：投稿記録＆クリック/反応集計(Google Apps Script Web App)
 *
 * 役割：
 *   1) クライアント(bluesky.js)から {op,videoId,channel,title,postUrl,affiliateUrl,workUrl,hashtags,postUri,shortUrl,testMode} を受け取る(doPost)
 *   2) videoId(背骨ID)をキーに「記録_ch1 / 記録_ch2」へ upsert。(重複行を作らない・列名マッピング)
 *      短縮URLはフロント生成(da.gd/link-worker)を優先、無い経路のみ GAS が da.gd で短縮。
 *   3) refreshEngagement()(毎時)で Bluesky反応(いいね/リポスト/返信)を更新
 *   4) Phase5：無人予約投稿(runReservations / 5分トリガー)
 *   ※ Bitly は全廃。(無料枠オーバーの主因かつ冗長＝共有されず計測不能)クリック計測は link-worker(KV) に一本化する方針。
 *      テンプレの 'Bitly_ID'/'Bitlyクリック' 列は当面温存。(未使用。将来 link-worker クリックへ転用可)
 *
 * 前提：記録先スプレッドシートは「動画記録分析テンプレート.xlsx」を取り込んだもの
 *   。(記録_ch1 / 記録_ch2 / 集計 / 設定、名前付き範囲 Holidays を含む)
 * スクリプトプロパティ：
 *   SHEET_ID(記録先スプレッドシートID・必須)／ BSKY_HANDLE / BSKY_APP_PW(無人予約に使用)
 *   ※ BITLY_TOKEN は不要。(Bitly全廃)設定が残っていても未使用。
 *   ※ SHARED_SECRET は設定しないこと(現クライアントは送らないため、設定すると弾かれる)
 */

// 記録シートの列ヘッダー。(新規シート作成時のヘッダーにも使う)
// ※不要な手動ラベル列(特別期間(手動)/サムネ・フック種別/CTA・リンク提示方法/Blueskyラベル)は削除済み。
var HEADERS40 = [
  'post_id','投稿日時','曜日','day-type','時間帯スロット','ジャンル','題名(コメント)',
  '作品cid','YouTube動画URL','短縮URL',
  'インプレッション','インプCTR%','視聴回数','平均視聴維持率%','いいね','リポスト','返信','フォロー増','短縮URLクリック数',
  'リンククリック率%','post_uri','クリック更新日時','反応更新日時'
];
// ?action=cleanup_columns で既存シートから削除する列。(コードが唯一の正・ClaudeCodeから増減)
//
// ★FANZA成約・報酬系とその派生指標を削除(Chami依頼 2026-07-23「検証不可のデータ列を削除」)。
//   実測(action=column_fill)の根拠:
//     ・FANZA発生成約/FANZA確定成約/発生報酬¥/確定報酬¥ … 両シートとも **0件**(手入力列・一度も入らず)
//     ・承認率% … 0件
//     ・CVR発生%/CVR確定%/EPC発生¥/EPC確定¥/RPM … 分子(成約・報酬)が空のため **常に0**が並ぶだけ
//   FANZAは投稿単位の成約を返さない(管理画面が正)ため、これらは埋めようがない＝分析を汚すだけ。
//   ★'リンククリック率%' は削除しない。クリック数÷視聴回数＝**両方とも実データがある**(検証可能)。
//     FANZA由来ではないので今回の「検証不可」に当たらない。
// ※'Bluesky投稿URL'/'Bitly_ID' は宵桜艶帖にだけ在った余分列。月詠みへ揃えるため削除。
//   Bluesky投稿URLは'共有URL'と重複、Bitly_IDはBitly廃止済みで死んだ列。
var CLEANUP_COLUMNS = [
  '特別期間(手動)', 'サムネ/フック種別(A/B)', 'CTA・リンク提示方法', 'Blueskyラベル',
  'FANZA発生成約', 'FANZA確定成約', '発生報酬¥', '確定報酬¥',
  '承認率%', 'CVR発生%', 'CVR確定%', 'EPC発生¥', 'EPC確定¥', 'RPM(¥/1000再生)',
  'Bluesky投稿URL', 'Bitly_ID'
];
// FANZA投稿時スナップショット列。(記録シート末尾追加。既存40列は不変)
// レビュー件数は販売部数の代理指標。(実際の売上本数は取得不可)
var FANZA_HEADERS = [
  '元値list_price','割引後price','割引率pct','FANZA取得日時',
  'レビュー件数(代理指標)','レビュー平均'
];
// 追加属性列。(記録シート末尾追加・移行で付与)
// カテゴリ＝作品属性を名前で明記。(キャラ/JK/ギャル/異世界・複数可・カンマ区切り。キャラ無し＝オリジナルで空欄)
// ※旧「キャラ○」方式は廃止。migrate_headers で既存「キャラ」列は「カテゴリ」へ改名。
// ※YouTube題名は廃止：題名(コメント)列に集約する。(consolidate_title で既存分も移行・列削除)
var EXTRA_HEADERS = ['カテゴリ', '作品状態', '共有URL', '作り直し', 'ハッシュタグ', 'リビルド元ID', 'タイトル文字数', '目的', 'コメント型', 'YT補正累計', '作品短縮URL'];
// 作品属性の定義。(順序＝カテゴリ列での並び)フラグ名→表示名。
var ATTR_DEFS = [
  { key: 'chara', label: 'キャラ' },
  { key: 'jk', label: 'JK' },
  { key: 'gyaru', label: 'ギャル' },
  { key: 'isekai', label: '異世界' },
  { key: 'harem', label: 'ハーレム' },
  { key: 'ai', label: 'AI' },
  { key: 'ol', label: 'OL' },
  { key: 'soshu', label: '総集編' }
];
function attrTrue_(v) { return v === true || v === 'true' || v === '○' || v === 1 || v === '1'; }
function attrProvided_(f) {
  for (var i = 0; i < ATTR_DEFS.length; i++) { if (f[ATTR_DEFS[i].key] !== undefined) return true; }
  return false;
}
function categoryOf_(f) {
  var cats = [];
  ATTR_DEFS.forEach(function (a) { if (attrTrue_(f[a.key])) cats.push(a.label); });
  return cats.join(', ');
}
//
// ── 列の自動取得マップ(保守用メモ：ClaudeCodeはここを基準に列を増減する)──
//   【自動で埋まる】post_id / 投稿日時 / 曜日 / day-type / 時間帯スロット / 題名(コメント) /
//     作品cid / YouTube動画URL / 短縮URL / 視聴回数 / いいね / リポスト / 返信 /
//     短縮URLクリック数 / post_uri / クリック更新日時 / 反応更新日時 / カテゴリ /
//     元値list_price / 割引後price / 割引率pct / FANZA取得日時 / レビュー件数(代理指標) / レビュー平均 /
//     リンククリック率%(←数式・クリック数÷視聴回数。両辺とも実データがあるので有効)
//   【手動入力のみ＝APIで自動取得不可】ジャンル / インプレッション / インプCTR% /
//     平均視聴維持率% / フォロー増
//   ※FANZA成約・報酬系(FANZA発生成約/FANZA確定成約/発生報酬¥/確定報酬¥)と、その派生数式
//     (承認率%/CVR発生%/CVR確定%/EPC発生¥/EPC確定¥/RPM)は **2026-07-23に削除**(Chami依頼)。
//     FANZAは投稿単位の成約を返さない=手入力するしかなく、実測で両シートとも0件だった。
//     派生数式は分子が空のため常に0を並べるだけで、分析を汚していた。**復活させないこと。**
//   ※特別期間(手動)/サムネ・フック種別/CTA・リンク提示方法/Blueskyラベル は CLEANUP_COLUMNS で削除済み。
//   ※Bluesky投稿URL/Bitly_ID は宵桜艶帖にのみ在った余分列。月詠みへ揃えるため削除(同日)。
var CH_SHEETS = ['月詠み','宵桜艶帖'];
// 再デプロイ確認用バージョン。(中身を変えたら上げる)<exec URL>?ping=1 で確認できる。
var GAS_VERSION = '2026-07-24A(競合分析を上位20件化。チャンネル名・登録者数・日次伸び・総再生数を返す)';

// 統一列順の正。(2026-07-12・⑥)両chシートの列の左右順をこの並びに固定する。(?action=reorder_headers / admin_setupが適用)
//   ここに無い列(手動追加など)は自然に末尾へ寄る。GASは列名で書くため機能は列順に依存しないが、
//   集計シートの位置参照数式やmove_row(列名不一致でサイレント欠落)の事故を防ぐため順序も固定する。
var CANONICAL_HEADERS = HEADERS40.concat(FANZA_HEADERS).concat(EXTRA_HEADERS);

function prop_(k) { return PropertiesService.getScriptProperties().getProperty(k); }
function jsonOut_(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }
function openSS_() {
  var id = prop_('SHEET_ID');
  var ss = id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('スプレッドシートが見つかりません(SHEET_ID を設定してください)');
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
// 短縮URLクリック数の列見出しを解決。(新名→旧名「開封数」→さらに旧名「Bitlyクリック」。どれも無ければ新名)
function clickColName_(map) {
  return map['短縮URLクリック数'] ? '短縮URLクリック数' : (map['開封数'] ? '開封数' : (map['Bitlyクリック'] ? 'Bitlyクリック' : '短縮URLクリック数'));
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  // ★再デプロイ確認用：<exec URL>?ping=1 を開くと、今“動いている”コードのバージョンが見える。
  //   再デプロイが成功していれば下の GAS_VERSION が返る。古い値や別物なら未反映。
  if (p.ping) {
    return jsonOut_({ ok: true, version: GAS_VERSION, now: new Date().toISOString(),
      bitly: 'removed', features: ['upsert', 'testMode', 'da.gd', 'link-worker-clicks', 'fanza-snapshot'] });
  }
  // 一回限りのヘッダ移行: <exec URL>?action=migrate_headers で既存シートに FANZA 列を追加する。
  if (p.action === 'migrate_headers') {
    return jsonOut_(migrateHeaders_());
  }
  // 診断: 全列のヘッダ書式を両シートで比較する。(読み取り専用)
  //   ★col1_format(1列目だけ)では不十分だった(Chami指摘・スクショで他列の色違いを提示された
  //   2026-07-23)。ヘッダ行全体を列ごとに比較し、どこが違うかを機械的に洗い出す。
  if (p.action === 'header_format') {
    try {
      var hfOut = {};
      CH_SHEETS.forEach(function (nm) {
        var hfsh = openSS_().getSheetByName(nm); if (!hfsh) { hfOut[nm] = null; return; }
        var hfCols = hfsh.getLastColumn();
        var hfHdrVals = hfsh.getRange(1, 1, 1, hfCols).getValues()[0].map(String);
        var hfBg = hfsh.getRange(1, 1, 1, hfCols).getBackgrounds()[0];
        var hfColor = hfsh.getRange(1, 1, 1, hfCols).getFontColors()[0];
        var hfWeight = hfsh.getRange(1, 1, 1, hfCols).getFontWeights()[0];
        var hfFamily = hfsh.getRange(1, 1, 1, hfCols).getFontFamilies()[0];
        var hfSize = hfsh.getRange(1, 1, 1, hfCols).getFontSizes()[0];
        var hfAlign = hfsh.getRange(1, 1, 1, hfCols).getHorizontalAlignments()[0];
        var cols = [];
        for (var hi = 0; hi < hfCols; hi++) {
          cols.push({
            col: hi + 1, header: hfHdrVals[hi], background: hfBg[hi], fontColor: hfColor[hi],
            fontWeight: hfWeight[hi], fontFamily: hfFamily[hi], fontSize: hfSize[hi], align: hfAlign[hi],
            width: hfsh.getColumnWidth(hi + 1)
          });
        }
        hfOut[nm] = { colCount: hfCols, cols: cols };
      });
      // 月詠みを正として、列名一致するもの同士で差分を出す。
      var diff = [];
      if (hfOut['月詠み'] && hfOut['宵桜艶帖']) {
        var byName = {}; hfOut['月詠み'].cols.forEach(function (c) { byName[c.header] = c; });
        hfOut['宵桜艶帖'].cols.forEach(function (c) {
          var ref = byName[c.header]; if (!ref) { diff.push({ header: c.header, status: 'not_in_月詠み' }); return; }
          var keys = ['background', 'fontColor', 'fontWeight', 'fontFamily', 'fontSize', 'align', 'width'];
          var d = {};
          keys.forEach(function (k) { if (ref[k] !== c[k]) d[k] = { 月詠み: ref[k], 宵桜艶帖: c[k] }; });
          if (Object.keys(d).length) diff.push({ header: c.header, col月詠み: ref.col, col宵桜艶帖: c.col, diff: d });
        });
      }
      return jsonOut_({ ok: true, format: hfOut, mismatches: diff });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 実行: 全列のヘッダ書式(背景/文字色/太さ/フォント/サイズ/揃え/幅)を月詠みへ揃える。
  //   (&apply=1 で実行・既定はdry-runで差分だけ返す)列名で対応付けるため列の並びがズレていても正しく揃う。
  if (p.action === 'header_align') {
    try {
      var haApply = String(p.apply || '') === '1';
      var haSrc = openSS_().getSheetByName('月詠み'), haDst = openSS_().getSheetByName('宵桜艶帖');
      if (!haSrc || !haDst) return jsonOut_({ ok: false, error: 'sheet not found' });
      var haSrcMap = headerMap_(haSrc), haDstMap = headerMap_(haDst);
      var haResult = [];
      Object.keys(haDstMap).forEach(function (name) {
        var sCol = haSrcMap[name], dCol = haDstMap[name];
        if (!sCol) { haResult.push({ header: name, status: 'skip_no_月詠み_match' }); return; }
        var sCell = haSrc.getRange(1, sCol), dCell = haDst.getRange(1, dCol);
        var before = { background: dCell.getBackground(), fontColor: dCell.getFontColor(), width: haDst.getColumnWidth(dCol) };
        var after = { background: sCell.getBackground(), fontColor: sCell.getFontColor(), width: haSrc.getColumnWidth(sCol) };
        if (haApply) {
          sCell.copyTo(dCell, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false); // 値は変えない・書式のみ
          haDst.setColumnWidth(dCol, haSrc.getColumnWidth(sCol));
        }
        haResult.push({ header: name, colSrc: sCol, colDst: dCol, before: before, after: after, changed: before.background !== after.background || before.fontColor !== after.fontColor || before.width !== after.width });
      });
      return jsonOut_({ ok: true, applied: haApply, result: haResult });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 1列目(post_id)のヘッダ・データセルの書式を両シートで比較する。(読み取り専用)
  //   ★「1列目の表示や色が変わっていない」報告(2026-07-23)の実態確認用。
  if (p.action === 'col1_format') {
    try {
      var fOut = {};
      CH_SHEETS.forEach(function (nm) {
        var fsh = openSS_().getSheetByName(nm); if (!fsh) { fOut[nm] = null; return; }
        var hdrCell = fsh.getRange(1, 1);
        var dataCell = fsh.getLastRow() >= 2 ? fsh.getRange(2, 1) : null;
        function snap(rng) {
          if (!rng) return null;
          return {
            background: rng.getBackground(), fontColor: rng.getFontColor(),
            fontWeight: rng.getFontWeight(), fontFamily: rng.getFontFamily(),
            fontSize: rng.getFontSize(), numberFormat: rng.getNumberFormat(),
            horizontalAlignment: rng.getHorizontalAlignment()
          };
        }
        fOut[nm] = { header: snap(hdrCell), data: snap(dataCell), colWidth: fsh.getColumnWidth(1) };
      });
      return jsonOut_({ ok: true, format: fOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 実行: 月詠み(正)の1列目の書式を宵桜艶帖へ揃える。(&apply=1 で実行・既定はdry-runで差分だけ返す)
  if (p.action === 'col1_align') {
    try {
      var faApply = String(p.apply || '') === '1';
      var srcSh = openSS_().getSheetByName('月詠み'), dstSh = openSS_().getSheetByName('宵桜艶帖');
      if (!srcSh || !dstSh) return jsonOut_({ ok: false, error: 'sheet not found' });
      var srcHdr = srcSh.getRange(1, 1), dstHdr = dstSh.getRange(1, 1);
      var srcW = srcSh.getColumnWidth(1);
      var before = { headerBg: dstHdr.getBackground(), headerColor: dstHdr.getFontColor(), width: dstSh.getColumnWidth(1) };
      var after = { headerBg: srcHdr.getBackground(), headerColor: srcHdr.getFontColor(), width: srcW };
      if (!faApply) return jsonOut_({ ok: true, applied: false, before: before, after: after });
      // ヘッダ行の書式一式をコピー(値は上書きしない=setValuesではなくcopyTo書式のみ)
      srcHdr.copyTo(dstHdr, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
      dstSh.setColumnWidth(1, srcW);
      // データ行があれば2行目以降の書式も列全体で揃える(値は変えない)
      var dstLast = dstSh.getLastRow();
      if (dstLast >= 2) {
        var srcDataFmt = srcSh.getLastRow() >= 2 ? srcSh.getRange(2, 1) : srcHdr;
        var dstRange = dstSh.getRange(2, 1, dstLast - 1, 1);
        srcDataFmt.copyTo(dstRange, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
      }
      return jsonOut_({ ok: true, applied: true, before: before, after: after });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 題名(コメント)列の生値を調べる。(読み取り専用)
  //   ★「記録の題名が2行モードで2行になっている/改行やスペースが入る」報告(2026-07-23)の実態確認用。
  //   JSON化前の生文字列を返すので、改行・前後空白・連続空白の有無が正確に分かる。
  if (p.action === 'title_scan') {
    try {
      var tsOut = {};
      CH_SHEETS.forEach(function (nm) {
        var tsh2 = openSS_().getSheetByName(nm); if (!tsh2) { tsOut[nm] = null; return; }
        var tmap = headerMap_(tsh2), tCol2 = tmap['題名(コメント)'];
        var tlast = tsh2.getLastRow();
        if (!tCol2 || tlast < 2) { tsOut[nm] = { rows: [] }; return; }
        var n = Math.min(tlast - 1, 1000); // 実運用は数十行なので全件走査で問題ない
        var start = Math.max(2, tlast - n + 1);
        var tvals = tsh2.getRange(start, tCol2, tlast - start + 1, 1).getValues();
        var rows = [];
        for (var ti = 0; ti < tvals.length; ti++) {
          var raw = String(tvals[ti][0] || '');
          if (!raw) continue;
          rows.push({
            row: start + ti, raw: raw,
            hasNewline: /\r|\n/.test(raw),
            hasLeadTrailSpace: raw !== raw.trim(),
            hasDoubleSpace: /[ 　]{2,}/.test(raw)
          });
        }
        tsOut[nm] = { rows: rows };
      });
      return jsonOut_({ ok: true, scan: tsOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 実行: 題名(コメント)列の改行・行境の余分な空白を正規化する。(&apply=1 で実行・既定はdry-run)
  //   ★フロント側(app.js titleForBurn)は2026-07-23に「行ごとtrimしてから結合」へ修正済み(新規は再発しない)。
  //   これは修正前に記録された既存2行(月詠み row2/3)を一度だけ正す後始末。
  //   正規化＝改行で分割→各行trim→空区切りで結合→連続空白を1つに圧縮→全体trim。
  if (p.action === 'title_fix') {
    try {
      var tfApply = String(p.apply || '') === '1';
      var tfOut = [];
      CH_SHEETS.forEach(function (nm) {
        var tfsh = openSS_().getSheetByName(nm); if (!tfsh) { tfOut.push({ sheet: nm, status: 'not_found' }); return; }
        var tfmap = headerMap_(tfsh), tfCol = tfmap['題名(コメント)'];
        var tfLast = tfsh.getLastRow();
        if (!tfCol || tfLast < 2) { tfOut.push({ sheet: nm, status: 'no_title_col_or_empty' }); return; }
        var tfVals = tfsh.getRange(2, tfCol, tfLast - 1, 1).getValues();
        var changes = [];
        for (var fi = 0; fi < tfVals.length; fi++) {
          var raw = String(tfVals[fi][0] || ''); if (!raw) continue;
          var fixed = raw.split(/\r?\n/).map(function (l) { return l.trim(); }).join('').replace(/[ \t　]{2,}/g, ' ').trim();
          if (fixed !== raw) changes.push({ row: fi + 2, before: raw, after: fixed });
        }
        if (tfApply && changes.length) {
          changes.forEach(function (c) { tfsh.getRange(c.row, tfCol).setValue(c.after); });
        }
        tfOut.push({ sheet: nm, status: tfApply ? 'fixed' : 'dry_run', changeCount: changes.length, changes: changes });
      });
      return jsonOut_({ ok: true, applied: tfApply, result: tfOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 全列の「実データが入っている行数」を返す。(読み取り専用)
  //   ★列を消す前に「何が失われるか」を数える。0件なら消しても失うものは無い、と機械的に言える。
  //   数えずに消すのは取り返しがつかない(スプレッドシートはコードと違って戻せない)。
  if (p.action === 'column_fill') {
    try {
      var cfOut = {};
      CH_SHEETS.forEach(function (nm) {
        var csh = openSS_().getSheetByName(nm); if (!csh) { cfOut[nm] = null; return; }
        var clast = csh.getLastRow(), ccols = csh.getLastColumn();
        var chdr = csh.getRange(1, 1, 1, ccols).getValues()[0].map(String);
        var counts = {};
        if (clast >= 2) {
          var vals = csh.getRange(2, 1, clast - 1, ccols).getValues();
          for (var ci = 0; ci < ccols; ci++) {
            var n = 0;
            for (var ri = 0; ri < vals.length; ri++) {
              var v = vals[ri][ci];
              if (v !== '' && v !== null && v !== undefined) n++;
            }
            counts[chdr[ci]] = n;
          }
        } else { chdr.forEach(function (h) { counts[h] = 0; }); }
        cfOut[nm] = { dataRows: Math.max(0, clast - 1), counts: counts };
      });
      return jsonOut_({ ok: true, fill: cfOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 末尾の空行を詰める: <exec URL>?action=trim_empty_rows
  //   ★既定は dry-run(数えるだけ・消さない)。実際に消すのは &apply=1 を付けた時だけ。
  //     行削除は列と違って「1行ズレただけで別の行が消える」ので、まず何が消えるかを見る。
  //   ★安全条件を満たさない限り消さない:
  //     ・削除するのは「最後の実データ行より下」だけ(データの間に挟まった空行には触らない)
  //     ・その範囲の全セルが空であることを実際に確認してから消す
  //   ・数式だけが入っている行も「空」とみなさない(getValuesは数式の結果を返すため、
  //     結果が空文字なら空と判定される=意図せず消えるのを防ぐためgetFormulasも見る)
  if (p.action === 'trim_empty_rows') {
    try {
      var apply = String(p.apply || '') === '1';
      var trOut = [];
      CH_SHEETS.forEach(function (nm) {
        var tsh = openSS_().getSheetByName(nm);
        if (!tsh) { trOut.push({ sheet: nm, status: 'not_found' }); return; }
        var maxRow = tsh.getMaxRows(), cols = tsh.getLastColumn();
        if (maxRow < 2 || cols < 1) { trOut.push({ sheet: nm, status: 'empty_sheet' }); return; }
        var vals = tsh.getRange(2, 1, maxRow - 1, cols).getValues();
        var frms = tsh.getRange(2, 1, maxRow - 1, cols).getFormulas();
        // ★境界は「表示される値がある最後の行」。数式が残っているだけの行は空とみなす。
        //   実測(宵桜艶帖)で分かったこと: 行を1000まで占有していたのは空行ではなく、
        //   曜日/day-type/時間帯スロット/リンククリック率% の**数式の残骸**だった(974行分)。
        //   これらは参照先が空なので表示は空。見た目は空行なのに「中身あり」と判定され消せなかった。
        //   値が無い＝表示上なにも失われないので、数式ごと行を消してよい。
        //   (逆に値がある行より上は絶対に触らない。データの間に挟まった空行も残す)
        var lastUsed = 1; // シート行番号(1=ヘッダ)
        for (var i = 0; i < vals.length; i++) {
          for (var c = 0; c < cols; c++) {
            if (vals[i][c] !== '' && vals[i][c] !== null) { lastUsed = i + 2; break; }
          }
        }
        var firstTrim = lastUsed + 1, count = maxRow - lastUsed;
        // 「値は無いが数式だけ残っている行」がどこから始まり、どの列が原因かを併せて返す。
        //   これが分かると「空に見えるのに消せない行」の正体が特定できる。
        var lastValue = 1, hdr = tsh.getRange(1, 1, 1, cols).getValues()[0].map(String);
        for (var vi = 0; vi < vals.length; vi++) {
          for (var vc = 0; vc < cols; vc++) {
            if (vals[vi][vc] !== '' && vals[vi][vc] !== null) { lastValue = vi + 2; break; }
          }
        }
        var ghostCols = {};
        for (var gi = lastValue - 1; gi < frms.length; gi++) {          // 最終“値”行より下
          for (var gc = 0; gc < cols; gc++) { if (frms[gi][gc] !== '') ghostCols[hdr[gc]] = (ghostCols[hdr[gc]] || 0) + 1; }
        }
        var info = { sheet: nm, maxRows: maxRow, lastUsedRow: lastUsed, lastValueRow: lastValue,
                     trimFrom: firstTrim, trimCount: count, formulaOnlyBelowValue: ghostCols };
        if (count <= 0) { info.status = 'already_tight'; trOut.push(info); return; }
        if (!apply) { info.status = 'dry_run'; trOut.push(info); return; }
        tsh.deleteRows(firstTrim, count);
        info.status = 'trimmed';
        info.maxRowsAfter = tsh.getMaxRows();
        trOut.push(info);
      });
      return jsonOut_({ ok: true, applied: apply, result: trOut });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 不要列の削除: <exec URL>?action=cleanup_columns で CLEANUP_COLUMNS の列を各シートから削除。(冪等)
  if (p.action === 'cleanup_columns') {
    return jsonOut_(cleanupColumns_());
  }
  // 列順統一(⑥): <exec URL>?action=reorder_headers で両chシートの列をCANONICAL_HEADERS順へ固定。(冪等)
  if (p.action === 'reorder_headers') {
    return jsonOut_(reorderHeaders_());
  }
  // 診断: <exec URL>?action=diagnose でスプレッドシート名・全タブ名・各記録タブの中身を返す。(読み取りのみ)
  if (p.action === 'diagnose') {
    return jsonOut_(diagnose_());
  }
  // 行分類と件数: <exec URL>?action=sheet_audit で各記録シートの行を分類して返す。(読み取りのみ)
  //   complete=postUri+YT両方あり / no_yt=postUriのみ / no_uri=YTのみ / minimal=どちらも無 / empty=post_id空
  //   ヘッダー一覧とCANONICALとの差分(missing/extra)も同時に返す。
  if (p.action === 'sheet_audit') {
    try { return jsonOut_(sheetAudit_()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // バックアップ: <exec URL>?action=backup_sheets で両記録シートを同スプレッドシート内にコピーする。(読み取りのみ)
  //   コピー先タブ名: <シート名>_bk_<YYYYMMdd_HHmm>。削除・上書きはしない。
  if (p.action === 'backup_sheets') {
    try { return jsonOut_(backupSheets_()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 視聴履歴(スナップショット)の末尾N行を返す。(読み取りのみ)
  //   YT_API_KEY が効いて views が記録できているか等、サーバー自動記録の生存確認用。
  if (p.action === 'stats_tail') {
    try {
      var ssh = statsSheet_(); var slast = ssh.getLastRow();
      var n = Math.min(Math.max(parseInt(p.n || '5', 10) || 5, 1), 20);
      var rows = slast >= 2 ? ssh.getRange(Math.max(2, slast - n + 1), 1, Math.min(n, slast - 1), STATS_HEADERS.length).getValues() : [];
      return jsonOut_({ ok: true, headers: STATS_HEADERS, totalRows: Math.max(0, slast - 1), tail: rows });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 診断: 無人予約投稿の待機状況を返す。(読み取りのみ・投稿はしない)
  //   ★2026-07-21追加: Bluesky凍結多発を受け「予約が自動発射し続けていないか」を外から確認するため。
  //   端末側(localStorage)の予約は見えないが、GAS側の無人予約はここで把握できる。
  //   本文は出さない(先頭20字のみ)=秘匿情報を診断URLに載せない。
  if (p.action === 'reservations_status') {
    try {
      var rsh = getResSheet_(), rlast = rsh.getLastRow();
      var counts = { pending: 0, posting: 0, posted: 0, error: 0, other: 0 }, upcoming = [];
      if (rlast >= 2) {
        var rrows = rsh.getRange(2, 1, rlast - 1, RES_HEADERS.length).getValues();
        for (var ri = 0; ri < rrows.length; ri++) {
          var st = String(rrows[ri][RCOL.status - 1] || '');
          if (counts[st] == null) counts.other++; else counts[st]++;
          if (st === 'pending' || st === 'posting') {
            var w = rrows[ri][RCOL.when - 1];
            upcoming.push({
              row: ri + 2, status: st, when: w ? String(w) : '',
              channel: String(rrows[ri][RCOL.channel - 1] || ''),
              textHead: String(rrows[ri][RCOL.text - 1] || '').slice(0, 20)
            });
          }
        }
      }
      // 5分トリガー(runReservations)が生きているか＝自動発射の有無を判断する材料
      var trg = [];
      try { trg = ScriptApp.getProjectTriggers().map(function (t) { return t.getHandlerFunction(); }); } catch (e) {}
      return jsonOut_({
        ok: true, totalRows: Math.max(0, rlast - 1), counts: counts,
        upcoming: upcoming.slice(0, 20),
        runReservationsTriggerAlive: trg.indexOf('runReservations') >= 0,
        triggers: trg, now: new Date().toISOString()
      });
    } catch (err) { return jsonOut_({ ok: false, error: String(err) }); }
  }
  // 題名集約: <exec URL>?action=consolidate_title で「YouTube題名」を「題名(コメント)」へ移し、列を削除。
  if (p.action === 'consolidate_title') {
    return jsonOut_(consolidateTitle_());
  }
  // 競合サーチ(gas/競合.gs)。部門はWebFetchでJSONを読む。設計書=docs/設計・調査/設計書_YouTube競合サーチ.md
  if (p.action === 'comp_digest' && !p.callback) { return jsonOut_(compDigest_()); }                       // 分析部: 週次サマリ(callback時は下のJSONP分岐へ)
  if (p.action === 'comp_titles' && !p.callback) { return jsonOut_(compTitles_(p.days, p.top)); }           // コピー部: 速度順タイトルコーパス(同上)
  if (p.action === 'comp_daily_now') { try { return jsonOut_(runCompetitorDaily()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }
  if (p.action === 'comp_discovery_now') { try { return jsonOut_(runCompetitorDiscovery()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }
  if (p.action === 'comp_add_seed' && !p.callback) { try { return jsonOut_(compAddSeed_(p.url, p.name, p.bluesky, p.x, p.note)); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }  // シード登録(callback時は下のJSONP分岐へ)
  if (p.action === 'comp_ensure_tabs') { try { return jsonOut_(compEnsureTabs_()); } catch (err) { return jsonOut_({ ok: false, error: String(err) }); } }  // 全タブ確保(手動記録タブ含む)
  // デプロイ後の自動後処理: トリガー再設定＋ヘッダ移行を一括冪等実行。(scripts/deploy_gas.mjs が反映確認後に呼ぶ)
  //   secret はスクリプトプロパティ ADMIN_SECRET(未設定なら固定のソフト鍵にフォールバック)と照合。
  //   ※ソフト鍵は deploy_gas.mjs の SOFT_ADMIN_SECRET と一致させる。(短縮URL用 shortSecret_ とは独立)
  if (p.action === 'admin_setup') {
    var adminWant = prop_('ADMIN_SECRET') || 'daremogamewoubawareteikukimihakanpekidekyukyokunoidol';
    if (String(p.secret || '') !== adminWant) return jsonOut_({ ok: false, error: 'bad_secret' });
    var mig = migrateHeaders_();
    var reo = reorderHeaders_(); // ⑥列順統一もデプロイ毎に冪等適用(以後ズレない)
    setupTrigger();
    var handlers = ScriptApp.getProjectTriggers().map(function (t) { return t.getHandlerFunction(); });
    return jsonOut_({ ok: true, version: GAS_VERSION, migrated: mig, reordered: reo, triggers: handlers });
  }
  // JSONP：ブラウザはGASのPOST応答をCORSで読めないため、callback 付きGETで取得する。
  if (p.callback) {
    var out;
    try {
      var ch = p.channel || 'acc1';
      if (p.action === 'history') out = { ok: true, items: historyItems_(ch, parseInt(p.limit || '40', 10)) };
      else if (p.action === 'delete') out = { ok: true, deleted: deleteRecord_(ch, p.videoId || '', p.postUri || '', p.short || '') };
      else if (p.action === 'settings_pull') out = settingsPull_();   // 端末間同期：非秘密設定の取得
      else if (p.action === 'settings_meta') out = settingsMeta_();   // 端末間同期：最終保存メタのみ(状態表示)
      else if (p.action === 'deltas') out = { ok: true, deltas: computeDeltas_(), peaks: computePeaks_() }; // 今日/昨日/週の増加＋最大瞬間風速
      else if (p.action === 'comp_digest') out = compDigest_();                          // 競合: 週次サマリ(分析タブ表示用)
      else if (p.action === 'comp_titles') out = compTitles_(p.days, p.top);             // 競合: 題名コーパス(分析タブ表示用)
      else if (p.action === 'comp_add_seed') out = compAddSeed_(p.url, p.name, p.bluesky, p.x, p.note); // 競合: フロント登録→GASへ同期
      else if (p.action === 'snapshot_now') { snapshotStats(); out = { ok: true, snapped: true }; } // 手動で即スナップ
      else out = { ok: true, shortUrl: p.postUri ? lookupShortByUri_(ch, p.postUri) : '' }; // 既定＝action=short
    } catch (err) { out = { ok: false, error: String(err) }; }
    return ContentService.createTextOutput(p.callback + '(' + JSON.stringify(out) + ')')
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
  // 該当アクション無し。どのバージョンが live か常に分かるよう version と対応アクションを返す。
  return jsonOut_({ ok: true, service: 'go5-maker recorder v2 (2ch)', version: GAS_VERSION,
    actions: ['ping', 'migrate_headers', 'cleanup_columns', 'diagnose', 'admin_setup'],
    note: 'diagnose が service応答になる場合は diagnose 追加版(2026-07-01F以降)が未デプロイ' });
}
// 指定 post_uri の行から短縮URLを返す。(読み取りのみ)
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
// チャンネル別の投稿履歴。(新しい順・読み取りのみ)
function historyItems_(channel, limit) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return [];
  var dCol = map['投稿日時'], tCol = map['題名(コメント)'], sCol = map['短縮URL'], uCol = map['post_uri'];
  var yCol = map['YouTube動画URL']; // 端末のverify_yt消失時にここから復元できるよう返す
  var pidCol = map['post_id'], shareCol = map['共有URL'], wsCol = map['作品状態'], cidCol = map['作品cid']; // 端末の投稿履歴復元用
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
  var items = [];
  for (var i = 0; i < vals.length; i++) {
    var row = vals[i];
    var d = dCol ? row[dCol - 1] : '', uri = uCol ? row[uCol - 1] : '', short = sCol ? row[sCol - 1] : '';
    var pid = pidCol ? row[pidCol - 1] : '';
    if (!d && !uri && !short && !pid) continue; // 完全な空行だけスキップ。動画IDだけ残る異常行も削除用に返す
    var ds = '', iso = '';
    try { if (d) { var dd = new Date(d); ds = Utilities.formatDate(dd, tz, 'MM/dd HH:mm'); iso = dd.toISOString(); } } catch (e) {}
    items.push({
      postUri: String(uri || ''), title: String(tCol ? row[tCol - 1] : ''),
      date: ds, postedAt: iso, shortUrl: String(short || ''), shareUrl: String(shareCol ? (row[shareCol - 1] || '') : ''), postUrl: '',
      videoId: String(pid || ''),
      workState: String(wsCol ? (row[wsCol - 1] || '') : ''),
      cid: String(cidCol ? (row[cidCol - 1] || '') : ''), // 作品URL復元用(cid→作品URLをフロントで再構成)
      youtubeUrl: String(yCol ? (row[yCol - 1] || '') : '')
    });
  }
  items.reverse(); // 新しい順
  return items.slice(0, limit > 0 ? limit : 40);
}
// 1件削除。(行の内容をクリア＝再利用可。行は詰めない＝集計の整合を保つ)
// 安定動画ID(post_id)を最優先し、無ければ post_uri、短縮URLの順。URL欠損の異常行も削除できる。
function deleteRecord_(channel, videoId, postUri, short) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var last = sh.getLastRow(); if (last < 2) return 0;
  var col = videoId ? map['post_id'] : (postUri ? map['post_uri'] : map['短縮URL']);
  var want = videoId || postUri || short; if (!col || !want) return 0;
  var vals = sh.getRange(2, col, last - 1, 1).getValues(), cleared = 0;
  for (var i = 0; i < vals.length; i++) {
    if (String(vals[i][0]) === String(want)) { sh.getRange(i + 2, 1, 1, sh.getLastColumn()).clearContent(); cleared++; }
  }
  return cleared;
}

// 行をチャンネル間で移動：videoId(post_id)→post_uri→短縮URL の順で元行を特定し、目的チャンネルへ
// 全列コピー(計算式列は式を貼り直し)＋元行をクリア。アカウント誤記録の矯正に使う。
function moveRow_(from, to, videoId, postUri, short) {
  if (!from || !to || from === to) return { ok: false, error: 'bad_channel' };
  var src = getChannelSheet_(from), smap = headerMap_(src); var slast = src.getLastRow(); if (slast < 2) return { ok: false, error: 'empty_src' };
  var keyDefs = [];
  if (videoId && smap['post_id']) keyDefs.push([smap['post_id'], videoId]);
  if (postUri && smap['post_uri']) keyDefs.push([smap['post_uri'], postUri]);
  if (short && smap['短縮URL']) keyDefs.push([smap['短縮URL'], short]);
  if (!keyDefs.length) return { ok: false, error: 'no_key' };
  var srow = 0;
  for (var ki = 0; ki < keyDefs.length && !srow; ki++) {
    var col = keyDefs[ki][0], want = String(keyDefs[ki][1]);
    var kv = src.getRange(2, col, slast - 1, 1).getValues();
    for (var i = 0; i < kv.length; i++) { if (String(kv[i][0]) === want) { srow = i + 2; break; } }
  }
  if (!srow) return { ok: false, error: 'src_not_found' };
  var headers = src.getRange(1, 1, 1, src.getLastColumn()).getValues()[0].map(String);
  var srcVals = src.getRange(srow, 1, 1, src.getLastColumn()).getValues()[0];
  var dst = getChannelSheet_(to), dmap = headerMap_(dst); var dlast = dst.getLastRow();
  var vid2 = videoId || (smap['post_id'] ? srcVals[smap['post_id'] - 1] : '');
  var target = 0;
  if (vid2 && dmap['post_id'] && dlast >= 2) {
    var pv = dst.getRange(2, dmap['post_id'], dlast - 1, 1).getValues();
    for (var j = 0; j < pv.length; j++) { if (String(pv[j][0]) === String(vid2)) { target = j + 2; break; } }
  }
  if (!target) {
    var ddc = dmap['投稿日時'] || 2;
    if (dlast >= 2) { var dv = dst.getRange(2, ddc, dlast - 1, 1).getValues(); for (var k = 0; k < dv.length; k++) { if (dv[k][0] === '' || dv[k][0] === null) { target = k + 2; break; } } }
    if (!target) target = dlast + 1;
  }
  setComputed_(dst, dmap, target); // 計算式列は式を貼る(値上書きしない)
  // 数式で自動計算される列。(手で書き込まない)FANZA成約由来の数式は2026-07-23に撤去済み。
  var COMPUTED = { '曜日': 1, 'day-type': 1, '時間帯スロット': 1, 'リンククリック率%': 1, 'タイトル文字数': 1 };
  headers.forEach(function (h, ci) {
    if (COMPUTED[h]) return;             // 計算式列は上書きしない
    var dc = dmap[h]; if (!dc) return;   // 目的地に無い列はスキップ
    dst.getRange(target, dc).setValue(srcVals[ci]); // 空も含め忠実にコピー
  });
  src.getRange(srow, 1, 1, src.getLastColumn()).clearContent(); // 元行クリア(行は詰めない＝集計整合)
  return { ok: true, moved: 1, from: from, to: to };
}

// 既存シートに FANZA_HEADERS を末尾追加する一回限りの移行関数。
// <exec URL>?action=migrate_headers で呼ぶ。既に存在する列は追加しない。(冪等)
function migrateHeaders_() {
  var result = [];
  var ss = openSS_();
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { result.push({ sheet: name, status: 'not_found' }); return; }
    var lastCol = sh.getLastColumn();
    if (lastCol < 1) { result.push({ sheet: name, status: 'empty' }); return; }
    var existing = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
    // クリック数列の見出しを「短縮URLクリック数」に統一。(旧名 開封数/Bitlyクリック はデータ保持のまま改名)
    var renamed = '';
    if (existing.indexOf('短縮URLクリック数') === -1) {
      var ai = existing.indexOf('開封数'); if (ai === -1) ai = existing.indexOf('Bitlyクリック');
      if (ai >= 0) { sh.getRange(1, ai + 1).setValue('短縮URLクリック数'); existing[ai] = '短縮URLクリック数'; renamed = '短縮URLクリック数'; }
    }
    // 「キャラ」列を「カテゴリ」へ改名。(旧○方式→属性名明記方式。データ保持のまま)
    var renamedCat = '';
    if (existing.indexOf('カテゴリ') === -1 && existing.indexOf('キャラ') >= 0) {
      var ci = existing.indexOf('キャラ');
      sh.getRange(1, ci + 1).setValue('カテゴリ'); existing[ci] = 'カテゴリ'; renamedCat = 'カテゴリ';
    }
    // 不足列を末尾に追加。(短縮URLクリック数が旧名も無く欠けていればここで新設)
    var wantHeaders = FANZA_HEADERS.concat(EXTRA_HEADERS).concat(['短縮URLクリック数']);
    var missing = wantHeaders.filter(function (h) { return existing.indexOf(h) === -1; });
    if (missing.length === 0 && !renamed && !renamedCat) { result.push({ sheet: name, added: [], renamedClick: '', renamedCategory: '', status: 'already_up_to_date' }); return; }
    missing.forEach(function (h) {
      sh.getRange(1, sh.getLastColumn() + 1).setValue(h);
    });
    result.push({ sheet: name, added: missing, renamedClick: renamed, renamedCategory: renamedCat, status: 'ok' });
  });
  return { ok: true, result: result };
}

// CLEANUP_COLUMNS の列を各記録シートから削除する。(冪等：存在する列だけ・右から削除して索引ズレ回避)
// 列削除時、Googleスプレッドシートは他セルの数式参照を自動補正するため分析数式は壊れない。
function cleanupColumns_() {
  var result = [];
  var ss = openSS_();
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { result.push({ sheet: name, status: 'not_found' }); return; }
    var lastCol = sh.getLastColumn();
    if (lastCol < 1) { result.push({ sheet: name, status: 'empty' }); return; }
    var header = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
    var removed = [], idxs = [];
    CLEANUP_COLUMNS.forEach(function (n) { var i = header.indexOf(n); if (i >= 0) { idxs.push(i + 1); removed.push(n); } });
    idxs.sort(function (a, b) { return b - a; });          // 右の列から削除(索引ズレ防止)
    idxs.forEach(function (c) { sh.deleteColumn(c); });
    result.push({ sheet: name, removed: removed, status: removed.length ? 'ok' : 'already_clean' });
  });
  return { ok: true, result: result };
}

// 「YouTube題名」列の値を「題名(コメント)」列へ移し(値があるものは上書き)、YouTube題名列を削除する。
// 題名を1列(題名(コメント))に集約するための一回限りの移行。(冪等：YouTube題名列が無ければ何もしない)
function consolidateTitle_() {
  var result = [];
  var ss = openSS_();
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { result.push({ sheet: name, status: 'not_found' }); return; }
    var map = headerMap_(sh);
    var gCol = map['題名(コメント)'], yCol = map['YouTube題名'];
    if (!yCol) { result.push({ sheet: name, moved: 0, removed: false, status: 'no_youtube_title_col' }); return; }
    var last = sh.getLastRow(), moved = 0;
    if (gCol && last >= 2) {
      var yVals = sh.getRange(2, yCol, last - 1, 1).getValues();
      for (var i = 0; i < yVals.length; i++) {
        var v = yVals[i][0];
        if (v !== '' && v !== null) { sh.getRange(i + 2, gCol).setValue(v); moved++; } // 値があれば題名(コメント)へ上書き
      }
    }
    sh.deleteColumn(yCol); // YouTube題名 列を削除
    result.push({ sheet: name, moved: moved, removed: true, status: 'ok' });
  });
  return { ok: true, result: result };
}

// 診断(読み取りのみ)：どのスプレッドシートのどのタブに、何が入っているかを可視化する。
// 「データがどこに書かれているか分からない」「クリック数/題名が空」の原因切り分けに使う。
function diagnose_() {
  var ss = openSS_();
  var allTabs = ss.getSheets().map(function (s) { return s.getName(); });
  var channels = {};
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { channels[name] = { exists: false, note: 'このタブは存在しません(GASは書き込み時に自動作成します)' }; return; }
    var map = headerMap_(sh);
    var headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
    var last = sh.getLastRow();
    var info = { exists: true, lastRow: last, clickCol: clickColName_(map), headers: headers };
    function countNonEmpty(col) {
      if (!col || last < 2) return 0;
      var vals = sh.getRange(2, col, last - 1, 1).getValues(), n = 0;
      for (var i = 0; i < vals.length; i++) { if (vals[i][0] !== '' && vals[i][0] !== null) n++; }
      return n;
    }
    info.dataRows = countNonEmpty(map['post_id']);
    info.filled = {
      短縮URL: countNonEmpty(map['短縮URL']),
      短縮URLクリック数: countNonEmpty(map[clickColName_(map)]),
      題名コメント: countNonEmpty(map['題名(コメント)']),
      YouTube題名: countNonEmpty(map['YouTube題名']),
      カテゴリ: countNonEmpty(map['カテゴリ']),
      post_uri: countNonEmpty(map['post_uri'])
    };
    channels[name] = info;
  });
  return { ok: true, version: GAS_VERSION, spreadsheet: ss.getName(), allTabs: allTabs, channels: channels };
}

// 行分類と件数。(読み取りのみ・削除しない)
// 各チャンネルシートの全行を post_id / post_uri / YouTube動画URL の3列で分類する。
// CANONICAL_HEADERS との差分(実シートに無い列 / 正本に無い余剰列)も同時に返す。
function sheetAudit_() {
  var ss = openSS_();
  var audit = {};
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { audit[name] = { exists: false }; return; }
    var map = headerMap_(sh);
    var headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String).filter(function (h) { return h !== ''; });
    var last = sh.getLastRow();
    var counts = { complete: 0, no_yt: 0, no_uri: 0, minimal: 0, empty: 0 };
    var uriSeen = {};  // postUri -> [{rowNum, hasYt}]
    var noYtRows = [];
    var extraColCounts = {};
    if (last >= 2) {
      var pidCol = map['post_id'], uriCol = map['post_uri'], ytCol = map['YouTube動画URL'];
      var titleCol = map['題名(コメント)'], shortCol = map['短縮URL'];
      var bitlyCol = map['Bitly_ID'], bskyUrlCol = map['Bluesky投稿URL'];
      var rows = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
      rows.forEach(function (row, i) {
        var pid = pidCol ? String(row[pidCol - 1] || '') : '';
        var uri = uriCol ? String(row[uriCol - 1] || '') : '';
        var yt  = ytCol  ? String(row[ytCol  - 1] || '') : '';
        if (!pid) { counts.empty++; return; }
        if (uri && yt) counts.complete++;
        else if (uri && !yt) {
          counts.no_yt++;
          noYtRows.push({
            rowNum: i + 2,
            title: titleCol ? String(row[titleCol - 1] || '') : '',
            postUri: uri,
            shortUrl: shortCol ? String(row[shortCol - 1] || '') : ''
          });
        }
        else if (!uri && yt) counts.no_uri++;
        else counts.minimal++;
        if (uri) { if (!uriSeen[uri]) uriSeen[uri] = []; uriSeen[uri].push({ rowNum: i + 2, hasYt: !!yt }); }
        if (bitlyCol && row[bitlyCol - 1]) extraColCounts['Bitly_ID'] = (extraColCounts['Bitly_ID'] || 0) + 1;
        if (bskyUrlCol && row[bskyUrlCol - 1]) extraColCounts['Bluesky投稿URL'] = (extraColCounts['Bluesky投稿URL'] || 0) + 1;
      });
    }
    var dups = [];
    Object.keys(uriSeen).forEach(function (uri) { if (uriSeen[uri].length > 1) dups.push({ postUri: uri, rows: uriSeen[uri] }); });
    // CANONICALとの差分
    var missingFromCanonical = CANONICAL_HEADERS.filter(function (h) { return !map[h]; });
    var extraColumns = headers.filter(function (h) { return CANONICAL_HEADERS.indexOf(h) < 0; });
    audit[name] = {
      exists: true, totalDataRows: Math.max(0, last - 1),
      counts: counts, duplicateUris: dups.length, dupDetail: dups.slice(0, 10),
      noYtRows: noYtRows, extraColCounts: extraColCounts,
      headers: headers, headerCount: headers.length,
      missingFromCanonical: missingFromCanonical, extraColumns: extraColumns
    };
  });
  return { ok: true, audit: audit, canonicalTotal: CANONICAL_HEADERS.length };
}

// 両記録シートをバックアップ。(コピーのみ・元シートを削除・変更しない)
// コピー先タブ名: <シート名>_bk_<YYYYMMdd_HHmm>。同スプレッドシート内に作成。冪等ではない(毎回新タブ)。
function backupSheets_() {
  var ss = openSS_();
  var ts = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyyMMdd_HHmm');
  var result = [];
  CH_SHEETS.forEach(function (name) {
    var sh = ss.getSheetByName(name);
    if (!sh) { result.push({ sheet: name, status: 'not_found' }); return; }
    var backupName = name + '_bk_' + ts;
    try {
      sh.copyTo(ss).setName(backupName);
      result.push({ sheet: name, backup: backupName, rows: Math.max(0, sh.getLastRow() - 1), status: 'ok' });
    } catch (err) {
      result.push({ sheet: name, status: 'error', error: String(err) });
    }
  });
  return { ok: true, result: result, timestamp: ts };
}

function doPost(e) {
  // T11: 書き込みは全て直列化。(同一videoIdの近接2リクエストが両方upsertをすり抜けて重複行を作る事故を根絶)
  var lock = LockService.getScriptLock();
  try { lock.waitLock(20000); } catch (le) { return jsonOut_({ ok: false, error: 'busy(同時書き込み中。数秒後に再試行してください)' }); }
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var need = prop_('SHARED_SECRET');
    if (need && body.secret !== need) return jsonOut_({ ok: false, error: 'bad_secret' });
    if (body.type === 'reserve') return handleReserve_(body);
    // 投稿履歴の一括同期。(フロントの投稿履歴を正とし、ID・投稿日時・キャラ等をまとめて upsert)
    if (body.op === 'sync_history') return syncHistory_(body.channel || 'acc1', body.items || []);
    // 投稿履歴の掃除。(keepIds に無い post_id の行をクリア＝アプリの履歴を正にシートを揃える)
    if (body.op === 'prune_history') return pruneHistory_(body.channel || 'acc1', body.keepIds || []);
    // 行のアカウント間移動(誤記録の矯正)：videoId/post_uri/短縮URL で元行を特定し正チャンネルへ移す。
    if (body.op === 'move_row') return jsonOut_(moveRow_(body.from || '', body.to || '', body.videoId || '', body.postUri || '', body.short || ''));
    // 端末間 設定同期：非秘密設定の保存。(クラウドへ push)
    if (body.op === 'settings_push') return settingsPush_(body.blob || '', body.updatedAt || '', body.device || '');
    // テストモード：シートには一切書かない。(Bluesky実投稿はフロント側で実施)
    if (body.testMode === true || body.testMode === 'true') return jsonOut_({ ok: true, testMode: true });
    // ウィザード経路はyoutube_url必須。他経路(無人予約/リビルド/矯正等)は素通り。(★writeRecord_中に置くな=裁定C)
    if (body.op === 'wizard_confirm' && !body.youtube_url) return jsonOut_({ ok: false, error: 'youtube_url_required' });
    var r = writeRecord_(body.channel || 'acc1', {
      videoId: body.videoId || '',   // 背骨ID。あれば post_id に採用＋同ID行へ upsert(重複行を作らない)
      postedAt: body.postedAt || '', // 過去データ矯正時に当時の投稿日時を保持(無ければGASがnow)
      title: body.title || '', postUrl: body.postUrl || '', affiliateUrl: body.affiliateUrl || '',
      workUrl: body.workUrl || '', hashtags: body.hashtags || '', postUri: body.postUri || '',
      rebuildOf: body.rebuildOf || '',     // リビルド元の投稿videoId(送っているのに未記録だった取りこぼしを回収・D-1)
      goal: body.goal || '', cmtType: body.cmtType || '', // 狙い(成約/集客)・コメント型(①〜⑧)＝勝ちパターン集計用
      shortUrl: body.shortUrl || '',       // r2計測用短縮URL(短縮URL列)
      shareUrl: body.shareUrl || '',       // da.gd共有URL(共有URL列)
      youtubeUrl: body.youtube_url || '',  // ウィザードのYouTube手動ゲートから(同IDの行へ後追いupsert)
      workShortUrl: body.work_short_url || '', // 導線2(作品クリック)の計測URL
      chara: body.chara, jk: body.jk, gyaru: body.gyaru, isekai: body.isekai, harem: body.harem, ai: body.ai, ol: body.ol, soshu: body.soshu, // カテゴリ属性(複数可)
      workState: body.workState,           // 作品状態(新作/準新作/旧作)
      rebuild: body.rebuild,               // この動画自体が作り直し版(動画作成タブのリビルド)
      remade: body.remade,                 // この動画は作り直されて置き換え済み(投稿履歴の作り直し印)
      fanza_list_price: body.fanza_list_price, fanza_price: body.fanza_price,
      fanza_discount_pct: body.fanza_discount_pct, fanza_fetched_at: body.fanza_fetched_at || '',
      fanza_review_count: body.fanza_review_count, fanza_review_avg: body.fanza_review_avg
    });
    return jsonOut_({ ok: true, shortUrl: r.shortUrl, row: r.row });
  } catch (err) {
    return jsonOut_({ ok: false, error: String(err) });
  } finally {
    try { lock.releaseLock(); } catch (e) {}
  }
}

// cid 抽出。(作品URL の cid= か、アフィリンクの lurl をデコードして cid=)
//   ・FANZA Books(book.dmm.(com|co.jp)/product/…)は cid= を持たずパスにIDがあるため、
//     フロント(affiliate-core.js buildAffiliateLink)と同じ規則で内部cidを取り出す。
//     これをしないと Books 作品の「作品cid」列が空になり、復元時に作品URL/投稿済み判定が戻らない。
function extractCid_(url) {
  if (!url) return '';
  var s = String(url);
  // アフィリンク(al.fanza.co.jp/?lurl=…)なら中身のURLをデコードして同じ規則で解析。
  var lm = s.match(/[?&]lurl=([^&]+)/);
  if (lm) { try { var dec = decodeURIComponent(lm[1]); if (dec) { var inner = extractCid_(dec); if (inner) return inner; } } catch (e) {} }
  // FANZA Books：/product/【数字ID】/【content_id】/。2階層目があれば .com/.co.jp を問わず優先
  //   。(数字IDはDMM APIのcontent_id照会に使えないため。フロント affiliate-core.js と同一規則)
  var booksM = s.match(/book\.dmm\.(com|co\.jp)\/product\/([^/?&#\s]+)(?:\/([^/?&#\s]+))?/);
  if (booksM) return booksM[3] || booksM[2];
  // 同人・動画：cid= パラメータ。
  var m = s.match(/cid=([^/?&\s]+)/);
  if (m) return m[1];
  return '';
}
function extractHashtags_(t) { var m = String(t || '').match(/#[^\s#]+/g); return m ? m.join(' ') : ''; }

// 1始まり列番号 → Excel列文字。(A/B/.../Z/AA/AB/...)動的に列参照を組み立てるために使う。
function columnLetter_(n) {
  if (!n || n < 1) return '';
  var s = '';
  while (n > 0) { n--; s = String.fromCharCode(65 + n % 26) + s; n = Math.floor(n / 26); }
  return s;
}

// 計算列の数式。(行番号 r に合わせる)列文字は headerMap_ から動的に取得するため列の増減に強い。
function setComputed_(sh, map, r) {
  function set(h, f) { if (map[h]) sh.getRange(r, map[h]).setFormula(f); }
  set('曜日', '=IF($B' + r + '="","",CHOOSE(WEEKDAY($B' + r + '),"日","月","火","水","木","金","土"))');
  set('day-type', '=IF($B' + r + '="","",IF(OR(WEEKDAY($B' + r + ',2)>=6,COUNTIF(Holidays,INT($B' + r + '))>0),"土日祝",IF(OR(WEEKDAY($B' + r + '+1,2)>=6,COUNTIF(Holidays,INT($B' + r + ')+1)>0),"休前日","平日")))');
  set('時間帯スロット', '=IF($B' + r + '="","",IF(HOUR($B' + r + ')<5,"深夜",IF(HOUR($B' + r + ')<11,"朝",IF(HOUR($B' + r + ')<15,"昼",IF(HOUR($B' + r + ')<19,"夕","夜")))))');
  var cTitle = map['題名(コメント)'] ? columnLetter_(map['題名(コメント)']) : ''; // タイトル文字数(伸びる題名の傾向分析用・D-1)
  if (cTitle) set('タイトル文字数', '=IF(' + cTitle + r + '="","",LEN(' + cTitle + r + '))');
  var cClick  = columnLetter_(map[clickColName_(map)]); // 短縮URLクリック数(旧称：開封数/Bitlyクリック)
  var cViews  = columnLetter_(map['視聴回数']);
  // ★FANZA成約・報酬由来の数式(承認率/CVR/EPC/RPM)は撤去(2026-07-23)。
  //   分子となる手入力4列が一度も埋まらず(実測0件)、結果は常に0＝分析を汚すだけだった。
  //   FANZAは投稿単位の成約を返さないため、今後も埋まる見込みが無い。
  //   残すのは「両辺とも実データがある」リンククリック率%だけ。
  if (cClick && cViews) set('リンククリック率%','=IFERROR(' + cClick + r + '/' + cViews + r + ',"")');
}

// 純粋関数：post_id 列の値配列(2行目以降)と videoId から upsert 先の行番号(2始まり)を返す。
// 一致が無ければ 0。videoId 空なら 0。(=従来の空行再利用/追記へ)
// ※ tests/test_record_upsert.js に同一ロジックのミラーあり。(変更時は両方を揃える)
function upsertRowOf_(postIdCol, videoId) {
  if (!videoId) return 0;
  for (var j = 0; j < postIdCol.length; j++) { if (String(postIdCol[j]) === String(videoId)) return j + 2; }
  return 0;
}

// 1投稿を記録。(短縮失敗でも記録は残す)doPost・無人予約の両方から使用。
// videoId(背骨ID)があれば post_id をそれにし、同ID行へ upsert。(重複行を作らない・変更フィールドのみ更新)
// videoId 無し＝完全に従来動作。(後方互換)
function writeRecord_(channel, f) {
  // T10: 背骨ID(videoId)接頭辞が channel と矛盾するなら、正しいチャンネルへリダイレクト。(拒否でなく＝データ喪失なし)
  //   クライアント側にバグ/旧キャッシュがあっても、宵桜タブに acc1-… の誤行を作らせない最終防壁。
  //   move_row は writeRecord_ を通らないため影響なし。test- 接頭辞も考慮。
  var _pm = String(f.videoId || '').match(/^(?:test-)?(acc[12])-/);
  if (_pm && _pm[1] !== channel) channel = _pm[1];
  // 短縮URL：フロントが生成済みなら優先。(da.gd/link-worker＝実際に共有するURL)
  // 無い経路(無人予約・旧クライアント)だけ GAS が da.gd で短縮。(1投稿1回・トークン不要・軽量)
  // ※Bitlyは無料枠オーバーの主因かつ冗長(共有されず計測不能)なため全廃。
  var shortUrl = f.shortUrl || '';
  // ★短縮URL列は計測キー(r2)専用。(2026-07-12・①)GAS側のda.gd代替は共有URL列へのみ入れ、
  //   計測キー列にda.gd/生URLを混ぜない。(投稿履歴の「クリック–」化の根絶)
  var fbShare = '';
  if (!shortUrl && f.postUrl && !f.noShorten) fbShare = daGdShorten_(f.postUrl);
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
  // 投稿日時：履歴の実投稿時刻(postedAt)があれば最優先。無ければ新規行/投稿URL記録時のみ now。
  // (YouTube URLだけの後追いupsertでは上書きしない＝既存の投稿日時を保護)
  var postedDate = null;
  if (f.postedAt) { var pd = new Date(f.postedAt); if (!isNaN(pd.getTime())) postedDate = pd; }
  if (postedDate) put('投稿日時', postedDate);
  else if (isNewRow || f.postUrl) put('投稿日時', now);
  putIf('題名(コメント)', f.ytTitle || f.title || '');         // YouTube題名を優先して題名(コメント)へ集約
  putIf('作品cid', extractCid_(f.workUrl || f.affiliateUrl || ''));
  putIf('短縮URL', shortUrl);                                   // r2＝計測用(codeFromShort_対象・r2以外は入れない)
  putIf('作品短縮URL', f.workShortUrl || '');                    // 導線2(作品クリック)の計測URL=作品クリック数の日次スナップ元
  putIf('共有URL', f.shareUrl || fbShare || '');                // da.gd＝実際に概要欄へ貼る短いURL(GAS代替はこちらへ)
  putIf('YouTube動画URL', f.youtubeUrl || '');
  putIf('視聴回数', (f.views !== undefined && f.views !== null && f.views !== '') ? f.views : '');   // YouTube再生数
  putIf(clickColName_(map), (f.clicks !== undefined && f.clicks !== null && f.clicks !== '') ? f.clicks : ''); // 短縮URLクリック数
  putIf('post_uri', f.postUri || '');
  putIf('ハッシュタグ', f.hashtags || '');       // 受信していたのに書いていなかった取りこぼしを回収(D-1)
  putIf('リビルド元ID', f.rebuildOf || '');       // リビルド前後の再生数比較をシートで可能に(D-1)
  putIf('目的', f.goal || '');                    // 狙い(成約/集客)＝維持率とクリック数の二系統検証用
  putIf('コメント型', f.cmtType || '');           // コメント型(①〜⑧)＝勝ちパターン集計用
  // FANZA 価格スナップショット。(投稿時1回のみ。null は書かない＝既存値を保護)
  putIf('元値list_price', f.fanza_list_price !== undefined && f.fanza_list_price !== null ? f.fanza_list_price : '');
  putIf('割引後price', f.fanza_price !== undefined && f.fanza_price !== null ? f.fanza_price : '');
  putIf('割引率pct', f.fanza_discount_pct !== undefined && f.fanza_discount_pct !== null ? f.fanza_discount_pct : '');
  putIf('FANZA取得日時', f.fanza_fetched_at || '');
  putIf('レビュー件数(代理指標)', f.fanza_review_count !== undefined && f.fanza_review_count !== null ? f.fanza_review_count : '');
  putIf('レビュー平均', f.fanza_review_avg !== undefined && f.fanza_review_avg !== null ? f.fanza_review_avg : '');
  // カテゴリ：payload に属性フラグ(chara/jk/gyaru/isekai)が含まれるときだけ明示セット。(未指定なら既存値を保護)
  // キャラ無し＝オリジナルは空欄。複数属性はカンマ区切りで列挙。
  if (attrProvided_(f) && map['カテゴリ']) {
    sh.getRange(target, map['カテゴリ']).setValue(categoryOf_(f));
  }
  // 作品状態：投稿当時の状態。(新作/準新作/旧作)payload に含まれるときだけセット。
  putIf('作品状態', f.workState || '');
  // 作り直し列：明示指定があるときだけセット/解除。(未指定=既存値を保護)
  //   remade=true → 作り直し済(この動画を消して作り直した)／remade=false → 解除
  //   rebuild=true → リビルド版(この動画自体が作り直し版)
  if (map['作り直し']) {
    if (f.remade === true || f.remade === 'true') put('作り直し', '作り直し済');
    else if (f.remade === false || f.remade === 'false') put('作り直し', '');
    else if (f.rebuild === true || f.rebuild === 'true') put('作り直し', 'リビルド版');
  }
  // カウンタは新規行のみ0初期化。(upsert更新で既存のいいね数等を0で潰さない)
  if (isNewRow) { put('いいね', 0); put('リポスト', 0); put('返信', 0); }
  // 投稿履歴を正とし、投稿日時の新しい順にシートを並べ替える。(空日時は末尾へ)
  // 一括同期(sync_history)では noSort で抑止し、最後に1回だけ並べ替える。
  if (!f.noSort) sortByDate_(sh, dcol);
  return { shortUrl: shortUrl, row: target };
}

// 投稿履歴の一括同期：各アイテムを post_id(背骨ID)キーで upsert し、最後に1回だけ日付降順ソート。
// 投稿履歴を「正」とするため ID・投稿日時(postedAt)・キャラ属性も反映する。(冪等：再実行しても重複しない)
function syncHistory_(channel, items) {
  if (!items || !items.length) return jsonOut_({ ok: true, synced: 0 });
  var n = 0;
  for (var i = 0; i < items.length; i++) {
    var it = items[i] || {};
    if (!it.videoId) continue;
    try {
      writeRecord_(channel, {
        videoId: it.videoId, title: it.title || '', postUrl: it.postUrl || '',
        workUrl: it.workUrl || '', postUri: it.postUri || '', shortUrl: it.shortUrl || '', shareUrl: it.shareUrl || '',
        youtubeUrl: it.youtubeUrl || '', ytTitle: it.ytTitle || '', workShortUrl: it.workShortUrl || '',
        views: it.views, clicks: it.clicks,
        chara: it.chara, jk: it.jk, gyaru: it.gyaru, isekai: it.isekai, harem: it.harem, ai: it.ai, ol: it.ol, soshu: it.soshu, // カテゴリ属性(複数可)
        workState: it.workState,           // 作品状態(新作/準新作/旧作)
        rebuild: it.rebuild, remade: it.remade, // 作り直し(リビルド版/作り直し済)
        goal: it.goal, cmtType: it.cmtType, // 狙い・コメント型(履歴にあれば同期)
        postedAt: it.postedAt || '',
        noShorten: true, noSort: true   // 同期は短縮API呼ばず・並べ替えは最後にまとめて
      });
      n++;
    } catch (e) {}
  }
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  sortByDate_(sh, map['投稿日時'] || 2);
  return jsonOut_({ ok: true, synced: n });
}

// 投稿履歴の掃除：keepIds(アプリの全post_id)に含まれない行をクリアする。(行は詰めず内容クリア＝再利用可)
// アプリの投稿履歴を「正」とし、履歴から消した投稿をシートからも消す用途。指定チャンネルのタブのみ対象。
function pruneHistory_(channel, keepIds) {
  var sh = getChannelSheet_(channel), map = headerMap_(sh);
  var pidc = map['post_id']; var last = sh.getLastRow();
  if (!pidc || last < 2) return jsonOut_({ ok: true, cleared: 0 });
  var keep = {};
  for (var i = 0; i < keepIds.length; i++) { if (keepIds[i]) keep[String(keepIds[i])] = true; }
  var pids = sh.getRange(2, pidc, last - 1, 1).getValues();
  var cleared = 0;
  for (var r = 0; r < pids.length; r++) {
    var pid = String(pids[r][0] || '');
    if (!pid) continue;                  // 既に空の行はスキップ
    if (!keep[pid]) { sh.getRange(r + 2, 1, 1, sh.getLastColumn()).clearContent(); cleared++; }
  }
  sortByDate_(sh, map['投稿日時'] || 2); // 空行は末尾へ
  return jsonOut_({ ok: true, cleared: cleared });
}

// ============================================================
// 端末間 設定同期(鍵＝秘密以外の設定・投稿履歴を端末間で共有)
//   クライアントは非秘密の localStorage を JSON 化(blob)して push、別端末で pull→上書き→再読込。
//   秘密(app_pw/secret/api_key)はクライアント側で除外済み＝クラウドには保存しない。
//   保存先：非表示シート '_sync'。A1=メタJSON、A2以降=blobチャンク。(1セル約5万字上限を回避)
// ============================================================
function syncSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName('_sync');
  if (!sh) { sh = ss.insertSheet('_sync'); try { sh.hideSheet(); } catch (e) {} }
  return sh;
}
// 非秘密設定 blob を保存。(POST)既存内容は毎回全消去してから書き直す。(＝最新スナップショットのみ保持)
function settingsPush_(blob, updatedAt, device) {
  var sh = syncSheet_();
  sh.clearContents();
  blob = String(blob || '');
  var CH = 45000, chunks = [];
  for (var i = 0; i < blob.length; i += CH) chunks.push([blob.slice(i, i + CH)]);
  var meta = { updatedAt: updatedAt || new Date().toISOString(), device: String(device || ''), chunks: chunks.length, len: blob.length };
  sh.getRange(1, 1).setValue(JSON.stringify(meta));
  if (chunks.length) sh.getRange(2, 1, chunks.length, 1).setValues(chunks);
  return jsonOut_({ ok: true, len: blob.length, chunks: chunks.length, updatedAt: meta.updatedAt });
}
// メタのみ返す。(軽量・状態表示用。JSONP GET)
function settingsMeta_() {
  var sh = syncSheet_();
  var v = sh.getRange(1, 1).getValue();
  if (!v) return { ok: true, empty: true };
  var meta = {}; try { meta = JSON.parse(v); } catch (e) { return { ok: true, empty: true }; }
  return { ok: true, empty: false, updatedAt: meta.updatedAt || '', device: meta.device || '', len: meta.len || 0 };
}
// blob 全体を返す。(JSONP GET)チャンクを結合して復元。
function settingsPull_() {
  var sh = syncSheet_();
  var last = sh.getLastRow();
  if (last < 2) return { ok: true, empty: true };
  var meta = {}; try { meta = JSON.parse(sh.getRange(1, 1).getValue() || '{}'); } catch (e) {}
  var vals = sh.getRange(2, 1, last - 1, 1).getValues();
  var blob = ''; for (var i = 0; i < vals.length; i++) blob += (vals[i][0] || '');
  return { ok: true, empty: false, blob: blob, updatedAt: meta.updatedAt || '', device: meta.device || '', len: blob.length };
}

// 記録シートを「投稿日時」降順で並べ替える。(ヘッダ行は固定、2行目以降が対象)
// 計算列の数式は行相対参照($B<row>)のため、並べ替えでも各行が自分の日時を正しく参照する。
function sortByDate_(sh, dcol) {
  var last = sh.getLastRow();
  if (last < 3) return; // データ行が0〜1件なら並べ替え不要
  sh.getRange(2, 1, last - 1, sh.getLastColumn()).sort({ column: dcol, ascending: false });
}

// ---- 短縮URL(da.gd・トークン不要・1投稿1回だけ。失敗時は空＝長いURLのまま記録) ----
//   ※Bitlyは全廃。(無料枠オーバーの主因かつ冗長)クリック計測は link-worker(KV) 側に一本化する方針。
function daGdShorten_(longUrl) {
  if (!longUrl) return '';
  try {
    var res = UrlFetchApp.fetch('https://da.gd/s?url=' + encodeURIComponent(longUrl), { muteHttpExceptions: true });
    if (res.getResponseCode() >= 300) return '';
    var t = String(res.getContentText() || '').trim();
    return /^https?:\/\//.test(t) ? t : '';
  } catch (e) { return ''; }
}

// ---- link-worker 開封数の取り込み(①計測の見える化) ----
//   YT説明欄に貼る短縮URL(go5-short/<code>)の「開かれた回数」を /api/stats から取得し、
//   テンプレ列「Bitlyクリック」(＝今後は link-worker の開封数の意味)に毎時反映する。
//   ※列名はテンプレ互換のため変えない。(意味だけ Bitly→開封数 に変更)
var SHORT_WORKER_URL = 'https://r2.trustsignalbot.workers.dev';
// ★このリストは「自前の計測リンクか」を判定する唯一の材料。**フロント(bluesky.js SHORT.WORKER_HOSTS)と
//   必ず揃えること**。片方だけ新ドメインを足すと、GASがコードを抽出できず視聴履歴シートの
//   クリック列が空のまま→画面は「取得⚠️」になる(2026-07-20 INC-112の実際の事故)。
//   ・5mgl.com(月詠み/acc1) と yoz2.com(宵桜艶帖/acc2) は2026-07-20に切替。同一worker・同一KV。
//   ・旧ホスト(r2/go5-short)は発行済みリンクの計測継続のため残す。
var SHORT_WORKER_HOSTS = [
  'https://5mgl.com',                                 // acc1(月詠み)・現行
  'https://yoz2.com',                                 // acc2(宵桜艶帖)・現行
  'https://r2.trustsignalbot.workers.dev',            // 旧(現在も生存)
  'https://go5-short.trustsignalbot.workers.dev'      // 最旧
];
function shortSecret_() { return prop_('SHORT_SHARED_SECRET') || 'daremogamewoubawareteikukimihakanpekidekyukyokunoidol'; }
// 自前ワーカーのURLから末尾コードを抽出。(da.gd等の別ホストは '')
function codeFromShort_(url) {
  var s = String(url || '');
  for (var i = 0; i < SHORT_WORKER_HOSTS.length; i++) {
    var base = SHORT_WORKER_HOSTS[i].replace(/\/+$/, '');
    if (s.indexOf(base + '/') === 0) {
      var rest = s.slice(base.length + 1).split(/[/?#]/)[0];
      if (/^[0-9A-Za-z]+$/.test(rest)) return rest;
    }
  }
  // ★未知ホストを無言で捨てない。ドメイン切替の取りこぼし(＝クリックが永久に空欄)は
  //   静かに起きると誰も気づけない。自前ドメイン風のURLだけログに出す(da.gd等の想定内は除く)。
  if (s && !/^https?:\/\/(da\.gd|tinyurl\.com)\//.test(s)) {
    try { Logger.log('codeFromShort_: 未知の短縮ホスト=' + s + ' (SHORT_WORKER_HOSTSに追加が必要かもしれません)'); } catch (e) {}
  }
  return '';
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
// 毎時：直近200行のうち短縮URLが go5-short のものだけ開封数を更新。(軽量・クォータ安全)
function refreshClicks() {
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow();
    var clickCol = map[clickColName_(map)]; // 短縮URLクリック数(旧名 開封数/Bitlyクリック も互換)
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

// ---- Bluesky反応(いいね/リポスト/返信)の定期更新。(毎時トリガー)公開API getPosts を25件ずつ ----
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

// ============================================================
// 再生数・クリック数の自動スナップショット(毎時トリガー)＝アプリ未起動でも記録される。
//   視聴履歴シートに (日付, videoId) 単位で「その日の最新の累計」を upsert。
//   これを差分計算(computeDeltas_)して 今日/昨日/直近1週間 の増加を出す。
//   ※再生数取得には Script Property `YT_API_KEY`(アプリ⚙のYouTube APIキーと同値)が必要。
// ============================================================
var STATS_SHEET = '視聴履歴';
var STATS_HEADERS = ['記録日時', '日付', 'channel', 'post_id', 'videoId', '再生数', '短縮URLクリック数', '作品クリック数'];
function statsSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName(STATS_SHEET) || ss.insertSheet(STATS_SHEET);
  if (sh.getLastRow() === 0) sh.appendRow(STATS_HEADERS);
  return sh;
}
// 最大瞬間風速(一番伸びた区間の伸び率と時間帯)を作品ごとに永続保存するシート。
var PEAK_SHEET = 'ピーク記録';
var PEAK_HEADERS = ['videoId', '再生ピーク(件/時)', '再生ピーク時間帯', 'クリックピーク(件/時)', 'クリックピーク時間帯', '更新日時'];
function peakSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName(PEAK_SHEET) || ss.insertSheet(PEAK_SHEET);
  if (sh.getLastRow() === 0) sh.appendRow(PEAK_HEADERS);
  return sh;
}
// ピーク記録シート → videoIdごとの {vRate,vWin,cRate,cWin}。
function computePeaks_() {
  var sh = peakSheet_(); var last = sh.getLastRow(); if (last < 2) return {};
  var d = sh.getRange(2, 1, last - 1, PEAK_HEADERS.length).getValues(); var out = {};
  d.forEach(function (r) { if (!r[0]) return; out[r[0]] = { vRate: r[1] === '' ? null : Number(r[1]), vWin: r[2] || '', cRate: r[3] === '' ? null : Number(r[3]), cWin: r[4] || '' }; });
  return out;
}
function ytApiKey_() { return prop_('YT_API_KEY') || ''; }
function ytIdFromUrl_(u) {
  u = String(u || '');
  var m = u.match(/[?&]v=([0-9A-Za-z_-]{6,})/) || u.match(/youtu\.be\/([0-9A-Za-z_-]{6,})/) || u.match(/shorts\/([0-9A-Za-z_-]{6,})/);
  return m ? m[1] : '';
}
function ytViews_(ids) {
  var key = ytApiKey_(), out = {};
  if (!key || !ids.length) return out;
  for (var i = 0; i < ids.length; i += 50) {
    var batch = ids.slice(i, i + 50);
    try {
      var u = 'https://www.googleapis.com/youtube/v3/videos?part=statistics&id=' + batch.join(',') + '&key=' + encodeURIComponent(key);
      var res = UrlFetchApp.fetch(u, { muteHttpExceptions: true });
      if (res.getResponseCode() >= 300) continue;
      var d = JSON.parse(res.getContentText() || '{}');
      (d.items || []).forEach(function (it) { if (it && it.id && it.statistics && it.statistics.viewCount != null) out[it.id] = parseInt(it.statistics.viewCount, 10); });
    } catch (e) {}
    Utilities.sleep(120);
  }
  return out;
}
function snapshotStats() {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var today = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  var nowStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm');
  var recs = [], tpRecs = []; // tpRecs=時点記録(投稿からの経過バケット)用の全行(vid無し・クリックのみも含む)
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name); if (!sh) return;
    var map = headerMap_(sh); var last = sh.getLastRow(); if (last < 2) return;
    var pidc = map['post_id'], ytc = map['YouTube動画URL'], sc = map['短縮URL'], dc = map['投稿日時'], wsc = map['作品短縮URL'];
    var chKey = (name === '宵桜艶帖') ? 'acc2' : 'acc1';
    var vals = sh.getRange(2, 1, last - 1, sh.getLastColumn()).getValues();
    vals.forEach(function (row) {
      var vid = ytc ? ytIdFromUrl_(row[ytc - 1]) : '';
      var code = sc ? codeFromShort_(row[sc - 1]) : '';
      var wcode = wsc ? codeFromShort_(row[wsc - 1]) : ''; // 導線2(作品クリック)の計測コード
      // 時点記録(⑤)用: vidが無くてもクリックだけ記録できるよう、YT未連携行も対象に含める。
      var pd = dc ? row[dc - 1] : '';
      var pms = pd instanceof Date ? pd.getTime() : (pd ? (new Date(String(pd).replace(/-/g, '/'))).getTime() : 0);
      if ((vid || code) && pms) tpRecs.push({ channel: chKey, post_id: pidc ? String(row[pidc - 1] || '') : '', vid: vid, code: code, postedAtMs: pms });
      if (!vid) return;
      recs.push({ channel: chKey, post_id: pidc ? String(row[pidc - 1] || '') : '', vid: vid, code: code, wcode: wcode });
    });
  });
  if (!recs.length && !tpRecs.length) return;
  // 同一videoId(同じ動画を複数投稿・両ch)で重複行を作らないよう vid で1件に正規化。(最初の1件＝コード保持)
  var seenVid = {}, urecs = [];
  recs.forEach(function (r) { if (r.vid && !seenVid[r.vid]) { seenVid[r.vid] = 1; urecs.push(r); } });
  recs = urecs;
  // セール会場リンク(導線3・共通コードJrziR=campaign利用のutm先)も日次記録する。(2026-07-14 Chami依頼)
  //   vid='SALE'の擬似行として保存→computeDeltas_が自動で今日/昨日/週を算出し、フロントの🏮表示が使う。
  recs.push({ channel: '-', post_id: 'SALE', vid: 'SALE', code: 'JrziR' });
  var vids = recs.map(function (r) { return r.vid; });
  var views = ytViews_(vids);
  var clickByCode = {};
  // 導線1(短縮URL)＋導線2(作品短縮URL)の両コードのクリックをまとめて取得。(同一コードは1回)
  recs.concat(tpRecs).forEach(function (r) {
    if (r.code && clickByCode[r.code] === undefined) { clickByCode[r.code] = workerClicks_(r.code); Utilities.sleep(80); }
    if (r.wcode && clickByCode[r.wcode] === undefined) { clickByCode[r.wcode] = workerClicks_(r.wcode); Utilities.sleep(80); }
  });
  var sh = statsSheet_(); var last = sh.getLastRow();
  var data = last >= 2 ? sh.getRange(2, 1, last - 1, STATS_HEADERS.length).getValues() : [];
  // ★日付列はSheetが 'yyyy-MM-dd' 文字列を Date に自動変換して返すことがある。キーは必ず
  //   同一TZの 'yyyy-MM-dd' 文字列に正規化する(Dateのまま比較すると today 文字列と一致せず、
  //   同日行の upsert が効かず重複追記＆deltas全null になる)。
  var idx = {}; for (var i = 0; i < data.length; i++) idx[ymd_(data[i][1], tz) + '|' + data[i][4]] = i + 2;
  // 前回スナップ(vidごとの最新の累計と時刻)＝最大瞬間風速(区間の伸び率)算出用。
  var prevByVid = {};
  for (var j = 0; j < data.length; j++) {
    var pv = data[j][4]; if (!pv) continue;
    var tstr = String(data[j][0] || ''), tms = Date.parse(tstr.replace(' ', 'T')) || 0;
    var pp = prevByVid[pv];
    if (!pp || tms > pp.tms) prevByVid[pv] = { tms: tms, tstr: tstr, views: data[j][5] === '' ? null : Number(data[j][5]), clicks: data[j][6] === '' ? null : Number(data[j][6]) };
  }
  var nowMs = new Date().getTime();
  // ピーク記録シートを読み込み。(vidごとの現ピーク)今runの更新はpeakUpdatesへ。
  var psh = peakSheet_(); var plast = psh.getLastRow();
  var pdata = plast >= 2 ? psh.getRange(2, 1, plast - 1, PEAK_HEADERS.length).getValues() : [];
  var pidx = {}; for (var pk = 0; pk < pdata.length; pk++) pidx[pdata[pk][0]] = pk + 2;
  var peakUpdates = {};
  function curPeak_(vid, kind) {
    if (peakUpdates[vid] && peakUpdates[vid][kind + 'Rate'] != null) return peakUpdates[vid][kind + 'Rate'];
    var rn = pidx[vid]; if (rn) { var col = kind === 'v' ? 1 : 3; var val = pdata[rn - 2][col]; return val === '' ? null : Number(val); }
    return null;
  }
  function considerPeak_(vid, kind, rate, win) {
    if (rate == null || !(rate > 0)) return; // 増加区間のみ
    var cur = curPeak_(vid, kind);
    if (cur == null || rate > cur) { var u = peakUpdates[vid] || (peakUpdates[vid] = {}); u[kind + 'Rate'] = Math.round(rate * 10) / 10; u[kind + 'Win'] = win; }
  }
  var appends = [];
  recs.forEach(function (r) {
    var v = views[r.vid]; var c = r.code ? clickByCode[r.code] : null;
    var wc = r.wcode ? clickByCode[r.wcode] : null; // 導線2(作品クリック)
    if (v == null && c == null && wc == null) return;
    var key = today + '|' + r.vid, rowN = idx[key];
    if (rowN && rowN > 0) {
      sh.getRange(rowN, 1).setValue(nowStr);
      if (v != null) sh.getRange(rowN, 6).setValue(v);
      if (c != null) sh.getRange(rowN, 7).setValue(c);
      if (wc != null) sh.getRange(rowN, 8).setValue(wc); // 作品クリック数列
    } else {
      appends.push([nowStr, today, r.channel, r.post_id, r.vid, v == null ? '' : v, c == null ? '' : c, wc == null ? '' : wc]);
      idx[key] = -1;
    }
    // 最大瞬間風速：前回スナップからの伸び率。(件/時)妥当な間隔(0.2〜6h)のみ採用。
    var prev = prevByVid[r.vid];
    if (prev && prev.tms) {
      var hrs = (nowMs - prev.tms) / 3600000;
      if (hrs >= 0.2 && hrs <= 6) {
        var win = String(prev.tstr).slice(5) + '〜' + nowStr.slice(11); // MM-dd HH:mm〜HH:mm
        if (v != null && prev.views != null) considerPeak_(r.vid, 'v', (v - prev.views) / hrs, win);
        if (c != null && prev.clicks != null) considerPeak_(r.vid, 'c', (c - prev.clicks) / hrs, win);
      }
    }
  });
  if (appends.length) sh.getRange(sh.getLastRow() + 1, 1, appends.length, STATS_HEADERS.length).setValues(appends);
  // ピーク更新を永続化。(vidごとにupsert。既存より大きい時だけ更新済み)
  Object.keys(peakUpdates).forEach(function (vid) {
    var u = peakUpdates[vid], rn = pidx[vid];
    if (rn) {
      if (u.vRate != null) { psh.getRange(rn, 2).setValue(u.vRate); psh.getRange(rn, 3).setValue(u.vWin); }
      if (u.cRate != null) { psh.getRange(rn, 4).setValue(u.cRate); psh.getRange(rn, 5).setValue(u.cWin); }
      psh.getRange(rn, 6).setValue(nowStr);
    } else {
      psh.appendRow([vid, u.vRate == null ? '' : u.vRate, u.vWin || '', u.cRate == null ? '' : u.cRate, u.cWin || '', nowStr]);
      pidx[vid] = psh.getLastRow();
    }
  });
  pruneStats_(sh, 12);
  // CH書き戻し(2026-07-13A・Chami依頼): 累計再生/クリックを投稿記録シートの列にも反映し、
  //   YouTubeの下方補正(前回スナップより累計が減った分)は「YT補正累計」列へ累積する。
  //   デルタ(昨日/週)は従来通り実測(マイナスあり得る)＝真の視聴増はこの列の増分を引けば分離できる。
  try {
    var corrByVid = {};
    recs.forEach(function (r0) {
      var v0 = views[r0.vid], p0 = prevByVid[r0.vid];
      if (v0 != null && p0 && p0.views != null && v0 < p0.views) corrByVid[r0.vid] = p0.views - v0;
    });
    CH_SHEETS.forEach(function (name3) {
      var ss3 = openSS_(); var sh3 = ss3.getSheetByName(name3); if (!sh3) return;
      var map3 = headerMap_(sh3); var l3 = sh3.getLastRow(); if (l3 < 2) return;
      var ytc3 = map3['YouTube動画URL']; if (!ytc3) return;
      var vc3 = map3['視聴回数'], cc3 = map3[clickColName_(map3)], sc3 = map3['短縮URL'], corrc3 = map3['YT補正累計'];
      var vals3 = sh3.getRange(2, 1, l3 - 1, sh3.getLastColumn()).getValues();
      for (var r3 = 0; r3 < vals3.length; r3++) {
        var vid3 = ytIdFromUrl_(vals3[r3][ytc3 - 1]); if (!vid3) continue;
        var rowN3 = r3 + 2;
        var v3 = views[vid3];
        if (vc3 && v3 != null && Number(vals3[r3][vc3 - 1]) !== v3) sh3.getRange(rowN3, vc3).setValue(v3);
        var code3 = sc3 ? codeFromShort_(vals3[r3][sc3 - 1]) : '';
        var c3 = code3 ? clickByCode[code3] : null;
        if (cc3 && c3 != null && Number(vals3[r3][cc3 - 1]) !== c3) sh3.getRange(rowN3, cc3).setValue(c3);
        var corr3 = corrByVid[vid3];
        if (corrc3 && corr3 > 0) {
          var cur3 = Number(vals3[r3][corrc3 - 1] || 0);
          sh3.getRange(rowN3, corrc3).setValue(cur3 + corr3);
        }
      }
    });
  } catch (e) {}
  // ⑤時点記録: 投稿からの経過バケット(30分〜72h)を跨いだ最初のスナップで再生数/クリック数を確定記録。
  try { captureTimepoints_(tpRecs, views, clickByCode, nowStr, tz); } catch (e) {}
}
// 12日より古い履歴行を掃除。(週次差分に必要なぶんだけ保持)
function pruneStats_(sh, keepDays) {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var cut = new Date(); cut.setDate(cut.getDate() - keepDays);
  var cutStr = Utilities.formatDate(cut, tz, 'yyyy-MM-dd');
  var last = sh.getLastRow(); if (last < 2) return;
  var dates = sh.getRange(2, 2, last - 1, 1).getValues();
  for (var i = dates.length - 1; i >= 0; i--) { if (ymd_(dates[i][0], tz) < cutStr) sh.deleteRow(i + 2); } // ★Date/文字列を正規化して比較
}
// 日付セルを 'yyyy-MM-dd' 文字列に正規化。(Date/文字列どちらで返っても同一TZの日付キーにする)
function ymd_(v, tz) {
  tz = tz || Session.getScriptTimeZone() || 'Asia/Tokyo';
  if (v instanceof Date) return Utilities.formatDate(v, tz, 'yyyy-MM-dd');
  var s = String(v || '');
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/); if (m) return m[0];
  var d = new Date(s); return isNaN(d.getTime()) ? s : Utilities.formatDate(d, tz, 'yyyy-MM-dd');
}
// 視聴履歴から videoId ごとの 今日/昨日/直近1週間 の増加(再生数・クリック数)を算出。
function computeDeltas_() {
  var tz = Session.getScriptTimeZone() || 'Asia/Tokyo';
  var sh = statsSheet_(); var last = sh.getLastRow(); if (last < 2) return {};
  var data = sh.getRange(2, 1, last - 1, STATS_HEADERS.length).getValues();
  var byVid = {};
  data.forEach(function (row) {
    var date = ymd_(row[1], tz), vid = row[4]; if (!vid || !date) return; // ★日付は文字列キーに正規化
    (byVid[vid] || (byVid[vid] = {}))[date] = { v: row[5] === '' ? null : Number(row[5]), c: row[6] === '' ? null : Number(row[6]), w: (row[7] === '' || row[7] == null) ? null : Number(row[7]) };
  });
  // 投稿日(vid別・最古)を記録シートから取得。ベースライン不在時の「0起点」判定に使う(Chami仕様2026-07-12):
  //   ・今日/昨日=その暦日の増分(投稿日に関係なく) ・週=直近7日間の合計
  //   ・投稿日が期間内でベースラインが存在し得ない場合は0起点(例: 今日投稿→今日=累計そのまま・週=同)
  //   ・「–」が許されるのは今日投稿の「昨日」のみ
  var postedByVid = {};
  CH_SHEETS.forEach(function (name) {
    var ss2 = openSS_(); var sh2 = ss2.getSheetByName(name); if (!sh2) return;
    var map2 = headerMap_(sh2); var l2 = sh2.getLastRow(); if (l2 < 2) return;
    var ytc2 = map2['YouTube動画URL'], dc2 = map2['投稿日時']; if (!ytc2 || !dc2) return;
    sh2.getRange(2, 1, l2 - 1, sh2.getLastColumn()).getValues().forEach(function (row) {
      var v2 = ytIdFromUrl_(row[ytc2 - 1]); if (!v2) return;
      var ds2 = ymd_(row[dc2 - 1], tz); if (!ds2) return;
      if (!postedByVid[v2] || ds2 < postedByVid[v2]) postedByVid[v2] = ds2;
    });
  });
  function dstr(off) { var d = new Date(); d.setDate(d.getDate() + off); return Utilities.formatDate(d, tz, 'yyyy-MM-dd'); }
  var today = dstr(0), yest = dstr(-1), wk = dstr(-7);
  var ZERO = { v: 0, c: 0 };
  var out = {};
  Object.keys(byVid).forEach(function (vid) {
    var m = byVid[vid], dates = Object.keys(m).sort();
    var posted = postedByVid[vid] || '';
    // ★列ごと(v=再生/c=クリック)に独立して基準を解決する。(2026-07-12C・根本修正)
    //   「再生数は前から記録・クリックは今日から記録開始」のような列単位のズレで、
    //   既存スナップの空欄(null)を基準に採って⚠を出していた設計ミスを直す。
    //   規則: 基準日以前に非nullが無い列=「その列の記録がまだ始まっていなかった」→0起点。
    //   (今日投稿の0起点・7日以内投稿の週0起点も、この一般則に自然に含まれる)
    function lastNonNull(k, ds, inclusive) { // ds以前(未満)で最後にk列が非nullだった値
      var best = null;
      for (var i = 0; i < dates.length; i++) {
        var ok = inclusive ? (dates[i] <= ds) : (dates[i] < ds);
        if (ok && m[dates[i]][k] != null) best = m[dates[i]][k];
      }
      return best;
    }
    function curOf(k) { var c = m[today]; if (c && c[k] != null) return c[k]; return lastNonNull(k, '9999-99-99', true); }
    function calc(k) {
      var cur = curOf(k);
      if (cur == null) return { t: null, y: null, w: null }; // その列は一度も記録なし=正直に⚠(取得失敗系)
      var bT = lastNonNull(k, today, false); if (bT == null) bT = 0;   // 今日の基準: 無ければ記録開始=今日→0起点
      var bW = lastNonNull(k, wk, true);     if (bW == null) bW = 0;   // 週の基準: 無ければ記録開始が7日以内→0起点
      var y;
      if (posted === today) y = null; // 唯一の–許容(今日投稿の昨日)
      else {
        var aY = lastNonNull(k, today, false);         // 昨日終了時点の値
        var bY = lastNonNull(k, yest, false);          // 一昨日終了時点の値(無ければ記録開始が昨日→0起点)
        y = (aY == null) ? null : (aY - (bY == null ? 0 : bY)); // aY自体が無い=昨日以前の記録ゼロ→⚠(不可知)
      }
      return { t: cur - bT, y: y, w: cur - bW };
    }
    var V = calc('v'), C = calc('c'), W = calc('w');
    // twc/ywc/wwc = 導線2(作品クリック=ピンク矢印)の今日/昨日/週デルタ。(Chami依頼2026-07-14)
    out[vid] = { tv: V.t, yv: V.y, wv: V.w, tc: C.t, yc: C.y, wc: C.w, twc: W.t, ywc: W.y, wwc: W.w };
  });
  return out;
}

// 初回1回：毎時トリガーを登録。
//   refreshClicks＝link-worker 開封数の取り込み／refreshEngagement＝Bluesky反応／
//   snapshotStats＝再生数・クリック数の日次スナップショット。(今日/昨日/週の増加算出用)
//   再実行で既存トリガーを掃除してから貼り直す。
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var f = t.getHandlerFunction();
    if (f === 'refreshClicks' || f === 'refreshEngagement' || f === 'snapshotStats' ||
        f === 'runCompetitorDaily' || f === 'runCompetitorDiscovery') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('refreshClicks').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('refreshEngagement').timeBased().everyHours(1).create();
  // ⑤時点記録(30分バケット)の精度確保のためスナップを30分毎に。(日次スナップはupsertなので2回/時でも無害)
  ScriptApp.newTrigger('snapshotStats').timeBased().everyMinutes(30).create();
  // 競合サーチ(gas/競合.gs): 日次スナップ=毎日4時台 / 発見=日曜4時台。watch対象0件の間は無害に空回り
  ScriptApp.newTrigger('runCompetitorDaily').timeBased().everyDays(1).atHour(4).create();
  ScriptApp.newTrigger('runCompetitorDiscovery').timeBased().onWeekDay(ScriptApp.WeekDay.SUNDAY).atHour(4).create();
}

// ============================================================
// ⑤ 時点記録: 投稿時刻からの経過バケット(30分/1h/2h/6h/24h/72h)ごとに、そのバケットを
//   跨いだ最初のスナップ実行時の再生数・クリック数を「時点記録」シートへ確定保存する。
//   旧実装(ランキングタブのlocalStorageバケット)は端末でアプリを開いた時しか記録されず
//   欠測が常態化していたため、サーバー(30分毎トリガー)で確実に記録する。(2026-07-12)
//   ・許容窓を過ぎたバケットは記録しない(遅れた値を「その時点の値」と偽らない)＝空欄は未記録の正直な表現
//   ・1行=1。(post_id×バケット)分析はピボットで post_id 別に横持ち化できる
// ============================================================
var TIMEPOINT_SHEET = '時点記録';
var TIMEPOINT_HEADERS = ['post_id', 'channel', '投稿日時', 'バケット', '経過分(実測)', '再生数', 'クリック数', '記録日時'];
var TIME_BUCKETS = [[30, '30分'], [60, '1時間'], [120, '2時間'], [360, '6時間'], [1440, '24時間'], [4320, '72時間']];
function timepointSheet_() {
  var ss = openSS_(); var sh = ss.getSheetByName(TIMEPOINT_SHEET);
  if (!sh) { sh = ss.insertSheet(TIMEPOINT_SHEET); sh.appendRow(TIMEPOINT_HEADERS); }
  else if (sh.getLastRow() === 0) { sh.appendRow(TIMEPOINT_HEADERS); }
  return sh;
}
function captureTimepoints_(tpRecs, viewsByVid, clickByCode, nowStr, tz) {
  if (!tpRecs || !tpRecs.length) return 0;
  var sh = timepointSheet_(); var last = sh.getLastRow();
  var seen = {};
  if (last >= 2) {
    var ex = sh.getRange(2, 1, last - 1, 4).getValues();
    for (var i = 0; i < ex.length; i++) seen[String(ex[i][0]) + '|' + String(ex[i][3])] = 1;
  }
  var now = Date.now(); var added = [];
  tpRecs.forEach(function (r) {
    if (!r.post_id || !r.postedAtMs) return;
    var elapsed = (now - r.postedAtMs) / 60000;
    TIME_BUCKETS.forEach(function (b) {
      var min = b[0], label = b[1];
      if (elapsed < min) return;
      var tol = Math.max(45, min * 0.5); // 30分トリガー前提の許容窓。超過分は未記録のまま(誤値を作らない)
      if (elapsed > min + tol) return;
      if (seen[r.post_id + '|' + label]) return;
      var v = (r.vid && viewsByVid && viewsByVid[r.vid] != null) ? viewsByVid[r.vid] : '';
      var c = (r.code && clickByCode && clickByCode[r.code] != null) ? clickByCode[r.code] : '';
      if (v === '' && c === '') return; // どちらも取れない行は書かない
      added.push([r.post_id, r.channel, Utilities.formatDate(new Date(r.postedAtMs), tz, 'yyyy-MM-dd HH:mm'), label, Math.round(elapsed), v, c, nowStr]);
      seen[r.post_id + '|' + label] = 1;
    });
  });
  if (added.length) sh.getRange(sh.getLastRow() + 1, 1, added.length, TIMEPOINT_HEADERS.length).setValues(added);
  return added.length;
}

// ============================================================
// ⑥ 列順統一: 両chシートの列を CANONICAL_HEADERS の並びへ固定する。(冪等)
//   無い列は正位置へ挿入。(空)CANONICALに無い列は末尾へ自然に寄る。値・書式ごとmoveColumnsで移動。
// ============================================================
function reorderHeaders_() {
  var out = {};
  CH_SHEETS.forEach(function (name) {
    var ss = openSS_(); var sh = ss.getSheetByName(name);
    if (!sh || sh.getLastRow() === 0) { out[name] = 'not_found'; return; }
    var moved = 0, inserted = 0;
    for (var target = 0; target < CANONICAL_HEADERS.length; target++) {
      var lastCol = sh.getLastColumn();
      var headers = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(function (h) { return String(h); });
      var cur = headers.indexOf(CANONICAL_HEADERS[target]);
      if (cur === -1) {
        // 挿入位置が現在の列数を超える(=canonical末尾に新列を足した)場合はinsertColumnBeforeが範囲外エラーに
        // なるため末尾追加に切り替える。(2026-07-13B: YT補正累計の追加で発覚)
        if (target + 1 <= lastCol) sh.insertColumnBefore(target + 1); else sh.insertColumnAfter(lastCol);
        sh.getRange(1, target + 1).setValue(CANONICAL_HEADERS[target]); inserted++; continue;
      }
      if (cur === target) continue;
      sh.moveColumns(sh.getRange(1, cur + 1, sh.getMaxRows(), 1), target + 1); // 左方向への移動のみ発生(cur>target)
      moved++;
    }
    var finalHeaders = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
    out[name] = { moved: moved, inserted: inserted, cols: sh.getLastColumn(), extraTail: finalHeaders.slice(CANONICAL_HEADERS.length) };
  });
  return out;
}

// ============================================================
// Phase5：無人予約投稿(タブを閉じても、時間トリガーが自動投稿)
//   追加プロパティ：BSKY_HANDLE / BSKY_APP_PW。画像は base64→ドライブ一時保存→投稿後ゴミ箱。
// ============================================================
var RES_SHEET = '予約';
var RES_HEADERS = ['予約ID', '予約日時', '本文', '画像fileId', 'slot_id', 'ステータス', '結果URI', '結果URL', '投稿日時', 'エラー', 'channel', 'meta'];
var RCOL = { id: 1, when: 2, text: 3, img: 4, slot: 5, status: 6, uri: 7, url: 8, postedAt: 9, error: 10, channel: 11, meta: 12 };

function getResSheet_() {
  var ss = openSS_();
  var sh = ss.getSheetByName(RES_SHEET) || ss.insertSheet(RES_SHEET);
  if (sh.getLastRow() === 0) { sh.appendRow(RES_HEADERS); return sh; }
  // 既存シートに meta 列が無ければ末尾に追加。(冪等・D-1で追加)
  if (sh.getLastColumn() < RES_HEADERS.length) {
    var hdr = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
    if (hdr.indexOf('meta') === -1) sh.getRange(1, RCOL.meta).setValue('meta');
  }
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
  // 動画メタ(videoId/カテゴリ/作品状態/リビルド元)をJSONで保持→投稿時に記録へ中継。(D-1・薄い行の解消)
  row[RCOL.meta - 1] = body.meta ? (typeof body.meta === 'string' ? body.meta : JSON.stringify(body.meta)) : '';
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
      var res = bskyPost_(text, blob, ch); // ★予約行のchannelの資格情報で投稿(誤アカウント防止)
      sh.getRange(i + 2, RCOL.status).setValue('posted');
      sh.getRange(i + 2, RCOL.uri).setValue(res.uri);
      sh.getRange(i + 2, RCOL.url).setValue(res.postUrl);
      sh.getRange(i + 2, RCOL.postedAt).setValue(new Date());
      try {
        // 予約時に凍結した動画メタ(videoId/カテゴリ/作品状態/リビルド元)を記録へ中継。(D-1)
        var meta = {};
        try { var mj = rows[i][RCOL.meta - 1]; if (mj) meta = JSON.parse(mj) || {}; } catch (e) { meta = {}; }
        var attrs = meta.attrs || {};
        writeRecord_(ch, {
          videoId: meta.videoId || '',
          title: (String(text).split('\n')[0] || ''), postUrl: res.postUrl,
          affiliateUrl: (String(text).match(/https?:\/\/[^\s]+/) || [''])[0],
          workUrl: meta.workUrl || '', hashtags: extractHashtags_(text), postUri: res.uri,
          workState: meta.workState, rebuild: meta.rebuild, rebuildOf: meta.rebuildOf || '',
          goal: meta.goal || '', cmtType: meta.cmtType || '',
          chara: attrs.chara, jk: attrs.jk, gyaru: attrs.gyaru, isekai: attrs.isekai, harem: attrs.harem, ai: attrs.ai, ol: attrs.ol, soshu: attrs.soshu
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

// Bluesky 投稿。(サーバー側＝GASのアプリパスワードで投稿)
// ★channel別の資格情報(BSKY_HANDLE_ACC1/_ACC2 等)を優先。無ければ従来のBSKY_HANDLE/PWにフォールバック。
//   これで無人予約が「予約したアカウントとは別のアカウントで実投稿される」取り違えを防ぐ。
function bskyCreds_(channel) {
  var suf = channel === 'acc2' ? '_ACC2' : '_ACC1';
  var h = prop_('BSKY_HANDLE' + suf), p = prop_('BSKY_APP_PW' + suf);
  if (h && p) return { handle: h, pw: p, scoped: true };
  var otherSuf = channel === 'acc2' ? '_ACC1' : '_ACC2';
  var otherScopedSet = !!(prop_('BSKY_HANDLE' + otherSuf) && prop_('BSKY_APP_PW' + otherSuf));
  return { handle: prop_('BSKY_HANDLE'), pw: prop_('BSKY_APP_PW'), scoped: false, otherScopedSet: otherScopedSet };
}
function bskyPost_(text, imageBlob, channel) {
  channel = channel || 'acc1';
  var cr = bskyCreds_(channel);
  var handle = cr.handle, pw = cr.pw;
  // 片方だけ per-account 資格が設定済み＝移行中。要求chの資格が無ければ誤アカウント投稿を避けて中止。
  //   (per-account 資格が全く無い純レガシーは従来通り共有BSKY_HANDLE/PWで投稿＝後方互換)
  if (!cr.scoped && cr.otherScopedSet) throw new Error(channel + ' の資格情報(BSKY_HANDLE_' + (channel === 'acc2' ? 'ACC2' : 'ACC1') + ' / BSKY_APP_PW_' + (channel === 'acc2' ? 'ACC2' : 'ACC1') + ')が未設定のため中止(誤アカウント投稿防止)');
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
    // ★alt(代替テキスト)は常に空。無人予約投稿でも画像ビューアに④コメント等が出るのを止める(Chami依頼2026-07-18・フロントのbluesky-core.jsと対で修正)。
    if (up.blob) embed = { '$type': 'app.bsky.embed.images', images: [{ alt: '', image: up.blob }] };
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

// 本文中の URL(#link) とハッシュタグ(#tag) の facet(index は UTF-8 バイトオフセット)
function byteLen_(s) { return Utilities.newBlob(String(s)).getBytes().length; }
function detectFacets_(text) {
  text = String(text || ''); var facets = [], used = [], m;
  var ure = /https?:\/\/[^\s]+/g;
  while ((m = ure.exec(text))) {
    var url = m[0].replace(/[.,;:!?。、！？))】」』]+$/, '');
    var s = m.index, e = s + url.length; used.push([s, e]);
    facets.push({ index: { byteStart: byteLen_(text.slice(0, s)), byteEnd: byteLen_(text.slice(0, e)) },
      features: [{ '$type': 'app.bsky.richtext.facet#link', uri: url }] });
  }
  var tre = /(^|\s)(#[^\s#]+)/g, t;
  while ((t = tre.exec(text))) {
    var hash = t[2].replace(/[.,;:!?。、！？))】」』]+$/, '');
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
