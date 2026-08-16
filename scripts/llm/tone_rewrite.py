#!/usr/bin/env python3
"""出力ゲートD-2(案F)= **送信直前に、崩れた便をその場で1回だけ書き直す段**。 2026-08-16

なぜ要るのか(この段が無かった時に何が起きたか):
  口調ゲートD(tone_gate)は送信直前に**検知**する。だが直せるのは
  「一人称/二人称/写像に置換先がある禁止語」だけで、**方言・敬体・指紋語尾**は
  `to=""`(書き直さない)で `remaining` へ落ちる(tone_gate.tone_corrections の分岐)。
  落ちた分は tone_audit.jsonl に貯まり、session_relay が**次の封筒**へ突き返す。
  ★★突き返しは**事後**の機構だ= **もうDiscordへ出た1便は止まらない**。
  実物= 2026-08-16 14:08:34 / dept=system-engineer / msg 1538408581752426526
  (花海咲季が「言わへん」「確認待ちや」「手ぇ」で出た便)。網を広げても(commit 2128ea6)
  検知が増えるだけで、**Chamiの目に触れるのは止まらない**。
  → 止めたいなら要るのは検知でも突き返しでもなく **送信前に書き直す段** = これ(案F)。
  Chami の Go= msg 1538456711378243715「goいらんでしょ、goするからやって」(2026-08-16)。
  C-039(寝る前Go案件)として同日中に実装。

設計(壊さないための骨):
  ★**1回だけ**。書き直しは1往復・リトライ無し。通らなければ**元の本文をそのまま送る**(fail-open)。
  ★**事実を1文字も変えさせない**。受け入れ判定は「口調が直ったか」より先に
    **数字・識別子・URL の不変**を機械で突き合わせる(共通規律§4.55「口調のために事実を曖昧にするな」)。
    LLMに"守れ"と書くのは願いだ。**守っていない物を弾く**のが機構(§3「心がけに任せない」)。
  ★**既定は「見ない」**= 書き直しの対象は `_REWRITABLE` の登録制。
    知らない reason は素通し=従来どおり突き返しへ回す(新しい判定は登録制にしろ・第17世代の教訓)。
  ★**突き返しは殺さない**。書き直して送っても、**生成側の癖は直っていない**。
    audit_tone が既に書いた event="tone" 行はそのまま残す=次の封筒への突き返しは従来どおり効く。
    ここが書くのは event="tone_rewrite"(測るための行)だけ。
  ★外へ出る手(LLM呼び出し)は**引数で差し替えられる**= 判定と分岐は本物のまま実行で検査できる
    (共通規律§3「入力を差し替えて経路を実行で通せ」)。テスト= test_tone_rewrite.py。

このモジュールは純関数＋1本のI/O(ask)だけ。ファイルも書かないしDiscordも触らない。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    import tone_gate as _tone_gate
except Exception:                       # import 失敗でも呼び出し側は死なない(fail-open)
    _tone_gate = None

# ★書き直しの対象(登録制)。ここに無い reason は**触らない**=従来どおり突き返しへ回す。
#   - dialect_kansai   = 方言。語尾の機械置換は文法が壊れるので tone_corrections は諦めた分。
#   - forbidden_word   = 写像に置換先が無い禁止語(例「手ぇ」「すまん」)。
#   - structural_polite= 地の文が敬体へ倒れた便。置換ではなく書き直しでしか戻らない。
#   - signature_absent = 常体だが指紋語尾が1つも無い便(Chami「ずっとこんな感じでいれてるけど効かないね」)。
#   ★入れていない物と理由=
#     first_person_mismatch  … 置換先が一意でないから残っている分。LLMに当てさせるな(誤った人格になる)。
#     speaker_misattributed / self_third_person … 口調ではなく**話者**の問題。ゲートFと生成側の管轄。
_REWRITABLE = ("dialect_kansai", "forbidden_word", "structural_polite", "signature_absent")

_REASON_JA = {
    "dialect_kansai": "関西弁(方言)が出ている",
    "forbidden_word": "この人格の禁止語が出ている",
    "structural_polite": "地の文が敬体(です・ます)へ倒れている",
    "signature_absent": "この人格の指紋語尾が1つも出ていない",
}

# 事実の不変量。**元にあった物が全部あり、無かった物が増えていない**ことだけを見る。
_NUM = re.compile(r"[0-9０-９]+")
# 識別子= ASCIIで始まる語(ファイル名・パス・commitハッシュ・関数名・msg_id・型番)。
# ★日本語は空白で切れないので**必ずASCIIから始める**(tone_gate の _PATHISH と同じ轍を踏まない)。
_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_./\\:+~%@-]{2,}")
_URL = re.compile(r"https?://\S+")
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.S)

# 書き直し後の長さの帯。切り詰め(要約)や膨張(説明の追加)を弾く。
_LEN_MIN, _LEN_MAX = 0.5, 1.8


def targets(remaining):
    """`remaining`(機械が直せなかった検知)のうち、**書き直しの対象**だけを返す。"""
    out = []
    for v in (remaining or ()):
        if str((v or {}).get("reason") or "") in _REWRITABLE:
            out.append(v)
    return out


def hard_tokens(text):
    """事実の指紋を取る= 数字の並び・ASCII識別子・URL。

    ★数字は**多重集合(出現回数込み)**で見る= 「4件」が「3件」になった / 消えたを弾く。
    ★識別子とURLは集合で見る= 大小や重複より「在るか」が本質。
    """
    s = str(text or "")
    return {
        "nums": sorted(_NUM.findall(s)),
        "idents": set(_IDENT.findall(s)),
        "urls": set(_URL.findall(s)),
    }


def clean_candidate(raw):
    """LLMの返しから本文だけを取り出す(囲みコードブロック・前後の空白を落とす)。"""
    s = str(raw or "").strip()
    m = _FENCE.match(s)
    if m:
        s = m.group(1).strip()
    return s


def fact_diff(original, candidate):
    """事実の不変量が壊れていれば**理由の文字列**を返す。無事なら ""。"""
    a, b = hard_tokens(original), hard_tokens(candidate)
    if a["nums"] != b["nums"]:
        lost = [n for n in a["nums"] if b["nums"].count(n) < a["nums"].count(n)]
        add = [n for n in b["nums"] if a["nums"].count(n) < b["nums"].count(n)]
        return "数字が変わった(消えた=%s / 増えた=%s)" % (lost[:5], add[:5])
    if a["idents"] != b["idents"]:
        lost = sorted(a["idents"] - b["idents"])
        add = sorted(b["idents"] - a["idents"])
        return "識別子が変わった(消えた=%s / 増えた=%s)" % (lost[:5], add[:5])
    if a["urls"] != b["urls"]:
        return "URLが変わった"
    return ""


def accept(original, candidate, tgt, after_verdicts, before_reasons=()):
    """書き直しを**採用してよいか**を決める(純関数)。返り値: (ok:bool, why:str)。

    before_reasons= 書き直し**前**に既にあった reason の一覧。ここに在った物は
      「増えた」と数えない= 元から居る崩れ(話者の取り違え等)はこの段の管轄ではないので、
      それを理由に書き直しを弾かない。
    ★弾く方へ倒す。落ちたら元の本文が出るだけ=**沈黙にはならない**(可用性は無傷)。
    """
    o, c = str(original or ""), str(candidate or "")
    if not c:
        return False, "空の返し"
    if c == o:
        return False, "本文が変わっていない"
    if not (_LEN_MIN * len(o) <= len(c) <= _LEN_MAX * len(o)):
        return False, "長さが帯の外(元%d字→%d字)" % (len(o), len(c))
    # ★名乗りタグを増やすな= `[名前]` は名義の解決に使われる。増やすと別人の名義で出る。
    tag = re.compile(r"^\s*\[[^\]\n]{1,20}\]", re.M)
    if len(tag.findall(c)) > len(tag.findall(o)):
        return False, "名乗りタグ[名前]が増えた"
    bad = fact_diff(o, c)
    if bad:
        return False, bad
    # 口調の側= 狙った崩れが**全部消えている**こと。半分だけ関西弁の文を送らない。
    want = set(str((v or {}).get("reason") or "") for v in (tgt or ()))
    after = [str((v or {}).get("reason") or "") for v in (after_verdicts or ())]
    still = sorted(set(after) & want)
    if still:
        return False, "崩れが残っている(%s)" % "/".join(still)
    # 新しい崩れを作っていないこと(直したつもりで別の人格の声になる事故を防ぐ)。
    before = set()
    for v in (tgt or ()):
        before.add(str((v or {}).get("reason") or ""))
    new = sorted(set(after) - before - set(before_reasons or ()))
    if new:
        return False, "別の崩れが増えた(%s)" % "/".join(new)
    return True, ""


def build_prompt(persona, entry, text, tgt):
    """書き直しの指示文を組む(純関数=テストで文字列として検査できる)。"""
    ent = entry or {}
    fp = [x for x in (ent.get("first_person") or ()) if x]
    tails = [x for x in (ent.get("signature_tails") or ()) if x]
    forb = [x for x in (ent.get("forbidden") or ()) if x]
    lines = []
    lines.append("あなたは文章の**口調だけ**を直す校正器だ。次の本文を、指定の人格の声に書き直す。")
    lines.append("")
    lines.append("【人格】%s" % (persona or ""))
    if fp:
        lines.append("【一人称(正)】%s" % " / ".join(fp))
    if tails:
        lines.append("【この人格の語尾(指紋)】%s" % " / ".join(tails))
    if ent.get("plain_only"):
        lines.append("【文体】常体のみ。地の文に「です・ます」を使わない。")
    if forb:
        lines.append("【この人格が使わない語】%s" % " / ".join(forb[:20]))
    lines.append("")
    lines.append("【直す点(機械が検知した崩れ)】")
    for v in (tgt or ()):
        r = str((v or {}).get("reason") or "")
        lines.append("- %s: %s" % (_REASON_JA.get(r, r), (v or {}).get("marker") or ""))
    lines.append("")
    lines.append("【絶対に守る規則】")
    lines.append("1. 事実を変えない。数字・時刻・件数・版・commitハッシュ・ファイル名・パス・URL・"
                 "msg_id・人名は**1文字も変えない**(1つでも変えたら不採用になる)。")
    lines.append("2. 内容を足さない・削らない。文の数と順序を保つ。要約しない。")
    lines.append("3. 変えてよいのは語尾・言い回し・一人称だけ。")
    lines.append("4. 「」内の引用・`コード`・行頭 > の引用行・箇条書きの記号は触らない。")
    lines.append("5. 出力は**書き直した本文だけ**。前置き・説明・囲み(```)・見出しを書かない。")
    lines.append("")
    lines.append("【本文】")
    lines.append(str(text or ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 外へ出る手(ここだけがI/O)。既定は Gemini flash= 安い・速い・C-017で使用許可済み。
# ---------------------------------------------------------------------------
def _read_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    p = os.path.join(ROOT, "local", "gemini_api_key.txt")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def gemini_ask(prompt, timeout=20, model="gemini-flash-lite-latest"):
    """1回だけ叩く。リトライしない・フォールバックしない(送信直前に待たせない)。

    ★失敗は例外で返す=呼び出し側が握り潰して元の本文を送る(fail-open)。
    """
    import urllib.request
    key = _read_key()
    if not key:
        raise RuntimeError("Gemini APIキーが無い")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + model + ":generateContent?key=" + key)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            # 元文と同じ長さが要る(要約させない)。日本語はおおよそ1文字1トークン。
            "maxOutputTokens": max(512, min(4096, int(len(prompt) * 1.2))),
        },
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    try:
        return d["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return ""                      # 安全フィルタ等で候補が無い= 書き直し無し


def rewrite_once(persona, dept, text, remaining, rules, ask=None, timeout=20):
    """★案Fの本体= 崩れた便を**1回だけ**書き直して、通れば書き直した本文を返す。

    返り値 dict:
      text     … 送るべき本文(採用なら書き直し後・不採用なら**元のまま**)
      ok       … 採用したか
      attempted… LLMを呼んだか(対象0件・鍵無し・例外は False/理由付き)
      why      … 不採用/未実施の理由(監査に残す)
      targets  … 対象にした reason の一覧
      after    … 書き直し後に残った検知の reason 一覧(採用時は空のはず)
    ★どんな例外でも元の本文を返す= この段が配送を殺さない(fail-open 厳守)。
    """
    out = {"text": text, "ok": False, "attempted": False, "why": "",
           "targets": [], "after": [], "elapsed_ms": 0}
    try:
        tgt = targets(remaining)
        if not tgt:
            out["why"] = "対象なし"
            return out
        out["targets"] = sorted(set(str(v.get("reason") or "") for v in tgt))
        if _tone_gate is None or not rules:
            out["why"] = "ゲート無効(rules未ロード)"
            return out
        ent = _tone_gate._persona_entry(rules, persona) or {}
        if not ent:
            out["why"] = "写像にこの人格が無い"
            return out
        prompt = build_prompt(persona, ent, text, tgt)
        fn = ask or (lambda p: gemini_ask(p, timeout=timeout))
        import time as _t
        t0 = _t.time()
        cand = clean_candidate(fn(prompt))
        out["elapsed_ms"] = int((_t.time() - t0) * 1000)
        out["attempted"] = True
        after = _tone_gate.tone_verdicts(persona, dept, cand, rules) or []
        out["after"] = sorted(set(str(v.get("reason") or "") for v in after))
        # 元から居た崩れ(この段の管轄外)は「増えた」と数えない。
        before_all = sorted(set(str((v or {}).get("reason") or "")
                                for v in (remaining or ())))
        ok, why = accept(text, cand, tgt, after, before_all)
        out["ok"], out["why"] = ok, why
        if ok:
            out["text"] = cand
        return out
    except Exception as e:                       # 鍵無し・通信断・タイムアウト・想定外
        out["why"] = "例外: %s" % (str(e) or e.__class__.__name__)
        return out


if __name__ == "__main__":                        # 手で1本試すためのCLI(本番は常駐が呼ぶ)
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", required=True)
    ap.add_argument("--dept", default="")
    ap.add_argument("--file", required=True, help="書き直したい本文のファイル")
    a = ap.parse_args()
    _rules = _tone_gate.load_tone_rules(os.path.join(
        ROOT, "..", "00_AI-HQ", "departments", "hr", "personas", "口調ルール.json"))
    _txt = open(a.file, encoding="utf-8").read()
    _rem = _tone_gate.tone_corrections(a.persona, a.dept, _txt, _rules).get("remaining") or []
    _res = rewrite_once(a.persona, a.dept, _txt, _rem, _rules)
    print(json.dumps({k: v for k, v in _res.items() if k != "text"}, ensure_ascii=False))
    print("----")
    print(_res["text"])
