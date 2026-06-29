/**
 * bluesky-core.js
 * Bluesky（AT Protocol）投稿コア — 完全クライアントサイド（サーバー不要）。
 * bsky.social の XRPC はブラウザ CORS 対応のため、アプリパスワードで直接投稿できる。
 *
 * 公開API（window / CommonJS 両対応）：
 *   buildBlueskyPost({ words, disclosure, link })  … 本文テキスト＋リンクfacet（純粋関数・テスト可）
 *   blueskyPostWithImage({ identifier, appPassword, words, disclosure, link, imageBlob, alt, service })
 *                                                  … ログイン→画像アップロード→投稿（ブラウザ実行）
 *
 * 注意：appPassword は通常パスワードではなく「アプリパスワード」。秘匿情報なので console には出さない。
 */
(function () {
  'use strict';

  var DEFAULT_SERVICE = 'https://bsky.social';

  // UTF-8 バイト長（facet の index は「バイト」オフセットで指定する必要がある）
  function byteLen(s) {
    if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(s).length;
    // フォールバック（TextEncoder 非対応環境用）
    return unescape(encodeURIComponent(s)).length;
  }

  /**
   * 投稿本文とリンク facet を組み立てる純粋関数。
   * 並び：固定文 →（空行）→ 提携文 →（改行）→ リンク
   * リンクは richtext#link facet を付け、Bluesky 上でクリック可能リンクになる。
   * @returns {{ text: string, facets: Array }}
   */
  function buildBlueskyPost(opts) {
    opts = opts || {};
    var words = String(opts.words || '').trim();
    var disclosure = String(opts.disclosure || '').trim();
    var link = String(opts.link || '').trim();

    var blocks = [];
    if (words) blocks.push(words);
    if (disclosure) blocks.push(disclosure);
    var text = blocks.join('\n\n');

    var facets = [];
    if (link) {
      if (text) text += '\n';
      var byteStart = byteLen(text);
      text += link;
      var byteEnd = byteLen(text);
      facets.push({
        index: { byteStart: byteStart, byteEnd: byteEnd },
        features: [{ $type: 'app.bsky.richtext.facet#link', uri: link }]
      });
    }
    return { text: text, facets: facets };
  }

  // ---- 以下はネットワーク呼び出し（ブラウザ／fetch 環境で動作） ----

  function safeJson(res) {
    return res.json().then(function (j) { return j; }, function () { return null; });
  }

  // ログイン（セッション発行）。identifier はハンドル（@なし）またはメール。
  function createSession(service, identifier, appPassword) {
    return fetch(service + '/xrpc/com.atproto.server.createSession', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identifier: identifier, password: appPassword })
    }).then(function (res) {
      if (!res.ok) {
        return safeJson(res).then(function (e) {
          var m = (e && e.message) ? e.message : ('HTTP ' + res.status);
          throw new Error('ログインに失敗しました（' + m + '）');
        });
      }
      return res.json(); // { accessJwt, did, handle, ... }
    });
  }

  // 画像 Blob をアップロードして blob 参照を得る。
  function uploadBlob(service, accessJwt, blob) {
    return fetch(service + '/xrpc/com.atproto.repo.uploadBlob', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + accessJwt,
        'Content-Type': blob.type || 'image/jpeg'
      },
      body: blob
    }).then(function (res) {
      if (!res.ok) {
        return safeJson(res).then(function (e) {
          var m = (e && e.message) ? e.message : ('HTTP ' + res.status);
          throw new Error('画像のアップロードに失敗しました（' + m + '）');
        });
      }
      return res.json(); // { blob: {...} }
    });
  }

  // 投稿レコードを作成。imageRef があれば images embed を付ける。
  function createPost(service, session, payload) {
    var record = {
      $type: 'app.bsky.feed.post',
      text: payload.text || '',
      createdAt: new Date().toISOString(),
      langs: ['ja']
    };
    if (payload.facets && payload.facets.length) record.facets = payload.facets;
    var imageRefs = payload.imageRefs || (payload.imageRef ? [payload.imageRef] : []);
    if (imageRefs.length) {
      record.embed = {
        $type: 'app.bsky.embed.images',
        images: imageRefs.slice(0, 4).map(function (ref, i) { return { alt: (i === 0 ? payload.alt : '') || '', image: ref }; })
      };
    }
    return fetch(service + '/xrpc/com.atproto.repo.createRecord', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + session.accessJwt,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        repo: session.did,
        collection: 'app.bsky.feed.post',
        record: record
      })
    }).then(function (res) {
      if (!res.ok) {
        return safeJson(res).then(function (e) {
          var m = (e && e.message) ? e.message : ('HTTP ' + res.status);
          throw new Error('投稿に失敗しました（' + m + '）');
        });
      }
      return res.json(); // { uri, cid }
    });
  }

  /**
   * 一連の投稿フロー：ログイン → （画像があれば）アップロード → 投稿。
   * @returns Promise<{ uri, cid, handle }>
   */
  function blueskyPostWithImage(o) {
    o = o || {};
    var service = o.service || DEFAULT_SERVICE;
    var ident = String(o.identifier || '').trim().replace(/^@/, '');
    var built = buildBlueskyPost(o);
    var sess;
    return createSession(service, ident, o.appPassword).then(function (s) {
      sess = s;
      if (o.imageBlob) return uploadBlob(service, sess.accessJwt, o.imageBlob);
      return null;
    }).then(function (up) {
      return createPost(service, sess, {
        text: built.text,
        facets: built.facets,
        imageRef: up ? up.blob : null,
        alt: o.alt || ''
      });
    }).then(function (res) {
      // at://did/app.bsky.feed.post/<rkey> から公開URL（共有URL）を組み立てる
      var rkey = String(res.uri || '').split('/').pop();
      var postUrl = (sess.handle && rkey)
        ? ('https://bsky.app/profile/' + sess.handle + '/post/' + rkey)
        : '';
      return { uri: res.uri, cid: res.cid, handle: sess.handle, rkey: rkey, postUrl: postUrl };
    });
  }

  // 自由テキストから URL（#link）とハッシュタグ（#tag）を検出して facets を作る。
  // index は UTF-8 バイトオフセット。タグ範囲は「#」を含み、tag値は「#」を除く。半角#のみ検出。
  function detectFacets(text) {
    text = String(text || '');
    var facets = [], used = [], m;

    // URL → link facet
    var ure = /https?:\/\/[^\s]+/g;
    while ((m = ure.exec(text))) {
      var url = m[0].replace(/[.,;:!?。、！？）)】」』]+$/, '');  // 末尾の句読点・閉じ括弧は含めない
      var s = m.index, e = s + url.length;
      used.push([s, e]);
      facets.push({
        index: { byteStart: byteLen(text.slice(0, s)), byteEnd: byteLen(text.slice(0, e)) },
        features: [{ $type: 'app.bsky.richtext.facet#link', uri: url }]
      });
    }

    // ハッシュタグ → tag facet（行頭 or 空白の直後の半角#のみ。URLと重なる分は除外）
    var tre = /(^|\s)(#[^\s#]+)/g, t;
    while ((t = tre.exec(text))) {
      var hash = t[2].replace(/[.,;:!?。、！？）)】」』]+$/, '');  // 末尾の句読点はタグに含めない
      if (hash.length < 2) continue;  // 「#」だけは除外
      var ts = t.index + t[1].length, te = ts + hash.length;
      var overlap = used.some(function (r) { return ts < r[1] && te > r[0]; });
      if (overlap) continue;
      facets.push({
        index: { byteStart: byteLen(text.slice(0, ts)), byteEnd: byteLen(text.slice(0, te)) },
        features: [{ $type: 'app.bsky.richtext.facet#tag', tag: hash.slice(1) }]
      });
    }

    facets.sort(function (a, b) { return a.index.byteStart - b.index.byteStart; });  // byteStart昇順
    return facets;
  }

  /**
   * 1つの自由テキスト本文をそのまま投稿（改行も維持／本文中のURLは自動でリンク化）。
   * @returns Promise<{ uri, cid, handle, rkey, postUrl }>
   */
  function blueskyPostRaw(o) {
    o = o || {};
    var service = o.service || DEFAULT_SERVICE;
    var ident = String(o.identifier || '').trim().replace(/^@/, '');
    var text = String(o.text || '');
    var sess;
    var blobs = (o.imageBlobs || []).concat(o.imageBlob ? [o.imageBlob] : []).filter(Boolean);
    return createSession(service, ident, o.appPassword).then(function (s) {
      sess = s;
      if (!blobs.length) return [];
      return Promise.all(blobs.slice(0, 4).map(function (b) { return uploadBlob(service, sess.accessJwt, b); }));
    }).then(function (ups) {
      var imageRefs = Array.isArray(ups) ? ups.map(function (u) { return u && u.blob; }).filter(Boolean) : [];
      return createPost(service, sess, { text: text, facets: detectFacets(text), imageRefs: imageRefs, alt: o.alt });
    }).then(function (res) {
      var rkey = String(res.uri || '').split('/').pop();
      var postUrl = (sess.handle && rkey) ? ('https://bsky.app/profile/' + sess.handle + '/post/' + rkey) : '';
      return { uri: res.uri, cid: res.cid, handle: sess.handle, rkey: rkey, postUrl: postUrl };
    });
  }

  /**
   * 資格情報の検証だけを行う（ログインを試すのみ・投稿はしない）。
   * 成功時：{ ok:true, handle, did }、失敗時：reject(Error)。
   */
  function blueskyVerify(o) {
    o = o || {};
    var service = o.service || DEFAULT_SERVICE;
    var ident = String(o.identifier || '').trim().replace(/^@/, '');
    return createSession(service, ident, o.appPassword).then(function (s) {
      return { ok: true, handle: s.handle, did: s.did };
    });
  }

  var api = {
    DEFAULT_SERVICE: DEFAULT_SERVICE,
    buildBlueskyPost: buildBlueskyPost,
    blueskyPostWithImage: blueskyPostWithImage,
    detectFacets: detectFacets,
    blueskyPostRaw: blueskyPostRaw,
    blueskyVerify: blueskyVerify
  };

  if (typeof window !== 'undefined') {
    window.BlueskyCore = api;
    window.buildBlueskyPost = buildBlueskyPost;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})();
