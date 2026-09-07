# -*- coding: utf-8 -*-
"""呼称の**持続ドリフト**を台帳から拾う(イージス研究室 / 2026-08-31)。

なぜ要るか:
  改善提案部門(トトリ)が「一ノ瀬」(裸の姓)呼び22件を実測し、機構側の手当てを回してきた
  (msg 1543872521093521478)。実測を当室でも取り直した結果、**回送の根因は1つ違っていた**=
  22件は素通りしていない。呼称ゲートは全部 `reason="override_allowed" / expected=["怜"]` で
  **違反と判定し、台帳へ書いていた**(`local/llm/naming_audit.jsonl`)。
  素通りしていたのは判定ではなく**読み手**だ= この台帳を読む機構が1つも無い(実測=
  `naming_audit` を参照するコードは書き手2本(dept_daemon / output_gates)だけ)。
  → 「鳴っている≠届いている」(共通規律§4)。**書きっぱなしの台帳は監視ではない。**

何を「ドリフト」と呼ぶか(★件数だけで鳴らさない理由):
  台帳の判定行は306行(2026-07-31〜08-31)。件数の閾値だけで鳴らすと**常に鳴る**=
  常に誤発火する安全網は無視される(§3)。だから3つ揃った時だけドリフトと呼ぶ:
    ① 直近 WINDOW_DAYS 日で MIN_COUNT 件以上   … 今も続いている
    ② MIN_DAYS 日以上にまたがる                … 一度の観測を状態の代理にしない(C-041)
    ③ MIN_PERSONAS 人以上の人格が使っている     … 1人のクセではなく**組織へ伝播した**形
  ★増分ではなく**持続**で見る= 件数が増えなくても、居座っている形は居座ったまま出る
    (増分だけの監視は滞留を見逃す)。

しきい値の根拠(実測・2026-08-31の台帳):
  (5,3,2) で7件が挙がる= 読める量。トトリが持ち込んだ「一ノ瀬」が**指定せずとも1位**に出る
  (件18/日6/人7)。狙い撃ちの検査ではないことの証拠として、この数字を残しておく。

自動置換はしない:
  正しい形は文脈で変わる(「一ノ瀬怜さんが」と紹介する文まで潰す)。ここは**数えて見せるだけ**。
  直すのは人事部門(呼称ルール.json と人格文脈)であって、この機構ではない。

★是正の**後**を測る時(--since):
  人事部門が生成側へ再ピンを入れた(2026-08-31・00_AI-HQ 6b1dc54)。「減ったか」を見るには
  **是正より後に書かれた行だけ**を数える必要がある= 既定の14日窓は是正前のバックログが
  支配していて、そこを見ても再ピンの効きは読めない。`--since 2026-08-31` で窓の始まりを
  **絶対日で**留める(`--days` は台帳の最終日から数え直すので、日が経つと基準がずれる)。
  ★★是正直後は窓が数日しか無い= 持続の条件(日数≥MIN_DAYS)は**原理的に満たせない**。
    だからこの窓の「持続ドリフトなし」は**直った証拠ではない**(C-041=一度の観測を状態の
    代理にしない)。--since を付けた時は持続判定を出さず、**生の件数と件/日**だけを見せる。
  ★件数を比べる時は必ず**件/日**で比べろ= 14日ぶんと3日ぶんの生の件数を並べると、
    窓が短くなっただけの減少を「効いた」と読む。

使い方:
    python scripts/llm/naming_drift_check.py            … 今の持続ドリフトを表で見る
    python scripts/llm/naming_drift_check.py --days 30  … 窓を変える
    python scripts/llm/naming_drift_check.py --since 2026-08-31
                                                        … 是正後だけを件/日で数える
"""
import argparse
import collections
import datetime as dt
import io
import json
import os
import re
import sys

PJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUDIT = os.path.join(PJ, "local", "llm", "naming_audit.jsonl")

WINDOW_DAYS = 14
MIN_COUNT = 5
MIN_DAYS = 3
MIN_PERSONAS = 2

# ★計器の自己汚染を切る(2026-09-06 実測・イージス研究室)。
#   何が起きていたか= 持続ドリフトの警報は本文へ「**ルカ・モドリッチ** を「ルカ・モドリッチ」と
#   呼んでいる」と、**違反の形をそのまま引用して**書く。その便は dispatch で人事部門へ出る=
#   投函経路の呼称ゲートC(output_gates.apply_naming_gate_only)を通り、
#   引用のつもりの形が**違反として naming_audit.jsonl へ書き戻される**。
#   翌朝その台帳をこの見張りが読む= **計器が自分の警報で自分の目盛りを押し上げる**。
#   実測(窓 2026-08-24〜09-06): 自分の本文から生まれた判定行 30。内訳=
#     target=ルカ・モドリッチ 10 / シャビ・アロンソ 10 / 一ノ瀬怜(found=一ノ瀬) 10。
#     ★「一ノ瀬」は人事部門へ回している見出しそのもの= **報告した分だけ翌日の件数が増える**。
#   ★_all_mention() は後段で**組ごと**黙らせるだけで count/days/personas は汚れたまま=
#     人事部門へ渡す数字が実際より大きく出る。外すべき層は「行」だ。
#   ★この見出しは envelope_naming_watch.build_drift_body() が**この定数から**組み立てる=
#     文言を変えても除外が外れない(2箇所に同じ文字列を置かない)。
SELF_REPORT_HEAD = "【イージス研究室(無人の見張り) → 人事部門】呼称の"


def is_self_report(r):
    """★この判定行は**この見張り自身の警報本文**から生まれたか(理由は SELF_REPORT_HEAD)。

    材料は excerpt(投函本文の頭200字)だけ= 台帳には他の手がかりが無い
    (source="dispatch" は他部門の便と共通・msg_id は投函時点で空)。
    ★excerpt が無い行は「違う」へ倒す= 判定できない時は**数える側**へ倒す(fail-open)。
      黙って落とす方向へ倒すと、見張りが静かに0件=健康へ倒れる。
    """
    return str(r.get("excerpt") or "").lstrip().startswith(SELF_REPORT_HEAD)


# ★同じ一箇所の違反が台帳へ2本書かれていた分を畳む(2026-09-08・イージス研究室)。
#   出所= dispatch は関門を2回通る(main() の同報前に1回・dispatch() の中でもう1回)。
#   ゲートCが**直す**違反は1回目で消えるが、大半は「警告のみ」で本文を変えない=
#   2回目が同じ違反をもう一度見つけて**同じ行をもう1本**書く。
#   ★生成側は 2026-09-06 に塞いである(scripts/llm/dispatch.py の `already_gated`)。
#     実測(2026-09-08)= 09-08の dispatch 判定行 5 / 一意 5 = 重複0。**塞がっている。**
#     だが**台帳に既に書かれた分は消えない**= 窓14日はまだ二重の行を抱えている。
#     実測(窓 2026-08-26〜09-08)= 判定行 621 / 一意 407 = **214行(34%)が重複**。
#     生成側だけ直して読み手を直さないと、直した後も2週間ぶん膨れた数字が人事部門へ出る。
#   ★畳む鍵に excerpt を入れない= 1回目と2回目で excerpt が違う(1回目が直した
#     呼びかけが2回目の excerpt に映る。実物= 「アロンソさん、」→「アロンソコーチ、」)。
#     同じ ts・同じ人格・同じ組・同じ現場(near)なら**同じ一箇所**だ。
#   ★near を鍵に入れる= 1つの本文に同じ形が2箇所出たら near が違う= 別々に数える(潰さない)。
DEDUPE_KEY = ("ts", "source", "dept", "persona", "target", "found", "near")


def dedupe(rows):
    """同じ一箇所を指す行を1本に畳む(理由は DEDUPE_KEY の上)。★順序は保つ。"""
    seen = set()
    out = []
    for r in rows:
        k = tuple(str(r.get(k_) or "") for k_ in DEDUPE_KEY)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def is_full_name_hit(r):
    """★その行の当たりは**正しいフル名を書いただけ**か(2026-09-08・イージス研究室)。

    実物= 便に「この件は**一ノ瀬怜**へ回します。」と書くと、`found="一ノ瀬"` の行が立つ。
    台帳を読むと「一ノ瀬怜 を **一ノ瀬** と呼んでいる」= 本文には裸の姓は1文字も無い。
    ★これはゲートの誤判定ではない(allowed は「怜」なのでフル名も許可形ではない)。
      だが**裸の姓で呼んだ**のと**フル名で書いた**のは別の崩れ方で、直し方も違う。
      1つの数字に混ぜると、人事部門は「裸の姓がN件」と読んで効かないピンを打つ。
    ★判定は near(現場の前後)だけで行う= 当たりが**全部** target の内側に埋まっている時だけ
      True。1つでも外に出ていれば False=**数える側へ倒す**(fail-open)。
      near が無い行・target が near に無い行も False(判定できない時は数える)。
    ★実測(窓 2026-08-26〜09-08・重複を畳んだ後 407行)= 56行(一ノ瀬怜>一ノ瀬 45 /
      ケヴィン・デブライネ>デブライネ 7 / 三笘薫>三笘 2 / デブライネ>ケヴィン 1、他1)。
      「一ノ瀬怜>一ノ瀬」の窓14日は 84件 → 39件へ落ちる(=残り45件がこの形)。
    ★**フル名が違反かどうかは決めていない**= 呼称の正本は人事部門(§役割)。
      ここでやるのは「別の棚に置いて件数を見せる」だけ= `full_name_hits()` で必ず表に出す。
    """
    near = str(r.get("near") or "")
    found = str(r.get("found") or "")
    target = str(r.get("target") or "")
    if not near or not found or not target or found == target or target not in near:
        return False
    spans = [(m.start(), m.end()) for m in re.finditer(re.escape(target), near)]
    hits = [(m.start(), m.end()) for m in re.finditer(re.escape(found), near)]
    if not hits:
        return False
    return all(any(s <= a and b <= e for s, e in spans) for a, b in hits)


def load_rows(path=None, keep_self=False, keep_full_name=False):
    """台帳から**判定行だけ**読む。★壊れた行で落ちない(1行の事故で監視を止めない)。

    event="naming_fix" は機械が直した行= ドリフトではなく**直った跡**なので数えない。
    ★この見張り自身の警報本文から生まれた行も数えない(理由は SELF_REPORT_HEAD)。
      数えたい時(=汚染そのものを測る時)だけ keep_self=True。
    ★同じ一箇所が2本書かれた行は畳む(理由は DEDUPE_KEY)。**これは常に効く**=
      畳んだ結果が「元の数」だ。畳む前の数を見たい時は dedupe() を通さず自分で読め。
    ★正しいフル名を書いただけの行も数えない(理由は is_full_name_hit)。
      数えたい時(=その分を測る時)だけ keep_full_name=True。
    """
    out = []
    for r in _read(path):
        if not keep_self and is_self_report(r):
            continue
        if not keep_full_name and is_full_name_hit(r):
            continue
        out.append(r)
    return dedupe(out)


def _read(path=None):
    """台帳の**判定行だけ**を素で読む(除外も重複畳みもしない)。

    ★壊れた行で落ちない(1行の事故で監視を止めない)。除外した分を数える窓口はここを見る=
      「畳む前」を知っているのはこの関数だけだ。
    """
    out = []
    try:
        with io.open(path or AUDIT, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if r.get("event") == "naming" and r.get("found") and r.get("target"):
                    out.append(r)
    except OSError:
        return []
    return out


def self_reports(path=None, end=None, window=WINDOW_DAYS, since=None):
    """★外した分(=自己汚染の行)を組ごとに返す。**0件に見せない**ための窓口。

    捨てた数を見えないところへ捨てると、次に読む者が「元から少なかった」と読む。
    main() はここを1行で必ず出す(「鳴らせない」「鳴らさない」と同じ扱い)。
    """
    rows = [r for r in load_rows(path, keep_self=True, keep_full_name=True)
            if is_self_report(r)]
    return _by_pair(rows, end, window, since)


def full_name_hits(path=None, end=None, window=WINDOW_DAYS, since=None):
    """★外した分(=正しいフル名を書いただけの行)を組ごとに返す。理由は is_full_name_hit。

    self_reports() と同じ理由でここに要る= 捨てた数を見えないところへ捨てない。
    ★2026-09-08 裁定(人事部門ククール)= **これは違反ではない。足し戻さない。**
      同日、生成側(naming_gate の `CROSS_SPEAKER_SPAN_EXEMPTION`)を直したので、
      **これから書かれる行にはもう「フル名の内側の裸姓」は載らない**。
      ここが数える対象は**裁定より前に台帳へ積まれた過去行**だけになる=
      窓14日が入れ替われば自然に0へ落ちる(前例= duplicates の154件)。
      落ちるまでは残す(消すと、過去行が「違反」の側へ紛れ込む)。
    """
    rows = [r for r in load_rows(path, keep_self=True, keep_full_name=True)
            if is_full_name_hit(r) and not is_self_report(r)]
    return _by_pair(rows, end, window, since)


def duplicates(path=None, end=None, window=WINDOW_DAYS, since=None):
    """★畳んだ分(=同じ一箇所が2度書かれた行)を組ごとに返す。理由は DEDUPE_KEY。

    ★生成側(dispatch.py の already_gated)は 2026-09-06 に塞いである。ここに数字が出るのは
      **塞ぐ前に書かれた行が窓に残っている**間だけだ= 窓が入れ替われば自然に0へ落ちる。
      0にならなくなったら、それは塞いだ所が外れた合図(この行がその見張りを兼ねる)。
    """
    rows = []
    seen = set()
    for r in _read(path):
        if is_self_report(r) or is_full_name_hit(r):
            continue
        k = tuple(str(r.get(k_) or "") for k_ in DEDUPE_KEY)
        if k in seen:
            rows.append(r)          # 2本目以降=畳まれた分
        seen.add(k)
    return _by_pair(rows, end, window, since)


def _by_pair(rows, end, window, since):
    """(target, found) ごとに件数と日数だけ畳んだ一覧(除外分を見せる窓口の共通形)。"""
    out = []
    for (target, found), a in _aggregate(rows, end, window, since=since).items():
        out.append({"target": target, "found": found, "count": a["count"],
                    "days": len(a["days"])})
    out.sort(key=lambda d: (-d["count"], d["target"]))
    return out


def _end_date(rows, end):
    """窓の終わり。★既定は**台帳の最終日**であって「今日」ではない(理由は `_aggregate`)。"""
    days_of = [r["ts"][:10] for r in rows if r.get("ts")]
    if not days_of:
        return None
    try:
        return dt.date.fromisoformat(end or max(days_of))
    except ValueError:
        return None


def _aggregate(rows, end, window, since=None):
    """(target, found) ごとに窓の中を畳む。

    ★端の扱い= `end` を含む `window` 日(end 当日を1日目と数える)。既定の end は台帳の最終日
      であって「今日」ではない= 台帳が数日止まっていても、止まる前の窓をそのまま見せる
      (「今日」を基準にすると、書き手が死んだ時に**静かに0件=健康**へ倒れる)。
    ★`since` を渡すと窓の始まりを**絶対日で**留める(is-fixed の測定用・`window` と併用可=
      両方の内側だけが残る)。`--days` は台帳の最終日から数え直すので、是正日を基準に
      したい場面では日が経つたびに基準がずれる= そこを固定するための引数。
    """
    if not rows:
        return {}
    end_d = _end_date(rows, end)
    if end_d is None:
        return {}
    since_d = None
    if since:
        try:
            since_d = dt.date.fromisoformat(since)
        except ValueError:
            return {}

    agg = collections.defaultdict(
        lambda: {"count": 0, "days": set(), "personas": set(),
                 "reasons": collections.Counter(), "expected": [],
                 "first": "", "last": "", "voc": 0, "judgeable": 0})
    for r in rows:
        ts = str(r.get("ts") or "")
        try:
            d = dt.date.fromisoformat(ts[:10])
        except ValueError:
            continue
        if not (0 <= (end_d - d).days < window):
            continue
        if since_d is not None and d < since_d:
            continue
        a = agg[(r["target"], r["found"])]
        a["count"] += 1
        a["days"].add(ts[:10])
        a["personas"].add(str(r.get("persona") or ""))
        a["reasons"][str(r.get("reason") or "")] += 1
        # ★呼びかけ / 地の文の内訳。`voc` を持たない行は**旧ゲートが書いた行**=
        #   判定できない。0 として数えると「全部が地の文」へ静かに倒れるので、
        #   judgeable(判定できた行数)を別に持ち、無い行はどちらにも入れない。
        if "voc" in r:
            a["judgeable"] += 1
            try:
                a["voc"] += int(r.get("voc") or 0)
            except (TypeError, ValueError):
                pass
        if not a["expected"]:
            a["expected"] = list(r.get("expected") or [])
        a["first"] = min(a["first"] or ts, ts)
        a["last"] = max(a["last"], ts)
    return agg


def _unreadable(a):
    """★実際の形が台帳に無い行= 直す先が読めない(実測=窓14日で2組8件)。

    呼称ゲートが台帳へ書く `found` は「見つかった**土台の**形」であって、**実際に使われた形
    ではない**。例= 「モドリッチさん」は違反(呼び捨てが正)だが、台帳には
    found="モドリッチ" / expected=["モドリッチ"] と残る= 読むと
    「モドリッチをモドリッチと呼ぶな」という無意味な文になる。
    ★これは判定の誤りではなく**台帳の表現力不足**だ(ゲートは正しく違反にしている)。
    直す先が読み取れない警報は、受け手が無視する側へ倒れる(§3)ので**鳴らさない**。
    ただし黙って捨てもしない= `unreadable()` で件数だけ見せ、ゲート側の宿題として残す。
    """
    return a["found"] in (a["expected"] or [])


def _all_mention(a, min_count=MIN_COUNT):
    """★この組は**地の文の言及だけ**か(=人事へ回しても直す先が無い)。

    なぜ要るか(2026-09-02・人事部門ククールの検算 msg DISPATCH-aegis-gl-1788299260538 の裏取り):
      08-31の再ピン後も5ペアが34件挙がり続けた。現場(near)を機械で割ると
      **呼びかけ位置0 / 地の文34**= 中身は「アロンソ・オタコン・三笘」の列挙、
      「アロンソ研究室」の部屋名、そして**このドリフトを論じている報告便そのもの**だ。
      これを鳴らし続けると、人事は毎回「当てる先の無いピン」を打つことになる=
      常に誤発火する安全網は無視される(共通規律§3)。

    ★ただし黙らせる条件は厳しくする(静かに壊れないように):
      ① 判定できた行(voc を持つ=新ゲートが書いた行)が min_count 以上ある
      ② そのうち呼びかけ位置が **1件も無い**
      → 旧ゲートの行しか無い組は判定できない= **鳴らす側へ倒す**(fail-open)。
      台帳が新しい行で埋まるにつれて自動で判定できるようになる。
    """
    return a.get("judgeable", 0) >= min_count and a.get("voc", 0) == 0


def span_days(rows=None, since=None, end=None, window=WINDOW_DAYS):
    """窓が実際に何日ぶんか(0なら窓が空)。

    ★件数を比べる時は必ずこれで割れ。是正の後は窓が短い= 生の件数は必ず小さく出るので、
      14日ぶんと3日ぶんの件数を並べると「窓が縮んだだけの減少」を効果と読む。
    """
    rows = load_rows() if rows is None else rows
    end_d = _end_date(rows, end)
    if end_d is None:
        return 0
    n = window
    if since:
        try:
            n = min(window, (end_d - dt.date.fromisoformat(since)).days + 1)
        except ValueError:
            return 0
    return max(0, n)


def counts(rows=None, since=None, end=None, window=WINDOW_DAYS):
    """窓の中の**生の件数**を組ごとに返す(持続のしきい値を通さない)。

    ★用途は是正後の測定= 是正直後は日数が足りず `scan()` は必ず空になる。その空を
      「直った」と読ませないために、しきい値と無関係な素の数をここで見せる。
    ★`unreadable` な組も落とさず flag を立てて返す= 鳴らせないだけで、出ている事実は同じ。
    """
    rows = load_rows() if rows is None else rows
    out = []
    for (target, found), a in _aggregate(rows, end, window, since=since).items():
        out.append({
            "target": target, "found": found, "expected": a["expected"],
            "count": a["count"], "days": len(a["days"]),
            "personas": sorted(p for p in a["personas"] if p),
            "first": a["first"], "last": a["last"],
            "voc": a["voc"], "judgeable": a["judgeable"],
            "unreadable": _unreadable(dict(a, target=target, found=found)),
            "all_mention": _all_mention(a),
        })
    out.sort(key=lambda d: (-d["count"], d["target"], d["found"]))
    return out


def mentions(rows=None, end=None, window=WINDOW_DAYS, since=None):
    """★鳴らさない(=地の文の言及だけの)組を件数順で返す。理由は `_all_mention`。

    黙って捨てはしない= `main()` が件数と内訳を1行で見せる(「鳴らせない」と同じ扱い)。
    """
    rows = load_rows() if rows is None else rows
    out = []
    for (target, found), a in _aggregate(rows, end, window, since=since).items():
        if _unreadable(dict(a, target=target, found=found)):
            continue
        if _all_mention(a):
            out.append({"target": target, "found": found, "count": a["count"],
                        "judgeable": a["judgeable"], "voc": a["voc"]})
    out.sort(key=lambda d: (-d["count"], d["target"]))
    return out


def unreadable(rows=None, end=None, window=WINDOW_DAYS, since=None):
    """鳴らせない(=台帳から直す先が読めない)組を件数順で返す。理由は `_unreadable`。"""
    rows = load_rows() if rows is None else rows
    out = []
    for (target, found), a in _aggregate(rows, end, window, since=since).items():
        a = dict(a, target=target, found=found)
        if _unreadable(a):
            out.append({"target": target, "found": found,
                        "expected": a["expected"], "count": a["count"]})
    out.sort(key=lambda d: (-d["count"], d["target"]))
    return out


def scan(rows=None, end=None, window=WINDOW_DAYS,
         min_count=MIN_COUNT, min_days=MIN_DAYS, min_personas=MIN_PERSONAS,
         since=None):
    """持続ドリフトを件数の多い順で返す。

    戻り値= [{"target","found","expected","count","days","personas","first","last","reasons"}]
    ★`since` で窓を狭めた時、返り値が空でも「直った」ではない= 窓の日数が min_days に
      届かなければ**何が起きていても空**になる。狭い窓で測るなら `counts()` を見ろ。
    """
    rows = load_rows() if rows is None else rows
    out = []
    for (target, found), a in _aggregate(rows, end, window, since=since).items():
        if _unreadable(dict(a, target=target, found=found)):
            continue
        # ★地の文の言及しか無い組は人事へ回さない(直す先が無い・理由は `_all_mention`)。
        if _all_mention(a, min_count):
            continue
        if (a["count"] >= min_count and len(a["days"]) >= min_days
                and len(a["personas"]) >= min_personas):
            out.append({
                "target": target, "found": found, "expected": a["expected"],
                "count": a["count"], "days": len(a["days"]),
                "personas": sorted(p for p in a["personas"] if p),
                "first": a["first"], "last": a["last"],
                "voc": a["voc"], "judgeable": a["judgeable"],
                "reasons": dict(a["reasons"]),
            })
    out.sort(key=lambda d: (-d["count"], d["target"], d["found"]))
    return out


def banned(d):
    """★**明示的に禁止したのに、まだ出ている**形か。

    `reason="forbidden"` は「呼称ルール.json の forbidden に名指しで載っている」の意味で、
    `override_allowed`(許可形リストに無いだけ)より**強い事実**だ= 人が手を入れた後の再発。
    2026-08-31 に人事部門が怜の override 4本へ `forbidden:["一ノ瀬"]` を入れた(00_AI-HQ 1e2e16b)。
    ★当室で前後を実測した= ラベルは override_allowed → forbidden へ変わるが、
      `naming_corrections()` の `applied` は空のまま= **文面は1文字も直らない**。
      つまりこれは「鳴る理由が変わっただけ」で、止めるのは生成側の再ピンの仕事だ。
    """
    return d.get("reasons", {}).get("forbidden", 0) > 0


def sig(drifts):
    """ドリフトの顔ぶれ。同じ顔ぶれを二度知らせないための版(件数は入れない=

    1件増えるたびに鳴り直すと、それは件数アラームと同じ騒がしさになる)。
    ★ただし「禁止に載ったか」は版に混ぜる= 禁止を入れた**後も**同じ形が出続けている、は
      顔ぶれが同じでも**別の事実**(再ピンが効かなかった)。混ぜないと、その節目が黙って通る。
      鳴り直すのは切り替わった一度だけで、その後はまた沈黙する。
    """
    return "|".join(sorted("%s>%s%s" % (d["target"], d["found"], "!" if banned(d) else "")
                           for d in drifts))


# ★鳴り方の正本(2026-09-08・イージス研究室)。発注= 人事部門ククール msg 1546651338312523827
#   「無人の見張りが答えの出た裁定を毎時間、有人部屋へ full-dump している」。
#
# 何が起きていたか(実測= local/_state/envelope_naming_watch.jsonl の drift_alert 17行):
#   `sig()` は「顔ぶれが同じなら鳴らし直さない」つもりの版だった。だが顔ぶれは**しきい値の
#   境目で毎時ばたつく**= 窓14日が1時間ずつ滑るたび、件5/日3/人2 の縁に居る組が出たり入ったり
#   する。実物(2026-09-08)= 04:38 は「一ノ瀬怜>怜」が増えて10組、05:38 は代わりに「ククール>ク」が
#   入って10組、06:38 は「シャビ・アロンソ>シャビ・アロンソ」が抜けて9組、07:38 は
#   「一ノ瀬怜>一ノ瀬!」が抜けて8組。**毎時 sig が変わる=毎時 full-dump**。
#   ★つまり「同じ顔ぶれを二度知らせない」は、**組の集合が完全一致した時しか**効かない実装で、
#     現実の集合は完全一致しなかった。集合の一致で黙らせる設計そのものが誤りだった。
#
# 直し方= **集合の一致ではなく「初めて見た組か」で鳴らす**:
#   ① その組を**この見張りが今まで一度も知らせていない**なら鳴らす(=本当に新しい事実)。
#   ② 既に知らせた組でも **禁止に載った後の再発へ変わった**(banned が False→True)なら鳴らす。
#      ここは「顔ぶれが同じでも別の事実」= 旧 sig() が版に "!" を混ぜていた理由をそのまま継ぐ。
#   ③ どちらも無い時刻は**鳴らさない**。組が消えただけ・件数が動いただけでは鳴らさない。
#   ★組の記憶は PAIR_TTL_DAYS 日で忘れる= 窓(14日)から完全に出た組が後日また立ったら、
#     それは**再発**なので鳴らす側へ戻す。忘れないと「一度鳴った組は二度と鳴らない」になる。
#
# 実測(上の17行を再生した結果・local/_work/drift_cadence_measure.py):
#   現行= dispatch 12回 / この方式= 8回。**2026-09-08 の4回(04/05/06/07時)は1回へ落ちる。**
PAIR_TTL_DAYS = WINDOW_DAYS


def pair_key(d):
    """組の鍵。★"!"(banned)は混ぜない= banned は別の欄で持つ(遷移を見たいから)。"""
    return "%s>%s" % (d["target"], d["found"])


def seed_pairs(old_sig, day):
    """旧 state の顔ぶれ文字列から組の記憶を作る(**移行のため**・2026-09-08)。

    ★これが無いと、この改修を入れた最初の1回で**既に知らせ済みの8組が全部「初出」**になり、
      静かにするための改修が逆に full-dump を1本余計に撃つ。移行の costs は必ず数える。
    """
    out = {}
    for k in str(old_sig or "").split("|"):
        if not k:
            continue
        banned_ = k.endswith("!")
        out[k[:-1] if banned_ else k] = {"last": day, "banned": banned_}
    return out


def diff_pairs(prev, drifts, day, ttl_days=PAIR_TTL_DAYS):
    """今この顔ぶれで**鳴らすべきか**を決める(理由は上のブロック)。

    prev  = {"組": {"last": "YYYY-MM-DD", "banned": bool}}(前回までに知らせた組)
    戻り値= {"fresh": [初出の組], "rebanned": [禁止後の再発へ変わった組], "pairs": 次のprev}
    ★fresh も rebanned も空なら鳴らさない。**判定はここだけ**= 見張り側に条件を書かない。
    """
    prev = prev if isinstance(prev, dict) else {}
    nxt = {}
    for k, v in prev.items():
        if not isinstance(v, dict):
            continue
        if _age_days(v.get("last"), day) <= ttl_days:
            nxt[k] = {"last": v.get("last") or day, "banned": bool(v.get("banned"))}
    fresh, rebanned = [], []
    for d in drifts:
        k = pair_key(d)
        b = banned(d)
        if k not in nxt:
            fresh.append(k)
            nxt[k] = {"last": day, "banned": b}
            continue
        if b and not nxt[k]["banned"]:
            rebanned.append(k)
        nxt[k] = {"last": day, "banned": b or nxt[k]["banned"]}
    return {"fresh": fresh, "rebanned": rebanned, "pairs": nxt}


def _age_days(last, day):
    """last から day までの日数。★読めない値は「古い」へ倒す=忘れる側(fail-open)。

    忘れる側へ倒すと、最悪でも**もう一度知らせる**だけで済む。覚えている側へ倒すと、
    壊れた記憶のせいで**本物の初出を黙って落とす**= 沈黙の事故になる。
    """
    try:
        return (dt.date.fromisoformat(day) - dt.date.fromisoformat(str(last))).days
    except (ValueError, TypeError):
        return ttl_infinite()


def ttl_infinite():
    return 10 ** 6


def _show_drops(window=WINDOW_DAYS, since=None):
    """★畳んだ分/外した分を**必ず**画面へ出す(2026-09-08)。

    なぜ関数にしたか= 通常表示と `--since` の2箇所で同じ行が要るからだ。片方に書き忘れると、
    「是正後モードだけ数が小さい」= 除外を効果と読み違える経路ができる。
    """
    dup = duplicates(window=window, since=since)
    if dup:
        print("(畳んだ %d件= 同じ一箇所を関門が2度書いた重複・生成側は 2026-09-06 に"
              "塞いだ〈dispatch.py already_gated〉ので窓が入れ替われば0へ落ちる: %s)"
              % (sum(d["count"] for d in dup),
                 "、".join("%s>%s×%d" % (d["target"], d["found"], d["count"])
                           for d in dup[:5])))
    fn = full_name_hits(window=window, since=since)
    if fn:
        print("(外した %d件= 正しいフル名を書いただけの行〈例「一ノ瀬怜へ回す」で"
              "found=一ノ瀬〉。**2026-09-08 人事裁定=違反ではない・足し戻さない**。"
              "生成側は同日に塞いだので〈naming_gate CROSS_SPEAKER_SPAN_EXEMPTION〉"
              "窓が入れ替われば0へ落ちる過去行だ: %s)"
              % (sum(f["count"] for f in fn),
                 "、".join("%s>%s×%d" % (f["target"], f["found"], f["count"])
                           for f in fn[:5])))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--since", help="窓の始まりを絶対日で留める(是正後の測定用 YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    rows = load_rows()
    if ns.since:
        # ★是正後モード= 持続判定は出さない(窓が短いと原理的に空になり「直った」と誤読
        #   される)。素の件数と**件/日**だけを見せる。
        cs = counts(rows, since=ns.since, window=ns.days)
        n = span_days(rows, since=ns.since, window=ns.days)
        if ns.json:
            print(json.dumps({"since": ns.since, "span_days": n, "counts": cs},
                             ensure_ascii=False, indent=2))
            return 0
        print("台帳の判定行 %d / %s以降 %d日ぶん(★持続判定はしない=件数だけ)"
              % (len(rows), ns.since, n))
        sr = self_reports(window=ns.days, since=ns.since)
        if sr:
            print("(外した %d件= 見張り自身の警報本文の書き戻し・自己汚染)"
                  % sum(s["count"] for s in sr))
        _show_drops(window=ns.days, since=ns.since)
        if not cs:
            print("この窓には1件も無い。★ただし**日数が %d 日しか無い**= "
                  "『直った』の証拠にはならない(是正前の窓と比べるなら件/日で)" % n)
        for c in cs:
            print("- %s を **%s** と呼んでいる(正=%s): 件%d 日%d 人%d = **%.2f件/日**"
                  "(判定%d/呼%d)%s%s"
                  % (c["target"], c["found"], "/".join(c["expected"]) or "?",
                     c["count"], c["days"], len(c["personas"]),
                     (c["count"] / n) if n else 0.0,
                     c["judgeable"], c["voc"],
                     "(鳴らせない)" if c["unreadable"] else "",
                     "(鳴らさない)" if c["all_mention"] else ""))
        return 0
    ds = scan(rows, window=ns.days)
    un = unreadable(rows, window=ns.days)
    mt = mentions(rows, window=ns.days)
    if ns.json:
        print(json.dumps({"drifts": ds, "unreadable": un, "mentions": mt},
                         ensure_ascii=False, indent=2))
        return 0
    print("台帳の判定行 %d / 窓%d日 / しきい値 件%d 日%d 人%d"
          % (len(rows), ns.days, MIN_COUNT, MIN_DAYS, MIN_PERSONAS))
    if not ds:
        print("持続ドリフトなし")
    for d in ds:
        print("- %s を **%s** と呼んでいる(正=%s): 件%d 日%d 人%d [%s〜%s]"
              % (d["target"], d["found"], "/".join(d["expected"]) or "?",
                 d["count"], d["days"], len(d["personas"]),
                 d["first"][:10], d["last"][:10]))
        print("    使っている人格= %s" % "、".join(d["personas"]))
    if un:
        # ★鳴らさない分を**見えるところに**残す。0件に見せると、次に読む者が
        #   「台帳は健康」と誤読する(C-041)。
        print("(鳴らせない %d件= 台帳に実際の形が無く直す先が読めない: %s)"
              % (sum(u["count"] for u in un),
                 "、".join("%s>%s" % (u["target"], u["found"]) for u in un)))
    sr = self_reports(window=ns.days)
    if sr:
        # ★**外した分**を見えるところに残す。除外は静かにやると「元から少なかった」に見える。
        print("(外した %d件= この見張り自身の警報本文が台帳へ書き戻された分・自己汚染: %s)"
              % (sum(s["count"] for s in sr),
                 "、".join("%s>%s×%d" % (s["target"], s["found"], s["count"]) for s in sr)))
    _show_drops(window=ns.days)
    if mt:
        # ★鳴らさない分も**見えるところに**残す(「鳴らせない」と同じ理由)。
        #   ここに出た組は「相手へ呼びかけた形が1件も無い」=人事がpinしても直す先が無い。
        #   ★0=誤呼称ゼロではない= `_is_vocative` は狭い(行頭+読点)。
        #     文中の裸の姓はこちら側に入る。疑うならこの行の組を現物で読め。
        print("(鳴らさない %d件= 呼びかけ位置が0で地の文の言及だけ: %s)"
              % (sum(m["count"] for m in mt),
                 "、".join("%s>%s(判定%d/呼%d)"
                          % (m["target"], m["found"], m["judgeable"], m["voc"])
                          for m in mt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
