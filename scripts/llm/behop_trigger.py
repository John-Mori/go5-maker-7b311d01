#!/usr/bin/env python3
"""べホップ(強Gemini)の名指し検知(gemini部屋専用の発火条件・純粋関数・副作用なし)。

背景:
  gemini部屋(dept=="gemini")はホイミン(scripts/llm/gemini_responder.py・弱Gemini/私用キー)が
  通常応答を担う。べホップ(scripts/behop/behop.py・強Gemini/事業用キー・専用bot)は
  「名指しされた時だけ」割り込む(縄張り規約=判断・コード・数字・データ編集は渡さない)。
  検知ロジックをgemini_responder.pyから切り出すことで、Discord接続なしにテストできる。

発火条件:
  - 本文に「べホップ」「ベホップ」「behop」(大小文字・全角@有無を問わない部分一致)のいずれかを含む。
  - 将来 local/discord_behop_bot_id.txt にべホップ本人のDiscordユーザーIDが置かれたら、
    実メンション <@ID>/<@!ID> も拾う(現状ファイル未設置=このチェックは素通しで無害)。
  - 分割表記(「べ ホップ」等)は誤爆防止のため意図的にヒットさせない。

テスト: python scripts/llm/behop_trigger.py --selftest
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
BEHOP_ID_FILE = os.path.join(LOCAL, "discord_behop_bot_id.txt")

_TEXT_TOKENS = ("べホップ", "ベホップ", "behop")


def _mention_tokens():
    toks = list(_TEXT_TOKENS)
    try:
        bid = open(BEHOP_ID_FILE, encoding="utf-8").read().strip()
        if bid:
            toks += [f"<@{bid}>", f"<@!{bid}>"]
    except OSError:
        pass
    return toks


def is_behop_mentioned(content):
    """本文にべホップへの名指しが含まれるか(大小文字を無視した部分一致)。"""
    if not content:
        return False
    low = content.lower()
    return any(t.lower() in low for t in _mention_tokens())


def _selftest():
    cases = [
        ("べホップ、これ要約して", True),
        ("＠べホップ 頼む", True),
        ("Behopさん教えて", True),
        ("BEHOP tell me", True),
        ("この画像をbehopに読ませて", True),
        ("ホイミン、これ何?", False),
        ("", False),
        ("べ ホップ", False),  # 分割表記はヒットしない(意図的=誤爆防止)
    ]
    ok = True
    for text, want in cases:
        got = is_behop_mentioned(text)
        mark = "PASS" if got == want else "FAIL"
        ok = ok and (got == want)
        print(f"  {mark}: {text!r} -> {got} (want {want})")
    print("== selftest", "PASS" if ok else "FAIL", "==")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
