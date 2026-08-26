'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'yt-clicks.js'), 'utf8');

function section(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, 'section not found: ' + start);
  return source.slice(from, to);
}

const localSave = section('function saveEdit_(', 'function saveEditFromSheet_(');
const sheetSave = section('function saveEditFromSheet_(', 'function mintWorkShortAtPost_(');
const mintCore = section('function mintWorkShortAtPost_(', 'function attemptPendingWorkShortMint_(');
const applyWorkShort = section('function applyWorkShort_(', 'function applyMergeUrls_(');
const reconcile = section('function reconcilePend_(', 'function acctByShort_(');
const completed = section('function addCompletedPost_(', 'function lsHasEntry_(');
const mintWrapper = section('function attemptPendingWorkShortMint_(', 'var _workShortMintBootScanned');
const bootReady = section('function workShortMintStoreReady_(', 'function retryPendingWorkShortMintsAtBoot_(');
const bootRetry = section('function retryPendingWorkShortMintsAtBoot_(', 'function chOfVid_(');
const refreshBlock = section('function refresh(', 'function sendSync_(');
const hydrateHook = section("document.addEventListener('go5-hist-hydrated'", 'function paintCachedNow_(');
const sendSync = source.slice(source.indexOf('function sendSync_('));

assert.ok(!/autoMeasureWorkShort_\s*\(/.test(localSave), 'saveEdit_ must not auto-generate work short URLs');
assert.ok(!/mintWorkShortAtPost_\s*\(/.test(localSave), 'saveEdit_ must not mint work short URLs');
assert.ok(!/autoMeasureWorkShort_\s*\(/.test(sheetSave), 'saveEditFromSheet_ must not auto-generate work short URLs');
assert.ok(!/mintWorkShortAtPost_\s*\(/.test(sheetSave), 'saveEditFromSheet_ must not mint work short URLs');

assert.ok(!/function\s+autoMeasureWorkShort_\s*\(/.test(source), 'autoMeasureWorkShort_ must stay removed');
assert.ok(!/function\s+mintMissingWorkShorts_\s*\(/.test(source), 'mintMissingWorkShorts_ must stay removed');

const mintCalls = source.match(/mintWorkShortAtPost_\s*\(/g) || [];
const mintDefinitions = source.match(/function\s+mintWorkShortAtPost_\s*\(/g) || [];
assert.strictEqual(mintDefinitions.length, 1, 'mintWorkShortAtPost_ must have one definition');
assert.strictEqual(mintCalls.length - mintDefinitions.length, 1, 'mintWorkShortAtPost_ must have one direct call');
assert.match(mintWrapper, /mintWorkShortAtPost_\s*\(/, 'the sole direct mint call must be in the guarded wrapper');
assert.ok(!/mintWorkShortAtPost_\s*\(/.test(completed), 'completion must call the wrapper, not mint directly');

const pendingAssignments = source.match(/\.workShortMintPending\s*=\s*true\s*;/g) || [];
assert.strictEqual(pendingAssignments.length, 1, 'pending may be assigned only by the true-new completion path');
const entryAt = completed.indexOf('var entry = { manual: true');
const pendingAt = completed.indexOf('entry.workShortMintPending = true');
const unshiftAt = completed.indexOf('manual.unshift(entry)');
const tailAt = completed.indexOf('function tail_()');
const wrapperAt = completed.indexOf('attemptPendingWorkShortMint_(entry, acc)');
assert.ok(entryAt >= 0 && pendingAt > entryAt && pendingAt < unshiftAt, 'true-new entry must persist pending before unshift');
assert.ok(wrapperAt > tailAt, 'the completion tail must invoke the guarded wrapper');
assert.match(completed, /!entry\.workShortUrl\s*&&\s*\/\^https\?:\\\/\\\//, 'pending requires a valid work URL and no existing short URL');
assert.match(completed, /matched\.workShortMintPending\s*===\s*true[^]*delete matched\.workShortMintPending/,
  'dupe completion must clear a stale pending marker without creating one');

assert.match(mintWrapper, /workShortMintPending\s*!==\s*true\s*\|\|\s*it\.workShortNone\s*\|\|\s*it\.workShortUrl/,
  'wrapper must accept explicit pending rows only');
assert.match(mintWrapper, /loadArrFor_\('verify_manual',\s*account\)/, 'success must reload the canonical manual ledger');
assert.match(mintWrapper, /String\(latest\.videoId\s*\|\|\s*''\)\s*!==\s*expectedVideoId/, 'success must re-check video identity');
assert.match(mintWrapper, /chOfVid_\(latest\.videoId,\s*''\)\s*!==\s*account/, 'success must re-check account identity');
assert.match(mintWrapper, /latest\.workShortMintPending\s*!==\s*true\s*\|\|\s*latest\.workShortNone\s*\|\|\s*latest\.workShortUrl/,
  'success must not overwrite a cleared, tombstoned, or already-filled latest row');
assert.ok(mintWrapper.indexOf('delete latest.workShortMintPending') < mintWrapper.indexOf("saveArrFor_('verify_manual'"),
  'success must clear pending before persisting and syncing');

assert.match(bootReady, /state\s*===\s*'hydrated'\s*\|\|\s*state\s*===\s*'degraded'/,
  'boot retry must skip pre-hydration storage');
assert.match(bootRetry, /loadArrFor_\('verify_manual',\s*account\)/, 'boot retry scans verify_manual only');
assert.match(bootRetry, /row\.workShortMintPending\s*===\s*true/, 'boot retry requires an exact pending marker');
assert.doesNotMatch(bootRetry, /short_hist|allItems/, 'boot retry must not infer candidates from other ledgers');
assert.match(hydrateHook, /verify_manual__acc1[^]*verify_manual__acc2/, 'both account hydrate events must be handled');
const fallbackCalls = source.match(/setTimeout\(function \(\) \{ retryPendingWorkShortMintsAtBoot_\(\); \}, 2500\);/g) || [];
assert.strictEqual(fallbackCalls.length, 1, 'boot retry must have exactly one fallback timer');
assert.match(mintCore, /tries\s*<\s*3[^]*setTimeout\(attempt_,\s*tries\s*\*\s*1500\)/, 'mint must retain three bounded attempts');
assert.match(mintCore, /catch\s*\(e\)\s*\{\s*retry_\(\);\s*\}/, 'synchronous mint failures must use the same bounded retry');
assert.doesNotMatch(refreshBlock, /retryPendingWorkShortMintsAtBoot_/, 'normal refresh must never trigger pending mint retries');

assert.match(source, /var\s+_openedWorkShort\s*=\s*''/,
  'modal-open snapshot for the work short URL must exist');
assert.match(source, /_openedWorkShort\s*=\s*workShortVal\s*\|\|\s*''/,
  'modal open must snapshot the displayed work short URL');
assert.match(applyWorkShort, /if\s*\(typedVal\s*===\s*_openedWorkShort\s*&&\s*typedVal\s*!==\s*''\)\s*\{\s*delete item\.workShortMintPending;\s*return;\s*\}/,
  'unchanged non-empty work short URL must be a no-op');

const applyFactory = new Function(
  '_openedWorkShort', '_pendingWorkShort', '_pendingWorkShare',
  applyWorkShort + '\nreturn applyWorkShort_;'
);
const oldDomain = 'https://old.example/legacy-code';
const keepLegacy = applyFactory(oldDomain, '', '');
const legacyItem = { workShortUrl: oldDomain, workShareUrl: oldDomain, workShortMintPending: true };
keepLegacy(legacyItem, oldDomain);
assert.deepStrictEqual(legacyItem, { workShortUrl: oldDomain, workShareUrl: oldDomain },
  'an unchanged legacy/non-domain value must remain byte-for-byte unchanged');
const confirmBlank = applyFactory('', '', '');
const blankItem = { workShortMintPending: true };
confirmBlank(blankItem, '');
assert.strictEqual(blankItem.workShortNone, true,
  'empty-on-open saved as empty must create an intentional-empty tombstone');
assert.ok(!Object.prototype.hasOwnProperty.call(blankItem, 'workShortMintPending'), 'blank save must clear pending');
const manualItem = { workShortMintPending: true };
applyFactory('', '', '')(manualItem, oldDomain);
assert.ok(!Object.prototype.hasOwnProperty.call(manualItem, 'workShortMintPending'), 'manual URL must clear pending');
const generatedItem = { workShortMintPending: true };
applyFactory('', 'https://new.example/r2', 'https://new.example/share')(generatedItem, 'https://new.example/share');
assert.ok(!Object.prototype.hasOwnProperty.call(generatedItem, 'workShortMintPending'), 'explicit generation must clear pending');

assert.match(sendSync, /workShortClear\s*:\s*!!it\.workShortNone/,
  'bulk sync must forward the intentional-empty tombstone');
assert.match(sendSync, /rec\.platform\s*=\s*it\.platform/,
  'bulk sync must forward the explicit platform');
assert.match(sheetSave, /work_short_clear\s*:\s*!!edited\.workShortNone/,
  'sheet upsert must forward the intentional-empty tombstone');
assert.match(sheetSave, /payload\.platform\s*=\s*edited\.platform/,
  'sheet upsert must forward the explicit platform');
assert.match(sheetSave, /workShortClear\s*:\s*!!payload\.work_short_clear/,
  'sheet verification must verify the intentional-empty tombstone');
assert.match(sheetSave, /expected\.platform\s*=\s*payload\.platform/,
  'sheet verification must verify the explicit platform');
assert.match(reconcile, /expected\.workShortClear\s*=\s*!!patch\.workShortNone/,
  'pending-edit reconciliation must verify the intentional-empty tombstone');
assert.match(reconcile, /expected\.platform\s*=\s*patch\.platform/,
  'pending-edit reconciliation must verify the explicit platform');

console.log('OK: history edit preservation contract');
