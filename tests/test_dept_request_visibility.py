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

# ── build_work_post: 見出し + 要点(全文ではない) ─────────────────
check("post_header_then_body",
      dispatch.build_work_post("hq", "調査して", "詳細はこちら。"),
      "【実依頼 / from hq】調査して\n\n詳細はこちら。")

# ── front_digest: 表へ流す量を要点までに切る(2026-08-23 Chami指示) ──
LIM = dispatch.FRONT_LIMIT
check("digest_short_passthrough", dispatch.front_digest("短い便。"), "短い便。")
check("digest_strips_edges", dispatch.front_digest("  中身  \n"), "中身")
check("digest_empty", dispatch.front_digest(""), "")
check("digest_none", dispatch.front_digest(None), "")
check("digest_exactly_limit_passthrough", dispatch.front_digest("あ" * LIM), "あ" * LIM)
check("digest_over_limit_is_cut",
      dispatch.front_digest("あ" * (LIM + 1)),
      "あ" * LIM + "…\n(以下 1字は裏の便へ。表は要点まで)")

_LONG = "い" * 5276          # ★実測の最大値(2026-08-23 キュー実測: 表へ出た本文の最大 5276字)
_post = dispatch.build_work_post("シャビ・アロンソ(研究室HQ)", "実物を引いて", _LONG)
check("long_body_not_pasted_whole", _LONG in _post, False)
check("long_post_stays_small", len(_post) < 420, True)
check("long_post_keeps_header",
      _post.startswith("【実依頼 / from シャビ・アロンソ】実物を引いて"), True)
check("long_post_says_where_the_rest_is", "裏の便へ" in _post, True)


# ── ★must-fail: 切り詰めを外したら、上の検査が本当に落ちることを実証する ──
#    (常にPASSする検査は無いのと同じ=SKILL.md。判定は本物のまま、切る関数だけ壊す)
def _broken_digest(body, limit=LIM):
    return (body or "").strip()          # 全文を表へ流す=壊れた版


_orig = dispatch.front_digest
dispatch.front_digest = _broken_digest
_broken_post = dispatch.build_work_post("シャビ・アロンソ(研究室HQ)", "実物を引いて", _LONG)
dispatch.front_digest = _orig
check("mustfail_broken_digest_pastes_whole_body", _LONG in _broken_post, True)
check("mustfail_broken_digest_is_huge", len(_broken_post) < 420, False)
check("mustfail_restored", dispatch.front_digest("あ" * (LIM + 1)).endswith("表は要点まで)"), True)

# ── pick_msg_id: 実Discord id 優先・取れなければ合成idへフォールバック ─
SYN = "DISPATCH-system-engineer-1700000000000"
check("pick_real_id_when_digit", dispatch.pick_msg_id(SYN, "1531002003004005006"),
      "1531002003004005006")
check("pick_synthetic_when_post_failed", dispatch.pick_msg_id(SYN, ""), SYN)
check("pick_synthetic_when_none", dispatch.pick_msg_id(SYN, None), SYN)
check("pick_synthetic_when_nondigit", dispatch.pick_msg_id(SYN, "not-an-id"), SYN)


# ── ★--also-post の抜け道(2026-08-23 C-050・イージス研究室) ─────────
#    --work の表投稿だけ削っても、同じ全文が --also-post で表へ出るなら C-050 はザル。
#    ★文字列一致では見ない= **dispatch() を実際に実行**して、外へ出る手(subprocess・
#      キュー)だけ偽物に差し替える。判定と分岐(is_work / also_post / 順序)は本物のまま。
import tempfile          # noqa: E402
import types             # noqa: E402

_ALSO = "あ" * 1500      # 表に丸ごと出たら困る長さの本文


def _run_dispatch(also_post, work, body):
    """本物の dispatch() を、外へ出る手だけ偽物にして1回通す。戻り=表へ渡された本文の一覧。"""
    posted = []

    class _FakeProc:
        returncode, stdout, stderr = 0, "", ""

    def _fake_run(argv, **kw):
        posted.append(argv[-1])          # persona_send へ渡した最後の引数=表へ出る本文
        return _FakeProc()

    class _FakeQueue:                    # キューは本体=壊さず、書いた中身だけ控える
        # ★2026-08-24 本物の契約に合わせた(イージス研究室)。本物の LeaseQueue.enqueue は
        #   **投入できたら True・msg_id が重複したら False** を返す。ここが None を返していたため、
        #   dispatch が戻り値を読むようになった途端この検査だけが赤くなった。
        #   = 偽物が契約を偽っていた(§3「検証が失敗したら、まず検証の妥当性を疑う」)。
        def __init__(self, *a, **k):
            self.rows = []
            self.ids = set()

        def enqueue(self, payload, msg_id=None, **k):
            if msg_id in self.ids:
                return False             # 本物と同じ冪等(msg_id は UNIQUE)
            self.ids.add(msg_id)
            enq.append(payload)
            return True

        def close(self):
            pass

    enq = []
    orig_run, orig_db, orig_ch = dispatch.subprocess.run, dispatch.QUEUE_DB, dispatch.CHANNELS
    orig_post = dispatch.post_work_to_channel
    tmpdir = tempfile.mkdtemp(prefix="c050_")
    chpath = os.path.join(tmpdir, "ch.json")
    with io.open(chpath, "w", encoding="utf-8") as f:
        f.write('[{"dept":"test-dept","name":"検査用","id":"1"}]')
    try:
        dispatch.subprocess.run = _fake_run
        dispatch.CHANNELS = chpath
        dispatch.QUEUE_DB = os.path.join(tmpdir, "q.db")
        # 表投稿(--work経路)も外へ出る手なので偽物へ。中身は本物の build_work_post を使う。
        dispatch.post_work_to_channel = lambda d, p, b, timeout=90: (posted.append(b), "")[1]
        sys.modules["leasequeue"] = types.SimpleNamespace(LeaseQueue=_FakeQueue)
        dispatch.dispatch("test-dept", "検査(イージス研究室)", body,
                          also_post=also_post, dry_run=False, work=work)
    finally:
        dispatch.subprocess.run, dispatch.QUEUE_DB, dispatch.CHANNELS = orig_run, orig_db, orig_ch
        dispatch.post_work_to_channel = orig_post
        sys.modules.pop("leasequeue", None)
    return posted, enq


_p, _e = _run_dispatch(also_post=True, work="", body=_ALSO)
check("alsopost_posted_once", len(_p), 1)
check("alsopost_body_is_digested", _ALSO in (_p[0] if _p else ""), False)
check("alsopost_body_is_small", len(_p[0]) < 420 if _p else False, True)
check("alsopost_says_where_the_rest_is", "裏の便へ" in (_p[0] if _p else ""), True)
# ★裏(キュー)には**全文が残っている**=表を削っても仕事は失われない。ここが適用条件。
check("alsopost_queue_keeps_full_body", _ALSO in (_e[0] if _e else ""), True)

# --work が有る時は二重投稿しない(表は1回だけ)= 既存の不変条件を壊していない
_p2, _e2 = _run_dispatch(also_post=True, work="実依頼の一行", body=_ALSO)
check("work_and_alsopost_posts_once", len(_p2), 1)
check("work_post_is_digested", _ALSO in (_p2[0] if _p2 else ""), False)
check("work_queue_keeps_full_body", _ALSO in (_e2[0] if _e2 else ""), True)

# ★must-fail: --also-post の front_digest を外したら、上の検査が本当に落ちるか
_orig_digest = dispatch.front_digest
try:
    dispatch.front_digest = lambda b, limit=LIM: (b or "")      # 切らない=壊した版
    _pb, _ = _run_dispatch(also_post=True, work="", body=_ALSO)
    check("mustfail_alsopost_pastes_whole_body", _ALSO in (_pb[0] if _pb else ""), True)
    check("mustfail_alsopost_is_huge", len(_pb[0]) < 420 if _pb else False, False)
finally:
    dispatch.front_digest = _orig_digest
_pr, _ = _run_dispatch(also_post=True, work="", body=_ALSO)
check("mustfail_restored_alsopost", _ALSO in (_pr[0] if _pr else ""), False)


# ── AST が壊れていないことも兼ねて import できた時点で成功 ──────────
if __name__ == "__main__":
    print(f"\n{'FAIL' if fails else 'PASS'} — {len(fails)} 件の失敗" if fails
          else "\nALL PASS")
    sys.exit(1 if fails else 0)
