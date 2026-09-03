# -*- coding: utf-8 -*-
"""MEMORY.md を部屋別に割ったら索引が何トークンになるかを**実データで**測る(見積の裏取り)。

★なぜ要るか(2026-09-03・人事部門ククール→イージス研究室)
  Chami「トークン減らしたり、ミスが起こったりするのを防ぐことできないかなって」。
  人事部門の調べで「95本すべて生きた事実で、安全に削れる死に体は無い」「効くのは構造= 部屋別索引」
  まで出た。だが**どの部屋がどれだけ軽くなるか**は測られていなかった。効き幅を知らずに
  構造を変えると、大工事の割に減らない(あるいは減らす必要が無い部屋を壊す)ので先に測る。

★何を測るか
  MEMORY.md の索引1行ずつに「どの部屋で自動で読まれるべきか」を割り当て(SCOPE)、
  部屋ごとに索引を組み直して**文字数**を出す。トークンは文字数×比率で換算する。
  比率は人事部門の実測値(7,897字 = 5,560トークン → 0.704 tok/char)を使う。
  ★これは換算であって計測ではない。桁を見るための数字として扱う。

★何を測っていないか(誤読を防ぐために先に書く)
  中身の正しさは見ていない。SCOPE の割り当ては人手の判断で、機械的な根拠は無い。
  ここで出るのは「この割り当てならこう減る」であって「この割り当てが正しい」ではない。

★C-045(部屋を跨いで記憶を持つ設定を、文脈を軽くする改修で削るな)
  この検討は**索引(自動で読まれる目次)だけ**を部屋別にする。記憶ファイル95本は1つの
  ディレクトリに置いたままで、どの部屋からも読める= recall は全体のまま。削除は1本もしない。

使い方:
  python scripts/llm/memory_index_scope_probe.py          # 部屋別の索引サイズ一覧
  python scripts/llm/memory_index_scope_probe.py --room hr-room --print   # その部屋の索引を出す
"""
import io
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MEMORY_DIR = os.path.join(
    os.path.expanduser("~"), ".claude", "projects",
    "D--SougouStartFolder-5SecMovieMaker", "memory")
MEMORY_MD = os.path.join(MEMORY_DIR, "MEMORY.md")

TOK_PER_CHAR = 5560.0 / 7897.0        # 人事部門の実測(2026-09-03)からの換算比

GLOBAL = "*"                          # 全部屋で読む(共通規律・Chami本人・作法)

# 索引行のリンク先(ファイル名)→ 自動で読ませたい部屋。
# ★GLOBAL は「どの部屋でも間違えると事故る規律」だけに絞る。迷ったら GLOBAL に倒す
#   (落として事故るより、載せて重い方が軽い害)。
SCOPE = {
    # --- 全部屋の規律・作法・Chami本人 -------------------------------------
    "feedback_client-doc-adult-tone-no-emoji.md": GLOBAL,
    "reflection-no-saved-preamble.md": GLOBAL,
    "room-session-must-not-self-send.md": GLOBAL,
    "feedback_recurrence-needs-permanent-fix.md": GLOBAL,
    "feedback_no-conclusion-without-evidence.md": GLOBAL,
    "handoff-moved-to-local-llm.md": GLOBAL,
    "ai-sennin-external-advisor.md": GLOBAL,
    "naming-5sec-not-go5.md": GLOBAL,
    "project_pivot-5ch-vtuber-manga.md": GLOBAL,
    "coach-no-rest-work-together.md": GLOBAL,
    "chami-sole-proprietor.md": GLOBAL,
    "passphrase.md": GLOBAL,
    "gemini-free-tier-is-per-model.md": GLOBAL,
    "manga-to-shorts-goal.md": GLOBAL,
    "biz-division-transition-planned.md": GLOBAL,
    "cwd-must-be-go5maker.md": GLOBAL,
    "escalation-to-main-box.md": GLOBAL,
    "limit-notify-retired.md": GLOBAL,
    "report-via-discord.md": GLOBAL,
    "wake-order-retreat-first.md": GLOBAL,
    "discord-approval-not-honored.md": GLOBAL,
    "never-fired-never-verified.md": GLOBAL,
    "discord-send-reliability.md": GLOBAL,
    "hr-idle-output-discipline.md": GLOBAL,
    "persona-voice-drifts-to-claude.md": GLOBAL,
    "no-self-introduction-in-discord.md": GLOBAL,
    "ui-instructions-in-japanese.md": GLOBAL,
    "meeting-dont-steamroll-chami.md": GLOBAL,
    "parallel-git-clobbers-worktree.md": GLOBAL,
    "staged-files-swept-by-parallel-commit.md": GLOBAL,
    "untracked-lost-without-commit.md": GLOBAL,
    "origin-verify-use-ls-tree.md": GLOBAL,
    "feedback_approval-stop-less.md": GLOBAL,
    "commit-standing-approval.md": GLOBAL,
    "path-commit-still-mixes-same-file.md": GLOBAL,
    "land-single-commit-via-worktree.md": GLOBAL,
    "feedback_numbered-options-format.md": GLOBAL,
    "feedback_hash-needs-repo-name.md": GLOBAL,
    "increment-only-alerts-miss-persisting-issues.md": GLOBAL,
    "verify-before-first-boot-report.md": GLOBAL,

    # --- 研究室HQ(イージス研究室)= 装置・常駐・配達・裁定 -------------------
    "qa-owns-notation-corruption.md": ["hq", "qa-reviewer"],
    "freshness-alarm-producer-registry.md": ["hq", "platform-se"],
    "daemon-reload-two-mechanisms.md": ["hq", "platform-se"],
    "english-dump-gate-at-confluence.md": ["hq", "platform-se"],
    "routing-deploy-proposal-alpha-direct.md": ["hq"],
    "model-override-policy-work-only.md": ["hq"],
    "feedback_platform-se-is-plumbing-not-adafi.md": ["hq", "platform-se"],
    "lab-claim-on-startup.md": ["hq"],
    "hq-identity-and-room-on-revive.md": ["hq"],
    "lab-revive-task-disabled.md": ["hq"],
    "escalate-needs-live-consumer.md": ["hq"],
    "daipa-race-double-post.md": ["hq"],
    "main-box-dept-duplicates.md": ["hq"],
    "remote-control-no-full-auto.md": ["hq"],
    "dont-centralize-delegate.md": ["hq"],
    "replied-unverified-is-race-not-loss.md": ["hq", "ad-room"],
    "permanent-fix-design-doc.md": ["hq"],
    "new-dept-channel-dropped-until-gateway-restart.md": ["hq", "platform-se"],
    "llm-growth-box-never-delivered.md": ["hq", "llm-edu"],
    "drain-window-loses-messages.md": ["hq", "platform-se"],
    "discord-target-architecture.md": ["hq"],
    "resilience-layers.md": ["hq"],
    "script-launched-claude-auth.md": ["hq"],
    "macbook-and-notion-plan.md": ["hq"],
    "launch-discord-primary.md": ["hq"],
    "chime-inbox-waiter.md": ["hq", "platform-se"],
    "hidden-daemons.md": ["hq"],
    "remote-uptime-logon-gap.md": ["hq"],
    "discord-needs-open-commander.md": ["hq"],
    "auto-poll-responsiveness.md": ["hq"],
    "idle-let-heartbeat-expire.md": ["hq"],
    "subordinate-rooms-dont-report-check-git.md": ["hq"],
    "waiter-never-shell-background.md": ["hq", "platform-se"],
    "incident-dept-external-ownership.md": ["hq"],

    # --- 人事部門(人格・呼称・characterfile) --------------------------------
    "persona-hub-image-add-via-inbox.md": ["hr-room"],
    "feedback_alonso-no-keigo.md": ["hr-room", "hq"],
    "persona-tag-leaks-when-not-in-room-roster.md": ["hr-room", "hq"],
    "dept-roster-two-lists.md": ["hr-room", "hq", "platform-se"],
    "avatar-cdn-expiry.md": ["hr-room"],
    "persona-tone-and-no-at-rule.md": ["hr-room", "ai-office"],
    "system-engineer-b-persona-tone-mapping.md": ["hr-room", "system-engineer-b"],

    # --- 運用(投稿・記録・リンク) ------------------------------------------
    "live-chain-bluesky-to-x.md": ["ad-room", "shorts-analyst"],
    "record-sheet-merge-not-delete.md": ["ad-room", "shorts-analyst"],
    "link-mint-additive-only.md": ["ad-room"],

    # --- グッズサイト -------------------------------------------------------
    "dmm-affi-no-scheduled-report-email.md": ["goods-afi"],
    "goods-afi-vtuber-expansion.md": ["goods-afi"],
    "competitor-monitor-split.md": ["goods-afi", "system-engineer", "system-engineer-b"],

    # --- 制作・学習 ---------------------------------------------------------
    "5ch-scraper-io-migration.md": ["system-engineer", "research-room"],
    "llm-edu-goal-strongest.md": ["llm-edu"],
    "manga-shorts-goal-sample-and-type.md": ["system-engineer", "llm-edu"],
    "chami-style-lora-training.md": ["llm-edu"],
    "copy-director-no-voice-split.md": ["copy-director"],
    "learning-room-kaizen-design.md": ["llm-edu"],
    "local-llm-work-logging-learning.md": ["llm-edu"],
    "gemini-3way-room-setup.md": ["hq", "llm-edu"],
}

# ★見出しが `[` で始まる索引行が実在する(`- [[名前]タグは…](persona-tag-….md)`)。
#   `[^\]]*` だと最初の `]` で切れてリンクを取り落とす= 1本まるごと数え漏れた(実測で発覚)。
#   最後の `](` まで貪欲に取る。
_LINK = re.compile(r"^\s*-\s*\[.*\]\(([^)]+)\)")


def read_index(path=MEMORY_MD):
    """MEMORY.md を (種別, 本文, リンク先) の列にする。種別= entry / other。"""
    out = []
    for ln in io.open(path, encoding="utf-8").read().split("\n"):
        m = _LINK.match(ln)
        out.append(("entry", ln, m.group(1)) if m else ("other", ln, None))
    return out


def rooms_for(target):
    """その記憶を自動で読ませる部屋。★未割り当ては GLOBAL に倒す(落として事故らせない)。"""
    return SCOPE.get(target, GLOBAL)


def index_for(room, rows=None):
    """その部屋の索引本文(見出しと空行は残し、他室専用の行だけ落とす)。"""
    rows = rows if rows is not None else read_index()
    keep = []
    for kind, ln, target in rows:
        if kind != "entry":
            keep.append(ln)
            continue
        sc = rooms_for(target)
        if sc == GLOBAL or room in sc:
            keep.append(ln)
    # 索引行が1本も残らなかった見出しの下の空行が連続するので畳む
    out = []
    for ln in keep:
        if not ln.strip() and out and not out[-1].strip():
            continue
        out.append(ln)
    return "\n".join(out)


def audit(rows=None):
    """C-045の見張り= 部屋別化で**記憶が読めなくなっていない**ことを機械で確かめる。

    見るのは3つだけ:
      1. 索引にあるのに実体が無い(=読みに行くと空振りする行)
      2. 実体があるのに索引に無い(=孤児。誰の目にも入らない記憶)
      3. どの部屋の索引にも載らない記憶(=部屋別化で消えた記憶)
    ★これは「recall で読めること」までは見ていない。実体が在り、どこかの索引に載っている、
      までしか担保しない。丸ごと落ちたら気づく、が正確な意味(c045_memory_guard と同じ立て付け)。
    """
    rows = rows if rows is not None else read_index()
    entries = [r for r in rows if r[0] == "entry"]
    linked = {r[2] for r in entries}
    files = {f for f in os.listdir(MEMORY_DIR)
             if f.endswith(".md") and f != "MEMORY.md" and not f.startswith("INDEX_")}
    rooms = sorted({r for t in SCOPE.values() if t != GLOBAL for r in t})
    seen = set()
    for room in rooms:
        for k, ln, t in rows:
            if k == "entry" and (rooms_for(t) == GLOBAL or room in rooms_for(t)):
                seen.add(t)
    bad = []
    for t in sorted(linked - files):
        bad.append("索引にあるが実体が無い: " + t)
    for f in sorted(files - linked):
        bad.append("実体があるが索引に無い(孤児): " + f)
    for t in sorted(linked - seen):
        bad.append("どの部屋の索引にも載らない(C-045違反): " + t)
    for b in bad:
        print("NG " + b)
    print(f"OK 索引{len(entries)}本 / 実体{len(files)}本 / どこかの部屋で読める{len(seen)}本"
          if not bad else f"{len(bad)}件のNG")
    return 1 if bad else 0


def main():
    args = sys.argv[1:]
    rows = read_index()
    entries = [r for r in rows if r[0] == "entry"]
    unmapped = [r[2] for r in entries if r[2] not in SCOPE]

    if "--audit" in args:
        return audit(rows)

    if "--print" in args:
        room = args[args.index("--room") + 1] if "--room" in args else "hr-room"
        print(index_for(room, rows))
        return 0

    whole = io.open(MEMORY_MD, encoding="utf-8").read()
    n0 = len(whole)
    print(f"MEMORY.md 全体: {len(entries)}本 / {n0}字 / 約{round(n0 * TOK_PER_CHAR):,}トークン")
    if unmapped:
        print(f"★SCOPE未割り当て(GLOBAL扱い)= {len(unmapped)}本: " + ", ".join(unmapped[:8]))
    n_global = sum(1 for r in entries if rooms_for(r[2]) == GLOBAL)
    print(f"うち全部屋共通(GLOBAL)= {n_global}本 / 部屋固有= {len(entries) - n_global}本\n")

    rooms = sorted({r for t in SCOPE.values() if t != GLOBAL for r in t})
    print(f"{'部屋':<20}{'本数':>6}{'字数':>8}{'トークン':>10}{'削減':>8}")
    for room in rooms:
        s = index_for(room, rows)
        n = len([1 for k, ln, t in rows
                 if k == "entry" and (rooms_for(t) == GLOBAL or room in rooms_for(t))])
        tok = round(len(s) * TOK_PER_CHAR)
        cut = 1 - (len(s) / float(n0))
        print(f"{room:<20}{n:>6}{len(s):>8}{tok:>10,}{cut:>7.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
