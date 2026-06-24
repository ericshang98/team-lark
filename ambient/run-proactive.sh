#!/usr/bin/env bash
# team-lark 主动模式 —— 由系统定时器（cron / launchd）调用，无头跑一轮：
# 遍历成员表，给每个人私信发当天的个人简报。排程在系统定时器，不在 skill 里。
#
# 用法：
#   run-proactive.sh            正式跑（真给成员发飞书 DM）
#   run-proactive.sh --dry-run  演练（只算只打印，绝不发任何 DM）
#
# 可选环境变量：
#   CLAUDE_BIN    claude 可执行（默认用 PATH 里的 claude；定时器环境 PATH 极简时建议填绝对路径）
#   CLAUDE_MODEL  指定模型（不填用 claude 默认）
#   CLAUDE_PROXY  出口代理。中国大陆用户：让 claude 走代理连 Anthropic 时设，形如
#                 http://user:pass@host:port —— 这样 claude 能正常用，团队协作仍在飞书（国内可落地）。
#   LOG_FILE      日志文件（默认 ~/.team-lark/proactive.log）
set -uo pipefail

DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
LOG="${LOG_FILE:-$HOME/.team-lark/proactive.log}"; mkdir -p "$(dirname "$LOG")"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
log() { echo "[$(date '+%F %T')] $*" >>"$LOG"; }

# 中国大陆：让 claude 走代理连 Anthropic（可选）
if [ -n "${CLAUDE_PROXY:-}" ]; then
  export https_proxy="$CLAUDE_PROXY" http_proxy="$CLAUDE_PROXY" all_proxy="$CLAUDE_PROXY"
  export no_proxy="localhost,127.0.0.1,::1"
fi

PROMPT="/team-lark 主动模式：无头定时触发、无交互用户。遍历成员表所有人，为每人算出他的（逾期/今日该做/待验收），复用今日简报模板生成个人简报，用 lark-cli im +messages-send 私聊 DM 给本人。只读 + 发 DM，绝不改任何任务状态。"
[ "$DRY" = 1 ] && PROMPT="$PROMPT 【演练 / dry-run】只算只打印每人简报，绝不发任何 DM 或群消息。"

log "run team-lark 主动模式 (dry=$DRY) bin=$CLAUDE_BIN"
"$CLAUDE_BIN" -p "$PROMPT" \
  --permission-mode acceptEdits --dangerously-skip-permissions \
  ${CLAUDE_MODEL:+--model "$CLAUDE_MODEL"} >>"$LOG" 2>&1
log "done rc=$?"
