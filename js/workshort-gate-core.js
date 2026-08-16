/**
 * workshort-gate-core.js — 投稿完了(ドラフト→投稿履歴)の直前に、導線2「作品クリック計測用の短縮URL」の
 *   非同期発番(link-worker往復)が着地するのを短時間だけ待つべきか、もう記録してよいかを判定する純粋関数。
 *
 * ★背景(REQ-65c7897f2f 再発2026-08-16)：ドラフトの投稿完了は handleCompleteOk_ が
 *   go5_draft_post_<id>.workShortUrl を"同期で1回読むだけ"。発番は openPostModal_ が非同期で蹴る
 *   (mintDraftWorkShort_)ため、発番が着地する前に投稿完了を押すと欄が空のまま履歴へ確定する競合が
 *   残っていた(過去の恒久対策=発番結果の localStorage 保存、は着地タイミングまでは揃えていなかった)。
 *   ここで「待つ/記録する」の判断だけを純粋関数として切り出し、CIで実行して固定する。
 *
 * 判定(引数: 保存済みドラフト投稿データ sv・当該メタ meta・経過ms・上限ms):
 *   'record' … もう記録してよい。次のいずれか。
 *     ・上限時間を過ぎた(待っても取れない→完了はブロックしない=従来挙動へフォールスルー)
 *     ・sv.workShortUrl が着地済み(値が入る)
 *     ・作品URL/アフィリンクが無い=発番対象が無い(待っても永遠に来ない)
 *   'wait'   … 発番の着地を待つ(上記以外)。
 */
(function (root) {
  'use strict';

  function step(sv, meta, elapsedMs, maxMs) {
    if (!(elapsedMs < maxMs)) return 'record'; // 上限到達 or maxMs不正(NaN等)は待たず記録
    try { if (sv && String(sv.workShortUrl || '').trim()) return 'record'; } catch (e) {}
    var aff = '';
    try { aff = (meta && ((meta.affiliateUrl || '').trim() || (meta.workUrl || '').trim())) || ''; } catch (e) {}
    if (!aff) return 'record'; // 発番対象なし=待つ意味がない
    return 'wait';
  }

  var api = { step: step };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.Go5WorkShortGate = api;
})(typeof window !== 'undefined' ? window : this);
