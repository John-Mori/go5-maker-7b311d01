# 改善提案 — 割引文/準新作・ドラフト遷移・画像表示の再発5件(2026-08-16)

改善提案部門(トトリ/アスナ)が、Chami報告5件(msg=1538552936399900693)をFable5で根本まで思考し、実コードで裏取りした「真因＋再発防止の型＋実装方針」の提案。**実装は改修部門α(Opus以下)**。ここは提案と型づくりまで。

Chamiが既に生の不具合リスト①〜⑤を改修αへ投函済み。本書はそれに**「なぜ何度も再発するか(⑥)」の答えと、人が気をつける以外で止める機構**を足すもの。

---

## 横断の芯(⑥への答え・1つに絞る)

**5件中4件の再発原因は「状態の権威の複数化」**。症状が出るたび、分裂した権威の"1つだけ"を直すから、別の経路から同じ症状が蘇る。

| 件 | 権威が何個に割れているか |
|---|---|
| ① 準新作チェック | DOMのchecked / `field_movieJunshinsaku`(persist) / 自動適用ガード`movie_auto_ws_cid` の**3つ** |
| ③ 割引文の状態語 | 割引行と定価行で**別実装の2つ** |
| ④ ドラフト遷移/DL | 動画blobが メモリ/IDB/R2 の**3所在**(遷移が調停前に発火) |
| ⑤ 画像表示 | 画像が IDB/メモリ/LS退避/R2 の**4所在** |

このリポジトリには既に成功した対抗パターンがある——`core/movie-attrs-core.js`(AI判定を4箇所→1本に束ねた)と `cand_text`(INC-127系のテキスト消失をLS単一マップへ昇格)。**新機能で状態を足すとき「この状態の唯一の正本はどこか」を1行で書かせ、正本以外からのread/writeをCI静的検査で弾く**——これが5件をまとめて再発クラスごと止める型。

---

## ① 準新作チェックが入らない

- **真因(実コード確認済)**: `js/persist-fields.js:23-45` の EXCLUDE に `discountNew2` は在る(29行)が **`movieJunshinsaku` が無い**=汎用永続化が `field_movieJunshinsaku` を保存/復元する。一方 `js/bluesky.js:117-119` の自動チェックONは**直接代入のみでchangeを発火しない**(新作`shin`だけ発火)ので、自動ONは field に保存されない。クリア時(`Go5NewMovieReset`)だけchange発火で"0"が保存される。→ 候補選択→reset(0保存)→FANZAで自動ON(fieldは0)→iOSのタブ再読込→"0"復元でチェックが外れる→cidガードで再適用されず二度と入らない。
- **なぜ再発**: 「新チェックボックス追加→EXCLUDE登録忘れ」が**4回目**(先例=`xTweetText`[30-35行に実録コメント]/`testMode`/カテゴリチェック[58行・2026-08-11])。EXCLUDEは**登録漏れが既定で「保存する」に倒れるdenylist**。
- **再発防止の型**: 「作品ごとに導出する派生値チェックボックスはpersist禁止」を**属性で機構化**。58行の `dataset.catKey` 除外と同方式で、`data-derived="1"` を持つinputを `persistable()` で一律除外→id列挙への足し忘れをクラスごと消す。CI門(新規混入だけ弾く)=**`check_persist_derived.mjs`**(既存 check_*.mjs 系[smoke.yml稼働中]と同型)で「派生チェックボックスはEXCLUDEか`data-derived`のどちらかでカバー」を静的検査。既存回帰ゼロ。
- **実装方針(Sonnet可)**: (a)index.html:329-331 の3チェックボックスに `data-derived="1"` 付与 (b)persist-fields `persistable()` に `if(el.dataset&&el.dataset.derived)return false;` を追加＋`cleanupExcludedLeftovers_`同型で `field_movieJunshinsaku`/`field_discountDigest2` を一度きり掃除 (c)bluesky.js:118 の `jun.checked=…` の後に `jun.dispatchEvent(new Event('change',{bubbles:true}))`(新作と対称に)。

## ② 表示順を 新作→準新作→総集編 に

- **真因(確認済)**: index.html:329-331 のDOM順が 新作(discountNew2)→総集編(discountDigest2)→準新作(movieJunshinsaku)。準新作が後付け(id命名も異質=末尾追記の痕跡)。
- **型**: Nodeテスト(`tests/test_button_width.js`同様にindex.htmlを文字列検査)で「discountNew2 → movieJunshinsaku → discountDigest2 の出現順」を固定。
- **実装方針(Sonnet可)**: 330と331の`<label>`行を入れ替え、332行のhint文言の語順も合わせる。`node scripts/bump.mjs`で一括バンプ。

## ③ 割引文に「準新作」ワードを入れる

- **真因**: `js/bluesky.js:558-563` `discSuffix_(isNew,isDigest)` が**二値ブールで準新作の概念を持たない**。準新作チェックは定価ステータス行(636行・acc2限定)にしか流れず、割引行のbuild/resplice経路へ一切渡らない。611行の剥がし正規表現も準新作を知らない。
- **なぜ再発**: 状態語(新作/準新作/旧作)が**割引行と定価行で別実装**。2026-08-04→08-05×複数と、同じ「状態語を本文へ反映」要求が経路ごとに個別実装され、割引行×準新作の組だけ空白のまま残った。
- **型**: **状態語の決定を1関数に一本化**(movie-attrs-core.js冒頭が説く「判定の唯一の正本」方式)。`bodyStateWord_()`(新作→'新作'/準新作→'準新作'/なし→'')を唯一の口にし、割引行build・resplice・定価行の3経路が全てこれを読む。純粋関数 `respliceDiscLine_` は `window.__go5RespliceDiscLine` で試験可=Nodeテストで「50%+準新作→『…50%オフの準新作&おトク作品…』」「準新作+総集編→『…準新作&総集編…』」を固定。
- **実装方針(Opus/Fable案件・bluesky.js内で完結)**: `discSuffix_` をword受け取りへ、呼び元4箇所(build acc1/acc2・resplice・discApply)差し替え、剥がし正規表現を `/^の(?:準?新作(?:&総集編)?|総集編)/` へ拡張、`movieJunshinsaku`のchangeリスナを割引行再適用へ拡張、Nodeテスト追加。既存文面(新作/総集編)はword='新作'経路で完全互換=回帰ゼロ。

## ④ ドラフト作成に遷移しない(acc2)/DLできない(acc1)

- **真因(アカウント分岐は無い=change_log 2026-08-13。端末×タイミング相関)**:
  - **遷移しない**: `js/stock.js:2145-2161` `decideNav_` は `localLanded||cloudLanded` の時だけ `goDraft_`。雲着地は `Go5Sync.configured()`偽だと `ensureVideoMirror_`即resolveで常にfail。iOSのIDB間欠死×sync未設定/低速回線で両レグ死→25秒後にholdバナー=遷移しない(設計どおり「黙って全滅させない」だが、Chami視点では「行かない」)。
  - **DLできない**: 作成が遅い→最初に着地した1レグ(通常ローカル)だけで即`location.href`遷移し、進行中のR2 PUT(第二レグ)がページ破棄で殺される→Stock.htmlでiOSのプロセス単位IDB死→手元にもR2にも動画が無い→alert「動画がまだ雲に届いていません」。
- **なぜ再発**: 同領域を2026-08-13〜16で連続修正。骨格=(a)動画blobの所有権が「遷移で死ぬページメモリ」にある (b)着地検証がiOS IDBという**非決定的資源**の上に立つ (c)`location.href`遷移が**第二レグの完了保証なしに**発火する。沈黙経路を1本ずつ喋らせてきたが骨格は残存。
- **再発防止の型**: 遷移条件を「片レグ着地」→**「雲着地 or 両レグ決着(allSettled)」**へ。ローカルだけ着地なら R2 PUT の settle まで遷移を待つ(上限+10秒。**タイマー期限25秒は据え置き=最悪でも従来と同時刻に遷移する非破壊拡張**)。e2e(`tests/e2e/draft-video-integrity.spec.js`・smoke.yml:149稼働中)へ「local即成功+cloud PUT遅延→遷移がPUT settleまで待つ」「sync未設定+IDB間欠死→holdバナー表示」を追加。既存3ケース回帰ゼロ。
- **実装方針(Opus/Fable案件=非同期順序)**: stock.js:2149-2161 のgateに `cloudSettled` を足し、navigate条件を `cloudLanded||(localLanded&&cloudSettled)||(localLanded&&timerFired)` へ。

## ⑤ 投稿履歴・候補ページで画像が表示されない

- **真因**: 画像読み出しが「同期read(メモリ`_imgMem`)+非同期ハイドレート」構造(candidates.js:673-719)。投稿履歴は `yt-clicks.js` が `Go5Cand.usedImgs()` を同期で読むが、実体はIDBから非同期展開までは空。iOS Safariのプロセス単位IDB死(candidates.js:1257-1263に実録コメント「リロードでは直らない・閉じて開き直すと直る」)では展開自体が失敗し続け、LS退避読み・R2マーカーの3層フォールバックを重ねてもなお表示は確率的。
- **なぜ再発**: 画像表示系の修正が多数積まれている。骨格=**読み出しの権威が4つ(IDB/メモリ/LS退避/R2)に分散**し寿命・失敗モードが違う。テキストは INC-127→129→132 の恒久対策で `cand_text`(LS単一マップ・同期read)へ昇格済だが、**画像は容量的にLSへ行けずIDB依存のまま**=テキストで潰した「ハイドレート前の空描画」構造が画像にだけ残存。
- **再発防止の型**: **一覧の先頭1枚だけ縮小サムネを同期化**。ドラフトメタが既にやる方式(stock.js:585-591 `thumbDataUrl`=90px・160KB上限でメタ同梱)を、投稿履歴の使用画像1枚目・候補カード1枚目にも適用——先頭1枚の縮小dataURLを `cand_text` 同型の `cand_thumb` 単一マップ(1件2-4KB)へ持つ。IDBが死んでいても一覧は必ず埋まる。フル画像(ズーム)は従来のIDB/R2経路のまま=回帰ゼロ。e2e=「IDB getを全rejectに差し替えても候補/StockListsの先頭サムネが出る」を追加。
- **実装方針(Opus/Fable案件=データモデル)**: candidates.js `usedImgSave_`/`refImgSave` の書込時に先頭画像をcanvas縮小して `cand_thumb[key]` へwrite-through。読み側は空を返す時のみ `cand_thumb` を返す(非破壊の追加読み)。`core/storage-keys.js` に新キー分類登録を忘れない(CLAUDE.md §2)。

---

## 発注区分(Opus以下で実装・Chami指示⑥)

- **Sonnet可**: ①(属性化＋掃除＋change発火) ②(行入れ替え)
- **Opus/Fable案件(状態一本化・非同期・データモデル)**: ③(状態語の唯一化) ④(遷移の非同期決着) ⑤(サムネ同期化)

各件、**再発防止の型(CI/e2e/Nodeテスト)を実装と同じPRに載せる**こと=これが無いと「直した」が次の追加で蘇る。
