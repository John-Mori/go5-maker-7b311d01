#!/usr/bin/env node
/**
 * check_dup_helper.mjs — 同名ヘルパを「中身違い」でコピーする新規追加を出す前に止める門。《複製判断》
 *
 * なぜ在るか(2026-08-16・改善提案部門アスナ依頼 msg=1538540148478976020 / 型=docs/departments/kaizen-analyst/preflight_duplicate-helper.md commit 141e923):
 *   同じ判断関数(自前ドメイン判定・終端処理・フォールバック分岐)を同一ファイル内へ中身違いでコピーすると、
 *   後で片方だけ直したとき もう片方が古いまま残り、静かに挙動が割れる=「直したのに再発」の形でバグる。
 *   生きた乖離: js/yt-clicks.js の function isR2 が 4定義・2変種(1560/1598=同文, 3427/3487=別実装)。同型 INC-112/134/140。
 *   「心がけ」でなく「機構」で止める(共通規律§3 / 裁定C-038)。
 *
 * 検査の芯(型 §機械で止める案・save-path/CSS波及/番犬門と同じ思想):
 *   同一ファイル内で同名 function が2回以上定義され、本文(正規化後)が一致しない=乖離コピー なら赤。
 *   現在の重複はベースラインJSONへ凍結し、新規の乖離コピーだけを弾く(回帰ゼロ)。
 *
 * ★おまけ発注(型 §ベースライン): isR2 の2変種は go5.ourBase 一本へ寄せる一本化を推奨。実装は別コミットで判断。
 *
 * ベースライン更新: 意図して重複を1つ増やしたら DUMP=1 で吐いて scripts/check_dup_helper.baseline.json を更新する。
 *
 * 使い方:
 *   node scripts/check_dup_helper.mjs           問題があれば exit 1
 *   DUMP=1 node scripts/check_dup_helper.mjs     現状の重複(rel::name)をJSONで吐く(ベースライン更新用)
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIRS = ['js', 'core'];
const BASELINE_FILE = join(ROOT, 'scripts', 'check_dup_helper.baseline.json');

// コメント/文字列を同長の空白へ(改行は保つ)。' " は同一行で閉じた時だけ文字列扱い(正規表現内の引用符で暴走消去しない)。
function sanitize(src) {
  const out = src.split('');
  const blank = (a, b) => { for (let k = a; k < b; k++) if (out[k] !== '\n') out[k] = ' '; };
  let i = 0; const n = src.length;
  while (i < n) {
    const c = src[i], d = src[i + 1];
    if (c === '/' && d === '*') { let j = src.indexOf('*/', i + 2); j = j < 0 ? n : j + 2; blank(i, j); i = j; continue; }
    if (c === '/' && d === '/') { let j = src.indexOf('\n', i + 2); j = j < 0 ? n : j; blank(i, j); i = j; continue; }
    if (c === '"' || c === "'") {
      let j = i + 1, closed = false;
      while (j < n && src[j] !== '\n') { if (src[j] === '\\') { j += 2; continue; } if (src[j] === c) { closed = true; j++; break; } j++; }
      if (closed) { blank(i, j); i = j; continue; }
      i++; continue;
    }
    if (c === '`') { let j = i + 1; while (j < n) { if (src[j] === '\\') { j += 2; continue; } if (src[j] === '`') { j++; break; } j++; } blank(i, j); i = j; continue; }
    i++;
  }
  return out.join('');
}
function matchParen(san, open) { let d = 0; for (let k = open; k < san.length; k++) { const c = san[k]; if (c === '(') d++; else if (c === ')') { d--; if (d === 0) return k; } } return -1; }
function matchBrace(san, open) { let d = 0; for (let k = open; k < san.length; k++) { const c = san[k]; if (c === '{') d++; else if (c === '}') { d--; if (d === 0) return k; } } return -1; }
function lineOf(text, index) { return text.slice(0, index).split('\n').length; }

function listJs(dir) {
  const abs = join(ROOT, dir);
  if (!existsSync(abs)) return [];
  return readdirSync(abs).filter((f) => f.endsWith('.js')).map((f) => `${dir}/${f}`);
}

// 各ファイルから { name → [{line, body}] } を収集(function NAME(...) と NAME = function(...) の2形)。
function defsOf(rel) {
  const src = readFileSync(join(ROOT, rel), 'utf8');
  const san = sanitize(src);
  const defs = [];
  const re = /(?:\bfunction\s+([A-Za-z_$][\w$]*)\s*\(|\b([A-Za-z_$][\w$]*)\s*=\s*function\s*\()/g;
  let m;
  while ((m = re.exec(san)) !== null) {
    const name = m[1] || m[2];
    // マッチ m[0] は必ず '(' で終わる。その末尾の '(' を引数リスト開始とする。
    const po = san.lastIndexOf('(', m.index + m[0].length - 1);
    const paramClose = matchParen(san, po);
    if (paramClose < 0) continue;
    // 引数リストの後、最初の '{' を本文開始とする(アロー/式は対象外)。
    let b = paramClose + 1;
    while (b < san.length && /\s/.test(san[b])) b++;
    if (san[b] !== '{') continue;
    const bodyEnd = matchBrace(san, b);
    if (bodyEnd < 0) continue;
    const body = san.slice(b, bodyEnd + 1).replace(/\s+/g, ''); // 正規化(空白除去・コメント/文字列は既に空白)
    defs.push({ name, line: lineOf(src, m.index), body });
  }
  // name → defs
  const byName = new Map();
  for (const d of defs) { if (!byName.has(d.name)) byName.set(d.name, []); byName.get(d.name).push(d); }
  return byName;
}

// 全ファイルの (rel, name) ごとの定義群を集める
const all = []; // {rel, name, defs:[{line,body}], variants:Set}
for (const dir of DIRS) {
  for (const rel of listJs(dir)) {
    const byName = defsOf(rel);
    for (const [name, defs] of byName) {
      if (defs.length < 2) continue; // 重複のみ関心
      const variants = new Set(defs.map((d) => d.body));
      all.push({ rel, name, defs, variants });
    }
  }
}

if (process.env.DUMP) {
  // ベースライン= 現在 重複している (rel::name) すべて(乖離の有無を問わず凍結)
  const keys = [...new Set(all.map((x) => `${x.rel}::${x.name}`))].sort();
  console.log(JSON.stringify(keys, null, 2));
  process.exit(0);
}

let base = [];
try { base = JSON.parse(readFileSync(BASELINE_FILE, 'utf8')); }
catch { console.error(`NG: ${BASELINE_FILE} を読めなかった=ベースライン未整備。DUMP=1 で作れ。`); process.exit(1); }
const baseSet = new Set(base);

// 違反= 乖離(variants≥2)している重複で、ベースラインに無いもの
const violations = all.filter((x) => x.variants.size >= 2 && !baseSet.has(`${x.rel}::${x.name}`));

if (violations.length) {
  console.error('NG: 同名ヘルパを「中身違い」でコピーする新規の乖離があります(片方だけ直すと「直したのに再発」する・INC-112/134/140 の再発源):');
  for (const v of violations) {
    const lines = v.defs.map((d) => d.line).join(',');
    console.error(`  ${v.rel}  function ${v.name}  定義行=${lines}  変種=${v.variants.size}`);
  }
  console.error('  直し方: 既存の同名関数を呼ぶ(引数で差分を吸収)/共有なら core/ の1関数へ出典を寄せる/');
  console.error('          どうしても複製が要るなら全箇所へ同じコミットで同じ変更を当てる。');
  console.error('          意図した重複なら DUMP=1 node scripts/check_dup_helper.mjs で吐いて baseline.json を更新する。');
  process.exit(1);
}

console.log(`OK: 同名ヘルパの新規の乖離コピーなし(重複 ${baseSet.size}件 を据え置き)`);
