/**
 * core/image-role.js — 画像1枚が「投稿プレビュー(仕上がり)」か「動画生成に使った素材」かを判定する
 *   唯一の場所。(Go5ImageRole)
 *
 * 【解く問題】「投稿プレビュー画像(仕上がり=used先頭のprevN枚)」と「動画生成に使った素材画像(candidate_N系・
 *   prevN番目以降)」の取り違え(Chami報告2026-08-23 05:47「生成に使った画像がプレビュー扱いされる/表示
 *   めちゃくちゃ」)。過去24hで投稿履歴の画像ビュー/サムネ・編集モーダル・Drive保存(appendImage)・候補ページ・
 *   カードサムネの7画面を個別に止血したが再発した＝判定が画面ごとに散っていたのが真因。ここへ1本化する。
 *   命名比較・位置比較のリテラルはこのファイルの外に置かない(呼び出し側は index/role/name を渡すだけ)。
 *
 * 【入力契約】imageRole(rec) の rec は、各画面が実際に持っているキーのどれか一つで渡す：
 *   a) 位置ベース(投稿履歴/候補ページの「used レコード」= {imgs:[...], prev:N} 由来。最も多い形)：
 *      { index: number, prevCount: number }
 *        used配列でのindex位置。index<prevCount なら仕上がりプレビュー(=stock.js capturePreview_ が撮った
 *        #cv最終フレーム)、index>=prevCount は動画生成に使った元画像(candidate_N系)。
 *      { index, prevCount, inUsed:false } … used配列に属さない画像(投稿画像/Bluesky添付/候補一覧の他候補等)は
 *        位置に関係なく 'attachment'。
 *   b) 明示タグ(stock.js salvageWithoutVideo_ 等・呼び出し側が既に何を持っているか分かっている時)：
 *      { role: 'preview' | 'source' | 'src' | 'attachment' } … 'src' は 'source' の別名(互換)。
 *   c) ファイル名ベース(Drive/File実体の命名規約。driveUpload_/appendImageToFolder_ が付ける名前と一致)：
 *      { name: string } … "題名_プレビュー.*" は preview、"題名_元画像.*" は source。
 *   どれにも当たらない・inUsed:false は 'attachment'(それ以外の添付・候補・投稿画像)。
 *
 * 使い方：ブラウザでは window.Go5ImageRole、Node(テスト)では module.exports。
 */
(function (root) {
  'use strict';

  function imageRole(rec) {
    rec = rec || {};
    if (rec.role === 'preview' || rec.role === 'source' || rec.role === 'attachment') return rec.role;
    if (rec.role === 'src') return 'source'; // 互換タグ(stock.js salvageWithoutVideo_ の imgs=[{blob,role:'src'}])
    if (rec.name != null) {
      var n = String(rec.name);
      if (n.indexOf('プレビュー') >= 0) return 'preview';
      if (n.indexOf('元画像') >= 0) return 'source';
    }
    if (rec.inUsed === false) return 'attachment';
    if (typeof rec.index === 'number') {
      if (rec.index < 0) return 'attachment';
      var prevCount = rec.prevCount | 0;
      return rec.index < prevCount ? 'preview' : 'source';
    }
    return 'attachment';
  }

  // used配列(usedImages)+prevCountの各要素roleを、位置ベースで一括判定して返す(表示側の反復用)。
  function rolesForUsed(usedImages, prevCount) {
    var imgs = Array.isArray(usedImages) ? usedImages : [];
    var n = prevCount | 0;
    return imgs.map(function (_, i) { return imageRole({ index: i, prevCount: n }); });
  }

  // used配列+prevCountから role='preview' の要素だけを順番通りに返す(投稿履歴の画像ビュー等が使う)。
  function previewImages(usedImages, prevCount) {
    var imgs = Array.isArray(usedImages) ? usedImages.filter(Boolean) : [];
    var n = prevCount | 0;
    return imgs.filter(function (_, i) { return imageRole({ index: i, prevCount: n }) === 'preview'; });
  }

  // used配列+prevCountから role='source' の要素だけを順番通りに返す(Drive退避保存の元画像取得等が使う)。
  function sourceImages(usedImages, prevCount) {
    var imgs = Array.isArray(usedImages) ? usedImages.filter(Boolean) : [];
    var n = prevCount | 0;
    return imgs.filter(function (_, i) { return imageRole({ index: i, prevCount: n }) === 'source'; });
  }

  var api = {
    imageRole: imageRole,
    rolesForUsed: rolesForUsed,
    previewImages: previewImages,
    sourceImages: sourceImages
  };
  if (typeof window !== 'undefined') root.Go5ImageRole = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
