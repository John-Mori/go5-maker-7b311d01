---
name: organization-test-gate
description: AI組織runtimeのテスト・検査を追加した時、またはrouting、写像、retry、fallback、daemon判定を変えた時だけ使う。YMM4、商品サイト、一般的な小修正のテストには使わない。
---

# AI組織の赤→緑テストゲート

対象範囲と実行入口は [README](../../../README.md)、[CLAUDE](../../../CLAUDE.md)、[layout.json](../../../config/layout.json) を正とする。旧runtimeのテスト名やディレクトリ一覧をこのスキルへ固定しない。

## 必須の証拠

1. 修正前の壊れた実物、または同じ分岐を通る失敗入力を保存する。
2. 検査を追加する。
3. 実装修正前、または安全な一時変異で検査が意図した理由によりFAILすることを見る。
4. 実装を直す、または変異を元のバイト列へ戻す。
5. 同じ検査がPASSし、関係する既存ゲートもPASSすることを見る。

0件実行、assert無し、例外の握り潰し、対象ファイル不在によるskipはFAIL証拠に数えない。

## 実行経路を検査する

- source文字列の存在だけで、引数、routing、fallbackが効いたと断定しない。
- 外部HTTP、送信、プロセス起動、永続化だけをfakeにし、実際の判定と分岐を呼んで渡された値を検査する。
- fallbackやquota切替は、1段目を意図的に失敗させて2段目まで通す。全部門、別persona、別queueなど独立した呼出口を数える。
- 共有mappingを変えたら、そのmappingの全readerと全writerを列挙し、片側だけの緑を完了証拠にしない。

## Python変異時の注意

同じバイト数の値を同じ秒内に差し替えると、古い`.pyc`が有効と判定され、偽のFAIL/偽のPASSが起こり得る。`python -B`は読込を止めない。

- 一時変異は`read_bytes()`/`write_bytes()`で往復し、改行を変えない。
- 変異ヘルパで対象moduleの`__pycache__`を毎回除去するか、隔離された新規import先で実行する。
- 必要なら実行中functionの`__code__.co_consts`などで、実際に読み込まれた定数を確認する。

## 報告

「テスト追加」は確認待ち。「意図したFAIL→修正後PASS」はゲート有効。同じ実利用経路を確認するまでは「症状解消」と報告しない。
