#!/bin/sh
set -e

echo "==> SOAR backend entrypoint: ensuring DB tables..."

# 重试 5 次，每次间隔 3 秒，等待 PostgreSQL 就绪并建表
MAX_RETRIES=5
RETRY_INTERVAL=3
ATTEMPT=0
SUCCESS=0

while [ $ATTEMPT -lt $MAX_RETRIES ]; do
    ATTEMPT=$((ATTEMPT + 1))
    echo "==> Attempt $ATTEMPT/$MAX_RETRIES: creating DB tables..."
    if python -c "from app.database import engine, Base; from app.models import Workflow, Execution, ExecutionTrace; Base.metadata.create_all(bind=engine); print('DB tables ensured')"; then
        echo "==> DB tables created successfully."
        SUCCESS=1
        break
    else
        echo "==> Failed to create DB tables (attempt $ATTEMPT)."
        if [ $ATTEMPT -lt $MAX_RETRIES ]; then
            echo "==> Retrying in $RETRY_INTERVAL seconds..."
            sleep $RETRY_INTERVAL
        fi
    fi
done

if [ $SUCCESS -ne 1 ]; then
    echo "==> Failed to create DB tables after $MAX_RETRIES attempts. Exiting."
    exit 1
fi

# 种子数据初始化：当工具/工作流表为空时自动种入默认数据（不会覆盖用户数据）
# 确保即使 docker compose down -v 清空卷后重建，平台仍具备基础可用能力
echo "==> Ensuring seed data (default tools & sample workflow)..."
python -c "from app.core.seed import ensure_seed_data; ensure_seed_data()" || echo "==> WARNING: seed data init failed, continuing anyway"

echo "==> Starting uvicorn server on 0.0.0.0:8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
