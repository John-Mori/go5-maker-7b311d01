#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""console_task_watch(黒窓の見張り)の回帰テスト。

実行: python scripts/_daemons/test_console_task_watch.py

★C-053= must-fail を1本入れる。「壊した実装なら落ちる」ではなく
  **動く別実装(素朴で、もっともらしい判定)を並べて、それが取りこぼすことを見せる。**
  ここでの素朴案= 「python.exe で終わるかどうか」。実際これで大半のタスクは当たるので、
  検査が無ければ誰かがこう書く。powershell.exe と cmd.exe と py.exe を丸ごと見逃す。
"""
import importlib.util
import io
import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
PJ = os.path.dirname(os.path.dirname(HERE))
SPEC = importlib.util.spec_from_file_location(
    "console_task_watch_under_test", os.path.join(HERE, "console_task_watch.py"))
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)

POLICY = w.load_policy()
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")


# --- 判定の正本 -------------------------------------------------------------
print("[判定] どの exe が窓を出すか")
check("python.exe は窓を出す", w.is_console_exe("python.exe", POLICY))
check("フルパスでも同じ判定", w.is_console_exe(r"C:\Python312\python.exe", POLICY))
check("引用符つきでも同じ判定", w.is_console_exe('"C:\\Program Files\\python.exe"', POLICY))
check("powershell.exe は窓を出す", w.is_console_exe("powershell.exe", POLICY))
check("cmd.exe は窓を出す", w.is_console_exe("cmd.exe", POLICY))
check("cscript.exe は窓を出す(wscriptと違う)", w.is_console_exe("cscript.exe", POLICY))
check("pythonw.exe は安全", not w.is_console_exe("pythonw.exe", POLICY))
check("wscript.exe は安全", not w.is_console_exe("wscript.exe", POLICY))
check("空文字は安全側へ倒す", not w.is_console_exe("", POLICY))

# --- ★must-fail(C-053): 動く別実装が取りこぼすこと ---------------------------
print("[must-fail] 素朴な別実装『python.exe で終わるか』")


def naive(execute, policy=None):
    """もっともらしいが不足している判定。実装として動きはする。"""
    return str(execute or "").strip().strip('"').lower().endswith("python.exe")


corpus = ["python.exe", r"C:\py\python.exe", "powershell.exe", "cmd.exe", "py.exe",
          "pythonw.exe", "wscript.exe"]
miss = [e for e in corpus if w.is_console_exe(e, POLICY) != naive(e)]
check("素朴案は powershell/cmd/py を取りこぼす(=この検査には意味がある)",
      set(miss) == {"powershell.exe", "cmd.exe", "py.exe"})
check("素朴案でも pythonw は安全と分かる(だから見逃しに気づけない)", not naive("pythonw.exe"))

# --- 走査範囲(接頭辞)の正本 --------------------------------------------------
print("[範囲] どのタスクを見るかは policy が決める(コードに埋めない)")
check("policy から接頭辞を読む",
      w.watch_prefixes({"watch_prefixes": ["a_", "b_"]}) == ["a_", "b_"])
check("文字列1本でも受ける", w.watch_prefixes({"watch_prefixes": "a_"}) == ["a_"])
check("未設定なら go5_ に倒す(今まで見ていた範囲は必ず見る)",
      w.watch_prefixes({}) == ["go5_"])
check("空リストでも go5_ に倒す", w.watch_prefixes({"watch_prefixes": []}) == ["go5_"])
check("★実物の policy は go5_ と chami_style_ の両方を見る",
      set(w.watch_prefixes(POLICY)) >= {"go5_", "chami_style_"})

# --- ★must-fail(C-053): 走査対象を go5_ 固定にした「動く別実装」が取りこぼす -------
print("[must-fail] 素朴な別実装『走査対象は go5_ で始まるタスクだけ』")

MIXED = [
    ("go5_bad_ps", "powershell.exe", "-File x.ps1"),
    ("chami_style_step9", r"D:\LoRAEasyStudio\...\python.exe", r"run_step9.py"),
]


def naive_scan(policy, tasks):
    """2026-08-30 の HEAD がやっていた形= 接頭辞をコードに固定した走査。動きはする。"""
    return w.scan_tasks(policy, tasks=[t for t in tasks if t[0].startswith("go5_")])[0]


real_bad, _ = w.scan_tasks(POLICY, tasks=MIXED)
check("★policy 版は chami_style_ の違反も拾う",
      {b[1] for b in real_bad} == {"go5_bad_ps", "chami_style_step9"})
check("★go5_固定の素朴案は chami_style_ を丸ごと素通りさせる(=この改修の意味)",
      {b[1] for b in naive_scan(POLICY, MIXED)} == {"go5_bad_ps"})

# --- タスク走査 -------------------------------------------------------------
print("[走査] 登録済みタスク(材料だけ差し替え・判定と分岐は本物)")
FAKE = [
    ("go5_ok_pyw", r"C:\py\pythonw.exe", r'"D:\x\a.py"'),
    ("go5_bad_ps", "powershell.exe", "-NoProfile -WindowStyle Hidden -File x.ps1"),
    ("go5_lora_step3", "cmd.exe", "/c python.exe train.py"),
]
bad, total = w.scan_tasks(POLICY, tasks=FAKE)
names = {b[1] for b in bad}
check("窓を出すタスクを拾う", "go5_bad_ps" in names)
check("pythonw のタスクは拾わない", "go5_ok_pyw" not in names)
check("★意図的な例外(go5_lora_step3)は鳴らさない", "go5_lora_step3" not in names)
check("走査した本数を返す", total == 3)
check("種別は live", all(b[0] == "live" for b in bad))

print("[走査] -WindowStyle Hidden は言い訳にならない")
check("Hidden 付きでも powershell.exe なら違反",
      any(b[1] == "go5_bad_ps" for b in bad))

# --- vbs の中身 -------------------------------------------------------------
print("[vbs] wscript から起動する .vbs が子を隠しているか")
tmpd = tempfile.mkdtemp(prefix="ctw_")
hidden = os.path.join(tmpd, "hidden.vbs")
shown = os.path.join(tmpd, "shown.vbs")
with io.open(hidden, "w", encoding="utf-8") as f:
    f.write('Set sh = CreateObject("WScript.Shell")\nWScript.Quit sh.Run(cmd, 0, True)\n')
with io.open(shown, "w", encoding="utf-8") as f:
    f.write('Set sh = CreateObject("WScript.Shell")\nWScript.Quit sh.Run(cmd, 1, True)\n')
check("Run(...,0,...) は問題なし", not w.vbs_shows_window('"%s"' % hidden)[0])
check("★Run(...,1,...) は窓が出る=拾う", w.vbs_shows_window('"%s"' % shown)[0])
check("存在しない .vbs は鳴らさない(fail-open)",
      not w.vbs_shows_window('"%s"' % os.path.join(tmpd, "nope.vbs"))[0])
check(".vbs が無い引数は無視", not w.vbs_shows_window("--once")[0])

bad2, _ = w.scan_tasks(POLICY, tasks=[("go5_v", "wscript.exe", '"%s" a' % shown)])
check("wscript 経由でも中身まで見る", bad2 and bad2[0][0] == "vbs")

# --- 本物の run_hidden.vbs ---------------------------------------------------
real_vbs = os.path.join(HERE, "run_hidden.vbs")
check("本物の run_hidden.vbs は子を隠している", not w.vbs_shows_window('"%s"' % real_vbs)[0])

# --- 登録スクリプトの保険 -----------------------------------------------------
print("[保険] 入口を通さない .ps1(★これは検査ではなく保険・共通規律§3)")
root = tempfile.mkdtemp(prefix="ctw_src_")
os.makedirs(os.path.join(root, "scripts", "_daemons"))
with io.open(os.path.join(root, "scripts", "raw.ps1"), "w", encoding="utf-8") as f:
    f.write("$a = New-ScheduledTaskAction -Execute 'powershell.exe'\n")
with io.open(os.path.join(root, "scripts", "gated.ps1"), "w", encoding="utf-8") as f:
    f.write(". hidden_task.ps1\n$a = New-Go5HiddenAction -Execute $python\n")
src = w.scan_register_scripts(POLICY, root=root)
rels = {s[1] for s in src}
check("直に登録している .ps1 を拾う", os.path.join("scripts", "raw.ps1") in rels)
check("入口を通す .ps1 は拾わない", os.path.join("scripts", "gated.ps1") not in rels)

allow_root = tempfile.mkdtemp(prefix="ctw_allow_")
os.makedirs(os.path.join(allow_root, "scripts", "_daemons"))
with io.open(os.path.join(allow_root, "scripts", "_daemons", "hidden_task.ps1"),
             "w", encoding="utf-8") as f:
    f.write("New-ScheduledTaskAction @params\n")
check("★入口自身は例外として鳴らさない", not w.scan_register_scripts(POLICY, root=allow_root))

# --- 実物の repo を走査 -------------------------------------------------------
print("[実物] いまの repo を走査する")
live_src = w.scan_register_scripts(POLICY)
check("repo に入口を通さない登録スクリプトが無い(%d件)" % len(live_src), not live_src)

print("[実物] 接頭辞が重なっても二重に数えない(★Get-ScheduledTask を本当に叩く)")
once = w.list_tasks(["go5_"])
twice = w.list_tasks(["go5_", "go5_"])
check("同じ接頭辞を2つ渡しても本数は増えない(%d本)" % len(once), len(once) == len(twice))
check("走査が実際に何か返している", len(once) > 0)

print("[実物] 立ち続ける違反を入れていない(★常に鳴る網は無視される)")
now_bad, now_total = w.scan_tasks(POLICY)
check("いまの走査範囲で live/vbs 違反が0(%d本走査)" % now_total, not now_bad)

# --- 知らせ方 ---------------------------------------------------------------
print("[知らせ方] 同じ顔ぶれを二度知らせない")
two = bad + [("live", "go5_another", "cmd.exe", "…")]
check("同じ違反なら順番が違っても署名は同じ", w.sig(two) == w.sig(list(reversed(two))))
check("顔ぶれが1件増えれば署名も変わる", w.sig(two) != w.sig(bad))
check("違反が消えれば署名は空", w.sig([]) == "")
body = w.build_body(bad + src, 31, w.watch_prefixes(POLICY))
check("本文に違反したタスク名が載る", "go5_bad_ps" in body)
check("本文に直し方(入口の呼び方)が載る", "New-Go5HiddenAction" in body)
check("本文に例外の足し方が載る", "allow_tasks" in body)
check("★本文に走査範囲が載る(どこまで見た警報かが分かる)",
      "go5_* / chami_style_*" in body and "watch_prefixes" in body)

# --- policy が2箇所に分かれていないこと ----------------------------------------
print("[正本] 判定のリストが1つであること")
with io.open(os.path.join(HERE, "hidden_task.ps1"), encoding="utf-8") as f:
    gate_src = f.read()
check("入口は policy JSON を読んでいる", "console_window_policy.json" in gate_src)
check("入口に exe リストの写しが無い",
      "'python.exe'" not in gate_src and '"python.exe"' not in gate_src)
with io.open(os.path.join(HERE, "console_task_watch.py"), encoding="utf-8") as f:
    watch_src = f.read()
check("見張りは policy JSON を読んでいる", "console_window_policy.json" in watch_src)
check("★見張りが powershell を呼ぶ時 CREATE_NO_WINDOW を付けている(自分が窓を出さない)",
      "creationflags=CREATE_NO_WINDOW" in watch_src)
check("例外には理由が書いてある",
      all(isinstance(v, str) and len(v) > 10
          for v in (POLICY["allow_tasks"] | POLICY["allow_register_scripts"]).values()))

ok = sum(1 for _, c in results if c)
print("\n%d/%d PASS" % (ok, len(results)))
for n, c in results:
    if not c:
        print("  FAILED:", n)
sys.exit(0 if ok == len(results) else 1)
