/**
 * tests/test_drive_savejob.mjs — drive-worker の save_job(サーバー側完走ジョブ)の「判定と分岐」を
 *   本物の関数を import して実行で確かめる(ソース文字列一致ではない)。
 *
 * 背景(Chami依頼 2026-08-16 msg1538479072609443931「途中で閉じても裏で完結」):
 *   投稿完了で動画をこのページ内でフルアップロードしていた=タブを閉じると中断し黙って消えた。恒久対策=
 *   動画はR2の控え(videoKey)だけを軽く渡し、Workerが即202→R2→Driveをサーバー側(ctx.waitUntil)で完走。
 *   ここでは入口の検証(validateSaveJobInput)・R2 URL の組み立て(r2ObjectUrl)・キー形式・チャンネル解決を
 *   本物のまま実行して固定する。fetch/Drive API 等「外へ出る手」は runSaveJob 内のみで、ここでは呼ばない。
 */
import assert from 'assert';
import {
  validateSaveJobInput,
  r2ObjectUrl,
  safeName,
  channelToFolderId,
  SAVE_JOB_VIDEO_KEY_RE,
  SAVE_JOB_R2_BASE_RE,
} from '../drive-worker/src/index.js';

const ENV = { FOLDER_ID_ACC1: 'FOLDER_ACC1', FOLDER_ID_ACC2: 'FOLDER_ACC2' };
const KEY64 = 'a'.repeat(64);
const KEY16 = 'b'.repeat(16);

let fails = 0;
function ok(name) { console.log('  PASS ' + name); }
function ng(name, e) { fails++; console.log('  FAIL ' + name + ' — ' + (e && e.message || e)); }

// --- channelToFolderId(チャンネル解決・取り違え防止) ---
try {
  assert.strictEqual(channelToFolderId('acc1', ENV), 'FOLDER_ACC1');
  assert.strictEqual(channelToFolderId('acc2', ENV), 'FOLDER_ACC2');
  assert.strictEqual(channelToFolderId('acc9', ENV), '');
  assert.strictEqual(channelToFolderId('', ENV), '');
  ok('T-1 channelToFolderId: acc1/acc2 解決・不明は空');
} catch (e) { ng('T-1', e); }

// --- validateSaveJobInput(入口の門・実行で分岐を通す) ---
try {
  const good = validateSaveJobInput({ channel: 'acc1', title: '冷やしおみくじ', videoKey: KEY64, r2Base: 'https://sync.example.dev' }, ENV);
  assert.deepStrictEqual(good, { ok: true, parentId: 'FOLDER_ACC1' });
  ok('T-2 valid → {ok:true, parentId}');
} catch (e) { ng('T-2', e); }

try {
  assert.strictEqual(validateSaveJobInput({ channel: 'nope', title: 't', videoKey: KEY64, r2Base: 'https://x.dev' }, ENV).error, 'channel_unresolved');
  ok('T-3 channel未解決 → channel_unresolved');
} catch (e) { ng('T-3', e); }

try {
  assert.strictEqual(validateSaveJobInput({ channel: 'acc1', title: '', videoKey: KEY64, r2Base: 'https://x.dev' }, ENV).error, 'missing_title');
  ok('T-4 title欠落 → missing_title');
} catch (e) { ng('T-4', e); }

try {
  assert.strictEqual(validateSaveJobInput({ channel: 'acc1', title: 't', videoKey: 'ZZZ', r2Base: 'https://x.dev' }, ENV).error, 'bad_video_key');
  assert.strictEqual(validateSaveJobInput({ channel: 'acc1', title: 't', videoKey: '', r2Base: 'https://x.dev' }, ENV).error, 'bad_video_key');
  ok('T-5 videoKey形式不正/空 → bad_video_key');
} catch (e) { ng('T-5', e); }

try {
  assert.strictEqual(validateSaveJobInput({ channel: 'acc1', title: 't', videoKey: KEY64, r2Base: 'ftp://x' }, ENV).error, 'bad_r2_base');
  assert.strictEqual(validateSaveJobInput({ channel: 'acc1', title: 't', videoKey: KEY64, r2Base: '' }, ENV).error, 'bad_r2_base');
  ok('T-6 r2Base非http → bad_r2_base');
} catch (e) { ng('T-6', e); }

// --- r2ObjectUrl(R2公開GETのURL組み立て・末尾スラッシュ吸収) ---
try {
  assert.strictEqual(r2ObjectUrl('https://sync.example.dev', KEY64), 'https://sync.example.dev/img/' + KEY64);
  assert.strictEqual(r2ObjectUrl('https://sync.example.dev/', KEY64), 'https://sync.example.dev/img/' + KEY64, '末尾/を二重にしない');
  ok('T-7 r2ObjectUrl: /img/<key>・末尾スラッシュ吸収');
} catch (e) { ng('T-7', e); }

// --- キー形式の門(sha256hex を通し・ゴミを弾く) ---
try {
  assert.ok(SAVE_JOB_VIDEO_KEY_RE.test(KEY64), '64hexは通る');
  assert.ok(SAVE_JOB_VIDEO_KEY_RE.test(KEY16), '16hexは通る');
  assert.ok(!SAVE_JOB_VIDEO_KEY_RE.test('a'.repeat(15)), '15桁は弾く');
  assert.ok(!SAVE_JOB_VIDEO_KEY_RE.test('../etc/passwd'), 'パス片は弾く');
  assert.ok(!SAVE_JOB_VIDEO_KEY_RE.test('A'.repeat(64)), '大文字16進は弾く(小文字hexのみ)');
  assert.ok(SAVE_JOB_R2_BASE_RE.test('http://x'), 'httpは通る');
  assert.ok(SAVE_JOB_R2_BASE_RE.test('https://x'), 'httpsは通る');
  assert.ok(!SAVE_JOB_R2_BASE_RE.test('javascript:alert(1)'), 'scheme偽装は弾く');
  ok('T-8 キー/URL形式ガード');
} catch (e) { ng('T-8', e); }

// --- safeName(題名→フォルダ名・パス区切りの無害化) ---
try {
  assert.strictEqual(safeName('a/b\\c'), 'a／b／c', 'スラッシュ類は全角へ');
  assert.strictEqual(safeName(''), 'video', '空は既定名');
  assert.strictEqual(safeName('冷やしおみくじ？'), '冷やしおみくじ？', '通常記号は保つ');
  ok('T-9 safeName: 危険文字のみ無害化');
} catch (e) { ng('T-9', e); }

if (fails) { console.log('\n' + fails + ' test(s) FAILED'); process.exit(1); }
console.log('\nAll drive save_job tests passed.');
