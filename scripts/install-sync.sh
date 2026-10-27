#!/usr/bin/env bash
# openclaw-magpie — 把 magpie 网关的模型清单自动同步进 OpenClaw
#
#   bash scripts/install-sync.sh                完整安装（含 launchd + cron）
#   bash scripts/install-sync.sh --no-launchd   不装 launchd，只装脚本/技能/cron
#   bash scripts/install-sync.sh --no-restart   写配置但不重启 OpenClaw 网关
#   bash scripts/install-sync.sh --dry-run      只报告会改什么，不写任何文件
#
# 用 HOME=... OPENCLAW_CONFIG_PATH=... 可以装到别的目录（自测用）。
set -euo pipefail

# the repository root — this script lives in <repo>/scripts/
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_DIR="${HERMES_DIR:-$HOME/.hermes}"
OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw}"
SKILL_DIR="$HERMES_DIR/skills/openclaw-magpie"
SCRIPT_DEST="$HERMES_DIR/scripts/magpie_openclaw_sync.py"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LABEL="com.walter.magpie-openclaw-sync"
PLIST="$LAUNCHD_DIR/$LABEL.plist"
JOB_NAME="magpie→OpenClaw 模型同步"

SYNC_ARGS=()
WITH_LAUNCHD=1
usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --no-restart) SYNC_ARGS+=(--no-restart) ;;
    --no-launchd) WITH_LAUNCHD=0 ;;
    --dry-run)    SYNC_ARGS+=(--dry-run) ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "✗ 未知参数: $arg（--help 看用法）" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "1/5 同步脚本 → $SCRIPT_DEST"
mkdir -p "$(dirname "$SCRIPT_DEST")" "$HERMES_DIR/logs"
install -m 0755 "$SRC/scripts/magpie_openclaw_sync.py" "$SCRIPT_DEST"
echo "   ✓ 已安装"

step "2/5 技能 → $SKILL_DIR"
rm -rf "$SKILL_DIR"
mkdir -p "$SKILL_DIR/scripts" "$SKILL_DIR/references"
cp "$SRC/scripts/openclaw_magpie.py" "$SKILL_DIR/scripts/"
cp "$SRC/references/platforms.md" "$SKILL_DIR/references/" 2>/dev/null || true
echo "   ✓ 已安装（含 doctor / list / install / uninstall / verify 五个子命令）"

step "3/5 launchd（magpie 配置一变就秒同步）"
if [[ "$WITH_LAUNCHD" -eq 0 ]]; then
  echo "   跳过（--no-launchd）"
elif [[ "$(uname)" != "Darwin" ]]; then
  echo "   跳过（非 macOS）。其他平台请用 cron：*/30 * * * * python3 $SCRIPT_DEST"
else
  sed "s|__HOME__|$HOME|g" "$SRC/references/magpie-openclaw-sync.plist.template" > "$PLIST"
  if plutil -lint "$PLIST" >/dev/null; then echo "   ✓ plist 已生成并通过 lint: $PLIST"; fi
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "   已卸载旧 job" || true
  if launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null; then
    echo "   ✓ launchd job 已加载"
  else
    echo "   ! 加载失败 —— Hermes 网关禁止 launchctl，改在你自己的终端里跑一次："
    echo "       launchctl bootstrap gui/\$(id -u) $PLIST"
    echo "   （不装也能用，靠下面的 cron 每 30 分钟兜底）"
  fi
fi

step "4/5 首次同步"
python3 "$SCRIPT_DEST" ${SYNC_ARGS[@]+"${SYNC_ARGS[@]}"}

step "5/5 cron（每 30 分钟兜底，纯脚本不烧 LLM）"
if ! command -v hermes >/dev/null 2>&1; then
  echo "   ! 没找到 hermes CLI，请在 Hermes 里手动建一个任务："
  echo "     no_agent=true  script=magpie_openclaw_sync.py  schedule=every 30m"
else
  # `hermes cron` always talks to the real profile store, whatever HOME says.
  # Only touch cron when this run targets the real Hermes directory, otherwise a
  # sandbox install would hijack (or skip) the live job.
  REAL_HOME="$(python3 -c 'import os,pwd;print(pwd.getpwuid(os.getuid()).pw_dir)' 2>/dev/null || echo "$HOME")"
  if [[ "$HERMES_DIR" != "$REAL_HOME/.hermes" ]]; then
    echo "   跳过 — HERMES_DIR 不是真实的 ~/.hermes，hermes cron 只认真实配置"
  elif hermes cron list 2>/dev/null | grep -q "magpie_openclaw_sync.py"; then
    echo "   ✓ 已存在，跳过（$(hermes cron list 2>/dev/null | awk '/^[[:space:]]+[0-9a-f]+ /{id=$1} /magpie_openclaw_sync\.py/{print id; exit}')）"
  elif hermes cron create --name "$JOB_NAME" --deliver origin \
          --script magpie_openclaw_sync.py --no-agent "every 30m" >/dev/null 2>&1; then
    echo "   ✓ cron 已注册：每 30 分钟跑一次，没变化就完全静默"
  else
    echo "   ! 注册失败，请在 Hermes 里手动建：no_agent=true script=magpie_openclaw_sync.py every 30m"
  fi
fi

printf '\n\033[1m完成。\033[0m 常用命令：\n'
echo "  $SCRIPT_DEST --dry-run    看看会改什么（退出码 2 = 有变化）"
echo "  $SCRIPT_DEST              手动同步一次"
echo "  tail -f $HERMES_DIR/logs/magpie-openclaw-sync.log"
echo "  python3 $SKILL_DIR/scripts/openclaw_magpie.py doctor    检查接线"
echo "  python3 $SKILL_DIR/scripts/openclaw_magpie.py verify    跑一轮真实对话验证"
