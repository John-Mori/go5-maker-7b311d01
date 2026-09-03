#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""競合Shorts 代表フレーム取得  (2026-07-29 改修部門α / Chami指示・分析部アーモンドアイ経由)

やること: GASの 競合_動画 から未取得のShortを引き、各1本の 4.5秒付近1枚 を抜き、
  ベホップ(強Gemini)で ①焼き込みのフック文字 ②コマ画像の中身の要約 を起こしてシートへ書き戻す。

方針(Chami条件):
  - 全編DLしない。yt-dlp --download-sections で 4.5秒付近の一瞬だけ取る。
  - 尺が4.5秒未満の動画は末尾フレームに落とす。取得位置 4.5秒 はChami確定。
  - 競合ID/実名は公開repoに出さない(このスクリプトはIDを実行時にGASから引くだけ・保持しない)。
  - ベホップのキー等の秘密は front/repo/ログに出さない。

前提ツール: ffmpeg(導入済) / yt-dlp(未導入なら `python -m pip install -U yt-dlp`)。
使い方:
  python scripts/comp_frames.py --check           # 疎通確認のみ(pending件数を出す・DL/生成しない)
  python scripts/comp_frames.py --limit 5         # 5本処理して書き戻す
  python scripts/comp_frames.py --limit 5 --dry   # DL＋視覚まで走るが書き戻さない(結果を印字)
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "behop"))
import behop  # noqa: E402  (ベホップの vision 経路を再利用: inline_data で画像を渡す)

GAS = json.load(open(os.path.join(ROOT, "scripts", "gas_deploy_config.json"), encoding="utf-8"))["execUrl"]
SECTION_START = 4.0       # DLする区間の開始秒(4.5をこの中に含める)
SECTION_END = 5.4         # DLする区間の終了秒
TARGET_OFFSET = 4.5 - SECTION_START   # 区間先頭からの目的フレーム位置(=0.5秒)
SHORT_TAIL_EPS = 0.15     # 短尺動画で末尾フレームを取る時の末尾からの戻し(秒)
BASE_MODEL = "gemini-flash-latest"   # flash基準(HQ 2026-07-30・安く)。実測(2026-07-30)でflashが
#   焼き込みタイトル・作者・コマ内セリフまで読めた=07-29の条件『flashだと認識が弱いなら要らない』は不成立。
#   proは無料枠が枯れやすい(実測で即quota)。flashは無料枠が広く、バッチ向き。
LITE_MODEL = "gemini-flash-lite-latest"   # ★1段降格先(選択肢1・モドリッチ msg 1544859485854498966 #2)。
#   flash-latest の無料枠が同じキーで尽きた(429)時、別枠のこのモデルへ落として当日打ち切りを減らす。
#   別モデル=別の無料枠(GenerateRequestsPerDayPerProjectPerModel-FreeTier)なので、同じキーで枠が増える。
LITE_FALLBACK_DEFAULT = True         # ★2026-09-03 ON。実フレーム3件で検証=latestは両鍵とも429(枠枯渇=6割打ち切りの
#   本体を再現)/flash-liteは3/3 ok で焼き込みの「引用:作者名＋テロップ」と誰が・何を・雰囲気の型分解を粒度良く取得。
#   降格が動くのはlatestが既に429の時だけ=代替は取得ゼロ(打ち切り)なので構造出力ゼロより厳密に良い。
#   実物= local/_work/comp_lite_report.md(モドリッチへ返した)。--lite/--no-lite で1回だけ上書き可。

VISION_PROMPT = (
    "この画像は縦型ショート動画(9:16)の1コマです。次を日本語で答え、JSONだけを返してください。\n"
    '{"frameText":"画面に焼き込まれている文字(フック/テロップ)をそのまま書き起こす。無ければ空文字",'
    '"panelDesc":"コマ(イラスト/写真)の中身を1〜2文で要約。誰が・何をしている・雰囲気"}\n'
    "余計な説明やコードフェンスは付けず、JSONオブジェクト1つだけを返す。"
)


def _secrets():
    """GAS doPost の SHARED_SECRET 候補(順に試す)。値は印字しない。"""
    out = []
    try:
        cfg = json.load(open(os.path.join(ROOT, "scripts", "scrape_config.json"), encoding="utf-8"))
        for k in ("sharedSecret", "adminSecret"):
            if cfg.get(k):
                out.append(cfg[k])
    except Exception:
        pass
    out.append("daremogamewoubawareteikukimihakanpekidekyukyokunoidol")  # GASのソフト鍵フォールバック
    return out


def gas_get(query, tries=3):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(f"{GAS}?{query}&callback=x", timeout=90) as r:
                raw = r.read().decode("utf-8", "replace").strip()
            return json.loads(re.sub(r"^x\(|\)$", "", raw))
        except Exception:
            time.sleep(3)
    return {}


def gas_write(items, tries=3):
    """comp_frame_write で書き戻す。SHARED_SECRET候補を順に試す。"""
    last = {}
    for sec in _secrets():
        payload = {"op": "comp_frame_write", "secret": sec, "items": items}
        for _ in range(tries):
            try:
                req = urllib.request.Request(GAS, data=json.dumps(payload).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=90) as r:
                    last = json.loads(r.read())
                break
            except Exception:
                time.sleep(3)
        if last.get("ok"):
            return last
        if last.get("error") and last.get("error") != "bad_secret":
            break
    return last


def have_ytdlp():
    return shutil.which("yt-dlp") is not None or _ytdlp_module()


def _ytdlp_module():
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def _run(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def ytdlp_cmd():
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def grab_frame(video_id, dur, workdir):
    """4.5秒付近(尺不足なら末尾)の1枚を frame.jpg として書き出す。成功でパス、失敗でNone。"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    seg = os.path.join(workdir, "seg.%(ext)s")
    short = dur and dur > 0 and dur < 4.6
    section = f"*0-{max(dur, 1):.1f}" if short else f"*{SECTION_START}-{SECTION_END}"
    dl = ytdlp_cmd() + [
        "--no-playlist", "--force-keyframes-at-cuts",
        "--download-sections", section,
        "-f", "bestvideo[height<=720]/best[height<=720]/best",
        "-o", seg, url,
    ]
    if not _run(dl):
        return None
    files = [f for f in os.listdir(workdir) if f.startswith("seg.")]
    if not files:
        return None
    segfile = os.path.join(workdir, files[0])
    frame = os.path.join(workdir, "frame.jpg")
    if short:
        ff = ["ffmpeg", "-y", "-sseof", f"-{SHORT_TAIL_EPS}", "-i", segfile,
              "-frames:v", "1", "-q:v", "3", frame]
    else:
        # 出力側シーク=区間先頭からデコードしてフレーム精度で TARGET_OFFSET を取る(PTS再設定に強い)
        ff = ["ffmpeg", "-y", "-i", segfile, "-ss", f"{TARGET_OFFSET}",
              "-frames:v", "1", "-q:v", "3", frame]
    if not _run(ff) or not os.path.exists(frame):
        # 末尾フォールバック(短尺誤判定・区間がPTSずれで空になった時)
        ff2 = ["ffmpeg", "-y", "-sseof", f"-{SHORT_TAIL_EPS}", "-i", segfile,
               "-frames:v", "1", "-q:v", "3", frame]
        if not _run(ff2) or not os.path.exists(frame):
            return None
    return frame


def parse_vision(text):
    """ベホップの返答からJSONを取り出す。コードフェンス/前後の地の文を許容。"""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    ft = str(d.get("frameText", "") or "").strip()
    pd = str(d.get("panelDesc", "") or "").strip()
    if not ft and not pd:
        return None
    return {"frameText": ft, "panelDesc": pd}


# ---------------------------------------------------------------- 打ち切りの見張り(モドリッチ msg 1544859485854498966・最優先)
#
# なぜ在るか: この収集は 2026-07〜09 に「毎日 pending の6割を 429 で黙って打ち切り→翌日へ
#   繰り越し」を続けたのに、打ち切りは %TEMP%\go5-comp-frames.log(誰も読まない)へしか出て
#   おらず、6割落ちても誰も気づかなかった。= 無警報滞留(D1)。ここはその穴を塞ぐ一枚。
#   設計は run_daily_teian_job.py と同じ思想=「脈は毎回書く / 便は止まり方が変わった日と
#   一定間隔だけ / どの便にも閉じ条件を1行(C-046)」。
PULSE = os.path.join(ROOT, "local", "_work", "comp_frames_pulse.md")   # producers.json が age で見張る脈
STATE = os.path.join(ROOT, "local", "_work", "comp_frames_state.json")
BODY  = os.path.join(ROOT, "local", "_work", "comp_frames_alert_body.txt")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
DEPT = "shorts-analyst"       # 競合監視の持ち主= 分析部門(comp_frames は「分析部アーモンドアイ経由」の道具)
QUIET_DAYS = 3                # 同じ止まり方が続く時、便を出す間隔(日)。毎日は鳴らさない(規律§3)


def classify_health(summary):
    """このランの止まり方。"ok" / "quota" / "fail"。
    - fail : 疎通/前提で落ちた(GAS不正・yt-dlp/ffmpeg無し・例外)= exit!=0 かつ 429以外。
    - quota: 429 で当日打ち切り、pending を1件以上取り残した(=今回の本体の再演)。
    - ok   : 打ち切りゼロで完走(pending 0本の平穏な日も含む)。
    """
    if summary.get("exit", 0) != 0 and not summary.get("quota_hit"):
        return "fail"
    if summary.get("quota_aborted", 0) > 0:
        return "quota"
    return "ok"


def should_alert(state, kind, today, quiet_days=QUIET_DAYS):
    """今日、便を出すべきか(純粋関数)。出す= ①止まり方が変わった日(節目は必ず1通) /
    ②同じ止まり方が続き前便から quiet_days 以上。出さない= ok が続く日 / 知らせた直後。"""
    st = state or {}
    was = str(st.get("last_kind") or "ok")
    if kind != was:
        return True
    if kind == "ok":
        return False
    last = str(st.get("last_alert_date") or "")
    if not last:
        return True
    try:
        d0 = dt.datetime.strptime(last, "%Y-%m-%d").date()
        d1 = dt.datetime.strptime(today, "%Y-%m-%d").date()
    except Exception:
        return True                          # 日付が読めない= 黙らせる理由にしない(fail-open)
    return (d1 - d0).days >= quiet_days


def _load_state():
    try:
        with open(STATE, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        f.write(json.dumps(state, ensure_ascii=False, indent=1))


def write_pulse(summary, kind, note=""):
    """★毎回書く脈(--check 以外)。更新が止まる= この収集ごと死んだ、と producers.json 側で読める。"""
    os.makedirs(os.path.dirname(PULSE), exist_ok=True)
    with open(PULSE, "w", encoding="utf-8") as f:
        f.write("# 競合フレーム収集 の脈(毎回上書き・モドリッチ msg 1544859485854498966)\n\n"
                "最終走行: %s\n"
                "状態: %s\n"
                "pending %d件 / 視覚化 %d件 / 打ち切り %d件 / スキップ %d件 / exit=%s\n"
                "%s\n"
                % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kind,
                   summary.get("pending", 0), summary.get("ok", 0),
                   summary.get("quota_aborted", 0), summary.get("skipped", 0),
                   summary.get("exit", 0), note))


def build_alert_body(kind, summary, today, streak):
    """便本文。★推測を書かず数を並べ、閉じ条件を1行で書く(C-046)。"""
    common_tail = (
        "\n■ 全文の脈: local/_work/comp_frames_pulse.md\n"
        "■ 次の自動便: 直るまで %d 日おき(毎日は鳴らさない)。打ち切り0の日に1回「戻った」を出す。\n"
        % QUIET_DAYS)
    if kind == "quota":
        return (
            "自動(競合フレーム日次収集 comp_frames)→ 分析部門\n\n"
            "■ **今日、無料枠が尽きて %d件を打ち切った**(pending %d件中・視覚化できたのは %d件・連続%d日目)。\n"
            "  429 で全キー(ベホップ/ホイミン)の flash 無料枠が尽き、残りは翌日 pending へ繰り越した。\n"
            "  ★これは2026-07〜09に『6割を黙って落として誰も気づかなかった』のと同じ形= だから鳴らしている。\n\n"
            "■ **閉じ条件**= 次の朝のランで打ち切り0件になること。手当ては2つ、選ぶのはChami:\n"
            "  1. flash-lite への1段降格(選択肢1)を ON にする= 同じキーの別枠を足して打ち切り前に粘る。\n"
            "     (品質が型分解に耐えるか検証してから ON。検証結果は改修部門αがモドリッチへ返す)\n"
            "  2. 1日に取りに行く上限(--limit)を実際に捌ける本数まで下げる= 毎日取り残しを繰り越さない。\n"
            % (summary.get("quota_aborted", 0), summary.get("pending", 0),
               summary.get("ok", 0), streak)
        ) + common_tail
    if kind == "fail":
        return (
            "自動(競合フレーム日次収集 comp_frames)→ 分析部門\n\n"
            "■ **収集が前提エラーで落ちた**(exit=%s・連続%d日目)。理由: %s\n"
            "  429の打ち切りではなく、疎通/前提(GAS応答・yt-dlp/ffmpeg・例外)側の故障だ。\n\n"
            "■ **閉じ条件**= 次の朝のランが正常終了(exit=0)すること。直った翌朝に1回「戻った」を出す。\n"
            "■ 手で試す: python scripts/comp_frames.py --check\n"
            % (summary.get("exit", 0), streak, summary.get("note") or "(不明)")
        ) + common_tail
    return (   # ok(戻った)
        "自動(競合フレーム日次収集 comp_frames)→ 分析部門\n\n"
        "■ **戻った**。今日のランは打ち切り0件で完走した(視覚化 %d件 / pending %d件)。\n"
        "  直前まで %d日続けて打ち切り/故障で止まっていた分は、これで閉じる。\n"
        % (summary.get("ok", 0), summary.get("pending", 0), streak)
    ) + common_tail


def dispatch_alert(body, dept=DEPT):
    os.makedirs(os.path.dirname(BODY), exist_ok=True)
    with open(BODY, "w", encoding="utf-8") as f:      # ★BOM無し(dispatch は utf-8 で読む)
        f.write(body)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, DISPATCH, "--dept", dept, "--direct",
                        "--from-dept", "system-engineer", "--audience", "ai",
                        "--from", "自動(競合フレーム日次収集 comp_frames)",
                        "--body-file", BODY],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout or r.stderr or "").strip()


def emit_health(args, summary):
    """脈を毎回書き、止まり方に応じて分析部門へ便を(スロットルして)出す。
    ★--check は疎通だけなので何も出さない。--dry は脈のみ(便は出さない)。本処理は絶対に止めない。"""
    if getattr(args, "check", False):
        return
    kind = classify_health(summary)
    today = dt.datetime.now().strftime("%Y-%m-%d")
    if getattr(args, "dry", False):
        write_pulse(summary, "%s(--dry)" % kind, note="--dry のため便は出さない")
        return
    state = _load_state()
    ok = (kind == "ok")
    streak = 1 if ok else int(state.get("fail_streak") or 0) + 1
    alert = should_alert(state, kind, today)
    state["last_run_at"] = dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    state["last_kind"] = kind
    state["fail_streak"] = 0 if ok else streak
    sent = ""
    if alert:
        acode, aout = dispatch_alert(build_alert_body(kind, summary, today, streak))
        if acode == 0:                       # 便が出せた日だけ日付を進める(出せない日は次回出し直し)
            state["last_alert_date"] = today
        sent = " / 分析部門へ便 exit=%s" % acode
        print("  警報: 分析部門へ便 exit=%s %s" % (acode, aout[:120]))
    _save_state(state)
    write_pulse(summary, kind, note=("止まり方=%s・連続%s日目%s" % (kind, streak, sent)) if not ok else "打ち切り0で完走")


def _collect(args, summary):
    """本処理。summary へ pending/ok/quota_aborted/skipped/quota_hit/note を書き込みつつ exit を返す。
    ★名前は _collect。サブプロセス用ヘルパ _run(cmd) と衝突させない(grab_frame が _run を使う)。"""
    pend = gas_get(f"action=comp_frame_pending&limit={args.limit}")
    if not pend.get("ok"):
        summary["note"] = f"comp_frame_pending 応答不正: {pend.get('error') or pend}"
        print(f"ABORT: {summary['note']}")
        return 2
    items = pend.get("pending", [])
    summary["pending"] = pend.get("count", len(items))
    print(f"pending: {summary['pending']}件")
    if args.check:
        return 0
    if not items:
        return 0

    if not have_ytdlp():
        summary["note"] = "yt-dlp が無い(python -m pip install -U yt-dlp)"
        print(f"ABORT: {summary['note']}")
        return 3
    if not shutil.which("ffmpeg"):
        summary["note"] = "ffmpeg が無い"
        print(f"ABORT: {summary['note']}")
        return 3

    key = behop._read(behop.KEY_FILE, "ベホップ用APIキー")
    # flash基準で読めるだけ読む→無料枠が尽きたらその日は打ち切り→残りは翌日pendingへ繰り越し(冪等)。
    if BASE_MODEL not in behop.list_models(key):
        summary["note"] = f"{BASE_MODEL} がこのキーで使えません"
        print(f"ABORT: {summary['note']}")
        return 5
    # ★2枠束ね(Chami 2026-07-30・msg 1532071671765143773「もしflashでも問題なければ
    #   もうひとつのGemini(ホイミン)も必要なら優先的に使って」)。ベホップのflash無料枠が
    #   尽きた(429)ら、ホイミンのキー(local/gemini_api_key.txt・別アカ=別枠)へ切り替えて続行する。
    #   ホイミンの別キーでも flash が焼き込み文字を読めることは実測済(2026-07-30)。無ければ従来通り1枚で回す。
    keys = [("ベホップ", key)]
    try:
        homin = open(os.path.join(ROOT, "local", "gemini_api_key.txt"), encoding="utf-8").read().strip()
    except OSError:
        homin = ""
    if homin and homin != key:
        keys.append(("ホイミン", homin))

    # flash-lite への1段降格(選択肢1)。--lite/--no-lite が無ければ既定(LITE_FALLBACK_DEFAULT)。
    use_lite = LITE_FALLBACK_DEFAULT if args.lite is None else args.lite
    print(f"flash-lite降格: {'ON' if use_lite else 'OFF'}(429で同キーのflash-liteへ落として続行{'する' if use_lite else 'しない'})")

    results, ok, skipped = [], 0, 0
    quota_hit = False
    kidx = 0                 # 現在使っているキーの番号(429で尽きたら次へ進めて戻さない)
    for i, it in enumerate(items):
        vid = it.get("videoId", "")
        dur = float(it.get("durationSec") or 0)
        if not vid:
            skipped += 1
            continue
        work = tempfile.mkdtemp(prefix="cf_")
        try:
            frame = grab_frame(vid, dur, work)
            if not frame:
                print(f"  {vid}: フレーム取得失敗(スキップ)")
                skipped += 1
                continue
            # 現キーで flash を試す。429なら(降格ONの時)同じキーの flash-lite へ1段落として粘り、
            # それも429なら初めてそのキーを諦めて次のキー(ホイミン)へ回して同じフレームを取り直す。
            text, status = None, None
            while kidx < len(keys):
                kname, kval = keys[kidx]
                text, status = behop.ask_pro(kval, VISION_PROMPT, [frame], BASE_MODEL,
                                             tag="comp_frames", who=behop.bundle_of(kname))
                if status == "quota":
                    if use_lite:
                        # ★同じキーの別枠(flash-lite)へ降格して同じフレームを読み直す(選択肢1)。
                        text, status = behop.ask_pro(kval, VISION_PROMPT, [frame], LITE_MODEL,
                                                     tag="comp_frames_lite", who=behop.bundle_of(kname))
                        if status != "quota":
                            print(f"  {vid}: {kname}のflash枠が尽きた→同キーのflash-liteで続行")
                            summary["lite_used"] = summary.get("lite_used", 0) + 1
                            break        # lite枠は生きている(ok or error)。以降は通常判定へ。
                    print(f"  {vid}: {kname}のflash{'/lite両' if use_lite else ''}無料枠が尽きた(429)→次のキーへ切替")
                    kidx += 1
                    continue
                break
            if kidx >= len(keys):
                # ★当日打ち切り。この item(i) と以降は未収集= 打ち切り件数(モドリッチが数えたい本体)。
                summary["quota_aborted"] = len(items) - i
                print(f"  {vid}: 全キーの無料枠が尽きた(429)。本日はここで打ち切り、"
                      f"残り{summary['quota_aborted']}件は翌日pendingへ繰り越し。")
                quota_hit = True
                break
            if status != "ok":
                print(f"  {vid}: 視覚失敗({status})スキップ")
                skipped += 1
                continue
            v = parse_vision(text)
            if not v:
                print(f"  {vid}: 視覚結果パース失敗(スキップ)")
                skipped += 1
                continue
            results.append({"videoId": vid, "frameText": v["frameText"], "panelDesc": v["panelDesc"]})
            ok += 1
            print(f"  {vid}: frameText={v['frameText'][:24]!r} panelDesc={v['panelDesc'][:32]!r}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        time.sleep(1.0)

    summary["ok"] = ok
    summary["skipped"] = skipped
    summary["quota_hit"] = quota_hit
    print(f"視覚化 {ok}/{len(items)} 件"
          + (f"(無料枠429で{summary['quota_aborted']}件打ち切り・残りは翌日)" if quota_hit else ""))
    if args.dry:
        print("--dry のため書き戻さない")
        return 0
    if not results:
        return 0
    w = gas_write(results)
    if w.get("ok"):
        print(f"書き戻し: {w.get('written', 0)}件")
        return 0
    summary["note"] = f"書き戻し失敗: {w.get('error') or w}"
    print(summary["note"])
    return 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--check", action="store_true", help="pending件数だけ出す(DL/生成しない)")
    ap.add_argument("--dry", action="store_true", help="DL＋視覚まで走るが書き戻さない")
    ap.add_argument("--lite", dest="lite", action="store_true", default=None,
                    help="flash枠が尽きたら同キーのflash-liteへ降格して続行(既定はLITE_FALLBACK_DEFAULT)")
    ap.add_argument("--no-lite", dest="lite", action="store_false",
                    help="降格しない(429でそのキーは打ち切り)")
    args = ap.parse_args()

    # summary= このランの実数。_run が埋め、emit_health が脈と便へ流す。exit で終わっても finally で必ず脈を残す。
    summary = {"pending": 0, "ok": 0, "quota_aborted": 0, "skipped": 0,
               "quota_hit": False, "exit": 0, "note": ""}
    code = 0
    try:
        code = _collect(args, summary)
    except Exception as e:               # ★例外でも脈を落とさない(黙って死ぬのを塞ぐのが本義)
        summary["note"] = f"例外: {e!r}"
        print(f"ABORT(例外): {e!r}")
        code = 99
    finally:
        summary["exit"] = code
        try:
            emit_health(args, summary)
        except Exception as e:           # 見張り自身の失敗は本処理を巻き込まない
            print(f"(健康便の書き込みに失敗・本処理には影響なし: {e!r})")
    return code


if __name__ == "__main__":
    sys.exit(main())
