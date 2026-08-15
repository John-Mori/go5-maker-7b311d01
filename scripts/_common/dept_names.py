#!/usr/bin/env python3
"""部門スラッグ → Chamiが読む日本語名 への変換。**この1本だけ**(ORG-11)。

なぜ在るか(Chami原文 2026-07-27・報告通知部屋に来た1便目のフィードバック):
  「用語が難しい、結論が見えないかな。たとえば部門は日本語表記にして欲しいな。
    hqは研究室HQでsystems engineerは改修部門 みたいに」
  = 報告に英語スラッグ(hq / system-engineer …)がそのまま漏れていた。
    根本原因は **日本語名を書く場所が台帳にもコードにも無かった** こと。
    だから正本を台帳(org_registry.yml)へ置き、変換はここ1本に集約する。

正本= 00_AI-HQ/org_registry.yml の depts.<slug>.display_ja (C-009: 台帳が正本)。
  台帳に定義が無いスラッグ(router / gemini / llm-growth / meeting-a / meeting-b /
  imagegen)だけ下の EXTRA_JA が持つ。**台帳は汚さない**(部門ではないため)。

★判定を2本持たない(ORG-11)。Chamiが読む報告を出す経路は全部ここを通す。
  同じ部屋が報告Aでは「改修部門」報告Bでは「改修部門α」になるのが一番たちが悪い。
★fail-safe: 台帳が読めない/yamlが無い等どんな失敗でも **スラッグをそのまま返す**。
  変換に失敗しても報告そのものは必ず出ること(落とさない・例外を出さない)。
★都度読み(mtime監視): Chamiが台帳へ1行足した次の報告から効く。
  registry_purpose()(dept_daemon.py)と同じ設計。

使い方:
    sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
    from dept_names import dept_ja
    dept_ja("system-engineer")                  # -> '改修部門α'
    dept_ja("system-engineer", with_slug=True)  # -> '改修部門α(system-engineer)'
    dept_ja("しらない部屋")                      # -> 'しらない部屋' (そのまま)
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# 5SecMovieMaker/scripts/_common → 5SecMovieMaker → SougouStartFolder
_SOUGOU = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
REGISTRY = os.path.join(_SOUGOU, "00_AI-HQ", "org_registry.yml")

# ★台帳(registry.depts)に定義が無いスラッグ。値はHQ決定(2026-07-27)。
#   これらは「部門」ではない(受け皿・別responder管轄・会議室・ユーティリティ)ので
#   depts へ足さない。足すと registry_tool.py の欠落検出が誤爆する。
EXTRA_JA = {
    "router": "通知受付",
    "gemini": "Gemini部屋",
    "llm-growth": "ローカルllm成長進捗",
    "meeting-a": "会議室α",
    "meeting-b": "会議室β",
    "imagegen": "画像生成部屋",
    # ★2026-08-16 横断会議部屋(部門ではない=会議室αβと同格)。台帳には足さない。
    "gunji": "軍議",
    # ★2026-07-27 HQ決定。定例報告(daily_report.py)が部屋ではない名前でも数えるため。
    #   旧 DEPT_DISPLAY が持っていた値を引き継ぐ("main"→司令塔 は旧実装のまま)。
    "main": "司令塔",
    "_main": "司令塔",
    "learning": "学習部門",
}

_cache = {"mtime": None, "ja": {}}


def _registry_ja():
    """台帳から {slug: display_ja} を都度読み。読めなければ直前のキャッシュ(初回は空)。"""
    try:
        m = os.path.getmtime(REGISTRY)
    except OSError:
        return _cache["ja"]
    if m == _cache["mtime"]:
        return _cache["ja"]
    try:
        import yaml
        with open(REGISTRY, encoding="utf-8") as f:
            depts = (yaml.safe_load(f) or {}).get("depts") or {}
        _cache["ja"] = {k: (v or {}).get("display_ja")
                        for k, v in depts.items() if (v or {}).get("display_ja")}
        _cache["mtime"] = m
    except Exception:
        return _cache["ja"]          # yaml不在・破損・権限。報告は止めない
    return _cache["ja"]


def dept_ja(slug, with_slug=False):
    """部門スラッグを日本語名へ。**未知のスラッグはそのまま返す**(捨てない)。

    with_slug=True のときだけ '日本語名(slug)' の形にする。
    ★使い分け: 直す手順にスラッグが要る技術警報(DEPT_CONFを見ろ 等)だけTrue。
      Chamiが読むだけの行はFalse=日本語だけ(情報を増やすのは逆効果=Chami原文)。
    """
    s = (slug or "").strip()
    if not s:
        return ""
    try:
        ja = _registry_ja().get(s) or EXTRA_JA.get(s) or s
    except Exception:
        return s                     # 想定外もここで止める(fail-safe)
    return f"{ja}({s})" if (with_slug and ja != s) else ja
