# -*- coding: utf-8 -*-
"""
tone_suffix_probe.py  — 改善提案部門(kaizen)の「語尾ドリフト検知」実証プローブ＋実測器(型の下書き)。

狙い= Chami 2026-08-29「こんなダメダメな返しもPython/トークン使わずに防げないか」への回答実証。
現行 tone_gate.py は「一人称の食い違い」だけを見る(オレ/俺/僕/…)。
だが相方混線の多くは【一人称が本文に一つも出ず、語尾だけが相方の声】で漏れる。
→ 純Python・正規表現・トークン0で「検知」できる(書き直しはしない=語尾は機械置換で文法が壊れるため。
   関西弁と同じく"検知して突き返す"側)。

★これは基盤(tone_gate)へ渡す前の【型の下書き】。本番配線=プラットフォームSE/イージス研究室、
  語尾指紋データの正本=人事(characterfile)。当室は「型を書き上げて渡す」まで。

■設計の要(この版で改善):
  指紋は各人格の【必須語尾(need)＝その人格の肯定的な語尾アイデンティティ】だけを登録する。
  「禁止語尾」は手で列挙しない=【他人格の必須語尾の総和 − 自分の必須語尾】として自動導出する(foreign)。
  → 人事は「この子は文末をどう締めるか」だけ書けばよく、相方の数だけ禁止リストを保守しなくて済む。

■ドリフト判定: そのブロックに foreign語尾 が1つ以上 かつ 自分の need語尾 が0 のとき = 相方の声に染まった疑い。

■本番実装での要注意(この下書きでは簡略):
  - 「」内の引用は tone_gate と同様に保護し触らない(コピー案 "俺だけじゃない" 等を誤検知しない)。
  - 語尾は句末(。、!?改行/文末)にアンカーして拾う(語中の偶然一致を避ける)。
  - fail-open(指紋未登録・判定不能なら喋る側へ倒す)。
"""
import re, json, glob, os

# 人格別の【必須語尾】だけを登録(正本は characterfile / 人事)。禁止語尾は書かない=自動導出する。
NEED = {
    "オタコン":          ["だよ", "だね", "なんだ"],
    "トトリ":            ["です", "ます", "ましょう", "ですね"],
    "花海咲季":          ["だわ", "わよ", "のよ"],
    "ジェンティルドンナ": ["ですわ", "ましてよ"],
    "アメス":            ["わよ", "のよ", "なによ"],
    "田中琴葉":          ["です", "だね", "だよ"],
    "ヴィルシーナ":      ["わ", "のよ", "かしら"],
    "十王星南":          ["かしら", "のよ", "わ", "ね"],
}
# 別名 → 正名(コーパスの名乗りゆれを吸収。正本化は人事)
ALIAS = {"咲季": "花海咲季", "ドンナ": "ジェンティルドンナ", "星南": "十王星南"}

# 中立語尾= 誰の声でもない汎用の締め。異物から必ず除外する(丁寧の ます/です や1字助詞 わ/ね/よ は
# 全人格に出得るので"相方混線"の証拠にならない=誤検知源。★崩れの証拠は かしら/わよ/のよ 等の"2字以上の色つき語尾"に限る)。
NEUTRAL = {"です", "ます", "ました", "ません", "ですね", "ますね", "わ", "ね", "よ", "な", "の"}

# 句末アンカー= 語尾は文の切れ目の直前だけ拾う(語中の偶然一致「じゃなくて」内の わ 等を除外)。
CLAUSE_END = "。、．，!?！？」』）)…\n"

def _at_clause_end(body, w):
    """w が句末(次が区切り記号か文末)に来る出現が1つでもあるか。"""
    start = 0
    while True:
        i = body.find(w, start)
        if i < 0:
            return False
        j = i + len(w)
        if j >= len(body) or body[j] in CLAUSE_END:
            return True
        start = i + 1

# tone_gate と同じ「際立つ一人称」= これが在れば現ゲートが拾える。私/わたし/自分/うち は中立で対象外。
DISTINCTIVE_FP = ("オレ", "俺", "僕", "ぼく", "あたし", "あたい", "わし", "わっち", "拙者", "小生", "あちき")

def canon(name):
    return ALIAS.get(name, name)

def foreign_suffixes(persona):
    """他人格の必須語尾の総和 − 自分の必須語尾。= この人格にとって"異物"の語尾。"""
    mine = set(NEED.get(persona, []))
    other = set()
    for p, s in NEED.items():
        if p != persona:
            other |= set(s)
    return sorted((other - mine) - NEUTRAL, key=len, reverse=True)  # 中立語尾を除外・長い語尾から

BLOCK_RE = re.compile(r"\[([^\]]+)\]")

def split_blocks(text):
    parts = BLOCK_RE.split(text)
    if len(parts) == 1:
        return [("", text)]
    out, i = [], 1
    while i < len(parts):
        name = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        out.append((name, body))
        i += 2
    return out

def probe(persona, body):
    p = canon(persona)
    if p not in NEED:
        return {"persona": persona, "known": False, "drift": None}
    foreign = [w for w in foreign_suffixes(p) if _at_clause_end(body, w)]
    has_need = any(_at_clause_end(body, w) for w in NEED[p])
    dist_fp = [m for m in DISTINCTIVE_FP if m in body]  # 現tone_gateが拾える印
    drift = bool(foreign) and not has_need
    return {
        "persona": p, "known": True,
        "foreign_hits": foreign, "has_need": has_need,
        "distinctive_fp": dist_fp,          # ← 空なら【現tone_gateは素通り】
        "invisible_to_gate": drift and not dist_fp,
        "drift": drift,
    }

def scan(text):
    return [probe(n, b) for n, b in split_blocks(text) if n]

def scan_corpus(pattern="local/llm/recent_*.jsonl"):
    """コーパス実測: 名乗り付きブロックを走査し、崩れ数/そのうち現ゲート素通り数を数える。"""
    stat = {"files": 0, "replies": 0, "blocks_named": 0, "blocks_known": 0,
            "drift": 0, "drift_invisible": 0, "samples": []}
    for f in sorted(glob.glob(pattern)):
        stat["files"] += 1
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rep = rec.get("reply") or ""
            if not rep:
                continue
            stat["replies"] += 1
            for name, body in split_blocks(rep):
                if not name:
                    continue
                stat["blocks_named"] += 1
                r = probe(name, body)
                if not r["known"]:
                    continue
                stat["blocks_known"] += 1
                if r["drift"]:
                    stat["drift"] += 1
                    if r["invisible_to_gate"]:
                        stat["drift_invisible"] += 1
                        if len(stat["samples"]) < 6:
                            stat["samples"].append({
                                "file": os.path.basename(f), "persona": r["persona"],
                                "foreign": r["foreign_hits"],
                                "snippet": body.strip().replace("\n", " ")[:60],
                            })
    return stat

if __name__ == "__main__":
    # (1) 実検体= 2026-08-28 改修α msg 1543026401349861386(Chamiが当室へ空本文転送した「ダメダメな返し」)
    SPECIMEN = (
        "[オタコン] 提案ページの地図取り終わり。土台を2枚入れたわよ(どちらもローカル・未デプロイ＝確認待ち)。"
        "次のバッチ実行で posted_ch が入るまでは全部「共通」に出るわ。"
        "「投稿できる」の線引きは完全に未投稿だけかしら? 今すぐ枠と作品が被るわよね? 索引を足す工数が要るのよ、やるわよね?\n"
        "[咲季] わたしは販売数のスナップショットで代用しているのよ。これで進めていいわよね?"
    )
    print("=== (1) 検体実証 改修α msg1543026401349861386 ===")
    for r in scan(SPECIMEN):
        if not r["known"]:
            print(f"[{r['persona']}] 指紋未登録=スキップ(fail-open)"); continue
        mark = "★ドリフト検知" if r["drift"] else "OK"
        gate = "【現ゲート素通り】" if r["invisible_to_gate"] else ""
        print(f"[{r['persona']}] {mark} {gate}")
        print(f"    異物語尾hit = {r['foreign_hits']}")
        print(f"    自分の必須語尾あり = {r['has_need']}")
        print(f"    際立つ一人称 = {r['distinctive_fp']}  ← 空なら現tone_gateは拾えない")

    # (2) コーパス実測
    print("\n=== (2) コーパス実測 local/llm/recent_*.jsonl ===")
    s = scan_corpus()
    print(f"ファイル {s['files']} / reply {s['replies']} / 名乗りブロック {s['blocks_named']}"
          f"(うち指紋既知 {s['blocks_known']})")
    print(f"語尾ドリフト検知 = {s['drift']} 件")
    print(f"  うち【際立つ一人称ゼロ=現tone_gate素通り】= {s['drift_invisible']} 件"
          f"  ← ここが語尾指紋で初めて拾える増分")
    if s["blocks_known"]:
        print(f"  既知ブロックに対する崩れ率 = {s['drift']/s['blocks_known']*100:.1f}% "
              f"/ 素通り率 = {s['drift_invisible']/s['blocks_known']*100:.1f}%")
    for smp in s["samples"]:
        print(f"    - {smp['file']} [{smp['persona']}] 異物={smp['foreign']} :: {smp['snippet']}")
