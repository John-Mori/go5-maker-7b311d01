/**
 * core/storage-keys.js — localStorage キーの登録制レジストリ。(Go5Keys)M-1。(改善書 §7・§2-4)
 *
 * 【解く問題】クラウド同期がこれまで「ブロックリスト方式」だった(settings-io の isNoSyncKey に
 *   載っていない新キーは自動的に同期対象)。この構造のため INC-62(アカウント混在)の恒久対策が
 *   新キーに効かず、`movie_drafts__`(画像dataURL)・`sch_state_v1`・`view_snaps`・`yt_scheduled__`
 *   等が意図せず同期対象に漏れていた。
 *
 * 【対策】同期を **許可リスト方式へ反転**する。syncAllowed(k) が true のキー(＝本物の「設定」)だけ
 *   クラウドへ送る。未登録の新キーは既定で同期されない＝恒久対策が新キーにも効く。
 *
 * 分類：
 *   - secret … アプリパスワード/各種トークン。export(safe)・同期のどちらでも絶対に出さない。
 *   - sync   … 本物の設定。(レイアウト・本文/説明欄テンプレ・テーマ色・共有設定)端末間同期する。
 *   - local  … それ以外。(記録/履歴/キャッシュ/下書き/DID/移行フラグ/スケジュール/スナップ/UI状態)
 *              端末ローカルに留める。(正本はスプレッドシート＋各端末)同期しない。
 *
 * legacySynced(k) は旧ブロックリスト時代の「同期されていたか」を再現する。(反転の差分ログ＝目視用)
 */
(function (root) {
  "use strict";

  // ── secret(秘密)：export(safe) と同期の両方で除外。現行 settings-io の isSecretKey と同一。
  function isSecret(k) {
    return /(app_pw|_pw__|password|secret|token|refresh|api_key)/i.test(String(k));
  }

  // ── 同期しないローカル/記録データ。(旧 settings-io の isNoSyncKey + isDeviceLocalKey 相当)
  //    差分(反転の目視)を出すために旧判定を保持する。
  function legacyNoSync(k) {
    k = String(k);
    return /^(short_hist__|verify_manual__|verify_yt__|bsky_did__|cand_)/.test(k)
      || /^(delta_cache|peak_cache|clicks_cache|yt_meta_cache|fanza_title_cache)$/.test(k)
      || /^acct_did_repair/.test(k)
      || k === "sync_device_name";
  }
  // 旧ブロックリスト方式で実際に同期されていたか。(＝秘密でも noSync でもない全て)
  function legacySynced(k) { k = String(k); return !isSecret(k) && !legacyNoSync(k); }

  // ── 許可リスト：本物の「設定」だけ true。base + '__' + acc のアカウント別キーも前方一致で拾う。
  //    ここに載っていないキーは同期されない。(新キーの既定 = ローカル)
  var SYNC_ALLOW = [
    /^preview_/,                 // レイアウト微調整(値・_default・各段・帯・余白)＝アカウント別
    /^btn_color_/,               // 編集ボタンの色カスタマイズ(theme-settings・全アカウント共通)
    // 本文・YouTube説明欄・アフィURL とその Qセーブ/元に戻す/やり直しスタック(アカウント別)：
    /^bsky_enable(__|$)/,
    /^bsky_unattended(__|$)/,
    /^bsky_text(_|__|$)/,        // bsky_text / bsky_text_quick(_at) / bsky_text_undostack / _redostack
    /^bsky_work_url(__|$)/,
    /^bsky_handle(__|$)/,        // ハンドル。(設定・非秘密)DID(bsky_did__) は含めない
    /^yt_desc(_|__|$)/,          // yt_desc / yt_desc_quick(_at) / yt_desc_undostack / _redostack
    /^yt_tags(__|$)/,
    /^affi_urls(_|__|$)/,        // affi_urls / affi_urls_quick(_at) / _undostack / _redostack
    /^bsky_tpl_book(__|$)/,      // 📝テンプレ帳(本文定型文・アカウント別・2026-07-12)
  ];
  // 前方一致では拾わない単発の共有設定キー。(完全一致)
  var SYNC_EXACT = {
    "bsky_gas_url": 1,           // 記録用GAS URL(共有設定)
    "fanza_af_id": 1,            // FANZA アフィリエイトID(共有設定)
    "fanza_worker_url": 1,       // FANZA worker URL(共有設定)
    "ytdesc_tpl_v3": 1,          // YouTube説明欄テンプレ版(共有設定)
    "yt_tags_shared": 1,         // YTタグ(全チャンネル共通・2026-07-12統一)
  };

  // このキーはクラウド同期してよいか。(＝本物の設定か)
  function syncAllowed(k) {
    k = String(k);
    if (isSecret(k)) return false;               // 秘密は決して同期しない
    if (SYNC_EXACT[k]) return true;
    for (var i = 0; i < SYNC_ALLOW.length; i++) { if (SYNC_ALLOW[i].test(k)) return true; }
    return false;                                // 未登録 = ローカル(同期しない)
  }

  // 分類ラベル。(ドキュメント/デバッグ用)
  function classify(k) {
    if (isSecret(k)) return "secret";
    if (syncAllowed(k)) return "sync";
    return "local";
  }

  var API = { isSecret: isSecret, syncAllowed: syncAllowed, classify: classify, legacySynced: legacySynced, legacyNoSync: legacyNoSync };

  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.Go5Keys = API;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
