# -*- coding: utf-8 -*-
"""send_audit — DiscordのOUT口に共通の送信ログを1本置く(記録先はここだけ)。

★0歩目に見た壊れた実物: msg 1544669455995637771(ad研究室ch)。本文が
  `--body-file /proc/self/fd/0` という**フラグの文字列そのもの**で投稿されていた。
  研究室HQが真因まで割った(bot_send.py L55= 残り引数を連結して本文にする口・フラグを解釈しない)。
  ★だが**誰がその便を出したのかは分からなかった**——bot_send.py 全89行に送信ログが1行も無く、
  「どのプロセスがどの部屋へ何を出したか」を残していなかったからだ。真因は分かったのに
  出所が追えない。これはガードの穴ではなく**観測の穴**で、次の事故でも同じ所で止まる。

なぜこの形か:
  - **合流点に置く**。OUT口ごとに書き方を変えると、割れた側が黙って抜ける
    (2026-09-01 の炎上表記ゲートが persona_send にだけ入って bot_send を素通しした型と同じ)。
    実際にDiscordへHTTPを撃つのは2箇所しかない= bot_send.main() と persona_send.post()。
    そこ**だけ**から呼ぶ。dispatch は自分でPOSTせず persona_send を起動する=この1本に乗る。
  - **記録先を2つに割らない**(ORG-11)。書き先は local/llm/send_audit.jsonl だけ。
  - **送信を殺さない**(fail-open)。この中の例外は全部握り潰す。ログが取れないより
    便が出ないことの方が重い(最悪の事故は沈黙)。
  - **止めた便も残す**(event="blocked")。鳴ったことが分からないガードは、
    登録されていても動いているか分からない=本番の初発火が初検証になる。

1行の形(JSONL):
  ts / event(send|blocked) / via(bot_send|persona_send) / channel_id / channel / dept /
  persona / status(HTTPコード or "ERR:例外名" or 止めた理由) / chars / head(本文の頭120字) /
  body(本文の全文) / body_truncated(全文が入り切らなかった時だけ true) /
  msg_id / pid / ppid / origin(環境変数 GO5_SEND_ORIGIN=呼び出し元の名乗り・任意) / argv

★secretは載せない= トークンはファイルから読むのでargvにもヘッダにも出ない。
  本文の頭は載せる(C-013= ローカル内は共有・ネットへは出さない。local/ は .gitignore 済み)。

★2026-09-04 本文を**全文**残すようにした(DEF-manga-shorts-ccd93dc601・動画制作部門から回付)。
  壊れた実物= 09-03 07:37 に動画制作部門が出した選択肢の便(501字)。Chamiは2分後に
  「1 b / 2 a」だけで確定したが、**何を確定したのかを後から誰も引けなかった**——
    ・この台帳: head=120字。選択肢は501字の**末尾130字**に在り、切り落とされていた。
    ・部屋の記憶(hr/memory): reply を500字で切る。ぎりぎり残ったのは偶然。
    ・当時のwebhook便は msg_id が空(wait=true 前)= Discordへ読み返しにも行けなかった。
  = 3つの写しが全部「頭だけ」で、決定の**指示対象**が黙って消える経路になっていた。
  ★msg_id の穴は 09-03 に塞がれている(persona_send=wait=true / bot_send=応答JSONを読む。
    実測: 09-03 17:00以降の429便すべてに msg_id が在る)。残っていたのは**本文の切り**の方。
  なぜ全文をここに置くか= 頭だけの写しを3つ持っていても、1つも本文を再現できない。
  Discordに残っているから良い、にもしない(外部・消える・APIが要る)。**撃った本文の正本は
  撃った側が持つ**。読み出しは `python scripts/discord/whatis.py <msg_id> --body`。
  ★記録先は増やさない(ORG-11)= 同じ1行に列を1つ足すだけ。head は既存の読み手
    (whatis.py 等)のために**残す**(消すと黙って壊れる)。
  ★太るぶんは回転で受ける= 8MB→32MB(実測 約430KB/日・全文で約1.4MB/日。
    旧設定のままだと保持が18日→6日へ**縮む**ので、縮ませないための引き上げ)。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
# ★テストは GO5_LOCAL_DIR で書き先だけ差し替える(判定と分岐は本物のまま回す)。
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
AUDIT = os.path.join(LOCAL, "llm", "send_audit.jsonl")
# ★検査便の行き先(2026-09-13 イージス研究室)。本番の台帳とは別ファイル。
TEST_AUDIT = os.path.join(LOCAL, "llm", "send_audit_test.jsonl")
ROTATE_BYTES = 32 * 1024 * 1024
HEAD_CHARS = 120
# ★本文の全文。Discordの1通の上限は2000字だが、分割前の原稿を渡してくる呼び元が居ても
#   丸ごと残せるように広く取る。ここを超えた時だけ body_truncated=true を立てる
#   (黙って切らない= 切られたことが分かれば msg_id からDiscordを読み返せる)。
BODY_CHARS = 20000


def _head(body):
    s = str(body or "").replace("\r", "").replace("\n", "⏎")
    return s[:HEAD_CHARS]


def _argv():
    """起動時の引数。長い本文をそのまま抱えないよう1項目200字で切る。"""
    out = []
    for a in list(sys.argv)[:24]:
        a = str(a)
        out.append(a if len(a) <= 200 else a[:200] + "…")
    return out


def _is_test_entry():
    """この実行が「検査の走行」か。★機械だけで判る材料で決める(2026-09-13 イージス研究室)。

    ★壊れた実物が2つある:
      ・2026-09-03 `test_enjoh_confluence.py` が本番台帳へ3行書いた
        (退避= local/llm/send_audit_quarantine_20260903_testdummy.jsonl)。
      ・2026-09-13 `test_persona_dupe_guard.py` が同じことをした
        (10:55:38 の blocked/dupe_guard 1行= 本物の事故と見分けが付かない)。
      10日空けて同じ穴を踏んでいる= 再発(C-038)。
    ★上の L55 に「テストは GO5_LOCAL_DIR で差し替える」と**書いてある**のに、10日で2本とも
      設定し忘れた。**人手の入口を要件にした機構は実測0件になる**(§3)。だから env は
      「差し替えたい時の手動の口」として残し、**既定は機械が自分で判る材料**へ寄せる。
    ★判定材料= 起動したスクリプト名(`sys.argv[0]`)が `test_*.py` / `*_test.py` か、
      pytest が積まれているか。どちらもプロセス自身の中に在る。
      ★`unittest` は見ない= `unittest.mock` を本番の道具が引くと**本物の送信が台帳から
        黙って消える**(誤発火の方が高く付く。ここは「拾えた分だけ得」で止める)。
    ★fail-open= ここで例外を出さない。判らなければ False(=本番台帳へ書く)。
      台帳の1行が惜しくて送信を殺す、は絶対にしない。
    """
    try:
        names = []
        # ★正本は「実際に起動されたスクリプト」= __main__.__file__。
        #   sys.argv[0] を先に見て失敗した実測がある(2026-09-13): test_persona_dupe_guard.py は
        #   本物の main() を回すために `sys.argv = ["persona_send.py", ...]` と**自分で書き換える**。
        #   argv だけ見ていると、検査の走行が本番の送信に化ける。argv は控えとして併せて見る。
        m = sys.modules.get("__main__")
        names.append(getattr(m, "__file__", "") or "")
        names.append(str(sys.argv[0] if sys.argv else "") or "")
        for n in names:
            base = os.path.basename(n).lower()
            if base.endswith(".py") and (base.startswith("test_") or base.endswith("_test.py")):
                return True
        return "pytest" in sys.modules
    except Exception:
        return False


def _rotate(path):
    try:
        if os.path.getsize(path) > ROTATE_BYTES:
            os.replace(path, path + ".1")
    except Exception:
        pass


def record(via, body="", event="send", status="", channel_id="", channel="",
           dept="", persona="", msg_id="", path=None):
    """1行追記する。★戻り値は使わせない=呼び出し元の分岐に絶対に絡ませない。"""
    try:
        # ★検査の走行は本番台帳へ混ぜない(2026-09-13)。捨てるのではなく**別ファイルへ残す**
        #   = 検査が撃ったつもりの1行も後から読める(黙って消すと検査side が壊れても気づかない)。
        p = path or (TEST_AUDIT if _is_test_entry() else AUDIT)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _rotate(p)
        _body = str(body or "")
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": str(event or "send"),
            "via": str(via or ""),
            "channel_id": str(channel_id or ""),
            "channel": str(channel or ""),
            "dept": str(dept or ""),
            "persona": str(persona or ""),
            "status": str(status or ""),
            "chars": len(_body),
            "head": _head(body),
            # ★全文(改行はそのまま。JSONが \n で包むので1行のまま保てる)。
            "body": _body[:BODY_CHARS],
            "msg_id": str(msg_id or ""),
            "pid": os.getpid(),
            "ppid": (os.getppid() if hasattr(os, "getppid") else 0),
            "origin": os.environ.get("GO5_SEND_ORIGIN", ""),
            # ★2026-09-17 追加(イージス研究室・発注= ローカル研究室カスミ
            #   DISPATCH-aegis-gl-1789632009829 / Chami直令 msg 1550050117401313311)。
            #   「裏(--audience ai)で回した便に表ackが出た」を**後から数えられる**ようにする列。
            #   ★なぜ要るか= 実測で判った穴。inbox.db の acked_at とこの台帳を15分窓で結ぶと、
            #     裏便221件のうち91件が窓内に表投稿を伴う。だが大半はChami宛の正当な本文で、
            #     **出ていく投稿の側に「どの便への返信か」の印が無い**ため、時間窓だけでは
            #     誤検知だらけになる(実測して確認した)。印は撃つ側が刻むしかない。
            #   ★origin と同じ型= 環境変数で渡す。刻まれていなければ空文字(fail-open)。
            #     判定にも分岐にも使わない=**記録だけ**。ここで送信を殺さない。
            "in_reply_to": os.environ.get("GO5_REPLY_TO", ""),
            "in_reply_audience": os.environ.get("GO5_REPLY_AUDIENCE", ""),
            "argv": _argv(),
        }
        if len(_body) > BODY_CHARS:
            rec["body_truncated"] = True    # ★切ったことを黙らせない(chars と付き合わせれば分かる)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass                    # ★fail-open= ここで送信を殺さない
