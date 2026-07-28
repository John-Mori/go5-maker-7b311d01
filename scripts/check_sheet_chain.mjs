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
// 【④の穴を塞ぐ ⑤=保存完成ゲートの往復アサート(2026-07-29 改善提案部門トトリ指摘)】
//   ①〜④は「繋ぎが在るか」の静的照合だが、実際の再発は「保存の確認(検証)の段そのものが失敗する」
//   ——保存はできているのに historyHasEdit(=保存完成の判定ゲート)が cid を復元できない階層で
//   永遠に false を返し「反映を確認できませんでした」と出て、Chami には保存が効いていないように見えた
//   (commit 4b965ca の自白)。静的に繋ぎが在っても、このゲートが誤って弾けば症状は再発する。
//   そこで作品URLの各 cid 階層(同人 d_* / Books 数字 / FANZA動画 cid= / FANZA動画 cid無し ?id=)について
//   「保存→再読込相当の行 → 完成ゲート historyHasEdit が true を返し、かつ表示 workUrl が入力と一致するか」
//   を実際に走らせて往復で確かめる。1階層でもゲートが弾いたら fail=「直った」を出す前にここで止まる。
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

// ⑤ 保存完成ゲートの往復アサート。作品URLの各 cid 階層で「保存→再読込相当→完成ゲート＋表示」を実行。
//   reloaded = GAS が upsert 後の action=history で返す1行を模す(生の 作品URL 列＋GAS が持つ cid)。
//   FANZA動画の cid 無し(?id=)は wantCid が空になり、旧来の cid 照合だけのゲートだと保存できても永遠に
//   false=これが 07-29 に5回再発した本体。生 workUrl 列の一致で true にならなければここで fail。
const ROUNDTRIP = [
  { name: '同人 d_*',        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_rt001/' },
  { name: 'Books 数字',      url: 'https://book.dmm.com/product/778899/' },
  { name: 'FANZA動画 cid=',  url: 'https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=ssis00777/' },
  { name: 'FANZA動画 cid無し', url: 'https://video.dmm.co.jp/av/content/?id=rtnocid' } // ← 4b965ca の再発本体
];
for (const r of ROUNDTRIP) {
  const vid = 'rtprobe';
  // 保存→再読込相当: GAS が返す行 = 生の作品URL列 + GAS が保持する cid(復元不能階層では空)。
  const reloaded = { videoId: vid, workUrl: r.url, cid: HM.workCidFromUrl(r.url), workState: '旧作' };
  const expected = { videoId: vid, workUrl: r.url, workState: '旧作' };
  // (a) 保存完成ゲートが true を返すか(=「反映を確認できませんでした」を出さないか)
  let gateOk = false;
  try { gateOk = !!(HM.historyHasEdit && HM.historyHasEdit([reloaded], expected)); } catch (e) {
    fails.push(`往復[${r.name}]: historyHasEdit が例外 (${e.message})`);
  }
  if (!gateOk)
    fails.push(`往復[${r.name}]: 保存完成ゲート historyHasEdit が false(保存できても「反映を確認できませんでした」と出て消えたように見える=07-29の再発型)`);
  // (b) リロード後の表示 workUrl が入力と一致するか
  let disp = null;
  try { disp = HM._toDisplayItem(reloaded); } catch (e) { fails.push(`往復[${r.name}]: toDisplayItem_ が例外 (${e.message})`); continue; }
  if (!disp || disp.workUrl !== r.url)
    fails.push(`往復[${r.name}]: 再読込後の表示 workUrl が入力と不一致(期待 ${r.url} / 実際 ${disp && disp.workUrl})`);
}

if (fails.length) {
  console.error('シート由来行の保存連鎖に欠落があります(編集→保存→リロードで消える型の再発):');
  for (const m of fails) console.error('  ✗ ' + m);
  process.exit(1);
}
console.log(`OK: シート保存連鎖 ${CHAIN.length} 項目すべて フロント表示⇄GAS列⇄putIf⇄historyItems_⇄保存確認 が繋がっている`);
console.log(`OK: 保存完成ゲートの往復アサート ${ROUNDTRIP.length} 階層すべて 保存→再読込→historyHasEdit(true)＋表示一致 を通過`);
