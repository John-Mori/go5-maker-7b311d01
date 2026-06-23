/**
 * get-refresh-token.mjs — refresh_token を1回だけ取得するローカル補助スクリプト
 *
 * 使い方（SETUP.md 参照）：
 *   1) Google Cloud で「OAuthクライアント（ウェブアプリ）」を作成し、
 *      承認済みリダイレクトURIに  http://localhost:53682/oauth2callback  を登録
 *   2) そのクライアントのJSONを「client_secret.json」という名前でこのフォルダに保存
 *   3) このフォルダで:  node get-refresh-token.mjs
 *   4) 開いたブラウザで自分のGoogleアカウントを選び「許可」
 *   5) 画面とターミナルに表示される refresh_token をコピー
 *      → wrangler secret put GOOGLE_REFRESH_TOKEN で登録
 *
 * Node標準モジュールのみ（npm install 不要）。秘密はファイルに保存しない（標準出力に表示のみ）。
 */

import http from "node:http";
import https from "node:https";
import { readFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { URL, URLSearchParams } from "node:url";

const PORT = 53682;
const REDIRECT = `http://localhost:${PORT}/oauth2callback`;
const SCOPE = "https://www.googleapis.com/auth/drive"; // 承認済みスコープ（既存フォルダへ保存するため）

function loadCreds() {
  let raw;
  try { raw = readFileSync(new URL("./client_secret.json", import.meta.url), "utf8"); }
  catch (e) {
    console.error("✗ client_secret.json が見つかりません。SETUP.md の手順で取得し、このフォルダに置いてください。");
    process.exit(1);
  }
  const j = JSON.parse(raw);
  const o = j.web || j.installed || j;
  if (!o.client_id || !o.client_secret) {
    console.error("✗ client_secret.json の形式が不正です（client_id / client_secret が見つかりません）。");
    process.exit(1);
  }
  return { clientId: o.client_id, clientSecret: o.client_secret };
}

function openBrowser(url) {
  const platform = process.platform;
  try {
    // Windowsは cmd "start" だとURL内の & で途中で切れるため rundll32 で開く（URLをそのまま1引数で渡す）
    if (platform === "win32") spawn("rundll32", ["url.dll,FileProtocolHandler", url], { stdio: "ignore", detached: true });
    else if (platform === "darwin") spawn("open", [url], { stdio: "ignore", detached: true });
    else spawn("xdg-open", [url], { stdio: "ignore", detached: true });
  } catch (e) { /* 自動起動に失敗してもURLは表示する */ }
}

function exchangeCode(creds, code) {
  return new Promise((resolve, reject) => {
    const body = new URLSearchParams({
      code,
      client_id: creds.clientId,
      client_secret: creds.clientSecret,
      redirect_uri: REDIRECT,
      grant_type: "authorization_code",
    }).toString();
    const req = https.request("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "Content-Length": Buffer.byteLength(body) },
    }, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => {
        try { resolve(JSON.parse(data)); } catch (e) { reject(new Error(data)); }
      });
    });
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

const creds = loadCreds();
const authUrl = "https://accounts.google.com/o/oauth2/v2/auth?" + new URLSearchParams({
  client_id: creds.clientId,
  redirect_uri: REDIRECT,
  response_type: "code",
  scope: SCOPE,
  access_type: "offline",      // refresh_token を発行
  prompt: "consent",           // 毎回 refresh_token を確実に返す
}).toString();

const server = http.createServer(async (req, res) => {
  if (!req.url.startsWith("/oauth2callback")) { res.writeHead(404); res.end("not found"); return; }
  const u = new URL(req.url, REDIRECT);
  const err = u.searchParams.get("error");
  const code = u.searchParams.get("code");
  if (err) {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(`<h2>認証がキャンセルされました</h2><p>${err}</p>`);
    console.error("✗ 認証エラー:", err);
    server.close(); process.exit(1);
  }
  try {
    const tok = await exchangeCode(creds, code);
    if (!tok.refresh_token) {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end("<h2>refresh_token が取得できませんでした</h2><p>一度 https://myaccount.google.com/permissions でこのアプリのアクセスを解除してから、もう一度実行してください。</p>");
      console.error("✗ refresh_token が返りませんでした。myaccount.google.com/permissions でアクセス解除後に再実行してください。");
      server.close(); process.exit(1);
    }
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(`<h2 style="font-family:sans-serif">取得できました ✓</h2>
      <p style="font-family:sans-serif">下の refresh_token をコピーして、ターミナルの指示どおり登録してください。このタブは閉じてOKです。</p>
      <textarea style="width:100%;height:90px;font-size:14px" readonly>${tok.refresh_token}</textarea>`);
    console.log("\n==================== ここをコピー ====================\n");
    console.log("GOOGLE_REFRESH_TOKEN =\n" + tok.refresh_token);
    console.log("\n=====================================================\n");
    console.log("次のコマンドで登録（プロンプトに上の値を貼り付け）：");
    console.log("  npx wrangler secret put GOOGLE_REFRESH_TOKEN\n");
    server.close(); process.exit(0);
  } catch (e) {
    res.writeHead(500, { "Content-Type": "text/html; charset=utf-8" });
    res.end("<h2>トークン交換に失敗しました</h2><pre>" + String(e.message || e) + "</pre>");
    console.error("✗ トークン交換失敗:", e.message || e);
    server.close(); process.exit(1);
  }
});

server.on("error", (e) => {
  if (e.code === "EADDRINUSE") {
    console.error("\n✗ ポート53682が使用中です。前回の実行がまだ残っています。");
    console.error("  → 黒い画面（ターミナル）をすべて閉じて、開き直してから、もう一度 node get-refresh-token.mjs を実行してください。");
    console.error("  （または PowerShell で:  Stop-Process -Name node -Force  を実行してから再実行）\n");
  } else {
    console.error("✗ 起動エラー:", e.message || e);
  }
  process.exit(1);
});

server.listen(PORT, () => {
  console.log("ブラウザで同意画面を開きます。開かない場合は次のURLを手動で開いてください：\n");
  console.log(authUrl + "\n");
  openBrowser(authUrl);
});
