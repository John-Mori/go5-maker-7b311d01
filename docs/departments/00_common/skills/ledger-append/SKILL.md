---
name: ledger-append
description: 台帳(JSONL)へ追記する・依頼や不具合をcloseする時の手順。local/llm/change_log.jsonl への改修記録、local/llm/open_defects.jsonl のclose、その他 local/ 配下のJSONL台帳を触る時に使う。「記録しておいて」「change_logに書いて」「closeして」「台帳へ追記」で使う。生JSONの手打ちで行が壊れ、確認済みの依頼が黙って消えた事故(2026-08-12)を機構で止める。
---

# 台帳への追記とclose

## なぜ手順を固定するのか
台帳は**追記専用**で、壊れた行は読み手が**黙って飛ばす**。だから壊れても誰も気づかない。実害2件:
- 2026-08-12: confirm を手打ちしたWindowsパスの `\` でJSONが壊れ、**closeした依頼2件が消えて**全部屋の起動文に未完了として出続けた(REQ-future-room-0a19d32276 / REQ-future-room-4bedba52c7)。
- 2026-07-17: `ts='t'` の接続テスト残骸が入り、文字列比較で `'t' > '2'` となって**テスト残骸が最新の発言として知識パックを占領**した。

結論=**生JSONを手で書かない。書き手の入口で弾く。**

## 追記の手順(change_log.jsonl 等)
`scripts/lib/jsonl_store.py` の `append_jsonl` を通す。`echo >>` や手打ちの1行追記はしない。

```python
import sys; sys.path.insert(0, "scripts/lib")
from jsonl_store import append_jsonl
append_jsonl("local/llm/change_log.jsonl", {
    "ts": "2026-08-13T18:20:00+09:00",   # ★JST・ISO8601。帯を必ず付ける
    "dept": "aegis-gl",                   # ★実際に作業した部門(代行時のみ代行部門)
    "何": "…",                            # 日本語1文
    "なぜ": "…",                          # 日本語1文
    "触った": "scripts/llm/xxx.py",
    "commit": "2bab10c",
    "report_to": "future-room",           # 依頼元部屋のスラッグ
})
```
- **`ts` の帯を省くな。** 同じ台帳の中で `Z`(UTC)で書かれた行が6本あり、**9時間ずれて別の日に落ちていた**(707行の内訳を2026-08-13に実測: 帯つき664 / 帯なし29 / `Z` 6 / 空白区切り等7 / 壊れ1)。読む側は `jsonl_store.ts_epoch()` を使い、**自前の `_parse_ts` を書かない**。
- PowerShell の `Out-File` / `>` は既定で**BOM付きUTF-8**を書く。これで1行目が読めず、**dept=system-engineer の実記録1件がどの読み手からも永久に見えなかった**(commit 1b4aa38 / 2026-07-22)。台帳へは PowerShell のリダイレクトで書かない。
- 追記はdispatchしない。**貯めるだけ**でよい(「何を改修したか」は調べれば分かる状態にしておく、が目的)。

## closeの手順(open_defects.jsonl)
唯一の口は `scripts/llm/close_item.py`。台帳へ直接書かない。

```bash
python scripts/llm/close_item.py --id DEF-xxx-yyy --dept <部門> \
    --fixed "<直った実物の在りか>" --scene "<どの場面で見たか>" --by "<誰>"
python scripts/llm/close_item.py --list --dept <部門>   # 未確認の一覧(弾かれた記録も出る)
python scripts/llm/close_item.py --health               # 台帳の壊れ行を数える
```
掟(ここで緩めない):
- `--fixed` は**機械が解決できる在りか**だけ= Discordのmsg_id/リンク・**実在する**パス・URL。
- ★**commitのhashは受理されない。** 台帳であって、Chamiの画面で終わっている実物ではない(「封じた」と書いたcommitの4〜19分後に同じ再発が5回来た実測がある)。
- `--scene`(どの場面で確かめたか)は必須。
- 受理されなかった行も**残る**。何が足りなかったかは `--list` で読める。

## やらないこと
- 既存行の書き換え・削除(**追記のみ**)。消すのでなく退避する(C-003)。
- 記録先を2つ持つこと。持つなら**対で閉じる**。起票の前に既存台帳を grep する。
- `local/` はgitignore=**commitされない**。「commitしたから残った」と考えない。

## 完了の言い方
台帳へ書いただけなら「入れた(確認待ち)」。**同じ場面の実物**を見るまで「直った」と書かない(§4.55)。
