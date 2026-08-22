/**
 * tests/test_bump_orphan.mjs — bump.mjs の「孤児検出」(2026-08-23 案2 / commit 24146de)の回帰網。
 *
 * 背景(AD研究室=モドリッチ 依頼 msg1540756045889015880):
 *   孤児検出は稼働しているが、それを突く回帰テストが commit されていなかった=
 *   将来 bump.mjs をリファクタして検出を壊しても、実際に孤児HTMLが現れるまで誰も気づかない
 *   (共通規律§3「ソースの文字列一致は検査ではなく保険/初発火が初検証に戻る」)。
 *
 * 設計(test-must-fail / SKILL 準拠):
 *   ・判定と分岐は本物のまま=**実物の scripts/bump.mjs をそのままコピーして実行**する
 *     (テストは毎回ライブのソースを読むので、bump.mjs を書き換えれば追従して落ちる)。
 *   ・外へ出る手だけ隔離=ROOT は import.meta.url 起点なので、コピー先を tmp/scripts/ に置けば
 *     ROOT が tmp を指す。直下の配信面(実リポの?v=)には一切触れない。--check で書き込みもしない。
 *   ・must-fail の実証を**テスト内に埋め込む**= 検出枝 `if (orphans.length)` を `if (false)` に
 *     潰したコピーでは、同じ孤児入力でも exit 8 が返らないことを assert(C-3)。
 *     =case A の exit 8 が「たまたま」ではなく孤児検出枝から来ていることを実行で示す。
 */
import assert from 'node:assert';
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REAL_BUMP = join(HERE, '..', 'scripts', 'bump.mjs');
const SRC = readFileSync(REAL_BUMP, 'utf8');

// ★アンカー検査: 検出枝の入口が居ることを先に確かめる。無ければ誰かがリファクタした=
//   このテストの前提が崩れている合図なので、静かにPASSさせず落とす(空PASS防止)。
const MUT_ANCHOR = 'if (orphans.length) {';
assert.ok(
  SRC.includes(MUT_ANCHOR),
  `検出枝のアンカー "${MUT_ANCHOR}" が bump.mjs に無い=リファクタされた。テストを見直せ。`,
);

let fails = 0;
const ok = (n) => console.log('  PASS ' + n);
const ng = (n, e) => { fails++; console.log('  FAIL ' + n + ' — ' + (e && e.message || e)); };

/**
 * tmp に scripts/bump.mjs(= bumpSrc)を置き、直下に files を書いて bump.mjs --check を実行。
 * files = { 'index.html': '<...?v=7...>', ... }。戻り値 = { status, stdout, stderr }。
 * 実行後、tmp は必ず削除(直下の配信面を汚さない)。
 */
function runBump(bumpSrc, files) {
  const root = mkdtempSync(join(tmpdir(), 'bumporphan-'));
  try {
    const sdir = join(root, 'scripts');
    mkdirSync(sdir);
    writeFileSync(join(sdir, 'bump.mjs'), bumpSrc);
    for (const [name, body] of Object.entries(files)) {
      writeFileSync(join(root, name), body);
    }
    const r = spawnSync(process.execPath, [join(sdir, 'bump.mjs'), '--check'], { encoding: 'utf8' });
    return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

// index.html は TARGETS の正規メンバー / stock 等は使わず最小構成。孤児 = TARGETS外なのに?v=持ち。
const ORPHAN_FILES = {
  'index.html': '<script src="app.js?v=7"></script>',
  'orphan.html': '<script src="new.js?v=7"></script>', // ← TARGETS外・?v=持ち = 孤児
  'noref.html': '<h1>版参照なし</h1>',                  // ← ?v=無し = 無視されるべき
};
const CLEAN_FILES = {
  'index.html': '<script src="app.js?v=7"></script>',
  'noref.html': '<h1>版参照なし</h1>',
};

// C-1: 孤児が居たら exit 8 で止まる(門が鳴る)
try {
  const r = runBump(SRC, ORPHAN_FILES);
  assert.strictEqual(r.status, 8, `孤児在りで exit 8 を期待したが ${r.status} / stderr=${r.stderr.trim()}`);
  assert.ok(/orphan\.html/.test(r.stderr), '停止メッセージに孤児名 orphan.html が出るべき');
  ok('C-1 孤児HTML有り → exit 8(検出メッセージに孤児名)');
} catch (e) { ng('C-1', e); }

// C-2: 孤児を外せば通常フロー(--check は exit 0・v=7 単一)
try {
  const r = runBump(SRC, CLEAN_FILES);
  assert.strictEqual(r.status, 0, `孤児無しで exit 0 を期待したが ${r.status} / stderr=${r.stderr.trim()}`);
  assert.ok(/v=7\b/.test(r.stdout), `--check が v=7 を報告するべき / stdout=${r.stdout.trim()}`);
  ok('C-2 孤児HTML無し → exit 0(通常フロー・v=7単一)');
} catch (e) { ng('C-2', e); }

// C-3: ★must-fail 実証(テスト内蔵)= 検出枝を潰したコピーでは、同じ孤児入力でも exit 8 が返らない。
//   → C-1 の exit 8 が孤児検出枝から来ている証明(空PASS/偶然のPASSでないことの担保)。
try {
  const mutated = SRC.replace(MUT_ANCHOR, 'if (false) {');
  assert.notStrictEqual(mutated, SRC, '変異が当たらなかった(アンカー不一致)');
  const r = runBump(mutated, ORPHAN_FILES);
  assert.notStrictEqual(r.status, 8, `検出枝を潰したのに exit 8 が返った=exit 8 の出所が孤児検出でない疑い / status=${r.status}`);
  assert.strictEqual(r.status, 0, `検出枝を潰せば孤児入力でも通常フロー(exit 0)のはず / status=${r.status} stderr=${r.stderr.trim()}`);
  ok('C-3 検出枝を if(false) に潰す → exit 8 が消える(exit 8 の出所=孤児検出 を実行で証明)');
} catch (e) { ng('C-3', e); }

if (fails) { console.log('\n' + fails + ' test(s) FAILED'); process.exit(1); }
console.log('\nAll bump orphan-detection tests passed.');
