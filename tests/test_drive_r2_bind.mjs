/**
 * tests/test_drive_r2_bind.mjs — fetchR2Bytes(動画バイトのR2取得)の「判定と分岐」を本物の関数を
 *   import して実行で固定する(ソース文字列一致ではない)。
 *
 * 背景(2026-08-18〜19・15コミットを費やしたDrDrive保存の真因):
 *   go5-drive-saver → go5-sync.workers.dev は「同一アカウント workers.dev 間の fetch」で、外部curlでは
 *   GET 200/8.7MB が返る同一URLでも Worker からは 404 を返す(Cloudflareのルーティングの落とし穴)。
 *   → r2_video_missing で静死し、投稿完了は成功なのにDriveに何も残らない=沈黙成功が15回再発した。
 *   恒久解=同じR2バケット(go5-sync-images)を drive-worker へ直バインド(env.SYNC_IMAGES)し in-process 直読み。
 *
 * ここで固定する不変条件(次世代が黙って壊せないように):
 *   1. 直バインドが在る時は .get() で読み、壊れたHTTP fetch を一切呼ばない(早期returnで枝を分ける)。
 *   2. 直バインドが権威=バケットに無ければ null を返し、壊れたHTTP経路へフォールバックしない(沈黙成功の再来を断つ)。
 *   3. 直バインドが無い環境でだけ従来の公開HTTP GET を使う(別アカウント運用の互換)。
 * 「外へ出る手」= R2 binding.get と global fetch は偽物にし、判定と分岐は本物のまま実行する。
 */
import assert from 'assert';
import { fetchR2Bytes } from '../drive-worker/src/index.js';

const KEY = 'a'.repeat(64);
let fails = 0;
function ok(name) { console.log('  PASS ' + name); }
function ng(name, e) { fails++; console.log('  FAIL ' + name + ' — ' + (e && e.message || e)); }

// global fetch を「呼ばれたら記録するスパイ」に差し替える(壊れたHTTP経路に落ちたら検知するため)
function withFetchSpy(status, body, fn) {
  const orig = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: () => 'video/mp4' },
      arrayBuffer: async () => new TextEncoder().encode(body || '').buffer,
    };
  };
  return Promise.resolve(fn(calls)).finally(() => { globalThis.fetch = orig; });
}

function makeBinding(map) {
  return {
    get: async (k) => {
      if (!(k in map)) return null;
      const bytes = new TextEncoder().encode(map[k]);
      return { arrayBuffer: async () => bytes.buffer, httpMetadata: { contentType: 'video/mp4' } };
    },
  };
}

// --- T-1 直バインド在り＋バケットに在る → .get()で読む・fetchは一度も呼ばない ---
await withFetchSpy(200, 'HTTP_SHOULD_NOT_BE_USED', async (calls) => {
  try {
    const env = { SYNC_IMAGES: makeBinding({ [KEY]: 'REAL_VIDEO_BYTES' }) };
    const r = await fetchR2Bytes(env, 'https://sync.example.dev', KEY, []);
    assert.ok(r && r.buf && r.buf.byteLength > 0, '直バインドでバイトが返る');
    assert.strictEqual(new TextDecoder().decode(r.buf), 'REAL_VIDEO_BYTES');
    assert.strictEqual(r.mime, 'video/mp4');
    assert.strictEqual(calls.length, 0, '直バインド在り時に壊れたHTTP fetch を呼んではいけない');
    ok('T-1 直バインド在り＋在庫あり: .getで読みfetchを呼ばない');
  } catch (e) { ng('T-1', e); }
});

// --- T-2 直バインド在り＋バケットに無い → nullを返す・壊れたHTTP経路へフォールバックしない(権威) ---
await withFetchSpy(200, 'HTTP_FALLBACK_MUST_NOT_HAPPEN', async (calls) => {
  try {
    const env = { SYNC_IMAGES: makeBinding({}) }; // バケット空
    const r = await fetchR2Bytes(env, 'https://sync.example.dev', KEY, []);
    assert.strictEqual(r, null, 'バインドが権威=無ければnull');
    assert.strictEqual(calls.length, 0, '直バインドで空でもHTTPへ倒してはいけない(沈黙成功の再来を断つ)');
    ok('T-2 直バインド在り＋在庫なし: nullを返しHTTPへフォールバックしない');
  } catch (e) { ng('T-2', e); }
});

// --- T-3 直バインド無し(別アカウント運用) → 公開HTTP GET を使う ---
await withFetchSpy(200, 'FALLBACK_HTTP_BYTES', async (calls) => {
  try {
    const env = {}; // SYNC_IMAGES バインド無し
    const r = await fetchR2Bytes(env, 'https://sync.example.dev', KEY, []);
    assert.ok(r && r.buf && r.buf.byteLength > 0, '直バインド不在時はHTTPで取得できる');
    assert.strictEqual(new TextDecoder().decode(r.buf), 'FALLBACK_HTTP_BYTES');
    assert.strictEqual(calls.length, 1, '直バインド不在時のみHTTPを1回呼ぶ');
    assert.ok(calls[0].indexOf('/img/' + KEY) >= 0, 'HTTPは r2Base/img/<key> を叩く');
    ok('T-3 直バインド無し: 公開HTTP GET へフォールバック');
  } catch (e) { ng('T-3', e); }
});

console.log(fails === 0 ? '\nALL PASS (test_drive_r2_bind)' : `\n${fails} FAIL`);
process.exit(fails === 0 ? 0 : 1);
