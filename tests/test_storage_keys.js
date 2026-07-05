/**
 * tests/test_storage_keys.js
 * localStorage キーレジストリ（core/storage-keys.js）と共通ユーティリティ（core/util.js）の検証。
 * M-1（改善書 §7・§2-4）の受け入れ条件：許可リスト方式の分類が正しいこと。
 * 実行: node tests/test_storage_keys.js
 */
'use strict';
const assert = require('assert');
const Keys = require('../core/storage-keys.js');
const Util = require('../core/util.js');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

// ── 本物の「設定」＝同期対象（sync:true）───────────────────────────────────
const SHOULD_SYNC = [
  'preview_offset_y__acc1', 'preview_offset_y_default__acc2', 'preview_band_pad__acc1',
  'preview_text_author__acc2', 'preview_img_y__acc1',
  'btn_color_save', 'btn_color_undo',
  'bsky_enable__acc1', 'bsky_unattended__acc2', 'bsky_text__acc1',
  'bsky_text_quick__acc1', 'bsky_text_quick_at__acc1', 'bsky_text_undostack__acc2', 'bsky_text_redostack__acc1',
  'bsky_work_url__acc1', 'bsky_handle__acc1',
  'yt_desc__acc1', 'yt_desc_quick__acc2', 'yt_desc_undostack__acc1', 'yt_tags__acc1',
  'affi_urls__acc1', 'affi_urls_quick__acc2', 'affi_urls_undostack__acc1',
  'bsky_gas_url', 'fanza_af_id', 'fanza_worker_url', 'ytdesc_tpl_v3',
];

// ── 記録/履歴/キャッシュ/下書き/DID/移行フラグ/スケジュール/スナップ/UI状態＝同期しない（sync:false）
//    改善書 §2-4 が「漏れて同期対象になっていた」と問題視したキー群を含む。
const SHOULD_NOT_SYNC = [
  'movie_drafts__acc1',          // 下書き（画像dataURL入り）
  'sch_state_v1',                // スケジュール状態
  'view_snaps',                  // 再生数スナップショット
  'yt_scheduled__acc1',          // YT予約
  'current_account',             // 端末UI状態
  'sync_device_name',            // 端末固有
  'short_hist__acc1', 'verify_manual__acc2', 'verify_yt__acc1', 'verify_hide_remade__acc1',
  'verify_fanza', 'fanza_manual_info', 'acct_move_log_last',
  'bsky_did__acc1',              // 投稿アカウントDID（識別子キャッシュ）
  'bsky_avatar_somehandle', 'bsky_dn_somehandle',
  'cand_items', 'cand_hidden__t1', 'cand_refimg__abc', 'cand_mk2__m1__all',
  'delta_cache', 'peak_cache', 'clicks_cache', 'yt_meta_cache', 'fanza_title_cache',
  'acct_did_repair_v1', 'acct_split_migrated', 'layout_acct_split_migrated', 'feat_2026q2_migrated',
  'rank_mode', 'field_top', 'field_author',
];

// ── 秘密キー＝secret かつ 同期しない ─────────────────────────────────────────
const SECRETS = ['bsky_app_pw__acc1', 'bsky_app_pw__acc2', 'yt_api_key', 'fanza_shared_secret', 'bsky_gas_secret'];

test('SYNC-1: 本物の設定はすべて syncAllowed=true', function () {
  SHOULD_SYNC.forEach(function (k) { assert.strictEqual(Keys.syncAllowed(k), true, k + ' は同期されるべき'); });
});

test('SYNC-2: 記録/キャッシュ/下書き等はすべて syncAllowed=false（許可リスト反転の肝）', function () {
  SHOULD_NOT_SYNC.forEach(function (k) { assert.strictEqual(Keys.syncAllowed(k), false, k + ' は同期されてはいけない'); });
});

test('SEC-1: 秘密キーは isSecret=true かつ syncAllowed=false', function () {
  SECRETS.forEach(function (k) {
    assert.strictEqual(Keys.isSecret(k), true, k + ' は秘密であるべき');
    assert.strictEqual(Keys.syncAllowed(k), false, k + ' は同期されてはいけない');
  });
});

test('SEC-2: 設定キーは秘密ではない', function () {
  SHOULD_SYNC.forEach(function (k) { assert.strictEqual(Keys.isSecret(k), false, k + ' は秘密ではない'); });
});

test('REG-1: 新キーは既定でローカル（未登録キーは同期されない＝INC-62 恒久対策）', function () {
  assert.strictEqual(Keys.syncAllowed('some_brand_new_key__acc1'), false);
  assert.strictEqual(Keys.syncAllowed('totally_unknown_cache'), false);
  assert.strictEqual(Keys.classify('some_brand_new_key__acc1'), 'local');
});

test('REG-2: classify のラベルが分類と一致', function () {
  assert.strictEqual(Keys.classify('bsky_text__acc1'), 'sync');
  assert.strictEqual(Keys.classify('bsky_app_pw__acc1'), 'secret');
  assert.strictEqual(Keys.classify('view_snaps'), 'local');
});

test('DIFF-1: legacySynced は反転前の同期集合（差分ログの基礎）', function () {
  // 旧ブロックリストでは view_snaps / movie_drafts__ / current_account は同期されていた（＝漏洩）。
  assert.strictEqual(Keys.legacySynced('view_snaps'), true);
  assert.strictEqual(Keys.legacySynced('movie_drafts__acc1'), true);
  assert.strictEqual(Keys.legacySynced('current_account'), true);
  // 旧でも同期されなかった：秘密・cand_・キャッシュ・bsky_did__。
  assert.strictEqual(Keys.legacySynced('bsky_app_pw__acc1'), false);
  assert.strictEqual(Keys.legacySynced('cand_items'), false);
  assert.strictEqual(Keys.legacySynced('bsky_did__acc1'), false);
  // これらは反転で「同期されなくなる」（差分に出る）＝改善書§2-4 の意図どおり。
  assert.strictEqual(Keys.legacySynced('view_snaps') && !Keys.syncAllowed('view_snaps'), true);
});

test('ESC-1: Go5Util.esc は " を必ずエスケープする（危険な系統の統一）', function () {
  assert.strictEqual(Util.esc('a<b>&"c"'), 'a&lt;b&gt;&amp;&quot;c&quot;');
  assert.strictEqual(Util.esc('"onclick"'), '&quot;onclick&quot;');
  assert.strictEqual(Util.esc(null), '');
  assert.strictEqual(Util.esc(undefined), '');
});

test('ESC-2: Go5Util.fmtTs / yen / num の基本', function () {
  assert.strictEqual(Util.yen(1234), '¥1,234');
  assert.strictEqual(Util.yen(null), '—');
  assert.strictEqual(Util.fmtTs(new Date(2026, 5, 3, 9, 7).getTime()), '06/03 09:07');
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
