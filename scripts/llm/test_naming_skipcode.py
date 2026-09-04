#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼称ゲートC「見送りの理由コード(skip)」の試験(2026-09-04・イージス研究室)。

引き金= 人事部門ククール msg 1545235859899555840
  「applied が空= ゲートが出力を書き換えていない。安全4ペアだけ有効化してくれ」

★この試験が固定する事実は3つ:
  (1) 安全クラス(裸姓→姓+さん)は **hr-room 以外では既に有効**= applied は空でない。
  (2) hr-room で有効化すると **ククール自身の依頼文が化ける**(依頼の中の
      「・三笘 → 三笘さん」が「・三笘さん → 三笘さん」になる)= だから開けない。
  (3) 今回の変更は **台帳の列を1本足しただけ**= 本文の扱いは1文字も変えていない。
      (3)は .bak(変更前の実装)を別モジュールとして読み込み、同じ本文を通して
      `fixed` と `applied` が完全一致することで示す=ソースの文字列一致で済ませない。

  python scripts/llm/test_naming_skipcode.py            … 通常(全部緑であるべき)
  python scripts/llm/test_naming_skipcode.py --mutate N … わざと壊す(赤くなるべき)
      1: 理由コードを残さない(_remain が素通し)
      2: 理由コードを1語に潰す(全部 vocative_only)
      3: hr-room でも地の文を直す(=ククールの依頼どおり開けた場合)
"""
import importlib.machinery
import importlib.util
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
HQ = os.path.normpath(os.path.join(ROOT, "..", "00_AI-HQ"))
RULES_PATH = os.path.join(HQ, "departments", "hr", "personas", "呼称ルール.json")
sys.path.insert(0, HERE)

import naming_gate as ng                                  # noqa: E402

MUTATE = 0
for i, a in enumerate(sys.argv):
    if a == "--mutate" and i + 1 < len(sys.argv):
        MUTATE = int(sys.argv[i + 1])

PASS = FAIL = 0


def ok(cond, name, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [NG] {name}" + (f"  … {detail}" if detail else ""))


# ── わざと壊す(must-fail) ────────────────────────────────────────
if MUTATE == 1:
    ng._remain = lambda v, code: v
elif MUTATE == 2:
    def _one(v, code):
        try:
            v["skip"] = "vocative_only"
        except Exception:
            pass
        return v
    ng._remain = _one
elif MUTATE == 3:
    # ★C-053= 壊した側も「動く別の実装」。ククールの依頼どおり
    #   「人事部門でも安全クラスは直す」を実装する(素直に voc_only を殺す)。
    ng.VOCATIVE_ONLY_DEPTS = set()


RULES = ng.load_naming_rules(RULES_PATH)
if not RULES:
    print(f"!! 呼称ルールが読めない: {RULES_PATH}")
    sys.exit(2)

# ── 検体 ─────────────────────────────────────────────────────────
# ククールの依頼文そのものの形(msg 1545235859899555840 の実物から抜いた3行)。
KUKURU = (
    "安全クラス(裸姓→既定敬称・単一・付与のみ・名前部分のswap無し)= 実測:\n"
    "・三笘   → 三笘さん   (allowed 単一)\n"
    "・デブライネ → デブライネさん (allowed 単一)\n"
    "・アロンソ  → アロンソさん  (default 一意)\n"
)
# 呼んでいる=直してよい。★話者はククール以外(ククールは呼び捨て特例の持ち主なので
#   モドリッチが違反にならない= 検体に混ぜると「効いていない」に見える)。
USE = "三笘に確認した。モドリッチから便が来た。"
FULLNAME = "報告者は三笘薫だ。"                        # 姓+名=直すと壊れる

print(f"=== 呼称ゲートC 見送り理由コード 試験 (mutate={MUTATE}) ===")

# ── 1) 安全クラスは hr-room 以外では既に効いている ──────────────
print("\n[1] 前提の検算(『applied が空』は部屋によりけり)")
# ★話者は「どちらの対象にも例外を持たない人格」を選ぶ(トトリ)。ククールは
#   モドリッチ呼び捨て特例、オタコン/星南/莉波は「三笘くん」の例外を持つ=
#   検体に混ぜると既定が効いているのに「効いていない」に見える。
r = ng.naming_corrections("トトリ", "aegis-gl", USE, RULES)
ok(r["fixed"] == "三笘さんに確認した。モドリッチさんから便が来た。",
   "★安全クラスは研究室では**既に**自動置換されている", repr(r["fixed"]))
ok(len(r["applied"]) == 2, "applied は空ではない", json.dumps(r["applied"], ensure_ascii=False))

# ── 2) hr-room で開けるとククール自身の依頼文が化ける ────────────
print("\n[2] 開けた場合に何が起きるか(ククールの依頼文そのもの)")
r_off = ng.naming_corrections("ККール", "hr-room", KUKURU, RULES)
ok(r_off["fixed"] == KUKURU,
   "今の設定では依頼文は1文字も変わらない", repr(r_off["fixed"][:60]))
r_on = ng.naming_corrections("ККール", "hr-room", KUKURU, RULES, vocative_only=False)
ok("・三笘さん   → 三笘さん" in r_on["fixed"],
   "★開けると「・三笘 → 三笘さん」が「・三笘さん → 三笘さん」に化ける",
   repr(r_on["fixed"][:80]))
ok(r_on["fixed"].count("さん  → アロンソさん") == 1 or "アロンソさん  → アロンソさん" in r_on["fixed"],
   "★アロンソの行も同じ形で化ける", repr(r_on["fixed"]))
ok(len(r_on["applied"]) >= 3,
   "化けるのは**安全クラスだけ**でも3ペア以上", json.dumps(r_on["applied"], ensure_ascii=False))

# ── 3) 見送りの理由が1行ごとに残る ──────────────────────────────
print("\n[3] 見送りの理由コード(skip)")
skips = {v.get("found"): v.get("skip") for v in r_off["remaining"]}
ok(all(s == "vocative_only" for s in skips.values()) and skips,
   "人事部門の地の文は skip='vocative_only'", json.dumps(skips, ensure_ascii=False))

r_full = ng.naming_corrections("トトリ", "aegis-gl", FULLNAME, RULES)
sk_full = [v.get("skip") for v in r_full["remaining"]]
ok(r_full["fixed"] == FULLNAME, "姓+名は本文を触らない(従来どおり)", repr(r_full["fixed"]))
ok(sk_full and all(s in ("unsafe_after", "mention", "whole_swap_not_vocative")
                   for s in sk_full),
   "姓+名の見送りは境界/言及の理由で残る", json.dumps(sk_full, ensure_ascii=False))

ok(all(v.get("skip") in ng.SKIP_CODES
       for v in list(r_off["remaining"]) + list(r_full["remaining"])),
   "理由コードは表(SKIP_CODES)の中の語だけ",
   json.dumps([v.get("skip") for v in r_off["remaining"]], ensure_ascii=False))
ok(len(set(skips.values()) | set(sk_full)) >= 2,
   "★理由は1語に潰れていない(見送りの型を数え分けられる)",
   json.dumps(sorted(set(skips.values()) | set(sk_full)), ensure_ascii=False))

# ── 4) 本文の扱いは変えていない(.bak と突き合わせ) ──────────────
print("\n[4] 退行(変更前の実装と本文が完全一致する)")
BAK = os.path.join(HERE, "naming_gate.py.bak_20260904_skipcode")
old = None
try:
    # ★拡張子が .py でないので loader を明示する(spec_from_file_location だけだと
    #   loader=None のまま返り、静かに読み込めない=退行の突き合わせが空振りする)。
    loader = importlib.machinery.SourceFileLoader("naming_gate_old", BAK)
    spec = importlib.util.spec_from_loader("naming_gate_old", loader)
    old = importlib.util.module_from_spec(spec)
    loader.exec_module(old)
except Exception as e:      # noqa: BLE001
    print(f"  (.bak を読めない: {e})")

CORPUS = [KUKURU, USE, FULLNAME,
          "アロンソ、頼む。", "アロンソが裁定する。",
          "**三笘薫** を「三笘」と呼んでいる(正=**三笘さん**)",
          "人格= オタコン、ククール、ケヴィン・デブライネ、シャビ・アロンソ、三笘薫",
          "", "ふつうの本文です。"]
WHO = [("ククール", "hr-room"), ("ククール", "aegis-gl"),
       ("ケヴィン・デブライネ", "hq"), ("シャビ・アロンソ", "aegis-gl")]
if old is not None:
    diff = []
    for t in CORPUS:
        for who, dept in WHO:
            a = ng.naming_corrections(who, dept, t, RULES)
            b = old.naming_corrections(who, dept, t, RULES)
            if a["fixed"] != b["fixed"] or len(a["applied"]) != len(b["applied"]):
                diff.append((who, dept, t[:30]))
    ok(not diff, "★変更前と本文・applied が完全一致(足したのは台帳の列だけ)",
       json.dumps(diff, ensure_ascii=False))
    ok(not any("skip" in json.dumps(v, ensure_ascii=False)
               for v in old.naming_corrections("ККール", "hr-room", KUKURU,
                                               RULES)["remaining"]),
       "変更前には skip が無い(=この列は今回足したものだ)")
else:
    ok(False, "★.bak が読めない(退行を突き合わせられない)", BAK)

# ── 5) fail-open ────────────────────────────────────────────────
print("\n[5] fail-open")
ok(ng.naming_corrections("ククール", "hr-room", KUKURU, None)["fixed"] == KUKURU,
   "ルールが無ければ素通し")
ok(ng.naming_corrections("ククール", "hr-room", "", RULES)["fixed"] == "", "空本文で落ちない")
ok(ng._remain(None, "vocative_only") is None, "_remain は壊れた入力でも例外を出さない")

print(f"\n=== {PASS}/{PASS + FAIL} PASS ===")
sys.exit(1 if FAIL else 0)
