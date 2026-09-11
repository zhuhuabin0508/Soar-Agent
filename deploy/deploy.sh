#!/usr/bin/env bash
# =============================================================================
# SOAR 平台 — 生产发版脚本（Nginx + 原生 uvicorn 架构）
#
# 流程：git pull → npm ci → npm run build → 重启 uvicorn(127.0.0.1:8081,
#       纯 HTTP、--proxy-headers) → nginx -s reload
#
# 特性：
#   - 幂等：重复执行安全（每次重新构建/重启即可）
#   - 失败即中止：任一步失败立即退出并提示，不掩盖错误
#   - 与 git 工作流完全兼容：只依赖 git pull + 构建 + 重启，不破坏 docker-compose 数据卷
#
# 前置条件：
#   - Nginx 已按 deploy/nginx.conf 配置，证书位于 /etc/nginx/ssl/
#   - 后端依赖的 Postgres/Redis 可用（可继续用 docker compose 里的 postgres/redis 服务）
#   - uvicorn 由 systemd/进程管理器托管（便于后台运行与开机自启），
#     或直接 nohup 启动（见下方 START_UVICORN 说明）
#
# 用法：
#   sudo bash deploy.sh                  # 完整发版
#   SKIP_UVICORN=1 sudo bash deploy.sh   # 只构建前端 + reload nginx（uvicorn 另由守护进程管）
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 定位项目根目录（脚本所在目录的父目录，即仓库根）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ===== 统一参数（可用环境变量覆盖）=====
# uvicorn 监听地址（仅本地，由 Nginx 反代对外）
UVICORN_HOST="${UVICORN_HOST:-127.0.0.1}"
UVICORN_PORT="${UVICORN_PORT:-8081}"
# 前端目录
FRONTEND_DIR="${FRONTEND_DIR:-$ROOT/frontend}"
# Nginx 静态根（生产放置 dist 产物处，与 deploy/nginx.conf 的 root 一致）
WEB_ROOT="${WEB_ROOT:-/usr/share/nginx/html}"

info "项目根目录：$ROOT"
[ -d "$FRONTEND_DIR" ] || error "前端目录不存在：$FRONTEND_DIR"
[ -f "$FRONTEND_DIR/package.json" ] || error "未找到 package.json，请确认在仓库根目录运行"

# ===== 1. 同步源码 =====
if [ -d .git ]; then
  info "同步最新源码（git pull --ff-only）..."
  git pull --ff-only || error "git pull 失败，请先解决冲突后重跑"
else
  warn "当前目录非 git 仓库，跳过 git pull（请确保源码已是最新）"
fi

# ===== 2. 安装前端依赖（生产用 npm ci，保证可复现）=====
info "安装前端依赖（npm ci）..."
(
  cd "$FRONTEND_DIR"
  # 若 node_modules 不存在或 package-lock 变更，npm ci 会正确处理；
  # npm ci 会删除 node_modules 后全新安装，确保与 package-lock.json 严格一致
  npm ci --legacy-peer-deps || error "npm ci 失败"
)

# ===== 3. 构建前端（产出 dist/）=====
info "构建前端（npm run build）..."
(
  cd "$FRONTEND_DIR"
  npm run build || error "前端构建失败"
  [ -d dist ] || error "构建结束未生成 dist/ 目录"
)

# ===== 4. 部署 dist 到 Nginx 静态根 =====
info "将前端产物部署到 $WEB_ROOT ..."
[ -d "$WEB_ROOT" ] || error "Nginx 静态根不存在：$WEB_ROOT（请先创建或调整 WEB_ROOT）"
# 先清空旧产物（避免残留旧文件被 Nginx 暴露），再整体拷贝
rm -rf "$WEB_ROOT"/. 2>/dev/null || true
cp -a "$FRONTEND_DIR"/dist/. "$WEB_ROOT"/ || error "部署 dist 到 $WEB_ROOT 失败"
info "前端产物已更新（$WEB_ROOT）"

# ===== 5. 重启 uvicorn（127.0.0.1:8081，纯 HTTP + --proxy-headers）=====
# 注：生产不得给 uvicorn 加任何 --ssl-* 参数，TLS 统一由 Nginx 终止。
if [ "${SKIP_UVICORN:-0}" = "1" ]; then
  warn "SKIP_UVICORN=1，跳过 uvicorn 重启（请确保守护进程已应用最新代码）"
else
  info "重启 uvicorn（${UVICORN_HOST}:${UVICORN_PORT}）..."

  # 方式 A（推荐）：由 systemd 服务管理（修改后需 systemctl restart）
  if [ -n "${UVICORN_SERVICE:-}" ] && systemctl list-unit-files | grep -q "${UVICORN_SERVICE}.service" 2>/dev/null; then
    systemctl restart "$UVICORN_SERVICE" || error "systemctl restart $UVICORN_SERVICE 失败"
    info "已通过 systemd 重启 $UVICORN_SERVICE"
  else
    # 方式 B：兜底 —— 先停旧进程再以后台 nohup 启动
    # （若你的环境用 systemd/supervisor 托管 uvicorn，请设置 UVICORN_SERVICE 变量走方式 A）
    pkill -f "uvicorn app.main:app" 2>/dev/null || warn "未发现正在运行的 uvicorn，跳过停止"
    sleep 1
    cd "$ROOT/backend"
    # 需在 backend 目录提供可用的 .env / 数据库连接
    nohup env PYTHONPATH="$ROOT/backend" uvicorn app.main:app \
        --host "$UVICORN_HOST" \
        --port "$UVICORN_PORT" \
        --proxy-headers \
        >> /var/log/soar-uvicorn.log 2>&1 &
    sleep 2
    curl -fsS "http://${UVICORN_HOST}:${UVICORN_PORT}/api/v1/version" >/dev/null \
      || error "uvicorn 未能健康启动（/api/v1/version 探测失败），日志：/var/log/soar-uvicorn.log"
    info "uvicorn 已在 ${UVICORN_HOST}:${UVICORN_PORT} 后台启动"
  fi
fi

# ===== 6. 重载 Nginx（不中断连接）=====
info "重载 Nginx（nginx -s reload）..."
nginx -t || error "nginx 配置检查失败，请先修正 deploy/nginx.conf"
nginx -s reload || error "nginx reload 失败"

info "发版完成。"
info "验证："
info "  curl -k https://10.223.132.41:8080/api/v1/version"
info "  curl -k -o /dev/null -w '%{http_code}\\n' https://10.223.132.41:8080/adpassword.txt   → 应 403/404"
