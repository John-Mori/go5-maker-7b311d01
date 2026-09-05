# -*- coding: utf-8 -*-
"""test_codex_trigger — 純関数 is_codex_mentioned の召喚判定を実行で通す(Discord接続不要)。

イージス研究室(デブライネ)依頼2026-09-05(1回目)の受け入れ線=
  ・「ソリッド・スネーク」(別人・品質管理部門)への言及で **召喚しない**(False)
  ・確定呼称「ネイキッド・スネーク」/「ネイキッド」で **召喚する**(True)
  ・Chami指定の「ボス」で **召喚する**(True)
must-fail(C-053・1回目)= 短縮「スネーク」を素で足すと誤召喚する、を機械が赤で捕まえることも確かめる。

イージス研究室(デブライネ)依頼2026-09-05(2回目)の受け入れ線=
  本番7日分(dispatch便除く)約600件に旧・素の部分一致を当てたら20件が付け替え対象、
  うち18件(90%)が「Codexで改修させた」等の話題言及で誤召喚だった実測に基づく修正。
  ・召喚は「名指しの形」(行頭 or 直前が空白/全角スペースの @/＠ + トークン、または実メンション<@id>)
    だけを真とする。素の本文中の言及では拾わない。
  ・下の REAL_FALSE_POSITIVES は inbox.db(local/queue/inbox.db)から引いた実物の本番本文
    (作り物の文字列ではない・C-053)。新ロジックで全件 False、旧ロジック(_old_is_codex_mentioned)
    に当てると誤って True へ転ぶ=回帰ガードに歯がある、を確認する。
  受け入れ条件(デブライネの言葉)= 「18件がFalse、@ボス/<@id>/明示の名指しがTrue。実物(テスト出力)で返せ」。
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows既定cp932だと絵文字入り実物本文で落ちる

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codex_trigger as ct  # noqa: E402


CASES = [
    # (本文, 期待, 狙い)
    ("ソリッド・スネークに聞いてくれ", False, "別人=誤召喚しない"),
    ("品質管理部門のソリッド・スネーク、レビュー頼む", False, "別人=誤召喚しない2"),
    ("@ネイキッド・スネーク 頼む", True, "確定呼称+@=名指しで召喚"),
    ("@ネイキッド 任せる", True, "確定呼称短縮+@=名指しで召喚"),
    ("@ボス 任せる", True, "Chami指定の召喚名+@=名指しで召喚"),
    ("@codex 実装して", True, "英語トークン+@=名指しで召喚"),
    ("@コーデックス お願い", True, "カナ+@=名指しで召喚"),
    ("＠ボス 全角＠でも召喚できる？", True, "全角＠でも名指し"),
    ("これ@ボス確認して", False, "直前が空白でない@は名指しでない(地の文中の@・デブライネ規則1に忠実)"),
    ("お願いします @ボス 確認して", True, "文中でも直前が空白の@なら名指し"),
    ("ネイキッド・スネークに頼む", False, "@なし素の言及=召喚しない(新ルール)"),
    ("ボスに任せる", False, "@なし素の言及=召喚しない(新ルール)2"),
    ("codexで実装して", False, "@なし素の名指し=召喚しない(新ルール・旧テストは逆だった)"),
    ("コーデックスお願い", False, "@なしカナ言及=召喚しない(新ルール)"),
    ("@スネークに任せて", False, "短縮スネーク単独は非TOKEN=@付きでも召喚しない(mutant検知用)"),
]

# 実物(本番): msg 5406(2026-09-05 01:13 dept=codex)。正しく召喚されるべき唯一の実例。
REAL_TRUE_POSITIVE = (
    "@ボス 必要なものとしてYMM4で編集する前段としてYMMPのファイルがいるそのために必要な台本作成であったり画像の差し込みどう画像を使っていくかとかのあとは音声\n"
    "限密な読み方とかの設定を編集できるサイトを作ってほしい自分専用だから他の辺には使わないから問題ないという考えで設計して。6Proで思考して、実装はそれ以下でモデル下げてやって",
    True,
    "実物・本番msg5406=正しい召喚(dept=codexに実際に届いた)",
)

# 実物(本番): デブライネ実測の誤召喚18件のうち inbox.db(local/queue/inbox.db)から実際に
# 引いた16件。id/部門はコメントに残す(local/_work/codex_fp_18.json と対応)。
REAL_FALSE_POSITIVES = [
    (4194, "system-engineer",
     "御託はいいから3択が表示されないから、多分もうこれClaudeでやっても解決しないから、Codexに依頼するための文章をコードブロックで表示して"),
    (4426, "hq",
     "1544454352029229148\n\n将来やることルームという部屋を立てた。IDはこれ。今のパソコンのスペックじゃ実現できなかったり、まだ新しく出てきた Claude CodeとかCodexみたいなAIエージェントのシステムとかの情報共有を取得で将来なんかやりたくなったりできるようになったらやるっていうところを\nちょっと保存しといてほしいんだよ。\nそのための チャットルーム、それがどう実現かどうかを検討してほしいというか 今色々それについて調べてもらったり 壁打ちするためのところ。\nメンバーは アロンソコーチ、ジェンティルドンナ、ヴィルシーナ、カスミ、補佐アメス。"),
    (4487, "someday-room",
     "……最初はいろいろなAIに同じ質問をして、比較することもよくしていました。最近はChatGPTと話すことがかなり増えましたが、AIによって見方や得意なことが違うのも面白いなと思っています。……最初のセットアップからかなり苦戦して、やっとこさCursorやCodexなども触り始めたところ。"),
    (4808, "hr-room",
     "Codexからも改修しやすくする。\n不要なとこまでファイルを読ませずに済む。綺麗に分けれる。みたいなメリットないかなと思って"),
    (4989, "gunji",
     "トークンとClaudeだと出来が悪すぎたからそれら考慮してCodexでやった。\nそのログと完成動画を置いとく。"),
    (5027, "hq", "アメス口調こえ〜、ボスですか？😅"),
    (5183, "learning-coach", "よし、ここにCodexを参戦させるよ！やり方教えて！"),
    (5199, "learning-coach",
     "システム設計力はコーデックスの方が強いと実感してるから、重いシステム実装や改修を主に任せるつもり。\nその他文系仕事はみんなにまかせたい。三選させるっていうのはここのDiscordにってことだよ。ホイミンGeminiみたいに。"),
    (5288, "learning-coach-2", "部屋というか、別のbotとしてキャラもCodex専用キャラで各部屋に入るって感じにしたくて。"),
    (5290, "learning-coach-2",
     "じゃあ@スネーク で呼べばいいか。ちなみにネイキッド・スネークというキャラでやる。\nオタコンの相棒でまだコンテキストも入れてないスネークはソリッド・スネークと言ってまた別人。"),
    (5296, "learning-coach-2", "とりあえずキャラは後にして、Codexをbotにして呼び出す登録の方法を教えて。先そっちやろう"),
    (5302, "hr-context",
     "で、コンテキストを整理して作る役割を一時的に\n1527286798542311554 \nこの部屋で行いたい。メインはオタコン、サブでククール。そしてCodexのネイキッドスネークが参戦させる予定。まだCodexを入れてないから2人だけ配線しといてよ"),
    (5383, "hr-room", "間違えた。ありがとう。これ全部ネイキッドの方だった"),
    (5393, "otacon-radio", "全部の原典を平等に効かせてほしいさ。でもそれはちょっと後で。まずネイキッドスネークの人格や原典を作ってくれる？Codexで必要なんだ"),
    (5395, "platform-se",
     "token設置=local/discord_codex_token.txt(ちゃみ手元の合鍵を安全経路で。中身は読まないから安心して)\n活性フラグ=local/codex_enabled.txt(空でいい、touch1発)\n+任意で local/discord_codex_bot_id.txt を置けば @スネーク をメンションでも拾う。\nこれ作ったよ"),
    (5413, "codex(誤配済)", "Codexのbotの名前変わってなかったから、スネーク(Codex)にしといて"),
]


def _old_is_codex_mentioned(content):
    """旧ロジック(2026-09-05修正前)=素の部分一致。誤召喚18件の原因になった実装を再現(C-053 must-fail用)。"""
    if not content:
        return False
    c = content.lower()
    return any(t.lower() in c for t in ct.TOKENS)


def run(label, tokens_override=None):
    saved = ct.TOKENS
    if tokens_override is not None:
        ct.TOKENS = tokens_override
    try:
        ok = True
        print(f"--- {label} (TOKENS={ct.TOKENS}) ---")
        for body, want, why in CASES:
            got = ct.is_codex_mentioned(body)
            mark = "PASS" if got == want else "FAIL"
            if got != want:
                ok = False
            print(f"  [{mark}] want={want!s:5} got={got!s:5}  {why}  << {body}")
        return ok
    finally:
        ct.TOKENS = saved


def run_real_true_positive():
    body, want, why = REAL_TRUE_POSITIVE
    got = ct.is_codex_mentioned(body)
    mark = "PASS" if got == want else "FAIL"
    print(f"--- 実物・正しい召喚(msg5406) ---")
    print(f"  [{mark}] want={want!s:5} got={got!s:5}  {why}  << {body[:40]}...")
    return got == want


def run_real_false_positives(use_old_logic):
    logic = _old_is_codex_mentioned if use_old_logic else ct.is_codex_mentioned
    label = "旧ロジック(must-fail変異=素の部分一致)" if use_old_logic else "新ロジック(本番)"
    want = True if use_old_logic else False
    print(f"--- 実物18件中16件・inbox.dbから実採取 / {label} ---")
    ok = True
    for msg_id, dept, body in REAL_FALSE_POSITIVES:
        got = logic(body)
        row_ok = (got == want)
        if not row_ok:
            ok = False
        mark = "PASS" if row_ok else "FAIL"
        print(f"  [{mark}] id={msg_id} dept={dept:20} want={want!s:5} got={got!s:5}  << {body[:30].replace(chr(10), ' ')}...")
    return ok


if __name__ == "__main__":
    # 本番のTOKENSで、名指しの形(@トークン)の真偽を検査
    green = run("本番TOKENS・名指しの形")

    # 実物・正しい召喚が新ロジックでTrueであること
    tp_ok = run_real_true_positive()

    # 実物・誤召喚18件中16件が新ロジックで全てFalseであること(デブライネの受け入れ条件そのもの)
    fp_new_ok = run_real_false_positives(use_old_logic=False)

    # must-fail(C-053・2回目): 旧・素の部分一致ロジックに戻すと、上の実物16件がTrueへ誤って転ぶ
    # (=このテストは実際に誤召喚を検出できる・歯がある)ことを示す
    fp_old_ok = run_real_false_positives(use_old_logic=True)
    if fp_old_ok:
        print("  ※旧ロジックに戻すと実物16件が全てTrueへ誤って転ぶ=赤=ガードに歯がある(期待どおり)")
    else:
        print("  ※旧ロジックでもFalseのままの行がある=このテストは誤召喚を検出できていない(歯が無い・要修正)")

    # C-053(1回目)変異: 短縮「スネーク」を素で足すと、別人ケースが True へ転ぶ(=テストに歯がある)
    mutant = tuple(ct.TOKENS) + ("スネーク",)
    mut_ok = run("変異(素のスネーク追加=誤り)", tokens_override=mutant)
    if mut_ok:
        print("  ※変異が全緑=このテストは誤召喚を捕まえられていない(歯が無い)")
    else:
        print("  ※変異で別人ケースが赤=ガードに歯がある(期待どおり)")

    # fp_old_ok=True は「旧ロジックが実物16件を予測どおり誤ってTrueにする」= must-failの再現が正しい(良)
    # mut_ok=False は「素のスネーク追加で@スネークケースが誤ってTrueに転ぶ」=ガードに歯がある(良)
    all_green = green and tp_ok and fp_new_ok and fp_old_ok and (not mut_ok)
    sys.exit(0 if all_green else 1)
