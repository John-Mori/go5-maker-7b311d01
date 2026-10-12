/* CI実行対象(.js): blueskyPostThreadのリプライに画像添付ができること(2026-10-12 Chami指定・
   msg 1559121504128471086「Blueskyの場合は続きはこちらというリプ欄と一緒にこの画像を毎回添付すること」)
   をネットワークをモックしたNodeから検証する。fetch呼び出し順: createSession → (親uploadBlob) →
   親createRecord → (待機) → リプライuploadBlob → リプライcreateRecord。 */
const assert = require('assert');
const { blueskyPostThread } = require('../js/bluesky-core.js');

(async function () {
  const calls = [];
  global.fetch = async function (url, init) {
    calls.push({ url: String(url), init: init });
    if (String(url).indexOf('com.atproto.server.createSession') >= 0) {
      return { ok: true, json: async () => ({ accessJwt: 'JWT', did: 'did:plc:test', handle: 'test.bsky.social' }) };
    }
    if (String(url).indexOf('com.atproto.repo.uploadBlob') >= 0) {
      return { ok: true, json: async () => ({ blob: { $type: 'blob', ref: { $link: 'cid-' + calls.length }, mimeType: 'image/jpeg', size: 123 } }) };
    }
    if (String(url).indexOf('com.atproto.repo.createRecord') >= 0) {
      const body = JSON.parse(init.body);
      return { ok: true, json: async () => ({ uri: 'at://did:plc:test/app.bsky.feed.post/rkey-' + calls.length, cid: 'cid-post-' + calls.length }), _record: body.record };
    }
    throw new Error('未モックのURL: ' + url);
  };

  const replyBlob = { type: 'image/jpeg', size: 419946 };
  const result = await blueskyPostThread({
    identifier: 'test.bsky.social',
    appPassword: 'app-pass',
    parentText: '固定文のテスト本文',
    replyText: '続きはこちら\nhttps://5mgl.com/abcd',
    replyImageBlob: replyBlob,
    delayMinMs: 0,
    delayMaxMs: 0
  });

  // ★呼び出し順の確認: createSession → 親createRecord(画像なし) → リプライuploadBlob → リプライcreateRecord
  const urls = calls.map(function (c) { return c.url; });
  assert.ok(urls[0].indexOf('createSession') >= 0, '1件目はログイン');
  const createRecordCalls = calls.filter(function (c) { return c.url.indexOf('createRecord') >= 0; });
  assert.strictEqual(createRecordCalls.length, 2, '親とリプライで2回createRecordが呼ばれる');

  const parentRecord = JSON.parse(createRecordCalls[0].init.body).record;
  const replyRecord = JSON.parse(createRecordCalls[1].init.body).record;

  // 親投稿には画像を渡していない(imageBlobを指定していない)ので embed は付かない
  assert.strictEqual(parentRecord.embed, undefined, '親には画像を渡していないのでembedなし');

  // リプライ本文に「続きはこちら」が含まれる
  assert.ok(replyRecord.text.indexOf('続きはこちら') >= 0, 'リプライ本文に「続きはこちら」が含まれる');

  // リプライに画像embedが付き、1枚添付されている(alt は既存仕様により常に空文字)
  assert.ok(replyRecord.embed, 'リプライにembedが付く');
  assert.strictEqual(replyRecord.embed['$type'], 'app.bsky.embed.images');
  assert.strictEqual(replyRecord.embed.images.length, 1, '画像が1枚添付される');
  assert.strictEqual(replyRecord.embed.images[0].alt, '', 'altは既存仕様により常に空');

  // uploadBlobが呼ばれている(リプライ画像のアップロード)
  const uploadCalls = calls.filter(function (c) { return c.url.indexOf('uploadBlob') >= 0; });
  assert.strictEqual(uploadCalls.length, 1, 'リプライ画像のuploadBlobが1回呼ばれる');

  // リプライがreply(root/parent)参照を持つ
  assert.ok(replyRecord.reply && replyRecord.reply.root && replyRecord.reply.parent, 'リプライにroot/parent参照がある');

  assert.ok(result.reply && result.reply.uri, 'resultにreply.uriが含まれる');

  console.log('PASS: blueskyPostThreadのリプライに「続きはこちら」本文+画像1枚が添付される');
})().catch(function (e) {
  console.error(e);
  process.exit(1);
});
