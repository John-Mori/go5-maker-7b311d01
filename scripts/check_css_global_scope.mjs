#!/usr/bin/env node
/**
 * check_css_global_scope.mjs — 「全称スタイルの波及」を出す前に機械で止める門。
 *
 * なぜ在るか(2026-08-16・改善提案部門アスナ依頼 msg=1538536324435415120 / 型=docs/departments/kaizen-analyst/preflight_global-css-scope-bleed.md commit f171ba5):
 *   裸の要素セレクタ(グローバル `button{width:100%}` 等)へ far-reaching プロパティを書くと、
 *   後から足す部品(モーダル/オーバーレイ/ツールバー)が黙って継いで壊れる。
 *   style.css は既に3箇所で個別に後追い修正している(130 .promo-toggle=fit-content / 137 恒久対策コメント /
 *   518-520 .fz-modal,.vedit-modal button=max-content)。`[hidden]×display:flex` も4日で2度(INC-37/47)。
 *   同じ穴を「心がけ」でなく「機構」で止める(共通規律§3 / 裁定C-038)。
 *
 * ★姉妹門との棲み分け:
 *   check_button_width.mjs = ボタンを flex:1 で引き伸ばす型(スコープ済みでも拾う)。
 *   本門 = 器のクラスへスコープしていない「裸の要素セレクタ」に far-reaching プロパティを増やす型。
 *   check_button_width.mjs が「静的には拾えない」と自書きした グローバル button{width:100%} の系統は こちらが担当。
 *
 * 検査の芯(型の§機械で止める案):
 *   「裸の要素セレクタ(.class/#id でスコープしていない)へ far-reaching プロパティ(width/display/position/margin)が
 *    1つでも "新規追加" されたら赤」。既存の裸ルールは BASELINE に退避し、新規の混入だけを弾く
 *    (save-path 型と同じ思想=回帰ゼロ)。
 *
 * 使い方:
 *   node scripts/check_css_global_scope.mjs           問題があれば exit 1
 *   DUMP=1 node scripts/check_css_global_scope.mjs     現状の (裸セレクタ|プロパティ) をJSONで吐く(BASELINE更新用)
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CSS_FILE = 'style.css';

// far-reaching = 隣の部品まで巻き込むプロパティ(型 §不変条件 I1)。省略形(margin-top 等)も前方一致で拾う。
const FAR_REACHING = ['width', 'display', 'position', 'margin'];

// ★BASELINE = 2026-08-16 時点で既に style.css に在る「裸セレクタ|プロパティ」。
//   ここに在るものは据え置き(回帰ゼロ)。新規追加は弾く。
//   更新手順: 意図してグローバルを1つ増やしたら DUMP=1 で吐いた行を追記し、なぜ器スコープに出来ないかをコメントで残す。
const BASELINE_KEYS = [
  'body|margin',                    // リセット(既定マージン除去)
  'button|margin',                  // ボタン既定マージンの調整(グローバル)
  'button|width',                   // ★既知のグローバル button{width:100%}。130/518-520 が個別に後追い打ち消し中。根治は別案件(C-039)
  'h1|margin',                      // 見出しの既定マージン調整
  'html|margin',                    // リセット
  'input[type=datetime-local]|width', // iOS Safari の固有min-widthを枠内に収める(css内コメントで既述)
  'input[type=text]|width',         // テキスト入力を枠幅に(textareaと同スタイル)
  'main|margin',                    // レイアウト土台のマージン
  'textarea|width',                 // input[type=text]と同スタイル
];
const BASELINE = new Set(BASELINE_KEYS);

// ---- 走査(フラットCSS: セレクタ { 宣言 } 単位。既存 check_button_width.mjs と同じ流儀) ----
let src;
try {
  src = readFileSync(join(ROOT, CSS_FILE), 'utf8');
} catch {
  console.error(`NG: ${CSS_FILE} を読めなかった=この検査は何も見ていない。パスが動いていないか確認せよ。`);
  process.exit(1);
}

// CSSコメントはセレクタへ混入するので、行番号を保つため中身だけ消して改行は残す。
const srcClean = src.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '));

function lineOf(text, index) { return text.slice(0, index).split('\n').length; }

// セレクタの1つのコンマ片が「裸(=器のクラス/idでスコープされていない)」か。
//   .class / #id を1つでも含めばスコープ済み=対象外。button / input / a / [hidden] / ul li / * は裸。
function isBarePart(part) {
  const p = part.trim();
  if (!p) return false;
  if (p.includes('.') || p.includes('#')) return false; // 器へスコープ済み
  if (p.startsWith('@') || p.startsWith('%') || p.startsWith(':')) return false; // @media等/keyframes%/:root
  if (p.startsWith('from') || p.startsWith('to')) return false; // keyframes
  return true;
}

// 宣言ブロックから far-reaching プロパティ名を拾う(値は問わない・存在で判定)。
function farReachingProps(decl) {
  const props = new Set();
  for (const chunk of decl.split(';')) {
    const name = chunk.split(':')[0].trim().toLowerCase();
    if (!name) continue;
    for (const fr of FAR_REACHING) {
      if (name === fr || name.startsWith(fr + '-')) props.add(fr);
    }
  }
  return props;
}

function* rules(text) {
  const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = ruleRe.exec(text)) !== null) {
    yield { selector: m[1].trim(), decl: m[2], index: m.index };
  }
}

// 現状の全ペアを収集(DUMP用にも使う)。key = "セレクタ片|プロパティ"
function collect(text) {
  const found = [];
  for (const { selector, decl, index } of rules(text)) {
    const props = farReachingProps(decl);
    if (!props.size) continue;
    for (const part of selector.split(',')) {
      if (!isBarePart(part)) continue;
      const norm = part.trim().replace(/\s+/g, ' ');
      for (const pr of props) found.push({ key: `${norm}|${pr}`, line: lineOf(text, index), sel: norm, prop: pr });
    }
  }
  return found;
}

const all = collect(srcClean);

if (process.env.DUMP) {
  const keys = [...new Set(all.map((f) => f.key))].sort();
  console.log(JSON.stringify(keys, null, 2));
  process.exit(0);
}

const violations = all.filter((f) => !BASELINE.has(f.key));

if (violations.length) {
  console.error('NG: 器のクラスへスコープしていない「裸の要素セレクタ」に far-reaching プロパティを新規追加しています。');
  console.error('    (グローバル button{width:100%} 型の波及=後から足す部品が黙って継いで壊れる・INC-37/47/🔥ボタン幅 の再発源)');
  for (const v of violations) {
    console.error(`  ${CSS_FILE}:${v.line}  ${v.sel} { …${v.prop}… }`);
  }
  console.error('  直し方: 器のクラスへスコープする(例 `.form button{...}`)。');
  console.error('          どうしてもグローバルに要るなら、なぜ器へ出来ないかをコメントに書き、');
  console.error('          DUMP=1 node scripts/check_css_global_scope.mjs の出力から該当行を BASELINE に追記する。');
  process.exit(1);
}

console.log(`OK: 裸の要素セレクタへの far-reaching 新規混入なし(BASELINE ${BASELINE.size}件を据え置き)`);
