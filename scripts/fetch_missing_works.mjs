/**
 * fetch_missing_works.mjs — API未収録作品のフル情報をPC(日本IP)でスクレイプしてワーカーへ登録
 *
 * なぜPCか：DMMの商品ページはCloudflare等のデータセンターIPを海外扱いし
 * ログイン壁に飛ばすため、サーバー側からは作品名・価格が取れない。
 * 日本の家庭用IP（このPC）からは普通に読める。
 *
 * 動き（AI不要・ワンクリック）:
 *   1. ワーカーの /api/fanza-queue から「取得依頼中のcid」と「登録済みcid(価格更新用)」を取得
 *   2. 各cidの商品ページをスクレイプ（作品名/サークル/価格/発売日/ジャンル）
 *   3. 画像CDNからサムネ/サンプルURLを確認（NOW PRINTINGプレースホルダは除外）
 *   4. /api/fanza-override へ保存 → 以後スマホの「DMM作品情報を取得」でフル表示される
 *
 * 使い方:
 *   node scripts/fetch_missing_works.mjs            … キュー＋登録済みを処理
 *   node scripts/fetch_missing_works.mjs d_753568   … cid/作品URLを直接指定も可
 *   （リポジトリ直下の「未収録作品を取得.bat」をダブルクリックでもOK）
 *
 * 設定: scripts/scrape_config.json（gitには入れない。example参照）
 *   { "workerUrl": "https://go5-fanza-proxy.....workers.dev", "adminSecret": "..." }
 *   ※adminSecret はワーカーの ADMIN_SECRET と同値（配布しない管理鍵。アプリの共有シークレットとは別物）。
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = path.join(__dirname, "scrape_config.json");

function die(msg) { console.error("❌ " + msg); process.exit(1); }

if (!fs.existsSync(CONFIG_PATH)) {
  die("設定ファイルがありません: " + CONFIG_PATH + "\n   scrape_config.example.json をコピーして workerUrl と sharedSecret を記入してください。");
}
const CFG = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
const WORKER = String(CFG.workerUrl || "").replace(/\/+$/, "");
const ADMIN = String(CFG.adminSecret || "");
if (!WORKER || !ADMIN) die("scrape_config.json の workerUrl / adminSecret が空です。");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── 商品ページのスクレイプ（日本IPなので普通に読める） ─────────────────────────
async function scrapePage(cid) {
  const url = "https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=" + encodeURIComponent(cid) + "/";
  const res = await fetch(url, {
    headers: {
      "Cookie": "age_check_done=1",
      "User-Agent": UA,
      "Accept-Language": "ja,en-US;q=0.7",
      "Referer": "https://www.dmm.co.jp/",
    },
  });
  if (!res.ok) return { error: "HTTP " + res.status };
  // リダイレクトで別ページ(一覧/トップ等)へ飛ばされた場合は誤タイトル登録になるため弾く
  if (res.url && res.url.indexOf("cid=" + cid) < 0) return { error: "商品ページ以外へリダイレクト（配信終了/移動の可能性）" };
  const html = await res.text();

  // 作品名（og:title）
  const ogT = html.match(/property=["']og:title["']\s+content=["']([^"']+)/) || html.match(/content=["']([^"']+)["']\s+property=["']og:title["']/);
  let title = ogT ? ogT[1].trim() : "";
  if (!title) { const t = html.match(/<title>([^<]+)</); if (t) title = t[1].replace(/\s*[|｜【].*$/, "").trim(); }
  if (!title || /ログイン|年齢確認|エラー/.test(title)) return { error: "タイトル取得不可（ページ構造変更 or 壁）" };

  // JSON-LD（サークル名・現在価格・発売日が取れることが多い）
  let author = "", price = null, releaseDate = "";
  const ldRe = /<script\s+type=["']application\/ld\+json["']>([\s\S]*?)<\/script>/g;
  let m;
  while ((m = ldRe.exec(html)) !== null) {
    try {
      const obj = JSON.parse(m[1]);
      if (obj["@type"] === "Product") {
        if (obj.brand && obj.brand.name) author = String(obj.brand.name);
        const offers = obj.offers || {};
        if (offers.price != null) { const v = parseInt(String(offers.price).replace(/[^\d]/g, ""), 10); price = Number.isFinite(v) ? v : null; } // 0円(無料)も保持
        if (obj.releaseDate) releaseDate = String(obj.releaseDate).slice(0, 10);
      }
    } catch (e) { /* 次のJSON-LDへ */ }
  }
  // 価格の保険（offers正規表現）
  if (price == null) {
    const pm = html.match(/["']offers["']\s*:\s*\{[^}]*["']price["']\s*:\s*["']?(\d+)/);
    if (pm) price = parseInt(pm[1], 10);
  }
  // 定価（取り消し線の元値。無ければ現在価格と同じ＝セール無し）
  let listPrice = null;
  const lm = html.match(/priceList__sub--big[^>]*>[\s\S]{0,80}?([\d,]+)\s*円/) || html.match(/(?:定価|通常価格)[^0-9]{0,20}([\d,]+)\s*円/);
  if (lm) listPrice = parseInt(lm[1].replace(/,/g, ""), 10);
  if (listPrice == null && price != null) listPrice = price;

  // 発売日の保険（情報テーブルの「配信開始日/発売日」： <dt>配信開始日</dt><dd>2026/06/17 16:00</dd>）
  if (!releaseDate) {
    const dm = html.match(/(?:配信開始日|発売日)<\/dt>\s*<dd[^>]*>\s*(\d{4})\/(\d{1,2})\/(\d{1,2})/);
    if (dm) releaseDate = dm[1] + "-" + ("0" + dm[2]).slice(-2) + "-" + ("0" + dm[3]).slice(-2);
  }

  // ジャンル（作品固有のジャンルタグ genreTag__txt のみ。左ナビのkeywordリンクは拾わない）
  const genres = [];
  const gRe = /class="genreTag__txt"[^>]*>\s*([^<]{1,24}?)\s*</g;
  let g;
  while ((g = gRe.exec(html)) !== null) {
    const name = g[1].trim();
    if (name && genres.indexOf(name) < 0) genres.push(name);
    if (genres.length >= 16) break;
  }

  return { title, author, price, listPrice, releaseDate, genres };
}

// ── 画像CDN（NOW PRINTINGプレースホルダを指紋で除外） ────────────────────────
async function headInfo(u) {
  try { const r = await fetch(u, { method: "HEAD" }); return r.ok ? { ok: true, len: r.headers.get("content-length") || "", etag: r.headers.get("etag") || "" } : { ok: false }; }
  catch (e) { return { ok: false }; }
}
async function cdnImages(cid) {
  for (const t of ["comic", "game", "voice", "cg"]) {
    const base = `https://doujin-assets.dmm.co.jp/digital/${t}/${cid}/${cid}`;
    const pl = await headInfo(base + "pl.jpg");
    if (!pl.ok) continue;
    const ref = await headInfo(base + "jp-999.jpg"); // 確実に存在しない番号＝プレースホルダの指紋
    const isPh = (h) => ref.ok && h.ok && ((ref.etag && h.etag) ? ref.etag === h.etag : (ref.len !== "" && h.len === ref.len));
    if (isPh(pl)) continue;
    const pt = await headInfo(base + "pt.jpg");
    const samples = [];
    for (let n = 1; n <= 10; n++) {
      const u = base + "jp-" + String(n).padStart(3, "0") + ".jpg";
      const h = await headInfo(u);
      if (!h.ok || isPh(h)) break;
      samples.push(u);
    }
    return {
      imageURL: { list: (pt.ok && !isPh(pt)) ? base + "pt.jpg" : base + "pl.jpg", large: base + "pl.jpg" },
      sampleImageURL: samples.length ? { sample_l: { image: samples } } : null,
    };
  }
  return { imageURL: null, sampleImageURL: null };
}

// ── メイン ───────────────────────────────────────────────────────────────
(async () => {
  console.log("=== 未収録作品のフル情報取得（PCスクレイプ → ワーカーKVへ登録） ===");

  // 対象cid：CLI引数（cid or 作品URL） ＋ ワーカーの依頼キュー ＋ 登録済み(価格更新)
  const targets = new Set();
  for (const a of process.argv.slice(2)) {
    const mm = String(a).match(/cid=([0-9A-Za-z_-]+)/) || String(a).match(/^([0-9A-Za-z_-]+)$/);
    if (mm) targets.add(mm[1]);
  }
  const qres = await fetch(WORKER + "/api/fanza-queue", { headers: { "X-Admin-Secret": ADMIN } }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }));
  if (!qres.ok) die("キュー取得に失敗: " + (qres.error || "unknown") + "（workerUrl/adminSecretを確認）");
  qres.queued.forEach((c) => targets.add(c));
  qres.overridden.forEach((c) => targets.add(c)); // 登録済みも再取得＝価格・セール情報を最新化
  console.log("対象: " + targets.size + "件（依頼中 " + qres.queued.length + " / 登録済みの更新 " + qres.overridden.length + " / 指定 " + Math.max(0, targets.size - qres.queued.length - qres.overridden.length) + "）");
  if (!targets.size) { console.log("✅ 取得依頼はありません。終わり。"); return; }

  const items = [], fails = [];
  for (const cid of targets) {
    process.stdout.write("・" + cid + " … ");
    try {
      const page = await scrapePage(cid);
      if (page.error) { console.log("✖ " + page.error); fails.push(cid); await sleep(800); continue; }
      const img = await cdnImages(cid);
      items.push({
        content_id: cid,
        title: page.title,
        date: page.releaseDate ? page.releaseDate + " 00:00:00" : "",
        service_name: "同人",
        floor_name: "同人",
        imageURL: img.imageURL,
        sampleImageURL: img.sampleImageURL,
        iteminfo: {
          author: page.author ? [{ name: page.author }] : [],
          genre: page.genres.map((n) => ({ name: n })),
        },
        prices: {
          list_price: page.listPrice != null ? String(page.listPrice) : null,
          price: page.price != null ? String(page.price) : null,
        },
        review: { count: null, average: null },
        scrapedAt: new Date().toISOString(),
      });
      console.log("✔ " + page.title.slice(0, 28) + (page.price != null ? "（¥" + page.price + "）" : ""));
    } catch (e) { console.log("✖ " + e.message); fails.push(cid); }
    await sleep(800); // DMMに優しく1件ずつ
  }

  if (items.length) {
    let savedTotal = 0;
    for (let i = 0; i < items.length; i += 100) { // ワーカー側の1回100件制限に合わせ分割POST
      const res = await fetch(WORKER + "/api/fanza-override", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Secret": ADMIN },
        body: JSON.stringify({ items: items.slice(i, i + 100) }),
      }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }));
      if (!res.ok) die("ワーカーへの保存に失敗: " + (res.error || "unknown"));
      savedTotal += res.saved;
    }
    console.log("\n✅ " + savedTotal + "件をワーカーへ登録しました。");
    console.log("   スマホで「DMM 作品情報を取得」ボタンを押すとフル情報が表示されます。");
  }
  if (fails.length) console.log("⚠️ 取得できなかったcid: " + fails.join(", "));
})();
