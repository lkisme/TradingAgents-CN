# TradingAgents-CN 本地构建部署指南

## 背景

默认部署使用 Docker Hub 预构建镜像 (`hsliup/tradingagents-backend:latest`)。当需要修改源码并部署时，需要从本地源码构建镜像并替换容器。

## 当前架构

| 服务 | 容器名 | 镜像 | 数据持久化 |
|-----|--------|------|-----------|
| Backend | `tradingagents-backend` | Docker Hub / 本地构建 | logs/data 目录映射 |
| Frontend | `tradingagents-frontend` | Docker Hub | 无 |
| MongoDB | `tradingagents-mongodb` | mongo:4.4 | named volume ✅ |
| Redis | `tradingagents-redis` | redis:7-alpine | named volume ✅ |
| Nginx | `tradingagents-nginx` | nginx:alpine | 配置文件映射 |

**数据安全**: MongoDB 和 Redis 数据存储在 named volumes 中，替换 backend 容器不会丢失数据。

---

## 快速开始

### 1. 部署本地构建版本

```bash
cd ~/workspace/TradingAgents-CN
./deploy-local.sh deploy
```

这会执行：
1. 构建 Docker 镜像 `tradingagents-backend:local`
2. 停止并删除旧容器
3. 启动新容器
4. 等待健康检查

### 2. 修改代码后更新部署

```bash
# 修改源码后...
./deploy-local.sh update
```

快速更新流程：构建 → 停止 → 删除 → 启动

---

## 命令详解

| 命令 | 说明 |
|-----|------|
| `./deploy-local.sh build` | 仅构建镜像，不部署 |
| `./deploy-local.sh deploy` | 构建并部署（完整流程） |
| `./deploy-local.sh update` | 快速更新（修改代码后） |
| `./deploy-local.sh logs` | 查看 backend 日志 |
| `./deploy-local.sh status` | 查看容器和镜像状态 |
| `./deploy-local.sh rollback` | 回滚到 Docker Hub 镜像 |
| `./deploy-local.sh clean` | 清理本地构建的镜像 |

---

## 手动操作流程

如果需要手动控制每一步：

```bash
# 1. 进入源码目录
cd ~/workspace/TradingAgents-CN

# 2. 构建镜像
docker build -f Dockerfile.backend -t tradingagents-backend:local .

# 3. 停止旧容器
docker stop tradingagents-backend
docker rm tradingagents-backend

# 4. 使用 docker-compose 启动新容器
docker-compose -f docker-compose.local.yml up -d backend

# 5. 查看状态
docker ps --filter "name=tradingagents-backend"
docker logs tradingagents-backend --tail 50
```

---

## 回滚到 Docker Hub 镜像

如果本地构建有问题，可以快速回滚：

```bash
./deploy-local.sh rollback
```

或手动：

```bash
docker stop tradingagents-backend
docker rm tradingagents-backend
docker-compose -f docker-compose.hub.nginx.yml up -d backend
```

---

## 文件说明

| 文件 | 说明 |
|-----|------|
| `docker-compose.local.yml` | 本地构建版本 compose 配置 |
| `docker-compose.hub.nginx.yml` | Docker Hub 版本 compose 配置（默认） |
| `Dockerfile.backend` | Backend 镜像构建文件 |
| `deploy-local.sh` | 本地构建部署脚本 |
| `.env` | 环境变量配置 |

---

## 构建镜像说明

`Dockerfile.backend` 构建内容：
- 基础镜像: Python 3.10-slim-bookworm
- 安装依赖: pip install + requirements
- 复制代码: app/, tradingagents/, config/, scripts/
- 安装工具: pandoc, wkhtmltopdf (用于 PDF 生成)

构建时间: 约 5-10 分钟（取决于网络和硬件）

---

## 常见问题

### Q: 构建很慢怎么办？

A: Dockerfile 已使用清华镜像加速。如果仍有问题：
```bash
# 使用 --no-cache 重新构建（解决缓存问题）
docker build --no-cache -f Dockerfile.backend -t tradingagents-backend:local .
```

### Q: 构建失败：下载 pandoc/wkhtmltopdf 失败？

A: 这些工具从 GitHub 下载，网络不稳定时可能失败。解决方案：
1. 使用代理
2. 预先下载 .deb 文件放到源码目录，修改 Dockerfile 使用本地文件

### Q: 如何确认本地镜像正在运行？

```bash
docker inspect tradingagents-backend --format '{{.Config.Image}}'
# 应输出: tradingagents-backend:local
```

### Q: 数据会丢失吗？

A: 不会。MongoDB 和 Redis 数据在 named volumes 中，替换 backend 不影响数据。

---

## 开发工作流建议

```
修改源码 → 本地测试 → 构建镜像 → 部署 → 验证
   ↓           ↓          ↓         ↓       ↓
 编辑文件   pytest    docker build  deploy  curl API
```

推荐流程：
1. 在本地修改代码
2. 本地运行 pytest 测试（可选）
3. `./deploy-local.sh update` 快速更新
4. `docker logs -f tradingagents-backend` 观察日志
5. 验证 API 响应是否正常

---

## 后续维护

- 定期清理旧镜像：`docker image prune`
- 查看镜像大小：`docker images | grep tradingagents`
- 备份配置：`.env` 文件包含 API 密钥，建议备份