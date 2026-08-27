'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'candidates.js'), 'utf8');
const helperAt = source.indexOf('function persistRefWithoutIdb_(');
const helperEnd = source.indexOf('\n  // go5ref:<cid>:0..n-1', helperAt);
assert(helperAt >= 0 && helperEnd > helperAt, 'the shared non-IDB durability helper must exist');
const helper = source.slice(helperAt, helperEnd);
const cdnAt = helper.indexOf("imageCdnMirror_('ref'");
const namedR2At = helper.indexOf('pushRefToR2_(');
const base64At = helper.indexOf('var recLs =');
assert(cdnAt >= 0 && namedR2At > cdnAt && base64At > namedR2At,
  'fallback order must be CDN ledger, named R2, then base64 localStorage');
assert(helper.includes("klog_('ref_image_saved_cdn'"), 'the cloud success lane must be observable');

const saveAt = source.indexOf('function refImgSave(cid, data)');
const saveEnd = source.indexOf('\n  function bskyImgOf', saveAt);
const save = source.slice(saveAt, saveEnd);
const uses = save.match(/persistRefWithoutIdb_\(/g) || [];
assert.strictEqual(uses.length, 2, 'IDB rejection and IDB-unavailable branches must share the same helper');
assert(save.includes('var hadPrevNoIdb'), 'the no-IDB lane must preserve rollback state');
assert(source.includes('var base = _imgMem.ref[cid] || legacyRefOf_(cid) || null;'),
  'fresh cloud-backed memory must remain readable even when IDB is unavailable');

console.log('candidate image durable fallback tests: ok');
