/**
 * fanza-worker — FANZA商品情報取得（go5-maker 専用）
 *
 * 優先順位:
 *   1. DMM公式API（FANZA_API_ID + FANZA_AFFILIATE_ID が設定されている場合）← 確実
 *   2. HTML スクレイピング（og:title → JSON-LD → <title> の順）← APIキー不要だが不安定
 *
 * ルート:
 *   POST /api/fanza-item  { cid: "d_784440" } → { ok, item }
 *   GET  /                → ヘルスチェック（デプロイ確認用）
 *
 * Secrets（wrangler secret put で登録）:
 *   SHARED_SECRET         ← フロント認証キー（必須）
 *   FANZA_API_ID          ← DMM API ID（任意・設定すると API 優先）
 *   FANZA_AFFILIATE_ID    ← FANZA アフィリエイトID（任意・FANZA_API_ID と対で設定）
 *
 * 安全:
 *   - Origin 制限（ALLOWED_ORIGIN 単一 Origin のみ）
 *   - 共有シークレット（X-Shared-Secret ヘッダ）
 */

const DMM_API_BASE    = "https://api.dmm.com/affiliate/v3/ItemList";
const DMM_DOUJIN_BASE = "https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=";

export default {
  async fetch(request, env) {
    const url    = new URL(request.url);
    const path   = url.pathname;
    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "";

    if (path === "/api/fanza-item") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const cors = corsHeaders(origin, allowed);
      if (!cors) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, cors);

      const secret = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || secret !== env.SHARED_SECRET) {
        return json({ ok: false, error: "bad_secret" }, 401, cors);
      }

      let body;
      try { body = await request.json(); }
      catch (e) { return json({ ok: false, error: "bad_json" }, 400, cors); }

      const cid = String(body.cid || "").trim();
      if (!cid) return json({ ok: false, error: "missing_cid" }, 400, cors);
      // KVキーに使うため形式を厳格に検証（req:キュー汚染・ゴミキー増殖の防止）
      if (!/^[0-9A-Za-z_-]{1,64}$/.test(cid)) return json({ ok: false, error: "bad_cid" }, 400, cors);
      // 作品ページURL（任意）：FANZA Books等、同人以外のスクレイプフォールバック先として使用。
      // SSRF防止のためFANZA配下のみ許可（それ以外は無視して従来動作）。book.dmm.com=現行のFANZAブックス。
      let srcUrl = String(body.url || "").trim();
      if (!/^https:\/\/(book\.dmm\.com|book\.dmm\.co\.jp|www\.dmm\.co\.jp)\//.test(srcUrl)) srcUrl = "";

      // ① DMM 公式 API（APIキーが設定されていれば優先）
      let item = null;
      if (env.FANZA_API_ID && env.FANZA_AFFILIATE_ID) {
        item = await fetchViaApi(cid, env.FANZA_API_ID, env.FANZA_AFFILIATE_ID);
      }

      // ①′ KV上書き：PC側バッチ(scripts/fetch_missing_works.mjs)が日本IPでスクレイプした
      //    フル情報。API未収録の作品はここで解決する。
      //    30日以上前のスクレイプは価格だけ無効化（旧セール価格の配信防止）し、再取得を依頼キューへ。
      if (!item) {
        try {
          const ov = await stGetOverride(env, cid);
          if (ov && ov.title) {
            const age = Date.now() - (Date.parse(ov.scrapedAt || "") || 0);
            if (age > 30 * 86400000) {
              ov.prices = { list_price: null, price: null };
              await stQueueInfoPut(env, cid, ""); // 30日超=再取得依頼（既存なら書かない=dedup内蔵）
            }
            item = ov;
          }
        } catch (e) {}
      }

      // ② スクレイピング（API なし or API で見つからなかった場合）。
      //    srcUrl があればそのページ（FANZA Books等）を、無ければ従来どおり同人ページを見る。
      if (!item) item = await scrapeFanzaItem(cid, srcUrl);

      // ③ 画像CDNフォールバック：アフィリエイトAPI未収録（サークル設定等）かつ商品ページが
      //    ログイン壁（Cloudflare=海外/DC IP扱い）の作品でも、画像CDN(doujin-assets)は認証・
      //    地域制限なしで取れる。サムネ＋サンプル画像だけの「部分情報」(partial)を返す。
      if (!item) item = await cdnFallbackItem(cid);

      // フル情報が取れなかった作品は「PC取得依頼キュー」へ記録（PCのバッチが拾ってスクレイプ→ov:へ保存）。
      //   book等のsrcUrlがあれば一緒に保存し、PC側がそのURL（同人以外）を正しくスクレイプできるようにする。
      // フル情報が取れなかった作品は取得依頼キューへ（dedup+Books用URL enrich はstQueueInfoPut内蔵）。
      //   ★KV1日書き込み上限の主因だった無条件req:書き込みは、ストレージ層のdedupで解消済み。
      if (!item || item.partial) {
        try { await stQueueInfoPut(env, cid, srcUrl); } catch (e) {}
      }

      if (!item) return json({ ok: false, error: "not_found", cid }, 404, cors);
      return json({ ok: true, item }, 200, cors);
    }

    // ── サークル（maker）の作品一覧：候補タブの「サークルタブ」用 ──────────────────
    //   POST /api/fanza-maker-list { makerId, sort? }
    //   sort: "date"(既定・発売日新しい順) | "rank"(人気=直近の売れ行きに近い動的ランキング) | "review"
    //   ★worker側で「全ページ＋全同人フロア(通常/BL/TL)」を巡回して全作品を返す（フロントは1回呼ぶだけ）。
    //     以前はフロントが offset<300 で最大400件に頭打ちし、大規模サークルの作品が欠けていた(取得漏れ)。
    //   ※sort=rank に gte_date(発売日)を重ねると"直近1週間に発売された新作限定"になり対象0件事故が
    //     起きたため発売日フィルタは廃止済み。フロントの「直近1週間で売れてる順」は sort=rank にマップ。
    if (path === "/api/fanza-maker-list") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const cors2 = corsHeaders(origin, allowed);
      if (!cors2) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, cors2);
      const sec2 = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || sec2 !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, cors2);
      if (!env.FANZA_API_ID || !env.FANZA_AFFILIATE_ID) return json({ ok: false, error: "api_not_configured" }, 500, cors2);
      let mbody;
      try { mbody = await request.json(); } catch (e) { return json({ ok: false, error: "bad_json" }, 400, cors2); }
      const makerId = String(mbody.makerId || "").trim();
      if (!/^\d{1,10}$/.test(makerId)) return json({ ok: false, error: "bad_maker_id" }, 400, cors2);
      const sort = ({ date: "date", rank: "rank", review: "review" })[String(mbody.sort || "date")] || "date";
      try {
        const result = await fetchAllMakerItems(env, makerId, sort);
        return json({ ok: true, total: result.items.length, floors: result.floors, items: result.items }, 200, cors2);
      } catch (e) {
        return json({ ok: false, error: "api_error", reason: String(e && e.message || e) }, 502, cors2);
      }
    }

    // ── PC取得依頼キュー：フル情報が取れなかったcid一覧＋登録済み上書き一覧（PCバッチが読む）──
    //    ※認証は「配布しない管理鍵(ADMIN_SECRET)」。公開ソフト鍵(SHARED_SECRET)では読めない。
    if (path === "/api/fanza-queue") {
      if (request.method !== "GET") return json({ ok: false, error: "method_not_allowed" }, 405, null);
      if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
      if (!env.FANZA_KV && !env.FANZA_DB) return json({ ok: false, error: "store_unbound" }, 500, null);
      const infoQ = await stQueueList(env, "info"); // 取得依頼中のcid（+book等のスクレイプ先url）
      const queuedUrls = {};
      infoQ.forEach((q) => { if (q.url) queuedUrls[q.cid] = q.url; });
      return json({
        ok: true,
        queued: infoQ.map((q) => q.cid),
        queuedUrls: queuedUrls,
        overridden: await stListOverrideCids(env),   // 上書き登録済みのcid（価格更新のため再取得対象）
      }, 200, null);
    }

    // ── 上書き情報の登録：PCスクレイプ結果(フル情報)を保存。以後 /api/fanza-item が優先返却 ──
    //    ※認証は管理鍵。保存前に許可フィールドのみ再構築（任意JSONの持ち込み・画像URLすり替え防止）。
    if (path === "/api/fanza-override") {
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, null);
      if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
      if (!env.FANZA_KV) return json({ ok: false, error: "kv_unbound" }, 500, null);
      let body;
      try { body = await request.json(); } catch (e) { return json({ ok: false, error: "bad_json" }, 400, null); }
      const items = Array.isArray(body.items) ? body.items.slice(0, 100) : []; // KV操作上限対策で1回100件まで
      let saved = 0, skipped = 0, quotaHit = false;
      for (const raw of items) {
        const it = sanitizeOverride(raw);
        if (!it) continue;
        if (quotaHit) { skipped++; continue; } // 上限到達後は残りを静かにスキップ（1件のクラッシュで全件失敗にしない）
        try {
          // 内容が前回と同一なら書き込みを省略（stPutOverride内蔵のdedup）。保存できたら取得依頼を消す。
          const { saved: didSave } = await stPutOverride(env, it);
          if (didSave) { await stQueueDelete(env, it.content_id, "info"); saved++; } else skipped++;
        } catch (e) {
          if (String(e && e.message || e).indexOf("limit exceeded") >= 0) quotaHit = true;
          skipped++;
        }
      }
      return json({ ok: true, saved, skipped, quotaHit: quotaHit || undefined }, 200, null);
    }

    // ── 実売本数（販売数）：作品詳細ページの「販売数」を返す（APIには無い数値）。──
    //   POST /api/fanza-sales { cid } or { cids:[...最大30] } → { ok, sales:{cid:number}, missing:[...] }
    //   ★販売数はDMM詳細ページHTMLにのみ存在し、そのページは海外IP(Cloudflare)だとログインへ飛ばされ
    //     取得不能。そのためPC(日本IP)のバッチがスクレイプして KV(sales:<cid>) へ保存したものを返す。
    //     KVに無いcidは missing に入れて返す（フロントはPC取得を促す/レビュー代理表示にフォールバック）。
    if (path === "/api/fanza-sales") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const cors3 = corsHeaders(origin, allowed);
      if (!cors3) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, cors3);
      const sec3 = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || sec3 !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, cors3);
      if (!env.FANZA_KV) return json({ ok: false, error: "kv_unbound" }, 500, cors3);
      let sbody;
      try { sbody = await request.json(); } catch (e) { return json({ ok: false, error: "bad_json" }, 400, cors3); }
      let cids = Array.isArray(sbody.cids) ? sbody.cids : (sbody.cid ? [sbody.cid] : []);
      cids = cids.map((c) => String(c || "").trim()).filter((c) => /^[0-9A-Za-z_]{1,64}$/.test(c)).slice(0, 30);
      if (!cids.length) return json({ ok: false, error: "missing_cid" }, 400, cors3);
      const { sales, missing } = await stGetSalesMany(env, cids);
      // 未取得cidは「PC取得依頼キュー(販売数)」へ（24h以内に登録済みなら書かない=stQueueSalesPut内蔵）。
      await Promise.all(missing.map(async (cid) => { try { await stQueueSalesPut(env, cid); } catch (e) {} }));
      return json({ ok: true, sales, missing }, 200, cors3);
    }

    // ── 販売数の登録（PCバッチが日本IPでスクレイプした販売数を保存）。認証は管理鍵。──
    //   POST /api/fanza-sales-save { items:[{cid,n}] }
    if (path === "/api/fanza-sales-save") {
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, null);
      if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
      if (!env.FANZA_KV) return json({ ok: false, error: "kv_unbound" }, 500, null);
      let body;
      try { body = await request.json(); } catch (e) { return json({ ok: false, error: "bad_json" }, 400, null); }
      const items = Array.isArray(body.items) ? body.items.slice(0, 200) : [];
      let saved = 0, skipped = 0, quotaHit = false;
      for (const raw of items) {
        const cid = String((raw && raw.cid) || "").trim();
        const n = raw && raw.n != null ? parseInt(raw.n, 10) : NaN;
        if (!/^[0-9A-Za-z_]{1,64}$/.test(cid) || isNaN(n)) continue;
        if (quotaHit) { skipped++; continue; } // 上限到達後は残りを静かにスキップ（1件のクラッシュで全件失敗にしない）
        try {
          // 数値が前回と同じなら書き込み省略（stPutSales内蔵）。保存できたら取得依頼を消す。
          const { saved: didSave } = await stPutSales(env, cid, n);
          if (didSave) { await stQueueDelete(env, cid, "sales"); saved++; } else skipped++;
        } catch (e) {
          if (String(e && e.message || e).indexOf("limit exceeded") >= 0) quotaHit = true;
          skipped++;
        }
      }
      return json({ ok: true, saved, skipped, quotaHit: quotaHit || undefined }, 200, null);
    }

    // ── 販売数の「今すぐ取得」リモート要求：どの端末のWebアプリからでも押せる。──
    //   POST（公開ソフト鍵＋Origin）= スマホ等が「今すぐPCで取得して」とフラグを立てる
    //   GET （管理鍵）              = PC常駐タスク(--poll)がフラグを読んで消費する
    //   ★実際のスクレイプはPC(日本IP)でしか動かないので、これは「実行の予約」だけを担う。
    if (path === "/api/fanza-sales-run") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      if (request.method === "GET") {
        if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
        const v = await stGetFlag(env, "sales_run");
        // 既定は peek（消さない）。?consume=1 の時だけ消費。
        // ※実行を確約した後にだけ消費することで、直近ガードで見送った要求を取りこぼさない。
        if (v && url.searchParams.get("consume") === "1") await stDeleteFlag(env, "sales_run");
        return json({ ok: true, pending: !!v, at: (v && v.at) || null }, 200, null);
      }
      const corsR = corsHeaders(origin, allowed);
      if (!corsR) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, corsR);
      const secR = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || secR !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, corsR);
      try {
        // dedup: 既に取得要求が立っていれば書き直さない(ボタン連打・複数端末からの同時要求でのKV消費防止)。
        await stPutFlagIfAbsent(env, "sales_run");
      } catch (e) {
        // KV1日書き込み上限等で失敗しても「クラッシュ(素の500)」ではなく分かるエラーを返す。
        const msg = String(e && e.message || e);
        return json({ ok: false, error: msg.indexOf("limit exceeded") >= 0 ? "kv_quota_exceeded" : "kv_error" }, 503, corsR);
      }
      return json({ ok: true, requested: true }, 200, corsR);
    }

    // ── 販売数の追跡サークル登録：候補タブでサークルタブを追加/削除した時にフロントが呼ぶ。──
    //   POST /api/fanza-sales-track { makerId, name } / 解除は { makerId, remove:true }
    //   登録済みサークルはPCバッチが「表示しなくても」全作品の販売数を自動取得する。
    if (path === "/api/fanza-sales-track") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const cors4 = corsHeaders(origin, allowed);
      if (!cors4) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, cors4);
      const sec4 = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || sec4 !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, cors4);
      let tbody;
      try { tbody = await request.json(); } catch (e) { return json({ ok: false, error: "bad_json" }, 400, cors4); }
      const mkId = String(tbody.makerId || "").trim();
      if (!/^\d{1,10}$/.test(mkId)) return json({ ok: false, error: "bad_maker_id" }, 400, cors4);
      if (tbody.remove) { await stDeleteMaker(env, mkId); return json({ ok: true, removed: mkId }, 200, cors4); }
      const mkName = String(tbody.name || "").slice(0, 100);
      try {
        // 既に同じ名前で登録済みなら書き込みを省略（stPutMaker内蔵）。
        await stPutMaker(env, mkId, mkName);
      } catch (e) {
        const msg = String(e && e.message || e);
        return json({ ok: false, error: msg.indexOf("limit exceeded") >= 0 ? "kv_quota_exceeded" : "kv_error" }, 503, cors4);
      }
      return json({ ok: true, tracked: mkId }, 200, cors4);
    }

    // ── 販売数の取得依頼キュー＋追跡サークル一覧（PCバッチが読む）。認証は管理鍵。──
    if (path === "/api/fanza-sales-queue") {
      if (request.method !== "GET") return json({ ok: false, error: "method_not_allowed" }, 405, null);
      if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
      if (!env.FANZA_KV && !env.FANZA_DB) return json({ ok: false, error: "store_unbound" }, 500, null);
      const trackedMakers = await stListMakers(env);
      const salesQ = await stQueueList(env, "sales");
      return json({ ok: true, queued: salesQ.map((q) => q.cid), trackedMakers }, 200, null);
    }

    // ── 一度きり：KV→D1 バックフィル（移行Phase1-C）。認証は管理鍵。冪等（何度呼んでも同じ結果）。──
    //   読み取り(KV)は無制限、書き込み(D1)は10万行/日なので351件程度は一撃。途中で切れても再実行で収束。
    //   ※このエンドポイントは移行専用。USE_D1="off"の間も既存ハンドラの挙動には一切影響しない（純増）。
    if (path === "/api/d1-backfill") {
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, null);
      if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
      if (!env.FANZA_KV) return json({ ok: false, error: "kv_unbound" }, 500, null);
      if (!env.FANZA_DB) return json({ ok: false, error: "d1_unbound" }, 500, null);
      try {
        const stats = await backfillKvToD1(env);
        return json({ ok: true, ...stats }, 200, null);
      } catch (e) {
        return json({ ok: false, error: String(e && e.message || e) }, 500, null);
      }
    }

    // ── 継続改善制度: 行動ログ受け口（フロントの core/kaizen-log.js が送る）──
    //   POST /api/kaizen-event { events:[{screen,action,objectType,objectId,meta,deviceType,sessionId}] }
    //   認証=公開ソフト鍵+Origin(他のフロント向けAPIと同型)。保存先=D1 go5_kaizen(KAIZEN_DB)。
    //   秘密を持ち込めないようフィールド許可制+文字数上限で再構築してから保存する。
    if (path === "/api/kaizen-event") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const corsK = corsHeaders(origin, allowed);
      if (!corsK) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, corsK);
      const secK = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || secK !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, corsK);
      if (!env.KAIZEN_DB) return json({ ok: false, error: "kaizen_unbound" }, 500, corsK);
      let kbody;
      try { kbody = await request.json(); } catch (e) { return json({ ok: false, error: "bad_json" }, 400, corsK); }
      const evs = Array.isArray(kbody.events) ? kbody.events.slice(0, 50) : [];
      const S = (v, n) => String(v == null ? "" : v).slice(0, n);
      const ID = (v, n) => (/^[0-9A-Za-z_:\-\.\/]*$/.test(String(v == null ? "" : v)) ? S(v, n) : "");
      const stmts = [];
      for (const raw of evs) {
        if (!raw || !raw.action) continue;
        stmts.push(env.KAIZEN_DB.prepare(
          "INSERT INTO user_events(device_type,session_id,screen,action,object_type,object_id,metadata) VALUES(?,?,?,?,?,?,?)"
        ).bind(
          S(raw.deviceType, 8), ID(raw.sessionId, 16), S(raw.screen, 40), S(raw.action, 64),
          S(raw.objectType, 32), S(raw.objectId, 80), S(raw.meta, 300)
        ));
      }
      if (!stmts.length) return json({ ok: true, saved: 0 }, 200, corsK);
      try { await env.KAIZEN_DB.batch(stmts); } catch (e) { return json({ ok: false, error: "d1_error" }, 503, corsK); }
      return json({ ok: true, saved: stmts.length }, 200, corsK);
    }

    // ── KV↔D1 照合（on切替前の安全確認）。認証は管理鍵。読み取りのみ（無害）。──
    if (path === "/api/d1-verify") {
      if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
      if (!env.FANZA_KV || !env.FANZA_DB) return json({ ok: false, error: "store_unbound" }, 500, null);
      try {
        const rep = await verifyKvVsD1(env);
        return json({ ok: true, ...rep }, 200, null);
      } catch (e) {
        return json({ ok: false, error: String(e && e.message || e) }, 500, null);
      }
    }

    if (path === "/" || path === "") {
      const mode = (env.FANZA_API_ID) ? "api+scrape" : "scrape-only";
      return text("go5-fanza-proxy ok (mode=" + mode + ")", 200);
    }

    return json({ ok: false, error: "not_found" }, 404, null);
  }
};

// DMM ItemList の item を候補タブ用の軽量オブジェクトへ整形。
function mapMakerItem(it) {
  const prices = it.prices || {};
  const lp = prices.list_price != null && prices.list_price !== "" ? parseInt(prices.list_price, 10) : null;
  const pr = prices.price != null && prices.price !== "" ? parseInt(prices.price, 10) : null;
  const disc = (lp != null && pr != null && lp > 0 && pr < lp) ? Math.round((1 - pr / lp) * 100) : 0; // pr=0(100%OFF)も割引計算する
  const img = it.imageURL || {};
  const rv = it.review || {};
  const info = it.iteminfo || {};
  const mk = (Array.isArray(info.maker) && info.maker[0]) ? info.maker[0] : null;
  const genres = (Array.isArray(info.genre) ? info.genre : []).map((g) => String((g && g.name) || "")).filter(Boolean);
  return {
    cid: it.content_id || "", title: it.title || "", url: (it.URL || "").split("?")[0],
    date: it.date || "", listPrice: lp, price: pr, discountPct: disc,
    reviewCount: rv.count != null ? rv.count : null, reviewAvg: rv.average != null ? rv.average : null,
    thumb: String(img.list || img.small || img.large || ""),
    makerName: mk ? String(mk.name || "") : "",
    genres: genres,
  };
}

// 指定サークル(maker)の作品を「全ページ×全同人フロア(通常/BL/TL)」で巡回取得し、cidで重複排除して返す。
// フロント側での取りこぼし(offset頭打ち)・フロア分割による欠落を根本から防ぐ。
async function fetchAllMakerItems(env, makerId, sort) {
  const FLOORS = ["digital_doujin", "digital_doujin_bl", "digital_doujin_tl"];
  const seen = new Set();
  const items = [];
  const floorsHit = [];
  for (const floor of FLOORS) {
    let offset = 1, floorTotal = 0;
    for (let guard = 0; guard < 30; guard++) { // 30×100=3000件/フロアの安全上限
      const params = new URLSearchParams({
        api_id: env.FANZA_API_ID, affiliate_id: env.FANZA_AFFILIATE_ID,
        site: "FANZA", service: "doujin", floor: floor,
        article: "maker", article_id: makerId,
        hits: "100", offset: String(offset), sort: sort, output: "json",
      });
      const data = await fetchDmmJson(DMM_API_BASE + "?" + params.toString(), 2);
      if (!data || !data.result) break;
      const pageItems = Array.isArray(data.result.items) ? data.result.items : [];
      floorTotal = parseInt(data.result.total_count, 10) || 0;
      for (const it of pageItems) {
        const cid = it.content_id || "";
        if (!cid || seen.has(cid)) continue;
        seen.add(cid); items.push(mapMakerItem(it));
      }
      // 次ページの有無：このフロアの total に達したか、100件未満で終端。
      if (pageItems.length < 100 || offset + 100 > floorTotal) break;
      offset += 100;
    }
    if (floorTotal > 0) floorsHit.push({ floor: floor, total: floorTotal }); // 診断用（作品のあるフロアのみ・1回）
  }
  return { items: items, floors: floorsHit };
}

// DMM APIのGET（一時的な失敗はshort backoffでリトライ）。成功時のみJSONを返す。
async function fetchDmmJson(url, tries) {
  for (let t = 0; t < tries; t++) {
    try {
      const res = await fetch(url, { headers: { "Accept": "application/json" } });
      if (res.ok) return await res.json();
    } catch (e) { /* リトライ */ }
    if (t < tries - 1) await new Promise((r) => setTimeout(r, 250));
  }
  return null;
}

// ── DMM 公式 API ─────────────────────────────────────────────────────────────
// https://affiliate.dmm.com/api/  で API ID を取得後に有効になる。
// doujin フロアで見つからない場合は複数フロアを試みる（CID プレフィックスで判定）。
async function fetchViaApi(cid, apiId, affiliateId) {
  // CID プレフィックスからフロアを推定。※FANZAの正しい service/floor コード（FloorList APIで確認済み）。
  //   同人＝service:doujin / floor:digital_doujin（旧コード service:digital,floor:doujin は無効）。
  //   FANZA Books＝service:ebook（comic/novel/photo/bl/tl の5フロア）。cid は b915… 形式または
  //   URL1階層目の数字ID（どちらでも cid= 照会が通ることを実測確認済み）。
  const DOUJIN_FLOORS = [
    { service: "doujin", floor: "digital_doujin"    }, // 同人（通常）
    { service: "doujin", floor: "digital_doujin_bl" }, // 同人BL
    { service: "doujin", floor: "digital_doujin_tl" }, // 同人TL
  ];
  const EBOOK_FLOORS = [
    { service: "ebook", floor: "comic" }, // 電子コミック
    { service: "ebook", floor: "novel" }, // 美少女ノベル・官能小説
    { service: "ebook", floor: "photo" }, // アダルト写真集・雑誌
    { service: "ebook", floor: "bl"    }, // BL
    { service: "ebook", floor: "tl"    }, // TL
  ];
  const VIDEO_FLOORS = [
    { service: "digital", floor: "videoc" }, // 素人・アダルト動画
    { service: "digital", floor: "anime"  }, // アニメ動画
  ];
  let floors;
  if (cid.startsWith("d_")) floors = DOUJIN_FLOORS;
  else if (/^(?:b\d|\d+$)/.test(cid)) floors = EBOOK_FLOORS.concat(VIDEO_FLOORS); // Books系はebook優先
  else floors = VIDEO_FLOORS.concat(EBOOK_FLOORS);

  for (const { service, floor } of floors) {
    try {
      const params = new URLSearchParams({
        api_id:       apiId,
        affiliate_id: affiliateId,
        site:         "FANZA",
        service:      service,
        floor:        floor,
        cid:          cid,
        output:       "json",
      });
      // 一時的な失敗（ネットワーク/レート）を吸収するため最大2回リトライしてからJSONを得る。
      const data = await fetchDmmJson(DMM_API_BASE + "?" + params.toString(), 2);
      if (!data) continue;
      const items = (data.result && Array.isArray(data.result.items)) ? data.result.items : [];
      if (!items.length) continue;
      const it = items[0];
      const prices = it.prices || {};
      // 同人はサークル名が iteminfo.maker に入る（author は空）。maker優先→author→circleでフォールバック。
      const info = it.iteminfo || {};
      const makerArr = Array.isArray(info.maker) ? info.maker : [];
      const circleArr = Array.isArray(info.circle) ? info.circle : [];
      const authorArr = makerArr.length ? makerArr : (Array.isArray(info.author) && info.author.length ? info.author : circleArr);
      var genreArr = Array.isArray(info.genre) ? info.genre : [];
      // ebook(Books)後処理：Booksの商品ページ(JSON-LD offers.price)はセール中でも定価のまま
      // 返る癖があるが、公式APIの prices.list_price/price が同じ癖を持つかは未確認（要live確認）。
      // 確証が無いため副作用ゼロの形にとどめる＝APIレスポンスに割引後価格の手がかり
      // (deliveries等の内訳)が実在すればそちらの最安値を採用し、無ければ何もせず素通しする。
      let apiListPrice = prices.list_price || null;
      let apiPrice = prices.price || null;
      if (service === "ebook" && Array.isArray(prices.deliveries) && prices.deliveries.length) {
        const dPrices = prices.deliveries
          .map((d) => parseInt(d && d.price, 10))
          .filter((n) => Number.isFinite(n) && n >= 0);
        if (dPrices.length) {
          const minD = Math.min.apply(null, dPrices);
          if (apiPrice == null || minD < apiPrice) {
            if (apiListPrice == null) apiListPrice = apiPrice;
            apiPrice = minD;
          }
        }
      }
      return {
        content_id:   cid,
        title:        it.title || "",
        date:         it.date  || "",   // 発売日（作品状態=新作/準新作/旧作 の判定に使用）
        service_name: it.service_name || "",
        floor_name:   it.floor_name   || "",
        imageURL:       it.imageURL       || null,   // {list, large}
        sampleImageURL: it.sampleImageURL || null,   // {sample_s:{image:[]}, sample_l:{image:[]}}
        iteminfo:   { author: authorArr, genre: genreArr },
        prices: {
          list_price: apiListPrice,
          price:      apiPrice,
        },
        review: it.review || { count: null, average: null },
      };
    } catch (e) { /* フロアごとに失敗しても続ける */ }
  }
  return null;
}

// ── HTML スクレイピング ───────────────────────────────────────────────────────
// og:title → JSON-LD Product → <title> の順でタイトルを取得する。
// ★CloudflareのIPは海外扱いされ、DMMが /en/age_check/?rurl=… へ302で飛ばす（API未収録作品が
//   スクレイプでも取れなかった根本原因）。redirect:manual で追い、age_check へ飛ばされたら
//   rurl を取り出して年齢クッキー付きで直接再訪問して突破する。
const SCRAPE_HEADERS = {
  "Cookie":          "age_check_done=1; ckcy=1; cklg=ja",
  "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
  "Referer":         "https://www.dmm.co.jp/",
};
async function fetchDmmPage(url, trace) {
  let cur = url;
  for (let hop = 0; hop < 6; hop++) {
    const res = await fetch(cur, { headers: SCRAPE_HEADERS, redirect: "manual" });
    if (trace) trace.push({ hop, url: cur, status: res.status, loc: res.headers.get("location") || "" });
    if (res.status >= 300 && res.status < 400) {
      let loc = res.headers.get("location") || "";
      if (!loc) return res;
      try { loc = new URL(loc, cur).href; } catch (e) { return res; }
      // 年齢確認ページへ飛ばされた → rurl（本来の行き先）を取り出して直接再訪問。
      const m = loc.match(/[?&]rurl=([^&]+)/);
      if (/age_check/.test(loc) && m) {
        try { loc = decodeURIComponent(m[1]); } catch (e) {}
        // /en/ 版へ差し替えられている場合は日本版URLへ戻す
        loc = loc.replace("://www.dmm.co.jp/en/", "://www.dmm.co.jp/");
      }
      if (loc === cur) return res; // 同一URLへのループ＝突破不能
      cur = loc;
      continue;
    }
    return res;
  }
  return null;
}
async function scrapeFanzaItem(cid, srcUrl) {
  // srcUrl（FANZA Books等の実ページURL・呼び出し元で許可ドメイン検証済み）があればそちらを優先。
  const isBook = /book\.dmm\./.test(srcUrl); // FANZAブックス判定（同人ページとは価格の出方が異なる＝下記価格ブロックで分岐）
  const pageUrl = srcUrl || (DMM_DOUJIN_BASE + encodeURIComponent(cid) + "/");
  let res;
  try { res = await fetchDmmPage(pageUrl); } catch (e) { return null; }
  if (!res || !res.ok) return null;
  const html = await res.text();

  // ブロック・年齢確認ページ検出
  if (html.includes("age_check") && !html.includes("og:title")) return null;

  let title = "";
  let circleName = "";

  // ① og:title（最も安定）
  const ogTitleM = html.match(/<meta\s+[^>]*property=["']og:title["']\s+content=["']([^"']+)["']/i)
    || html.match(/<meta\s+[^>]*content=["']([^"']+)["']\s+property=["']og:title["']/i);
  if (ogTitleM && ogTitleM[1]) title = ogTitleM[1].trim();

  // ② JSON-LD Product
  if (!title) {
    const ldRe = /<script\s+type=["']application\/ld\+json["']>([\s\S]*?)<\/script>/g;
    let ldM;
    while ((ldM = ldRe.exec(html)) !== null) {
      try {
        const obj = JSON.parse(ldM[1]);
        if (obj["@type"] === "Product" && obj.name) {
          title = obj.name;
          if (obj.brand && obj.brand.name) circleName = String(obj.brand.name);
          break;
        }
      } catch (e) {}
    }
  }

  // ③ <title> タグ（サイト名を除去）
  if (!title) {
    const tM = html.match(/<title>([^<]+)<\/title>/);
    if (tM) title = tM[1].replace(/\s*[|｜【].*$/, "").trim();
  }

  if (!title) return null;

  // ログイン・年齢確認・ブロックページは商品タイトルでない → null 扱い
  if (
    title.includes('ログイン') ||
    title.toLowerCase().includes('login') ||
    title.includes('年齢確認') ||
    title.includes('エラー') ||
    title === 'FANZA' ||
    title === 'DMM'
  ) return null;

  // 価格情報（取れれば付ける）
  let currentPriceStr = null;
  let listPriceStr = null;
  if (isBook) {
    // FANZAブックス：JSON-LD offers.price はセール中でも定価のままのことがある（値引きは
    // カート適用のため）。定価＋割引バッジ(>◯%OFF<)から割引後価格を逆算する。
    // ロジックは scripts/fetch_missing_works.mjs の scrapeBookPage() と同一（移植・同期を保つ）。
    const ldPriceM = html.match(/["']offers["']\s*:\s*\{[^}]*["']price["']\s*:\s*["']?(\d+)/);
    let price = ldPriceM ? parseInt(ldPriceM[1], 10) : null;
    const lm = html.match(/(?:定価|通常価格|参考価格)[^0-9]{0,16}([\d,]+)\s*円/);
    let listPrice = lm ? parseInt(lm[1].replace(/,/g, ""), 10) : null;
    if (listPrice == null) listPrice = price; // 定価表記が無ければ現在価格＝定価扱い
    const offM = html.match(/>\s*(\d{1,3})\s*[%％]\s*OFF\s*</i);
    if (offM && price != null) {
      const pct = parseInt(offM[1], 10);
      if (pct > 0 && pct <= 100) {
        if (listPrice == null || listPrice < price) listPrice = price; // 定価＝JSON-LDの価格
        price = Math.round(listPrice * (100 - pct) / 100);              // 割引後（100%OFFなら0円）
      }
    }
    currentPriceStr = price != null ? String(price) : null;
    listPriceStr = listPrice != null ? String(listPrice) : null;
  } else {
    // 同人（従来ロジック・無変更）
    const currentPriceM = html.match(/["']offers["']\s*:\s*\{[^}]*["']price["']\s*:\s*["']?(\d+)/);
    currentPriceStr = currentPriceM ? currentPriceM[1] : null;

    const lpM = html.match(/priceList__sub--big[^>]*>[\s\S]{0,80}?([\d,]+)円/);
    listPriceStr = lpM ? lpM[1].replace(/,/g, "") : null;
  }

  // 発売日（JSON-LD releaseDate / 商品情報の「YYYY-MM-DD」表記から拾えれば）。取れなければ空。
  var dateStr = "";
  var rdM = html.match(/["']releaseDate["']\s*:\s*["'](\d{4}-\d{2}-\d{2})/)
    || html.match(/(?:発売日|配信開始日)[^0-9]{0,12}(\d{4})[\/\-年](\d{1,2})[\/\-月](\d{1,2})/);
  if (rdM) {
    dateStr = rdM.length >= 4 && rdM[2] ? (rdM[1] + "-" + ("0" + rdM[2]).slice(-2) + "-" + ("0" + rdM[3]).slice(-2)) : rdM[1];
  }

  // サムネ（og:image）。サンプル画像はスクレイプでは安定取得できないため空。
  var ogImgM = html.match(/<meta\s+[^>]*property=["']og:image["']\s+content=["']([^"']+)["']/i)
    || html.match(/<meta\s+[^>]*content=["']([^"']+)["']\s+property=["']og:image["']/i);
  var ogImg = ogImgM && ogImgM[1] ? ogImgM[1].trim() : "";

  // サークルID：ページ内のサークル一覧リンク（…/article=maker/id=数字/…）から抽出。
  //   ★これで API未収録作品でも「作品URL→サークルID→全作品」の導線が繋がる（候補タブ用）。
  //   注意: ページには「関連サークルのおすすめ」リンク(…/id=NNN/sort=date/…)も混じる。作品自身の
  //   サークルはパンくず・サークル名・「このサークルの他の作品」等で何度も出るため、
  //   「sort= を含まない素のリンク(/id=NNN/ の直後が sort= でない)」の最頻値を採用する。
  var makerCounts = {};
  var mkRe = /article=maker\/id=(\d+)\/(?!sort=)/g;
  var mkm;
  while ((mkm = mkRe.exec(html)) !== null) { makerCounts[mkm[1]] = (makerCounts[mkm[1]] || 0) + 1; }
  var makerId = "";
  var bestCount = 0;
  for (var mid in makerCounts) { if (makerCounts[mid] > bestCount) { bestCount = makerCounts[mid]; makerId = mid; } }
  // サークル名：採用した makerId のリンクのアンカーテキスト（表示名）から拾う（JSON-LDで取れない時の保険）。
  if (makerId && !circleName) {
    var anchorRe = new RegExp("article=maker\\/id=" + makerId + "\\/[^>]*>\\s*([^<]{1,60}?)\\s*<", "i");
    var anchorM = html.match(anchorRe);
    if (anchorM && anchorM[1]) {
      var nm = anchorM[1].replace(/&amp;/g, "&").trim();
      // 「もっと見る」等のUI文言や空は除外
      if (nm && !/^(もっと見る|一覧|>|＞|»)$/.test(nm)) circleName = nm;
    }
  }
  var authorArr = makerId
    ? [{ id: makerId, name: circleName || "" }]
    : (circleName ? [{ name: circleName }] : []);

  return {
    content_id: cid,
    title:      title,
    date:       dateStr,
    service_name: isBook ? "FANZAブックス" : "同人",
    floor_name:   isBook ? "ブックス"     : "同人",
    imageURL:       ogImg ? { list: ogImg, large: ogImg } : null,
    sampleImageURL: null,
    iteminfo:   { author: authorArr, genre: [] },
    prices: {
      list_price: listPriceStr,
      price:      currentPriceStr,
    },
    review: { count: null, average: null },
  };
}

// ── 管理エンドポイント用ヘルパ ─────────────────────────────────────────────────
// 管理鍵（配布しない・PCバッチのみ保持）。公開ソフト鍵とは別物＝書き込み/列挙を第三者から守る。
function adminOk(request, env) {
  const s = request.headers.get("X-Admin-Secret") || "";
  return !!(env.ADMIN_SECRET && s === env.ADMIN_SECRET);
}
// KV list はデフォルト1000件で打ち切られるため、cursor で全件たどる。
async function listAll(kv, prefix) {
  const out = [];
  let cursor;
  do {
    const r = await kv.list(cursor ? { prefix, cursor } : { prefix });
    r.keys.forEach((k) => out.push(k.name.slice(prefix.length)));
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return out;
}

// ══ ストレージ抽象層（KV or D1・env.USE_D1 で切替）════════════════════════════
//   off  = KVのみ（現行・デフォルト）
//   dual = 読みはKV（両書きでKVも最新）／書きは D1+KV 両方（D1を実データで検証しつつKVで安全網）
//   on   = 読み書きともD1のみ（カットオーバー後・KV書き込み停止＝1,000/日の天井が消える）
//   ★dualでKVも最新に保つため、読みは on の時だけD1にすればよい（移行中の読み取りリスク最小）。
function d1on_(env) { return (env.USE_D1 || "off") === "on"; }      // 読みをD1にするか
function d1write_(env) { return (env.USE_D1 || "off") !== "off"; }  // D1へ書くか（dual/on）
function kvwrite_(env) { return (env.USE_D1 || "off") !== "on"; }   // KVへ書くか（off/dual）
function nowIso_() { return new Date().toISOString(); }
function plusDaysIso_(d) { return new Date(Date.now() + d * 86400000).toISOString(); }
function flagKvKey_(key) { return key === "sales_run" ? "salesrun:req" : ("flag:" + key); }
// D1書き込み実行：dual(KVも書く)ならD1失敗を握りつぶしてKV(安全網)へ進む／on(D1のみ)なら失敗を伝播。
async function d1run_(env, stmt) {
  try { await stmt.run(); return true; }
  catch (e) { if (kvwrite_(env)) return false; throw e; }
}

// ---- override（作品フル情報：works.info_json） ----
async function stGetOverride(env, cid) {
  if (d1on_(env)) {
    const r = await env.FANZA_DB.prepare("SELECT info_json FROM works WHERE cid=?").bind(cid).first().catch(() => null);
    return (r && r.info_json) ? safeJsonParse_(r.info_json) : null;
  }
  return await env.FANZA_KV.get("ov:" + cid, "json").catch(() => null);
}
async function stListOverrideCids(env) {
  if (d1on_(env)) {
    const rs = await env.FANZA_DB.prepare("SELECT cid FROM works WHERE info_json IS NOT NULL").all().catch(() => null);
    return (rs && rs.results) ? rs.results.map((r) => r.cid) : [];
  }
  return await listAll(env.FANZA_KV, "ov:");
}
async function stPutOverride(env, item) { // returns {saved}
  const cid = item.content_id, newStr = JSON.stringify(item);
  let saved = false;
  if (d1write_(env)) {
    const r = await env.FANZA_DB.prepare("SELECT info_json FROM works WHERE cid=?").bind(cid).first().catch(() => null);
    if (!r || r.info_json !== newStr) {
      if (await d1run_(env, env.FANZA_DB.prepare("INSERT INTO works(cid,title,info_json,scraped_at,updated_at) VALUES(?,?,?,?,datetime('now')) ON CONFLICT(cid) DO UPDATE SET title=excluded.title, info_json=excluded.info_json, scraped_at=excluded.scraped_at, updated_at=datetime('now')")
        .bind(cid, item.title || null, newStr, item.scrapedAt || null))) saved = true;
    }
  }
  if (kvwrite_(env)) {
    try {
      const prevStr = await env.FANZA_KV.get("ov:" + cid).catch(() => null);
      if (prevStr !== newStr) { await env.FANZA_KV.put("ov:" + cid, newStr); saved = true; }
    } catch (e) { if (!d1write_(env)) throw e; } // offはquota検出のため再送出／dualはD1が正なので握りつぶす
  }
  return { saved };
}

// ---- sales（実売本数：works.sales_n） ----
async function stGetSalesMany(env, cids) { // {sales:{cid:n}, missing:[cid]}
  const sales = {}, missing = [];
  if (d1on_(env)) {
    const ph = cids.map(() => "?").join(",");
    const rs = cids.length ? await env.FANZA_DB.prepare("SELECT cid, sales_n FROM works WHERE sales_n IS NOT NULL AND cid IN (" + ph + ")").bind(...cids).all().catch(() => null) : null;
    const found = new Set();
    if (rs && rs.results) rs.results.forEach((r) => { sales[r.cid] = r.sales_n; found.add(r.cid); });
    cids.forEach((c) => { if (!found.has(c)) missing.push(c); });
    return { sales, missing };
  }
  await Promise.all(cids.map(async (c) => {
    const v = await env.FANZA_KV.get("sales:" + c, "json").catch(() => null);
    if (v && v.n != null) sales[c] = v.n; else missing.push(c);
  }));
  return { sales, missing };
}
async function stPutSales(env, cid, n) { // returns {saved}
  let saved = false;
  if (d1write_(env)) {
    const r = await env.FANZA_DB.prepare("SELECT sales_n FROM works WHERE cid=?").bind(cid).first().catch(() => null);
    if (!r || r.sales_n !== n) {
      if (await d1run_(env, env.FANZA_DB.prepare("INSERT INTO works(cid,sales_n,sales_at,updated_at) VALUES(?,?,?,datetime('now')) ON CONFLICT(cid) DO UPDATE SET sales_n=excluded.sales_n, sales_at=excluded.sales_at, updated_at=datetime('now')")
        .bind(cid, n, nowIso_()))) saved = true;
    }
  }
  if (kvwrite_(env)) {
    try {
      const prev = await env.FANZA_KV.get("sales:" + cid, "json").catch(() => null);
      if (!(prev && prev.n === n)) { await env.FANZA_KV.put("sales:" + cid, JSON.stringify({ n, at: nowIso_() })); saved = true; }
    } catch (e) { if (!d1write_(env)) throw e; }
  }
  return { saved };
}

// ---- fetch_queue（取得依頼：req:=info / salesreq:=sales） ----
async function stQueueGet(env, cid, kind) { // {url, at}|null
  if (d1on_(env)) {
    const r = await env.FANZA_DB.prepare("SELECT src_url, requested_at FROM fetch_queue WHERE cid=? AND kind=? AND (expires_at IS NULL OR expires_at > ?)").bind(cid, kind, nowIso_()).first().catch(() => null);
    return r ? { url: r.src_url || "", at: r.requested_at } : null;
  }
  return await env.FANZA_KV.get((kind === "info" ? "req:" : "salesreq:") + cid, "json").catch(() => null);
}
async function stQueueList(env, kind) { // [{cid, url}]
  if (d1on_(env)) {
    const rs = await env.FANZA_DB.prepare("SELECT cid, src_url FROM fetch_queue WHERE kind=? AND (expires_at IS NULL OR expires_at > ?)").bind(kind, nowIso_()).all().catch(() => null);
    return (rs && rs.results) ? rs.results.map((r) => ({ cid: r.cid, url: r.src_url || "" })) : [];
  }
  const prefix = kind === "info" ? "req:" : "salesreq:";
  const cids = await listAll(env.FANZA_KV, prefix);
  const out = [];
  for (const cid of cids) { const v = await env.FANZA_KV.get(prefix + cid, "json").catch(() => null); out.push({ cid, url: (v && v.url) || "" }); }
  return out;
}
// info: 既存なら書かない（enrich=既存にurl無く今回srcUrlありの時のみ上書き）。req:はquota握りつぶし（原コード踏襲）。
async function stQueueInfoPut(env, cid, srcUrl) {
  const prev = await stQueueGet(env, cid, "info");
  const needEnrich = srcUrl && (!prev || !prev.url);
  if (prev && !needEnrich) return;
  const url = srcUrl || (prev && prev.url) || "";
  const at = nowIso_();
  if (d1write_(env)) {
    await env.FANZA_DB.prepare("INSERT INTO fetch_queue(cid,kind,src_url,requested_at,expires_at) VALUES(?,'info',?,?,?) ON CONFLICT(cid,kind) DO UPDATE SET src_url=excluded.src_url, requested_at=excluded.requested_at, expires_at=excluded.expires_at")
      .bind(cid, url || null, at, plusDaysIso_(7)).run().catch(() => {});
  }
  if (kvwrite_(env)) { try { await env.FANZA_KV.put("req:" + cid, JSON.stringify({ at, url }), { expirationTtl: 604800 }); } catch (e) {} }
}
// sales: 24h以内に登録済みなら書かない。
async function stQueueSalesPut(env, cid) {
  const prev = await stQueueGet(env, cid, "sales");
  if (prev && prev.at && (Date.now() - Date.parse(prev.at)) < 86400000) return;
  const at = nowIso_();
  if (d1write_(env)) {
    await env.FANZA_DB.prepare("INSERT INTO fetch_queue(cid,kind,requested_at,expires_at) VALUES(?,'sales',?,?) ON CONFLICT(cid,kind) DO UPDATE SET requested_at=excluded.requested_at, expires_at=excluded.expires_at")
      .bind(cid, at, plusDaysIso_(14)).run().catch(() => {});
  }
  if (kvwrite_(env)) { try { await env.FANZA_KV.put("salesreq:" + cid, JSON.stringify({ at }), { expirationTtl: 1209600 }); } catch (e) {} }
}
async function stQueueDelete(env, cid, kind) {
  if (d1write_(env)) await env.FANZA_DB.prepare("DELETE FROM fetch_queue WHERE cid=? AND kind=?").bind(cid, kind).run().catch(() => {});
  if (kvwrite_(env)) { try { await env.FANZA_KV.delete((kind === "info" ? "req:" : "salesreq:") + cid); } catch (e) {} }
}

// ---- tracked_makers（追跡サークル：salestrack:） ----
async function stGetMaker(env, mid) {
  if (d1on_(env)) {
    const r = await env.FANZA_DB.prepare("SELECT name FROM tracked_makers WHERE maker_id=?").bind(mid).first().catch(() => null);
    return r ? { name: r.name || "" } : null;
  }
  return await env.FANZA_KV.get("salestrack:" + mid, "json").catch(() => null);
}
async function stListMakers(env) { // [{makerId, name}]
  if (d1on_(env)) {
    const rs = await env.FANZA_DB.prepare("SELECT maker_id, name FROM tracked_makers").all().catch(() => null);
    return (rs && rs.results) ? rs.results.map((r) => ({ makerId: r.maker_id, name: r.name || "" })) : [];
  }
  const ids = await listAll(env.FANZA_KV, "salestrack:");
  const out = [];
  for (const mid of ids) { const v = await env.FANZA_KV.get("salestrack:" + mid, "json").catch(() => null); out.push({ makerId: mid, name: (v && v.name) || "" }); }
  return out;
}
async function stPutMaker(env, mid, name) { // 同名なら書かない。quotaはoffのみ再送出。
  const prev = await stGetMaker(env, mid);
  if (prev && prev.name === name) return;
  if (d1write_(env)) {
    await d1run_(env, env.FANZA_DB.prepare("INSERT INTO tracked_makers(maker_id,name,added_at) VALUES(?,?,?) ON CONFLICT(maker_id) DO UPDATE SET name=excluded.name")
      .bind(mid, name || null, nowIso_()));
  }
  if (kvwrite_(env)) {
    try { await env.FANZA_KV.put("salestrack:" + mid, JSON.stringify({ name, at: nowIso_() })); }
    catch (e) { if (!d1write_(env)) throw e; }
  }
}
async function stDeleteMaker(env, mid) {
  if (d1write_(env)) await env.FANZA_DB.prepare("DELETE FROM tracked_makers WHERE maker_id=?").bind(mid).run().catch(() => {});
  if (kvwrite_(env)) { try { await env.FANZA_KV.delete("salestrack:" + mid); } catch (e) {} }
}

// ---- run_flags（単発フラグ：salesrun:req = key 'sales_run'） ----
async function stGetFlag(env, key) {
  if (d1on_(env)) {
    const r = await env.FANZA_DB.prepare("SELECT requested_at FROM run_flags WHERE key=? AND (expires_at IS NULL OR expires_at > ?)").bind(key, nowIso_()).first().catch(() => null);
    return r ? { at: r.requested_at } : null;
  }
  return await env.FANZA_KV.get(flagKvKey_(key), "json").catch(() => null);
}
async function stPutFlagIfAbsent(env, key) { // 既に立っていれば書かない。quotaはoffのみ再送出。
  const prev = await stGetFlag(env, key);
  if (prev) return;
  const at = nowIso_();
  if (d1write_(env)) {
    await d1run_(env, env.FANZA_DB.prepare("INSERT INTO run_flags(key,requested_at,expires_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET requested_at=excluded.requested_at, expires_at=excluded.expires_at")
      .bind(key, at, plusDaysIso_(1)));
  }
  if (kvwrite_(env)) {
    try { await env.FANZA_KV.put(flagKvKey_(key), JSON.stringify({ at }), { expirationTtl: 86400 }); }
    catch (e) { if (!d1write_(env)) throw e; }
  }
}
async function stDeleteFlag(env, key) {
  if (d1write_(env)) await env.FANZA_DB.prepare("DELETE FROM run_flags WHERE key=?").bind(key).run().catch(() => {});
  if (kvwrite_(env)) { try { await env.FANZA_KV.delete(flagKvKey_(key)); } catch (e) {} }
}
function safeJsonParse_(s) { try { return JSON.parse(s); } catch (e) { return null; } }

// ── KV↔D1 照合（on切替前の安全確認）。キー集合の全件差分＋値サンプル比較。読み取りのみ。──
async function verifyKvVsD1(env) {
  const kv = env.FANZA_KV, db = env.FANZA_DB;
  const nowIso = nowIso_();
  const d1cids = async (sql, ...b) => { const rs = await db.prepare(sql).bind(...b).all().catch(() => null); return (rs && rs.results) ? rs.results.map((r) => r.cid != null ? r.cid : r.maker_id) : []; };
  const setDiff = (a, b) => { const bs = new Set(b); return a.filter((x) => !bs.has(x)); };
  const pair = (kvArr, d1Arr) => ({ kv: kvArr.length, d1: d1Arr.length, onlyKv: setDiff(kvArr, d1Arr).slice(0, 8), onlyD1: setDiff(d1Arr, kvArr).slice(0, 8) });

  const ov = pair(await listAll(kv, "ov:"), await d1cids("SELECT cid FROM works WHERE info_json IS NOT NULL"));
  const kvSales = await listAll(kv, "sales:");
  const sales = pair(kvSales, await d1cids("SELECT cid FROM works WHERE sales_n IS NOT NULL"));
  const reqInfo = pair(await listAll(kv, "req:"), await d1cids("SELECT cid FROM fetch_queue WHERE kind='info' AND (expires_at IS NULL OR expires_at > ?)", nowIso));
  const reqSales = pair(await listAll(kv, "salesreq:"), await d1cids("SELECT cid FROM fetch_queue WHERE kind='sales' AND (expires_at IS NULL OR expires_at > ?)", nowIso));
  const makers = pair(await listAll(kv, "salestrack:"), await d1cids("SELECT maker_id FROM tracked_makers"));

  // 値サンプル比較（sales_n）：先頭最大15件を KV と D1 で突き合わせ。
  let checked = 0, mismatch = 0; const samples = [];
  for (const cid of kvSales.slice(0, 15)) {
    const kvv = await kv.get("sales:" + cid, "json").catch(() => null);
    const d1v = await db.prepare("SELECT sales_n FROM works WHERE cid=?").bind(cid).first().catch(() => null);
    checked++;
    if (!kvv || !d1v || kvv.n !== d1v.sales_n) { mismatch++; if (samples.length < 5) samples.push({ cid, kv: kvv && kvv.n, d1: d1v && d1v.sales_n }); }
  }
  const clean = ov.onlyKv.length === 0 && ov.onlyD1.length === 0 && sales.onlyKv.length === 0 && sales.onlyD1.length === 0 &&
    reqInfo.onlyKv.length === 0 && reqSales.onlyKv.length === 0 && makers.onlyKv.length === 0 && makers.onlyD1.length === 0 && mismatch === 0;
  return { clean, ov, sales, reqInfo, reqSales, makers, valueSample: { checked, mismatch, samples } };
}

// ── KV→D1 バックフィル（移行Phase1-C）。冪等。ov:+sales:を works へ統合、req:/salesreq:を fetch_queue へ。──
async function backfillKvToD1(env) {
  const db = env.FANZA_DB, kv = env.FANZA_KV;
  const now = new Date().toISOString();
  const addDays = (d) => new Date(Date.now() + d * 86400000).toISOString();
  let works = 0, salesN = 0, queueInfo = 0, queueSales = 0, makers = 0, flags = 0;

  // ov: → works(title/info_json/scraped_at)
  for (const cid of await listAll(kv, "ov:")) {
    const ov = await kv.get("ov:" + cid, "json").catch(() => null);
    if (!ov) continue;
    await db.prepare(
      "INSERT INTO works(cid,title,info_json,scraped_at,updated_at) VALUES(?,?,?,?,datetime('now')) " +
      "ON CONFLICT(cid) DO UPDATE SET title=excluded.title, info_json=excluded.info_json, scraped_at=excluded.scraped_at, updated_at=datetime('now')"
    ).bind(cid, ov.title || null, JSON.stringify(ov), ov.scrapedAt || null).run();
    works++;
  }
  // sales: → works(sales_n/sales_at)  ※同一cidの ov: 行があれば統合される
  for (const cid of await listAll(kv, "sales:")) {
    const v = await kv.get("sales:" + cid, "json").catch(() => null);
    if (!v || v.n == null) continue;
    await db.prepare(
      "INSERT INTO works(cid,sales_n,sales_at,updated_at) VALUES(?,?,?,datetime('now')) " +
      "ON CONFLICT(cid) DO UPDATE SET sales_n=excluded.sales_n, sales_at=excluded.sales_at, updated_at=datetime('now')"
    ).bind(cid, v.n, v.at || now).run();
    salesN++;
  }
  // req: → fetch_queue(kind='info', src_url)
  for (const cid of await listAll(kv, "req:")) {
    const v = await kv.get("req:" + cid, "json").catch(() => null);
    await db.prepare(
      "INSERT INTO fetch_queue(cid,kind,src_url,requested_at,expires_at) VALUES(?,'info',?,?,?) " +
      "ON CONFLICT(cid,kind) DO UPDATE SET src_url=excluded.src_url, requested_at=excluded.requested_at, expires_at=excluded.expires_at"
    ).bind(cid, (v && v.url) || null, (v && v.at) || now, addDays(7)).run();
    queueInfo++;
  }
  // salesreq: → fetch_queue(kind='sales')
  for (const cid of await listAll(kv, "salesreq:")) {
    const v = await kv.get("salesreq:" + cid, "json").catch(() => null);
    await db.prepare(
      "INSERT INTO fetch_queue(cid,kind,requested_at,expires_at) VALUES(?,'sales',?,?) " +
      "ON CONFLICT(cid,kind) DO UPDATE SET requested_at=excluded.requested_at, expires_at=excluded.expires_at"
    ).bind(cid, (v && v.at) || now, addDays(14)).run();
    queueSales++;
  }
  // salestrack: → tracked_makers
  for (const mid of await listAll(kv, "salestrack:")) {
    const v = await kv.get("salestrack:" + mid, "json").catch(() => null);
    await db.prepare(
      "INSERT INTO tracked_makers(maker_id,name,added_at) VALUES(?,?,?) " +
      "ON CONFLICT(maker_id) DO UPDATE SET name=excluded.name"
    ).bind(mid, (v && v.name) || null, (v && v.at) || now).run();
    makers++;
  }
  // salesrun:req → run_flags('sales_run')
  const runFlag = await kv.get("salesrun:req", "json").catch(() => null);
  if (runFlag) {
    await db.prepare(
      "INSERT INTO run_flags(key,requested_at,expires_at) VALUES('sales_run',?,?) " +
      "ON CONFLICT(key) DO UPDATE SET requested_at=excluded.requested_at, expires_at=excluded.expires_at"
    ).bind(runFlag.at || now, addDays(1)).run();
    flags++;
  }
  return { works, salesN, queueInfo, queueSales, makers, flags };
}
// override の入力検証：許可フィールドのみ再構築。画像URLはDMM公式CDNドメイン限定。
const IMG_OK = /^https:\/\/(doujin-assets\.dmm\.co\.jp|pics\.dmm\.co\.jp|ebook-assets\.dmm\.com)\//;
function sanitizeOverride(raw) {
  if (!raw || typeof raw !== "object") return null;
  const cid = String(raw.content_id || "").trim();
  const title = String(raw.title || "").slice(0, 300);
  if (!/^[0-9A-Za-z_-]{1,64}$/.test(cid) || !title) return null;
  const numStr = (v) => (v != null && /^\d{1,9}$/.test(String(v))) ? String(v) : null;
  const img = (u) => (typeof u === "string" && IMG_OK.test(u) && u.length < 300) ? u : null;
  const names = (arr, max) => (Array.isArray(arr) ? arr : []).slice(0, max)
    .map((x) => ({ name: String((x && x.name) || "").slice(0, 64) })).filter((x) => x.name);
  const imageURL = raw.imageURL ? { list: img(raw.imageURL.list), large: img(raw.imageURL.large) } : null;
  const sImgs = (raw.sampleImageURL && raw.sampleImageURL.sample_l && Array.isArray(raw.sampleImageURL.sample_l.image))
    ? raw.sampleImageURL.sample_l.image.slice(0, 20).map(img).filter(Boolean) : [];
  return {
    content_id: cid,
    title,
    date: String(raw.date || "").slice(0, 32),
    service_name: String(raw.service_name || "同人").slice(0, 32),
    floor_name: String(raw.floor_name || "同人").slice(0, 32),
    imageURL: (imageURL && (imageURL.list || imageURL.large)) ? imageURL : null,
    sampleImageURL: sImgs.length ? { sample_l: { image: sImgs } } : null,
    iteminfo: { author: names(raw.iteminfo && raw.iteminfo.author, 3), genre: names(raw.iteminfo && raw.iteminfo.genre, 32) },
    prices: { list_price: numStr(raw.prices && raw.prices.list_price), price: numStr(raw.prices && raw.prices.price) },
    review: { count: null, average: null },
    scrapedAt: String(raw.scrapedAt || "").slice(0, 32),
  };
}

// ── 画像CDNフォールバック ─────────────────────────────────────────────────────
// doujin-assets.dmm.co.jp は認証・地域制限なし。URLは決定的パターン：
//   digital/{type}/{cid}/{cid}pl.jpg（大）/ pt.jpg（小）/ jp-001.jpg…（サンプル）
const DOUJIN_ASSET_TYPES = ["comic", "game", "voice", "cg"];
async function headInfo_(u) {
  try {
    const r = await fetch(u, { method: "HEAD" });
    return r.ok ? { ok: true, len: r.headers.get("content-length") || "", etag: r.headers.get("etag") || "" } : { ok: false };
  } catch (e) { return { ok: false }; }
}
async function cdnFallbackItem(cid) {
  for (const t of DOUJIN_ASSET_TYPES) {
    const base = "https://doujin-assets.dmm.co.jp/digital/" + t + "/" + cid + "/" + cid;
    const pl = await headInfo_(base + "pl.jpg");
    if (!pl.ok) continue;
    // ★CDNは存在しない画像でも404ではなく「200＋NOW PRINTINGプレースホルダ」を返す。
    //   確実に存在しない番号(jp-999)の指紋(ETag/サイズ)を基準に、一致する画像を除外する。
    const ref = await headInfo_(base + "jp-999.jpg");
    const isPh = (h) => ref.ok && h.ok && ((ref.etag && h.etag) ? ref.etag === h.etag : (ref.len !== "" && h.len === ref.len));
    if (isPh(pl)) continue; // 表紙自体がプレースホルダ＝このtypeに画像なし
    const pt = await headInfo_(base + "pt.jpg");
    const listUrl = (pt.ok && !isPh(pt)) ? base + "pt.jpg" : base + "pl.jpg";
    const samples = [];
    for (let n = 1; n <= 8; n++) {
      const u = base + "jp-" + String(n).padStart(3, "0") + ".jpg";
      const h = await headInfo_(u);
      if (!h.ok || isPh(h)) break; // 実在しない番号＝プレースホルダを検知したら打ち切り
      samples.push(u);
    }
    return {
      content_id: cid,
      title:   "",          // タイトルは取得不可（API未収録＋ページはログイン壁）
      partial: true,        // 画像のみの部分情報
      date: "",
      service_name: "同人",
      floor_name:   "同人",
      imageURL: { list: listUrl, large: base + "pl.jpg" },
      sampleImageURL: samples.length ? { sample_l: { image: samples } } : null,
      iteminfo: { author: [], genre: [] },
      prices: { list_price: null, price: null },
      review: { count: null, average: null },
    };
  }
  return null;
}

// ── CORS ヘルパ ──────────────────────────────────────────────────────────────

function corsHeaders(origin, allowed) {
  if (!allowed) return null;
  if (allowed !== "*" && origin !== allowed) return null;
  return {
    "Access-Control-Allow-Origin":  allowed === "*" ? "*" : origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Shared-Secret",
    "Access-Control-Max-Age":       "86400",
  };
}

function preflight(origin, allowed) {
  const h = corsHeaders(origin, allowed);
  if (!h) return new Response(null, { status: 403 });
  return new Response(null, { status: 204, headers: h });
}

function json(obj, status, cors) {
  const headers = { "Content-Type": "application/json" };
  if (cors) Object.assign(headers, cors);
  return new Response(JSON.stringify(obj), { status, headers });
}

function text(str, status) {
  return new Response(str, { status, headers: { "Content-Type": "text/plain" } });
}
