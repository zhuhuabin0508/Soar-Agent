OAR 平台发版脚本：前端构建 + 后端镜像重建 + Nginx 平滑加载
# 用法：cd /opt/soar-src && bash deploy/deploy.sh
set -euo pipefail

PROJECT_DIR="/opt/soar-src"
cd "$PROJECT_DIR"

echo "==> [1/5] 拉取最新代码"
git pull --ff-only

echo "==> [2/5] 构建前端"
cd frontend
npm ci
npm run build
cd ..

echo "==> [3/5] 重建并重启后端容器"
docker compose --env-file .env.dev up -d --build backend worker beat

echo "==> [4/5] 等待后端就绪"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8001/api/v1/version >/dev/null 2>&1; then
    echo "    后端已就绪"
    break
  fi
  [ "$i" -eq 30 ] && { echo "    后端 30 秒未就绪，请查日志：docker logs soar-backend-dev --tail 50"; exit 1; }
  sleep 1
done

echo "==> [5/5] 同步 Nginx 配置（仅当仓库配置有变化时 reload）"
if ! diff -q deploy/nginx.conf /etc/nginx/conf.d/secops.conf >/dev/null 2>&1; then
  cp deploy/nginx.conf /etc/nginx/conf.d/secops.conf
  nginx -t && systemctl reload nginx
  echo "    Nginx 配置已更新并 reload"
else
  echo "    Nginx 配置无变化，跳过"
fi

echo "==> 发版完成，冒烟验证："
echo "    curl -k https://10.223.132.41:8080/api/v1/version"
