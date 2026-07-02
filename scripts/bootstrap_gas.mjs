// bootstrap_gas.mjs — GAS自動反映の「初回だけ」のセットアップ（依存パッケージなし）。
//
//   node scripts/bootstrap_gas.mjs                 対話で scriptId / exec URL を入力
//   node scripts/bootstrap_gas.mjs <scriptId> <execUrl> [adminSecret]   引数指定
//
// やること:
//   1) クラウドGASを一時ディレクトリへ clasp pull（gas/ は絶対に上書きしない）
//   2) 実際のクラウド構成を読み、gas/appsscript.json を実物で用意
//   3) クラウドに在ってローカルに無いファイルを gas/ へ取り込み、.claspignore を実構成に確定
//      （push のミラー同期でクラウド側ファイルを消さないための安全化）
//   4) exec URL から デプロイID（AKfycb… トークン）を抽出し ?ping=1 で疎通確認
//   5) scripts/gas_deploy_config.json を書き出す
//
// 前提: 先に「clasp login」で Google 承認を済ませておくこと（GAS初期設定.bat が面倒を見る）。

import { readFileSync, writeFileSync, existsSync, mkdtempSync, readdirSync, copyFileSync, rmSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join, basename } from 'node:path';
import { tmpdir } from 'node:os';
import { createInterface } from 'node:readline/promises';
import { stdin as input, stdout as output } from 'node:process';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const GAS_DIR = join(ROOT, 'gas');
const CONFIG_PATH = join(ROOT, 'scripts', 'gas_deploy_config.json');
const CLASPIGNORE = join(ROOT, '.claspignore');

function die(msg) { console.error('\n❌ ' + msg + '\n'); process.exit(1); }
function ok(msg) { console.log('✅ ' + msg); }
function info(msg) { console.log('   ' + msg); }

const args = process.argv.slice(2);

async function main() {
  if (existsSync(CONFIG_PATH)) {
    console.log('ℹ️ 既に scripts/gas_deploy_config.json があります（設定済み）。');
    info('やり直す場合はこのファイルを消してから再実行してください。');
    return;
  }

  // clasp ログイン確認
  const home = process.env.HOME || process.env.USERPROFILE || '';
  if (home && !existsSync(join(home, '.clasprc.json'))) {
    die('先に clasp login が必要です。\n   「GAS初期設定.bat」を使うと自動でログインまで案内します。');
  }

  // 入力受け取り
  let scriptId = args[0] || '';
  let execUrl = args[1] || '';
  let adminSecret = args[2] || '';
  if (!scriptId || !execUrl) {
    const rl = createInterface({ input, output });
    if (!scriptId) scriptId = (await rl.question('スクリプトID（プロジェクトの設定→スクリプトID）: ')).trim();
    if (!execUrl) execUrl = (await rl.question('exec URL（…/macros/s/AKfycb…/exec）: ')).trim();
    if (!adminSecret) adminSecret = (await rl.question('ADMIN_SECRET（未設定ならEnterで空）: ')).trim();
    rl.close();
  }
  if (!scriptId) die('スクリプトIDが空です。');
  const mDep = /\/macros\/s\/([A-Za-z0-9_-]+)\/exec/.exec(execUrl);
  if (!mDep) die('exec URL の形式が不正です（…/macros/s/AKfycb…/exec が必要）。');
  const deploymentId = mDep[1];

  // ---- 一時ディレクトリへ clasp pull（gas/ は触らない）----
  const tmp = mkdtempSync(join(tmpdir(), 'go5gas-'));
  info('一時取得先: ' + tmp);
  writeFileSync(join(tmp, '.clasp.json'), JSON.stringify({ scriptId, rootDir: '.' }) + '\n');
  console.log('📥 クラウドGASの構成を取得中（clasp pull）…');
  const pr = spawnSync('npx', ['--yes', '@google/clasp', 'pull'], {
    cwd: tmp, stdio: 'inherit', encoding: 'utf8', shell: process.platform === 'win32'
  });
  if (pr.status !== 0) { try { rmSync(tmp, { recursive: true, force: true }); } catch (e) {} die('clasp pull に失敗しました（scriptId とログインを確認）。'); }

  // ---- 取得したクラウド構成を読む ----
  const cloudFiles = readdirSync(tmp).filter((f) => f !== '.clasp.json');
  const gsFiles = cloudFiles.filter((f) => f.endsWith('.gs') || f.endsWith('.js'));
  const jsonFiles = cloudFiles.filter((f) => f.endsWith('.json'));
  const htmlFiles = cloudFiles.filter((f) => f.endsWith('.html'));
  info('クラウド上のファイル: ' + cloudFiles.join(', '));

  if (!jsonFiles.includes('appsscript.json')) {
    try { rmSync(tmp, { recursive: true, force: true }); } catch (e) {}
    die('クラウドに appsscript.json が見つかりません（想定外）。');
  }

  // appsscript.json は実物を採用（webappのアクセス設定を壊さないため手書きしない）。
  copyFileSync(join(tmp, 'appsscript.json'), join(GAS_DIR, 'appsscript.json'));
  ok('gas/appsscript.json をクラウドの実物で用意しました。');

  // クラウドに在ってローカルgas/に無い .gs を取り込む（push で消さないため）。コード.gs はローカルを正とする。
  const whitelist = new Set(['appsscript.json']);
  for (const f of gsFiles) {
    whitelist.add(f);
    const localPath = join(GAS_DIR, f);
    if (f === 'コード.gs') { info('コード.gs はローカルを正として保持（クラウド版は取り込まない）。'); continue; }
    if (!existsSync(localPath)) { copyFileSync(join(tmp, f), localPath); info('取り込み: gas/' + f + '（クラウドのみに存在したため）'); }
    else info('保持: gas/' + f + '（両方に存在・ローカルを使用）');
  }
  // クラウドに HTML があれば parity 維持のため取り込み＆whitelist（recorderでは通常無い）。
  for (const f of htmlFiles) {
    whitelist.add(f);
    const localPath = join(GAS_DIR, f);
    if (!existsSync(localPath)) { copyFileSync(join(tmp, f), localPath); }
    console.log('⚠️ クラウドに HTML ファイル ' + f + ' がありました。whitelist に追加しました（誤削除防止）。');
  }

  try { rmSync(tmp, { recursive: true, force: true }); } catch (e) {}

  // ---- .claspignore を実構成で確定（全無視→クラウド実ファイルだけ許可）----
  const lines = [
    '# clasp push が対象にするファイルのホワイトリスト（bootstrap_gas.mjs がクラウド実構成から生成）。',
    '# clasp push はクラウドをローカル(gas/)のミラーに置き換えるため、実体ファイルだけを許可する。',
    '',
    '**/**',
    ''
  ].concat([...whitelist].sort().map((f) => '!' + f));
  writeFileSync(CLASPIGNORE, lines.join('\n') + '\n');
  ok('.claspignore をクラウド構成に合わせて確定: ' + [...whitelist].sort().join(', '));

  // ---- 疎通確認（?ping=1）----
  console.log('🔌 exec URL の疎通確認（?ping=1）…');
  try {
    const url = execUrl + (execUrl.includes('?') ? '&' : '?') + 'ping=1';
    const res = await fetch(url, { redirect: 'follow' });
    const data = JSON.parse(await res.text());
    if (!data || !data.ok || !data.version) throw new Error('version 応答なし');
    ok('疎通OK。現在の稼働版: ' + data.version);
  } catch (e) {
    console.log('⚠️ ?ping=1 の確認に失敗: ' + e.message);
    info('exec URL とアクセス設定（全員）を確認してください。設定自体は保存を続行します。');
  }

  // ---- 設定書き出し ----
  const cfg = { scriptId, deploymentId, execUrl, adminSecret };
  writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2) + '\n');
  ok('scripts/gas_deploy_config.json を書き出しました（このファイルはコミットされません）。');

  console.log('\n🎉 初回セットアップ完了。以後は「GASを反映.bat」で自動反映できます。');
  if (!adminSecret) info('（任意）GAS のスクリプトプロパティに ADMIN_SECRET を設定すると後処理の門番が強くなります。');
}

main().catch((e) => die('想定外のエラー: ' + (e && e.stack ? e.stack : e)));
