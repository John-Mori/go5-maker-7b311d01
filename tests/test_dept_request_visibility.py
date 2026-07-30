#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GOLDEN test — C-023 部門間「実依頼」の可視化(dispatch.py の純粋部分)。

Discord送信・queue・本番には一切触れない。純粋関数だけを固定する。
実行: python tests/test_dept_request_visibility.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts", "llm"))
import dispatch  # noqa: E402

fails = []


def check(name, got, want):
    if got == want:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name}\n    got : {got!r}\n    want: {want!r}")
        fails.append(name)


# ── is_work_request: --work の有無=表/裏の分岐 ──────────────────────
check("work_none_is_hidden", dispatch.is_work_request(""), False)
check("work_blank_is_hidden", dispatch.is_work_request("   "), False)
check("work_newline_only_is_hidden", dispatch.is_work_request("\n \t"), False)
check("work_present_is_visible", dispatch.is_work_request("エラー引き渡し"), True)
check("work_none_arg_is_hidden", dispatch.is_work_request(None), False)

# ── build_work_header: Chamiが「誰が何を」を一目で見る行 ────────────
check("header_basic",
      dispatch.build_work_header("シャビ・アロンソ(研究室HQ)", "改修αのエラーを調べて"),
      "【実依頼 / from シャビ・アロンソ】改修αのエラーを調べて")
check("header_strips_paren_role",
      dispatch.build_work_header("product-scout(商品選定)", "この作品の販売数を確認"),
      "【実依頼 / from product-scout】この作品の販売数を確認")
check("header_flattens_newlines",
      dispatch.build_work_header("hq", "1行目\n2行目"),
      "【実依頼 / from hq】1行目 2行目")
check("header_empty_sender",
      dispatch.build_work_header("", "調査"),
      "【実依頼 / from 不明】調査")

# ── build_work_post: 見出し + 本体 ───────────────────────────────
check("post_header_then_body",
      dispatch.build_work_post("hq", "調査して", "詳細はこちら。"),
      "【実依頼 / from hq】調査して\n\n詳細はこちら。")

# ── pick_msg_id: 実Discord id 優先・取れなければ合成idへフォールバック ─
SYN = "DISPATCH-system-engineer-1700000000000"
check("pick_real_id_when_digit", dispatch.pick_msg_id(SYN, "1531002003004005006"),
      "1531002003004005006")
check("pick_synthetic_when_post_failed", dispatch.pick_msg_id(SYN, ""), SYN)
check("pick_synthetic_when_none", dispatch.pick_msg_id(SYN, None), SYN)
check("pick_synthetic_when_nondigit", dispatch.pick_msg_id(SYN, "not-an-id"), SYN)


# ── AST が壊れていないことも兼ねて import できた時点で成功 ──────────
if __name__ == "__main__":
    print(f"\n{'FAIL' if fails else 'PASS'} — {len(fails)} 件の失敗" if fails
          else "\nALL PASS")
    sys.exit(1 if fails else 0)
