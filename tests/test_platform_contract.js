/**
 * 投稿先(platform)のフロント→GAS→記録シート中継契約を固定する静的回帰テスト。
 * Apps Script本体はNodeへ直接requireできないため、各書込経路がwriteRecord_へ値を渡すことを検査する。
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const gas = fs.readFileSync(path.join(__dirname, '..', 'gas', 'コード.gs'), 'utf8');
const bluesky = fs.readFileSync(path.join(__dirname, '..', 'js', 'bluesky.js'), 'utf8');
const ytClicks = fs.readFileSync(path.join(__dirname, '..', 'js', 'yt-clicks.js'), 'utf8');

function section(source, start, end) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, 'section not found: ' + start);
  return source.slice(a, b);
}

const doPost = section(gas, 'function doPost(e)', 'function teianDecide_');
assert.match(
  doPost,
  /platform\s*:\s*\(body\.platform\s*===\s*'x'\s*\|\|\s*body\.platform\s*===\s*'bsky'\)[\s\S]*?body\.platform[\s\S]*?body\.postUri/,
  'doPost must forward body.platform and only infer legacy Bluesky from postUri'
);
assert.ok(doPost.includes('/^at:') && doPost.includes(".test(String(body.postUri || ''))"), 'doPost legacy inference must require an at:// URI');
assert.ok(!doPost.includes("(body.postUri ? 'bsky' : '')"), 'doPost must not classify every truthy postUri as Bluesky');

const syncHistory = section(gas, 'function syncHistory_(channel, items)', 'function pruneHistory_');
assert.match(
  syncHistory,
  /platform\s*:\s*\(it\.platform\s*===\s*'x'\s*\|\|\s*it\.platform\s*===\s*'bsky'\)[\s\S]*?it\.platform[\s\S]*?it\.postUri/,
  'syncHistory_ must forward each item.platform'
);
assert.ok(syncHistory.includes('/^at:') && syncHistory.includes(".test(String(it.postUri || ''))"), 'syncHistory legacy inference must require an at:// URI');
assert.ok(!syncHistory.includes("(it.postUri ? 'bsky' : '')"), 'syncHistory must not classify every truthy postUri as Bluesky');
assert.ok(syncHistory.includes("workShortClear: it.workShortClear === true || it.workShortClear === 'true'"), 'syncHistory_ must accept only an explicit true clear command');
assert.ok(!syncHistory.includes('workShortClear: !!it.workShortClear'), 'syncHistory_ must not coerce string "false" into a destructive clear');
assert.ok(syncHistory.includes('preserveMutableExisting: true'), 'bulk sync must request server-side preservation of mutable truth');

const writeRecord = section(gas, 'function writeRecord_(channel, f)', 'function syncHistory_');
assert.ok(writeRecord.includes("putIf('投稿先'"), 'writeRecord_ must write platform into the 投稿先 sheet cell');
assert.ok(writeRecord.includes("put('作品短縮URL', '')") && writeRecord.includes("putIf('作品短縮URL'"), 'writeRecord_ must support explicit clear and value writes for 作品短縮URL');
assert.ok(writeRecord.includes("preserveMutableExisting && existingPlatform !== ''"), 'bulk sync must preserve a non-empty server platform');
assert.ok(writeRecord.includes("preserveMutableExisting && existingWorkShort !== ''"), 'bulk sync must preserve a non-empty server work-short URL');
assert.ok(writeRecord.includes('sh.getRange(target, mutableMin, 1, mutableMax - mutableMin + 1).getValues()[0]'), 'bulk preservation must read the two mutable cells in one range call');

const historyItems = section(gas, 'function historyItems_(channel, limit)', 'function deleteRecord_');
assert.ok(historyItems.includes('platform: pfCol ? String'), 'historyItems_ must return platform from the 投稿先 sheet cell');
assert.ok(historyItems.includes('workShortUrl: wsuCol ? String'), 'historyItems_ must return the 作品短縮URL sheet cell');

const reservations = section(gas, 'function runReservations()', 'function bskyCreds_');
assert.match(reservations, /writeRecord_\(ch,[\s\S]*?platform\s*:\s*'bsky'/, 'GAS Bluesky reservation must record platform=bsky');

const recordToSheet = section(bluesky, 'function recordToSheet(record)', 'function updateGasStatus()');
assert.ok(
  recordToSheet.includes("platform: (record.platform === 'x' || record.platform === 'bsky') ? record.platform : 'bsky'"),
  'recordToSheet must explicitly send platform=bsky for a new Bluesky post'
);

const histAdd = section(bluesky, 'function histAdd(rec)', 'function fmtTs(ts)');
assert.ok(
  histAdd.includes("platform: (rec.platform === 'x' || rec.platform === 'bsky') ? rec.platform : 'bsky'"),
  'histAdd must persist platform=bsky in local post history'
);

const isXLink = section(ytClicks, 'function isXLink_(href, it)', 'function postLinkHtml_(href, it)');
assert.ok(
  isXLink.includes('/^at:') && isXLink.includes(".test(String(it.postUri || ''))"),
  'post-link rendering must infer Bluesky only from an at:// URI'
);
assert.ok(!isXLink.includes('if (it && it.postUri)'), 'post-link rendering must not classify every truthy postUri as Bluesky');

const platOf = section(ytClicks, 'function platOf_(it)', 'function saleCodes_()');
assert.ok(
  platOf.includes('/^at:') && platOf.includes(".test(String(it.postUri || ''))"),
  'the edit modal must infer Bluesky only from an at:// URI'
);
assert.ok(!platOf.includes('if (it && it.postUri)'), 'the edit modal must not classify every truthy postUri as Bluesky');

const inheritRebuild = section(bluesky, 'function inheritRebuildPost_(old, ev)', 'function maybeInheritRebuild_(ev)');
assert.ok(inheritRebuild.includes("(old.platform === 'x' || old.platform === 'bsky') ? old.platform : ''"), 'rebuild inheritance must accept only an explicit x/bsky platform');
assert.ok(inheritRebuild.includes('if (inheritedPlatform) histRecord.platform = inheritedPlatform'), 'rebuild inheritance must preserve platform in local history');
assert.ok(inheritRebuild.includes('if (inheritedPlatform) sheetRecord.platform = inheritedPlatform'), 'rebuild inheritance must preserve platform in the sheet payload');

console.log('OK: platform forwarding contract (frontend inference / doPost / syncHistory / reservation / Bluesky creation)');
