---
paths:
  - "app.js"
  - "index.html"
  - "style.css"
---

> ★この章は `CLAUDE.md` から移した。**内容は変えていない**(2026-08-29・研究室HQ)。
> 毎便の固定費(床)を下げるため、上の `paths` に当たるファイルを触る時だけ読み込まれる。

## 3. 座標系の規約(最重要・崩さない)

- 基準フレーム **`W=1080, H=1920`(9:16)が唯一の基準座標系**。`index.html` の `<canvas width height>` も一致させる。
- 位置・フォントサイズは `H×係数` / `W×係数`。旧来の絶対px定数は **`U(v)=v*H/1280`** で基準フレームに換算。
- プレビューも書き出しも**同一Canvasに同じ式で描画** → PC/スマホ/書き出しで一致(CSSは9:16を一様縮小表示するだけ)。
- 縦オフセットは `OFF` オブジェクトで一元管理：
  - `OFF.whole`(全体)／`OFF.textAuthor/textDetail/textTitle`(各段の位置＝帯＋文字を一体で動かす)。
  - **段別オフセットは描画位置にのみ加算し、段の送りY(次段位置)には反映しない**＝他段に波及しない。
  - **帯は各段のテキストに統合**＝帯と文字は常に同じオフセットで一緒に動く(★旧・帯独立軸 `OFF.bandAuthor/bandDetail/bandTitle` は廃止・2026-07-07。「帯だけ」を別に動かすことはできない)。
- `document.fonts.ready` 後に再描画(フォールバックフォント計測由来のズレ防止)。

### localStorage キー
`preview_offset_y`(全体)／`preview_text_author|detail|title`、各 `*_default`(既定値)。2行モード＝`movie_author_two_line`/`movie_two_line`。旧キー `v_offset`・`preview_band_y`・`preview_band_author|detail|title` は退役(読まれない)。
