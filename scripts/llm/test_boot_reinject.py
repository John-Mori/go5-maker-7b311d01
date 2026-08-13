# -*- coding: utf-8 -*-
"""起動文の再注入と、直近の便の引き渡しを検査する(2026-08-13 イージス研究室・HQ論点1/3)。

なぜ要るか(実測・HQ msg 1537452059643740302):
  人格ファイル(characterfile)を1枚直すたびに、**生きている全セッションへ起動文(11,448字)を
  丸ごと再注入**していた。人事部門が口調を磨くほど各部屋の文脈が押し出され、圧縮が早く回り、
  「圧縮5回以上 かつ 文脈100,000以上」の定期リフレッシュ交代まで前倒しになる。
  2026-08-13 22:18 のChami「急に文脈読まなくなった」の直接の原因がこれだった
  (llm-edu 22:01:54 / copy-director 22:08:15 に交代=便の10〜17分前)。

この検査が固定する規則=
  ① 人格ファイル**だけ**が変わった便では、起動文の全文を積まない(読み直しの指示だけ)
  ② 起動文そのものが変わった便・圧縮直後の再送では、**今までどおり全文を渡す**(品質保険)
  ③ 変わった1枚を名指しできる(内訳が無い旧セッションは全部を挙げる=fail-open)
  ④ 直近の便の巻物は末尾 RECENT_KEEP 件だけ残り、世代交代の起動文にだけ入る
  ⑤ 直近の便の塊は boot_hash に入らない(=再送のたびに積み直されない)

実行: python scripts/llm/test_boot_reinject.py
"""
import hashlib
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FAILED = []


def check(name, got, want=True):
    ok = (got == want)
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"  (got={got!r} want={want!r})"))
    if not ok:
        FAILED.append(name)


def _conf(tmp, names):
    """人格2枚の部屋の設定を作る(実体のファイルも作る=指紋はstatを見るため)。"""
    paths = []
    for n in names:
        p = os.path.join(tmp, f"{n}.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"# {n}\n")
        paths.append(p)
    return {"persona": names[0],
            "personas": [{"persona": n, "character": p} for n, p in zip(names, paths)]}, paths


def main():
    tmp = tempfile.mkdtemp(prefix="bootreinject_")
    os.environ["GO5_LOCAL_DIR"] = tmp
    sys.path.insert(0, HERE)
    sys.modules.pop("session_relay", None)
    import session_relay as sr

    conf, paths = _conf(tmp, ["デブライネ", "アメス"])

    print("[1] 人格ファイルの内訳(どの1枚が変わったか)")
    parts1 = sr._char_parts(conf)
    check("2枚とも拾えている", len(parts1), 2)
    fp1 = sr._char_fingerprint(conf)
    check("指紋が取れる", bool(fp1))

    with open(paths[1], "a", encoding="utf-8") as f:
        f.write("口調を直した\n")
    os.utime(paths[1], (1_800_000_000, 1_800_000_000))     # mtimeを確実に動かす
    parts2 = sr._char_parts(conf)
    changed = [p for p, v in sorted(parts2.items()) if parts1.get(p) != v]
    check("変わった1枚だけを名指しできる", changed, [paths[1]])
    check("指紋も変わっている", sr._char_fingerprint(conf) != fp1)
    check("内訳が無い旧セッションは全部が『変わった』扱い(fail-open)",
          len([p for p, v in sorted(parts2.items()) if {}.get(p) != v]), 2)

    print("[2] 読み直しの指示は起動文より**桁で**小さい")
    boot = sr._boot_prompt("test-room", conf, 2)
    notice = ("=== ★この部屋の人格ファイル(characterfile)が更新された(以後はファイルの中身が正) ===\n"
              + "".join(f"- {p}\n" for p in changed))
    check(f"起動文={len(boot):,}字 / 読み直しの指示={len(notice):,}字 → 1/5以下",
          len(notice) * 5 < len(boot))

    print("[3] 直近の便の巻物")
    for i in range(sr.RECENT_KEEP + 3):
        sr._recent_append("test-room", {"ts": f"t{i}", "msg_id": str(1000 + i),
                                        "author": "Chami", "content": f"依頼{i}"}, f"返信{i}")
    rows = open(sr._recent_path("test-room"), encoding="utf-8").read().splitlines()
    check(f"末尾 {sr.RECENT_KEEP} 件だけ残る", len(rows), sr.RECENT_KEEP)
    blk = sr._recent_block("test-room")
    check("最新の便が入っている", f"依頼{sr.RECENT_KEEP + 2}" in blk)
    check("前の世代の返信も入っている", f"返信{sr.RECENT_KEEP + 2}" in blk)
    check(f"渡すのは {sr.RECENT_IN_BOOT} 往復だけ(古いものは切る)",
          f"依頼{sr.RECENT_KEEP + 2 - sr.RECENT_IN_BOOT}" not in blk)
    check("長い便は切り詰める(1件 RECENT_CHARS 字まで)",
          len(sr._recent_block("test-room")) < (sr.RECENT_IN_BOOT * sr.RECENT_CHARS * 2 + 2000))

    print("[4] 世代交代の起動文にだけ入る / hashには入らない")
    plain = sr._boot_prompt("test-room", conf, 3)
    withho = sr._boot_prompt("test-room", conf, 3, handoff_path=os.path.join(tmp, "h.md"))
    failed = sr._boot_prompt("test-room", conf, 3, handoff_failed=True)
    check("普段の起動文には入らない", "直前の会話" in plain, False)
    check("交代の起動文には入る", "直前の会話" in withho)
    check("引き継ぎが取れなかった時ほど要るので、そちらにも入る", "直前の会話" in failed)
    h_plain = hashlib.sha256(plain.encode("utf-8")).hexdigest()[:16]
    h_again = hashlib.sha256(sr._boot_prompt("test-room", conf, 3).encode("utf-8")).hexdigest()[:16]
    check("boot_hash の元(handoff無し)は直近の便に影響されない", h_plain, h_again)

    print("[5] 巻物が無い部屋は1文字も変わらない(既存の回帰なし)")
    check("未知の部屋は空", sr._recent_block("no-such-room"), "")
    check("その部屋の交代の起動文は素のまま",
          sr._boot_prompt("no-such-room", conf, 3, handoff_path="x") ==
          sr._boot_prompt("no-such-room", conf, 3, handoff_path="x"))

    print("[6] 台帳を boot_hash から外した(本命)")
    # ★実在の部屋で、切り出しが**無損失**であることを確かめる。
    #   ここが崩れると全部屋の起動文が壊れるので、机上の合成データでは足りない。
    # ★★localを**本物に戻してから import し直す**。tmpのままだと台帳が1件も読めず、
    #   「全部屋で無損失」が**0字と0字の一致**になって空振りする(実際にそれで一度落ちた)。
    os.environ.pop("GO5_LOCAL_DIR", None)
    sys.modules.pop("session_relay", None)
    import session_relay as sr        # noqa: F811  (本物のlocalを見る版へ差し替える)
    try:
        sys.path.insert(0, HERE)
        from dept_daemon import DEPT_CONF
    except Exception as e:                                  # noqa: BLE001
        print(f"  SKIP  DEPT_CONF を読めない({type(e).__name__})")
        DEPT_CONF = {}
    lossless, sized = 0, []
    for d, c in sorted(DEPT_CONF.items()):
        full = sr._boot_prompt(d, c, 5)
        plain = sr._boot_prompt(d, c, 5, ledger=False)
        led = "\n".join(sr._ledger_lines(d))
        if full == (plain + ("\n" + led if led else "")):
            lossless += 1
        if led:
            sized.append((d, len(full), len(led)))
    if DEPT_CONF:
        check(f"実在{len(DEPT_CONF)}部屋すべてで 起動文 = 台帳抜き + 台帳(無損失)",
              lossless, len(DEPT_CONF))
        check("台帳を持つ部屋が実際にある(検査が空振りしていない)", bool(sized))
        for d, fl, ll in sorted(sized, key=lambda x: -x[2])[:3]:
            print(f"        {d}: 起動文{fl:,}字 のうち 台帳{ll:,}字 ({100.0 * ll / fl:.0f}%)")
        check("台帳を抜いた起動文は、台帳が動いても変わらない",
              all(sr._boot_prompt(d, DEPT_CONF[d], 5, ledger=False)
                  == sr._boot_prompt(d, DEPT_CONF[d], 5, ledger=False) for d, _, _ in sized))
    check("台帳0件の部屋は ledger=False でも1文字も変わらない",
          sr._boot_prompt("no-such-room", conf, 5),
          sr._boot_prompt("no-such-room", conf, 5, ledger=False))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILED:
        print(f"FAIL {len(FAILED)}件: " + ", ".join(FAILED))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
