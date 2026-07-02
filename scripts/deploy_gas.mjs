// deploy_gas.mjs — gas/コード.gs をクラウドの GAS Web App へ自動反映する（依存パッケージなし）。
//
//   node scripts/deploy_gas.mjs            通常反映（push→デプロイID固定で再デプロイ→検証→後処理）
//   node scripts/deploy_gas.mjs --check    dry-run（稼働版 vs ローカル版のバージョン比較だけ）
//   node scripts/deploy_gas.mjs --force    バージョンが同じでも反映を強行
//
// 前提: scripts/gas_deploy_config.json（GAS初期設定.bat が生成）と clasp login 済み。
// exec URL は不変（既存デプロイIDに新バージョンを当てるため）。

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CONFIG_PATH = join(ROOT, 'scripts', 'gas_deploy_config.json');
const CODE_PATH = join(ROOT, 'gas', 'コード.gs');
const CLASP_JSON = join(ROOT, '.clasp.json');

const argv = process.argv.slice(2);
const isCheck = argv.includes('--check');
const isForce = argv.includes('--force');

function die(msg) { console.error('\n❌ ' + msg + '\n'); process.exit(1); }
function ok(msg) { console.log('✅ ' + msg); }
function info(msg) { console.log('   ' + msg); }
function mask(s) { s = String(s || ''); return s.length <= 8 ? '****' : s.slice(0, 6) + '…(' + s.length + '文字)'; }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- 設定読込 ----
if (!existsSync(CONFIG_PATH)) {
  die('scripts/gas_deploy_config.json がありません。\n   先に「GAS初期設定.bat」（bootstrap_gas.mjs）を実行してください。');
}
let cfg;
try { cfg = JSON.parse(readFileSync(CONFIG_PATH, 'utf8')); }
catch (e) { die('gas_deploy_config.json が壊れています: ' + e.message); }
for (const k of ['scriptId', 'deploymentId', 'execUrl']) {
  if (!cfg[k]) die('gas_deploy_config.json に "' + k + '" がありません。GAS初期設定.bat をやり直してください。');
}
const adminSecret = cfg.adminSecret || '';

// ---- ローカル GAS_VERSION をパース ----
if (!existsSync(CODE_PATH)) die('gas/コード.gs が見つかりません。');
const codeSrc = readFileSync(CODE_PATH, 'utf8');
const mVer = /var\s+GAS_VERSION\s*=\s*'([^']+)'/.exec(codeSrc);
if (!mVer) die("gas/コード.gs 内に GAS_VERSION が見つかりません（var GAS_VERSION = '…';）。");
const localVer = mVer[1];
info('スクリプトID : ' + mask(cfg.scriptId));
info('デプロイID   : ' + mask(cfg.deploymentId));
info('ローカル版   : ' + localVer);

// ---- exec URL の ?ping=1 で稼働中バージョンを取得（302追従＋JSON検証）----
async function fetchPing() {
  const url = cfg.execUrl + (cfg.execUrl.includes('?') ? '&' : '?') + 'ping=1';
  const res = await fetch(url, { redirect: 'follow', headers: { 'cache-control': 'no-cache' } });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); }
  catch (e) {
    throw new Error('?ping=1 が JSON を返しませんでした（HTMLログインページ等）。\n' +
      '   → Web App のアクセス設定が「全員（匿名を含む）」になっているか確認してください。\n' +
      '   先頭: ' + text.slice(0, 120).replace(/\s+/g, ' '));
  }
  if (!data || !data.version) throw new Error('?ping=1 の応答に version がありません: ' + text.slice(0, 200));
  return data.version;
}

// ---- clasp 実行ヘルパ ----
function clasp(args, opts = {}) {
  const r = spawnSync('npx', ['--yes', '@google/clasp', ...args], {
    cwd: ROOT, stdio: opts.capture ? 'pipe' : 'inherit', encoding: 'utf8', shell: process.platform === 'win32'
  });
  if (r.error) die('clasp の起動に失敗しました: ' + r.error.message);
  return r;
}
function assertClaspLogin() {
  // 認証情報が無いと push/deploy が対話待ちになるため事前にガード。
  const home = process.env.HOME || process.env.USERPROFILE || '';
  if (home && !existsSync(join(home, '.clasprc.json'))) {
    die('clasp にログインしていません。\n   「GAS初期設定.bat」を実行して Google 承認を済ませてください。');
  }
}

async function main() {
  let liveVer;
  try { liveVer = await fetchPing(); }
  catch (e) { die('稼働中バージョンの取得に失敗しました。\n   ' + e.message); }
  info('稼働中版     : ' + liveVer);

  if (isCheck) {
    console.log('');
    if (liveVer === localVer) ok('一致しています（反映の必要なし）。');
    else { console.log('🟡 未反映：ローカル版がクラウドに反映されていません。'); info('反映するには「GASを反映.bat」を実行してください。'); }
    return;
  }

  if (liveVer === localVer && !isForce) {
    die('稼働中と同じ GAS_VERSION です（' + localVer + '）。\n' +
      '   gas/コード.gs の GAS_VERSION を上げてから実行してください。\n' +
      '   （比較だけしたいときは --check、同一でも強行するなら --force）');
  }

  assertClaspLogin();

  // .clasp.json を毎回生成（scriptId はローカル設定が唯一の正）。rootDir=gas、.claspignore は直下。
  writeFileSync(CLASP_JSON, JSON.stringify({ scriptId: cfg.scriptId, rootDir: 'gas' }, null, 2) + '\n');

  console.log('\n📤 コードを転送中（clasp push）…');
  if (clasp(['push', '-f']).status !== 0) die('clasp push に失敗しました（上のログを確認）。');

  const desc = 'auto ' + new Date().toISOString().slice(0, 10) + ' ' + localVer.slice(0, 16);
  console.log('\n🚀 既存デプロイに新バージョンを反映中（clasp deploy -i）…');
  if (clasp(['deploy', '-i', cfg.deploymentId, '-d', desc]).status !== 0) {
    die('clasp deploy に失敗しました。デプロイIDが正しいか（exec URLの AKfycb… トークン）確認してください。');
  }

  console.log('\n⏳ 反映の伝播を待っています（最大120秒）…');
  let reflected = false;
  for (let i = 0; i < 24; i++) {
    await sleep(5000);
    let v = '';
    try { v = await fetchPing(); } catch (e) { /* 伝播中は失敗しうる */ }
    if (v === localVer) { reflected = true; break; }
    process.stdout.write('.');
  }
  console.log('');
  if (!reflected) {
    die('デプロイは実行しましたが、反映（?ping=1 のバージョン一致）を確認できませんでした。\n' +
      '   数分後に ' + cfg.execUrl + '?ping=1 を手動で開いて version を確認してください。');
  }
  ok('反映を確認（version = ' + localVer + '）。exec URL は変わっていません。');

  // ---- 後処理：トリガー再設定＋ヘッダ移行（冪等）----
  console.log('\n🔧 後処理（トリガー再設定＋ヘッダ移行）を実行中…');
  try {
    const url = cfg.execUrl + (cfg.execUrl.includes('?') ? '&' : '?') +
      'action=admin_setup&secret=' + encodeURIComponent(adminSecret);
    const res = await fetch(url, { redirect: 'follow' });
    const data = JSON.parse(await res.text());
    if (!data.ok) {
      if (data.error === 'bad_secret') {
        console.log('⚠️ admin_setup が secret 不一致で拒否されました。');
        info('gas_deploy_config.json の adminSecret を、GAS のスクリプトプロパティ ADMIN_SECRET と一致させてください。');
        info('（コード反映自体は成功しています。トリガー設定だけ手動 setupTrigger 実行でも可）');
      } else {
        console.log('⚠️ admin_setup 応答: ' + JSON.stringify(data));
      }
    } else {
      const triggers = data.triggers || [];
      const want = ['refreshClicks', 'refreshEngagement', 'snapshotStats'];
      const missing = want.filter((w) => !triggers.includes(w));
      ok('後処理完了。トリガー: ' + triggers.join(', '));
      if (missing.length) info('⚠️ 未設定のトリガー: ' + missing.join(', ') + '（setupTrigger を確認）');
      if (data.migrated) info('ヘッダ移行: ' + JSON.stringify(data.migrated).slice(0, 160));
    }
  } catch (e) {
    console.log('⚠️ 後処理の呼び出しに失敗: ' + e.message + '（コード反映は成功）。');
  }

  console.log('\n🎉 GAS 自動反映が完了しました。');
  info('バージョン: ' + localVer);
}

main().catch((e) => die('想定外のエラー: ' + (e && e.stack ? e.stack : e)));
