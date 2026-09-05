---
name: go5-deploy
description: go5-makerのフロント改修をGitHub Pages(公開URL)へ反映する手順。フロント(index.html/app.js/style.css/js)を変更した後、「反映」「デプロイ」「公開して」「pushして」等で使う。?v=バージョンの一括バンプ→commit→pull --rebase→push→検証の順を必ず守り、並行セッションとの衝突や、スマホで古いJSが読まれる版ずれを防ぐ。GASの反映は対象外(そちらはGASを反映.bat=deploy_gas.mjs)。
---

# フロント反映(GitHub Pages)

## なぜ手順を固定するか
go5-makerは複数セッションが並行でrepoを触る。pushの前に `git pull --rebase` を忘れると、他セッションの未pushコミットと衝突し、作業ツリーが壊れる(過去の事故=INC-99)。また、アセット参照の `?v=N` を上げ忘れると、スマホのキャッシュが古いJS/CSSを読み続け「直したのに直らない」が起きる。この2つを機械的に潰すのがこのSkill。

## 手順(この順を崩さない)

### 1. ?v= を一括バンプ
index.html のアセット参照 `app.js?v=N` 等の N を +1(中身を変えたアセット全て)。現在の版は index.html を見て確認する(CLAUDE.mdの版数表記は目安・正はindex.html)。

### 2. テスト(あれば)
`node tests/test_affiliate.js` 等、触った領域のテストを通す。

### 3. commit
変更したファイルを確認してから add(他セッションの無関係な変更を巻き込まない)。コミットメッセージは「変更内容(Chami承認/依頼の根拠)」。UI文言・メッセージの括弧は半角()。

### 4. push前に必ず pull --rebase
`git pull --rebase`(未コミットがあれば `--autostash`)。並行セッションの衝突を防ぐ。コンフリクトが出たら解消してから続行。

### 5. push
`git push`。1〜2分でGitHub Pagesの公開URLに反映される。

### 6. 検証
公開URL(https://john-mori.github.io/go5-maker-7b311d01/)を preview_start でブラウザに開き、変更が反映されているか・コンソールエラーが無いかを確認。スマホは ?v= が上がっていれば最新が読まれる。

## 出力の型
各ステップの結果を報告。特に「?v= を N→N+1 にした」「pull --rebase 実行(衝突なし)」「push成功」を明示。検証はスクショ or コンソール確認結果を添える。

## 触ってはいけない
- GAS(gas/コード.gs)はこの手順の対象外。GAS反映は GASを反映.bat(node scripts/deploy_gas.mjs)+ GAS_VERSIONバンプ。
- 座標系(基準フレーム W=1080 / H=1920 の比率ベース)を崩さない。px/vh/vw を直接使わない。
