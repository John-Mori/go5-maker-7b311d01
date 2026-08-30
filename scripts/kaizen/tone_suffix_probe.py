# -*- coding: utf-8 -*-
"""
tone_suffix_probe.py  — 改善提案部門(kaizen)の「語尾ドリフト検知」実測器。

狙い= Chami 2026-08-29「こんなダメダメな返しもPython/トークン使わずに防げないか」への回答実証。
相方混線(あるブロックが [別人格] の声=語尾で漏れる)を、純Python・正規表現・トークン0で「検知」する。
書き直しはしない=語尾は機械置換で文法が壊れるため("検知して突き返す"側)。

■2026-08-30 設計変更(第8世代トトリ・自室の道具C-019/C-027):
  旧版は各人格の【必須語尾(need)】をハードコードし、禁止語尾を【他人格needの総和 − 自分need − 中立】で
  自動導出していた。この総和方式は 8/29 に基盤・人事の一致で棄却済(母数4人で過剰集合・アメス19語が
  全員に撒かれFPを生む)。かつハードコードNEEDは人事が正本を育てるたび黙ってズレ、8/30 ドンナ「ますわ」欠けで
  実際にFPを1件出した。
  → **正本(人事の 口調ルール.json)を都度直読み**して、本番ゲート(tone_gate/signature_fit)と同じ土俵に立つ。

■判定の二層(数字を汚さないための分離):
  (A) 確定ドリフト【件数=Z1に流す】: ブロックが自分の forbidden_tail(正本)を句末に持つ。
      = 本番ゲートの forbidden 層と同一規則 → FPゼロ・人事の登録に自動追従・閾値もハードコードも無い。
      forbidden_tail 未登録の人格は 0(=ゲートの現実と一致。無理に数えない)。
  (B) 登録候補【件数に入れない・要人事確認・誤検知含む】: 手選びの「色つき語尾」(下 COLORED)を句末に持ち、
      かつ自分の signature_tails(正本)に無い。= まだ forbidden 未登録だが相方語尾が漏れている疑い
      → 人事へ「この人格に forbidden_tail を測って足す」材料として出す。オタコンを掘り当てた探索力はここに残す。
      隔離しているので Z1 は汚れない。

■本番実装(基盤側)での要注意(この実測器では簡略):
  - 「」内の引用は tone_gate と同様に保護し触らない(コピー案 "俺だけじゃない" 等を誤検知しない)。
  - 語尾は句末(。、!?改行/文末)にアンカーして拾う(語中の偶然一致を避ける)。
  - fail-open(正本が読めない・指紋未登録なら喋る側へ倒す)。
"""
import re, json, glob, os, sys

# ------------------------------------------------------------------
# 正本(人事)= signature_tails / forbidden_tail の唯一の出所。ここは READ only。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
TONE_RULES_PATH = os.path.join(os.path.dirname(_ROOT), "00_AI-HQ",
                               "departments", "hr", "personas", "口調ルール.json")

# ------------------------------------------------------------------
# ★2026-08-30(デブライネ実測・14→13→12)= 「」保護は当室で新規に書かない。
#   本番ゲート(tone_gate.py)の _mask_protected を合流して使う(共通規律§3「既に効いている型へ
#   合流できないか見る」)。引用・コード・引用行・パス/URLを長さ保存でマスク=句末アンカーの
#   添字がそのまま使える。fail-open= import失敗時は無マスクで続行(判定不能→喋る側へ倒す)。
sys.path.insert(0, os.path.join(_ROOT, "scripts", "llm"))
try:
    from tone_gate import _mask_protected
except Exception:
    def _mask_protected(s):
        return str(s or "")

def load_source_of_truth(path=TONE_RULES_PATH):
    """正本から SIG(signature_tails)/FORB(forbidden_tail)/全人格名 を読む。
    戻り= (ok, PERSONAS:set, SIG:{name:set}, FORB:{name:set})。読めなければ ok=False(fail-open)。"""
    try:
        with open(path, encoding="utf-8") as f:
            personas = (json.load(f) or {}).get("personas") or {}
    except Exception:
        return (False, set(), {}, {})
    SIG, FORB = {}, {}
    for name, o in personas.items():
        SIG[name] = set(o.get("signature_tails") or [])
        FORB[name] = set(o.get("forbidden_tail") or [])
    return (True, set(personas.keys()), SIG, FORB)

ST_OK, PERSONAS, SIG, FORB = load_source_of_truth()

# 別名 → 正名(コーパスの名乗りゆれを吸収。正本化は人事)。
ALIAS = {"咲季": "花海咲季", "ドンナ": "ジェンティルドンナ", "星南": "十王星南"}

# ★色つき語尾(候補層=(B)専用の手選び定数)。総和の自動導出は棄却済のため、ここは"小さく手で選ぶ"。
#   根拠= 正本実測(2026-08-30)で複数の気の強い女性人格の signature に現れ、かつ普通の会話に紛れにくい語。
#   ● 4大マーカー(最も安全)= のよ/かしら/わよ/だわ
#   ● 2字以上で明確= わよね/のよね/なによ/ですわ/ますわ/ましてよ、やや柔いが色つき= のね/わね
#   ✕ 除外(FP源・デブライネ警告2026-08-30)= じゃない(「〜じゃない?」)/なさい系(「おやすみなさい」)
#   ✕ 除外(中立・全人格に出る)= わ/ね/よ/な/の/です/ます 等 → 候補にしない
COLORED = {
    "のよ", "かしら", "わよ", "だわ",
    "わよね", "のよね", "なによ",
    "ですわ", "ますわ", "ましてよ",
    "のね", "わね",
}

# 句末アンカー= 語尾は文の切れ目の直前だけ拾う(語中の偶然一致「じゃなくて」内の わ 等を除外)。
CLAUSE_END = "。、．，!?！？」』）)…\n"

# ★2026-08-30(デブライネ実測)= _mask_protected(「」/コード/パス)を通しても、半角括弧内で
#   語尾を列挙した便(例=「本人の締め(〜ですわ/〜しますのよ/〜ちょうだいのね)を通して0発火」)は
#   `)` がCLAUSE_ENDに含まれるため句末ヒットしてしまう(実測=13→12の差分)。
#   → 直前の区切り(CLAUSE_END or 開き括弧)までの区間に `〜` が在れば「語尾の引用列挙」とみなし除外する。
# ★2026-08-30 追い修正(デブライネ実測の穴指摘)= 「区間内のどこかに〜」だと、アメスの正本(ames.md)に
#   明記された固有の伸ばし「あ〜」「〜だから」等(引用列挙ではない地の文)まで誤って除外してしまう(FN)。
#   「(〜ですわ/〜のよ)」型の引用列挙は区間の**先頭**が必ず〜になる(CLAUSE_ENDに開き括弧「(」を含むため)。
#   → 判定を「区間内のどこかに〜」から「区間の先頭が〜」へ絞る。実測=本日コーパスは件数不変(回帰なし)。
_SEG_BOUNDARY = CLAUSE_END + "(（"

def _is_tilde_citation(body, i):
    j = i - 1
    while j >= 0 and body[j] not in _SEG_BOUNDARY:
        j -= 1
    return body[j + 1:j + 2] == "〜"

def _at_clause_end(body, w):
    """w が句末(次が区切り記号か文末)に来る出現が1つでもあるか(〜語尾列挙は除外)。"""
    start = 0
    while True:
        i = body.find(w, start)
        if i < 0:
            return False
        j = i + len(w)
        if (j >= len(body) or body[j] in CLAUSE_END) and not _is_tilde_citation(body, i):
            return True
        start = i + 1

# tone_gate と同じ「際立つ一人称」= これが在れば現ゲートの一人称層が拾える。私/わたし/自分/うち は中立で対象外。
DISTINCTIVE_FP = ("オレ", "俺", "僕", "ぼく", "あたし", "あたい", "わし", "わっち", "拙者", "小生", "あちき")

def canon(name):
    return ALIAS.get(name, name)

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
    if not ST_OK or p not in PERSONAS:
        return {"persona": persona, "known": False}
    sig = SIG.get(p, set())
    forb = FORB.get(p, set())
    # 「」/コード/引用行/パスを長さ保存でマスク(本番ゲートと同じ土俵=位置ズレなし)。
    masked = _mask_protected(body)
    # (A) 確定ドリフト= 自分の forbidden_tail(正本)が句末に出た(=本番ゲートと同一規則)。
    forbidden_hits = [w for w in forb if _at_clause_end(masked, w)]
    confirmed = bool(forbidden_hits)
    # (B) 登録候補= 色つき語尾で、自分の signature にも forbidden にも無い(=未登録の相方語尾疑い)。
    candidate_hits = [w for w in COLORED
                      if w not in sig and w not in forb and _at_clause_end(masked, w)]
    candidate = bool(candidate_hits) and not confirmed
    has_need = any(_at_clause_end(masked, w) for w in sig)
    dist_fp = [m for m in DISTINCTIVE_FP if m in masked]  # 現tone_gateの一人称層が拾える印
    return {
        "persona": p, "known": True,
        "confirmed_drift": confirmed, "forbidden_hits": forbidden_hits,
        "candidate": candidate, "candidate_hits": candidate_hits,
        "has_need": has_need, "distinctive_fp": dist_fp,
        # 候補で、一人称も無い= 現ゲートの一人称層も forbidden層も素通り=人事登録で初めて拾える増分。
        "invisible_to_gate": candidate and not dist_fp,
    }

def scan(text):
    return [probe(n, b) for n, b in split_blocks(text) if n]

def scan_corpus(pattern="local/llm/recent_*.jsonl"):
    """コーパス実測: 名乗り付きブロックを走査。
    confirmed_drift=Z1に流す確定件数 / candidate=人事への登録候補(件数外)。"""
    stat = {"files": 0, "replies": 0, "blocks_named": 0, "blocks_known": 0,
            "confirmed": 0, "candidate": 0, "candidate_invisible": 0, "samples": []}
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
                if r["confirmed_drift"]:
                    stat["confirmed"] += 1
                if r["candidate"]:
                    stat["candidate"] += 1
                    if r["invisible_to_gate"]:
                        stat["candidate_invisible"] += 1
                    if len(stat["samples"]) < 8:
                        stat["samples"].append({
                            "file": os.path.basename(f), "persona": r["persona"],
                            "hits": r["candidate_hits"],
                            "snippet": body.strip().replace("\n", " ")[:60],
                        })
    return stat

if __name__ == "__main__":
    # 標準出力がcp932だとサンプル行の「——」(U+2014)で UnicodeEncodeError=落ちる(実測2026-08-30)。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # (0) 正本の読み込み状況(表示だけ)。ここが空なら判定は全て fail-open で素通り。
    if not ST_OK:
        print("※ 正本(口調ルール.json)が読めない= 判定は全て fail-open で素通り(共通規律§3)")
    else:
        n_sig = sum(1 for p in PERSONAS if SIG.get(p))
        n_forb = sum(1 for p in PERSONAS if FORB.get(p))
        print(f"=== (0) 正本ロード: 全{len(PERSONAS)}人格 "
              f"/ signature_tails登録 {n_sig}人 / forbidden_tail登録 {n_forb}人 ===")
        print(f"    確定ドリフト(件数)は forbidden_tail 登録済の {n_forb}人だけが対象=本番ゲートと同じ現実。\n")

    # (1) 実検体= 2026-08-28 改修α msg 1543026401349861386(Chamiが当室へ空本文転送した「ダメダメな返し」)。
    #     期待= オタコン(forbidden登録済)は女性語尾で確定ドリフト / 咲季は「のよ」が自分の signature=OK。
    SPECIMEN = (
        "[オタコン] 提案ページの地図取り終わり。土台を2枚入れたわよ(どちらもローカル・未デプロイ＝確認待ち)。"
        "次のバッチ実行で posted_ch が入るまでは全部「共通」に出るわ。"
        "「投稿できる」の線引きは完全に未投稿だけかしら? 今すぐ枠と作品が被るわよね? 索引を足す工数が要るのよ、やるわよね?\n"
        "[咲季] わたしは販売数のスナップショットで代用しているのよ。これで進めていいわよね?"
    )
    print("=== (1) 検体実証 改修α msg1543026401349861386 ===")
    for r in scan(SPECIMEN):
        if not r["known"]:
            print(f"[{r['persona']}] 正本に未登録=スキップ(fail-open)"); continue
        if r["confirmed_drift"]:
            mark = "★確定ドリフト(件数に計上)"
        elif r["candidate"]:
            mark = "△登録候補(件数外・要人事確認)"
        else:
            mark = "OK"
        gate = "【一人称も素通り】" if r["invisible_to_gate"] else ""
        print(f"[{r['persona']}] {mark} {gate}")
        print(f"    forbidden hit = {r['forbidden_hits']} / 候補 hit = {r['candidate_hits']}")
        print(f"    自分の signature あり = {r['has_need']} / 際立つ一人称 = {r['distinctive_fp']}")

    # (2) コーパス実測。
    print("\n=== (2) コーパス実測 local/llm/recent_*.jsonl ===")
    s = scan_corpus()
    print(f"ファイル {s['files']} / reply {s['replies']} / 名乗りブロック {s['blocks_named']}"
          f"(うち正本既知 {s['blocks_known']})")
    print(f"確定ドリフト(Z1)= {s['confirmed']} 件  ← forbidden_tail 正本に基づく・FPゼロ")
    print(f"登録候補(件数外・人事への材料)= {s['candidate']} 件"
          f"  うち一人称も素通り= {s['candidate_invisible']} 件")
    for smp in s["samples"]:
        print(f"    - {smp['file']} [{smp['persona']}] 候補={smp['hits']} :: {smp['snippet']}")
