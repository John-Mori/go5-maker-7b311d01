// tests/test_video_integrity.js — 空動画/誤種別を「保存成功」に昇格させない回帰。
var V = require('../core/video-integrity.js');

var fails = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { fails++; console.error('  ✗ ' + msg); } }

ok(!V.isUsableBlob(null), 'null は動画ではない');
ok(!V.isUsableBlob(new Blob([], { type: 'video/mp4' })), '空の video/mp4 を拒否');
ok(!V.isUsableBlob(new Blob([new Uint8Array(V.MIN_VIDEO_BYTES - 1)], { type: 'video/mp4' })), '下限未満を拒否');
ok(!V.isUsableBlob(new Blob([new Uint8Array(V.MIN_VIDEO_BYTES)], { type: 'image/jpeg' })), '十分大きくても画像Blobを拒否');
ok(V.isUsableBlob(new Blob([new Uint8Array(V.MIN_VIDEO_BYTES)], { type: 'video/mp4' })), '下限以上のvideo/mp4を許可');
ok(V.isUsableBlob(new Blob([new Uint8Array(V.MIN_VIDEO_BYTES)], { type: '' })), 'R2旧データの空MIMEを許可');
ok(V.isUsableBlob(new Blob([new Uint8Array(V.MIN_VIDEO_BYTES)], { type: 'application/octet-stream' })), 'R2旧データのoctet-streamを許可');

if (fails) { console.error('FAIL: ' + fails + '/' + checks); process.exit(1); }
console.log('PASS: test_video_integrity (' + checks + ' checks)');
