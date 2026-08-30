// scripts/run_unit_tests.mjs — ローカルの `npm run test:unit` を CI と一致させる。
//
//   これまで package.json の test:unit は tests/ の一部(4本)しか列挙しておらず、
//   CI(smoke.yml)は `tests/test_*.js` を全部回す=食い違いがあった。さらに tests/test_*.mjs
//   (bump_orphan / candidate_fetch / drive_r2_bind / drive_savejob)は CI の .js ループにも
//   test:unit にも載らず、どちらでも一度も走っていなかった(2026-08-30 発見・改修α朝の一手)。
//   ＝ローカルで緑でも push 後に初めて赤になる/そもそも検査されない、を無くす。
//   このランナーは tests/test_*.js と tests/test_*.mjs を全部実行し、1本でも失敗したら exit 1。
import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const testsDir = join(root, 'tests');
const files = readdirSync(testsDir)
  .filter((f) => /^test_.*\.(js|mjs)$/.test(f))
  .sort();

let fail = 0;
for (const f of files) {
  process.stdout.write(`── tests/${f} ──\n`);
  const r = spawnSync(process.execPath, [join(testsDir, f)], { stdio: 'inherit' });
  if (r.status !== 0) fail = 1;
}
if (fail) {
  console.error(`\nFAIL: いずれかの単体テストが失敗しました(上のログ参照)`);
  process.exit(1);
}
console.log(`\nOK: 全 ${files.length} 本の単体テストが緑`);
