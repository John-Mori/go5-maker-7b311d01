// persona-hub/icon.js — アイコン整形ページの配線。
// 完全クライアントサイド。アップロード/送信は一切行わない(書き出しはローカルダウンロードのみ)。
// 座標系は本体アプリ(app.js)の作法を踏襲=Canvas内部解像度を固定し、CSSは表示縮小のみに使う
// (プレビューと書き出しが同じ式で一致する)。
(function () {
  'use strict';

  var SIZE = 512; // Canvas内部解像度=書き出しPNGの一辺(推奨512×512)

  var canvas = document.getElementById('iconCanvas');
  var ctx = canvas.getContext('2d');
  var fileInput = document.getElementById('iconFile');
  var dropZone = document.getElementById('iconDrop');
  var statusEl = document.getElementById('iconStatus');
  var exportBtn = document.getElementById('exportBtn');
  var resetBtn = document.getElementById('resetBtn');
  var fileNamePreview = document.getElementById('fileNamePreview');

  var rotEl = document.getElementById('rotRange');
  var rotVal = document.getElementById('rotVal');
  var zoomEl = document.getElementById('zoomRange');
  var zoomVal = document.getElementById('zoomVal');
  var xEl = document.getElementById('xRange');
  var xVal = document.getElementById('xVal');
  var yEl = document.getElementById('yRange');
  var yVal = document.getElementById('yVal');

  var img = null;
  var baseScale = 1; // 画像をSIZE四方へ「収める(contain)」フィット倍率(ズーム100%の基準)

  function defaults() { return { rot: 0, zoom: 1, x: 0, y: 0 }; }
  var state = defaults();

  function clamp(v, min, max) { return Math.min(max, Math.max(min, v)); }

  function setStatus(msg, isErr) {
    if (!statusEl) return;
    statusEl.textContent = msg || '';
    statusEl.style.color = isErr ? '#dc465a' : '';
  }

  function loadFile(file) {
    if (!file || !/^image\//.test(file.type)) { setStatus('画像ファイルを選んでください。', true); return; }
    var url = URL.createObjectURL(file);
    var im = new Image();
    im.onload = function () {
      img = im;
      baseScale = Math.min(SIZE / img.width, SIZE / img.height);
      state = defaults();
      syncControls();
      setStatus('画像を読み込みました(' + img.width + '×' + img.height + ')。角度・拡大・位置を調整してください。');
      draw();
      URL.revokeObjectURL(url);
    };
    im.onerror = function () { setStatus('画像の読み込みに失敗しました。', true); URL.revokeObjectURL(url); };
    im.src = url;
  }

  function buildFileName() {
    var r = Math.round(state.rot);
    var z = Math.round(state.zoom * 100);
    var x = Math.round(state.x);
    var y = Math.round(state.y);
    return 'persona_icon_r' + r + '_z' + z + '_x' + x + '_y' + y + '.png';
  }

  function syncControls() {
    rotEl.value = state.rot; rotVal.textContent = Math.round(state.rot) + '°';
    zoomEl.value = Math.round(state.zoom * 100); zoomVal.textContent = Math.round(state.zoom * 100) + '%';
    xEl.value = state.x; xVal.textContent = Math.round(state.x) + 'px';
    yEl.value = state.y; yVal.textContent = Math.round(state.y) + 'px';
    fileNamePreview.textContent = buildFileName();
  }

  // 描画本体(プレビュー/書き出し共通の1本)。maskOn=true でDiscordの円マスクを重ねて見せる。
  // 書き出し時(maskOn=false)は円の外もそのまま含む素の正方形PNG=Discord側の円クロップに委ねる。
  function drawContent(targetCtx, maskOn) {
    targetCtx.clearRect(0, 0, SIZE, SIZE);
    if (maskOn) {
      targetCtx.fillStyle = '#141419';
      targetCtx.fillRect(0, 0, SIZE, SIZE);
    }
    if (img) {
      var eff = baseScale * state.zoom;
      targetCtx.save();
      targetCtx.translate(SIZE / 2 + state.x, SIZE / 2 + state.y);
      targetCtx.rotate(state.rot * Math.PI / 180);
      targetCtx.scale(eff, eff);
      targetCtx.drawImage(img, -img.width / 2, -img.height / 2);
      targetCtx.restore();
    }
    if (maskOn) {
      // 円の外だけ暗く塗る(四角と円の差分=evenoddルール)。円の内側=実際にDiscordで見える範囲。
      targetCtx.save();
      targetCtx.beginPath();
      targetCtx.rect(0, 0, SIZE, SIZE);
      targetCtx.moveTo(SIZE, SIZE / 2);
      targetCtx.arc(SIZE / 2, SIZE / 2, SIZE / 2, 0, Math.PI * 2, true);
      targetCtx.closePath();
      targetCtx.fillStyle = 'rgba(6,8,16,.58)';
      targetCtx.fill('evenodd');
      targetCtx.restore();
      // 円の縁線
      targetCtx.save();
      targetCtx.beginPath();
      targetCtx.arc(SIZE / 2, SIZE / 2, SIZE / 2 - 1, 0, Math.PI * 2);
      targetCtx.strokeStyle = '#2bb3c0';
      targetCtx.lineWidth = 2;
      targetCtx.stroke();
      targetCtx.restore();
    }
  }

  function draw() { drawContent(ctx, true); }

  // ドラッグ(マウス/タッチ共通=Pointer Events)で位置(state.x/y)を動かす。
  var dragging = false, dragStart = null, dragOrigin = null;
  function clientDeltaToCanvasPx(dxClient, dyClient) {
    var rect = canvas.getBoundingClientRect();
    var sx = SIZE / rect.width, sy = SIZE / rect.height; // 表示縮小率をCanvas内部座標へ換算
    return { dx: dxClient * sx, dy: dyClient * sy };
  }
  canvas.addEventListener('pointerdown', function (ev) {
    if (!img) return;
    dragging = true;
    dragStart = { x: ev.clientX, y: ev.clientY };
    dragOrigin = { x: state.x, y: state.y };
    try { canvas.setPointerCapture(ev.pointerId); } catch (e) {}
  });
  canvas.addEventListener('pointermove', function (ev) {
    if (!dragging) return;
    var d = clientDeltaToCanvasPx(ev.clientX - dragStart.x, ev.clientY - dragStart.y);
    state.x = clamp(Math.round(dragOrigin.x + d.dx), -SIZE, SIZE);
    state.y = clamp(Math.round(dragOrigin.y + d.dy), -SIZE, SIZE);
    syncControls();
    draw();
  });
  function endDrag() { dragging = false; }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('pointerleave', endDrag);

  rotEl.addEventListener('input', function () { state.rot = clamp(parseInt(rotEl.value, 10) || 0, -180, 180); syncControls(); draw(); });
  zoomEl.addEventListener('input', function () { state.zoom = clamp((parseInt(zoomEl.value, 10) || 100) / 100, 0.2, 4); syncControls(); draw(); });
  xEl.addEventListener('input', function () { state.x = clamp(parseInt(xEl.value, 10) || 0, -SIZE, SIZE); syncControls(); draw(); });
  yEl.addEventListener('input', function () { state.y = clamp(parseInt(yEl.value, 10) || 0, -SIZE, SIZE); syncControls(); draw(); });

  resetBtn.addEventListener('click', function () { state = defaults(); syncControls(); draw(); });

  fileInput.addEventListener('change', function () {
    if (fileInput.files && fileInput.files[0]) loadFile(fileInput.files[0]);
  });
  dropZone.addEventListener('click', function () { fileInput.click(); });
  ['dragover'].forEach(function (t) {
    dropZone.addEventListener(t, function (ev) { ev.preventDefault(); dropZone.classList.add('is-over'); });
  });
  ['dragleave', 'dragend'].forEach(function (t) {
    dropZone.addEventListener(t, function () { dropZone.classList.remove('is-over'); });
  });
  dropZone.addEventListener('drop', function (ev) {
    ev.preventDefault();
    dropZone.classList.remove('is-over');
    var f = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
    if (f) loadFile(f);
  });

  exportBtn.addEventListener('click', function () {
    if (!img) { setStatus('先に画像を選んでください。', true); return; }
    drawContent(ctx, false); // 書き出しは暗幕/円線なしの素の正方形
    canvas.toBlob(function (blob) {
      draw(); // プレビュー表示(暗幕+円線)へ戻す
      if (!blob) { setStatus('書き出しに失敗しました。', true); return; }
      var name = buildFileName();
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
      setStatus('書き出しました: ' + name + '(このファイルをChamiが受け取り、登録は別のセッションで行います)');
    }, 'image/png');
  });

  syncControls();
  draw();
})();
