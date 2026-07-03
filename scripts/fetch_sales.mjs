/**
 * fetch_sales.mjs — 実売本数（販売数）を PC(日本IP) でスクレイプしてワーカーへ登録
 *
 * なぜPCか：DMMの作品ページはCloudflare等のデータセンターIPを海外扱いし「ログイン」へ飛ばすため、
 * サーバー(worker)からは販売数が取れない。日本の家庭用IP（このPC）からは普通に読める。
 *
 * 動き（AI不要・ワンクリック）:
 *   1. ワーカーの /api/fanza-sales-queue から「取得依頼中のcid」＋「追跡サークル一覧」を取得
 *      （候補タブでサークルタブを登録した時点で追跡対象になる＝タブを表示しなくてもよい）
 *   2. 追跡サークルは全作品のcidを /api/fanza-maker-list から取得し、まとめてスクレイプ対象へ
 *      （前回の全件取得から18時間以内のサークルはスキップ。状態は scripts/sales_state.json）
 *   3. 各cidの作品ページをスクレイプして販売数(numberOfSales__txt / detailInfo-sales)を抽出
 *   4. /api/fanza-sales-save へ保存 → 以後スマホの候補タブで「販売数(実売)」が表示される
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
  return { queued: Array.isArray(j.queued) ? j.queued : [], trackedMakers: Array.isArray(j.trackedMakers) ? j.trackedMakers : [] };
}

// 追跡サークルの全作品cidを取得（worker側で全ページ＋全同人フロア巡回済み）。
// ※このAPIは公開ソフト鍵＋Originチェックなので、本番サイトのOriginを付けて呼ぶ。
async function getMakerCids(makerId) {
  const res = await fetch(WORKER + "/api/fanza-maker-list", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Shared-Secret": String(CFG.sharedSecret || ""), "Origin": String(CFG.siteOrigin || "https://john-mori.github.io") },
    body: JSON.stringify({ makerId, sort: "rank" }),
  });
  const j = await res.json().catch(() => null);
  if (!j || !j.ok) { console.error("  ⚠️ サークル" + makerId + " の作品一覧取得に失敗: " + (j && j.error ? j.error : ("HTTP " + res.status))); return null; }
  return (j.items || []).map((it) => it.cid).filter(Boolean);
}

// サークルごとの前回全件取得時刻（ローカル状態・このPC専用なのでファイルでよい）。
const STATE_PATH = path.join(__dirname, "sales_state.json");
const FULL_SCRAPE_INTERVAL_MS = 18 * 3600 * 1000; // 18時間: 1日1回のbat実行で必ず更新される間隔
function loadState() { try { return JSON.parse(fs.readFileSync(STATE_PATH, "utf8")); } catch (e) { return {}; } }
function saveState(s) { fs.writeFileSync(STATE_PATH, JSON.stringify(s, null, 2)); }
async function saveBatch(items) {
  const res = await fetch(WORKER + "/api/fanza-sales-save", { method: "POST", headers: { "Content-Type": "application/json", "X-Admin-Secret": ADMIN }, body: JSON.stringify({ items }) });
  const j = await res.json().catch(() => null);
  if (!j || !j.ok) { console.error("  ⚠️ 保存失敗: " + (j && j.error ? j.error : ("HTTP " + res.status))); return 0; }
  return j.saved || 0;
}

async function main() {
  const args = process.argv.slice(2).map(toCid).filter(Boolean);
  let cids = [];
  const ranMakers = []; // 今回全件取得を実施したサークル（完走後に時刻を記録）
  if (args.length) {
    cids = args; // cid/URL直接指定モード
  } else {
    const q = await getQueue();
    cids = q.queued;
    // 追跡サークル（候補タブに登録済みのサークル）: 全作品を取得対象に追加。
    // 18時間以内に全件取得済みのサークルはスキップ（DMMへの負荷と実行時間を抑える）。
    const state = loadState();
    for (const mk of q.trackedMakers) {
      const last = state[mk.makerId] || 0;
      const label = (mk.name || ("サークル" + mk.makerId));
      if (Date.now() - last < FULL_SCRAPE_INTERVAL_MS) { console.log("⏭️ " + label + ": 前回取得から18時間未満のためスキップ"); continue; }
      const mcids = await getMakerCids(mk.makerId);
      if (!mcids) continue; // 一覧取得失敗（次回リトライ）
      console.log("📚 " + label + ": 全" + mcids.length + "作品を取得対象に追加");
      cids.push(...mcids);
      ranMakers.push(mk.makerId); // 完走したら最後に時刻を記録（途中中断なら次回やり直し）
    }
  }
  cids = [...new Set(cids)];
  if (!cids.length) { console.log("✅ 取得するものはありません。候補タブでサークルタブを登録すると、そのサークルの全作品がここで取得されます。"); return; }
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
  // 全件スクレイプを完走したサークルの時刻を記録（次回は18時間スキップが効く）
  if (ranMakers.length) { const st = loadState(); ranMakers.forEach((mid) => { st[mid] = Date.now(); }); saveState(st); }
  console.log(`\n✅ 完了: 成功 ${ok}件 / 取得できず ${ng}件。スマホの候補タブをリロードすると販売数が反映されます。`);
}
main().catch((e) => die(String(e && e.stack ? e.stack : e)));
