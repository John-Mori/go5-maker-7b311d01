// CI adapter: WorkerのES module実行テストを tests/test_*.js の全件門から起動する。
const { spawnSync } = require('child_process');
const path = require('path');
const target = path.join(__dirname, 'test_drive_savejob.mjs');
const result = spawnSync(process.execPath, [target], { stdio: 'inherit' });
if (result.error) throw result.error;
process.exit(result.status == null ? 1 : result.status);