# 既知の問題 (system-engineer)
> 運用: 結論先頭・1項目=数行・新しい項目を上へ。この部門だけが更新する(他部門はinsight経由で提案)。

## INC 2026-07-15 宵桜艶帖の投稿履歴消失+削除候補の復活+サムネ空白(調査完了/実装保留)
依頼=改修-依頼 2026-07-14 16:28(msg 1526626514249056297・main箱→processed回収済)。3症状に分離。横断改修のため実装は司令塔調整+Chami承認待ち。無断でsync-coreに触らない。

- **①消した候補が復活【確定・コード確認済】**: 候補削除(`candidates.js` の `data-delcid` ハンドラ 約2169行)が `filter(x.cid !== c)` のみ=トゥームストーン無し。`core/sync.js` の `unionCand`(173-190行)が cand_items を cid union+新しい方採用で「集めた候補を失わない」設計のため、他端末に残る削除前の候補が再union で必ず復活する。削除が同期で伝播しない機序。
- **②サムネ/画像が空白【確定・①随伴】**: 復活候補はR2に画像実体が無い→`core/sync.js` `downloadImagesIn`(114-123行)が fetch 失敗/非data: 時に `""` を返す(119・121行)ため空表示になる。①を直せば大半消えるが、取得失敗の握り潰しも独立の穴。
- **③acc2(宵桜)履歴消失【別系統・未確定】**: `short_hist__`/`verify_manual__` は `core/storage-keys.js` の同期許可リスト `syncAllowed` に無い=クラウド同期対象外。よってsync経由では消えない。犯人候補はサニタイザ(`yt-clicks.js` `sanitizeOwnership_`/`ownerOf_` 1838-1895行)or 復元処理。静的解析だけでは断定不可=現地データ必須。
- **③断定に必要な捕獲(Chamiに依頼済・未回収)**: 次に消えた時、復旧前にPC F12コンソールで採取→
  `JSON.stringify({acc2hist:(JSON.parse(localStorage.short_hist__acc2||'[]')).length, acc2man:(JSON.parse(localStorage.verify_manual__acc2||'[]')).length, moves:localStorage.sanitize_move_log, h1:localStorage.bsky_handle__acc1, h2:localStorage.bsky_handle__acc2, d1:localStorage.bsky_did__acc1, d2:localStorage.bsky_did__acc2})`
- **修正案(承認後・?v=一括バンプ→commit→push)**: ①候補削除にトゥームストーン(`cand_del__<tab>`: cid+削除ts)新設→sync union後に削除記録が新しければ除外。「消したものは消えたまま/集めた候補は失わない」を両立。②R2取得失敗を`""`で潰さず旧dataURL保持orリトライ。③捕獲データを見てから(DID台帳の同期経由汚染ならガード追加)。
- **横断範囲**: sync-core × account-model。1オーナー規約で司令塔と所有権調整が前提。
- **関連ファイル**: `core/sync.js`(unionCand/downloadImagesIn) / `core/storage-keys.js`(syncAllowed) / `candidates.js`(候補削除:約2169) / `yt-clicks.js`(サニタイザ:1838-1895) / `bluesky.js`(Go5AccountRepair:1062-1103)
