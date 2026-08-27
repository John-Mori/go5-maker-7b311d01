// ブラウザ側の同作品Drive保存single-flightを、CIの構造門として固定する。
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'js', 'stock.js'), 'utf8');
const historySrc = fs.readFileSync(path.join(__dirname, '..', 'js', 'yt-clicks.js'), 'utf8');

assert.ok(src.includes('var _driveDatasetInFlight = Object.create(null);'), '作品別in-flight台帳が必要');
assert.ok(src.includes("var flightKey = String(meta.account || '') + '\\n' + String(meta.title || meta.id);"), 'チャンネル＋題名を同一保存キーにする');
assert.ok(/if \(activeFlight\) \{[\s\S]{0,180}activeFlight\.waiters\.push\(opts\.onDone\);[\s\S]{0,80}return;/.test(src), '二本目は先行処理へjoinしてDrive書込みを開始しない');
assert.ok(src.includes('delete _driveDatasetInFlight[flightKey]'), '終端でロックを解放する');
assert.ok(src.includes('flight.watchdog = setTimeout'), '無応答でもロックを永久保持しない');
assert.ok(!src.includes("done(true, '☁️ Driveへ保存中(裏で継続)・結果はカードに出ます');"), 'queueSave前にsingle-flightを解放する旧早期doneを復活させない');
assert.ok(src.includes('var _draftAssetMirrorReady = Object.create(null);'), '新規ドラフトの元画像・プレビュー着地PromiseをDrive保存と共有する');
assert.ok(src.includes('_draftAssetMirrorReady[id] = Promise.all(assetMirrorJobs'), '元画像とプレビューはタイマー待ちでなく作成直後に並列ミラーする');
assert.ok(!/setTimeout\(function \(\) \{ try \{ ensureSrcMirror_/.test(src) && !/setTimeout\(function \(\) \{ try \{ ensurePrevMirror_/.test(src), '6秒/8秒の意図的な付随画像遅延を復活させない');
assert.ok(src.indexOf('var assetMirrorReady = _draftAssetMirrorReady[id]') < src.indexOf('window.Go5Drive.queueSave({'), 'Driveジョブは新規ドラフトの付随画像ミラーを先に共有する');
const joinAt = src.indexOf('if (activeFlight)');
const queueAt = src.indexOf('window.Go5Drive.queueSave({', joinAt);
assert.ok(joinAt >= 0 && queueAt > joinAt, 'join判定がqueueSaveより必ず先');
const saveAt = src.indexOf('function driveSaveDataset_');
const cleanAt = src.indexOf('meta = driveDataMeta_(meta);', saveAt);
const flightAt = src.indexOf('var flightKey =', saveAt);
assert.ok(cleanAt > saveAt && cleanAt < flightAt, 'Drive保存はsingle-flight/ensure/uploadより前にタグなしdataTitleへ正規化する');
assert.ok(src.includes("replace(/(?:^|\\s)#[^\\s#]+(?:\\s*#[^\\s#]+)*\\s*$/, '')"), '未知・連結・タグだけの末尾群を除去する規則が必要');
assert.ok(src.includes("String(meta.id || meta.videoId || 'video').replace(/#/g, '')"), 'タグしかない旧題名でも非#の安定IDへフォールバックする');

const driveTitleAt = historySrc.indexOf('function driveLinkTitle_');
const driveLinkAt = historySrc.indexOf('function driveLinkHtml_');
const driveTitleBlock = historySrc.slice(driveTitleAt, driveLinkAt);
const driveLinkBlock = historySrc.slice(driveLinkAt, historySrc.indexOf('function platOf_', driveLinkAt));
assert.ok(driveTitleBlock.includes('window.Go5RegenIdentity.cleanTitle(v)'), '投稿履歴Driveリンクも単一権威cleanTitleを使う');
assert.ok(driveTitleBlock.includes("replace(/(?:^|\\s)#[^\\s#]+(?:\\s*#[^\\s#]+)*\\s*$/, '')"), 'core異常時もDrive保存と同じ末尾タグ除去へ倒す');
assert.ok(driveLinkBlock.includes("title = driveLinkTitle_(it.title || '')"), 'Drive検索・folder解決にはclean titleだけを渡す');
assert.ok(!/it\.title\s*=/.test(driveTitleBlock + driveLinkBlock), '旧投稿履歴の表示題名そのものは変更しない');
assert.ok(driveLinkBlock.indexOf('driveLinkTitle_') < driveLinkBlock.indexOf('Go5Drive.folderUrl(ch, title, vid)'), '題名正規化はDrive URL組立より前に行う');


const regenAt = src.indexOf('function regenDataset_');
const preserveAt = src.indexOf('var rawLocatorTitle =', regenAt);
const regenCleanAt = src.indexOf('meta = driveDataMeta_(meta, rawLocatorTitle);', regenAt);
const ensureAt = src.indexOf('window.Go5Drive.ensureFolder(meta.account, meta.title', regenAt);
assert.ok(preserveAt > regenAt && regenCleanAt > preserveAt && ensureAt > regenCleanAt, '再生成は旧原文を別に保持し、Drive ensure前にdataTitleを確定する');
assert.ok(src.includes("readDriveAsset_('fetchPreview')") && src.includes("readDriveAsset_('fetchVideo')"), '旧タグ付きDriveは素材のread-only救出だけに使う');
assert.ok(!src.includes('Go5Drive.fetchPreview(meta.account, meta.title)') && !src.includes('Go5Drive.fetchVideo(meta.account, meta.title)'), '旧直読みを共通read-onlyフォールバック外へ残さない');
assert.ok(src.includes('var out = Object.assign({}, meta, { title: title });'), '履歴/ドラフトmeta原文を直接変更しない');
assert.ok(src.includes("if (rawVideoName) out.videoName = title + (extMatch ? extMatch[1] : '');"), '旧videoNameをclean title＋元拡張子へ揃え、動画ファイル名にも末尾タグを残さない');
assert.ok(src.indexOf('var out = Object.assign({}, meta, { title: title });') < src.indexOf('out.videoName = title +'), 'clone後だけvideoNameを変更し原metaを不変にする');

const legacyReadAt = src.indexOf('function readLegacyDriveVideo_()');
const queueRecoverAt = src.indexOf('function ensureQueueVideoOnR2_()');
const legacyUploadAt = src.indexOf('function resolveLegacyUploadVideo_()');
const previewAt = src.indexOf("readDriveAsset_('fetchVideo')");
assert.ok(legacyReadAt > saveAt && queueRecoverAt > legacyReadAt && legacyUploadAt > queueRecoverAt,
  '旧Drive動画のread-only救出をDrive保存single-flight内へ集約する');
const legacyReadBlock = src.slice(legacyReadAt, queueRecoverAt);
assert.ok(legacyReadBlock.includes('meta._regenReadTitles') && legacyReadBlock.includes('window.Go5Drive.fetchVideo(meta.account, title)'),
  '旧タグ付き題名だけをDrive動画の救出元として順次読む');
assert.ok(legacyReadBlock.includes('isUsableVideoBlob_(blob)') && legacyReadBlock.includes('putVidMem_(id, blob)') && legacyReadBlock.includes("store.set('stock_v_' + id, blob)"),
  '破損Blobを拒否し、正常な旧Drive動画だけをメモリ/IDBへ戻す');
assert.ok(!/\.upload\(|\.queueSave\(|\.ensureFolder\(|\.rememberFolder\(/.test(legacyReadBlock),
  '旧タグ付きDriveフォルダはread-onlyとし一切書き込まない');
const queueRecoverBlock = src.slice(queueRecoverAt, legacyUploadAt);
assert.ok(/ensureVideoOnR2_\(id\)[\s\S]*if \(onR2\) return true;[\s\S]*readLegacyDriveVideo_\(\)[\s\S]*ensureVideoOnR2_\(id\)/.test(queueRecoverBlock),
  'queue経路は既存R2を優先し、初回ensure失敗時だけ旧Driveを救出して再ensureする');
assert.ok(src.indexOf('ensureQueueVideoOnR2_().then(function (onR2)', queueRecoverAt) < queueAt,
  'queueSaveは旧動画のR2再着地確認後にだけ呼ぶ');
const legacyUploadBlock = src.slice(legacyUploadAt, previewAt);
assert.ok(/resolveVideoBlob_\(id\)[\s\S]*isUsableVideoBlob_\(blob\) \? blob : readLegacyDriveVideo_\(\)/.test(legacyUploadBlock),
  'legacy uploadは手元/R2解決失敗時だけ旧Drive動画へfallbackする');
assert.ok(src.includes('resolveLegacyUploadVideo_().then(function (blob)') && src.includes('if (!isUsableVideoBlob_(blob)) {'),
  '直upload境界でも破損動画を拒否する');
assert.ok(src.includes('window.Go5Drive.queueSave({ videoId: id, title: meta.title') &&
  src.includes('window.Go5Drive.upload(blob, meta.videoName, meta.title'),
  '救出後のqueue/uploadはいずれもcleanTitleへだけ書く');

function functionSource_(startNeedle, endNeedle) {
  const start = src.indexOf(startNeedle);
  const end = src.indexOf(endNeedle, start);
  assert.ok(start >= 0 && end > start, startNeedle + ' の動的テスト対象を抽出できる');
  return src.slice(start, end);
}
const legacyReadSource = functionSource_('    function readLegacyDriveVideo_() {', '    // 現行のタグなしフォルダを先に読み');
const queueRecoverSource = functionSource_('    function ensureQueueVideoOnR2_() {', '    // 旧環境の直uploadも');
const legacyUploadSource = functionSource_('    function resolveLegacyUploadVideo_() {', '    // ── ★最後の砦=');
const recoveryFactory = new Function('deps',
  "var window=deps.window,meta=deps.meta,id=deps.id,store=deps.store;" +
  "var legacyDriveVideoRead_=null,putVidMem_=deps.putVidMem_,isUsableVideoBlob_=deps.isUsableVideoBlob_;" +
  "var ensureVideoOnR2_=deps.ensureVideoOnR2_,resolveVideoBlob_=deps.resolveVideoBlob_;" +
  legacyReadSource + queueRecoverSource + legacyUploadSource +
  'return {readLegacyDriveVideo_:readLegacyDriveVideo_,ensureQueueVideoOnR2_:ensureQueueVideoOnR2_,resolveLegacyUploadVideo_:resolveLegacyUploadVideo_};');
function recoveryHarness_(cfg) {
  cfg = cfg || {};
  const state = { ensure: 0, fetchTitles: [], mem: 0, stores: 0 };
  const ensureResults = (cfg.ensureResults || []).slice();
  const usable = b => !!(b && b.size >= 16 * 1024 && (!b.type || String(b.type).indexOf('video/') === 0));
  const api = recoveryFactory({
    window: { Go5Drive: { fetchVideo: (_account, title) => { state.fetchTitles.push(title); return Promise.resolve(cfg.driveBlob || null); } } },
    meta: { account: 'acc1', title: '作品', _regenReadTitles: ['作品 #漫画 #PR'] },
    id: 'vid-1',
    store: { set: () => { state.stores++; return Promise.resolve(); } },
    putVidMem_: () => { state.mem++; },
    isUsableVideoBlob_: usable,
    ensureVideoOnR2_: () => Promise.resolve(ensureResults[state.ensure++]),
    resolveVideoBlob_: () => cfg.rejectLocal ? Promise.reject(new Error('missing')) : Promise.resolve(cfg.localBlob || null)
  });
  return { api, state };
}
(async function runLegacyRecoveryDynamic_() {
  const good = { size: 32 * 1024, type: 'video/mp4', arrayBuffer: function () {} };
  const broken = { size: 15, type: 'video/mp4', arrayBuffer: function () {} };

  let h = recoveryHarness_({ ensureResults: [true], driveBlob: good });
  assert.strictEqual(await h.api.ensureQueueVideoOnR2_(), true, '既存R2があればそのままqueue可能');
  assert.deepStrictEqual(h.state.fetchTitles, [], '既存R2成功時は旧Driveを読まない');
  assert.strictEqual(h.state.ensure, 1, '既存R2成功時のensureは一回だけ');

  h = recoveryHarness_({ ensureResults: [false, true], driveBlob: good });
  assert.strictEqual(await h.api.ensureQueueVideoOnR2_(), true, 'R2欠損時は旧Drive動画を載せて再ensureできる');
  assert.deepStrictEqual(h.state.fetchTitles, ['作品 #漫画 #PR'], '旧タグ付き題名だけを救出元にする');
  assert.strictEqual(h.state.ensure, 2, '救出後にR2着地を再確認する');
  assert.strictEqual(h.state.mem, 1, '正常動画をメモリへ一度だけ戻す');
  assert.strictEqual(h.state.stores, 1, '正常動画をIDBへ一度だけ戻す');

  h = recoveryHarness_({ ensureResults: [false], driveBlob: broken });
  assert.strictEqual(await h.api.ensureQueueVideoOnR2_(), false, '破損した旧Drive動画ではqueueしない');
  assert.strictEqual(h.state.ensure, 1, '破損Blobでは再ensureしない');
  assert.strictEqual(h.state.mem, 0, '破損Blobをメモリへ入れない');
  assert.strictEqual(h.state.stores, 0, '破損BlobをIDBへ入れない');

  h = recoveryHarness_({ localBlob: good, driveBlob: good });
  assert.strictEqual(await h.api.resolveLegacyUploadVideo_(), good, 'legacy uploadは手元動画を最優先する');
  assert.deepStrictEqual(h.state.fetchTitles, [], '手元動画があれば旧Driveを読まない');

  h = recoveryHarness_({ localBlob: null, driveBlob: good });
  assert.strictEqual(await h.api.resolveLegacyUploadVideo_(), good, '手元/R2欠損時だけ旧Driveへfallbackする');
  const pair = await Promise.all([h.api.readLegacyDriveVideo_(), h.api.readLegacyDriveVideo_()]);
  assert.strictEqual(pair[0], good); assert.strictEqual(pair[1], good);
  assert.strictEqual(h.state.fetchTitles.length, 1, '同一single-flight内の旧Drive読込は一回だけ');

  console.log('All Drive frontend single-flight gates passed.');
})().catch(function (err) { console.error(err); process.exitCode = 1; });
