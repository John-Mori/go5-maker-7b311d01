# -*- coding: utf-8 -*-
"""ゲートI= 部門参照ゲート(DEF-kaizen-analyst-9d9bd45e55 の基盤側)

何を直すか:
  本文で「部門を指す位置」に、その部門の常駐人格名が**単独で**置かれた崩れ。
    NG 「一ノ瀬怜へ回す」(=部門を人の名前で呼んでいる) → 「プラットフォームSEへ回す」
  正本= 00_AI-HQ/org_registry.yml の <dept>.display_ja(人事部門の裁定・呼称ルール.json
  department_reference_rule)。ここは判定だけを持ち、部門名の別本は作らない。

何を直さないか(人事部門の裁定に明記された誤爆源):
  ① 人物その人への言及(「怜が言ってた」「一ノ瀬怜さん」)
  ② 併記形(「プラットフォームSE(一ノ瀬怜)」「platform-se(一ノ瀬怜)」)
  → だから単純な部分文字列一致(`"一ノ瀬怜" in text`)は採らない。**文脈の合図**で拾う。

設計の根拠(先例):
  ゲートC(呼称)/D(口調)は話者別の写像を本文へ当てて引用文を誤爆し、既定を警告のみへ倒した
  (output_gates.py L106-120=アロンソ実便1,407件で書き換わった1件が誤りだった)。
  ゲートH(kana_choice)が書き換えてよいのは「話者非依存・本文だけで判定・置換が1対1」だから。
  このゲートは H 側に寄せる= 話者に依らず、本文の文脈だけで判定し、置換は 人格名→display_ja の1対1。

fail-open: 例外は握り潰して元の本文を返す。ゲートで沈黙を作らない。
"""
import os
import re
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 5SecMovieMaker
HQ = os.path.join(os.path.dirname(ROOT), "00_AI-HQ")
ORG_REGISTRY = os.environ.get("GO5_ORG_REGISTRY") or os.path.join(HQ, "org_registry.yml")

# ---------------------------------------------------------------- 写像
# 人格名→display_ja は org_registry.yml から機械的に作る。ただし:
#  (a) 1人格が複数部門を持つ場合(アメス=7室・花海咲季=5室…)、正しい置換先が一意に決まらない。
#      → 置換対象から外す。「どの部門を指しているか」は本文からは決められない。
#  (b) シャビ・アロンソは registry 上 someday-room 付きだが、実運用の名義は研究室HQ。
#      registry が実態に追いついていない間に置換すると大事故(将来やることルームへ化ける)。
#      → 明示除外。registry 側の是正は人事部門/組織の裁定であって基盤の仕事ではない。
EXCLUDE_PERSONA = {"シャビ・アロンソ"}

# 呼び捨て・短縮形。名字と名前の切り出しは機械では当てられないので、
# 人事部門の裁定が名指しした分だけを表に持つ(増やすのは人事部門の担当)。
SHORT_FORMS = {
    "一ノ瀬怜": ["怜"],
}

_cache = {"mtime": None, "map": None}


def dept_map(path=None):
    """{人格名: (dept, display_ja)} 置換先が一意なものだけ。registry の mtime で読み直す。"""
    p = path or ORG_REGISTRY
    try:
        mt = os.path.getmtime(p)
    except Exception:
        return {}
    if _cache["mtime"] == mt and _cache["map"] is not None and path is None:
        return _cache["map"]
    rec = {}
    cur = None
    try:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                m = re.match(r"^  ([a-z0-9_-]+):\s*(#.*)?$", ln)
                if m:
                    cur = m.group(1)
                    continue
                m = re.match(r"^\s+display_ja:\s*(\S+)", ln)
                if m and cur:
                    rec.setdefault(cur, {})["ja"] = m.group(1)
                m = re.match(r"^\s+persona:\s*(\S+)", ln)
                if m and cur:
                    rec.setdefault(cur, {})["persona"] = m.group(1)
    except Exception:
        return {}
    by_persona = {}
    for dept, v in rec.items():
        if v.get("ja") and v.get("persona"):
            by_persona.setdefault(v["persona"], []).append((dept, v["ja"]))
    out = {}
    for persona, lst in by_persona.items():
        if persona in EXCLUDE_PERSONA:
            continue
        if len(lst) != 1:      # (a) 一意でない=置換先が決まらない
            continue
        out[persona] = lst[0]
    if path is None:
        _cache["mtime"] = mt
        _cache["map"] = out
    return out


# ---------------------------------------------------------------- 文脈の合図
# 部門位置と読める並び。rule ごとに名前を付けてあるのは、FP実測を rule 単位で見て
# 「どれを書き換えに格上げするか」を分けて決められるようにするため。
_ROUTE = r"(?:回し|回す|回せ|回った|回送|渡し|渡す|振っ|振る|投げ|下ろ|上げ|発注|依頼|上申|エスカレ|引き継|申し送|差し戻)"
_OWN = r"(?:担当|管轄|所管|マター|受け持|持ち場|職掌|側で|側が|側の|案件)"

RULES = [
    # A 送り先型: 「一ノ瀬怜へ回す」= 仕事の宛先=部門の位置。FP実測 0/10,590本文(下記)。
    ("A_route", re.compile(r"(?P<name>{name})(?P<tail>(?:へ|に))(?P<mid>[^。．\n]{0,12}?)" + _ROUTE)),
    # B 所管型: 「一ノ瀬怜が担当」「一ノ瀬怜の管轄」。FP実測 1/2件=書き換えない(検知のみ)。
    ("B_own",   re.compile(r"(?P<name>{name})(?P<tail>(?:が|は|の))(?P<mid>[^。．\n]{0,10}?)" + _OWN)),
    # ★C 並列型(部門名と同じ行に並ぶ)は**採らなかった**。2026-09-02の実測で71件中ほぼ全部が
    #   名簿の列挙(「アメス/ヴィルシーナ/ジェンティルドンナ/オタコン/十王星南 の5人」)=人物言及で
    #   誤爆した。部門名が同じ行に在ることは「部門の位置」の証拠にならない。
]

# 人物その人への言及= 敬称/呼びかけが付く形。ここは触らない(裁定の除外①)。
HONORIFIC = re.compile(r"^(?:さん|くん|君|ちゃん|氏|先輩|さま|様)")


def _mask_spans(text):
    """引用行・コードブロック・インラインコード・1行目の[名前]札 の範囲を返す。"""
    spans = []
    # 1行目の [名前] 札は絶対に触らない
    first_nl = text.find("\n")
    head = text if first_nl < 0 else text[:first_nl]
    if re.match(r"^\s*\[[^\]\n]{1,20}\]\s*$", head):
        spans.append((0, len(head)))
    for m in re.finditer(r"```.*?```", text, re.S):
        spans.append(m.span())
    for m in re.finditer(r"`[^`\n]+`", text):
        spans.append(m.span())
    # 鉤括弧の中は触らない。ゲートC/Dが倒れた実測(output_gates.py L106-120=引用中の「僕」を
    # 書き換えて誤りだった)と同じ踏み方をしないため。実測での損失は当たり14件中1件。
    for m in re.finditer(r"[「『][^」』\n]{0,80}[」』]", text):
        spans.append(m.span())
    pos = 0
    for line in text.split("\n"):
        if re.match(r"^\s*>", line):
            spans.append((pos, pos + len(line)))
        pos += len(line) + 1
    return spans


def _masked(i, spans):
    return any(a <= i < b for a, b in spans)


def _is_paired(text, start, end, display_ja, dept):
    """併記形(裁定の除外②)か。『プラットフォームSE(一ノ瀬怜)』『platform-se(一ノ瀬怜)』"""
    before = text[max(0, start - len(display_ja) - len(dept) - 4):start]
    if re.search(r"[(（]\s*$", before) and (display_ja in before or dept in before):
        return True
    # 逆順の併記『一ノ瀬怜(プラットフォームSE)』も人物側の表記として触らない
    after = text[end:end + len(display_ja) + len(dept) + 4]
    if re.match(r"\s*[(（]", after) and (display_ja in after or dept in after):
        return True
    return False


def _list_context(text, start, end, all_display):
    """並列型= 同じ行に他の部門名(display_ja)が在り、区切り記号で並んでいる。"""
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    line = text[ls:le if le >= 0 else len(text)]
    if not any(d in line for d in all_display):
        return False
    around = text[max(ls, start - 2):min(le if le >= 0 else len(text), end + 2)]
    return bool(re.search(r"[/／・、と]", around))


def find(text, enabled=None, path=None):
    """当たりの一覧を返す。[{rule,name,dept,display_ja,start,end,line}]"""
    hits = []
    try:
        dm = dept_map(path)
        if not dm or not text:
            return hits
        spans = _mask_spans(text)
        all_display = set(v[1] for v in dm.values())
        for persona, (dept, ja) in dm.items():
            names = [persona] + SHORT_FORMS.get(persona, [])
            for nm in names:
                # 短縮形は長い方の一部を再び拾わないように後読みで外す
                pre = r"(?<![一-龥ぁ-んァ-ヶA-Za-z])" if len(nm) <= 2 else ""
                for rname, rx in RULES:
                    if enabled and rname not in enabled:
                        continue
                    pat = re.compile(pre + rx.pattern.replace("{name}", re.escape(nm)))
                    for m in pat.finditer(text):
                        s, e = m.span("name")
                        if _masked(s, spans):
                            continue
                        if HONORIFIC.match(text[e:]):        # 除外① 人物への言及
                            continue
                        if _is_paired(text, s, e, ja, dept):  # 除外② 併記形
                            continue
                        if rname == "C_list" and not _list_context(text, s, e, all_display):
                            continue
                        ls = text.rfind("\n", 0, s) + 1
                        le = text.find("\n", e)
                        hits.append({
                            "rule": rname, "name": nm, "dept": dept, "display_ja": ja,
                            "start": s, "end": e,
                            "line": text[ls:le if le >= 0 else len(text)].strip(),
                        })
    except Exception:
        return []
    # 同じ位置に複数ルールが当たったら1件に畳む
    seen, out = set(), []
    for h in sorted(hits, key=lambda x: (x["start"], x["rule"])):
        if h["start"] in seen:
            continue
        seen.add(h["start"])
        out.append(h)
    return out


# 書き換えへ格上げする rule。★FP実測の結果だけを根拠に足すこと。
# 2026-09-02 実測(コーパス= 00_AI-HQ/departments/*/memory/*.jsonl の reply+content 10,590本文):
#   A_route 当たり13件 / 誤爆 0件 → 書き換えへ格上げ
#   B_own   当たり 2件 / 誤爆 1件(「十王星南は future 側では保持」=名簿の話)→ 検知のみ
#   C_list  当たり71件 / ほぼ全部誤爆 → ルールごと不採用
# 再測: python scripts/llm/dept_ref_gate.py --measure
FIX_RULES = set(
    x for x in (os.environ.get("GO5_DEPTREF_FIX_RULES") or "A_route").split(",") if x
)


def apply(text, fix=None, enabled=None):
    """(新しい本文, 当たり一覧) を返す。fix=False なら検知だけ(本文は素通し)。"""
    hits = find(text, enabled=enabled)
    if not hits:
        return text, []
    do_fix = FIX_RULES if fix is None else (FIX_RULES if fix else set())
    if fix is True:
        do_fix = set(h["rule"] for h in hits)
    if not do_fix:
        return text, hits
    out = text
    for h in sorted(hits, key=lambda x: -x["start"]):
        if h["rule"] in do_fix:
            out = out[:h["start"]] + h["display_ja"] + out[h["end"]:]
    return out, hits


# ---------------------------------------------------------------- 計測CLI
def _measure(paths, enabled=None):
    import glob as _glob
    files = []
    for p in paths:
        files.extend(_glob.glob(p))
    n_rec = 0
    hits = []
    for p in files:
        try:
            f = open(p, encoding="utf-8", errors="replace")
        except Exception:
            continue
        for ln in f:
            try:
                d = json.loads(ln)
            except Exception:
                continue
            for key in ("reply", "content"):
                t = d.get(key)
                if not isinstance(t, str) or not t:
                    continue
                n_rec += 1
                for h in find(t, enabled=enabled):
                    h["_src"] = "%s:%s" % (os.path.basename(p), key)
                    h["_who"] = d.get("from") or ""
                    hits.append(h)
        f.close()
    return n_rec, hits


if __name__ == "__main__":
    sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    if args and args[0] == "--measure":
        n, hits = _measure(args[1:] or [os.path.join(HQ, "departments", "*", "memory", "*.jsonl")])
        by = {}
        for h in hits:
            by[h["rule"]] = by.get(h["rule"], 0) + 1
        print("本文 %d 件を検査 / 当たり %d 件 %s" % (n, len(hits), by))
        for h in hits:
            print("---- [%s] %s→%s  (%s / %s)" % (h["rule"], h["name"], h["display_ja"], h["_src"], h["_who"]))
            print("     %s" % h["line"][:200])
    else:
        m = dept_map()
        print("置換先が一意な人格 %d 件:" % len(m))
        for k, v in sorted(m.items()):
            print("  %-14s → %s (%s)" % (k, v[1], v[0]))
