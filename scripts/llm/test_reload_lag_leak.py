#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""名簿の反映ズレ(reload_lag_leak)の検査。

★2026-09-03 改善提案部門トトリの発注(名乗りタグ漏れの恒久策)。イージス研究室が実装。
  発注の受け入れ条件と must-fail を、そのまま検査項目にした。

受け入れ条件
  A. 反映ズレで引けない名乗りが、**その部屋のオンディスク名簿に実在する**なら
     reload_lag_leak として数え、地の文へ残さず**割る**。
  B. 名簿へ足した人格が走行中の常駐に載ったかを、機械が答えられる(反映ゲートの目)。

must-fail(崩れたら実装が誤り。★ここが「入れれば必ず緑」にならないよう、
          落ちる側の実装へ戻して**赤くなることを確かめている**= C-053)
  1. 名簿に無いタグ(`[検証]` `[1]`)を割らない= 文を壊さない。
  2. 他部屋の人格名(オンディスク名簿にも居ない)を割らない= 部屋の外の人を演じさせない。
  3. 救済しても**漏れの回数を消さない**= reload_lag_leak が必ず1行残る。

E-1(モドリッチ便 2026-09-03 の教訓)= 検査は**本番台帳を1バイトも増やさない**。
  監査の書き先を砂場へ向け、finally で必ず戻し、本番の大きさが不変であることを最後に見る。
  「監査が止まっただけで緑」を防ぐため、砂場に行が落ちていることも同時に見る。

使い方: python scripts/llm/test_reload_lag_leak.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import dept_daemon as dd            # noqa: E402
import persona_render as pr         # noqa: E402
import dept_roster_lag as lag       # noqa: E402

PASS, FAIL = [], []
DEPT = "__testroom__"               # ★実在しない部屋名= 本番の名簿に触れない


def ck(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (("  " + detail) if detail else ""))


def mk_resolve(names):
    """走行中の常駐が持っている名簿(=メモリ側)。単純な完全一致で足りる。"""
    def r(nm):
        n = str(nm or "").strip()
        return n if n in names else None
    r.names = tuple(names)
    return r


def set_ondisk(personas):
    """オンディスク名簿を差し込む(mtimeキャッシュの鍵ごと上書き)。"""
    path = os.path.abspath(dd.__file__)
    dd._ONDISK_ROSTER_CACHE["mtime"] = os.path.getmtime(path)
    dd._ONDISK_ROSTER_CACHE["by_dept"] = {
        DEPT: {"personas": tuple({"persona": p, "aliases": ()} for p in personas)}}


def read_audit(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    out.append(json.loads(ln))
    except OSError:
        pass
    return out


def outcomes(path, name):
    return [r for r in read_audit(path) if r.get("outcome") == name]


def main():
    prod = pr.RENDER_AUDIT
    prod_before = os.path.getsize(prod) if os.path.exists(prod) else 0
    sand = tempfile.mkdtemp(prefix="reload_lag_")
    audit = os.path.join(sand, "persona_render_audit.jsonl")
    keep_fix = dd.PERSONA_TAG_RELOAD_LAG_FIX
    keep_cache = dict(dd._ONDISK_ROSTER_CACHE)
    try:
        pr.RENDER_AUDIT = audit

        # --- A. 受け入れ条件: 反映ズレを割る -----------------------------------
        print("[A] 反映ズレ(オンディスクに居る・メモリに居ない)")
        set_ondisk(["アーモンドアイ", "早坂芽衣"])
        res = mk_resolve(["アーモンドアイ"])          # ★常駐はまだ芽衣を載せていない
        text = "[アーモンドアイ] 分析の結論はこうだ。\n[早坂芽衣] コピー案はこちらです。"
        blocks = dd.split_persona_blocks(text, res, dept=DEPT, names=res.names)
        ck("A-1 2ブロックへ割れる", len(blocks) == 2, f"len={len(blocks)}")
        ck("A-2 名義が両方とも正しい",
           [b[0] for b in blocks] == ["アーモンドアイ", "早坂芽衣"],
           str([b[0] for b in blocks]))
        ck("A-3 本文にタグが残らない",
           all("[早坂芽衣]" not in b[1] and "[アーモンドアイ]" not in b[1] for b in blocks))
        lags = outcomes(audit, "reload_lag_leak")
        ck("A-4 reload_lag_leak を1行残す(must-fail 3)", len(lags) == 1, f"n={len(lags)}")
        ck("A-5 記録が救った正式名を指す",
           bool(lags) and lags[0].get("persona") == "早坂芽衣",
           str(lags[0].get("persona") if lags else None))

        # --- must-fail 1: 名簿に無いタグで文を壊さない -------------------------
        print("[B] must-fail 1: 名簿外のタグ([検証]/[1])を割らない")
        n0 = len(read_audit(audit))
        t2 = "[検証] ここは本文だ。\n[1] これも本文。"
        b2 = dd.split_persona_blocks(t2, mk_resolve([]), dept=DEPT, names=())
        ck("B-1 割らない", len(b2) == 1 and b2[0][0] is None, f"len={len(b2)}")
        ck("B-2 本文を1文字も変えない", b2[0][1] == t2)
        ck("B-3 reload_lag_leak を出さない",
           len(outcomes(audit, "reload_lag_leak")) == 1)
        ck("B-4 名簿外の記号タグは数えもしない(台帳を汚さない)",
           len(read_audit(audit)) == n0, f"+{len(read_audit(audit)) - n0}行")

        # --- must-fail 2: 他部屋の人格を割らない -------------------------------
        print("[C] must-fail 2: オンディスク名簿にも居ない人格名は割らない")
        keys = dd._avatar_keys()
        foreign = next((k for k in keys if k not in ("アーモンドアイ", "早坂芽衣")), "")
        ck("C-0 他部屋の人格名を1つ取れた(検査の前提)", bool(foreign), foreign)
        if foreign:
            t3 = f"[アーモンドアイ] 本題だ。\n[{foreign}] と他室が言っていた。"
            b3 = dd.split_persona_blocks(t3, mk_resolve(["アーモンドアイ"]),
                                         dept=DEPT, names=("アーモンドアイ",))
            ck("C-1 割らない(1ブロックのまま)", len(b3) == 1, f"len={len(b3)}")
            ck("C-2 引用は本文に残る(壊さない)", f"[{foreign}]" in b3[0][1])
            ck("C-3 reload_lag_leak を出さない",
               len(outcomes(audit, "reload_lag_leak")) == 1)
            ck("C-4 代わりに tag_absent_leak で**数える**(計器の穴を塞ぐ)",
               len(outcomes(audit, "tag_absent_leak")) == 1,
               f"n={len(outcomes(audit, 'tag_absent_leak'))}")

        # --- D. 出力ゲートE: 逃げた反映ズレを別の名前で数える -------------------
        print("[D] 出力ゲートE: reload_lag_leak と tag_foreign_leak を分ける")
        n_lag = len(outcomes(audit, "reload_lag_leak"))
        n_for = len(outcomes(audit, "tag_foreign_leak"))
        g1 = dd.persona_tag_leak_gate("[早坂芽衣] コピー案です。", mk_resolve(["アーモンドアイ"]),
                                      dept=DEPT, speaker="アーモンドアイ")
        ck("D-1 本文は触らない(直すのは上流1箇所)", g1 == "[早坂芽衣] コピー案です。")
        ck("D-2 オンディスクに居る名前は reload_lag_leak",
           len(outcomes(audit, "reload_lag_leak")) == n_lag + 1)
        if foreign:
            g2 = dd.persona_tag_leak_gate(f"[{foreign}] 他室の引用。",
                                          mk_resolve(["アーモンドアイ"]),
                                          dept=DEPT, speaker="アーモンドアイ")
            ck("D-3 居ない名前は従来どおり tag_foreign_leak",
               len(outcomes(audit, "tag_foreign_leak")) == n_for + 1 and "[" in g2)

        # --- E. must-fail の裏取り: 栓を抜くと A が崩れる(C-053) ---------------
        print("[E] must-fail の裏取り: 救済を切ると元の事故が再現する")
        dd.PERSONA_TAG_RELOAD_LAG_FIX = False
        b4 = dd.split_persona_blocks(text, mk_resolve(["アーモンドアイ"]),
                                     dept=DEPT, names=("アーモンドアイ",))
        ck("E-1 切ると割れない(=これが 09-03 00:57 の事故の形)", len(b4) == 1, f"len={len(b4)}")
        ck("E-2 切ると本文へタグが漏れる", "[早坂芽衣]" in b4[0][1])
        dd.PERSONA_TAG_RELOAD_LAG_FIX = keep_fix

        # --- F. 反映ゲートの目: 控え → 突き合わせ ------------------------------
        print("[F] 反映ゲート: 載せた名簿の控えと、オンディスク名簿の突き合わせ")
        snap = os.path.join(sand, "snap")
        os.makedirs(snap, exist_ok=True)
        keep_dir = dd.ROSTER_SNAP_DIR
        try:
            dd.ROSTER_SNAP_DIR = snap
            p = dd._record_loaded_roster(DEPT, {"personas": ({"persona": "アーモンドアイ"},)})
            ck("F-1 控えを書ける", bool(p) and os.path.exists(p))
            loaded, started, pid = lag.loaded_roster(DEPT, snap_dir=snap)
            ck("F-2 控えを読み戻せる", loaded == ["アーモンドアイ"] and pid == os.getpid(),
               str(loaded))
            v, missing, extra = lag.verdict(["アーモンドアイ", "早坂芽衣"], loaded)
            ck("F-3 載っていない人を★反映待ちとして名指しできる",
               v == lag.LAG and missing == ["早坂芽衣"], f"{v} {missing}")
            v2, _, _ = lag.verdict(["アーモンドアイ"], loaded)
            ck("F-4 一致すれば反映済", v2 == lag.OK, v2)
            v3, _, _ = lag.verdict(["アーモンドアイ"], None)
            ck("F-5 控えが無い時は不明(fail-open・赤で止めない)", v3 == lag.UNKNOWN, v3)
        finally:
            dd.ROSTER_SNAP_DIR = keep_dir

        # --- G. オンディスク名簿の読み取りが本物に効く -------------------------
        print("[G] オンディスク名簿(実ファイル)を ast で読める")
        real = dd._parse_dept_conf_rosters(os.path.abspath(dd.__file__))
        ck("G-1 部屋が10室以上取れる", len(real) >= 10, f"n={len(real)}")
        ag = [p["persona"] for p in (real.get("aegis-gl", {}).get("personas") or ())]
        mem = [str(p.get("persona") or "")
               for p in (dd.DEPT_CONF["aegis-gl"].get("personas") or ())]
        ck("G-2 走行中のメモリと同じ結果になる(同じ版なら一致)", ag == mem, f"{ag} vs {mem}")

        # --- E-1(モドリッチ便の教訓): 本番台帳を汚していない -------------------
        print("[H] 検査が本番台帳を汚さない")
        ck("H-1 砂場に監査行が落ちている(監査が止まっただけの緑を防ぐ)",
           len(read_audit(audit)) >= 5, f"n={len(read_audit(audit))}")
    finally:
        pr.RENDER_AUDIT = prod
        dd.PERSONA_TAG_RELOAD_LAG_FIX = keep_fix
        dd._ONDISK_ROSTER_CACHE.clear()
        dd._ONDISK_ROSTER_CACHE.update(keep_cache)

    prod_after = os.path.getsize(prod) if os.path.exists(prod) else 0
    ck("H-2 本番台帳が1バイトも増えていない", prod_before == prod_after,
       f"{prod_before} -> {prod_after}")

    print(f"\n{len(PASS)} PASS / {len(FAIL)} FAIL")
    for f in FAIL:
        print("  FAIL:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
