#!/usr/bin/env bash
# openclaw-magpie — 卸载
#
#   bash scripts/uninstall-sync.sh             只拆自动化（launchd + cron + 同步脚本 + 技能），
#                                              OpenClaw 里的 magpie 接线原样保留
#   bash scripts/uninstall-sync.sh --with-wiring  连接线一起还原（恢复 install 前的 openclaw.json）
#   bash scripts/uninstall-sync.sh --purge     再加上删日志和备份
set -euo pipefail

# the repository root — this script lives in <repo>/scripts/
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_DIR="${HERMES_DIR:-$HOME/.hermes}"
SKILL_DIR="$HERMES_DIR/skills/openclaw-magpie"
SCRIPT_DEST="$HERMES_DIR/scripts/magpie_openclaw_sync.py"
LOG_DIR="$HERMES_DIR/logs"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LABEL="com.walter.magpie-openclaw-sync"
PLIST="$LAUNCHD_DIR/$LABEL.plist"
CONFIG="${OPENCLAW_CONFIG_PATH:-$HOME/.openclaw/openclaw.json}"

WITH_WIRING=0
PURGE=0
usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --with-wiring) WITH_WIRING=1 ;;
    --purge)       PURGE=1 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "✗ 未知参数: $arg（--help 看用法）" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# 先还原接线：技能目录马上要被删掉，这一步必须排在最前
if [[ "$WITH_WIRING" -eq 1 ]]; then
  step "1/5 还原 OpenClaw 的 magpie 接线"
  if [[ -f "$SKILL_DIR/scripts/openclaw_magpie.py" ]]; then
    python3 "$SKILL_DIR/scripts/openclaw_magpie.py" uninstall || {
      echo "   ! 还原失败，$CONFIG 未被改动" >&2
      exit 1
    }
    echo "   ⚠ 改了配置，记得重启网关：openclaw gateway stop --force && openclaw gateway start"
  else
    echo "   ! 找不到技能脚本，改用同名备份手动还原："
    echo "       cp $CONFIG.bak-openclaw-magpie $CONFIG"
  fi
else
  echo "==> 保留 OpenClaw 里的 magpie 接线（要一起还原请加 --with-wiring）"
fi

step "2/5 launchd"
if launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null; then
  echo "   ✓ job 已卸载"
else
  echo "   没有在跑的 job"
fi
[[ -f "$PLIST" ]] && { rm -f "$PLIST"; echo "   ✓ 已删除 $PLIST"; } || true

step "3/5 cron"
if command -v hermes >/dev/null 2>&1; then
  # `hermes cron` always talks to the real profile store, whatever HOME says.
  # Uninstalling from a sandbox HOME must not delete the live cron job, so only
  # touch cron when this run targets the real Hermes directory. The real home
  # comes from the password database — $HOME may be overridden by the caller.
  REAL_HOME="$(python3 -c 'import os,pwd;print(pwd.getpwuid(os.getuid()).pw_dir)' 2>/dev/null || echo "$HOME")"
  if [[ "$HERMES_DIR" == "$REAL_HOME/.hermes" ]]; then
    JOB_ID="$(hermes cron list 2>/dev/null | awk '/^[[:space:]]+[0-9a-f]+ /{id=$1} /magpie_openclaw_sync\.py/{print id; exit}')" || true
    if [[ -n "${JOB_ID:-}" ]]; then
      hermes cron remove "$JOB_ID" >/dev/null 2>&1 && echo "   ✓ 已删除任务 $JOB_ID" \
        || echo "   ! 删除失败，手动执行：hermes cron remove $JOB_ID"
    else
      echo "   没找到对应任务"
    fi
  else
    echo "   跳过 — HERMES_DIR 不是真实的 ~/.hermes，hermes cron 只认真实配置"
  fi
else
  echo "   没有 hermes CLI；如果建过任务请手动删除"
fi

step "4/5 同步脚本与技能"
[[ -f "$SCRIPT_DEST" ]] && { rm -f "$SCRIPT_DEST"; echo "   ✓ $SCRIPT_DEST"; } || echo "   脚本已不存在"
[[ -d "$SKILL_DIR" ]] && { rm -rf "$SKILL_DIR"; echo "   ✓ $SKILL_DIR"; } || echo "   技能已不存在"

step "5/5 日志与备份"
if [[ "$PURGE" -eq 1 ]]; then
  rm -f "$LOG_DIR"/magpie-openclaw-sync*.log "$CONFIG".bak-magpie-sync 2>/dev/null && echo "   ✓ 已清空日志和同步备份" || true
else
  echo "   保留：$LOG_DIR/magpie-openclaw-sync*.log 以及 $CONFIG.bak-magpie-sync"
  echo "   要一起删掉：./uninstall.sh --purge"
fi

printf '\n\033[1m完成。\033[0m OpenClaw 网关不用重启（除非你用了 --with-wiring）。\n'
