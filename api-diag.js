/**
 * api-diag.js — ⚙️詳細設定「🩺 API一括診断」。
 * 「再生数やDMM情報が取れない」とき、どの層(端末のYouTubeキー/FANZA worker/クリック計測/記録GAS)が
 * 壊れているかを1クリックで切り分ける。各系統は独立に検査し、結果を ✅/⚠️/❌ で一覧表示する。
 * 教訓: 同種の設定が複数層に分かれていると故障箇所が画面から区別できない(インシデント.md参照)。
 */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function ls(k) { try { return (localStorage.getItem(k) || '').trim(); } catch (e) { return ''; } }

  // 診断用の既知公開動画（YouTube公式のグローバル定番・削除リスク極小）
  var PROBE_YT_ID = 'jNQXAC9IVRw'; // "Me at the zoo"（YouTube最初の動画）
  var PROBE_FANZA_CID = 'd_784975';

  function line(name, state, detail) {
    var mark = state === 'ok' ? '✅' : state === 'warn' ? '⚠️' : '❌';
    var color = state === 'ok' ? 'var(--accent2, #7fe87f)' : state === 'warn' ? '#f0b429' : '#ff6b6b';
    return '<div><span style="color:' + color + ';font-weight:700;">' + mark + ' ' + esc(name) + '</span>：' + esc(detail) + '</div>';
  }

  // ── ① YouTube Data API（端末キー）──
  function checkYouTube() {
    var key = ls('yt_api_key');
    if (!key) return Promise.resolve(line('YouTube再生数', 'warn', 'APIキー未設定（⚙️のYouTube欄に AIza… を設定してください）'));
    var u = 'https://www.googleapis.com/youtube/v3/videos?part=statistics&id=' + PROBE_YT_ID + '&key=' + encodeURIComponent(key);
    return fetch(u).then(function (r) { return r.json().then(function (j) { return { s: r.status, j: j }; }); }).then(function (res) {
      if (res.j && res.j.items && res.j.items.length) return line('YouTube再生数', 'ok', 'APIキー正常（テスト動画の再生数を取得できました）');
      var reason = (res.j && res.j.error && res.j.error.message) || ('HTTP ' + res.s);
      var hint = res.s === 403 ? '（キー無効化/1日の割当(quota)超過/APIが無効の可能性。Google Cloudコンソールで確認）'
               : res.s === 400 ? '（キーの形式不正・リファラー制限に github.io が含まれていない可能性）' : '';
      return line('YouTube再生数', 'bad', reason + hint);
    }).catch(function () { return line('YouTube再生数', 'bad', '通信エラー（オフライン/ブロック）'); });
  }

  // ── ② FANZA worker（作品情報）──
  function checkFanza() {
    var w = ls('fanza_worker_url'), s = ls('fanza_shared_secret');
    if (!w) return Promise.resolve(line('FANZA作品情報', 'warn', 'Worker URL未設定（⚙️のFANZA欄を設定してください）'));
    return fetch(w.replace(/\/+$/, '') + '/api/fanza-item', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': s },
      body: JSON.stringify({ cid: PROBE_FANZA_CID })
    }).then(function (r) { return r.json().then(function (j) { return { s: r.status, j: j }; }); }).then(function (res) {
      if (res.j && res.j.ok && res.j.item && res.j.item.title) return line('FANZA作品情報', 'ok', 'worker正常（テスト作品「' + String(res.j.item.title).slice(0, 14) + '…」取得OK）');
      // 認証は成功したが、この特定のテスト作品がまだ「部分情報(画像のみ)」の状態。
      //   Cloudflare側からのDMM直接スクレイプは地域判定でブロックされることがあり(既知の制約)、
      //   PC側の定期取得タスクが解決するまで作品ごとに一時的に起こり得る。設定不備ではない。
      if (res.j && res.j.ok && res.j.item && res.j.item.partial) {
        return line('FANZA作品情報', 'warn', '認証OK・このテスト作品はまだ部分情報(画像のみ)です。設定は正常。PC側の定期取得(タスクスケジューラ)が解決するまで作品ごとに一時的に起こり得ます');
      }
      var code = (res.j && res.j.error) || ('HTTP ' + res.s);
      var hint = code === 'bad_secret' ? '（共有シークレット不一致。⚙️の値とworkerのSHARED_SECRETを揃えてください）'
               : code === 'origin_not_allowed' ? '（このサイトのOriginがworkerで未許可）' : '';
      return line('FANZA作品情報', 'bad', code + hint);
    }).catch(function () { return line('FANZA作品情報', 'bad', '通信エラー（URL間違い/未デプロイ/オフライン）'); });
  }

  // ── ③ クリック計測（r2 link-worker）──
  function checkClicks() {
    var cfg = window.Go5Short || {};
    if (!cfg.WORKER_URL) return Promise.resolve(line('クリック計測', 'warn', '短縮worker設定が読めません'));
    return fetch(cfg.WORKER_URL.replace(/\/+$/, '') + '/api/stats?code=__diag__&secret=' + encodeURIComponent(cfg.SHARED_SECRET || ''))
      .then(function (r) { return r.json().then(function (j) { return { s: r.status, j: j }; }); })
      .then(function (res) {
        if (res.s === 401 || (res.j && res.j.error === 'bad_secret')) return line('クリック計測', 'bad', 'シークレット不一致（クリック数が全て取得不能）');
        return line('クリック計測', 'ok', 'worker応答OK（HTTP ' + res.s + '）');
      }).catch(function () { return line('クリック計測', 'bad', '通信エラー（worker未デプロイ/オフライン）'); });
  }

  // ── ④ 記録GAS（バージョン＋サーバー側自動記録の健全性）──
  function checkGas() {
    var gas = ls('bsky_gas_url');
    if (!gas) return Promise.resolve(line('記録GAS', 'warn', 'GAS URL未設定（🦋投稿タブ⚙で設定）'));
    return new Promise(function (resolve) {
      var done = false;
      var timer = setTimeout(function () { if (!done) { done = true; resolve(line('記録GAS', 'bad', '応答なし（デプロイ/アクセス権を確認）')); } }, 15000);
      // ping（バージョン）→ deltas（サーバー側自動記録が数値を返しているか）
      fetch(gas + (gas.indexOf('?') >= 0 ? '&' : '?') + 'ping=1').then(function (r) { return r.json(); }).then(function (p) {
        var ver = (p && p.version) || '?';
        return fetch(gas + (gas.indexOf('?') >= 0 ? '&' : '?') + 'action=deltas&callback=x').then(function (r) { return r.text(); }).then(function (t) {
          if (done) return; done = true; clearTimeout(timer);
          var m = t.match(/^x\((.*)\)$/s); var d = null;
          try { d = m ? JSON.parse(m[1]) : JSON.parse(t); } catch (e) {}
          var deltas = (d && d.deltas) || {};
          var vids = Object.keys(deltas);
          var hasNum = vids.some(function (v) { var x = deltas[v] || {}; return ['tv','yv','wv','tc','yc','wc'].some(function (k) { return x[k] != null; }); });
          if (!vids.length) resolve(line('記録GAS', 'warn', '稼働中(' + String(ver).slice(0, 13) + ')・スナップショット記録がまだありません（毎時トリガーの実行待ち）'));
          else if (!hasNum) resolve(line('記録GAS', 'warn', '稼働中(' + String(ver).slice(0, 13) + ')・全指標が未計算。GASのスクリプトプロパティ YT_API_KEY 未設定か、記録開始から日が浅い可能性'));
          else resolve(line('記録GAS', 'ok', '稼働中(' + String(ver).slice(0, 13) + ')・サーバー側自動記録も数値を返しています'));
        });
      }).catch(function () { if (!done) { done = true; clearTimeout(timer); resolve(line('記録GAS', 'bad', '通信エラー（URL/公開設定を確認）')); } });
    });
  }

  // ── ⑤ 記録GASへの<script>タグ読込（実際の「シートから復元」と同じ経路）──
  //   checkGas()はfetch()、実際の復元機能(yt-clicks.jsのjsonp_)は<script>タグ挿入。
  //   広告ブロッカー/セキュリティソフトはこの2つを別々に扱う(fetchは通すがscriptタグは遮断、等)ことが
  //   あるため、fetch()でOKでも実際の復元は失敗し得る。ここは実物と同じ<script>経路で直接検査する。
  function checkGasScriptTag() {
    var gas = ls('bsky_gas_url');
    if (!gas) return Promise.resolve(line('復元(シート読込)', 'warn', 'GAS URL未設定'));
    return new Promise(function (resolve) {
      var name = '__go5diag_' + Date.now(), done = false, t0 = Date.now();
      var s = document.createElement('script');
      function clean() { try { delete window[name]; } catch (e) { window[name] = undefined; } if (s.parentNode) s.parentNode.removeChild(s); }
      var timer = setTimeout(function () {
        if (done) return; done = true; clean();
        resolve(line('復元(シート読込)', 'bad', (Date.now() - t0) + 'msで応答なし(タイムアウト)。通信不安定またはGAS側の遅延'));
      }, 10000);
      window[name] = function (d) {
        if (done) return; done = true; clearTimeout(timer); clean();
        resolve((d && d.ok) ? line('復元(シート読込)', 'ok', '<script>読込も正常(HTTP経路と同じ結果)')
          : line('復元(シート読込)', 'bad', 'GASが応答しましたが内容が異常です'));
      };
      s.onerror = function () {
        if (done) return; done = true; clearTimeout(timer); clean();
        resolve(line('復元(シート読込)', 'bad', (Date.now() - t0) + 'msで読込失敗＝広告ブロッカー/セキュリティソフト/DNSフィルタが script.google.com への<script>読込だけを遮断している可能性が高いです(fetch()は通っても<script>だけ止める拡張機能があります)。拡張機能を無効化するかシークレットウィンドウで試してください'));
      };
      // ★action未指定でcallbackだけ送る＝GAS側のJSONP分岐(p.callback)がデフォルトの軽い応答
      //   ({ok:true,shortUrl:''})を返す。action=pingはcallbackより先に判定されJSONPで包まれない
      //   ため使えない(gas/コード.gs の doGet 参照)。
      s.src = gas + (gas.indexOf('?') >= 0 ? '&' : '?') + 'callback=' + name;
      document.body.appendChild(s);
    });
  }

  // ── ⑥ FANZA画像CDN（サムネイル表示の実体）──
  function checkImageCdn() {
    return new Promise(function (resolve) {
      var t0 = Date.now(), done = false;
      var img = new Image();
      var timer = setTimeout(function () { if (done) return; done = true; resolve(line('サムネ画像CDN', 'bad', (Date.now() - t0) + 'msで応答なし(タイムアウト)。回線が遅いか読み込みが遮断されている可能性')); }, 8000);
      img.onload = function () { if (done) return; done = true; clearTimeout(timer); resolve(line('サムネ画像CDN', 'ok', '正常(' + (Date.now() - t0) + 'ms)')); };
      img.onerror = function () { if (done) return; done = true; clearTimeout(timer); resolve(line('サムネ画像CDN', 'bad', (Date.now() - t0) + 'msで読込失敗＝広告ブロッカー/セキュリティソフト/DNSフィルタが doujin-assets.dmm.co.jp 等の画像を遮断している可能性が高いです')); };
      img.src = 'https://doujin-assets.dmm.co.jp/digital/comic/d_784975/d_784975pt.jpg?diag=' + Date.now();
    });
  }

  function runDiag() {
    var out = $('apiDiagResult'), btn = $('apiDiagBtn');
    if (!out) return;
    if (btn) btn.disabled = true;
    out.innerHTML = '<span style="color:var(--sub);">診断中…（数秒かかります）</span>';
    Promise.all([checkYouTube(), checkFanza(), checkClicks(), checkGas(), checkGasScriptTag(), checkImageCdn()]).then(function (lines) {
      out.innerHTML = lines.join('') +
        '<div class="hint" style="margin-top:6px;">⚠️/❌の行が故障箇所です。全部✅なのに一覧が「…」のままの場合は、投稿履歴タブの「🔄 更新」を押すか、少し待ってから再読込してください。「復元(シート読込)」「サムネ画像CDN」が❌の場合は、広告ブロッカー/セキュリティソフトの拡張機能を疑ってください(シークレットウィンドウ/拡張機能オフで再テスト推奨)。</div>';
      if (btn) btn.disabled = false;
    });
  }

  function init() { var b = $('apiDiagBtn'); if (b) b.addEventListener('click', runDiag); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
