# ===== SOAR 前端镜像：多阶段构建 =====

# ----- Stage 1: Builder -----
FROM node:20-alpine AS builder

WORKDIR /app

# 先复制依赖清单与 npm 配置，利用 Docker 缓存层
# .npmrc 已配置 legacy-peer-deps=true，避免 peer 依赖冲突
COPY package.json package-lock.json .npmrc ./

# 安装依赖：优先 npm ci（确定性安装），失败则回退 npm install
RUN npm ci || npm install

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
