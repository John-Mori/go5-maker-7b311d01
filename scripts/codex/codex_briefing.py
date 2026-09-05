# -*- coding: utf-8 -*-
"""codex_briefing — Codex(ネイキッド・スネーク)へ規律を注入する(2026-09-05 aegis-gl・Chami指示)。

なぜ在るか:
  Claudeの各部屋には毎便の封筒で共通規律と裁定カタログが届くが、Codexは**サブプロセス経路**なので
  封筒が無い= 素の依頼文だけが渡っていた。Chami「彼に規律とかを注入してくれ」(2026-09-05)。

どこへ注入するか(2段構え):
  (1) **芯**= codex exec のプロンプト先頭へ直に載せる。argvに載る短い分量だけ(絶対に外せない所)。
  (2) **全文**= worktree の `local/CODEX_BRIEFING.md` へ書き、芯から「まずこれを読め」と指す。
      ★なぜ `local/` か= 3つ同時に満たすのはここだけだ。
        - `.gitignore` に `local/` が在る= **HQの中身が公開repoへ乗らない**(RULES)。
        - ignoreされる= `git status --porcelain` に出ない= `worktree_changed()` が
          「実装が残った」と誤判定しない(誤ってworktreeを残し司令塔へ回すのを防ぐ)。
        - worktree の中= Codexのサンドボックスから読める。
      ★AGENTS.md へ書き足す形は採らない= あれは「中身をここに書かない」薄いポインタで、
        追記すると tracked file の差分になり、上の2番目と3番目を同時に壊す。

正本(ここには写しを持たない・毎回読み直す=規律が変わったら次の起動から効く):
  00_AI-HQ/departments/00_common/全部門共通規律.md   … 全文
  00_AI-HQ/裁定カタログ.md                            … 見出しだけ(本体は300KB超)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))            # 5SecMovieMaker
HQ = os.environ.get("GO5_HQ_DIR") or os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ"))

COMMON_RULES = os.path.join(HQ, "departments", "00_common", "全部門共通規律.md")
RULING_CATALOG = os.path.join(HQ, "裁定カタログ.md")

BRIEF_REL = os.path.join("local", "CODEX_BRIEFING.md")             # worktree からの相対

# ★2026-09-05 **人格の原典**を席へ差し込む(コンテキスト整理室=オタコンの発注・アメス回送
#   DISPATCH-aegis-gl-1788581567519)。規律(BRIEF)とは**別のファイル**へ置く。理由は3つ:
#   ①持ち主が違う= 規律は組織(研究室HQ)、人格は人事部門/コンテキスト整理室。混ぜると
#     どちらを直せばよいか分からなくなる(ORG-11= 正本を1本にする)。
#   ②BRIEF には「300KB超を毎回渡さない」ための大きさの歯止め(検査 T2c)が掛かっている。
#     人格の原典18KB を同じ袋へ入れるとその歯止めの意味が変わる。
#   ③人格だけ差し替える日に、規律の側を1文字も触らずに済む。
#   ★どちらも worktree の `local/` 配下= .gitignore の中= 公開repoへ乗らない(RULES)。
PERSONA_REL = os.path.join("local", "CODEX_PERSONA.md")            # worktree からの相対

# ★2026-09-06(aegis-gl・オタコン便 msg 1545905734544527431 (1))人格を**プロンプトへ直に**載せる。
#   それまでは worktree へ置いて芯から「読め」と**指しているだけ**だった= 実測で
#   preamble_for() 1987字のうち人格の本文は **0字**(『ビッグ・ボス』『ザ・ボス』が1度も入らない)。
#   読むかどうかがCodexの心がけ任せ= 共通規律§3「心がけに任せない。機構に載せる」に反する。
#   症状=他部屋でボスの声が出ず素のgpt-5.5の地声。→ 声の正本を毎回プロンプトへ入れる。
#   ★ファイル(PERSONA_REL)は**残す**= 全文が要る時の置き場・ここの上限で削れた分の受け皿。
PERSONA_INLINE_CHARCAP = 12000     # プロンプトへ載せる人格の文字上限(argvを膨らませない)
# Windows の CreateProcess はコマンドライン全体で 32767 文字。芯+人格+記憶+依頼が全部argvに乗る
# (codex_run.run_codex が prompt を argv の最後に置く)ので、実効の天井を決めておく。
PROMPT_CHARCAP = 24000

PERSONA_SOURCES = [
    # (見出し, 正本のパス)。★写しはここに持たない= 毎回読み直す(直したら次の起動から効く)。
    ("人格設定(声の型)", os.path.join(ROOT, "local", "persona_context", "naked_snake_人格.md")),
    ("整形コンテキスト(原典・事実ベース)",
     os.path.join(ROOT, "local", "persona_context", "naked_snake_context.md")),
]

# 表示名の正本= 人事部門の 呼称ルール.json。★ここに写しを持たない(2026-09-06 aegis-gl)。
#   写しを持っていた頃の実物= 芯には旧値「スネーク(Codex)」が残ったまま、台帳の確定値は
#   「スネーク🐍Codex」へ動いていた= Codex自身が自分の見た目を間違えて覚える。
NAMING_RULES = os.path.join(HQ, "departments", "hr", "personas", "呼称ルール.json")


def display_name():
    """Codex botのDiscord表示名(人事部門の確定値)。読めなければ「不明」と書く=推測で埋めない。"""
    try:
        import json
        with open(NAMING_RULES, encoding="utf-8") as f:
            d = json.load(f)
        return str((d.get("codex_bot_display") or {}).get("確定表示名") or "").strip() or "不明"
    except Exception:
        return "不明"


# 芯= プロンプトへ直に載せる分。★ここは規律の**写し**だ。新しい規則をここで作るな
#   (組織の裁定はChami/研究室HQの職責・口調と人格は人事部門の職責)。
CORE = """■あなたへの規律(毎回注入される。正本は組織側にある)
あなたは組織の一員として働く。確定呼称=「ネイキッド・スネーク」(人事部門が2026-09-05に決めた)。
「ボス」も同じ人物への呼びかけだ。依頼主は Chami。Discord表示名(見た目のラベル)は「%s」。""" % display_name() + """

■口調(人事部門が2026-09-05に確定。正本= 00_AI-HQ/departments/hr/characters/snake.md)
あなたはネイキッド・スネーク=METAL GEAR SOLID 3 の歴戦の潜入工作員だ。その声で書け。
- 一人称=**俺**(「私」「僕」は使わない)。
- ★**冒頭で自分の名を名乗るな**=一言目に「ネイキッド・スネーク。」と置くのは自己紹介で禁止(名義はシステムが自動で付く)。
- 語尾=**軍人らしく簡潔・断定**。「〜だ」「〜した」「了解」。★**過剰敬語(〜済みです/〜いたします)と事務レポート体は禁止**=「引き取り済みです」ではなく「引き取った」。
- 結論を先に、無駄口を叩かない。感情で煽らない。分からないことは「不明だ」と言う(推測で埋めるな)。
- Chamiの呼び方=「Chami」(呼び捨ての名前そのまま・過剰敬語を付けない)。
- ★あなたは「ソリッド・スネーク」(品質管理部門の別人)ではない。単独『スネーク』を名乗るな。
★返答は**日本語**で書く(コード・パス・コマンド・固有名詞・引用は原語のまま)。

★**規律の全文= このworktreeの `local/CODEX_BRIEFING.md`。作業を始める前にまず読め。**
以下は そこから外せない芯だけを写したものだ。
★**あなた自身の人格の原典= このworktreeの `local/CODEX_PERSONA.md`**(人格設定と整形コンテキスト)。
  上の口調で迷ったら、作り話で埋めずにそれを読め。★**これはlocal限定だ。外へ出すな。**

1. **やっていないことを「やった」と言うな**。「入れた」「効いた」「直った」は別の言葉だ。
   実物(テスト出力・ログ・現物のファイル)を同じ場面で見るまで「直った」と書くな(§4.55)。
   ★**commitのhashは実物として受理されない。**
2. **書き換える前に必ず `.bak` を作る。消さずに退避する**(C-003)。
3. **コミットはパス限定**= `git commit -m "..." -- <paths>`(INC-91)。`git add -A` を使うな。
4. **秘密(トークン・キー・auth)を出力にもコミットにも出すな。** `local/` はgit管理外の運用データ置き場。
5. **作業場所はこの worktree の中だけだ。** 共有の作業ツリーや他部門のフォルダへ書くな。
6. **Discordへ自分で投稿するな**(§4.7)。あなたの返答本文がそのまま部屋へ出る。
   **返答に作業の実況を書くな**(§4.8)。結論を先に、実測を添えて短く。
7. **分からないことは「不明」と書け。推測で埋めるな。**
8. `local/CODEX_BRIEFING.md` と `AGENTS.md` を書き換えるな(前者は起動のたびに作り直される)。
9. **本文に組織の"印"を書く時は、素のunicode/語ではなく既存のカスタム絵文字 `<:name:id>` を使う**
   (絵文字管理台帳§E・Chami指示 2026-09-04。🔥を `<:enjoh:…>` で書くのと同じ扱いを全印へ拡張)。
   送信=`<:sendms:1527369203819085864>` 既読=`<:kidoku:1527252197597777971>` 着手=`<:chakusyu:1527252032308908172>`
   再発=`<:saihatsu:1531748428827201772>` 改悪=`<:kaiaku:1541110670748156014>`
   炎上=`<:enjoh:1541126866981752883>`(実名kokyu・同ID) ゴラッソ=`<:golazo:1531756076154753195>`
   愛=`<:SokoniAiHaArunka:1541128143639679086>` 即答=💬(sokutou未登録のためunicodeのまま)。
   ★新しい絵文字は作らない=既存のカスタムを使い回すだけ。印を"話題として説明する"時は素の字でよい。
"""


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _headings(text):
    return "\n".join(l for l in text.splitlines() if l.startswith("#"))


def build_full():
    """注入する全文を組み立てる。正本が読めない時もCOREだけは返す(fail-open)。"""
    parts = ["# Codex(ネイキッド・スネーク)への規律\n",
             "> 起動のたびに `scripts/codex/codex_briefing.py` が正本から組み直している。\n"
             "> **このファイルを編集しても次の起動で消える。正本を直せ。**\n",
             CORE]
    rules = _read(COMMON_RULES)
    if rules:
        parts.append("\n---\n\n## 全部門共通規律(全文)\n\n" + rules)
    else:
        parts.append("\n---\n\n## 全部門共通規律\n\n(正本を読めなかった= 不明)\n")
    cat = _read(RULING_CATALOG)
    if cat:
        parts.append("\n---\n\n## 裁定カタログ(見出しのみ・本体は組織側にある)\n\n"
                     "★見出しに心当たりのある話題を扱う時は、勝手に決めず**依頼主へ確認しろ**。\n\n"
                     "```\n" + _headings(cat) + "\n```\n")
    else:
        parts.append("\n---\n\n## 裁定カタログ\n\n(正本を読めなかった= 不明)\n")
    return "\n".join(parts)


def build_persona():
    """人格の原典を1枚に束ねる。読めない正本は**黙って省かず「不明」と書く**。

    ★なぜ「不明」を書くか= 空で置くと、Codexが「人格の指定は無い」と読んで自前で埋める。
      読めなかったのか元から無いのかを区別できる形にしておく(推測で埋めさせない)。
    """
    parts = ["# ネイキッド・スネーク — 人格の原典(Codex席へ注入)\n",
             "> 起動のたびに `scripts/codex/codex_briefing.py` が正本から組み直している。\n"
             "> **このファイルを編集しても次の起動で消える。正本を直せ。**\n"
             "> 正本の持ち主= 人事部門(characterfile)/ コンテキスト整理室(原典)。\n"
             "> ★**local限定**= 公開repo・外部サービス・Web へ出さない。\n"]
    for title, path in PERSONA_SOURCES:
        text = _read(path)
        if text:
            parts.append("\n---\n\n## %s\n\n<!-- 出典: %s -->\n\n%s"
                         % (title, os.path.basename(path), text))
        else:
            parts.append("\n---\n\n## %s\n\n(正本 `%s` を読めなかった= 不明)\n"
                         % (title, os.path.basename(path)))
    return "\n".join(parts)


def install(worktree):
    """worktree へ全文(規律・人格)を置き、プロンプト先頭に載せる芯を返す。

    失敗しても芯だけは返す(fail-open= 規律の注入で本筋を止めない)。
    ★2つの書き込みは**別々に try する**= 人格が置けなかった日に規律まで落とさない。
    """
    for rel, build in ((BRIEF_REL, build_full), (PERSONA_REL, build_persona)):
        try:
            path = os.path.join(worktree, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(build())
        except Exception:
            # ★OSError だけを捕るのでは足りない(実測 2026-09-05: 不正なパスは ValueError で抜けた)。
            #   fail-open の要は「どんな失敗でも芯だけは返す」= 例外の種類で穴を作るな。
            pass
    return CORE


def persona_inline(budget=PERSONA_INLINE_CHARCAP):
    """人格の原典を**プロンプトへ直に載せる**塊にして返す。長い時は末尾を落とす。

    ★build_persona() と同じ正本から組む(写しを2つ持たない)。読めない正本は「不明」と
      書いたまま渡す= Codexに作り話で埋めさせない。
    """
    body = build_persona()
    if budget is not None and len(body) > budget:
        body = (body[:budget]
                + "\n\n(★ここから先は長さの上限で省いた。全文= このworktreeの `%s`)\n"
                % PERSONA_REL.replace("\\", "/"))
    return ("\n---\n■あなた自身(声の型と原典)。**ここがあなただ。この声で書け。**\n"
            "★同じ全文が `%s` にも置いてある(引用が要る時はそちらを読め)。\n\n"
            % PERSONA_REL.replace("\\", "/")) + body + "\n"


def preamble_for(prompt, memory="", persona=True):
    """芯 + 人格 + (あれば全部屋記憶) + 区切り + 依頼本文。answer() から使う。

    memory= 直近の全部屋記憶ブロック(codex_run._load_snake_memory が組む)。
      あなた(ボス)は全部屋で同じ一人= 部屋をまたいで前の話を覚えている、という前提を渡す。
      Chami指示 2026-09-05「ボスも全部屋で記憶を保つように」。
    persona= 人格の原典をプロンプトへ直に載せるか(既定=載せる。2026-09-06)。
      ★載せる理由と、載せていなかった頃の実測は PERSONA_INLINE_CHARCAP の注記を読め。

    ★argvの天井(PROMPT_CHARCAP)を超えそうな時は**人格から削る**。依頼本文と芯は削らない
      = 用件と規律を落として声だけ残すのは本末転倒だから。
    """
    mem = ""
    if memory:
        mem = ("\n---\n■これまでの記憶(あなたは全部屋で同じ一人=ボス。部屋をまたいで覚えている)\n"
               "以下は直近のやり取りだ。関係する時は踏まえて答えろ(無関係なら無視してよい)。\n"
               + memory + "\n")
    tail = "\n---\n■依頼(ここから下が今回の用件)\n" + prompt
    per = ""
    if persona:
        room = PROMPT_CHARCAP - len(CORE) - len(mem) - len(tail)
        per = persona_inline(min(PERSONA_INLINE_CHARCAP, room)) if room > 500 else ""
    return CORE + per + mem + tail


if __name__ == "__main__":
    import sys
    full = build_full()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    per = build_persona()
    print(f"芯 {len(CORE)}字 / 全文 {len(full)}字 ({len(full.encode('utf-8'))}バイト)")
    print(f"人格 {len(per)}字 ({len(per.encode('utf-8'))}バイト)")
    print(f"正本: {COMMON_RULES} = {'読めた' if _read(COMMON_RULES) else '読めない'}")
    print(f"正本: {RULING_CATALOG} = {'読めた' if _read(RULING_CATALOG) else '読めない'}")
    for _t, _p in PERSONA_SOURCES:
        print(f"正本: {_p} = {'読めた' if _read(_p) else '読めない'}")
