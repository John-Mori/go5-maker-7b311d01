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
const SALES_UNAVAILABLE_RETRY_MS = 7 * 86400000;
function infoCidSupported_(cid) { return !/^tw_/i.test(String(cid || "")); }
function salesCidSupported_(cid) { return /^d_[0-9A-Za-z]+$/i.test(String(cid || "")); }

export default {
  async fetch(request, env, ctx) {
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
            // ★scrapedAt が空/不正だと Date.parse は NaN → 従来は (NaN||0)=0 で「約56年前」と誤判定し、
            //   価格を毎回 null 化していた（scrapedAt 未設定の override で価格が恒久的に消える真因）。
            //   「30日以上前」と確定できる時だけ価格を無効化。年齢不明は価格を保ったまま再取得だけ依頼する。
            const scrapedMs = Date.parse(ov.scrapedAt || "");
            if (!isFinite(scrapedMs)) {
              await stQueueInfoPut(env, cid, ""); // 年齢不明=再取得依頼（既存なら書かない=dedup内蔵）
            } else if (Date.now() - scrapedMs > 30 * 86400000) {
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

      // ③′ FANZAブックスのサムネ補完：ebook作品の書影は cid から決定的
      //    （…/digital/e-book/<cid>/<cid>pl.jpg @ ebook-assets.dmm.co.jp）。API未収録＋画像なしの
      //    古い override（上のIMG_OK取りこぼしで画像が剥がれて保存された分）で「タイトルは在るのに
      //    サムネだけ空」になる作品を、決定的URLをHEADで実在確認してから埋める（再スクレイプ不要で即時）。
      if (item && item.title && (!item.imageURL || !item.imageURL.list) && /^b\d/i.test(cid)) {
        const cov = "https://ebook-assets.dmm.co.jp/digital/e-book/" + cid + "/" + cid + "pl.jpg";
        try {
          const h = await headInfo_(cov);
          if (h.ok && (h.len === "" || parseInt(h.len, 10) > 3000)) item.imageURL = { list: cov, large: cov };
        } catch (e) {}
      }

      // ③″ FANZAブックスのジャンル/発売日補完：API/override がタイトルだけで genre/date を
      //    持たない（旧overrideや同人以外でAPI未収録）時、実ページ(srcUrl)を1回スクレイプして
      //    空欄だけ埋める。scrapeFanzaItem を流用（同一抽出）。scrape 由来（line 84）で既に
      //    埋まっている場合は noGenre/noDate が false になり二重フェッチしない。
      if (item && item.title && /book\.dmm\./.test(srcUrl)) {
        const noGenre = !(item.iteminfo && Array.isArray(item.iteminfo.genre) && item.iteminfo.genre.length);
        const noDate = !item.date;
        if (noGenre || noDate) {
          try {
            const pg = await scrapeFanzaItem(cid, srcUrl);
            if (pg) {
              if (noDate && pg.date) item.date = pg.date;
              if (noGenre && pg.iteminfo && Array.isArray(pg.iteminfo.genre) && pg.iteminfo.genre.length) {
                item.iteminfo = item.iteminfo || {};
                item.iteminfo.genre = pg.iteminfo.genre;
              }
            }
          } catch (e) {}
        }
      }

      // ③⁗ FANZAブックスの元値(list_price)補完：DMM公式APIはebook(Books)の prices を
      //    「price 一つだけ・list_price/deliveries 無し」で返す（実測2026-08-18 b915awnmg04393→{price:"1430"}）。
      //    つまりAPI経由のBooksは"元値330円"が構造的に取れない（Chami報告2026-08-18）。しかも商品ページは
      //    海外IP(=このWorker=Cloudflare)だとログイン壁で価格が読めない（実測2026-08-18・PCスクレイプが在る理由）。
      //    ＝元値は「PC(日本IP)がSSRから拾って override(ov:) に入れた list_price」だけが真値。
      //    そこで①API結果に list_price が欠け ②override が list_price を持っていれば その元値を採用し、
      //    ③override にも無ければ PC取得依頼キューへ積む（PCがSSRから元値を埋める）。Books系cidのみ・追加のみ。
      if (item && item.title && (/^(?:b\d|\d+$)/.test(cid) || /book\.dmm\./.test(srcUrl))) {
        const hasList = !!(item.prices && item.prices.list_price != null && item.prices.list_price !== "");
        if (!hasList) {
          try {
            const ov = await stGetOverride(env, cid);
            const ovList = ov && ov.prices && ov.prices.list_price;
            if (ovList != null && ovList !== "") {
              item.prices = item.prices || {};
              item.prices.list_price = ovList; // PCがSSRから拾った元値
              const ovPrice = ov.prices.price;
              if (ovPrice != null && ovPrice !== "") item.prices.price = ovPrice; // 割引後もoverride側を正とする
            } else if (infoCidSupported_(cid)) {
              await stQueueInfoPut(env, cid, srcUrl); // 元値をPCに埋めさせる（dedup内蔵）
            }
          } catch (e) {}
        }
      }

      // ③‴ 同人のAI生成判定(verified-ai)：APIで解決した同人(d_)はAIがiteminfo.genreに載らない(実測)ため、
      //    クライアントが checkAi を立てた時だけ作品ページを1回見てAIフラグを付ける。routine の
      //    情報取得には乗せない=DMMへの余計なスクレイプを増やさない(候補1件につきクライアント側で一度きり)。
      //    ★三値判定=「AI開示文ヒット=確定true(aiChecked)」「og:titleあり+壁マーカー無し=本物のページを読めた=確定false(aiChecked)」
      //      「壁(age_check/ログイン)で読めない=未判定(aiChecked付けない)」。壁で読めなかったHTMLから ai:false を配ると、
      //      フロントが「未確認」を「非AI」と誤認して既存のAIチェックを外し恒久凍結する(REQ-3babd19ddb の真因)。
      if (item && item.title && body.checkAi === true && /^d_/i.test(cid) && !item.aiChecked) {
        if (item.ai) {
          item.aiChecked = true; // 既にAI確定(scrape/override由来)なら全文判定済み=検証済み扱い
        } else {
          try {
            const aiRes = await fetchDmmPage(DMM_DOUJIN_BASE + encodeURIComponent(cid) + "/");
            if (aiRes && aiRes.ok) {
              const aiHtml = await aiRes.text();
              const hasOg = aiHtml.includes("og:title");
              const walled = !hasOg && (aiHtml.includes("age_check") || /ログイン/.test(aiHtml)); // scrapeFanzaItem L877 と同一基準+ログイン
              if (aiFromHtml_(aiHtml)) { item.ai = true; item.aiChecked = true; }       // AI開示文=確定true
              else if (hasOg && !walled) item.aiChecked = true;                          // 本物のページを読めた=確定false
              // それ以外(壁)は aiChecked を付けない=未判定のまま(下でoverride引き当て/PC取得依頼へ)
            }
          } catch (e) { /* best-effort: 判定できなくても本体情報は返す */ }
        }
      }
      // 未判定(壁で読めなかった)なら、PCバッチが日本IPで検証済みの override を引き当てる。無ければ取得依頼キューへ
      //   積んでPC(日本IP)に検証させる(dedup=read-before-write は stQueueInfoPut 内蔵)。
      if (item && item.title && body.checkAi === true && /^d_/i.test(cid) && !item.aiChecked) {
        try {
          const ov = await stGetOverride(env, cid);
          if (ov && ov.aiChecked) { item.ai = !!ov.ai; item.aiChecked = true; }
          else await stQueueInfoPut(env, cid, srcUrl);
        } catch (e) {}
      }

      // フル情報が取れなかった作品は「PC取得依頼キュー」へ記録（PCのバッチが拾ってスクレイプ→ov:へ保存）。
      //   book等のsrcUrlがあれば一緒に保存し、PC側がそのURL（同人以外）を正しくスクレイプできるようにする。
      // フル情報が取れなかった作品は取得依頼キューへ（dedup+Books用URL enrich はstQueueInfoPut内蔵）。
      //   ★KV1日書き込み上限の主因だった無条件req:書き込みは、ストレージ層のdedupで解消済み。
      if ((!item || item.partial) && infoCidSupported_(cid)) {
        try { await stQueueInfoPut(env, cid, srcUrl); } catch (e) {}
      }

      if (!item) return json({ ok: false, error: "not_found", cid }, 404, cors);
      return json({ ok: true, item }, 200, cors);
    }

    // ── 全候補プール：📚全候補タブの作品cid集合を保存/参照 ──────────────────
    //   POST /api/candidate-pool { cids:[...] } = プールを総入れ替え(除外タブ反映済みの集合をフロントが送る)。
    //     cids 要素は "cid"(旧) でも {cid,source}(source='main'|'circle'|'list') でも可。source は出所タブの区別用。
    //   GET  /api/candidate-pool               = { ok, count, cids } (部門・検証用)。
    //   部門は go5_fanza を candidate_pool でJOINして「全候補タブに出ている作品だけ」を読む。
    if (path === "/api/candidate-pool") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const corsC = corsHeaders(origin, allowed);
      if (!corsC) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (!env.FANZA_DB) return json({ ok: false, error: "db_unbound" }, 500, corsC);

      // (一時診断 ?selftest=N は 2026-08-06 に撤去=INC-126 の書き込み修正が実 candidate_pool へ着地
      //   COUNT 1→243 を確認したため。真因の実測経緯は §210 付近の本番コメントに残す。)
      if (request.method === "GET") {
        // ?log=1 = 最後に着いたPOSTの観測ログを返す(着信の有無・secret照合・件数・永続化結果)。
        //   ブラウザから直接読めるようにGETへ相乗り(部門/実機どちらでも1回で「どこで死んだか」が出る)。
        if (url.searchParams.get("log") === "1") {
          try {
            const raw = env.FANZA_KV ? await env.FANZA_KV.get("candpost:last") : null;
            return json({ ok: true, log: raw ? JSON.parse(raw) : null }, 200, corsC);
          } catch (e) { return json({ ok: false, error: String((e && e.message) || e) }, 500, corsC); }
        }
        try {
          const rs = await env.FANZA_DB.prepare("SELECT cid FROM candidate_pool ORDER BY cid").all();
          const list = (rs.results || []).map((r) => r.cid);
          return json({ ok: true, count: list.length, cids: list }, 200, corsC);
        } catch (e) { return json({ ok: false, error: String((e && e.message) || e) }, 500, corsC); }
      }
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, corsC);
      // ★着信ログ(観測点・十王星南の要請2026-08-05)：POSTがWorkerへ着いた瞬間にKV candpost:last へ1行残す。
      //   これで「そもそも着いていない(=クライアント/URLの問題)」のか「着いたが書けていない/別物を返す」のかが
      //   実機リロード1回で確定する(部門はKVを直読できる)。secret照合前に着信を刻む=bad_secret も観測対象。
      const logCandPost_ = async (rec) => {
        if (!env.FANZA_KV) return;
        try { await env.FANZA_KV.put("candpost:last", JSON.stringify(Object.assign({ at: nowIso_(), atMs: Date.now() }, rec))); } catch (e) {}
      };
      const secretC = request.headers.get("X-Shared-Secret") || "";
      const secretOkC = !!(env.SHARED_SECRET && secretC === env.SHARED_SECRET);
      await logCandPost_({ stage: "arrived", hasSecret: !!secretC, secretOk: secretOkC, ua: (request.headers.get("User-Agent") || "").slice(0, 80) });
      if (!secretOkC) { await logCandPost_({ stage: "reject_bad_secret", hasSecret: !!secretC }); return json({ ok: false, error: "bad_secret" }, 401, corsC); }
      let bodyC;
      try { bodyC = await request.json(); }
      catch (e) { await logCandPost_({ stage: "reject_bad_json" }); return json({ ok: false, error: "bad_json" }, 400, corsC); }
      // cidを厳格検証＋重複除去。安全上限5000(巨大サークル群でも収まる)。
      //   ★2026-08-09: 出所タグ source を受ける。cids 要素は文字列(旧・source無)でも
      //     {cid,source} でも可(後方互換)。source は 'main'|'circle'|'list' のみ許可、他はnull。
      //     初出勝ち=同一cidが複数タブに在ってもフロントが main を先に送る(手動追加の帰属を保つ)。
      const seenC = {}, poolRows = [];
      for (const raw of (Array.isArray(bodyC.cids) ? bodyC.cids : [])) {
        const isObj = raw && typeof raw === "object";
        const cid = String((isObj ? raw.cid : raw) || "").trim();
        let src = isObj ? String(raw.source || "").trim() : "";
        if (src !== "main" && src !== "circle" && src !== "list") src = null;
        if (!/^[0-9A-Za-z_-]{1,64}$/.test(cid) || seenC[cid]) continue;
        seenC[cid] = true; poolRows.push({ cid, source: src });
        if (poolRows.length >= 5000) break;
      }
      // ★空/不正ボディで candidate_pool を全消去しない安全弁（誤爆でプールを飛ばさない=INC-126系の再発防止）。
      //   cids が配列でない（POST {} 等）＝明確な不正 → DBに触れず 400。
      //   有効cidが1件も無い配列 → 総入れ替えは必ず現行候補を積んで送られるので、空替えは誤爆の可能性が高い。
      //   ここで DELETE を走らせずに no-op で返す（プールは前回の内容を保持）。
      if (!Array.isArray(bodyC.cids)) {
        await logCandPost_({ stage: "reject_no_cids" });
        return json({ ok: false, error: "cids_required" }, 400, corsC);
      }
      if (poolRows.length === 0) {
        await logCandPost_({ stage: "skip_empty_no_wipe" });
        return json({ ok: true, count: 0, skipped: "empty_no_wipe" }, 200, corsC);
      }
      const nowC = Date.now();
      try {
        // 手動追加/独立タブだけを入れ替え、Workerが管理するcircle行は保持。重複cidは端末側sourceを優先する。
        // ★D1のbind変数上限は【1文あたり100】(実測2026-08-05・十王星南 selftest=50→OK/60→"too many SQL variables"）。
        //   旧コードは400件/文=800変数で上限突破し、候補が50件を超えると毎回バッチ全体がSQLITE_ERRORで
        //   ロールバック→candidate_poolが最後の小さな成功書き込み(d_754842・1件)に凍結していた(=Chamiの候補241件が
        //   一度もD1へ入らなかった真因。クライアントv647/648/656はすべて別レイヤを直しており無効)。
        //   ★source列追加で1行3変数(cid,updated_at,source)=CHUNK 30で90変数(上限100に安全マージン)。
        const CHUNK = 30;
        const stmts = [env.FANZA_DB.prepare("DELETE FROM candidate_pool WHERE source IS NULL OR source<>'circle'")];
        for (let i = 0; i < poolRows.length; i += CHUNK) {
          const chunk = poolRows.slice(i, i + CHUNK);
          const ph = chunk.map(() => "(?, ?, ?)").join(", ");
          const binds = [];
          chunk.forEach((r) => { binds.push(r.cid, nowC, r.source); });
          stmts.push(env.FANZA_DB.prepare("INSERT INTO candidate_pool (cid, updated_at, source) VALUES " + ph + " ON CONFLICT(cid) DO UPDATE SET updated_at=excluded.updated_at,source=excluded.source").bind(...binds));
        }
        await env.FANZA_DB.batch(stmts);
        await logCandPost_({ stage: "persist_ok", count: poolRows.length });
        return json({ ok: true, count: poolRows.length }, 200, corsC);
      } catch (e) {
        await logCandPost_({ stage: "persist_err", err: String((e && e.message) || e), cidsLen: poolRows.length });
        return json({ ok: false, error: String((e && e.message) || e) }, 500, corsC);
      }
    }

    // ── 投稿履歴ミラー：作品cid×チャンネル別のYouTube最終投稿日を保存(product-scout daily_pick 用)──
    //   POST /posted { cid, channel, posted_at, yt_url } = 投稿完了(client stock.js archiveStock_)が1件POST。
    //     UPSERT(PK=cid,channel)。posted_at が現行より新しい時だけ更新=古い履歴で上書きしない。
    //   認証=公開ソフト鍵(X-Shared-Secret)+Origin(他フロント向けAPIと同型)。書き込み先=D1 go5_fanza(FANZA_DB)。
    //   部門は SELECT posted_at FROM posted_log WHERE cid=? AND channel=? で「両CHの最終投稿日」を読む。
    if (path === "/posted") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const corsP = corsHeaders(origin, allowed);
      if (!corsP) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, corsP);
      const secP = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || secP !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, corsP);
      if (!env.FANZA_DB) return json({ ok: false, error: "db_unbound" }, 500, corsP);
      let pbody;
      try { pbody = await request.json(); } catch (e) { return json({ ok: false, error: "bad_json" }, 400, corsP); }
      const pcid = String((pbody && pbody.cid) || "").trim();
      const pch = String((pbody && pbody.channel) || "").trim();
      if (!/^[0-9A-Za-z_-]{1,64}$/.test(pcid)) return json({ ok: false, error: "missing_cid" }, 400, corsP);
      if (pch !== "acc1" && pch !== "acc2") return json({ ok: false, error: "bad_channel" }, 400, corsP);
      // posted_at は ISO8601 想定。空/不正は現在時刻で埋めず 400=投稿日が正データなので取り違えを黙認しない。
      const pat = String((pbody && pbody.posted_at) || "").trim();
      if (!pat || !Number.isFinite(Date.parse(pat))) return json({ ok: false, error: "bad_posted_at" }, 400, corsP);
      let pyt = String((pbody && pbody.yt_url) || "").trim().slice(0, 300);
      if (pyt && !/^https?:\/\//.test(pyt)) pyt = "";
      try {
        await env.FANZA_DB.prepare(
          "INSERT INTO posted_log(cid,channel,posted_at,yt_url,updated_at) VALUES(?,?,?,?,?) " +
          "ON CONFLICT(cid,channel) DO UPDATE SET posted_at=excluded.posted_at, yt_url=excluded.yt_url, updated_at=excluded.updated_at " +
          "WHERE excluded.posted_at > posted_log.posted_at"
        ).bind(pcid, pch, pat, pyt || null, nowIso_()).run();
        // 投稿を権威としてサークルを解決し、一度投稿したサークルは全候補の巡回対象へ恒久登録する。
        if (ctx && ctx.waitUntil) ctx.waitUntil(registerPostedMaker_(env, pcid, pat, true));
        return json({ ok: true, cid: pcid, channel: pch }, 200, corsP);
      } catch (e) {
        return json({ ok: false, error: String((e && e.message) || e) }, 500, corsP);
      }
    }

    // ── 投稿履歴の直近読み出し：候補ページの「投稿済み非表示」ゲートを生成側(daily_pick.py)と同一のD1権威で駆動 ──
    //   GET /posted/recent?limit=40 → posted_at 降順の直近 limit 件 {cid,channel,posted_at}。既定40=「直近3日 OR 直近10件」の
    //   両方を賄える件数(実測≈5本/日)。候補ページのts再構築(ローカル履歴由来・欠落でゲートが素通り)を排し、
    //   生成側 posted_recent(3d)/posted_recent_by_count(10) と同じ判定を客户端でも同一データで効かせる(Chami 2026-08-24)。
    //   認証=公開ソフト鍵(X-Shared-Secret)+Origin(/posted と同型)。読み取り専用。
    if (path === "/posted/recent") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const corsR = corsHeaders(origin, allowed);
      if (!corsR) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "GET") return json({ ok: false, error: "method_not_allowed" }, 405, corsR);
      const secR = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || secR !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, corsR);
      if (!env.FANZA_DB) return json({ ok: false, error: "db_unbound" }, 500, corsR);
      let limR = parseInt(url.searchParams.get("limit") || "40", 10);
      if (!Number.isFinite(limR) || limR < 1) limR = 40;
      if (limR > 200) limR = 200;
      try {
        const rsR = await env.FANZA_DB.prepare(
          "SELECT cid, channel, posted_at FROM posted_log ORDER BY posted_at DESC LIMIT ?"
        ).bind(limR).all();
        return json({ ok: true, items: (rsR && rsR.results) || [] }, 200, corsR);
      } catch (e) {
        return json({ ok: false, error: String((e && e.message) || e) }, 500, corsR);
      }
    }

    // ── 全候補カタログ：表示中の1ページだけ返し、全件収集はWorker側で継続する ──
    //   GET  /api/candidate-catalog?sort=rank7d&page=1&limit=20&q=...
    //   POST /api/candidate-catalog { makerIds:[...], items:[...] }
    //     makerIdsは巡回キューへ、itemsは手動追加/独立タブの表示情報をカタログへ反映する。
    if (path === "/api/candidate-catalog") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const corsCat = corsHeaders(origin, allowed);
      if (!corsCat) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      const secCat = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || secCat !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, corsCat);
      if (!env.FANZA_DB) return json({ ok: false, error: "db_unbound" }, 500, corsCat);
      if (request.method === "GET") {
        try { return json(await queryCandidateCatalog_(env, url.searchParams), 200, corsCat); }
        catch (e) { return json({ ok: false, error: "catalog_query_failed" }, 500, corsCat); }
      }
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, corsCat);
      let catBody;
      try { catBody = await request.json(); } catch (e) { return json({ ok: false, error: "bad_json" }, 400, corsCat); }
      const makerIdsCat = Array.isArray(catBody.makerIds) ? catBody.makerIds.slice(0, 200) : [];
      for (const rawMid of makerIdsCat) {
        const mid = String(rawMid || "").trim();
        if (/^\d{1,10}$/.test(mid)) await seedCatalogMaker_(env, mid, "");
      }
      const imported = await importCandidateCatalog_(env, Array.isArray(catBody.items) ? catBody.items : []);
      if (ctx && ctx.waitUntil && makerIdsCat.length) ctx.waitUntil((async () => { await backfillPostedMakers_(env, 3); await runCandidateCatalog_(env, 17); })());
      const progress = await candidateCatalogProgress_(env);
      return json({ ok: true, imported, progress }, 200, corsCat);
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
      const infoQAll = await stQueueList(env, "info"); // 取得依頼中のcid（+book等のスクレイプ先url）
      const staleInfoQ = infoQAll.filter((q) => !infoCidSupported_(q.cid));
      await Promise.all(staleInfoQ.map((q) => stQueueDelete(env, q.cid, "info")));
      const infoQ = infoQAll.filter((q) => infoCidSupported_(q.cid));
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
          // 内容が同一でも「取得成功」は確定しているため、古い取得依頼は必ず消す。
          const { saved: didSave } = await stPutOverride(env, it);
          await stQueueDelete(env, it.content_id, "info");
          if (didSave) saved++; else skipped++;
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
      let requested = Array.isArray(sbody.cids) ? sbody.cids : (sbody.cid ? [sbody.cid] : []);
      requested = requested.map((c) => String(c || "").trim()).filter((c) => /^[0-9A-Za-z_]{1,64}$/.test(c)).slice(0, 30);
      if (!requested.length) return json({ ok: false, error: "missing_cid" }, 400, cors3);
      const unsupported = requested.filter((cid) => !salesCidSupported_(cid));
      const cids = requested.filter(salesCidSupported_);
      const { sales, missing, unavailable } = await stGetSalesMany(env, cids);
      // 本当にPC取得できる同人cidだけをキューへ。Books/SNSはunsupportedとして完了させる。
      await Promise.all(missing.map(async (cid) => { try { await stQueueSalesPut(env, cid); } catch (e) {} }));
      return json({ ok: true, sales, missing, unavailable, unsupported }, 200, cors3);
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
        const unavailable = !!(raw && raw.status === "unavailable");
        const n = raw && raw.n != null ? parseInt(raw.n, 10) : NaN;
        if (!salesCidSupported_(cid) || (!unavailable && isNaN(n))) continue;
        if (quotaHit) { skipped++; continue; } // 上限到達後は残りを静かにスキップ（1件のクラッシュで全件失敗にしない）
        try {
          const { saved: didSave } = unavailable ? await stPutSalesUnavailable(env, cid) : await stPutSales(env, cid, n);
          // 数値が同じ/取得不可が再確認済みでも成功なので、古い依頼を必ず完了させる。
          await stQueueDelete(env, cid, "sales");
          if (didSave) saved++; else skipped++;
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
      await seedCatalogMaker_(env, mkId, mkName);
      // 登録直後から裏で先頭ページを取得。応答は待たせず、失敗時も保存済みカーソルからcronが再開する。
      if (ctx && ctx.waitUntil) ctx.waitUntil(runCandidateCatalog_(env, 6));
      return json({ ok: true, tracked: mkId }, 200, cors4);
    }

    // ── 販売数の取得依頼キュー＋追跡サークル一覧（PCバッチが読む）。認証は管理鍵。──
    if (path === "/api/fanza-sales-queue") {
      if (request.method !== "GET") return json({ ok: false, error: "method_not_allowed" }, 405, null);
      if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
      if (!env.FANZA_KV && !env.FANZA_DB) return json({ ok: false, error: "store_unbound" }, 500, null);
      const trackedMakers = await stListMakers(env);
      const salesQAll = await stQueueList(env, "sales");
      const staleSalesQ = salesQAll.filter((q) => !salesCidSupported_(q.cid));
      await Promise.all(staleSalesQ.map((q) => stQueueDelete(env, q.cid, "sales")));
      const salesQ = salesQAll.filter((q) => salesCidSupported_(q.cid));
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

    // ── 市場全体巡回(Market Crawl)の手動起動：cronと同じ処理をその場で1回実行。──
    //   認証は管理鍵(ADMIN_SECRET・配布しない)。無認証で本番を叩かせない(既存管理EPと同型)。
    //   通常は毎朝cronが自動実行するため、これは検証/取りこぼし補完用。
    if (path === "/api/market-crawl") {
      if (request.method !== "GET" && request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, null);
      if (!adminOk(request, env)) return json({ ok: false, error: "bad_secret" }, 401, null);
      if (!env.FANZA_DB) return json({ ok: false, error: "d1_unbound" }, 500, null);
      if (!env.FANZA_API_ID || !env.FANZA_AFFILIATE_ID) return json({ ok: false, error: "api_not_configured" }, 500, null);
      // ?sample=1：巡回/保存/投入は行わず、rankフロアから生item1件だけ取得して構造を返す(T5期限フィールド調査・§2.3)。
      //   ★秘密対策：URL/affiliateURL/imageURL/sampleImageURL は affiliate_id を含むため返さない。許可フィールドのみ。
      if (url.searchParams.get("sample") === "1") {
        try {
          const raw = await fetchMarketSampleRaw(env);
          if (!raw) return json({ ok: false, error: "no_sample" }, 502, null);
          return json({
            ok: true,
            keys: Object.keys(raw),
            prices: raw.prices || null,
            campaign: raw.campaign || null,
            review: raw.review || null,
            date: raw.date || null,
            iteminfo_keys: raw.iteminfo ? Object.keys(raw.iteminfo) : null,
          }, 200, null);
        } catch (e) {
          return json({ ok: false, error: String(e && e.message || e) }, 500, null);
        }
      }
      try {
        const stats = await runMarketCrawl(env);
        return json({ ok: true, ...stats }, 200, null);
      } catch (e) {
        return json({ ok: false, error: String(e && e.message || e) }, 500, null);
      }
    }

    if (path === "/" || path === "") {
      const mode = (env.FANZA_API_ID) ? "api+scrape" : "scrape-only";
      return text("go5-fanza-proxy ok (mode=" + mode + ")", 200);
    }

    return json({ ok: false, error: "not_found" }, 404, null);
  },

  // ── cron: 市場全体巡回(毎朝06:00 JST=UTC 21:00)。──
  //   同人フロアのランキング上位+新着を D1 market_snapshot へ保存し、90日より前を掃除する。
  //   既存works表/KV/候補タブ/実売取得には一切触れない(追加のみ・回帰ゼロ)。失敗は次回cronで回復。
  async scheduled(event, env, ctx) {
    try {
      if (!env.FANZA_API_ID || !env.FANZA_AFFILIATE_ID || !env.FANZA_DB) return;
      await runMarketCrawl(env);
      await backfillPostedMakers_(env, 5);
      await seedTrackedCatalogMakers_(env);
      await runCandidateCatalog_(env, 35);
    } catch (e) {
      // cronは投げ返しても再試行が乱れるだけ。翌朝の再実行で収束させる(秘密はログに出さない)。
      console.error("scheduled_refresh_failed", String(e && e.message || e));
    }
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

// ── 全候補のサーバー側カタログ ──────────────────────────────────────────────
// 同人はコミック/CG系だけ、Books(ebook)は全件。ゲーム・音声・ボイスコミック・動画は取得段階で除外する。
const CATALOG_SOURCES = [
  { service: "doujin", floor: "digital_doujin", article: "maker" },
  { service: "doujin", floor: "digital_doujin_bl", article: "maker" },
  { service: "doujin", floor: "digital_doujin_tl", article: "maker" },
  { service: "ebook", floor: "comic", article: "author" },
  { service: "ebook", floor: "novel", article: "author" },
  { service: "ebook", floor: "photo", article: "author" },
  { service: "ebook", floor: "bl", article: "author" },
  { service: "ebook", floor: "tl", article: "author" },
];
const CATALOG_REFRESH_MS = 24 * 3600000;
function catalogType_(it, src) {
  if (src.service === "ebook") return { eligible: true, type: "Books" };
  const info = it.iteminfo || {};
  const names = [];
  [info.genre, info.type, info.category].forEach((arr) => {
    (Array.isArray(arr) ? arr : []).forEach((x) => names.push(String((x && (x.name || x.value)) || x || "")));
  });
  names.push(String(it.category_name || ""), String(it.floor_name || ""));
  const text = names.join(" ");
  if (/(ゲーム|game|ボイス|音声|ボイコミ|ボイスコミック|動画|アニメ動画)/i.test(text)) return { eligible: false, type: "excluded" };
  if (/(コミック|漫画|comic|ＣＧ|CG|イラスト|image)/i.test(text)) {
    const ai = /(AI|ＡＩ|人工知能)/i.test(text);
    const cg = /(ＣＧ|CG|イラスト|image)/i.test(text);
    return { eligible: true, type: ai ? (cg ? "AI CG" : "AIコミック") : (cg ? "CG" : "コミック") };
  }
  return { eligible: false, type: "other" };
}
function mapCatalogItem_(it, makerId, src, rank) {
  const base = mapMakerItem(it);
  const type = catalogType_(it, src);
  return Object.assign(base, {
    makerId: String(makerId || ""), service: src.service, floor: src.floor,
    workType: type.type, eligible: type.eligible, rank: rank || null,
  });
}
async function seedCatalogMaker_(env, makerId, name) {
  if (!env.FANZA_DB || !/^\d{1,10}$/.test(String(makerId || ""))) return;
  const now = Date.now();
  await env.FANZA_DB.prepare(
    "INSERT INTO candidate_catalog_makers(maker_id,name,status,updated_at) VALUES(?,?,'pending',?) " +
    "ON CONFLICT(maker_id) DO UPDATE SET name=CASE WHEN excluded.name<>'' THEN excluded.name ELSE candidate_catalog_makers.name END, " +
    "status=CASE WHEN candidate_catalog_makers.completed_at IS NULL OR candidate_catalog_makers.completed_at<? THEN 'pending' ELSE candidate_catalog_makers.status END, updated_at=excluded.updated_at"
  ).bind(String(makerId), String(name || "").slice(0, 100), now, now - CATALOG_REFRESH_MS).run();
}
async function seedTrackedCatalogMakers_(env) {
  const seen = new Set();
  for (const m of await stListMakers(env)) {
    seen.add(String(m.makerId)); await seedCatalogMaker_(env, m.makerId, m.name || "");
  }
  const rs = await env.FANZA_DB.prepare("SELECT maker_id,name FROM posted_makers").all().catch(() => null);
  for (const m of (rs && rs.results || [])) if (!seen.has(String(m.maker_id))) await seedCatalogMaker_(env, m.maker_id, m.name || "");
}
async function registerPostedMaker_(env, cid, postedAt, startRun) {
  if (!env.FANZA_DB || !env.FANZA_API_ID || !env.FANZA_AFFILIATE_ID) return;
  const item = await fetchViaApi(cid, env.FANZA_API_ID, env.FANZA_AFFILIATE_ID);
  const author = item && item.iteminfo && Array.isArray(item.iteminfo.author) ? item.iteminfo.author[0] : null;
  const makerId = String(author && author.id || "");
  await env.FANZA_DB.prepare("INSERT INTO posted_maker_resolutions(cid,maker_id,checked_at) VALUES(?,?,?) ON CONFLICT(cid) DO UPDATE SET maker_id=excluded.maker_id,checked_at=excluded.checked_at")
    .bind(cid, /^\d{1,10}$/.test(makerId) ? makerId : null, Date.now()).run();
  if (!/^\d{1,10}$/.test(makerId)) return;
  const name = String(author && author.name || "").slice(0, 100);
  await env.FANZA_DB.prepare(
    "INSERT INTO posted_makers(maker_id,name,first_posted_at,updated_at) VALUES(?,?,?,?) " +
    "ON CONFLICT(maker_id) DO UPDATE SET name=CASE WHEN excluded.name<>'' THEN excluded.name ELSE posted_makers.name END,updated_at=excluded.updated_at"
  ).bind(makerId, name, postedAt, Date.now()).run();
  await seedCatalogMaker_(env, makerId, name);
  if (startRun) await runCandidateCatalog_(env, 6);
}
async function backfillPostedMakers_(env, limit) {
  const rs = await env.FANZA_DB.prepare("SELECT p.cid,MIN(p.posted_at) AS posted_at FROM posted_log p LEFT JOIN posted_maker_resolutions r ON r.cid=p.cid WHERE r.cid IS NULL GROUP BY p.cid ORDER BY posted_at LIMIT ?")
    .bind(limit).all().catch(() => null);
  for (const row of (rs && rs.results || [])) await registerPostedMaker_(env, row.cid, row.posted_at, false);
}
async function candidateCatalogProgress_(env) {
  const row = await env.FANZA_DB.prepare(
    "SELECT COUNT(*) AS makers, SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END) AS complete, " +
    "SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending, SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running FROM candidate_catalog_makers"
  ).first().catch(() => null);
  const works = await env.FANZA_DB.prepare("SELECT COUNT(*) AS n FROM candidate_catalog c JOIN candidate_pool p ON p.cid=c.cid WHERE c.eligible=1").first().catch(() => null);
  return { makers: Number(row && row.makers || 0), complete: Number(row && row.complete || 0), pending: Number(row && row.pending || 0), running: Number(row && row.running || 0), works: Number(works && works.n || 0) };
}
async function saveCatalogRows_(env, rows, source) {
  if (!rows.length) return 0;
  const now = Date.now();
  const stmts = [];
  for (const it of rows) {
    const discovered = now;
    stmts.push(env.FANZA_DB.prepare(
      "INSERT INTO candidate_catalog(cid,maker_id,maker_name,title,url,released,list_price,price,discount_pct,review_count,review_avg,thumb,genres_json,service,floor,work_type,eligible,source,discovered_at,refreshed_at) " +
      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cid) DO UPDATE SET " +
      "maker_id=COALESCE(excluded.maker_id,candidate_catalog.maker_id), maker_name=COALESCE(NULLIF(excluded.maker_name,''),candidate_catalog.maker_name), " +
      "title=excluded.title, url=excluded.url, released=excluded.released, list_price=excluded.list_price, price=excluded.price, discount_pct=excluded.discount_pct, " +
      "review_count=excluded.review_count, review_avg=excluded.review_avg, thumb=COALESCE(NULLIF(excluded.thumb,''),candidate_catalog.thumb), genres_json=excluded.genres_json, " +
      "service=excluded.service, floor=excluded.floor, work_type=excluded.work_type, eligible=MAX(candidate_catalog.eligible,excluded.eligible), " +
      "source=CASE WHEN candidate_catalog.source='main' OR excluded.source='main' THEN 'main' WHEN candidate_catalog.source='list' OR excluded.source='list' THEN 'list' ELSE 'circle' END, refreshed_at=excluded.refreshed_at"
    ).bind(
      it.cid, it.makerId || null, it.makerName || null, it.title || "", it.url || "", it.date || "",
      it.listPrice, it.price, it.discountPct || 0, it.reviewCount, it.reviewAvg, it.thumb || "",
      JSON.stringify(it.genres || []), it.service || "", it.floor || "", it.workType || "", it.eligible ? 1 : 0,
      source || "circle", discovered, now
    ));
    if (it.eligible) {
      const src = source === "main" ? "main" : (source === "list" ? "list" : "circle");
      stmts.push(env.FANZA_DB.prepare(
        "INSERT INTO candidate_pool(cid,updated_at,source) VALUES(?,?,?) ON CONFLICT(cid) DO UPDATE SET updated_at=excluded.updated_at, " +
        "source=CASE WHEN candidate_pool.source='main' OR excluded.source='main' THEN 'main' WHEN candidate_pool.source='list' OR excluded.source='list' THEN 'list' ELSE 'circle' END"
      ).bind(it.cid, now, src));
    }
  }
  for (let i = 0; i < stmts.length; i += 80) await env.FANZA_DB.batch(stmts.slice(i, i + 80));
  return rows.filter((x) => x.eligible).length;
}
async function importCandidateCatalog_(env, rawItems) {
  const rows = [];
  for (const raw of rawItems.slice(0, 500)) {
    const cid = String(raw && raw.cid || "").trim();
    if (!/^[0-9A-Za-z_-]{1,64}$/.test(cid)) continue;
    const url = String(raw.url || "").slice(0, 500);
    const isBook = /book\.dmm\.(com|co\.jp)/i.test(url) || String(raw.kind || "") === "Books";
    rows.push({
      cid, makerId: null, makerName: String(raw.author || raw.makerName || "").slice(0, 100),
      title: String(raw.title || "").slice(0, 300), url, date: String(raw.date || raw.releaseDate || "").slice(0, 32),
      listPrice: raw.listPrice != null && Number.isFinite(Number(raw.listPrice)) ? Number(raw.listPrice) : null,
      price: raw.price != null && Number.isFinite(Number(raw.price)) ? Number(raw.price) : null,
      discountPct: Number(raw.discountPct) || 0, reviewCount: raw.reviewCount == null ? null : Number(raw.reviewCount),
      reviewAvg: raw.reviewAvg == null ? null : Number(raw.reviewAvg), thumb: String(raw.thumb || "").slice(0, 500),
      genres: Array.isArray(raw.genres) ? raw.genres.slice(0, 32).map(String) : [], service: isBook ? "ebook" : "doujin",
      floor: isBook ? "books" : "manual", workType: isBook ? "Books" : "manual", eligible: true,
      source: raw.source === "main" ? "main" : "list",
    });
  }
  const groups = { main: [], list: [] };
  rows.forEach((x) => groups[x.source].push(x));
  return (await saveCatalogRows_(env, groups.main, "main")) + (await saveCatalogRows_(env, groups.list, "list"));
}
async function runCandidateCatalog_(env, pageBudget) {
  if (!env.FANZA_DB || !env.FANZA_API_ID || !env.FANZA_AFFILIATE_ID) return { pages: 0 };
  await seedTrackedCatalogMakers_(env);
  let pages = 0, saved = 0;
  while (pages < pageBudget) {
    let job = await env.FANZA_DB.prepare(
      "SELECT maker_id,name,source_index,next_offset,status,completed_at FROM candidate_catalog_makers " +
      "WHERE status<>'complete' OR completed_at<? ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, updated_at LIMIT 1"
    ).bind(Date.now() - CATALOG_REFRESH_MS).first();
    if (!job) break;
    let sourceIndex = Number(job.source_index || 0), offset = Number(job.next_offset || 1);
    if (job.status === "complete") { sourceIndex = 0; offset = 1; }
    if (sourceIndex >= CATALOG_SOURCES.length) sourceIndex = 0;
    const src = CATALOG_SOURCES[sourceIndex];
    const scanStarted = (sourceIndex === 0 && offset === 1) ? Date.now() : null;
    await env.FANZA_DB.prepare(
      "UPDATE candidate_catalog_makers SET status='running',scan_started_at=COALESCE(?,scan_started_at),updated_at=?,last_error=NULL WHERE maker_id=?"
    ).bind(scanStarted, Date.now(), job.maker_id).run();
    const params = new URLSearchParams({
      api_id: env.FANZA_API_ID, affiliate_id: env.FANZA_AFFILIATE_ID, site: "FANZA",
      service: src.service, floor: src.floor, article: src.article, article_id: job.maker_id,
      hits: "100", offset: String(offset), sort: "date", output: "json",
    });
    const data = await fetchDmmJson(DMM_API_BASE + "?" + params.toString(), 2);
    if (!data || !data.result) {
      await env.FANZA_DB.prepare("UPDATE candidate_catalog_makers SET status='pending',last_error='api_error',updated_at=? WHERE maker_id=?")
        .bind(Date.now(), job.maker_id).run();
      break;
    }
    const pageItems = Array.isArray(data.result.items) ? data.result.items : [];
    const total = parseInt(data.result.total_count, 10) || 0;
    const rows = pageItems.map((it, i) => mapCatalogItem_(it, job.maker_id, src, offset + i));
    saved += await saveCatalogRows_(env, rows, "circle");
    pages++;
    const floorDone = pageItems.length < 100 || offset + 100 > total;
    if (floorDone) { sourceIndex++; offset = 1; } else offset += 100;
    if (sourceIndex >= CATALOG_SOURCES.length) {
      await env.FANZA_DB.prepare(
        "UPDATE candidate_catalog_makers SET source_index=0,next_offset=1,status='complete',completed_at=?,updated_at=?,last_error=NULL WHERE maker_id=?"
      ).bind(Date.now(), Date.now(), job.maker_id).run();
    } else {
      await env.FANZA_DB.prepare(
        "UPDATE candidate_catalog_makers SET source_index=?,next_offset=?,status='pending',updated_at=?,last_error=NULL WHERE maker_id=?"
      ).bind(sourceIndex, offset, Date.now(), job.maker_id).run();
    }
  }
  return { pages, saved };
}
async function queryCandidateCatalog_(env, sp) {
  const limitRaw = parseInt(sp.get("limit") || "20", 10);
  const limit = [20, 30, 50, 100].includes(limitRaw) ? limitRaw : 20;
  let page = parseInt(sp.get("page") || "1", 10); if (!Number.isFinite(page) || page < 1) page = 1;
  const q = String(sp.get("q") || "").trim().slice(0, 100);
  const saleOnly = sp.get("sale") === "1";
  const priceMax = Math.max(0, parseInt(sp.get("priceMax") || "0", 10) || 0);
  const sort = String(sp.get("sort") || "rank7d");
  const order = {
    added_desc: "c.discovered_at DESC", price_asc: "CASE WHEN c.price IS NULL THEN 1 ELSE 0 END,c.price ASC,c.released DESC",
    date_desc: "c.released DESC", date_asc: "c.released ASC", discount_desc: "c.discount_pct DESC,c.released DESC",
    rank: "COALESCE(w.sales_n,-1) DESC,COALESCE(c.review_count,-1) DESC,COALESCE(c.review_avg,-1) DESC",
    rank7d: "COALESCE(w.sales_n,-1) DESC,COALESCE(c.review_count,-1) DESC,c.refreshed_at DESC",
  }[sort] || "c.discovered_at DESC";
  const where = ["c.eligible=1"];
  const binds = [];
  if (q) { where.push("(c.title LIKE ? OR c.maker_name LIKE ? OR c.cid LIKE ?)"); const like = "%" + q + "%"; binds.push(like, like, like); }
  if (saleOnly) where.push("c.discount_pct>0 AND c.price<c.list_price");
  if (priceMax) { where.push("(COALESCE(c.price,c.list_price) IS NULL OR COALESCE(c.price,c.list_price)<=?)"); binds.push(priceMax); }
  const from = " FROM candidate_catalog c JOIN candidate_pool p ON p.cid=c.cid LEFT JOIN works w ON w.cid=c.cid WHERE " + where.join(" AND ");
  const countRow = await env.FANZA_DB.prepare("SELECT COUNT(*) AS n" + from).bind(...binds).first();
  const total = Number(countRow && countRow.n || 0), pages = Math.max(1, Math.ceil(total / limit));
  if (page > pages) page = pages;
  const rs = await env.FANZA_DB.prepare(
    "SELECT c.*,p.source AS pool_source,w.sales_n" + from + " ORDER BY " + order + ",c.cid LIMIT ? OFFSET ?"
  ).bind(...binds, limit, (page - 1) * limit).all();
  const items = ((rs && rs.results) || []).map((r) => ({
    cid: r.cid, title: r.title || "", url: r.url || "", date: r.released || "", listPrice: r.list_price,
    price: r.price, discountPct: r.discount_pct || 0, reviewCount: r.review_count, reviewAvg: r.review_avg,
    thumb: r.thumb || "", makerName: r.maker_name || "", author: r.maker_name || "",
    genres: safeJsonParse_(r.genres_json || "[]") || [], service: r.service || "", floor: r.floor || "",
    kind: r.service === "ebook" ? "Books" : "同人", workType: r.work_type || "", source: r.pool_source || r.source,
    salesN: r.sales_n,
  }));
  return { ok: true, total, page, pages, limit, items, progress: await candidateCatalogProgress_(env) };
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

// ── 市場全体巡回(Market Crawl)─────────────────────────────────────────────────
//   fetchAllMakerItems の様式を流用し、サークル指定(article=maker/article_id)を外して
//   同人フロア(digital_doujin)を sort 指定で引く=市場全体の巡回。fetchDmmJson + mapMakerItem
//   をそのまま再利用(レビュー件数/平均・割引率・ジャンル・メーカー名・サムネまで整形済)。
//   対象は通常フロアのみ(BL/TLは別客層のため初期対象外=設計書§2.1 裁定1(A))。
//   ※campaign/セール期限フィールドがAPIレスポンスに入るかは【未確認・要実測】(実測は親=T5/§2.3)。
//     入るなら market_snapshot へ列追加、入らなければ現行「期限は出品ページで要確認」を維持する。
//   ※実売数(sales_n)はAPIに無い→予選通過cidのみ既存の sales キュー経路(stQueueSalesPut)で翌日補完
//     するのは【次段】。本PRは市場snapshot保存までに留める(全件の実売スクレイプはしない=設計書§2.4)。
const MARKET_FLOOR = { site: "FANZA", service: "doujin", floor: "digital_doujin" };

// 採算予選の閾値(selection-rules.md「定期スキャン」節 / morning_scan.py と同期・暫定値=較正対象)。
//   discountPct>=40 かつ reviewCount>=30 かつ reviewAvg>=4.4 を reviewCount 降順で上位 TOP_N 件。
//   これに通ったcidだけ sales 取得キューへ投入=全件の実売スクレイプはしない(設計書§2.4)。
const MARKET_PICK_MIN_DISCOUNT = 40;
const MARKET_PICK_MIN_REVIEW_COUNT = 30;
const MARKET_PICK_MIN_REVIEW_AVG = 4.4;
const MARKET_PICK_TOP_N = 3;

// JST(UTC+9)の暦日 YYYY-MM-DD。cron は UTC 21:00=JST 06:00 に発火するため当日=JST基準で決める。
function todayJst_() { return new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10); }
function jstDayMinus_(days) { return new Date(Date.now() + 9 * 3600000 - days * 86400000).toISOString().slice(0, 10); }

// 同人フロアを sort 指定で最大 limit 件(hits上限=100・1ページ)取得し mapMakerItem で整形して返す。
async function fetchMarketItems(env, sort, limit) {
  const params = new URLSearchParams({
    api_id: env.FANZA_API_ID, affiliate_id: env.FANZA_AFFILIATE_ID,
    site: MARKET_FLOOR.site, service: MARKET_FLOOR.service, floor: MARKET_FLOOR.floor,
    hits: String(Math.min(limit, 100)), offset: "1", sort: sort, output: "json",
  });
  const data = await fetchDmmJson(DMM_API_BASE + "?" + params.toString(), 2);
  if (!data || !data.result) return [];
  const pageItems = Array.isArray(data.result.items) ? data.result.items : [];
  return pageItems.map(mapMakerItem);
}

// 当日の市場行を組み立てる：①sort=rank 上位100(rank=順位) ②sort=date 新着100(発売7日以内のみ採用)。
//   rank枠とdate枠で重複したcidは rank枠の順位を優先(date枠のみで拾った作品は rank=null)。
async function gatherMarketRows(env) {
  const rankItems = await fetchMarketItems(env, "rank", 100);
  const dateItems = await fetchMarketItems(env, "date", 100);
  const cutoff = Date.now() - 7 * 86400000; // 新着枠は発売7日以内のみ
  const byCid = new Map();
  rankItems.forEach((it, i) => { if (it.cid && !byCid.has(it.cid)) byCid.set(it.cid, { it, rank: i + 1 }); });
  for (const it of dateItems) {
    if (!it.cid || byCid.has(it.cid)) continue; // rank枠にあればその順位を尊重
    const rel = Date.parse(it.date || "");
    if (!Number.isFinite(rel) || rel < cutoff) continue; // 発売7日より前は捨てる
    byCid.set(it.cid, { it, rank: null });
  }
  return Array.from(byCid.values());
}

// 当日の market_snapshot を UPSERT 保存し、末尾で90日より前(91日以上前)を掃除する(PK=day,cid)。
//   市場snapshotはD1専用の追加テーブル=既存works表/KV/USE_D1切替弁の挙動には一切触れない。
async function saveMarketSnapshot(env, day, rows) {
  if (!env.FANZA_DB) throw new Error("d1_unbound");
  const num  = (v) => (v != null && v !== "" && Number.isFinite(Number(v))) ? Math.round(Number(v)) : null;
  const real = (v) => (v != null && v !== "" && Number.isFinite(Number(v))) ? Number(v) : null;
  const stmts = [];
  for (const { it, rank } of rows) {
    stmts.push(env.FANZA_DB.prepare(
      "INSERT INTO market_snapshot(day,cid,rank,title,price,list_price,discount_pct,review_count,review_avg,genres,maker_name,thumb,released) " +
      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) " +
      "ON CONFLICT(day,cid) DO UPDATE SET rank=COALESCE(excluded.rank, market_snapshot.rank), title=excluded.title, price=excluded.price, list_price=excluded.list_price, discount_pct=excluded.discount_pct, review_count=excluded.review_count, review_avg=excluded.review_avg, genres=excluded.genres, maker_name=excluded.maker_name, thumb=excluded.thumb, released=excluded.released"
    ).bind(
      day, it.cid, (rank != null ? rank : null),
      it.title || "", num(it.price), num(it.listPrice), (num(it.discountPct) || 0),
      num(it.reviewCount), real(it.reviewAvg),
      JSON.stringify(Array.isArray(it.genres) ? it.genres : []),
      it.makerName || "", it.thumb || "", it.date || ""
    ));
  }
  // 90日より前(91日以上前)の行を掃除(容量対策・設計書§2.1)。同一batchの末尾で実行。
  stmts.push(env.FANZA_DB.prepare("DELETE FROM market_snapshot WHERE day < ?").bind(jstDayMinus_(90)));
  if (stmts.length) await env.FANZA_DB.batch(stmts);
  return { rows: rows.length };
}

// 当日rowsから採算予選(selection-rules.md/morning_scan.pyと同期)を通ったcidを reviewCount 降順で上位 TOP_N 件返す。
//   実売数(sales_n)はAPIに無いため、通過分だけ既存の sales キュー経路で翌サイクルに補完させる。
function marketSalesPicks_(rows) {
  const q = [];
  for (const { it } of rows) {
    if (!it || !it.cid) continue;
    const d = Number(it.discountPct), c = Number(it.reviewCount), a = Number(it.reviewAvg);
    if (!Number.isFinite(d) || !Number.isFinite(c) || !Number.isFinite(a)) continue;
    if (d >= MARKET_PICK_MIN_DISCOUNT && c >= MARKET_PICK_MIN_REVIEW_COUNT && a >= MARKET_PICK_MIN_REVIEW_AVG) q.push(it);
  }
  q.sort((x, y) => (Number(y.reviewCount) || 0) - (Number(x.reviewCount) || 0));
  return q.slice(0, MARKET_PICK_TOP_N).map((it) => it.cid);
}

// 市場巡回の実行本体(cron と手動エンドポイント /api/market-crawl の共通処理)。
async function runMarketCrawl(env) {
  const day = todayJst_();
  const rows = await gatherMarketRows(env);
  const rankN = rows.filter((r) => r.rank != null).length;
  await saveMarketSnapshot(env, day, rows);
  // 採算予選の上位を sales 取得キューへ投入(PC側sales_fetchが翌サイクルで sales_n を埋める)。
  //   stQueueSalesPut は24hデデュープ内蔵=同日再実行でも重複投入しない。best-effort=巡回本体を壊さない。
  const picks = marketSalesPicks_(rows);
  let enqueued = 0;
  for (const cid of picks) {
    try { await stQueueSalesPut(env, cid); enqueued++; } catch (e) { /* best-effort(投入失敗は次回cronで回復) */ }
  }
  return { day, saved: rows.length, rank: rankN, date: rows.length - rankN, enqueued };
}

// ?sample=1 用：rankフロアから生item(mapMakerItem前)を1件だけ取得して返す(T5期限フィールド調査・§2.3)。
//   保存も投入もしない・純粋な参照。生itemの構造キーを親がcurlで1回確認するため。
async function fetchMarketSampleRaw(env) {
  const params = new URLSearchParams({
    api_id: env.FANZA_API_ID, affiliate_id: env.FANZA_AFFILIATE_ID,
    site: MARKET_FLOOR.site, service: MARKET_FLOOR.service, floor: MARKET_FLOOR.floor,
    hits: "1", offset: "1", sort: "rank", output: "json",
  });
  const data = await fetchDmmJson(DMM_API_BASE + "?" + params.toString(), 2);
  if (!data || !data.result) return null;
  const items = Array.isArray(data.result.items) ? data.result.items : [];
  return items[0] || null;
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
// AI生成作品の判定：FANZA同人はAIをジャンルタグに載せず、作品説明の必須開示文でのみ示す
//   (実測 d_748630=ジャンルは巨乳/制服/中出し等でAI無し・説明に「＊本作品はAI生成で作成しています」)。
//   カテゴリchrome(コミック・AI / CG・AI / ボイス・一部AI)は全ページ共通で紛れるが、素の「AI生成」
//   「生成AI」は非AI作品4件の実測でpage全体0件＝作品固有の信号として使える(誤検知しない)。
function aiFromHtml_(html) { return /AI生成|生成AI/.test(String(html || "")); }
async function scrapeFanzaItem(cid, srcUrl) {
  // srcUrl（FANZA Books等の実ページURL・呼び出し元で許可ドメイン検証済み）があればそちらを優先。
  const isBook = /book\.dmm\./.test(srcUrl); // FANZAブックス判定（同人ページとは価格の出方が異なる＝下記価格ブロックで分岐）
  // ★新フロント book.dmm.co.jp は Next.js の"空の器"を返す（値段・JSON-LDが1つもHTMLに載らず、
  //   全部あとからJSで描く＝実測2026-08-18）。旧フロント book.dmm.com は同じ商品パスをサーバー側で
  //   組み立てる（JSON-LD offers.price=定価＋◯%OFFバッジが載る）ので、Booksは com を読みにいく。
  //   これが「Booksで元値330円が取れない」の根本原因（co.jpを読んでも価格文字がゼロだった）。
  const ssrUrl = srcUrl ? srcUrl.replace("://book.dmm.co.jp/", "://book.dmm.com/") : "";
  const pageUrl = ssrUrl || (DMM_DOUJIN_BASE + encodeURIComponent(cid) + "/");
  let res;
  try { res = await fetchDmmPage(pageUrl); } catch (e) { res = null; }
  // com が404等で読めなかった時だけ、元のURL（co.jp）へフォールバック（回帰ゼロ＝従来動作以上）。
  if ((!res || !res.ok) && ssrUrl && ssrUrl !== srcUrl) {
    try { res = await fetchDmmPage(srcUrl); } catch (e) { res = null; }
  }
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

  // 発売日（JSON-LD releaseDate/dateCreated/datePublished／FANZAブックスの商品詳細
  //   data-testid="volume-description-content-publish-date"／「発売日・配信開始日」表記の順で拾う）。
  //   ★book商品ページは配信開始日と発売日ラベルの間にタグが挟まり従来の {0,12} では届かなかった
  //     ため data-testid アンカー経由も見る。取れなければ空。
  var dateStr = "";
  var rdM = html.match(/["'](?:releaseDate|dateCreated|datePublished)["']\s*:\s*["'](\d{4}-\d{2}-\d{2})/)
    || html.match(/publish-date["'][^>]{0,20}>\s*(\d{4})[\/\-年](\d{1,2})[\/\-月](\d{1,2})/)
    || html.match(/(?:発売日|配信開始日)[^0-9]{0,12}(\d{4})[\/\-年](\d{1,2})[\/\-月](\d{1,2})/);
  if (rdM) {
    dateStr = rdM.length >= 4 && rdM[2] ? (rdM[1] + "-" + ("0" + rdM[2]).slice(-2) + "-" + ("0" + rdM[3]).slice(-2)) : rdM[1];
  }

  // ジャンル（FANZAブックス：商品詳細の data-testid="volume-detail-info-genre" のアンカー、旧構造 volume-description-genre も許容、
  //   無ければJSON-LDの genre 配列）。同人ページはこのアンカーが無いので従来どおり空になる。
  //   ★実ページ検証(2026-07-29)=現行testidは volume-detail-info-genre。旧名だけだと0件でJSONフォールバック頼みだった。
  var genreArr = [];
  var gRe = /data-testid=["']volume-(?:detail-info|description)-genre["'][^>]*>\s*([^<]+?)\s*</g;
  var gm;
  while ((gm = gRe.exec(html)) !== null) {
    var gn = gm[1].replace(/&amp;/g, "&").trim();
    if (gn && genreArr.length < 32) genreArr.push({ name: gn });
  }
  if (!genreArr.length) {
    var gjM = html.match(/["']genre["']\s*:\s*\[([^\]]*)\]/);
    if (gjM) {
      gjM[1].split(",").forEach(function (s) {
        var t = s.replace(/^\s*["']|["']\s*$/g, "").trim();
        if (t && genreArr.length < 32) genreArr.push({ name: t });
      });
    }
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
    ai:         aiFromHtml_(html),   // ページ由来のAI生成判定(ジャンルタグに載らない同人AI作品を拾う)
    aiChecked:  true,                // 作品ページ全文を実読して判定した=検証済み(壁ならこの関数はnullを返す=ここに来ない)
    title:      title,
    date:       dateStr,
    service_name: isBook ? "FANZAブックス" : "同人",
    floor_name:   isBook ? "ブックス"     : "同人",
    imageURL:       ogImg ? { list: ogImg, large: ogImg } : null,
    sampleImageURL: null,
    iteminfo:   { author: authorArr, genre: genreArr },
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
async function stGetSalesMany(env, cids) { // {sales:{cid:n}, missing:[cid], unavailable:[cid]}
  const sales = {}, missing = [], unavailable = [], now = Date.now();
  const classify = (cid, n, at, status) => {
    if (n != null) { sales[cid] = n; return; }
    const age = now - (Date.parse(at || "") || 0);
    if ((status === "unavailable" || at) && age >= 0 && age < SALES_UNAVAILABLE_RETRY_MS) unavailable.push(cid);
    else missing.push(cid); // 7日後に再確認し、後から販売数が出た作品も回復させる
  };
  if (d1on_(env)) {
    const ph = cids.map(() => "?").join(",");
    const rs = cids.length ? await env.FANZA_DB.prepare("SELECT cid, sales_n, sales_at FROM works WHERE cid IN (" + ph + ")").bind(...cids).all().catch(() => null) : null;
    const found = new Set();
    if (rs && rs.results) rs.results.forEach((r) => { found.add(r.cid); classify(r.cid, r.sales_n, r.sales_at, ""); });
    cids.forEach((c) => { if (!found.has(c)) missing.push(c); });
    return { sales, missing, unavailable };
  }
  await Promise.all(cids.map(async (c) => {
    const v = await env.FANZA_KV.get("sales:" + c, "json").catch(() => null);
    if (v) classify(c, v.n, v.at, v.status); else missing.push(c);
  }));
  return { sales, missing, unavailable };
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
async function stPutSalesUnavailable(env, cid) { // 販売数欄の無い有効ページ。既存の実数は消さない。
  let saved = false;
  const at = nowIso_();
  if (d1write_(env)) {
    const r = await env.FANZA_DB.prepare("SELECT sales_n, sales_at FROM works WHERE cid=?").bind(cid).first().catch(() => null);
    if (!r || r.sales_n == null) {
      const prevAt = r && Date.parse(r.sales_at || "");
      if (!prevAt || Date.now() - prevAt >= SALES_UNAVAILABLE_RETRY_MS) {
        if (await d1run_(env, env.FANZA_DB.prepare("INSERT INTO works(cid,sales_n,sales_at,updated_at) VALUES(?,NULL,?,datetime('now')) ON CONFLICT(cid) DO UPDATE SET sales_at=excluded.sales_at, updated_at=datetime('now') WHERE works.sales_n IS NULL")
          .bind(cid, at))) saved = true;
      }
    }
  }
  if (kvwrite_(env)) {
    try {
      const prev = await env.FANZA_KV.get("sales:" + cid, "json").catch(() => null);
      if (!(prev && prev.n != null)) {
        const prevAt = prev && Date.parse(prev.at || "");
        if (!prevAt || Date.now() - prevAt >= SALES_UNAVAILABLE_RETRY_MS) {
          await env.FANZA_KV.put("sales:" + cid, JSON.stringify({ n: null, status: "unavailable", at })); saved = true;
        }
      }
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
  if (d1write_(env)) {
    await env.FANZA_DB.prepare("DELETE FROM tracked_makers WHERE maker_id=?").bind(mid).run().catch(() => {});
    // 投稿済みサークルは明示タブを削除しても全候補の母集団から外さない。
    const posted = await env.FANZA_DB.prepare("SELECT maker_id FROM posted_makers WHERE maker_id=?").bind(mid).first().catch(() => null);
    if (!posted) {
      const rows = await env.FANZA_DB.prepare("SELECT cid FROM candidate_catalog WHERE maker_id=?").bind(mid).all().catch(() => null);
      const cids = (rows && rows.results || []).map((r) => r.cid);
      await env.FANZA_DB.prepare("DELETE FROM candidate_catalog_makers WHERE maker_id=?").bind(mid).run().catch(() => {});
      await env.FANZA_DB.prepare("DELETE FROM candidate_catalog WHERE maker_id=?").bind(mid).run().catch(() => {});
      for (const cid of cids) await env.FANZA_DB.prepare("DELETE FROM candidate_pool WHERE cid=? AND source='circle'").bind(cid).run().catch(() => {});
    }
  }
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
// ★ebook-assets は実体が .co.jp（FANZAブックスの og:image/JSON-LD image のホスト）。.com だけだと
//   PC側スクレイプが渡す書影URL(…dmm.co.jp/…)が sanitizeOverride で剥がれ、override が「タイトルのみ・
//   画像なし」で保存される＝ブックスのサムネが永久に出ない主因だった（2026-07-29 実測）。両方許可。
const IMG_OK = /^https:\/\/(doujin-assets\.dmm\.co\.jp|pics\.dmm\.co\.jp|ebook-assets\.dmm\.(com|co\.jp))\//;
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
    // verified-ai: PCバッチ(日本IP)が作品ページ全文から立てたAI判定。ホワイトリスト再構築で落とさず通す
    //   (これが無いと ai/aiChecked がsanitizeで消え、検証済みフラグが override に永久保存されない)。
    ai: !!raw.ai,
    aiChecked: !!raw.aiChecked,
    date: String(raw.date || "").slice(0, 32),
    service_name: String(raw.service_name || "同人").slice(0, 32),
    floor_name: String(raw.floor_name || "同人").slice(0, 32),
    imageURL: (imageURL && (imageURL.list || imageURL.large)) ? imageURL : null,
    sampleImageURL: sImgs.length ? { sample_l: { image: sImgs } } : null,
    iteminfo: { author: names(raw.iteminfo && raw.iteminfo.author, 3), genre: names(raw.iteminfo && raw.iteminfo.genre, 32) },
    prices: { list_price: numStr(raw.prices && raw.prices.list_price), price: numStr(raw.prices && raw.prices.price) },
    review: {
      count: (raw.review && raw.review.count != null && raw.review.count !== "" && Number.isInteger(Number(raw.review.count)) && Number(raw.review.count) >= 0) ? Number(raw.review.count) : null,
      average: (raw.review && raw.review.average != null && raw.review.average !== "" && Number.isFinite(Number(raw.review.average)) && Number(raw.review.average) >= 0 && Number(raw.review.average) <= 5) ? Number(raw.review.average) : null,
    },
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
    "Vary":                         "Origin", // ★具体Origin反射時に前段キャッシュが別Origin向けACAOを再利用しない（link/drive worker と実装統一）
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

// 回帰テスト専用。Workerルートの公開APIには露出しない。
export { catalogType_ as __testCatalogType };
