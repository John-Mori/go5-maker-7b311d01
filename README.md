# 5秒動画メーカー（スマホ単体版）

iPhone（やAndroid）の**ブラウザだけ**で、写真とテキストから5秒・縦型(9:16)の動画を作るツールです。
**PCもサーバーも不要**。合成は端末内で行われ、写真や動画はどこにもアップロードされません。

このフォルダ（`スマホ用/`）の中身を**そのままGitHub Pagesに公開**するだけで使えます。

---

## A. iPhoneでの使い方（公開後）

1. Safariで公開URLを開く（ホーム画面に追加しておくとアプリのように使えます）。
2. **「📷 写真を選ぶ / 撮る」** をタップ → フォトライブラリかカメラから画像を選ぶ。
3. **作者名 / 誘導文 / コメント** を入力（コメントが動画のファイル名にもなります）。
4. プレビューで仕上がりを確認（入力後、別の欄をタップすると更新）。
5. **「▶ 動画を作成」** をタップ → 約5秒で完成。
6. **「⬇ 保存 / 共有」** → 共有シートから「ビデオを保存」で写真アプリへ。
   （うまくいかない時は、出てきた動画を**長押し →「ビデオを保存」**）

> 対応：iOS 15 以降の Safari 推奨。

---

## B. 公開方法（GitHub Pages・無料）

### いちばん簡単（Web画面だけ・gitコマンド不要）

1. GitHub にログイン → 右上「＋」→ **New repository**。
   - Repository name：**推測されにくい名前**にする（例：`go5-maker-7x9k`）。リンクを知る人だけが使えるようにするため。
   - **Public** を選ぶ（無料アカウントのPagesは公開リポジトリが必要）。「Create repository」。
2. リポジトリ画面の **「uploading an existing file」** をクリック。
3. この `スマホ用/` フォルダの中身（`index.html` / `app.js` / `style.css` / `assets/` フォルダ）を
   **まとめてドラッグ&ドロップ**してアップロード →「Commit changes」。
   - ※ フォルダ構造を保つため、`assets` フォルダごとドロップしてください。
4. 上タブ **Settings → Pages** →「Build and deployment」の Source を **Deploy from a branch**、
   Branch を **main / (root)** にして Save。
5. 1〜2分待つと、同ページに **公開URL**（`https://ユーザー名.github.io/リポジトリ名/`）が表示されます。
   そのURLをiPhoneで開けば完成。

### git に慣れている場合

```bash
cd スマホ用
git init && git add . && git commit -m "5秒動画メーカー スマホ版"
git branch -M main
git remote add origin https://github.com/<ユーザー名>/<リポジトリ名>.git
git push -u origin main
# あとは Settings → Pages で main/(root) を有効化
```

---

## C. ファイル構成

| ファイル | 役割 |
|---|---|
| `index.html` | 画面 |
| `app.js` | 合成（Canvas）＋録画（MediaRecorder）＋保存 |
| `style.css` | スマホ向けスタイル |
| `assets/bg_main.mp4` | 背景動画（Web軽量版・720×1280） |
| `設計書_スマホ版.md` | 設計書 |

---

## D. カスタマイズ

- **背景を差し替える**：`assets/bg_main.mp4` を別の9:16動画に置き換え（Web用に軽くするのが◎）。
- **仕上がり調整**：`app.js` 冒頭の定数（`REVEAL_START` / `FG_MAX_RATIO` / `FG_CENTER_Y` など）を変更。
  デスクトップ版（`composite.py` / `config/jobs.json`）と同じ値にしてあります。

---

## E. 注意

- 端末・ブラウザによっては出力が **webm** になることがあります（iOS Safari は mp4）。
- 前景画像の内容判定はしません。**権利的に使用可・未成年の性的描写を含まない・配信先規約に適合**する素材をご用意ください。
