/**
 * 下書きの2行モード復元(2026-07-19 Chami指示・2026-07-20 実装)のテスト。
 *
 * 対象の仕様:
 *   「更新前に下書き保存した作品でも、更新後に下書きから引っ張る作品は
 *     更新後の影響を反映して表示すること」
 *
 * なぜこのテストが要るか:
 *   2行モードのON/OFFは長らく下書きに保存されていなかった。top/author の値には改行が
 *   入っているのに、呼び出し先のチェックがOFFだと fitOneLine(app.js)で1行に潰れ、
 *   **保存した時と見た目が変わる**。下書きは見た目の再現が仕事なので、これは機能の破綻。
 *   フラグを足したあとも、**フラグを持たない旧い下書き**が壊れないことを保証し続ける必要がある。
 *
 * ★ここで固定しているのは「undefinedとfalseを区別する」こと。
 *   `draft.topTwoLine === undefined` で判定すると、**意図してOFFで保存した下書き**まで
 *   推定へ流れてしまい、改行入りの本文だと勝手に2行へ戻る(ユーザーの選択を無視する)。
 *   hasOwnProperty で「そのキーを持っているか」を見るのが正しい。
 */
'use strict';

// drafts.js の applyDraft_ 内の twoLineOf_ と同じ判定(実装を変えたらここも合わせる)
function twoLineOf_(draft, key, text) {
  if (draft && Object.prototype.hasOwnProperty.call(draft, key)) return !!draft[key];
  return String(text || '').indexOf('\n') >= 0;
}

let fails = 0;
function eq(got, want, label) {
  if (got === want) { console.log(`  PASS ${label}`); }
  else { console.log(`  FAIL ${label}: got=${JSON.stringify(got)} want=${JSON.stringify(want)}`); fails++; }
}

console.log('--- 新しい下書き(フラグあり)= 保存値をそのまま使う ---');
eq(twoLineOf_({ topTwoLine: true }, 'topTwoLine', 'あ\nい'), true, '2行ONで保存 -> ON');
eq(twoLineOf_({ topTwoLine: false }, 'topTwoLine', 'あ\nい'), false,
  '★2行OFFで保存 -> 改行が入っていてもOFF(ユーザーの選択を尊重)');
eq(twoLineOf_({ topTwoLine: false }, 'topTwoLine', 'あい'), false, '2行OFF・改行なし -> OFF');
eq(twoLineOf_({ topTwoLine: true }, 'topTwoLine', 'あい'), true, '2行ON・改行なし -> ON');

console.log('--- 旧い下書き(フラグなし)= 本文の改行から推定する ---');
eq(twoLineOf_({ top: 'あ\nい' }, 'topTwoLine', 'あ\nい'), true,
  '改行あり -> 2行だったと推定(当時の見た目を復元)');
eq(twoLineOf_({ top: 'あい' }, 'topTwoLine', 'あい'), false, '改行なし -> 1行');
eq(twoLineOf_({}, 'topTwoLine', ''), false, '空文字 -> 1行');
eq(twoLineOf_({}, 'topTwoLine', null), false, 'null -> 1行(落ちない)');
eq(twoLineOf_({}, 'topTwoLine', undefined), false, 'undefined -> 1行(落ちない)');

console.log('--- author側も同じ判定であること ---');
eq(twoLineOf_({ authorTwoLine: true }, 'authorTwoLine', 'A'), true, 'authorフラグあり');
eq(twoLineOf_({ author: 'A\nB' }, 'authorTwoLine', 'A\nB'), true, 'author改行から推定');

console.log('--- draft自体が無い/壊れている場合 ---');
eq(twoLineOf_(null, 'topTwoLine', 'あ\nい'), true, 'draft=null でも落ちず推定に倒れる');
eq(twoLineOf_(undefined, 'topTwoLine', 'あい'), false, 'draft=undefined でも落ちない');

console.log(fails ? `\n*** FAIL ${fails}件 ***` : '\nPASS 下書きの2行モード復元(後方互換つき)');
process.exit(fails ? 1 : 0);
