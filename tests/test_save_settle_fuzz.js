// tests/test_save_settle_fuzz.js
// 保存経路「単一着地権威」の4軸総当り回帰(改善提案部門の型 §3 の発注)。
//   既存の test_idb_failopen(軸①の読み)と test_drive_save_settle(ボタン終端)は
//   それぞれ1つの組み合わせしか固定していない。「遷移前に動画を失う全滅」は両方の範囲外。
//   このハーネスは4故障軸を総当りし、どの組み合わせでも
//     『動画が手元 or 雲に必ず残る、さもなくば明示保留(hold)。黙って遷移して全滅しない』
//   を assert する。外へ出る手(IDB/R2/location.href)は模擬、判定 decide() は本番と同一。
//
// 実行: node tests/test_save_settle_fuzz.js

var Gate = require('../core/save-gate.js');

var fails = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { fails++; console.error('  ✗ ' + msg); } }

// ── 4故障軸の値域 ──
var IDB    = ['die', 'live'];              // 軸① IDB書込 stock_v_
var R2     = ['fail', 'delay', 'success']; // 軸② R2ミラー _vidUp
var NAV    = ['early', 'normal'];          // 軸③ navTimer(着地より先=early / 後=normal)
var TAB    = ['destroy', 'keep'];          // 軸④ iOSがタブ/bfcacheを捨てる

// シナリオ→「遷移を判定する瞬間(terminal)の state」を作る現実モデル。
//   * localLanded = IDB書込が生きて成功した時だけ
//   * cloudLanded = R2が success かつ タブが破棄されていない時だけ
//       (タブ破棄=飛んでいるR2 PUTが殺される / delay=terminalまでに完了していない)
//   * timerFired  = navTimerが terminal 時点で発火している(=early、または normalで未着地)
function terminalState(idb, r2, nav, tab) {
  var localLanded = (idb === 'live');
  var cloudLanded = (r2 === 'success' && tab !== 'destroy');
  var landed = localLanded || cloudLanded;
  // early=着地シグナルより先に期限が来る / normal=着地判定の後に期限。
  //   どちらでも「最終的に着地していなければ期限は発火して hold へ倒れる」。
  var timerFired = (nav === 'early') ? true : !landed;
  return { localLanded: localLanded, cloudLanded: cloudLanded, timerFired: timerFired };
}

var total = 0, silentLoss = 0;
IDB.forEach(function (idb) {
  R2.forEach(function (r2) {
    NAV.forEach(function (nav) {
      TAB.forEach(function (tab) {
        total++;
        var st = terminalState(idb, r2, nav, tab);
        var act = Gate.decide(st);
        var landed = st.localLanded || st.cloudLanded;
        var tag = '[idb=' + idb + ' r2=' + r2 + ' nav=' + nav + ' tab=' + tab + ']';

        // 不変条件1: 着地していないのに navigate は絶対に出さない(=黙って全滅しない)
        if (act === 'navigate' && !landed) silentLoss++;
        ok(!(act === 'navigate' && !landed),
          tag + ' 未着地で navigate=黙って全滅した');

        // 不変条件2: 着地済みなら必ず navigate(閉じ込めない)
        if (landed) ok(act === 'navigate', tag + ' 着地済みなのに遷移しない(閉じ込め)');

        // 不変条件3: 未着地かつ期限到来なら hold(明示保留)・wait のまま無言放置にしない
        if (!landed && st.timerFired) ok(act === 'hold', tag + ' 未着地の期限到来が hold でない');
      });
    });
  });
});

// ── 名指しの再発シナリオ(5031ddb 全滅)を明示固定 ──
// 軸① IDB死 × 軸② R2失敗 → 動画はどこにも残せない → 黙って遷移せず hold
ok(Gate.decide(terminalState('die', 'fail', 'normal', 'keep')) === 'hold',
  'IDB死×R2失敗=hold(黙って全滅しない)');
// 軸① IDB死 × 軸④ タブ破棄がR2 PUTを殺す(R2 success 指定でも着地は不成立)→ hold
ok(Gate.decide(terminalState('die', 'success', 'early', 'destroy')) === 'hold',
  'IDB死×タブ破棄(R2殺し)=hold');
// 健全端末: IDB生 → early navTimer でも navigate(着地しているので遷移してよい)
ok(Gate.decide(terminalState('live', 'fail', 'early', 'keep')) === 'navigate',
  'IDB生=早発タイマーでも navigate');
// IDB死でも R2成功かつタブ生存 → 雲に着地 → navigate
ok(Gate.decide(terminalState('die', 'success', 'normal', 'keep')) === 'navigate',
  'IDB死でもR2着地=navigate');

console.log('総当り ' + total + ' 通り / assert ' + checks + ' 件 / 黙って全滅した組み合わせ ' + silentLoss + ' 件');
if (fails) { console.error('FAIL: ' + fails + ' 件'); process.exit(1); }
console.log('PASS: test_save_settle_fuzz (4軸総当り・単一着地権威)');
