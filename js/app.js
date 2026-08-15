/* 5秒動画メーカー(クライアントサイド合成)
   背景動画＋前景画像＋テキスト3段を Canvas で描画し、MediaRecorder で録画して動画化する。
   仕上がりはデスクトップ版 composite.py に合わせている。 */
(() => {
  "use strict";

  // ---- 仕上がり設定(composite.py / jobs.json と統一) ----
  // 基準フレーム＝唯一の基準座標系。(9:16)位置・サイズ・余白・行間は全てこの値への比率で表現する。
  // プレビューも書き出しも同じ Canvas(=この解像度) に描くため、画面幅に関係なく完全に一致する。
  const W = 1080, H = 1920;         // 基準フレーム解像度(ここを変えれば出力解像度が変わる／レイアウトは比率維持)
  const DURATION = 5, FPS = 30;
  const REVEAL_START = 0.5, REVEAL_DUR = 2.4;   // 浮き上がり: 0.5s開始→2.9s完成(以後2.1s保持)。Chami依頼2026-07-18で0.7s遅らせた
  const FG_MAX_RATIO = 0.92, FG_ZOOM = 0.04, FG_CENTER_Y = 0.55;
  // YouTube Shorts が縦長端末で左右各約9%を切り落とす(cover)。前景画像の"幅"だけは
  // 切られない安全域(=中央82%)に収まる比率でフィットさせ、端が欠けないよう自動で適正化する
  // (切れ範囲ガイドの表示は廃止し、代わりに最初から枠内へ収める・Chami依頼2026-07-31)。
  // 高さは従来どおり FG_MAX_RATIO(上下は切られないため)。プレビューも書き出しも同式=一致。
  const YT_SIDE_CROP = 0.09, FG_SAFE_W_RATIO = 1 - 2 * YT_SIDE_CROP; // = 0.82
  const DEFAULT_DETAIL = "作品の詳細は右上の：から説明";

  // 旧来 1280px フレーム基準で決めた絶対px定数(余白・行間・縁取り下限など)を、
  // 現在の基準フレーム高さに合わせて比率換算する。基準解像度を変えてもレイアウトが崩れない。
  const U = (v) => v * H / 1280;

  // 構成全体(上部テキストブロック＋前景の漫画ページ)の縦位置オフセット。
  // 基準フレーム高さに対する比率。(0〜VOFF_MAX)テキスト開始Yと前景中心Yに同じだけ加算するため、
  // 両者の相対関係(中央揃え・行間)は崩れない。スライダーで微調整する。
  const VOFF_DEFAULT = 0.02, VOFF_MAX = 0.05;   // 全体(文字＋帯＋漫画)を下へ
  const ROW_MIN = -0.03, ROW_MAX = 0.03;        // 段別(文字・帯とも)上下双方向(＋下／−上)
  const BANDPAD_MAX = 0.02;                      // 黒帯の余白(厚み)を追加できる上限(基準フレーム高さ比)
  const ROWGAP_MAX = 0.04;                       // 段と段の追加スペース上限(基準フレーム高さ比)
  const TSCALE_MIN = 0.7, TSCALE_MAX = 1.5;      // 大タイトルの拡大率(1.0＝従来。影・帯は文字サイズ比なので連動)
  const IMG_MIN = -0.15, IMG_MAX = 0.15;         // 前景画像だけの上下オフセット(基準フレーム高さ比・文字とは独立)
  const ISCALE_MIN = 0.5, ISCALE_MAX = 2.0;      // 前景画像の拡大率(1.0=従来のフィット)。二本指ピンチと±で操作(Chami依頼2026-07-17)

  // 縦オフセット。(すべて基準フレーム高さ比)段別は「文字」1軸のみ＝帯は文字に統合され一緒に動く。
  // 段別オフセットはその段の描画位置にのみ加算し、段の送り(次段Y)には影響させない＝他段は不動。
  const OFF = {
    whole: VOFF_DEFAULT,
    textAuthor: 0, textDetail: 0, textTitle: 0,  // 各段の位置(帯＋文字を一体で動かす)
    bandPad: 0,                                  // 黒帯の余白(全段共通で厚みを足す)
    rowGap: 0,                                   // 段と段の間に足す縦スペース
    titleScale: 1,                               // 大タイトルの拡大率(1.0＝従来。影・帯は px 比で自動連動)
    imgY: 0,                                      // 前景画像だけの上下オフセット(文字・帯は不動)
    imgScale: 1,                                  // 前景画像の拡大率(1.0=フィット)。★プレビューの見た目ではなく書き出す動画の画像そのものを拡大縮小する(Chami依頼2026-07-17)
  };

  const $ = (id) => document.getElementById(id);
  const cv = $("cv"), ctx = cv.getContext("2d");
  const bg = $("bg");

  // ---- アカウント定義(背景動画の切替。Bluesky/YouTube個別資格情報は保留＝acc1共有を流用)----
  const ACCOUNTS = {
    acc1: { label: "月詠み色恋劇場", bg: "assets/bg_main.mp4" },
    acc2: { label: "宵桜艶帖～Yoizakura Tsuyacho～", bg: "assets/bg_account2.mp4?v=203" }, // S-1a: 5.0sシームレスループ版に差し替え。(継ぎ目21.2→27.0dB)?vはキャッシュ更新用
  };
  let curAccount = "acc1";

  // ---- アカウント別テンプレ・テーマ(派生プリセット)----
  // 変えるのは「表示テキストと装飾色」のみ。レイアウト・座標・送り・生成フローは共通。(§3座標規約は不変)
  // acc1＝従来値そのまま。(見た目不変)acc2＝桜ピンクの派生。(温白文字＋桜グロー＋ダークプラム帯)
  const THEME = {
    acc1: {
      authorPrefix: "作者：",
      defaultDetail: DEFAULT_DETAIL,        // "作品の詳細は右上の：から説明"(：→⋮、説明→≡説明)
      detailMenu: true,                     // 誘導文の「説明」前に ≡(ハンバーガー)を出す
      textFill: "#F5E6B8",                  // 月光金(文字)
      stroke: "rgba(0,0,0,1)",              // soft時は未使用
      bandRGB: "46,64,104",                 // #2E4068 宵藍の帯
      bandAlpha255: 204,                    // 不透明度80%(acc1のみ固定＝#2E4068CC相当)
      soft: true,                           // 淡金のごく弱いグロー＋可読性用の暗い影(黒い太縁は使わない)
      glowSoft: "rgba(245,230,184,0.15)",   // 淡金グロー(ほぼ無し・ぼかし6px相当)
      darkShadow: "rgba(0,0,0,0.5)",        // 可読性用の暗い影(0 1px 2px 相当)
      iconFill: "#F5E6B8", iconHalo: "rgba(46,64,104,0.95)",  // アイコンも月光金＋宵藍で統一
    },
    acc2: {
      authorPrefix: "引用：",               // A：作者：→引用：
      defaultDetail: "作品は右上の：から説明へ🌸",  // A：誘導文(：→⋮、≡なし、末尾🌸)
      detailMenu: false,                    // acc2は ≡ を出さない(「⋮から説明へ🌸」)
      textFill: "#FFF0F5",                  // C：温白(lavender blush)
      stroke: "rgba(0,0,0,1)",              // glow時は未使用(黒縁は廃止)
      bandRGB: "74,30,58",                  // D：#4A1E3A 葡萄色プラム(α＝既存0.69〜0.76を踏襲＝指定の0.7前後)
      glow: true,                           // B：黒縁→桜ローズの発光影(にじみ・グロー)
      glow1: "rgba(232,75,138,0.95)",       // #E84B8A 中心・小ぼかし(強)
      glow2: "rgba(214,51,108,0.60)",       // #D6336C 中間・中ぼかし
      glow3: "rgba(214,51,108,0.40)",       // #D6336C 外側・大ぼかし
      contour: "rgba(140,30,70,0.9)",       // 最内の細い同系濃色の輪郭(可読性確保・黒は使わない)
      iconFill: "#FFF0F5", iconHalo: "rgba(140,30,70,0.95)",  // アイコンも温白の芯＋同系濃色の輪郭で艶トーン統一
    },
  };
  const theme = () => THEME[curAccount] || THEME.acc1;

  // 文字本体の描画。(テーマ依存)acc1＝黒縁＋白、acc2＝桜ピンク2層グロー＋温白の芯。
  function paintGlyph(ln, x, y, px, sw, shadowScale) {
    const t = theme();
    var ss = shadowScale || 1;  // 影のスケール(大タイトル拡大に連動。既定=1)
    if (t.soft) {
      // acc1：淡金のごく弱いグロー＋可読性用の暗い影(参考: 0 0 6px rgba(245,230,184,.15), 0 1px 2px rgba(0,0,0,.5))。
      // px固定値はU()で基準フレームへ換算。(CSSの6/1/2px相当)黒い太縁は使わない。
      ctx.save();
      ctx.fillStyle = t.textFill;
      // 暗い影(0 1px 2px rgba(0,0,0,.5))※大タイトル拡大時は同率で拡大
      ctx.shadowColor = t.darkShadow; ctx.shadowBlur = U(2) * ss; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = U(1) * ss;
      ctx.fillText(ln, x, y);
      // 淡金のグロー(0 0 6px rgba(245,230,184,.15))※同率で拡大
      ctx.shadowColor = t.glowSoft; ctx.shadowBlur = U(6) * ss; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
      ctx.fillText(ln, x, y);
      ctx.restore();
      ctx.fillStyle = t.textFill; ctx.fillText(ln, x, y);  // 影なしの芯(くっきり)
    } else if (t.glow) {
      // 桜ローズの発光影。(外→内の3層グロー)ぼかし量は文字サイズ比。(CSSの6/14/22px相当)
      ctx.save();
      ctx.fillStyle = t.textFill;
      ctx.shadowColor = t.glow3; ctx.shadowBlur = px * 0.55; ctx.fillText(ln, x, y);
      ctx.shadowColor = t.glow2; ctx.shadowBlur = px * 0.35; ctx.fillText(ln, x, y);
      ctx.shadowColor = t.glow1; ctx.shadowBlur = px * 0.18; ctx.fillText(ln, x, y);
      ctx.restore();
      // 黒縁は使わず、最内に細い同系濃色の輪郭を1枚だけ重ねて滲みの中でも字形を保つ
      ctx.lineJoin = "round"; ctx.lineWidth = Math.max(1, sw * 0.9);
      ctx.strokeStyle = t.contour; ctx.strokeText(ln, x, y);
      ctx.fillStyle = t.textFill; ctx.fillText(ln, x, y);  // 温白の芯(影なし)
    } else {
      ctx.lineJoin = "round"; ctx.lineWidth = sw * 2;
      ctx.strokeStyle = t.stroke; ctx.strokeText(ln, x, y);
      ctx.fillStyle = t.textFill; ctx.fillText(ln, x, y);
    }
  }

  const els = {
    photo: $("photo"), photoName: $("photoName"), photoBtn: $("photoBtn"),
    author: $("author"), detail: $("detail"), top: $("top"),
    previewBtn: $("previewBtn"), makeBtn: $("makeBtn"), status: $("status"),
    resultArea: $("resultArea"), result: $("result"), saveBtn: $("saveBtn"), dl: $("dl"),
    voffSaveDefault: $("voffSaveDefault"), voffReset: $("voffReset"),
    acctBtn1: $("acctBtn1"), acctBtn2: $("acctBtn2"),
  };
  els.detail.value = DEFAULT_DETAIL;

  let fgImg = null;               // 前景画像
  let fgFile = null;              // 実際に動画生成へ使った元ファイル(投稿履歴の使用画像を候補画像と分離して記録)
  let fgLoadSeq = 0;
  const K_PHOTO_CACHE = 'movie_photo_cache'; // リロード後の前景画像復元用キャッシュ
  let fontReady = false;
  let lastBlob = null, lastName = "video.mp4";
  let _making = false; // 作成中の再入防止。★見た目のdisabledに依存しない=押されたボタンだけを busy 表示できる
  let _makingAt = 0;   // 作成開始時刻(performance.now)。異常終了で _making が立ったまま固着した時に奪い返す判定に使う
  let _makeRunSeq = 0; // stale奪回後に旧MediaRecorderが遅れて完了しても、古い動画を通知しない世代番号

  // ---- フォント読み込み(Canvas描画前に必須) ----
  function ensureFont() {
    if (fontReady) return Promise.resolve();
    const loads = [
      document.fonts.load('900 60px "Noto Sans JP"'),
      document.fonts.load('700 40px "Noto Sans JP"'),
    ];
    return Promise.all(loads).then(() => { fontReady = true; }).catch(() => { fontReady = true; });
  }

  function setFont(px, weight) { ctx.font = `${weight || 700} ${px}px "Noto Sans JP", sans-serif`; }
  function smoothstep(x) { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); }
  // 浮き上がりのイージング(前半で認識可能まで進み後半で緩やかに完成・Chami依頼2026-07-18 §5/§6)。
  //   ★仕様推奨の cubic-bezier(0.22,1,0.36,1) は前半が急でDUR2.4でもt=2.5sで100%に達し、狙い(2.9s完成・
  //     後半の静止を減らす §4/§9)を満たせなかった(実測1.0s=69%)。そこで §4タイムライン(1.0s≈28%/2.5s<100/
  //     2.9s=100)に合う cubic-bezier(0.30,0.3,0.50,1) を採用(実測 28/60/88/97/100)。漫画・ラベル共通。
  //   x(時間0..1)→y(進捗)。Newton法でベジェのtを解く(標準実装)。
  const easeReveal = (function () {
    var x1 = 0.30, y1 = 0.3, x2 = 0.50, y2 = 1;
    function bz(t, a, b) { return (((1 - 3 * b + 3 * a) * t + (3 * b - 6 * a)) * t + (3 * a)) * t; }
    function sl(t, a, b) { return 3 * (1 - 3 * b + 3 * a) * t * t + 2 * (3 * b - 6 * a) * t + (3 * a); }
    return function (x) {
      if (x <= 0) return 0; if (x >= 1) return 1;
      var t = x;
      for (var i = 0; i < 8; i++) { var s = sl(t, x1, x2); if (!s) break; t -= (bz(t, x1, x2) - x) / s; }
      return bz(t, y1, y2);
    };
  })();

  // ---- テキスト：折り返し(文字単位) ----
  function wrap(text, px, maxw) {
    setFont(px, 700);
    const lines = [];
    for (const para of String(text).split("\n")) {
      let cur = "";
      for (const ch of para) {
        const t = cur + ch;
        if (ctx.measureText(t).width <= maxw || !cur) cur = t;
        else { lines.push(cur); cur = ch; }
      }
      lines.push(cur);
    }
    return lines;
  }

  function roundRect(x, y, w, h, r) {
    r = Math.min(r, h / 2, w / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // 通常テキストブロック。(中央寄せ・帯・白文字＋黒縁)
  // 実際の字形インクの上端/下端(canvas座標)を返す。帯を「行ボックス」でなく「見えている文字」に
  //   合わせて上下対称の余白で囲うために使う。drawY＝テキスト描画Y。(baselineは呼び出し側の設定に一致)
  //   actualBoundingBox が使えない/退化時はフォント比の近似にフォールバック。
  function inkExtent(sampleText, drawY, px) {
    const m = ctx.measureText(sampleText);
    const aBA = m.actualBoundingBoxAscent, aBD = m.actualBoundingBoxDescent;
    if (typeof aBA === "number" && typeof aBD === "number" && (aBA + aBD) > px * 0.3) {
      return { top: drawY - aBA, bot: drawY + aBD };
    }
    return { top: drawY + px * 0.06, bot: drawY + px * 0.94 };
  }

  // off＝この段の縦オフセット比。帯と文字を一体で動かす。(帯は常に文字を包む＝各段に統合)
  //   送りy(次段位置)には反映しない＝この段を動かしても他段は不動。
  //   帯は「行ボックス」ではなく実際の字形インクに対称な余白(vpad)で囲う＝文字の上下と帯の余白が等しい。
  function drawBlock(lines, y, px, pad, gap, bandAlpha, off, shadowScale) {
    setFont(px, 700);
    ctx.textBaseline = "top";
    const sw = Math.max(U(2), px / 12);
    const th = px * 1.04;
    const offY = H * (off || 0);  // 帯＋文字を一緒に縦シフト
    for (const ln of lines) {
      const tw = ctx.measureText(ln).width;
      const x = (W - tw) / 2;
      const mB = sw;  // 縁取り分だけ帯を広げ、文字が帯からはみ出ないようにする
      const drawY = y + offY;
      const vpad = pad * 0.45 + mB;                 // 文字インクの上下に付ける対称な余白
      const ie = inkExtent(ln, drawY, px);
      const ba = theme().bandAlpha255 != null ? theme().bandAlpha255 : bandAlpha;  // テーマで固定不透明度があれば優先
      ctx.fillStyle = `rgba(${theme().bandRGB},${ba / 255})`;
      roundRect(x - pad - mB, ie.top - vpad, tw + (pad + mB) * 2, (ie.bot - ie.top) + vpad * 2, pad + mB * 0.5);
      ctx.fill();
      paintGlyph(ln, x, drawY, px, sw, shadowScale);
      y += th + pad + gap;  // 送りは基準位置のまま(オフセットの影響を受けない＝他段に波及しない)
    }
    return y;
  }

  // アイコン
  function dot(cx, cy, r, halo) {
    const t = theme();
    ctx.fillStyle = t.iconHalo;
    ctx.beginPath(); ctx.arc(cx, cy, r + halo, 0, 7); ctx.fill();
    ctx.fillStyle = t.iconFill;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.fill();
  }
  function kebab(cx, ym, fs) {
    const r = Math.max(1, fs * 0.072), sp = Math.max(r * 2 + 2, fs * 0.26), halo = Math.max(1, fs * 0.022);
    for (const dy of [-sp, 0, sp]) dot(cx, ym + dy, r, halo);
  }
  function hbar(xl, y0, w, t, halo) {
    const th = theme();
    ctx.fillStyle = th.iconHalo; roundRect(xl - halo, y0 - t / 2 - halo, w + 2 * halo, t + 2 * halo, (t + 2 * halo) / 2); ctx.fill();
    ctx.fillStyle = th.iconFill; roundRect(xl, y0 - t / 2, w, t, t / 2); ctx.fill();
  }
  function hamburger(xl, ym, fs) {
    const t = Math.max(2, fs * 0.12), sp = fs * 0.28, halo = Math.max(1, fs * 0.05), w = fs * 0.80;
    for (const dy of [-sp, 0, sp]) hbar(xl, ym + dy, w, t, halo);
  }

  // 2段目(誘導文)：「：」→⋮、「説明」→≡説明 をインライン描画。
  // off＝この段の縦オフセット比。帯と文字(アイコン含む)を一体で動かす。
  function drawDetail(text, y, px, pad, off) {
    setFont(px, 700);
    ctx.textBaseline = "middle";
    const sw = Math.max(U(2), px / 12), th = px * 1.04, ym = y + th / 2 + H * (off || 0);
    const iconPad = px * 0.16, kebabW = px * 0.42, hamW = px * 0.80;
    // トークン分解
    const segs = []; let i = 0; const s = String(text);
    while (i < s.length) {
      const c = s[i];
      if (c === "：" || c === ":") { segs.push(["kebab"]); i++; }
      else if (s.substr(i, 2) === "説明") { if (theme().detailMenu) segs.push(["menu"]); segs.push(["text", "説明"]); i += 2; }
      else { let j = i, buf = ""; while (j < s.length && s[j] !== "：" && s[j] !== ":" && s.substr(j, 2) !== "説明") { buf += s[j]; j++; } segs.push(["text", buf]); i = j; }
    }
    const widths = segs.map(([k, v]) => k === "text" ? ctx.measureText(v).width : (k === "kebab" ? kebabW : hamW) + 2 * iconPad);
    const total = widths.reduce((a, b) => a + b, 0);
    let x = (W - total) / 2;
    const mB = sw;  // 縁取り分だけ帯を広げる
    const vpad = pad * 0.45 + mB;                 // 文字インクの上下に付ける対称な余白
    const ie = inkExtent(s, ym, px);              // baseline "middle" のまま実インクを計測(ymはオフセット込み)
    const ba = theme().bandAlpha255 != null ? theme().bandAlpha255 : 175;  // テーマで固定不透明度があれば優先
    ctx.fillStyle = `rgba(${theme().bandRGB},${ba / 255})`;
    roundRect(x - pad - mB, ie.top - vpad, total + (pad + mB) * 2, (ie.bot - ie.top) + vpad * 2, pad + mB * 0.5); ctx.fill();
    for (let k = 0; k < segs.length; k++) {
      const [kind, val] = segs[k], w = widths[k];
      if (kind === "text") {
        paintGlyph(val, x, ym, px, sw);
      } else if (kind === "kebab") kebab(x + w / 2, ym, px);
      else hamburger(x + iconPad, ym, px);
      x += w;
    }
    ctx.textBaseline = "top";
    return y + th + pad;
  }

  // 3段目コメントを「必ず1行」に。収まらない場合だけフォントを縮小する。
  function fitOneLine(text, basePx, maxw, minPx) {
    text = String(text).replace(/\n/g, " ").trim();
    setFont(basePx, 700);
    const w = ctx.measureText(text).width;
    let px = basePx;
    if (w > maxw && w > 0) px = Math.max(minPx || 14, Math.floor(basePx * (maxw / w) * 0.98));
    return { px, text };
  }
  // 3段目コメントの「2行モード」：★ユーザーの改行(\n)で分割。(1行目=改行前 / 2行目=改行後)
  //   改行が無ければ1行。各行が幅に収まる最大フォントを求める。(広い行に合わせて縮小)
  function fitTwoLines(text, basePx, maxw, minPx) {
    var parts = String(text).split("\n");
    var lines = [(parts[0] || "").trim()];
    if (parts.length >= 2) { var rest = parts.slice(1).join(" ").trim(); if (rest) lines.push(rest); }
    setFont(basePx, 700);
    var widest = 0;
    for (var i = 0; i < lines.length; i++) { var wdt = ctx.measureText(lines[i]).width; if (wdt > widest) widest = wdt; }
    var px = basePx;
    if (widest > maxw && widest > 0) px = Math.max(minPx || 14, Math.floor(basePx * (maxw / widest) * 0.98));
    return { px: px, lines: lines.length ? lines : [""] };
  }
  // 2行モードの大タイトル：帯は「両行をひとまとめに囲う1枚」。影の位置分離はせず、帯と文字は同じ
  //   blockOff(＝文字オフセット)で一緒に動く＝拡大/移動しても影が同量ずれる。文字は帯の中央に来る。
  function drawTitleBlockUnified(lines, y, px, pad, gap, shadowScale, blockOff, bandAlpha) {
    setFont(px, 700);
    ctx.textBaseline = "top";
    const sw = Math.max(U(2), px / 12);
    const th = px * 1.04, mB = sw;
    const offY = H * (blockOff || 0);       // 帯・文字を一緒に動かす(分離しない)
    let maxTw = 0;
    for (let i = 0; i < lines.length; i++) { const tw = ctx.measureText(lines[i]).width; if (tw > maxTw) maxTw = tw; }
    const blockH = lines.length * th + (lines.length - 1) * gap;
    // 帯は「行ボックス」でなく実際の字形インク(1行目の上端〜最終行の下端)を上下対称の余白(vpad)で囲う
    //   ＝文字の上下と帯の余白が等しくなる。
    const line1Y = y + offY, lineNY = y + offY + (lines.length - 1) * (th + gap);
    const ie1 = inkExtent(lines[0], line1Y, px), ieN = inkExtent(lines[lines.length - 1], lineNY, px);
    const inkTop = ie1.top, inkBot = ieN.bot, vpad = pad * 0.45 + mB;
    const ba = theme().bandAlpha255 != null ? theme().bandAlpha255 : (bandAlpha || 195);
    ctx.fillStyle = `rgba(${theme().bandRGB},${ba / 255})`;
    roundRect((W - maxTw) / 2 - pad - mB, inkTop - vpad, maxTw + (pad + mB) * 2, (inkBot - inkTop) + vpad * 2, pad + mB * 0.5);
    ctx.fill();
    let ly = y + offY;
    for (let j = 0; j < lines.length; j++) {
      const tw = ctx.measureText(lines[j]).width, x = (W - tw) / 2;
      paintGlyph(lines[j], x, ly, px, sw, shadowScale);
      ly += th + gap;
    }
    return y + blockH + pad;
  }
  // 3段目コメントを「2行モード」で描くか。(④コメント横のチェックボックス)
  function isTwoLineMode() { var c = document.getElementById("topTwoLine"); return !!(c && c.checked); }
  // ①作者も「2行モード」で描くか。(作者欄横のチェックボックス。コメントと同仕様)
  function isAuthorTwoLineMode() { var c = document.getElementById("authorTwoLine"); return !!(c && c.checked); }

  function drawText(author, detail, top) {
    const maxw = W * 0.9;
    const fA = Math.round(H * 0.025), fD = Math.round(H * 0.027), fT = Math.round(H * 0.048);
    const padExtra = H * OFF.bandPad;   // 黒帯の余白(厚み)を全段に加算
    const rowGap = H * OFF.rowGap;      // 段と段の間に足す縦スペース
    let y = Math.round(H * (0.020 + OFF.whole));  // 軸1：構成全体の縦オフセットを加算
    if (author) {
      author = author.replace(/^(作者|引用)\s*[:：]\s*/, "");      // 既存プレフィックスを一旦除去
      author = theme().authorPrefix + author;                      // テーマのプレフィックスを常に表示(acc1=作者：/acc2=引用：)
      if (isAuthorTwoLineMode()) {
        // 作者も2行モード(コメントと同仕様)：ユーザーの改行(\n)で最大2行・中央揃え・帯は両行を1枚で囲う。
        var fa2 = fitTwoLines(author, fA, maxw, U(11));
        y = drawTitleBlockUnified(fa2.lines, y, fa2.px, U(11) + padExtra, U(3), 1, OFF.textAuthor, 175) + U(2) + rowGap;
      } else {
        y = drawBlock(wrap(author, fA, maxw), y, fA, U(11) + padExtra, U(3), 175, OFF.textAuthor) + U(2) + rowGap;
      }
    }
    if (detail) y = drawDetail(detail, y, fD, U(11) + padExtra, OFF.textDetail) + U(4) + rowGap;
    if (top) {
      // まず幅に収まる基準サイズを求め、その上に「大タイトル拡大」を掛ける＝拡大が幅上限で打ち消されない。
      // 影も同じ倍率(ss)で拡大。(drawBlock→paintGlyphへ伝播)
      var tScale = OFF.titleScale || 1;
      if (isTwoLineMode()) {
        // 2行モード：最大2行・中央揃え。帯は両行を1枚で囲い、帯と文字は同じオフセット(textTitle)で一緒に動く。
        var f2 = fitTwoLines(top, fT, maxw, U(14));
        var tpx2 = Math.max(1, Math.round(f2.px * tScale));
        y = drawTitleBlockUnified(f2.lines, y, tpx2, U(16) + padExtra, U(6), tScale, OFF.textTitle) + U(4);
      } else {
        var f = fitOneLine(top, fT, maxw, U(14));
        var tpx = Math.max(1, Math.round(f.px * tScale));
        y = drawBlock([f.text], y, tpx, U(16) + padExtra, U(6), 195, OFF.textTitle, tScale) + U(4);
      }
    }
  }

  // ---- 1フレーム描画 ----
  function drawFrame(t) {
    ctx.clearRect(0, 0, W, H);
    // 背景(9:16をそのまま)
    if (bg.readyState >= 2) {
      const vw = bg.videoWidth, vh = bg.videoHeight, tar = W / H, cur = vw / vh;
      let sx = 0, sy = 0, sw = vw, sh = vh;
      if (cur > tar) { sw = vh * tar; sx = (vw - sw) / 2; } else { sh = vw / tar; sy = (vh - sh) / 2; }
      ctx.drawImage(bg, sx, sy, sw, sh, 0, 0, W, H);
    } else { ctx.fillStyle = "#28424a"; ctx.fillRect(0, 0, W, H); }
    // 前景(フェードイン＋微ズーム)
    if (fgImg) {
      const a = t < REVEAL_START ? 0 : (REVEAL_DUR <= 0 ? 1 : easeReveal((t - REVEAL_START) / REVEAL_DUR));
      if (a > 0) {
        // フィット倍率 × ユーザーの拡大率(OFF.imgScale)。プレビューも書き出しも同じ式=見た目と動画が一致する。
        // 幅は安全域(FG_SAFE_W_RATIO=82%)で、高さは FG_MAX_RATIO(92%)でフィット=左右の切れを自動で防ぐ。
        const base = Math.min(W * FG_SAFE_W_RATIO / fgImg.width, H * FG_MAX_RATIO / fgImg.height) * (OFF.imgScale || 1);
        const sc = (a < 1 && FG_ZOOM > 0) ? base * ((1 - FG_ZOOM) + FG_ZOOM * a) : base;
        const fw = fgImg.width * sc, fh = fgImg.height * sc;
        ctx.globalAlpha = a;
        ctx.drawImage(fgImg, (W - fw) / 2, H * (FG_CENTER_Y + OFF.whole + (OFF.imgY || 0)) - fh / 2, fw, fh);  // 軸1：全体オフセット＋画像だけの個別オフセット(OFF.imgY)
        ctx.globalAlpha = 1;
      }
    }
    // テキスト
    drawText(els.author.value.trim(), els.detail.value.trim() || theme().defaultDetail, titleForDraw(els.top.value));
    // 販促ラベル(今なら◯%OFF)=動画フレームへ重ね描き(写真に焼き込まない=Bluesky添付に入らない・Chami2026-07-15)。
    // フレーム基準(W×H)で描くので画像の外(黒帯・余白)にも自由に置ける。
    if (window.Go5PromoLabel && window.Go5PromoLabel.drawOverlay) {
      // 画像と同じ"浮き出てくる"演出のため、前景画像と同じreveal進捗(0..1)を渡す(Chami依頼2026-07-18)。
      var promoReveal = t < REVEAL_START ? 0 : (REVEAL_DUR <= 0 ? 1 : easeReveal((t - REVEAL_START) / REVEAL_DUR)); // 漫画と同一進捗・同一イージング(§6)
      try { window.Go5PromoLabel.drawOverlay(ctx, W, H, promoReveal); } catch (e) {}
    }
  }

  // ---- 背景動画の再生ゲート(リロード頻発対策・2026-08-08) ----
  //   背景動画(#bg)は「動画作成タブが前面 かつ ページが可視」の時だけ再生する。
  //   プレビューは静止フレーム(drawFrame)なので、他タブ閲覧中やアプリ背面では bg を再生する必要が
  //   一切ない。にもかかわらず従来は起動時から loop 再生し続けており、隠れた動画の連続デコードが
  //   iOSのメモリ/電力を食い、タブごと破棄→「戻るたびに再読込」の主因になっていた(Chami報告)。
  //   ★動画作成タブが前面の時の挙動は従来どおり(再生)=作成フローには一切触れない。停止するのは
  //     他タブ/背面の“見えていない”時だけなので、見た目の変化はゼロ。
  function bgShouldPlay_() {
    try {
      if (document.hidden) return false;
      var t = document.documentElement.getAttribute('data-tab') || 'tabMovie';
      return t === 'tabMovie';
    } catch (e) { return true; }
  }
  // ★他タブ/背面では「止める」だけでなく背景動画のデコードバッファ自体を解放する(2026-08-10)。
  //   pause しても src が付いたままだと iOS は復号済みデータを保持し続け、これがタブ丸ごと破棄→
  //   「アプリから戻ると再読込」を誘発するメモリ圧の主因になる。src を外して load() で手放し、
  //   動画作成タブへ戻った瞬間に当該アカウントの背景を貼り直して再生する=作成フロー・見た目は不変。
  function bgReleaseSrc_() {
    try {
      if (!bg.getAttribute("src")) return;
      try { bg.pause(); } catch (e) {}
      bg.removeAttribute("src");
      try { bg.load(); } catch (e) {}   // バッファ解放
    } catch (e) {}
  }
  function bgRestoreSrc_() {
    try {
      var want = (ACCOUNTS[curAccount] && ACCOUNTS[curAccount].bg) || ACCOUNTS.acc1.bg;
      var cur = bg.getAttribute("src") || "";
      if (!cur.endsWith(want)) { bg.src = want; try { bg.load(); } catch (e) {} }
    } catch (e) {}
  }
  function syncBgPlayback_() {
    try {
      if (bgShouldPlay_()) { bgRestoreSrc_(); bg.play().catch(function () {}); }
      else { bgReleaseSrc_(); }
    } catch (e) {}
  }
  window.Go5SyncBgPlayback = syncBgPlayback_;

  // ---- プレビュー(完全表示状態の1枚) ----
  async function preview() {
    await ensureFont();
    // 1フレームだけデコードできれば静止プレビューは描ける。可視・動画作成タブでない限り、
    //   デコード後は即停止して連続再生に戻さない(隠れた動画を回し続けない)。
    if (bg.readyState < 2) { try { await bg.play(); } catch (e) {} }
    drawFrame(DURATION);
    if (!bgShouldPlay_()) { try { bg.pause(); } catch (e) {} }
  }
  window.Go5Preview = preview; // 販促ラベル等がプレビュー再描画を要求するためのフック
  // 二本指ピンチ(promo-label.jsが取得)から前景画像の拡大率を操作するためのフック。
  //   ★旧実装のピンチは canvas に CSS transform を掛けるだけ=プレビューの見た目が拡大するだけで
  //     書き出す動画は一切変わらなかった。Chamiの意図は「動画に使う画像自体の拡大縮小」なので、
  //     ピンチをこのフック経由で OFF.imgScale へ繋ぎ替える(=描画式に入る=動画に反映される)。
  window.Go5ImgScale = {
    get: () => OFF.imgScale || 1,
    set: (k) => { const c = CONTROLS.find((x) => x.key === "imgScale"); if (!c) return; applyC(c, k, true); Store.set(lsk(c.ls), OFF[c.key]); }, // ±ボタンと同じ保存経路(アカウント別キー)
    min: ISCALE_MIN, max: ISCALE_MAX,
  };

  // ---- 画像選択 ----
  // 表示専用の匿名化。(実ファイル名の代わりにランダムな英数字)アップロード/投稿には一切関与しない。
  function anonPhotoLabel_(file) {
    const ext = (file && file.name && /\.[0-9a-z]{1,5}$/i.test(file.name)) ? file.name.slice(file.name.lastIndexOf(".")) : ".jpg";
    const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
    let s = "";
    for (let i = 0; i < 10; i++) s += chars.charAt(Math.floor(Math.random() * chars.length));
    return s + ext;
  }
  function loadForegroundFile_(f) {
    if (!f) return false;
    const loadSeq = ++fgLoadSeq;
    fgFile = f;
    els.photoName.textContent = anonPhotoLabel_(f);
    const url = URL.createObjectURL(f);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      if (loadSeq !== fgLoadSeq) return;
      fgImg = img;
      cachePhotoToStorage_(img);
      preview();
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      if (loadSeq === fgLoadSeq) setStatus("画像を読み込めませんでした(形式をご確認ください)");
    };
    img.src = url;
    return true;
  }
  els.photo.addEventListener("change", () => {
    const f = els.photo.files[0];
    if (f) loadForegroundFile_(f);
  });

  // 前景画像をlocalStorageへ圧縮保存(リロード後に復元するため)。失敗は無害。
  function cachePhotoToStorage_(img) {
    try {
      const MAX = 1280;
      const scale = Math.min(1, MAX / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      localStorage.setItem(K_PHOTO_CACHE, c.toDataURL('image/jpeg', 0.85));
    } catch (e) {}
  }
  // リロード後: localStorageのキャッシュから前景画像を復元(テキストと同じく保持)。
  function restorePhotoCache_() {
    let dataUrl;
    try { dataUrl = localStorage.getItem(K_PHOTO_CACHE); } catch (e) {}
    if (!dataUrl) return;
    const restoreSeq = ++fgLoadSeq;
    const img = new Image();
    img.onload = () => {
      if (restoreSeq !== fgLoadSeq) return;
      fgImg = img;
      // fgFileも復元: Blob変換(動画生成後のDrive/Bluesky添付用。失敗しても描画は動く)。
      try { fetch(dataUrl).then(r => r.blob()).then(b => {
        if (restoreSeq === fgLoadSeq) fgFile = new File([b], 'restored.jpg', { type: 'image/jpeg' });
      }).catch(() => {}); } catch (e) {}
      preview();
    };
    img.src = dataUrl;
  }
  // リロード(iOS Safariのタブ破棄=メモリ退避を含む)後: 入力テキストを復元。前景写真(K_PHOTO_CACHE)と対で、
  // 「戻ってきたら書いた文字が消えていた」を防ぐ。端末別の下書き状態(sync_decisions=local)。
  function restoreTextCache_() {
    try {
      const a = localStorage.getItem('movie_author_text');
      const d = localStorage.getItem('movie_detail_text');
      const t = localStorage.getItem('movie_top_text');
      if (a != null && els.author) els.author.value = a;
      if (d != null && els.detail) els.detail.value = d;
      if (t != null && els.top) els.top.value = t;
    } catch (e) {}
  }
  els.previewBtn.addEventListener("click", preview);
  // テキストは入力確定(フォーカスアウト/Enter)で反映＝IMEを妨げない
  for (const el of [els.author, els.detail, els.top]) {
    el.addEventListener("change", preview);
    el.addEventListener("blur", preview);
  }
  // ④コメントの「2行モード」チェックボックス：保存値を復元し、切替でプレビュー再描画。
  const twoLineEl = document.getElementById("topTwoLine");
  if (twoLineEl) {
    try { twoLineEl.checked = localStorage.getItem("movie_two_line") === "1"; } catch (e) {}
    const syncTopRows = () => { if (els.top && els.top.tagName === "TEXTAREA") els.top.rows = twoLineEl.checked ? 2 : 1; };
    syncTopRows(); // 保存状態に応じて①行/②行のテキストボックスに
    twoLineEl.addEventListener("change", () => {
      try { localStorage.setItem("movie_two_line", twoLineEl.checked ? "1" : "0"); } catch (e) {}
      syncTopRows();
      preview();
    });
  }
  // ④コメントは textarea 化＝入力中(改行含む)も即プレビュー反映。(2行モードの改行が2行目に出るのを確認しやすく)
  els.top.addEventListener("input", preview);

  // ①作者の「2行モード」チェックボックス(コメントと同仕様)：保存値を復元し、切替でプレビュー再描画。
  const authorTwoLineEl = document.getElementById("authorTwoLine");
  if (authorTwoLineEl) {
    try { authorTwoLineEl.checked = localStorage.getItem("movie_author_two_line") === "1"; } catch (e) {}
    const syncAuthorRows = () => { if (els.author && els.author.tagName === "TEXTAREA") els.author.rows = authorTwoLineEl.checked ? 2 : 1; };
    syncAuthorRows(); // 保存状態に応じて①行/②行のテキストボックスに
    authorTwoLineEl.addEventListener("change", () => {
      try { localStorage.setItem("movie_author_two_line", authorTwoLineEl.checked ? "1" : "0"); } catch (e) {}
      syncAuthorRows();
      preview();
    });
  }
  // 作者も textarea 化＝入力中(改行含む)も即プレビュー反映。
  els.author.addEventListener("input", preview);

  // 入力テキストを即localStorageへ退避(iOS Safariがタブを破棄→戻ると勝手にリロードされ、
  // 従来は作者名/誘導文/④コメントが消えていた=「ヒヤッとする」の正体)。前景写真の退避と対で「戻っても消えない」を作る。
  els.author.addEventListener("input", function () { try { localStorage.setItem("movie_author_text", els.author.value); } catch (e) {} });
  els.top.addEventListener("input", function () { try { localStorage.setItem("movie_top_text", els.top.value); } catch (e) {} });
  els.detail.addEventListener("input", function () { try { localStorage.setItem("movie_detail_text", els.detail.value); } catch (e) {} });
  els.detail.addEventListener("change", function () { try { localStorage.setItem("movie_detail_text", els.detail.value); } catch (e) {} });

  function setStatus(m) { els.status.textContent = m; }
  function sanitize(t) {
    t = (t || "").trim().replace(/[\\/:*?"<>|\r\n\t]/g, "").replace(/^\.+|\.+$/g, "");
    return (t.slice(0, 60) || "video");
  }
  // 保存ファイル名用：定型投稿タグを非表示にし、★改行は無視して連続した文字列にする。(2行モードでも1つの名前に)
  //   このtitleForBurnの結果は投稿記録(スプレッドシートの題名(コメント)列)の題名にもなる(video-created
  //   イベントのtitleとしてbluesky.jsへ渡る)ため、記録に改行・余分な空白を残さないことが重要(Chami指摘2026-07-23)。
  //   ★行ごとにtrimしてから結合する。旧実装は単純に\nを除去するだけで、行末尾のスペースがそのまま
  //   結合部に残る余地があった(例「行1 \n行2」→「行1 行2」は良いが「行1  \n  行2」→二重空白が残る)。
  //   行ごとtrim→区切り無しで結合→万一残った連続空白を1つに圧縮→全体trim、の順で確実に1行・素の文字列にする。
  function titleForBurn(s) {
    var t = String(s == null ? "" : s)
      .split("\n").map(function (line) { return line.trim(); }).join("")
      .replace(/[ \t　]{2,}/g, " ").trim();
    return (typeof Go5Util !== "undefined" && Go5Util.stripPostTags) ? Go5Util.stripPostTags(t) : t;
  }
  // 動画へ焼く描画用：定型投稿タグを除去しつつ改行(\n)は保持。(2行モードの行分割に使う)
  function titleForDraw(s) {
    var t = String(s == null ? "" : s);
    if (typeof Go5Util !== "undefined" && Go5Util.stripPostTags) {
      return t.split("\n").map(function (line) { return Go5Util.stripPostTags(line); }).join("\n");
    }
    return t;
  }
  function pickMime() {
    const c = ["video/mp4;codecs=avc1.42E01E", "video/mp4", "video/webm;codecs=vp9", "video/webm"];
    for (const m of c) if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
    return "";
  }

  // ---- 動画作成 ----
  async function make() {
    // ★ドラフトで作成の意図を「作成イベント」に載せる(Chami報告2026-08-11「ドラフトで作成が今すぐ投稿の挙動になる」)。
    //   従来は draftMakeBtn が bskyEnable を外すだけで、Bluesky側の maybeInheritRebuild_(自動投稿ON/OFFに
    //   関わらず走るリビルド引き継ぎ)や他の購読者へは「これはドラフトだ」が伝わらず、投稿/確認フローへ漏れていた。
    //   ここで一度だけフラグを消費して detail.draft に確定=購読者全員が確実に投稿を抑止できる(早期returnでも滞留しない)。
    var isDraft = !!window.__go5DraftPending; window.__go5DraftPending = false;
    if (!fgImg) { setStatus("先に写真を選んでください。"); return; }
    if (!window.MediaRecorder) { setStatus("この端末は動画書き出しに未対応です。(iOS15以降のSafari推奨)"); return; }
    // 狙い・コメント型は生成前の必須選択＝未設定のまま投稿されると分析を汚すため入口で止める。(Chami指定2026-07-14)
    // ★テストモード時は必須にしない(Chami指定2026-07-19)。テストは記録シートに残らない
    //   (bluesky.js の testMode 分岐で除外される)ので、そもそも分析を汚さない。
    //   動作確認のたびに狙いとコメント型を選ばされるのは手間だけで得るものが無い。
    const testChk = document.getElementById("testMode");
    const isTestRun = !!(testChk && testChk.checked);
    const goalSel = document.getElementById("movieGoal"), cmtSel = document.getElementById("movieCmtType");
    const missSel = [];
    if (!isTestRun && goalSel && !goalSel.value) missSel.push("狙い");
    if (!isTestRun && cmtSel && !cmtSel.value) missSel.push("コメント型");
    if (missSel.length) {
      setStatus("⚠ " + missSel.join("と") + "が未選択です。選択してから動画を作成してください。(生成前の必須項目)");
      const tgt = (goalSel && !goalSel.value) ? goalSel : cmtSel;
      try { tgt.scrollIntoView({ behavior: "smooth", block: "center" }); tgt.focus(); } catch (e) {}
      return;
    }
    await ensureFont();
    // ★「押されたボタンだけ」を作成中の見た目にする(Chami報告2026-08-12「ドラフトで作成が今すぐ作成・投稿の
    //   ボタンが押されたような挙動になる」)。従来は isDraft でも常に els.makeBtn(＝今すぐ作成・投稿)を disabled に
    //   していたため、ドラフトを押しても隣の「今すぐ作成・投稿」が灰色化＝押された見た目になっていた。
    //   再入防止は _making フラグで持ち、ボタンの disabled 表示と切り離す(ドラフト中に makeBtn を触っても _making で弾く)。
    // ★再入は弾くが「黙って」弾かない=最悪の事故は沈黙(§3 可用性は喋る側へ倒す)。前回の作成が異常終了して
    //   _making が立ったまま(MediaRecorderのonstop不達など)固着すると、以後「ドラフトで作成」を押しても
    //   ここで無言 return され、動画も出ず遷移もしない=「動画が生成されない/遷移しない」に化ける
    //   (Chami報告2026-08-13・月詠みで再現)。①busyなら理由を必ず画面に出す ②20秒(録画5秒+書出の数倍)を
    //   超えて立ったままなら stale とみなし奪い返す=固着で永久に無反応にならないようにする。
    if (_making) {
      if (!_makingAt || (performance.now() - _makingAt) < 20000) {
        setStatus(isDraft ? "前の作成がまだ終わっていません。数秒待ってから、もう一度「ドラフトで作成」を押してください。"
                          : "前の作成がまだ終わっていません。数秒お待ちください。");
        return;
      }
      try { if (window.console && console.warn) console.warn("[go5] _making が20秒以上固着=stale。作成を奪い返す"); } catch (e) {}
    }
    _making = true; _makingAt = performance.now();
    const runId = ++_makeRunSeq;
    var activeBtn = isDraft ? document.getElementById("draftMakeBtn") : els.makeBtn;
    var activeLabel = activeBtn ? activeBtn.textContent : "";
    if (activeBtn) { activeBtn.disabled = true; activeBtn.textContent = isDraft ? "📦 作成中…" : "作成中…"; }
    els.resultArea.hidden = true;
    setStatus(isDraft ? "ドラフトを作成中…(約5秒録画します。画面はそのままで)" : "動画を作成中…(約5秒録画します。画面はそのままで)");

    try {
      bg.currentTime = 0;
      try { await bg.play(); } catch (e) {}
      const mime = pickMime();
      const stream = cv.captureStream(FPS);
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 8_000_000 } : undefined);
      const chunks = [];
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      let stopError = null;
      const stopped = new Promise((resolve, reject) => {
        rec.onstop = resolve;
        rec.onerror = (e) => { stopError = (e && e.error) || new Error("MediaRecorder error"); reject(stopError); };
      });

      const t0 = performance.now();
      // 1秒ごとにチャンクを確保する。stop時の最後のdataavailable 1回だけに依存すると、
      // iOS Safariの間欠不達で空Blobになっても気付けなかった。
      rec.start(1000);
      await new Promise((resolve) => {
        const loop = () => {
          const t = (performance.now() - t0) / 1000;
          drawFrame(Math.min(t, DURATION));
          if (t >= DURATION) return resolve();
          requestAnimationFrame(loop);
        };
        loop();
      });
      try { if (rec.state === "recording") rec.requestData(); } catch (e) {}
      if (rec.state !== "inactive") rec.stop();
      let stopTimer = null;
      const stopTimeout = new Promise((resolve, reject) => {
        stopTimer = setTimeout(() => reject(new Error("動画書き出しの完了応答がありません。もう一度お試しください。")), 12000);
      });
      try { await Promise.race([stopped, stopTimeout]); } finally { if (stopTimer) clearTimeout(stopTimer); }
      if (stopError) throw stopError;
      if (runId !== _makeRunSeq) throw new Error("古い作成処理の完了を破棄しました。もう一度お試しください。");

      const type = mime || "video/webm";
      const candidateBlob = new Blob(chunks, { type });
      const integrity = window.Go5VideoIntegrity;
      const sizeOk = integrity && integrity.isUsableBlob
        ? integrity.isUsableBlob(candidateBlob)
        : candidateBlob.size >= 16 * 1024;
      if (!sizeOk) throw new Error("動画データが空または不完全でした。ドラフトには保存していません。もう一度お試しください。");
      const playable = integrity && integrity.probePlayable
        ? await integrity.probePlayable(candidateBlob, { timeoutMs: 10000 })
        : true;
      if (!playable) throw new Error("動画を再生確認できなかったため、壊れたドラフトは保存しませんでした。もう一度お試しください。");
      if (runId !== _makeRunSeq) throw new Error("古い作成処理の完了を破棄しました。もう一度お試しください。");
      lastBlob = candidateBlob;
      const ext = type.includes("mp4") ? "mp4" : "webm";
      lastName = sanitize(titleForBurn(els.top.value)) + "." + ext;

      const url = URL.createObjectURL(lastBlob);
      els.result.src = url;
      els.dl.href = url; els.dl.download = lastName;
      // ★ドラフト作成時は動画作成タブに結果(プレビュー＋動画DL)を出さない(Chami依頼2026-08-13)。
      //   ドラフトタブ内で動画をDLできるので動画作成タブ側の導線は不要＝生成後はドラフトタブへ自動遷移する(stock.js)。
      if (!isDraft) {
        els.resultArea.hidden = false;
      }
      setStatus((isDraft ? "✅ ドラフトを作成しました：" : "✅ 完成しました：") + lastName + (ext === "webm" ? "(この端末ではwebm形式)" : ""));
      if (!isDraft) els.resultArea.scrollIntoView({ behavior: "smooth" });
      // 完成を通知。(Bluesky自動投稿などが購読)この時点で Canvas は最終フレームを保持している。
      // 一本道運用の背骨＝安定動画IDを“作成時(投稿前)”に発番し、購読側(Drive保存・記録)へ串刺しで渡す。
      var account = (typeof window.getCurrentAccount === "function") ? window.getCurrentAccount() : "acc1";
      var testEl = document.getElementById("testMode");
      var isTest = !!(testEl && testEl.checked);   // テストモード＝記録しない(IDに test- 接頭辞)
      var videoId = (window.IdGen && window.IdGen.makeVideoId) ? window.IdGen.makeVideoId(account, new Date(), { test: isTest }) : "";
      // ★titleは titleForBurn で改行を潰してから配る(Chami指定2026-07-19
      //   「2行モードで改行しても、投稿など他の箇所では改行や空白を挟まない」)。
      //   改行が要るのは**Canvasの行分割だけ**(titleForDraw)で、購読側は全て1行の題名を欲しがる:
      //   Bluesky alt / GAS記録のtitle / 端末予約 / Drive のフォルダ名・ファイル名。
      //   ★空白に置換しない=詰めて連結する(Chami明示「改行や空白を挟まない」)。
      //   ここ1箇所で潰すことで購読側6経路すべてに効く(個別対処だと足し忘れが必ず出る)。
      document.dispatchEvent(new CustomEvent("video-created", { detail: { title: titleForBurn(els.top.value), blob: lastBlob, name: lastName, videoId: videoId, account: account, test: isTest, sourceImageFile: fgFile, draft: isDraft } }));
    } catch (e) {
      setStatus("作成に失敗しました：" + e.message);
    } finally {
      // stale奪回で新しい作成が始まっている場合、旧処理のfinallyが新処理のbusy表示を解除しない。
      if (runId === _makeRunSeq) {
        _making = false;
        if (activeBtn) { activeBtn.disabled = false; activeBtn.textContent = activeLabel; }
      }
    }
  }

  els.makeBtn.addEventListener("click", make);

  // ---- 保存 / 共有 ----
  els.saveBtn.addEventListener("click", async () => {
    if (!lastBlob) return;
    const file = new File([lastBlob], lastName, { type: lastBlob.type });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file], title: lastName }); return; }
      catch (e) { /* キャンセル等 */ }
    }
    els.dl.click();
  });

  // ---- 設定の保存・復元(localStorage 汎用ヘルパ：アフィID等 将来の設定値もこれで保存できる) ----
  const Store = {
    getNum(key) { try { const v = localStorage.getItem(key); const n = v === null ? NaN : parseFloat(v); return isNaN(n) ? null : n; } catch (e) { return null; } },
    set(key, val) { try { localStorage.setItem(key, String(val)); } catch (e) {} },
    remove(key) { try { localStorage.removeItem(key); } catch (e) {} },
  };

  // ---- 位置調整。(＋/−ボタン式・プレビュー横)各コントロールは独立。----
  // 値は基準フレーム高さ比、localStorage に保存・自動復元。legacy は旧バージョンの保存キー。(移行用)
  function flashBtn(btn, msg) {
    if (!btn) return;
    if (!btn.dataset.label) btn.dataset.label = btn.textContent;
    btn.textContent = msg;
    setTimeout(() => { btn.textContent = btn.dataset.label; }, 1500);
  }
  // m/p/v = マイナス／プラスボタン／値表示の要素id。step = 1タップの変化量。signed = ＋符号と±方向。
  const CONTROLS = [
    { key: "whole",      m: "wholeMinus", p: "wholePlus", v: "wholeVal", ls: "preview_offset_y",    lsDef: "preview_offset_y_default",    legacy: "v_offset",       def: VOFF_DEFAULT, min: 0,       max: VOFF_MAX,    step: 0.0025, signed: false },
    { key: "textAuthor", m: "taMinus",    p: "taPlus",    v: "taVal",    ls: "preview_text_author", lsDef: "preview_text_author_default", legacy: null,             def: 0,            min: ROW_MIN, max: ROW_MAX,     step: 0.0025, signed: true  },
    { key: "textDetail", m: "tdMinus",    p: "tdPlus",    v: "tdVal",    ls: "preview_text_detail", lsDef: "preview_text_detail_default", legacy: null,             def: 0,            min: ROW_MIN, max: ROW_MAX,     step: 0.0025, signed: true  },
    { key: "textTitle",  m: "ttMinus",    p: "ttPlus",    v: "ttVal",    ls: "preview_text_title",  lsDef: "preview_text_title_default",  legacy: null,             def: 0,            min: ROW_MIN, max: ROW_MAX,     step: 0.0025, signed: true  },
    { key: "bandPad",    m: "bpMinus",    p: "bpPlus",    v: "bpVal",    ls: "preview_band_pad",    lsDef: "preview_band_pad_default",    legacy: null,             def: 0,            min: 0,       max: BANDPAD_MAX, step: 0.0025, signed: false },
    { key: "rowGap",     m: "rgMinus",    p: "rgPlus",    v: "rgVal",    ls: "preview_row_gap",     lsDef: "preview_row_gap_default",     legacy: null,             def: 0,            min: 0,       max: ROWGAP_MAX,  step: 0.005,  signed: false },
    { key: "titleScale", m: "tsMinus",    p: "tsPlus",    v: "tsVal",    ls: "preview_title_scale", lsDef: "preview_title_scale_default", legacy: null,             def: 1,            min: TSCALE_MIN, max: TSCALE_MAX, step: 0.05,   signed: false },
    { key: "imgY",       m: "iyMinus",    p: "iyPlus",    v: "iyVal",    ls: "preview_img_y",       lsDef: "preview_img_y_default",       legacy: null,             def: 0,            min: IMG_MIN, max: IMG_MAX,     step: 0.0025, signed: true  },
    { key: "imgScale",   m: "isMinus",    p: "isPlus",    v: "isVal",    ls: "preview_img_scale",   lsDef: "preview_img_scale_default",   legacy: null,             def: 1,            min: ISCALE_MIN, max: ISCALE_MAX, step: 0.05,   signed: false },
  ];
  function clampC(c, v) {
    if (isNaN(v)) v = c.def;
    v = Math.round(v / c.step) * c.step;          // step に丸めて浮動小数の誤差を防ぐ
    v = Math.round(v * 100000) / 100000;
    return Math.min(c.max, Math.max(c.min, v));
  }
  function ctlLabel(c) {
    const el = $(c.v); if (!el) return;
    const sign = (c.signed && OFF[c.key] >= 0) ? "+" : "";
    el.textContent = sign + (OFF[c.key] * 100).toFixed(1) + "%";
  }
  function applyC(c, v, redraw) {
    OFF[c.key] = clampC(c, v);
    ctlLabel(c);
    if (redraw) preview();
  }

  // ---- レイアウト設定をアカウント別に(Task 8d)----
  // 位置調整値は preview_*__acc1 / preview_*__acc2 に保存し、アカウントごとに独立。
  // 旧来の共通キー(preview_*)は一度だけ両アカウントへ複製して引き継ぐ。(移行・冪等)
  function lsk(base) { return base + "__" + curAccount; }
  (function migrateLayoutOnce() {
    try { if (localStorage.getItem("layout_acct_split_migrated") === "1") return; } catch (e) { return; }
    // 旧共通値(無ければ旧バージョンキー)を両アカウントの現在値へ、旧共通既定値を両既定値へ複製。
    ["acc1", "acc2"].forEach((a) => {
      CONTROLS.forEach((c) => {
        const curKey = c.ls + "__" + a, defKey = c.lsDef + "__" + a;
        const liveOld = Store.getNum(c.ls); const legacyOld = c.legacy ? Store.getNum(c.legacy) : null;
        const live = liveOld != null ? liveOld : legacyOld;
        if (Store.getNum(curKey) == null && live != null) Store.set(curKey, live);
        const defOld = Store.getNum(c.lsDef);
        if (Store.getNum(defKey) == null && defOld != null) Store.set(defKey, defOld);
      });
    });
    // 旧共通キー・旧バージョンキーは退役。(per-account リセット後に値が蘇らないように)
    CONTROLS.forEach((c) => { Store.remove(c.ls); Store.remove(c.lsDef); if (c.legacy) Store.remove(c.legacy); });
    try { localStorage.setItem("layout_acct_split_migrated", "1"); } catch (e) {}
  })();

  // 現在アカウントの保存値を OFF に反映。優先順位：当該acc現在値 → 当該acc既定値 →
  // 共通(旧・通常は退役済) → 旧バージョンキー → 工場既定。
  function loadOffsets(redraw) {
    CONTROLS.forEach((c, i) => {
      const cur = Store.getNum(lsk(c.ls)), def = Store.getNum(lsk(c.lsDef));
      const sharedCur = Store.getNum(c.ls), sharedDef = Store.getNum(c.lsDef);
      const legacy = c.legacy ? Store.getNum(c.legacy) : null;
      const v = cur != null ? cur : (def != null ? def : (sharedCur != null ? sharedCur :
        (sharedDef != null ? sharedDef : (legacy != null ? legacy : c.def))));
      applyC(c, v, !!redraw && i === CONTROLS.length - 1);  // 最後の1回だけ再描画
    });
  }

  CONTROLS.forEach((c) => {
    const mb = $(c.m), pb = $(c.p);
    if (mb) mb.addEventListener("click", () => { applyC(c, OFF[c.key] - c.step, true); Store.set(lsk(c.ls), OFF[c.key]); });
    if (pb) pb.addEventListener("click", () => { applyC(c, OFF[c.key] + c.step, true); Store.set(lsk(c.ls), OFF[c.key]); });
  });
  loadOffsets(false); // 起動時の初期復元(このあとの setAccount でも再読込される)

  // 「既定値に保存」：現アカウントの全コントロール現在値を既定値として確定
  if (els.voffSaveDefault) els.voffSaveDefault.addEventListener("click", () => {
    CONTROLS.forEach((c) => { Store.set(lsk(c.lsDef), OFF[c.key]); Store.set(lsk(c.ls), OFF[c.key]); });
    flashBtn(els.voffSaveDefault, "✓ 既定値に保存しました");
  });

  // 「リセット」：現アカウントの保存値だけ消し、工場既定に戻す(他アカウントには影響しない)
  if (els.voffReset) els.voffReset.addEventListener("click", () => {
    CONTROLS.forEach((c) => { Store.remove(lsk(c.ls)); Store.remove(lsk(c.lsDef)); });
    CONTROLS.forEach((c, i) => applyC(c, c.def, i === CONTROLS.length - 1));  // 最後の1回だけ再描画
    flashBtn(els.voffReset, "✓ リセットしました");
  });

  // ---- アカウント切替 ----
  function setAccount(id) {
    if (!ACCOUNTS[id]) id = "acc1";
    curAccount = id;
    try { localStorage.setItem("current_account", id); } catch (e) {}
    // 誘導文が未編集(空 or いずれかのテーマ既定文)なら、当該テーマの既定文へ追従。ユーザーが書き換えた文面は尊重して残す。
    if (els.detail) {
      const known = Object.keys(THEME).map((k) => THEME[k].defaultDetail).concat([DEFAULT_DETAIL]);
      const cur = els.detail.value.trim();
      if (cur === "" || known.indexOf(cur) >= 0) els.detail.value = theme().defaultDetail;
    }
    if (els.acctBtn1) els.acctBtn1.classList.toggle("active", id === "acc1");
    if (els.acctBtn2) els.acctBtn2.classList.toggle("active", id === "acc2");
    // ★背景動画は「動画作成タブが前面の時」だけメモリに載せる(2026-08-10・リロード緩和)。
    //   他タブ閲覧中にアカウントを切替えても動画は読み込まない=そのページを軽いままにする。
    //   動画作成タブへ入る時に bgRestoreSrc_ が当該アカウントの背景を貼り直す。
    const want = ACCOUNTS[id].bg;
    if (bgShouldPlay_()) {
      const cur = bg.getAttribute("src") || "";
      if (!cur.endsWith(want)) { bg.src = want; try { bg.load(); } catch (e) {} }
      bg.play().catch(() => {});
    }
    if (typeof loadOffsets === "function") loadOffsets(false); // このアカウントのレイアウト設定を反映
    preview();
    document.dispatchEvent(new CustomEvent("account-changed", { detail: { id } }));
  }
  window.getCurrentAccount = () => curAccount;

  // 下書き機能(drafts.js)向け：Fileを #photo の実際のFileListにセットし、通常の写真選択と
  // 同じ経路(changeイベント)で反映する。こうすることで、以後のBluesky添付/Drive保存等が
  // 参照する photo.files[0] も正しく更新される。(プレビューだけを書き換えるより確実)
  window.Go5ClearForeground = () => {
    const clearSeq = ++fgLoadSeq;
    fgImg = null;
    fgFile = null;
    if (els.photo) {
      try { els.photo.value = ''; } catch (e) {}
    }
    if (els.photoName) els.photoName.textContent = '未選択';
    try { localStorage.removeItem(K_PHOTO_CACHE); } catch (e) {}
    preview();
    return clearSeq;
  };

  // iOS SafariなどでDataTransfer/FileList代入が使えない場合も、内部の前景FileとCanvasへ直接反映する。
  window.Go5ForegroundFile = () => fgFile;
  window.Go5SetForegroundFile = (file, expectedSeq) => {
    if (!file || !els.photo) return false;
    // Reject a delayed candidate fetch if the user already selected another image.
    if (expectedSeq != null && expectedSeq !== fgLoadSeq) return false;
    try {
      if (typeof DataTransfer !== "undefined") {
        const dt = new DataTransfer();
        dt.items.add(file);
        els.photo.files = dt.files;
        if (els.photo.files && els.photo.files.length) {
          els.photo.dispatchEvent(new Event("change", { bubbles: true }));
          return true;
        }
      }
    } catch (e) {}
    return loadForegroundFile_(file);
  };

  // 販促ラベル(promo-label.js)向け: プレビュー完全表示時(t=DURATION・ズーム完了)の前景写真の
  // キャンバス内矩形。タッチ座標→写真内座標の変換に使う。(drawFrameと同じ式で計算)
  window.Go5PhotoRect = function () {
    if (!fgImg) return null;
    const base = Math.min(W * FG_SAFE_W_RATIO / fgImg.width, H * FG_MAX_RATIO / fgImg.height) * (OFF.imgScale || 1); // drawFrameと同式(幅=安全域82%・拡大率込み)
    const fw = fgImg.width * base, fh = fgImg.height * base;
    return {
      x: (W - fw) / 2,
      y: H * (FG_CENTER_Y + OFF.whole + (OFF.imgY || 0)) - fh / 2,
      w: fw, h: fh,
      imgW: fgImg.width, imgH: fgImg.height,
      cvW: W, cvH: H
    };
  };

  // ---- 初期化 ----
  bg.addEventListener("loadeddata", preview);
  restorePhotoCache_(); // リロード後の前景画像復元
  restoreTextCache_();   // リロード後の入力テキスト復元(setAccountの誘導文既定追従より前=書いた文面を尊重して残す)
  ensureFont().then(preview);
  // フォント確定後にもう一度描画(初回がフォールバックフォントの計測で描かれてしまうのを防ぐ＝
  // プレビューと書き出しで measureText 由来の自動縮小・折返しがズレないようにする保険)。
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => { fontReady = true; preview(); });
  }
  // iOSはミュート自動再生が許可されるが、念のため初回操作でも再生を促す。
  //   ★ただしゲートを尊重する=動画作成タブが前面でない/背面の時は再生しない(隠れた動画を回さない)。
  const kick = () => { syncBgPlayback_(); document.removeEventListener("touchstart", kick); document.removeEventListener("click", kick); };
  document.addEventListener("touchstart", kick, { once: true, passive: true });
  document.addEventListener("click", kick, { once: true });
  // タブ切替(affiliate.js が documentElement の data-tab を切替える)と可視状態の変化に追従して、
  //   背景動画の再生/停止を同期する。これが「リロード頻発」対策の本体。
  document.addEventListener("visibilitychange", syncBgPlayback_);
  try {
    var _bgTabObs = new MutationObserver(syncBgPlayback_);
    _bgTabObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-tab"] });
  } catch (e) {}

  // ---- プレビューを「YouTube実機の見え方」に合わせる(左右各9%が切れる=中央82%幅・全高だけを表示) ----
  //   YouTube Shortsは縦長端末で動画を画面高いっぱいに拡大表示し、左右各約9%を切り落とす(cover)。
  //   そのため実機の再生では中央82%幅・全高だけが見え、全画面のプレビューより"拡大して"見える。
  //   ここではプレビューの「表示」だけを実機の可視域に合わせる=書き出す動画・キャンバス実体(1080×1920)は
  //   一切変えない(captureStreamは実体を録るためCSSの表示加工は録画に影響しない=§3のプレビュー/書き出し一致は不変)。
  //   Chami依頼2026-08-15「実際の動画に動画作成タブ内のプレビューを合わせたい」。
  function applyYtFrame_(on) {
    var box = document.querySelector('.canvas-box');
    if (!box || !cv) return;
    // まず前回の適用分を必ず解除してから素の表示サイズを測る(解除→測定→適用=回転/リサイズでも安定)。
    cv.style.position = ''; cv.style.left = ''; cv.style.top = ''; cv.style.transform = '';
    cv.style.width = ''; cv.style.height = ''; cv.style.maxWidth = ''; cv.style.maxHeight = '';
    box.style.position = ''; box.style.overflow = ''; box.style.width = ''; box.style.height = '';
    if (!on) return;
    var r = cv.getBoundingClientRect();
    var w = r.width, h = r.height;
    if (!w || !h) return; // 動画作成タブが非表示など未レイアウト時は何もしない(戻った時に再適用)。
    // キャンバスの表示サイズを固定して絶対配置し、外側(左右各9%)を枠でクリップ=中央82%幅・全高が見える。
    cv.style.width = w + 'px'; cv.style.height = h + 'px'; cv.style.maxWidth = 'none'; cv.style.maxHeight = 'none';
    cv.style.position = 'absolute'; cv.style.left = '50%'; cv.style.top = '0'; cv.style.transform = 'translateX(-50%)';
    box.style.position = 'relative'; box.style.overflow = 'hidden';
    box.style.width = (w * FG_SAFE_W_RATIO) + 'px'; box.style.height = h + 'px';
  }
  var _ytFrameCb = $('pvYtFrame');
  if (_ytFrameCb) {
    var _ytSaved = null; try { _ytSaved = localStorage.getItem('preview_yt_frame'); } catch (e) {}
    _ytFrameCb.checked = (_ytSaved === null) ? true : (_ytSaved === '1'); // 既定ON(実機の見え方を初期表示)
    var _ytApply = function () { applyYtFrame_(_ytFrameCb.checked); };
    _ytFrameCb.addEventListener('change', function () {
      try { localStorage.setItem('preview_yt_frame', _ytFrameCb.checked ? '1' : '0'); } catch (e) {}
      _ytApply();
    });
    window.addEventListener('resize', function () { if (_ytFrameCb.checked) { applyYtFrame_(false); applyYtFrame_(true); } });
    window.addEventListener('orientationchange', function () { if (_ytFrameCb.checked) setTimeout(function () { applyYtFrame_(false); applyYtFrame_(true); }, 200); });
    // タブ復帰(data-tab→tabMovie)でキャンバスが再レイアウトされたら測り直す。
    try { new MutationObserver(function () { if (_ytFrameCb.checked) { applyYtFrame_(false); applyYtFrame_(true); } }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-tab"] }); } catch (e) {}
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { setTimeout(_ytApply, 0); });
    setTimeout(_ytApply, 60);
  }

  // ---- アカウント切替ボタン配線・起動時復元 ----
  if (els.acctBtn1) els.acctBtn1.addEventListener("click", () => setAccount("acc1"));
  if (els.acctBtn2) els.acctBtn2.addEventListener("click", () => setAccount("acc2"));
  let savedAcct = "acc1";
  try { savedAcct = localStorage.getItem("current_account") || "acc1"; } catch (e) {}
  setAccount(savedAcct);
  // 起動直後に、復元されたタブ(動画作成でないこともある)に合わせて背景動画の再生要否を確定。
  //   例:前回タブが投稿履歴なら、起動時に bg を回し始めない=最初から軽い。
  syncBgPlayback_();
})();
