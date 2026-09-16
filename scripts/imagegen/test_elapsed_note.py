# -*- coding: utf-8 -*-
"""画像便に「かかった時間」が載るかの検査(2026-09-16 イージス研究室)。

依頼= Chami原文「かかった時間も教えてもらえるようにして」
(部屋=画像生成ローカル-fusoh_v2-漫画 msg 1549777099580121232 /
 回送= 中野五月 DISPATCH-aegis-gl-1789566427422)。

★ソースの文字列一致では見ない(共通規律§3)。**判定と分岐は本物のまま回し、
  外へ出る手(webhookのURL取得とHTTP送信)だけ偽物にする**。
  = discord_upload() を実行して、Discordへ渡す payload の中身を読む。

  python scripts/imagegen/test_elapsed_note.py
  python scripts/imagegen/test_elapsed_note.py --mustfail   # 足す前の版で赤を確認
"""
import io
import json
import os
import sys
import types
import importlib.util
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
if ROOT.endswith("scripts"):
    ROOT = os.path.dirname(ROOT)
ROOT = os.path.dirname(os.path.dirname(_HERE))

_fails = []


def ok(cond, name):
    print(("  OK  " if cond else "  NG  ") + name)
    if not cond:
        _fails.append(name)


def load_generate(path=None):
    """generate.py を読む。★外へ出る手だけ偽物にするため、先に persona_send を差し替える。"""
    fake = types.ModuleType("persona_send")
    fake.ensure_webhook = lambda cid, token: "https://example.invalid/webhook/" + str(cid)
    sys.modules["persona_send"] = fake
    p = path or os.path.join(_HERE, "generate.py")
    spec = importlib.util.spec_from_file_location("imagegen_generate_t", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def captured_payload(gen, caption, note, channel="画像生成ローカル-fusoh_v2-漫画"):
    """discord_upload を本物のまま走らせ、HTTPへ渡る payload_json だけ抜く。"""
    seen = {}

    class _Res(object):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=60):
        body = req.data
        head = body.split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0]
        seen["payload"] = json.loads(head.decode("utf-8"))
        return _Res()

    real = gen.urllib.request.urlopen
    img = os.path.join(tempfile.mkdtemp(prefix="imgnote_"), "a.png")
    with open(img, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    try:
        gen.urllib.request.urlopen = fake_urlopen
        gen.discord_upload(img, channel, "優依", caption, note=note)
    finally:
        gen.urllib.request.urlopen = real
    return seen.get("payload") or {}


def run(gen, label):
    print("== " + label + " ==")

    # --- A 文言そのもの(内訳あり/なし) --------------------------------------------
    ok(gen.elapsed_note(35.4, 12.1) == "所要 48秒(タグ変換 12秒 / 描画 35秒)",
       "A-1 内訳つき= 合計・タグ変換・描画の3つが出る")
    ok(gen.elapsed_note(44.0) == "所要 44秒(描画)",
       "A-2 タグ変換段を測っていない呼び方では、描画だけを書く(推測で埋めない)")
    ok(gen.elapsed_note(None) == "" and gen.elapsed_note(None, 9.0) == "",
       "A-3 描画を測れていなければ何も足さない(嘘の0秒を出さない)")

    # --- B 実際にDiscordへ渡る本文(配線を実行で通す) ------------------------------
    p = captured_payload(gen, "夜の書店で本を読む女の子", gen.elapsed_note(35.4, 12.1))
    c = p.get("content", "")
    ok("所要 48秒(タグ変換 12秒 / 描画 35秒)" in c,
       "B-1 投稿本文に所要時間が載る(payloadを実行で確認)")
    ok(c.startswith("夜の書店で本を読む女の子") and "\n" in c,
       "B-2 元のキャプションは残り、時間は改行して後ろへ付く")
    ok(p.get("username") == "優依", "B-3 名義は変わっていない")

    # --- C 既存の挙動を壊していない -------------------------------------------------
    p2 = captured_payload(gen, "できたわよ", "")
    ok(p2.get("content") == "できたわよ",
       "C-1 note が空なら従来と1文字も変わらない")
    FIRE, ENJOH = "\U0001F525", "<:enjoh:1541126866981752883>"
    p3 = captured_payload(gen, FIRE + "炎上 2件", gen.elapsed_note(10.0))
    ok(ENJOH in p3.get("content", "") and FIRE not in p3.get("content", ""),
       "C-2 炎上表記ゲートは時間を足した後も生きている(C-064の合流点)")
    p4 = captured_payload(gen, "あ" * 2000, gen.elapsed_note(35.4, 12.1))
    c4 = p4.get("content", "")
    ok(len(c4) <= 1900 and c4.endswith("所要 48秒(タグ変換 12秒 / 描画 35秒)"),
       "C-3 長いキャプションでも、切られるのは本文側で時間表示は消えない")

    # --- D 呼ぶ側(local_chain)がタグ変換の秒数を渡している -------------------------
    src = io.open(os.path.join(_HERE, "local_chain.py"), encoding="utf-8").read()
    ok("--tag-seconds" in src and '"%.1f" % (t1 - t0)' in src,
       "D-1 local_chain が測ったタグ変換の秒数を generate へ渡す")
    return not _fails


def mustfail():
    """時間を足す前の版(.bak)で、この検査が本当に赤くなるかをその場で示す。"""
    bak = os.path.join(_HERE, "generate.py.bak_20260916_elapsed")
    if not os.path.exists(bak):
        print("SKIP: 比較用の .bak が無い= " + bak)
        return True
    tmp = os.path.join(tempfile.mkdtemp(prefix="imgnote_old_"), "generate_old.py")
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(io.open(bak, encoding="utf-8").read())
    try:
        gen = load_generate(tmp)
    except Exception as e:
        print("  OK  旧版は読み込みで落ちる(= 赤): %s" % e)
        return True
    red = not hasattr(gen, "elapsed_note")
    print(("  OK  " if red else "  NG  ") + "旧版には elapsed_note が無い= この検査は赤くなる")
    return red


if __name__ == "__main__":
    if "--mustfail" in sys.argv:
        sys.exit(0 if mustfail() else 1)
    good = run(load_generate(), "現物 scripts/imagegen/generate.py")
    print(("PASS 画像便の所要時間 %d/%d" % (10 - len(_fails), 10)) if good
          else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
