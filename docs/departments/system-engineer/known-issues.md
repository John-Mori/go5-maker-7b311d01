# 既知の問題 (system-engineer)
> 運用: 結論先頭・1項目=数行・新しい項目を上へ。この部門だけが更新する(他部門はinsight経由で提案)。

## INC 2026-07-17 候補の画像・コメントが「動画生成へ」で消える(修正済・v=349)
Chami報告(改修α 15:38 msg 1527338759342002288)「候補から動画生成へ進むと登録してた候補用画像とコメントが候補から消える。途中でやめたら作り直せない」。**真因は画像展開(hydrate)との競合**。commit 2a16fce が直したのは別件(IDB書込のfire-and-forget=保存完了待ち)で、この競合は残っていた=Chamiの「多分治ってない」は正しかった。

- **機序**: `candidates.js` の `_imgMem` は空で開始し `_idbOk` は即true。`hydrateImages_`(IDB→メモリ展開)は**非同期**。完了前は `refImgOf()` が「実際はIDBに在るのに null」を返す → モーダルの `pending` が全項目空で生成 → 「動画生成へ/保存」が `refImgSave(cid, 空)` を呼ぶ → `empty` 判定で `rec=null` → **`Go5Idb.del` で画像もコメントも永久削除**。画像が多い/重いほど展開が遅く**間欠的に発火**する(Chamiは実測32MB級)。
- **対策(二段)**: ①`_hydrated` フラグを新設し、未展開のうちは `refImgSave`/`bskyImgSave` の**破壊的な空保存を拒否**(戻り値false)。②`openRefImgModal_` は展開を待ってから開く(`whenImagesReady_`・保険で最大3秒)＝空pendingが生成されない。
- **検証(本番条件で発火させた)**: 32MB/37枚を仕込み、展開を人為的に遅延させて未展開状態を作成 → `refImgs=0`(競合中)でモーダルは**開かず待機**・空保存は**false で拒否**・IDBデータ無傷を確認。展開後は自動で開き画像1+コメント保持、「動画生成へ」後もデータ生存・遷移OK。検証用フックは完全撤去(grep確認)。コンソールエラー0・既存テスト全PASS。
- **教訓**: 「読めていない」と「無い」を同一視すると削除事故になる。非同期展開を挟むストアでは**未ロード中の空=削除**を禁じる。

## INC 2026-07-15 宵桜艶帖の投稿履歴消失+削除候補の復活+サムネ空白(①②修正済デプロイ/③データ待ち)
依頼=改修-依頼 2026-07-14 16:28(msg 1526626514249056297・main箱→processed回収済)。3症状に分離。Chamiから承認不要・進行指示(2026-07-15)。①②は commit 00447af / v=333 でデプロイ済。③は捕獲データ待ちで未着手。

- **①消した候補が復活【修正済・v=333】**: 候補削除(`candidates.js` の `data-delcid` ハンドラ)が `filter(x.cid !== c)` のみ=トゥームストーン無し。`core/sync.js` の `unionCand` が cand_items を cid union+新しい方採用で「集めた候補を失わない」設計のため、他端末に残る削除前の候補が再union で必ず復活していた。→**対策**: 削除時に `cand_del__<tab>`(cid+削除ts)を記録(同期対象・cid単位union=片側削除を失わない)。sync の候補union後に `applyTombstone` で「削除ts>=addedAt」のcidを除外。**再収集は addedAt が新しいので自動復活**=「消したものは消えたまま/集めた候補は失わない」を両立。consumerは無改変(union出力を掃除するだけ)。テスト=`tests/test_sync_tombstone.js` 15項目。
- **②サムネ/画像が空白【修正済・v=333】**: 復活候補はR2に画像実体が無い→`core/sync.js` `downloadImagesIn` が fetch 失敗/非data: 時に `""` を返し空表示になっていた。→**対策**: 取得失敗数を返すようにし、既存IDB値がある時は空で上書きしない(初回のみ部分書込)。①解消で発生源も大幅減。
- **③acc2(宵桜)履歴消失【別系統・未確定】**: `short_hist__`/`verify_manual__` は `core/storage-keys.js` の同期許可リスト `syncAllowed` に無い=クラウド同期対象外。よってsync経由では消えない。犯人候補はサニタイザ(`yt-clicks.js` `sanitizeOwnership_`/`ownerOf_` 1838-1895行)or 復元処理。静的解析だけでは断定不可=現地データ必須。
- **③断定に必要な捕獲(Chamiに依頼済・未回収)**: 次に消えた時、復旧前にPC F12コンソールで採取→
  `JSON.stringify({acc2hist:(JSON.parse(localStorage.short_hist__acc2||'[]')).length, acc2man:(JSON.parse(localStorage.verify_manual__acc2||'[]')).length, moves:localStorage.sanitize_move_log, h1:localStorage.bsky_handle__acc1, h2:localStorage.bsky_handle__acc2, d1:localStorage.bsky_did__acc1, d2:localStorage.bsky_did__acc2})`
- **修正案(承認後・?v=一括バンプ→commit→push)**: ①候補削除にトゥームストーン(`cand_del__<tab>`: cid+削除ts)新設→sync union後に削除記録が新しければ除外。「消したものは消えたまま/集めた候補は失わない」を両立。②R2取得失敗を`""`で潰さず旧dataURL保持orリトライ。③捕獲データを見てから(DID台帳の同期経由汚染ならガード追加)。
- **横断範囲**: sync-core × account-model。1オーナー規約で研究室と所有権調整が前提。
- **関連ファイル**: `core/sync.js`(unionCand/downloadImagesIn) / `core/storage-keys.js`(syncAllowed) / `candidates.js`(候補削除:約2169) / `yt-clicks.js`(サニタイザ:1838-1895) / `bluesky.js`(Go5AccountRepair:1062-1103)
