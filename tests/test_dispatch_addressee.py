# -*- coding: utf-8 -*-
"""dispatch.py の宛先ズレ警告(2026-08-23 研究室HQ発注)の検査。

★実物で測る= 実際に起きた3件の見出しをそのまま入力にする。
  `"..." in src` は使わない。**本物の org_registry.yml を読ませて**判定を通す。
★must-fail= 「ズレていたら鳴る」だけでなく「**合っていたら黙る**」も見る。
  常に鳴る警告は無視される=そのガードは死んでいる。
★このガードは fail-open= 判定できない時は黙る(通信路を止めない)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts", "llm"))
from dispatch import addressee_warning, display_names   # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("[PASS] %s" % name)
    else:
        FAILS.append(name)
        print("[FAIL] %s %s" % (name, detail))


def main():
    names = display_names()
    check("W-0 org_registry.yml を実際に読めている(主要4部門の日本語名が引ける)",
          all(names.get(k) for k in ("hq", "platform-se", "kaizen-analyst", "aegis-gl")),
          {k: names.get(k) for k in ("hq", "platform-se", "kaizen-analyst", "aegis-gl")})

    # ①実際に起きた事故そのもの(FCC起動器の依頼書)
    w1 = addressee_warning("【研究室HQ → プラットフォームSE】FCCの安全起動器を作ってくれ\n本文",
                           ["aegis-gl"])
    check("W-1 見出しがプラットフォームSEなのに投函先がイージス研究室だけ=鳴る",
          "プラットフォームSE" in w1, w1)

    # ②経由の書き方でも、**最後の矢印の先**が本当の宛先
    w2 = addressee_warning(
        "【研究室HQ → イージス研究室(部門長)経由 → 改善提案部門(トトリ)】裁定した\n本文",
        ["aegis-gl"])
    check("W-2 『→A経由→B』はBが宛先=Bへ出していなければ鳴る",
          "改善提案部門" in w2, w2)

    # ③直すと黙る= 名指しした部門へ実際に出した時
    check("W-3 直すと黙る= 改善提案部門へ投函していれば鳴らない",
          addressee_warning(
              "【イージス研究室(部門長) → 改善提案部門(トトリ)】転送する\n本文",
              ["kaizen-analyst"]) == "",
          addressee_warning("【イージス研究室(部門長) → 改善提案部門(トトリ)】転送する\n本文",
                            ["kaizen-analyst"]))

    # ★差出人を宛先と読み違えない= 左側の「研究室HQ」で鳴ってはいけない
    check("W-4 見出し左の差出人では鳴らない(研究室HQ→人事部門を人事部門へ出した)",
          addressee_warning("【研究室HQ → 人事部門】通達\n本文", ["hr-room"]) == "",
          addressee_warning("【研究室HQ → 人事部門】通達\n本文", ["hr-room"]))

    # ★矢印の無い見出しは対象外(普通の報告文で鳴らせない)
    check("W-5 矢印の無い本文では鳴らない",
          addressee_warning("ハ4の実測結果を返す。プラットフォームSEの話ではない\n本文",
                            ["hr-room"]) == "")

    # ★同報のうち1つでも欠けていれば鳴る / 全部揃えば黙る
    w6 = addressee_warning("【研究室HQ → プラットフォームSE・改善提案部門】\n本文", ["platform-se"])
    check("W-6 複数名指しのうち欠けた方だけを挙げる",
          "改善提案部門" in w6 and "プラットフォームSE" not in w6.split("実際に投函")[0], w6)
    check("W-7 直すと黙る= 名指しした2部門の両方へ出せば鳴らない",
          addressee_warning("【研究室HQ → プラットフォームSE・改善提案部門】\n本文",
                            ["platform-se", "kaizen-analyst"]) == "")

    # ★fail-open= 判定材料が壊れていても黙る(通信路を止めない)
    import dispatch
    orig = dispatch.ORG_REGISTRY
    try:
        dispatch.ORG_REGISTRY = os.path.join(os.path.dirname(__file__), "no_such_registry.yml")
        check("W-8 fail-open= 名簿が読めない時は警告を出さない(送信は止めない)",
              addressee_warning("【研究室HQ → プラットフォームSE】\n本文", ["aegis-gl"]) == "")
    finally:
        dispatch.ORG_REGISTRY = orig

    print("=== 全PASS ===" if not FAILS else "=== FAIL %d件: %s" % (len(FAILS), FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
