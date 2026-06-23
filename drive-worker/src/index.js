/**
 * 5秒動画メーカー → Google Drive 自動保存 中継 Worker
 *
 * ★非破壊設計（最重要）★
 *   このWorkerが行うのは次の3種だけ：
 *     1) フォルダの新規作成（create）
 *     2) ファイルの新規アップロード（create / resumable）
 *     3) 参照（list / get）= 読み取りのみ
 *   既存物の削除・上書き・移動・改名・ゴミ箱送りに相当するAPIは一切実装しない。
 *   同名があっても既存には触れず _2, _3… の別名で新規作成する。
 *
 * 認証情報（client_id / client_secret / refresh_token / 共有シークレット）は
 * Cloudflare Worker Secrets にのみ保持し、レスポンス・ログには出力しない。
 */

const TOKEN_URL = "https://oauth2.googleapis.com/token";
const DRIVE_API = "https://www.googleapis.com/drive/v3/files";
const DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files";

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "";

    // ---- CORS（許可Originのみ。ワイルドカード不可）----
    if (request.method === "OPTIONS") return preflight(origin, allowed);
    const cors = corsHeaders(origin, allowed);
    if (!cors) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
    if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, cors);

    // ---- 共有シークレット（多層防御の1枚）----
    const secret = request.headers.get("X-Shared-Secret") || "";
    if (!env.SHARED_SECRET || secret !== env.SHARED_SECRET) {
      return json({ ok: false, error: "bad_secret" }, 401, cors);
    }

    // ---- 簡易レート制限（KV：日次カウンタ）----
    try {
      if (await rateLimited(env)) return json({ ok: false, error: "rate_limited" }, 429, cors);
    } catch (e) { /* KV未設定でも停止させない（他の防御で守る） */ }

    // ---- 入力 ----
    let form;
    try { form = await request.formData(); }
    catch (e) { return json({ ok: false, error: "bad_form" }, 400, cors); }

    const channel = String(form.get("channel") || "").trim();
    const title = String(form.get("title") || "").trim();
    const video = form.get("video");
    const image = form.get("image");

    // ---- チャンネル判定（曖昧なら保存しない＝取り違え事故より保存しないを優先）----
    const parentId = channelToFolderId(channel, env);
    if (!parentId) return json({ ok: false, error: "channel_unresolved", channel }, 400, cors);
    if (!title) return json({ ok: false, error: "missing_title" }, 400, cors);
    if (!(video && typeof video.arrayBuffer === "function")) {
      return json({ ok: false, error: "missing_video" }, 400, cors);
    }

    // ---- アクセストークン（refresh_token から都度取得。メモリのみ）----
    let token;
    try { token = await getAccessToken(env); }
    catch (e) { return json({ ok: false, error: "auth_failed" }, 502, cors); }

    // ---- 親（チャンネル）フォルダの存在確認（read-only）。無ければ保存しない ----
    const parent = await getFolder(parentId, token);
    if (!parent) return json({ ok: false, error: "parent_folder_not_found", parentId }, 400, cors);

    // ---- [動画名]フォルダを衝突回避で新規作成（既存には触れない）----
    const baseName = safeName(title);
    let folder;
    try { folder = await createUniqueChildFolder(parentId, baseName, token); }
    catch (e) { return json({ ok: false, error: "folder_create_failed" }, 502, cors); }

    // ---- アップロード（新規作成のみ。同名は連番で別名）----
    const uploaded = [];
    try {
      const vext = extOf(video.type) || extFromName(video.name) || "mp4";
      const vname = await uniqueFileName(folder.id, baseName + "." + vext, token);
      uploaded.push(await uploadNew(folder.id, vname, video, token));

      if (image && typeof image.arrayBuffer === "function") {
        const fallback = "image." + (extOf(image.type) || "jpg");
        const iname = await uniqueFileName(folder.id, safeName(image.name || fallback), token);
        uploaded.push(await uploadNew(folder.id, iname, image, token));
      }
    } catch (e) {
      return json({ ok: false, error: "upload_failed", folderId: folder.id }, 502, cors);
    }

    return json({
      ok: true,
      channel,
      parentName: parent.name,
      folderId: folder.id,
      folderName: folder.name,
      folderLink: folder.webViewLink || ("https://drive.google.com/drive/folders/" + folder.id),
      files: uploaded.map((f) => ({ id: f.id, name: f.name, link: f.webViewLink || "" })),
    }, 200, cors);
  },
};

/* ====================== チャンネル→フォルダID（ID直指定が主・名前は予備）====================== */
function channelToFolderId(channel, env) {
  const c = (channel || "").toLowerCase();
  if (c === "acc1") return env.FOLDER_ID_ACC1 || "";
  if (c === "acc2") return env.FOLDER_ID_ACC2 || "";
  // 予備：ラベル一致（IDが主、これは保険）
  if (env.LABEL_ACC1 && channel === env.LABEL_ACC1) return env.FOLDER_ID_ACC1 || "";
  if (env.LABEL_ACC2 && channel === env.LABEL_ACC2) return env.FOLDER_ID_ACC2 || "";
  return "";
}

/* ====================== OAuth（refresh_token → access_token）====================== */
async function getAccessToken(env) {
  const body = new URLSearchParams({
    client_id: env.GOOGLE_CLIENT_ID,
    client_secret: env.GOOGLE_CLIENT_SECRET,
    refresh_token: env.GOOGLE_REFRESH_TOKEN,
    grant_type: "refresh_token",
  });
  const r = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!r.ok) throw new Error("token");
  const j = await r.json();
  if (!j.access_token) throw new Error("token");
  return j.access_token;
}

/* ====================== 参照（read-only）====================== */
async function getFolder(id, token) {
  const url = DRIVE_API + "/" + encodeURIComponent(id) + "?fields=id,name,mimeType&supportsAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return null;
  const j = await r.json();
  return j && j.id ? j : null;
}

async function childFolderExists(parentId, name, token) {
  const q = "name='" + escQ(name) + "' and '" + parentId +
    "' in parents and mimeType='application/vnd.google-apps.folder'";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) + "&fields=files(id)&pageSize=1";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return false;
  const j = await r.json();
  return !!(j.files && j.files.length);
}

async function childFileExists(parentId, name, token) {
  const q = "name='" + escQ(name) + "' and '" + parentId + "' in parents";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) + "&fields=files(id)&pageSize=1";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return false;
  const j = await r.json();
  return !!(j.files && j.files.length);
}

/* ====================== 新規作成（create のみ）====================== */
async function createUniqueChildFolder(parentId, baseName, token) {
  let name = baseName, n = 1;
  while (await childFolderExists(parentId, name, token)) { n++; name = baseName + "_" + n; }
  const meta = { name, mimeType: "application/vnd.google-apps.folder", parents: [parentId] };
  const r = await fetch(DRIVE_API + "?fields=id,name,webViewLink&supportsAllDrives=true", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json; charset=UTF-8" },
    body: JSON.stringify(meta),
  });
  if (!r.ok) throw new Error("folder_create");
  return await r.json();
}

async function uniqueFileName(parentId, base, token) {
  const dot = base.lastIndexOf(".");
  const stem = dot > 0 ? base.slice(0, dot) : base;
  const ext = dot > 0 ? base.slice(dot) : "";
  let name = base, n = 1;
  while (await childFileExists(parentId, name, token)) { n++; name = stem + "_" + n + ext; }
  return name;
}

// 新規アップロード（resumable：大きさに依らず安全。常に新規作成）
async function uploadNew(parentId, name, fileObj, token) {
  const meta = { name, parents: [parentId] };
  const start = await fetch(DRIVE_UPLOAD + "?uploadType=resumable&fields=id,name,webViewLink&supportsAllDrives=true", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json; charset=UTF-8" },
    body: JSON.stringify(meta),
  });
  if (!start.ok) throw new Error("upload_init");
  const session = start.headers.get("Location");
  if (!session) throw new Error("no_session");
  const buf = await fileObj.arrayBuffer();
  const put = await fetch(session, {
    method: "PUT",
    headers: { "Content-Type": fileObj.type || "application/octet-stream" },
    body: buf,
  });
  if (!put.ok) throw new Error("upload_put");
  return await put.json();
}

/* ====================== レート制限（KV 日次カウンタ）====================== */
async function rateLimited(env) {
  if (!env.RL) return false; // KV未バインド時はスキップ（他の防御で守る）
  const limit = parseInt(env.DAILY_LIMIT || "100", 10);
  const day = new Date().toISOString().slice(0, 10); // UTC日付
  const key = "rl:" + day;
  const cur = parseInt((await env.RL.get(key)) || "0", 10);
  if (cur >= limit) return true;
  await env.RL.put(key, String(cur + 1), { expirationTtl: 172800 }); // 2日で自動失効
  return false;
}

/* ====================== ユーティリティ ====================== */
// パス区切り等の危険文字のみ安全文字へ。？ … 等の通常記号はそのまま残す。
function safeName(t) {
  t = String(t || "")
    .replace(/[\\/]/g, "／")              // / \ → 全角スラッシュ
    .replace(/\p{Cc}/gu, "")            // 制御文字除去
    .replace(/^\.+|\.+$/g, "")            // 先頭末尾のドット
    .trim();
  return t.slice(0, 120) || "video";
}
function escQ(s) { return String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'"); }
function extOf(mime) {
  mime = (mime || "").toLowerCase();
  if (mime.includes("mp4")) return "mp4";
  if (mime.includes("webm")) return "webm";
  if (mime.includes("quicktime") || mime.includes("mov")) return "mov";
  if (mime.includes("png")) return "png";
  if (mime.includes("jpeg") || mime.includes("jpg")) return "jpg";
  if (mime.includes("gif")) return "gif";
  if (mime.includes("webp")) return "webp";
  return "";
}
function extFromName(name) {
  const m = String(name || "").match(/\.([A-Za-z0-9]{1,5})$/);
  return m ? m[1].toLowerCase() : "";
}

/* ====================== CORS / レスポンス ====================== */
function corsHeaders(origin, allowed) {
  if (!allowed || origin !== allowed) return null;
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Shared-Secret",
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
