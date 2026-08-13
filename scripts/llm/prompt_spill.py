"""長すぎるpromptを**コマンドラインに載せずファイルへ逃がす**(★止血・2026-08-13 研究室HQ)。

## なぜ在るか(実測した事故)
2026-08-13 08:08〜08:29、`DISPATCH-system-engineer-1786575652694`(絵文字監視の毎朝8時巡回=
Chamiが前日に付けた🔥/再発スタンプのdigest)が6回とも
`配送処理の例外(FileNotFoundError)` で失敗し、queue(`local/queue/inbox.db`)で **status='dead'**
になって完全に落ちた。

真因は**受け口の欠落ではない**。`FileNotFoundError: [WinError 206] ファイル名または拡張子が
長すぎます。`= **Windowsのコマンドライン長の上限**(CreateProcessの32,767字)超過だ。
`session_relay._run_claude()` は prompt を **argvの位置引数**として渡すので、
prompt が3万字を超えると起動そのものが失敗する。Pythonはこれを FileNotFoundError で表に出す
ため、「ファイルが無い」に見えていた。

実測(研究室HQ・2026-08-13):
- 落ちた便の prompt = **36,298字**(圧縮直後の再送で `boot 11,448` + `envelope(規律全文) 24,744`)
- 同じ便を通常経路(envelopeのみ)で組むと 24,744字 = **通る**。だから前後の便は成功していた。
- 空argvでの実測の壁= 32,500字は通り、32,700字で WinError 206(exeのパス長を含むため可変)。

## 何をするか
`guard(prompt, tag)` が上限を超えた prompt を `local/_work/prompt_spill_*.txt` へ**全文**書き出し、
「そのファイルを読め」という短い prompt に差し替える。**落とさない(fail-open)**のが目的で、
理想形(stdin渡し等)ではない。**恒久対策はプラットフォームSE/イージス研究室の担当。**

★これは止血だ。呼び出し側の挙動は上限以下では**1文字も変わらない**。
★書き出しに失敗したら**元のpromptをそのまま返す**(止血が本体を巻き添えにしない)。

## 適用範囲(★2026-08-13 15:30 時点)
- `dept_daemon.generate()` … 対話セッションを持たない部屋の応答生成。**まだ positional argv**。
- `persona_render.py` … 報告digestをキャラの声へ言い換える所。**まだ positional argv**。
- ★`session_relay._run_claude()` は**対象外**。同日に一ノ瀬怜(platform-se)が prompt を
  **stdin へ移す恒久対策**(commit 3f5ac58)を入れ、長さの上限そのものが消えたため、
  こちらの止血は外した(同じ穴を2つの機構で塞ぐと片方だけ直して食い違う)。
  → 上の2箇所も stdin へ移せばこのモジュールは不要になる。**恒久はプラットフォームSEの持ち場。**
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
SPILL_DIR = os.path.join(LOCAL, "_work")
SPILL_LOG = os.path.join(LOCAL, "llm", "prompt_spill.jsonl")

# ★実測の壁は約32,500〜32,700字(argvの固定分=exeパス・フラグを含む)。
#   固定分は実測で240字程度だが、モデル名やallowedToolsが増えると伸びる。
#   28,000で切る= 4,000字以上の余裕。ここを超える便は元々ほぼ無い(通常便の実測=24,744字)。
LIMIT = 28000

# ★依頼2(2026-08-13 一ノ瀬怜/WinError206 恒久対策)= 壁に達する手前で気づく。
#   「余裕(=WALL-len)が閾値を割ったら記録」。spill(LIMIT超過=データをファイルへ逃がす)より
#   手前の WARN 域を残しておくと、deadman_check が状態遷移で1回だけ鳴らせる=壊れる前に気づく。
#   ★通常便(実測24,744字)は WARN に達しない= 1行も書かない(ノイズにしない)。
WALL = 32700               # argv固定分込みの実測の壁(これを超えると WinError 206)
WARN_MARGIN = 6000         # 余裕がこれを割る= len > 26,700 で WARN(spill の LIMIT=28,000 より手前)


def _log(rec):
    try:
        os.makedirs(os.path.dirname(SPILL_LOG), exist_ok=True)
        with open(SPILL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass                                  # 記録の失敗で配送を巻き添えにしない


def guard(prompt, tag="relay"):
    """(prompt, spill_path) を返す。上限以下なら (prompt, None) で**何もしない**。

    ★上限以下でも「壁に近い便」(余裕 < WARN_MARGIN)は level="warn" で記録する=依頼2。
      挙動(返り値)は旧版と1文字も変わらない。記録の失敗は配送を巻き添えにしない(fail-open)。
    """
    text = prompt or ""
    n = len(text)
    if n <= LIMIT:
        if (WALL - n) < WARN_MARGIN:
            _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "level": "warn", "tag": str(tag),
                  "chars": n, "margin": WALL - n, "spilled": False})
        return prompt, None
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(tag))[:40]
    path = os.path.join(SPILL_DIR, f"prompt_spill_{safe}_{ts}.txt")
    try:
        os.makedirs(SPILL_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        # ★書けなかった= 止血できない。**元のpromptをそのまま返す**(挙動を旧版と同じにする)。
        _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "level": "spill", "tag": str(tag),
              "chars": len(text), "margin": WALL - len(text), "spilled": False,
              "error": f"{type(e).__name__}: {e}"})
        return prompt, None
    _log({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "level": "spill", "tag": str(tag),
          "chars": len(text), "margin": WALL - len(text), "spilled": True, "path": path})
    head = (
        "=== ★この便は長すぎてコマンドラインに載らない"
        f"(Windowsの上限32,767字・実測{len(text):,}字)。全文をファイルへ書き出した ===\n"
        "★最初に必ず次のファイルを Read しろ。その中身が**この便の全文**"
        "(起動文・共通規律・封筒・依頼の本文)だ:\n"
        f"{path}\n"
        "★読まずに答えるな。読んだら、そのファイルに書かれた指示どおりに動け"
        "(このメッセージ自体には指示は入っていない)。\n"
        "★これは配送の止血だ(2026-08-13 研究室HQ)。この注記についてChamiへ報告しなくてよい。\n"
    )
    return head, path
