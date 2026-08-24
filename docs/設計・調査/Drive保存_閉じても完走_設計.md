# Drive保存「途中で閉じても裏で完走」恒久設計 (2026-08-16 / オタコン)

> 2026-08-25更新：保存起点は「投稿完了」から、動画作成タブの「ドラフトで作成」押下後に動画実体とドラフト台帳が確定した直後へ移動した。現行は `saveStock_.onCommitted` → `autoDriveSaveDraft_` → `driveSaveDataset_`。非同期処理より先に永続pendingを記録し、投稿完了はDrive保存を起動しない。以下の「投稿完了」記述は2026-08-16時点の障害分析として残す。
Chami依頼 msg_id=1538479072609443931「今日月詠みで投稿した2本(冷やしおみくじ/逮捕できない相手)がGoogleドライブに保存されていない。ボタン一つで保存すべき内容が丸々作成される機能を(途中で閉じても裏で完結)」。追い便 1538480280933900298「何も出てないというか確認していない」= 失敗は無言・原因の切り分けはChamiに求めない。

## 芯(root cause)
今のDrive保存は投稿完了の瞬間に「開いているページの中で」動画を丸ごとアップロードしている
(`js/stock.js` driveSaveDataset_ → `js/drive-upload.js` driveUpload_ → send)。
- スマホ回線で動画アップロードは数秒〜十数秒。その最中にSafariがタブをbg破棄/閉じると fetch が切れて中断。
- 積み直す永続キューが無い=黙って消える。エラーも残らない(Chami「何も出てない」と一致)。
- 二次的に、resolveVideoBlob_ が手元IDBにもR2にも動画を見つけられない瞬間(mirror未着)も「動画データ無し」でスキップ。

## 物理的制約
iOS Safari はタブを完全に閉じた後は JS を1行も実行しない。keepalive/sendBeacon は本体64KB制限で動画に使えない。
→ 「閉じても完走」は**サーバー側でやるしかない**。

## 使える既存の駒(新規Cloudflareリソース不要)
- 動画は作成直後に R2 へ控え済み: `core/sync.js` putBlobR2At、キー = `sha256hex("go5vid:"+ドラフトID)`(`stock.js` VIDNAME)。
  公開GET = `<sync url>/img/<key>`(`fetchBlobR2At` と同じ)。認証不要。
- drive-worker は Drive OAuth(refresh_token)を Secrets に保持済み。`handleFetchVideo` で既に Drive から動画を取れている
  =「外からバイトを取ってDriveへ上げる」形は前例あり。
- drive-worker の破壊面不変条件は維持: create / upload / reference / trash(overwrite二重ロック時のみ)の4種だけ。今回も破壊APIは足さない。

## 設計(実装するもの)
### A. drive-worker/src/index.js — 新アクション `save_job`(サーバー側完走)
1. `fetch(request, env, ctx)` に **ctx** を足す(現状 ctx 未受領)。
2. `action=save_job` を追加。入力(小さいFormData/JSON): `channel, title, videoId, r2Base, videoKey, previewDataUrl?(小), overwrite?`。
   - 元画像は大きいので初版はDrive保存対象から外してよい(複雑化回避)。プレビューは小さいので dataURL 同梱可。
3. 早期に **202 Accepted** を返す(フロントはこれを見て投稿完了UIを止めない)。
4. `ctx.waitUntil((async()=>{ ... })())` の中で:
   - `r2Base + "/img/" + videoKey` を fetch して動画 arrayBuffer を得る(無ければ最大N回リトライ後あきらめ・ログ無害)。
   - 既存の getAccessToken/getFolder/createUniqueChildFolder(または overwrite経路)/uploadNew をそのまま使って
     [題名]フォルダ + 動画(+プレビュー)を新規作成。**既存のフォルダ命名・上書き規約をそのまま踏襲**。
   - 冪等: 二重POST対策に、作成前に「同題名フォルダに動画が既に在れば作らない」チェック(findChildFolderIds+findVideoFile 流用)。
5. `save_job` はアップロード系レート制限の対象に含める(既存 rateLimited を通す)。
6. CORS/secret は既存経路と同じ多層防御。

### B. フロント: 投稿完了で「軽いジョブ」を投げる + 永続リトライ
- `js/drive-upload.js`: `window.Go5Drive.queueSave(videoId, title, channel, previewBlob?, overwrite?)` を追加。
  - videoKey = Go5Sync 側で算出(sha256hexを公開するか、mirror成功時に返る key を stock.js が控えて渡す)。
  - r2Base = Go5Sync.getConfig().url。
  - `fetch(WORKER_URL, {..., keepalive:true})` で save_job を投げる(本体は小さいので keepalive OK=閉じても送信は出る)。
- `js/stock.js` driveSaveDataset_: folderId未保存の通常経路を「重いupload」から「queueSave(軽いジョブ)」へ切替。
  - 動画がR2未着(mirror未完了)の時は、その場で ensureVideoMirror_ を待ってから投げる/または pending に積む。
- 永続ネット: 投稿完了時 `localStorage go5_drive_savejob_<id>` に pending 記録。
  アプリ起動時 sweep で、確認できていない pending を save_job 再送(サーバー側冪等で二重フォルダを作らない)。
  サーバーで動画がDriveに在ると確認できたら pending を消す。

### C. テスト(ソース文字列一致でなく実行で)
- 冪等判定・keyの算出・pending sweep の分岐を純関数へ切り出し Node テスト。
- 外へ出る手(fetch/Drive)だけ偽物、判定と分岐は本物。

## デプロイ/検証
- drive-worker: `wrangler deploy`(C-002 承認不要)。ALLOWED_ORIGIN 等の既存 env はそのまま。
- フロント: `node scripts/bump.mjs` で一括バンプ → commit → pull --rebase → push。
- ★「直った」は言わない。Chami実機でドラフト→投稿完了→**タブを即閉じ**→数十秒後にDriveの[チャンネル]/[題名]に動画が在るのを見て初めて確認(§4.55)。

## 対象REQ
主: msg_id=1538479072609443931(Drive未保存の再発 + ワンボタン完走)。
関連(炎上): DEF/REQ の「保存中のまま」「投稿履歴に載らない」系とも土台を共有。
