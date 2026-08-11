#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_pulse — 定期発火の進捗押し出し便(可視化・★督促ではない)。

背景(HQ発注 DISPATCH-aegis-gl / Chami重大インシデント 2026-08-01〜02):
  完了報告の「押し出し」経路が無かった。change_log.jsonl は §3.8で「貯めるだけ・
  知らせに行くな(Chami『テキストだけ貯めといて』)」の**受動台帳**で、Chamiが自分で
  見に行かない限り進捗が可視化されない。→ Chami「応答なし・自律的報告なし・改善してくれ」。
  日次報告便(daily_report.py)は0時/8時の2便で"動静の件数"は出すが、
  **「何を改修したか(change_log)」を押し出さない**=作業の実物が見えない。

役割(HQ指定「数時間ごと or 日次で change_log/git log の未報告分を整形しChamiの部屋へ1通」):
  数時間ごとに発火し、前回マーカー以降の change_log の"未報告分"だけを
  結論行(§4.5 目安5行以内)へ丸めて報告部屋へ1通。
  ★**新規が無ければ沈黙**(督促にしない=ORG-42「常に鳴る警報は読まれなくなる」。
  純粋な生存確認は日次便=daily_report.py の担当。ここは"変化があった時だけ"喋る)。

v1の範囲(★正直に明記=daily_report.py の作法を踏襲):
  正本= change_log.jsonl(§3.8の curated ledger。何/なぜ/commit が揃う)。
  ★**change_log に無い素のcommit**(bump等)は v1では拾わない。二重報告と騒音を避けるため。
  必要になったら git log 側の"changelogに無いcommit"を副節で足す(未実装)。

マーカー: local/llm/report_pulse_marker.json = {"last_ts": ISO8601}
  ★**送信に成功した時だけ前進**させる(送信失敗で取りこぼさない=§3 fail-open寄り)。
  初回(マーカー無し)は現時点の最新entryで**種蒔きのみ・送信しない**(過去249件を一気に吐かない)。

使い方: python scripts/report/report_pulse.py [--send]
  --send無し = 印字のみ(検証用・マーカー不変)。
"""
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LOCAL = os.path.join(ROOT, "local")
CHANGE_LOG = os.path.join(LOCAL, "llm", "change_log.jsonl")
MARKER = os.path.join(LOCAL, "llm", "report_pulse_marker.json")
# ★着弾先を「Chami依頼元部屋」へ向ける(設計_report_pulse着弾先の根治_2026-08-03.md §A)。
#   change_log の任意フィールド `report_to`(=依頼元部屋のslug)でグループ化し、その部屋へも1本出す。
#   report-notify への全体ダイジェストは**従来どおり必ず送る**(監査証跡・マーカー前進の条件はこちら)。
SENT_STATE = os.path.join(LOCAL, "llm", "report_pulse_sent.json")
DEFAULT_REPORT_PERSONA = "オタコン"      # entry に report_persona が無い時の名義

sys.path.insert(0, os.path.join(ROOT, "scripts", "_common"))
try:
    from dept_names import dept_ja           # 部門名は日本語で(C-020・Chami指示)
except Exception:                            # fail-safe: 変換できなくても便は必ず出す
    def dept_ja(slug, with_slug=False):
        return slug

JST = timezone(timedelta(hours=9))
WEEK = ("月", "火", "水", "木", "金", "土", "日")


def _parse_ts(s):
    """change_log の ts をaware datetimeへ。tz無しはJSTとみなす。壊れていればNone。"""
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=JST) if dt.tzinfo is None else dt


def _load_marker():
    try:
        return _parse_ts(json.load(io.open(MARKER, encoding="utf-8")).get("last_ts"))
    except Exception:
        return None


def _save_marker(ts_dt):
    with io.open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"last_ts": ts_dt.isoformat()}, f, ensure_ascii=False)


def _entries():
    """change_log を新しい順ではなく、そのまま(古い→新しい)で読み、(ts_dt, rec)の列にする。"""
    out = []
    if not os.path.exists(CHANGE_LOG):
        return out
    for l in io.open(CHANGE_LOG, encoding="utf-8"):
        l = l.strip()
        if not l:
            continue
        try:
            rec = json.loads(l)
        except ValueError:
            continue
        ts = _parse_ts(rec.get("ts"))
        if ts is not None:
            out.append((ts, rec))
    out.sort(key=lambda x: x[0])
    return out


# ★「何」は §3.8 で「日本語1文の要約」と決まっている=途中で切ると意味そのものが消える。
#   旧実装は 44字で強制カットしていた(実測: change_log 578件のうち 482件=83% が犠牲)。
#   2026-08-10 Chami報告「途中で消えててわからない」で発覚(報告通知 msg_id=1536091578341269624)。
#   →★字数ではなく**文の切れ目**で畳む。畳むのは長文だけで、大半はそのまま最後まで出す。
LINE_MAX = 300        # 1行の上限(実測95%tile=187字なので、ほとんどの「何」はここに収まる)
TEXT_MAX = 1900       # Discord 2000字上限に対する余白(超えそうな時だけ全体を締め直す)
_BREAKS = "。！？!?、,・"


def _fold(s, n=LINE_MAX):
    """n字を超える時だけ、句読点の切れ目で畳む(★用言の手前で切らない)。"""
    s = str(s or "").replace("\n", " ").strip()
    if len(s) <= n:
        return s                              # ここが通常経路= 1文まるごと出る
    cut = max(s.rfind(c, 0, n + 1) for c in _BREAKS)
    if cut < n // 3:                          # 切れ目が無い/前すぎる=やむを得ず字数で切る
        cut = n
    else:
        cut += 1                              # 区切り記号まで含める(文として読める形で終える)
    return s[:cut].rstrip("、,・") + "…"


def _digest(fresh, head):
    """entries を結論行へ丸める(§4.5 目安5行以内)。明細は最大4件+超過は「他N件」。"""
    LIMIT = 4
    show = fresh[-LIMIT:] if len(fresh) > LIMIT else fresh   # 新しい順に近い方(末尾)を優先

    def build(limit):
        lines = [f"・{dept_ja(r.get('dept', '?'))}: {_fold(r.get('何'), limit)}"
                 for _ts, r in show]
        if len(fresh) > LIMIT:
            lines.append(f"・(ほか {len(fresh) - LIMIT}件は change_log 参照)")
        return "\n".join([head] + lines)

    limit, text = LINE_MAX, build(LINE_MAX)
    while len(text) > TEXT_MAX and limit > 60:   # 長文が重なった便だけ締め直す(送信落ち防止)
        limit //= 2
        text = build(limit)
    return text


def _room_groups(fresh):
    """report_to を持つ entry を部屋ごとに束ねる。→ {slug: [(ts, rec), ...]}(順序は入力のまま)。"""
    groups = {}
    for ts, r in fresh:
        slug = str(r.get("report_to") or "").strip()
        if slug:
            groups.setdefault(slug, []).append((ts, r))
    return groups


def _load_sent():
    try:
        v = json.load(io.open(SENT_STATE, encoding="utf-8"))
        return set(v) if isinstance(v, list) else set()
    except Exception:
        return set()                          # 状態が読めなくても便は止めない(fail-safe)


def _save_sent(sent):
    try:
        with io.open(SENT_STATE, "w", encoding="utf-8") as f:
            json.dump(sorted(sent), f, ensure_ascii=False)
    except Exception as e:                    # 追加送信の記録失敗で本便を落とさない
        print(f"[report_pulse] 送信済セットの保存に失敗(無視して続行): {e}")


def build(send=False):
    """戻り値: (本文 or None, 前進させるべきts or None, 状態文字列, 部屋別グループ dict)。"""
    entries = _entries()
    if not entries:
        return None, None, "change_log が空", {}
    newest_ts = entries[-1][0]
    marker = _load_marker()

    if marker is None:                       # ★初回=種蒔きのみ(過去分を吐かない)
        if send:
            _save_marker(newest_ts)
        return None, None, f"初回:マーカーを {newest_ts.isoformat()} で種蒔き(送信なし)", {}

    fresh = [(ts, r) for (ts, r) in entries if ts > marker]
    if not fresh:
        return None, None, "未報告なし(前回以降に新規のchange_logは無い)=沈黙", {}

    now = datetime.now(JST)
    head = f"■進捗 {now.month}/{now.day:02d}({WEEK[now.weekday()]}) {now:%H:%M} — 前回以降 {len(fresh)}件"
    text = _digest(fresh, head)
    groups = _room_groups(fresh)
    state = f"未報告 {len(fresh)}件 → 送信対象"
    if groups:
        state += "(依頼元部屋への押し出し: " + " / ".join(
            f"{dept_ja(k)}{len(v)}件" for k, v in groups.items()) + ")"
    return text, newest_ts, state, groups


def _post(dept, persona, text, tag):
    """1通送る。戻り値=成功したか。★例外は握り潰す(1部屋の失敗で便全体を落とさない)。"""
    try:
        tmp = os.path.join(LOCAL, f"_report_pulse_body_{tag}.txt")
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "discord", "persona_send.py"),
             "--dept", dept, "--persona", persona, "--body-file", tmp],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        print((r.stdout or "").strip().splitlines()[-1] if r.stdout else f"送信rc={r.returncode}")
        return r.returncode == 0
    except Exception as e:
        print(f"[report_pulse] {dept} への送信で例外(無視して続行): {e}")
        return False


# ★部屋別の押し出し(②)は既定OFF(2026-08-11 Chami指示 msg_id=1536639654760284220
#   「これ各部門のチャットで進捗表示されるけど別にいらないんだけど。」)。
#   ①報告通知部門への全体ダイジェストは従来どおり出す(監査証跡・マーカー前進の条件)。
#   復活させたい時は --push-rooms を付けて起動する(コードは消していない)。
ROOM_PUSH = "--push-rooms" in sys.argv


def main():
    send = "--send" in sys.argv
    text, advance_ts, state, groups = build(send=send)
    print(state)
    if text is None:
        return 0
    print("----")
    print(text)
    now = datetime.now(JST)
    if ROOM_PUSH:
        for slug, items in groups.items():   # ★検証用に印字は --send 無しでも出す
            head = (f"■進捗 {now.month}/{now.day:02d}({WEEK[now.weekday()]}) {now:%H:%M}"
                    f" — {dept_ja(slug)}宛 {len(items)}件")
            print(f"---- → {slug}")
            print(_digest(items, head))
    elif groups:
        print(f"[report_pulse] 部屋別の押し出しは停止中(--push-rooms で復活): "
              + " / ".join(f"{dept_ja(k)}{len(v)}件" for k, v in groups.items()))
    if not send:
        return 0
    # ① 全体ダイジェスト(report-notify)= 監査証跡。★マーカー前進の条件はこちらだけ。
    ok = _post("report-notify", DEFAULT_REPORT_PERSONA, text, "all")
    if ok and advance_ts is not None:        # ★送れた時だけマーカーを前進(取りこぼし防止)
        _save_marker(advance_ts)
        print(f"マーカー前進: {advance_ts.isoformat()}")
    # ② 依頼元部屋への押し出し。失敗してもマーカーには触らない=致命にしない。
    if not ROOM_PUSH:                        # ★既定OFF(Chami 2026-08-11・上のROOM_PUSH参照)
        return 0 if ok else 1
    sent = _load_sent()
    changed = False
    for slug, items in groups.items():
        key = f"{slug}|{items[-1][0].isoformat()}"        # 同一部屋×同一tsを二度送らない
        if key in sent:
            print(f"[report_pulse] 送信済のためスキップ: {key}")
            continue
        head = (f"■進捗 {now.month}/{now.day:02d}({WEEK[now.weekday()]}) {now:%H:%M}"
                f" — {dept_ja(slug)}宛 {len(items)}件")
        persona = str(items[-1][1].get("report_persona") or DEFAULT_REPORT_PERSONA)
        if _post(slug, persona, _digest(items, head), slug.replace("/", "_")):
            sent.add(key)
            changed = True
        else:
            print(f"[report_pulse] ★{dept_ja(slug)} への押し出しに失敗(次便で再試行)")
    if changed:
        _save_sent(sent)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
