#!/usr/bin/env bash
# =============================================================================
# SOAR 平台 — 联网构建后端运行镜像并导出离线 tar
#
# 用途：
#   热重载环境仍需要 soar-backend:latest（Python 依赖已装好，源码另外挂载）。
#   前端不再打 Nginx 镜像，使用 node:20-alpine + 源码挂载。
#
# 用法：
#   bash scripts/build-and-export-images.sh
#
# 输出（offline-images/）：
#   - soar-backend-latest.tar
#   - python-3.11-slim.tar
#   - node-20-alpine.tar
#   - postgres-15.tar
#   - redis-7.4-alpine.tar
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

OUT_DIR="$PROJECT_ROOT/offline-images"
mkdir -p "$OUT_DIR"

info "项目目录：$PROJECT_ROOT"
info "输出目录：$OUT_DIR"
info "宿主架构：$(uname -m)"

info "==> [1/3] 拉取基础镜像..."
docker pull python:3.11-slim
docker pull node:20-alpine
docker pull postgres:15
docker pull redis:7.4-alpine

info "==> [2/3] 构建后端镜像 soar-backend:latest ..."
docker build -t soar-backend:latest "$PROJECT_ROOT/backend"

info "==> [3/3] 导出镜像 tar ..."
docker save -o "$OUT_DIR/soar-backend-latest.tar" soar-backend:latest
docker save -o "$OUT_DIR/python-3.11-slim.tar"    python:3.11-slim
docker save -o "$OUT_DIR/node-20-alpine.tar"      node:20-alpine
docker save -o "$OUT_DIR/postgres-15.tar"         postgres:15
docker save -o "$OUT_DIR/redis-7.4-alpine.tar"   redis:7.4-alpine

info "完成，镜像 tar 已导出到 $OUT_DIR/"
ls -lh "$OUT_DIR"
