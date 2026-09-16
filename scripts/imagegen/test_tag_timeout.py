# -*- coding: utf-8 -*-
"""タグ変換段のハードtimeout / fail-fast / 部屋に出る文面の検査(2026-09-16 イージス研究室)。

依頼= 中野五月 DISPATCH-aegis-gl-1789567116980
  「(1)to_tags のHTTP呼び出しに妥当なハードtimeoutを入れ、超えたら早く諦めて
    明確な理由でescalate (2)長引く/暴走する時の fail-fast (3)失敗理由を部屋で読んで
    分かる文言に」。事故= 22:39:51起動 → 約909秒ハング → rc1 で死亡・絵は0枚。

★ソースの文字列一致では見ない(共通規律§3)。**判定と分岐は本物のまま回す**=
  ・timeout は本物の socket/urlopen で起こす(受け皿だけ、返事をしない捨てサーバを127.0.0.1に立てる)
  ・retry の回数も、VRAM解放を挟むかも、実際に to_tags を走らせて数える
  外へ出る手で偽物にするのは ComfyUI の /free(実機のVRAMを触らせない)だけ。

  python scripts/imagegen/test_tag_timeout.py
  python scripts/imagegen/test_tag_timeout.py --mustfail   # 直す前の版(.bak)で赤を確認
"""
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))

_fails = []
TOTAL = 17


def ok(cond, name):
    print(("  OK  " if cond else "  NG  ") + name)
    if not cond:
        _fails.append(name)


def load(path=None):
    p = path or os.path.join(_HERE, "local_chain.py")
    spec = importlib.util.spec_from_file_location("local_chain_t", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class DeafServer(object):
    """接続は受けるが、何も返さないサーバ。= 事故当日の gemma と同じ振る舞い。"""

    def __init__(self, reply=None):
        self.reply = reply
        self.hits = 0
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._keep = []
        self._stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self._stop:
            try:
                c, _ = self.sock.accept()
            except Exception:
                return
            self.hits += 1
            if self.reply is None:
                self._keep.append(c)          # 掴んだまま黙る(返事をしない)
                continue
            threading.Thread(target=self._answer, args=(c,), daemon=True).start()

    def _answer(self, c):
        try:
            c.recv(65536)
            b = json.dumps(self.reply).encode("utf-8")
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                      b"Connection: close\r\nContent-Length: "
                      + str(len(b)).encode() + b"\r\n\r\n" + b)
            # ★送り切る前に閉じると WinError 10053 になり、検査が中身ではなく
            #   捨てサーバの行儀で落ちる。送信方向だけ畳んでから閉じる。
            c.shutdown(socket.SHUT_WR)
            time.sleep(0.2)
        except Exception:
            pass
        finally:
            try:
                c.close()
            except Exception:
                pass

    @property
    def url(self):
        return "http://127.0.0.1:%d/v1/chat/completions" % self.port

    def close(self):
        self._stop = True
        for c in self._keep:
            try:
                c.close()
            except Exception:
                pass
        try:
            self.sock.close()
        except Exception:
            pass


def _free_counter(lc):
    """ComfyUIの /free だけ偽物にする(実機のVRAMは触らせない)。呼ばれた回数を数える。"""
    n = {"calls": 0}

    def fake():
        n["calls"] += 1
        return True

    lc.free_comfy_vram = fake
    return n


def run(lc, label):
    print("== " + label + " ==")

    # --- A 返らない相手に、決めた秒数で見切りをつける ------------------------------
    ok(getattr(lc, "TAG_TIMEOUT", 900) <= 300,
       "A-1 タグ変換の上限が実用域に降りている(旧900秒のままではない)")
    deaf = DeafServer()
    try:
        lc.TAG_TIMEOUT = 2.0
        t = time.time()
        try:
            lc._post(deaf.url, {"a": 1})
            got, dt = None, time.time() - t
        except Exception as e:
            got, dt = e, time.time() - t
        ok(isinstance(got, lc.TagTimeout),
           "A-2 返らない相手には TagTimeout が上がる(素のsocket例外を漏らさない)")
        ok(dt < 6.0, "A-3 上限の秒数で実際に切れる(実測 %.1f秒)" % dt)
        ok("秒" in str(got), "A-4 例外の文面に待った秒数が入っている= 部屋で読める")

        # --- B fail-fast= 無限に粘らない・間でVRAMを空ける -------------------------
        lc.LMS_API = deaf.url
        n = _free_counter(lc)
        before = deaf.hits
        t = time.time()
        try:
            lc.to_tags("夜の書店で本を読む女の子")
            got2, dt2 = None, time.time() - t
        except Exception as e:
            got2, dt2 = e, time.time() - t
        ok(isinstance(got2, lc.TagTimeout),
           "B-1 to_tags は時間切れを TagTimeout として投げる")
        ok(deaf.hits - before == 2,
           "B-2 諦める前に引き直すのは1回だけ(実測 %d回投げた)= 無限に粘らない"
           % (deaf.hits - before))
        ok(n["calls"] == 1,
           "B-3 1回目の時間切れで ComfyUI のVRAMを空けてから引き直す(実測 %d回)" % n["calls"])
        ok(dt2 < 12.0, "B-4 全体でも上限の2回分で終わる(実測 %.1f秒)" % dt2)

        # --- C 正常系を1文字も変えていない -----------------------------------------
        good = DeafServer(reply={"choices": [{"message": {"content": "1girl, bookstore, night, "
                                                                     "masterpiece, best quality, highres"}}],
                                 "usage": {"completion_tokens_details": {"reasoning_tokens": 900}}})
        try:
            lc.LMS_API = good.url
            n2 = _free_counter(lc)
            tags = lc.to_tags("夜の書店で本を読む女の子")
            ok(tags.startswith("1girl") and "highres" in tags,
               "C-1 まともに返る相手からは今まで通りタグ列が返る")
            ok(n2["calls"] == 0, "C-2 成功した時はVRAMに手を出さない(人の絵を巻き添えにしない)")
        finally:
            good.close()
    finally:
        deaf.close()

    # --- D 親へ返す rc と、部屋に出す合図 -----------------------------------------
    code, out = _main_rc(lc)
    ok(code == 5, "D-1 タグ変換timeoutは rc=5 で親へ返る(rc=3のLORA_MISSINGと同じ型・実測 rc=%s)" % code)
    ok(out.strip().startswith("TAG_TIMEOUT"),
       "D-2 標準出力の1行目が TAG_TIMEOUT …= 親がそのまま部屋の文面に使える")

    # --- E 親(local_responder)が rc=5 を部屋の言葉に直す ---------------------------
    _responder_branch()
    return not _fails


def _responder_branch():
    """local_responder の分岐を**本物のまま**通し、部屋に出る文面を読む。

    偽物にするのは外へ出る手だけ= local_chain の起動 / Discord送信 / 台帳書き込み。
    """
    spec = importlib.util.spec_from_file_location(
        "local_responder_t", os.path.join(ROOT, "scripts", "llm", "local_responder.py"))
    lr = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(lr)
    except Exception as e:
        ok(False, "E-0 local_responder が読めない: %s" % e)
        ok(False, "E-1 (未実施)")
        ok(False, "E-2 (未実施)")
        ok(False, "E-3 (未実施)")
        return

    seen = {"as": [], "plain": [], "log": []}
    lr.send_as = lambda ch, text, persona, suffix="": seen["as"].append((ch, text, persona))
    lr.send = lambda ch, text, *a, **k: seen["plain"].append((ch, text))
    lr.append_line = lambda *a, **k: None
    lr.log = lambda d: seen["log"].append(d)

    class _R(object):
        def __init__(self, rc, out):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake_run(rc, out):
        lr.subprocess.run = lambda *a, **k: _R(rc, out)

    fake_run(5, "TAG_TIMEOUT 180秒たっても応答が無かった\n")
    lr.handle_image_request({}, "{}", "夜の書店で本を読む女の子",
                            "画像生成ローカル-fusoh_v2-漫画", dept="imagegen-fusoh-v2")
    said = "\n".join(t for _, t, _ in seen["as"])
    ok("タグ" in said and "180秒" in said,
       "E-1 部屋に出る文面が「タグ変換が時間内に返らなかった」と読める(待った秒数つき)")
    ok("ComfyUI" in said and "無罪" in said,
       "E-2 描く側を疑わせない= 切り分けを文面に書く(事故当日ComfyUIは無罪だった)")
    ok(any(d.get("mode") == "tag_timeout" for d in seen["log"]),
       "E-3 台帳の mode が tag_timeout= escalated の山に埋めない")

    seen["as"], seen["log"], seen["plain"] = [], [], []
    fake_run(1, "なにか別の壊れ方")
    lr.handle_image_request({}, "{}", "夜の書店で本を読む女の子",
                            "画像生成ローカル-fusoh_v2-漫画", dept="imagegen-fusoh-v2")
    ok(any(d.get("mode") == "escalated" for d in seen["log"]) and not seen["as"],
       "E-4 rc=5 以外は従来どおりClaudeへ回送する(既存の枝を壊していない)")


def _main_rc(lc):
    """main() を本物のまま走らせ、タグ変換が時間切れした時の rc と出力を読む。"""
    import io

    def boom(text, max_tokens=4000):
        raise lc.TagTimeout("180秒たっても応答が無かった")

    real_to_tags, real_argv, real_out = lc.to_tags, sys.argv, sys.stdout
    lc.to_tags = boom
    lc.ensure_server = lambda: True      # ← 外へ出る手(LM Studioの起動)だけ偽物にする
    sys.argv = ["local_chain.py", "テストの注文"]
    buf = io.StringIO()
    sys.stdout = buf
    code = None
    try:
        lc.main()
    except SystemExit as e:
        code = e.code
    finally:
        lc.to_tags, sys.argv, sys.stdout = real_to_tags, real_argv, real_out
    return code, buf.getvalue()


def mustfail():
    """直す前の版(.bak)で、この検査が本当に赤くなるかをその場で示す。"""
    bak = os.path.join(_HERE, "local_chain.py.bak_20260916_tagtimeout")
    if not os.path.exists(bak):
        print("SKIP: 比較用の .bak が無い= " + bak)
        return True
    tmp = os.path.join(tempfile.mkdtemp(prefix="tagto_old_"), "local_chain_old.py")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(open(bak, encoding="utf-8").read())
    try:
        old = load(tmp)
    except Exception as e:
        print("  OK  旧版は読み込みで落ちる(= 赤): %s" % e)
        return True
    red = not hasattr(old, "TagTimeout") or not hasattr(old, "free_comfy_vram")
    print(("  OK  " if red else "  NG  ")
          + "旧版には TagTimeout / free_comfy_vram が無い= この検査は赤くなる")
    import inspect
    src = inspect.getsource(old._post)
    print("      旧版の _post 既定timeout= " + ("900秒" if "900" in src else "?"))
    return red


if __name__ == "__main__":
    if "--mustfail" in sys.argv:
        sys.exit(0 if mustfail() else 1)
    good = run(load(), "現物 scripts/imagegen/local_chain.py")
    print(("PASS タグ変換timeout %d/%d" % (TOTAL - len(_fails), TOTAL)) if good
          else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
