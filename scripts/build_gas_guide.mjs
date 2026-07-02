/**
 * build_gas_guide.mjs — GAS自動記録セットアップ・ガイドHTMLを生成。
 * gas/コード.gs の中身をコピー用ブロックに埋め込む（HTMLエスケープ）。
 * 実行: node scripts/build_gas_guide.mjs → GAS自動記録_設定ガイド.html
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const code = fs.readFileSync(path.join(root, 'gas', 'コード.gs'), 'utf8');
const codeEsc = esc(code);

const EXEC = 'https://script.google.com/macros/s/AKfycbyQlrWuud5WfE3YMjoYzX2WhstTyWw_sOxVCaT8EfaFMXwi_WZzWIBKarHdtXVsY3Fj/exec';
const PING = EXEC + '?ping=1';
const MIGRATE = EXEC + '?action=migrate_headers';
const SS = 'https://docs.google.com/spreadsheets/d/1DcOXq9nVZOf6n9ILTxRuuN3P-jxsh3bYVmoEZ0JkE44/edit';
const SCRIPT_HOME = 'https://script.google.com/home';

// コピー用ブロック（1行URL/値用）
const cb = (text) => '<div class="cb"><pre class="cb-t">' + esc(text) + '</pre><button class="cbtn" type="button" onclick="cp(this)">コピー</button></div>';

const html = `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GAS 自動記録セットアップ・ガイド</title>
<style>
:root{
  --bg:#f5edd7; --paper:#fffdf5; --ink:#4b3f2c; --sub:#8a7a5c; --line:#e6d6ad;
  --accent:#c26a3f; --accent2:#7a9a54; --badge:#c26a3f; --code-bg:#fbf4e0; --code-ink:#5a4a2e; --warn:#b5533a;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",system-ui,sans-serif;line-height:1.75;padding:18px;}
.wrap{max-width:760px;margin:0 auto;}
header{text-align:center;margin:6px 0 18px;}
header h1{font-size:22px;margin:0 0 6px;color:var(--accent);}
header p{margin:0;color:var(--sub);font-size:14px;}
.card{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin:0 0 16px;
  box-shadow:0 4px 14px rgba(150,115,55,.08);}
.lead{font-size:14.5px;}
.lead b{color:var(--accent);}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;justify-content:center;margin:14px 0 4px;}
.flow .node{background:#fbf4e0;border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:12.5px;font-weight:700;color:var(--ink);text-align:center;}
.flow .arw{color:var(--accent);font-weight:900;}
.step{display:flex;gap:12px;align-items:flex-start;margin-top:6px;}
.step-no{flex:0 0 34px;height:34px;border-radius:50%;background:var(--badge);color:#fff;font-weight:800;
  display:flex;align-items:center;justify-content:center;font-size:16px;box-shadow:0 2px 6px rgba(194,106,63,.35);}
.step-body{flex:1;min-width:0;}
.step-body h2{font-size:16.5px;margin:4px 0 8px;color:var(--ink);}
.step-body ol,.step-body ul{margin:6px 0;padding-left:20px;}
.step-body li{margin:4px 0;}
.k{background:#f0e7cf;border:1px solid var(--line);border-radius:6px;padding:1px 7px;font-weight:700;font-family:ui-monospace,Menlo,monospace;font-size:.9em;color:var(--accent);white-space:nowrap;}
.path{background:#f0e7cf;border-radius:6px;padding:1px 8px;font-weight:700;font-size:.92em;}
/* コピー用ブロック（URL・値） */
.cb{display:flex;align-items:stretch;gap:0;margin:8px 0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--code-bg);}
.cb-t{margin:0;flex:1;min-width:0;overflow-x:auto;white-space:nowrap;padding:10px 12px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;color:var(--code-ink);}
.cbtn{flex:0 0 auto;border:none;background:var(--accent);color:#fff;font-weight:700;font-size:12.5px;padding:0 14px;cursor:pointer;}
.cbtn:active{opacity:.8}
.cbtn.done{background:var(--accent2);}
.note{background:#fbf4e0;border-left:4px solid var(--accent2);border-radius:8px;padding:10px 12px;margin:10px 0;font-size:13px;color:#5a4a2e;}
.warn{background:#fdeee6;border-left:4px solid var(--warn);border-radius:8px;padding:10px 12px;margin:10px 0;font-size:13px;color:#7a3b2a;}
.warn b{color:var(--warn);}
details.code{margin:10px 0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--code-bg);}
details.code>summary{cursor:pointer;padding:10px 12px;font-weight:700;color:var(--accent);list-style:none;}
details.code>summary::-webkit-details-marker{display:none}
details.code>summary::before{content:"▶ ";}
details.code[open]>summary::before{content:"▼ ";}
.code-head{display:flex;justify-content:flex-end;padding:6px 8px 0;}
.codebox{margin:0;max-height:340px;overflow:auto;padding:10px 12px;font-family:ui-monospace,Menlo,Consolas,monospace;
  font-size:11px;line-height:1.5;color:var(--code-ink);white-space:pre;}
.check{background:#eef3e2;border:1px solid #cdd9b0;border-radius:12px;padding:14px 16px;}
.check h2{margin:0 0 8px;font-size:16px;color:var(--accent2);}
.small{color:var(--sub);font-size:12.5px;}
.tag{display:inline-block;background:var(--accent);color:#fff;border-radius:6px;font-size:11px;padding:1px 7px;font-weight:700;margin-right:4px;}
.ok{color:var(--accent2);font-weight:700;}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>⚙️ GAS 自動記録セットアップ・ガイド</h1>
  <p>再生数・クリック数を「アプリを開かなくても」自動で記録するための初期設定（1回だけ・約5〜10分）</p>
</header>

<div class="card">
  <p class="lead">この設定を終えると、以下が<b>サーバー側（GAS）で自動的に</b>貯まります：</p>
  <ul>
    <li>各投稿の<b>今日 / 昨日 / 直近1週間</b>の再生数・クリック数の増加（ゴミ箱の左に表示）</li>
    <li>ランキングの<b>30分 / 1時間 / 2時間 / 6時間 / 24時間</b>バケット</li>
    <li><b>最大瞬間風速ランキング</b>（一番伸びた時間帯とその伸び率）＝スプレッドシートに永久保存</li>
  </ul>
  <div class="flow">
    <span class="node">毎時トリガー</span><span class="arw">→</span>
    <span class="node">GASが再生数＋<br>クリック数を取得</span><span class="arw">→</span>
    <span class="node">スプレッドシートに記録</span><span class="arw">→</span>
    <span class="node">アプリに表示</span>
  </div>
  <p class="small">※アプリ（スマホ）は表示するだけ。記録はGoogleのサーバーが淡々と続けます。</p>
</div>

<div class="card">
  <div class="step">
    <div class="step-no">1</div>
    <div class="step-body">
      <h2>コードを最新版に貼り替える</h2>
      <ol>
        <li>スプレッドシートを開く（下のURLをコピーしてブラウザで開く）
          ${cb(SS)}
        </li>
        <li>上メニュー <span class="path">拡張機能</span> → <span class="path">Apps Script</span> をクリック（エディタが開きます）。<br>
          <span class="small">開けない場合はこちら（Apps Scriptのホーム）からプロジェクトを開く：</span>
          ${cb(SCRIPT_HOME)}
        </li>
        <li>エディタ左の <span class="path">コード.gs</span> を選び、<b>中の文字を全部消して</b>（Windowsは <span class="k">Ctrl+A</span> → <span class="k">Delete</span>）、下の「最新コード」を<b>まるごと貼り付け</b>。</li>
        <li><span class="k">Ctrl+S</span>（または 💾 保存）で保存。</li>
      </ol>
      <details class="code">
        <summary>最新コード（コード.gs）を開く／コピー</summary>
        <div class="code-head"><button class="cbtn" type="button" onclick="cpCode(this)">全部コピー</button></div>
        <pre class="codebox" id="gascode">${codeEsc}</pre>
      </details>
      <div class="note">貼り替えは「今回追加した機能（自動記録・ランキング・カテゴリAI/OL/総集編 など）」を動かすために必須です。既存の設定・記録は消えません。</div>
    </div>
  </div>
</div>

<div class="card">
  <div class="step">
    <div class="step-no">2</div>
    <div class="step-body">
      <h2>YouTube APIキーを登録（スクリプトプロパティ）</h2>
      <p>再生数の自動取得にはキーが必要です。<b>アプリの ⚙詳細設定 に入れているYouTube APIキーと同じ値</b>を使います。</p>
      <ol>
        <li>エディタ左下の <span class="path">⚙ プロジェクトの設定</span> をクリック。</li>
        <li>下へスクロールし <span class="path">スクリプト プロパティ</span> → <span class="path">スクリプト プロパティを追加</span>。</li>
        <li><b>プロパティ（名前）</b>に、これを貼り付け：
          ${cb('YT_API_KEY')}
        </li>
        <li><b>値</b>に、アプリのYouTube APIキーを貼り付け（例：<span class="k">AIza…</span> で始まる文字列）。</li>
        <li><span class="path">スクリプト プロパティを保存</span> をクリック。</li>
      </ol>
      <div class="warn"><b>注意：</b>このキーは他人に渡さないでください。ここ（自分のGASの設定）にだけ入れます。</div>
    </div>
  </div>
</div>

<div class="card">
  <div class="step">
    <div class="step-no">3</div>
    <div class="step-body">
      <h2>新しいバージョンで再デプロイ</h2>
      <p>コードの変更を「公開版」に反映します。<b>ここを忘れると変更が効きません</b>（毎回ここでつまずきがち）。</p>
      <ol>
        <li>エディタ右上 <span class="path">デプロイ</span> → <span class="path">デプロイを管理</span>。</li>
        <li>今あるデプロイの右の <b>鉛筆✏️（編集）</b> をクリック。</li>
        <li><span class="path">バージョン</span> のプルダウンで <b>「新バージョン」</b> を選ぶ。</li>
        <li><span class="path">デプロイ</span> をクリックして完了。</li>
      </ol>
      <p><b>反映チェック：</b>下のURLを開いて、<span class="ok">2026-07-02G</span>（またはそれ以降）と表示されればOK。</p>
      ${cb(PING)}
      <div class="note">「<span class="k">version</span>」が古い日付のままなら、まだ新バージョンになっていません。もう一度「デプロイ → デプロイを管理 → ✏️ → 新バージョン」を試してください。</div>
    </div>
  </div>
</div>

<div class="card">
  <div class="step">
    <div class="step-no">4</div>
    <div class="step-body">
      <h2>自動記録をオンにする（トリガー設定）</h2>
      <ol>
        <li>エディタ上部の関数プルダウンで <span class="k">setupTrigger</span> を選ぶ。</li>
        <li><span class="path">▶ 実行</span> をクリック。</li>
        <li>初回は<b>権限の承認</b>ダイアログが出ます → 自分のGoogleアカウントを選択 → 「詳細」→「（安全ではないページ）に移動」→「許可」。<br>
          <span class="small">※自分で作った自分用スクリプトなので許可して問題ありません。</span></li>
        <li>これで<b>毎時、自動で記録</b>されるようになります。</li>
      </ol>
      <div class="note">すぐ1回記録したいときは、関数プルダウンで <span class="k">snapshotStats</span> を選んで <span class="path">▶ 実行</span>。今の再生数・クリック数がすぐ記録されます。</div>
    </div>
  </div>
</div>

<div class="card">
  <div class="step">
    <div class="step-no">5</div>
    <div class="step-body">
      <h2>（まだなら）スプレッドシートの列を追加</h2>
      <p>「カテゴリ／作品状態／共有URL」列がまだ無い場合だけ。下のURLを1回開くと自動で列が追加されます（何度開いても安全）。</p>
      ${cb(MIGRATE)}
      <p class="small">開くと <span class="k">{"ok":true,...}</span> のような文字が表示されればOK（閉じて大丈夫）。</p>
    </div>
  </div>
</div>

<div class="card check">
  <h2>✅ 仕上がりチェック</h2>
  <ul>
    <li><span class="tag">確認1</span> STEP3のURLで <span class="ok">2026-07-02G</span> 以降が出る</li>
    <li><span class="tag">確認2</span> アプリの📋投稿履歴で、ゴミ箱の左に「今日 / 昨日 / 週」が出る（<b>数字は貯まるまで数日</b>かかります）</li>
    <li><span class="tag">確認3</span> 🏆ランキングに「再生ピーク」「クリックピーク」「30分〜24時間」タブが増えている</li>
  </ul>
  <div class="note">
    <b>数字がすぐ出ない理由（正常です）：</b><br>
    ・「今日の増加」は<b>2日分たまってから</b>意味を持ちます（初日は基準づくり）。<br>
    ・「最大瞬間風速」「バケット」は<b>2回目以降の記録</b>から差分が出ます。<br>
    毎時トリガーが回れば自動で貯まります。急ぐときはSTEP4の <span class="k">snapshotStats</span> を時間をあけて2回手動実行してください。
  </div>
</div>

<p class="small" style="text-align:center;margin:18px 0 6px;">うまくいかないときは、STEP3の <span class="k">?ping=1</span> の表示（バージョン）を教えてください。どこで止まっているかすぐ分かります。</p>
</div>

<script>
function flash(btn){ var t=btn.textContent; btn.textContent='✓ コピー'; btn.classList.add('done'); setTimeout(function(){ btn.textContent=t; btn.classList.remove('done'); },1400); }
function copyText(text,btn){
  if(navigator.clipboard&&navigator.clipboard.writeText){ navigator.clipboard.writeText(text).then(function(){flash(btn);}).catch(function(){fallback(text,btn);}); }
  else fallback(text,btn);
}
function fallback(text,btn){ var ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); try{document.execCommand('copy');flash(btn);}catch(e){} document.body.removeChild(ta); }
function cp(btn){ var pre=btn.previousElementSibling; copyText(pre.textContent,btn); }
function cpCode(btn){ copyText(document.getElementById('gascode').textContent,btn); }
</script>
</body>
</html>`;

fs.writeFileSync(path.join(root, 'GAS自動記録_設定ガイド.html'), html);
console.log('生成: GAS自動記録_設定ガイド.html  (code ' + code.split('\n').length + ' lines embedded)');
