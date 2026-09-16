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

        def read(self):
            # ★2026-09-16: wait=true を付けたので、本物のDiscordは投稿JSONを返す。
            #   偽物もそれに合わせる= msg_id を拾う枝を本物のまま通すため。
            return b'{"id": "1549999999999999999"}'

    def fake_urlopen(req, timeout=60):
        body = req.data
        head = body.split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0]
        seen["payload"] = json.loads(head.decode("utf-8"))
        seen["url"] = req.full_url
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
    LAST.clear()
    LAST.update(seen)
    return seen.get("payload") or {}


LAST = {}


def audited(gen, caption, note):
    """本番と同じ道で discord_upload を1回通し、**台帳に落ちた行**をその場で読む。

    ★書き先だけサンドボックスへ逃がす(GO5_LOCAL_DIR)。判定と分岐は本物のまま=
      台帳へ書くか/何を書くかは generate.py の中の本物のコードが決める。
    """
    box = tempfile.mkdtemp(prefix="imgaudit_")
    old_env = os.environ.get("GO5_LOCAL_DIR")
    os.environ["GO5_LOCAL_DIR"] = box
    sys.modules.pop("send_audit", None)          # LOCAL を読み直させる
    try:
        payload = captured_payload(gen, caption, note)
    finally:
        if old_env is None:
            os.environ.pop("GO5_LOCAL_DIR", None)
        else:
            os.environ["GO5_LOCAL_DIR"] = old_env
        sys.modules.pop("send_audit", None)

    def rows(name):
        p = os.path.join(box, "llm", name)
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in io.open(p, encoding="utf-8").read().splitlines() if l.strip()]

    return payload, rows("send_audit_test.jsonl"), rows("imagegen_posts_test.jsonl")


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

    # --- E 撃った本文がローカルに残る(2026-09-16 中野五月 DISPATCH-aegis-gl-1789568669959) ---
    #   壊れた実物= 23:13:32 の go5org_00017_.png。所要時間の行が載ったかを、ローカルの
    #   どの台帳からも読めなかった=「載ったはず」を数字で裏取りできなかった。
    cap = "生成依頼テキストを読んで画像生成して"
    note = gen.elapsed_note(33.0, 34.0)
    payload, audit, index = audited(gen, cap, note)
    body = audit[0].get("body", "") if audit else ""
    ok(len(audit) == 1, "E-1 画像を1枚貼ると送信台帳に1行だけ残る(実測 %d行)" % len(audit))
    ok(body == payload.get("content"),
       "E-2 台帳の本文が、Discordへ渡した content と**1文字も違わない**(頭だけの写しではない)")
    ok("所要 67秒(タグ変換 34秒 / 描画 33秒)" in body,
       "E-3 その本文から所要時間の行を**そのまま読める**= 実物確認が記憶でなく数字になる")
    ok(bool(audit and audit[0].get("msg_id")),
       "E-4 msg_id が入る(wait=true)= 台帳の行から実物の投稿へ辿り直せる")
    ok("wait=true" in (LAST.get("url") or ""),
       "E-5 webhookのURLに wait=true が付いている(付けないとDiscordは204・本文なし)")
    ok(len(index) == 1 and index[0].get("image", "").endswith(".png")
       and index[0].get("msg_id") == (audit[0].get("msg_id") if audit else None),
       "E-6 どのpngがどの投稿になったかの索引が1行残る(msg_idで本文へ繋がる)")
    ok("content" not in (index[0] if index else {}),
       "E-7 索引は本文の写しを持たない(ORG-11= 本文の正本は send_audit 1本)")

    # --- F 台帳のために投稿を殺さない(fail-open) -----------------------------------
    real_rec = None
    try:
        import send_audit as _sa
        real_rec = _sa.record

        def boom(*a, **k):
            raise RuntimeError("台帳が壊れている")

        _sa.record = boom
        p5 = captured_payload(gen, "台帳が死んでいても出す", gen.elapsed_note(9.0))
        ok(p5.get("content", "").startswith("台帳が死んでいても出す"),
           "F-1 台帳側が例外を出しても投稿は通る(最悪の事故は沈黙)")
    except AssertionError:
        raise
    finally:
        if real_rec is not None:
            _sa.record = real_rec
    return not _fails


def mustfail():
    """足す前の版(.bak)で、この検査が本当に赤くなるかをその場で示す。

    ★2本ある= 所要時間(_elapsed)と、台帳へ残す口(_sendaudit)。どちらの版でも
      この検査のどこかが必ず赤くなることを、同じ手番で見せる。
    """
    reds = []
    for bak, attr, why in (
            ("generate.py.bak_20260916_elapsed", "elapsed_note", "所要時間の1行(A/B)"),
            ("generate.py.bak_20260916_sendaudit", "_audit", "撃った本文の台帳(E)")):
        p = os.path.join(_HERE, bak)
        if not os.path.exists(p):
            print("SKIP: 比較用の .bak が無い= " + p)
            continue
        tmp = os.path.join(tempfile.mkdtemp(prefix="imgnote_old_"), "generate_old.py")
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(io.open(p, encoding="utf-8").read())
        try:
            gen = load_generate(tmp)
        except Exception as e:
            print("  OK  %s の版は読み込みで落ちる(= 赤): %s" % (bak, e))
            reds.append(True)
            continue
        red = not hasattr(gen, attr)
        print(("  OK  " if red else "  NG  ")
              + "%s には %s が無い= %s が赤くなる" % (bak, attr, why))
        reds.append(red)
    return bool(reds) and all(reds)


if __name__ == "__main__":
    if "--mustfail" in sys.argv:
        sys.exit(0 if mustfail() else 1)
    TOTAL = 18
    good = run(load_generate(), "現物 scripts/imagegen/generate.py")
    print(("PASS 画像便の所要時間と送信台帳 %d/%d" % (TOTAL - len(_fails), TOTAL)) if good
          else ("FAIL %d件: %s" % (len(_fails), " / ".join(_fails))))
    sys.exit(0 if good else 1)
