# -*- coding: utf-8 -*-
"""pending_age_watch — 「入れた(確認待ち)」に**日齢**を打ち、誰にも督促されないまま沈む穴を塞ぐ。

★なぜ在るか(2026-09-05 裁定 C-070・研究室HQ → イージス研究室 `DISPATCH-aegis-gl-1788503402548`)
  HQ実測= `00_AI-HQ/status/hq_open_items.md` の「確認待ち」84行。日付が読めた72件で最古46日・
  中央値22日。**入れた本人も、待っている側も、誰も日齢を見ていなかった。**
  → 3日超で**所有部門へ督促** / 7日超で**依頼元の部屋へ状態を1行**。
  ★**増分ではなく経過時間で鳴らす**(増分だけの監視は滞留を見逃す)。

★載せ方= 新しい定刻タスクを作らない。`watch_triggers.py` の **T6** として、既に定刻で回っている
  `quota_alarm.py` の頭から呼ばれる線に相乗りする(発火しない安全網は検証されない=§3)。

★在庫を一斉に鳴らさない(HQ要件4)= 状態ファイルに **基準日** を1回だけ焼き、
  **基準日より前の行は数えるが鳴らさない**。在庫の棚卸しはHQが別で持つ(HQ-0236)。

★日付が読めない行は「日齢不明」として**数だけ**出す(HQ要件5)。推定で埋めない(§4.55)。
  ただし拾い方はHQ指定の `★YYYY-MM-DD` だけでは足りない=**実測で 146行中100行が★を持たない**。
  行の中に素の `YYYY-MM-DD` が在ればそれも拾う(推測ではなく、行に書いてある字を読む)。
  どちらで読んだかは `date_src` に残す= 数え方を隠さない。

使い方:
  python scripts/llm/pending_age_watch.py --report     # 分布を見るだけ(便は出さない)
  python scripts/llm/pending_age_watch.py --dry-run    # 判定まで回して、出す便を画面に出す
  python scripts/llm/pending_age_watch.py              # 本番(T6 から呼ばれるのと同じ)
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
HQ = os.path.join(os.path.dirname(ROOT), "00_AI-HQ")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
STATUS = os.path.join(HQ, "status")
REGISTRY = os.path.join(HQ, "org_registry.yml")
STATE = os.path.join(ROOT, "local", "llm", "pending_age_state.json")
DISPATCH = os.path.join(ROOT, "scripts", "llm", "dispatch.py")

# ★基準日= ここより前の行は「在庫」として数えるだけで鳴らさない(HQ要件4)。
#   2026-09-01(直近の週の頭)に切った理由= 実測で、今日(09-05)に切ると鳴る行は0件=
#   **発火しない安全網は検証されない**。09-01なら 6件/5便= 景色にならず、しかも全部が本物の遅延。
#   在庫(112件)の棚卸しはHQが HQ-0236 で別に持つ。
BASELINE_DEFAULT = "2026-09-01"
AGE_REMIND = 3.0        # 日。所有部門へ督促(C-070)
AGE_ESCALATE = 7.0      # 日。依頼元の部屋へ状態を1行(C-070)
MAX_LINES_PER_MAIL = 12  # 1便に並べる件数の上限(残りは件数だけ)
SEND_DRY = False         # 真= dispatch.py は本当に起動するが投函だけ止まる(watch_triggers と同じ作法)

# ★「入れた(確認待ち)」。★直前が「 の時は**その語について喋っている行**= 対象外
#   (例= HQ-0236「『入れた(確認待ち)』の在庫84行を片付ける」は棚卸しの起票であって確認待ちではない)
PENDING = re.compile(r"(?<!「)入れた\(確認待ち\)")
STAR_DATE = re.compile(r"★\s*(\d{4})-(\d{2})-(\d{2})")
ANY_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
ITEM_ID = re.compile(r"\b((?:HQ|ORG|INC)-\d{2,5})\b")
CHECKBOX = re.compile(r"^\s*-\s*\[([ xX])\]")
# 依頼元の合図。この後ろに出てくる最初の部門名を「待っている側」と読む
REQ_MARK = re.compile(r"(?:発注|裁定|依頼|起票|指示|依頼元)\s*=")

# 台帳の字面に出る通称(org_registry.yml の display_ja に無い呼ばれ方)
EXTRA_ALIASES = {
    "改修α": "system-engineer", "改修部門α": "system-engineer",
    "改修β": "system-engineer-b", "改修部門β": "system-engineer-b",
    "改修γ": "ai-office", "改修部門γ": "ai-office",
    "イージスGL": "aegis-gl", "イージス研究室": "aegis-gl",
    "研究室HQ": "hq", "HQ": "hq",
    "ad研究室": "research-room", "AD研究室": "research-room",
}


def read_json(path, default=None):
    try:
        with io.open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def dept_aliases(registry=REGISTRY):
    """部門名 → スラッグ。正本= org_registry.yml の display_ja(§共通規律)。"""
    out = dict(EXTRA_ALIASES)
    try:
        import yaml
        doc = yaml.safe_load(io.open(registry, encoding="utf-8")) or {}
        for slug, v in (doc.get("depts") or {}).items():
            out.setdefault(slug, slug)
            dj = (v or {}).get("display_ja")
            if dj:
                out[dj] = slug
    except Exception as e:
        print("  ★org_registry.yml を読めなかった(通称だけで当てる): %s" % e)
    return out


def rooms(registry=REGISTRY):
    """部屋が実在する部門のスラッグ。★居ない相手に預けない= 偽の受領が沈黙を隠す。"""
    try:
        import yaml
        doc = yaml.safe_load(io.open(registry, encoding="utf-8")) or {}
        return {c.get("dept") for c in (doc.get("channels") or []) if c.get("dept")}
    except Exception:
        return set()


def _leftmost(text, alias):
    """行の中で**一番左**に出る部門名を返す。見出しや札は行頭側に在る=そこが持ち主。"""
    best = None
    for name, slug in alias.items():
        i = text.find(name)
        if i < 0:
            continue
        # 同じ位置から始まるなら長い方(「改修部門α」>「改修α」)
        if best is None or i < best[0] or (i == best[0] and len(name) > best[2]):
            best = (i, slug, len(name))
    return best


def parse_line(text, alias):
    """1行から (日付, date_src, 所有部門, 依頼元) を読む。読めない所は None。"""
    m = STAR_DATE.search(text)
    src = "star"
    if not m:
        m = ANY_DATE.search(text)
        src = "line"
    date = None
    if m:
        try:
            date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=JST)
        except ValueError:
            date = None
    if date is None:
        src = None

    # ★台帳IDを伏せてから部門名を探す= `HQ-0034` の "HQ" を持ち主と読み違えない
    masked = ITEM_ID.sub("  ", text)
    # 持ち主は「入れた(確認待ち)・<部門>」の形で札の直後に書かれることが多い= そこを先に見る。
    # 無ければ行の一番左(見出し・commit札が行頭側に在る)。★どちらも当て推量ではなく字面。
    owner = None
    pm = PENDING.search(masked)
    if pm:
        near = _leftmost(masked[pm.end():pm.end() + 30], alias)
        owner = near[1] if near else None
    if not owner:
        near = _leftmost(masked, alias)
        owner = near[1] if near else None

    req = None
    rm = REQ_MARK.search(masked)
    if rm:
        tail = _leftmost(masked[rm.end():rm.end() + 60], alias)
        if tail:
            req = tail[1]
    return date, src, owner, req


def ledger_files(status=STATUS):
    """対象= 現行 + 月別アーカイブ(HQ要件1)。.bak は見ない(退避であって台帳ではない)。"""
    out = [os.path.join(status, "hq_open_items.md")]
    out += sorted(glob.glob(os.path.join(
        status, "archive", "hq_open_items_[0-9][0-9][0-9][0-9]-[0-9][0-9].md")))
    return [p for p in out if os.path.exists(p)]


def scan(now, files=None, alias=None):
    """台帳を1周して「入れた(確認待ち)」行を全部拾う。**判定はしない**(数えるだけ)。"""
    alias = alias if alias is not None else dept_aliases()
    items = []
    for path in (files if files is not None else ledger_files()):
        for no, raw in enumerate(io.open(path, encoding="utf-8", errors="replace"), 1):
            text = raw.rstrip("\n")
            if not PENDING.search(text):
                continue
            cb = CHECKBOX.match(text)
            if cb and cb.group(1).lower() == "x":
                continue                       # 閉じ済みのチェックボックスは対象外
            date, src, owner, req = parse_line(text, alias)
            mid = ITEM_ID.search(text)
            key = mid.group(1) if mid else "L" + hashlib.sha1(
                text.strip().encode("utf-8")).hexdigest()[:10]
            items.append({
                "key": key,
                "file": os.path.basename(path),
                "line": no,
                "date": date.strftime("%Y-%m-%d") if date else None,
                "date_src": src,
                "age": round((now - date).total_seconds() / 86400.0, 1) if date else None,
                "dept": owner,
                "req": req or "hq",          # 台帳の持ち主= 研究室HQ(読めない時の受け皿)
                "head": text.strip()[:110],
            })
    return items


def summarize(items, baseline):
    """数え方を添えた分布。★不明は不明のまま数える(§4.55)。"""
    dated = [i for i in items if i["age"] is not None]
    unknown = [i for i in items if i["age"] is None]
    fresh = [i for i in dated if i["date"] >= baseline]
    stock = [i for i in dated if i["date"] < baseline]
    ages = sorted(i["age"] for i in dated)
    return {
        "total": len(items),
        "dated": len(dated),
        "unknown": len(unknown),
        "by_star": len([i for i in dated if i["date_src"] == "star"]),
        "by_line": len([i for i in dated if i["date_src"] == "line"]),
        "fresh": len(fresh),
        "stock": len(stock),
        "oldest": ages[-1] if ages else None,
        "median": ages[len(ages) // 2] if ages else None,
        "over3": len([i for i in dated if i["age"] > AGE_REMIND]),
        "over7": len([i for i in dated if i["age"] > AGE_ESCALATE]),
        "no_dept": len([i for i in items if not i["dept"]]),
    }


def decide(items, baseline, fired, live=None):
    """鳴らす対象を決める。★基準日より前(=在庫)は**数えるが鳴らさない**(HQ要件4)。

    返り値= (3日超で督促する部門ごとの束, 7日超で報告する部屋ごとの束)
    """
    live = rooms() if live is None else live

    def to(slug):
        # 部屋が無い部門へ投げると便が消える= 台帳の持ち主(研究室HQ)が受け取る
        return slug if (slug and (not live or slug in live)) else "hq"

    d3, d7 = {}, {}
    for it in items:
        if it["age"] is None or it["date"] < baseline:
            continue
        st = fired.get(it["key"]) or {}
        if it["age"] > AGE_ESCALATE and not st.get("d7"):
            d7.setdefault(to(it["req"]), []).append(it)
        elif it["age"] > AGE_REMIND and not st.get("d3"):
            d3.setdefault(to(it["dept"]), []).append(it)
    for g in (d3, d7):
        for v in g.values():
            v.sort(key=lambda x: -x["age"])
    return d3, d7


def _rows(items):
    out = []
    for it in items[:MAX_LINES_PER_MAIL]:
        out.append("  - **%.1f日** `%s` %s:%s%s\n      %s"
                   % (it["age"], it["key"], it["file"], it["line"],
                      "" if it["date_src"] == "star" else "(★印なし=行内の日付で読んだ)",
                      it["head"]))
    if len(items) > MAX_LINES_PER_MAIL:
        out.append("  - …ほか %d件(全部は台帳側に在る)" % (len(items) - MAX_LINES_PER_MAIL))
    return "\n".join(out)


def _foot(stats, baseline):
    return ("\n★数え方= `status/hq_open_items.md` + `status/archive/hq_open_items_<年-月>.md` の"
            "「入れた(確認待ち)」行 %d件を1周。日付が読めたのは %d件"
            "(★印 %d / 行内の日付 %d)、**日齢不明 %d件**(推定で埋めていない)。\n"
            "★基準日 %s より前の %d件(在庫)は数えたが鳴らしていない= 棚卸しはHQが別で持つ(HQ-0236)。\n"
            "★宛先は台帳の字面から機械が当てている(札の直後の部門名 → 無ければ行の一番左)。"
            "違うなら1行返してくれ= 誤配は台帳の書き方の側で直す。\n"
            "★出所= 裁定 C-070 / 見張り `scripts/llm/pending_age_watch.py`(定刻 watch_triggers T6)。"
            % (stats["total"], stats["dated"], stats["by_star"], stats["by_line"],
               stats["unknown"], baseline, stats["stock"]))


GUARD_LEAD = re.compile(r"の部門長は\s*'([A-Za-z0-9_-]+)'")


def _dispatch_once(dept, text):
    path = os.path.join(ROOT, "local", "_pending_age_body.txt")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    cmd = [sys.executable, DISPATCH, "--dept", dept, "--from-dept", "aegis-gl",
           "--from", "日齢の見張り(定刻・イージス研究室)", "--audience", "ai",
           "--body-file", path]
    if SEND_DRY:                    # ★配線の検証用= dispatch.py は本当に起動し、投函だけ止まる
        cmd.append("--dry-run")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    print("   dispatch %s rc=%s %s" % (dept, p.returncode, out[:160]))
    return p.returncode, out


def send_dispatch(dept, title, body, dry):
    """便を1本。★宛先は台帳から機械が決める= 人手の入口を要件にしない(§3)。"""
    text = "【日齢の見張り(C-070)】%s\n\n%s" % (title, body)
    if dry:
        print("---- dry-run(送らない) → dept=%s ----\n%s\n" % (dept, text))
        return True
    rc, out = _dispatch_once(dept, text)
    if rc == 0:
        return True
    # ★3階梯(RULES §6.4)で弾かれたら、その部門の部門長へ回す。
    #   ここで --direct へ逃げない= 飛び級を機構で誤魔化すと、階梯が形だけになる。
    m = GUARD_LEAD.search(out)
    if m and m.group(1) != dept:
        lead = m.group(1)
        note = ("★本来の宛先= **%s**。3階梯(RULES §6.4)でイージス研究室から直接は出せないので、"
                "部門長の当室へ回した。配下への割り振りを頼む。\n\n" % dept)
        rc2, _ = _dispatch_once(lead, "【日齢の見張り(C-070)】" + note + title + "\n\n" + body)
        return rc2 == 0
    return False


def run(now=None, dry=False, sender=None, state_path=STATE, files=None, save=True):
    """T6の本体。**鳴らした分だけ**状態へ焼く(同じ便を毎時間送り直さない)。"""
    now = now or datetime.now(JST)
    sender = sender or send_dispatch
    st = read_json(state_path, {}) or {}
    baseline = st.get("baseline") or BASELINE_DEFAULT
    fired = st.setdefault("fired", {})

    items = scan(now, files=files)
    stats = summarize(items, baseline)
    print("T6 確認待ち %d件(日付あり %d / 不明 %d)・3日超 %d / 7日超 %d ・基準日 %s(在庫 %d件は鳴らさない)"
          % (stats["total"], stats["dated"], stats["unknown"],
             stats["over3"], stats["over7"], baseline, stats["stock"]))
    d3, d7 = decide(items, baseline, fired)
    if not d3 and not d7:
        if save and not dry:
            st["baseline"] = baseline
            st["last_run"] = now.strftime("%Y-%m-%dT%H:%M:%S")
            write_json(state_path, st)
        return 0

    n = 0
    for dept, rows in sorted(d3.items()):
        ok = sender(dept, "**%d件が3日を超えた**。入れた本人の確認が要る。" % len(rows),
                    "「入れた(確認待ち)」のまま日齢が3日を超えた行だ。**入れただけでは閉じない**"
                    "(§4.55)= 壊れていたのと同じ場面の実物を見て `close_item.py` か台帳で閉じるか、"
                    "**まだ見られていないなら『まだ見ていない』と1行書け**。\n\n"
                    + _rows(rows) + "\n" + _foot(stats, baseline), dry)
        if ok:
            n += 1
            for it in rows:
                fired.setdefault(it["key"], {})["d3"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    for dept, rows in sorted(d7.items()):
        ok = sender(dept, "**%d件が7日を超えた**。依頼元の部屋へ状態を出す。" % len(rows),
                    "3日の督促を過ぎても閉じていない行だ。**待っている側が知らないまま沈むのが"
                    "C-070の穴**= 進んでいないなら進んでいないと書けばいい。\n\n"
                    + _rows(rows) + "\n" + _foot(stats, baseline), dry)
        if ok:
            n += 1
            for it in rows:
                d = fired.setdefault(it["key"], {})
                d["d7"] = now.strftime("%Y-%m-%dT%H:%M:%S")
                d.setdefault("d3", d["d7"])
    if save and not dry:
        st["baseline"] = baseline
        st["last_run"] = now.strftime("%Y-%m-%dT%H:%M:%S")
        write_json(state_path, st)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="分布だけ見る(判定も送信もしない)")
    ap.add_argument("--dry-run", action="store_true", help="判定まで回して便は画面に出すだけ")
    a = ap.parse_args()
    now = datetime.now(JST)
    if a.report:
        items = scan(now)
        st = read_json(STATE, {}) or {}
        base = st.get("baseline") or now.strftime("%Y-%m-%d")
        s = summarize(items, base)
        print(json.dumps(s, ensure_ascii=False, indent=1))
        for it in sorted([i for i in items if i["age"] is not None],
                         key=lambda x: -x["age"])[:15]:
            print("  %6.1f日 %-10s %-24s:%-5s %s" % (it["age"], it["dept"] or "-",
                                                     it["file"], it["line"], it["head"][:70]))
        return 0
    print("→ 発火 %d本" % run(now, dry=a.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
