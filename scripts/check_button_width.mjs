#!/usr/bin/env node
/**
 * check_button_width.mjs — ボタンを「無闇に横へ引き伸ばす」CSSを、出す前に機械で止める門。
 *
 * なぜ在るか(2026-08-16・改修部門αの毎朝振り返りで実装):
 *   直近24hのChami言い直しの最多型が「ボタンの幅(肥大化)」の再発だった。
 *   🔥 DEF-system-engineer-c7f98afd62「ボタンの横幅は無闇に広げるな・前のサイズで良かった」
 *   🔥 DEF-system-engineer-132b05c4b4「なんで余計に悪くなってんの」
 *   と同型の肥大化が、今度は「データ再作成ボタン」で再発した(commit 018ceb8 で応急修正)。
 *   好みは docs/departments/frontend/design-preferences.md §4.5 に🔥恒久対策として既に書いてある。
 *   だが「書いてあるのに実装が読まずに再発」した=心がけでは止まらない。だから機構に載せる(共通規律§3/裁定C-038)。
 *
 * 検査するアンチパターン(design-preferences §4.5 が明示的に禁止しているもの):
 *   B1. `button` を対象にするCSSルールが flex で横いっぱいに引き伸ばしている
 *       (`flex:1` / `flex:1 1 0` / `flex:1 1 auto` / `flex-grow:1以上`)。
 *       → Chami🔥「flex:1 で横幅いっぱいに引き伸ばすな・文字量なりでいい」の再発源。
 *
 * ★この門の限界(正直に書く):
 *   グローバル `button{width:100%}`(style.css)を継いで「幅指定なしのボタンが全幅化」する型は、
 *   HTMLの並び(どの行に置かれたか)を見ないと静的には判定できないため、この門では拾えない。
 *   その根治(グローバル既定を width:auto へ反転)は全ページのボタン回帰を伴うので、
 *   実機確認を1周してから入れる案件として別途ChamiのGoで進める(C-039)。
 *
 * 使い方: node scripts/check_button_width.mjs   (問題があれば exit 1)
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CSS_FILE = 'style.css';
const RECIPE = '安全レシピ= 行内に並ぶ操作ボタンは width:auto;flex:0 0 auto(縮まない・文字量なり)+コンテナ flex-wrap:wrap。flex:1 で引き伸ばさない(design-preferences §4.5)';

// ★許可リスト= flex:1 での等幅分割を Chami が明示的に受け入れた場所だけ。
//   ここに足す時は「Chamiが等幅でよいと言った実物(msg_id等)」をコメントに残すこと。
const ALLOW = [
  '.rsv-dlg-btns',   // 予約ダイアログの2ボタン脚(キャンセル/確定の等幅=design-preferences §モーダル脚の受理済みパターン)
];

// flex-grow が正になる書き方: `flex:1`(=1 1 0)/`flex:1 1 auto` 等 / `flex-grow:1..9`
const STRETCH_RE = /flex\s*:\s*(?:1\b|[1-9]\d*\s+[1-9]\d*)|flex-grow\s*:\s*[1-9]/i;

const findings = [];
const add = (line, sel, msg) => findings.push({ line, sel, msg });

function lineOf(text, index) { return text.slice(0, index).split('\n').length; }

let src;
try {
  src = readFileSync(join(ROOT, CSS_FILE), 'utf8');
} catch {
  // ★静かにパスさせない(検査が仕事をしていないことを可視化する)。
  console.error(`NG: ${CSS_FILE} を読めなかった=この検査は何も見ていない。パスが動いていないか確認せよ。`);
  process.exit(1);
}

// フラットなCSSを「セレクタ { 宣言 }」の単位で走査する(このファイルはネストなし)。
const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
let m;
while ((m = ruleRe.exec(src)) !== null) {
  const selector = m[1].trim();
  const decl = m[2];
  // セレクタが button を対象にしているルールだけを見る。
  if (!/\bbutton\b/i.test(selector)) continue;
  if (!STRETCH_RE.test(decl)) continue;
  // 許可リストに載っているセレクタはスキップ。
  if (ALLOW.some((a) => selector.includes(a))) continue;
  add(lineOf(src, m.index), selector, `ボタンを flex で横いっぱいに引き伸ばしている(${decl.trim().replace(/\s+/g, ' ').slice(0, 60)})`);
}

if (findings.length) {
  console.error('NG: ボタンの幅の🔥恒久対策に反する指定があります(Chami「横幅を無闇に広げるな」の再発源):');
  for (const f of findings) {
    console.error(`  ${CSS_FILE}:${f.line}  ${f.sel}\n      → ${f.msg}`);
  }
  console.error(`  ${RECIPE}`);
  console.error('  等幅にする正当な理由がある場合は、Chamiの受理を確認のうえ scripts/check_button_width.mjs の ALLOW に追記する。');
  process.exit(1);
}

console.log('OK: ボタンを不当に引き伸ばす指定なし');
