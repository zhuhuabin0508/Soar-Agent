#!/usr/bin/env bash
# =============================================================================
# SOAR 平台 — Kylin V10 源码部署脚本（仅应用层）
#
# 前置条件（脚本会检查，缺失则退出）：
#   - 已安装并启动：PostgreSQL、Redis、Nginx
#   - 已安装：Python 3.9~3.12（推荐 3.11）、Node.js 20+（含 npm）
#   - 数据库账号已创建（脚本不建库，仅按下方 DB_* 变量生成连接串）
#
# 本脚本完成：
#   1. 创建专用运行用户
#   2. 后端：创建 venv、安装 Python 依赖、生成 backend/.env
#   3. 前端：安装依赖并构建生产产物（dist）
#   4. Nginx：生成站点配置并 reload
#   5. systemd：注册并启动 soar-backend / soar-worker / soar-beat 三个服务
#
# 用法：
#   sudo bash deploy-kylin.sh
# 可覆盖变量示例：
#   APP_DIR=/data/soar REDIS_PASSWORD=xxx DB_PASSWORD=xxx sudo -E bash deploy-kylin.sh
#
# 注意：DB_PASSWORD / SEED_ADMIN_PASSWORD / REDIS_PASSWORD 请避免使用
#       $ ` \ 等 shell 特殊字符，以免 .env 生成时被错误解析。
# =============================================================================
set -euo pipefail

# =============================================================================
# 可配置变量（按需修改）
# =============================================================================
APP_DIR="${APP_DIR:-/opt/soar-src}"          # 源码根目录
APP_USER="${APP_USER:-soar}"                 # 运行后端/worker/beat 的系统用户
BACKEND_PORT="${BACKEND_PORT:-8000}"         # 后端监听端口（Nginx 反代目标）
FORCE="${FORCE:-0}"                          # 1=强制重装依赖（默认跳过已存在的 venv/node_modules）

# ---- 数据库（需与已就绪的 PostgreSQL 一致）----
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-postgres}"       # TODO: 生产务必修改
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-soar}"

# ---- Redis（需与已就绪的 Redis requirepass 一致，修复未授权访问漏洞）----
REDIS_PASSWORD="${REDIS_PASSWORD:-12345678}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"

# ---- 鉴权 ----
JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32 2>/dev/null || date +%s | sha256sum | awk '{print $1}')}"
SEED_ADMIN_USERNAME="${SEED_ADMIN_USERNAME:-admin}"
SEED_ADMIN_PASSWORD="${SEED_ADMIN_PASSWORD:-admin123}"   # TODO: 首次登录后立即修改

# ---- 其他 ----
CORS_ORIGINS="${CORS_ORIGINS:-http://localhost,http://127.0.0.1}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

# =============================================================================
# 颜色输出
# =============================================================================
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# =============================================================================
# 1. 前置检查
# =============================================================================
[ "$(id -u)" -eq 0 ] || error "请以 root 运行：sudo bash deploy-kylin.sh"
[ -f "$APP_DIR/backend/requirements.txt" ] || error "未找到 $APP_DIR/backend/requirements.txt，请确认源码已就绪"

# 检测 Python（3.9~3.12，优先 3.11）
detect_python() {
  local cand
  for cand in python3.11 python3.10 python3.12 python3.9 python3; do
    if command -v "$cand" >/dev/null 2>&1 \
       && "$cand" -c 'import sys; v=sys.version_info[:2]; sys.exit(0 if (3,9)<=v<=(3,12) else 1)' 2>/dev/null; then
      echo "$cand"; return 0
    fi
  done
  return 1
}
PYTHON_BIN="$(detect_python)" || error "未找到 Python 3.9~3.12，请先安装（推荐 3.11）"
info "使用 Python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"

command -v node >/dev/null 2>&1 || error "未找到 node，请先安装 Node.js 20+"
command -v npm  >/dev/null 2>&1 || error "未找到 npm"
command -v nginx >/dev/null 2>&1 || error "未找到 nginx"
info "Node: $(node --version) / npm: $(npm --version)"
node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
[ "$node_major" -ge 20 ] 2>/dev/null || warn "Node 版本低于 20，Vite 构建可能失败，建议升级到 20+"

command -v psql >/dev/null 2>&1 || warn "未找到 psql（不影响部署，但数据备份功能需要）"
command -v redis-cli >/dev/null 2>&1 || warn "未找到 redis-cli（不影响部署，无法校验 Redis 连通性）"

# =============================================================================
# 2. 创建运行用户
# =============================================================================
if id "$APP_USER" >/dev/null 2>&1; then
  info "用户 $APP_USER 已存在，跳过创建"
else
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
  info "已创建系统用户 $APP_USER"
fi

# =============================================================================
# 3. 后端：venv + 依赖
# =============================================================================
if [ -d "$APP_DIR/backend/.venv" ] && [ "$FORCE" != "1" ]; then
  info "虚拟环境已存在，跳过依赖安装（FORCE=1 可强制重装）"
else
  info "创建后端虚拟环境..."
  "$PYTHON_BIN" -m venv "$APP_DIR/backend/.venv"
  info "安装 Python 依赖（可能较慢，请耐心等待）..."
  "$APP_DIR/backend/.venv/bin/pip" install --upgrade pip \
    -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -q
  "$APP_DIR/backend/.venv/bin/pip" install --prefer-binary \
    -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    -r "$APP_DIR/backend/requirements.txt"
fi

# 上传目录（源码相对 backend 自动创建）与硬编码备份目录 /app/backups
mkdir -p "$APP_DIR/backend/uploads"
mkdir -p /app/backups

# =============================================================================
# 4. 生成 backend/.env
# =============================================================================
ENV_FILE="$APP_DIR/backend/.env"
if [ -f "$ENV_FILE" ]; then
  warn "$ENV_FILE 已存在，保留原文件（如需重新生成请先删除该文件）"
else
  info "生成 backend/.env ..."
  cat > "$ENV_FILE" <<EOF
DATABASE_URL=postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT}
DB_NAME=${DB_NAME}
REDIS_URL=redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/0
CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/0
CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/1
JWT_SECRET=${JWT_SECRET}
SEED_ADMIN_USERNAME=${SEED_ADMIN_USERNAME}
SEED_ADMIN_PASSWORD=${SEED_ADMIN_PASSWORD}
CORS_ORIGINS=${CORS_ORIGINS}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
EOF
fi

# =============================================================================
# 5. 前端：构建
# =============================================================================
cd "$APP_DIR/frontend"
if [ -d "node_modules" ] && [ "$FORCE" != "1" ]; then
  info "node_modules 已存在，跳过依赖安装（FORCE=1 可强制重装）"
else
  info "安装前端依赖..."
  npm config set registry https://registry.npmmirror.com
  npm ci --legacy-peer-deps || npm install --legacy-peer-deps
fi
info "构建前端生产产物..."
npm run build
[ -d "$APP_DIR/frontend/dist" ] || error "前端构建失败，未生成 dist 目录"

# =============================================================================
# 6. Nginx 配置
# =============================================================================
info "生成 Nginx 配置..."
cat > /etc/nginx/conf.d/soar.conf <<EOF
server {
    listen 80;
    server_name _;
    client_max_body_size 50M;

    root ${APP_DIR}/frontend/dist;
    index index.html;

    location = /assets { try_files /index.html =404; }
    location = /assets/ { try_files /index.html =404; }
    location / { try_files \$uri \$uri/ /index.html; }

    location /api/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_cache off;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        chunked_transfer_encoding on;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 3600s;
    }

    location ~* \.(js|css|png|jpg|svg)\$ {
        expires 1d;
        add_header Cache-Control "public, no-transform";
    }
}
EOF

# SELinux（若启用）：允许 nginx 反代与读取 dist
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null)" = "Enforcing" ]; then
  warn "检测到 SELinux Enforcing，尝试放行 nginx 网络访问与静态目录..."
  setsebool -P httpd_can_network_connect 1 2>/dev/null || true
  chcon -R -t httpd_sys_content_t "$APP_DIR/frontend/dist" 2>/dev/null || true
fi

nginx -t || error "Nginx 配置校验失败"
nginx -s reload 2>/dev/null || systemctl reload nginx || true
info "Nginx 已 reload"

# =============================================================================
# 7. systemd 服务
# =============================================================================
UVICORN="$APP_DIR/backend/.venv/bin/uvicorn"
CELERY="$APP_DIR/backend/.venv/bin/celery"

cat > /etc/systemd/system/soar-backend.service <<EOF
[Unit]
Description=SOAR Backend (FastAPI/Uvicorn)
After=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
ExecStart=${UVICORN} app.main:app --host 0.0.0.0 --port ${BACKEND_PORT}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=soar-backend

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/soar-worker.service <<EOF
[Unit]
Description=SOAR Celery Worker
After=network-online.target soar-backend.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
ExecStart=${CELERY} -A app.core.celery_app worker -l info
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=soar-worker

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/soar-beat.service <<EOF
[Unit]
Description=SOAR Celery Beat
After=network-online.target soar-backend.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
ExecStart=${CELERY} -A app.core.celery_app beat -l info
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=soar-beat

[Install]
WantedBy=multi-user.target
EOF

# 权限：项目目录与 /app/backups 归属运行用户
chown -R "${APP_USER}:${APP_USER}" "$APP_DIR"
chown -R "${APP_USER}:${APP_USER}" /app/backups

systemctl daemon-reload
systemctl enable --now soar-backend.service soar-worker.service soar-beat.service

# =============================================================================
# 8. 完成
# =============================================================================
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
info "部署完成！"
echo ""
echo "  前端访问：   http://${HOST_IP}"
echo "  后端 API：   http://${HOST_IP}/api/v1/docs"
echo "  默认管理员： ${SEED_ADMIN_USERNAME} / ${SEED_ADMIN_PASSWORD}（请立即登录修改）"
echo ""
echo "  服务管理："
echo "    systemctl status soar-backend soar-worker soar-beat"
echo "    journalctl -u soar-backend -f"
echo "    journalctl -u soar-worker -f"
echo ""
echo "  安全提示："
echo "    - 请修改 DB_PASSWORD / SEED_ADMIN_PASSWORD / REDIS_PASSWORD 为强密码"
echo "    - Redis 需在 /etc/redis.conf 设置 requirepass ${REDIS_PASSWORD}（修复未授权访问）"
echo "    - 安全工具集 defectdojo-redis 已在 docker-compose.security-tools.yml 设置 requirepass ${REDIS_PASSWORD}"
echo "    - 安全工具集（nuclei/subfinder 等）未安装，如需使用请部署到 /opt/security-tools"
echo "    - 备份目录为硬编码 /app/backups，已在本次部署中创建并授权"
