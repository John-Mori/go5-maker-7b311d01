# -*- coding: utf-8 -*-
"""dept_ja() の配線が**本物**であることを、経路を実行で通して確かめる(§3)。

なぜ要るか:
  2026-09-04、改修部門α/β は「5chシステム構築部門α/β」へ改名され、**同日10:22に
  Chami本人が撤回した**(msg 1545242696824655892「よく考えたら一度構築したら保守が
  ほとんどだから…従来通り改修αで」)。半日で往復した= **名前は今後も動く**。
  だから手書きの日本語名を `dept_names.dept_ja()` 呼びへ寄せた。だが「ソースに
  dept_ja と書いてある」ことは検査ではない= リテラルが残っていても grep は通る。
  そこで**台帳(org_registry.yml)を偽物に差し替えて**、外へ出る本文がその値へ
  追従するかを見る。追従したなら、次に名前が動いてもこのファイル群は触らなくてよい。

作法(共通規律§3):
  - 外へ出る手(集計の子プロセス・dispatch・ログ書き込み)だけ偽物にする。
  - 判定と分岐(どの本文を組むか)は本物のまま回す。
  - ★変異(must-fail)は「動く別の実装」へ戻す= dept_ja を**旧名を返す実装**に
    差し替え、同じ検査が**赤になる**ことを見る(赤にならない検査は無意味)。

実行= python scripts/_common/test_dept_ja_wiring.py
"""
import io
import os
import sys
import types
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "kaizen"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "_daemons"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "maintenance"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "analysis"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import dept_names  # noqa: E402

SWAP_JA = "ダミー構築部門ZZZ"          # 台帳を差し替えた時に出るべき字(実運用に無い字)
SLUG = "system-engineer"
# ★正解をここに書かない= 名前は動く(実際に半日で往復した)。台帳から**独立に読み直す**。
RETRACTED = "構築部門α"                # 撤回された名前。これが本文へ出たら回帰だ

FAKE_YML = os.path.join(ROOT, "local", "_work", "_test_registry_swap.yml")
MISSING_YML = os.path.join(ROOT, "local", "_work", "_test_registry_absent.yml")

_ok = _ng = 0


def check(cond, label):
    global _ok, _ng
    if cond:
        _ok += 1
        print("  PASS  " + label)
    else:
        _ng += 1
        print("  NG    " + label)
    return bool(cond)


@contextlib.contextmanager
def registry(path):
    """台帳の差し替え。★キャッシュも落とす(mtime都度読みの初期状態へ戻す)。"""
    old_path, old_cache = dept_names.REGISTRY, dict(dept_names._cache)
    dept_names.REGISTRY = path
    dept_names._cache["mtime"] = None
    dept_names._cache["ja"] = {}
    try:
        yield
    finally:
        dept_names.REGISTRY = old_path
        dept_names._cache.update(old_cache)


# ---------------------------------------------------------------- 経路(本物)
def path_kaizen_analysis():
    """改善提案部門への毎朝の集計本文(見出し+注記3行)。"""
    import daily_repair_analysis as m
    return m.render_md(1757000000.0, 24.0, [], [], [], 2, 1)


def path_cf_usage():
    """Cloudflare 使用量の上限超過アラート。"""
    import cf_usage_report as m
    return m.build_line("2026-09-03", [("go5-sync", 150000)])


def path_teian_job():
    """毎朝7時の提案チェーンの便(ok=復旧 / fail=非0終了)。"""
    import run_daily_teian_job as m
    return (m.build_body("ok", 0, "tail", "2026-09-04", 3)
            + "\n" + m.build_body("fail", 9, "tail", "2026-09-04", 3))


def path_kaizen_job():
    """毎朝8:10の起動器= 集計が失敗した時の「失敗そのものを届ける」本文。"""
    import run_kaizen_daily_repair as m
    fake = types.SimpleNamespace(returncode=1, stdout="", stderr="boom")
    old_run, old_log, old_argv = m.run, m.log, sys.argv
    m.run = lambda cmd: fake                 # 外へ出る手だけ偽物(子プロセスを起こさない)
    m.log = lambda msg: None                 # 本番ログを汚さない
    sys.argv = ["run_kaizen_daily_repair.py", "--dry-run"]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = m.main()                    # ★判定と分岐は本物
    finally:
        m.run, m.log, sys.argv = old_run, old_log, old_argv
    assert rc == 0, "dry-run は 0 で終わるはず(rc=%s)" % rc
    return buf.getvalue()


def path_gas_freeze():
    """GAS凍結監視の週次リマインド本文(凍結中・新規検知)。"""
    import gas_freeze_watch as m
    got = {}
    fake_out = types.SimpleNamespace(
        returncode=0, stdout="上流スナップが 2026-08-18 で停止しています", stderr="")
    old = (m.subprocess, m._ring, m._log, m._load_state, m.DRY)
    m.subprocess = types.SimpleNamespace(run=lambda *a, **k: fake_out,
                                         TimeoutExpired=old[0].TimeoutExpired)
    m._ring = lambda body: (got.update(body=body), True)[1]   # 外へ出す口だけ偽物
    m._log = lambda msg: None
    m._load_state = lambda: {}
    m.DRY = True                                              # 状態ファイルを書かない
    try:
        rc = m.main()                                         # ★凍結判定は本物
    finally:
        m.subprocess, m._ring, m._log, m._load_state, m.DRY = old
    assert rc == 0, "凍結検知は 0 で終わるはず(rc=%s)" % rc
    return got.get("body", "")


PATHS = [
    ("改善提案部門への24h集計 (kaizen/daily_repair_analysis.py)", path_kaizen_analysis),
    ("Cloudflare上限超過アラート (maintenance/cf_usage_report.py)", path_cf_usage),
    ("提案チェーン日次便 (_daemons/run_daily_teian_job.py)", path_teian_job),
    ("8:10起動器の失敗通知 (_daemons/run_kaizen_daily_repair.py)", path_kaizen_job),
    ("GAS凍結の週次リマインド (analysis/gas_freeze_watch.py)", path_gas_freeze),
]

MODULES = ["daily_repair_analysis", "cf_usage_report",
           "run_daily_teian_job", "run_kaizen_daily_repair", "gas_freeze_watch"]


def dept_ja_from_yaml_text():
    """★台帳を yaml ではなく生テキストで読む別実装。dept_names の読み方が壊れても
    こちらは壊れない= 「台帳の一致」ではなく実物と突き合わせるため(共通規律§1)。"""
    with io.open(dept_names.REGISTRY, encoding="utf-8") as f:
        lines = f.read().split("\n")
    for i, ln in enumerate(lines):
        if ln.strip() == SLUG + ":":
            for nx in lines[i + 1:i + 4]:
                if "display_ja:" in nx:
                    return nx.split("display_ja:", 1)[1].split("#")[0].strip()
    raise AssertionError("台帳に %s の display_ja が無い" % SLUG)


def write_fake_registry():
    os.makedirs(os.path.dirname(FAKE_YML), exist_ok=True)
    with io.open(FAKE_YML, "w", encoding="utf-8") as f:
        f.write("depts:\n"
                "  system-engineer:\n"
                "    display_ja: %s\n"
                "  system-engineer-b:\n"
                "    display_ja: ダミー構築部門YYY\n" % SWAP_JA)


def main():
    write_fake_registry()
    if os.path.exists(MISSING_YML):
        os.remove(MISSING_YML)

    real = dept_ja_from_yaml_text()          # ★別実装で読んだ値(1本に頼らない)
    print("=== 0. 台帳そのもの ===")
    check(dept_names.dept_ja(SLUG) == real,
          "台帳の生テキストから読んだ値と一致する(実測= %s)" % real)
    with registry(FAKE_YML):
        check(dept_names.dept_ja(SLUG) == SWAP_JA, "差し替えた台帳の値を返す")
    with registry(MISSING_YML):
        check(dept_names.dept_ja(SLUG) == SLUG,
              "★fail-safe= 台帳が読めなければスラッグをそのまま返す(例外を出さない)")

    print("\n=== 1. 台帳を差し替えたら、外へ出る本文が追従するか(本命) ===")
    for label, fn in PATHS:
        with registry(FAKE_YML):
            body = fn()
        ok = SWAP_JA in body and real not in body
        check(ok, "%s → 差し替えた名前で出る" % label)
        if not ok:
            print("      ---- 実物 ----\n      " + body.replace("\n", "\n      ")[:600])

    print("\n=== 2. 台帳が読めない時も、本文そのものは出るか(沈黙を作らない) ===")
    for label, fn in PATHS:
        with registry(MISSING_YML):
            body = fn()
        check(len(body.strip()) > 20 and SLUG in body,
              "%s → スラッグへ落ちるが本文は出る" % label)

    print("\n=== 3. 素の台帳では今の正式名で出る(撤回された名前は出ない) ===")
    for label, fn in PATHS:
        body = fn()
        check(real in body and RETRACTED not in body,
              "%s → '%s'。撤回名は出ない" % (label, real))

    print("\n=== 4. ★must-fail= dept_ja を旧名固定の実装へ戻すと、検査1が赤になるか ===")
    #   C-053= 壊した側は「動く別の実装」。行を消して文法を壊すのは偽の緑。
    hardcoded = lambda slug, with_slug=False: "改修部門α"   # noqa: E731 旧実装の再現
    for name in MODULES:
        mod = sys.modules[name]
        old = mod.dept_ja
        mod.dept_ja = hardcoded
        try:
            # モジュールを1本だけ壊した状態で全経路を回し、どこかが赤になることを見る
            broke = False
            for label, fn in PATHS:
                with registry(FAKE_YML):
                    try:
                        b = fn()
                    except Exception:           # noqa: BLE001
                        broke = True
                        continue
                if SWAP_JA not in b or "改修部門α" in b:
                    broke = True
            check(broke, "%s の dept_ja を旧名固定にすると検査1が落ちる" % name)
        finally:
            mod.dept_ja = old

    print("\n=== 5. 変異を戻した後、検査1が再び緑か(偽の赤で終わっていない) ===")
    for label, fn in PATHS:
        with registry(FAKE_YML):
            body = fn()
        check(SWAP_JA in body, "%s → 復旧確認" % label)

    try:
        os.remove(FAKE_YML)
    except OSError:
        pass
    print("\n%d/%d PASS" % (_ok, _ok + _ng))
    return 1 if _ng else 0


if __name__ == "__main__":
    sys.exit(main())
