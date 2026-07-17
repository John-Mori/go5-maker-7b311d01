/**
 * tests/test_bat_encoding.js
 * .bat ファイルの改行・文字コード検証（P0-3: INC-58型の文字化け障害の再発防止）。
 * リポジトリ内の全 .bat を走査し、以下2点を検証する:
 *   (a) LF単独行が無い（全行 CRLF）
 *   (b) 非ASCIIバイトを含む .bat は `chcp 65001` 行を持つ（UTF-8での文字化け対策）
 * 実行: node tests/test_bat_encoding.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SKIP_DIRS = new Set(['.git', 'node_modules']);

// 既知の違反(2026-07-16監査時点で既存のLF改行bat)。クラウドから盲目変換せず、
// PC側で「cmd /c で1回実行して確認」(INC-58の教訓)とセットで順次CRLF化する
// (handoff_P0_常駐自動復帰と実体棚卸_2026-07-16.md タスク4)。
// ★修正したらこのリストから削除する。新規batがここに増えるのは禁止(必ずCRLFで作る)。
const KNOWN_VIOLATIONS = new Set([
  'GASを反映.bat',
  'GAS初期設定.bat',
  'scripts/discord/test_discord_once.bat',
  'scripts/llm/start_local_responder.bat',
  'scripts/maintenance/start_daily_maintenance.bat',
  'scripts/sales_fetch_3h.bat',
  'scripts/sales_poll.bat',
  '未収録作品を取得.bat',
  '販売数-3時間ごと自動取得を停止.bat',
  '販売数-自動取得を停止.bat',
  '販売数-自動取得を設定.bat',
  '販売数を取得.bat',
]);

function findBatFiles(dir, out) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      findBatFiles(full, out);
    } else if (entry.isFile() && entry.name.toLowerCase().endsWith('.bat')) {
      out.push(full);
    }
  }
  return out;
}

function hasBareLf(buf) {
  for (let i = 0; i < buf.length; i++) {
    if (buf[i] === 0x0a && (i === 0 || buf[i - 1] !== 0x0d)) return true;
  }
  return false;
}

function hasNonAscii(buf) {
  for (let i = 0; i < buf.length; i++) {
    if (buf[i] > 0x7f) return true;
  }
  return false;
}

function hasChcpUtf8(buf) {
  return buf.toString('binary').indexOf('chcp 65001') !== -1;
}

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('PASS: ' + name); passed++; }
  catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; }
}

const batFiles = findBatFiles(ROOT, []).sort();

if (batFiles.length === 0) {
  console.log('FAIL: .bat ファイルが1件も見つからない（走査ロジックの異常の可能性）');
  failed++;
}

let knownSkipped = 0;
batFiles.forEach(function (file) {
  const rel = path.relative(ROOT, file).split(path.sep).join('/');
  const buf = fs.readFileSync(file);

  if (KNOWN_VIOLATIONS.has(rel)) {
    if (!hasBareLf(buf)) {
      // 直っているのにリストに残っている=リストの掃除漏れを検出
      test('CLEANUP: ' + rel + ' は修正済み。KNOWN_VIOLATIONSから削除すること', function () {
        throw new Error(rel + ' はCRLF化済み。tests/test_bat_encoding.js のリストから削除する');
      });
    } else {
      knownSkipped++;
    }
    return;
  }

  test('CRLF: ' + rel + ' に LF単独行が無い', function () {
    if (hasBareLf(buf)) {
      throw new Error(rel + ' に CRLF化されていない行(LF単独)がある');
    }
  });

  if (hasNonAscii(buf)) {
    test('CHCP: ' + rel + ' は非ASCIIを含むため chcp 65001 を持つ', function () {
      if (!hasChcpUtf8(buf)) {
        throw new Error(rel + ' は非ASCII文字を含むが chcp 65001 が無い（INC-58型の文字化けリスク）');
      }
    });
  }
});

console.log('');
if (knownSkipped > 0) {
  console.log('注意: 既知の違反 ' + knownSkipped + ' 件をスキップ(PC側でcmd実行テストとセットでCRLF化予定=handoff参照)');
}
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
