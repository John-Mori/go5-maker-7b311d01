/**
 * 再発上位の構造ガード。
 * 症状ごとの画面テストだけではなく、再発源となる「別実装の復活」をCIで止める。
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const read = rel => fs.readFileSync(path.join(root, rel), 'utf8');

let passed = 0;
function test(name, fn) {
  fn();
  passed++;
  console.log('PASS: ' + name);
}

test('R-1: 外部短縮APIの新規発番器がフロント/GASへ存在しない', function () {
  const src = read('js/bluesky.js') + '\n' + read('gas/コード.gs');
  assert.ok(!/https:\/\/(?:da\.gd|tinyurl\.com)\//i.test(src), '外部短縮API URLが復活している');
  assert.ok(!/\b(?:daGdShorten_|SHARE_SHORTENERS|USE_DAGD_CHAIN)\b/.test(src), '退役した外部短縮発番器が復活している');
  assert.ok(/managed-short-only/.test(src), 'GASの稼働機能宣言が独自短縮限定になっていない');
});

test('R-2: 投稿履歴の重複判定はHistMergeの単一権威を使う', function () {
  const src = read('js/yt-clicks.js');
  const uses = src.match(/HistMerge\.findDuplicate/g) || [];
  assert.ok(uses.length >= 2, '投稿完了とアカウント移送の両方が共通重複判定を通っていない');
  assert.ok(/function itemYt_\([^)]*\)[\s\S]{0,240}historyMapValue/.test(src), '旧キー互換のYouTube URL読取が共通化されていない');
});

test('R-3: 保存中ボタンの本番とテストが同じOperationGateを使う', function () {
  const stock = read('js/stock.js');
  const candidates = read('js/candidates.js');
  const testSrc = read('tests/test_drive_save_settle.js');
  assert.ok(/Go5OperationGate\.armButton/.test(stock), '本番Drive保存が共通終端制御を使っていない');
  assert.ok(/Go5OperationGate\.armButton/.test(candidates), '本番候補保存が共通終端制御を使っていない');
  assert.ok(/require\('\.\.\/core\/operation-gate\.js'\)/.test(testSrc), '回帰テストが本番状態機械ではなくコピーを検証している');
  ['index.html', 'Stock.html', 'KouhoTeian.html'].forEach(function (rel) {
    const html = read(rel);
    const gate = html.indexOf('core/operation-gate.js');
    const featureJs = rel === 'KouhoTeian.html' ? html.indexOf('js/candidates.js') : html.indexOf('js/stock.js');
    assert.ok(gate >= 0 && featureJs > gate, rel + ' の読込順が不正');
  });
});

test('R-4: 実行対象JSにNULバイトを混入させない', function () {
  ['core', 'js'].forEach(function (dir) {
    fs.readdirSync(path.join(root, dir)).filter(n => n.endsWith('.js')).forEach(function (name) {
      const buf = fs.readFileSync(path.join(root, dir, name));
      assert.strictEqual(buf.includes(0), false, dir + '/' + name + ' にNULバイトがある');
    });
  });
});

console.log('PASS: test_recurrence_architecture (' + passed + ' checks)');
