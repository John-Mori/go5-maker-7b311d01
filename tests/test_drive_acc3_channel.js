// 癒やし倉庫(acc3)のDrive保存先が配線されているかの回帰テスト(2026-10-12 Chami指示)。
//   Worker: channelToFolderId が acc3 → FOLDER_ID_ACC3 を返す / wrangler.toml に FOLDER_ID_ACC3 がある。
//   フロント: drive-upload.js の isDriveCh が acc3 を通す。
'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const root = path.join(__dirname, '..');

function extractFn(src, name) {
  const i = src.indexOf('function ' + name + '(');
  assert(i >= 0, name + ' が見つからない');
  let depth = 0, j = src.indexOf('{', i);
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}' && --depth === 0) return src.slice(i, k + 1);
  }
  throw new Error(name + ' の終端が見つからない');
}

const worker = fs.readFileSync(path.join(root, 'drive-worker/src/index.js'), 'utf8');
const channelToFolderId = new Function(extractFn(worker, 'channelToFolderId') + '; return channelToFolderId;')();
const env = { FOLDER_ID_ACC1: 'F1', FOLDER_ID_ACC2: 'F2', FOLDER_ID_ACC3: 'F3', LABEL_ACC3: '癒やし倉庫' };
assert.strictEqual(channelToFolderId('acc3', env), 'F3');
assert.strictEqual(channelToFolderId('ACC3', env), 'F3');
assert.strictEqual(channelToFolderId('癒やし倉庫', env), 'F3');
assert.strictEqual(channelToFolderId('acc1', env), 'F1');
assert.strictEqual(channelToFolderId('acc2', env), 'F2');
assert.strictEqual(channelToFolderId('acc4', env), '');
assert.strictEqual(channelToFolderId('acc3', {}), '');
console.log('  PASS Worker channelToFolderId acc3');

const toml = fs.readFileSync(path.join(root, 'drive-worker/wrangler.toml'), 'utf8');
assert(/^FOLDER_ID_ACC3 = "[^"]+"/m.test(toml), 'wrangler.toml に FOLDER_ID_ACC3 が無い');
console.log('  PASS wrangler.toml FOLDER_ID_ACC3');

const front = fs.readFileSync(path.join(root, 'js/drive-upload.js'), 'utf8');
const isDriveCh = new Function(extractFn(front, 'isDriveCh') + '; return isDriveCh;')();
assert(isDriveCh('acc1') && isDriveCh('acc2') && isDriveCh('acc3'));
assert(!isDriveCh('') && !isDriveCh('acc4'));
assert(!/channel !== "acc1" && channel !== "acc2"(?! && channel !== "acc3")/.test(front), 'acc1/acc2限定のゲートが残っている');
console.log('  PASS drive-upload.js isDriveCh acc3');

console.log('\nAll drive acc3 channel tests passed.');
