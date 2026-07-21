#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Claude Codeの素文を、Discordの部屋に出せる「キャラの発言」へ整える。

なぜ要るか(2026-07-20 Chami指摘):
  「Discord側の返事がClaude Codeそのまんまの文章で人格が消えてる」。
  ミラーは名前だけアロンソを借りて、中身は見出し・表・コードの素文をそのまま流していた。
  しかも1ターンが10個の断片に割れて連投されるので、部屋が読めない。

★ローカルLLMでの書き換えは実測して**不採用**にした(2026-07-20):
    qwen3:4b … 32〜53秒。敬語混入・英語で返す・生ログに無い文を捏造(「この期間は部屋を
                見ていませんでした」等)。報告として使えない。
    qwen3:8b … 51.6秒。前置きを付け、自分を三人称で呼び、日付を取り違えた。
                さらにVRAM 7730/8192MiB(94%)・70℃ = Chamiが避けろと言ったギリギリ運用。
  報告の書き換えは「事実を1つも変えてはいけない」タスクで、小型モデルが最も苦手な種類。
  **人格のために事実を壊すのは本末転倒**なので、生成に頼らない方式にした。

採用した方式(二段構え):
  1. 私(研究室)がターン中に voice ファイルへ**自分の言葉で**一言を書く。これが本命。
     文脈も口調台帳も持っている本人が書くのだから、一番質が高くタダで速い。
  2. 書き忘れた時は素文を機械的に整形して出す(見出し・表・コード柵を落として文章化)。
     ★絶対に黙らない。人格は装飾であって、届くことより優先されない(AegisConciel)。
"""
import os
import re
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
VOICE_MAX_AGE = 1800        # 秒。これより古いvoiceは前のターンの残骸とみなして使わない
# ★2026-07-21 Chami「この文面、ディスコード上には帰ってきてない。だからディスコードだけ見てたら
#   そっちの提案をこっちが無視することになってた」で発覚(ORG-16)。
#   旧値=1800。**ここが3層目の打ち切りだった**:
#     mirror_to_discord(9000へ緩和済) → persona_render(**1800で切っていた**) → persona_send(1900ずつ分割送信)
#   persona_send は split_body() で全文を複数通に分けて送れる(実測 8000字→5通・欠落0)のに、
#   その手前で1800字に捨てていた=**下流の分割送信が無意味になっていた**。
#   しかも切った印「…(続きはClaude Code側)」はこの後のLLM書き換えで消えるため、
#   Chamiには**完全な文章に見えて実は途中で終わっている**=最悪の壊れ方(静かな欠落)をしていた。
#   実害= 研究室HQの**質問と提案が毎回末尾ごと消え**、Chamiが無視した形になっていた。
MAX_CHARS = 9000            # persona_send側が1900字ずつに分割して全部送る。ここでは捨てない
# 口調変換の結果がこの割合を下回ったら「情報が落ちた」とみなし、口調を捨てて素のdigestを届ける。
# 0.75= 言い換えで多少縮むのは許すが、2〜3割以上消えたら欠落とみなす(実測の事故は 1314/2800=0.47)。
LOSS_RATIO = 0.75
REWRITE_TIMEOUT = 120       # 口調変換の上限。超えたらdigestで届ける(黙らせない)
CLAUDE = r"C:\Users\chami\.local\bin\claude.exe"


def voice_path(dept):
    return os.path.join(os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local"),
                        f"_voice_{dept}.txt")


def take_voice(dept):
    """私が書いた一言を取り出して**消す**(消さないと次のターンで再送されるため)。"""
    p = voice_path(dept)
    try:
        if time.time() - os.path.getmtime(p) > VOICE_MAX_AGE:
            os.remove(p)
            return ""
        body = open(p, encoding="utf-8").read().strip()
        os.remove(p)
        return body
    except OSError:
        return ""


def digest(body):
    """素のmarkdownを、チャットで読める平文へ落とす(生成しない=事実は絶対に変わらない)。"""
    s = body or ""
    s = re.sub(r"```.*?```", "", s, flags=re.S)          # コードブロックは部屋に出さない
    out = []
    for line in s.splitlines():
        t = line.strip()
        if not t:
            continue
        if re.match(r"^\|?\s*[-:|]+\s*\|", t) or t.startswith("|--"):
            continue                                     # 表の区切り行
        if t.startswith("|"):                            # 表の行 -> 読点で繋いだ1行に
            cells = [c.strip() for c in t.strip("|").split("|") if c.strip()]
            if cells:
                out.append("・" + " / ".join(cells))
            continue
        t = re.sub(r"^#{1,6}\s*", "", t)                 # 見出し記号
        t = re.sub(r"^[-*]\s+", "・", t)                  # 箇条書き
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)           # 強調
        t = re.sub(r"`([^`]+)`", r"\1", t)               # インラインコード
        out.append(t)
    s = "\n".join(out).strip()
    if len(s) > MAX_CHARS:
        s = s[:MAX_CHARS] + "\n…(続きはClaude Code側)"
    return s


_CHAR_DIR = os.path.join(r"D:\SougouStartFolder\00_AI-HQ",
                         "departments", "hr", "characters")


def _character_by_persona(persona):
    """**名乗る人格名**からcharacterfileを引く(取れなければ空)。

    ★これが無いと何が起きたか(2026-07-20 Chami指摘で発覚):
      ミラーは `シャビ・アロンソ` の名前で投稿するのに、口調変換は
      `DEPT_CONF[dept]["character"]`(hq= ames.md)を読んでいた。
      結果、**アロンソの名前でアメスの口調**が出ていた。しかもvoiceファイルを
      書いた時だけアロンソになるので、Chamiからは「アロンソだったりアメスだったり」
      という不可解な揺れに見えていた。
      部屋の常駐(デーモン)と、その部屋で**セッションが名乗る人格**は別物。
      口調は**名乗る人格**で引かないと必ずズレる。

    照合は characters/*.md の見出し `# characterfile: <名前>(...` を読む。
    DEPT_CONFのpersonaに載らない人格(アロンソ等=デーモンが居ない部屋の演者)も
    これなら引ける。ファイル名の命名規則に依存しないのも狙い。
    """
    name = (persona or "").strip()
    if not name:
        return ""
    try:
        for fn in sorted(os.listdir(_CHAR_DIR)):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(_CHAR_DIR, fn)
            try:
                head = open(path, encoding="utf-8").readline()
            except OSError:
                continue
            m = re.match(r"#\s*characterfile:\s*([^(（\n]+)", head)
            if m and m.group(1).strip() == name:
                return open(path, encoding="utf-8").read()
    except OSError:
        pass
    return ""


def _character_of(dept):
    """その部屋の**常駐デーモン**のcharacterfile本文とペルソナ名を返す(取れなければ空)。

    ※口調変換には使わない(上の _character_by_persona を使う)。デーモン用の参照として残す。
    """
    try:
        import sys
        if _HERE not in sys.path:
            sys.path.insert(0, _HERE)
        import dept_daemon                      # 遅延import(循環と起動コストを避ける)
        conf = dept_daemon.DEPT_CONF.get(dept) or {}
        path = conf.get("character")
        if path and os.path.exists(path):
            return open(path, encoding="utf-8").read(), (conf.get("persona") or "")
    except Exception:
        pass
    return "", ""


def persona_rewrite(dept, text, persona=None):
    """digestをそのキャラの口調へ言い換える。**失敗したら必ず元のtextを返す**。

    ★2026-07-20 21:35 Chami「やって」で追加。それまで voice ファイルが無い時は digest
      (=素文の機械整形)がそのまま部屋へ出ており、実測で **_voice_*.txt は全部屋で1件も
      存在しなかった**=常時Claude原文が出ていた。voice方式は「セッションが毎ターン自分で
      書く」心がけに依存しており、誰も書かないので機能していなかった。

    ★設計の要点(ここを緩めないこと):
      - **黙らない**より優先するものは無い。例外・タイムアウト・空応答・認証失効の
        どれが起きても digest を返す=ミラーは絶対に止まらない(AegisConciel)。
      - **事実を変えさせない**。書き換えは口調だけで、追加・削除・推測を禁じる。
        これは小型ローカルLLMが最も苦手な種類のタスクだったので不採用にした経緯がある
        (上のdocstring参照)。ここでは claude を使うので事実保持の精度が違う。
      - 環境変数 `GO5_PERSONA_REWRITE=0` で即座に無効化できる(事故時の逃げ道)。
    """
    if os.environ.get("GO5_PERSONA_REWRITE") == "0":
        return text
    body = (text or "").strip()
    if not body:
        return text
    # ★口調は**名乗る人格**で引く(2026-07-20 Chami指摘の修正)。
    #   personaが渡らない旧い呼び出しだけ、従来どおり部屋の常駐から引く(後方互換)。
    character = _character_by_persona(persona) if persona else ""
    if not character:
        character, persona = _character_of(dept)
    if not character:
        return text                             # 人格が無い部屋はそのまま出す
    try:
        import subprocess
        local = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
        env = dict(os.environ)
        try:
            tok = open(os.path.join(local, "cli_auth_token.txt"),
                       encoding="utf-8").read().strip()
            if tok:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
        except OSError:
            pass
        prompt = (
            "あなたは以下のcharacterfileの人物です。【報告】をこの人物の口調へ言い換えてください。\n"
            "■絶対規則\n"
            "1. 事実を1つも変えない。数値・固有名詞・判断・結論をそのまま保つ。\n"
            "2. 情報を足さない。報告に無いことを書かない(推測・感想の創作は禁止)。\n"
            "3. 情報を削らない。要点を落とさない。\n"
            "4. 出力は言い換えた本文のみ。前置き・見出し・箇条書きの記号・メタ発言は書かない。\n"
            "5. 括弧は半角()を使う。\n\n"
            f"=== characterfile ===\n{character}\n\n"
            f"=== 報告 ===\n{body}"
        )
        p = subprocess.run([CLAUDE, "--print", prompt], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=REWRITE_TIMEOUT)
        out = (p.stdout or "").strip()
        if p.returncode != 0 or not out:
            return text                         # 認証失効・失敗 → 素のdigestで届ける
        # ★欠落ガード(2026-07-21・ORG-16): 規則3「情報を削らない」を書いても**LLMは実際に削る**。
        #   実測= 2800字の報告が1314字で返り、**末尾の質問(「直しとくか?」)が丸ごと消えた**。
        #   Chamiはそれを知らずに提案を無視した形になっていた=**静かな欠落**。
        #   口調は"あると良い"もの、内容は"必須"のもの。**削られたと分かったら口調を捨てて内容を取る**。
        #   ★プロンプトの強化では直せない(禁じても起きたのが実測)。だから機構で判定する。
        if len(out) < len(body) * LOSS_RATIO:
            return text                         # 縮みすぎ=情報が落ちた → 素のdigestを届ける
        if len(out) > MAX_CHARS:
            out = out[:MAX_CHARS] + "\n…(続きはClaude Code側)"
        return out
    except Exception:
        return text                             # タイムアウト含め、何が起きても届ける


def render(dept, bodies, persona=None):
    """1ターン分の素文(複数)を、部屋へ出す1発言にまとめる。

    persona= **その発言が名乗る人格名**(例 シャビ・アロンソ)。口調はこれで決まる。
    渡さないと部屋の常駐デーモンの口調になり、名前と口調が食い違う(2026-07-20の事故)。

    戻り値は必ず非空(呼び出し側が「送らない」判断をしなくて済むように)。
    """
    voice = take_voice(dept)
    if voice:
        return voice                            # 本人が書いた一言が最優先(タダで速い)
    joined = "\n\n".join(b for b in bodies if b and b.strip())
    return persona_rewrite(dept, digest(joined), persona=persona)
