#!/bin/bash
set -e

# ===== SOAR 后端栈运维便捷脚本（前端不在容器内） =====
# 用法：
#   bash dev.sh up        启动
#   bash dev.sh down      停止（保留数据卷）
#   bash dev.sh logs      查看所有服务日志（实时）
#   bash dev.sh logs b    仅看 backend 日志
#   bash dev.sh logs w    仅看 worker 日志
#   bash dev.sh restart b 重启 backend
#   bash dev.sh restart w 重启 worker（改完 Celery 代码后必须执行）
#   bash dev.sh ps        查看容器状态
#   bash dev.sh shell b   进入 backend 容器 sh
#   bash dev.sh shell w   进入 worker 容器 sh
#
# 前端开发：宿主机 cd frontend && npm run dev（http://localhost:8080）

cd "$(dirname "$0")"

if [ -f .env.dev ]; then
  ENV_FILE=".env.dev"
elif [ -f .env ]; then
  ENV_FILE=".env"
else
  echo "❌ 未找到 .env.dev 或 .env"
  echo "   请先：cp .env.example .env.dev  并按环境修改"
  exit 1
fi

CMD="${1:-ps}"
SVC="${2:-}"

COMPOSE="docker compose --env-file $ENV_FILE"

ensure_network() {
  if ! docker network inspect config_default >/dev/null 2>&1; then
    echo "==> 创建网络 config_default ..."
    docker network create config_default >/dev/null
  fi
}

case "$CMD" in
  up)
    echo "==> 启动 SOAR 后端栈..."
    ensure_network
    $COMPOSE up -d
    echo ""
    echo "✅ 已启动"
    echo "   后端 API：http://$(hostname -I 2>/dev/null | awk '{print $1}'):8001/docs"
    echo "   前端开发：宿主机 cd frontend && npm run dev"
    echo "   日志：bash dev.sh logs"
    ;;
  down)
    echo "==> 停止 SOAR 环境..."
    $COMPOSE down
    echo "✅ 已停止（数据卷保留）"
    ;;
  logs)
    case "$SVC" in
      b|backend) $COMPOSE logs -f backend-dev ;;
      w|worker) $COMPOSE logs -f worker-dev ;;
      *) $COMPOSE logs -f ;;
    esac
    ;;
  restart)
    case "$SVC" in
      b|backend) docker restart soar-backend-dev ;;
      w|worker) docker restart soar-worker-dev ;;
      *) echo "用法: bash dev.sh restart [b|w]"; exit 1 ;;
    esac
    ;;
  ps)
    $COMPOSE ps
    ;;
  shell)
    case "$SVC" in
      b|backend) docker exec -it soar-backend-dev sh ;;
      w|worker) docker exec -it soar-worker-dev sh ;;
      *) echo "用法: bash dev.sh shell [b|w]"; exit 1 ;;
    esac
    ;;
  *)
    echo "用法: bash dev.sh [up|down|logs|restart|ps|shell] [b|w]"
    exit 1
    ;;
esac
