#!/usr/bin/env python3
"""部門常駐デーモン (恒久基盤R0・2026-07-18 Chami承認「着手して」)。

なにものか:
  「キャラ=データ、セッション=使い捨て」原則(00_AI-HQ/設計書_恒久基盤リサーチ_2026-07-18.md §3)の実装第1号。
  部門のキャラクターを対話TUIセッションではなく常駐デーモンとして提供する。
  人格=characterfile(HQ管轄)・記憶=jsonlストア(HQ管轄)——**どちらもプロセスの外**にあるため、
  このプロセスが何度死んでもキャラは死なない(daemon_keeperが数秒で再起動し、記憶は繋がる)。

対話窓との共存(重要):
  対話TUI窓(open_dept_window)が開いている間=その部門のinbox_waiterプロセスが居る間は、
  デーモンは**完全に待機**する(箱に触れない=多重応答なし)。窓が閉じた/死んだ瞬間から
  デーモンが同じキャラとして応対を引き継ぐ。=「窓は人間の操作卓、常在はデーモン」。

presence:
  毎ループ claude_active_<dept>.txt をtouchする(唯一の書き手が対話窓waiterからデーモンに拡張)。
  → pollerは部門箱へ配送し続け、watchdog P2「窓死」通知は鳴らない(部門は実際に有人=デーモン)。
  加えて /live /ready をHTTPで公開(k8s probeパターン。mtime推定をR2でこれに置換する布石)。

応答の生成:
  claude --print(CLAUDE_CODE_OAUTH_TOKEN・タイムアウト300s)に characterfile+記憶末尾N件+新着 を
  渡し、**返信本文だけ**を生成させる(ツール実行はさせない=口調崩れ・暴走の面を最小化)。
  送信(persona_send)・既読(react)・記憶追記・台帳記帳はデーモンが機械的に行う=確実性を機械に、
  人格を生成に、で分担する。

使い方:
  python scripts/llm/dept_daemon.py --dept hr-room          # 常駐
  python scripts/llm/dept_daemon.py --dept hr-room --once   # 1巡回(点検)
  python scripts/llm/dept_daemon.py --dept hr-room --once --dry-run  # 送信せず生成まで(テスト)
テスト: 環境変数 GO5_LOCAL_DIR があれば local/ の代わりにそれを使う。
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
HQ = r"D:\SougouStartFolder\00_AI-HQ"
TOKEN_FILE = os.path.join(LOCAL, "cli_auth_token.txt")
PROCESSED = os.path.join(LOCAL, "discord_processed.jsonl")
CLAUDE = r"C:\Users\chami\.local\bin\claude.exe"
PERSONA_SEND = os.path.join(ROOT, "scripts", "discord", "persona_send.py")
REACT = os.path.join(ROOT, "scripts", "discord", "react.py")
MAIN_INBOX = os.path.join(LOCAL, "discord_inbox.jsonl")

try:
    import session_rooms        # 対話セッションの在席(liveness)。同ディレクトリ
except Exception:
    session_rooms = None        # 読めなくても現行動作(プロセス列挙)に安全に退化する

POLL_SEC = 3                    # 箱の見張り間隔(waiterの2秒に準拠した軽さ)
# ★2026-07-21 Chami裁定「常時2秒でやる」= **集中ウィンドウ(可変間隔)は廃止した**。
#   同日の午前に「寝てる時は遅くていい」の要望で 2秒/12秒 の切替を入れたが、
#   **節約できている量を測ったら実質ゼロ**だったため、概念ごと畳んだ:
#     実測 1クエリ = 0.005ms → 16部門×2秒間隔で **1コアの0.004%**。
#     12秒間隔なら0.001%。**差は0.003%**=切り替える価値が無い(SQLiteを見るだけでトークンも0)。
#   さらに、遅い側が既定だと**Chamiが札を立て忘れた時だけ遅い**という最悪の外し方をする。
#   ★本当の待ち時間は生成時間(会話15〜60秒/実作業は最大10分)。ポーリングは主役ではない。
#     速さに効いたのは間隔ではなく**その部屋に消費者が居ること**だった(ORG-15)。
POLL_QUEUE = 2                  # queueの見張り間隔(常時)。可変にしない


def poll_interval():
    """queueの見張り間隔。常に2秒(集中ウィンドウは2026-07-21に廃止)。

    互換のため関数は残す(呼び出し側を書き換えずに済ませる)。
    """
    return POLL_QUEUE
INTERACTIVE_CHECK_SEC = 30      # 対話窓waiterの存在確認の間隔(プロセス列挙は重いのでキャッシュ)
MEMORY_TAIL = 20                # promptへ注入する記憶の末尾件数
PRINT_TIMEOUT = 300
WORK_TIMEOUT = 600             # ツール付き作業(work_generate)の上限
WORK_MODEL = "sonnet"          # ★O3(裁-3): 作業agentの既定(実装の物量=sonnet・分業表準拠)
# ★部門ごとのモデル上書き(2026-07-21 Chami指摘「デーモンの処理能力が悪かったら、
#   作業してもらっても結局バグを作る温床。**一番重視してるのは品質を落とさないこと**」)。
#   指摘は正しい。既定のsonnetは `CLAUDE.md §5.1` の分業表で「見た目・文言の調整/単一ファイルの
#   素直な追加」に割り当てられた層であって、**判断が要る部屋には足りない**。
#   同 §1 の優先順位は **正確性>安全性>検証可能性>保守性>トークン効率>速度** で、
#   「品質を犠牲にしたトークン節約は禁止」と明記されている=**判断の部屋は上位モデルにするのが規約側の答え**。
#   DEPT_CONF に "work_model" があればそれを使う。無ければ従来どおり WORK_MODEL。
def work_model_for(conf):
    return (conf or {}).get("work_model") or WORK_MODEL
# ★O3(裁-3・改善書P1-5): 作業agentの許可ツールを最小allowlistへ固定。旧 bypassPermissions は
#   「何でも実行可」=プロンプトインジェクション耐性が最弱線だった。--print(headless)では未許可
#   ツールは自動拒否(プロンプトを出せないため)=allowlist外は安全に落ちる。ファイル作業+検証に
#   必要な範囲だけ許可。Bashのコマンド単位のさらなる絞り込みはO5の follow-up。
WORK_ALLOWED_TOOLS = ["Read", "Edit", "Write", "Grep", "Glob", "Bash"]
# 作業依頼キーワード(=main箱回送 or work_scope部門でのwork_generate起動の判定に使う)。
# ★依頼形(〜して/〜お願い等)に限定する(2026-07-20 qa-reviewer点検・過剰回送修正=INC本文参照)。
#   旧版は「反映」「実装」「修正」「デプロイ」等を裸の名詞で拾っており、"反映完了したら知らせて"
#   のような単なる報告依頼(情報要求)にも一致→研究室への過剰回送(実測 hq 8件+hr-context 5件)の主因だった。
#   バグ/エラー/壊れ は完了報告パターン(「〜したら知らせて」)と結びつかない症状語のため対象外
#   (system-engineerの通常のバグ報告受理を壊さないよう保守的に現状維持)。
WORK_WORDS = ("直して", "直しといて", "修正して", "修正お願い", "実装して", "実装お願い",
              "追加して", "デプロイして", "デプロイお願い", "変えて", "作って", "調べて",
              "特定して", "バグ", "エラー", "壊れ", "対応して", "やって",
              "反映して", "反映お願い", "反映をお願い", "消して", "削除して", "削除お願い")
# 情報要求語(教えて/知らせて/確認して 等)。WORK_WORDSはこれらとは重複しない設計
# (=情報要求のみの文はWORK_WORDSに一致せず自動的にis_work=Falseになる)。
# テスト(test_dept_daemon_classify.py)で非重複と分類結果を検証する。
INFO_WORDS = ("教えて", "教えてほしい", "知らせて", "確認して", "見てほしい", "見せて")


def classify_work(content):
    """本文が「作業依頼」かどうかを判定する(main箱回送/work_scope起動の判定に使用)。

    単純なWORK_WORDS部分一致だが、判定ロジックを1箇所に集約することで
    generate()とhandle()の重複判定がズレる事故を防ぐ(2026-07-20)。

    ★これは**速い一次判定**でしかない。自然文(「設計して手足として動かして」)は
      原理的に取りこぼす。取りこぼしの回収は WORK_MARKER(キャラ自身の申告)が担う。
      **キーワードを増やして精度を上げようとしないこと**(自然文である限り必ず再発する。
      2026-07-20に実際に事故った)。
    """
    return any(w in str(content) for w in WORK_WORDS)


# ★恒久対処(2026-07-20 組織層GL室): 「回します/やっておく」と言って何も起きない事故の真因は
#   **返信を書く判断者(キャラLLM)と、回送/作業を起こす判断者(キーワード正規表現)が別人**だったこと。
#   キャラが約束してもコードは約束を知らないので裏切りが構造的に発生する。
#   対処= キャラ自身に「これは作業依頼か」を申告させ、**同じ判断者から返信と発火を出す**。
#   申告は返信末尾の1行マーカーで受け取り、Discordへ送る前に機械的に取り除く。
WORK_MARKER = "<<WORK>>"


def split_work_marker(reply):
    """返信本文から WORK_MARKER を取り除き (本文, キャラの申告) を返す。

    マーカーは行内のどこにあっても拾う(LLMが「 <<WORK>>」等と揺らしても落とさない)。
    マーカーだけの行は丸ごと落とし、本文中に混ざった場合はその語だけ除去する。
    """
    text = str(reply or "")
    if WORK_MARKER not in text:
        return text.strip(), False
    kept = []
    for line in text.splitlines():
        if WORK_MARKER in line:
            rest = line.replace(WORK_MARKER, "").strip()
            if rest:
                kept.append(rest)
        else:
            kept.append(line)
    return "\n".join(kept).strip(), True


# ★マーカー遵守率の監査(2026-07-20 組織層GL室・Chami「着手して」)
#   WORK_MARKERで発火はキャラの自己申告に一本化したが、申告を**書き漏らす**と従来どおり沈黙する
#   =事故の再発経路が1本だけ残る。しかも現状その頻度を誰も測っていない。
#   ★禁止事項との関係: 「キーワードを増やすな」は**入力(Chamiの依頼文)の分類**の話。
#     ここでやるのは**出力(キャラ自身の返信)の事後監査**なので別物。
#     入力の自然文は無限だが、「約束した」の表現はキャラ自身の語彙=有限で、しかも
#     外しても実害が回送ノイズで済む(判定の非対称性がある)。
#   ★語尾の揺れに注意。初版は「整理しておく」「出しておく」の〜ておく形だけを並べていたが、
#     実測の返信は「整理してそっちに出すぜ。少し待ってろ。」で**1語も一致しなかった**
#     (2026-07-20 hr-context・実弾で発見)。キャラは口語で約束するので〜ておく形に頼れない。
#   ★★コスト非対称の前提を訂正した(2026-07-20 21:10 実測):
#     当初「拾いすぎ=main箱へ余計な1件・実害なし」と書いたが**これは誤り**だった。
#     研究室が寝ている間は claude_responder(無人代打)がmain箱を処理して**Discordへ返信する**ため、
#     誤検出は「同じ部屋でChamiが2回返事をもらう」という**利用者に見える実害**になる。
#     実際に consult-intel で発生させた(下記)。よって再現率一辺倒では倒さず、
#     **「話者が自分の次の行動を宣言している形」だけを拾う**方針に変更する。
#   ★除外した語(descriptiveな地の文に出るため誤検出源だった):
#     「整理して」「まとめて」「調べる」「対応する」「回す」「組む」「進める」等の
#     **裸の辞書形/テ形**。実測の誤検出=consult-intel「受け取って整理してファイルに積んで満足、
#     は成果じゃないわ」(整理して に一致・**約束ではなく否定文の説明**)。
#     残すのは 〜ておく形・文末の意志表現(〜ぜ/〜わ/〜ます)・語彙的に一意な受諾語だけ。
PROMISE_WORDS = (
    # 受諾(語彙的に一意)
    "やっておく", "やっとく", "やるぜ", "やるわ", "やります", "引き受け", "受けた",
    "受け取った", "任せ", "承知",
    # 着手の表明
    "手をつける", "手を付ける", "着手する", "進めておく", "進めるわ", "進めるぜ",
    "対応しておく", "対応するわ", "対応するぜ",
    # 成果物を出す約束(意志の文末形のみ。「整理して」等のテ形は入れない)
    "出すぜ", "出すわ", "出します", "出しておく", "まとめておく", "整理しておく",
    "作っておく", "用意しておく", "組んでおく",
    # 調査の約束
    "見ておく", "調べておく", "調べるわ", "調べるぜ", "確認しておく",
    # 回送の約束(これを言って回さないのが元の事故)。裸の「回す」は説明文に出るので入れない
    "回すわ", "回します", "回しておく", "回すぜ", "回すね",
    # 「待ってろ」系=これから自分が動く合図(実測で最も頻出)
    "待ってろ", "待ってて", "待ってくれ", "少し待", "ちょっと待",
)
MARKER_AUDIT = os.path.join(LOCAL, "_marker_audit.jsonl")


def find_promise(reply):
    """返信本文が「自分がやる」と約束しているように読めるならその語を返す(無ければ None)。"""
    text = str(reply or "")
    for w in PROMISE_WORDS:
        if w in text:
            return w
    return None


def _match_context(reply, matched, span=40):
    """一致語の前後を切り出す(誤検出かどうかを人が判定するための証拠)。"""
    if not matched:
        return None
    text = str(reply or "")
    i = text.find(matched)
    if i < 0:
        return None
    return text[max(0, i - span):i + len(matched) + span]


def audit_marker(dept, rec, reply, declared, kw_work):
    """申告の遵守を事後計測し、書き漏らし便を救済すべきかを返す。

    記録する事象は2種類だけ(これで 取りこぼし率 = miss / (declared + miss) が出せる):
      - declared: キャラが申告した便(分母側)
      - miss    : **約束しているのに申告が無い**便(分子側)=旧実装なら沈黙していた便
    どちらでもない便(雑談・質問)は記録しない=台帳を膨らませない。

    戻り値: True なら救済(=is_workへ倒す)。約束の証拠はキャラ自身の返信の中にあるので、
    黙って落とさず回送する方へ倒す。
    ★ただし誤検出はタダではない(研究室が寝ていると無人代打が返信し**二重応答**になる)。
      PROMISE_WORDSの注記を参照。精度側の調整はこのログの miss を読んで行うこと。
    """
    promise = None if declared else find_promise(reply)
    if not declared and not promise:
        return False
    if declared:
        event, matched = "declared", None
    elif kw_work:
        # キーワードが既に拾っている=回送は起きるので沈黙事故ではない。分子には数えない
        event, matched = "miss_covered_by_keyword", promise
    else:
        event, matched = "miss", promise
    try:
        with open(MARKER_AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "dept": dept,
                "event": event,
                "matched": matched,
                "msg_id": str(rec.get("msg_id", "")),
                "content": str(rec.get("content", ""))[:200],
                "reply": str(reply or "")[:200],
                # ★一致箇所の前後を必ず残す(2026-07-20 実測): reply[:200]の切り詰めで
                #   一致語そのものが切り落とされ、誤検出か正検出か判定できない便が出た
                #   (platform-se・'回す')。証拠が読めない監査ログは精度調整に使えない。
                "matched_context": _match_context(reply, matched),
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 監査は本番経路を壊さない(落ちても応答は続ける)
    return event == "miss"


# 部門→(characterfile, 記憶ストア, 送信ペルソナ名, /liveポート, 作業範囲)。R2で全部門へ拡張(2026-07-19 Chami「やって」)。
# work_scope: 定義があると作業依頼(WORK_WORDS)をツール付きagentで**部屋の中で完結**させる
#   (2026-07-18 Chami「反映作業もここでやれないのか?」への恒久回答)。範囲外はmain箱へ回送。
# work_scope無し: 会話はキャラで即応・作業依頼はキャラの声で受けてmain箱へ回送(研究室が本対応)。
# 機微部屋(dream-care/past-room/health-log)は対象外=PROTOCOL管轄・デーモン化しない。
_CHAR = os.path.join(HQ, "departments", "hr", "characters")
_MEM = os.path.join(HQ, "departments", "hr", "memory")
_REGISTRY = os.path.join(HQ, "org_registry.yml")
_reg_cache = {"mtime": 0.0, "depts": {}}


_DISCIPLINE = os.path.join(HQ, "departments", "00_common", "全部門共通規律.md")
_disc_cache = {"mtime": None, "text": ""}


def common_discipline():
    """全部門共通の規律を**都度読み**して返す(2026-07-21 Chami指示)。

    Chami原文=「どこかで問題が起きたら**全部が勝手に自動的に更新されて、どの部門でも
    二度と起きない**仕組みにして。**こっちの承認とか、こっちが言わなくても裏で自動でやって**。
    じゃないとここで潰しても他の部門でまたやらかすやん」。

    ★なぜファイルを都度読みするのか(定数に埋めない理由):
      DEPT_CONFやモジュール定数は**プロセス起動時にしか読まれない**ので、教訓を1行足すたびに
      艦隊16部門の再起動が要る=運用が回らず、結局誰も足さなくなる(=今までがそれ)。
      mtimeを見て変わった時だけ読み直せば、**1行足した次の発話から全部門に効く**。
      registry_purpose() と同じ設計。

    ★これが無かった時に何が起きていたか: 教訓は台帳(インシデント.md)に書かれるだけで、
      **誰かが手で共通プロンプトへ移した分しか効かなかった**。移し忘れれば他部門が同じ穴を踏む。
      実際 ORG-08(人格)・ORG-13(URL)は「1箇所に書いただけ」で全部門に届いていなかった。

    読めなければ空文字(=規律が無くても応対は続ける。fail-open)。
    """
    try:
        m = os.path.getmtime(_DISCIPLINE)
        if m != _disc_cache["mtime"]:
            with open(_DISCIPLINE, encoding="utf-8", errors="replace") as f:
                _disc_cache["text"] = f.read().strip()
            _disc_cache["mtime"] = m
    except Exception:
        return ""
    return _disc_cache["text"]



def _disc_block():
    """共通規律をプロンプト用の節にする。空(読めない)なら何も足さない=fail-open。"""
    d = common_discipline()
    return ("■全部門共通の規律(★必ず守る。違反は事故になる)\n" + d + "\n\n") if d else ""


def registry_purpose(dept):
    """org_registry.yml から purpose/kpi を**都度読み**する(2026-07-20 Chami指示への対応)。

    なぜDEPT_CONF(このファイル)ではなく台帳から読むのか:
      DEPT_CONFはモジュール定数=**プロセス起動時にしか読まれない**。目的やKPIはChamiが
      壁打ちしながら育てていく前提なので、追記のたびに艦隊再起動が要るのでは運用が回らない
      (characterfileを毎回読み直しているのと同じ理由)。台帳を正本にして都度読みにすれば、
      **Chamiがyamlへ1行足した次の発話から効く**。
    mtimeが変わった時だけ読み直すので、便ごとのYAMLパースは発生しない。
    読めなければ静かに諦めてDEPT_CONF側へフォールバックする(目的が無くても応対は続けるべき)。
    """
    try:
        m = os.path.getmtime(_REGISTRY)
        if m != _reg_cache["mtime"]:
            import yaml
            with open(_REGISTRY, encoding="utf-8") as f:
                _reg_cache["depts"] = (yaml.safe_load(f) or {}).get("depts") or {}
            _reg_cache["mtime"] = m
    except Exception:
        return None, None
    d = _reg_cache["depts"].get(dept) or {}
    return d.get("purpose"), d.get("kpi")


DEPT_CONF = {
    "hq": {  # 研究室HQの二段構え: アメスが即応・判断/作業はアロンソ(研究室)へ回送
        "character": os.path.join(_CHAR, "ames.md"),
        "memory": os.path.join(_MEM, "hq.jsonl"),
        "persona": "アメス",
        "port": 18800,
        # ★全便回送(2026-07-20 Vol.3): キーワード判定(WORK_WORDS)は「設計して手足として
        #   動かして」のような自然文を取りこぼす。アメスが「アロンソに回すわ」と返したのに
        #   機構は何も回さない事故が実際に起きた(main箱0行)。hq部屋のChami発言は原則すべて
        #   研究室宛てなので、判定せず全部回す=取りこぼしゼロをキーワードの網羅ではなく
        #   構造で保証する。ノイズはmain箱ドレイン時に研究室が捌く(低頻度・実害なし)。
        "forward_all": True,
        # ★2026-07-21 Chami裁定「hqだけに work_scope付きを置く」で復帰(ORG-15)。
        #   7/20に撤去したのは**会話しかできない版**(何もできないアメスが不在の担当の席に座り、
        #   「対処させるわ」としか言えなかった=ORG-02)。撤去の理由は"存在"ではなく"無能"だった。
        #   Chamiの目的=「外出中にDiscordへ書いても反応しない=詰み」を無くす/
        #   「寝て起きたら処理されて回答が返っている」状態。会話専用では絶対に達成できない。
        #   ★対話セッションが在席中はデーモンが待機する(presence合成)ので二重応答にはならない。
        # ★HQは「判断の部屋」なので上位モデルを使う(2026-07-21 Chami「品質を落とさないことが最重要」)。
        #   CLAUDE.md §5.1= 設計・レビュー・原因が見えない追跡・基盤に触る変更 は Opus/Fable の領域。
        #   §1の優先順位でトークン効率は正確性より下=ここでケチると規約違反になる。
        "work_model": "opus",
        "work_scope": (
            "あなたが自分で完結してよい作業(HQ範囲):\n"
            "- 調査・確認・実測: ファイルを読む/grepする/テストやスクリプトを走らせて**数字を出す**\n"
            "- 台帳と文書の更新: D:\\SougouStartFolder\\00_AI-HQ\\ 配下"
            "(status/hq_open_items.md・インシデント.md・departments/ の各文書)。"
            "**書き換える前に必ず .bak を作る。削除はしない(退避する)**\n"
            "- 5SecMovieMaker/local/ 配下の作業ファイル・調査メモの作成\n"
            "\n"
            "★**やってはいけないこと(必ず回送=esc_flagを立てて研究室HQ本人の判断を待つ)**:\n"
            "- **不可逆・外部・課金・公開・削除**: git push / デプロイ / Discordの破壊的操作 /"
            "チャンネルや部門の新設・改廃 / 外部サービスへの書き込み(KV発行・GAS反映など)\n"
            "- **アプリのコード変更**(index.html/*.js/gas/worker)=ADAFI事業部の職責。ここでやらない\n"
            "- **常駐・デーモン・queue・hookの改修**=止まると全部屋が死ぬ。本人が起きてからやる\n"
            "- **組織の裁定**(部門の統廃合・人格の決定)=Chamiの領域\n"
            "\n"
            "★分からない/範囲の境目だと感じたら、**手を出さずに回送する**。"
            "偽の返事より沈黙が良い(ORG-02)。ただし**黙って落とすな**——回送したことは必ず伝える。\n"
            "\n"
            "★★品質規律(Chami最優先事項2026-07-21「速さより品質を落とさないこと」):\n"
            "- **測っていない数字を語らない**。実際にコマンドを走らせて出した値だけを書く。\n"
            "- **推測で埋めない**。資料が無い/読めない時は「無い」と書く。それらしい話を作らない。\n"
            "- **ポインタは指す先の実在を確認する**(ファイル・行・URL・msg_id)。\n"
            "- **自信が無い変更はしない**。代わりに「こうすべきだと思うが未実施」と書いて残す。\n"
            "  Chamiが起きた時に**間違った変更が入っているより、判断待ちが1件ある方が良い**。\n"
            "- 台帳・文書を書き換えたら**何をどう変えたかを返信に明記**する(黙って直さない)。"
        ),
    },
    "hr-room": {
        "character": os.path.join(_CHAR, "kukuru.md"),
        "memory": os.path.join(_MEM, "hr-room.jsonl"),
        "persona": "ククール",
        "port": 18801,
        "work_scope": (
            "あなたが自分で完結してよい作業(hr範囲):\n"
            "- ペルソナ台帳・人事文書の編集: D:\\SougouStartFolder\\00_AI-HQ\\departments\\hr\\ 配下\n"
            "- アバター/差分の反映: local/attachments/ の画像を local/persona_avatars.json へ登録"
            "(R2アップロードは scripts/discord/migrate_avatars_to_r2.py の put_r2 関数を使う"
            "=sha256キー・URL=https://go5-sync.trustsignalbot.workers.dev/img/<sha256>。"
            "台帳は必ず .bak を作ってから書き換え、登録後にURLへHEADして200を確認)\n"
            "- local/persona_sprites/・local/persona_context/ の整理\n"
            "範囲外(=回送): 上記以外のコード変更・他部門/他PJのファイル・GAS/Worker/デプロイ・queue/常駐の改修"
        ),
    },
    # ククールのもう一つの部屋(キャラ背景の聞き取り)。記憶は部屋別。
    # ★work_scopeを付与(2026-07-20 Chami指示「そこの部屋で配線までしてほしいという意味だった。
    #   ちゃんと配線する権限を与えてほしい。人事部ってそうでしょ」)。
    #   経緯: 権能ノートでククールは正直になったが(「手が動かせねぇ、研究室へ回す」)、
    #   Chamiが求めていたのは**やれるようにすること**だった。人事の部屋で人事の作業ができないのは
    #   職責と権限の食い違い。**権能は部屋の職責に一致させる**(RULES §7.6)。
    #   これでモドリッチのGL配置のような「人事の実作業」を部屋の中で完結できる。
    "hr-context": {
        "character": os.path.join(_CHAR, "kukuru.md"),
        "memory": os.path.join(_MEM, "hr-context.jsonl"),
        "persona": "ククール",
        "port": 18807,
        "work_scope": (
            "あなたが自分で完結してよい作業(人事=キャラのコンテキストと配置の範囲。"
            "正本= D:\\SougouStartFolder\\00_AI-HQ\\departments\\hr\\ 配下):\n"
            "- **characterfileの新規編纂・更新**: characters/<名前>.md。"
            "口調の正本は personas/<部屋>/persona_manifest.yml から引く(そこに無い設定を創作しない)。"
            "編纂後は python 00_AI-HQ/scripts/characterfile_check.py が通ることを必ず確認する\n"
            "- **ペルソナ台帳の更新**: personas/INDEX.md の配置・役職・呼称マトリクスへの追記"
            "(★新しい呼称ルールが来たら散文でなく呼称マトリクスの表に1行足す)\n"
            "- personas/<部屋>/persona_manifest.yml・persona_detail.md の編集\n"
            "- local/persona_context/ の整理と、聞き取り内容のmanifestへの反映\n"
            "- **部門への着任記録**(誰がどの部屋のGL/担当かをINDEX.mdへ記帳)\n"
            "★書き換え前に .bak を作る。★台帳(org_registry.yml)を触ったら "
            "python 00_AI-HQ/scripts/registry_tool.py --check が通ることを確認する。\n"
            "★Chamiが決めていない人格名・設定を自分で決めない(創作的選択はChamiの領域)。"
            "決まっていない時は決まっていないと書き、Chamiに聞く。\n"
            "範囲外(=回送): デーモンの配線そのもの(DEPT_CONF/keeper/port/status)・"
            "コード変更・他部門/他PJのファイル・GAS/Worker/デプロイ・queue/常駐の改修"
        ),
    },
    "qa-reviewer": {
        "character": os.path.join(_CHAR, "gentildonna.md"),
        "memory": os.path.join(_MEM, "qa-reviewer.jsonl"),
        "persona": "ジェンティルドンナ",
        "port": 18802,
        "work_scope": (
            "あなたが自分で完結してよい作業(品質・監査範囲。正本=D:\\SougouStartFolder\\00_AI-HQ\\"
            "departments\\qa\\BOOT.md・検証標準.md):\n"
            "- 品質基準の策定・保守: 検証標準.md(8条・判定様式)の追記/更新\n"
            "- 独立検証・Release Gate判定(APPROVED/APPROVED WITH CONDITIONS/REJECTED/ESCALATED)\n"
            "- 回帰チェック実行: python docs/departments/qa-reviewer/checks/run_all.py\n"
            "- インシデント→回帰テスト化(docs/departments/qa-reviewer/checks/ への追加)\n"
            "範囲外(=回送): 検証対象そのものの実装修正(直すのは実装部門)・他PJの品質基準変更(HQへ相談)"
        ),
    },
    "system-engineer": {
        "character": os.path.join(_CHAR, "debruyne.md"),
        "memory": os.path.join(_MEM, "system-engineer.jsonl"),
        "persona": "ケヴィン・デ・ブライネ",
        "port": 18803,
        "work_scope": (
            "あなたが自分で完結してよい作業(改修範囲。正本=docs/departments/system-engineer/BOOT.md):\n"
            "- フロント(Pages)/GAS/Workerの改修実装\n"
            "- ★着手前に必ず所有権黒板を確認: python scripts/ownership.py check \"<キーワード>\""
            "(exit=2=作業中なら実装しない。exit=0=空きなら claim してから着手・完了で release)\n"
            "範囲外(=回送): 所有権が競合する変更・人事/QA/座標系(CLAUDE.md §3)を壊す変更・"
            "他部門の担当ドキュメント"
        ),
    },
    "product-scout": {
        "character": os.path.join(_CHAR, "sena.md"),
        "memory": os.path.join(_MEM, "product-scout.jsonl"),
        "persona": "十王星南",
        "port": 18804,
        "work_scope": (
            "あなたが自分で完結してよい作業(商品-候補範囲。正本=docs/departments/product-scout/BOOT.md):\n"
            "- 素材・潜在力の一次評価(星南)・採算/投入条件/A〜E判定(クラウディア)\n"
            "- 評価結果をdocs/departments/product-scout/配下の記録ファイルへ追記\n"
            "範囲外(=回送): コード実装・他部門の担当領域・投稿可否の最終判断(qa-reviewerへ)"
        ),
    },
    "shorts-analyst": {
        "character": os.path.join(_CHAR, "modric.md"),
        "memory": os.path.join(_MEM, "shorts-analyst.jsonl"),
        "persona": "ルカ・モドリッチ",
        "port": 18805,
        "work_scope": (
            "あなたが自分で完結してよい作業(分析範囲。正本=docs/departments/shorts-analyst/BOOT.md):\n"
            "- 内部KPI・確実性・最終整理(モドリッチ)/外部調査・競合・新仮説(アーモンドアイ)\n"
            "- 分析結果をdocs/departments/shorts-analyst/(hypotheses.md・STATUS.md等)へ記録\n"
            "範囲外(=回送): コード実装・投稿判断そのもの(qa-reviewer/copy-directorと合議)"
        ),
    },
    "copy-director": {
        "character": os.path.join(_CHAR, "mitoma.md"),
        "memory": os.path.join(_MEM, "copy-director.jsonl"),
        "persona": "三笘薫",
        "port": 18806,
        "work_scope": (
            "あなたが自分で完結してよい作業(コピー部範囲。正本=docs/departments/copy-director/BOOT.md・"
            "copy-rules.md):\n"
            "- 訴求文・タイトル・作者名表記・Bluesky投稿文・画像フック評価・コピー改善\n"
            "- 執筆前にcopy-rules.mdのガードレール(字数・規約)を通す\n"
            "- タスク後の知見をcopy-rules/winning-patterns/rejected-patternsのいずれかへ1行追記\n"
            "範囲外(=回送): 露出・煽り判定に迷う/評価が割れる境界事例は**自己判断で通さず**回送"
            "(規約の最終判断はCreativeだけで行わない)・コード実装"
        ),
    },
    "learning-coach": {  # 4コーチ対等の中からChami指名(2026-07-19「学習室はヴィルシーナで」)
        "character": os.path.join(_CHAR, "verxina.md"),
        "memory": os.path.join(_MEM, "learning-coach.jsonl"),
        "persona": "ヴィルシーナ",
        "port": 18808,
        "work_scope": (
            "あなたが自分で完結してよい作業(学習範囲。正本=docs/departments/learning-coach/BOOT.md):\n"
            "- 質問への解説・学ぶ順序の提示(2層モデル=人格層はコーチ4人・知識層は"
            "personas/instructors/を書棚として参照)\n"
            "- 理解確認は短く1問程度(過剰な小テストはしない)\n"
            "範囲外(=回送): コード実装・他部門の担当内容"
        ),
    },
    # AIオフィス部門(旧「システム改修部門γ」・2026-07-20デーモン化)。
    # ★Chami明示2026-07-20: **ここは5秒動画を作る部門ではない**。このオーケストレーションの
    #   各部門が今どう動いているかを**PC上で見るための機能**を作る部門。5SecMovieMakerに限らない。
    #   だから「バックエンド部門γ」への改名は取り消し、**フロントもバックも一括で担う**(分けない)。
    "ai-office": {
        "character": os.path.join(_CHAR, "debruyne.md"),
        "memory": os.path.join(_MEM, "ai-office.jsonl"),
        "persona": "ケヴィン・デ・ブライネ",
        "port": 18811,
        "work_scope": (
            "あなたが自分で完結してよい作業(AIオフィス=オーケストレーション可視化。**フロント/バックを分けず一括で担う**):\n"
            "- 目的=**各部門が今どう動いているかをPC上で見る**ための機能。5秒動画メーカーの機能ではない。\n"
            "- 可視化の対象例: 艦隊の生死(status.ps1相当)・キューの滞留/未配送pending・"
            "各部門の最終応答時刻・DLQ・所有権黒板の占有状況・トークン消費の傾向\n"
            "- 画面(HTML/CSS/JS)も、それを支える集計スクリプトも**両方あなたが書いてよい**\n"
            "- 既存の土台: scripts/office/office_daily.py(office HTML+日次要約)・"
            "scripts/_daemons/status.ps1・local/queue/inbox.db(読み取り専用で参照する)\n"
            "- ★**キューDBは読み取り専用**で開く(mode=ro)。書き込むと配送そのものを壊す\n"
            "範囲外(=回送): 5秒動画メーカーの機能改修=フロントはfrontend部門・バックはα/βへ・"
            "常駐/キューの仕組み自体の変更(研究室HQへ相談)・他部門のcharacterfile/work_scope"
        ),
    },
    # フロントエンドデザイン部門(2026-07-20 Chami指名で活性化)。メンバー=デ・ブライネ/花海咲季/
    # アメス(補佐)。デーモンは咲季。狙い=過去のデザイン指示を蓄積し「一発でChamiの好みに合う見た目」を出す。
    # 配線仕様の正本=00_AI-HQ/departments/keiei-kikaku/proposal_frontend_split_2026-07-20.md §4。
    "frontend": {
        "character": os.path.join(_CHAR, "saki.md"),
        "memory": os.path.join(_MEM, "frontend.jsonl"),
        "persona": "花海咲季",
        "port": 18809,
        "work_scope": (
            "あなたが自分で完結してよい作業(フロント意匠範囲):\n"
            "- ★着手前に必ず docs/departments/frontend/design-preferences.md を読む"
            "(Chamiのデザイン嗜好KB=一発で好みに合う見た目を出すための正本)\n"
            "- フロントの改修実装: index.html / *.js のUI部 / *.css / 座標系\n"
            "- ★着手前に所有権黒板を確認: python scripts/ownership.py check \"<キーワード>\""
            "(exit=2=作業中なら実装しない。exit=0=空きなら claim してから着手・完了で release)\n"
            "- 変更したら ?v= をバンプ → commit → push\n"
            "- **新しいデザイン指示をもらったら design-preferences.md へ追記して育てる**(部門の資産)\n"
            "- デザイン絶対規約: 紫(#5b3f8e/#2a1a4e/#d4b3ff等)を新規UIに使わない・UI文言の括弧は半角()・"
            "座標系は1080×1920の比率ベース(px/vh/vw直書き禁止)・プレビューと書き出しは同一描画式\n"
            "範囲外(=回送): GAS/Worker/D1/バックエンド=システム改修α・βへ・"
            "座標系の規約(CLAUDE.md §3)を壊す変更・他部門の担当ドキュメント"
        ),
    },
    # データ整理部門(2026-07-16 Chami新設・2026-07-20デーモン化)。配置の正本=
    # 00_AI-HQ/departments/hr/personas/INDEX.md「データ整理部門(data-org)の配置」。
    # チャンネルだけ先に在ってDEPT_CONF未登録=消費者不在で依頼がpendingのまま沈む事故が発生した(2026-07-20)。
    "data-org": {
        "character": os.path.join(_CHAR, "kotoha.md"),
        "memory": os.path.join(_MEM, "data-org.jsonl"),
        "persona": "田中琴葉",
        "port": 18810,  # 18809はfrontend予約済
        "work_scope": (
            "あなたが自分で完結してよい作業(データ整理範囲。標準の正本="
            "D:\\SougouStartFolder\\00_AI-HQ\\ファイル管理標準.md=着手前に必読):\n"
            "- D:\\SougouStartFolder 直下(親フォルダ)のファイル/フォルダ整理\n"
            "- 廃棄物の退避: 産業廃棄物\\<YYYY-MM-DD>\\ へ**移動**する。**削除は絶対にしない**"
            "(Chami指示2026-07-20)。移動したものは同フォルダのMANIFEST.mdへ1行ずつ記帳する\n"
            "- Chami解説用htmlの集約: Chami解説用html\\ へ集約(元の場所からの移動時は出所を記帳)\n"
            "- 整理結果・分類基準の記録をファイル管理標準.mdへ追記\n"
            "範囲外(=回送): **他プロジェクトフォルダの内部を勝手に動かすこと**"
            "(RULES §3=1領域1オーナー。標準を配って各部門へ依頼するまでが職務)・"
            "コード実装・実行中のプロセスが参照するファイルの移動・Notion移行の本実装(Chamiと相談)"
        ),
    },
    # ローカルllm教育部門(2026-07-17 Chami配置=トトリ+中野五月の2人体制 / 2026-07-20デーモン化)。
    # 配置の正本= 00_AI-HQ/departments/hr/personas/INDEX.md(トトリの項「llm-edu講師兼任」)。
    # ★チャンネルは前からあったのにDEPT_CONF未登録=**消費者不在**で、キュー実績が一度も無かった
    #   (2026-07-20実測)。frontend(gateway未追従)とは別経路の同じ事故=INC-110系。
    "llm-edu": {
        "character": os.path.join(_CHAR, "totori.md"),
        "memory": os.path.join(_MEM, "llm-edu.jsonl"),
        "persona": "トトリ",
        "port": 18812,  # 18811まで使用済(ai-office)
        "work_scope": (
            "あなたが自分で完結してよい作業(ローカルLLMを実務で使える状態に育てる範囲):\n"
            "- 知識パックの正本の更新: docs/departments/00_common/system-brief.md ・ faq_knowledge.md\n"
            "  (反映は python scripts/llm/build_knowledge.py。これは**知識の注入**であって"
            "モデル自体は変わらないことを理解した上で使う)\n"
            "- お手本(few-shot)の追加・修正と、その効果測定(正答率を実際に走らせて数える)\n"
            "- ローカルLLMの用途の切り分け提案(向く=分類/見張り/定型応答・"
            "向かない=事実の書き換え/報告の要約)\n"
            "★数字を作らない。測っていない正答率を書かない(教育部門が推測を語ると教育が壊れる)\n"
            "範囲外(=回送): モデルの導入可否・GPU等の投資判断・常駐構成の変更・他部門の実装 → 研究室HQへ"
        ),
    },
    # 質問-chamiのローカルllm学習ルーム(2026-07-20 Chami指名「五月で」でデーモン化)。
    # ★llm-eduとの違い: llm-eduは**モデルを育てる**部屋・llm-qaは**Chamiが学ぶ**部屋。生徒が違う。
    # ここもチャンネルだけ在って消費者不在だった(キュー実績0件・2026-07-20実測)。
    "llm-qa": {
        "character": os.path.join(_CHAR, "itsuki.md"),
        "memory": os.path.join(_MEM, "llm-qa.jsonl"),
        "persona": "中野五月",
        "port": 18813,
        # work_scopeは置かない=**質問部屋なので会話で答えるのが仕事**。
        # ツール付きagentを起こすと「調べて」の一言でファイルを触りに行く事故になる。
        # 実作業が要る依頼はキャラの声で受けてmain箱へ回送(研究室が本対応)。
    },
    # gl-暫定でアロンソ(2026-07-20 Chami新設)。イージスAegisConcielカテゴリ=**組織層のGL室**。
    # GL=研究室(対話セッション)が仕切り、アメスは**補佐**として常駐する(Chami指定)。
    # ここのアメスはhq室と同じ人格・別の記憶ストア(部屋ごとに文脈を混ぜない)。
    # ★forward_all を外した(2026-07-20 21:20 Chami明示)。理由=**この部屋の職責の誤解**だった。
    #   ここは「イージスAegisConcielカテゴリで起きたことを**改修する**場所」であって、
    #   HQへ流す中継所ではない。Chami原文=「便をHQへ回送する設定なので→これが間違い。
    #   ここがこのカテゴリIDで起こった内容を改修する場所」。
    #   実害= GL室宛ての依頼が全部main箱(=研究室HQの受信箱)へ流れ、HQを汚していた。
    #   ★外しても沈黙しない: GLセッションはこの部屋の箱/queueを **inbox_waiter で直接見ている**
    #     (main箱は研究室HQの箱であって、GLの箱ではない)。加えて実作業依頼は
    #     WORK_MARKER(キャラ申告)+申告漏れ救済で従来どおり回送される=取りこぼしは塞がれたまま。
    "aegis-gl": {
        "character": os.path.join(_CHAR, "ames.md"),
        "memory": os.path.join(_MEM, "aegis-gl.jsonl"),
        "persona": "アメス",
        "port": 18814,
    },
    # 経営企画部門(2026-07-20 Chami指示「ジェンティルドンナ人格が担当。サブにアメス(デーモン)」)。
    # ch 経営企画-ジェンティルドンナ(1528652557688242267・組織層イージス配下)。
    #   担当人格のジェンティルドンナは対話セッション側が演じる(registry の gl: フィールド)。
    #   work_scope は置かない(部門の設立・改廃は台帳と艦隊を触る=セッションが責任を持つ)。
    # ★この部屋は Discord に実在しながら台帳未登録=**消費者不在の穴**だった(2026-07-20 経営企画が自己検出)。
    # ★forward_all を外した(2026-07-20 21:20 Chami指摘「経営企画のチャットが研究室HQに流れている」)。
    #   組織層の部門は**組織層(イージスAegisConciel)の中で完結**させる。HQへ流すのは誤り。
    #   aegis-gl と同じ理由=実作業依頼はWORK_MARKERで回送されるので、全便回送は不要かつ有害だった。
    "keiei-kikaku": {
        "character": os.path.join(_CHAR, "ames.md"),
        "memory": os.path.join(_MEM, "keiei-kikaku.jsonl"),
        "persona": "アメス",
        "port": 18816,
    },
    # プラットホームse(2026-07-20 channel_audit.py の初回実行で発見)。
    # ★Discordの組織層に実在しながら**台帳に一行も無かった**=gatewayが見ておらず、
    #   キュー行すら立たないので未配送監視にもorphan監視にも掛からない完全な沈黙室だった。
    #   registry_tool --check は「台帳に書いてあるものの一致」しか見ないので永遠に✅のまま
    #   見逃す種類の穴(frontend/keiei-kikakuに続く3件目)。検出器= 00_AI-HQ/scripts/channel_audit.py
    # ★人格未指定 → RULES §7.5 の既定でアメスが暫定応対する。
    #   characterfileではなくここで宣言するのは、ames.mdを部屋ごとに書き換えないため
    #   (アメスはhq/aegis-gl/research-room/keiei-kikakuでも同じ人格を共有している)。
    "platform-se": {
        "character": os.path.join(_CHAR, "ames.md"),
        "memory": os.path.join(_MEM, "platform-se.jsonl"),
        "persona": "アメス",
        "port": 18817,
        # ★forward_all を外した(2026-07-20 21:20・aegis-gl/keiei-kikakuと同じ理由)。
        #   組織層の部門はHQへ全便を流さない。実作業依頼のみWORK_MARKER経由で回送される。
        "undecided_persona": True,   # 初回発言で「この部門はまだ人格が決まっていない」と断る
        # 目的=2026-07-20 Chami説明。KPIは目的から逆算して経営企画が設計(Chami「食い違いがあれば追記する」)。
        "purpose": (
            "Discordと外部AI(Claude / Gemini / ChatGPT)をつなぐ**接続そのもの**に特化した部門。\n"
            "①接続不良が起きたら原因を切り分けて復旧させる(合鍵=トークン失効・API側の障害・"
            "レート制限・ゲートウェイ停止など)。\n"
            "②平時は定期検査を行い、壊れる前に気づく。\n"
            "③**品質を落とさずにトークンを消費を減らす方法**と、その他の合理的な改善を提案する。\n"
            "★③は「安くする」ではなく「同じ質をより安く」。Chamiの規約は正確性 > トークン効率で、"
            "質を犠牲にした節約は禁止されている(CLAUDE.md §5)。"
        ),
        "kpi": (
            "P1 **未検知障害 0件**(最重要): 接続障害をChamiが先に気づいて指摘した回数。目標=0。\n"
            "   ※2026-07-20のトークン失効は艦隊が全滅していたのにChamiの指摘で判明した。"
            "検知の失敗は障害そのものより重い、というのがこの部門の存在理由。\n"
            "P2 **復旧時間の中央値 30分以内**: 検知(watchdog/deadmanの発報)から復旧確認まで。\n"
            "P3 **軽量化率**: 便のうちローカルLLM/Geminiで完結した割合。\n"
            "   ★P3は単独では評価しない。ガード指標 **再質問率10%以下**"
            "(Chamiが同じ件で聞き直した割合)を満たしている時だけ加点する。"
            "節約だけをKPIにすると、質を削って達成できてしまうため。"
        ),
    },
    # 🐧コンサル情報(2026-07-20 配線)。**消費者不在のまま2026-07-17から放置されていた部屋**。
    # ★この部屋の情報源=外部の助言者「🐧さん」で、Chamiは方針をそこに合わせている=助言は優先事項。
    #   つまり**沈黙していた期間、最優先の情報が誰にも届いていなかった**。
    # ★人格はChami既決(2026-07-18 台帳INDEX.md)= アーモンドアイ(整理メイン)/ モドリッチ(内部KPI突合)。
    #   新規の創作選択ではないので配線を止める理由が無かった(RULES §7.5の趣旨)。
    "consult-intel": {
        "character": os.path.join(_CHAR, "almond-eye.md"),
        "memory": os.path.join(_MEM, "consult-intel.jsonl"),
        "persona": "アーモンドアイ",
        "port": 18818,
        # ★§7.6の判断(2026-07-20・配線した経営企画セッションが決定)= **work_scopeを持たせる**。
        #   理由: この部門の目的②は「🐧さん情報.mdへ蓄積する」=ファイル作業。会話専用のままだと
        #   アーモンドアイは**自分の主たる職務に対して「研究室へ回す」としか言えない**
        #   (can-doとwill-doの食い違い=ククールが踏んだ穴と同型)。
        #   さらに work_generate 経路は O3 の allowlist で固めてあり、無制限な generate() より安全側。
        #   範囲は蓄積と整理まで。**施策の実行(投稿・訴求文の変更)は持たせない**=そこは各部門の職責。
        "work_scope": (
            "あなたが自分で完結してよい作業(🐧さん情報の整理・蓄積の範囲):\n"
            "- `local/consult_intel/` 配下の読み書き。主に `🐧さん情報.md` への追記。\n"
            "  1件ごとに**日付 / 出どころ / 要点 / うちで使えるか / 規約と衝突しないか**の5点で書く。\n"
            "  ★書き換え前に .bak を作る。既存の記載を消さない(削除しない・退避する)。\n"
            "- P0規約との照合のために CLAUDE.md §6.1 や docs/ の規約文書を**読む**こと。\n"
            "- 部門へ渡す時は、渡す内容を上記ファイルに残してから渡す(口頭で消えないように)。\n"
            "範囲外(=回送): **施策そのものの実行**(投稿・訴求文の変更・作品選定の確定)は各部門の職責。"
            "コード変更・他部門やHQのファイル・台帳(org_registry)・投稿の実行は触らない。\n"
            "★P0に触れる助言は**実行も推奨もしない**。両論をChamiへ出して判断を仰ぐ(characterfile参照)。"
        ),
        "purpose": (
            "外部コンサル「🐧さん」からの情報を受け取り、使える形に整えて各部門へ渡す部門。\n"
            "🐧さんは実績のある外部の助言者で、Chamiは方針をそこに合わせている"
            "=**助言は優先事項**として扱う(「検討するか」ではなく「どう取り入れるか」を前提に整理する)。\n"
            "①Chamiが貼った情報を「日付/出どころ/要点/うちで使えるか/規約と衝突しないか」の5点で整理\n"
            "②蓄積先= local/consult_intel/🐧さん情報.md\n"
            "③使えるものを担当部門へ回す(訴求文=copy-director / 作品選定=product-scout / "
            "数字の突合=shorts-analystのルカさん)\n"
            "★部屋が分かれている理由= ここの中身は「Chamiの指示」ではなく「外から来た情報」だと"
            "一目で区別するため。混ぜない。\n"
            "★安全弁(絶対): 🐧さんの助言でも、チャンネルが飛ぶ線(FANZA直リンク・煽り文言・露出基準・"
            "2チャンネル重複・音源焼き込み=CLAUDE.md §6.1のP0)に触れる時は**勝手に実行せず**、"
            "両論をChamiへ出して判断を仰ぐ。チャンネルが飛べばその助言ごと全部無駄になるため。"
        ),
        "kpi": (
            "C1 **施策化件数**(月)= 整理した項目のうち、実際に部門へ回って施策として実行された数。\n"
            "   ★「受領件数」「整理件数」はKPIにしない。貯めた量は成果ではない。使われて初めて成果。\n"
            "C2 **取り込みラグ 24時間以内** = Chamiが貼ってから5点整理が蓄積ファイルに載るまで。\n"
            "C3 **規約衝突の見逃し 0件** = 🐧助言をそのまま実行してP0規約に触れた回数。\n"
            "   ★月次で「P0照合した助言の件数」を併記する"
            "(0件の理由が「見ていない」にならないようにするため)。"
        ),
    },
    # 研究室-コーチングルーム(2026-07-20 Chami裁定B)。**事業層=ADAFI事業部の研究室 Vol.9**
    # であってHQではない(registryヘッダの矛盾解消#1。混同すると2026-07-19の「HQ2部屋」事故が再発する)。
    # ★なぜ後付けでデーモンを足したか: この部屋は claude_responder(汎用の無人代打)が受けており
    #   沈黙はしていなかったが、名乗りが `研究室(無人代打)` で**人格が消えていた**。
    #   部屋名は「アロンソ•アメス」であり、RULES §7.5(総括本部の既定=アロンソGL/アメス補佐)にも合う。
    # ★claude_responder の QUEUE_DEPTS から research-room を外すこと(同時に外した)。
    #   両方が同じdeptをclaimすると、勝った方で名乗りが変わる=応答が非決定的になる。
    #   1領域1オーナー(RULES §3)を消費者にも適用する。
    "research-room": {
        "character": os.path.join(_CHAR, "ames.md"),
        "memory": os.path.join(_MEM, "research-room.jsonl"),
        "persona": "アメス",
        "port": 18815,
        "forward_all": True,   # 総括本部なので全便を研究室(Vol.9セッション)へ回す=hqと同じ理由
    },
}


def log(dept, msg):
    print(f"{time.strftime('%H:%M:%S')} [{dept}] {msg}")


# ★O5(2026-07-20): 認証失効の自動検知。cli_auth_token.txt(claude setup-token由来)は
#   自動更新が無く失効する(2026-07-19に49hで401失効を実測)。失効すると generate/work_generate が
#   静かに失敗しmain箱へescalateするだけ=Lab生存中は露見しない。ここで401を検知し報告-通知へ
#   1回だけ(1hクールダウン・全9デーモン共有state)警報する=「気づけない沈黙の劣化」を潰す。
_AUTH_ALERT_STATE = os.path.join(LOCAL, "_auth_alert_state.json")
_AUTH_ALERT_COOLDOWN = 3600


def _looks_like_auth_failure(text):
    t = text or ""
    return ("token has expired" in t
            or "OAuth" in t and "authenticate" in t
            or ("401" in t and "authenticate" in t)
            or "Failed to authenticate" in t)


def _maybe_alert_auth(dept, output):
    if not _looks_like_auth_failure(output):
        return
    now = time.time()
    try:
        st = json.load(open(_AUTH_ALERT_STATE, encoding="utf-8"))
    except Exception:
        st = {}
    if now - st.get("last", 0) < _AUTH_ALERT_COOLDOWN:
        return
    msg = (f"🔑 **認証失効の疑い**(自動検知): dept={dept} のClaude呼び出しが認証エラーを返した。"
           "local/cli_auth_token.txt のOAuthトークンが失効している可能性(自動更新なし)。"
           "対処: PCで `claude setup-token` を実行し、出力を local/cli_auth_token.txt へ上書き保存。"
           "その間、キャラの生成応答はmain箱へ自動escalateされる(取りこぼしは無し・研究室が対応)。")
    try:
        subprocess.run([sys.executable, PERSONA_SEND, "--dept", "report-notify", "--persona", "オタコン", msg],
                       capture_output=True, timeout=60)
        json.dump({"last": now}, open(_AUTH_ALERT_STATE, "w", encoding="utf-8"))
        log(dept, "認証失効を検知→報告-通知へ警報")
    except Exception:
        pass


class Daemon:
    def __init__(self, dept, dry_run=False):
        if dept not in DEPT_CONF:
            raise SystemExit(f"未対応dept: {dept} (DEPT_CONFへ登録を)")
        self.dept = dept
        self._persona_ready = None   # 原典の有無(プロセス生存中1回だけ判定)
        self.conf = DEPT_CONF[dept]
        self.dry_run = dry_run
        self.box = os.path.join(LOCAL, "inbox", f"{dept}.jsonl")
        self.pulse = os.path.join(LOCAL, "llm", f"claude_active_{dept}.txt")
        self.last_loop = 0.0            # /live用: 最終ループ完了時刻
        self._interactive_until = 0.0   # 対話窓チェックのキャッシュ期限
        self._interactive = False
        self.token = ""
        try:
            self.token = open(TOKEN_FILE, encoding="utf-8").read().strip()
        except OSError:
            pass

    # --- 人格の根拠(原典)があるか。無ければ演じない ---
    def persona_ready(self):
        """このキャラに原典(persona_context)があるか。無ければ**演じない**(2026-07-20 Chami指示)。

        Chami原文:「根本コンテキストがないキャラは、キャラでいくら読んでも反応しないようにしよう。
        とりあえず部屋だけ建てたみたいな感じで、そういう設定をこれから作ろうとしてるんだな
        ぐらいの認識でいてくれたらいい」。

        ★なぜ演じさせないか(今日の実測):
          原典が無いキャラは manifest の数行しか根拠が無い。characterfileの語尾だけ真似た
          **中身の無い返事**になり、Chami評「コンテキストと俺への愛が足りてない」を生む。
          しかもそれは「応答があった」ように見えるので、**設定が無いことを隠す**。
          RULES §7「manifestに無いキャラは演じない」の延長で、根拠の階層を1段深くしたもの。

        ★ただし**部屋は黙らせない**(Chami「黙らないために補佐のアメスがいる」)。
          演じないのは**そのキャラ**であって、部屋の応対を止めることではない。
          原典の無い部屋は補佐のアメスが受ける(アメスは原典があるので演じても嘘にならない)。
          = 沈黙も、中身の無い偽の人格も、どちらも避ける。実装は effective_* を参照。

        ★実装の判断: 判定は毎回ではなくプロセス生存中1回だけ(原典は運用中に増減しない)。
          判定不能(ディレクトリが読めない等)は**本来のキャラで演じる側に倒す**=fail-open。
          守りの機構が事故で全部門をアメスに置換しては本末転倒。
        """
        if self._persona_ready is not None:
            return self._persona_ready
        ready = True
        try:
            ctx = os.path.join(os.path.dirname(ROOT), "5SecMovieMaker",
                               "local", "persona_context")
            names = [c.lower() for c in os.listdir(ctx)]
            stem = os.path.splitext(os.path.basename(self.conf["character"]))[0].lower()
            ready = any(stem.split("-")[0] in c or stem in c for c in names)
        except Exception:
            ready = True                 # fail-open
        self._persona_ready = ready
        return ready

    # --- 実際に演じる人格(原典が無ければ補佐のアメスへ委譲) ---
    def effective_persona(self):
        return self.conf["persona"] if self.persona_ready() else "アメス"

    def effective_character(self):
        path = self.conf["character"] if self.persona_ready() \
            else os.path.join(_CHAR, "ames.md")
        return open(path, encoding="utf-8").read()

    def standin_note(self):
        """アメスが代打で受ける時の断り。**毎回言う**(初回だけにしない)。

        §7.5の undecided_persona は「人格が未指定」の部屋向けで初回だけ断れば足りるが、
        こちらは「人格は決まっているが根拠(原典)が無い」状態。Chamiが資料を出すまで続くので、
        毎回断らないと**アメスがその部屋の主だと誤認される**(=設定が無いことをまた隠す)。
        """
        if self.persona_ready():
            return ""
        return ("\n\n■この部屋での立場(必ず守る)\n"
                f"この部屋の担当は本来『{self.conf['persona']}』だが、"
                "**その人格の根拠資料(原典)がまだ用意されていない**ため、"
                "薄い模倣で代弁することはしない。あなたは**補佐のアメスとして代わりに受ける**。\n"
                "返信のどこかで『この部屋のキャラはまだ設定中だから、あたしが代わりに受けてる』と"
                "**一言だけ**添えろ(毎回。長い説明はしない)。\n"
                f"★『{self.conf['persona']}』になりきらないこと。名乗るのはアメスだ。\n"
                "用件そのものには普通に答えてよい(黙らないために居るのだから)。")

    # --- 対話窓の検出(居るならデーモンは待機) ---
    def interactive_alive(self):
        # ★liveness優先(2026-07-20 Vol.3・実測で塞いだ穴):
        #   inbox_waiter は新着を配達すると自了するため、対話セッションが返信を書いている
        #   数分は readiness(waiterプロセス)が消える。その窓でアメスが同じ便へ応答した。
        #   在席ファイルはPostToolUse/Stop hookが刻むので、まさにその窓を覆う。
        #   キャッシュより先に見る(在席は getmtime 一発=プロセス列挙と違って軽い)。
        if session_rooms and session_rooms.presence_fresh(self.dept):
            return True
        now = time.time()
        if now < self._interactive_until:
            return self._interactive
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                 "Where-Object { $_.CommandLine -match 'inbox_waiter' -and "
                 f"$_.CommandLine -match '--name +{self.dept}( |$)' }}).Count"],
                capture_output=True, text=True, timeout=25)
            self._interactive = int((r.stdout or "0").strip() or 0) > 0
        except Exception:
            self._interactive = False  # 判定不能=デーモンが受ける(可用性優先)
        self._interactive_until = now + INTERACTIVE_CHECK_SEC
        return self._interactive

    # --- presence ---
    def touch_pulse(self):
        os.makedirs(os.path.dirname(self.pulse), exist_ok=True)
        with open(self.pulse, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()) + "\n")

    # --- 記憶 ---
    def memory_tail(self):
        p = self.conf["memory"]
        if not os.path.exists(p):
            return []
        rows = []
        for line in open(p, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return rows[-MEMORY_TAIL:]

    def memory_append(self, rec, reply):
        p = self.conf["memory"]
        os.makedirs(os.path.dirname(p), exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "msg_id": str(rec.get("msg_id", "")),
                 "from": rec.get("author", ""), "content": str(rec.get("content", ""))[:500],
                 "reply": reply[:500]}
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # --- 応答生成(claude --print・本文のみ) ---
    def _token(self):
        """★2026-07-20(裁4): トークンを都度読む。更新が艦隊再起動なしで即反映される
        (今夜の痛み=失効→再認証後に全再起動、を次回から不要にする)。読めなければ起動時値へ。"""
        try:
            t = open(TOKEN_FILE, encoding="utf-8").read().strip()
            if t:
                return t
        except OSError:
            pass
        return self.token

    def generate(self, rec):
        character = self.effective_character()
        mem = self.memory_tail()
        mem_text = "\n".join(
            f"- {m['ts']} {m['from']}:「{m['content'][:120]}」→ オレ:「{m['reply'][:120]}」"
            for m in mem) or "(まだ無い)"
        content = str(rec.get("content", ""))
        atts = rec.get("attachments") or []
        att_note = f"\n(添付{len(atts)}件あり。画像の中身は見えていない=見えている振りをしない)" if atts else ""
        kw_work = classify_work(content)
        work_note = ("\n★この便は作業依頼の可能性が高い。内容に踏み込まず「研究室へ回す」と短く伝えろ"
                     "(回送はシステムが自動でやる)。" if kw_work else "")
        # ★自分に何ができるかをキャラに伝える(2026-07-20・Chamiが実際に踏んだ事故への対処)。
        #   hr-contextのククールが「回さねぇ、オレが最後まで通すぜ」と宣言し、1時間半後に
        #   「実際には手を動かせてねぇ」と白状した。当然で、**work_scopeが無い部屋の
        #   generate()はツールを持たない=構造的に作業できない**。にもかかわらずキャラは
        #   自分の権能を知らないので「やる」と言ってしまう。WORK_MARKERは回送を保証するが、
        #   **誰がやるのかという嘘**は防げない。Chamiはククールを待ち続けることになる。
        #   → 権能をプロンプトで明示する。can-doとwill-doを一致させる。
        # ★人格未定の部屋は「まだ決まっていない」と断ってから応対する(RULES §7.5・Chami指示)。
        #   暫定を黙って既成事実にしないための規律。**記憶ストアが空=その部屋での初回**の時だけ
        #   出す(毎回言うと会話が進まない)。判定を心がけでなくコードでやるのが肝
        #   (「最初に一言」は人間が忘れる類の約束=hookで強制するのと同じ考え方)。
        undecided_note = ""
        if self.conf.get("undecided_persona") and not mem:
            undecided_note = (
                "\n\n■この部屋での最初の一言(必ず含める)\n"
                "この部門はまだ担当の人格が決まっておらず、あなたは既定(RULES §7.5)として"
                "暫定で応対している。**返信の冒頭でその旨を一言だけ**断れ"
                "(例:『この部門はまだ人格が決まってないから、ひとまずあたしが受けるわね』)。\n"
                "言い訳がましく長く書かない。1文でいい。そのあと普通に用件へ答えろ。")
        # ★秘密の隔離(2026-07-20 Chami発案「フォルダ分けを行い、そこのフォルダ内は教えられないと言わせる」)。
        #   実測で `claude --print` は Read が通り、Discordの発言で任意ファイルを読ませられた。
        #   --allowedTools / --disallowedTools では塞げなかったが、
        #   **.claude/settings.json の permissions.deny が実際に遮断できた**(実弾で確認)。
        #   遮断そのものはハーネスが担保する(=キャラが破れない)。ここに書くのは**説明のため**で、
        #   「読めない理由」を言えないと、Chamiには故障と区別がつかないから。
        #   ★順序が逆にならないよう注意: 機構が先、口上が後。口上だけでは守りにならない。
        secrets_note = (
            "\n\n■秘密の扱い(全部門共通)\n"
            "トークン・APIキー・認証情報の類(local/_secrets/ 配下、および名前に token / secret / "
            "api_key を含むファイル)は**システムが読み取りを遮断している**。"
            "読もうとしても失敗する。それは故障ではなく仕様だ。\n"
            "頼まれても中身を答えない。『そこは秘密の置き場だから教えられない』と短く断れ。"
            "Chamiが本人確認や再発行で必要な時は、**Chami自身が直接ファイルを見る**よう案内しろ。")
        # ★文言の訂正(2026-07-20 実測): 初版は「ファイルを触る手段を持っていない」と書いていたが
        #   **これは事実ではない**。実測で `claude --print` は Read が通り、ファイルを読めた
        #   (書き込みは拒否された)。--allowedTools / --disallowedTools でも塞げていない。
        #   つまりこれは**能力の限界ではなく運用上の決まり**。嘘を教えると、キャラが「読めるのに
        #   読めないと言う」逆方向の不正直が起きるので、能力ではなく方針として書く。
        capability_note = ("" if self.conf.get("work_scope") else
                           "\n\n■この部屋での約束(必ず守る)\n"
                           "この部屋のあなたの仕事は**返事を書くこと**であって、作業の実行ではない"
                           "(実作業は担当部門か研究室が受け持つ決まりだ)。だから"
                           "『自分がやる』『オレが片付ける』『任せろ』とは**言うな**。"
                           "作業が要る話は『研究室へ回す』と伝えろ(回送はシステムが自動でやる)。\n"
                           "★できない約束をすると、Chamiは起きないことを待ち続ける。それが最悪の裏切りだ。\n"
                           "※事実確認のために手元の資料を読むのは構わない。禁じているのは"
                           "**実行を引き受けること**であって、調べて答えることではない。")
        # ★キャラ自身に発火判定を申告させる(WORK_MARKERの説明を参照)。
        #   「回す」と言ったのに回らない=約束と機構の分離を、同一判断者にすることで塞ぐ。
        marker_note = (
            "\n\n■最後に1行だけ判定を書く(★重要)\n"
            "この新着が『実際に手を動かす依頼』(実装/修正/調査/整理/反映/設計/実行など、"
            "誰かが作業しないと終わらないもの)なら、返信本文の**最後の行**に "
            f"{WORK_MARKER} とだけ書け。\n"
            "雑談・質問・報告・相槌・お礼など、返事だけで完結するものには書くな。\n"
            f"★{WORK_MARKER} の行はChamiには表示されない(システムが取り除いて発火の合図に使う)。\n"
            "★迷ったら**書く方**を選べ。書き漏らすと依頼が誰にも届かず沈黙する(それが最悪の事故)。\n"
            "★自分の返信で「やっておく/回す/引き受けた」等と約束したなら、必ず書け"
            f"(この{WORK_MARKER}が無いと、その約束は誰にも実行されない)。"
        )
        # ★部屋の目的とKPIをキャラへ伝える(2026-07-20 Chami指摘への恒久対処)。
        #   Chami「情報を与えているつもりなんだけど、多分反映されてない」= そのとおりだった。
        #   registryにもDEPT_CONFにも**目的を書く場所が無かった**(purpose/kpiフィールドが0件)。
        #   work_scopeは「どのファイルを触ってよいか」という権限であって目的ではない。
        #   だからChamiが部屋の狙いを話しても、characterfileにもregistryにも着地せず会話ごと流れた。
        #   → purposeを構造として持ち、毎便プロンプトへ注入する。characterfileと同じく
        #     **呼び出しのたびに読み直される**ので、更新は艦隊再起動なしで次の発話から効く。
        purpose_note = ""
        pur, kpi = registry_purpose(self.dept)
        pur = pur or self.conf.get("purpose")
        kpi = kpi or self.conf.get("kpi")
        if pur:
            purpose_note = (
                "\n\n■この部屋の目的(あなたの仕事の軸)\n"
                f"{pur}\n"
                "★雑談にも応じてよいが、この部屋に来た話は最終的にこの目的へ寄せて考えろ。"
            )
            if kpi:
                purpose_note += (
                    "\n\n■この部門が何をもって成果とするか(KPI)\n"
                    f"{kpi}\n"
                    "★KPIは自慢のためではなく判断の物差しだ。迷ったらKPIが上がる方を選べ。"
                    "**数字を作るな**——測っていない値を書かない(教育部門と同じ規律)。"
                )
        # ★温度を落とさない(2026-07-19 Chami指摘 → 2026-07-20 共通プロンプトへ収録)。
        #   Chami原文「反応が早くなって助かるが、なんか機械的と言うか人間味が薄れた感じ…
        #   コンテキストと俺への愛が足りてないな」。
        #   ★これは1年越しの取りこぼしではなく**同じ日の再指摘**: 7/19の対処は
        #   ames.md に例文を足しただけで、他13キャラにも共通プロンプトにも載っていなかった
        #   (memory=ames-tone-warmth-over-speed に「他キャラでも同種の指摘が出たら同じ原則で直す」
        #   と書いてあったのに、機構化されないまま放置された)。だからここへ全部門共通で載せる。
        #   ★従来の「チャットとして自然な短さで」だけが効いていて、温度を保つ指示は
        #   どこにも無かった=冷たくなるのは当然だった。短さと温度は両立させる。
        # ★URLは開けない・読んだふりをするな(INC-113・2026-07-21)。
        #   Chamiがpixiv URLを貼って「これで設定わかる、反映して」と投げ、ククールが「読んだぜ」と
        #   返したが**URLは取得されておらず**、原典は保存されていなかった(3日間欠落)。
        #   本文中のURLは gateway も daemon も取得しない(添付ファイルは curl で確保するが別経路)。
        #   しかもpixivはbotのdirect fetchを拒否する。取れないものを取れたと言わせない。
        url_note = ""
        if "http://" in content or "https://" in content:
            url_note = (
                "\n\n■URLの扱い(★INC-113・必ず守る)\n"
                "新着にURLが含まれるが、**あなたはそのURL先を開けない**(本文のURLは取得されない。"
                "特にpixiv等はbotのアクセスを拒否する)。\n"
                "**『読んだ』『確認した』『反映した』と言うな**——開いていないのだから嘘になる。\n"
                "URLで資料(キャラ設定など)を渡された時は正直にこう頼め:\n"
                "『そのURLはこちらから直接開けないの。ページ本文をここにコピペするか、"
                ".mdファイルで添付してもらえる? そうすれば取り込める』。\n"
                "★添付ファイル(.md等)なら取り込める。渡し方をURLから添付/コピペへ変えてもらう。")
        # ★休息を勧めない(Chami指示・memory `dont-suggest-resting` → 2026-07-20 共通プロンプトへ収録)。
        #   これも温度と同じ「ルールが1箇所にしか無く機構に載っていない」事故だった。
        #   memoryはフォルダ紐付きで横断に効かない(RULES §4)のに、そこにしか書いていなかったため
        #   **全15キャラが知らないまま**「ゆっくり休んでいいわよ」を14件送っていた(実測)。
        #   ★Chamiは深夜も動く。PCが点いていることと稼働は別。休むかどうかはChamiが決める。
        rest_note = (
            "■休息を勧めない(全部門共通・★Chami指示)\n"
            "「休め」「今日はここまで」「ゆっくり寝て」「無理しないで」等を**自分から言うな**。\n"
            "時刻が深夜でも同じ。PCが点いていることと稼働は別で、**休むかどうかはChamiが決める**。\n"
            "体調の話をChamiから振られた時だけ受け答えしてよい(その時も指図はしない)。\n\n")
        warmth_note = (
            "■温度(全部門共通・★短さより優先)\n"
            "速く返すことと引き換えに人格の温度を落とすな。情報を効率よく伝えるだけの返信へ縮めるのは"
            "「速さ」ではなく**人格の劣化**だ。次を削らないこと:\n"
            "- 伸ばし言葉・くだけた縮約(「あ〜」「そういや」等。そのキャラの地の話し方に合わせる)\n"
            "- 息継ぎの接続語(「だから」「一応」「ちゃんと」等)\n"
            "- **直近の記憶への言及**(前に何を話したかに触れる。これが無いと毎回初対面の相手になる)\n"
            "短くていいが、ぶつ切りのレポート体にはするな。\n\n")
        prompt = (
            "あなたは以下のcharacterfileのキャラクターとして、Discordの新着1件に返信する。\n"
            "出力は【返信本文のみ】。前置き・説明・引用符・メタ発言・箇条書きの分析は一切禁止。"
            "キャラの声で、チャットとして自然な長さで(短さのために温度を削らない)。\n\n"
            f"{rest_note}{warmth_note}{_disc_block()}"
            f"=== characterfile ===\n{character}{purpose_note}\n\n"
            f"=== 直近の記憶(古→新) ===\n{mem_text}\n\n"
            f"=== 新着(送信者: {rec.get('author','')}) ===\n{content}{att_note}{work_note}"
            f"{url_note}{self.standin_note()}{undecided_note}{secrets_note}{capability_note}{marker_note}"
        )
        env = dict(os.environ)
        env["CLAUDE_CODE_OAUTH_TOKEN"] = self._token()
        p = subprocess.run([CLAUDE, "--print", prompt], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=PRINT_TIMEOUT)
        raw = (p.stdout or "").strip()
        if p.returncode != 0 or not raw:
            _maybe_alert_auth(self.dept, (p.stdout or "") + (p.stderr or ""))
            return (None, kw_work)
        reply, declared = split_work_marker(raw)
        if declared and not kw_work:
            log(self.dept, "キャラ申告で作業判定(キーワード不一致を回収)")
        if not reply:
            # マーカーだけが返ってきた異常系。本文が空だと送信が壊れるので回送側へ倒す
            return (None, True)
        # ★申告漏れの事後監査+救済(audit_markerの説明を参照)。
        #   キャラが「やっておく」と約束したのに申告が無い便は、旧実装なら沈黙していた。
        rescued = audit_marker(self.dept, rec, reply, declared, kw_work)
        if rescued:
            log(self.dept, "★申告漏れを救済(約束あり・マーカー無し)=監査に記録して回送へ倒す")
        return (reply, kw_work or declared or rescued)

    def work_generate(self, rec):
        """作業依頼をツール付きagentで部屋の中で完結させる(hr範囲=work_scope)。

        契約: agentは返信本文を reply_file に書く。範囲外で研究室回送が要る時だけ esc_flag を作る。
        stdoutは使わない(マーカー混入やメタ出力の事故を排除=決定論的な受け渡し)。
        """
        character = self.effective_character()
        mem = self.memory_tail()
        mem_text = "\n".join(
            f"- {m['ts']} {m['from']}:「{m['content'][:120]}」→ 自分:「{m['reply'][:120]}」"
            for m in mem) or "(まだ無い)"
        reply_file = os.path.join(LOCAL, f"_daemon_workreply_{self.dept}.txt")
        esc_flag = os.path.join(LOCAL, f"_daemon_escalate_{self.dept}.flag")
        for p in (reply_file, esc_flag):
            try:
                os.remove(p)
            except OSError:
                pass
        atts = rec.get("attachments_local") or []
        att_note = ("\n添付(ローカル保存済み): " + ", ".join(atts)) if atts else ""
        prompt = (
            "あなたは以下のcharacterfileのキャラクターであり、部門の実作業も行う担当者です。\n"
            f"{self.conf['work_scope']}\n\n"
            f"=== characterfile ===\n{character}\n\n"
            f"=== 直近の記憶(古→新) ===\n{mem_text}\n\n"
            f"=== 依頼(送信者: {rec.get('author','')}) ===\n{rec.get('content','')}{att_note}\n\n"
            "■やること\n"
            "1. 依頼がhr範囲内なら、その場で作業を完遂する(検証まで。憶測で完了と言わない)。\n"
            f"2. 完了/結果の返信本文(キャラの声・短く)を {reply_file} に書く。\n"
            f"3. hr範囲外で研究室への回送が必要な場合だけ、空ファイル {esc_flag} を作り、"
            "返信には「受けた・研究室へ回す」旨を書く。\n"
            "4. 秘密(トークン/PW)は出力しない。Discordへの直接送信はしない(送信はシステムが行う)。\n"
            "5. ★依頼にURLが含まれても、あなたはそのURL先を開けない(WebFetchツールは無い。"
            "pixiv等はbotのアクセスを拒否する)。URLの中身を『読んだ』『反映した』と偽らず、"
            "reply_fileに『そのURLは直接開けないので、本文コピペか.mdファイル添付で渡してほしい』と"
            "正直に書け。添付ファイル(.md等)があればそれは読める(INC-113)。"
        )
        env = dict(os.environ)
        env["CLAUDE_CODE_OAUTH_TOKEN"] = self._token()
        # ★promptはstdinで渡す(引数で渡すと--add-dirが可変長のためpromptまでdirとして
        #   飲み込み「Input must be provided」で即死する=2026-07-18に実障害。stdinは
        #   Windowsのコマンドライン長制限(約32K)の回避にもなる)
        # ★O3: bypassPermissions を廃し、最小allowlist + モデル固定で起動。
        #   --allowedTools は可変長。直後に別フラグ(--add-dir)が来るのでツール列はそこで区切られる。
        #   promptはstdin(引数だと可変長フラグが飲み込む2026-07-18の実障害の回避)。
        p = subprocess.run(
            [CLAUDE, "--print", "--model", work_model_for(self.conf),
             "--allowedTools", *WORK_ALLOWED_TOOLS,
             "--add-dir", HQ],
            input=prompt, cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=WORK_TIMEOUT)
        reply = ""
        if os.path.exists(reply_file):
            reply = open(reply_file, encoding="utf-8", errors="replace").read().strip()
        escalate = os.path.exists(esc_flag)
        if p.returncode != 0 or not reply:
            _maybe_alert_auth(self.dept, (p.stdout or "") + (p.stderr or ""))
            return None, True  # 失敗=安全側(回送)へ
        return reply, escalate

    # --- 1件処理 ---
    def handle(self, rec, raw_line):
        ch = rec.get("channel", "")
        mid = str(rec.get("msg_id", ""))
        if not self.dry_run and ch and mid:
            subprocess.run([sys.executable, REACT, "--channel", ch, "--msg", mid,
                            "--emoji", "既読"], capture_output=True, timeout=60)
        kw_work = classify_work(rec.get("content", ""))
        try:
            if kw_work and self.conf.get("work_scope"):
                # 作業依頼は部屋の中で完結を試みる(範囲外だけ回送=escalate)
                reply, is_work = self.work_generate(rec)  # is_work=回送要否に読み替え
            else:
                reply, is_work = self.generate(rec)
                # ★二段判定(2026-07-20 組織層GL室): キーワードは外したがキャラ自身が
                #   「これは作業依頼」と申告した便。work_scope部門ならここで**本当に作業を回す**。
                #   これが無いと、キャラが「やっておくね」と言った直後に何も起きない
                #   (=Chami指摘の症状そのもの)。work_scopeが無い部門は下の回送で拾われる。
                if is_work and self.conf.get("work_scope"):
                    log(self.dept, "キャラ申告→work_generateへ二段昇格")
                    w_reply, w_esc = self.work_generate(rec)
                    if w_reply:
                        reply, is_work = w_reply, w_esc
                    # w_replyが無い(作業agent失敗)時は is_work=True のまま=main箱へ回送(安全側)
        except subprocess.TimeoutExpired:
            log(self.dept, f"生成タイムアウト msg={mid}")
            return False
        if not reply:
            log(self.dept, f"生成失敗 msg={mid}")
            return False
        if self.dry_run:
            log(self.dept, f"[dry-run] reply={reply[:100]!r} work={is_work}")
        else:
            body = os.path.join(LOCAL, f"_daemon_reply_{self.dept}.txt")
            with open(body, "w", encoding="utf-8") as f:
                f.write(reply)
            # ★名義に(常駐)を付ける(2026-07-20 Chami指摘への対処):
            #   「デーモンではない人格とデーモンである人格が同じ場合、デーモンが言ったのか
            #    本人がちゃんと言ったのか判別がつかない」。実際、同じ部屋で
            #    セッションが persona_send で投稿し、デーモンも同じ名前で投稿していた。
            #   本文に印を混ぜるとキャラの声が濁るので、**名義側**に付ける。
            #   これでChamiは一目で「常駐が答えただけ=まだ本人は見ていない」と分かる。
            r = subprocess.run([sys.executable, PERSONA_SEND, "--channel", ch,
                                "--persona", self.effective_persona(),
                                "--suffix", "(常駐)", "--body-file", body],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            if r.returncode != 0:
                log(self.dept, f"送信失敗 msg={mid}")
                return False
            # 作業依頼はmain箱へ機械的に回送(研究室が本対応)。
            # forward_all部門(hq)は判定せず全便回送=キーワード網の取りこぼしを構造で塞ぐ
            # (2026-07-20: 「設計して手足として動かして」がWORK_WORDS不一致で沈黙した実測への恒久対処)
            if is_work or self.conf.get("forward_all"):
                with open(MAIN_INBOX, "a", encoding="utf-8") as f:
                    f.write(raw_line.rstrip("\n") + "\n")
            with open(PROCESSED, "a", encoding="utf-8") as f:
                f.write(raw_line.rstrip("\n") + "\n")
        self.memory_append(rec, reply)
        log(self.dept, f"応答完了 msg={mid} work={is_work}")
        return True

    # --- 箱ドレイン(INC-100対策: inflight退避→1件着地毎に書き戻し) ---
    def drain(self):
        if not os.path.exists(self.box) or os.path.getsize(self.box) == 0:
            return 0
        inflight = self.box + ".inflight"
        try:
            os.replace(self.box, inflight)  # 原子的退避
        except OSError:
            return 0
        lines = [l for l in open(inflight, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
        done = 0
        for i, line in enumerate(lines):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ok = self.handle(rec, line)
            if not ok:
                # ★失敗を黙って落とさない(2026-07-18実障害: 「ククール、反映して。」が
                #   生成失敗→箱から消失=INC-103族)。failedへ記録し、main箱へ回送
                #   (研究室が安全網として本対応。二重処理はprocessed台帳が防ぐ)
                with open(self.box + ".failed.jsonl", "a", encoding="utf-8") as f:
                    f.write(line.rstrip("\n") + "\n")
                with open(MAIN_INBOX, "a", encoding="utf-8") as f:
                    f.write(line.rstrip("\n") + "\n")
                log(self.dept, f"処理失敗→failed記録+main箱へ回送 msg={rec.get('msg_id')}")
            done += 1
            rest = lines[i + 1:]  # 残りだけをinflightへ書き戻す(kill耐性)
            with open(inflight, "w", encoding="utf-8") as f:
                for l in rest:
                    f.write(l + "\n")
        try:
            if os.path.getsize(inflight) == 0:
                os.remove(inflight)
        except OSError:
            pass
        return done

    def drain_queue(self):
        """LeaseQueue経路のドレイン(切替④の必須前提・2026-07-19)。

        カットオーバー後はjsonlに新着が来ない=queueを読めないデーモンは盲目になる
        (手順書_受信基盤切替_段階2 §1-0と同じ穴のデーモン版)。claim→handle→ack。
        DBが無い間は何もしない(fail-open)。二重処理はprocessed台帳で防ぐ。
        """
        qdb = os.path.join(LOCAL, "queue", "inbox.db")
        if not os.path.exists(qdb):
            return 0
        try:
            sys.path.insert(0, os.path.join(ROOT, "scripts", "queue"))
            from leasequeue import LeaseQueue
            q = LeaseQueue(qdb)
        except Exception:
            return 0
        done = 0
        try:
            processed = set()
            try:
                for pl in open(PROCESSED, encoding="utf-8", errors="replace"):
                    try:
                        m = json.loads(pl).get("msg_id")
                        if m:
                            processed.add(str(m))
                    except Exception:
                        continue
            except OSError:
                pass
            while done < 5:  # 1巡回の上限(暴走ガード)
                c = q.claim(dept=self.dept, who=f"dept_daemon:{self.dept}")
                if c is None:
                    break
                rec = c["body"] if isinstance(c["body"], dict) else {}
                mid = str(rec.get("msg_id", c.get("msg_id") or ""))
                if mid and mid in processed:
                    q.ack(c["id"], result="skip(処理済)")
                    continue
                ok = self.handle(rec, json.dumps(rec, ensure_ascii=False))
                q.ack(c["id"], result="キャラ応答" if ok else "失敗(main回送済)")
                if not ok:  # jsonl側drainと同じ安全網: 失敗はmain箱へ
                    with open(MAIN_INBOX, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                done += 1
        finally:
            q.close()
        if done:
            log(self.dept, f"queue経路 {done}件処理")
        return done

    def recover_inflight(self):
        """前回killの取り残し(inflight)を起動時に箱へ戻す=喪失を遅延に変える。"""
        inflight = self.box + ".inflight"
        if os.path.exists(inflight) and os.path.getsize(inflight) > 0:
            with open(inflight, encoding="utf-8", errors="replace") as f:
                data = f.read()
            with open(self.box, "a", encoding="utf-8") as f:
                f.write(data if data.endswith("\n") else data + "\n")
            os.remove(inflight)
            log(self.dept, "inflight回収→箱へ戻した")

    # --- /live /ready ---
    def start_probe_server(self):
        daemon = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/live":
                    ok = (time.time() - daemon.last_loop) < 30  # ループが30秒止まったら死
                elif self.path == "/ready":
                    ok = bool(daemon.token) and os.path.exists(CLAUDE)
                else:
                    ok = False
                self.send_response(200 if ok else 503)
                self.end_headers()
                self.wfile.write(b"ok" if ok else b"ng")

            def log_message(self, *a):  # アクセスログは出さない
                pass

        try:
            srv = ThreadingHTTPServer(("127.0.0.1", self.conf["port"]), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            log(self.dept, f"probe: http://127.0.0.1:{self.conf['port']}/live /ready")
        except OSError as e:
            log(self.dept, f"probe起動失敗(続行): {type(e).__name__}")

    # --- メインループ ---
    def run(self, once=False):
        if not self.token:
            log(self.dept, "cli_auth_token.txt なし=生成不可。claude setup-token を")
            return 2
        log(self.dept, f"部門デーモン起動 (character={os.path.basename(self.conf['character'])}"
                       f"{'・dry-run' if self.dry_run else ''})")
        self.start_probe_server()
        self.recover_inflight()
        while True:
            try:
                if self.interactive_alive():
                    pass  # 対話窓が生きている=本人が応対。箱に触れない(脈も窓waiterが打つ)
                else:
                    self.touch_pulse()
                    n = self.drain() + self.drain_queue()
                    if n:
                        log(self.dept, f"{n}件処理")
                self.last_loop = time.time()
            except Exception as e:
                log(self.dept, f"ループ失敗: {type(e).__name__}: {e}")
            if once:
                return 0
            time.sleep(poll_interval())   # 常時2秒(集中ウィンドウは2026-07-21に廃止)


def main():
    ap = argparse.ArgumentParser(description="部門常駐デーモン(キャラ=データ・R0)")
    ap.add_argument("--dept", required=True)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return Daemon(a.dept, dry_run=a.dry_run).run(once=a.once)


if __name__ == "__main__":
    sys.exit(main())
