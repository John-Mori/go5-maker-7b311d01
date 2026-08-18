/* posted-source.js — 「投稿済み」判定の読み取り専用ソース(分割ページ用の共有土台)。
 *
 * なぜ要るか(2026-08-11 Chami「候補タブ内の投稿履歴のつながりが消えて投稿済みの演出が出なくなった」):
 *   候補ページを独立HTML(KouhoLists.html)へ分割(809ea89)した際、window.Go5PostedItems を定義する
 *   bluesky.js が候補ページには積まれていなかった。candidates.js の postedIndexFor_ は
 *     if (typeof window.Go5PostedItems !== 'function') return {};
 *   で早期に空を返すため、投稿履歴との照合が全て外れ=投稿済みpillが一切光らなくなっていた。
 *   index.html は bluesky.js を積むので無事=分割ページだけが壊れていた。
 *
 * 設計:
 *   Go5PostedItems / Go5PostedWorkUrls は localStorage を読むだけの純粋なリーダー(DOM・app.js非依存)。
 *   bluesky.js 内の同名定義から、その読み取り部分だけを切り出した。★挙動は bluesky.js と一致させること。
 *   既に定義済み(=bluesky.js を積む index.html)なら上書きしない=二重定義の衝突を避ける。
 *   依存は core/account.js(Go5Acct.current) のみ。候補ページはこれを先に読み込む。
 */
(function () {
  'use strict';
  // 既に本家(bluesky.js)が供給済みなら何もしない。分割ページ(bluesky.js無し)でのみ定義する。
  if (typeof window.Go5PostedItems === 'function') return;

  function acctId() {
    try { if (window.Go5Acct) return window.Go5Acct.current(); } catch (e) {}
    return (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1');
  }
  function histKeyFor_(a) { return 'short_hist__' + (a || acctId()); }
  // 「中身が空」と「読めなかった(壊れている)」を区別しつつ、ここは読み取り専用なので壊れていても [] を返すだけ。
  function histBrokenMap_() { return histBrokenMap_._ || (histBrokenMap_._ = {}); }
  function histBrokenSet_(k, v) { histBrokenMap_()[k] = v; }
  function histLoadFor_(a) {
    var k = histKeyFor_(a), raw = null;
    // ★履歴のIDB正本(Go5Hist)が積まれているページでは、そこを読む(直LSはミラーを迂回=古い/消えた行を出すA-1退行)。未ロードのページはLS直読み。
    if (window.Go5Hist) { try { var mv = window.Go5Hist.read(k); if (Array.isArray(mv)) { histBrokenSet_(k, null); return mv; } } catch (e) {} }
    try { raw = localStorage.getItem(k); } catch (e) { histBrokenSet_(k, 'localStorage読み取り不可'); return []; }
    if (raw == null || raw === '') { histBrokenSet_(k, null); return []; }
    try {
      var v = JSON.parse(raw);
      if (!Array.isArray(v)) { histBrokenSet_(k, '配列ではない'); return []; }
      histBrokenSet_(k, null);
      return v;
    } catch (e) {
      histBrokenSet_(k, 'JSONが壊れている(' + raw.length + '文字)');
      return [];
    }
  }
  // 指定アカウントで投稿済みの作品URL一覧。(候補タブの「投稿済み」判定用・重複投稿=P0-3の防止に使う)
  try { window.Go5PostedWorkUrls = function (a) { try { return histLoadFor_(a || acctId()).map(function (h) { return (h && h.workUrl) || ''; }).filter(Boolean); } catch (e) { return []; } }; } catch (e) {}
  // 指定アカウントの投稿履歴アイテム一覧。(候補タブの投稿詳細モーダル用＝いつ/何で投稿したか)
  //   短縮URL履歴(short_hist__) + 手動追加分(verify_manual__) + 全端末同期の作成履歴(go5_stock_archive)を合成。
  //   ★この合成ルールは bluesky.js の Go5PostedItems と一致させる(片方だけ変えると分割ページで pill がズレる)。
  try { window.Go5PostedItems = function (a) {
    var acc = a || acctId(), out = [];
    try { out = histLoadFor_(acc) || []; } catch (e) { out = []; }
    try { var man = (window.Go5Hist ? window.Go5Hist.read('verify_manual__' + acc) : JSON.parse(localStorage.getItem('verify_manual__' + acc) || '[]')); if (Array.isArray(man) && man.length) out = out.concat(man); } catch (e) {}
    // 全端末同期される作成履歴(go5_stock_archive)も「投稿済み」の根拠に含める(短縮URL履歴/手動追加は端末ローカルで
    //   同期しないため、別端末で投稿完了した作品は候補pillが光らなかった=Chami依頼2026-08-03「連動させて」)。
    try {
      var arch = JSON.parse(localStorage.getItem('go5_stock_archive') || '[]');
      if (arch && arch.length) out = out.concat(arch.filter(function (m) {
        if (!m) return false;
        if (m.account === 'acc1' || m.account === 'acc2') return m.account === acc; // 所属明示=そのchだけ
        var pf = String(m.videoId || '').match(/^(acc[12])-/);
        if (pf) return pf[1] === acc;                                                // 所属欄が空でも背骨IDのprefixで判定
        return false; // 所属不明は含めない=別chを誤って「投稿済み」にしない(片ch誤判定の再発防止)
      }));
    } catch (e) {}
    return out;
  }; } catch (e) {}
})();
