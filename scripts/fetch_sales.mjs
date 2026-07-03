/**
 * fetch_sales.mjs — 実売本数（販売数）を PC(日本IP) でスクレイプしてワーカーへ登録
 *
 * なぜPCか：DMMの作品ページはCloudflare等のデータセンターIPを海外扱いし「ログイン」へ飛ばすため、
 * サーバー(worker)からは販売数が取れない。日本の家庭用IP（このPC）からは普通に読める。
 *
 * 動き（AI不要・ワンクリック）:
 *   1. ワーカーの /api/fanza-sales-queue から「販売数の取得依頼中のcid」を取得
 *      （候補タブでサークル作品を表示すると、未取得cidが自動でこのキューに積まれる）
 *   2. 各cidの作品ページをスクレイプして販売数(numberOfSales__txt / detailInfo-sales)を抽出
 *   3. /api/fanza-sales-save へ保存 → 以後スマホの候補タブで「販売数(実売)」が表示される
 *
 * 使い方:
 *   node scripts/fetch_sales.mjs                 … キューを処理
 *   node scripts/fetch_sales.mjs d_724627 d_...  … cid/作品URLを直接指定も可
 *   （リポジトリ直下の「販売数を取得.bat」をダブルクリックでもOK）
 *
 * 設定: scripts/scrape_config.json（gitに入れない）
 *   { "workerUrl": "https://go5-fanza-proxy.....workers.dev", "adminSecret": "..." }
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = path.join(__dirname, "scrape_config.json");
function die(msg) { console.error("❌ " + msg); process.exit(1); }
if (!fs.existsSync(CONFIG_PATH)) die("設定ファイルがありません: " + CONFIG_PATH + "\n   scrape_config.example.json をコピーして workerUrl / adminSecret を記入してください。");
const CFG = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
const WORKER = String(CFG.workerUrl || "").replace(/\/+$/, "");
const ADMIN = String(CFG.adminSecret || "");
if (!WORKER || !ADMIN) die("scrape_config.json の workerUrl / adminSecret が空です。");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 作品URL/文字列 → cid（d_XXXX 形式）。
function toCid(s) {
  s = String(s || "").trim();
  const m = s.match(/cid=([0-9A-Za-z_]+)/) || (/^[0-9A-Za-z_]+$/.test(s) ? [null, s] : null);
  return m ? m[1] : "";
}

// 作品ページから販売数を抽出（日本IPなので普通に読める）。取れなければ null。
async function scrapeSales(cid) {
  const url = "https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=" + encodeURIComponent(cid) + "/";
  let res;
  try {
    res = await fetch(url, { headers: { "Cookie": "age_check_done=1", "User-Agent": UA, "Accept-Language": "ja,en-US;q=0.7", "Referer": "https://www.dmm.co.jp/" } });
  } catch (e) { return { error: "network" }; }
  if (!res.ok) return { error: "HTTP " + res.status };
  const finalUrl = res.url || "";
  if (/accounts\.dmm\.co\.jp|\/login\//.test(finalUrl)) return { error: "login_wall(このPCのIPが海外扱い?)" };
  const html = await res.text();
  const m = html.match(/numberOfSales__txt["'][^>]*>\s*([\d,]+)/)
    || html.match(/detailInfo-sales["'][^>]*>\s*販売数[:：]\s*<em>\s*([\d,]+)/)
    || html.match(/detailInfo-sales["'][^>]*>\s*販売数[:：]\s*([\d,]+)/);
  if (!m) return { error: "販売数が見つからない(配信終了/ページ構造変化?)" };
  const n = parseInt(m[1].replace(/,/g, ""), 10);
  return isNaN(n) ? { error: "数値解析失敗" } : { n };
}

async function getQueue() {
  const res = await fetch(WORKER + "/api/fanza-sales-queue", { headers: { "X-Admin-Secret": ADMIN } });
  const j = await res.json().catch(() => null);
  if (!j || !j.ok) die("キュー取得に失敗: " + (j && j.error ? j.error : ("HTTP " + res.status)));
  return Array.isArray(j.queued) ? j.queued : [];
}
async function saveBatch(items) {
  const res = await fetch(WORKER + "/api/fanza-sales-save", { method: "POST", headers: { "Content-Type": "application/json", "X-Admin-Secret": ADMIN }, body: JSON.stringify({ items }) });
  const j = await res.json().catch(() => null);
  if (!j || !j.ok) { console.error("  ⚠️ 保存失敗: " + (j && j.error ? j.error : ("HTTP " + res.status))); return 0; }
  return j.saved || 0;
}

async function main() {
  const args = process.argv.slice(2).map(toCid).filter(Boolean);
  let cids = args.length ? args : await getQueue();
  cids = [...new Set(cids)];
  if (!cids.length) { console.log("✅ 取得依頼中の販売数はありません。候補タブでサークルを表示すると、ここに溜まります。"); return; }
  console.log("📊 販売数を取得します: " + cids.length + "件（日本IPのこのPCで実行中）\n");

  const results = [];
  let ok = 0, ng = 0;
  for (let i = 0; i < cids.length; i++) {
    const cid = cids[i];
    const r = await scrapeSales(cid);
    if (r.n != null) { results.push({ cid, n: r.n }); ok++; console.log(`  [${i + 1}/${cids.length}] ${cid} … 販売数 ${r.n.toLocaleString("ja-JP")}`); }
    else { ng++; console.log(`  [${i + 1}/${cids.length}] ${cid} … 取得できず（${r.error}）`); }
    // 20件ごとに中間保存（大量でも取りこぼさない）
    if (results.length >= 20) { const s = await saveBatch(results.splice(0, results.length)); console.log("   → 保存 " + s + "件"); }
    await sleep(700); // DMMへの負荷を避ける
  }
  if (results.length) { const s = await saveBatch(results); console.log("   → 保存 " + s + "件"); }
  console.log(`\n✅ 完了: 成功 ${ok}件 / 取得できず ${ng}件。スマホの候補タブをリロードすると販売数が反映されます。`);
}
main().catch((e) => die(String(e && e.stack ? e.stack : e)));
