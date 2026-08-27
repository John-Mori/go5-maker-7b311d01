'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const sale = fs.readFileSync(path.join(__dirname, '..', 'js', 'yt-clicks.js'), 'utf8');
const stock = fs.readFileSync(path.join(__dirname, '..', 'js', 'stock.js'), 'utf8');
assert.ok(/return arr\.map\([\s\S]*?\)\.sort\(function \(a, b\) \{[\s\S]*?Number\(b\.at\)[\s\S]*?Number\(a\.at\)/.test(sale), 'セールは記載開始日atの降順にする');
assert.ok(stock.indexOf('videoEndFramePreview_(evDetail.blob)') < stock.indexOf('var capP = Promise.all([captureThumb_(), finalPreviewP])'), '完成動画の終端を取得してから保存へ進む');
console.log('PASS: sale start-date order / final-video preview source');