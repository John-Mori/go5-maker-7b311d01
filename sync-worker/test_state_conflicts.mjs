import assert from 'node:assert/strict';
import { memorySync } from '../tests/helpers/sync-worker.cjs';

const server = memorySync();
function req(path, body) {
  return new Request('https://sync.example.test/api/' + path, {
    method: body ? 'POST' : 'GET', headers: { 'X-Sync-Token': 'test-only' },
    body: body ? JSON.stringify(body) : undefined
  });
}
async function push(baseVersion, name) {
  const r = await server.fetch(req('push', { baseVersion, blob: JSON.stringify({ ls: { name }, idb: {} }) }));
  return r.json();
}
let pass = 0, fail = 0;
async function check(name, fn) {
  try { await fn(); pass++; console.log('PASS ' + name); }
  catch (e) { fail++; console.error('FAIL ' + name + ': ' + e.message); }
}
await check('空のR2へ同時pushしても成功は1件だけ', async () => {
  const results = await Promise.all([push(0, 'A'), push(0, 'B')]);
  assert.equal(results.filter(r => r.ok).length, 1);
  assert.equal(results.filter(r => r.conflict).length, 1);
});
await check('同じversionを読んだ2台のpushは競合として返す', async () => {
  const version = server.state().version;
  const results = await Promise.all([push(version, 'A2'), push(version, 'B2')]);
  assert.equal(results.filter(r => r.ok).length, 1);
  assert.equal(results.filter(r => r.conflict).length, 1);
});
await check('R2読取障害をemptyとして返さず、旧KVへも巻き戻さない', async () => {
  server.r2.failRead = true;
  server.env.SYNC = { get: async () => 'old-KV' };
  const r = await server.fetch(req('pull'));
  assert.equal(r.status, 503);
  assert.equal((await r.json()).error, 'state_unavailable');
});
await check('R2読取障害中のpushで既存stateを上書きしない', async () => {
  const before = JSON.stringify(server.state());
  const r = await server.fetch(req('push', { baseVersion: 0, blob: '{}' }));
  assert.equal(r.status, 503);
  assert.equal(JSON.stringify(server.state()), before);
});
console.log(`${pass} passed, ${fail} failed`);
if (fail) process.exitCode = 1;
