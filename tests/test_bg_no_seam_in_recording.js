// 背景動画の継ぎ目(ループで頭へ戻る瞬間)が録画の中に入ると、Androidで単色のコマが焼き込まれる(Chami 2026-10-11 恒久)。
// v983で支給の5.03秒動画を勝手に4.0秒ループへ縮め、継ぎ目が録画の4秒目に来た。同じ縮めと、録画中のループ再開を禁止する。
//  1) 各アカウントの背景mp4は見た目の長さ DURATION 以上(ffprobe が無い環境ではこの項目だけ飛ばす)
//  2) 録画開始では bg.loop=false を play より前に置く(録画末尾で頭へ跳ね戻らない)
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'js', 'app.js'), 'utf8').replace(/\r\n/g, '\n');
let pass = 0, fail = 0;
function ok(c, msg) { if (c) { pass++; console.log('ok  ' + msg); } else { fail++; console.log('NG  ' + msg); } }

const DURATION = Number((src.match(/const DURATION = ([\d.]+)/) || [])[1]);
ok(DURATION > 0, 'DURATION を読める(' + DURATION + 's)');

let probe = true;
try { execFileSync('ffprobe', ['-version'], { stdio: 'ignore' }); } catch (e) { probe = false; console.log('skip ffprobe が無いので長さ検査を飛ばす'); }
const bgs = [...src.matchAll(/acc\d+: \{[^\n]*?bg: "(assets\/[^"?]+)/g)].map((m) => m[1]);
ok(bgs.length >= 1, '背景mp4の指定を拾える(' + bgs.join(', ') + ')');
if (probe) for (const b of bgs) {
  const out = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path.join(root, b)]).toString().trim();
  ok(Number(out) >= DURATION - 0.02, b + ' の長さ ' + out + 's ≥ ' + DURATION + 's(継ぎ目が見た目の5秒に入らない)');
}

const i0 = src.indexOf('bg.currentTime = 0;\n      // 録画中は背景をループさせない');
const seg = i0 >= 0 ? src.slice(i0, i0 + 400) : '';
const iLoop = seg.indexOf('bg.loop = false'), iPlay = seg.indexOf('bg.play()');
ok(iLoop >= 0 && iPlay > iLoop, '録画開始で bg.loop=false を play より前に置いている');
console.log((fail ? 'FAIL' : 'OK') + ' test_bg_no_seam_in_recording: ' + pass + ' pass, ' + fail + ' fail');
process.exit(fail ? 1 : 0);
