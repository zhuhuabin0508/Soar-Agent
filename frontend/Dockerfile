# ===== SOAR 前端 Nginx 镜像（已不再用于日常运行）=====
# 平台只保留热重载：docker-compose.yml 里的 soar-frontend-dev（node:20-alpine + Vite）。
# 本文件仅在需要单独打静态包镜像时使用，日常请勿 docker compose build frontend。

# ----- Stage 1: Builder -----
FROM node:20-alpine AS builder

WORKDIR /app

# 先复制依赖清单与 npm 配置，利用 Docker 缓存层
# .npmrc 已配置 legacy-peer-deps=true，避免 peer 依赖冲突
COPY package.json package-lock.json .npmrc ./

# 安装依赖：优先 npm ci（确定性安装），失败则回退 npm install
# 使用国内 npm 镜像源加速下载（离线构建环境无法直连 registry.npmjs.org）
RUN npm config set registry https://registry.npmmirror.com \
    && npm install --legacy-peer-deps

# 构建时间戳（用于破坏缓存，确保每次构建都使用最新代码）
ARG BUILD_DATE=unknown
ENV BUILD_DATE=${BUILD_DATE}

# 复制其余源码
COPY . .

# 构建生产产物（输出至 dist/）
RUN npm run build

# ----- Stage 2: Nginx 运行时 -----
FROM nginx:alpine

# 复制构建产物到 nginx 静态目录
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制自定义 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
