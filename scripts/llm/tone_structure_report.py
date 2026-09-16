#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""構造指標(軸②/軸③)の分布を出すだけの読み手。**閾値を提案しない**。

出所は2つ。混ぜて1つの数字にしない= 出所が違えば母集団が違う。
  live     : local/llm/tone_audit.jsonl の event=tone_structure(合流点が書いた実測)
  backfill : local/llm/recent_*.jsonl の本文をその場で数える(過去便・**台帳へは書かない**)
             ★書かないのは、過去便を live と同じ台帳へ流し込むと
               「いつ数えたか」と「いつ送られたか」が混ざって分布が読めなくなるから。

実行=
  python scripts/llm/tone_structure_report.py                 # live の分布
  python scripts/llm/tone_structure_report.py --backfill      # 過去便から分布を作る
  python scripts/llm/tone_structure_report.py --backfill --persona 花海咲季
  python scripts/llm/tone_structure_report.py --leaks         # 軸③が0でない便を人格名付きで一覧
"""
import glob
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from tone_structure import (COMPOSITE_KEYS, _load_rules,      # noqa: E402
                            composite_score, count_structure)

TONE_AUDIT = os.path.join(ROOT, "local", "llm", "tone_audit.jsonl")
RECENT = os.path.join(ROOT, "local", "llm", "recent_*.jsonl")

KEYS = ("chars", "bold", "bold_head", "hr", "heading", "bullet", "bullet_depth",
        "numlabel", "table", "other_names_total", "other_first_person_total")


def _pct(vals, q):
    if not vals:
        return 0
    s = sorted(vals)
    i = max(0, min(len(s) - 1, int(round((len(s) - 1) * q))))
    return s[i]


def _summarize(label, rows):
    print(f"\n== {label}: {len(rows)} 便 ==")
    if not rows:
        print("  (0件。合流点を通った便がまだ無いか、台帳が別の場所に在る)")
        return
    print(f"  {'指標':<22} {'中央値':>7} {'p90':>7} {'p99':>7} {'最大':>7} {'>0の便':>7}")
    for k in KEYS:
        v = [int(r.get(k) or 0) for r in rows]
        nz = sum(1 for x in v if x > 0)
        print(f"  {k:<22} {_pct(v, .5):>7} {_pct(v, .9):>7} {_pct(v, .99):>7} "
              f"{max(v):>7} {nz:>7}")
    # ★合成は**個別指標と同じ表に必ず出す**= 口で運ぶと次の手番でズレる
    #   (2026-09-16 AD研究室 msg 1549612208940654593 の指摘。当室が実際にズラした)。
    #   ★古い台帳の行には composite キーが無いので、その場で同じ関数に通し直す。
    cv = [int(r.get("composite") if r.get("composite") is not None
              else composite_score(r)) for r in rows]
    print(f"  {'composite':<22} {_pct(cv, .5):>7} {_pct(cv, .9):>7} {_pct(cv, .99):>7} "
          f"{max(cv):>7} {sum(1 for x in cv if x > 0):>7}"
          f"   ← 定義= {' + '.join(COMPOSITE_KEYS)}(tone_structure.COMPOSITE_KEYS)")
    # ★軸③の中身は名前が分かると効く(誰に引っ張られたか)。上位だけ出す。
    tally = {}
    for r in rows:
        for d in (r.get("other_names") or {}, r.get("other_first_person") or {}):
            for k, c in d.items():
                tally[k] = tally.get(k, 0) + int(c or 0)
    if tally:
        top = sorted(tally.items(), key=lambda kv: -kv[1])[:10]
        print("  軸③ 内訳(上位): " + " / ".join(f"{k}×{c}" for k, c in top))


def _audit_links():
    """audit_id → 実msg_id の対応を tone_audit.jsonl から拾う(persona_send が投稿後に書く行)。

    ★なぜ要るか= 構造監査の行は**投稿より前**に書かれるので msg_id をまだ持てない
      (2026-09-16・AD研究室 msg 1549614905580068977 ④= tone_fix 173行中24行が照合不能)。
      ゲート時に発行した audit_id を、投稿後の `event=audit_link` 行で実IDへ繋ぐ。
    ★1つの audit_id に複数の msg_id が付き得る(分割連投)= 全部返す。
    """
    out = {}
    try:
        with open(TONE_AUDIT, encoding="utf-8") as f:
            for ln in f:
                if '"audit_link"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:                        # noqa: BLE001
                    continue
                if d.get("event") != "audit_link":
                    continue
                a, m = str(d.get("audit_id") or ""), str(d.get("msg_id") or "")
                if a and m:
                    out.setdefault(a, []).append(m)
    except OSError:
        pass
    return out


def _leaks(label, rows, links=None):
    """★軸③(他人格の一人称が混ざった便)を**人格名付きで一覧する**。

    注文の出所= 2026-09-16 AD研究室 msg 1549614905580068977 ⑤
      「当室の目視を要件にするな」「機械が切り、人事部門が読む」。
      共通規律§3「人手の入口を要件にした機構は実測0件になる」と同じ型だ=
      人がログを目で追わないと出てこない一覧は、担当が代わった日に消える。
    ★ここでも**判定しない**= 「混ざっている」と書くだけで「崩れている」とは言わない。
      部門間の報告では他人格の名前も一人称も正当に出る(引用・伝言)。切るのは読む側の仕事だ。
    """
    links = links or {}
    hit = [r for r in rows if int(r.get("other_first_person_total") or 0) > 0]
    print(f"\n== {label}: 軸③(他人格の一人称)が0でない便 {len(hit)}/{len(rows)} ==")
    if not hit:
        print("  (0件。混入が無いのか、まだ数えた便が少ないのかは分布の行数で見ろ)")
        return
    print(f"  {'ts':<20} {'人格':<14} {'混入':>4}  {'内訳':<28} msg_id")
    for r in sorted(hit, key=lambda x: str(x.get("ts") or "")):
        fp = r.get("other_first_person") or {}
        detail = " ".join(f"{k}×{v}" for k, v in sorted(fp.items(), key=lambda kv: -kv[1]))
        mid = str(r.get("msg_id") or "")
        if not mid:
            mid = ",".join(links.get(str(r.get("audit_id") or ""), [])) or \
                  (f"(audit_id={r.get('audit_id')} 未投稿/未突合)" if r.get("audit_id")
                   else "(鍵なし= 突合できない行)")
        print(f"  {str(r.get('ts') or '')[:19]:<20} {str(r.get('persona') or ''):<14} "
              f"{r.get('other_first_person_total'):>4}  {detail:<28} {mid}")
    # ★名前(固有名詞)の混入は**別に出す**= 一人称の混入とは重さが違う。
    #   他部門の人格名を書くのは普通の業務連絡だ。同じ表に混ぜたら一人称の方が埋もれる。
    nm = [r for r in rows if int(r.get("other_names_total") or 0) > 0]
    print(f"  (参考: 他人格の**名前**が出る便は {len(nm)}/{len(rows)}。"
          f"これは伝言・引用で正当に出る= 一覧の対象にしない)")


def _one_msg(msg_id):
    """★1便を同じ関数に通して数える(口で値を運ばないため)。

    置き場が2つある= corpus(Chamiの指摘に紐づく元便)と recent_*(部門の便)。
    どちらに在っても同じ `count_structure()` を通す= 読み手が同じ数字を再現できる。
    """
    src = os.path.join(ROOT, "local", "corpus", "chami.jsonl")
    cand = []
    try:
        with open(src, encoding="utf-8") as f:
            for ln in f:
                if msg_id not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:                        # noqa: BLE001
                    continue
                rt = d.get("reply_to") or {}
                if rt.get("msg_id") == msg_id and (rt.get("content") or rt.get("body")):
                    cand.append((rt.get("author") or "", rt.get("content") or rt.get("body")))
    except OSError:
        pass
    for p in sorted(glob.glob(RECENT)):
        try:
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    if msg_id not in ln:
                        continue
                    try:
                        d = json.loads(ln)
                    except Exception:                    # noqa: BLE001
                        continue
                    if str(d.get("msg_id") or "") == msg_id and d.get("body"):
                        cand.append((d.get("author") or "", d["body"]))
        except OSError:
            continue
    if not cand:
        print(f"\n== msg {msg_id} ==\n  (本文が手元に無い。SKIP= 数字を作らない)")
        return
    author, body = cand[0]
    r = count_structure(body, persona=author)
    print(f"\n== msg {msg_id}(author={author}) ==")
    for k in KEYS:
        print(f"  {k:<22} {r.get(k)}")
    print(f"  {'composite':<22} {r['composite']}"
          f"   ← 定義= {' + '.join(COMPOSITE_KEYS)}")


def main():
    persona = None
    if "--persona" in sys.argv:
        i = sys.argv.index("--persona")
        if i + 1 < len(sys.argv):
            persona = sys.argv[i + 1]
    if "--msg" in sys.argv:
        i = sys.argv.index("--msg")
        if i + 1 < len(sys.argv):
            _one_msg(sys.argv[i + 1])
            return 0
        print("--msg には msg_id が要る")
        return 2

    live = []
    try:
        with open(TONE_AUDIT, encoding="utf-8") as f:
            for ln in f:
                if '"tone_structure"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:                    # noqa: BLE001
                    continue
                if d.get("event") != "tone_structure":
                    continue
                if persona and d.get("persona") != persona:
                    continue
                live.append(d)
    except OSError:
        pass
    want_leaks = "--leaks" in sys.argv
    _summarize("live(合流点の実測)" + (f" persona={persona}" if persona else ""), live)
    if want_leaks:
        _leaks("live" + (f" persona={persona}" if persona else ""), live, _audit_links())

    if "--backfill" in sys.argv:
        # ★母集団を人格の便だけに絞る(2026-09-16 AD研究室 msg 1549612208940654593 の
        #   「分母の取り方を1行で聞かせてくれ」で数え直して判った欠陥)=
        #   recent_*.jsonl の 195便のうち **103便が chami_fusoh 本人**、他に完遂通知・
        #   定刻トリガー等の自動便が混ざっていた。Chamiが人格名を呼ぶのは正常なので、
        #   軸③(他人格の引っ張り)の分母にそれを入れると数字が意味を失う。
        #   ★口調ルール.json に載っている人格だけを母集団にする。--all で従来どおり全部。
        known = set((_load_rules().get("personas") or {}).keys())
        only_personas = "--all" not in sys.argv and bool(known)
        rows = []
        for p in sorted(glob.glob(RECENT)):
            try:
                with open(p, encoding="utf-8") as f:
                    for ln in f:
                        try:
                            d = json.loads(ln)
                        except Exception:            # noqa: BLE001
                            continue
                        a = d.get("author")
                        b = d.get("body")
                        if not b or not a:
                            continue
                        if persona and a != persona:
                            continue
                        if only_personas and not any(
                                a == k or a.startswith(k) for k in known):
                            continue
                        r = count_structure(b, persona=a)
                        r["persona"] = a
                        # ★一覧(--leaks)で辿れるように出所を載せる= 過去便には実IDが在る。
                        r["msg_id"] = str(d.get("msg_id") or "")
                        r["ts"] = str(d.get("ts") or d.get("created_at") or "")
                        rows.append(r)
            except OSError:
                continue
        _summarize("backfill(過去便・台帳へは書かない"
                   + ("・人格の便だけ" if only_personas else "・--all=全便")
                   + ")" + (f" persona={persona}" if persona else ""), rows)
        # ★下振れの注意。recent_*.jsonl の body は700字で切られている(2026-09-16 実測=
        #   195便中59便が700字ちょうど)。切られた後ろに在る区切り線・番号ラベルは数えられない=
        #   backfill の数字は**下限**だ。閾値をこの母集団だけで決めるな。live が溜まるのを待て。
        cut = sum(1 for r in rows if r.get("chars", 0) >= 700)
        if cut:
            print(f"  ★注意: {cut}/{len(rows)} 便が700字で切られた本文だ= この分布は**下限**。")
        if want_leaks:
            _leaks("backfill" + (f" persona={persona}" if persona else ""), rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
