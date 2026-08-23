# -*- coding: utf-8 -*-
"""毎朝8:00(JST)の起動器= フロントエンドデザイン室を起こして §100「朝のデザイン振り返り」を回させる。

なぜ在るか(2026-08-24・イージス研究室 / 発注= AD研究室(モドリッチ) msg 1541120579136917524):
  Chami原文「毎朝8時にその日の改修からデザインに関する振り返りを行ってよ!成果が出てないからさ」。
  フロント室は手順(design-preferences.md §100)を正本へ入れ済みで、足りないのは**発火**だけ。
  フロント室は基盤を触らない(職責外)ので、配線=こちらの持ち場。

設計の要点:
  ①**手順の全文をここへ抱えない**。便は「§100を回せ・窓はここからここまで」の一言だけ。
    手順が変わる時に直す場所を2か所にしない(正本= design-preferences.md §100 ただ1つ)。
  ②**窓は直近に過ぎた8:00で切る**= 8:00の定時起動なら「前日8:00〜当日8:00」になる。
    `--as-of` で任意の時刻の起動を**そのまま再現**できる(=初発火を初検証にしないため)。
  ③**同じ窓で二度起こさない**(状態= FRONT_STATE)。定時起動と手動の予行が重なっても便は1本。
  ④★**脈は毎回書く**(起こしても・起こさなくても・投函に失敗しても)。
    「起こさなかった日」と「起動器が死んだ日」を区別できないと、静かな死が見えない。
    脈は producers.json へ登録済み= absence_watchdog が age で見張る(C-042の対)。
  ⑤fail-open= 拾えるデザイン改修が0件でも、フロント室は「今日はデザイン改修なし」の1行を残す
    (§100 手順5)。**空でも走った印が出る**のがこの定例の生死判定になる。

登録= scripts/_daemons/register_frontend_design_review.ps1(タスク名 go5_frontend_design_0800)
手で試す= python scripts/_daemons/run_frontend_design_review.py --dry-run
明朝と同じ入力で予行= python scripts/_daemons/run_frontend_design_review.py --as-of 2026-08-24T08:00
検査= python tests/test_frontend_design_review.py
"""
import argparse
import datetime as dt
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")
LOG = os.path.join(ROOT, "local", "_frontend_design_review.log")
BODY = os.path.join(ROOT, "local", "_work", "frontend_design_review_body.txt")
# ★脈(毎回書く)。producers.json の frontend_design_review が age で見張る。
PULSE = os.path.join(ROOT, "local", "_work", "frontend_design_review_pulse.md")
STATE = os.path.join(ROOT, "local", "_work", "frontend_design_review_state.json")

DEPT = "frontend"                 # フロントエンドデザイン室(咲季)
SPEC = "docs/departments/frontend/design-preferences.md"   # §100 の正本
BOUNDARY_HOUR = 8                 # 毎朝8時(JST)で1日を切る


# ---------------------------------------------------------------- 純粋関数

def window_jst(now, hour=BOUNDARY_HOUR):
    """振り返りの窓を返す=(始まり, 終わり)。★純粋関数。

    終わり= **直近に過ぎた hour 時**(8:00に走れば当日8:00 / 8:00前に走れば前日8:00)。
    始まり= その24時間前。= 定時起動では「前日8:00〜当日8:00」になる。
    """
    end = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now < end:
        end -= dt.timedelta(days=1)
    return end - dt.timedelta(days=1), end


def window_key(end):
    """同じ窓で二度起こさないための鍵。窓の終わりだけで決まる(起動時刻には依らない)。"""
    return end.strftime("%Y-%m-%dT%H")


def should_wake(state, key, force=False):
    """この窓でまだ起こしていないか。★純粋関数(状態は dict をそのまま受ける)。"""
    if force:
        return True
    return str((state or {}).get("last_window", "")) != key


def build_body(start, end):
    """フロント室への便。★手順は書かない=正本(§100)を指すだけ。"""
    w = "%s 〜 %s (JST)" % (start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"))
    return (
        "自動(毎朝8時)→ フロントエンドデザイン室(咲季)\n"
        "\n"
        "■ 今日の定例= **朝のデザイン振り返り**を1回回してくれ。手順は正本の §100 を開いて見る\n"
        "  (= %s の「100. 朝のデザイン振り返り」)。ここには手順を写さない=直す場所を2つにしないため。\n"
        "\n"
        "■ 今日の窓= **%s**\n"
        "  この窓の `git log` と `local/llm/change_log.jsonl` から、デザイン関連の改修だけを絞る。\n"
        "\n"
        "■ 出すもの(§100 手順4〜5)\n"
        "  ・design-preferences.md の該当§を更新し、追記ログへ `- (日付) 【朝のデザイン振り返り 第N回】…` を1行。\n"
        "  ・咲季の口調で **5行以内**、その日拾った好みを部屋へ返す。\n"
        "  ・★**拾えるデザイン改修が0件でも「今日はデザイン改修なし」と1行残す**"
        "(空でも走った印= この定例が生きている証拠になる)。\n"
        % (SPEC, w)
    )


# ---------------------------------------------------------------- 外へ出る手

def log(msg):
    line = "%s %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_pulse(state_line):
    """★毎回書く脈。起こした日も起こさなかった日も、ここが更新されるのが「生きている」印。"""
    os.makedirs(os.path.dirname(PULSE), exist_ok=True)
    with io.open(PULSE, "w", encoding="utf-8") as f:
        f.write("# 朝のデザイン振り返り 起動器の脈(毎回上書き)\n\n"
                "最終走行: %s\n%s\n"
                % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), state_line))


def load_state():
    try:
        with io.open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with io.open(STATE, "w", encoding="utf-8") as f:
        f.write(json.dumps(state, ensure_ascii=False, indent=1))


def dispatch_letter(body):
    """便を1本投函する。戻り=(exit code, 出力)。★テストはここだけ偽物へ差し替える。"""
    os.makedirs(os.path.dirname(BODY), exist_ok=True)
    with io.open(BODY, "w", encoding="utf-8") as f:      # ★BOM無し(dispatchはutf-8で読む)
        f.write(body)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"                     # ★タスク実行時のcp932化けを作らない
    r = subprocess.run([sys.executable, DISPATCH, "--dept", DEPT, "--direct",
                        "--from-dept", "aegis-gl",
                        "--audience", "chami",           # 振り返りの中身はChamiが読む=返信を削らせない
                        "--from", "自動(毎朝8時のデザイン振り返り)",
                        "--body-file", BODY],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout or r.stderr or "").strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description="フロントエンドデザイン室に §100 の朝の振り返りを回させる")
    ap.add_argument("--dry-run", action="store_true", help="投函しない(便文を表示して終わる)")
    ap.add_argument("--force", action="store_true", help="同じ窓で起こし済みでも起こす")
    ap.add_argument("--as-of", dest="as_of", default="",
                    help="この時刻に起動したことにする(例 2026-08-24T08:00)。予行用")
    a = ap.parse_args(argv)

    now = dt.datetime.now()
    if a.as_of:
        now = dt.datetime.strptime(a.as_of[:16], "%Y-%m-%dT%H:%M")
    start, end = window_jst(now)
    key = window_key(end)
    state = load_state()

    if not should_wake(state, key, a.force):
        # ★起こさない日も脈は書く(=起動器が生きている印。静かな死と区別する)
        write_pulse("状態: この窓(%s)は起こし済み= 便は出していない" % key)
        log("窓 %s は起こし済み= 二重に起こさない" % key)
        return 0

    body = build_body(start, end)
    if a.dry_run:
        write_pulse("状態: --dry-run(投函していない) / 窓=%s" % key)
        log("--dry-run= 投函しない。便文は以下:")
        print(body)
        return 0

    code, out = dispatch_letter(body)
    if code == 0:
        state["last_window"] = key
        state["last_sent_at"] = dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        save_state(state)
        write_pulse("状態: 起こした / 窓=%s" % key)
        log("フロント室を起こした 窓=%s / %s" % (key, out[:200]))
        return 0
    # ★失敗を黙って飲まない(沈黙が最悪の事故)。状態も進めない=次の起動で必ず再挑戦になる。
    write_pulse("状態: ★投函に失敗(exit=%s) / 窓=%s" % (code, key))
    log("★投函に失敗 exit=%s / %s" % (code, out[:300]))
    return code


if __name__ == "__main__":
    sys.exit(main())
