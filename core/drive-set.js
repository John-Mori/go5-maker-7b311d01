(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Go5DriveSet = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Drive の保存完了は「動画がある」だけではない。動画・完成プレビュー・元画像の3種類が
  // 同じ作品フォルダに揃った時だけ complete とする。folder_state の null/通信失敗は未完了。
  function normalize(state) {
    state = state && typeof state === 'object' ? state : {};
    return {
      video: state.saved === true || state.hasVideo === true,
      preview: state.hasPreview === true,
      source: state.hasSrc === true || state.hasSource === true
    };
  }
  function isComplete(state) {
    var s = normalize(state);
    return s.video && s.preview && s.source;
  }
  function missing(state) {
    var s = normalize(state), out = [];
    if (!s.video) out.push('video');
    if (!s.preview) out.push('preview');
    if (!s.source) out.push('source');
    return out;
  }

  return { normalize: normalize, isComplete: isComplete, missing: missing };
}));