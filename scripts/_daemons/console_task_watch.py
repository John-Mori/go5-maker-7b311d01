# -*- coding: utf-8 -*-
r"""定刻タスクが黒窓(コンソール窓)を出す形に戻っていないかを**無人で**見張る。

  イージス研究室 / 2026-08-30 / 依頼= 研究室HQ DISPATCH-aegis-gl-1788093688716
  走査範囲の拡張(接頭辞→ポリシー)= 研究室HQ DISPATCH-aegis-gl-1788095116580

なぜ要るか:
  Chami「タイムスケジューラで定期的に出る黒い画面はここのプロジェクトの内容? 表に表示しないで
  欲しい」(msg 1543598413340475462・2026-08-30 21:29)。研究室HQが実測= go5_* 31本のうち
  **19本が python.exe / powershell.exe を直に叩いていた**=コンソールを持つので窓が描かれる。
  `-WindowStyle Hidden` は**窓を作ってから隠す**ので一瞬光る。HQは19本を
  `wscript.exe + run_hidden.vbs` へ変換した。

  ★**それはタスクを直しただけで、穴は塞いでいない。**HQ自身がそう書いて再発防止を回してきた=
  「今回は**人が気づいて人が直した**。同じ穴がまた開く」。この見張りが無人側を持つ。

★**「go5_ の見張り」ではない。「Chamiの画面に黒窓を出さない見張り」だ。**
  走査するタスク名の接頭辞は `console_window_policy.json` の `watch_prefixes` に置く=
  コードに `go5_` を埋めると、名前がそれで始まらないというだけで同じ穴が丸ごと素通りする
  (実測= `chami_style_step1/step1b/step2` の3本が範囲外で console持ちだった)。

穴は3つある(この見張りは3つとも数える):
  live … 登録済みタスクの Execute がコンソールを持つ exe。**これが実物の計器**。
  vbs  … wscript.exe から起動する .vbs が、子を SW_HIDE(Run の第2引数 0)で作っていない。
          「hidden という名前なのに隠していない」は名前では分からない。
  src  … 登録スクリプト(.ps1)が `New-Go5HiddenAction` を通さず `New-ScheduledTaskAction` を
          直に呼んでいる。★**これは検査ではなく保険**(ソースの文字列一致・共通規律§3)。
          ただし**再発の経路そのもの**だ= 実測で8本の登録スクリプトが python/powershell を
          手書きしていたので、どれか1本を再実行すればHQの変換は黙って巻き戻る。

判定の正本は1つ:
  `console_window_policy.json`。**登録の入口(hidden_task.ps1)とこの見張りが同じJSONを読む。**
  リストを2箇所に書くと必ず片方が古くなる。

鳴らし方(★常に鳴る安全網は無視される・共通規律§3):
  ① 違反の**顔ぶれが前回と変わった時だけ**研究室HQへ1便(C-052=宛先は1つ)。
  ② 綺麗な時は何も出さない(沈黙が正常)。
  ③ 意図的な例外は policy の `allow_tasks` / `allow_register_scripts` に**理由つきで**置く
     (例= go5_lora_step3 は Chami が進捗を見る窓かもしれないのでHQが意図的に残した)。

★この見張り自身が窓を出さないこと:
  pythonw.exe から起動される=親にコンソールが無い。そこから powershell.exe を素で
  subprocess すると **Windows が新しいコンソールを割り当てて窓が出る**(見張りが症状を作る)。
  → `CREATE_NO_WINDOW` を必ず付ける。★タスクXMLを直読みする手は使えない=
     `C:\Windows\System32\Tasks` は listdir が拒否される(実測: WinError 5)。

fail-open:
  例外は握って exit 0。**見張りが落ちても他は何も止めない。**ただし黙って落ちない=
  `local/_state/console_task_watch.jsonl` に理由を1行残す。

使い方:
    python scripts/_daemons/console_task_watch.py            # 本番(違反が変われば1便)
    python scripts/_daemons/console_task_watch.py --dry-run  # 出すはずだった本文を画面へ
    python scripts/_daemons/console_task_watch.py --json     # 機械向け(検査から呼ぶ)
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime


def _ensure_std():
    """★pythonw.exe だと sys.stdout / stderr が None。reconfigure が裸で落ちるのを防ぐ。

    (envelope_naming_watch.py が 2026-08-23 に実測で踏んだ穴。登録済みなのに毎時 fail-open
     していた=「登録済み≠動く」C-041。同じ足場を使う以上、同じ手当てを最初から入れる)
    """
    for nm in ("stdout", "stderr"):
        if getattr(sys, nm, None) is None:
            try:
                setattr(sys, nm, io.TextIOWrapper(io.open(os.devnull, "wb"),
                                                  encoding="utf-8", errors="replace"))
            except Exception:
                pass
        try:
            getattr(sys, nm).reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_ensure_std()

PJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
POLICY = os.path.join(HERE, "console_window_policy.json")
STATE = os.path.join(PJ, "local", "_state", "console_task_watch.json")
LOG = os.path.join(PJ, "local", "_state", "console_task_watch.jsonl")
DISPATCH = os.path.join(PJ, "scripts", "llm", "dispatch.py")

CREATE_NO_WINDOW = 0x08000000          # ★見張り自身が黒窓を作らないための唯一の砦


def _now():
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def _log(row):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(row, ts=_now()), ensure_ascii=False) + "\n")
    except Exception:
        pass                            # ★記録に失敗しても見張りは落とさない


def load_policy(path=None):
    with io.open(path or POLICY, encoding="utf-8") as f:
        return json.load(f)


def is_console_exe(execute, policy):
    """その Execute はコンソールを持つか。★ファイル名だけで見る(フルパスでも裸名でも同じ判定)。"""
    s = str(execute or "").strip().strip('"')
    if not s:
        return False
    return os.path.basename(s).lower() in {e.lower() for e in policy["console_exes"]}


def watch_prefixes(policy):
    """走査するタスク名の接頭辞。★正本は policy 側=コードに埋めない。

    空・非リストなら go5_ だけに倒す(fail-safe= 少なくとも今まで見ていた範囲は見る)。
    """
    v = (policy or {}).get("watch_prefixes")
    if isinstance(v, str):
        v = [v]
    out = [str(p).strip() for p in (v or []) if str(p).strip()]
    return out or ["go5_"]


def list_tasks(prefixes=("go5_",)):
    """登録済みタスクの (名前, Execute, Arguments) を返す。

    ★タスクXMLの直読みは使えない(System32\\Tasks は listdir がアクセス拒否)。
      PowerShell の Get-ScheduledTask が唯一の列挙路。**CREATE_NO_WINDOW を必ず付ける。**
    ★接頭辞は複数取る。1つも当たらない接頭辞があっても他は返す(-ErrorAction SilentlyContinue)。
      同じタスクが2つの接頭辞に当たっても二重に数えない(同名・同Executeの行は畳む)。
    """
    if isinstance(prefixes, str):
        prefixes = [prefixes]
    pats = ["'%s*'" % str(p).replace("'", "''") for p in prefixes if str(p).strip()]
    if not pats:
        raise RuntimeError("watch_prefixes が空だ(policy を見ろ)")
    ps = ("$rows=@(); foreach($p in @(%s)){ "
          "foreach($t in @(Get-ScheduledTask -TaskName $p -ErrorAction SilentlyContinue)){ "
          "foreach($a in $t.Actions){ $rows += [pscustomobject]@{ name=$t.TaskName; "
          "exe=$a.Execute; arg=$a.Arguments } } } }; "
          "$rows | ConvertTo-Json -Compress -Depth 3" % ",".join(pats))
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=120,
                       creationflags=CREATE_NO_WINDOW)
    out = (r.stdout or b"").decode("utf-8", "replace").strip()
    if not out:
        raise RuntimeError("Get-ScheduledTask が空を返した: rc=%d %s"
                           % (r.returncode, (r.stderr or b"").decode("utf-8", "replace")[:200]))
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    rows, seen = [], set()
    for d in data:
        row = (d.get("name") or "", d.get("exe") or "", d.get("arg") or "")
        if row in seen:
            continue                        # ★接頭辞が重なった時の二重計上を畳む
        seen.add(row)
        rows.append(row)
    return rows


_VBS_ARG = re.compile(r'"?([^"]+\.vbs)"?', re.I)
_VBS_RUN = re.compile(r"\.Run\s*\(?\s*([^,]+),\s*(\d+)", re.I)


def vbs_shows_window(arg, root=None):
    """wscript の引数に載っている .vbs が、子を隠さずに起動していないか。

    返り値= (問題があるか, 見た .vbs のパス, 理由)。★読めない時は「問題なし」に倒す
    (fail-open= 判定不能で鳴らすと、常に鳴る安全網になって無視される)。
    """
    m = _VBS_ARG.search(arg or "")
    if not m:
        return (False, "", "")
    p = m.group(1)
    if not os.path.isabs(p):
        p = os.path.join(root or PJ, p)
    try:
        with io.open(p, encoding="utf-8", errors="replace") as f:
            src = f.read()
    except Exception:
        return (False, p, "読めない(fail-open)")
    styles = [int(g[1]) for g in _VBS_RUN.findall(src)]
    if not styles:
        return (False, p, "Run が見つからない(fail-open)")
    bad = [s for s in styles if s != 0]
    if bad:
        return (True, p, "WshShell.Run の窓スタイルが %s(0=SW_HIDE でない)" % bad)
    return (False, p, "")


def scan_tasks(policy, tasks=None):
    """live+vbs の違反。★tasks を差し替えれば判定と分岐は本物のまま通せる(must-fail 用)。"""
    rows = list_tasks(watch_prefixes(policy)) if tasks is None else list(tasks)
    allow = policy.get("allow_tasks") or {}
    bad = []
    for name, exe, arg in rows:
        if name in allow:
            continue
        if is_console_exe(exe, policy):
            bad.append(("live", name, "%s %s" % (exe, arg[:120]),
                        "Execute がコンソールを持つ(%s)" % os.path.basename(exe.strip('"'))))
            continue
        if os.path.basename(exe.strip('"')).lower() == "wscript.exe":
            hit, p, why = vbs_shows_window(arg)
            if hit:
                bad.append(("vbs", name, p, why))
    return bad, len(rows)


def scan_register_scripts(policy, root=None):
    """★保険(検査ではない)= 入口を通さずタスクを登録している .ps1 を数える。

    「-Execute の値が python か」を正規表現で当てにいくと `$python` のような変数で外す。
    そこで**判定を1つに単純化**= New-ScheduledTaskAction を直に呼んでいるか否か。
    入口(New-Go5HiddenAction)を通す限り、窓を出す形では登録できない。
    """
    root = root or PJ
    allow = {k.replace("/", os.sep).lower() for k in (policy.get("allow_register_scripts") or {})}
    bad = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, "scripts")):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules")]
        for fn in filenames:
            if not fn.lower().endswith(".ps1"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if rel.lower() in allow:
                continue
            try:
                with io.open(full, encoding="utf-8", errors="replace") as f:
                    src = f.read()
            except Exception:
                continue
            if "New-ScheduledTaskAction" in src:
                bad.append(("src", rel, "New-ScheduledTaskAction",
                            "入口(New-Go5HiddenAction)を通さず直に登録している"))
    return sorted(bad)


def sig(bad):
    """違反の顔ぶれ。同じ顔ぶれを二度知らせない。"""
    return "|".join(sorted("%s:%s" % (b[0], b[1]) for b in bad))


def read_state():
    try:
        with io.open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STATE)


def build_body(bad, total, prefixes=None):
    live = [b for b in bad if b[0] == "live"]
    vbs = [b for b in bad if b[0] == "vbs"]
    src = [b for b in bad if b[0] == "src"]
    scope = " / ".join("%s*" % p for p in (prefixes or ["go5_"]))
    L = ["【イージス研究室(無人の見張り) → 研究室HQ】黒窓が出る形のタスクが %d件ある" % len(bad), ""]
    L.append("%s を %d本走査した(意図的な例外は除く)。" % (scope, total))
    if live:
        L += ["", "■ live= 登録済みタスクの Execute がコンソールを持つ(**窓が出る**)"]
        for _, name, what, why in live[:20]:
            L.append("- `%s` … %s" % (name, why))
            L.append("    %s" % what)
    if vbs:
        L += ["", "■ vbs= wscript から起動する .vbs が子を隠していない"]
        for _, name, what, why in vbs[:20]:
            L.append("- `%s` … %s" % (name, why))
            L.append("    %s" % what)
    if src:
        L += ["", "■ src(保険)= 入口を通さずタスクを登録している .ps1 = **再発の経路**"]
        for _, rel, _what, why in src[:20]:
            L.append("- `%s` … %s" % (rel, why))
    L += [
        "",
        "★直し方= 登録の入口を通す。",
        "    . (Join-Path $PSScriptRoot 'hidden_task.ps1')",
        "    $action = New-Go5HiddenAction -Execute $python -Argument ... -WorkingDirectory $root",
        "★意図的に窓を出したいタスクは `scripts/_daemons/console_window_policy.json` の",
        "  `allow_tasks` へ**理由つきで**足す(理由の無い例外は次の世代が消す)。",
        "★走査するタスク名の接頭辞も同じJSONの `watch_prefixes` が正本(コードに埋めない)。",
        "",
        "手元で今の状態を見る= `python scripts\\_daemons\\console_task_watch.py --dry-run`",
    ]
    return "\n".join(L)


def notify(body, dry):
    """研究室HQへ1便。★外へ出る手はここだけ= dry-run ではここだけ偽物にする。"""
    tmp = os.path.join(PJ, "local", "_work", "console_task_alert.md")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    if dry:
        print("--- dry-run: ここで研究室HQへ出すはずだった本文 ---")
        print(body)
        print("--- (dispatchは呼んでいない) ---")
        return "dry-run"
    r = subprocess.run([sys.executable, DISPATCH, "--dept", "hq", "--direct",
                        "--audience", "ai", "--from", "ケヴィン・デブライネ",
                        "--from-dept", "aegis-gl", "--body-file", tmp],
                       capture_output=True, timeout=120,
                       creationflags=CREATE_NO_WINDOW)
    print((r.stdout or b"").decode("utf-8", "replace").strip())
    return "sent" if r.returncode == 0 else "failed:%d" % r.returncode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="dispatchを呼ばず本文を画面へ")
    ap.add_argument("--json", action="store_true", help="機械向けに違反をJSONで出す")
    ap.add_argument("--force", action="store_true", help="顔ぶれが同じでも知らせる")
    ns = ap.parse_args(argv)

    try:
        policy = load_policy()
        bad, total = scan_tasks(policy)
        bad += scan_register_scripts(policy)
    except Exception as e:
        _log({"event": "error", "何": "走査が落ちた", "err": "%s: %s" % (type(e).__name__, e)})
        print("走査に失敗(fail-open): %s: %s" % (type(e).__name__, e))
        return 0                                    # ★fail-open

    pfx = watch_prefixes(policy)
    scope = " / ".join("%s*" % p for p in pfx)

    if ns.json:
        print(json.dumps({"total": total, "prefixes": pfx, "bad": bad},
                         ensure_ascii=False, indent=2))
        return 0

    if not bad:
        write_state({"bad": "", "checked": _now(), "total": total, "prefixes": pfx})
        print("違反なし(%s %d本)" % (scope, total))
        return 0

    s = sig(bad)
    st = read_state()
    if not (ns.dry_run or ns.force) and st.get("bad") == s:
        write_state(dict(st, checked=_now(), total=total))
        print("違反 %d件(前回と同じ顔ぶれ=知らせ直さない)" % len(bad))
        return 0

    res = notify(build_body(bad, total, pfx), ns.dry_run)
    _log({"event": "alert", "件数": len(bad), "結果": res, "sig": s[:300]})
    if not ns.dry_run:
        write_state({"bad": s, "checked": _now(), "total": total, "last": res})
    print("違反 %d件 → 研究室HQへ %s" % (len(bad), res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
