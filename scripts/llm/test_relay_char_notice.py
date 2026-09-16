# -*- coding: utf-8 -*-
"""characterfile更新通知が複数人格の部屋のセッションを1人格へ固定しないことの回帰検査。

台帳= DEF-manga-shorts-845a033c51(enjoh恒久・発注元 manga-shorts/三笘薫)
引き金= Chami msg 1548031056404414485(2026-09-11)
  「Fableの依頼になると口調アメス固定になる設定でもあんの?」
  ames.md の編集 → session_relay の更新通知が manga-shorts(6人格)へ
  「今すぐ読み直して、**その声で書け**」を注入 → 通常タスクまでアメス口調に固定された。

★C-053(must-fail): ソースの文字列一致だけの保険にしない= **実際に文面を生成して**
  検査する。さらに `--mutate` で「直しを外した版(=常に単数の文面)」を同じ検査に掛け、
  **赤くなること**まで確かめる(赤くならない検査は何も守っていない)。

使い方=
  python scripts/llm/test_relay_char_notice.py
  python scripts/llm/test_relay_char_notice.py --mutate
"""
import argparse
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import dept_daemon as dd          # noqa: E402
import session_relay as sr        # noqa: E402

KINDS = ("extra", "solo", "resend")
NAMES = [r"D:\SougouStartFolder\00_AI-HQ\departments\hr\characters\ames.md"]

# ★固定の引き金になった言い回し。複数人格の部屋では**これが出てはいけない**。
PIN = "その声で書け"
# ★複数人格の部屋では**これが出なければいけない**(黙って省くだけでは、直前に読ませた
#   1枚へ引きずられる= C-026の相方混線と同じ形だから、名指しで打ち消す)。
FREE = "固定するな"

# ★旧版(.bak_20260912_multipersona_charnotice)の単数向け文面。
#   単数人格の部屋は**1文字も変えない**という約束を機械で押さえる。
OLD_SOLO = {
    "extra": (
        "\n=== ★人格ファイル(characterfile)も更新された"
        "(以後はファイルの中身が正) ===\n"
        "★記憶の中の口調ではなく、下のファイルを今すぐ読み直して、その声で書け。\n"
        + "".join("- %s\n" % p for p in NAMES)
    ),
    "solo": (
        "=== ★この部屋の人格ファイル(characterfile)が更新された"
        "(以後はファイルの中身が正) ===\n"
        "★セッション起動後に台帳が編集されている。**記憶の中の口調ではなく、"
        "下のファイルを今すぐ読み直して**、その声で書け。\n"
        + "".join("- %s\n" % p for p in NAMES)
        + "★これは運用の変更ではない(起動文は前のままで正)。"
        "読み直すのはこのファイルだけでよい。\n"
        "=== ここまで ===\n\n"
    ),
    "resend": (
        "=== ★この部屋の人格ファイル(characterfile)が更新された"
        "(以後はファイルの中身が正) ===\n"
        "★セッション起動後に台帳が編集されている。**記憶の中の口調ではなく、"
        "下に挙げたcharacterfileを今すぐ読み直して**、その声で書け。\n"
    ),
}


def _mutant(conf, names=None, kind="solo"):
    """直しを外した版= 部屋の人格数を見ずに常に単数の文面を返す(事故当時の挙動)。"""
    return sr._char_update_note({"personas": []}, names, kind=kind)


class R(object):
    def __init__(self):
        self.ok = 0
        self.ng = []

    def check(self, cond, label):
        if cond:
            self.ok += 1
        else:
            self.ng.append(label)


def run(note):
    r = R()
    multi = [(k, v) for k, v in dd.DEPT_CONF.items()
             if len(v.get("personas") or ()) > 1]
    single = [(k, v) for k, v in dd.DEPT_CONF.items()
              if len(v.get("personas") or ()) <= 1]
    r.check(len(multi) >= 2, "複数人格の部屋が実物の名簿から引けない(検査の前提が壊れている)")
    r.check(len(single) >= 1, "単数/無しの部屋が実物の名簿から引けない(回帰の比較対象が無い)")

    # ① 複数人格の部屋= 固定の文言が出ない・選び直しの許可が出る(実物の全室で)
    for dept, conf in multi:
        for kind in KINDS:
            t = note(conf, NAMES, kind=kind)
            r.check(PIN not in t, "[%s/%s] 複数人格の部屋なのに「%s」が出た" % (dept, kind, PIN))
            r.check(FREE in t, "[%s/%s] 複数人格の部屋なのに「%s」が無い" % (dept, kind, FREE))
            r.check("読み直" in t, "[%s/%s] 読み直しの指示そのものが消えた" % (dept, kind))

    # ② 単数の部屋= 旧版と1文字も変わらない(回帰なし)
    for dept, conf in single:
        for kind in KINDS:
            t = note(conf, NAMES, kind=kind)
            r.check(t == OLD_SOLO[kind],
                    "[%s/%s] 単数の部屋の文面が旧版と違う" % (dept, kind))

    # ③ manga-shorts(事故の現場)を名指しで押さえる
    ms = dd.DEPT_CONF["manga-shorts"]
    r.check(len(ms.get("personas") or ()) == 6, "manga-shorts の人格数が6でない(名簿が動いた)")
    for kind in KINDS:
        t = note(ms, NAMES, kind=kind)
        r.check(PIN not in t, "[manga-shorts/%s] 事故の現場で「%s」が再発した" % (kind, PIN))
        r.check("前に出ない" in t,
                "[manga-shorts/%s] 待機枠(トラブル時のみ)への言及が無い" % kind)

    # ④ conf が壊れていても落ちない(fail-open= 単数扱い)
    for bad in ({}, {"personas": None}, {"personas": []}):
        t = note(bad, NAMES, kind="solo")
        r.check(t == OLD_SOLO["solo"], "conf が %r の時に単数の文面へ倒れていない" % (bad,))

    # ⑤ ログの印= 実物を後から数えられる(発注元が台帳を閉じる材料)
    r.check(sr._char_note_tag(dd.DEPT_CONF["manga-shorts"]) == "・人格6名=固定しない文面",
            "manga-shorts のログ印が『固定しない文面』にならない")
    for dept, conf in single:
        r.check("単数の文面" in sr._char_note_tag(conf),
                "[%s] 単数の部屋のログ印が単数側にならない" % dept)
    r.check("単数の文面" in sr._char_note_tag(None), "conf が None でログ印が落ちる")

    # ⑥ 呼び出し側の保険= relay() 本体へ literal を書き戻していないこと。
    #   ★これは①〜④の**実行検査に足す保険**であって、これ単独では守れない。
    src = io.open(os.path.join(HERE, "session_relay.py"), encoding="utf-8").read()
    body = src.split("def _char_update_note(", 1)[1]
    body = body.split("\ndef ", 1)[1] if "\ndef " in body else ""
    r.check(PIN not in body,
            "_char_update_note の外(呼び出し側)に「%s」の literal が残っている" % PIN)
    r.check(len(re.findall(r"_char_update_note\(", src)) >= 4,
            "呼び出し側3箇所すべてが _char_update_note を通っていない")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true",
                    help="直しを外した版で赤くなることを確かめる(C-053 must-fail)")
    a = ap.parse_args()
    note = _mutant if a.mutate else sr._char_update_note
    r = run(note)
    for m in r.ng:
        print("FAIL:", m)
    print("%d PASS / %d FAIL" % (r.ok, len(r.ng)))
    if a.mutate:
        # 変異体では①③が総崩れになるはず= 赤が出なければ検査に歯が無い
        ok = len(r.ng) > 0
        print("must-fail:", "OK(変異体は赤くなった)" if ok else "NG(変異体が緑=検査が何も見ていない)")
        return 0 if ok else 1
    return 0 if not r.ng else 1


if __name__ == "__main__":
    sys.exit(main())
