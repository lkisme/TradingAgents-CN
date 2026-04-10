#!/bin/bash
# TradingAgents-CN 本地构建部署脚本
# 用于从源码构建 Docker 镜像并替换 backend 容器

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="tradingagents-backend:local"
CONTAINER_NAME="tradingagents-backend"

cd "$SCRIPT_DIR"

echo "=========================================="
echo "TradingAgents-CN 本地构建部署"
echo "=========================================="
echo ""

# 检查现有容器状态
CURRENT_IMAGE=$(docker inspect "$CONTAINER_NAME" --format '{{.Config.Image}}' 2>/dev/null || echo "not_running")
echo "当前容器镜像: $CURRENT_IMAGE"

# 自动检测正确的网络
MONGODB_NETWORK=$(docker inspect tradingagents-mongodb --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null || echo "tradingagents-network")
echo "检测到 MongoDB 网络: $MONGODB_NETWORK"
echo ""

case "${1:-deploy}" in
  build)
    echo "📦 步骤1: 构建 Docker 镜像..."
    docker build -f Dockerfile.backend -t "$IMAGE_NAME" .
    echo "✅ 镜像构建完成: $IMAGE_NAME"
    ;;
    
  deploy)
    echo "📦 步骤1: 构建 Docker 镜像..."
    docker build -f Dockerfile.backend -t "$IMAGE_NAME" .
    echo "✅ 镜像构建完成: $IMAGE_NAME"
    echo ""
    
    echo "🛑 步骤2: 停止旧容器..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    echo "✅ 旧容器已移除"
    echo ""
    
    echo "🚀 步骤3: 启动新容器..."
    docker run -d \
      --name "$CONTAINER_NAME" \
      --network "$MONGODB_NETWORK" \
      --restart unless-stopped \
      -p 8000:8000 \
      -e TZ=Asia/Shanghai \
      -e MONGODB_URL="mongodb://admin:tradingagents123@tradingagents-mongodb:27017/tradingagents?authSource=admin" \
      -e REDIS_URL="redis://:tradingagents123@tradingagents-redis:6379/0" \
      -e DOCKER_CONTAINER=true \
      -e CORS_ORIGINS="*" \
      -e JWT_SECRET="docker-jwt-secret-key-change-in-production-2024" \
      -e JWT_ALGORITHM="HS256" \
      -e ACCESS_TOKEN_EXPIRE_MINUTES="480" \
      -e TRADINGAGENTS_LOG_LEVEL="INFO" \
      -v ~/workspace/TradingAgents-CN/logs:/app/logs \
      -v ~/workspace/TradingAgents-CN/data:/app/data \
      "$IMAGE_NAME"
    echo "✅ 新容器已启动"
    echo ""
    
    echo "⏳ 步骤4: 等待健康检查..."
    sleep 10
    docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
    echo ""
    
    echo "📋 查看日志..."
    docker logs "$CONTAINER_NAME" --tail 20
    ;;
    
  update)
    # 快速更新：仅重新构建并替换
    echo "🔄 快速更新部署..."
    docker build -f Dockerfile.backend -t "$IMAGE_NAME" .
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    docker run -d \
      --name "$CONTAINER_NAME" \
      --network "$MONGODB_NETWORK" \
      --restart unless-stopped \
      -p 8000:8000 \
      -e TZ=Asia/Shanghai \
      -e MONGODB_URL="mongodb://admin:tradingagents123@tradingagents-mongodb:27017/tradingagents?authSource=admin" \
      -e REDIS_URL="redis://:tradingagents123@tradingagents-redis:6379/0" \
      -e DOCKER_CONTAINER=true \
      -e CORS_ORIGINS="*" \
      -e JWT_SECRET="docker-jwt-secret-key-change-in-production-2024" \
      -v ~/workspace/TradingAgents-CN/logs:/app/logs \
      -v ~/workspace/TradingAgents-CN/data:/app/data \
      "$IMAGE_NAME"
    echo "✅ 更新完成"
    ;;
    
  logs)
    echo "📋 查看 backend 日志..."
    docker logs "$CONTAINER_NAME" --tail 100 -f
    ;;
    
  status)
    echo "📊 容器状态..."
    docker ps --filter "name=tradingagents" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
    echo ""
    echo "🔍 镜像列表..."
    docker images | grep tradingagents
    ;;
    
  rollback)
    echo "🔙 回滚到 Docker Hub 镜像..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    docker run -d \
      --name "$CONTAINER_NAME" \
      --network "$MONGODB_NETWORK" \
      --restart unless-stopped \
      -p 8000:8000 \
      -e TZ=Asia/Shanghai \
      -e MONGODB_URL="mongodb://admin:tradingagents123@tradingagents-mongodb:27017/tradingagents?authSource=admin" \
      -e REDIS_URL="redis://:tradingagents123@tradingagents-redis:6379/0" \
      -e DOCKER_CONTAINER=true \
      -v ~/workspace/TradingAgents-CN/logs:/app/logs \
      -v ~/workspace/TradingAgents-CN/data:/app/data \
      hsliup/tradingagents-backend:latest
    echo "✅ 已回滚到 hsliup/tradingagents-backend:latest"
    ;;
    
  clean)
    echo "🧹 清理本地镜像..."
    docker rmi "$IMAGE_NAME" 2>/dev/null || true
    echo "✅ 清理完成"
    ;;
    
  *)
    echo "用法: $0 {build|deploy|update|logs|status|rollback|clean}"
    echo ""
    echo "命令说明:"
    echo "  build   - 仅构建镜像"
    echo "  deploy  - 构建并部署（完整流程）"
    echo "  update  - 快速更新（修改代码后重新部署）"
    echo "  logs    - 查看 backend 日志"
    echo "  status  - 查看容器和镜像状态"
    echo "  rollback - 回滚到 Docker Hub 镜像"
    echo "  clean   - 清理本地构建的镜像"
    exit 1
    ;;
esac