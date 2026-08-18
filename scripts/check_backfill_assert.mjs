// scripts/check_backfill_assert.mjs — 「後埋まり列を直したと言うが、実データで埋まるのを見ていない」型の再発を出荷前に止める門《実物着地》。
//
// 【なぜ在るか】GAS記録シートの「後から埋まる列」(ピーク値・成約・クリック数・いいね/リポスト等、
//   改修後N時間経って毎時トリガーが実データで初めて埋める列)を埋める改修が、`"列名" in src` の
//   ソース文字列一致や「入れた」だけで『直った』と報告されて閉じられていた。実物=シートの当該列が
//   非空になったかを見ていない。実測=ピーク列は 8/2・8/6・8/11 と3回改修しても 8/15 にChamiが
//   「(ピーク値が)5回言ってる」で🔥(型=docs/departments/kaizen-analyst/preflight_claimed-fix-realdata-assert.md)。
//
// 【この門がすること】後埋まり列の唯一の登録簿 scripts/backfill_columns.json を正として、
//   ① 各登録列が GAS のヘッダ(PEAK_HEADERS/STATS_HEADERS/TIMEPOINT_HEADERS/記録シートヘッダ)に在る
//   ② 各登録列を N時間後に埋める writer 関数が GAS に在り、その列を実際に書いている
//   ③ 各登録列が読取口 backfillProbe_(GAS action=backfill_probe) に載っている
//      =b面(改善提案部門アスナの Z2運用ツール)が「N時間後に非空か」を外から突き合わせられる口が在る
//   ④【新規混入検知】後埋まり列を新規に GAS へ足したのに登録簿へ足していない=実データassert無しの
//      commit を落とす。header配列(PEAK/STATS/TIMEPOINT)の非空metric列・writer の map['列']).setValue
//      書き込み先で、登録簿にも allowlist にも無い列が在れば fail。
//   これで「入れた」で閉じられない=実データで非空を見る(backfill_probe)まで assert の対象に残る。
//
// 実行: node scripts/check_backfill_assert.mjs   (CI: smoke.yml の secret-guard ジョブ)
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');
const gas = readFileSync(join(root, 'gas', 'コード.gs'), 'utf8');
const reg = JSON.parse(readFileSync(join(__dirname, 'backfill_columns.json'), 'utf8'));

const fails = [];

// ── ヘッダ配列リテラルの中身(要素の配列)を取り出す ─────────────────────
function headerArray(name) {
  const m = gas.match(new RegExp('var\\s+' + name + '\\s*=\\s*\\[([\\s\\S]*?)\\];'));
  if (!m) return null;
  return m[1].split(',').map(s => s.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
}
// 記録シート(月詠み/宵桜艶帖)のヘッダは HEADERS40/FANZA_HEADERS/EXTRA_HEADERS の合成。
function recordHeaderBlob() {
  let blob = '';
  for (const name of ['HEADERS40', 'FANZA_HEADERS', 'EXTRA_HEADERS']) {
    const arr = headerArray(name);
    if (arr) blob += '' + arr.join('') + '';
  }
  return blob;
}
const RECORD_BLOB = recordHeaderBlob();

// ── 関数本体を切り出す(次の同レベル `function ` 直前まで) ────────────────
function fnBody(name) {
  const key = 'function ' + name;
  const i = gas.indexOf(key);
  if (i < 0) return null;
  const rest = gas.slice(i + key.length);
  const j = rest.indexOf('\nfunction ');
  return j < 0 ? rest : rest.slice(0, j);
}

// ── 読取口 backfillProbe_ の本体(③の検査対象) ───────────────────────────
const PROBE_BODY = fnBody('backfillProbe_');
if (!PROBE_BODY)
  fails.push('GAS に読取口 backfillProbe_ が無い(③b面がN時間後の非空を外から確かめる口=action=backfill_probe が塞がれる)');

// ── ① ② ③ 登録簿の各列を検査 ────────────────────────────────────────────
for (const c of reg.columns) {
  const where = `${c.sheet}:${c.col}`;
  // ① ヘッダに列が在る
  if (c.header_array) {
    const arr = headerArray(c.header_array);
    if (!arr) fails.push(`${where}: ヘッダ配列 ${c.header_array} が GAS に見つからない`);
    else if (!arr.includes(c.col)) fails.push(`${where}: ${c.header_array} に列 '${c.col}' が無い(列が無ければ書き込み先が無い)`);
  } else {
    if (RECORD_BLOB.indexOf('' + c.col + '') < 0)
      fails.push(`${where}: 記録シートのヘッダ(HEADERS40/FANZA_HEADERS/EXTRA_HEADERS)に列 '${c.col}' が無い`);
  }
  // ② writer 関数が在り、その列を実際に書いている
  const body = fnBody(c.writer);
  if (!body) {
    fails.push(`${where}: writer 関数 ${c.writer} が GAS に無い(N時間後にこの列を埋める主体が居ない)`);
  } else {
    // 索引書き込み(setValues でヘッダ配列の列位置へ) or map['列']).setValue or 短縮URLクリック数(clickColName_)経由
    const writesByIndex = !!c.header_array && (body.indexOf('setValue') >= 0);
    const writesByMap = body.indexOf("map['" + c.col + "']") >= 0 || body.indexOf('map["' + c.col + '"]') >= 0;
    const writesClick = c.col === '短縮URLクリック数' && body.indexOf('clickColName_') >= 0;
    if (!writesByIndex && !writesByMap && !writesClick)
      fails.push(`${where}: writer ${c.writer} が列 '${c.col}' を書いている形跡が無い(登録簿の writer が実体とズレている)`);
  }
  // ③ 読取口が列を報告している(b面の突き合わせ対象になっているか)
  if (PROBE_BODY && PROBE_BODY.indexOf("'" + c.col + "'") < 0 && PROBE_BODY.indexOf('"' + c.col + '"') < 0)
    fails.push(`${where}: 読取口 backfillProbe_ が列 '${c.col}' を報告していない(③b面がこの列のN時間後の非空を確かめられない)`);
}

// ── ④ 新規混入検知(A): header配列の metric列で、登録簿にも allowlist にも無いもの ──────
const registeredByArray = {};
for (const c of reg.columns) if (c.header_array) (registeredByArray[c.header_array] ||= new Set()).add(c.col);
for (const arrName of ['PEAK_HEADERS', 'STATS_HEADERS', 'TIMEPOINT_HEADERS']) {
  const arr = headerArray(arrName);
  if (!arr) continue;
  const allow = new Set(reg.identity_or_timestamp_allow[arrName] || []);
  const registered = registeredByArray[arrName] || new Set();
  for (const col of arr) {
    if (allow.has(col) || registered.has(col)) continue;
    fails.push(`【新規混入】${arrName} の列 '${col}' が後埋まり列の登録簿にも allowlist にも無い(新しい後埋まり列を足したなら scripts/backfill_columns.json へ実データassertを登録せよ=「入れた」で閉じさせないため)`);
  }
}
// ── ④ 新規混入検知(B): 記録シート writer の map['列']).setValue 書き込み先 ─────────────
const RECORD_REGISTERED = new Set(reg.columns.filter(c => c.sheet === '記録').map(c => c.col));
const TS_ALLOW = new Set(['クリック更新日時', '反応更新日時', 'クリック更新日時', '投稿日時']);
for (const wname of ['refreshClicks', 'refreshEngagement']) {
  const body = fnBody(wname);
  if (!body) continue;
  const re = /map\[(['"])([^'"]+)\1\]\)\.setValue/g;
  let m;
  while ((m = re.exec(body))) {
    const col = m[2];
    if (TS_ALLOW.has(col) || RECORD_REGISTERED.has(col)) continue;
    fails.push(`【新規混入】記録シート writer ${wname} が列 '${col}' を setValue で書いているが後埋まり列の登録簿に無い(scripts/backfill_columns.json へ登録し実データで非空を確かめる対象にせよ)`);
  }
}

if (fails.length) {
  console.error('後埋まり列の実データassertに欠落があります(「入れた」で閉じて実データ非空を見ていない型の再発):');
  for (const f of fails) console.error('  ✗ ' + f);
  process.exit(1);
}
console.log(`OK: 後埋まり列 ${reg.columns.length} 列すべて ヘッダ在⇄writer書込⇄読取口(backfill_probe)報告 が繋がっている`);
console.log('OK: 新規混入検知(header配列 PEAK/STATS/TIMEPOINT + 記録writer setValue)= 未登録の後埋まり列なし');
