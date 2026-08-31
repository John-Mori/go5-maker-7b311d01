import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import assert from 'node:assert';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.platform === 'win32' ? 'python' : 'python3';
const script = join(root, 'tests', 'test_ready_comment_pipeline.py');
const r = spawnSync(python, [script], { cwd: root, encoding: 'utf8' });
// CodexのWindows sandboxはNode子プロセスだけEPERMになる。通常ローカル/CIではPython実体を
// 実行し、EPERM環境でも配線自体を静的に検査する(本turnではPython本体も直接実行する)。
if (r.error && r.error.code === 'EPERM') {
  const gen = readFileSync(join(root, 'docs', 'departments', 'product-scout', 'tools', 'candidates_json.py'), 'utf8');
  const vision = readFileSync(join(root, 'scripts', 'teian', 'vision_comments.py'), 'utf8');
  const publish = readFileSync(join(root, 'scripts', 'teian', 'publish_candidates.py'), 'utf8');
  assert.ok(gen.includes('def parse_ready_sync_bundle('));
  assert.ok(gen.includes('"ready_library": ready_library'));
  assert.ok(vision.includes('for key in ("candidates", "ready_library")'));
  assert.ok(vision.includes('c.get("vision_images") or c.get("images")'));
  assert.ok(publish.includes('for c in doc.get("ready_library", [])'));
  console.log('OK: ready comment pipeline wiring (Python child execution blocked by sandbox)');
  process.exit(0);
}
if (r.stdout) process.stdout.write(r.stdout);
if (r.stderr) process.stderr.write(r.stderr);
if (r.status !== 0) process.exit(r.status || 1);
