#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""persona-hub 静的セルフチェック(読み取り専用)。
狙い= 「見た目を出荷前にCLIから実機確認できない」ぶんの手数(入れた→Chami確認→配線漏れ/構文崩れで往復)を、
機械が撃てる範囲で先に潰す。改修αの最頻の穴=UIのボタンを足して配線し忘れる/JS構文で真っ白/参照CSS欠落。

検査(実物と突き合わせる。台帳一致ではない):
 1. app.js が JS として構文が通るか(node --check)。node が無ければその項はskipし警告。
 2. style.css の { } が釣り合うか(INC-47系の崩れ・未閉じブロック)。
 3. renderで吐く data-act="X" / data-c="X" の全種に、対応する act==="X" / c==="X" のハンドラ枝があるか。
 4. renderで参照する主要CSSクラスが style.css に定義されているか(av-removed / cropper-*)。

exit 0=異常なし / exit 1=要修正(検出内容を出す)。
"""
import os, re, subprocess, sys, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()

errors, warns = [], []

app = read("app.js")
css = read("style.css")

# 1) app.js の構文(node があれば)
node = shutil.which("node")
if node:
    r = subprocess.run([node, "--check", os.path.join(HERE, "app.js")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        errors.append("app.js の構文エラー: " + (r.stderr.strip() or r.stdout.strip()))
else:
    warns.append("node が無いので app.js の構文検査をskipした")

# 2) style.css の波括弧の釣り合い
op, cl = css.count("{"), css.count("}")
if op != cl:
    errors.append("style.css の {}=%d/%d で釣り合っていない(未閉じブロックの疑い)" % (op, cl))

# 3) 吐く属性と、それを捌くハンドラ枝の突き合わせ
def emitted(attr):
    return set(re.findall(r'data-' + attr + r'="([a-z0-9\-]+)"', app))
def handled(var):
    # act === "remove" / c === "apply" どちらの引用符も拾う
    return set(re.findall(var + r'\s*===\s*["\']([a-z0-9\-]+)["\']', app))

for attr, var, label in [("act", "act", "data-act"), ("c", "c", "data-c")]:
    em, hd = emitted(attr), handled(var)
    missing = sorted(em - hd)
    if missing:
        errors.append("%s=%s を吐くが捌く枝が無い(配線漏れ)" % (label, ",".join(missing)))

# 4) renderが参照する主要クラスが CSS にあるか
need = ["av-removed", "av-removed-chip", "cropper-overlay", "cropper-frame",
        "cropper-grid", "cropper-btn", "cropper-cv"]
for cls in need:
    if ("." + cls) not in css:
        errors.append("CSSクラス .%s が style.css に無い(参照はあるのに未定義)" % cls)

if errors:
    print("NG persona-hub selfcheck:")
    for e in errors:
        print("  - " + e)
    sys.exit(1)
print("OK persona-hub selfcheck" + (" (warn: " + "; ".join(warns) + ")" if warns else ""))
sys.exit(0)
