/**
 * secret-reveal.js — 秘密入力欄(●●で隠れる値)に「👁 表示/🙈 隠す」トグルを付ける。
 *
 * 対象：type="password" の全入力＋ data-secret を付けた入力（APIキー/トークン等）。
 *   ・既定はマスク(password)。👁 で一時的に平文表示、🙈 で再マスク。値は console に出さない。
 *   ・入力を .secret-wrap で包み、右端に目のボタンを重ねる（見た目は style.css）。
 *   ・動的に増える欄にも対応するため、詳細設定タブを開いた時にも再スキャンする。
 */
(function () {
  "use strict";
  function addToggle(input) {
    if (!input || input.__revealWired) return;
    input.__revealWired = true;
    input.type = "password"; // data-secret の text 欄も既定でマスクして統一
    var wrap = document.createElement("div");
    wrap.className = "secret-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    input.classList.add("secret-input");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secret-eye";
    btn.textContent = "👁";
    btn.title = "値を表示";
    btn.setAttribute("aria-label", "値を表示");
    wrap.appendChild(btn);
    btn.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "🙈" : "👁";
      var lbl = show ? "値を隠す" : "値を表示";
      btn.title = lbl; btn.setAttribute("aria-label", lbl);
    });
  }
  function scan() {
    var list = document.querySelectorAll('input[type="password"], input[data-secret]');
    for (var i = 0; i < list.length; i++) addToggle(list[i]);
  }
  document.addEventListener("DOMContentLoaded", function () {
    scan();
    var tab = document.getElementById("tabSettings");
    if (tab) tab.addEventListener("click", function () { setTimeout(scan, 100); });
  });
})();
