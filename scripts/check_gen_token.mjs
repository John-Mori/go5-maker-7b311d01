#!/usr/bin/env node
/**
 * check_gen_token.mjs — 共有状態へ非同期で書く時の「世代トークン(stale-guard)」の欠落を出す前に止める門《世代トークン》。
 *
 * なぜ在るか(2026-08-18・改善提案部門アスナ→AD研究室モドリッチ→改修α / 型=docs/departments/kaizen-analyst/preflight_generation-token-on-shared-write.md):
 *   共有状態(前景画像・一覧DOM・録画Blob・作品情報の行など「後から非同期に書き込む先」)へ、複数の非同期継続が
 *   "世代照合なし"で書き込むと、遅く完了した古い応答が新しい状態を上書きする(前の画像が残る/別作品に化ける/黒い無言箱)。
 *   解法は毎回同じ(採番→書く直前に最新世代か確認→古ければ捨てる)なのに、事故のたびに別の関数で再実装している
 *   =INC-07(取得ジョブ)/INC-15(作品情報行)/INC-135(候補→動画作成の画像読込)/INC-139(録画Blobの着地)。
 *   INC-140「同じ判断・終端・フォールバックを複数箇所にコピーするな」がそのまま芯。「心がけ」でなく「機構」で止める(§3/C-038)。
 *
 * 検査の芯(型 §機械で見る案・番犬門/CSS波及門/複製判断門と同じ「新規混入だけ止める」思想):
 *   grep一発は不可(onload代入/then は正当な使い方が大多数=有無だけでは撃てない)。だから
 *   「世代管理が必須の書き込み先」の登録簿(scripts/check_gen_token.baseline.json)を正とする。
 *     I1: counters の各カウンタは『採番(=++X を local へ控える)』と『照合(myGen(!==|===)X で古い世代を破棄)』の両方を持つ(片方でも欠けたら赤)。
 *     I3: 同じ状態のカウンタは1本(宣言が2つ以上=世代の分裂 なら赤)。
 *     新規混入: js/・core/ に新しい *Seq/*Gen カウンタ(宣言 + ++)が増え、登録簿(counters/id_counter_allow)に無ければ赤。
 *              →『stale-guardなら採番+照合の対で書き counters へ / 一意ID採番なら id_counter_allow へ』登録を強制する。既存は据え置き=回帰ゼロ。
 *
 * 使い方:
 *   node scripts/check_gen_token.mjs            問題があれば exit 1(CI: smoke.yml の secret-guard ジョブ)
 *   DUMP=1 node scripts/check_gen_token.mjs     現状のカウンタ(file::name)をJSONで吐く(登録簿更新用)
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIRS = ['js', 'core'];
const BASELINE_FILE = join(ROOT, 'scripts', 'check_gen_token.baseline.json');

// コメント/文字列を同長の空白へ(改行は保つ)。'"` は閉じた時だけ文字列扱い。※check_dup_helper.mjs と同じ土台。
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
function lineOf(text, index) { return text.slice(0, index).split('\n').length; }
function listJs(dir) {
  const abs = join(ROOT, dir);
  if (!existsSync(abs)) return [];
  return readdirSync(abs).filter((f) => f.endsWith('.js')).map((f) => `${dir}/${f}`);
}

// ── ファイルから「カウンタ」を検出する ────────────────────────────────────────
//   カウンタ = 名前が /(Seq|Gen)$/ で、宣言(let/var/const X = ) と 増分(++X / X++) の両方を持つ識別子。
//   ※ loadSeq/myGen 等の『= ++counter で控える local』は ++ の対象ではない=カウンタに含めない(採番の控え側)。
function countersOf(rel, san) {
  const declared = new Map(); // name → 宣言行(最初)
  const declRe = /\b(?:let|var|const)\s+([A-Za-z_$][\w$]*(?:Seq|Gen))\b/g;
  let m;
  while ((m = declRe.exec(san)) !== null) if (!declared.has(m[1])) declared.set(m[1], lineOf(san, m.index));
  const incremented = new Set();
  const incRe = /(?:\+\+\s*([A-Za-z_$][\w$]*(?:Seq|Gen))\b|\b([A-Za-z_$][\w$]*(?:Seq|Gen))\s*\+\+)/g;
  while ((m = incRe.exec(san)) !== null) incremented.add(m[1] || m[2]);
  const out = [];
  for (const [name, line] of declared) if (incremented.has(name)) out.push({ name, line });
  return out;
}

// ── 採番(=++X を local へ控える)が在るか ─────────────────────────────────────
function hasMintCapture(san, name) {
  // const/var/let Y = ++X   /   Y = ++X   /   Y = X++
  const re = new RegExp('(?:\\b(?:let|var|const)\\s+[A-Za-z_$][\\w$]*|[A-Za-z_$][\\w$]*)\\s*=\\s*(?:\\+\\+\\s*' + name + '\\b|' + name + '\\s*\\+\\+)');
  return re.test(san);
}
// ── 照合(myGen (!==|===|!=|==) X。ただし ++/-- を巻き込まない)が在るか ─────────
function hasGuardCompare(san, name) {
  const re = new RegExp('(?:[A-Za-z_$][\\w$]*\\s*(?:!==|===|!=|==)\\s*' + name + '\\b|\\b' + name + '\\s*(?:!==|===|!=|==)\\s*[A-Za-z_$][\\w$]*)');
  // 前後に + が付く(++X === / X++ 等)誤検出を避けるため、比較の左右いずれかが name 単体であることは正規表現側で担保済み。
  return re.test(san);
}
// ── I3: 同じ状態カウンタの宣言が1本か(let/var の宣言回数) ─────────────────────
function declCount(san, name) {
  const re = new RegExp('\\b(?:let|var|const)\\s+' + name + '\\b', 'g');
  return (san.match(re) || []).length;
}

// ── 全 js/・core/ を走査してカウンタを集める ─────────────────────────────────
const found = []; // {rel, name, line}
const sanByRel = new Map();
for (const dir of DIRS) for (const rel of listJs(dir)) {
  const san = sanitize(readFileSync(join(ROOT, rel), 'utf8'));
  sanByRel.set(rel, san);
  for (const c of countersOf(rel, san)) found.push({ rel, name: c.name, line: c.line });
}

if (process.env.DUMP) {
  console.log(JSON.stringify(found.map((f) => `${f.rel}::${f.name}`).sort(), null, 2));
  process.exit(0);
}

let reg;
try { reg = JSON.parse(readFileSync(BASELINE_FILE, 'utf8')); }
catch { console.error(`NG: ${BASELINE_FILE} を読めなかった=登録簿が未整備。DUMP=1 で吐いて作れ。`); process.exit(1); }

const counters = reg.counters || [];
const idAllow = reg.id_counter_allow || [];
const regKey = (x) => `${x.file}::${x.name}`;
const counterSet = new Set(counters.map(regKey));
const idAllowSet = new Set(idAllow.map(regKey));

const fails = [];

// (1) 新規混入: 見つかったカウンタが登録簿(counters/id_counter_allow)のどちらにも無い
for (const f of found) {
  const key = `${f.rel}::${f.name}`;
  if (counterSet.has(key) || idAllowSet.has(key)) continue;
  fails.push(`【新規混入】${f.rel}:${f.line} の世代/連番カウンタ '${f.name}' が登録簿に無い`
    + `(共有状態への stale-guard なら『採番(++${f.name}をlocalへ控える)＋照合(myGen!==${f.name}で古い世代を破棄)』の対で書き counters へ、`
    + `一意ID採番用の連番なら id_counter_allow へ、scripts/check_gen_token.baseline.json に登録せよ=「入れた」で閉じさせないため)`);
}

// (2) I1+I3: 登録簿 counters の各カウンタが 採番＋照合 の対を持ち、宣言が1本か
for (const c of counters) {
  const san = sanByRel.get(c.file);
  if (!san) { fails.push(`${c.file}::${c.name}: 登録簿のファイル ${c.file} が js/・core/ に見つからない(登録簿が実体とズレている)`); continue; }
  const present = found.some((f) => f.rel === c.file && f.name === c.name);
  if (!present) { fails.push(`${c.file}::${c.name}: 登録済みカウンタ '${c.name}'(宣言+増分)が実体に無い(削除/改名したなら登録簿からも外せ)`); continue; }
  if (!hasMintCapture(san, c.name))
    fails.push(`${c.file}::${c.name}: 採番が無い=『(const/var) myGen = ++${c.name}』で発行時に世代を控えていない(I1・遅着を後で照合できない)`);
  if (!hasGuardCompare(san, c.name))
    fails.push(`${c.file}::${c.name}: 照合が無い=『if (myGen !== ${c.name}) return』等で書く直前に世代を確認していない(I1/I2・古い応答が新しい状態を上書きする)`);
  const dc = declCount(san, c.name);
  if (dc !== 1)
    fails.push(`${c.file}::${c.name}: カウンタ宣言が ${dc} 本(I3・同じ状態の世代は1本に束ねる。分裂すると切替で片方だけ進み stale判定が崩れる)`);
}

// (3) id_counter_allow の腐り防止: 登録した連番が実在するか(消えたなら登録簿から外させる)
for (const a of idAllow) {
  if (!found.some((f) => f.rel === a.file && f.name === a.name))
    fails.push(`${a.file}::${a.name}: id_counter_allow に登録された連番 '${a.name}' が実体に無い(消えたなら scripts/check_gen_token.baseline.json から外せ)`);
}

if (fails.length) {
  console.error('世代トークン(共有状態への stale-guard)に欠落があります(古い応答が新しい状態を上書きする型・INC-07/15/135/139 の再発源):');
  for (const f of fails) console.error('  ✗ ' + f);
  console.error('  直し方: 状態ごとに世代カウンタを1本決め、非同期発行時に myGen=++gen を控え、書く直前に if(myGen!==gen)return で古い応答を捨てる。');
  console.error('          意図した新規カウンタなら DUMP=1 node scripts/check_gen_token.mjs で吐いて登録簿へ分類登録する。');
  process.exit(1);
}
console.log(`OK: 世代トークン ${counters.length}本 すべて 採番＋照合 の対を持ち、状態ごとに1本(I1/I3)。一意ID採番 ${idAllow.length}本 は照合不要として据え置き。新規の未登録カウンタなし。`);
