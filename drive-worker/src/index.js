/**
 * 5秒動画メーカー → Google Drive 自動保存 中継 Worker
 *
 * ★破壊面の不変条件（最重要・2026-08-13にChami指示で「同題名の上書き」を追加）★
 *   このWorkerが行うのは次の4種だけ：
 *     1) フォルダの新規作成（create）
 *     2) ファイルの新規アップロード（create / resumable）
 *     3) 参照（list / get）= 読み取りのみ
 *     4) ★フォルダのゴミ箱送り（trashed=true の PATCH）ただ1種のみ
 *        — 発動は「overwrite=1（フロント明示）かつ env.ALLOW_OVERWRITE='1'（サーバ側キルスイッチ）」の
 *          二重ロック時だけ。完全削除（files.delete）・改名（name update）・移動（parents update）の
 *          破壊APIは今回も一切実装しない（=grep検証の対象は "trashed" ただ1語）。
 *   上書きは「新フォルダを先に作って全部上げ、成功後に旧フォルダをtrash」＝どの時点で落ちても両方失う状態が
 *   存在しない。trashは30日間Drive側で復元可能（完全削除はしない）。1ヶ月判定はDriveの createdTime を正とし、
 *   trash直前に「そのチャンネル親の直下・フォルダ・trashed=false・題名完全一致・窓内」を全て再検証する。
 *   窓外/同名なし/フラグ無しなら従来どおり _2, _3… の別名で新規作成（既存挙動を温存）。
 *
 * 認証情報（client_id / client_secret / refresh_token / 共有シークレット）は
 * Cloudflare Worker Secrets にのみ保持し、レスポンス・ログには出力しない。
 */

const TOKEN_URL = "https://oauth2.googleapis.com/token";
const DRIVE_API = "https://www.googleapis.com/drive/v3/files";
const DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files";
const OVERWRITE_WINDOW_MS = 30 * 24 * 60 * 60 * 1000; // 「1ヶ月」=30日固定（暦月の28〜31日曖昧性を排除）
const OVERWRITE_MAX_TRASH = 3;                        // 窓内の同名候補がこれ超なら上書き全面中止（異常サイン）

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

    // ---- 入力（先にパース：読み取り専用アクションはレート制限の対象外にするため）----
    let form;
    try { form = await request.formData(); }
    catch (e) { return json({ ok: false, error: "bad_form" }, 400, cors); }

    // ---- 参照アクション：過去分プレビュー取り込み（read-only・非破壊）----
    //   [題名] フォルダ内の「題名_プレビュー.*」を探して画像を data URL で返すだけ。
    //   作成・削除・上書きは一切しない＝アップロードのレート制限とは別枠（読み取りは数えない）。
    if (String(form.get("action") || "") === "fetch_preview") {
      return await handleFetchPreview(form, env, cors);
    }
    // ---- 参照アクション：過去分プレビュー生成用に、[題名]フォルダの動画本体を返す（read-only・非破壊）----
    //   別端末で作った投稿は手元にもR2にも動画blobが無い。だがDriveには投稿完了時に動画が保存されている＝
    //   そこから取り寄せて先頭フレームでプレビューを起こせる（Chami指摘2026-08-14「別端末とか関係なくDriveの
    //   動画を参照すればできる」）。作成・削除・上書きは一切しない＝アップロードのレート制限とは別枠。
    if (String(form.get("action") || "") === "fetch_video") {
      return await handleFetchVideo(form, env, cors);
    }

    // ---- 簡易レート制限（KV：日次カウンタ・アップロード系のみ）----
    try {
      if (await rateLimited(env)) return json({ ok: false, error: "rate_limited" }, 429, cors);
    } catch (e) { /* KV未設定でも停止させない（他の防御で守る） */ }

    const channel = String(form.get("channel") || "").trim();
    const title = String(form.get("title") || "").trim();
    const video = form.get("video");
    const images = form.getAll("image"); // 複数可（元写真＋仕上がりプレビュー など）
    // 追記モード：既存の[動画名]フォルダへ画像だけ後追い保存（Bsky添付画像用）。
    const appendFolderId = String(form.get("folderId") || "").trim();

    // ---- チャンネル判定（曖昧なら保存しない＝取り違え事故より保存しないを優先）----
    const parentId = channelToFolderId(channel, env);
    if (!parentId) return json({ ok: false, error: "channel_unresolved", channel }, 400, cors);
    if (!title) return json({ ok: false, error: "missing_title" }, 400, cors);
    if (appendFolderId && !/^[A-Za-z0-9_-]{10,80}$/.test(appendFolderId)) {
      return json({ ok: false, error: "bad_folder_id" }, 400, cors);
    }
    if (!appendFolderId && !(video && typeof video.arrayBuffer === "function")) {
      return json({ ok: false, error: "missing_video" }, 400, cors);
    }

    // ---- アクセストークン（refresh_token から都度取得。メモリのみ）----
    let token;
    try { token = await getAccessToken(env); }
    catch (e) { return json({ ok: false, error: "auth_failed", reason: e.reason || "" }, 502, cors); }

    // ---- 親（チャンネル）フォルダの存在確認（read-only）。無ければ保存しない ----
    const parent = await getFolder(parentId, token);
    if (!parent) return json({ ok: false, error: "parent_folder_not_found", parentId }, 400, cors);

    // ---- 追記モード：指定フォルダが「このチャンネル親の直下」であることを検証してから画像を追加 ----
    if (appendFolderId) {
      const child = await getFolderMeta(appendFolderId, token);
      if (!child || child.trashed || !(child.parents || []).includes(parentId)) {
        return json({ ok: false, error: "folder_not_found" }, 400, cors);
      }
      const added = [];
      try {
        for (const image of images) {
          if (!(image && typeof image.arrayBuffer === "function")) continue;
          const fallback = "image." + (extOf(image.type) || "jpg");
          const iname = await uniqueFileName(appendFolderId, safeName(image.name || fallback), token);
          added.push(await uploadNew(appendFolderId, iname, image, token));
        }
      } catch (e) {
        return json({ ok: false, error: "upload_failed", folderId: appendFolderId }, 502, cors);
      }
      if (!added.length) return json({ ok: false, error: "missing_image" }, 400, cors);
      return json({ ok: true, appended: true, folderId: appendFolderId, files: added.map((f) => ({ id: f.id, name: f.name })) }, 200, cors);
    }

    // ---- 上書きモード判定（二重ロック：フロント明示 overwrite=1 ＆ env.ALLOW_OVERWRITE='1'）----
    //   safeName で "video" に潰れた題名（元題名≠video）はフォールバック名での誤爆源なので上書きしない。
    const baseName = safeName(title);
    const wantOverwrite = String(form.get("overwrite") || "") === "1"
      && env.ALLOW_OVERWRITE === "1"
      && !(baseName === "video" && title !== "video");
    // 窓内（30日以内作成）の同名フォルダを「新フォルダ作成の前」に確定させる（read-only）。
    let candidates = [];
    if (wantOverwrite) {
      try { candidates = await findOverwriteCandidates(parentId, baseName, token); }
      catch (e) { candidates = []; } // 列挙失敗＝消さない側へ倒す（従来経路で新規作成）
    }
    const doOverwrite = wantOverwrite && candidates.length > 0 && candidates.length <= OVERWRITE_MAX_TRASH;

    // ---- [動画名]フォルダを作成 ----
    //   上書き時は exact-name で作る（Driveは同名重複を許容＝改名API不要で穴が無い）。
    //   非上書き時は従来どおり衝突回避で _2, _3… の別名。
    let folder;
    try {
      folder = doOverwrite
        ? await createChildFolderExact(parentId, baseName, token)
        : await createUniqueChildFolder(parentId, baseName, token);
    }
    catch (e) { return json({ ok: false, error: "folder_create_failed" }, 502, cors); }

    // ---- アップロード（新規作成のみ。同名は連番で別名）----
    const uploaded = [];
    try {
      const vext = extOf(video.type) || extFromName(video.name) || "mp4";
      const vname = await uniqueFileName(folder.id, baseName + "." + vext, token);
      uploaded.push(await uploadNew(folder.id, vname, video, token));

      for (const image of images) {
        if (!(image && typeof image.arrayBuffer === "function")) continue;
        const fallback = "image." + (extOf(image.type) || "jpg");
        const iname = await uniqueFileName(folder.id, safeName(image.name || fallback), token);
        uploaded.push(await uploadNew(folder.id, iname, image, token));
      }
    } catch (e) {
      return json({ ok: false, error: "upload_failed", folderId: folder.id }, 502, cors);
    }

    // ---- 全アップロード成功後：旧フォルダをゴミ箱へ（唯一の破壊操作・trash直前に全条件を再検証）----
    //   先に新規を上げてからここへ来る＝どの時点で落ちても喪失ゼロ。trash失敗は一時的な重複で済み、
    //   次回の上書きで自分も窓内候補として回収される（自己修復）。
    const trashed = [], trashFailed = [];
    if (doOverwrite) {
      for (const c of candidates) {
        const ok = await trashFolderGuarded(c.id, { parentId, baseName, newFolderId: folder.id }, token);
        (ok ? trashed : trashFailed).push({ id: c.id, name: c.name });
      }
    }

    return json({
      ok: true,
      channel,
      parentName: parent.name,
      folderId: folder.id,
      folderName: folder.name,
      folderLink: folder.webViewLink || ("https://drive.google.com/drive/folders/" + folder.id),
      files: uploaded.map((f) => ({ id: f.id, name: f.name, link: f.webViewLink || "" })),
      overwritten: trashed.length > 0,
      ...(trashed.length ? { trashedFolders: trashed } : {}),
      ...(trashFailed.length ? { warning: "trash_failed", trashFailed } : {}),
      ...(wantOverwrite && !doOverwrite ? { overwriteSkipped: candidates.length ? "too_many" : "no_recent_match" } : {}),
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
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.access_token) {
    const e = new Error("token");
    e.reason = j.error || ("http_" + r.status); // 例: invalid_grant / invalid_client（秘密ではない・診断用）
    throw e;
  }
  return j.access_token;
}

/* ====================== 参照（read-only）====================== */
// 過去分プレビュー取り込み：[題名]フォルダの「題名_プレビュー.*」画像を data URL で返す（無ければ found:false）。
//   非破壊＝一切書かない。folder名は safeName(title) 換算で照合（アップロード時と同じ規則）。
async function handleFetchPreview(form, env, cors) {
  const channel = String(form.get("channel") || "").trim();
  const title = String(form.get("title") || "").trim();
  const parentId = channelToFolderId(channel, env);
  if (!parentId) return json({ ok: false, error: "channel_unresolved", channel }, 400, cors);
  if (!title) return json({ ok: false, error: "missing_title" }, 400, cors);

  let token;
  try { token = await getAccessToken(env); }
  catch (e) { return json({ ok: false, error: "auth_failed", reason: e.reason || "" }, 502, cors); }

  const baseName = safeName(title);
  let folderIds;
  try { folderIds = await findChildFolderIds(parentId, baseName, token); }
  catch (e) { return json({ ok: false, error: "list_failed" }, 502, cors); }
  if (!folderIds.length) return json({ ok: true, found: false, reason: "folder_not_found" }, 200, cors);

  let file = null;
  for (const fid of folderIds) { file = await findPreviewFile(fid, token); if (file) break; }
  if (!file) return json({ ok: true, found: false, reason: "preview_not_found" }, 200, cors);

  let dataUrl;
  try { dataUrl = await downloadMediaDataUrl(file.id, file.mimeType || "image/jpeg", token); }
  catch (e) { return json({ ok: false, error: "download_failed" }, 502, cors); }
  return json({ ok: true, found: true, name: file.name, dataUrl }, 200, cors);
}

// 過去分プレビュー生成の最終手段：[題名]フォルダの動画本体をそのまま返す（非破壊）。
//   動画は大きいので data URL(base64)化せず、Driveの応答ボディをそのままストリームで中継する
//   （フロントは Content-Type が video/ なら r.blob() で受ける）。見つからなければ found:false のJSON。
async function handleFetchVideo(form, env, cors) {
  const channel = String(form.get("channel") || "").trim();
  const title = String(form.get("title") || "").trim();
  const parentId = channelToFolderId(channel, env);
  if (!parentId) return json({ ok: false, error: "channel_unresolved", channel }, 400, cors);
  if (!title) return json({ ok: false, error: "missing_title" }, 400, cors);

  let token;
  try { token = await getAccessToken(env); }
  catch (e) { return json({ ok: false, error: "auth_failed", reason: e.reason || "" }, 502, cors); }

  const baseName = safeName(title);
  let folderIds;
  try { folderIds = await findChildFolderIds(parentId, baseName, token); }
  catch (e) { return json({ ok: false, error: "list_failed" }, 502, cors); }
  if (!folderIds.length) return json({ ok: true, found: false, reason: "folder_not_found" }, 200, cors);

  let file = null;
  for (const fid of folderIds) { file = await findVideoFile(fid, token); if (file) break; }
  if (!file) return json({ ok: true, found: false, reason: "video_not_found" }, 200, cors);

  const url = DRIVE_API + "/" + encodeURIComponent(file.id) + "?alt=media&supportsAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok || !r.body) return json({ ok: false, error: "download_failed" }, 502, cors);
  const headers = Object.assign({ "Content-Type": file.mimeType || "video/mp4" }, cors || {});
  return new Response(r.body, { status: 200, headers });
}

// フォルダ内の動画ファイルを1件返す（無ければ null）。仕上がりプレビュー等の画像は mimeType で除外。
async function findVideoFile(folderId, token) {
  const q = "'" + folderId + "' in parents and mimeType contains 'video/' and trashed=false";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) + "&fields=files(id,name,mimeType)&pageSize=5&supportsAllDrives=true&includeItemsFromAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return null;
  const j = await r.json();
  const f = (j.files || [])[0];
  return f && f.id ? f : null;
}

// 親フォルダ直下で name 完全一致のサブフォルダIDを列挙（連番 _2 等は別名なので拾えない＝題名一致のみ）。
async function findChildFolderIds(parentId, name, token) {
  const q = "name='" + escQ(name) + "' and '" + parentId +
    "' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) + "&fields=files(id)&pageSize=20&supportsAllDrives=true&includeItemsFromAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) throw new Error("list");
  const j = await r.json();
  return (j.files || []).map((f) => f.id);
}

// フォルダ内で「プレビュー」を名前に含む画像ファイルを1件返す（無ければ null）。
async function findPreviewFile(folderId, token) {
  const q = "'" + folderId + "' in parents and name contains 'プレビュー' and mimeType contains 'image/' and trashed=false";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) + "&fields=files(id,name,mimeType)&pageSize=5&supportsAllDrives=true&includeItemsFromAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return null;
  const j = await r.json();
  const f = (j.files || [])[0];
  return f && f.id ? f : null;
}

// ファイル本体を取得して data URL 化（alt=media）。
async function downloadMediaDataUrl(id, mime, token) {
  const url = DRIVE_API + "/" + encodeURIComponent(id) + "?alt=media&supportsAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) throw new Error("media");
  const buf = await r.arrayBuffer();
  return "data:" + (mime || "image/jpeg") + ";base64," + abToBase64(buf);
}

function abToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  return btoa(bin);
}

async function getFolder(id, token) {
  const url = DRIVE_API + "/" + encodeURIComponent(id) + "?fields=id,name,mimeType&supportsAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return null;
  const j = await r.json();
  return j && j.id ? j : null;
}

// 追記モード用：フォルダのメタ（親・ゴミ箱状態つき）。存在しなければ null。
async function getFolderMeta(id, token) {
  const url = DRIVE_API + "/" + encodeURIComponent(id) + "?fields=id,name,mimeType,parents,trashed&supportsAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return null;
  const j = await r.json();
  return (j && j.id && j.mimeType === "application/vnd.google-apps.folder") ? j : null;
}

async function childFolderExists(parentId, name, token) {
  const q = "name='" + escQ(name) + "' and '" + parentId +
    "' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) + "&fields=files(id)&pageSize=1";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return false;
  const j = await r.json();
  return !!(j.files && j.files.length);
}

async function childFileExists(parentId, name, token) {
  const q = "name='" + escQ(name) + "' and '" + parentId + "' in parents and trashed=false";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) + "&fields=files(id)&pageSize=1";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return false;
  const j = await r.json();
  return !!(j.files && j.files.length);
}

/* ====================== 上書き（overwrite=1 ＆ env.ALLOW_OVERWRITE 時のみ）====================== */
// 窓内（createdTime が30日以内）の exact-name サブフォルダを列挙。findChildFolderIds の createdTime 付き版。
//   createdTime は Drive サーバの正＝フロントの時計/申告に依存しない。境界（ちょうど30日）は含む（<=）。
async function findOverwriteCandidates(parentId, name, token) {
  const q = "name='" + escQ(name) + "' and '" + parentId +
    "' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) +
    "&fields=files(id,name,createdTime)&pageSize=20&supportsAllDrives=true&includeItemsFromAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) throw new Error("list");
  const j = await r.json();
  const now = Date.now();
  return (j.files || []).filter((f) =>
    f.createdTime && (now - Date.parse(f.createdTime)) <= OVERWRITE_WINDOW_MS);
}

// exact-name でフォルダ作成（同名existsチェックを意図的にしない。Driveは同一親内の同名フォルダを許容）。
async function createChildFolderExact(parentId, name, token) {
  const meta = { name, mimeType: "application/vnd.google-apps.folder", parents: [parentId] };
  const r = await fetch(DRIVE_API + "?fields=id,name,webViewLink&supportsAllDrives=true", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json; charset=UTF-8" },
    body: JSON.stringify(meta),
  });
  if (!r.ok) throw new Error("folder_create");
  return await r.json();
}

// ★このWorker唯一の破壊操作。trash直前に全条件を再検証し、1つでも満たさなければ何もしない（消さない側へ）。
//   完全削除はしない＝trashed=true の PATCH のみ（30日間Drive側で復元可能）。
async function trashFolderGuarded(id, ctx, token) {
  if (!id || id === ctx.parentId || id === ctx.newFolderId) return false;
  const url = DRIVE_API + "/" + encodeURIComponent(id) +
    "?fields=id,name,mimeType,parents,trashed,createdTime&supportsAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) return false;
  const m = await r.json();
  if (m.mimeType !== "application/vnd.google-apps.folder") return false; // ファイルは絶対にtrashしない
  if (m.trashed) return false;
  if (!(m.parents || []).includes(ctx.parentId)) return false;          // チャンネル親の直下限定
  if (m.name !== ctx.baseName) return false;                            // 題名完全一致
  if (!m.createdTime || (Date.now() - Date.parse(m.createdTime)) > OVERWRITE_WINDOW_MS) return false; // 窓内
  const p = await fetch(DRIVE_API + "/" + encodeURIComponent(id) + "?supportsAllDrives=true", {
    method: "PATCH",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json; charset=UTF-8" },
    body: JSON.stringify({ trashed: true }),
  });
  return p.ok;
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
