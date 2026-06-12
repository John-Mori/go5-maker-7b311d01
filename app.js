/* 5秒動画メーカー（クライアントサイド合成）
   背景動画＋前景画像＋テキスト3段を Canvas で描画し、MediaRecorder で録画して動画化する。
   仕上がりはデスクトップ版 composite.py に合わせている。 */
(() => {
  "use strict";

  // ---- 仕上がり設定（composite.py / jobs.json と統一） ----
  const W = 720, H = 1280;          // 内部解像度（9:16）
  const DURATION = 5, FPS = 30;
  const REVEAL_START = 0.5, REVEAL_DUR = 2.0;
  const FG_MAX_RATIO = 0.92, FG_ZOOM = 0.04, FG_CENTER_Y = 0.55;
  const DEFAULT_DETAIL = "作品の詳細は右上の：から説明";

  const $ = (id) => document.getElementById(id);
  const cv = $("cv"), ctx = cv.getContext("2d");
  const bg = $("bg");
  const els = {
    photo: $("photo"), photoName: $("photoName"), photoBtn: $("photoBtn"),
    author: $("author"), detail: $("detail"), top: $("top"),
    previewBtn: $("previewBtn"), makeBtn: $("makeBtn"), status: $("status"),
    resultArea: $("resultArea"), result: $("result"), saveBtn: $("saveBtn"), dl: $("dl"),
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

  // 通常テキストブロック（中央寄せ・帯・白文字＋黒縁）
  function drawBlock(lines, y, px, pad, gap, bandAlpha) {
    setFont(px, 700);
    ctx.textBaseline = "top";
    const sw = Math.max(2, px / 12);
    const th = px * 1.04;
    for (const ln of lines) {
      const tw = ctx.measureText(ln).width;
      const x = (W - tw) / 2;
      ctx.fillStyle = `rgba(0,0,0,${bandAlpha / 255})`;
      roundRect(x - pad, y - pad * 0.45, tw + pad * 2, th + pad * 0.9, pad);
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

  // 2段目（誘導文）：「：」→⋮、「説明」→≡説明 をインライン描画
  function drawDetail(text, y, px, pad) {
    setFont(px, 700);
    ctx.textBaseline = "middle";
    const sw = Math.max(2, px / 12), th = px * 1.04, ym = y + th / 2;
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
    ctx.fillStyle = `rgba(0,0,0,${130 / 255})`;
    roundRect(x - pad, y - pad * 0.45, total + pad * 2, th + pad * 0.9, pad); ctx.fill();
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
    let y = Math.round(H * 0.020);
    if (author) y = drawBlock(wrap(author, fA, maxw), y, fA, 11, 3, 130) + 2;
    if (detail) y = drawDetail(detail, y, fD, 11) + 4;
    if (top) { const f = fitOneLine(top, fT, maxw); y = drawBlock([f.text], y, f.px, 16, 6, 150) + 4; }
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
        ctx.drawImage(fgImg, (W - fw) / 2, H * FG_CENTER_Y - fh / 2, fw, fh);
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

  // ---- 初期化 ----
  bg.addEventListener("loadeddata", preview);
  ensureFont().then(preview);
  // iOSはミュート自動再生が許可されるが、念のため初回操作でも再生を促す。
  bg.play().catch(() => {});
  const kick = () => { bg.play().catch(() => {}); document.removeEventListener("touchstart", kick); document.removeEventListener("click", kick); };
  document.addEventListener("touchstart", kick, { once: true, passive: true });
  document.addEventListener("click", kick, { once: true });
})();
