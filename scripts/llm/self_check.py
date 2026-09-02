# -*- coding: utf-8 -*-
"""self-check(生成後LLM検品)= 恒久策#5(イージス研究室 / 2026-09-02)。

正本= `docs/departments/kaizen-analyst/設計_4種不具合恒久策_横断_2026-09-02.md` §3。
裁定は**条件付き採用**= 全便一律ではない。掛けるのは灰色の4条件だけ:
  1. ゲートJ(構造ドリフト)発火便
  2. 呼称ルール対象の**漢字名がフル形**で出た便
  3. lang_gate の中間帯(英字20〜34字の散文=既存ゲートの閾値未満)
  4. nonjp 検知後の**再生成2周目**
純関数のゲート(A〜J)で決まる物はここへ回さない= 意味の層でしか見えない分だけを回す。

★このモジュールの生命線は **fail-open**(設計§3・§5-7「検品APIを殺した状態で便が届かなければfail」)。
  検品が落ちる・遅い・壊れた答えを返す・そもそも `claude` が居ない= **全部 None を返す**。
  None は「検品していない」であって「不合格」ではない。呼び側は None を素通しに使う。
  ここを守れないと、検品の故障がそのまま**部屋の沈黙**になる= 最悪の事故(§3)。

★4項目は**1呼び出しに束ねる**(モデルはHaiku級)。基準文と灰色条件の保守はQA室の持ち場
  (設計§4の割り振り)。基準文はコードに埋めず `local/llm/self_check_criteria.json` を先に読む
  = QAがコードを触らずに直せる。ファイルが無い/壊れていれば下の既定へ倒す(fail-open)。

★止め方= `SELF_CHECK_ON = False` の1行。呼び側は None を受け取り、今までどおり送る。
"""
import json
import os
import re
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("GO5_LOCAL_DIR") or os.path.join(ROOT, "local")
CRITERIA_PATH = os.path.join(LOCAL, "llm", "self_check_criteria.json")

SELF_CHECK_ON = True          # ★逃げ道: これを False にすれば1行で止まる
SELF_CHECK_MODEL = "haiku"    # 設計§3=Haiku級
SELF_CHECK_TIMEOUT_S = 25     # 短い上限。超えたら**無条件で通す**
MIDBAND_LO = 20               # 灰色③の帯(下)= これ未満は固有名詞・略語で日常的に出る
MIDBAND_HI = 34               # 灰色③の帯(上)= 35字以上は detect_english_paragraph の持ち場

# 基準の既定(QAが local/llm/self_check_criteria.json を置けばそちらが優先)。
DEFAULT_CRITERIA = [
    {"key": "jp_only", "text": "本文が日本語で書かれている(英語の段落・英語の見出しが混じっていない)"},
    {"key": "first_person", "text": "話者の一人称が指定どおり(別人格の一人称になっていない)"},
    {"key": "naming", "text": "人の呼び方が統一されている(同じ相手を途中で呼び分けていない・敬称の付け外しが揺れていない)"},
    {"key": "script", "text": "日本語として正当でない文字(キリル・ハングル・簡体字など)が混じっていない"},
]
CRITERIA_KEYS = tuple(c["key"] for c in DEFAULT_CRITERIA)

_KANJI_NAME_RE = re.compile(r"^[一-鿿々ヶノ]{2,12}$")
_JSON_RE = re.compile(r"\{.*\}", re.S)


def load_criteria(path=None):
    """基準文を読む。QAの保守面。**読めなければ既定**(検品ごと死なせない=fail-open)。"""
    try:
        with open(path or CRITERIA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items") if isinstance(data, dict) else data
        out = [c for c in (items or [])
               if isinstance(c, dict) and c.get("key") in CRITERIA_KEYS and c.get("text")]
        # ★4項目そろっていない表は採らない(欠けた項目が黙って検品から消えるのを防ぐ)
        if len(out) == len(CRITERIA_KEYS):
            return out
    except Exception:
        pass
    return list(DEFAULT_CRITERIA)


def kanji_fullnames(rules):
    """呼称ルールから**漢字のフル名**(2字以上連結)だけを集める= 灰色②の材料。

    ★単字(「怜」)は入れない= C-035 の誤爆源そのもの。フル形だけを灰色の合図に使う。
    ★**1人につき一番長い漢字形だけ**を採る= 「怜」「一ノ瀬」「一ノ瀬怜」の3形が在る人から
      拾うのは「一ノ瀬怜」だけ。姓だけ・名だけを混ぜると灰色が広がりすぎて全便一律に近づく
      (=設計§3で不採用にした形へ戻ってしまう)。
    ★rules が読めない/形が違う時は空= 灰色②が鳴らないだけ(fail-open)。
    """
    out = set()
    try:
        for key in ("honorific_required_targets", "target_detect_forms",
                    "speaker_target_overrides"):
            block = (rules or {}).get(key) or {}
            if not isinstance(block, dict):
                continue
            for name, forms in block.items():
                cands = [str(name).strip()]
                if isinstance(forms, list):
                    cands += [str(f).strip() for f in forms if isinstance(f, str)]
                kanji = [c for c in cands if len(c) >= 2 and _KANJI_NAME_RE.match(c)]
                if kanji:
                    out.add(max(kanji, key=len))
    except Exception:
        return set()
    return out


_TAG_LINE_RE = re.compile(r"(?m)^[ \t　]*\[([^\[\]\n]{1,24})\][ \t　]*")


def gray_reasons(text, struct_drift=False, regen_round=0, kanji_names=(), speaker=""):
    """この便を検品へ回すか= **理由の一覧**を返す(空なら回らない)。純関数・例外は空。

    ★ここに条件を足すのは QA の裁量(設計§4)。足す時は「純関数のゲートで決まらない」ことが条件。
    ★灰色②は**自分の名前を除く**。実測(2026-09-02・各部屋 memory の返信4,659便)=
      素朴に「フル名が出た便」を数えると **17.45%**(三笘薫393・花海咲季266…)で、中身は
      ほとんど**その部屋の人格が自分の名で名乗った便**だった。呼称崩れは「他人の呼び方」の話で、
      自分の名乗りは対象外だ。話者と名乗りタグを除くと **4.38%(204便)** まで落ちる
      = 設計§3の「全便の数%〜10%以下」に収まる。ここを外すと検品が全便一律に近づく。
    """
    try:
        reasons = []
        s = str(text or "")
        if struct_drift:
            reasons.append("struct_drift")
        if int(regen_round or 0) >= 2:
            reasons.append("nonjp_regen2")
        body = _TAG_LINE_RE.sub("", s)          # 名乗りタグは本文ではない
        me = str(speaker or "").strip()
        for nm in (kanji_names or ()):
            if nm and nm != me and nm in body:
                reasons.append("kanji_fullname:" + nm)
                break
        try:
            import lang_gate
            mid = lang_gate.detect_latin_midband(s, lo=MIDBAND_LO, hi=MIDBAND_HI)
            if mid:
                reasons.append("latin_midband:%d" % mid.get("latin", 0))
        except Exception:
            pass                       # 検知器が居なくても他の3条件は生きる
        return reasons
    except Exception:
        return []


def build_prompt(text, speaker="", first_person="", room="", criteria=None):
    """4項目を**1呼び出し**へ束ねた検品文を組む。返りはJSON1行だけを求める。"""
    items = criteria or load_criteria()
    lines = ["次の返信文を4項目で検品しろ。直すのではなく、判定だけを返せ。"]
    if room:
        lines.append("部屋= %s" % room)
    if speaker:
        lines.append("話者= %s" % speaker)
    if first_person:
        lines.append("話者の一人称= %s" % first_person)
    lines.append("")
    for i, c in enumerate(items, 1):
        lines.append("%d. [%s] %s" % (i, c["key"], c["text"]))
    lines.append("")
    lines.append("--- 返信文ここから ---")
    lines.append(str(text or "")[:4000])
    lines.append("--- 返信文ここまで ---")
    lines.append("")
    lines.append('出力はJSON1行だけ。説明も前置きも書くな。形式= '
                 '{"jp_only":true,"first_person":true,"naming":true,"script":true,"why":""}')
    lines.append("各項目は**満たしていれば true**。false にしたら why に理由を20字程度で書け。")
    return "\n".join(lines)


def parse_verdict(raw):
    """検品の答えを読む。**読めなければ None**(=検品していない扱い・不合格にはしない)。"""
    try:
        s = str(raw or "").strip()
        if not s:
            return None
        m = _JSON_RE.search(s)
        if not m:
            return None
        data = json.loads(m.group(0))
        if not isinstance(data, dict):
            return None
        items = {}
        for k in CRITERIA_KEYS:
            if k not in data:
                return None            # 4項目そろわない答えは採らない(部分判定で騒がない)
            items[k] = bool(data.get(k))
        ng = [k for k, v in items.items() if not v]
        return {"ok": not ng, "ng": ng, "items": items,
                "why": str(data.get("why") or "")[:120]}
    except Exception:
        return None


def _claude_runner(prompt, model, timeout_s):
    """外へ出る唯一の手= `claude -p`。検査ではここだけ偽物へ差し替える。

    ★戻りは生テキスト。失敗・タイムアウト・非ゼロ終了は **None**(呼び側で素通しになる)。
    """
    try:
        p = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s)
    except Exception:
        return None                    # claude が無い/落ちた/時間切れ= 通す
    if p.returncode != 0:
        return None
    return p.stdout


def check(text, speaker="", first_person="", room="", reasons=(), runner=None,
          model=None, timeout_s=None, criteria=None):
    """灰色便を1回だけ検品する。**返りは dict か None**。None= 検品していない(=通す)。

    ★呼び側は返りで**送信を止めてはならない**(設計§3の経路②= 送信は止めず台帳+突き返しのみ)。
    ★reasons が空なら呼ばない(灰色でない便に金を掛けない)。
    """
    if not SELF_CHECK_ON or not str(text or "").strip() or not reasons:
        return None
    t0 = time.time()
    try:
        prompt = build_prompt(text, speaker=speaker, first_person=first_person,
                              room=room, criteria=criteria)
        raw = (runner or _claude_runner)(prompt,
                                         model or SELF_CHECK_MODEL,
                                         timeout_s or SELF_CHECK_TIMEOUT_S)
    except Exception:
        return None                    # 検品の失敗で本文を巻き添えにしない
    v = parse_verdict(raw)
    if v is None:
        return None
    v["elapsed_ms"] = int((time.time() - t0) * 1000)
    v["reasons"] = list(reasons)
    v["model"] = model or SELF_CHECK_MODEL
    return v
