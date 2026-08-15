// core/save-gate.js — 保存経路の「単一着地権威」(Go5SaveGate)
// ─────────────────────────────────────────────────────────────
// 由来= 改善提案部門(トトリ/アスナ)の型
//   docs/departments/kaizen-analyst/preflight_save-path-single-authority.md
// 背景= 候補→作成→IDB(stock_v_)→R2ミラー(_vidUp)→遷移(goDraft_/navTimer) の保存経路は、
//   単一バグではなく「4つの故障軸の掛け算」で全滅する:
//     軸① IDB書込が無言で死ぬ(iOS Safari)  軸② R2ミラーが遅延/失敗する
//     軸③ 遷移タイマー(navTimer)が着地より先に発火  軸④ iOSがタブ/bfcacheを捨てる
//   🔥のたびに1つの組み合わせを個別に潰してきたが、掛け算なので次の組み合わせで再発した
//   (8/12以降この塊だけで改修39件・根治表記11件・それでも8/15朝に全滅=commit 5031ddb)。
//
// この型の核= 遷移を起こす権威を「1本の真理値」へ集約する:
//   * 遷移(navigate)は動画が 手元(IDB) か 雲(R2) の"どちらかに着地"した時だけ。
//   * タイマーは"進む"既定を持たない=期限が来て未着地なら『着地不能を明示して保留(hold)』へ倒す。
//     黙って遷移してJSコンテキストを破棄すると、飛んでいるR2ミラーごと動画を殺す(=全滅)。
//
// ★このモジュールは「判定と分岐」だけを持つ純粋関数。外へ出る手(IDB/R2/location.href)は
//   呼び元が注入する=本番(stock.js)と回帰テスト(tests/test_save_settle_fuzz.js)が
//   同一の decide() を通す(共通規律§3「判定と分岐は本物のまま回す」)。
(function (root) {
  'use strict';

  // s: { localLanded:Bool, cloudLanded:Bool, timerFired:Bool }
  //   localLanded = 動画が手元(IDB stock_v_)に書けた
  //   cloudLanded = 動画が雲(R2ミラー _vidUp)に上がった
  //   timerFired  = 遷移期限が来た(navTimer)/両失敗で着地不能が確定した
  // 返り値:
  //   'navigate' = 遷移してよい(手元 or 雲に着地済み)
  //   'hold'     = 未着地のまま期限到来=黙って進まず明示保留(I4)
  //   'wait'     = まだ着地待ち(タイマー未発火)
  function decide(s) {
    if (s && (s.localLanded || s.cloudLanded)) return 'navigate';
    if (s && s.timerFired) return 'hold';
    return 'wait';
  }

  var api = { decide: decide };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Go5SaveGate = api;
})(typeof window !== 'undefined' ? window : this);
