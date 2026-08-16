#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常駐ライフサイクルの作成時プリフライト(改善提案部門の型 preflight_daemon-lifecycle.md を機構化)。

芯= 「常駐の集合・載せ替えの集合・監視の集合」がずれていないかを作業前/CIで機械が見る。
    ずれ= 登録漏れ(C-042)か 退役し忘れの誤警報(C-044)。

★なぜコードにこれを置くか(=心がけでは止まらない実証):
  deadman_check.py の EXPECTED はコメントで自認している——
    「恒久解: O2でorg_registry.ymlから生成。それまではsupervisorのName列と手動一致」。
  この検査は、その"手動一致"を機械の一致に替えるだけ。既存の一致はホワイトリスト=回帰ゼロ。

第1弾(このファイルが今アサートするもの・実物で弾ける2本):
  A) 常駐7本の一致(C-044): supervise_daemons.ps1 の $daemons(アクティブ=コメント除く)Name集合
     == deadman_check.py の EXPECTED 集合。片方だけ足す/外すと赤。
     (退役はコメント化=両方から同時に消す。片方だけコメント化すると差集合が出て赤)
  B) dept艦隊の名簿整合: daemon_keeper.DEPTS(keeperが起動する部門)⊆ dept_daemon.DEPT_CONF のキー。
     設定の無い部門をkeeperが起動しようとする"空撃ち"を作成時に止める(gunji配線時に手で確認した不変条件)。

第2弾(型に有り・未実装=別コミットで足す。ここでは info として出すだけ):
  - 各常駐が新規に読むファイルが載せ替え閉包(keeper WATCH_FILES / supervise codever)に入っているか(C-042)。
    → import閉包解析が要るので段階実装。
  - DEPT_CONF各エントリの characterfile / personas の characterfile がディスクに実在するか。
    → per-entryブロック解析。gunji配線時は手で確認済み=次弾で機構化。

出力: 一致していれば exit 0(緑)。ずれがあれば該当を並べて exit 1(赤)。
    --json で機械可読。読み取り専用(何も書き換えない・C-006)。
"""
import os
import re
import sys
import json

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))  # 5SecMovieMaker

SUPERVISE = os.path.join(ROOT, "scripts", "_daemons", "supervise_daemons.ps1")
DEADMAN = os.path.join(ROOT, "scripts", "_daemons", "deadman_check.py")
KEEPER = os.path.join(ROOT, "scripts", "_daemons", "daemon_keeper.py")
DEPT_DAEMON = os.path.join(ROOT, "scripts", "llm", "dept_daemon.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def supervised_active():
    """supervise_daemons.ps1 の $daemons からアクティブ(非コメント)な Name を集合で返す。
       行頭(空白除く)が # で始まる行=退役/ロールバック用=除外。"""
    active, retired = set(), set()
    for line in _read(SUPERVISE).splitlines():
        m = re.search(r"@\{\s*Name\s*=\s*'([\w]+)'", line)
        if not m:
            continue
        name = m.group(1)
        if line.lstrip().startswith("#"):
            retired.add(name)
        else:
            active.add(name)
    return active, retired


def deadman_expected():
    """deadman_check.py の EXPECTED = [...] を集合で返す(複数行リテラル対応)。"""
    src = _read(DEADMAN)
    m = re.search(r"EXPECTED\s*=\s*\[(.*?)\]", src, re.DOTALL)
    if not m:
        raise RuntimeError("deadman_check.py に EXPECTED = [...] が見つからない")
    return set(re.findall(r'"([\w]+)"', m.group(1)))


def keeper_depts():
    """daemon_keeper.py の DEPTS = [...](単一行)を集合で返す。"""
    src = _read(KEEPER)
    m = re.search(r"^DEPTS\s*=\s*(\[[^\]]*\])", src, re.MULTILINE)
    if not m:
        raise RuntimeError("daemon_keeper.py に DEPTS = [...] が見つからない(単一行前提)")
    return set(re.findall(r'"([\w-]+)"', m.group(1)))


def dept_conf_keys():
    """dept_daemon.py の DEPT_CONF から部門キーを集合で返す。
       部門エントリは module-level 4スペース字下げで `    "slug": {` と開く。
       `{` の直後に行内コメント(例 `"hq": {  # 研究室HQ…`)が付く実例があるので許す。
       personas等の入れ子(8スペース以深/inline)は 4スペース開始に一致しないので拾わない。"""
    src = _read(DEPT_DAEMON)
    return set(re.findall(r'^    "([\w-]+)":\s*\{\s*(?:#.*)?$', src, re.MULTILINE))


def run():
    problems = []
    info = []

    # --- A) 常駐7本の一致(C-044) ---
    sup, retired = supervised_active()
    exp = deadman_expected()
    only_sup = sorted(sup - exp)
    only_exp = sorted(exp - sup)
    if only_sup:
        problems.append(
            "C-044: supervise で管理しているのに deadman EXPECTED に無い常駐= "
            + ", ".join(only_sup) + " (=死んでも艦隊全滅検知が見ていない盲点)")
    if only_exp:
        problems.append(
            "C-044: deadman EXPECTED に居るのに supervise が管理していない常駐= "
            + ", ".join(only_exp) + " (=退役し忘れ=死んだ常駐を待つ誤警報の芽)")
    info.append("常駐(active)=%d本: %s" % (len(sup), ", ".join(sorted(sup))))
    if retired:
        info.append("退役(コメント化・両方から消えていること)= " + ", ".join(sorted(retired)))

    # --- B) dept艦隊の名簿整合(DEPTS ⊆ DEPT_CONF) ---
    depts = keeper_depts()
    conf = dept_conf_keys()
    missing_conf = sorted(depts - conf)
    if missing_conf:
        problems.append(
            "名簿整合: keeper DEPTS に居るが dept_daemon.DEPT_CONF に設定が無い部門= "
            + ", ".join(missing_conf) + " (=設定なしで起動する空撃ち)")
    info.append("keeper DEPTS=%d部門 / DEPT_CONF=%dキー / 差(設定漏れ)=%d"
                % (len(depts), len(conf), len(missing_conf)))

    return problems, info


def main():
    as_json = "--json" in sys.argv
    try:
        problems, info = run()
    except Exception as e:  # 検査自身がコケたら赤(=見張れていない)
        if as_json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print("PREFLIGHT ERROR: %s" % e)
        return 2

    if as_json:
        print(json.dumps({"ok": not problems, "problems": problems, "info": info},
                         ensure_ascii=False, indent=2))
    else:
        for line in info:
            print("  - " + line)
        if problems:
            print("\n[NG] 常駐ライフサイクルのずれを検出:")
            for p in problems:
                print("  ✗ " + p)
        else:
            print("\n[OK] 常駐の集合・載せ替え・監視は整合(3集合ずれなし)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
