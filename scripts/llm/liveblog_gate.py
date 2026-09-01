# -*- coding: utf-8 -*-
"""出力ゲートG= 実況漏れ(名乗り皆無の生ログ)を、人格の顔で出さない。 2026-09-02

★何を塞ぐか(0歩目= 壊れている実物を1つ見た)
  `local/_daemon_reply_system-engineer.txt`(改修α部屋の最終投稿・2026-09-02 00:25:27 JST)
    「打ち切ったが、この便で local\\teian\\candidates_2026-09-02.json … ほか計5件 を
      書き換えていた(実測=作業前後のファイル差分)。完了扱いにせず残してあるから…」
  = 350バイト・1行・`^[` が **0個**。文頭が文の途中で、生Windowsパスが並ぶ純粋な実況。
  声ゼロ・名乗り皆無なのに **ケヴィン・デブライネの名義でChamiの画面へ出た**。
  約3.5時間後にChamiが『重大インシデント。返事バグってます』(msg 1544420696933802056)。
  型= docs/departments/kaizen-analyst/型_実況漏れ_名乗り無し生ログ露出_2026-09-01.md

★なぜ既存のゲートで止まらなかったか
  `_audit_preamble` は「最初の `[名前]` より前」を落とす= **タグをアンカーにする**。
  この便はタグが0個でアンカーが無く、`split_persona_blocks` は仕様どおり
  `return [(None, t)]`(=既定人格の名義で本文丸ごと)を返して丸ごと素通りする。

★判定は **4因子**(改善提案部門の依頼は「タグ0個で保留」だったが、実測で落とした)
  ① 多人格部屋で解決できる `[名前]` が 0個 …… 呼び出し側(dept_daemon)が判定
  ② 実況指紋 = 機械ログ語 または 生Windowsパス
  ③ 声が無い = 一人称/呼びかけ/終助詞/感嘆が1つも無い
  ④ 構造が無い = 改行が1つも無い(人格の返信は見出し・箇条書き・改行を持つ)
  実測(多人格23室・実文3583便 = hr/memory/<dept>.jsonl の reply):
    ①だけ            → 893件(24.9%)が該当 = **常に誤発火する安全網**(共通規律§3で死ぬ)
    ①+②             → 49件
    ①+②+③          → 11件(うち9件は見出し付きの正常な返信)
    ①+②+③+④       → **3件**。3件とも実況漏れの実物(llm-edu「…をDL中。」/
                        research-room「dispatch msg=… 実測で回帰の当たり: v=845…」/
                        shorts-analyst「リトライ中はPythonのstdoutバッファで…完了通知を待つ。」)
    → 人格の声で書けている便への誤発火 **0件**。

★処置(削除しない・沈黙しない)
  1. `tone_rewrite` と同じ型で **1回だけ** 人格ラッピングをやり直す(1往復・リトライ無し・
     事実の不変を機械で検査・通らなければ元文)。新方式は起こさない(§3=既に効いている型へ合流)。
  2. 通らなかったら **人格の名義では出さない** → 呼び出し側が機械名義(メタルギアMk.II)へ倒す。
     ★strip(削除)は沈黙事故を招く(改善提案部門の§8で当室が指摘し、向こうも取り下げた)。
     ★字は1文字も消さない= 中身は届く。人格の顔と声だけ汚さない= fail-loud。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    import tone_rewrite as _tr          # clean_candidate / fact_diff / gemini_ask を借りる
except Exception:                       # 借り先が壊れていてもこの段は判定だけは動く
    _tr = None

# ---------------------------------------------------------------------------
# 判定(純関数= 実行で試験できる。I/Oは一切しない)
# ---------------------------------------------------------------------------
# ②実況指紋= 機械の状態語(型_実況漏れ §3 の語彙をそのまま使う)。
MACHINE_WORDS = ("DL中", "バッチ", "flush", "stdout", "投函済", "msg=", "pending",
                 "リトライ", "quota", "HTTP 5", "完了通知", "回送済", "実測=", "(実測")
# 生Windowsパス= 「英数の語 \ 英数の語」。日本語の文中に出たら機械の吐き出し。
RE_WINPATH = re.compile(r"[A-Za-z0-9_.\-]+\\[A-Za-z0-9_.\-]+")
# ③声= ①一人称 ②相手への呼びかけ ③終助詞/口語の語尾 ④感嘆。1つでもあれば人格が喋っている。
RE_VOICE = re.compile(
    r"俺|オレ|僕|ぼく|私|わたし|あたし|わし|Chami|ちゃみ|"
    r"[ねよわなぞぜさ][。!!?？]|"
    r"わよ|かしら|だぜ|だろ|じゃん|よね|ですね|でしょ|ますね|ましょ|"
    r"[ぁ-んァ-ヶ]〜|あら|ほら|はいはい|うん|ふふ|なるほど|よし|さて|"
    r"[!!?？]")
RE_TAG_HEAD = re.compile(r"^\s*\[([^\]\n]{1,20})\]\s*")


def machine_markers(text):
    """実況指紋を列挙する(空なら因子②が立たない)。"""
    t = str(text or "")
    out = [w for w in MACHINE_WORDS if w in t]
    if RE_WINPATH.search(t):
        out.append("winpath")
    return out


def has_voice(text):
    """人格が喋っている印(因子③の否定)。"""
    return bool(RE_VOICE.search(str(text or "")))


def liveblog_verdict(text):
    """因子②③④を見る。①(タグ0個・多人格部屋)は呼び出し側の責任。

    返り値 dict: {hit, markers, why}
    ★hit=True は「人格の名義で出してはいけない実況」の意味。
    """
    t = str(text or "").strip()
    out = {"hit": False, "markers": [], "why": ""}
    if not t:
        out["why"] = "空文"
        return out
    out["markers"] = machine_markers(t)
    if not out["markers"]:
        out["why"] = "実況指紋なし"
        return out
    if has_voice(t):
        out["why"] = "声がある(一人称/呼びかけ/終助詞)"
        return out
    if "\n" in t:
        out["why"] = "構造がある(改行あり)"
        return out
    out["hit"] = True
    out["why"] = "実況指紋=%s / 声なし / 改行なし" % "+".join(out["markers"])
    return out


# ---------------------------------------------------------------------------
# 書き直し(1回だけ)= tone_rewrite と同じ作法
# ---------------------------------------------------------------------------
_LEN_MIN, _LEN_MAX = 0.8, 3.0     # 名乗り+口調を足す分、伸びる側へ広い(削る側は狭い)


def build_prompt(persona, dept, text, markers, entry=None):
    """人格ラッピングの指示文を組む(純関数=テストで文字列として検査できる)。"""
    ent = entry or {}
    fp = [x for x in (ent.get("first_person") or ()) if x]
    tails = [x for x in (ent.get("signature_tails") or ()) if x]
    lines = [
        "あなたは日本語のDiscordで「%s」という人格として話す担当です。" % persona,
        "下の文章は、機械の作業ログがそのまま返信に出てしまったものです。",
        "これを **%s 本人の言葉** に書き直してください。" % persona,
        "",
        "必ず守ること:",
        "1. 1行目は `[%s]` だけの名乗りにする(角括弧つき)。" % persona,
        "2. 事実を1つも足さない・1つも削らない。ファイル名/パス/数字/識別子はそのまま残す。",
        "3. 相手へ話しかける自然な話し言葉にする。箇条書きにしなくてよい。",
        "4. 新しい固有名詞・英数字・ファイル名を足さない(元の文に無い語を増やさない)。",
        "5. 出力は書き直した本文だけ。前置き・説明・コードブロックは付けない。",
    ]
    if fp:
        lines.append("6. 一人称は「%s」を使う。" % fp[0])
    if tails:
        lines.append("7. 語尾の癖: %s" % "、".join(tails[:4]))
    lines += ["", "機械の口調が出ている箇所: %s" % "、".join(markers or []) or "(不明)",
              "", "--- 書き直す文章 ---", str(text or "")]
    return "\n".join(lines)


def strip_tag_head(text):
    """先頭の `[名前]` を1つ落とした本文を返す(事実の比較に使う)。"""
    return RE_TAG_HEAD.sub("", str(text or ""), count=1).strip()


# 包み直しで**増えてよい**識別子= 相手の呼び名だけ。人格の声にすると呼びかけが1つ生えるため。
# ★これ以外の英数字が増えたら捏造として弾く(ファイル名/コマンド名の創作を通さない)。
ALLOW_ADD_IDENTS = ("Chami",)


def fact_kept(original, candidate, allow_add=ALLOW_ADD_IDENTS):
    """事実の不変を見る。壊れていれば理由の文字列、無事なら ""。

    ★tone_rewrite.fact_diff の**緩和版**= 数え方(hard_tokens)は借りて1本のまま(ORG-11)。
      違いは1点だけ= この段は名乗りと呼びかけを**足させる**段なので、
      許可した呼び名だけは「増えてよい」。消える側は1つも許さない。
    """
    if _tr is None:
        return ""
    a, b = _tr.hard_tokens(original), _tr.hard_tokens(candidate)
    if a["nums"] != b["nums"]:
        lost = [n for n in a["nums"] if b["nums"].count(n) < a["nums"].count(n)]
        add = [n for n in b["nums"] if a["nums"].count(n) < b["nums"].count(n)]
        return "数字が変わった(消えた=%s / 増えた=%s)" % (lost[:5], add[:5])
    lost = sorted(a["idents"] - b["idents"])
    if lost:
        return "識別子が消えた(%s)" % lost[:5]
    add = sorted(b["idents"] - a["idents"] - set(allow_add or ()))
    if add:
        return "識別子が増えた(%s)" % add[:5]
    if a["urls"] != b["urls"]:
        return "URLが変わった"
    return ""


def accept(original, candidate, persona, resolve=None):
    """書き直しを採用してよいか(純関数)。返り値: (ok:bool, why:str)。

    ★弾く方へ倒す。弾いても本文は消えない(呼び出し側が機械名義で出す)= 沈黙にならない。
    """
    o, c = str(original or "").strip(), str(candidate or "").strip()
    if not c:
        return False, "空の返し"
    if c == o:
        return False, "本文が変わっていない"
    m = RE_TAG_HEAD.match(c)
    if not m:
        return False, "1行目が名乗りになっていない"
    nm = m.group(1)
    if resolve is not None:
        if not resolve(nm):
            return False, "名乗り[%s]が名簿で解決できない" % nm
    elif nm != persona:
        return False, "名乗り[%s]がこの人格ではない" % nm
    body = strip_tag_head(c)
    if not body:
        return False, "名乗りだけで本文が無い"
    if not (_LEN_MIN * len(o) <= len(body) <= _LEN_MAX * len(o)):
        return False, "長さが帯の外(元%d字→%d字)" % (len(o), len(body))
    bad = fact_kept(o, body)              # 数字の多重集合・識別子集合・URL集合(呼び名だけ増加可)
    if bad:
        return False, bad
    if not has_voice(body):
        return False, "書き直しても声が無い"
    return True, ""


def wrap_once(persona, dept, text, markers, resolve=None, entry=None,
              ask=None, timeout=20):
    """★実況を人格の言葉へ **1回だけ** 包み直す。返り値 dict(rewrite_once と同じ形)。

      text     … 送るべき本文(採用なら包んだ後・不採用なら**元のまま**)
      ok       … 採用したか
      attempted… LLMを呼んだか
      why      … 不採用/未実施の理由(監査に残す)
    ★どんな例外でも元の本文を返す(fail-open)。採否は呼び出し側が名義の判断に使う。
    """
    out = {"text": text, "ok": False, "attempted": False, "why": "", "elapsed_ms": 0}
    try:
        if _tr is None:
            out["why"] = "tone_rewriteが無い"
            return out
        prompt = build_prompt(persona, dept, text, markers, entry=entry)
        fn = ask or (lambda p: _tr.gemini_ask(p, timeout=timeout))
        import time as _t
        t0 = _t.time()
        cand = _tr.clean_candidate(fn(prompt))
        out["elapsed_ms"] = int((_t.time() - t0) * 1000)
        out["attempted"] = True
        ok, why = accept(text, cand, persona, resolve=resolve)
        out["ok"], out["why"] = ok, why
        if ok:
            out["text"] = cand
        return out
    except Exception as e:                # 鍵無し・通信断・タイムアウト・想定外
        out["why"] = "例外: %s" % (str(e) or e.__class__.__name__)
        return out


if __name__ == "__main__":                # 手で1本試すためのCLI(本番は常駐が呼ぶ)
    import argparse
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="ケヴィン・デブライネ")
    ap.add_argument("--dept", default="")
    ap.add_argument("--file", required=True, help="判定したい本文のファイル")
    a = ap.parse_args()
    with open(a.file, encoding="utf-8") as f:
        _t = f.read()
    v = liveblog_verdict(_t)
    print("判定: hit=%s 理由=%s" % (v["hit"], v["why"]))
    if v["hit"]:
        r = wrap_once(a.persona, a.dept, _t, v["markers"])
        print("書き直し: ok=%s why=%s %dms" % (r["ok"], r["why"], r["elapsed_ms"]))
        print("---")
        print(r["text"])
