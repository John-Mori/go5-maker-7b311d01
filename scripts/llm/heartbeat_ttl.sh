#!/usr/bin/env bash
# INC-091 対策1+2: TTL付きハートビート+限界前Discord自動通知
# ------------------------------------------------------------------
# 使い方(セッションが実仕事の区切りごとに"再武装"=再実行する):
#   bash scripts/llm/heartbeat_ttl.sh              # 司令塔(main): 30回×20秒=10分
#   bash scripts/llm/heartbeat_ttl.sh 30 research-room   # 部門窓: claude_active_research-room.txt
#
# 対策1(TTL): while true 禁止。最大10分で脈が止まり、本体が暴走/フリーズしても
#   ローカルqwen/受信箱回収が自動で引き継げる(偽の生存信号を出さない)。
# 対策2(限界前通知): 再武装の積み上げ(直近3hで9回以上≒90分超の連続稼働)を検知したら
#   Discord総合受付(router)へ「引き継ぎ推奨」を自動発報(2時間スロットル)。
#   モデルの自覚に頼らず、OS側の事実(再武装回数)だけで機械的に判断する。
set -euo pipefail

N="${1:-30}"          # 脈の回数(既定30 = 20秒×30 = 10分でTTL満了)
NAME="${2:-main}"     # セッション名(main=司令塔 / 部門窓はdept名: research-room 等)
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LLM_DIR="$ROOT/local/llm"
mkdir -p "$LLM_DIR"
if [ "$NAME" = "main" ]; then
  ACTIVE="$LLM_DIR/claude_active.txt"
else
  ACTIVE="$LLM_DIR/claude_active_${NAME}.txt"
fi

# --- 対策2: 再武装ログ→限界前通知 ---
LOG="$LLM_DIR/heartbeat_rearm_${NAME}.log"
NOW=$(date +%s)
echo "$NOW" >> "$LOG"
CUTOFF=$((NOW - 10800))                       # 直近3時間
COUNT=$(awk -v c="$CUTOFF" '$1 >= c' "$LOG" | wc -l | tr -d ' ')
tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"   # ログ肥大防止

THRESH=9
MARK="$LLM_DIR/limit_notified_${NAME}.txt"
if [ "$COUNT" -ge "$THRESH" ]; then
  LAST=0
  [ -f "$MARK" ] && LAST=$(cat "$MARK" 2>/dev/null || echo 0)
  if [ $((NOW - LAST)) -ge 7200 ]; then
    python "$ROOT/scripts/discord/bot_send.py" --dept router \
      "⏳【限界前通知/INC-091対策】セッション[${NAME}]の連続稼働が長くなっています(直近3hで再武装${COUNT}回)。区切りの良い所で引き継ぎ(正本md/memory更新→新セッション)を推奨。※開始直後のセッションならこの通知は無視してOK" \
      >/dev/null 2>&1 || true
    echo "$NOW" > "$MARK"
  fi
fi

# --- 対策1: TTL付きの脈 ---
for i in $(seq 1 "$N"); do
  touch "$ACTIVE"
  sleep 20
done
