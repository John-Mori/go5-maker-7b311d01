// tests/test_workstate.js — 発売日→作品状態(新作/準新作/旧作)の判定を「本物の判定口」で検証する。
//
//   背景(2026-08-13・Chami報告「新作判定が漏れる」): 新作チェック(discountNew2)を実際に立てる bluesky.js の
//     deriveWorkState_ だけ日付パースが new Date(str.replace('/','-')) で、FANZA/DMM API の date
//     "YYYY-MM-DD HH:mm:ss"(スペース区切り・T無し)を iOS Safari(WebKit)が Invalid Date にし、新作でも
//     チェックが立たず本文に「の新作」が入らなかった(V8/Chromeは寛容で気づけない)。candidates.js /
//     yt-clicks.js は .replace(' ','T') で正規化済みだったが起点だけ抜けていた=AIカテゴリと同型の食い違い。
//   対策: 判定を core/movie-attrs-core.js(deriveWorkState)へ集約。このテストは本物を直接叩き、特に
//     スペース区切り形式(iOS Safari 落とし穴)を固定する。さらに bluesky.js が core を通す配線をガードする。
//     実行: node tests/test_workstate.js
'use strict';
var fs = require('fs');
var path = require('path');
var Core = require('../core/movie-attrs-core.js'); // ★本物の判定口(runtime と同一)

var fails = 0;
function check(name, cond) { if (cond) { console.log('  ok  ' + name); } else { console.log('  NG  ' + name); fails++; } }

// 基準の「今」を固定して曜日/実行時刻に依存しない。テスト日付(スペース/T区切り)と同じローカル解釈で
//   合わせる=境界(30日ちょうど)がタイムゾーンずれで揺れないよう Z を付けない。
var NOW = Date.parse('2026-08-13T00:00:00');
function ws(dateStr) { return Core.deriveWorkState(dateStr, NOW); }

// ── 1) 判定ロジック(本物の deriveWorkState) ───────────────────────────────
// ★核: FANZA API 形式(スペース区切り・T無し)。iOS Safari が Invalid Date にしていた再発クラス。
check('スペース区切り "YYYY-MM-DD HH:mm:ss" 12日前 → 新作', ws('2026-08-01 10:00:00') === '新作');
check('スペース区切り 45日前 → 準新作', ws('2026-06-29 10:00:00') === '準新作');
check('スペース区切り 200日前 → 旧作', ws('2026-01-25 10:00:00') === '旧作');
// 日付のみ(時刻なし)
check('日付のみ 5日前 → 新作', ws('2026-08-08') === '新作');
// スラッシュ表記(保険パース)
check('スラッシュ "YYYY/MM/DD" 10日前 → 新作', ws('2026/08/03') === '新作');
// 境界(30日ちょうど=新作 / 31日=準新作)
check('30日ちょうど → 新作', ws('2026-07-14 00:00:00') === '新作');
check('31日前 → 準新作', ws('2026-07-13 00:00:00') === '準新作');
// 空/不正
check('空文字 → ""', ws('') === '');
check('パース不能 → ""', ws('のちほど') === '');

// ── 2) 配線ガード(bluesky.js/candidates.js/yt-clicks.js が本物の core を通すか) ──────────
//   3ファイルの deriveWorkState_ に別パース実装が再び忍び込むのを防ぐ。core 委譲行が在ることを固定する。
function guard(file) {
  // ★2026-08-14 直下の .js を js/ へ集約した(整理フェーズ3)。読めなければ落とす=黙って飛ばさない。
  var src = fs.readFileSync(path.join(__dirname, '..', 'js', file), 'utf8');
  check(file + ' が Go5MovieAttrsCore.deriveWorkState へ委譲', src.indexOf('Go5MovieAttrsCore.deriveWorkState') >= 0);
  // 起点(bluesky.js)に旧バグの素の new Date(...replace('/','-')) が残っていないこと。
  check(file + ' に旧パース new Date(replace(/\\//)) が無い', !/new Date\(String\(dateStr\)\.replace\(\/\\\/\/g/.test(src));
}
guard('bluesky.js');
guard('candidates.js');
guard('yt-clicks.js');

if (fails) { console.log('\nFAIL: ' + fails + '件'); process.exit(1); }
console.log('\nALL PASS (workstate)');
