# 裁定 — holodri_noel cut_list の正本を一本化する(2026-09-05 / AD研究室 モドリッチ)

新規ファイル(既存の書き換えではないので .bak 不要)。台本cutlistが3つに割れていた件の決着。

## 裁定(確定)

**正本 = `D:\SougouStartFolder\5chShortMovie\holodri_noel\holodri_noel_cutlist.yaml`(714行)。**
`5SecMovieMaker\local\5ch\projects\holodri_noel\holodri_noel_cutlist.yaml`(718行)は**退避で残す=削除しない**。

## 根拠(2026-09-05 実測)

| | A=718行版(5SecMovieMaker/local側) | B=714行版(5chShortMovie側)★正本 |
|---|---|---|
| 動画になった実績 | **一度も無い** | `holodri_noel.mp4` 1,728,417,227B(09-04 02:26)/ `_youtube.mp4` 15,967,444B(02:32) |
| assets | **無い**(生成器が実走できない) | 同フォルダに `assets/images/` 実在(5枚+IMG_2877) |
| global の運用パラメータ | **1本も無い** | **13本ある**(voice_speed / background_color / background_image_file / unique_image_variants / center_images / show_original_full / require_project_assets / image_safe_width / image_safe_height / caption_stack_limit / ungroup_all ほか) |
| end_card | **復活させてしまっている**(Chami裁定5=不採用に反する) | 置いていない(裁定5遵守) |
| カット数 | 21 | 22ブロック / 総尺65.6秒(等倍)=1.2倍速で約54.7秒(Chami指示「50〜59秒」に収まっている) |
| 🐧さんFB反映 | **持っている**(下記) | 持っていない |

★AはBの後継ではない。**Bより前の祖先から分かれた枝**だ(だから運用パラメータを1本も持たず、廃止したはずのend_cardが生えている)。
→ ゆえに「Aで上書き」は退行になる。**Bを土台にし、Aの固有価値だけを移す。**

## 動画制作部門の申告との差分(訂正)

回答紙 `local/consult_intel/manga-shorts_cutlist正本と背景キー_20260905.md` L45 は「**718行版の背景改稿**を714行版へ取り込む」と書いている。**正本の向きは合っているが、移す中身の名指しが違う。**
- 背景は移植不要=`background_style: radial_blue_motion` を **globalへ1キー足すだけ**で足りる(同紙 Q2)。
- 実際に移すべき本体は **🐧さんフィードバック反映分**(冒頭フック+コメント増量5カット)だ。

## Aから移す実体(これだけ)

1. **cut_001 の差し替え** = スレタイ風フック。`cut_type: "thread_title_hook"` / caption `【朗報?】ホロ夏の水着ガチャ\n団長がヤバすぎて話題にwww` / 4.5秒 / 画像=03_mosaic_appstore_post.png / SE=試合開始のゴング.mp3。参考chの【速報】…wボックス型。
2. **新規5カット**(いずれも `caption_type: comment_card` / `voice_role: viewer` / 1.8〜2.2秒)
   - `cut_005b` 「教育に悪い」
   - `cut_007b` 「合法です。」
   - `cut_008b` 「またぺこちゃんが反応してて草」
   - `cut_013b` 「団長がガチのエロ売りしたら\nダメでしょｗ 禁止カードだよｗ」
   - `cut_013c` 「ぶっちゃけこれだけ欲しいw」
   - 全て `local/attachments/1544800550023995512_0.md` の原文ママ(013bのみｗ連打を1つへ短縮)。
3. **ナレ専用つなぎの削減**(A側は旧cut_009を除去し、その橋渡し役を cut_008b に吸収させている)。B側の該当= `cut_004_listener_intro` / `cut_010`(いずれも `narration_bridge`)。**どちらを落とすかは移植担当が突合して決める。**
4. **global へ 1キー追加** = `background_style: radial_blue_motion`(★`#`コメント帯に書くと機械が拾えない=silent-ignore。必ずキーで渡す)。

## 移してはいけない物(★)

- **A の `end_card:` ブロック**(Chami裁定5=説明欄/共有CTAを出さない、に反する)。
- **A の画像絶対パス**(`5SecMovieMaker\local\5ch\...` を指している)。Bのassets解決へ揃える。
- **B の global 運用パラメータ13本**は1本も消さない。`require_project_assets: true` が効いているので、パスが外を向くと生成器が弾く。

## 尺の制約(★見落とすと必ず溢れる)

Bは既に等倍65.6秒(1.2倍で54.7秒)。Aの新規5カットは計9.6秒。**足すだけだと1.2倍で約62.7秒**=Chami指示「50〜59秒」を超える。
→ **足した分と同尺を既存から削る**(候補=上記3の narration_bridge 2本、および冗長なnarrationカットの短縮)。

## 手番

- 統合版の作成(YAML編集)= **分析部門(shorts-analyst)**。cut_listの作者だから。
- 一本化後に通しで1本書き出し、動く青放射背景がYMM4で回って見えるかの**目視確認**= 動画制作部門(manga-shorts)。※`background_style` は現状「入れた(確認待ち)」= C-070の日齢対象。起点 2026-09-05。
- **Chamiの手番はゼロ**(C-069)。

## 追記 2026-09-05 11:03(モドリッチ)— 統合は着地した(実測)

★上の表の「B=714行」は**この裁定を書いた 03:36 時点の値**。**05:28 に統合版が着地して 894行になっている**(mtime 2026-09-05 05:28:26 / 37,636B / PyYAMLでparse OK / cuts 26 / global 20キー)。以後この裁定を引く者は 894行版を見ること。

俺が数えた着地の実測(すべて正本ファイル内):

| 裁定で「移す」と決めた物 | 実測 |
|---|---|
| cut_001 スレタイ風フック | `thread_title_hook` 3件 = **入っている** |
| 新規5カット | `cut_005b` / `cut_007b` / `cut_008b` / `cut_013b` / `cut_013c` **5本とも在る** |
| global へ `background_style` | `radial_blue_motion` 4件 = **キーで入っている**(コメント帯ではない) |
| ★移してはいけない `end_card` | **実体なし**(L18・L31・L90・L889 のコメントでの言及のみ)= 裁定5を守っている |
| 尺(50〜59秒) | 等倍 **65.2秒** / `playback_speed: 1.2` で **54.3秒** = **収まっている** |

→ **統合版の作成(分析部門の手番)は完了**。残るのは **1分shorts制作部門の目視確認**(通しで1本書き出し、動く青放射背景がYMM4で回って見えるか)だけ。`background_style` は「入れた(確認待ち)」のまま=C-070の日齢対象・起点 2026-09-05・**所有=1分shorts制作部門**(C-072)。3日目(9/8)に督促、7日目(9/12)に依頼元へ1行。

## 追記 2026-09-05 11:15(モドリッチ)— artifactレベルは取れた。ただし**Chamiが開くファイルがまだ無い**

1分shorts制作部門(ヴィルシーナ)が 11:07 に、正本に触れず audio-off 複製で実走→出力 `.ymmp` を実読→即削除、という形で **artifact レベルの確認**を前倒しで取った(Rotation 0.0→360.0 / Span=全長3380f / AnimationType「直線移動」/ Zoom 166.5 / IsAlwaysOnTop False / BackgroundColor `#FFFFFFFF` / 納品ゲート通過)。

俺は**その主張をソースと手元の実物で検算した**(GASは叩いていない・読み取りのみ):

| 主張 | 俺の検算 | 判定 |
|---|---|---|
| `radial_blue_motion` で回転が点く | `cut_list_to_ymmp.py:1860` `bg_in_motion = "motion" in background_style` = 部分一致で True | ○ |
| 尺全体で0→360を一周 | `:1881` `bg_item["Rotation"] = anim_linear(0.0, 360.0, total_frames)`。`total_frames` は `:1815`、`timeline["Length"] = total_frames` は `:1898` = **Span と Length は同じ変数**。よって音声長で総尺が変わっても「全長で一周」は構造上不変 | ○ |
| AnimationType「直線移動」 | `anim_linear` の生成部 `:246-247` = `Span: float(span_frames)` / `AnimationType: "直線移動"` | ○ |
| Zoom 166.5 | ★言い方だけ訂正。「√2×1.45」ではなく **被覆zoom × 1.45**(`:1872-1875`)。手元の**静止版**実物 `output/holodri_noel.ymmp` の Zoom = **114.83253588516746**、×1.45 = **166.51** で申告値と一致 | ○(数値は正) |
| Remark | 静止版の実物は `generated_fresh_background`(`:1886`)。動く版は `generated_fresh_background_motion`(`:1882`) | ○ |

### ★穴(俺が見つけた):**本番の出力ファイルが1つも存在しない**

正本の `work.output` = `D:/SougouStartFolder/5chShortMovie/holodri_noel/output/holodri_noel_v22_merged.ymmp`。
**`holodri_noel` 配下を再帰で走査して `v22` / `merged` を名前に含むファイルは 0 件**(2026-09-05 11:13 実測)。
`output/` に在る `.ymmp` は17本すべて **09-03〜09-04 の統合前の版**で、最新 `holodri_noel.ymmp`(177,278B・09-04 02:21)を JSON で開いて背景 item を実読した結果:

```
Remark   = generated_fresh_background   ← 静止版
Rotation = {"Values":[{"Value":0.0}], "Span":0.0, "AnimationType":"なし"}
Zoom     = 114.83253588516746 / Layer 0 / IsAlwaysOnTop False / Length 3433 / Timeline Length 3454
```
※ 正本ゲート CLI(`python -X utf8 validate_ymmp.py <file>`)は `[OK]` / exit 0。

→ **手元に残っているのは「回っていない版」だけだ。**audio-off 複製は即削除されているので、**Chami が YMM4 で開いて青放射を目視できるファイルは今この瞬間どこにも無い。**

### 手番の訂正

- 残手番は「Chami の GUI 目視のみ」**ではない**。その前に **1分shorts制作部門が本番(`synthesize_audio: true`)で通しを1本書き出し、`holodri_noel_v22_merged.ymmp` を消さずに残す**手番が要る。所有は manga-shorts のまま(C-073=ymmp生成の所有)。★研究室は生成を代行しない。
- `background_style` の位置は §4.55 で **「効いた」**(生成物の中に回転が書かれているのを実物で確認した)。**「直った」ではない**(YMM4 が実際に回して描画するかは未確認)。
- C-070 の日齢は起点 2026-09-05 のまま据え置き。**artifact が取れても確認待ちは閉じない**(Chami の目視が残っているため)。9/8 督促の内容は「本番書き出しが残っているか」に変わる。

## 追記 2026-09-05 11:28(モドリッチ)— 本番出力は出来た。ただし**尺が77.2秒で溢れている**

11:15追記の穴(Chamiが開くファイルが無い)は**閉じた**。ただし**1分shorts制作部門の手番としてではない**——**改修α**が 11:20 に着地させた台本編集ツール(`5SecMovieMaker 57787d7` / ローカルFlask 127.0.0.1:5057)の**検証実走の副産物**として出来た。

実測(第13世代・読み取りのみ):

| 項目 | 実測値 |
|---|---|
| ファイル | `D:/SougouStartFolder/5chShortMovie/holodri_noel/output/holodri_noel_v22_merged.ymmp` **実在**・246,835B・mtime 2026-09-05 11:18:58 |
| 背景item | `Remark = generated_fresh_background_motion` / Layer 0 / IsAlwaysOnTop False |
| 回転 | `Rotation.Values = [0.0, 360.0]` / `Span = 4629.0` / `AnimationType = 直線移動` |
| Zoom | 166.5071770334928(静止版 114.8325… × 1.45 と一致) |
| 総尺 | `Timeline.Length = 4629` = `max(Frame+Length) = 4629` = **77.2秒**(fps 60) |
| 納品ゲート | `python -X utf8 validate_ymmp.py <file>` = `[OK]` / exit 0 |

→ **`background_style: radial_blue_motion` は §4.55 の「効いた」のまま**だが、**今度は Chami が YMM4 で開ける実物がある**。

### ★新しい穴:尺 77.2秒(Chami指示 50〜59秒 / 生成器の自前ガード 45〜60秒を超えている)

- **audio-off 複製 = 3380f(56.3秒)** → **本番(`synthesize_audio: true`)= 4629f(77.2秒)**。差 **+1249f = +20.8秒**。
- 真因= `cut_list_to_ymmp.py:1628-1638` の**収容延長**。`required = _voice_seconds + 0.06` がカット尺の**下限**になる(`extra = max(0.0, required - duration)`)。
- ★**この延長は `playback_speed` の除算(`:1528-1535`)より後に走る**= **`playback_speed` を上げても音声ぶんは1フレームも縮まない**。効くのは ①喋る文字を削る/カットを減らす ②`voice_speed`(現在 1.2)を上げる、の2つだけ。
- 裁定 §尺の制約 の見積り(「1.2倍で約62.7秒」)も、分析部門の申告(「1.2倍 54.3秒」)も、**yaml の `duration` から計算した値**であって**音声長を含んでいない**。**この型では yaml の尺見積りは常に過小になる。**

### 手番(訂正)

1. **分析部門(shorts-analyst)**= cutlist の尺を **77.2秒 → 50〜59秒** へ削る。削る量の目安 **18〜27秒**。★`playback_speed` を上げる手は効かない。
2. **1分shorts制作部門(manga-shorts)**= 1 の後に**本番でもう1回書き出す**(C-073=ymmp生成の所有)。
3. **Chami の YMM4 目視は 2 の後に1回だけ**。今の 77.2秒 版を開かせない(直せば作り直しになる=同じ手番を2回積むことになる・C-069)。
4. `background_style` の C-070 日齢は**起点 2026-09-05 のまま据え置き**(所有=manga-shorts)。9/8 督促の中身は「**尺を直した本番書き出しが残っているか**」へ更新。

※編集ツール側は生成器の stdout を画面へ出す実装になっている(`5ch-daihon/server/app.py:344` で返し、`static/app.js:210` で `genStdout` へ表示)= **Chami がツールから生成した時は「⚠ 尺オーバー」がその場で見える**。ここは塞がっている。

※この版は**編集サイト(改修α)が参照すべき型の正本**でもある。`cut_list_template.yaml`(17,924B・mtime 2026-08-05 08:32)は voice系キーを1つも持たないので**型に使うな**(`voice_reading`/`voice_char`/`voice_role`/`narration_text`/`reaction_text`/`voices`/`background_style`/`comment_card`/`title_card` すべて0件・実測)。

---

## 追記 2026-09-05 11:36(モドリッチ)— 尺の内訳を割った。エンドカードは入っていない

1分shorts制作部門(ヴィルシーナ・11:21:31着)から2点上がってきたので、**両方こちらで実測して決着させた**。本番 ymmp の全96アイテムと VOICEVOX 音声24本の Length を1本ずつ読んでいる(生成器は実走していない=既にある実物から読める数字だった)。

### 決着1:**エンドカードは出力に入っていない。裁定5は破られていない**

上がってきた疑い= 「エンドカードは正本『未配置』のはずが本番出力には込み=生成器が付加している疑い」。**誤認だった。**

| 検査 | 結果 |
|---|---|
| 「画面を長押し」「右上の3点ボタン」「概要欄は右上の3点をタップ」を含むテキスト | **0件**(= `cut_list_to_ymmp.py:1795-1812` の `end_card` ブロックは発火していない) |
| 正本の `end_card:` ブロック | **無し**(コメント4箇所で「置かない」と明記されているのみ) |
| 末尾に見えていた実体 | `cut_019` の CTA = `caption_box:cta` / `editable_caption:cta`「この水着、引いた?」Frame 4330 / Length 299(4.98秒) |

→ 正体は **`:1819-1826`**= `if not end_card and cuts:` で、**エンドカードを置かない動画では最後のCTAアイテムを `ec_frames`(2.0秒)だけ伸ばす**仕様。**付加されたのは尺2.0秒だけで、画も文言も増えていない。**
→ したがって尺対策としての「**エンドカード尺詰め**」は**最大2.0秒しか効かない**。18〜27秒の勘定に入れない。

### 決着2:**総尺 77.15秒の内訳=削れる余白は実質ゼロ**

| 内訳 | 秒 | 備考 |
|---|---|---|
| 音声の実尺 合計 | **70.07** | VOICEVOX item 24本 |
| カット間の無音 合計 | 5.03 | うち16箇所が 3f(0.05秒)= 固定の詰まり。**削れない** |
| 末尾の余韻(`ec_frames`) | 2.05 | 上記 |
| **計** | **77.15** | = `Timeline.Length 4629` / fps 60 |

→ **59秒着地に要る 18.2秒は、全部「音声そのもの」から出すしかない。**

### カット別 音声実尺(長い順 TOP8 / 全24本を実測)

| cut_id | cut_type | 音声 | 字数 | yaml `duration` |
|---|---|---|---|---|
| **cut_001** | thread_title_hook | **9.55s** | 73 | 5.0 |
| **cut_003** | theme_intro | **6.27s** | 42 | 5.5 |
| **cut_018** | punchline_follow | **5.48s** | 42 | 5.2 |
| **cut_011** | member_bandwagon | **5.27s** | 34 | 5.0 |
| **cut_004** | reaction_burst | **4.72s** | 39 | 4.5 |
| cut_013b | viewer_comment | 3.08s | 27 | 2.2 |
| cut_017 | viewer_comment | 3.07s | 27 | 2.2 |
| cut_019 | cta | 2.93s | 20 | 3.4 |

- **上5本で 31.29秒 = 全音声の 45%。** 残り19本は平均2.04秒で、1本落としても2秒しか動かない。**削るならナレーション5本。**
- 換算レート(この動画の実測)= **531字 / 70.07秒 = 7.58 字/秒**(`voice_speed 1.2` 時)。**1秒縮める ≒ 7.6字削る。18.2秒 ≒ 138字(全体の26%)。**
- `voice_speed` 単独で解く場合に必要な値= **1.62**(音声 70.07秒 → 51.9秒)。早口すぎる= **単独では解けない**。併用が現実的(例: `voice_speed 1.35` で音声62.3秒/総尺69.4秒 → 残り10.4秒 ≒ 79字を文字削りで出す)。配分は分析部門の裁量。

### 11:28 追記の訂正

- 「narration_bridge 2本= `cut_004_listener_intro` / `cut_010`」と書いたが、**`cut_010` は正本894行に存在しない**(cut_id 26本を実読)。narration_bridge は `cut_004_listener_intro` の1本だけで**音声1.85秒**= 削り先として弱い。

### 生成者の食い違い(事実だけ・未決着)

- 1分shorts制作部門の申告= 生成 **11:15**。実測 mtime= **11:18:58**。`change_log.jsonl` は **改修α(system-engineer)** が `5SecMovieMaker 57787d7` の検証実走でこのファイルを生成したと記帳(11:20:10)。
- **現存の1本は改修αの実走の産物**。同一パスなので 11:15 の版は残っていない(上書きされた公算)。正本894行から同じ生成器を通せば中身は同じになるので**成果物の正しさには影響しない**が、**「1分shorts制作部門の手番として残した」証拠はファイル側に無い**。次の再書き出しで取り直す。
- なお先方の便(11:21:31)は**当室の状況便(11:27:12)より前**に出ている= 手番の認識ずれ(「対処はChami裁量」)はそれで説明が付く。

### 出した便

| 宛先 | msg_id | 中身 |
|---|---|---|
| 分析部門 | `DISPATCH-shorts-analyst-1788575711082` | 上の内訳・カット別実測・換算レート・`cut_010` 不在の訂正 |
| 1分shorts制作部門 | `DISPATCH-manga-shorts-1788575757309` | end_card 切り分けは不要(結論を渡した)・時刻の食い違い・尺はChami裁量にしない |
