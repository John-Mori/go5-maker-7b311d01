/**
 * verify-core.js — Phase4 Bluesky検証KPIの純粋関数。(テスト可)
 * Bluesky公開API(public.api.bsky.app)は未認証・CORSでエンゲージメントを取得できる。
 *   buildGetPostsUrl(uris) … getPosts のURL(最大25件)
 *   parseEngagement(json)  … uri→{like,repost,reply,quote}
 *   postedSlotsFromState(state) … 共有ストアから「公開済＋post_uri/url」スロットを新しい順に
 */
(function (global) {
  'use strict';
  var PUBLIC_API = 'https://public.api.bsky.app';

  function buildGetPostsUrl(uris) {
    var list = (uris || []).filter(Boolean).slice(0, 25);
    return PUBLIC_API + '/xrpc/app.bsky.feed.getPosts?' +
      list.map(function (u) { return 'uris=' + encodeURIComponent(u); }).join('&');
  }

  function parseEngagement(json) {
    var out = {};
    var posts = (json && json.posts) || [];
    posts.forEach(function (p) {
      if (!p || !p.uri) return;
      out[p.uri] = {
        like: p.likeCount || 0, repost: p.repostCount || 0,
        reply: p.replyCount || 0, quote: p.quoteCount || 0
      };
    });
    return out;
  }

  function postedSlotsFromState(state) {
    var sd = (state && state.slotData) || {};
    return Object.keys(sd).map(function (k) { return sd[k]; })
      .filter(function (s) { return s && s.status === '公開済' && (s.post_uri || s.post_url); })
      .sort(function (a, b) {
        return (b.date || '').localeCompare(a.date || '') || ((b.slot_index || 0) - (a.slot_index || 0));
      });
  }

  var api = {
    PUBLIC_API: PUBLIC_API,
    buildGetPostsUrl: buildGetPostsUrl,
    parseEngagement: parseEngagement,
    postedSlotsFromState: postedSlotsFromState
  };
  if (typeof window !== 'undefined') global.VerifyCore = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
