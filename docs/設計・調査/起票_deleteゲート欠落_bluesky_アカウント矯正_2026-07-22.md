# 起票: delete ゲート欠落 — bluesky.js アカウント矯正経路

- 発見: 2026-07-22 (AD-GL モドリッチ・裁定C の副産物)
- 発見契機: 投稿履歴シート正本化の設計レビュー中に露見
- 現状: **今すぐ壊れていない**。発火条件が存在しないため現時点では無害。
- リスク: **発火条件を1つ追加するだけで不可逆事故になる**。起票して可視化する。
- この改修(投稿履歴シート正本化)には**混ぜない**。別件として管理する。

---

## 問題の所在

`bluesky.js` の `repairAccountsByDid_()` (INC-112の修復機構):

```javascript
// bluesky.js:1207 付近
recordToSheet({ account: mv.to, ... });  // 正チャンネルへ再upsert
if (it.postUri) jsonpGet(gasUrl + '?action=delete&channel=' + mv.from + '...', function () {});  // 誤チャンネルの行を削除
```

**delete は再upsertの成否で gate されていない**。`jsonp` の撃ちっぱなしで、コールバックで再upsertの成否を待っていない。

発生シナリオ:
1. `recordToSheet()` が何らかの理由で失敗(GASエラー・ネットワーク切断・バリデーション拒否 等)
2. それに関係なく `jsonpGet(... delete ...)` が即座に発火
3. 誤チャンネルの行が削除される
4. 正チャンネルへの書き戻しは失敗しているため、**行がどこにも存在しない状態になる**

結果: INC-112 を修正するための機構が、データを消す装置に変わる。不可逆。

---

## 現状の危険度

- **現時点**: `recordToSheet()` に失敗する条件が無いため発火しない。
- **危険になるトリガーの例**:
  - `writeRecord_()` の中に必須バリデーションを追加した場合(裁定Cで差し戻した理由の1つ)
  - GASのデプロイ失敗 / バグによる一時的なエラー返却
  - ネットワーク不安定でのリクエスト失敗

---

## 推奨修正(将来の担当者へ)

`recordToSheet()` の成功コールバック内に delete を移動する:

```javascript
recordToSheet({ account: mv.to, ... }, function(result) {
  if (result && result.ok) {
    // 再upsertが成功した時だけ削除する
    if (it.postUri) jsonpGet(gasUrl + '?action=delete&channel=' + mv.from + '...');
  } else {
    console.warn('アカウント矯正: 再upsert失敗のため delete を中止', it.postUri);
  }
});
```

ただし `recordToSheet()` が現状コールバックを受け付ける構造かどうかを確認してから着手すること。

---

## 着手条件

- 投稿履歴シート正本化(本設計書)の実装が完了し安定してから着手推奨
- 優先度: **中**(今すぐ壊れないが、将来の改修で踏む地雷)
- 担当: system-engineer
