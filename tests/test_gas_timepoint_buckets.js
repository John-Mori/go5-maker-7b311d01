// GAS(コード.gs)の時点記録バケットに 3時間/36時間 が入り、cap窓(次の境界の直前まで)が正しく効くことの回帰テスト。
// 2026-10-12: Chami「従来プラス 0.5h,1h,2h,3h,6h,12h,24h,36h,48h」。72時間は残す=10窓。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'gas', 'コード.gs'), 'utf8');
let pass = 0, fail = 0;
function check(name, ok) { if (ok) { pass++; console.log('PASS: ' + name); } else { fail++; console.log('FAIL: ' + name); } }

const pick = (re) => { const m = src.match(re); return m ? m[0] : ''; };
const capSrc = pick(/function captureTimepoints_\([\s\S]*?\n\}\r?\n/);
const ctx = {
  Utilities: { formatDate: () => '2026-10-12 00:00' },
  rows: [],
  timepointSheet_: function () {
    const rows = ctx.rows;
    return {
      getLastRow: () => rows.length + 1,
      getRange: (r, c, n) => ({
        getValues: () => rows.slice(r - 2, r - 2 + n).map((x) => x.slice(0, 4)),
        setValues: (vals) => { vals.forEach((v) => rows.push(v)); }
      })
    };
  }
};
vm.runInNewContext(pick(/var TIMEPOINT_HEADERS = \[[^\]]*\];/) + '\n' + pick(/var TIME_BUCKETS = \[[^\n]*\];/) + '\n' + capSrc +
  '\nthis.TIME_BUCKETS = TIME_BUCKETS; this.captureTimepoints_ = captureTimepoints_;', ctx);

const mins = ctx.TIME_BUCKETS.map((b) => b[0]);
check('10窓(30/60/120/180/360/720/1440/2160/2880/4320)', JSON.stringify(mins) === JSON.stringify([30, 60, 120, 180, 360, 720, 1440, 2160, 2880, 4320]));
check('昇順(cap窓が次の境界を正しく引く前提)', mins.every((m, i) => i === 0 || m > mins[i - 1]));
check('LAB に 3時間=b180 / 36時間=b2160', /'3時間': 'b180'/.test(src) && /'36時間': 'b2160'/.test(src));
check('LAB に既存8窓が残る', ['b30', 'b60', 'b120', 'b360', 'b720', 'b1440', 'b2880', 'b4320'].every((k) => src.indexOf("': '" + k + "'") >= 0));

// 経過分ごとにどのバケットが書かれるか(既記録なしの前提で1回スナップ)
function labelsAt(elapsedMin) {
  ctx.rows = [];
  const rec = { post_id: 'acc3-x', channel: 'acc3', postedAtMs: Date.now() - elapsedMin * 60000, vid: 'v', code: 'c' };
  ctx.captureTimepoints_([rec], { v: 10 }, { c: 1 }, 'now', 'Asia/Tokyo');
  return ctx.rows.map((r) => r[3]);
}
check('150分→2時間だけ', JSON.stringify(labelsAt(150)) === '["2時間"]');
check('185分→3時間(2時間窓は3hで閉じる)', JSON.stringify(labelsAt(185)) === '["3時間"]');
check('370分→6時間', JSON.stringify(labelsAt(370)) === '["6時間"]');
check('1500分→24時間', JSON.stringify(labelsAt(1500)) === '["24時間"]');
check('2200分→36時間(24時間窓は36hで閉じる)', JSON.stringify(labelsAt(2200)) === '["36時間"]');
check('2900分→48時間', JSON.stringify(labelsAt(2900)) === '["48時間"]');
check('5000分→72時間(上限96hは不変)', JSON.stringify(labelsAt(5000)) === '["72時間"]');
check('5800分→何も書かない', labelsAt(5800).length === 0);

console.log('\n結果: ' + pass + ' PASS / ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
