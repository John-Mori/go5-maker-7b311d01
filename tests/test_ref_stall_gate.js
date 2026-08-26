// tests/test_ref_stall_gate.js — 動画生成用画像の「持続失敗」ゲート refStallDecide_ の境界を固定する。
//   ★HQの作法=ソース文字列一致でなく、本物の純関数へ本物の入力を通して分岐を実行で確かめる。
//   狙い=⏳(読込中)/🔍(確認中)が「取得の持続失敗」で永久スピナー(吸収状態)に嵌るのを、n回/T秒 で
//   ⌛(タップで再試行)へ抜けさせる境界。しきい=3回 かつ 連鎖開始から20秒。
const assert = require('assert');
const { refStallDecide_, refRetryPlan_, histDirectRetryPlan_ } = require('../js/candidates.js');

let n = 0;
function t(name, got, want) {
  n++;
  assert.strictEqual(got, want, `[${name}] want=${want} got=${got}`);
  console.log(`  ok  ${name} => ${got}`);
}

// 引数順= (n, sinceMs, nowMs)。now-since が経過時間(ms)。
const T0 = 1000000; // 連鎖開始の基準時刻(任意)

// 1) 回数が足りない=falseのまま(時間だけ満たしても2回では落とさない=一過性のちらつきで⌛にしない)。
t('2回・25秒経過=まだ', refStallDecide_(2, T0, T0 + 25000), false);
t('1回・60秒経過=まだ', refStallDecide_(1, T0, T0 + 60000), false);

// 2) 時間が足りない=falseのまま(3回でも直後は⏳のまま=正当な取得中を⌛と誤らない)。
t('3回・0秒=まだ', refStallDecide_(3, T0, T0), false);
t('3回・19.999秒=まだ', refStallDecide_(3, T0, T0 + 19999), false);

// 3) 3回 かつ 20秒ちょうど=stalledへ落とす(境界)。
t('3回・20秒ちょうど=stalled', refStallDecide_(3, T0, T0 + 20000), true);
t('5回・30秒=stalled', refStallDecide_(5, T0, T0 + 30000), true);

// 4) since=0(連鎖なし)は経過時間が巨大に見えても false(記帳の起点が無い=持続と見なさない)。
t('since=0は落とさない', refStallDecide_(9, 0, T0 + 999999), false);

// 5) stalledは表示状態の変更であり、再試行の終端ではない。30秒で頭打ちにし、何回失敗してもretry=true。
const p1 = refRetryPlan_(1, T0, T0);
assert.deepStrictEqual(p1, { stalled: false, retry: true, delay: 3000 });
n++;
console.log('  ok  1回目は3秒後に再試行');

const p3 = refRetryPlan_(3, T0, T0 + 20000);
assert.deepStrictEqual(p3, { stalled: true, retry: true, delay: 30000 });
n++;
console.log('  ok  stalled到達後も30秒後に再試行');

const p99 = refRetryPlan_(99, T0, T0 + 999999);
assert.deepStrictEqual(p99, { stalled: true, retry: true, delay: 30000 });
n++;
console.log('  ok  99回失敗しても自動再試行を諦めない');

// 6) 投稿履歴の可視画像も3回で打ち切らない。以後は30秒間隔で必ず追跡を続ける。
assert.deepStrictEqual(histDirectRetryPlan_(1), { retry: true, delay: 1000 });
n++;
assert.deepStrictEqual(histDirectRetryPlan_(2), { retry: true, delay: 2000 });
n++;
assert.deepStrictEqual(histDirectRetryPlan_(3), { retry: true, delay: 30000 });
n++;
assert.deepStrictEqual(histDirectRetryPlan_(99), { retry: true, delay: 30000 });
n++;
console.log('  ok  投稿履歴は99回失敗しても30秒間隔で再試行を諦めない');
console.log(`\nAll ${n} passed (refStallDecide_/refRetryPlan_).`);
