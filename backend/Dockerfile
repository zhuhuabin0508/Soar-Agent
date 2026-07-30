# ===== SOAR 后端镜像 =====
# Python 3.11 slim 基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 环境变量：避免生成 .pyc、不缓冲输出（日志即时可见）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
# libpq-dev：PostgreSQL 客户端库头文件（psycopg2-binary 为预编译，但保留以确保兼容）
# gcc：部分依赖可能需要编译（稳妥起见）
# postgresql-client：pg_dump / psql 命令行工具（数据备份与恢复）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 先单独复制 requirements.txt 安装依赖，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码与入口脚本
COPY app ./app
COPY entrypoint.sh ./entrypoint.sh

# 赋予入口脚本可执行权限
RUN chmod +x ./entrypoint.sh

# 暴露 FastAPI 服务端口
EXPOSE 8000

# 入口：等待 PG 就绪并建表，随后启动 uvicorn
ENTRYPOINT ["./entrypoint.sh"]
