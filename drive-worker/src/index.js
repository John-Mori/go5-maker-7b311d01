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
 *   normalize以外は同名フォルダを再利用し、不足ファイルだけ追加する。同名が無い初回だけexact-nameで作成する。
 *
 * 認証情報（client_id / client_secret / refresh_token / 共有シークレット）は
 * Cloudflare Worker Secrets にのみ保持し、レスポンス・ログには出力しない。
 */

const TOKEN_URL = "https://oauth2.googleapis.com/token";
const DRIVE_API = "https://www.googleapis.com/drive/v3/files";
const DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files";
const OVERWRITE_WINDOW_MS = 30 * 24 * 60 * 60 * 1000; // 「1ヶ月」=30日固定（暦月の28〜31日曖昧性を排除）
const OVERWRITE_MAX_TRASH = 3;                        // 窓内の同名候補がこれ超なら上書き全面中止（異常サイン）
const SAVE_JOB_VIDEO_KEY_RE = /^[a-f0-9]{16,64}$/;    // R2キー(sha256hex)の形式
const SAVE_JOB_R2_BASE_RE = /^https?:\/\//;
const SAVE_JOB_RETRY_DELAYS_MS = [1500, 4000]; // 動画バイトのR2取得：最大3回(計約5.5秒)。★フロントが投稿完了前にHEADでR2着地を実測してから撃つ(ensureVideoOnR2_)=初回GETで取れるのが通常。長い窓(旧37秒)はrunSaveJobをリクエスト時間予算から溢れさせ、waitUntilのアップロードを途中でCloudflareに殺させていた真因(2026-08-18 wrangler tailで実測=「waitUntil() tasks…cancelled」)。窓はR2の結果整合レースの保険だけに絞る。
// 同一Worker isolate内で同じ親＋題名の同時作成を1本へ束ねる。
// Driveは同一親内の同名フォルダを許すため、単純な list→create だけでは並列再送時に二重作成できる。
const EXACT_FOLDER_INFLIGHT = new Map();
// 同じ作品のsave_jobを別Worker isolateから同時実行させない分散リース。
// R2の条件付きPUT(If-None-Match / If-Match)を使い、list→create/upload の隙間をプロセス境界ごと塞ぐ。
const DRIVE_JOB_LEASE_MS = 15 * 60 * 1000;
const DRIVE_JOB_COOLDOWN_MS = 5 * 60 * 1000;
//   フロントはHEADでR2着地を確認してからsave_jobを撃つ(2026-08-18)ので通常は初回で取れるが、R2の反映レース/公開GETの
//   一時的な不整合に備えて窓を広げる。waitUntil内の待機はCPUを消費しない=Workers上限内。

export default {
  async fetch(request, env, ctx) {
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
    // ---- 参照アクション：save_jobの完走確認（read-only・非破壊）----
    //   [題名]フォルダ内に動画ファイルが既に在るか(=保存済みか)だけを返す。フロントの永続pending sweepが
    //   「もうDriveに在る」と確認できたらpendingを畳むための軽い照会。作成・削除・上書きは一切しない。
    if (String(form.get("action") || "") === "check_saved") {
      return await handleCheckSaved(form, env, cors);
    }
    // ---- 参照アクション：作品フォルダの直リンク解決（read-only・非破壊）----
    //   投稿履歴のGoogleドライブ・アイコンを押した時、[チャンネル]/[題名] フォルダのIDと webViewLink を返す。
    //   これで題名検索ではなく「その作品のフォルダそのもの」を開ける（Chami依頼2026-08-16②）。作成・削除・上書きはしない。
    if (String(form.get("action") || "") === "folder_link") {
      return await handleFolderLink(form, env, cors);
    }
    // ---- 参照アクション：作品フォルダの中身の在り無し（read-only・非破壊）----
    //   [題名]フォルダに 動画 / 仕上がりプレビュー / 元画像 がそれぞれ在るかを1回で返す。データ再生成が
    //   「Driveに無いものだけ補う（既にあるものは上げ直さない）」判定に使う＝プレビューの重複生成を止め、
    //   足りない元画像だけを補う（Chami報告2026-08-18「元画像だけがない場合でデータ再生成してもプレビューが
    //   もう一つできるだけ。意味なし」）。check_saved(動画の有無だけ・sweepが多用)とは別アクション＝hot pathを重くしない。
    if (String(form.get("action") || "") === "folder_state") {
      return await handleFolderState(form, env, cors);
    }

    // ---- 簡易レート制限（KV：日次カウンタ・アップロード系のみ）----
    try {
      if (await rateLimited(env)) return json({ ok: false, error: "rate_limited" }, 429, cors);
    } catch (e) { /* KV未設定でも停止させない（他の防御で守る） */ }

    // ---- サーバー側完走ジョブ：save_job（軽いFormData→即202→ctx.waitUntilで裏完走。閉じても続く）----
    //   2026-08-16 Chami依頼「途中で閉じても裏で完結」。動画バイトはこのリクエストに乗せず、
    //   R2上の在り処(videoKey)だけを受け取り、ここから先はサーバー側でR2→Driveを完走させる。
    if (String(form.get("action") || "") === "save_job") {
      return await handleSaveJob(form, env, cors, ctx);
    }

    // ---- 退避保存：ensure_folder（write・動画が無くても最低限フォルダを作り、手元の画像だけ退避）----
    //   Chami依頼2026-08-18「動画がないとつくれないなら仕方ない。にしてもフォルダくらい作ってくれ、あと
    //   プレビュー画像や元画像はあるならそれを取得して名前変えて保存すればいいだろ」。動画本体が復元不能でも
    //   全か無かにせず、[チャンネル]/[題名]フォルダを確保し、渡された画像(プレビュー/元画像)だけ保存する。
    //   破壊面の不変条件は不変＝フォルダ新規作成・ファイル新規アップロードのみ（削除/改名/移動/trashは一切しない）。
    if (String(form.get("action") || "") === "ensure_folder") {
      return await handleEnsureFolder(form, env, cors);
    }

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

    // ---- 上書き/trash モード判定 ----
    //   ★Chami依頼2026-08-24「(後で足す時は)昔のやつを更新するな。足りてないものだけを足せ。2を作るな」。
    //   自動保存(overwrite=1)でも "trashしない"＝既存フォルダを再利用し足りないものだけ足す(save_job経路と同一作法)。
    //   旧フォルダのゴミ箱送りは手動の明示 normalize=1 の時だけ。safeName で "video" に潰れた題名は誤爆源なので除外。
    const baseName = safeName(title);
    const wantOverwrite = String(form.get("normalize") || "") === "1"
      && String(form.get("overwrite") || "") === "1"
      && env.ALLOW_OVERWRITE === "1"
      && !(baseName === "video" && title !== "video");
    const noWindow = wantOverwrite; // normalize時は30日窓を外す(古いフォルダも作り直し対象)
    // 窓内（30日以内作成）の同名フォルダを「新フォルダ作成の前」に確定させる（read-only）。noWindow時は窓を外す。
    let candidates = [];
    if (wantOverwrite) {
      try { candidates = await findOverwriteCandidates(parentId, baseName, token, noWindow); }
      catch (e) { candidates = []; } // 列挙失敗＝消さない側へ倒す（従来経路で新規作成）
    }
    const doOverwrite = wantOverwrite && candidates.length > 0 && candidates.length <= OVERWRITE_MAX_TRASH;

    // ---- [題名]フォルダを決定 ----
    //   ★normalize時は exact-name で"新しく"作り成功後に旧をtrash。それ以外(自動保存)は同題名フォルダが在れば
    //     再利用=連番 _2, _3… を作らない(Chami依頼2026-08-24「2を作るな」)。初回のみ exact-name で新規作成。
    let folder, reused = false;
    try {
      if (doOverwrite) {
        folder = await createChildFolderExact(parentId, baseName, token);
      } else {
        const ensured = await getOrCreateExactFolder(parentId, baseName, token);
        folder = ensured.folder;
        reused = !!ensured.reused;
      }
    }
    catch (e) { return json({ ok: false, error: (e && e.message) || "folder_create_failed" }, 502, cors); }

    // ---- アップロード（動画=既に在れば上げ直さない／画像=role単位で既存なら上げ直さない＝重複を作らない）----
    const uploaded = [];
    try {
      if (!(reused && await findVideoFile(folder.id, token))) {
        const vext = extOf(video.type) || extFromName(video.name) || "mp4";
        const vname = await uniqueFileName(folder.id, baseName + "." + vext, token);
        uploaded.push(await uploadNew(folder.id, vname, video, token));
      }
      for (const image of images) {
        if (!(image && typeof image.arrayBuffer === "function")) continue;
        const fallback = "image." + (extOf(image.type) || "jpg");
        const nm = safeName(image.name || fallback);
        // role(プレビュー/元画像)が既にフォルダに在れば上げ直さない=題名_プレビュー_2 等の増殖を止める。
        if (nm.indexOf("プレビュー") >= 0 && await findPreviewFile(folder.id, token)) continue;
        if (nm.indexOf("元画像") >= 0 && await findSrcImageFile(folder.id, token)) continue;
        const iname = await uniqueFileName(folder.id, nm, token);
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
        const ok = await trashFolderGuarded(c.id, { parentId, baseName, newFolderId: folder.id, noWindow }, token);
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

/* ====================== 退避保存（ensure_folder・write）====================== */
// 動画本体が復元不能でも、せめて[チャンネル]/[題名]フォルダを作り、渡された画像だけ退避保存する。
//   冪等：同題名フォルダが既に在れば再利用（連番 _2 を作らない）、同じ役割（プレビュー/元画像）が既に在れば
//   上げ直さない（＝データ再生成で「_プレビュー」が増殖する事故を再演しない）。行う操作は create/upload の
//   2種だけ＝破壊面の不変条件（削除/改名/移動/trashなし）は変わらない。フロントは folder_state で不足分だけ
//   送る想定だが、ここでも役割ごとに存在確認して二重を防ぐ（サーバ側でも冪等を保証）。
async function handleEnsureFolder(form, env, cors) {
  const channel = String(form.get("channel") || "").trim();
  const title = String(form.get("title") || "").trim();
  const images = form.getAll("image"); // 0〜N枚（プレビュー/元画像）。0枚でもフォルダは作る（Chami「フォルダくらい作って」）。
  const parentId = channelToFolderId(channel, env);
  if (!parentId) return json({ ok: false, error: "channel_unresolved", channel }, 400, cors);
  if (!title) return json({ ok: false, error: "missing_title" }, 400, cors);

  let token;
  try { token = await getAccessToken(env); }
  catch (e) { return json({ ok: false, error: "auth_failed", reason: e.reason || "" }, 502, cors); }

  const parent = await getFolder(parentId, token);
  if (!parent) return json({ ok: false, error: "parent_folder_not_found", parentId }, 400, cors);

  const baseName = safeName(title);
  // ── フォルダ確保：既存があれば再利用、無ければ exact-name で新規作成（連番にしない＝1作品1フォルダ）──
  let folderId = "", created = false;
  try {
    const ensured = await getOrCreateExactFolder(parentId, baseName, token);
    folderId = ensured.folder.id;
    created = !!ensured.created;
  } catch (e) {
    return json({ ok: false, error: (e && e.message) || "folder_create_failed" }, 502, cors);
  }
  if (!folderId) return json({ ok: false, error: "folder_create_failed" }, 502, cors);

  // ── 渡された画像を役割ごとに冪等保存（同役割が既に在れば上げ直さない）──
  const added = [], skipped = [];
  try {
    for (const image of images) {
      if (!(image && typeof image.arrayBuffer === "function")) continue;
      const nm = safeName(image.name || ("image." + (extOf(image.type) || "jpg")));
      const isPreview = nm.indexOf("プレビュー") >= 0;
      const isSrc = nm.indexOf("元画像") >= 0;
      if (isPreview && await findPreviewFile(folderId, token)) { skipped.push(nm); continue; }
      if (isSrc && await findSrcImageFile(folderId, token)) { skipped.push(nm); continue; }
      const iname = await uniqueFileName(folderId, nm, token);
      const up = await uploadNew(folderId, iname, image, token);
      added.push(up.name || iname);
    }
  } catch (e) { return json({ ok: false, error: "upload_failed", folderId }, 502, cors); }

  return json({
    ok: true,
    channel,
    folderId,
    created,
    folderLink: "https://drive.google.com/drive/folders/" + folderId,
    added,
    skipped,
  }, 200, cors);
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

/* ====================== save_job（軽いジョブ→サーバー側完走）====================== */
// 入力検証（純関数・envも副作用なしの参照のみ）。channel未解決/title欠落/videoKey・r2Baseの形式不正は400。
function validateSaveJobInput(fields, env) {
  const parentId = channelToFolderId(fields.channel, env);
  if (!parentId) return { ok: false, error: "channel_unresolved" };
  if (!fields.title) return { ok: false, error: "missing_title" };
  if (!SAVE_JOB_VIDEO_KEY_RE.test(fields.videoKey || "")) return { ok: false, error: "bad_video_key" };
  if (!SAVE_JOB_R2_BASE_RE.test(fields.r2Base || "")) return { ok: false, error: "bad_r2_base" };
  return { ok: true, parentId };
}

async function handleSaveJob(form, env, cors, ctx) {
  const fields = {
    channel: String(form.get("channel") || "").trim(),
    title: String(form.get("title") || "").trim(),
    videoId: String(form.get("videoId") || "").trim(),
    r2Base: String(form.get("r2Base") || "").trim(),
    videoKey: String(form.get("videoKey") || "").trim(),
    previewKey: String(form.get("previewKey") || "").trim(), // 任意・R2上の仕上がりプレビュー(小)の在り処
    srcKey: String(form.get("srcKey") || "").trim(),         // 任意・R2上の元画像(動画に使った写真)の在り処
    overwrite: String(form.get("overwrite") || "") === "1",
    // ★正常化(手動の明示「名前を正しく保存し直す」だけ)。これが立った時だけ30日窓を外して古いフォルダも作り直し
    //   対象にする(Chami承認2026-08-22)。自動保存(投稿完了/作成時)には絶対に付かない=誤爆で古い作品をゴミ箱送りにしない。
    //   二重ロック(overwrite ＆ env.ALLOW_OVERWRITE)が揃った時のみ後続で有効化する(下 wantOverwrite 参照)。
    normalize: String(form.get("normalize") || "") === "1",
  };
  const v = validateSaveJobInput(fields, env);
  if (!v.ok) return json({ ok: false, error: v.error }, 400, cors);

  // ★根本修正(2026-08-18 wrangler tailで実測)：旧実装は即202を返してから重いアップロードを ctx.waitUntil に丸投げ
  //   していた=「応答後」の待機はCloudflareの予算が小さく、動画アップロード完走前に "waitUntil() tasks…cancelled"
  //   で黙って殺され、Driveに何も残らないのに投稿完了UIは成功に見えた(=保存されない事故の真因)。
  //   直し方：重い処理は「リクエスト実行中(=大きい予算)」に await して本物の結果を返す。同時に waitUntil にも
  //   同じジョブを載せる=クライアント(タブ)が途中で切れても、Cloudflareがそのジョブを保持して完走させる
  //   (＝「閉じても裏で完結」Chami 2026-08-16 も維持)。フロント queueSave_ は 202/200 どちらも成功扱い・失敗(502)は
  //   error を拾える=結果が見える。破壊面の不変条件(create/upload/reference/trashの4種)は不変。
  const job = runSaveJob(env, fields, v.parentId).catch((e) => ({ ok: false, error: "exception:" + (e && e.message || e) }));
  if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(job); // タブが切れても保持=完走
  const result = await job; // ★リクエスト実行中に本体を回す=応答後waitUntilの狭い予算で殺されない
  if (result && result.ok) {
    // videoPending=true は「フォルダの床＋付随画像は作ったが動画バイトがまだR2から取れなかった」床保存。
    //   saved は動画が載った時だけ true=フロントは checkSaved(動画有無)で pending を管理し続ける(=次回sweepで動画を再送)。
    return json({
      ok: true,
      saved: !result.videoPending,
      folderId: result.folderId || "",
      skipped: !!result.skipped,
      ...(result.videoPending ? { videoPending: true } : {}),
    }, 200, cors);
  }
  return json({ ok: false, error: (result && result.error) || "save_failed" }, 502, cors);
}

// R2条件付きPUTによる分散リース。同じ親＋題名に対し、別isolate/別リクエストでも所有者は必ず1つ。
async function driveJobLeaseKey(parentId, baseName) {
  const raw = new TextEncoder().encode(String(parentId || "") + "\n" + String(baseName || ""));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", raw);
  const hex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  return "__go5_drive_lease/" + hex;
}
function leaseExpiresAt(obj) {
  return Number(obj && obj.customMetadata && obj.customMetadata.expiresAt) || 0;
}
function leaseIfMatch(obj) {
  const etag = obj && (obj.httpEtag || (obj.etag ? ("\"" + obj.etag + "\"") : ""));
  return etag ? new Headers({ "If-Match": etag }) : null;
}
async function acquireDriveJobLease(env, parentId, baseName, owner, nowMs) {
  const bucket = env && env.SYNC_IMAGES;
  if (!bucket || typeof bucket.head !== "function" || typeof bucket.put !== "function")
    return { ok: false, error: "drive_lease_binding_missing" };
  const now = Number(nowMs || Date.now());
  try {
    const key = await driveJobLeaseKey(parentId, baseName);
    const current = await bucket.head(key);
    if (current && leaseExpiresAt(current) > now) return { ok: false, busy: true, key };
    let onlyIf;
    if (current) {
      onlyIf = leaseIfMatch(current);
      if (!onlyIf) return { ok: false, error: "drive_lease_etag_missing" };
    } else {
      onlyIf = new Headers({ "If-None-Match": "*" });
    }
    const expiresAt = now + DRIVE_JOB_LEASE_MS;
    let created;
    try {
      created = await bucket.put(key, String(owner || ""), {
        onlyIf, customMetadata: { owner: String(owner || ""), expiresAt: String(expiresAt) }
      });
    } catch (e) {
      // 条件競合を一般障害と誤報しない。現在の所有者が見えればbusyへ倒す。
      const latest = await bucket.head(key).catch(() => null);
      if (latest && leaseExpiresAt(latest) > now) return { ok: false, busy: true, key };
      return { ok: false, error: "drive_lease_put_failed" };
    }
    if (!created) return { ok: false, busy: true, key };
    return { ok: true, key, owner: String(owner || ""), object: created, expiresAt };
  } catch (e) {
    return { ok: false, error: "drive_lease_unavailable" };
  }
}
async function rewriteDriveJobLease(env, lease, expiresAt) {
  const bucket = env && env.SYNC_IMAGES;
  const onlyIf = leaseIfMatch(lease && lease.object);
  if (!bucket || !onlyIf || !lease || !lease.key) return false;
  try {
    const obj = await bucket.put(lease.key, lease.owner || "", {
      onlyIf, customMetadata: { owner: lease.owner || "", expiresAt: String(expiresAt) }
    });
    if (!obj) return false;
    lease.object = obj; lease.expiresAt = expiresAt;
    return true;
  } catch (e) { return false; }
}
async function holdDriveJobLease(env, lease, ms) {
  return rewriteDriveJobLease(env, lease, Date.now() + Math.max(1000, Number(ms || 0)));
}
async function releaseDriveJobLease(env, lease) {
  // deleteは、期限切れ直後に新所有者が取ったリースを消す競合を作る。自分のETagが一致する時だけ期限0へ更新する。
  return rewriteDriveJobLease(env, lease, 0);
}

// R2から動画バイトを取得→Driveへ保存する本体。フロントの重複抑止に加え、Worker間も分散リースで直列化する。
async function runSaveJob(env, fields, parentId) {
  const owner = (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function")
    ? globalThis.crypto.randomUUID()
    : (Date.now() + "-" + Math.random().toString(36).slice(2));
  const lease = await acquireDriveJobLease(env, parentId, safeName(fields.title), owner);
  if (!lease.ok) {
    if (lease.busy) {
      try { console.log("[save_job] duplicate suppressed: " + (fields.videoId || "?") + " / " + (fields.title || "?")); } catch (_) {}
      // 先行ジョブが保存中。pendingを残し、後の実物確認で完了へ上げる。
      return { ok: true, videoPending: true, skipped: true, inFlight: true };
    }
    return { ok: false, error: lease.error || "drive_lease_unavailable" };
  }
  let result;
  try {
    result = await runSaveJobUnlocked(env, fields, parentId);
    return result;
  } finally {
    // 動画まで成功した後は5分のクールダウンを残す。2分遅れで来た別経路もDriveへ触れない。
    // 失敗/動画未着は即解放し、永続pendingの自己修復を妨げない。
    if (result && result.ok && !result.videoPending) await holdDriveJobLease(env, lease, DRIVE_JOB_COOLDOWN_MS);
    else await releaseDriveJobLease(env, lease);
  }
}

async function runSaveJobUnlocked(env, fields, parentId) {
  // ★観測ライン(2026-08-17 オタコン)：この完走本体は失敗が全て静かなreturnで、サーバー側に痕跡が一切無く
  //   「アプリは"裏で完走"と出すのにDriveに動画が来ない」を事後に診断できなかった(H5)。各終端に構造化ログを
  //   残す=wrangler tail / Workers Logs で「どの段で落ちたか」を実測できる。ログのみ＝破壊面は不変。
  const tag = "[save_job] " + (fields.videoId || "?") + " / " + (fields.title || "?") + " / " + (fields.channel || "?");
  const fail = function (why) { try { console.warn(tag + " FAIL:" + why); } catch (_) {} return { ok: false, error: why }; };
  try { console.log(tag + " START"); } catch (_) {} // ★どこまで進んだかを実測する起点(cancelされた時に「入口までは来た」が分かる)

  // ★トークン・親フォルダを"動画バイトの取得より先"に確保する(Chami依頼2026-08-24「せめて一億歩譲ってフォルダ
  //   だけは作れ」)。旧実装は動画バイトが R2 から取れないと即 fail("r2_video_missing") で return=フォルダも
  //   プレビューも元画像も一切作られず「投稿完了したのにDriveに何も無い」だった。動画が取れなくても最低限
  //   [チャンネル]/[題名]フォルダを確保し、手元にある(previewKey/srcKey=R2)プレビュー・元画像だけは保存する。
  let token;
  try { token = await getAccessToken(env); } catch (e) { return fail("auth_failed"); }
  const parent = await getFolder(parentId, token);
  if (!parent) return fail("parent_folder_missing");

  const baseName = safeName(fields.title);

  // 通常の再生成/自動保存は、重いR2探索より先にDriveの同名フォルダを確認・確保する。
  // これで旧IDが外れて動画探索が空振りしても、フォルダだけは先に着地する。
  // normalizeは動画実在時だけ新旧入替を行う特殊経路なので、ここでは先作成しない。
  let floor = null;
  if (!fields.normalize) {
    try { floor = await getOrCreateExactFolder(parentId, baseName, token); }
    catch (e) { return fail((e && e.message) || "folder_create_failed"); }
  }

  // ---- 動画バイト取得(R2)。取れなくてもここで止めず、下でフォルダの床＋付随画像だけは作る ----
  const vid = await fetchR2Bytes(env, fields.r2Base, fields.videoKey, SAVE_JOB_RETRY_DELAYS_MS);
  const buf = vid ? vid.buf : null;
  const mime = (vid && vid.mime) || "video/mp4";
  const haveVideo = !!(buf && buf.byteLength);
  if (haveVideo) { try { console.log(tag + " r2_ok bytes=" + buf.byteLength); } catch (_) {} }
  else { try { console.warn(tag + " r2_video_missing → フォルダの床だけ作る"); } catch (_) {} }

  // ---- 上書き/trash モード判定 ----
  //   ★Chami依頼2026-08-24「(後で足す時は)昔のやつを更新するな。必要な、足りてないものだけを足せ」。
  //   自動の投稿完了/再送は overwrite=1 を送ってきても "trashしない"＝既存フォルダを再利用して足りないものだけ足す。
  //   旧フォルダをゴミ箱送りにする破壊は、手動の明示 normalize=1(「名前を正しく保存し直す」)の時だけに限定する。
  //   これで sweep 再送(previewKey/srcKey 無し)が floor フォルダをtrashして付随画像を失う事故を封じる。
  //   三重ロック：normalize=1(手動明示) ＆ フロント overwrite=1 ＆ env.ALLOW_OVERWRITE='1'。動画実在も必須。
  const wantOverwrite = haveVideo && !!fields.normalize && !!fields.overwrite && env.ALLOW_OVERWRITE === "1"
    && !(baseName === "video" && fields.title !== "video");
  const noWindow = wantOverwrite; // normalize時は30日窓を外す(古いフォルダも作り直し対象=既存 normalize 仕様)
  let candidates = [];
  if (wantOverwrite) {
    try { candidates = await findOverwriteCandidates(parentId, baseName, token, noWindow); } catch (e) { candidates = []; }
  }
  const doOverwrite = wantOverwrite && candidates.length > 0 && candidates.length <= OVERWRITE_MAX_TRASH;

  // ---- 保存先フォルダの決定 ----
  //   ★上書きでない時は「同題名フォルダが在れば再利用」する(Chami依頼2026-08-24「2を作るな」)。旧実装は
  //     createUniqueChildFolder で 題名_2, 題名_3… を量産していた=動画が無い床フォルダの後に本保存が来ると
  //     "同題名だが動画未検出"を見て別名フォルダを新規作成→二重フォルダ、が起きていた。再利用+足りないものだけ足す。
  //   ★上書き時だけ exact-name で"新しく"作り、成功後に旧フォルダをtrash(従来どおり)。
  let folder, reused = false;
  try {
    if (doOverwrite) {
      folder = await createChildFolderExact(parentId, baseName, token);
    } else {
      const ensured = floor || await getOrCreateExactFolder(parentId, baseName, token);
      folder = ensured.folder;
      reused = !!ensured.reused;
    }
  } catch (e) { return fail((e && e.message) || "folder_create_failed"); }

  // ---- 動画アップロード（有る時だけ・既に同フォルダに動画が在れば上げ直さない=足りないものだけ）----
  let videoAlready = false;
  if (haveVideo) {
    try {
      if (reused) videoAlready = !!(await findVideoFile(folder.id, token));
      if (!videoAlready) {
        const vext = extOf(mime) || "mp4";
        const vname = await uniqueFileName(folder.id, baseName + "." + vext, token);
        await uploadNewBuffer(folder.id, vname, buf, mime, token);
      }
    } catch (e) { return fail("video_upload_failed:" + (e && e.message || e)); }
  }

  // ---- 元画像（任意・R2から取り寄せ）。★同フォルダに「元画像」が既に在れば上げ直さない(role単位の冪等)。
  //   旧実装は uniqueFileName で 題名_元画像_2.jpg を毎回増やしていた(Chami報告2026-08-22「いらんやつ作られてまっせ」)。
  //   付随物なので失敗しても動画保存の成功は覆さない。----
  if (SAVE_JOB_VIDEO_KEY_RE.test(fields.srcKey || "")) {
    try {
      if (!(await findSrcImageFile(folder.id, token))) {
        const sv = await fetchR2Bytes(env, fields.r2Base, fields.srcKey, [500, 1500]);
        if (sv && sv.buf && sv.buf.byteLength) {
          const sname = await uniqueFileName(folder.id, baseName + "_元画像." + (extOf(sv.mime) || "jpg"), token);
          await uploadNewBuffer(folder.id, sname, sv.buf, sv.mime || "image/jpeg", token);
        }
      }
    } catch (e) { /* 元画像は付随物。失敗は無視 */ }
  }

  // ---- プレビュー（任意・R2から取り寄せ・小さい）。★同フォルダに「プレビュー」が既に在れば上げ直さない(role単位の冪等)----
  if (SAVE_JOB_VIDEO_KEY_RE.test(fields.previewKey || "")) {
    try {
      if (!(await findPreviewFile(folder.id, token))) {
        const pv = await fetchR2Bytes(env, fields.r2Base, fields.previewKey, [500, 1500]);
        if (pv && pv.buf && pv.buf.byteLength) {
          const pname = await uniqueFileName(folder.id, baseName + "_プレビュー." + (extOf(pv.mime) || "jpg"), token);
          await uploadNewBuffer(folder.id, pname, pv.buf, pv.mime || "image/jpeg", token);
        }
      }
    } catch (e) { /* プレビューは付随物。失敗は無視 */ }
  }

  // ---- 動画保存が成功した後にだけ旧フォルダをtrash（唯一の破壊操作・全条件を再検証）----
  if (doOverwrite && haveVideo) {
    for (const c of candidates) {
      try { await trashFolderGuarded(c.id, { parentId, baseName, newFolderId: folder.id, noWindow }, token); } catch (e) {}
    }
  }

  // ---- 動画が取れなかった=フォルダの床＋付随画像だけ作った。videoPending=true でフロントの再送に委ねる
  //   (checkSaved は動画の有無で判定するので pending は畳まれず、次回 sweep が動画を載せ直す=自己修復・二重にはならない)。
  if (!haveVideo) {
    try { console.warn(tag + " FOLDER_ONLY folderId=" + folder.id + (reused ? " (reused)" : " (created)")); } catch (_) {}
    return { ok: true, folderId: folder.id, videoPending: true, reused };
  }
  try { console.log(tag + " OK folderId=" + folder.id + (doOverwrite ? " (overwrote " + candidates.length + ")" : reused ? " (reused)" : "")); } catch (_) {}
  return { ok: true, folderId: folder.id, skipped: videoAlready, reused };
}

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

// R2公開GETのURLを組む（純関数・DOM非依存）。sync-worker の /img/<key> と同じ経路。
function r2ObjectUrl(r2Base, key) {
  return String(r2Base || "").replace(/\/$/, "") + "/img/" + String(key || "");
}

// R2から <key> のバイト列を取得→{buf,mime}。取れなければ null。delaysMs の回数だけ指数バックオフで再試行
//   （R2ミラー未着＝アップロード直後のレースに耐える）。
//   ★真因(2026-08-18 実測・wrangler tailで確定): 動画バイトは R2 に確実に在る(外部curlで GET 200 / 8.7MB・
//     ?cbバスター付きでも200)のに、この Worker からの fetch だけが 404 を返し r2_video_missing で静死していた。
//     go5-drive-saver → go5-sync.workers.dev は「同一アカウント workers.dev 間の fetch」で、Cloudflare が
//     外部とは違う経路へ回し sync-worker の R2.get が null を返す既知の落とし穴。キャッシュバスターでも直らない
//     (キャッシュではなくルーティングの問題)。→ ★HTTP を跨がず、sync-worker と同じ R2 バケット
//     (go5-sync-images)を drive-worker へ直バインド(env.SYNC_IMAGES)し in-process で直読みするのが根本解。
//   フォールバック: 直バインドが無い環境(別アカウント運用等)では従来の公開HTTP GET を残す(cf.cacheTtl=0＋?cbバスター)。
async function fetchR2Bytes(env, r2Base, key, delaysMs) {
  const k = String(key || "");
  const delays = Array.isArray(delaysMs) ? delaysMs : [];
  // ── 最優先: 同一アカウントの R2 を直バインドで in-process 読み(HTTP/クロスWorker/エッジキャッシュを一切経由しない) ──
  if (env && env.SYNC_IMAGES && typeof env.SYNC_IMAGES.get === "function" && /^[a-f0-9]{16,64}$/.test(k)) {
    for (let i = 0; i <= delays.length; i++) {
      try {
        const obj = await env.SYNC_IMAGES.get(k);
        if (obj) {
          const buf = await obj.arrayBuffer();
          if (buf && buf.byteLength) {
            const mime = (obj.httpMetadata && obj.httpMetadata.contentType) || "";
            return { buf, mime };
          }
        }
      } catch (e) { try { console.warn("[fetchR2Bytes] r2get throw try=" + i + " msg=" + (e && e.message || e)); } catch (_) {} }
      if (i < delays.length) await sleep(delays[i]);
    }
    try { console.warn("[fetchR2Bytes] r2bind_miss key=" + k.slice(0, 12)); } catch (_) {}
    return null; // 直バインドが権威=バケットに無ければ本当に無い(壊れたHTTP経路へは倒さない)
  }
  // ── フォールバック(直バインド不在時のみ): 公開HTTP GET ──
  const base = r2ObjectUrl(r2Base, key);
  const bust = () => (base.indexOf("?") >= 0 ? "&" : "?") + "cb=" + Date.now() + "-" + Math.random().toString(36).slice(2);
  const noCache = { cf: { cacheTtl: 0, cacheEverything: false } }; // ★Workersは fetch の 'cache' フィールド未実装=throwする。cf指定＋?cbバスターだけで素通す
  for (let i = 0; i <= delays.length; i++) {
    try {
      const r = await fetch(base + bust(), noCache);
      if (r.ok) {
        const buf = await r.arrayBuffer();
        if (buf && buf.byteLength) return { buf, mime: r.headers.get("Content-Type") || "" };
      } else {
        try { console.warn("[fetchR2Bytes] status=" + r.status + " try=" + i + " key=" + String(key).slice(0, 12)); } catch (_) {}
      }
    } catch (e) { try { console.warn("[fetchR2Bytes] throw try=" + i + " msg=" + (e && e.message || e) + " url=" + base.slice(0, 60)); } catch (_) {} }
    if (i < delays.length) await sleep(delays[i]);
  }
  return null;
}

// save_jobの完走確認（read-only）：[題名]フォルダに動画が在れば {saved:true}。作成/削除は一切しない。
async function handleCheckSaved(form, env, cors) {
  const channel = String(form.get("channel") || "").trim();
  const title = String(form.get("title") || "").trim();
  const parentId = channelToFolderId(channel, env);
  if (!parentId) return json({ ok: false, error: "channel_unresolved" }, 400, cors);
  if (!title) return json({ ok: false, error: "missing_title" }, 400, cors);
  let token;
  try { token = await getAccessToken(env); } catch (e) { return json({ ok: false, error: "auth_failed" }, 502, cors); }
  const baseName = safeName(title);
  let ids = [];
  try { ids = await findChildFolderIds(parentId, baseName, token); } catch (e) { ids = []; }
  for (const fid of ids) {
    const v = await findVideoFile(fid, token);
    if (v) return json({ ok: true, saved: true }, 200, cors);
  }
  return json({ ok: true, saved: false }, 200, cors);
}

// 作品フォルダの中身の在り無し（read-only）：[題名]フォルダに 動画/プレビュー/元画像 が在るかを返す。
//   データ再生成の「足りないものだけ補う」判定用。作成・削除・上書きは一切しない＝非破壊。
async function handleFolderState(form, env, cors) {
  const channel = String(form.get("channel") || "").trim();
  const title = String(form.get("title") || "").trim();
  const parentId = channelToFolderId(channel, env);
  if (!parentId) return json({ ok: false, error: "channel_unresolved" }, 400, cors);
  if (!title) return json({ ok: false, error: "missing_title" }, 400, cors);
  let token;
  try { token = await getAccessToken(env); } catch (e) { return json({ ok: false, error: "auth_failed" }, 502, cors); }
  const baseName = safeName(title);
  let ids = [];
  try { ids = await findChildFolderIds(parentId, baseName, token); } catch (e) { return json({ ok: false, error: "list_failed" }, 502, cors); }
  let saved = false, hasPreview = false, hasSrc = false;
  for (const fid of ids) {
    if (!saved && await findVideoFile(fid, token)) saved = true;
    if (!hasPreview && await findPreviewFile(fid, token)) hasPreview = true;
    if (!hasSrc && await findSrcImageFile(fid, token)) hasSrc = true;
    if (saved && hasPreview && hasSrc) break;
  }
  return json({ ok: true, saved, hasPreview, hasSrc }, 200, cors);
}

// 作品フォルダの直リンク解決（read-only）：[チャンネル]/[題名] の実フォルダIDと webViewLink を返す。
//   複数の同名候補（連番等は別名なので基本1件）があれば「作成が新しい」ものを優先＝直近の投稿先に合わせる。
//   作成・削除・上書きは一切しない＝アップロードのレート制限とは別枠。見つからなければ {found:false}。
async function handleFolderLink(form, env, cors) {
  const channel = String(form.get("channel") || "").trim();
  const title = String(form.get("title") || "").trim();
  const parentId = channelToFolderId(channel, env);
  if (!parentId) return json({ ok: false, error: "channel_unresolved" }, 400, cors);
  if (!title) return json({ ok: false, error: "missing_title" }, 400, cors);
  let token;
  try { token = await getAccessToken(env); } catch (e) { return json({ ok: false, error: "auth_failed" }, 502, cors); }
  const baseName = safeName(title);
  const q = "name='" + escQ(baseName) + "' and '" + parentId +
    "' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) +
    "&fields=files(id,webViewLink,createdTime)&orderBy=createdTime desc&pageSize=5&supportsAllDrives=true&includeItemsFromAllDrives=true";
  let f = null;
  try {
    const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
    if (r.ok) { const j = await r.json(); f = (j.files || [])[0] || null; }
  } catch (e) { f = null; }
  if (!f || !f.id) return json({ ok: true, found: false }, 200, cors);
  return json({ ok: true, found: true, folderId: f.id, link: f.webViewLink || ("https://drive.google.com/drive/folders/" + f.id) }, 200, cors);
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

// フォルダ内で「元画像」を名前に含む画像ファイルを1件返す（無ければ null）。データ再生成が
//   「Driveに元画像が既に在るか」を判定するのに使う（在れば重複アップロードしない）。命名規則＝
//   アップロード時の "題名_元画像(_2,_3…).*"（driveUpload_/handleSaveJob と一致）。
async function findSrcImageFile(folderId, token) {
  const q = "'" + folderId + "' in parents and name contains '元画像' and mimeType contains 'image/' and trashed=false";
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
async function findOverwriteCandidates(parentId, name, token, noWindow) {
  const q = "name='" + escQ(name) + "' and '" + parentId +
    "' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false";
  const url = DRIVE_API + "?q=" + encodeURIComponent(q) +
    "&fields=files(id,name,createdTime)&pageSize=20&supportsAllDrives=true&includeItemsFromAllDrives=true";
  const r = await fetch(url, { headers: { Authorization: "Bearer " + token } });
  if (!r.ok) throw new Error("list");
  const j = await r.json();
  const now = Date.now();
  // noWindow=true(正常化の明示intentのみ)は30日窓を外す。それ以外は従来どおり createdTime が30日以内のものだけ。
  return (j.files || []).filter((f) =>
    noWindow ? true : (f.createdTime && (now - Date.parse(f.createdTime)) <= OVERWRITE_WINDOW_MS));
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

// [親]/[題名]フォルダを「既存なら再利用、無ければ1つだけ作成」する共通境界。
// 重要: list失敗を「存在しない」と読み替えない。確認不能時は作成せず失敗へ倒し、次回再送で回復する。
// opsは実行テスト用の注入口。実運用ではDrive API本体を使う。
async function getOrCreateExactFolder(parentId, baseName, token, ops) {
  ops = ops || {};
  const listFn = ops.list || findChildFolderIds;
  const createFn = ops.create || createChildFolderExact;
  const lockKey = String(parentId) + "\n" + String(baseName);
  const active = EXACT_FOLDER_INFLIGHT.get(lockKey);
  if (active) {
    const shared = await active;
    return { folder: shared.folder, reused: true, created: false, shared: true };
  }

  const work = (async () => {
    let ids;
    try { ids = await listFn(parentId, baseName, token); }
    catch (e) {
      const err = new Error("folder_lookup_failed");
      err.cause = e;
      throw err;
    }
    if (ids && ids.length) return { folder: { id: ids[0] }, reused: true, created: false };
    const folder = await createFn(parentId, baseName, token);
    if (!folder || !folder.id) throw new Error("folder_create_failed");
    return { folder, reused: false, created: true };
  })();

  EXACT_FOLDER_INFLIGHT.set(lockKey, work);
  try { return await work; }
  finally {
    if (EXACT_FOLDER_INFLIGHT.get(lockKey) === work) EXACT_FOLDER_INFLIGHT.delete(lockKey);
  }
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
  // 窓内(作成30日以内)。★正常化の明示intent(ctx.noWindow)の時だけこの窓を外す。他の全ガード(フォルダ限定・
  //   未trash・親直下・題名一致)は外さない=誤爆の面積は「同題名の古いフォルダ」に限定されたまま。復元は30日可(trashのみ)。
  if (!ctx.noWindow && (!m.createdTime || (Date.now() - Date.parse(m.createdTime)) > OVERWRITE_WINDOW_MS)) return false;
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
  const buf = await fileObj.arrayBuffer();
  return await uploadNewBuffer(parentId, name, buf, fileObj.type || "application/octet-stream", token);
}

// uploadNew のバイト列直接版（save_job用：R2から取得済みのArrayBufferをFileObjへ包み直さずそのまま上げる）。
//   行う操作は uploadNew と同じ2種（resumable create → PUT）のみ＝破壊面の不変条件は変わらない。
async function uploadNewBuffer(parentId, name, buf, mime, token) {
  const meta = { name, parents: [parentId] };
  const start = await fetch(DRIVE_UPLOAD + "?uploadType=resumable&fields=id,name,webViewLink&supportsAllDrives=true", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json; charset=UTF-8" },
    body: JSON.stringify(meta),
  });
  if (!start.ok) throw new Error("upload_init");
  const session = start.headers.get("Location");
  if (!session) throw new Error("no_session");
  const put = await fetch(session, {
    method: "PUT",
    headers: { "Content-Type": mime || "application/octet-stream" },
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

/* ====================== テスト用（named export・default外の副次公開。Worker実行には影響なし）======================
 * tests/test_drive_savejob.js が save_job の「判定と分岐」を実行で検証するための純関数エクスポート。
 * fetch/Drive API等の「外へ出る手」は含まない（それらは runSaveJob 内でのみ呼ぶ）。 */
export {
  getOrCreateExactFolder,
  validateSaveJobInput,
  r2ObjectUrl,
  safeName,
  channelToFolderId,
  fetchR2Bytes,
  SAVE_JOB_VIDEO_KEY_RE,
  SAVE_JOB_R2_BASE_RE,
  SAVE_JOB_RETRY_DELAYS_MS,
  DRIVE_JOB_LEASE_MS,
  DRIVE_JOB_COOLDOWN_MS,
  driveJobLeaseKey,
  acquireDriveJobLease,
  holdDriveJobLease,
  releaseDriveJobLease,
};
