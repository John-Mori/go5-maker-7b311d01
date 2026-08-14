/**
 * tests/test_no_retired_globals.js
 * Node で実行できる自己完結テスト（追加パッケージ不使用）
 * 実行: node tests/test_no_retired_globals.js
 *
 * 【なぜ在るか】2026-08-02 のカテゴリ集約（commit 62fbc80・Go5Cats へ一元化）で、
 *   カテゴリ配列を持っていた 5 つのグローバルが退役した。ところが bluesky.js には
 *   退役した `MOVIE_ATTRS` への参照が 3 箇所残り、投稿履歴の保存経路（histAdd/recordToSheet）が
 *   ReferenceError で throw → 投稿履歴・シート記録が「無音で」欠落していた（2026-08-15・v=797 で除去）。
 *
 *   この型（＝退役した識別子への裸参照が、めったに通らない保存/記録経路で初めて throw する）は
 *   目視レビューでもテスト通過でもすり抜け、「直したつもり→本番で無音失敗→再発」の温床になる。
 *   ★ソースの文字列一致は保険にすぎないが、この用途は「退役語が完全に消えたか」の存在検査なので
 *     静的走査が正しい道具。1 つでも裸参照が復活したら CI が緑にならない＝再混入を機構で止める。
 *
 * 【対象】js/*.js のうち、コメント・文字列を除いた本体に、下の退役識別子が
 *   単語境界で現れ、かつ「その同じファイル内で宣言されていない」場合のみ FAIL。
 *   ＝ ReferenceError になる裸参照だけを咎める。ローカル var/let/const/function で
 *      同名を宣言し直しているファイル（例 wizard.js の `var ATTR_KEYS`）は throw しないので対象外。
 *   カテゴリの正本は core/categories.js（Go5Cats）だが、この検査が見るのは「throw するか否か」だけ。
 */

'use strict';

const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log('PASS: ' + name);
    passed++;
  } catch (e) {
    console.log('FAIL: ' + name);
    console.log('      ' + e.message);
    failed++;
  }
}

// 2026-08-02 のカテゴリ集約で退役した識別子（core/categories.js 冒頭の「5 箇所」）。
//   これらは Go5Cats.list() 由来へ置換済み。裸参照が残ると保存/記録経路で ReferenceError になる。
const RETIRED = ['MOVIE_ATTRS', 'GENRE_ATTR_KEYWORDS', 'ATTR_KEYS', 'MOVIE_ATTR_IDS', 'ATTR_DEFS'];

// コメント（/* */ と //）と文字列（' " `）を空白へ潰す。退役語が「解説文の中」や
//   「ログ文字列」に出るのは無害なので、本体コードだけを走査対象にする。
function stripCommentsAndStrings(src) {
  let out = '';
  let i = 0;
  const n = src.length;
  let state = 'code'; // code | line | block | sq | dq | tpl
  while (i < n) {
    const c = src[i];
    const c2 = src[i + 1];
    if (state === 'code') {
      if (c === '/' && c2 === '/') { state = 'line'; i += 2; continue; }
      if (c === '/' && c2 === '*') { state = 'block'; i += 2; continue; }
      if (c === "'") { state = 'sq'; i += 1; out += ' '; continue; }
      if (c === '"') { state = 'dq'; i += 1; out += ' '; continue; }
      if (c === '`') { state = 'tpl'; i += 1; out += ' '; continue; }
      out += c; i += 1; continue;
    }
    if (state === 'line') { if (c === '\n') { state = 'code'; out += '\n'; } i += 1; continue; }
    // ブロックコメント内の改行は保持する（行番号がズレないように）。
    if (state === 'block') { if (c === '*' && c2 === '/') { state = 'code'; i += 2; } else { if (c === '\n') out += '\n'; i += 1; } continue; }
    // 文字列内の改行も保持（テンプレートリテラルは複数行にまたがる）。
    if (state === 'sq') { if (c === '\\') { i += 2; continue; } if (c === "'") { state = 'code'; } if (c === '\n') out += '\n'; i += 1; continue; }
    if (state === 'dq') { if (c === '\\') { i += 2; continue; } if (c === '"') { state = 'code'; } if (c === '\n') out += '\n'; i += 1; continue; }
    if (state === 'tpl') { if (c === '\\') { i += 2; continue; } if (c === '`') { state = 'code'; } if (c === '\n') out += '\n'; i += 1; continue; }
  }
  return out;
}

function listJsFiles(dir) {
  const out = [];
  for (const name of fs.readdirSync(dir)) {
    if (name.endsWith('.js')) out.push(path.join(dir, name));
  }
  return out.sort();
}

test('退役したカテゴリ・グローバルへの裸参照が js/ に残っていない', function () {
  const jsDir = path.join(__dirname, '..', 'js');
  const files = listJsFiles(jsDir);
  if (!files.length) throw new Error('js/ に .js が見つからない（走査対象ゼロ＝検査が空振り）');

  const hits = [];
  for (const file of files) {
    const raw = fs.readFileSync(file, 'utf8');
    const body = stripCommentsAndStrings(raw);
    const lines = body.split('\n');
    for (const id of RETIRED) {
      const ref = new RegExp('\\b' + id + '\\b');
      // 同一ファイル内で宣言し直していれば ReferenceError にならない＝対象外。
      const declared = new RegExp('\\b(?:var|let|const|function)\\s+' + id + '\\b').test(body);
      if (declared) continue;
      for (let ln = 0; ln < lines.length; ln++) {
        if (ref.test(lines[ln])) {
          hits.push(path.basename(file) + ':' + (ln + 1) + ' → ' + id + '（宣言なし＝ReferenceError）');
        }
      }
    }
  }
  if (hits.length) {
    throw new Error(
      '退役識別子への裸参照を検出（Go5Cats.list() 由来へ置換せよ）:\n      ' + hits.join('\n      ')
    );
  }
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
