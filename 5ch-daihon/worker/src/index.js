/**
 * 5ch事業「台本(cut_list)編集システム」止血版 Worker
 *
 * ★スコープ(止血版だけ・増やさない)
 *   Chamiがブラウザから cut_list(YAML)の各コマの caption_text / narration_text / reaction_text を
 *   編集・保存できる。それ以外(AI生成/VOICEVOX試聴/字幕トグル新設/並べ替え/画像差し替え)はやらない。
 *
 * ★最優先の受け入れ条件＝保存してもYAML冒頭の長大なコメント(露出注記・裁定履歴)を壊さないこと。
 *   これを満たすため、素朴な yaml.parse→yaml.stringify の往復は使わない(コメントが消える)。
 *   eemeli/yaml の Document API(parseDocument→doc.setIn→doc.toString())でコメントをround-trip保全する。
 *
 * ★保存先＝R2バケット(binding名 DAIHON・bucket_name go5-5ch-daihon)。r2.dev の公開URLは有効化しない前提
 *   (README参照)。R2への読み書きは常にこのWorker経由＝R2直URL・list公開は作らない。
 *
 * ★認証＝Cloudflare Access(Zero Trust)にedgeで委ねるのが基本防御。このWorkerでは追加の多層防御として、
 *   Accessが付与する Cf-Access-Jwt-Assertion ヘッダの「存在チェック」だけ行う(無ければ403)。
 *   ★JWTの完全検証(署名/aud/exp)は止血版では未実装＝本実装送り。edgeのAccess遮断が主防御(README参照)。
 *
 * 秘密は無し(認証はCloudflare Access側)。CORSは許可Originのみ(ワイルドカード不可・drive-worker踏襲)。
 */

import { parseDocument } from "yaml";

const EDITABLE_FIELDS = new Set(["caption_text", "narration_text", "reaction_text"]);
const PROJECTS_PREFIX = "projects/";

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "";

    // ---- CORS(許可Originのみ・ワイルドカード不可)----
    if (request.method === "OPTIONS") return preflight(origin, allowed);
    const cors = corsHeaders(origin, allowed);
    if (!cors) return json({ ok: false, error: "origin_not_allowed" }, 403, null);

    // ---- 多層防御: Cloudflare Access の付与ヘッダが無ければ拒否(主防御はedgeのAccess遮断・README参照) ----
    if (!request.headers.get("Cf-Access-Jwt-Assertion")) {
      return json({ ok: false, error: "access_required" }, 403, cors);
    }

    const url = new URL(request.url);
    try {
      if (request.method === "GET" && url.pathname === "/api/projects") {
        return await handleListProjects(env, cors);
      }
      if (request.method === "GET" && url.pathname === "/api/cutlist") {
        return await handleGetCutlist(url, env, cors);
      }
      if (request.method === "POST" && url.pathname === "/api/cutlist") {
        return await handleSaveField(request, url, env, cors);
      }
    } catch (e) {
      return json({ ok: false, error: "exception:" + (e && e.message ? e.message : String(e)) }, 500, cors);
    }
    return json({ ok: false, error: "not_found" }, 404, cors);
  },
};

/* ====================== GET /api/projects ====================== */
// R2の projects/ プレフィックスを列挙し、cut_listキー一覧を返す(read-only)。
async function handleListProjects(env, cors) {
  if (!env.DAIHON) return json({ ok: false, error: "r2_not_bound" }, 500, cors);
  const keys = [];
  let cursor;
  do {
    const listed = await env.DAIHON.list({ prefix: PROJECTS_PREFIX, cursor });
    for (const obj of listed.objects || []) {
      if (/\.ya?ml$/i.test(obj.key)) keys.push(obj.key);
    }
    cursor = listed.truncated ? listed.cursor : undefined;
  } while (cursor);
  return json({ ok: true, projects: keys }, 200, cors);
}

/* ====================== GET /api/cutlist?key=... ====================== */
// R2からYAMLを読み、cutsの表示用サマリをJSONで返す(read-only)。生YAMLも同梱(参考用・編集の正はサーバ側)。
async function handleGetCutlist(url, env, cors) {
  if (!env.DAIHON) return json({ ok: false, error: "r2_not_bound" }, 500, cors);
  const key = String(url.searchParams.get("key") || "");
  if (!isValidKey(key)) return json({ ok: false, error: "bad_key" }, 400, cors);

  const obj = await env.DAIHON.get(key);
  if (!obj) return json({ ok: false, error: "not_found" }, 404, cors);
  const text = await obj.text();

  let doc;
  try { doc = parseDocument(text); }
  catch (e) { return json({ ok: false, error: "yaml_parse_failed" }, 500, cors); }

  const cutsNode = doc.get("cuts", true);
  const cuts = [];
  if (cutsNode && typeof cutsNode.items !== "undefined") {
    for (const item of cutsNode.items) {
      cuts.push({
        cut_id: scalarOf(item, "cut_id"),
        image_file: scalarOf(item, "image_file"),
        phase: scalarOf(item, "phase"),
        cut_type: scalarOf(item, "cut_type"),
        caption_text: scalarOf(item, "caption_text"),
        narration_text: scalarOf(item, "narration_text"),
        reaction_text: scalarOf(item, "reaction_text"),
      });
    }
  }
  return json({ ok: true, key, cuts, raw: text }, 200, cors);
}

/* ====================== POST /api/cutlist?key=... ====================== */
// body= {cut_id, field, value}。fieldは caption_text|narration_text|reaction_text のみ許可。
// R2の現YAMLをparseDocument→該当cutの該当スカラーだけsetIn→doc.toString()(コメント保全)→R2へput。
async function handleSaveField(request, url, env, cors) {
  if (!env.DAIHON) return json({ ok: false, error: "r2_not_bound" }, 500, cors);
  const key = String(url.searchParams.get("key") || "");
  if (!isValidKey(key)) return json({ ok: false, error: "bad_key" }, 400, cors);

  let body;
  try { body = await request.json(); }
  catch (e) { return json({ ok: false, error: "bad_body" }, 400, cors); }

  const cutId = String((body && body.cut_id) || "");
  const field = String((body && body.field) || "");
  const value = (body && typeof body.value === "string") ? body.value : "";
  if (!cutId) return json({ ok: false, error: "missing_cut_id" }, 400, cors);
  if (!EDITABLE_FIELDS.has(field)) return json({ ok: false, error: "field_not_allowed" }, 400, cors);

  const obj = await env.DAIHON.get(key);
  if (!obj) return json({ ok: false, error: "not_found" }, 404, cors);
  const text = await obj.text();

  let doc;
  try { doc = parseDocument(text); }
  catch (e) { return json({ ok: false, error: "yaml_parse_failed" }, 500, cors); }

  const cutsNode = doc.get("cuts", true);
  if (!cutsNode || typeof cutsNode.items === "undefined") {
    return json({ ok: false, error: "no_cuts_in_document" }, 500, cors);
  }
  const idx = cutsNode.items.findIndex((item) => scalarOf(item, "cut_id") === cutId);
  if (idx < 0) return json({ ok: false, error: "cut_id_not_found" }, 404, cors);

  // ★コメント保全の核心: doc.setIn(パス, 値) で該当スカラーだけを書き換える。
  //   Document API のノードはコメント(comment/commentBefore)を保持したまま toString() で戻る。
  doc.setIn(["cuts", idx, field], value);

  const nextText = doc.toString();
  await env.DAIHON.put(key, nextText, { httpMetadata: { contentType: "text/yaml; charset=utf-8" } });

  return json({ ok: true, key, cut_id: cutId, field }, 200, cors);
}

/* ====================== ユーティリティ ====================== */
// YAMLマップノードから文字列スカラーを1つ取り出す(無ければ空文字)。
function scalarOf(mapNode, key) {
  if (!mapNode || typeof mapNode.get !== "function") return "";
  const v = mapNode.get(key);
  return v === null || typeof v === "undefined" ? "" : String(v);
}

// R2キーの形式検証(パストラバーサル・想定外プレフィックスを弾く)。
function isValidKey(key) {
  if (!key) return false;
  if (key.indexOf("..") >= 0) return false;
  if (!key.startsWith(PROJECTS_PREFIX)) return false;
  return /^[A-Za-z0-9_\-./]+\.ya?ml$/i.test(key);
}

/* ====================== CORS / レスポンス(drive-worker踏襲・ワイルドカード不可) ====================== */
function corsHeaders(origin, allowed) {
  if (!allowed || origin !== allowed) return null;
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Cf-Access-Jwt-Assertion",
    "Vary": "Origin",
  };
}
function preflight(origin, allowed) {
  const h = corsHeaders(origin, allowed);
  if (!h) return new Response(null, { status: 403 });
  return new Response(null, { status: 204, headers: h });
}
function json(obj, status, cors) {
  const headers = Object.assign({ "Content-Type": "application/json; charset=utf-8" }, cors || {});
  return new Response(JSON.stringify(obj), { status, headers });
}
