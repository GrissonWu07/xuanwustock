# 使用官方Python镜像作为基础镜像
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim

# 设置时区环境变量
ENV TZ=Asia/Shanghai
ENV LOCAL_MARKET_DATA_DIR=/app/data/local_sources
ENV MARKET_DATA_CACHE_ENABLED=true
ENV STOCK_ANALYSIS_ASYNC_REFRESH_ENABLED=false

# 替换apt-get源为国内源（阿里源）
RUN echo "deb https://mirrors.aliyun.com/debian/ bookworm main" > /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian/ bookworm-updates main" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian-security bookworm-security main" >> /etc/apt/sources.list && \
    rm -rf /etc/apt/sources.list.d/* || true

# 设置工作目录
WORKDIR /app

# 安装基础依赖、中文字体和时区数据
RUN apt-get update && apt-get install -y \
    curl \
    tar \
    xz-utils \
    ca-certificates \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fontconfig \
    tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js（多源回退 + 重试，降低网络抖动导致的构建失败）
RUN NODE_VERSION=18.20.4 && \
    ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then NODE_ARCH="x64"; \
    elif [ "$ARCH" = "arm64" ]; then NODE_ARCH="arm64"; \
    else NODE_ARCH="$ARCH"; fi && \
    NODE_TARBALL="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.gz" && \
    NODE_URLS="https://registry.npmmirror.com/-/binary/node/v${NODE_VERSION}/${NODE_TARBALL} https://npmmirror.com/mirrors/node/v${NODE_VERSION}/${NODE_TARBALL} https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}" && \
    DOWNLOAD_OK=0 && \
    for url in $NODE_URLS; do \
      echo "Downloading Node.js from ${url}"; \
      if curl --fail --location --silent --show-error --retry 5 --retry-delay 2 --retry-max-time 180 --retry-all-errors --http1.1 "${url}" -o /tmp/node.tar.gz; then \
        DOWNLOAD_OK=1; \
        break; \
      fi; \
    done && \
    if [ "$DOWNLOAD_OK" -ne 1 ]; then echo "Failed to download Node.js from all mirrors"; exit 1; fi && \
    tar -xzf /tmp/node.tar.gz -C /usr/local --strip-components=1 && \
    rm /tmp/node.tar.gz && \
    ln -sf /usr/local/bin/node /usr/local/bin/nodejs

# 验证安装
RUN node --version && npm --version

# 配置npm使用淘宝镜像源
RUN npm config set registry https://registry.npmmirror.com/

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖（多源回退 + 重试，降低镜像源波动导致的构建失败）
RUN set -eux; \
    PIP_INDEX_URLS="https://pypi.tuna.tsinghua.edu.cn/simple/ https://mirrors.aliyun.com/pypi/simple/ https://pypi.org/simple"; \
    INSTALL_OK=0; \
    for index in $PIP_INDEX_URLS; do \
      host=$(echo "$index" | awk -F/ '{print $3}'); \
      echo "Installing Python deps from ${index}"; \
      if pip install --no-cache-dir --default-timeout=1000 --index-url "$index" --trusted-host "$host" -r requirements.txt; then \
        INSTALL_OK=1; \
        break; \
      fi; \
      echo "Install failed from ${index}, trying next mirror..."; \
      sleep 2; \
    done; \
    if [ "$INSTALL_OK" -ne 1 ]; then echo "Failed to install Python deps from all mirrors"; exit 1; fi

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p /app/data/local_sources && chmod -R 777 /app/data

# 暴露 Python API 默认端口
EXPOSE 8501

# 设置健康检查
HEALTHCHECK CMD curl --fail http://localhost:8501/api/health || exit 1

# 启动 Python API
CMD ["python", "app/gateway.py"]
