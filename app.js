/* 5秒動画メーカー（クライアントサイド合成）
   背景動画＋前景画像＋テキスト3段を Canvas で描画し、MediaRecorder で録画して動画化する。
   仕上がりはデスクトップ版 composite.py に合わせている。 */
(() => {
  "use strict";

  // ---- 仕上がり設定（composite.py / jobs.json と統一） ----
  // 基準フレーム＝唯一の基準座標系（9:16）。位置・サイズ・余白・行間は全てこの値への比率で表現する。
  // プレビューも書き出しも同じ Canvas(=この解像度) に描くため、画面幅に関係なく完全に一致する。
  const W = 1080, H = 1920;         // 基準フレーム解像度（ここを変えれば出力解像度が変わる／レイアウトは比率維持）
  const DURATION = 5, FPS = 30;
  const REVEAL_START = 0.5, REVEAL_DUR = 2.0;
  const FG_MAX_RATIO = 0.92, FG_ZOOM = 0.04, FG_CENTER_Y = 0.55;
  const DEFAULT_DETAIL = "作品の詳細は右上の：から説明";

  // 旧来 1280px フレーム基準で決めた絶対px定数（余白・行間・縁取り下限など）を、
  // 現在の基準フレーム高さに合わせて比率換算する。基準解像度を変えてもレイアウトが崩れない。
  const U = (v) => v * H / 1280;

  // 構成全体（上部テキストブロック＋前景の漫画ページ）の縦位置オフセット。
  // 基準フレーム高さに対する比率（0〜VOFF_MAX）。テキスト開始Yと前景中心Yに同じだけ加算するため、
  // 両者の相対関係（中央揃え・行間）は崩れない。スライダーで微調整する。
  const VOFF_DEFAULT = 0.02, VOFF_MAX = 0.05;   // 全体（文字＋帯＋漫画）を下へ
  const ROW_MIN = -0.03, ROW_MAX = 0.03;        // 段別（文字・帯とも）上下双方向（＋下／−上）
  const BANDPAD_MAX = 0.02;                      // 黒帯の余白（厚み）を追加できる上限（基準フレーム高さ比）
  const ROWGAP_MAX = 0.04;                       // 段と段の追加スペース上限（基準フレーム高さ比）
  const TSCALE_MIN = 0.7, TSCALE_MAX = 1.5;      // 大タイトルの拡大率（1.0＝従来。影・帯は文字サイズ比なので連動）
  const IMG_MIN = -0.15, IMG_MAX = 0.15;         // 前景画像だけの上下オフセット（基準フレーム高さ比・文字とは独立）

  // 縦オフセット（すべて基準フレーム高さ比）。段別は「文字」と「帯」を別個に持ち、互いに独立。
  // 文字オフセットはその段の文字描画位置にのみ加算し、段の送り（次段Y）には影響させない＝他段は不動。
  const OFF = {
    whole: VOFF_DEFAULT,
    textAuthor: 0, textDetail: 0, textTitle: 0,  // 各段の「文字」だけ
    bandAuthor: 0, bandDetail: 0, bandTitle: 0,  // 各段の「黒帯」だけ
    bandPad: 0,                                  // 黒帯の余白（全段共通で厚みを足す）
    rowGap: 0,                                   // 段と段の間に足す縦スペース
    titleScale: 1,                               // 大タイトルの拡大率（1.0＝従来。影・帯は px 比で自動連動）
    imgY: 0,                                      // 前景画像だけの上下オフセット（文字・帯は不動）
  };

  const $ = (id) => document.getElementById(id);
  const cv = $("cv"), ctx = cv.getContext("2d");
  const bg = $("bg");

  // ---- アカウント定義（背景動画の切替。Bluesky/YouTube個別資格情報は保留＝acc1共有を流用）----
  const ACCOUNTS = {
    acc1: { label: "月読み色恋劇場", bg: "assets/bg_main.mp4" },
    acc2: { label: "宵桜艶帖～Yoizakura Tsuyacho～", bg: "assets/bg_account2.mp4" },
  };
  let curAccount = "acc1";

  // ---- アカウント別テンプレ・テーマ（派生プリセット）----
  // 変えるのは「表示テキストと装飾色」のみ。レイアウト・座標・送り・生成フローは共通（§3座標規約は不変）。
  // acc1＝従来値そのまま（見た目不変）。acc2＝桜ピンクの派生（温白文字＋桜グロー＋ダークプラム帯）。
  const THEME = {
    acc1: {
      authorPrefix: "作者：",
      defaultDetail: DEFAULT_DETAIL,        // "作品の詳細は右上の：から説明"（：→⋮、説明→≡説明）
      detailMenu: true,                     // 誘導文の「説明」前に ≡（ハンバーガー）を出す
      textFill: "#F5E6B8",                  // 月光金（文字）
      stroke: "rgba(0,0,0,1)",              // soft時は未使用
      bandRGB: "46,64,104",                 // #2E4068 宵藍の帯
      bandAlpha255: 204,                    // 不透明度80%（acc1のみ固定＝#2E4068CC相当）
      soft: true,                           // 淡金のごく弱いグロー＋可読性用の暗い影（黒い太縁は使わない）
      glowSoft: "rgba(245,230,184,0.15)",   // 淡金グロー（ほぼ無し・ぼかし6px相当）
      darkShadow: "rgba(0,0,0,0.5)",        // 可読性用の暗い影（0 1px 2px 相当）
      iconFill: "#F5E6B8", iconHalo: "rgba(46,64,104,0.95)",  // アイコンも月光金＋宵藍で統一
    },
    acc2: {
      authorPrefix: "引用：",               // A：作者：→引用：
      defaultDetail: "作品は右上の：から説明へ🌸",  // A：誘導文（：→⋮、≡なし、末尾🌸）
      detailMenu: false,                    // acc2は ≡ を出さない（「⋮から説明へ🌸」）
      textFill: "#FFF0F5",                  // C：温白（lavender blush）
      stroke: "rgba(0,0,0,1)",              // glow時は未使用（黒縁は廃止）
      bandRGB: "74,30,58",                  // D：#4A1E3A 葡萄色プラム（α＝既存0.69〜0.76を踏襲＝指定の0.7前後）
      glow: true,                           // B：黒縁→桜ローズの発光影（にじみ・グロー）
      glow1: "rgba(232,75,138,0.95)",       // #E84B8A 中心・小ぼかし（強）
      glow2: "rgba(214,51,108,0.60)",       // #D6336C 中間・中ぼかし
      glow3: "rgba(214,51,108,0.40)",       // #D6336C 外側・大ぼかし
      contour: "rgba(140,30,70,0.9)",       // 最内の細い同系濃色の輪郭（可読性確保・黒は使わない）
      iconFill: "#FFF0F5", iconHalo: "rgba(140,30,70,0.95)",  // アイコンも温白の芯＋同系濃色の輪郭で艶トーン統一
    },
  };
  const theme = () => THEME[curAccount] || THEME.acc1;

  // 文字本体の描画（テーマ依存）。acc1＝黒縁＋白、acc2＝桜ピンク2層グロー＋温白の芯。
  function paintGlyph(ln, x, y, px, sw, shadowScale) {
    const t = theme();
    var ss = shadowScale || 1;  // 影のスケール（大タイトル拡大に連動。既定=1）
    if (t.soft) {
      // acc1：淡金のごく弱いグロー＋可読性用の暗い影（参考: 0 0 6px rgba(245,230,184,.15), 0 1px 2px rgba(0,0,0,.5)）。
      // px固定値はU()で基準フレームへ換算（CSSの6/1/2px相当）。黒い太縁は使わない。
      ctx.save();
      ctx.fillStyle = t.textFill;
      // 暗い影（0 1px 2px rgba(0,0,0,.5)）※大タイトル拡大時は同率で拡大
      ctx.shadowColor = t.darkShadow; ctx.shadowBlur = U(2) * ss; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = U(1) * ss;
      ctx.fillText(ln, x, y);
      // 淡金のグロー（0 0 6px rgba(245,230,184,.15)）※同率で拡大
      ctx.shadowColor = t.glowSoft; ctx.shadowBlur = U(6) * ss; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
      ctx.fillText(ln, x, y);
      ctx.restore();
      ctx.fillStyle = t.textFill; ctx.fillText(ln, x, y);  // 影なしの芯（くっきり）
    } else if (t.glow) {
      // 桜ローズの発光影（外→内の3層グロー）。ぼかし量は文字サイズ比（CSSの6/14/22px相当）。
      ctx.save();
      ctx.fillStyle = t.textFill;
      ctx.shadowColor = t.glow3; ctx.shadowBlur = px * 0.55; ctx.fillText(ln, x, y);
      ctx.shadowColor = t.glow2; ctx.shadowBlur = px * 0.35; ctx.fillText(ln, x, y);
      ctx.shadowColor = t.glow1; ctx.shadowBlur = px * 0.18; ctx.fillText(ln, x, y);
      ctx.restore();
      // 黒縁は使わず、最内に細い同系濃色の輪郭を1枚だけ重ねて滲みの中でも字形を保つ
      ctx.lineJoin = "round"; ctx.lineWidth = Math.max(1, sw * 0.9);
      ctx.strokeStyle = t.contour; ctx.strokeText(ln, x, y);
      ctx.fillStyle = t.textFill; ctx.fillText(ln, x, y);  // 温白の芯（影なし）
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
  let fontReady = false;
  let lastBlob = null, lastName = "video.mp4";

  // ---- フォント読み込み（Canvas描画前に必須） ----
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

  // ---- テキスト：折り返し（文字単位） ----
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

  // 通常テキストブロック（中央寄せ・帯・白文字＋黒縁）。
  // bandOff＝この段の帯だけ／textOff＝この段の文字だけ の縦オフセット比（互いに独立）。
  function drawBlock(lines, y, px, pad, gap, bandAlpha, bandOff, textOff, shadowScale) {
    setFont(px, 700);
    ctx.textBaseline = "top";
    const sw = Math.max(U(2), px / 12);
    const th = px * 1.04;
    const bandY = H * (bandOff || 0);  // 帯だけの縦シフト
    const txtY = H * (textOff || 0);   // 文字だけの縦シフト（送り y には反映しない）
    for (const ln of lines) {
      const tw = ctx.measureText(ln).width;
      const x = (W - tw) / 2;
      const mB = sw;  // 縁取り分だけ帯を広げ、文字が帯からはみ出ないようにする
      const ba = theme().bandAlpha255 != null ? theme().bandAlpha255 : bandAlpha;  // テーマで固定不透明度があれば優先
      ctx.fillStyle = `rgba(${theme().bandRGB},${ba / 255})`;
      roundRect(x - pad - mB, y - pad * 0.45 - mB + bandY, tw + (pad + mB) * 2, th + pad * 0.9 + mB * 2, pad + mB * 0.5);
      ctx.fill();
      paintGlyph(ln, x, y + txtY, px, sw, shadowScale);
      y += th + pad + gap;  // 送りは基準位置のまま（文字オフセットの影響を受けない＝他段に波及しない）
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

  // 2段目（誘導文）：「：」→⋮、「説明」→≡説明 をインライン描画。
  // bandOff＝この段の帯だけ／textOff＝この段の文字（アイコン含む）だけ の縦オフセット比。
  function drawDetail(text, y, px, pad, bandOff, textOff) {
    setFont(px, 700);
    ctx.textBaseline = "middle";
    const sw = Math.max(U(2), px / 12), th = px * 1.04, ym = y + th / 2 + H * (textOff || 0);
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
    const bandY = H * (bandOff || 0);  // 軸2：この段の帯だけを上下（文字は動かさない）
    const ba = theme().bandAlpha255 != null ? theme().bandAlpha255 : 175;  // テーマで固定不透明度があれば優先
    ctx.fillStyle = `rgba(${theme().bandRGB},${ba / 255})`;
    roundRect(x - pad - mB, y - pad * 0.45 - mB + bandY, total + (pad + mB) * 2, th + pad * 0.9 + mB * 2, pad + mB * 0.5); ctx.fill();
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

  function drawText(author, detail, top) {
    const maxw = W * 0.9;
    const fA = Math.round(H * 0.025), fD = Math.round(H * 0.027), fT = Math.round(H * 0.048);
    const padExtra = H * OFF.bandPad;   // 黒帯の余白（厚み）を全段に加算
    const rowGap = H * OFF.rowGap;      // 段と段の間に足す縦スペース
    let y = Math.round(H * (0.020 + OFF.whole));  // 軸1：構成全体の縦オフセットを加算
    if (author) {
      author = author.replace(/^(作者|引用)\s*[:：]\s*/, "");      // 既存プレフィックスを一旦除去
      author = theme().authorPrefix + author;                      // テーマのプレフィックスを常に表示（acc1=作者：/acc2=引用：）
      y = drawBlock(wrap(author, fA, maxw), y, fA, U(11) + padExtra, U(3), 175, OFF.bandAuthor, OFF.textAuthor) + U(2) + rowGap;
    }
    if (detail) y = drawDetail(detail, y, fD, U(11) + padExtra, OFF.bandDetail, OFF.textDetail) + U(4) + rowGap;
    if (top) {
      // まず幅に収まる基準サイズを求め、その上に「大タイトル拡大」を掛ける＝拡大が幅上限で打ち消されない。
      // 影も同じ倍率(ss)で拡大（drawBlock→paintGlyphへ伝播）。
      var tScale = OFF.titleScale || 1;
      var f = fitOneLine(top, fT, maxw, U(14));
      var tpx = Math.max(1, Math.round(f.px * tScale));
      y = drawBlock([f.text], y, tpx, U(16) + padExtra, U(6), 195, OFF.bandTitle, OFF.textTitle, tScale) + U(4);
    }
  }

  // ---- 1フレーム描画 ----
  function drawFrame(t) {
    ctx.clearRect(0, 0, W, H);
    // 背景（9:16をそのまま）
    if (bg.readyState >= 2) {
      const vw = bg.videoWidth, vh = bg.videoHeight, tar = W / H, cur = vw / vh;
      let sx = 0, sy = 0, sw = vw, sh = vh;
      if (cur > tar) { sw = vh * tar; sx = (vw - sw) / 2; } else { sh = vw / tar; sy = (vh - sh) / 2; }
      ctx.drawImage(bg, sx, sy, sw, sh, 0, 0, W, H);
    } else { ctx.fillStyle = "#28424a"; ctx.fillRect(0, 0, W, H); }
    // 前景（フェードイン＋微ズーム）
    if (fgImg) {
      const a = t < REVEAL_START ? 0 : (REVEAL_DUR <= 0 ? 1 : smoothstep((t - REVEAL_START) / REVEAL_DUR));
      if (a > 0) {
        const base = Math.min(W * FG_MAX_RATIO / fgImg.width, H * FG_MAX_RATIO / fgImg.height);
        const sc = (a < 1 && FG_ZOOM > 0) ? base * ((1 - FG_ZOOM) + FG_ZOOM * a) : base;
        const fw = fgImg.width * sc, fh = fgImg.height * sc;
        ctx.globalAlpha = a;
        ctx.drawImage(fgImg, (W - fw) / 2, H * (FG_CENTER_Y + OFF.whole + (OFF.imgY || 0)) - fh / 2, fw, fh);  // 軸1：全体オフセット＋画像だけの個別オフセット(OFF.imgY)
        ctx.globalAlpha = 1;
      }
    }
    // テキスト
    drawText(els.author.value.trim(), els.detail.value.trim() || theme().defaultDetail, els.top.value.trim());
  }

  // ---- プレビュー（完全表示状態の1枚） ----
  async function preview() {
    await ensureFont();
    if (bg.readyState < 2) { try { await bg.play(); } catch (e) {} }
    drawFrame(DURATION);
  }

  // ---- 画像選択 ----
  els.photo.addEventListener("change", () => {
    const f = els.photo.files[0];
    if (!f) return;
    els.photoName.textContent = f.name;
    const url = URL.createObjectURL(f);
    const img = new Image();
    img.onload = () => { fgImg = img; preview(); };
    img.onerror = () => { setStatus("画像を読み込めませんでした（形式をご確認ください）"); };
    img.src = url;
  });

  els.previewBtn.addEventListener("click", preview);
  // テキストは入力確定（フォーカスアウト/Enter）で反映＝IMEを妨げない
  for (const el of [els.author, els.detail, els.top]) {
    el.addEventListener("change", preview);
    el.addEventListener("blur", preview);
  }

  function setStatus(m) { els.status.textContent = m; }
  function sanitize(t) {
    t = (t || "").trim().replace(/[\\/:*?"<>|\r\n\t]/g, "").replace(/^\.+|\.+$/g, "");
    return (t.slice(0, 60) || "video");
  }
  function pickMime() {
    const c = ["video/mp4;codecs=avc1.42E01E", "video/mp4", "video/webm;codecs=vp9", "video/webm"];
    for (const m of c) if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
    return "";
  }

  // ---- 動画作成 ----
  async function make() {
    if (!fgImg) { setStatus("先に写真を選んでください。"); return; }
    if (!window.MediaRecorder) { setStatus("この端末は動画書き出しに未対応です（iOS15以降のSafari推奨）。"); return; }
    await ensureFont();
    els.makeBtn.disabled = true;
    els.resultArea.hidden = true;
    setStatus("動画を作成中…（約5秒録画します。画面はそのままで）");

    try {
      bg.currentTime = 0;
      try { await bg.play(); } catch (e) {}
      const mime = pickMime();
      const stream = cv.captureStream(FPS);
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 8_000_000 } : undefined);
      const chunks = [];
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      const stopped = new Promise((r) => { rec.onstop = r; });

      const t0 = performance.now();
      rec.start();
      await new Promise((resolve) => {
        const loop = () => {
          const t = (performance.now() - t0) / 1000;
          drawFrame(Math.min(t, DURATION));
          if (t >= DURATION) return resolve();
          requestAnimationFrame(loop);
        };
        loop();
      });
      rec.stop();
      await stopped;

      const type = mime || "video/webm";
      lastBlob = new Blob(chunks, { type });
      const ext = type.includes("mp4") ? "mp4" : "webm";
      lastName = sanitize(els.top.value) + "." + ext;

      const url = URL.createObjectURL(lastBlob);
      els.result.src = url;
      els.dl.href = url; els.dl.download = lastName;
      els.resultArea.hidden = false;
      setStatus("✅ 完成しました：" + lastName + (ext === "webm" ? "（この端末ではwebm形式）" : ""));
      els.resultArea.scrollIntoView({ behavior: "smooth" });
      // 完成を通知（Bluesky自動投稿などが購読）。この時点で Canvas は最終フレームを保持している。
      // 一本道運用の背骨＝安定動画IDを“作成時（投稿前）”に発番し、購読側（Drive保存・記録）へ串刺しで渡す。
      var account = (typeof window.getCurrentAccount === "function") ? window.getCurrentAccount() : "acc1";
      var testEl = document.getElementById("testMode");
      var isTest = !!(testEl && testEl.checked);   // テストモード＝記録しない（IDに test- 接頭辞）
      var videoId = (window.IdGen && window.IdGen.makeVideoId) ? window.IdGen.makeVideoId(account, new Date(), { test: isTest }) : "";
      document.dispatchEvent(new CustomEvent("video-created", { detail: { title: els.top.value.trim(), blob: lastBlob, name: lastName, videoId: videoId, account: account, test: isTest } }));
    } catch (e) {
      setStatus("作成に失敗しました：" + e.message);
    } finally {
      els.makeBtn.disabled = false;
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

  // ---- 設定の保存・復元（localStorage 汎用ヘルパ：アフィID等 将来の設定値もこれで保存できる） ----
  const Store = {
    getNum(key) { try { const v = localStorage.getItem(key); const n = v === null ? NaN : parseFloat(v); return isNaN(n) ? null : n; } catch (e) { return null; } },
    set(key, val) { try { localStorage.setItem(key, String(val)); } catch (e) {} },
    remove(key) { try { localStorage.removeItem(key); } catch (e) {} },
  };

  // ---- 位置調整（＋/−ボタン式・プレビュー横）。各コントロールは独立。----
  // 値は基準フレーム高さ比、localStorage に保存・自動復元。legacy は旧バージョンの保存キー（移行用）。
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
    { key: "bandAuthor", m: "baMinus",    p: "baPlus",    v: "baVal",    ls: "preview_band_author", lsDef: "preview_band_author_default", legacy: "preview_band_y", def: 0,            min: ROW_MIN, max: ROW_MAX,     step: 0.0025, signed: true  },
    { key: "bandDetail", m: "bdMinus",    p: "bdPlus",    v: "bdVal",    ls: "preview_band_detail", lsDef: "preview_band_detail_default", legacy: "preview_band_y", def: 0,            min: ROW_MIN, max: ROW_MAX,     step: 0.0025, signed: true  },
    { key: "bandTitle",  m: "btMinus",    p: "btPlus",    v: "btVal",    ls: "preview_band_title",  lsDef: "preview_band_title_default",  legacy: "preview_band_y", def: 0,            min: ROW_MIN, max: ROW_MAX,     step: 0.0025, signed: true  },
    { key: "bandPad",    m: "bpMinus",    p: "bpPlus",    v: "bpVal",    ls: "preview_band_pad",    lsDef: "preview_band_pad_default",    legacy: null,             def: 0,            min: 0,       max: BANDPAD_MAX, step: 0.0025, signed: false },
    { key: "rowGap",     m: "rgMinus",    p: "rgPlus",    v: "rgVal",    ls: "preview_row_gap",     lsDef: "preview_row_gap_default",     legacy: null,             def: 0,            min: 0,       max: ROWGAP_MAX,  step: 0.005,  signed: false },
    { key: "titleScale", m: "tsMinus",    p: "tsPlus",    v: "tsVal",    ls: "preview_title_scale", lsDef: "preview_title_scale_default", legacy: null,             def: 1,            min: TSCALE_MIN, max: TSCALE_MAX, step: 0.05,   signed: false },
    { key: "imgY",       m: "iyMinus",    p: "iyPlus",    v: "iyVal",    ls: "preview_img_y",       lsDef: "preview_img_y_default",       legacy: null,             def: 0,            min: IMG_MIN, max: IMG_MAX,     step: 0.0025, signed: true  },
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

  // ---- レイアウト設定をアカウント別に（Task 8d）----
  // 位置調整値は preview_*__acc1 / preview_*__acc2 に保存し、アカウントごとに独立。
  // 旧来の共通キー（preview_*）は一度だけ両アカウントへ複製して引き継ぐ（移行・冪等）。
  function lsk(base) { return base + "__" + curAccount; }
  (function migrateLayoutOnce() {
    try { if (localStorage.getItem("layout_acct_split_migrated") === "1") return; } catch (e) { return; }
    // 旧共通値（無ければ旧バージョンキー）を両アカウントの現在値へ、旧共通既定値を両既定値へ複製。
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
    // 旧共通キー・旧バージョンキーは退役（per-account リセット後に値が蘇らないように）。
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
  loadOffsets(false); // 起動時の初期復元（このあとの setAccount でも再読込される）

  // 「既定値に保存」：現アカウントの全コントロール現在値を既定値として確定
  if (els.voffSaveDefault) els.voffSaveDefault.addEventListener("click", () => {
    CONTROLS.forEach((c) => { Store.set(lsk(c.lsDef), OFF[c.key]); Store.set(lsk(c.ls), OFF[c.key]); });
    flashBtn(els.voffSaveDefault, "✓ 既定値に保存しました");
  });

  // 「リセット」：現アカウントの保存値だけ消し、工場既定に戻す（他アカウントには影響しない）
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
    // 誘導文が未編集（空 or いずれかのテーマ既定文）なら、当該テーマの既定文へ追従。ユーザーが書き換えた文面は尊重して残す。
    if (els.detail) {
      const known = Object.keys(THEME).map((k) => THEME[k].defaultDetail).concat([DEFAULT_DETAIL]);
      const cur = els.detail.value.trim();
      if (cur === "" || known.indexOf(cur) >= 0) els.detail.value = theme().defaultDetail;
    }
    if (els.acctBtn1) els.acctBtn1.classList.toggle("active", id === "acc1");
    if (els.acctBtn2) els.acctBtn2.classList.toggle("active", id === "acc2");
    const want = ACCOUNTS[id].bg;
    const cur = bg.getAttribute("src") || "";
    if (!cur.endsWith(want)) { bg.src = want; try { bg.load(); } catch (e) {} }
    bg.play().catch(() => {});
    if (typeof loadOffsets === "function") loadOffsets(false); // このアカウントのレイアウト設定を反映
    preview();
    document.dispatchEvent(new CustomEvent("account-changed", { detail: { id } }));
  }
  window.getCurrentAccount = () => curAccount;

  // ---- 初期化 ----
  bg.addEventListener("loadeddata", preview);
  ensureFont().then(preview);
  // フォント確定後にもう一度描画（初回がフォールバックフォントの計測で描かれてしまうのを防ぐ＝
  // プレビューと書き出しで measureText 由来の自動縮小・折返しがズレないようにする保険）。
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => { fontReady = true; preview(); });
  }
  // iOSはミュート自動再生が許可されるが、念のため初回操作でも再生を促す。
  const kick = () => { bg.play().catch(() => {}); document.removeEventListener("touchstart", kick); document.removeEventListener("click", kick); };
  document.addEventListener("touchstart", kick, { once: true, passive: true });
  document.addEventListener("click", kick, { once: true });

  // ---- アカウント切替ボタン配線・起動時復元 ----
  if (els.acctBtn1) els.acctBtn1.addEventListener("click", () => setAccount("acc1"));
  if (els.acctBtn2) els.acctBtn2.addEventListener("click", () => setAccount("acc2"));
  let savedAcct = "acc1";
  try { savedAcct = localStorage.getItem("current_account") || "acc1"; } catch (e) {}
  setAccount(savedAcct);
})();
