#!/usr/bin/env bash
# =============================================================================
# SOAR 平台 — 热重载部署更新脚本（无需重建镜像）
#
# 流程：
#   1. 同步最新源码（git pull）
#   2. 热重载自动生效（无需额外操作）：
#      - 后端 backend-dev：uvicorn --reload 监听 .py 变化自动重启
#      - 前端 frontend-dev：vite HMR 监听前端文件变化自动热更新
#   3. 检测依赖清单变化并提示（requirements.txt / package.json）
#   4. 按需重启 worker（改 Celery 代码后）
#
# 用法：
#   sudo bash update.sh                   # 常规更新（源码热重载自动生效）
#   RESTART_WORKER=1 sudo bash update.sh  # 同时重启 worker（应用 Celery 代码变更）
#
# 注意：
#   - 只改源码（.py / .tsx / .jsx / .css 等）无需任何手动操作，热重载自动生效
#   - 改了 requirements.txt / package.json（增删依赖）热重载不生效，需手动安装依赖并重启容器
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ===== 确保 inotify 限制足够（vite / uvicorn --reload 依赖文件监听）=====
ensure_inotify_limits() {
  local need_watches=524288
  local need_instances=512
  local cur_watches cur_instances changed=0

  cur_watches=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo 0)
  cur_instances=$(cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo 0)

  if [ "$cur_watches" -lt "$need_watches" ]; then
    info "max_user_watches 过低（当前 $cur_watches，需 >= $need_watches），正在设置..."
    sysctl -w fs.inotify.max_user_watches=$need_watches >/dev/null 2>&1 \
      || warn "sysctl 设置失败（请确认以 root 运行）"
    changed=1
  fi

  if [ "$cur_instances" -lt "$need_instances" ]; then
    info "max_user_instances 过低（当前 $cur_instances，需 >= $need_instances），正在设置..."
    sysctl -w fs.inotify.max_user_instances=$need_instances >/dev/null 2>&1 \
      || warn "sysctl 设置失败（请确认以 root 运行）"
    changed=1
  fi

  # 永久化写入 /etc/sysctl.conf（避免宿主机重启后失效）
  if [ "$changed" = "1" ] && [ -w /etc/sysctl.conf ]; then
    grep -q "^fs.inotify.max_user_watches" /etc/sysctl.conf 2>/dev/null \
      || echo "fs.inotify.max_user_watches=$need_watches" >> /etc/sysctl.conf
    grep -q "^fs.inotify.max_user_instances" /etc/sysctl.conf 2>/dev/null \
      || echo "fs.inotify.max_user_instances=$need_instances" >> /etc/sysctl.conf
    info "已写入 /etc/sysctl.conf（宿主机重启后仍生效）"
  elif [ "$changed" = "1" ]; then
    warn "/etc/sysctl.conf 不可写，本次仅临时生效（宿主机重启后需重新设置）"
  fi
}

# 定位项目根目录：
#   1. 优先使用 APP_DIR 环境变量（如 APP_DIR=/opt/soar-src bash update.sh）
#   2. 否则从脚本所在位置向上查找 docker-compose.yml
if [ -n "${APP_DIR:-}" ]; then
  cd "$APP_DIR"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  _dir="$SCRIPT_DIR"
  _found=""
  while [ "$_dir" != "/" ]; do
    if [ -f "$_dir/docker-compose.yml" ]; then
      _found="$_dir"
      break
    fi
    _dir="$(dirname "$_dir")"
  done
  if [ -n "$_found" ]; then
    cd "$_found"
  else
    error "未找到 docker-compose.yml，请用 APP_DIR=/项目路径 指定后重跑"
  fi
fi

[ -f "docker-compose.yml" ] || error "当前目录 $PWD 未找到 docker-compose.yml，请用 APP_DIR=/项目路径 指定"
info "项目目录：$PWD"

# ===== 0. 确保 inotify 限制足够（热重载依赖文件监听）=====
ensure_inotify_limits

# ===== 1. 同步源码 =====
if [ -d .git ]; then
  info "同步最新源码..."
  BEFORE="$(git rev-parse HEAD 2>/dev/null || true)"
  git pull --ff-only 2>&1 || warn "git pull 失败（若非 git 同步方式，请手动同步源码后重跑）"
  AFTER="$(git rev-parse HEAD 2>/dev/null || true)"
else
  warn "当前目录不是 git 仓库，请先手动同步源码（rsync/scp）后再运行"
  BEFORE=""
  AFTER=""
fi

# ===== 2. 依赖变化检测 =====
DEPS_CHANGED=0
if [ -n "$BEFORE" ] && [ -n "$AFTER" ] && [ "$BEFORE" != "$AFTER" ]; then
  info "本次更新涉及的依赖清单变更："
  CHANGED="$(git diff --name-only "$BEFORE" "$AFTER" | grep -E "requirements.txt|package.json" || true)"
  if [ -n "$CHANGED" ]; then
    DEPS_CHANGED=1
    echo "$CHANGED"
  else
    info "  无（仅源码变更，热重载自动生效）"
  fi
fi

if [ "$DEPS_CHANGED" = "1" ]; then
  warn "检测到依赖清单变化！热重载不会自动安装新依赖，请手动执行："
  warn "  后端：docker exec soar-backend-dev pip install -r requirements.txt && docker restart soar-backend-dev"
  warn "  前端：docker exec soar-frontend-dev npm install --legacy-peer-deps && docker restart soar-frontend-dev"
fi

# ===== 3. 重启 worker（Celery 无自动重载，改代码后需手动重启）=====
if [ "${RESTART_WORKER:-0}" = "1" ]; then
  info "重启 worker（应用 Celery 代码变更）..."
  docker restart soar-worker-dev
else
  info "跳过 worker 重启（如需应用 Celery 代码变更，用 RESTART_WORKER=1 bash update.sh）"
fi

# ===== 4. 状态 =====
info "更新完成，热重载已自动生效，当前容器状态："
if [ -f .env.dev ]; then
  docker compose --env-file .env.dev ps
elif [ -f .env ]; then
  docker compose --env-file .env ps
else
  docker compose ps
fi
