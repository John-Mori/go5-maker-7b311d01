#!/usr/bin/env node
/**
 * check_persist_derived.mjs — 「作品ごとに導出する派生チェックを persist して、リロードで前作の値が残る」型を、
 *   出す前に機械で止める門。⑥(何度も再発する)への恒久対策の一つ。
 *
 * なぜ在るか(Chami報告2026-08-16①・改善提案部門アスナの分析 proposal_2026-08-16_movie-attrs-5recur.md):
 *   準新作チェックが「翌日/リロードで消えて二度と入らない」根っこは、派生値(発売日から毎回導出する)を
 *   汎用 persist(field_<id>)が保存/復元して、自動導出のガードと相まって決定機になったこと。
 *   芯は「新しいチェックボックスを足す→persist-fields の EXCLUDE へ id を足し忘れる」=EXCLUDE が
 *   『登録漏れは既定で保存に倒れる』denylist だから。これは **4回目**(先例= xTweetText / testMode /
 *   カテゴリチェック[data-catKey])。心がけでは止まらないので機構に載せる(共通規律§3 / 裁定C-038)。
 *
 * この門が実際に見るもの(2つとも「実物どうしの照合」= "..." in src の保険で終わらせない):
 *   A. persist-fields.js の persistable() を**抽出して実行**し、data-derived="1" の入力が確かに
 *      除外され(false)、素の新規欄は保存対象(true)のまま=ガードが広すぎない、を実挙動で確認する。
 *      → 「本番の初発火が初検証」を避ける(共通規律§3・2026-08-14 HQ裁定)。
 *   B. index.html の割引/作品状態チェック群(label.disc-new)の各 checkbox が、
 *      EXCLUDE登録 / data-derived="1" / 手動フラグ(下の MANUAL)のどれか一つで**必ずカバーされる**。
 *      新しい5個目のチェックを足すと、どれも選ばずには通れない=登録忘れがクラスごと出る前に落ちる。
 *
 * ★この門の限界(正直に書く):
 *   「その入力が本当に派生値か(発売日から導出されるか)」は静的には判定できない。だから B は
 *   『割引/作品状態クラスの checkbox は必ず明示的に分類しろ(保存する手動フラグか・保存しない派生値か)』
 *   という強制に留める。分類そのものの正しさは実装者の判断=data-derived を付けるか MANUAL へ足すか。
 *
 * 使い方: node scripts/check_persist_derived.mjs   (問題があれば exit 1)
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PERSIST = 'js/persist-fields.js';
const HTML = 'index.html';

// ★手動フラグ= 発売日から導出されない・ユーザーが作品ごとに手で決める=保存してよい checkbox。
//   ここに足す時は「なぜ導出値でなく手動なのか」を必ずコメントで残すこと。
const MANUAL = {
  // 総集編は acc1/acc2/PC の3変種。いずれも発売日から導出できない手動フラグ(新作/準新作のような
  // 日付導出値ではない)ので保存してよい=リロードで消えると手で付け直す手間になる。
  discountDigest: '総集編(acc1)= 手動フラグ(日付導出値でない)ので保存してよい',
  discountDigest2: '総集編(acc2)= 手動フラグ(日付導出値でない)ので保存してよい',
  discountDigestPc: '総集編(PC)= 手動フラグ(日付導出値でない)ので保存してよい',
};

function read(rel) {
  try { return readFileSync(join(ROOT, rel), 'utf8'); }
  catch { console.error(`NG: ${rel} を読めなかった=この検査は何も見ていない。パスを確認せよ。`); process.exit(1); }
}

// コメントを剥がす(以降の波括弧走査がコメント内の記号に惑わされないように)。
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
}

// openIdx(='{' の位置)から釣り合う '}' までを返す(波括弧の深さで数える)。
function balanced(src, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(openIdx, i + 1); }
  }
  return null;
}

const fails = [];

// ── A. persistable() を抽出して実行し、data-derived の除外を実挙動で確認する ───────────────
const persistNo = stripComments(read(PERSIST));

const exAt = persistNo.indexOf('EXCLUDE');
const exBrace = persistNo.indexOf('{', exAt);
const exDef = exBrace >= 0 ? `var EXCLUDE = ${balanced(persistNo, exBrace)};` : null;

const fnAt = persistNo.search(/function\s+persistable\s*\(\s*el\s*\)/);
const fnBrace = fnAt >= 0 ? persistNo.indexOf('{', fnAt) : -1;
const fnDef = fnBrace >= 0 ? `function persistable(el){${balanced(persistNo, fnBrace).slice(1)}` : null;

let EXCLUDE_IDS = new Set();
if (!exDef || !fnDef) {
  fails.push(`${PERSIST}: EXCLUDE か persistable() を抽出できなかった=構造が変わった。この門を追随させよ。`);
} else {
  try {
    const persistable = new Function(`${exDef}\n${fnDef}\nreturn persistable;`)();
    // EXCLUDE の id を実オブジェクトから採取(B のカバー判定に使う)。
    EXCLUDE_IDS = new Set(Object.keys(new Function(`${exDef}\nreturn EXCLUDE;`)()));
    const cases = [
      { name: 'data-derived の checkbox は除外される', el: { id: '__probeDerived', dataset: { derived: '1' }, tagName: 'INPUT', type: 'checkbox' }, want: false },
      { name: '素の新規 textarea は保存対象のまま(ガードが広すぎない)', el: { id: '__probeNormal', dataset: {}, tagName: 'TEXTAREA' }, want: true },
      { name: 'EXCLUDE の id は属性無しでも除外される', el: { id: 'movieJunshinsaku', dataset: {}, tagName: 'INPUT', type: 'checkbox' }, want: false },
    ];
    for (const c of cases) {
      const got = !!persistable(c.el);
      if (got !== c.want) fails.push(`${PERSIST}: persistable() 実行結果が期待と違う — 「${c.name}」 期待=${c.want} 実際=${got}`);
    }
  } catch (e) {
    fails.push(`${PERSIST}: persistable() の抽出実行に失敗 — ${e && e.message}`);
  }
}

// ── B. index.html の割引/作品状態 checkbox が全て明示分類されているか ──────────────────────
const html = read(HTML);
// label class="disc-new" の中の <input ...> を拾う。
const labelRe = /<label[^>]*class="[^"]*\bdisc-new\b[^"]*"[^>]*>([\s\S]*?)<\/label>/g;
let lm;
const cluster = [];
while ((lm = labelRe.exec(html)) !== null) {
  const inner = lm[1];
  const idM = inner.match(/<input[^>]*\bid="([^"]+)"/);
  if (!idM) continue;
  const inputTag = inner.match(/<input[^>]*>/)[0];
  const hasDerived = /\bdata-derived="1"/.test(inputTag);
  const isCheckbox = /type="checkbox"/.test(inputTag);
  if (!isCheckbox) continue;
  cluster.push({ id: idM[1], hasDerived });
}

if (cluster.length === 0) {
  fails.push(`${HTML}: label.disc-new の checkbox を1つも拾えなかった=構造が変わった。この門を追随させよ(黙って素通りさせない)。`);
}
for (const c of cluster) {
  const covered = EXCLUDE_IDS.has(c.id) || c.hasDerived || Object.prototype.hasOwnProperty.call(MANUAL, c.id);
  if (!covered) {
    fails.push(
      `${HTML}: 割引/作品状態チェック「${c.id}」が未分類=汎用persistで field_${c.id} が保存され、` +
      `リロードで前作の値が残る(準新作①の再発源)。次のどれかで分類せよ: ` +
      `(1)発売日から導出する派生値なら input へ data-derived="1" を付ける ` +
      `(2)ユーザーが作品ごとに手で決める手動フラグなら scripts/check_persist_derived.mjs の MANUAL へ理由つきで足す ` +
      `(3)EXCLUDE(${PERSIST})へ id 登録。`
    );
  }
}

if (fails.length) {
  console.error('NG: 派生チェックの persist 分類に漏れ/退行があります(Chami①「準新作チェックが入らない」の再発源):');
  for (const f of fails) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`OK: 派生チェックの persist 分類は健全(cluster=${cluster.length}件 / EXCLUDE=${EXCLUDE_IDS.size}件 / persistable実挙動3ケース緑)`);
