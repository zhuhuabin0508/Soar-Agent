#!/usr/bin/env bash
# =============================================================================
# SOAR 平台 — 联网构建镜像并导出离线 tar
#
# 用途：
#   在联网机器上构建 backend/frontend 镜像，并把所有需要的镜像
#   （业务镜像 + 基础镜像）导出为 tar，供离线环境 `docker load` 使用，
#   避免离线环境重新联网拉取依赖或镜像。
#
# 用法：
#   bash scripts/build-and-export-images.sh
#
# 输出：
#   offline-images/ 目录下的镜像 tar 文件
#   - soar-backend-latest.tar     后端镜像
#   - soar-frontend-latest.tar    前端镜像
#   - python-3.11-slim.tar        后端基础镜像
#   - node-20-alpine.tar          前端构建基础镜像
#   - nginx-alpine.tar            前端运行基础镜像
#   - postgres-15.tar             数据库镜像
#   - redis-7.4-alpine.tar        缓存镜像
#
# 离线环境加载方式：
#   docker load -i offline-images/soar-backend-latest.tar
#   （依次加载其余 tar 即可，无需联网）
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 项目根目录（脚本位于 scripts/ 下）
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

OUT_DIR="$PROJECT_ROOT/offline-images"
mkdir -p "$OUT_DIR"

info "项目目录：$PROJECT_ROOT"
info "输出目录：$OUT_DIR"
info "宿主架构：$(uname -m)"

# ===== 1. 确保基础镜像存在 =====
info "==> [1/4] 拉取基础镜像..."
docker pull python:3.11-slim
docker pull node:20-alpine
docker pull nginx:alpine
docker pull postgres:15
docker pull redis:7.4-alpine

# ===== 2. 构建后端镜像 =====
info "==> [2/4] 构建后端镜像 soar-backend:latest ..."
docker build -t soar-backend:latest "$PROJECT_ROOT/backend"

# ===== 3. 构建前端镜像 =====
info "==> [3/4] 构建前端镜像 soar-frontend:latest ..."
docker build -t soar-frontend:latest "$PROJECT_ROOT/frontend"

# ===== 4. 导出镜像为 tar =====
info "==> [4/4] 导出镜像 tar ..."
docker save -o "$OUT_DIR/soar-backend-latest.tar"  soar-backend:latest
docker save -o "$OUT_DIR/soar-frontend-latest.tar" soar-frontend:latest
docker save -o "$OUT_DIR/python-3.11-slim.tar"     python:3.11-slim
docker save -o "$OUT_DIR/node-20-alpine.tar"       node:20-alpine
docker save -o "$OUT_DIR/nginx-alpine.tar"         nginx:alpine
docker save -o "$OUT_DIR/postgres-15.tar"          postgres:15
docker save -o "$OUT_DIR/redis-7.4-alpine.tar"     redis:7.4-alpine

info "完成，镜像 tar 已导出到 $OUT_DIR/"
ls -lh "$OUT_DIR"
