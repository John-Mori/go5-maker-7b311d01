/**
 * tests/test_bsky_reply_resume.js
 * 子(リプライ)の取りこぼし対策(Chami 2026-10-13 msg 1559263050572369951「リプライができてない」)を固定する。
 *   親を出した瞬間に台帳へ「この親へ子を出す」を書き、子が出たら消す。待ちの間にタブが落ちても、
 *   次に開いた時に子だけ出し直す。親へ自分の返信が既に付いていれば出さない(二重の子を作らない)。
 * bluesky-core.js の本物と、bluesky.js の台帳ブロックの本物を、通信だけ偽物にして実行する。
 * 実行: node tests/test_bsky_reply_resume.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const read = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8');
let fails = 0;
function eq(a, b, m) { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? '  ok   ' : '  FAIL ') + m + (ok ? '' : ' got=' + JSON.stringify(a) + ' want=' + JSON.stringify(b))); if (!ok) fails++; }

// ---- 偽の Bluesky(通信だけ偽物) ----
let calls = []; let failReplies = 0; let threadReplies = [];
function res(ok, body) { return Promise.resolve({ ok: ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) }); }
global.fetch = function (url, init) {
  const u = String(url);
  if (/createSession/.test(u)) { calls.push('session'); return res(true, { accessJwt: 'J', did: 'did:x', handle: 'me.bsky.social' }); }
  if (/uploadBlob/.test(u)) { calls.push('upload'); return res(true, { blob: { ref: 'b' } }); }
  if (/createRecord/.test(u)) {
    const rec = JSON.parse(init.body).record;
    if (rec.reply) {
      calls.push('reply');
      if (failReplies > 0) { failReplies--; return res(false, { message: 'boom' }); }
      return res(true, { uri: 'at://did:x/app.bsky.feed.post/child1', cid: 'c2' });
    }
    calls.push('parent');
    return res(true, { uri: 'at://did:x/app.bsky.feed.post/par1', cid: 'c1' });
  }
  if (/getPostThread/.test(u)) { calls.push('thread'); return res(true, { thread: { replies: threadReplies } }); }
  if (/bsky-reply-continue/.test(u)) return Promise.resolve({ blob: () => Promise.resolve({ type: 'image/jpeg' }) });
  throw new Error('unexpected ' + u);
};
const realSetTimeout = setTimeout;
global.setTimeout = (fn) => realSetTimeout(fn, 0); // 待ちは0秒で回す(分岐は本物のまま)

const core = require('../js/bluesky-core.js');

(async function () {
  console.log('--- core: 親が出た瞬間に知らせる / 子だけ失敗したら親の在りかを付けて返す ---');
  let posted = null;
  failReplies = 2;
  let err = null;
  await core.blueskyPostThread({ identifier: 'me', appPassword: 'pw', parentText: '親', replyText: '続きはこちら\nhttps://x', onParentPosted: (p, ms) => { posted = { uri: p.uri, ms: typeof ms }; } }).catch((e) => { err = e; });
  eq(posted, { uri: 'at://did:x/app.bsky.feed.post/par1', ms: 'number' }, 'onParentPosted は待ちの前に親のuriで呼ばれる');
  eq([!!err, err && err.parentOut && err.parentOut.uri], [true, 'at://did:x/app.bsky.feed.post/par1'], '子が2回失敗=親の在りか付きで落ちる');
  eq(calls.filter((c) => c === 'reply').length, 2, '子は1回だけ再試行する');

  calls = []; failReplies = 1;
  const okRes = await core.blueskyPostThread({ identifier: 'me', appPassword: 'pw', parentText: '親', replyText: 'r' });
  eq(okRes.reply.postUrl, 'https://bsky.app/profile/me.bsky.social/post/child1', '一過性の失敗1回なら再試行で子が出る');

  console.log('--- bluesky.js: 取りこぼし台帳から子だけ出し直す ---');
  const bs = read('js/bluesky.js');
  const s = bs.indexOf('  var BSKY_PENDING_KEY');
  const e = bs.indexOf('  // ドラフト投稿一続き(柱分け)');
  const ls = {}; const events = []; const listeners = {};
  const env = {
    localStorage: { getItem: (k) => (k in ls ? ls[k] : null), setItem: (k, v) => { ls[k] = String(v); } },
    window: { BlueskyCore: core, dispatchEvent: (ev) => events.push(ev.detail), addEventListener: (n, f) => { listeners[n] = f; } },
    document: { addEventListener: (n, f) => { listeners[n] = f; }, visibilityState: 'visible' },
    CustomEvent: function (n, o) { this.detail = o.detail; },
    handleOfAcct_: () => 'me.bsky.social', pkOf_: (k, a) => k + '__' + a,
    replyImageBlob_: () => Promise.resolve({ type: 'image/jpeg' }),
  };
  ls['bsky_app_pw__acc3'] = 'pw';
  const M = new Function(...Object.keys(env), bs.slice(s, e) + '\nreturn { addPendingReply_, pendingJobOf_, resumePendingReplies_, loadPendingReplies_, inflight: _bskyReplyInflight };')(...Object.values(env));
  const parentOut = { uri: 'at://did:x/app.bsky.feed.post/par9', cid: 'c9', postUrl: 'https://bsky.app/profile/me.bsky.social/post/par9', handle: 'me.bsky.social' };
  M.addPendingReply_(M.pendingJobOf_(parentOut, 'acc3', '続きはこちら\nhttps://x', 0, { kind: 'draft', draftId: 'D1' }));
  eq(Object.keys(JSON.parse(ls['bsky_pending_reply'])[0]).some((k) => /pw|pass|jwt/i.test(k)), false, '台帳に資格情報を書かない');
  eq(typeof listeners.visibilitychange, 'function', '画面へ戻った時に拾う');

  calls = []; threadReplies = []; failReplies = 0;
  M.inflight[parentOut.uri] = 1;
  eq(await M.resumePendingReplies_(), 0, '同じ画面で待ち中(inflight)の子は横取りしない');
  delete M.inflight[parentOut.uri];
  eq(await M.resumePendingReplies_(), 1, 'タブが落ちた後=子だけ出し直す');
  eq(calls, ['thread', 'session', 'upload', 'reply'], '出す前に親へ自分の返信が無いか確かめる');
  eq(M.loadPendingReplies_().length, 0, '出せたら台帳から消える');
  eq([events.length, events[0] && events[0].job.draftId, events[0] && events[0].reply.postUrl], [1, 'D1', 'https://bsky.app/profile/me.bsky.social/post/child1'], 'ドラフトへ書き戻す合図を出す');

  calls = []; threadReplies = [{ post: { uri: 'at://did:x/app.bsky.feed.post/old', cid: 'c', author: { handle: 'me.bsky.social' } } }];
  M.addPendingReply_(M.pendingJobOf_(parentOut, 'acc3', 'r', 0, { kind: 'draft', draftId: 'D1' }));
  eq(await M.resumePendingReplies_(), 1, '既に自分の返信が付いていれば済み扱い');
  eq(calls.indexOf('reply'), -1, 'その時は子を二重に出さない');

  calls = []; threadReplies = []; failReplies = 99;
  M.addPendingReply_(M.pendingJobOf_(parentOut, 'acc3', 'r', 0, {}));
  await M.resumePendingReplies_();
  eq([M.loadPendingReplies_().length, M.loadPendingReplies_()[0].tries], [1, 1], '失敗したら台帳に残して回数を数える');

  console.log('--- 配線 ---');
  eq((bs.match(/onParentPosted: function \(p, ms\) \{ _bskyReplyInflight\[p\.uri\] = 1; addPendingReply_/g) || []).length, 2, 'ドラフト投稿と🧵一括投稿の両方で台帳へ書く');
  eq((bs.match(/dropPendingReply_\(res\.parent\.uri\)/g) || []).length, 2, '両方とも子が出たら台帳から消す');
  const st = read('js/stock.js');
  eq(/draftId: meta\.id/.test(st) && /'go5:bsky-reply-resumed'/.test(st), true, 'ドラフトIDを渡し、出し直しをドラフト/履歴へ書き戻す');
  eq(/"bsky_pending_reply": \{ "decision": "local"/.test(read('scripts/sync_decisions.json')), true, '台帳は端末ローカル(同期すると二重に出しうる)');
  if (fails) { console.log(fails + ' FAIL'); process.exit(1); }
  console.log('all ok');
})();
