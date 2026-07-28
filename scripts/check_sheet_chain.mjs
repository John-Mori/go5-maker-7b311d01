// scripts/check_sheet_chain.mjs — 「シート由来行の編集がリロードで消える」型の再発を出荷前に止める門。
//
// 【なぜ在るか】投稿履歴のシート由来行で編集した値がリロードで消える不具合が繰り返し起きた
//   (作品URL・投稿先/platform)。真因は毎回同じ構造=「編集モーダルで保存できる項目」が
//   フロント表示→GAS列→保存(putIf)→履歴返却(historyItems_)→保存確認(historyHasEdit)の
//   5つの繋ぎのどれか1つを欠くと、保存はできても再表示で復元できず「消えた」に見える。
//   1つ欠けるたびにChamiが実機で踏んで再依頼していた(2026-07-28〜29)。
//
// 【この門がする
//   こと】シート由来行で残さねばならない項目を CHAIN に列挙し、各項目について
//   ①GAS のヘッダ配列に列がある ②upsert に putIf がある ③historyItems_ が返す
//   ④hist-merge-core の表示変換が値を復元する——を静的に照合する。1つでも欠けたら fail。
//   新しい編集項目を足したら、この CHAIN にも足すこと(足さないと守られない)。
//
// 実行: node scripts/check_sheet_chain.mjs   (CI: smoke.yml の secret-guard ジョブ)
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');
const require = createRequire(import.meta.url);
const HM = require(join(root, 'hist-merge-core.js'));
const gas = readFileSync(join(root, 'gas', 'コード.gs'), 'utf8');

// シート由来行で「保存したらリロード後も残る」ことを保証する編集項目。
//   col     = GAS のシート列名(ヘッダ配列・putIf・historyItems_ の map キー)
//   histKey = historyItems_ が返すキー(GAS の返却オブジェクトのプロパティ名)
//   probe   = hist-merge-core の toDisplayItem_ へ渡すシート1行(このキーで値を入れる)
//   expect  = 表示アイテムのどのキーに、どんな値が復元されれば正か
const CHAIN = [
  { name: '作品URL(作品↗)', col: '作品URL', histKey: 'workUrl',
    probe: { workUrl: 'https://video.dmm.co.jp/av/content/?id=chainprobe' },
    expect: (it) => it.workUrl === 'https://video.dmm.co.jp/av/content/?id=chainprobe' },
  { name: '作品状態', col: '作品状態', histKey: 'workState',
    probe: { workState: '独占先行' }, expect: (it) => it.workState === '独占先行' },
  { name: '投稿先(X/Bsky)', col: '投稿先', histKey: 'platform',
    probe: { platform: 'x' }, expect: (it) => it.platform === 'x' },
  { name: '作品短縮URL(導線2)', col: '作品短縮URL', histKey: 'workShortUrl',
    probe: { workShortUrl: 'https://5mgl.com/Chain1' }, expect: (it) => it.workShortUrl === 'https://5mgl.com/Chain1' },
  { name: 'YouTube動画URL', col: 'YouTube動画URL', histKey: 'youtubeUrl',
    probe: { youtubeUrl: 'https://youtu.be/CHAINabc' }, expect: (it) => it.ytUrl === 'https://youtu.be/CHAINabc' }
];

// GAS のヘッダ配列(HEADERS40 / FANZA_HEADERS / EXTRA_HEADERS)の中身を1つの文字列に集める。
function headerBlob() {
  let blob = '';
  for (const name of ['HEADERS40', 'FANZA_HEADERS', 'EXTRA_HEADERS']) {
    const m = gas.match(new RegExp('var\\s+' + name + '\\s*=\\s*\\[([\\s\\S]*?)\\];'));
    if (m) blob += m[1];
  }
  return blob;
}
const HEADERS = headerBlob();

const fails = [];
for (const f of CHAIN) {
  // ① ヘッダ配列に列がある(map[col] が引ける前提)
  if (HEADERS.indexOf("'" + f.col + "'") < 0 && HEADERS.indexOf('"' + f.col + '"') < 0)
    fails.push(`${f.name}: GAS のヘッダ配列に列 '${f.col}' が無い(列が無いと map[col] が空で保存も復元も落ちる)`);
  // ② upsert に putIf('col', ...) がある(保存経路)
  if (gas.indexOf("putIf('" + f.col + "'") < 0 && gas.indexOf('putIf("' + f.col + '"') < 0)
    fails.push(`${f.name}: GAS upsert に putIf('${f.col}', …) が無い(編集値がシートへ書かれない)`);
  // ③ historyItems_ がそのキーを返す(再表示の入口)
  if (!new RegExp('\\b' + f.histKey + '\\s*:').test(gas))
    fails.push(`${f.name}: GAS historyItems_ が '${f.histKey}:' を返していない(シート由来行に値が来ない)`);
  // ④ hist-merge-core の表示変換が値を復元する(実行して確かめる)
  let it = null;
  try { it = HM._toDisplayItem({ videoId: 'chainprobe', ...f.probe }); } catch (e) {
    fails.push(`${f.name}: toDisplayItem_ が例外 (${e.message})`); continue;
  }
  if (!f.expect(it))
    fails.push(`${f.name}: hist-merge-core の表示変換が '${f.histKey}' を復元しない(保存できても再表示で消える)`);
}

if (fails.length) {
  console.error('シート由来行の保存連鎖に欠落があります(編集→保存→リロードで消える型の再発):');
  for (const m of fails) console.error('  ✗ ' + m);
  process.exit(1);
}
console.log(`OK: シート保存連鎖 ${CHAIN.length} 項目すべて フロント表示⇄GAS列⇄putIf⇄historyItems_⇄保存確認 が繋がっている`);
