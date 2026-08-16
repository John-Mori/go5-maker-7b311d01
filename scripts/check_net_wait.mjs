#!/usr/bin/env node
/**
 * check_net_wait.mjs — 「外へ出る待ちに時限が無い」新規コードを出す前に機械で止める門。《番犬》
 *
 * なぜ在るか(2026-08-16・改善提案部門アスナ依頼 msg=1538540148478976020 / 型=docs/departments/kaizen-analyst/preflight_net-wait-watchdog.md commit 141e923):
 *   fetch()/IndexedDB を「時限(AbortController・番犬タイマー)無し」で新規に書くと、応答が返らない時に
 *   「保存中…」「取得中…」が永久固着する。待ちに上限が無いコードは「たまに遅い」でなく「二度と返らない」になる。
 *   同型の固着インシデントが並ぶ= INC-108/116/125/132/134。js+core の fetch( は62箇所、番犬付きは3箇所だけ(実測2026-08-16)。
 *   「心がけ」でなく「機構」で止める(共通規律§3 / 裁定C-038)。
 *
 * 検査の芯(型 §機械で止める案・save-path/CSS波及門と同じ思想):
 *   現在の fetch 呼び出しと indexedDB.open をベースラインJSONへ凍結=据え置き(回帰ゼロ)。
 *   ・新規に増えた fetch が、同一関数内に AbortController/signal:/abort のいずれも持たない=裸 なら赤。
 *   ・core/idb-store.js 以外に新規の indexedDB.open( が増えたら赤(番犬済みの共通経路へ寄せる)。
 *
 * ベースライン更新: 意図して待ちを1つ増やしたら DUMP=1 で吐いて scripts/check_net_wait.baseline.json を更新する。
 *
 * 使い方:
 *   node scripts/check_net_wait.mjs           問題があれば exit 1
 *   DUMP=1 node scripts/check_net_wait.mjs     現状の {fetch:[], idbOpen:[]} をJSONで吐く(ベースライン更新用)
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIRS = ['js', 'core'];
const IDB_ALLOWED = 'core/idb-store.js'; // 番犬付きの共通IDB経路。ここへ寄せる。
const BASELINE_FILE = join(ROOT, 'scripts', 'check_net_wait.baseline.json');
// 待ちが時限とセットである印(型 §不変条件 I1)。時限ラッパを増やす時はここへ足す。
const WATCHDOG_RE = /AbortController|AbortSignal|signal\s*:|\.abort\s*\(/;

// ---- ソースの無害化(コメント/文字列を同長の空白へ。改行は保つ=行番号維持) ----
//   ' " は「同一行で閉じた時だけ」文字列扱い=正規表現内の引用符(/['"]/ 等)でファイル末尾まで暴走消去するのを防ぐ。
//   ` はテンプレートなので複数行を許す。正規表現リテラルは特別扱いしない(中の { ( はまず不均衡にならない)。
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
      i++; continue; // 同一行で閉じない=文字列ではない(正規表現等)。素通し。
    }
    if (c === '`') { let j = i + 1; while (j < n) { if (src[j] === '\\') { j += 2; continue; } if (src[j] === '`') { j++; break; } j++; } blank(i, j); i = j; continue; }
    i++;
  }
  return out.join('');
}
function matchBrace(san, open) { let d = 0; for (let k = open; k < san.length; k++) { const c = san[k]; if (c === '{') d++; else if (c === '}') { d--; if (d === 0) return k; } } return san.length; }
function matchParen(san, open) { let d = 0; for (let k = open; k < san.length; k++) { const c = san[k]; if (c === '(') d++; else if (c === ')') { d--; if (d === 0) return k; } } return -1; }

// fetch を含む「最も近い関数の本文」の範囲を返す(型が言う『同一関数内』の近似)。
function enclosingFunctionSpan(san, pos) {
  const stack = [];
  for (let k = 0; k < pos; k++) { const c = san[k]; if (c === '{') stack.push(k); else if (c === '}') stack.pop(); }
  for (let i = stack.length - 1; i >= 0; i--) {
    const open = stack[i];
    const pre = san.slice(Math.max(0, open - 40), open);
    if (/\bfunction\b/.test(pre) || /=>\s*$/.test(pre)) return [open, matchBrace(san, open)];
  }
  if (stack.length) { const open = stack[stack.length - 1]; return [open, matchBrace(san, open)]; }
  return [0, san.length];
}

function listJs(dir) {
  const abs = join(ROOT, dir);
  if (!existsSync(abs)) return [];
  return readdirSync(abs).filter((f) => f.endsWith('.js')).map((f) => `${dir}/${f}`);
}
function lineOf(text, index) { return text.slice(0, index).split('\n').length; }

// {fetch:[{sig,rel,line,naked}], idbOpen:[{sig,rel,line}]} を収集
function collect() {
  const fetchSites = [];
  const idbSites = [];
  for (const dir of DIRS) {
    for (const rel of listJs(dir)) {
      const src = readFileSync(join(ROOT, rel), 'utf8');
      const san = sanitize(src);
      let m;
      const fre = /\bfetch\s*\(/g;
      while ((m = fre.exec(san)) !== null) {
        const openParen = san.indexOf('(', m.index);
        const end = matchParen(san, openParen);
        const arg = end > 0 ? src.slice(openParen, end + 1) : src.slice(openParen, openParen + 80);
        const sig = `${rel}::${arg.replace(/\s+/g, ' ').trim()}`;
        const [s, e] = enclosingFunctionSpan(san, m.index);
        const naked = !WATCHDOG_RE.test(san.slice(s, e));
        fetchSites.push({ sig, rel, line: lineOf(src, m.index), naked });
      }
      const ire = /indexedDB\s*\.\s*open\s*\(/g;
      while ((m = ire.exec(san)) !== null) {
        const openParen = san.indexOf('(', m.index);
        const end = matchParen(san, openParen);
        const arg = end > 0 ? src.slice(openParen, end + 1) : src.slice(openParen, openParen + 80);
        idbSites.push({ sig: `${rel}::${arg.replace(/\s+/g, ' ').trim()}`, rel, line: lineOf(src, m.index) });
      }
    }
  }
  return { fetchSites, idbSites };
}

const { fetchSites, idbSites } = collect();

if (process.env.DUMP) {
  console.log(JSON.stringify({
    fetch: [...new Set(fetchSites.map((f) => f.sig))].sort(),
    idbOpen: [...new Set(idbSites.map((f) => f.sig))].sort(),
  }, null, 2));
  process.exit(0);
}

let base = { fetch: [], idbOpen: [] };
try { base = JSON.parse(readFileSync(BASELINE_FILE, 'utf8')); }
catch { console.error(`NG: ${BASELINE_FILE} を読めなかった=ベースライン未整備。DUMP=1 で作れ。`); process.exit(1); }
const baseFetch = new Set(base.fetch || []);
const baseIdb = new Set(base.idbOpen || []);

const violations = [];
for (const f of fetchSites) {
  if (baseFetch.has(f.sig)) continue;       // 既存=据え置き
  if (!f.naked) continue;                    // 番犬付きの新規=OK
  violations.push(`${f.rel}:${f.line}  裸のfetch(時限=AbortController/signal:/abort が同関数内に無い)`);
}
for (const f of idbSites) {
  if (f.rel === IDB_ALLOWED) continue;       // 番犬付きの共通経路=OK
  if (baseIdb.has(f.sig)) continue;          // 既存=据え置き
  violations.push(`${f.rel}:${f.line}  直の indexedDB.open(=番犬済みの ${IDB_ALLOWED} 経由にする`);
}

if (violations.length) {
  console.error('NG: 時限(番犬)の無い待ちを新規追加しています(応答が返らない時「保存中…」が永久固着する・INC-108/116/125/132/134 の再発源):');
  for (const v of violations) console.error(`  ${v}`);
  console.error('  直し方: fetch は AbortController+setTimeout(()=>ctrl.abort(),N) とセットで書くか時限ラッパを通す。');
  console.error(`          IDB は ${IDB_ALLOWED} の共通ストア経由にする。「…中」表示は時限到達で必ず戻す枝を同コミットで書く。`);
  console.error('          意図した新規の待ちなら DUMP=1 node scripts/check_net_wait.mjs で吐いて baseline.json を更新する。');
  process.exit(1);
}

console.log(`OK: 時限無しの待ちの新規混入なし(fetch ${baseFetch.size}件 / idbOpen ${baseIdb.size}件 を据え置き)`);
