#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提案日次チェーン起動器の警報ロジックの回帰テスト。

実行:            python scripts/_daemons/test_teian_daily_job.py
変異(must-fail): python scripts/_daemons/test_teian_daily_job.py --mutate

★2026-09-02 新設。引き金= 初日(09-02 07:00)の実測で C-046 の穴が出たこと:
  チェーンは exit=2(publish の空配信ガード)で止まったが、起動器は「非0=故障」としか
  読まず、**閉じ条件(room_comments を埋める)を持っていない改修部門α**へ3日おきに
  永久に便を打つ形になっていた。当てる先の無い警報は二度目から読まれない(規律§3)。
  そこで止まり方を classify で3つに分け、宛先と間隔を変えた。ここで釘付けにする。

★釘付けにする芯は「黙る側へ倒れないこと」:
  - 合図行が変わったら guard と判定できなくなる → **fail(=毎3日・改修部門α)へ倒れる**
  - 止まり方が変わった日は間隔を無視して必ず1通
  - 直った日は必ず1通(閉じる便)
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_daily_teian_job as J   # noqa: E402

results = []
GUARD_OUT = ("⑤ 配信 publish_candidates.py(空配信ガード)\n"
             "  - ready:dmmmg_1731(④comments)\n"
             "→ 未充填の候補があり配信を止めた(上の一覧)。軍議で room_comments を埋めて再実行。")

# ★実物から取った枠切れの出力(2026-09-02 の実測形)。room_comments.py:230/372 が stderr へ出し、
#   run_daily_teian.py:120 は capture していない=そのまま起動器の capture_output に入る。
QUOTA_OUT = ("④.5 room_comments.py(軍議/咲季の会話・空の候補のみ)\n"
             "  [gemini-flash-latest] 429…次のモデルへ\n"
             "  [gemini-2.5-flash] 404…次のモデルへ\n"
             "  vision 呼び出し失敗: 全モデルで失敗(最後: gemini-flash-lite-latest HTTP 429)\n"
             "room_comments が失敗。④commentsは残るが軍議が欠ける可能性(⑤ガードが空を止める)。\n"
             + GUARD_OUT)

# ★実物から取った 2026-09-06 07:21:45 の形。**ここが 09-02 の判定の穴**:
#   途中の段は 429 で落ちるが、ラダーは最後の段(flash-lite-latest)まで降りて回復する。
#   実際に埋まらなかった候補が落ちた所は 429 ではなく **HTTP 400**(local/llm/gemini_usage.jsonl
#   の 2026-09-06 実測= lite の 429 は 0 件 / 成功 194 件 / 400 が 6 件)。
#   旧判定は「出力のどこかに 429」で quota にしていたので、5日連続でイージス研究室へ誤送した。
GENFAIL_OUT = ("④ comments vision_comments.py\n"
               "  [gemini-flash-latest] HTTP 429→次のモデルへ\n"
               "  [gemini-3.5-flash] HTTP 429→次のモデルへ\n"
               "  [gemini-2.5-flash] HTTP 404→次のモデルへ\n"
               "  [gemini-flash-lite-latest] HTTP 400→次のモデルへ\n"
               "  vision 呼び出し失敗: 全モデルで失敗(最後: gemini-flash-lite-latest HTTP 400)\n"
               + GUARD_OUT)


def check(name, cond):
    results.append((name, bool(cond)))
    print(("  OK  " if cond else "  NG  ") + name)


def st(kind, last_alert):
    return {"last_kind": kind, "last_ok": kind == "ok", "last_alert_date": last_alert}


def main():
    print("=== 提案日次 起動器: 止まり方の切り分けと警報間隔 ===")

    print("\n[1] 止まり方の切り分け")
    check("exit=0 は ok", J.classify(0, "") == "ok")
    check("exit=2 + 合図行 は guard", J.classify(2, GUARD_OUT) == "guard")
    check("exit=1 は fail(合図行があっても exit が違えば guard にしない)",
          J.classify(1, GUARD_OUT) == "fail")
    check("★合図行が変わったら guard と読まない= fail へ倒す(黙る側へ倒さない)",
          J.classify(2, "⑤ 配信 publish_candidates.py で何かあった") == "fail")
    check("タイムアウト(124)は fail", J.classify(124, "★3600秒で打ち切った") == "fail")

    print("\n[1.5] 枠切れ(429)は guard からさらに分ける")
    check("★429の証拠が在る guard は quota", J.classify(2, QUOTA_OUT) == "quota")
    check("429の証拠が無ければ guard のまま(分からない日を軍議素通りにしない)",
          J.classify(2, GUARD_OUT) == "guard")
    check("★429が在っても合図行が無ければ fail(枠切れは停止の理由であって停止そのものではない)",
          J.classify(2, "  [gemini-flash-latest] 429…次のモデルへ") == "fail")
    check("404だけ(名前の陳腐化)は quota にしない= 枠の話ではない",
          J.classify(2, GUARD_OUT + "\n  [gemini-2.5-flash] 404…次のモデルへ") == "guard")
    check("cid や件数の中の素の 429 では quota にしない",
          J.classify(2, GUARD_OUT + "\n  - ready:dmmmg_429(④comments)") == "guard")

    print("\n[1.6] 途中の段の429と、使い切って落ちた行を混ぜない(2026-09-06 実測)")
    check("★最後の段が 400 で落ちたら genfail= 枠の話ではなく生成器の故障",
          J.classify(2, GENFAIL_OUT) == "genfail")
    check("★途中の段の 429 だけで quota にしない(5日連続の誤送の芯)",
          J.classify(2, GENFAIL_OUT) != "quota")
    check("最後の段が 429 なら今までどおり quota(枠の判定は殺さない)",
          J.classify(2, QUOTA_OUT) == "quota")
    check("使い切った行が無ければ genfail にしない= guard のまま",
          J.classify(2, GUARD_OUT) != "genfail")
    check("最後の段が 503 でも genfail(429以外は全部 生成器側)",
          J.classify(2, GUARD_OUT + "\n  vision 呼び出し失敗: 全モデルで失敗(最後: "
                        "gemini-flash-lite-latest HTTP 503)") == "genfail")
    check("使い切った行が2本あり片方が429でも、429が在れば quota を優先(枠は塞がっている)",
          J.classify(2, GENFAIL_OUT + "\n  room_comments 失敗: 全モデルで失敗(最後: "
                        "gemini-flash-lite-latest HTTP 429)") == "quota")

    print("\n[2] 宛先= 閉じ条件の鍵を持つ部屋")
    check("guard の宛先は軍議(room_comments を埋められる側)",
          J.alert_dept("guard") == "gunji")
    check("fail の宛先は改修部門α(チェーン本体の持ち主)",
          J.alert_dept("fail") == "system-engineer")
    check("★quota の宛先は軍議ではない= 枠は軍議には開けられない(2026-09-02 三笘の実測)",
          J.alert_dept("quota") != "gunji")
    check("quota の宛先はイージス研究室(共有キーと計器の持ち場)",
          J.alert_dept("quota") == "aegis-gl")
    check("★genfail の宛先は改修部門α= ラダー(scripts/teian/)を直せる側",
          J.alert_dept("genfail") == "system-engineer")
    check("★genfail をイージス研究室へ送らない= 当室に生成器は直せない(09-02〜09-06 の誤送)",
          J.alert_dept("genfail") != "aegis-gl")

    print("\n[3] 節目は間隔を無視して必ず1通")
    check("成功→guard(初日)は出す",
          J.should_alert(st("ok", "2026-09-02"), "guard", "2026-09-02"))
    check("★guard→fail(設計どおりの停止が本当の故障に変わった)は出す",
          J.should_alert(st("guard", "2026-09-02"), "fail", "2026-09-02"))
    check("fail→guard も出す",
          J.should_alert(st("fail", "2026-09-02"), "guard", "2026-09-02"))
    check("guard→ok(戻った日)は必ず出す= 閉じる便",
          J.should_alert(st("guard", "2026-09-02"), "ok", "2026-09-05"))

    print("\n[4] 同じ止まり方が続く間の間隔")
    check("fail 継続: 翌日は出さない",
          not J.should_alert(st("fail", "2026-09-02"), "fail", "2026-09-03"))
    check("fail 継続: 3日後は出す",
          J.should_alert(st("fail", "2026-09-02"), "fail", "2026-09-05"))
    check("★guard 継続: 3日後は出さない(改修αへの永久便を作らない)",
          not J.should_alert(st("guard", "2026-09-02"), "guard", "2026-09-05"))
    check("guard 継続: 14日後は出す(止まったまま忘れられない)",
          J.should_alert(st("guard", "2026-09-02"), "guard", "2026-09-16"))
    check("成功が続く日は黙る",
          not J.should_alert(st("ok", "2026-09-02"), "ok", "2026-09-30"))
    check("guard→quota(同じ停止でも原因が枠切れに変わった日)は出す",
          J.should_alert(st("guard", "2026-09-02"), "quota", "2026-09-03"))
    check("★quota 継続: 3日後は出す= guard の14日で黙らせない(Chamiの課金判断が要る)",
          J.should_alert(st("quota", "2026-09-02"), "quota", "2026-09-05"))
    check("quota 継続: 翌日は出さない",
          not J.should_alert(st("quota", "2026-09-02"), "quota", "2026-09-03"))
    check("★quota→genfail(原因が枠から故障に変わった日)は出す= 宛先が変わる日を黙らせない",
          J.should_alert(st("quota", "2026-09-06"), "genfail", "2026-09-07"))
    check("genfail 継続: 3日後は出す(故障なので fail と同じ間隔)",
          J.should_alert(st("genfail", "2026-09-02"), "genfail", "2026-09-05"))
    check("genfail 継続: 翌日は出さない",
          not J.should_alert(st("genfail", "2026-09-02"), "genfail", "2026-09-03"))

    print("\n[5] 読めない状態は鳴らす側へ(fail-open)")
    check("last_alert_date が空なら出す",
          J.should_alert(st("guard", ""), "guard", "2026-09-03"))
    check("日付が壊れていても出す",
          J.should_alert(st("guard", "きのう"), "guard", "2026-09-03"))
    check("last_kind が無い旧stateでも落ちない(last_ok から読む)",
          J.should_alert({"last_ok": True}, "guard", "2026-09-02"))

    print("\n[6] 便の本文は閉じ条件を必ず書く")
    for k in ("guard", "quota", "genfail", "fail", "ok"):
        b = J.build_body(k, 2, GUARD_OUT, "2026-09-02", 1)
        check("%s の本文に閉じ方が書いてある" % k,
              ("閉じ条件" in b) or ("閉じる" in b))
    check("guard の本文で「落ちた」と断定しない",
          "設計どおりの停止" in J.build_body("guard", 2, GUARD_OUT, "2026-09-02", 1))
    check("guard の本文に --publish-force 禁止が残っている",
          "--publish-force` は使うな" in J.build_body("guard", 2, GUARD_OUT, "2026-09-02", 1))
    qb = J.build_body("quota", 2, QUOTA_OUT, "2026-09-02", 1)
    check("★quota の本文に実数(20/日/モデル)が書いてある= 「枠が枯れた」で終わらせない",
          "20" in qb and "モデル毎" in qb)
    check("quota の本文に「軍議へは送っていない」理由が書いてある",
          "軍議" in qb)
    check("quota の本文にChamiが選ぶ道が並んでいる(待つ/課金/ローカル)",
          "課金" in qb and "ローカル" in qb)
    gb = J.build_body("genfail", 2, GENFAIL_OUT, "2026-09-06", 5)
    check("★genfail の本文に「枠切れではない」と書いてある= 誤診を繰り返させない",
          "枠切れ(429)ではない" in gb)
    check("★genfail の本文に、使い切った時の最後のエラーが実文で載っている",
          "HTTP 400" in gb)
    check("genfail の本文に直す場所(DEFAULT_MODELS)が書いてある",
          "DEFAULT_MODELS" in gb)
    check("genfail の本文に --publish-force 禁止が残っている",
          "--publish-force` は使うな" in gb)

    bad = sum(1 for _, c in results if not c)
    print("\n%d件中 %d件OK / %d件NG" % (len(results), len(results) - bad, bad))
    return 0 if bad == 0 else 1


# --- must-fail 変異(C-053: 壊れた実装ではなく「もっともらしく動く別実装」) ---

def _mut_code_only():
    """exit だけで guard を決める(合図行を見ない)。
    ★動く。だが**たまたま2で落ちた本物の故障**が14日間の静かな側へ沈む。"""
    J.classify = lambda code, out: "ok" if code == 0 else (
        "guard" if code == J.GUARD_CODE else "fail")


def _mut_same_interval():
    """間隔を止まり方で分けず、全部3日にする(=元の実装)。
    ★動く。だが軍議しか閉じられない停止を3日おきに鳴らし続ける= 元の穴に戻る。"""
    J.should_alert = (lambda state, kind, today, quiet_days=J.QUIET_DAYS,
                      guard_quiet_days=J.GUARD_QUIET_DAYS:
                      _orig_should(state, kind, today, quiet_days, quiet_days))


def _mut_interval_only():
    """間隔だけで決め、止まり方の変化を節目として見ない。
    ★動く。だが guard→fail(本当に壊れた日)が間隔の内側だと黙って通る。"""
    def f(state, kind, today, quiet_days=J.QUIET_DAYS,
          guard_quiet_days=J.GUARD_QUIET_DAYS):
        if kind == "ok":
            return not bool((state or {}).get("last_ok", True))
        return _orig_should(dict(state or {}, last_kind=kind), kind, today,
                            quiet_days, guard_quiet_days)
    J.should_alert = f


def _mut_quota_folded():
    """枠切れを分けず、429 の日も guard のままにする(= 2026-09-02 午前までの実装)。
    ★動く。だが「軍議が room_comments を埋めろ」を、埋める当てが有るのに枠で書けない
      軍議へ14日おきに送り続ける= 閉じられない部屋を叩く(C-046 の再演)。"""
    J.classify = lambda code, out: "ok" if code == 0 else (
        "guard" if (code == J.GUARD_CODE and J.GUARD_MARK in (out or "")) else "fail")


def _mut_quota_to_gunji():
    """枠切れも「配信が止まっている話」だから宛先は軍議のまま、とする。
    ★動く(便は届く)。だが軍議には Gemini の枠も課金も開けられない= 閉じ条件を持たない
      部屋への便になる。宛先は「話題の持ち主」ではなく**鍵を持つ側**で決める。"""
    J.alert_dept = lambda kind: J.GUARD_DEPT if kind in ("guard", "quota") else J.DEPT


def _mut_quota_anywhere():
    """出力の**どこかに** 429 が在れば quota とする(= 2026-09-02〜09-06 の実装)。
    ★動く。だがラダーの**途中の段**の 429 も拾う= 最後の段まで降りて別の理由(400/503)で
      落ちた日まで「枠切れ」と読む。これで5日連続、枠を開けられないイージス研究室へ送った。"""
    J.classify = lambda code, out: "ok" if code == 0 else (
        (("quota" if any(m in (out or "") for m in J.QUOTA_MARKS) else "guard")
         if (code == J.GUARD_CODE and J.GUARD_MARK in (out or "")) else "fail"))


def _mut_genfail_to_aegis():
    """生成器の故障も「Gemini の話」だから計器の持ち場(イージス研究室)へ、とする。
    ★動く(便は届く)。だが当室に scripts/teian/ のラダーは直せない= また閉じられない部屋へ
      の便になる。宛先は「話題の持ち主」ではなく**直せる手を持つ側**で決める。"""
    J.alert_dept = lambda kind: (
        "aegis-gl" if kind in ("quota", "genfail")
        else (J.GUARD_DEPT if kind == "guard" else J.DEPT))


def _mut_dept_owner():
    """宛先を「チェーンの持ち主」で決める(全部 改修部門α)。
    ★動く。だが閉じ条件を持たない部屋へ出す= 当てる先の無い便に戻る。"""
    J.alert_dept = lambda kind: J.DEPT


_orig_should = J.should_alert
_orig_class = J.classify
_orig_dept = J.alert_dept

MUTANTS = (
    ("exit だけで guard を決める", _mut_code_only,
     "★合図行が変わったら guard と読まない= fail へ倒す(黙る側へ倒さない)"),
    ("間隔を分けない(全部3日)", _mut_same_interval,
     "★guard 継続: 3日後は出さない(改修αへの永久便を作らない)"),
    ("止まり方の変化を節目として見ない", _mut_interval_only,
     "★guard→fail(設計どおりの停止が本当の故障に変わった)は出す"),
    ("宛先を持ち主で決める", _mut_dept_owner,
     "guard の宛先は軍議(room_comments を埋められる側)"),
    ("枠切れを guard に畳む(09-02午前までの実装)", _mut_quota_folded,
     "★429の証拠が在る guard は quota"),
    ("枠切れも軍議へ送る", _mut_quota_to_gunji,
     "★quota の宛先は軍議ではない= 枠は軍議には開けられない(2026-09-02 三笘の実測)"),
    ("出力のどこかに429が在れば quota(09-02〜09-06の実装)", _mut_quota_anywhere,
     "★最後の段が 400 で落ちたら genfail= 枠の話ではなく生成器の故障"),
    ("生成器の故障もイージス研究室へ送る", _mut_genfail_to_aegis,
     "★genfail の宛先は改修部門α= ラダー(scripts/teian/)を直せる側"),
)


def mutate():
    bad = 0
    for name, fn, want_red in MUTANTS:
        del results[:]
        fn()
        try:
            print("\n=== %s ===" % name)
            try:
                main()
            except Exception as e:
                print("  (検査が例外で止まった: %s)" % e)
        finally:
            J.should_alert, J.classify, J.alert_dept = (
                _orig_should, _orig_class, _orig_dept)
        red = [n for n, c in results if not c]
        hit = want_red in red
        print("  → 狙った1件が赤か: %s  (赤=%d件)" % ("OK" if hit else "NG", len(red)))
        if not hit:
            bad += 1
    print("\n変異 %d件中 %d件が狙いどおり赤" % (len(MUTANTS), len(MUTANTS) - bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(mutate() if "--mutate" in sys.argv else main())
