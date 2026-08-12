#!/usr/bin/env python3
"""毎日朝5時の自己振り返りトリガー — future-room(現在と未来)を起こして「直前に閉じた1日」分を1件出させる配線。

★区切りは朝5時アンカー(Chami指示 2026-08-11 / グラブル・ウマ娘・プリコネのログボ更新に合わせる)。
  24時を過ぎて05:00までにやった作業も、その『前日』の1日に算入する。旧仕様=0時発火。

なぜ要るか(2026-07-30 アメスの証拠つき再依頼 / DISPATCH-aegis-gl-1785336943411 の実体化):
  「Chamiの性格・言動への率直な自己振り返り」は future-room(アメス)の職務。だが**0時に部屋を
  起こす仕掛けが無かった**ため一度も自動生成されていなかった(local/llm/daily_reflection/ に
  手動作成分しか無い=偽受領)。既存の go5_daily_report_0000 は「日報」であって振り返りではない
  (別物)。reflect.py は「方針変更検出バッチ」でこれも別物。→ ここが唯一の欠けていた配線。

責任範囲(platform-se/aegis-gl=基盤・常駐構成・C-015):
  **朝5時に future-room を起こして振り返りを1件出させる、そこまで。**
  生成の中身(率直な他者視点)はアメスの職務なので**書かない**。この便は「今日の分を書いて
  保存して返して」と頼むだけ。future-room は生きたデーモン(session_relay)なので、この便を
  キューから消費し、永続セッションが振り返りを生成→ファイル保存→返信(=現在と未来へ自動投稿)する。

なぜ「配って終わり」で消えないか:
  便は local/queue/inbox.db(LeaseQueue)に載る=**future-room が処理するまで残る**。朝5時に部屋が
  取り込み中でも便は消えず、空いた時に処理される。これが「トリガーが無い(=何も起きない)」
  状態との決定的な差。トリガー自体は Windows タスクで定刻に確実に発火する。

冪等:
  当日分 local/llm/daily_reflection/YYYY-MM-DD.md が既に在れば投函しない(二重投稿を防ぐ)。
  --force で上書き再依頼。

使い方:
  python scripts/llm/daily_reflection_trigger.py --dry-run   # 便の中身を印字するだけ(投函しない)
  python scripts/llm/daily_reflection_trigger.py             # future-room へ実際に投函(朝5時タスクが呼ぶ)
  python scripts/llm/daily_reflection_trigger.py --force     # 当日分が在っても再依頼
"""
import argparse
import datetime as dt
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
REFLECT_DIR = os.path.join(ROOT, "local", "llm", "daily_reflection")
# ★定刻発火の結末を残す台帳(2026-08-12 platform-se・C-038/C-041)。
#   旧仕様は当日分が在ると os.path.exists→黙って return 0=「発火したが何も出さなかった」が
#   どこにも残らず、Chamiが05:00過ぎに自分で気づくまで誰も分からなかった(fail-silentの穴)。
#   ここへ毎発火 posted/skip/fail を残し、deadman_check がこれと実ファイルを見て鳴らす。
STATE_PATH = os.path.join(REFLECT_DIR, "_trigger_state.json")
MIN_VALID_BYTES = 40   # これ未満は中身が無い/スタブ=生成できていないとみなす(存在だけで正としない)

JST = dt.timezone(dt.timedelta(hours=9))
SENDER = "定刻トリガー(朝5時)"
TARGET_DEPT = "future-room"


def valid_reflection(path):
    """その対象日の振り返りが『実際に在る』か。存在だけでなく中身の量で判定する。
    空/スタブ(生成が途中で失敗した残骸)は False=作り直させる(旧仕様の黙ってskipを止める)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return len(f.read().strip()) >= MIN_VALID_BYTES
    except OSError:
        return False


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st):
    try:
        os.makedirs(REFLECT_DIR, exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 台帳が書けなくても本業(投函)は止めない


def record_outcome(outcome, day, extra=None):
    """定刻発火の結末を台帳へ残す=黙って終わらない(①)。outcome= posted|skip|fail。
    正常運用では毎日『新しい対象日』を投函するので skip は本来まれ=連続すると異常の芽。"""
    st = _load_state()
    st["last_fire_at"] = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    st["last_fire_day"] = day
    st["last_outcome"] = outcome
    if outcome == "posted":
        st["last_post_day"] = day
        st["consecutive_skips"] = 0
    else:  # skip / fail はどちらも「発火したのに新しい振り返りを出していない」
        st["consecutive_skips"] = int(st.get("consecutive_skips", 0)) + 1
        st["last_" + outcome + "_day"] = day
    if extra:
        st.update(extra)
    _save_state(st)
    return st


def target_day():
    # 振り返りの「対象日 D」。★ファイル名も冪等判定もこの対象日で持つ(Chami確定 2026-08-11:
    # 振り返っている日で名付ける)。発火は D+1 の 05:00 JST なので、発火時点の暦日の前日が D。
    # 例= 8/11 05:00 に起きたら D=8/10(材料窓 8/10 05:00〜8/11 05:00)、ファイル名 2026-08-10.md。
    return (dt.datetime.now(JST).date() - dt.timedelta(days=1)).strftime("%Y-%m-%d")


def reflection_path(day):
    return os.path.join(REFLECT_DIR, f"{day}.md")


def build_body(day):
    """future-room(アメス)へ渡す依頼本文。中身の作法は部屋の boot_note と前日分に委ねる=
    ここでは「何を・どこへ保存して・どう返すか」の配線だけを指示する(生成はアメスの職務)。"""
    rel = f"local/llm/daily_reflection/{day}.md"
    nxt = (dt.datetime.strptime(day, "%Y-%m-%d").date() + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    return (
        f"【定刻・朝5時の自己振り返り(自動)】\n"
        f"{day}(JST)分=直前に閉じた『5時区切りの1日』の「Chamiの性格・言動への率直な自己振り返り」を1件、書いてください。\n"
        f"- 対象の1日= {day} 05:00 から {nxt} 05:00 まで(JST)。★24時を過ぎて明け方({nxt} 05:00)までにやった作業も、"
        f"この『{day}の1日』に算入する(グラブル/ウマ娘/プリコネのログボ更新=朝5時アンカー)。\n"
        f"- 慰めでなく率直な他者視点で(当たり障りのない返しはこの部屋の失敗)。ぼかさない(C-013)。\n"
        f"- 材料= その区切りの1日にChamiが実際にやった言動(各部屋のログ・ames_shared.jsonl・便)。推測は書かない。\n"
        # ★2026-08-13 aegis-gl(依頼元= future-room/アメス・DEF-future-room-4746096476)。
        #   commit/ログの打刻(=点)を連続稼働・労働時間(=線)へ勝手に繋ぐ読み違いが3回再発した
        #   (7/31・8/01・8/11)。前日教訓を書く運用では止まらなかったので便本文へ恒久で埋める(C-038)。
        f"- ★労働時間・連続稼働・徹夜・休息の有無・過集中・生活リズムなど『打刻の「間」を必要とする断定』は書かない。"
        f"連続を言うなら打刻の間隔が連続を示すことを本文に添える(示せないなら書かない)。"
        f"働き方への評価は本人の申告がある時だけ引用で扱う。\n"
        f"- 書式は前日分に倣う(local/llm/daily_reflection/ の直近ファイル)。\n"
        f"- ★書き上げたら {rel} に保存してから、本文をこの部屋へ返してください"
        f"(あなたの返信がそのまま現在と未来へ投稿されます)。\n"
        f"- ネットへ出さない(local/ の中だけで完結)。"
    )


def main():
    ap = argparse.ArgumentParser(description="0時の自己振り返りトリガー(future-roomを起こす)")
    ap.add_argument("--dry-run", action="store_true", help="投函せず便の中身を印字する")
    ap.add_argument("--force", action="store_true", help="当日分が既に在っても再依頼する")
    a = ap.parse_args()

    day = target_day()
    path = reflection_path(day)
    body = build_body(day)

    if not a.dry_run and not a.force:
        if valid_reflection(path):
            # 有効な当日分が本当に在ってのskip=正常。だが「発火して何も出さなかった」事実は台帳へ必ず残す。
            st = record_outcome("skip", day, {"reason": "有効な当日分が既に在る"})
            print(f"[skip] {day} の有効な振り返りが既に在る: {path}(--force で再依頼)"
                  f" / 連続skip={st.get('consecutive_skips')}")
            return 0
        if os.path.exists(path):
            # ファイルは在るが空/スタブ=生成が途中で失敗した残骸。黙ってskipせず作り直す(②)。
            print(f"[regen] {path} は在るが中身が {MIN_VALID_BYTES}字未満(空/スタブ)"
                  f"=生成できていないとみなし作り直す")

    sys.path.insert(0, HERE)
    import dispatch  # noqa: E402  同じ scripts/llm 配下

    ok, mid = dispatch.dispatch(TARGET_DEPT, SENDER, body, dry_run=a.dry_run)
    if a.dry_run:
        print("---- 便本文(dry-run) ----")
        print(body)
        return 0
    if ok:
        record_outcome("posted", day, {"msg": mid})
        print(f"[ok] future-room(現在と未来)へ 朝5時の振り返り依頼を投函 msg={mid} day={day}")
        return 0
    record_outcome("fail", day)
    print(f"[fail] 投函できなかった day={day}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
