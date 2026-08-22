# -*- coding: utf-8 -*-
"""対応表の「山(context_peak_tokens)」と「床(floor_tokens)」を**記録ファイルから測って**埋める。

★何のための道具か(2026-08-22・イージス研究室)
  定期リフレッシュの判定は山を見る(谷を見ると圧縮するほど交代しなくなるため)。床は
  「毎便必ず再送する固定費」で、圧縮の直後に台帳へ入る値が持ち越し量だけにならないための下駄。
  どちらも**普通に便が流れていれば relay が自分で入れる**。この道具が要るのは次の2場面だけ:
    ① 対応表が壊れて手で復元した後(実測 2026-08-22 16:48 研究室HQ・ORG-47)。
       復元した行には山も床も無いので、その部屋は「測れていない」状態に戻る。
    ② 山・床の仕組みを入れた直後(既に走っている世代には過去の実測が無い)。
★測るのであって推測しない= 各部屋の**現行セッションの記録ファイル**を全行読み、
  assistant 行(サブエージェントを除く)の input+cache読み+cache作成 から
  山= 最大値 / 床= 最小値 を出す。読めない部屋は**触らない**(0で埋めない)。
★既定は --check(読むだけ)。書くのは --apply の時だけ。
  書く時も **relay と同じ save_room** を通す= 他の部屋・進んだ世代を巻き込まない。

使い方:
    python scripts/llm/seed_context_marks.py           # 今どうなっているかを見るだけ
    python scripts/llm/seed_context_marks.py --apply   # 欠けている列だけ埋める
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_relay as sr          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                    # noqa: BLE001
    pass


def measure(sid):
    """記録ファイルから (山, 床, 行数)。読めなければ (0, 0, 0)。"""
    if not sid:
        return 0, 0, 0
    path = sr._transcript_path(sid)
    if not path or not os.path.exists(path):
        return 0, 0, 0
    hi, lo, n = 0, 0, 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant" or d.get("isSidechain"):
                continue          # ★サブエージェントは別の文脈= 混ぜない(relay と同じ規則)
            u = ((d.get("message") or {}).get("usage")) or {}
            if not isinstance(u, dict) or not u:
                continue
            t = (int(u.get("input_tokens") or 0)
                 + int(u.get("cache_read_input_tokens") or 0)
                 + int(u.get("cache_creation_input_tokens") or 0))
            if t <= 0:
                continue
            n += 1
            hi = max(hi, t)
            lo = t if not lo else min(lo, t)
    return hi, lo, n


def main(argv):
    apply_ = "--apply" in argv
    table = sr.load_sessions() or {}
    print("== 対応表の山と床(%s) ==" % ("書き込む" if apply_ else "読むだけ"))
    print("%-18s %-10s %-10s %-10s %s" % ("部屋", "山", "床", "直近", "したこと"))
    touched = 0
    for dept in sorted(table):
        entry = table[dept]
        sid = str(entry.get("active_session_id") or "")
        peak = int(entry.get("context_peak_tokens") or 0)
        floor = int(entry.get("floor_tokens") or 0)
        ctx = int(entry.get("context_tokens") or 0)
        carry = int(entry.get("carry_tokens") or 0)
        did = []
        if not (peak and floor):
            hi, lo, n = measure(sid)
            if not n:
                did.append("記録が読めない=触らない")
            else:
                if not peak and hi:
                    entry["context_peak_tokens"] = peak = hi
                    did.append("山を実測(%d行)" % n)
                if not floor and lo:
                    entry["floor_tokens"] = floor = lo
                    did.append("床を実測")
        # ★圧縮の直後に持ち越し量だけが入っている行は、測れた床を足して**次の便が払う量**にする。
        #   (床が分かる前に書かれた行= 実測 hq 9,039 / system-engineer-b 3,953 等)
        # ★見分け方は **ctx < 床**。1便で必ず払う固定費より小さい文脈量は定義上あり得ないので、
        #   その行には持ち越し量だけが入っている。carry と一致するかで見ない=
        #   普通の便でも carry には同じ値が入る(read_transcript が両方に最後の実測を入れる)ため、
        #   一致で見ると platform-se 142,931 のような**正しい行まで倍にしてしまう**(実測で発覚)。
        if floor and ctx and ctx < floor:
            carry = ctx
            entry["carry_tokens"] = carry
            entry["context_tokens"] = ctx = carry + floor
            entry["context_source"] = "transcript+圧縮直後(床は記録の実測)"
            did.append("持ち越し%s+床=%s へ直す" % (format(carry, ","), format(ctx, ",")))
        if did and apply_:
            sr.save_room(dept, entry)
            touched += 1
        print("%-18s %-10s %-10s %-10s %s"
              % (dept, format(peak, ",") or "-", format(floor, ",") or "-",
                 format(ctx, ","), " / ".join(did) or ""))
    print("")
    print("書き込んだ部屋= %d (%s)" % (touched if apply_ else 0,
                                  "--apply" if apply_ else "--apply を付けると書く"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
