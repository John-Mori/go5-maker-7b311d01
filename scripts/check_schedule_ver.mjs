#!/usr/bin/env node
// check_schedule_ver.mjs — カレンダー iframe(schedule/)の「版ずれ」を機械で止める門。
//
// なぜ要るか:
//   schedule/ は本体 index.html とは別に、自前の ?v= を持つ独立バンプ領域だ。
//   `node scripts/bump.mjs` は本体65参照だけを揃え、schedule/ の版には一切触れない。
//   そのため schedule/js/*.js や css/style.css を直しても、
//     ① schedule/index.html 内の ?v= を上げ忘れる / ② affiliate.js の iframe src ?v= を上げ忘れる
//   と、スマホは古い calendar のまま(=Chamiには「直ってない」と映る)。CIの既存スモークは
//   本体 index.html の版一致しか見ておらず、この iframe の版は無検査だった(2026-08-06朝レビュー実装)。
//
// 仕組み(心がけでなく機構):
//   schedule/.verstamp.json に「各キャッシュバスト資産の版と内容ハッシュ」を焼く。
//   資産の中身が変わったのに版が据え置きなら CI が落ちる=版を上げるまで出せない。
//   使い方:  node scripts/check_schedule_ver.mjs          … 検査(CI/コミット前)
//            node scripts/check_schedule_ver.mjs --stamp  … 版を上げた後に基準を焼き直す
//
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const STAMP = join(ROOT, 'schedule', '.verstamp.json');
const SCH_INDEX = join(ROOT, 'schedule', 'index.html');
const AFFILIATE = join(ROOT, 'affiliate.js');

const sha = (buf) => createHash('sha256').update(buf).digest('hex').slice(0, 16);

// schedule/index.html の <link>/<script ...?v=N> を全部拾う(相対パスと版)
function scheduleAssets() {
  const html = readFileSync(SCH_INDEX, 'utf8');
  const out = {};
  const re = /(?:href|src)="((?:css|js)\/[^"?]+)\?v=(\d+)"/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const rel = m[1], v = Number(m[2]);
    const abs = join(ROOT, 'schedule', rel);
    if (!existsSync(abs)) { console.error(`::error::schedule/index.html が存在しない資産を参照: ${rel}`); process.exit(2); }
    out[rel] = { v, sha: sha(readFileSync(abs)) };
  }
  return out;
}

// affiliate.js の iframe src(schedule/index.html?v=N)の版
function iframeVersion() {
  const js = readFileSync(AFFILIATE, 'utf8');
  const m = js.match(/schedule\/index\.html\?v=(\d+)/);
  if (!m) { console.error('::error::affiliate.js に schedule/index.html?v=N が見つからない'); process.exit(2); }
  return Number(m[1]);
}

const current = { iframe: iframeVersion(), assets: scheduleAssets() };
const doStamp = process.argv.includes('--stamp');
const prev = existsSync(STAMP) ? JSON.parse(readFileSync(STAMP, 'utf8')) : null;

// 版据え置きなのに中身が変わった資産(=版ずれの本体)を洗い出す
function staleAssets(base) {
  if (!base) return [];
  const bad = [];
  for (const [rel, cur] of Object.entries(current.assets)) {
    const b = base.assets[rel];
    if (b && b.v === cur.v && b.sha !== cur.sha) bad.push(rel);
  }
  return bad;
}

if (doStamp) {
  const stale = staleAssets(prev);
  if (stale.length) {
    console.error('::error::中身が変わったのに ?v= が据え置きの資産があります。先に schedule/index.html の版を上げてから --stamp してください:');
    stale.forEach((r) => console.error('  - ' + r));
    process.exit(1);
  }
  writeFileSync(STAMP, JSON.stringify(current, null, 2) + '\n');
  console.log('OK: schedule/.verstamp.json を焼き直しました(iframe v=' + current.iframe + ')');
  process.exit(0);
}

// 検査モード
if (!prev) {
  console.error('::error::schedule/.verstamp.json が無い。初回は `node scripts/check_schedule_ver.mjs --stamp` で基準を焼いてください');
  process.exit(1);
}
const stale = staleAssets(prev);
if (stale.length) {
  console.error('::error::カレンダー(schedule/)の中身が変わったのに ?v= が据え置きです(スマホが古い calendar を読む版ずれ)。該当:');
  stale.forEach((r) => console.error('  - ' + r + ' の ?v= を schedule/index.html で上げ、affiliate.js の iframe 版も上げてから `--stamp`'));
  process.exit(1);
}
const changed = JSON.stringify(prev) !== JSON.stringify(current);
if (changed) {
  console.error('::error::schedule/ の版/内容が verstamp と一致しません。版を上げたなら `node scripts/check_schedule_ver.mjs --stamp` で基準を更新してコミットしてください');
  process.exit(1);
}
console.log('OK: カレンダー(schedule/)の版ずれなし(iframe v=' + current.iframe + '・資産 ' + Object.keys(current.assets).length + '本)');
