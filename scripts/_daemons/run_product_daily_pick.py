# -*- coding: utf-8 -*-
"""毎朝8:00の起動器= 商品候補選定部門の候補ピックを生成して、その部屋へ投稿する。

依頼= 十王星南(商品候補選定部門) msg 1537487811081404566 / 元はChami直依頼
      msg 1537485839758663742「毎朝8時に…ピックアップして教えて。寝るからやっといて」。
分担= 生成(採点・件数・母集団)は product-scout 側の
      `docs/departments/product-scout/tools/daily_pick.py` が正本。**こちらは触らない。**
      実行のスケジュールと部屋への投稿だけが基盤(この起動器)の担当。

なぜ起動器が「投稿」までやるか(C-036)=
  生成して stdout に出すだけでは**誰も読まない**。対話セッションの自発報告を当てにせず、
  **終わった瞬間に起動器自身が部屋へ出す**。名義は部門常駐の十王星南(依頼の指定どおり)。
  ★kaizen の起動器は dispatch(キュー投函)だが、こちらは **persona_send で直接投稿**する。
    理由= Chamiが毎朝「見る」ことが依頼の中身であって、部屋のセッションが起きて出し直す
    一段を挟むと、そこが死んでいる朝は静かに出ない。見せる物は直接出す。

沈黙させない(共通規律§3 fail-open)=
  生成が失敗した / 空だった / 文字化けした のどれでも、**その事実を部屋へ出す**。
  「取得できなかった」が出る朝はあってよい。何も出ない朝があってはいけない。

登録= scripts/_daemons/register_product_daily_pick_task.ps1(タスク名 go5_product_daily_pick_0800)
手で試す= python scripts/_daemons/run_product_daily_pick.py --dry-run
"""
import argparse
import datetime as dt
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PICK = os.path.join(ROOT, "docs", "departments", "product-scout", "tools", "daily_pick.py")
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
LOG = os.path.join(ROOT, "local", "_product_daily_pick.log")
BODY = os.path.join(ROOT, "local", "_work", "product_daily_pick_body.txt")
DEPT = "product-scout"           # 商品候補選定部門の部屋
PERSONA = "十王星南"             # 部門常駐(精霊)。アバター/色/webhookはこの素の名前で引かれる


def log(msg):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "%s %s" % (stamp, msg)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _child_env():
    """★子のpythonに UTF-8 で喋らせる。

    タスクスケジューラから走らせると端末が無く、子のstdoutは **cp932** になる。
    こちらが utf-8 として読むので日本語のタイトルが化け、`errors="replace"` が
    化けたまま通す= 中身が壊れた本文がそのまま投稿される(2026-08-13 に改修α集計で実際に焼かれた)。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run(cmd, timeout=None):
    return subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=_child_env(), timeout=timeout)


def main():
    ap = argparse.ArgumentParser(description="毎朝の候補ピックを生成して商品候補選定部門の部屋へ投稿する")
    ap.add_argument("--dry-run", action="store_true",
                    help="生成は走らせるが、投稿しない(本文を表示して終わる)")
    a = ap.parse_args()

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = "**■ 毎朝の候補ピック(%s)**\n" % now      # ★走った実時刻を出す(8時以外に走った朝が見て分かる)

    if not os.path.exists(PICK):
        body = head + "★生成の台本が見つからない= `%s`\n(商品候補選定部門の持ち物。移動/改名されていないか見てくれ)" % PICK
        log("★台本が無い= %s" % PICK)
    else:
        try:
            # D1をwrangler越しに読む=ネットワーク待ちがある。タスク側の上限(15分)より内側で切る。
            r = run([PICK], timeout=600)
            out = (r.stdout or "").strip()
        except subprocess.TimeoutExpired:
            r, out = None, ""
            log("★生成が10分で終わらなかった(timeout)")
            body = head + "★候補ピックを取得できなかった= 生成が10分で終わらなかった(D1/wranglerの応答待ち)。\nログ= `local/_product_daily_pick.log`"
        else:
            if r.returncode != 0 or not out:
                # ★黙って落とすな= 失敗そのものを届ける(沈黙が最悪の事故)。
                body = (head + "★候補ピックを取得できなかった(exit=%s)。\n```\n%s\n```" %
                        (r.returncode, (r.stderr or "(stderrも空)")[:1200]))
                log("★生成が失敗した exit=%s" % r.returncode)
            elif "�" in out:
                # ★化けた本文を投稿しない= 壊れた物を黙って配るくらいなら、壊れたと言う。
                n = out.count("�")
                body = (head + "★候補ピックは生成できたが、**本文が文字化けした**(U+FFFD %d個)。\n"
                        "子プロセスの出力エンコーディングを疑え(PYTHONIOENCODING)。\n"
                        "化けた本文は捨てた= `local/_product_daily_pick.log` を見てくれ。" % n)
                log("★本文が化けている(U+FFFD %d個)= 投稿しない" % n)
            else:
                body = head + out
                log("生成OK= %d字" % len(out))

    if a.dry_run:
        log("--dry-run= 投稿しない。本文は以下:")
        # ★TextIOWrapper で包むと、それが捨てられる時に sys.stdout.buffer ごと閉じる
        #   (同一プロセスで2回呼ぶと2回目のprintが ValueError で落ちる)。bytesで直に書く。
        sys.stdout.buffer.write((body + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0

    os.makedirs(os.path.dirname(BODY), exist_ok=True)
    with io.open(BODY, "w", encoding="utf-8") as f:     # ★BOM無しで書く(persona_sendはutf-8で読む)
        f.write(body + "\n")

    p = run([PERSONA_SEND, "--dept", DEPT, "--persona", PERSONA, "--body-file", BODY], timeout=180)
    ok = p.returncode == 0
    log("投稿 exit=%s / %s" % (p.returncode, (p.stdout or p.stderr or "").strip()[-300:]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
