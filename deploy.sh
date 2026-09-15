#!/bin/bash
# ============================================================
# 一键部署脚本 v2（引擎版：Milvus 混合检索 + 远程 GPU 编码）
# 用法：在项目根目录（kb-platform/）执行：
#   sed -i 's/\r$//' deploy.sh   # 修复 Windows 换行符（如需要）
#   bash deploy.sh               # 轻量云服务器（80 端口）
#   bash deploy.sh 6006          # AutoDL（6006 自定义服务端口）
#
# 前置条件（脚本会检查）：
#   1. backend/.env.production 已填写：SECRET_KEY / LLM_API_KEY
#   2. AutoDL GPU 服务已部署（gpu-services/），且
#      EMBEDDING_API_URL / RERANKER_API_URL / EMBEDDING_API_KEY 已填实际地址
# ============================================================
set -e
cd "$(dirname "$0")"
PORT="${1:-80}"
export PORT
echo "对外端口: ${PORT}"

echo "=== [1/6] 检查 Docker ==="
if ! command -v docker &>/dev/null; then
    echo "安装 Docker（apt 镜像源，避开被墙的官方脚本）..."
    apt-get update -qq
    apt-get install -y -qq docker.io docker-compose-v2
fi
# 国内镜像加速（Docker Hub 拉取）
if [ ! -f /etc/docker/daemon.json ]; then
    echo '{"registry-mirrors":["https://mirror.ccs.tencentyun.com","https://docker.m.daocloud.io"]}' > /etc/docker/daemon.json
    systemctl restart docker 2>/dev/null || true
fi
# AutoDL 容器内无 systemd，需手动拉起 dockerd
if ! docker info &>/dev/null 2>&1; then
    echo "启动 Docker daemon（AutoDL 环境无 systemd）..."
    nohup dockerd > /tmp/dockerd.log 2>&1 &
    for i in $(seq 1 30); do
        docker info &>/dev/null 2>&1 && break
        sleep 2
    done
    docker info &>/dev/null || { echo "Docker 启动失败，请查看 /tmp/dockerd.log"; exit 1; }
fi
docker compose version &>/dev/null || { echo "缺少 compose 插件"; exit 1; }
echo "Docker 就绪"

echo "=== [2/6] 准备数据目录 ==="
mkdir -p data/uploads data/etcd data/minio data/milvus

echo "=== [3/6] 检查配置 ==="
if [ ! -f backend/.env.production ]; then
    echo "缺少 backend/.env.production"; exit 1
fi
if grep -q "CHANGE_ME" backend/.env.production; then
    echo "⚠️  请先编辑 backend/.env.production："
    echo "   1. EMBEDDING_API_URL / RERANKER_API_URL 填 AutoDL GPU 服务实际地址"
    echo "   2. EMBEDDING_API_KEY / RERANKER_API_KEY 填 GPU 服务 Bearer Token"
    echo "   3. LLM_API_KEY 填入你的 DeepSeek 密钥"
    echo "改完后重新执行本脚本"
    exit 1
fi

echo "=== [4/6] 构建并启动容器（v2 镜像无 torch/本地模型，首次约 2~5 分钟）==="
docker compose up -d --build

echo "=== [5/6] 等待引擎就绪（Milvus 初始化约 30~60s）==="
for i in $(seq 1 40); do
    ready=$(docker compose exec -T backend python -c \
        "import urllib.request as u; import json; print(json.load(u.urlopen('http://localhost:8000/api/health'))['model_ready'])" \
        2>/dev/null || echo "False")
    [ "$ready" = "True" ] && { echo "引擎就绪（Milvus + GPU 编码服务连通）"; break; }
    sleep 3
done
if [ "$ready" != "True" ]; then
    echo "⚠️  引擎未就绪，请排查："
    echo "   docker compose logs backend | grep Warmup   # 看编码服务/Milvus 哪个失败"
    echo "   curl http://<AutoDL地址>/health             # GPU 服务是否在线"
fi

echo "=== [6/6] 初始化数据库 + 种子数据 ==="
docker compose exec -T backend python scripts/seed.py

echo ""
echo "============================================"
echo " 部署完成！对外端口: ${PORT}"
if [ "$PORT" = "6006" ]; then
    echo " AutoDL 访问：控制台 → 更多 → 自定义服务 → 开启 6006"
    echo "   https://<实例ID>-6006.autodl.pro"
else
    echo " 访问地址: http://<服务器公网IP>"
    echo " 记得在云控制台防火墙放行 ${PORT} 与 9000（知识图片）端口"
fi
echo ""
echo " 测试账号：admin / admin123"
echo "============================================"
docker compose ps
