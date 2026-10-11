// 背景動画のループ継ぎ目(readyState<2)で単色コマを描かず、直前の背景で埋めるか(Chami 2026-10-11 msg 1558822056676818964)
// app.js の drawBg_ を本物のまま取り出し、video/canvas だけ偽物にして回す。
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'js', 'app.js'), 'utf8');
const m = src.replace(/\r\n/g, '\n').match(/  let _bgHold = null[\s\S]*?\n  function drawBg_\(\) \{[\s\S]*?\n  \}\n/);
if (!m) { console.error('FAIL: drawBg_ が見つからない'); process.exit(1); }

let pass = 0, fail = 0;
function ok(c, msg) { if (c) { pass++; console.log('ok  ' + msg); } else { fail++; console.log('NG  ' + msg); } }

function make() {
  const log = [];
  const ctx = { drawImage: (s) => log.push(s && s.__id ? s.__id : 'other'), fillRect: () => log.push('fill'), set fillStyle(v) {} };
  const bg = { __id: 'video', readyState: 4, videoWidth: 720, videoHeight: 1280, _src: 'assets/bg_account3_sea2.mp4', getAttribute() { return this._src; } };
  const cv = { __id: 'cv' };
  const document = { createElement: () => ({ __id: 'hold', width: 0, height: 0, getContext: () => ({ drawImage: () => {} }) }) };
  const sb = { W: 1080, H: 1920, bg, cv, ctx, document };
  vm.createContext(sb);
  vm.runInContext(m[0] + '\nthis.drawBg_ = drawBg_;', sb);
  return { sb, bg, log };
}

{ // 描けた後にループ継ぎ目が来た
  const { sb, bg, log } = make();
  sb.drawBg_();
  bg.readyState = 1; log.length = 0;
  sb.drawBg_();
  ok(log.indexOf('fill') < 0, '継ぎ目のコマで単色を描かない');
  ok(log.indexOf('hold') >= 0, '継ぎ目のコマは直前の背景で埋める');
}
{ // まだ1枚も描けていない
  const { sb, bg, log } = make();
  bg.readyState = 0;
  sb.drawBg_();
  ok(log.indexOf('fill') >= 0, '初回でデコード前なら単色(従来どおり)');
}
{ // アカウントを切り替えた直後は前の背景を使わない
  const { sb, bg, log } = make();
  sb.drawBg_();
  bg._src = 'assets/bg_account2.mp4'; bg.readyState = 1; log.length = 0;
  sb.drawBg_();
  ok(log.indexOf('hold') < 0 && log.indexOf('fill') >= 0, '背景が変わったら控えを使わない');
}
{ // 正常時は動画そのものを描く
  const { sb, log } = make();
  sb.drawBg_();
  ok(log[0] === 'video', 'デコード済みなら動画を描く');
}
console.log(`${pass} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
