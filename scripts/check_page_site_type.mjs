#!/usr/bin/env node
/**
 * check_page_site_type.mjs — 新しいページを「サイト種別」を決めずに作らせない門。
 *
 * なぜ在るか(2026-11-03・Chami msg 1566918391460266096「この部屋の決まり見てから作ってって言ってるはず」・恒久/残念スタンプ):
 *   作品DBの作業場 WorksEdit.html を、本体と同じダーク#0e1422+ティール#2bb3c0 で新規に作って出した。
 *   着手前チェック §B では「分析・一覧系ツール=ダーク禁止・水色ボタン禁止」で、本体の色は「楽だから使っている既定で好みではない」。
 *   着手前チェックは依頼文の言葉(デザイン/画面/html 等)で自動添付される仕組みなので、
 *   「組むのやって」型の依頼で始まった作業には載らず、決まりを読まないまま本体の色を写した。
 *   読む/読まないを「心がけ」に任せず、ページ側に種別を書かせて機械で照合する。
 *
 * 検査の芯:
 *   1. 追跡中の .html(BASELINE と除外ディレクトリ以外)は <meta name="site-type" content="..."> を必ず持つ。無ければ赤。
 *      → 新しいページを作る時点で、着手前チェック §B のどの行に当たるかを決めないと push できない。
 *   2. site-type=list-tool(分析・一覧系)なら、地(--bg/--card/body の background)が暗い、
 *      またはティール系の色(#2bb3c0 系の青緑)が在れば赤。
 *
 * 種別(着手前チェック §B と1対1):
 *   main-canvas = 5秒動画メーカー本体(ダーク+ティール可)
 *   list-tool   = 分析・一覧系ツール(ダーク禁止・水色ボタン禁止)
 *   iyashi      = 癒やし倉庫(クリーム地)
 *   goods       = グッズアフィ系
 *   doc         = 手順書・ガイド・社外資料
 *
 * 使い方:
 *   node scripts/check_page_site_type.mjs            問題があれば exit 1
 *   node scripts/check_page_site_type.mjs a.html     指定ファイルだけ(BASELINE を無視して必ず検査=壊れた実物で赤を確かめる用)
 */
import { readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const TYPES = ['main-canvas', 'list-tool', 'iyashi', 'goods', 'doc'];
const SKIP_DIRS = ['産業廃棄物/', 'gas/', 'guide_HTML/', 'node_modules/'];

// ★BASELINE = 2026-11-03 時点で在るページ。据え置き(回帰ゼロ)。新しいページだけに種別を求める。
//   既存ページを直す時は、ここから外して meta を足すこと。
const BASELINE = new Set([
  'index.html', 'recovery.html', 'analytics.html', 'KouhoLists.html', 'KouhoTeian.html',
  'Stock.html', 'StockLists.html', 'YouTube再生数_APIキー取得ガイド.html',
  'persona-hub/icon.html', 'persona-hub/index.html', 'schedule/index.html', 'tools/vtomo_analyze/index.html',
]);

function hexToRgb(h) {
  h = h.replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  if (h.length !== 6) return null;
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}
function lum([r, g, b]) { return 0.2126 * r + 0.7152 * g + 0.0722 * b; }
function isTeal(rgb) {
  const [r, g, b] = rgb, mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  if (d < 0.2 || mx < 0.3) return false;
  let hue;
  if (mx === r) hue = 60 * (((g - b) / d) % 6);
  else if (mx === g) hue = 60 * ((b - r) / d + 2);
  else hue = 60 * ((r - g) / d + 4);
  if (hue < 0) hue += 360;
  return hue >= 165 && hue <= 200;
}

function check(file) {
  const src = readFileSync(join(ROOT, file), 'utf8').replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
  const m = src.match(/<meta\s+name=["']site-type["']\s+content=["']([\w-]+)["']/i);
  if (!m) return [`${file}: <meta name="site-type"> が無い。着手前チェック §B のどれか(${TYPES.join('/')})を決めて書くこと`];
  if (!TYPES.includes(m[1])) return [`${file}: site-type="${m[1]}" は未知。${TYPES.join('/')} のどれか`];
  if (m[1] !== 'list-tool') return [];
  const errs = [];
  const grounds = [
    ...[...src.matchAll(/--(?:bg|card)\s*:\s*(#[0-9a-f]{3,6})\b/gi)].map((x) => x[1]),
    ...[...src.matchAll(/(?:^|[}\s])body\s*\{[^}]*?background(?:-color)?\s*:\s*(#[0-9a-f]{3,6})\b/gi)].map((x) => x[1]),
  ];
  for (const c of grounds) {
    const rgb = hexToRgb(c);
    if (rgb && lum(rgb) < 0.35) errs.push(`${file}: list-tool なのに地が暗い(${c})。一覧系はダーク禁止(着手前チェック §B)`);
  }
  const teals = [...new Set([...src.matchAll(/#[0-9a-f]{6}\b|#[0-9a-f]{3}\b/gi)].map((x) => x[0].toLowerCase()))]
    .filter((c) => { const rgb = hexToRgb(c); return rgb && isTeal(rgb); });
  if (teals.length) errs.push(`${file}: list-tool なのにティール/水色系の色(${teals.join(',')})。一覧系は水色ボタン禁止(着手前チェック §B)`);
  return errs;
}

const args = process.argv.slice(2);
const files = args.length ? args : execSync('git ls-files -z -- "*.html"', { cwd: ROOT, encoding: 'utf8' })
  .split('\0').filter(Boolean)
  .filter((f) => !SKIP_DIRS.some((d) => f.startsWith(d)) && !BASELINE.has(f));
const errs = files.flatMap(check);
if (errs.length) {
  console.error(`✖ ページのサイト種別検査: ${errs.length}件\n  ` + errs.join('\n  '));
  process.exit(1);
}
console.log(`OK: ページのサイト種別検査(${files.length}ページ)`);
