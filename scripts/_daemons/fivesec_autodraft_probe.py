"""β-5a 0歩目: 無人の Chrome 本体で本番ページから5秒動画を録れるかを測るだけのprobe。

アプリは改修しない。本番 index.html を Chrome(channel="chrome")で開き、
#photo へテスト画像を入れ、#testMode をONにして __go5RequestMake({draft:true}) を呼ぶ。
video-created の blob をディスクへ出し、ffprobe で コンテナ/コーデック/fps/秒数 を測って
LocalData/fivesec/autodraft_probe.log へ1行JSONで残す。

一時プロファイルなので sync token は無い=cloud(hasBlobR2At)は測れない(未測と記録する)。
受け入れ条件(設計§56): mp4/avc1・5.0秒・30fps・hasBlobR2At true・スマホ一覧で再生可。
"""
import argparse
import base64
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

PROD_URL = "https://john-mori.github.io/go5-maker-7b311d01/"
LOCAL_ROOT = r"D:\SougouStartFolder\LocalData\fivesec"
LOG_PATH = os.path.join(LOCAL_ROOT, "autodraft_probe.log")
OUT_DIR = os.path.join(LOCAL_ROOT, "autodraft_probe")
FFPROBE = shutil.which("ffprobe") or (
    r"C:\Users\chami\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffprobe.exe"
)

# video-created を拾って blob を base64 で window へ置く(ページ側の挙動は変えない)
HOOK_JS = """
window.__probe = { done: false };
document.addEventListener('video-created', async (ev) => {
  const d = ev.detail || {};
  const out = { name: d.name, title: d.title, draft: d.draft, test: d.test, videoId: d.videoId,
                type: d.blob && d.blob.type, size: d.blob && d.blob.size,
                hasBlobR2At: !!(d.blobR2At || (d.blob && d.blob.r2At)) };
  try {
    const buf = new Uint8Array(await d.blob.arrayBuffer());
    let s = ''; for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    out.b64 = btoa(s);
  } catch (e) { out.err = String(e); }
  window.__probe = Object.assign({ done: true }, out);
});
"""


def ffprobe(path):
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, encoding="utf-8",
    )
    if r.returncode != 0:
        return {"ffprobe_error": r.stderr.strip()[:300]}
    j = json.loads(r.stdout)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "format": j.get("format", {}).get("format_name"),
        "duration": float(j.get("format", {}).get("duration") or 0),
        "codec": v.get("codec_name"),
        "codec_tag": v.get("codec_tag_string"),
        "r_frame_rate": v.get("r_frame_rate"),
        "avg_frame_rate": v.get("avg_frame_rate"),
        "nb_frames": v.get("nb_frames"),
        "size": f'{v.get("width")}x{v.get("height")}',
    }


def run_once(mode, image, timeout_s):
    rec = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "mode": mode, "url": PROD_URL}
    args = ["--autoplay-policy=no-user-gesture-required"]
    headless = mode == "headless"
    if not headless:
        args.append("--window-position=-32000,0")
    prof = tempfile.mkdtemp(prefix="fivesec_autodraft_probe_")
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                prof, channel="chrome", headless=headless, args=args,
                viewport={"width": 430, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            console = []
            page.on("console", lambda m: console.append(f"{m.type}: {m.text}"[:200]))
            page.add_init_script(HOOK_JS)
            page.goto(PROD_URL, wait_until="load", timeout=60000)
            rec["ver"] = page.evaluate(
                "() => { const s=[...document.scripts].map(x=>x.src).find(x=>/app\\.js/.test(x)); return s||''; }")
            rec["ua"] = page.evaluate("() => navigator.userAgent")
            rec["mimes"] = page.evaluate("""() => ['video/mp4;codecs=avc1','video/mp4','video/webm;codecs=vp9','video/webm']
                .filter(m => window.MediaRecorder && MediaRecorder.isTypeSupported(m))""")
            page.locator("#photo").set_input_files(image)
            page.locator("#testMode").check(force=True)
            for sel, val in (("#author", "probe"), ("#top", "無人probe")):
                if page.locator(sel).count():
                    page.locator(sel).fill(val)
            page.wait_for_timeout(1500)
            page.evaluate("() => window.__go5RequestMake({draft:true})")
            status_js = "() => { const s=document.getElementById('status'); return s ? s.textContent.trim().slice(0,160) : ''; }"
            try:
                page.wait_for_function("() => window.__probe && window.__probe.done", timeout=timeout_s * 1000)
            except Exception:
                rec["status"] = page.evaluate(status_js)
                rec["console"] = console[-12:]
                raise
            pr = page.evaluate("() => window.__probe")
            rec["status"] = page.evaluate(status_js)
            b64 = pr.pop("b64", None)
            rec.update({k: pr.get(k) for k in ("name", "draft", "test", "type", "size", "hasBlobR2At", "err")})
            rec["hasBlobR2At"] = "未測(一時プロファイル=sync token無し)"
            if b64:
                os.makedirs(OUT_DIR, exist_ok=True)
                ext = "mp4" if "mp4" in (pr.get("type") or "") else "webm"
                path = os.path.join(OUT_DIR, f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{mode}.{ext}")
                with open(path, "wb") as f:
                    f.write(base64.b64decode(b64))
                rec["file"] = path
                rec["probe"] = ffprobe(path)
            rec["console_err"] = [c for c in console if c.startswith("error")][:5]
            ctx.close()
    except Exception as e:  # noqa: BLE001 - probeは失敗内容を記録して返す
        rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--modes", default="headless,headful")
    ap.add_argument("--timeout", type=int, default=60)
    a = ap.parse_args()
    os.makedirs(LOCAL_ROOT, exist_ok=True)
    for mode in a.modes.split(","):
        rec = run_once(mode.strip(), a.image, a.timeout)
        line = json.dumps(rec, ensure_ascii=False)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
