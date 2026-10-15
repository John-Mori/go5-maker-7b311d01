#!/usr/bin/env node
// check_e2e_touch.mjs — 画面のJSを変えたのに、本物の操作を通すE2Eを1本も足していない push を手元で止める門。
//
// なぜ要るか(2026-10-15 朝レビュー):
//   v1032「公開枠ピッカーに選択済みの題名を出す」は、カレンダーへ手で taken を流し込んで見ただけで出荷し、
//   ドラフト→takenSlots_ の本物の経路を一度も通さなかった。Chamiの実機では出ず「出ないんだけど」の言い直しになった。
//   前日24hの画面JSの出荷12本のうち、tests/ を伴わなかった4本の1本がこれだった。
//
// 仕組み:
//   origin/main..HEAD(+ステージ済み)で js/ core/ schedule/js/ が変わり、tests/ が1つも変わっていなければ落ちる。
//   見た目だけの変更など、E2Eが要らない理由がある時は  E2E_SKIP="理由" node scripts/check_e2e_touch.mjs  で通す(理由は表示して残す)。
//   CIでは回さない(失敗メールをChamiへ飛ばさないため・2026-10-10「このメールやめて欲しい」)。push前に手元で回す。
//
// 使い方:  node scripts/check_e2e_touch.mjs [基準ref=origin/main]
import { execFileSync } from 'node:child_process';

const base = process.argv[2] || 'origin/main';
const git = (...a) => execFileSync('git', a, { encoding: 'utf8' }).split('\n').map((s) => s.trim()).filter(Boolean);

let files;
try {
  files = new Set([...git('diff', '--name-only', `${base}...HEAD`), ...git('diff', '--name-only', '--cached')]);
} catch (e) {
  console.error(`check_e2e_touch: ${base} と比べられない(${String(e.message).split('\n')[0]})。判定せず通す。`);
  process.exit(0); // 判定不能は通す側へ倒す
}

const front = [...files].filter((f) => /^(js|core|schedule\/js)\/.+\.js$/.test(f));
const tests = [...files].filter((f) => f.startsWith('tests/'));

if (!front.length) { console.log('check_e2e_touch: 画面のJSの変更なし'); process.exit(0); }
if (tests.length) { console.log(`check_e2e_touch: OK 画面JS ${front.length}本 / tests ${tests.length}本`); process.exit(0); }

const skip = (process.env.E2E_SKIP || '').trim();
if (skip) { console.log(`check_e2e_touch: E2Eなしで通す(理由: ${skip}) 画面JS= ${front.join(', ')}`); process.exit(0); }

console.error('check_e2e_touch: 画面のJSを変えたのに tests/ の変更が無い。');
console.error('  変えた画面JS= ' + front.join(', '));
console.error('  Chamiが触るのと同じ操作(クリック・保存・同期)で通すE2Eを tests/e2e に1本足すこと。');
console.error('  ★値を手で流し込んで見ただけの検証では足りない(v1032の言い直しの元)。');
console.error('  見た目だけ等で要らないなら  E2E_SKIP="理由" node scripts/check_e2e_touch.mjs');
process.exit(1);
