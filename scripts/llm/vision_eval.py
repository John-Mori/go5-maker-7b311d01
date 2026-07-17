#!/usr/bin/env python3
"""ローカルVLMのミニeval基盤 (T-3 / 改善設計書_ローカルLLM画像認識強化_2026-07-17 §4.1)。

役割:
  画像の正解セット(local/llm/vision_eval/cases.jsonl)に対しローカルVLMを回し、
  出力に正解語(must_contain)がどれだけ含まれるかで採点する。モデル間AB比較ができる。
  「qwenの画像認識の成長を週次で数字にする」ための土台(V4評価ループの下敷き)。

  ask_vision.describe_images() と image_prep.prepare_image() をそのまま使う(再実装しない)。
  本ファイルは「採点・集計・AB比較・CLI」だけを担当する。

採点方式(決定論的・LLM審判なし):
  - kind=ocr / kind=caption とも同じ規則: VLM出力(draft)に must_contain の各語が
    部分文字列として含まれるかで含有率(recall)を出す。
  - must_not_contain の語が1つでも出たら「誤り扱い」= そのケースの score を 0 にする
    (簡易ペナルティ。recall自体は含有率として別に記録する)。
  - 全体スコア = 成功ケースの score の平均(0-1)。完全一致ケース数 = 全must_contain含有
    かつ違反なしのケース数。応答時間(秒)は成功ケースの中央値。

使い方:
  python scripts/llm/vision_eval.py
  python scripts/llm/vision_eval.py --model gemma3:4b
  python scripts/llm/vision_eval.py --ab gemma3:4b,qwen3.5:9b
  python scripts/llm/vision_eval.py --out local/llm/vision_eval/results/2026-07-17.json

堅牢性: 画像が無い/Ollamaが落ちている/モデルが未pullでもクラッシュしない。
  該当ケースは error として記録し続行、最後に「N件エラー」を表示。全ケースがエラーなら終了コード1。
"""
import io
import json
import os
import statistics
import sys
import unicodedata
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import ask_vision  # noqa: E402  既存の describe_images をそのまま使う

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

CASES_FILE = os.path.join(ROOT, "local", "llm", "vision_eval", "cases.jsonl")
RESULTS_DIR = os.path.join(ROOT, "local", "llm", "vision_eval", "results")


def load_cases(path):
    """cases.jsonl を読む。壊れた行は警告してスキップ(全滅させない)。"""
    cases = []
    if not os.path.exists(path):
        print(f"NG: データセットが見つかりません: {path}")
        return cases
    with io.open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(json.loads(line))
            except Exception:
                print(f"WARN: cases.jsonl {i}行目のJSON解析に失敗・スキップ")
    return cases


def resolve_image(path):
    """リポジトリ相対パスをROOT基準の絶対パスへ。URLはそのまま。"""
    if not path:
        return path
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(ROOT, path))


def _norm(s):
    """突合用の正規化: NFKC(全角→半角)+空白除去+小文字化。

    VLMは「%OFF」を「% OFF」や「％ＯＦＦ」と書き出すことがある。これはモデルの読み取り
    誤りではなく表記の癖なので、減点すると「モデルの実力」ではなく「空白の入れ方」を
    測ってしまう(実測: gemma3:4bのc001がこの理由だけで0.667になった)。
    NFKCは ％→% ￥→¥ Ｏ→O １→1 　→空白 をまとめて畳む(手書きの置換表では
    全角英字を取りこぼす=このテストで実際に踏んだ)。
    ※日本語の読み取り誤り(「今宵の」→「分前」)は正規化しても一致しない=実力の差は残る。
    """
    return "".join(unicodedata.normalize("NFKC", s or "").split()).lower()


def score_case(draft, must_contain, must_not_contain):
    """draft(VLM出力)を正解語と突合してスコア化する(表記ゆれは_normで吸収)。"""
    draft = _norm(draft)
    must_contain = must_contain or []
    must_not_contain = must_not_contain or []
    total = len(must_contain)
    matched = [t for t in must_contain if _norm(t) in draft]
    missing = [t for t in must_contain if _norm(t) not in draft]
    recall = (len(matched) / total) if total else 1.0
    # ★禁止語も必ず_normを通す(draftは正規化済み=生のtと比べると小文字化・全角で
    #   すり抜ける。V3の「電車内で見られて困らないか」判定でNG語に使う予定の経路なので
    #   ここのすり抜けは安全側の欠陥になる)
    violated = [t for t in must_not_contain if _norm(t) in draft]
    score = 0.0 if violated else recall
    exact = (recall == 1.0) and not violated
    return {
        "matched": matched, "missing": missing, "recall": round(recall, 3),
        "violated_terms": violated, "score": round(score, 3), "exact_match": exact,
    }


def _empty_score(must_contain):
    return {"matched": [], "missing": list(must_contain or []), "recall": None,
            "violated_terms": [], "score": None, "exact_match": False}


def run_one(case, model):
    """1ケース×1モデルを実行。例外を投げない(原因名だけ返す)。"""
    cid = case.get("id", "?")
    kind = case.get("kind", "ocr")
    raw_image = case.get("image", "")
    must_contain = case.get("must_contain") or []
    must_not_contain = case.get("must_not_contain") or []
    prompt = case.get("prompt") or ask_vision.DEFAULT_PROMPT
    image = resolve_image(raw_image)

    base = {"id": cid, "kind": kind, "image": raw_image, "model": model}
    # ★must_containが空/キー名typoのケースは「満点」ではなく検証エラー(2026-07-17レビュー指摘)。
    #   recall=len([])/0 を 1.0 と扱う実装だったため、正解語を書き忘れたケースが常に
    #   完全一致に化け、evalの平均スコアを押し上げていた=測定器が嘘をつく側に倒れていた。
    if not [t for t in must_contain if str(t).strip()]:
        return dict(base, status="error", error="no_must_contain", sec=0.0, draft="",
                    **_empty_score(must_contain))
    if not image or (not image.startswith("http") and not os.path.exists(image)):
        return dict(base, status="error", error="image_not_found", sec=0.0, draft="",
                    **_empty_score(must_contain))
    try:
        res = ask_vision.describe_images([image], prompt=prompt, model=model)
    except Exception as e:  # describe_images自体は投げない設計だが念のため二重防御
        return dict(base, status="error", error=type(e).__name__, sec=0.0, draft="",
                    **_empty_score(must_contain))
    if res.get("error"):
        return dict(base, status="error", error=res["error"], sec=res.get("sec", 0.0), draft="",
                    **_empty_score(must_contain))
    draft = res.get("draft", "")
    sc = score_case(draft, must_contain, must_not_contain)
    return dict(base, status="ok", error=None, sec=res.get("sec", 0.0), draft=draft, **sc)


def run_model(cases, model):
    """全ケースを1モデルで実行し、結果一覧とサマリを返す。"""
    print(f"\n--- {model} ---")
    results = []
    for case in cases:
        r = run_one(case, model)
        if r["status"] == "ok":
            mark = "OK" if r["exact_match"] else "△"
            print(f"  [{mark}] {r['id']} ({r['kind']}) 含有率={r['recall']} {r['sec']}秒")
        else:
            print(f"  [NG] {r['id']} ({r['kind']}) error={r['error']}")
        results.append(r)

    ok = [r for r in results if r["status"] == "ok"]
    err = [r for r in results if r["status"] == "error"]
    scores = [r["score"] for r in ok if r["score"] is not None]
    secs = [r["sec"] for r in ok if r.get("sec") is not None]
    summary = {
        "n": len(results),
        "n_ok": len(ok),
        "n_error": len(err),
        "score_avg": round(sum(scores) / len(scores), 3) if scores else None,
        "exact_match": sum(1 for r in ok if r["exact_match"]),
        "median_sec": round(statistics.median(secs), 1) if secs else None,
    }
    return results, summary


def print_summary(model, summary):
    sa = "-" if summary["score_avg"] is None else f"{summary['score_avg']:.2f}"
    ms = "-" if summary["median_sec"] is None else f"{summary['median_sec']}秒"
    print(f"  [{model}] 件数={summary['n']} エラー={summary['n_error']} "
          f"平均スコア={sa} 完全一致={summary['exact_match']}/{summary['n_ok']} 秒(中央値)={ms}")


def print_ab_table(order, summaries):
    print("\n=== AB比較 ===")
    print(f"  {'モデル':<20} {'平均スコア':>8} {'完全一致':>8} {'秒(中央値)':>10} {'エラー':>6}")
    for model in order:
        s = summaries[model]
        sa = "-" if s["score_avg"] is None else f"{s['score_avg']:.2f}"
        ms = "-" if s["median_sec"] is None else str(s["median_sec"])
        print(f"  {model:<20} {sa:>8} {str(s['exact_match']) + '/' + str(s['n_ok']):>8} {ms:>10} {s['n_error']:>6}")


def parse_args(argv):
    opt = {"model": None, "ab": None, "out": None, "cases": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--model" and i + 1 < len(argv):
            opt["model"] = argv[i + 1]; i += 2
        elif a == "--ab" and i + 1 < len(argv):
            opt["ab"] = argv[i + 1]; i += 2
        elif a == "--out" and i + 1 < len(argv):
            opt["out"] = argv[i + 1]; i += 2
        elif a == "--cases" and i + 1 < len(argv):
            opt["cases"] = argv[i + 1]; i += 2
        else:
            i += 1
    return opt


def main():
    opt = parse_args(sys.argv[1:])
    cases_path = opt["cases"] or CASES_FILE
    cases = load_cases(cases_path)
    if not cases:
        print("NG: 実行できるケースが0件です。")
        return 1

    if opt["ab"]:
        models = [m.strip() for m in opt["ab"].split(",") if m.strip()]
    elif opt["model"]:
        models = [opt["model"]]
    else:
        models = [ask_vision.VISION_MODEL]

    print(f"vision_eval: {len(cases)}件のケース × {len(models)}モデル ({', '.join(models)})")

    all_results, summaries = {}, {}
    for model in models:
        results, summary = run_model(cases, model)
        all_results[model] = results
        summaries[model] = summary

    print("\n=== サマリ ===")
    for model in models:
        print_summary(model, summaries[model])

    if len(models) > 1:
        print_ab_table(models, summaries)

    total_n = sum(s["n"] for s in summaries.values())
    total_err = sum(s["n_error"] for s in summaries.values())
    print(f"\n{total_err}件エラー" if total_err else "\nエラーなし")

    out_path = opt["out"]
    if not out_path:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        out_path = os.path.join(RESULTS_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}.json")
    else:
        if not os.path.isabs(out_path):
            out_path = os.path.join(ROOT, out_path)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    payload = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "cases_file": cases_path,
        "models": models,
        "results": {m: {"cases": all_results[m], "summary": summaries[m]} for m in models},
    }
    with io.open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"保存: {out_path}")

    return 1 if total_err and total_err == total_n else 0


if __name__ == "__main__":
    sys.exit(main())
