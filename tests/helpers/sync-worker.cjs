// Worker本体を実行し、保存先だけメモリへ差し替える。実トークン・本番通信は使わない。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function memorySync() {
  const source = fs.readFileSync(path.join(__dirname, '../../sync-worker/src/index.js'), 'utf8');
  const context = { URL, Request, Response, Headers, Blob, Uint8Array, ArrayBuffer, TextEncoder, TextDecoder, console };
  vm.runInNewContext(source.replace('export default {', 'globalThis.worker = {'), context);
  const values = new Map();
  let revision = 0;
  const r2 = {
    failRead: false,
    async get(key) {
      if (r2.failRead) throw new Error('simulated R2 outage');
      const rec = values.get(key);
      if (!rec) return null;
      return { etag: rec.etag, httpEtag: '"' + rec.etag + '"', body: rec.value,
        text: async () => String(rec.value), writeHttpMetadata: h => h.set('Content-Type', rec.type) };
    },
    async head(key) { return values.has(key) ? { key } : null; },
    async put(key, value, opts = {}) {
      const old = values.get(key), c = opts.onlyIf || {};
      if (c.etagMatches && (!old || old.etag !== c.etagMatches)) return null;
      if (c.etagDoesNotMatch === '*' && old) return null;
      const etag = String(++revision);
      values.set(key, { value, etag, type: opts.httpMetadata?.contentType || 'application/octet-stream' });
      return { etag };
    }
  };
  const env = { SYNC_IMAGES: r2, SYNC_TOKEN: 'test-only', ALLOWED_ORIGINS: '*' };
  return { env, r2, values,
    fetch: req => context.worker.fetch(req, env, {}),
    state: () => {
      const rec = values.get('state/sync-v1.json');
      return rec ? JSON.parse(rec.value) : null;
    }
  };
}

module.exports = { memorySync };
