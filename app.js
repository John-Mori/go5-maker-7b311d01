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
  const VOFF_DEFAULT = 0.02, VOFF_MAX = 0.05;   // 軸1：全体（文字＋帯＋漫画）を下へ
  const BAND_MIN = -0.03, BAND_MAX = 0.03;      // 軸2：各段の黒帯だけ（上下双方向 ＋下／−上）

  // 縦オフセット（すべて基準フレーム高さ比）。whole=全体、author/detail/title=各段の黒帯だけ。
  // 帯オフセットは段ごとに独立（文字は動かさず、その段の帯Yだけを動かす）。
  const OFF = { whole: VOFF_DEFAULT, author: 0, detail: 0, title: 0 };

  const $ = (id) => document.getElementById(id);
  const cv = $("cv"), ctx = cv.getContext("2d");
  const bg = $("bg");
  const els = {
    photo: $("photo"), photoName: $("photoName"), photoBtn: $("photoBtn"),
    author: $("author"), detail: $("detail"), top: $("top"),
    previewBtn: $("previewBtn"), makeBtn: $("makeBtn"), status: $("status"),
    resultArea: $("resultArea"), result: $("result"), saveBtn: $("saveBtn"), dl: $("dl"),
    voff: $("voff"), voffVal: $("voffVal"),
    bandAuthor: $("bandAuthor"), bandAuthorVal: $("bandAuthorVal"),
    bandDetail: $("bandDetail"), bandDetailVal: $("bandDetailVal"),
    bandTitle: $("bandTitle"), bandTitleVal: $("bandTitleVal"),
    voffSaveDefault: $("voffSaveDefault"), voffReset: $("voffReset"),
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

  // 通常テキストブロック（中央寄せ・帯・白文字＋黒縁）。bandOff＝この段の帯だけの縦オフセット比。
  function drawBlock(lines, y, px, pad, gap, bandAlpha, bandOff) {
    setFont(px, 700);
    ctx.textBaseline = "top";
    const sw = Math.max(U(2), px / 12);
    const th = px * 1.04;
    for (const ln of lines) {
      const tw = ctx.measureText(ln).width;
      const x = (W - tw) / 2;
      const mB = sw;  // 縁取り分だけ帯を広げ、文字が帯からはみ出ないようにする
      const bandY = H * (bandOff || 0);  // 軸2：この段の帯だけを上下（文字は動かさない）
      ctx.fillStyle = `rgba(0,0,0,${bandAlpha / 255})`;
      roundRect(x - pad - mB, y - pad * 0.45 - mB + bandY, tw + (pad + mB) * 2, th + pad * 0.9 + mB * 2, pad + mB * 0.5);
      ctx.fill();
      ctx.lineJoin = "round";
      ctx.lineWidth = sw * 2;
      ctx.strokeStyle = "rgba(0,0,0,1)";
      ctx.strokeText(ln, x, y);
      ctx.fillStyle = "#fff";
      ctx.fillText(ln, x, y);
      y += th + pad + gap;
    }
    return y;
  }

  // アイコン
  function dot(cx, cy, r, halo) {
    ctx.fillStyle = "rgba(0,0,0,1)";
    ctx.beginPath(); ctx.arc(cx, cy, r + halo, 0, 7); ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.fill();
  }
  function kebab(cx, ym, fs) {
    const r = Math.max(1, fs * 0.072), sp = Math.max(r * 2 + 2, fs * 0.26), halo = Math.max(1, fs * 0.022);
    for (const dy of [-sp, 0, sp]) dot(cx, ym + dy, r, halo);
  }
  function hbar(xl, y0, w, t, halo) {
    ctx.fillStyle = "rgba(0,0,0,1)"; roundRect(xl - halo, y0 - t / 2 - halo, w + 2 * halo, t + 2 * halo, (t + 2 * halo) / 2); ctx.fill();
    ctx.fillStyle = "#fff"; roundRect(xl, y0 - t / 2, w, t, t / 2); ctx.fill();
  }
  function hamburger(xl, ym, fs) {
    const t = Math.max(2, fs * 0.12), sp = fs * 0.28, halo = Math.max(1, fs * 0.05), w = fs * 0.80;
    for (const dy of [-sp, 0, sp]) hbar(xl, ym + dy, w, t, halo);
  }

  // 2段目（誘導文）：「：」→⋮、「説明」→≡説明 をインライン描画。bandOff＝この段の帯だけの縦オフセット比。
  function drawDetail(text, y, px, pad, bandOff) {
    setFont(px, 700);
    ctx.textBaseline = "middle";
    const sw = Math.max(U(2), px / 12), th = px * 1.04, ym = y + th / 2;
    const iconPad = px * 0.16, kebabW = px * 0.42, hamW = px * 0.80;
    // トークン分解
    const segs = []; let i = 0; const s = String(text);
    while (i < s.length) {
      const c = s[i];
      if (c === "：" || c === ":") { segs.push(["kebab"]); i++; }
      else if (s.substr(i, 2) === "説明") { segs.push(["menu"]); segs.push(["text", "説明"]); i += 2; }
      else { let j = i, buf = ""; while (j < s.length && s[j] !== "：" && s[j] !== ":" && s.substr(j, 2) !== "説明") { buf += s[j]; j++; } segs.push(["text", buf]); i = j; }
    }
    const widths = segs.map(([k, v]) => k === "text" ? ctx.measureText(v).width : (k === "kebab" ? kebabW : hamW) + 2 * iconPad);
    const total = widths.reduce((a, b) => a + b, 0);
    let x = (W - total) / 2;
    const mB = sw;  // 縁取り分だけ帯を広げる
    const bandY = H * (bandOff || 0);  // 軸2：この段の帯だけを上下（文字は動かさない）
    ctx.fillStyle = `rgba(0,0,0,${175 / 255})`;
    roundRect(x - pad - mB, y - pad * 0.45 - mB + bandY, total + (pad + mB) * 2, th + pad * 0.9 + mB * 2, pad + mB * 0.5); ctx.fill();
    for (let k = 0; k < segs.length; k++) {
      const [kind, val] = segs[k], w = widths[k];
      if (kind === "text") {
        ctx.lineJoin = "round"; ctx.lineWidth = sw * 2; ctx.strokeStyle = "rgba(0,0,0,1)"; ctx.strokeText(val, x, ym);
        ctx.fillStyle = "#fff"; ctx.fillText(val, x, ym);
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
    let y = Math.round(H * (0.020 + OFF.whole));  // 軸1：構成全体の縦オフセットを加算
    if (author) {
      if (!/^作者/.test(author)) author = "作者：" + author;  // 「作者：」を常に表示（消えないように）
      y = drawBlock(wrap(author, fA, maxw), y, fA, U(11), U(3), 175, OFF.author) + U(2);
    }
    if (detail) y = drawDetail(detail, y, fD, U(11), OFF.detail) + U(4);
    if (top) { const f = fitOneLine(top, fT, maxw, U(14)); y = drawBlock([f.text], y, f.px, U(16), U(6), 195, OFF.title) + U(4); }
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
        ctx.drawImage(fgImg, (W - fw) / 2, H * (FG_CENTER_Y + OFF.whole) - fh / 2, fw, fh);  // 軸1：テキストと同じ全体オフセット
        ctx.globalAlpha = 1;
      }
    }
    // テキスト
    drawText(els.author.value.trim(), els.detail.value.trim() || DEFAULT_DETAIL, els.top.value.trim());
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

  // ---- 縦位置オフセット 4スライダー（全体1本＋各段の黒帯3本）をテーブル駆動で管理 ----
  // 各スライダーは独立。値は基準フレーム高さ比、localStorage に保存・自動復元する。
  // legacy は旧バージョンの保存キー（移行用）。3段の帯は旧・単一帯キー "preview_band_y" を引き継ぐ。
  function flashBtn(btn, msg) {
    if (!btn) return;
    if (!btn.dataset.label) btn.dataset.label = btn.textContent;
    btn.textContent = msg;
    setTimeout(() => { btn.textContent = btn.dataset.label; }, 1500);
  }
  const SLIDERS = [
    { key: "whole",  el: els.voff,       lab: els.voffVal,       ls: "preview_offset_y", lsDef: "preview_offset_y_default", legacy: "v_offset",        def: VOFF_DEFAULT, min: 0,        max: VOFF_MAX, signed: false },
    { key: "author", el: els.bandAuthor, lab: els.bandAuthorVal, ls: "preview_band_author", lsDef: "preview_band_author_default", legacy: "preview_band_y", def: 0,        min: BAND_MIN, max: BAND_MAX, signed: true },
    { key: "detail", el: els.bandDetail, lab: els.bandDetailVal, ls: "preview_band_detail", lsDef: "preview_band_detail_default", legacy: "preview_band_y", def: 0,        min: BAND_MIN, max: BAND_MAX, signed: true },
    { key: "title",  el: els.bandTitle,  lab: els.bandTitleVal,  ls: "preview_band_title",  lsDef: "preview_band_title_default",  legacy: "preview_band_y", def: 0,        min: BAND_MIN, max: BAND_MAX, signed: true },
  ];
  const clampS = (s, v) => Math.min(s.max, Math.max(s.min, isNaN(v) ? s.def : v));
  function setSliderLabel(s) {
    if (!s.lab) return;
    const sign = (s.signed && OFF[s.key] >= 0) ? "+" : "";
    s.lab.textContent = sign + (OFF[s.key] * 100).toFixed(1) + "%";
  }
  function applyS(s, v, redraw) {
    OFF[s.key] = clampS(s, v);
    if (s.el) s.el.value = String(OFF[s.key]);
    setSliderLabel(s);
    if (redraw) preview();
  }

  SLIDERS.forEach((s) => {
    if (!s.el) return;
    s.el.min = String(s.min); s.el.max = String(s.max); s.el.step = "0.0025";
    // 復元の優先順位：現在値 → ユーザー既定値 → 旧キー → 工場既定
    const cur = Store.getNum(s.ls), def = Store.getNum(s.lsDef), legacy = s.legacy ? Store.getNum(s.legacy) : null;
    applyS(s, cur != null ? cur : (def != null ? def : (legacy != null ? legacy : s.def)), false);
    s.el.addEventListener("input", () => { applyS(s, parseFloat(s.el.value), true); Store.set(s.ls, OFF[s.key]); });
  });

  // 「デフォルトとして保存」：全スライダーの現在値を既定値として確定（次回はこの値で初期表示）
  if (els.voffSaveDefault) els.voffSaveDefault.addEventListener("click", () => {
    SLIDERS.forEach((s) => { Store.set(s.lsDef, OFF[s.key]); Store.set(s.ls, OFF[s.key]); });
    flashBtn(els.voffSaveDefault, "✓ 既定値に保存しました");
  });

  // 「リセット」：全スライダーの保存値（旧キー含む）を消し、初期状態（工場既定）に戻す
  if (els.voffReset) els.voffReset.addEventListener("click", () => {
    SLIDERS.forEach((s) => { Store.remove(s.ls); Store.remove(s.lsDef); if (s.legacy) Store.remove(s.legacy); });
    SLIDERS.forEach((s, i) => applyS(s, s.def, i === SLIDERS.length - 1));  // 最後の1回だけ再描画
    flashBtn(els.voffReset, "✓ リセットしました");
  });

  // ---- 初期化 ----
  bg.addEventListener("loadeddata", preview);
  ensureFont().then(preview);
  // フォント確定後にもう一度描画（初回がフォールバックフォントの計測で描かれてしまうのを防ぐ＝
  // プレビューと書き出しで measureText 由来の自動縮小・折返しがズレないようにする保険）。
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => { fontReady = true; preview(); });
  }
  // iOSはミュート自動再生が許可されるが、念のため初回操作でも再生を促す。
  bg.play().catch(() => {});
  const kick = () => { bg.play().catch(() => {}); document.removeEventListener("touchstart", kick); document.removeEventListener("click", kick); };
  document.addEventListener("touchstart", kick, { once: true, passive: true });
  document.addEventListener("click", kick, { once: true });
})();
