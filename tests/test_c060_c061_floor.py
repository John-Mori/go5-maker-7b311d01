#!/usr/bin/env python3
"""C-060(床削り)と C-061(AI便の合流)の検査。

★2026-08-24 イージス研究室。裁定= 研究室HQ commit e330f0e(C-060 / C-061)。
★must-fail(C-053)= 「壊した側」は**行を消すのではなく、動く別の実装**へ差し替えて赤くする。
  ここでは各テーマごとに「もっともらしいが間違った実装」を1本ずつ用意し、
  検査が実際にそれを落とすことを確かめる(常にPASSする検査を足さないため)。

走らせ方= `python tests/test_c060_c061_floor.py`
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))

import session_relay as S          # noqa: E402
import dept_daemon as D            # noqa: E402

FAILS = []


def ok(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- C-060 ① CLAUDE.md を外す引数
def t_context_args(argsf):
    """組織層だけ project の設定源を外し、本体を触る部屋はそのまま。"""
    org = argsf("aegis-gl")
    app = argsf("system-engineer")
    r = []
    r.append(("組織層に --setting-sources が付く", "--setting-sources" in org))
    r.append(("組織層の値は user,local(project を外す)", "user,local" in org))
    r.append(("hooks と deny を保つため --settings で設定ファイルを明示",
              "--settings" in org and org[org.index("--settings") + 1].endswith("settings.json")))
    r.append(("改修α(本体を触る部屋)は1バイトも変えない", app == []))
    return r


def t_context_args_broken(dept):
    """★動く別の実装= 「床が減るなら全部屋から外せばいい」。

    これは C-035(名指し1箇所の指示を全体へ広げるな)違反であり、
    5秒動画メーカー本体を触る部屋から仕様書を奪う=実害が出る。検査はこれを落とすべき。
    """
    return ["--setting-sources", "user,local", "--settings",
            os.path.join(ROOT, ".claude", "settings.json")]


# ---------------------------------------------------------------- C-060 ② 裁定見出しの差分送付
def _env(**kw):
    return S.build_envelope({"content": "x", "author": "Chami", "msg_id": "1"},
                            dept="aegis-gl", **kw)


def t_verdict(shortf):
    heads_txt, table_txt, heads = S.verdict_parts()
    full = _env(verdict_full=True)
    diff = S.build_envelope({"content": "x", "author": "Chami", "msg_id": "1"},
                            dept="aegis-gl", verdict_full=False,
                            verdict_fp="abc", verdict_added=[])
    # 差分の便を、渡された短縮実装で作り直して比べる(must-fail はここを差し替える)
    diff = diff.replace(S._verdict_short("abc", len(heads), []), shortf("abc", len(heads), []))
    r = []
    r.append(("裁定の見出しが61本前後読めている", len(heads) >= 50, f"n={len(heads)}"))
    r.append(("全文の便には見出しの本文が入る", "C-041" in full))
    r.append(("差分の便では見出しの本文が落ちる", "C-041" not in diff))
    r.append(("★発注先の表(C-015)は差分の便にも必ず残る",
              "発注先" in diff and "system-engineer" in diff))
    r.append(("差分の便は全文より小さい", len(diff) < len(full),
              f"{len(full)}→{len(diff)}字"))
    r.append(("指紋を書いて『変更なし』と分かる形にしている", "abc" in diff))
    return r


def t_verdict_short_broken(fp, n, added):
    """★動く別の実装= 「見出しを送らないなら表も要らない」。

    表(C-015 発注先)は2026-07-28に**誤配の実害**があって毎便入れた物で、落としてはいけない。
    この実装は封筒からその節ごと消す=検査はこれを落とすべき。
    """
    return ""


def t_verdict_plan():
    heads_txt, table_txt, heads = S.verdict_parts()
    ids = S._verdict_ids(heads)
    r = []
    full, added = S.verdict_plan({}, heads, table_txt, "", False)
    r.append(("新セッションは全文", full and added == []))
    full, added = S.verdict_plan({"verdict_ids": ids, "verdict_since_full": 1},
                                 heads, table_txt, "sid", False)
    r.append(("変わっていなければ差分(増分ゼロ)", (not full) and added == []))
    full, added = S.verdict_plan({"verdict_ids": ids[:-2], "verdict_since_full": 1},
                                 heads, table_txt, "sid", False)
    r.append(("2本増えたら『増えた分だけ』", (not full) and len(added) == 2,
              str([a[:5] for a in added])))
    full, _ = S.verdict_plan({"verdict_ids": ids + ["C-999"], "verdict_since_full": 1},
                             heads, table_txt, "sid", False)
    r.append(("消えた/書き換わったら全文へ倒す", full))
    full, _ = S.verdict_plan({"verdict_ids": ids, "verdict_since_full": 1},
                             heads, table_txt, "sid", True)
    r.append(("圧縮の直後は全文", full))
    full, _ = S.verdict_plan({"verdict_ids": ids,
                              "verdict_since_full": S.VERDICT_FULL_EVERY},
                             heads, table_txt, "sid", False)
    r.append((f"{S.VERDICT_FULL_EVERY}便に1回は全文", full))
    full, _ = S.verdict_plan({"verdict_ids": ids, "verdict_since_full": 1},
                             heads, "", "sid", False)
    r.append(("表が読めない時は安全側(全文)へ倒す", full))
    return r


# ---------------------------------------------------------------- C-061 AI便の合流
class _FakeQ:
    """claim() だけを持つ最小のキュー(本物の LeaseQueue は触らない)。"""

    def __init__(self, rows):
        self.rows = list(rows)

    def claim(self, dept=None, who=""):
        return self.rows.pop(0) if self.rows else None


def _row(i, audience="ai", author="研究室HQ"):
    return {"id": i, "body": {"msg_id": f"M{i}", "audience": audience,
                              "author": author, "content": f"本文{i}"}}


class _Bot:
    """_take_same_kind / _merge_coalesced だけを借りた最小の実体。"""
    dept = "aegis-gl"
    _take_same_kind = D.Daemon._take_same_kind
    _is_ai_letter = staticmethod(D.Daemon._is_ai_letter)
    _is_from_chami = staticmethod(D.Daemon._is_from_chami)
    _merge_coalesced = staticmethod(D.Daemon._merge_coalesced)


def t_take(takef):
    b = _Bot()
    b._claim_carry = []
    q = _FakeQ([_row(2), _row(3), _row(4, audience="", author="Chami")])
    extra = takef(b, q, is_kind=_Bot._is_ai_letter)
    r = []
    r.append(("AI便が続いていれば掴んで束ねる", len(extra) == 2, f"n={len(extra)}"))
    r.append(("★種類の違う便は捨てず手元へ戻す(次の周で普通に処理される)",
              [c["id"] for c in b._claim_carry] == [4], str(b._claim_carry)))
    # 上限: COALESCE_MAX_ITEMS を超えて掴まない
    b2 = _Bot()
    b2._claim_carry = []
    q2 = _FakeQ([_row(i) for i in range(20)])
    extra2 = takef(b2, q2, is_kind=_Bot._is_ai_letter)
    r.append((f"1回に束ねる上限({D.COALESCE_MAX_ITEMS})を超えない",
              len(extra2) + 1 <= D.COALESCE_MAX_ITEMS, f"n={len(extra2) + 1}"))
    return r


def t_take_broken(self, q, is_kind):
    """★動く別の実装= 「種類が違う便は要らないので捨てる」。

    ack もせず握り潰す=**無言で1件消える**(規律§3「最悪の事故は沈黙」)。検査はこれを落とすべき。
    """
    extra = []
    while len(extra) + 1 < D.COALESCE_MAX_ITEMS:
        c = q.claim(dept=self.dept)
        if c is None:
            break
        nrec = c["body"] if isinstance(c["body"], dict) else {}
        if not is_kind(nrec):
            break                      # ← 手元へ戻さない(消える)
        extra.append((c, nrec))
    return extra


def t_merge(mergef):
    recs = [_row(1)["body"], _row(2)["body"], _row(3)["body"]]
    recs[0]["author"] = "研究室HQ"
    recs[1]["author"] = "改修部門α"
    m = mergef(recs)
    r = []
    r.append(("3本ぶんの本文が1つも欠けていない",
              all(f"本文{i}" in m["content"] for i in (1, 2, 3))))
    r.append(("★差出人が分かる形で並ぶ(誰の話か消えない)",
              "研究室HQ" in m["content"] and "改修部門α" in m["content"]))
    r.append(("束ねた元の msg_id が残る(ack と印のため)",
              m.get("coalesced_from") == ["M1", "M2"], str(m.get("coalesced_from"))))
    r.append(("1本で返せと明示している", "1回で返せ" in m["content"]))
    # Chamiの連投は今までどおり(素の連結・差出人の見出しを足さない)
    ch = [{"msg_id": "a", "author": "Chami", "content": "あ"},
          {"msg_id": "b", "author": "Chami", "content": "い"}]
    m2 = D.Daemon._merge_coalesced(ch)
    r.append(("Chamiの連投の束ね方は1バイトも変えていない", m2["content"] == "あ\nい"))
    return r


def t_merge_broken(recs):
    """★動く別の実装= 「本文を繋ぐだけで十分」(=AI便でも Chami と同じ扱い)。

    差出人が消えるので、受け取った部屋は誰へ返すのか分からなくなる。検査はこれを落とすべき。
    """
    base = dict(recs[-1])
    base["content"] = "\n".join(str(r.get("content") or "") for r in recs)
    base["coalesced_from"] = [str(r.get("msg_id", "")) for r in recs[:-1]]
    return base


def run(title, rows):
    print(title)
    for item in rows:
        ok(item[0], item[1], item[2] if len(item) > 2 else "")


def must_fail(title, rows):
    """壊した実装で赤が出ることを確かめる(赤が1つも出なければ、この検査は無意味)。"""
    bad = [r for r in rows if not r[1]]
    print(f"{title}: 壊した実装で {len(bad)} 件が赤 " + ("(OK)" if bad else "★空PASS!"))
    if not bad:
        FAILS.append(title + "(must-fail が赤くならない)")


if __name__ == "__main__":
    print("=== C-060/C-061 検査 ===")
    run("[C-060①] 組織層から CLAUDE.md を外す引数", t_context_args(S.context_args))
    run("[C-060②] 裁定の見出しの差分送付", t_verdict(S._verdict_short))
    run("[C-060②] 全文/差分の切り替え", t_verdict_plan())
    run("[C-061] 同じ種類の便を掴む", t_take(lambda b, q, is_kind: b._take_same_kind(q, is_kind)))
    run("[C-061] AI便の束ね方", t_merge(D.Daemon._merge_coalesced))
    print("--- must-fail(壊した実装で赤くなるか) ---")
    must_fail("[C-060①] 全部屋から外す実装", t_context_args(t_context_args_broken))
    must_fail("[C-060②] 表まで落とす実装", t_verdict(t_verdict_short_broken))
    must_fail("[C-061] 違う便を捨てる実装", t_take(t_take_broken))
    must_fail("[C-061] 差出人を消す実装", t_merge(t_merge_broken))
    print()
    if FAILS:
        print(f"★FAIL {len(FAILS)}件: " + " / ".join(FAILS))
        sys.exit(1)
    print("ALL PASS")
