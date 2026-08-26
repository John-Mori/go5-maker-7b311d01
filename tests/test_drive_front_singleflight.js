// ブラウザ側の同作品Drive保存single-flightを、CIの構造門として固定する。
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'js', 'stock.js'), 'utf8');

assert.ok(src.includes('var _driveDatasetInFlight = Object.create(null);'), '作品別in-flight台帳が必要');
assert.ok(src.includes("var flightKey = String(meta.account || '') + '\\n' + String(meta.title || meta.id);"), 'チャンネル＋題名を同一保存キーにする');
assert.ok(/if \(activeFlight\) \{[\s\S]{0,180}activeFlight\.waiters\.push\(opts\.onDone\);[\s\S]{0,80}return;/.test(src), '二本目は先行処理へjoinしてDrive書込みを開始しない');
assert.ok(src.includes('delete _driveDatasetInFlight[flightKey]'), '終端でロックを解放する');
assert.ok(src.includes('flight.watchdog = setTimeout'), '無応答でもロックを永久保持しない');
assert.ok(!src.includes("done(true, '☁️ Driveへ保存中(裏で継続)・結果はカードに出ます');"), 'queueSave前にsingle-flightを解放する旧早期doneを復活させない');
const joinAt = src.indexOf('if (activeFlight)');
const queueAt = src.indexOf('window.Go5Drive.queueSave({', joinAt);
assert.ok(joinAt >= 0 && queueAt > joinAt, 'join判定がqueueSaveより必ず先');
console.log('All Drive frontend single-flight gates passed.');