# -*- coding: utf-8 -*-
"""毎朝のコミュニティ投稿ブリーフを、分析部門の部屋へアーモンドアイ名義で1本push(毎朝08:00の常駐が呼ぶ)。

背景= Chami 2026-09-02「差し替え」指示(msg 1544486499653910629)。
  従来の毎朝の押し出し=競合"動画"日次は上流(GAS)が8/18で止まり毎朝同じ内容の再掲になっていた。
  → 動きのある競合"コミュニティ投稿"の分析(記号ゼロの短いブリーフ)へ中身を差し替える。
  動画のGASが復旧したら、動画の一行を戻すのは別途(competitor_daily_push.py は残置)。

やること:
  1) python scripts/analysis/community_daily.py --emit --fresh --top N を実行
     (--fresh= 先に community_scrape.py で収集を更新してから分析=毎朝新しい中身になる)
  2) rc==0 かつ stdout が非空なら、その短いブリーフを 分析部門の部屋へ アーモンドアイ名義で post
  3) 失敗時(材料0件・異常終了)は、黙らず「自動集計が失敗した」旨を同じ部屋へ1本出す(沈黙=成功と誤認させない)
  --dry: 集計は本当に走らせるが post はせず、本文を stdout に出すだけ(本番部屋を汚さず配線検証する用)

分析部門は §4.7 で自分では persona_send を叩けないため、この常駐が代わりに配送する。
ログ= local/community_daily_push.log(UTF-8)。
"""
import os, sys, subprocess, datetime, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable or "python"
TOP = "3"
EMIT = [PY, os.path.join("scripts", "analysis", "community_daily.py"),
        "--emit", "--fresh", "--top", TOP]
SEND = [PY, os.path.join("scripts", "discord", "persona_send.py"),
        "--dept", "shorts-analyst", "--persona", "アーモンドアイ"]
LOG = os.path.join(ROOT, "local", "community_daily_push.log")
DRY = "--dry" in sys.argv
# 子プロセスの stdout を必ず UTF-8 で(Windows既定=cp932 だと親が読めず出力が消える)
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
    fd, path = tempfile.mkstemp(prefix="commdaily_", suffix=".txt")
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
    _log("=== コミュニティ日次 開始 (dry=%s) ===" % DRY)
    try:
        r = subprocess.run(EMIT, cwd=ROOT, env=CHILD_ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        _log("集計タイムアウト(600秒超)")
        if not DRY:
            _deliver("コミュニティ日次(自動): 08:00の自動集計がタイムアウトしました(収集/視覚で600秒超)。"
                     "手動で再実行してください。詳細= local/community_daily_push.log")
        return 1

    # --emit の本文は最終行のブリーフ。進捗ログ(収集を更新/503再試行 等)が前に混じるので、
    # 「おはよう、Chami」で始まるブリーフ本体だけを取り出して配送する。
    out = (r.stdout or "")
    idx = out.find("おはよう、Chami")
    body = out[idx:].strip() if idx >= 0 else out.strip()

    if r.returncode == 0 and idx >= 0 and body:
        _log("集計OK: %d文字 / %d行" % (len(body), body.count("\n") + 1))
        if DRY:
            _log("--dry: postせず本文を表示\n----\n%s\n----" % body)
            return 0
        return 0 if _deliver(body) else 1

    # 失敗: 黙らずに部屋へ知らせる(材料0件/収集失敗/異常終了)
    err = (r.stderr or out or "").strip()[-400:]
    _log("集計NG rc=%d 末尾=%s" % (r.returncode, err))
    if DRY:
        _log("--dry: 失敗のため post もスキップ")
        return 1
    _deliver("コミュニティ日次(自動): 08:00の自動集計が失敗しました(材料0件か収集/分析の異常終了)。"
             "手動で `python scripts/analysis/community_daily.py --emit --fresh` を再実行してください。"
             "詳細= local/community_daily_push.log")
    return 1


if __name__ == "__main__":
    sys.exit(main())
