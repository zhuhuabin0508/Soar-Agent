#!/usr/bin/env bash
# =============================================================================
# SOAR 平台 — 生产更新脚本（Docker Compose 部署）
#
# 功能：
#   1. 更新服务器源码（git pull）
#   2. 重新构建有源码变化的镜像（backend / frontend）
#   3. 重建配置变化的容器（redis 密码、后端连接串等，compose 自动判断）
#   4. 重启 frontend 刷新 nginx 上游 DNS（backend 重建后 IP 变化，避免 502）
#   5. 更新安全工具集（DefectDojo / BloodHound，含 defectdojo-redis 密码变更）
#
# 用法：
#   sudo bash update.sh            # 常规更新（安全工具集不拉新镜像）
#   PULL=1 sudo bash update.sh     # 安全工具集同时拉取 latest 镜像（谨慎）
#
# 注意：
#   - 更新过程中 redis / backend / worker / beat 会被重建，存在短暂中断
#   - 切勿使用 docker compose down -v（会清空数据卷）
# =============================================================================
set -euo pipefail

# 定位项目根目录（脚本位于 scripts/ 下，根目录为上一级）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$APP_DIR"

SEC_COMPOSE="docker-compose.security-tools.yml"
PULL="${PULL:-0}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

command -v docker >/dev/null 2>&1 || error "未找到 docker"
docker compose version >/dev/null 2>&1 || error "docker compose 不可用"

# ===== 1. 更新源码 =====
if [ -d .git ]; then
  info "拉取最新源码..."
  git pull --ff-only || error "git pull 失败（可能存在本地改动或冲突，请先处理）"
else
  warn "当前目录不是 git 仓库，跳过源码更新（请手动同步源码后重跑本脚本）"
fi

# ===== 2. 重新构建镜像 =====
# worker / beat 复用 soar-backend:latest 镜像，无需单独构建
info "重新构建 backend / frontend 镜像..."
docker compose build backend frontend

# ===== 3. 重建主系统容器（compose 只重建配置/镜像发生变化的容器）=====
info "重建主系统容器..."
docker compose up -d

# ===== 4. 重启 frontend 刷新 nginx 上游 DNS =====
info "重启 frontend 刷新上游 DNS（避免 502）..."
docker restart soar-frontend

# ===== 5. 更新安全工具集 =====
if [ -f "$SEC_COMPOSE" ]; then
  if [ "$PULL" = "1" ]; then
    info "拉取安全工具集最新镜像..."
    docker compose -f "$SEC_COMPOSE" pull
  fi
  info "重建安全工具集容器（含 defectdojo-redis 密码变更）..."
  docker compose -f "$SEC_COMPOSE" up -d
else
  warn "未找到 $SEC_COMPOSE，跳过安全工具集"
fi

# ===== 6. 清理无引用镜像 =====
info "清理无引用镜像..."
docker image prune -f

# ===== 7. 状态 =====
info "更新完成，当前容器状态："
docker compose ps
[ -f "$SEC_COMPOSE" ] && docker compose -f "$SEC_COMPOSE" ps
