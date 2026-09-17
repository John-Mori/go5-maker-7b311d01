# -*- coding: utf-8 -*-
"""毎朝の「⚠️(自動)生成不良」集計(改善提案部門)。

なぜ要るか= Chami依頼 2026-09-17(便 msg=1549984430041595997)
  「⚠️ のやつちゃんと数えたりして欲しいなこれから。0の日は何も言わなくていいよ」
そして追いの依頼 2026-09-17(便 msg=1549987372178087949)=
  「ただ、実際は問題ない時もあるから本当に問題があるのかどうか確かめてね」
  → 生の⚠️件数は**誤検知(偽陽性)を含む**。数えるだけでなく「本当に生成不良か」を
    こちらで確かめてから報告する。確かめ方は下の2段(_flag_kind / _verify)。

「⚠️(自動)生成不良」とは=
  dept_daemon.py が bot の出力に**自動で付ける自己申告フラグ**。生成そのものが
  壊れている(非日本語混入・名乗り無し)のを機械が検知した印で、絵文字監視の
  「Chamiが押したスタンプ」台帳とは**別物**(あちらは「機械の印…は除外」と明記)。

なぜ生の件数が水増しになるか(実測 send_audit.jsonl 20件を1件ずつ見た・2026-09-17)=
  (A) 自室(改善提案)・QA・HQ・研究室は**この不具合を論じる部屋**なので、字例
      (无・实况・进捗 等)や警告文そのものを引用する。dept_daemon の検知は引用でも
      鳴る(lang_gate.detect_simplified の docstring「これは誤検出ではなく仕様」)。
  (B) 人格が地の文で警告を語尾変えして書いた文(例「…要確認なのよ」)や、当室が
      「⚠️を数える仕組みを入れた」と報告した便は、**機械が付けたフラグではない**のに
      "⚠️(自動)生成不良" の文字列を含む=素朴な部分一致だと数に入ってしまう。

確かめ方は2段=
  1. _flag_kind: 本文の**末尾の非空行**が dept_daemon の *_WARN 定数と**完全一致**した
     時だけ「機械が実際に付けたフラグ」とみなす。daemon は `本文 + "\\n\\n" + 警告文`
     で必ず末尾に貼る(_append_nonjp_warn / _append_narration_warn)。中間に在る/語尾が
     違う/報告文は**フラグではない**=数えない。→ (B)を落とす。
  2. _verify: フラグ済みの本文から、コード柵・インラインコード・URL・引用符の中を
     長さ保存で潰し(lang_gate._mask_code_spans を再利用)、素の本文に混入字が**残るか**
     を lang_gate の検知器で見直す。残れば「本物疑い」、引用の中だけなら「引用・報告」。
     → (A)を「引用・報告(=実際は問題ない)」へ仕分ける。

正直さ(共通規律§1)=
  ・件数は send_audit.jsonl(実際に送られた本文)を**読んで**数える。推測しない。
  ・「本物疑い(nonjp)」+「実況(名乗り無し)」が0件の日は**何も返さない**
    (render が "" を返す= 便に何も乗らない。Chami「0の日は何も言わない」+「実際は
     問題ない時もある」の両方を満たす=問題が無い日は黙る)。
  ・仕分けは**推し**であって断定ではない。だから本物疑いは部屋と前後文を必ず添え、
    「引用・誤検知として数から外した件数」も併記する(取りこぼしも水増しも隠さない)。

手で試す= PYTHONIOENCODING=utf-8 python scripts/kaizen/warn_gen_count.py
          （窓を変える例）--hours 720 --now <epoch>
          （内訳を全部見る）--debug
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AUDIT = os.path.join(ROOT, "local", "llm", "send_audit.jsonl")

# dept_daemon.py が末尾に貼る警告文の**完全な文面**(正本)。ここが動いたら
# scripts/llm/dept_daemon.py の HANGUL_WARN / SIMPLIFIED_WARN / CYRILLIC_WARN と
# NARRATION_WARN を写し直す(完全一致で照合するため、1字でもズレたら数えない)。
FLAG_SENTENCES = {
    "ハングル混入": "⚠️(自動)生成不良: 非日本語スクリプト(ハングル)混入を検知。要確認。",
    "簡体字混入": "⚠️(自動)生成不良: 日本の漢字でない簡体字の混入を検知。要確認。",
    "キリル文字混入": "⚠️(自動)生成不良: ラテン文字そっくりのキリル文字混入を検知。名乗りが壊れている恐れ。要確認。",
    "名乗り無し": "⚠️(自動)生成不良: 名乗りも話者も無い機械ログのままの本文を検知。要確認。",
}

# lang_gate(純関数・import副作用なし= re と unicodedata だけ)を検知の芯として借りる。
# dept_daemon 本体は常駐/基盤なので import しない(C-015)。lang_gate は判定の家(ORG-11)。
_lg = None
try:
    sys.path.insert(0, os.path.join(ROOT, "scripts", "llm"))
    import lang_gate as _lg  # noqa: E402
except Exception:  # noqa: BLE001
    _lg = None

# ハングル(音節・字母)。lang_gate に detect_hangul は無いのでここで最小の1本を持つ。
_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

# 「この不具合を論じている便」の語彙。基準本文(フラグ行を除いた本体)にこれが在れば、
# 素の本文に混入字が残っていても**字例の引用/報告**と見なす(偽陽性 (A) を落とす二段目の芯)。
# ★ここは**狭く**保つ= 一般語(「検知」「ゲート」単独等)を入れると本物の生成崩れ(例
#   aegis の `무理せず`= 検証を論じた便に紛れた本物のハングル化け)まで誤って引用へ倒す。
#   実測(send_audit.jsonl 2026-09-17)で、この集合は本物4件(无く/请けた/监督/무理せず)を
#   一つも取りこぼさず、自室・QAの字例引用5件だけを落とすことを確かめてある。
_META_WORDS = (
    "⚠️", "生成不良", "自動検知",             # 警告そのものを引用/報告している便
    "簡体字", "簡体", "ハングル", "キリル",     # 文字体系を名指しで論じている便
    "誤発火", "誤検知", "字例", "ルールA", "混入", "U+",  # ゲート監査の語彙・字を定義している便
)

# 引用符で囲まれた span= 「字そのものを論じた文」。長さ保存で潰す(index/前後文を壊さない)。
_QUOTE_PATTERNS = (
    re.compile(r"「[^」\n]*」"),
    re.compile(r"『[^』\n]*』"),
    re.compile(r"“[^”\n]*”"),
    re.compile(r"\"[^\"\n]*\""),
)


def _parse_ts(s):
    """send_audit.jsonl の ts(例 '2026-09-05T03:07:53')を naive datetime に。失敗は None。"""
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return None


def _flag_kind(body):
    """本文の**末尾の非空行**が正本の警告文と完全一致した時だけ (種別, 元本文) を返す。

    そうでなければ (None, body)。元本文= フラグ行(と後続の空行)を落とした本体。
    daemon は `本体 + "\\n\\n" + 警告文` で必ず末尾に貼る= 末尾以外/語尾違い/報告文は
    「機械が付けたフラグ」ではない=数えない(偽陽性 (B) を落とす一段目)。
    """
    s = str(body or "")
    lines = s.split("\n")
    j = len(lines) - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j < 0:
        return None, s
    last = lines[j].strip()
    for kind, sent in FLAG_SENTENCES.items():
        if last == sent:
            return kind, "\n".join(lines[:j])
    return None, s


def _mask_all(s):
    """コード柵/インラインコード/URL(lang_gate と同じ)+ 引用符の中を長さ保存で潰す。"""
    out = str(s or "")
    if _lg is not None:
        try:
            out = _lg._mask_code_spans(out)
        except Exception:  # noqa: BLE001
            pass
    for pat in _QUOTE_PATTERNS:
        out = pat.sub(lambda m: " " * len(m.group(0)), out)
    return out


def _detect_residual(kind, masked):
    """引用/コードを潰した後の本文に混入字が残るか。残れば {char, codepoint, index}。

    ★簡体字・キリルは lang_gate の検知器そのもの(daemon と同じ芯)。ハングルは最小の regex。
    """
    try:
        if kind == "簡体字混入" and _lg is not None:
            return _lg.detect_simplified(masked)
        if kind == "キリル文字混入" and _lg is not None:
            return _lg.detect_cyrillic(masked)
        if kind == "ハングル混入":
            m = _HANGUL_RE.search(masked)
            if m:
                return {"char": m.group(0), "codepoint": "U+%04X" % ord(m.group(0)),
                        "index": m.start()}
            return None
    except Exception:  # noqa: BLE001
        return None
    return None


def _verify(kind, base):
    """フラグ済み本文が「本当に生成不良か」を推す(断定ではない・二段目)。

    返り値= (bucket, detail)
      bucket ∈ {"本物", "引用", "実況"}
      detail = 部屋へ添える一言(本物なら前後文つき)。
    """
    txt = str(base or "")
    if kind == "名乗り無し":
        # 名乗りも話者も無い機械ログ= 設計どおりの検知(引用の概念が無い)。多くは背景の状態通知。
        return "実況", "名乗りも話者も無い機械ログ(設計どおりの検知)"
    # この不具合を論じている便(警告そのもの/文字体系名/ゲート語彙を本文が含む)=
    # 混入字が地の文に在っても**字例の引用**=実際は問題ない側へ倒す。
    if any(w in txt for w in _META_WORDS):
        return "引用", "本文が不具合そのものを論じている(字例の引用・報告便)"
    masked = _mask_all(txt)
    hit = _detect_residual(kind, masked)
    if hit:
        i = hit.get("index", 0)
        ctx = txt[max(0, i - 18):i + 19].replace("\n", " ")
        return "本物", "引用・コード外に %s(%s)…%s" % (
            hit.get("char", "?"), hit.get("codepoint", "?"), ctx)
    return "引用", "混入字は引用符/コード/URLの中だけ(字例の引用)"


def collect(now, hours):
    """窓の間に**機械が実際に付けた**⚠️を数え、本物疑い/引用/実況へ仕分ける。

    返り値= dict(
      genuine     : 機械フラグの総数(末尾完全一致したもの),
      real        : 本物疑い(nonjp・引用/コード外に混入字が残る)件数,
      narration   : 実況(名乗り無し)件数,
      quoted      : 引用・報告(実際は問題ない疑い)件数,
      real_by_dept, narr_by_dept : 部屋別(本物疑い・実況),
      real_items  : [(dept, detail), ...] 本物疑いの前後文つき,
      narr_items  : [(dept, detail), ...] 実況,
    )
    """
    lo = dt.datetime.fromtimestamp(now - hours * 3600)
    hi = dt.datetime.fromtimestamp(now)
    r = {"genuine": 0, "real": 0, "narration": 0, "quoted": 0,
         "real_by_dept": {}, "narr_by_dept": {}, "real_items": [], "narr_items": []}
    if not os.path.exists(AUDIT):
        return r
    with io.open(AUDIT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            body = o.get("body") or ""
            kind, base = _flag_kind(body)
            if kind is None:                       # 機械が付けたフラグではない=数えない
                continue
            t = _parse_ts(o.get("ts"))
            if t is None or not (lo <= t <= hi):
                continue
            r["genuine"] += 1
            dept = o.get("dept") or "(不明)"
            bucket, detail = _verify(kind, base)
            if bucket == "本物":
                r["real"] += 1
                r["real_by_dept"][dept] = r["real_by_dept"].get(dept, 0) + 1
                r["real_items"].append((dept, detail))
            elif bucket == "実況":
                r["narration"] += 1
                r["narr_by_dept"][dept] = r["narr_by_dept"].get(dept, 0) + 1
                r["narr_items"].append((dept, detail))
            else:
                r["quoted"] += 1
    return r


def _span(now, hours):
    fmt = "%#m/%#d %H:%M" if os.name == "nt" else "%-m/%-d %H:%M"
    dfrom = dt.datetime.fromtimestamp(now - hours * 3600).strftime(fmt)
    duntil = dt.datetime.fromtimestamp(now).strftime(fmt)
    return "%s〜%s" % (dfrom, duntil)


def render(now, hours):
    """便に乗せる1ブロックを返す。本物疑い+実況が0件なら "" を返す。

    「0の日は何も言わない」(Chami)+「実際は問題ない時もある」(Chami)を両立=
    引用・誤検知しか無い日は**問題が無い日**として黙る。数字だけの水増し報告はしない。
    """
    r = collect(now, hours)
    speak = r["real"] + r["narration"]
    if speak == 0:
        return ""
    span = _span(now, hours)
    out = ["◆⚠️(自動)生成不良 直近%.0fh(%s)" % (hours, span)]
    out.append("  本物疑い= %d件 / 実況(名乗り無し)= %d件"
               "（機械フラグ %d件のうち、引用・誤検知%d件は数から外した）"
               % (r["real"], r["narration"], r["genuine"], r["quoted"]))
    if r["real"]:
        depts = sorted(r["real_by_dept"].items(), key=lambda kv: (-kv[1], kv[0]))
        out.append("  本物疑いの部屋= " + " / ".join("%s %d" % (d, v) for d, v in depts))
        for dept, detail in r["real_items"][:6]:
            out.append("    ・[%s] %s" % (dept, detail))
    if r["narration"]:
        depts = sorted(r["narr_by_dept"].items(), key=lambda kv: (-kv[1], kv[0]))
        out.append("  実況の部屋= " + " / ".join("%s %d" % (d, v) for d, v in depts))
    out.append("  ※機械が本文末尾に自分で貼った自己申告フラグの集計(押しスタンプ台帳とは別物)。"
               "引用・誤検知は「本当に混入字が引用/コードの外に残るか」で外した=推しであって断定ではない。")
    return "\n".join(out)


def main():
    import time
    ap = argparse.ArgumentParser(description="毎朝の⚠️(自動)生成不良を数え、本物か確かめて報告する")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--now", type=float, default=None, help="epoch秒。既定=現在時刻")
    ap.add_argument("--debug", action="store_true", help="仕分けの内訳を全部出す(手検証用)")
    a = ap.parse_args()
    now = a.now if a.now is not None else time.time()
    if a.debug:
        r = collect(now, a.hours)
        lines = ["genuine=%(genuine)d real=%(real)d narration=%(narration)d quoted=%(quoted)d" % r]
        lines.append("[本物疑い]")
        for dept, detail in r["real_items"]:
            lines.append("  %s | %s" % (dept, detail))
        lines.append("[実況]")
        for dept, detail in r["narr_items"]:
            lines.append("  %s | %s" % (dept, detail))
        sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
        return
    blk = render(now, a.hours)
    if blk:
        sys.stdout.buffer.write((blk + "\n").encode("utf-8"))
    # 本物疑い+実況が0件は何も出さない(Chami明示)= main も沈黙する。


if __name__ == "__main__":
    main()
