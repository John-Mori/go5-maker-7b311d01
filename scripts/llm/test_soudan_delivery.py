#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配送が『ツール後の地の文メモ』を人格名義で漏らす穴(DEF-soudan-room-0cd2f26ad7)の回帰テスト。

実行: python scripts/llm/test_soudan_delivery.py

★2026-08-23 新設(一ノ瀬怜/platform-se)。理由= `claude -p` の result は**ターンの最後の
  assistantテキスト**しか返さないため、「[名前]本文 → 道具 → 地の文メモ」の並びだと本文が落ち、
  メモがその人格名義でDiscordへ漏れる(実物= 何でも相談ルーム msg 1540814674319376494)。
  _turn_spoken_reply が記録ファイルから同ターンの assistant 本文を全部読み、[名前]で名乗った
  メッセージだけを配る=メモを落とす。この検査はその写像を**実際に実行して**突き合わせる。

★継ぎ目(seam)= 記録ファイル(トランスクリプト)だけ偽物を書く=外部入力。判定と分岐
  (_turn_spoken_reply / _turn_assistant_messages)は本物のまま回す。
"""
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_relay as sr   # noqa: E402

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


def _assistant(text):
    """assistant行(textブロック1つ)を組む。"""
    return {"type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]}}


def _tool_pair():
    """assistantのtool_use + userのtool_result(=道具の往復1回)を返す。"""
    return (
        {"type": "assistant",
         "message": {"content": [{"type": "tool_use", "name": "Write",
                                  "id": "t1", "input": {}}]}},
        {"type": "user",
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                  "content": "ok"}]}},
    )


def _human(text):
    return {"type": "user", "message": {"content": text}}


def _write_transcript(rows):
    """行のリストをjsonlで一時ファイルへ書き、そのパスを返す。"""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _spoken(rows, result_text):
    """記録ファイルを差し込み、result=result_text の時の配送本文を返す(本物のロジック)。"""
    path = _write_transcript(rows)
    orig = sr._transcript_path
    sr._transcript_path = lambda sid, cwd=None: path      # ★記録ファイルだけ偽物(seam)
    try:
        data = {"result": result_text, "session_id": "fake-sid", "is_error": False}
        return sr._turn_spoken_reply(data, "fake-sid")
    finally:
        sr._transcript_path = orig
        try:
            os.remove(path)
        except OSError:
            pass


def main():
    tu, tr = _tool_pair()

    # ---- 1) ★実物の並び: [名前]本文 → 道具 → 地の文メモ ----
    #   result はツール後のメモ(=claude -p の実挙動)。本文が落ちてメモが漏れていた。
    body = "[アメス] 猫アレルギーはね、まず耐性の話からいくわよ。"
    memo = "記録済み。返信本文は上のアメスのブロックがそのままDiscordへ届く。"
    rows = [_human("猫アレルギーについて教えて"),
            _assistant(body), tu, tr, _assistant(memo)]
    got = _spoken(rows, result_text=memo)
    check("実物: 落ちていた[名前]本文が配送本文に戻る", body in got)
    check("実物: 道具後の地の文メモは配送されない", memo not in got)
    check("実物: 配送本文は本文そのもの(メモ混入なし)", got == body)

    # ---- 2) 名乗り無しの素の返信(単独人格)は1文字も変えない=退避 ----
    plain = "うん、それで合ってるよ。"
    rows2 = [_human("これで合ってる?"), _assistant(plain)]
    check("名乗り無しの素の返信はresultのまま(退避)",
          _spoken(rows2, result_text=plain) == plain)

    # ---- 3) 名乗り無しで道具後にメモが出た場合= 機械には見分けられない=result退避 ----
    #   [名前]の信号が無いので落とせない。止血(返信を最終ブロックへ)側の責務=ここでは壊さない。
    rows3 = [_human("q"), _assistant("本文だけどタグ無し"), tu, tr, _assistant("末尾メモ")]
    check("名乗り無し+道具後メモはresult退避(誤って本文を捨てない=fail-open)",
          _spoken(rows3, result_text="末尾メモ") == "末尾メモ")

    # ---- 4) 多人格: [名前]ブロックが複数。道具後のメモだけ落とす ----
    rows4 = [_human("軍議"),
             _assistant("[十王星南] 私はこれを推す。"), tu, tr,
             _assistant("[クラウディア] 私は反対よ。"), tu, tr,
             _assistant("記録した。")]
    got4 = _spoken(rows4, result_text="記録した。")
    check("多人格: 両方の[名前]ブロックが配送される",
          "[十王星南]" in got4 and "[クラウディア]" in got4)
    check("多人格: 道具後の地の文メモは落ちる", "記録した。" not in got4)

    # ---- 5) 止血の並び(道具を先に済ませ返信を最終ブロックへ)= 従来どおり通る ----
    rows5 = [_human("q"), tu, tr, _assistant("[アメス] はい、終わったわよ。")]
    check("止血の並び(道具→[名前]返信)も正しく配送",
          _spoken(rows5, result_text="[アメス] はい、終わったわよ。")
          == "[アメス] はい、終わったわよ。")

    # ---- 6) fail-open: 記録ファイルが読めない → result をそのまま返す ----
    orig = sr._transcript_path
    sr._transcript_path = lambda sid, cwd=None: os.path.join(
        tempfile.gettempdir(), "does-not-exist-xyz.jsonl")
    try:
        data = {"result": "[アメス] 素通し", "session_id": "x", "is_error": False}
        check("記録が読めない時はresult退避(配送を巻き添えにしない)",
              sr._turn_spoken_reply(data, "x") == "[アメス] 素通し")
    finally:
        sr._transcript_path = orig

    ok = all(v for _, v in results)
    print(f"\n== {sum(v for _, v in results)}/{len(results)} PASS ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
