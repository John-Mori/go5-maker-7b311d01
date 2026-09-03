"""起動文の人格欄が DEPT_CONF(正本)から引かれていることの検査。

型= docs/departments/kaizen-analyst/型_起動文人格欄の正本一元化_2026-09-03.md(改善提案部門)。
§4 の回帰ガード(must-fail)3本をそのまま実装している:
  1. 改善提案部門の起動文に**トトリが含まれ**、アメス(名簿外)が**含まれない**こと。
  2. 全 dept の人格欄が `DEPT_CONF['<dept>']['personas']` と**集合一致**すること(1室でも食い違えばfail)。
  3. DEPT_CONF に人格を1名足した擬似入力で、起動文の人格欄に**即反映**されること
     (=2箇所を書かずに済むことの担保)。

★must-fail(C-053)= 検査が本当に落ちることを、**動く別実装へ差し戻して**確かめる。
  ここでは「一元化前の実装」=ハードコードの控えを返す roster() を差し込み、3本が全部落ちるのを見る。
  落ちなければ検査が緑を出しているだけで何も見ていない。

使い方: python scripts/_daemons/test_boot_prompt_roster.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dept_boot_prompt as bp     # noqa: E402

FAILS = []
OKS = [0]


def check(cond, label):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(label)
    return bool(cond)


# ★正本の名簿が空の部屋(=DEPT_CONF側の穴)。ここは控えへ倒れる仕様なので集合一致の対象外にする。
#   ただし**一覧を検査が持つ**=穴が見えたまま残る。塞ぐのは人事(DEPT_CONF.personas の内容)。
def empty_roster_depts(conf_all):
    return sorted(d for d in bp.DEPTS
                  if not ((conf_all.get(d) or {}).get("personas") or ()))


def guard1(conf_all):
    """1. 改善提案部門の起動文にトトリが居て、アメス(名簿外)が居ない。"""
    text = bp.build("kaizen-analyst")
    names = [p["persona"] for p in (conf_all.get("kaizen-analyst") or {}).get("personas") or ()]
    check("トトリ" in names, "前提: 正本の改善提案部門の名簿にトトリが居ない")
    field, speaker, from_src = bp.roster("kaizen-analyst")
    check("トトリ" in field, "guard1: 人格欄にトトリが無い")
    check("アメス" not in field, "guard1: 人格欄に名簿外のアメスが居る")
    check("トトリ" in text, "guard1: 起動文本文にトトリが無い")
    check("アメス" not in text, "guard1: 起動文本文に名簿外のアメスが居る")
    check(from_src, "guard1: 正本からでなく控えから組んでいる")


def guard2(conf_all):
    """2. 全 dept の人格欄が DEPT_CONF の名簿と集合一致(1室でも食い違えばfail)。"""
    holes = empty_roster_depts(conf_all)
    for dept in sorted(set(bp.DEPTS) | set(conf_all)):
        conf = conf_all.get(dept) or {}
        names = [p["persona"] for p in conf.get("personas") or ()]
        if not names:
            continue                      # 穴(下で別途報告する)
        field, speaker, from_src = bp.roster(dept)
        check(from_src, f"guard2[{dept}]: 正本から引けていない")
        # 人格欄に**名簿の全員が居る**こと
        for n in names:
            check(n in field, f"guard2[{dept}]: 人格欄に {n} が無い")
        # 人格欄に**名簿外の名前が居ない**こと(区切りで割って頭の名前だけ見る)
        listed = [chunk.split("(")[0] for chunk in field.split("/")]
        listed = [x for x in listed if x]
        for x in listed:
            check(x in names, f"guard2[{dept}]: 人格欄に名簿外の {x} が居る")
        check(len(listed) == len(names), f"guard2[{dept}]: 人格の数が名簿と違う")
        # 既定の発言キャラは必ず名簿の中の人
        check(speaker in names, f"guard2[{dept}]: 既定発言キャラ {speaker} が名簿に居ない")
    return holes


def guard3():
    """3. 擬似 DEPT_CONF に1名足したら、人格欄に即反映される。"""
    fake = {"aegis-gl": {"persona": "ケヴィン・デブライネ", "personas": (
        {"persona": "ケヴィン・デブライネ", "role": "GL(部門長)", "aliases": ()},
        {"persona": "アメス", "role": "補佐", "aliases": ()},
    )}}
    real = bp._on_disk_rosters
    try:
        bp._on_disk_rosters = lambda: fake
        before, _s, ok = bp.roster("aegis-gl")
        check(ok and "アメス" in before and "十王星南" not in before,
              "guard3: 擬似入力の前提が崩れている")
        fake["aegis-gl"]["personas"] += ({"persona": "十王星南", "role": "選定眼", "aliases": ()},)
        after, _s2, _ok2 = bp.roster("aegis-gl")
        check("十王星南" in after, "guard3: 名簿へ足した人格が人格欄へ反映されない(2箇所書きが残っている)")
        check("十王星南(選定眼)" in after, "guard3: 役割が反映されない")
    finally:
        bp._on_disk_rosters = real


def failopen():
    """★fail-open(§3): 正本が読めない時は控えへ倒れ、人格欄を空にしない。最悪の事故は沈黙。"""
    real = bp._on_disk_rosters
    try:
        bp._on_disk_rosters = lambda: {}
        field, speaker, from_src = bp.roster("hq")
        check(not from_src, "fail-open: 正本ゼロなのに正本から引けたことになっている")
        check(field.strip() != "", "fail-open: 人格欄が空になった")
        check(speaker.strip() != "", "fail-open: 既定発言キャラが空になった")
        text = bp.build("hq")
        check("控え" in text, "fail-open: 控えを使っている旨が起動文に出ていない")
    finally:
        bp._on_disk_rosters = real


def guard4(conf_all):
    """★人格欄の括弧が対応していること(2026-09-03 実測の再発防止・イージス研究室)。

    役割文を「先頭の一句」に詰める時に `。` が括弧の**中**にあると、開いたまま切れる。
    実測2室(イージス研究室・LLM教育部門)が `アメス(補佐(この部屋の元の常駐` の形で出ていた。
    起動文は毎便セッションの目に入る面で、どこまでが役割かを読み違えさせる。
    """
    for dept in sorted(conf_all):
        field, _speaker, from_src = bp.roster(dept)
        if not from_src:
            continue
        for op, cl in (("(", ")"), ("（", "）")):
            check(field.count(op) == field.count(cl),
                  f"guard4 {dept}: 人格欄の括弧が閉じていない= {field}")


def run():
    conf_all = bp._on_disk_rosters()
    check(len(conf_all) >= 20, f"前提: 正本を読めていない(部屋数={len(conf_all)})")
    guard1(conf_all)
    holes = guard2(conf_all)
    guard3()
    guard4(conf_all)
    failopen()
    return holes


def must_fail():
    """★C-053: **動く別実装(一元化前=ハードコードの控え)**へ差し戻して、3本が本当に落ちるのを見る。

    「検査を書いた」だけでは何も担保しない。落ちるべき時に落ちない検査は緑を売っているだけだ。
    """
    real = bp.roster

    def legacy(dept):                     # 一元化前の実装そのもの
        if dept not in bp.DEPTS:          # 一元化前は DEPTS に無い部屋を出せなかった(21室 vs 25室超)
            return "", "", False
        room, personas, boot, speaker = bp.DEPTS[dept]
        return personas, speaker, True

    try:
        bp.roster = legacy
        conf_all = bp._on_disk_rosters()
        del FAILS[:]
        OKS[0] = 0
        guard1(conf_all)
        g1 = len(FAILS)
        guard2(conf_all)
        g2 = len(FAILS) - g1
        guard3()
        g3 = len(FAILS) - g1 - g2
    finally:
        bp.roster = real

    # guard4 は「役割文の詰め方」を見る検査なので、差し戻す先も**その詰め方の旧実装**にする
    # (素朴な `。` 切り= 2026-09-03 まで実際に動いていた版)。控えへ差し戻すと from_src=False で
    # guard4 は全室を素通りし、落ちないのが当たり前になる=何も担保しない。
    real_fs = bp._first_sentence
    try:
        bp._first_sentence = lambda role: role.split("。")[0]
        del FAILS[:]
        guard4(bp._on_disk_rosters())
        g4 = len(FAILS)
    finally:
        bp._first_sentence = real_fs
    print(f"must-fail(一元化前の実装へ差し戻し): guard1={g1}件 guard2={g2}件 guard3={g3}件 "
          f"guard4={g4}件(素朴な「。」切りへ差し戻し) が落ちた")
    bad = [n for n, c in (("guard1", g1), ("guard2", g2), ("guard3", g3), ("guard4", g4)) if c == 0]
    if bad:
        print("  ★" + "/".join(bad) + " が落ちなかった=この検査は何も見ていない")
        return 1
    return 0


def main():
    if "--must-fail" in sys.argv:
        return must_fail()
    holes = run()
    print(f"検査: PASS={OKS[0]} FAIL={len(FAILS)}")
    for f in FAILS:
        print("  FAIL " + f)
    if holes:
        print("\n★正本(DEPT_CONF)に名簿が無く控えへ倒れている部屋="
              + "/".join(holes))
        print("  = 一元化では消えない穴。塞ぐのは人事(personas の内容)。起動文には控え表示が出る。")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
