#!/usr/bin/env node
/**
 * check_ui_ios.mjs — iOS Safari 固有のレイアウト崩れを「出す前」に機械で止める門。
 *
 * なぜ在るか(2026-07-29・改修部門αの毎朝振り返りで実装):
 *   直近24hのChami言い直しの最多型は「反映されてない/文字列崩れ/箱が消えた」=
 *   PC/Chromeでは再現せず iOS Safari でだけ壊れるレイアウトを、実機未確認で出したこと。
 *   同じ穴を二度踏まないため、既知の iOS Safari 落とし穴を CI(smoke)で fail させる。
 *
 * 検査する落とし穴(すべて実際に事故を起こした型):
 *   R1. <input>/<textarea> の inline style に flex: があるのに min-width:0 が無い
 *       → iOS Safari が入力欄を幅ゼロに潰す(v=450「箱が消えた」の真因)。
 *   R2. flex の basis に % を使っている(flex:N N NN%)
 *       → iOS Safari で同列にならず折り返す(v=453「同じ列を満たしていない」の真因)。
 *       ※ 変数合成された style も拾えるよう *.js 全体を対象に文字列で検出する。
 *   R3. style.css で background-attachment:fixed / body::before{…z-index:-1}
 *       → iOS Safari で背景が消える/後ろに落ちる(v=435 背景が変わらない の真因)。
 *
 * 使い方: node scripts/check_ui_ios.mjs   (問題があれば exit 1)
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const RECIPE = '安全レシピ= 入力は flex:1;min-width:0 / ボタンは flex:0 0 auto / basis に%を使わない';
const JS_FILES = ['stock.js', 'app.js', 'affiliate.js', 'bluesky.js', 'candidates.js', 'scheduler.js', 'integration.js'];

const findings = [];
const add = (file, line, rule, msg) => findings.push({ file, line, rule, msg });

function lineOf(text, index) { return text.slice(0, index).split('\n').length; }

for (const f of JS_FILES) {
  let src;
  try { src = readFileSync(join(ROOT, f), 'utf8'); } catch { continue; }

  // R1: <input>/<textarea> タグ(> まで・改行跨ぎ可)を取り、inline style に flex: があって min-width:0 が無いもの。
  const tagRe = /<(input|textarea)\b[^>]*?>/gis;
  let m;
  while ((m = tagRe.exec(src)) !== null) {
    const tag = m[0];
    const styleM = /style\s*=\s*"([^"]*)"/i.exec(tag);
    if (!styleM) continue;              // style が変数合成(style="'+v+'")のものは R2 で拾う
    const style = styleM[1];
    if (/(^|[;\s])flex\s*:/i.test(style) && !/min-width\s*:\s*0/i.test(style)) {
      add(f, lineOf(src, m.index), 'R1', `<${m[1]}> に flex: があるが min-width:0 が無い → iOS Safariで幅ゼロに潰れる。${RECIPE}`);
    }
  }

  // R2: flex の % basis(flex:1 1 58% など)。変数合成も拾えるよう全文を走査。
  const pctRe = /flex\s*:\s*\d+\s+\d+\s+\d+%/gi;
  while ((m = pctRe.exec(src)) !== null) {
    add(f, lineOf(src, m.index), 'R2', `flexのbasisに%を使用(${m[0]}) → iOS Safariで折り返し「同じ列」が崩れる。basisは0(=flex:1)にする。`);
  }
}

// R3: style.css の背景落とし穴(コメント行は除外)。
try {
  const css = readFileSync(join(ROOT, 'style.css'), 'utf8');
  const lines = css.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const code = raw.replace(/\/\*.*?\*\//g, '');      // 同一行コメント除去
    if (/^\s*\/\//.test(raw) || /^\s*\*/.test(raw)) continue;  // 行コメント/ブロック内注釈行はスキップ
    if (/background-attachment\s*:\s*fixed/i.test(code)) {
      add('style.css', i + 1, 'R3', 'background-attachment:fixed は iOS Safariで背景が崩れる → 使わない。');
    }
  }
  // body::before + z-index:-1 の組(数行以内)。コメントは上で除外済みの実コードのみ対象。
  const cssNoComment = css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  if (/body::before\b[\s\S]{0,200}z-index\s*:\s*-1/i.test(cssNoComment)) {
    add('style.css', 0, 'R3', 'body::before{…z-index:-1} は iOS SafariでHTML背景の後ろに落ちる → html{background} を使う。');
  }
} catch { /* style.css 無しは無視 */ }

if (findings.length) {
  console.error('✗ iOS Safari レイアウト検査で ' + findings.length + ' 件:');
  for (const x of findings) console.error(`  [${x.rule}] ${x.file}:${x.line}  ${x.msg}`);
  console.error('\n' + RECIPE);
  process.exit(1);
}
console.log('✓ iOS Safari レイアウト検査 OK(既知の落とし穴なし)');
