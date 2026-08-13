# -*- coding: utf-8 -*-
"""競合日次ランキングを集計し、分析部門の部屋へアーモンドアイ名義で1本push(毎朝08:00の常駐が呼ぶ)。

依頼元= 分析部門(アーモンドアイ, msg 1537489528393171025)。無人化の配送は基盤(platform-se)側で持つ。
分析部門は §4.7 で自分では persona_send を叩けないため、この常駐が代わりに配送する。

やること:
  1) python scripts/analysis/competitor_daily.py --emit を実行(GAS取得は最長数分・スクリプト側で最大4回リトライ)
  2) rc==0 かつ stdout が非空なら、その5行サマリを 分析部門の部屋へ アーモンドアイ名義で post
  3) 失敗時(GASが4回ともJSONでない等で異常終了)は、黙らず「自動集計が失敗した」旨を同じ部屋へ1本出す
     (=沈黙を成功と誤認させない。dispatch補足「失敗時はその時だけエラー通知を」の機構化)
  --dry: 集計は本当に走らせるが post はせず、本文を stdout に出すだけ(本番部屋を汚さずに配線を検証する用)

ログ= local/competitor_daily_push.log(読めないログは記録が無いのと同じ=UTF-8で残す)。
"""
import os, sys, subprocess, datetime, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable or "python"
EMIT = [PY, os.path.join("scripts", "analysis", "competitor_daily.py"), "--emit"]
SEND = [PY, os.path.join("scripts", "discord", "persona_send.py"),
        "--dept", "shorts-analyst", "--persona", "アーモンドアイ"]
LOG = os.path.join(ROOT, "local", "competitor_daily_push.log")
DRY = "--dry" in sys.argv
# 子プロセスの stdout を必ず UTF-8 で吐かせる(Windows既定=cp932 のままだと親が
# utf-8 で読めず reader スレッドが落ちて出力が丸ごと消える。タスク経由でもBash直叩きでも同じにする)。
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def _log(msg):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %s" % (stamp, msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line)


def _deliver(body):
    """body を --body-file 経由で分析部門の部屋へ post(改行安全・長さ壁も避ける)。"""
    fd, path = tempfile.mkstemp(prefix="compdaily_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        r = subprocess.run(SEND + ["--body-file", path], cwd=ROOT, env=CHILD_ENV,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        if r.returncode == 0:
            _log("配送OK: %s" % (r.stdout or "").strip()[:200])
        else:
            _log("配送NG rc=%d err=%s" % (r.returncode, ((r.stderr or r.stdout or "").strip())[:300]))
        return r.returncode == 0
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def main():
    _log("=== 競合日次 開始 (dry=%s) ===" % DRY)
    try:
        r = subprocess.run(EMIT, cwd=ROOT, env=CHILD_ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        _log("集計タイムアウト(600秒超)")
        if not DRY:
            _deliver("競合日次(自動): 08:00の自動集計がタイムアウトしました(GAS応答待ちで600秒超)。"
                     "手動で再実行してください。詳細= local/competitor_daily_push.log")
        return 1

    body = (r.stdout or "").strip()
    if r.returncode == 0 and body:
        _log("集計OK: %d文字 / %d行" % (len(body), body.count("\n") + 1))
        if DRY:
            _log("--dry: postせず本文を表示\n----\n%s\n----" % body)
            return 0
        return 0 if _deliver(body) else 1

    # 失敗: 黙らずに部屋へ知らせる(GASが4回ともJSONでない/その他の異常終了)
    err = (r.stderr or "").strip()[-400:]
    _log("集計NG rc=%d stderr=%s" % (r.returncode, err))
    if DRY:
        _log("--dry: 失敗のため post もスキップ")
        return 1
    _deliver("競合日次(自動): 08:00の自動集計が失敗しました(GAS応答がJSONでない/リトライ後の異常終了)。"
             "手動で `python scripts/analysis/competitor_daily.py` を再実行してください。"
             "詳細= local/competitor_daily_push.log")
    return 1


if __name__ == "__main__":
    sys.exit(main())
