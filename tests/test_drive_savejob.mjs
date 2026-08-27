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
import fs from 'fs';
import {
  validateSaveJobInput,
  getOrCreateExactFolder,
  r2ObjectUrl,
  safeName,
  channelToFolderId,
  SAVE_JOB_VIDEO_KEY_RE,
  SAVE_JOB_R2_BASE_RE,
  DRIVE_JOB_LEASE_MS,
  acquireDriveJobLease,
  holdDriveJobLease,
  releaseDriveJobLease,
} from '../drive-worker/src/index.js';

const ENV = { FOLDER_ID_ACC1: 'FOLDER_ACC1', FOLDER_ID_ACC2: 'FOLDER_ACC2' };
const KEY64 = 'a'.repeat(64);
const KEY16 = 'b'.repeat(16);
const workerSource = fs.readFileSync(new URL('../drive-worker/src/index.js', import.meta.url), 'utf8');
const saveJobSource = workerSource.slice(workerSource.indexOf('async function runSaveJobUnlocked'), workerSource.indexOf('function sleep', workerSource.indexOf('async function runSaveJobUnlocked')));
const sourceUploadAt = saveJobSource.indexOf('baseName + "_元画像."');
const previewUploadAt = saveJobSource.indexOf('baseName + "_プレビュー."');
const videoUploadAt = saveJobSource.indexOf('baseName + "." + vext');
assert.ok(saveJobSource.includes('const [vid, sourceAsset, previewAsset] = await Promise.all(['), '動画・元画像・プレビューをR2から並列取得する');
assert.ok(sourceUploadAt >= 0 && previewUploadAt > sourceUploadAt && videoUploadAt > previewUploadAt, 'Driveでは付随画像を先に保存し、動画を最後に表示させる');

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


// --- 同名フォルダ単一化(list失敗時は作らない・並列作成は1回だけ) ---
try {
  let created = 0;
  const got = await getOrCreateExactFolder('P-existing', '同名作品', 'TOKEN', {
    list: async () => ['FOLDER_EXISTING'],
    create: async () => { created++; return { id: 'SHOULD_NOT_CREATE' }; },
  });
  assert.strictEqual(got.folder.id, 'FOLDER_EXISTING');
  assert.strictEqual(got.reused, true);
  assert.strictEqual(created, 0, '同名があれば新規作成しない');
  ok('T-10 exact-name既存フォルダを再利用');
} catch (e) { ng('T-10', e); }

try {
  let listed = 0, created = 0;
  const ops = {
    list: async () => { listed++; await new Promise((r) => setTimeout(r, 10)); return []; },
    create: async () => { created++; await new Promise((r) => setTimeout(r, 10)); return { id: 'FOLDER_ONLY_ONE' }; },
  };
  const pair = await Promise.all([
    getOrCreateExactFolder('P-parallel', '同時再送', 'TOKEN', ops),
    getOrCreateExactFolder('P-parallel', '同時再送', 'TOKEN', ops),
  ]);
  assert.strictEqual(pair[0].folder.id, 'FOLDER_ONLY_ONE');
  assert.strictEqual(pair[1].folder.id, 'FOLDER_ONLY_ONE');
  assert.strictEqual(listed, 1, '並列でもDrive一覧確認は1回');
  assert.strictEqual(created, 1, '並列でもフォルダ作成は1回');
  ok('T-11 同一isolateの並列再送をsingle-flight');
} catch (e) { ng('T-11', e); }

try {
  let created = 0;
  await assert.rejects(getOrCreateExactFolder('P-list-fail', '照合不能', 'TOKEN', {
    list: async () => { throw new Error('drive-list-error'); },
    create: async () => { created++; return { id: 'DUPLICATE' }; },
  }), /folder_lookup_failed/);
  assert.strictEqual(created, 0, 'Drive一覧を確認できない時は新規作成しない');
  ok('T-12 list失敗を未存在と誤認しない');
} catch (e) { ng('T-12', e); }

// --- 別Worker isolateをまたぐR2条件付きリース（同じ作品のDrive書込みは常に1本）---
class FakeR2 {
  constructor() { this.map = new Map(); this.seq = 0; }
  async head(key) { return this.map.get(key) || null; }
  async put(key, value, opts = {}) {
    const cur = this.map.get(key) || null;
    const onlyIf = opts.onlyIf;
    const none = onlyIf && typeof onlyIf.get === 'function' ? onlyIf.get('If-None-Match') : '';
    const match = onlyIf && typeof onlyIf.get === 'function' ? onlyIf.get('If-Match') : '';
    if (none === '*' && cur) return null;
    if (match && (!cur || cur.httpEtag !== match)) return null;
    const etag = 'etag-' + (++this.seq);
    const obj = { key, etag, httpEtag: '"' + etag + '"', customMetadata: Object.assign({}, opts.customMetadata || {}) };
    this.map.set(key, obj);
    return obj;
  }
}

try {
  const bucket = new FakeR2();
  const env = { SYNC_IMAGES: bucket };
  const first = await acquireDriveJobLease(env, 'P1', '同じ作品', 'owner-a', 1000);
  assert.strictEqual(first.ok, true, '先頭だけがリースを取る');
  assert.strictEqual(Number(first.object.customMetadata.expiresAt), 1000 + DRIVE_JOB_LEASE_MS);
  const second = await acquireDriveJobLease(env, 'P1', '同じ作品', 'owner-b', 1001);
  assert.deepStrictEqual({ ok: second.ok, busy: second.busy }, { ok: false, busy: true }, '別isolate相当の二本目を止める');
  assert.strictEqual(await releaseDriveJobLease(env, first), true, '所有者ETag一致時だけ解放');
  const third = await acquireDriveJobLease(env, 'P1', '同じ作品', 'owner-c', 2000);
  assert.strictEqual(third.ok, true, '解放後は自己修復ジョブが取得できる');
  assert.strictEqual(await holdDriveJobLease(env, third, 5000), true, '成功後クールダウンを条件付きで延長');
  const cooled = await acquireDriveJobLease(env, 'P1', '同じ作品', 'owner-d', Date.now() + 1000);
  assert.strictEqual(cooled.busy, true, '成功直後の遅延再送も止める');
  ok('T-13 R2分散リース: 別isolate/遅延再送を単一化');
} catch (e) { ng('T-13', e); }

try {
  const noBinding = await acquireDriveJobLease({}, 'P', '題名', 'owner', 1000);
  assert.strictEqual(noBinding.ok, false);
  assert.strictEqual(noBinding.error, 'drive_lease_binding_missing');
  ok('T-14 リース基盤不在は重複許可せずfail-closed');
} catch (e) { ng('T-14', e); }
if (fails) { console.log('\n' + fails + ' test(s) FAILED'); process.exit(1); }
console.log('\nAll drive save_job tests passed.');
