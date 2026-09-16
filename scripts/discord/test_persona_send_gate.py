#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""persona_send の最後の合流点ゲート english_backstop の回帰テスト。

なぜ要るか(2026-08-23 platform-se・一ノ瀬怜 / 🔥 DEF-platform-se-f827f07985):
  日本語話者の部屋にClaude原文の英語ダンプが出る事故(ORG-23)。dept_daemon の返信は上流の
  english_gate を通るが、**無人代打(claude_responder)・直送は persona_send が唯一の関門**。
  そこに恒久ゲートを置いた=真の合流点。判定は lang_gate 1本を引く(ドリフト防止)。

★test-must-fail: english_backstop が常に body を返す(=保留しない)なら
  「本文まるごと英語は保留」ケースが FAIL する=この検査は空PASSではない。

実行= python scripts/discord/test_persona_send_gate.py (全PASSで exit 0)。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import persona_send as p  # noqa: E402

_PASS = 0
_FAIL = 0


def _check(name, cond):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("PASS", name)
    else:
        _FAIL += 1
        print("FAIL", name)


# 実物(花海咲季の英文ダンプ冒頭)。まるごと英語=保留すべき。
ENGLISH = (
    "I've delivered the measured branch-A verdict to the room. The live-click probe is still "
    "fetching against the throttled worker and will notify me when it lands. I'll apply the fix "
    "once it returns, and won't close anything until I see real data. Standing by for the result."
)
# 普通の日本語返信(英字=固有名詞のみ)。素通しすべき(1ミリも変えない)。
NORMAL_JP = (
    "Chami、直したわ。Drive保存のWorkerは生存で、月詠みの認証→照会で saved:false が返った。"
    "最新版は昨夜0:36(JST)に本番反映済み。確認をお願いします。"
)
# 日本語本文+**末尾の英文**。実物(2026-09-11 system-engineer msg 1547703386911285425)と
# 同じ形。Chami「末尾の英文いらんて」(msg 1549527667571818507・恒久+再発)が4度目。
# 既存ゲートは1枚も鳴らない= detect_english_dump は日本語優勢で None、strip_english_preamble
# は先頭が日本語なので対象外。剥ぐ手 strip_english_paragraphs は在ったが persona_send へ
# 配線されていなかった(呼んでいたのは enjoh.py だけ)。ここがその配線の回帰ガード。
TRAILER_JP = (
    "[オタコン]名簿の件、追えた。roster.json のキーが41室ぶん在って、欠けてるのは"
    "ソリッド・スネークの characterfile だけだ。編纂待ちであって「居ない」じゃない。\n\n"
    "Let me investigate the data source behind the roster and report back once I have the numbers."
)
# 末尾が英語の固有名詞・URL・規約番号で終わる**普通の返信**。1ミリも変えてはいけない。
NORMAL_TAIL_EN = (
    "[一ノ瀬怜]配線しました。入口は scripts/discord/persona_send.py の english_backstop で、"
    "判定は lang_gate 1本に寄せてあります。境界の根拠は C-015。\n\n"
    "参照: https://example.invalid/docs/lang_gate#english_backstop"
)
# 英語前置き+日本語本文。前置きを剥がし、日本語本文だけ送るべき。
PREAMBLE_JP = (
    "Confirmed at line 1408: applyPreview early-returns when prevB is null, and the previewReady "
    "chain yields null exactly when the preview was never captured. Reporting honestly:\n"
    "追えたよ。これ、別々の壊れ方が2つ重なってる——分けて話す。履歴サムネが真っ黒なのは"
    "今日直した capturePreview の穴の下流だ。投稿完了時にプレビュー実体が撮れてないと画像が出ない。"
)


def test_backstop():
    # ① まるごと英語 → 保留(None)。★これが test-must-fail の芯
    _check("① まるごと英語は保留(None)", p.english_backstop(ENGLISH, "アメス", "何でも相談ルーム") is None)

    # ② 通常の日本語返信 → 素通し(不変)
    out = p.english_backstop(NORMAL_JP, "一ノ瀬怜", "platform-se")
    _check("② 通常の日本語は不変", out == NORMAL_JP)

    # ③ 英語前置き+日本語本文 → 前置きを剥がして日本語本文を送る(保留しない)
    out = p.english_backstop(PREAMBLE_JP, "オタコン", "system-engineer")
    _check("③ 前置き剥離で日本語本文が残る", out is not None and out.startswith("追えたよ。"))
    _check("③ 英語前置きが消えている", out is not None and "Confirmed" not in out and "Reporting honestly" not in out)

    # ④ ミラー名義(Chami本人の言葉)は英語でも触らない=素通し(誤保留しない)
    out = p.english_backstop(ENGLISH, "Chami(from Claude)", "何でも相談ルーム")
    _check("④ ミラー名義は英語でも保留しない", out == ENGLISH)

    # ⑤ 空/None は素通し(fail-safe・送信段の空チェックに委ねる)
    _check("⑤ 空文字は保留しない", p.english_backstop("", "アメス", "x") == "")

    # ⑥ 日本語本文+末尾英文 → **末尾だけ剥いで**日本語本文は送る(保留しない)
    #    ★test-must-fail: strip_english_paragraphs を english_backstop へ配線しないと
    #      out == TRAILER_JP のまま=この2本が FAIL する(配線前のコードで赤を実測済み)。
    out = p.english_backstop(TRAILER_JP, "オタコン", "system-engineer")
    _check("⑥ 末尾英文が消えている", out is not None and "Let me investigate" not in out)
    _check("⑥ 日本語本文と名乗りは残る",
           out is not None and out.startswith("[オタコン]") and "編纂待ち" in out)

    # ⑦ 末尾が英語の固有名詞・URL・規約番号の**普通の返信**は1ミリも変えない(誤爆ガード)
    out = p.english_backstop(NORMAL_TAIL_EN, "一ノ瀬怜", "platform-se")
    _check("⑦ 末尾がURL/固有名詞の通常返信は不変", out == NORMAL_TAIL_EN)


if __name__ == "__main__":
    test_backstop()
    print("\n%d PASS / %d FAIL" % (_PASS, _FAIL))
    sys.exit(1 if _FAIL else 0)
