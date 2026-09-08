#!/bin/bash
set -e

# ===== SOAR Vibe Coding 开发环境便捷脚本 =====
# 用法：
#   bash dev.sh up        启动 dev 环境
#   bash dev.sh down      停止 dev 环境（保留数据与 node_modules）
#   bash dev.sh logs      查看所有 dev 服务日志（实时）
#   bash dev.sh logs b    仅看 backend 日志
#   bash dev.sh logs f    仅看 frontend 日志
#   bash dev.sh logs w    仅看 worker 日志
#   bash dev.sh restart b 重启 backend（uvicorn --reload 已自动，必要时手动）
#   bash dev.sh restart w 重启 worker（改完 Celery 代码后必须执行）
#   bash dev.sh ps        查看 dev 容器状态
#   bash dev.sh shell b   进入 backend 容器 sh
#   bash dev.sh shell f   进入 frontend 容器 sh

cd "$(dirname "$0")"
ENV_FILE="/opt/soar-src/.env.dev"

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ 未找到 $ENV_FILE"
  echo "   dev 环境使用独立的 .env.dev，请确认该文件已创建"
  exit 1
fi

CMD="${1:-ps}"
SVC="${2:-}"

COMPOSE="docker compose --env-file $ENV_FILE -f docker-compose.dev.yml"

case "$CMD" in
  up)
    echo "==> 启动 SOAR dev 环境..."
    $COMPOSE up -d
    echo ""
    echo "✅ dev 环境已启动"
    echo "   前端：http://$(hostname -I | awk '{print $1}'):8080"
    echo "   后端 API：http://$(hostname -I | awk '{print $1}'):8001/docs"
    echo "   日志：bash dev.sh logs"
    ;;
  down)
    echo "==> 停止 SOAR dev 环境..."
    $COMPOSE down
    echo "✅ dev 环境已停止（数据与 node_modules 保留）"
    ;;
  logs)
    case "$SVC" in
      b|backend) $COMPOSE logs -f backend-dev ;;
      f|frontend) $COMPOSE logs -f frontend-dev ;;
      w|worker) $COMPOSE logs -f worker-dev ;;
      *) $COMPOSE logs -f ;;
    esac
    ;;
  restart)
    case "$SVC" in
      b|backend) docker restart soar-backend-dev ;;
      w|worker) docker restart soar-worker-dev ;;
      f|frontend) docker restart soar-frontend-dev ;;
      *) echo "用法: bash dev.sh restart [b|f|w]"; exit 1 ;;
    esac
    ;;
  ps)
    $COMPOSE ps
    ;;
  shell)
    case "$SVC" in
      b|backend) docker exec -it soar-backend-dev sh ;;
      f|frontend) docker exec -it soar-frontend-dev sh ;;
      w|worker) docker exec -it soar-worker-dev sh ;;
      *) echo "用法: bash dev.sh shell [b|f|w]"; exit 1 ;;
    esac
    ;;
  *)
    echo "用法: bash dev.sh [up|down|logs|restart|ps|shell] [b|f|w]"
    exit 1
    ;;
esac
