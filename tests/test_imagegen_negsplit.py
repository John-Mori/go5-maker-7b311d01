# -*- coding: utf-8 -*-
"""画像部屋の【ポジティブ】【ネガティブ】切り分け(2026-09-23 イージス研究室)。

発注= 研究室HQ DISPATCH-aegis-gl-1790166561731 / Chami原文 msg 1552295146882736229。
★文字列一致ではなく**経路を実行で通す**(共通規律§3)=
  local_chain.main() を本物のまま回し、外へ出る手(LM Studio・lms unload・subprocess)だけ偽物にする。
  出来た generate.py の引数で generate.main() も本物のまま回し、ComfyUIへ投げる直前の
  グラフを捕まえて **KSampler の negative ノードに入る文字列**を見る。
★must-fail= 旧 local_chain(.bak_20260923_negsplit)へ差し替えると【ネガティブ】の語がポジへ入り、
  ネガは既定のまま=事故(仕様書の副作用4)が再現することも確かめる。
"""
import importlib.machinery
import importlib.util
import io
import os
import sys
import contextlib

PJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(PJ, "scripts", "imagegen")
sys.path.insert(0, IMG)
import generate as gen  # noqa: E402

FAILS = []
LAST = {}


def check(name, ok):
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        FAILS.append(name)


def load_chain(path):
    name = "lc_%d" % abs(hash(path))     # .bak は拡張子が .py でないので loader を明示する
    spec = importlib.util.spec_from_file_location(
        name, path, loader=importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Stop(Exception):
    pass


def run(chain_path, text):
    """返り値= (rc, ポジ文字列, ネガ文字列, キャプション, to_tagsに渡った(本文,system)列)。"""
    lc = load_chain(chain_path)
    seen = []

    def fake_to_tags(t, max_tokens=4000, system=None):   # 外へ出る手(LM Studio)だけ偽物
        seen.append((t, system))
        return ("NEG<%s>" % t) if system else ("POS<%s>" % t)
    lc.to_tags = fake_to_tags
    lc.ensure_server = lambda: True
    lc.unload_llm = lambda: None
    got = {}

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(cmd, **kw):
        got["cmd"] = cmd
        return _R()
    lc.subprocess.run = fake_run
    sys.argv = ["local_chain.py", text, "--discord", "画像生成ルーム", "--persona", "優依"]
    rc = 0
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            lc.main()
    except SystemExit as e:
        rc = e.code or 0
    if rc:
        return rc, None, None, None, seen
    # generate.main を本物で回す。ComfyUIへの /prompt だけ捕まえて止める
    cap = {}

    def fake_api(path, payload=None):
        cap["wf"] = payload["prompt"]
        raise _Stop()
    gen.api = fake_api
    sys.argv = got["cmd"][1:]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            gen.main()
    except _Stop:
        pass
    wf = cap["wf"]
    ks = [n for n in wf.values() if n["class_type"] == "KSampler"][0]["inputs"]
    pos = wf[ks["positive"][0]]["inputs"]["text"]
    neg = wf[ks["negative"][0]]["inputs"]["text"]
    cmd = got["cmd"]
    LAST["cmd"] = list(cmd)
    caption = cmd[cmd.index("--caption") + 1] if "--caption" in cmd else None
    return rc, pos, neg, caption, seen


NEW = os.path.join(IMG, "local_chain.py")
OLD = os.path.join(IMG, "local_chain.py.bak_20260923_negsplit")
D = gen.NEG_DEFAULT

# A マーカー無し= 旧と同じ
t = "夜の書店で本を読む女の子"
rc, p, n, c, s = run(NEW, t)
cmd_new = LAST["cmd"]
_, p0, n0, c0, s0 = run(OLD, t)
cmd_old = LAST["cmd"]
check("A マーカー無し: generate.py へ渡す引数が旧と完全一致(--neg も足さない)",
      cmd_new == cmd_old and "--neg" not in cmd_new)
check("A マーカー無し: ネガは既定のまま", n == D)
check("A マーカー無し: to_tagsへ渡る本文もポジもキャプションも旧と一致", (p, c, s) == (p0, c0, s0))

# B 【ポジティブ】だけ
rc, p, n, c, s = run(NEW, "【ポジティブ】\n 銀髪の少女、笑顔 \n")
check("B ポジだけ: 中身(前後trim)がポジへ", p == "POS<銀髪の少女、笑顔>")
check("B ポジだけ: ネガは既定のまま", n == D)

# C 地の文+【ポジティブ】+【ネガティブ】
rc, p, n, c, s = run(NEW, "夜の書店\n【ポジティブ】銀髪の少女\n【ネガティブ】 眼鏡、帽子 ")
check("C ポジ= 地の文+【ポジティブ】の中身(ネガの語は入らない)", p == "POS<夜の書店\n銀髪の少女>")
check("C ネガ= 既定の後ろに指定分を足す(置き換えない)", n == D + ", NEG<眼鏡、帽子>")
check("C ネガの変換はネガ用の指示で(品質タグを足す SYSTEM を使わない)",
      any(sy is not None and "品質タグ" in sy and "足さない" in sy for _, sy in s))
check("C 投稿に使ったネガ(指定分)が1行載る", c is not None and "描かないもの: 眼鏡、帽子 → NEG<眼鏡、帽子>" in c)

# 空のマーカーは無かったものとして扱う
rc, p, n, c, s = run(NEW, "猫\n【ネガティブ】\n")
check("空の【ネガティブ】= 既定のまま・ネガ変換を呼ばない", n == D and all(sy is None for _, sy in s))

# ポジが空= 描かずに rc=6
rc, p, n, c, s = run(NEW, "【ネガティブ】眼鏡")
check("ポジが空= rc=6 で止まり、タグ変換も描画も呼ばない", rc == 6 and s == [])

# must-fail= 旧実装では【ネガティブ】の語がポジへ入り、ネガは既定のまま
_, p0, n0, _, _ = run(OLD, "夜の書店\n【ポジティブ】銀髪の少女\n【ネガティブ】 眼鏡、帽子 ")
check("★must-fail: 旧実装では『眼鏡』がポジ側へ入る(=逆に描かれうる事故の再現)", "眼鏡" in p0 and n0 == D)

print("-" * 60)
print("全PASS" if not FAILS else "%d 件 FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
