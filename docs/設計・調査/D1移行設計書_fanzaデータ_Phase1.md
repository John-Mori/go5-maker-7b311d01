# D1移行設計書 — fanza高頻度データ (KV→D1) Phase 1

作成: 2026-07-11 ／ 対象: `fanza-worker` (go5-fanza-proxy)
ステータス: **設計・未着手**。この文書は実装・DB作成・デプロイの前段。承認後にPhase 1-Aから着手。
関連: [[マルチエージェント部門制_移行設計書_v1]] §G(agent event-bus用D1は別DB) / インシデント2026-07-09(KV上限クラッシュ)

> 目的: KV書き込み**1,000/日**の天井を、D1**10万行/日**(=100倍)へ移すことで「制限がすぐ来る」問題を構造的に解消する。
> 今回のdedup最適化(2026-07-11・Version dbde0e7f)は消費を抑えるが天井は残る。D1移行が恒久解。

---

## 0. なぜD1か (KVとの比較・無料枠)

| | KV (現行) | D1 (移行先) |
|---|---|---|
| 書き込み無料枠 | **1,000/日** ← 天井が低い | **100,000行/日** (書き込み) |
| 読み取り無料枠 | 100,000/日 | 500万行/日 |
| ストレージ | 1GB | 5GB |
| 課金単位 | キー単位のput/delete | 行単位のread/write |
| 向き | 単純KV・エッジキャッシュ | リレーショナル・集計クエリ可 |
| dedup工夫 | **必須**(枠が低いため read-before-write を全経路に実装) | ほぼ不要(枠が100倍) |

FANZAデータは「cid別の構造化データ+集計(サークル別・販売数順)」なのでリレーショナルが自然。
D1移行後は現在の read-before-write dedup を維持しつつも、枠に余裕ができ上限クラッシュのリスクが消える。

**要確認(未確定)**: D1無料枠の同時DB数上限・行課金の正確な定義(UPSERTの行カウント)は移行着手時にCloudflare公式で再確認する(§7)。

---

## 1. 移行対象データ (現行KVキー → D1テーブル)

現行fanza-workerのKVキー体系(2026-07-11時点):

| KVキー | 中身 | 書き手 | 読み手 | 移行先テーブル |
|---|---|---|---|---|
| `ov:<cid>` | PCスクレイプのフル情報(title/価格/画像) | PCバッチ | /api/fanza-item | `works` |
| `sales:<cid>` | 実売本数 | PCバッチ | /api/fanza-sales | `works.sales_n` |
| `req:<cid>` | 情報取得依頼キュー(+Books用url) | フロント/worker | /api/fanza-queue(PC) | `fetch_queue(kind='info')` |
| `salesreq:<cid>` | 販売数取得依頼キュー | フロント | queue(PC) | `fetch_queue(kind='sales')` |
| `salestrack:<makerId>` | 追跡サークル登録 | フロント | queue(PC) | `tracked_makers` |
| `salesrun:req` | 「今すぐ取得」要求フラグ(単一) | フロント | PC --poll | `run_flags` |

ポイント: `ov:` と `sales:` は**どちらもcid単位**なので、D1では1つの `works` 行に統合できる(cid=主キー)。
現在は別キー=別書き込みだが、D1では1行のUPSERTで両方更新でき、書き込み効率も上がる。

## 2. D1スキーマ (fanza専用DB・仮称 `go5_fanza`)

```sql
-- 作品ごとのFANZA情報(ov:とsales:を統合)
CREATE TABLE works (
  cid         TEXT PRIMARY KEY,
  title       TEXT,
  info_json   TEXT,           -- sanitizeOverride() 済みオブジェクトのJSON文字列(prices/images等)
  sales_n     INTEGER,        -- 実売本数(未取得はNULL)
  scraped_at  TEXT,           -- info(ov:)のスクレイプ時刻 ISO8601
  sales_at    TEXT,           -- 販売数のスクレイプ時刻
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- PC取得依頼キュー(req: と salesreq: を kind で統合)
CREATE TABLE fetch_queue (
  cid          TEXT NOT NULL,
  kind         TEXT NOT NULL,   -- 'info' | 'sales'
  src_url      TEXT,            -- Books等のスクレイプ先URL(kind='info'用)
  requested_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at   TEXT,            -- TTL相当(過ぎたら掃除)。info=7日 sales=14日 を踏襲
  PRIMARY KEY (cid, kind)
);
CREATE INDEX idx_queue_kind ON fetch_queue(kind, expires_at);

-- 追跡サークル
CREATE TABLE tracked_makers (
  maker_id  TEXT PRIMARY KEY,
  name      TEXT,
  added_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 単発フラグ(salesrun:req 等)。将来の他フラグも1行=1keyで持てる
CREATE TABLE run_flags (
  key          TEXT PRIMARY KEY,   -- 'sales_run'
  requested_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at   TEXT
);
```

TTLの扱い: KVは `expirationTtl` で自動失効するが、D1に自動失効はない。
→ `expires_at` 列を持たせ、(a)読み取り時に `WHERE expires_at > now` で除外、(b)PC --poll実行時など低頻度に `DELETE WHERE expires_at < now` で掃除(cron trigger でも可)。

## 3. worker側の変更方針 (API仕様は不変)

★最重要: **フロントエンドは一切変更しない**。`/api/fanza-item` `/api/fanza-sales` `/api/fanza-override` `/api/fanza-sales-save` `/api/fanza-queue` 等のリクエスト/レスポンス形は現状のまま。worker内部の保存先だけ KV→D1 に差し替える。

主なマッピング:

| 現行(KV) | 移行後(D1) |
|---|---|
| `env.FANZA_KV.get("ov:"+cid,"json")` | `SELECT info_json,... FROM works WHERE cid=?` |
| `env.FANZA_KV.put("ov:"+cid, newStr)` | `INSERT INTO works(...) VALUES(...) ON CONFLICT(cid) DO UPDATE SET ...` |
| `env.FANZA_KV.get("sales:"+cid,"json")` | `SELECT sales_n FROM works WHERE cid=?` |
| `env.FANZA_KV.put("sales:"+cid,...)` | `UPDATE works SET sales_n=?, sales_at=? WHERE cid=?` (無ければINSERT) |
| `listAll(KV,"req:")` | `SELECT cid,src_url FROM fetch_queue WHERE kind='info' AND expires_at>now` |
| `put("salesreq:"+cid)` | `INSERT ... ON CONFLICT DO NOTHING`(24h dedupはrequested_at比較) |
| `put("salestrack:"+id)` | `INSERT INTO tracked_makers ... ON CONFLICT DO UPDATE` |
| `get/delete("salesrun:req")` | `SELECT/DELETE FROM run_flags WHERE key='sales_run'` |

D1バッチ: PCの `/api/fanza-sales-save`(最大200件)・`/api/fanza-override`(最大100件)は
`db.batch([...])` で1トランザクションにまとめられる → 往復も書き込みも効率化。

## 4. 移行手順 (無停止・可逆) — フェーズ分割

### Phase 1-A: 器を作る (影響ゼロ・要承認=D1作成)
1. `wrangler d1 create go5_fanza` でDB作成
2. `wrangler.toml` に `[[d1_databases]]` バインド追加(binding=`FANZA_DB`)
3. スキーマ適用: `wrangler d1 execute go5_fanza --file schema.sql`
   → この時点でworkerコードは未変更=**現行KV運用に影響なし**

### Phase 1-B: 二重書き込み+D1優先読み (要承認=worker deploy)
4. worker改修: 書き込みは **D1へ**(正)、当面KVへも書く(保険)。読み取りは **D1優先→無ければKVフォールバック**
   - フラグ `USE_D1=true` を env に持たせ、問題時に即KV運用へ戻せるようにする(ロールバック弁)
5. デプロイ後、`/api/fanza-item` 等をスモークテスト(D1経路で200・内容一致)

### Phase 1-C: 既存KVデータのバックフィル (影響ゼロ・KV読みは無制限)
6. 一度きりの移送スクリプト `scripts/migrate_kv_to_d1.mjs`:
   - KVの `ov:`/`sales:`/`req:`/`salesreq:`/`salestrack:` を全listして読む(読みは無制限)
   - D1へUPSERT(10万行/日枠なので数千件でも余裕)
   - 冪等(再実行しても同じ結果)。件数照合で完了確認

### Phase 1-D: カットオーバー (要承認=worker deploy)
7. 読み取りをD1のみに(KVフォールバック撤去)。KVへの書き込みを停止
8. 1〜2週間 安定監視(wrangler tailでエラーゼロ確認)

### Phase 1-E: 後片付け
9. KV経路コード削除。KVネームスペースは当面残置(緊急時の証跡)→安定後に破棄検討

## 5. フロント/PC側への影響

| 対象 | 影響 |
|---|---|
| フロント(index.html+JS) | **無変更**。API形不変のため |
| PCスクレイパ(fetch_sales.mjs/fetch_missing_works.mjs) | **無変更**。呼ぶエンドポイントは同じ。移送スクリプトのみ新規追加 |
| 他Worker(sync/link/drive)・GAS | **無変更**。fanzaドメインに閉じる |

データ移行(§4-C)は「純増コピー」でありKV側は破壊しない=可逆。

## 6. リスクと対策

| リスク | 対策 |
|---|---|
| D1の読み取り遅延(KVエッジキャッシュより遅い可能性) | 本用途の頻度なら実用上無視できる想定。Phase1-Bのスモークで実測 |
| 二重書き込み中のKV枠消費 | 二重書き込み期間を短く(1-B→1-Dを数日で)。KV書き込みは既にdedup済みで低い |
| D1スキーマ/クエリのバグでデータ不整合 | USE_D1フラグで即ロールバック。KVデータをカットオーバーまで温存 |
| D1無料枠の正確な上限が想定と違う | §7で着手前に公式確認。万一不足でも本用途(数千行・数千書込/日)は余裕 |
| TTL自動失効が無い→キュー肥大 | expires_at列+定期DELETE(または Cron Trigger) |

## 7. 未確認事項 (着手前に確認)

1. D1無料枠の正確な数値: 同時DB数上限・行書き込みの課金定義(UPSERT/バッチの行カウント)・1クエリの制約
2. Cron Trigger(キュー掃除用)を fanza-worker に足すか、--poll時のDELETEで足りるか
3. agent event-bus用D1([[マルチエージェント部門制_移行設計書_v1]] §G)と**同一DBに相乗り**させるか、別DB(`go5_fanza` と `go5_hub`)で分けるか
   - 推奨: **別DB**(ドメイン分離・障害隔離)。ただし無料枠のDB数上限次第(§7-1)
4. 現行KVの実データ件数(移送量の見積り): 着手時に `wrangler kv key list --binding FANZA_KV --prefix ...` で採取(2026-07-11の採取はwrangler新版の出力形式差で0表示・要再取得)

## 8. 進め方 (承認ゲート) ＋ 進捗

- [x] **Phase 1-A 完了 (2026-07-11)**: D1 `go5_fanza`(APAC/大阪KIX) 作成・schema.sql適用(4テーブル)。database_id=`39c22ab0-e90b-4755-9270-7265b9fed530`
- [x] **Phase 1-B(器) 完了**: wrangler.tomlにD1バインド+`USE_D1`切替弁追加。`/api/d1-backfill`(移送エンドポイント)実装。**USE_D1="off"でデプロイ済(Version 029e02e8)＝現行挙動と完全同一**。既存ハンドラは未変更
- [x] **Phase 1-C(移送) 完了**: KV→D1バックフィル実行。works 282行(info83+sales246をcid統合)・queue info1/sales19・makers2 で**KV実測と完全一致を照合済**
- [x] **Phase 1-B(本体) 完了 (2026-07-11)**: 全8ハンドラをストレージ抽象層(stGetOverride/stPutSales/stQueue*/stMaker*/stFlag*)に載せ替え。読みは`on`時のみD1、書きは`dual`でD1+KV両方(dualはd1run_でD1失敗時もKV安全網へ)。まず`off`で再デプロイしKV経路の無回帰をスモーク確認(Version 45b4bd5c)→`USE_D1="dual"`でデプロイ(Version 5e561849)。クリーンテスト(maker 8888888)でKV+D1両書きを実証・テストデータ掃除済
- [x] **Phase 1-D 完了 (2026-07-11)**: `/api/d1-verify`で全件照合し `clean:true`(ov83/sales246/reqInfo1/reqSales19/makers2 全一致・値サンプル15件不一致0)を確認 → **`USE_D1="on"`でカットオーバー(Version 95fd81a3)**。読み書きともD1のみ・**KV書き込み停止=1,000/日の天井が消滅**。on検証: 全読みD1由来で正常、書き込みテスト(maker 7777777)がD1のみに入りKVには入らないことを実証、テスト掃除済
- [ ] **Phase 1-E(残)**: 安定確認後、KV経路コード(ストレージ層のkvwrite_分岐等)の削除・KVネームスペース破棄を検討。当面はKVデータを証跡として温存(ロールバック弁)

**現状=on 稼働中(移行完了)**。読み書きともD1。WorkerのD1バインドはプライマリ読み=強整合(レプリカラグ無し)。KV書き込みは停止したが**KVデータは温存**しているので、`USE_D1`を`dual`/`off`に戻して再デプロイすれば即ロールバック可能(ただしon中のD1新規書き込みはKVに無いので、戻す場合は再backfillが必要)。
- 注意(既知・無害): デプロイ直後の数十秒はエッジ伝播ラグで一部PoPが旧版のまま処理しうる。バグではない。
- 照合/移送エンドポイント: `/api/d1-verify`(照合・読取のみ)、`/api/d1-backfill`(KV→D1移送・冪等)。いずれも管理鍵。

## 付録: 今回(2026-07-11)実施済みのKV最適化 (D1移行までの延命策)

D1移行の前段として、KV書き込みを全経路dedup化済み(Version dbde0e7f):
- `/api/fanza-item` の `req:` 書き込み(唯一dedup無し=上限消費の主因)に存在チェック追加。Books用url後付けのみ維持
- `stale_override`・`salesrun:req` にもdedup追加 → 全7 PUT経路がdedup済み
これにより明日以降のKV消費は大幅減。D1移行完了までの「すぐ来る」を緩和する。
