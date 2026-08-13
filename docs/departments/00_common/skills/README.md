# skills 置き場(`.claude/skills/` へ入れる前の正本)

2026-08-13 イージス研究室。Chamiの Go(ESC-kaizen-analyst-1537342206371954689)で作成。
根拠と数え方= `docs/設計・調査/改修ログ共通項分析_skill化候補.md`。

## なぜここに在るのか(★重要)
Claude Code の権限で **`.claude/skills/` への書き込みが通らなかった**(Write も Edit も
`haven't granted it yet` で弾かれる。Discord経由の承認は装置に通らないため、誰も許可を押せない)。
**Bashのヒアドキュメントで迂回はしない**(権限の意味が無くなる)ので、
中身はここへ置き、許可が下りた時に**そのままコピーするだけ**にしてある。

## 入れ方(許可が下りたら1回だけ)
```bash
cp -r docs/departments/00_common/skills/ledger-append          .claude/skills/
cp -r docs/departments/00_common/skills/daemon-reload-check    .claude/skills/
cp -r docs/departments/00_common/skills/test-must-fail         .claude/skills/
cp -r docs/departments/00_common/skills/failopen-guard         .claude/skills/
cp -r docs/departments/00_common/skills/single-source-predicate .claude/skills/
```
入った後の確認= セッションの skill 一覧に5本の名前が出ること(**出るまでは「入れた」であって「効いた」ではない**)。
★許可の恒久化は `.claude/settings.local.json` の `permissions.allow` へ
`"Write(./.claude/skills/**)"` と `"Edit(./.claude/skills/**)"` を足す(この編集自体も許可が要る)。

## 中身(5本・番号は分析書の候補番号)
1. `ledger-append` 《記録》 台帳JSONLの追記とclose。根拠85件+実害2件。
2. `daemon-reload-check` 《載せ替え》 常駐が読むものを足した時のC-042経路。根拠43件。
3. `test-must-fail` 《検査》 足した検査が**落ちること**を1回見る。根拠61件。
4. `failopen-guard` 《無言死》 端末側の非同期は黙って止まらない側へ倒す。根拠32件。
5. `single-source-predicate` 《一本化》 同じ判定式を複数経路が各自持たない。根拠14件。

候補6(《同期》sync-both-sides・67件)は**skillにしない**。案件ごとに中身が違い手順が固定できない=
設計書向き、と判定した(分析書§3)。
