#!/bin/bash
# AutoDL GPU 服务一键启动脚本（模型缺失时自动从 modelscope 下载）
#
# 单端口模式：combined_service.py 同时提供 /v1/embeddings 与 /v1/rerank。
# 原因：AutoDL 自定义服务只开放 6006 一个端口，embedding 与 reranker
# 分端口部署时 reranker 公网不可达。
#
# 用法：bash start.sh          # 启动合并服务(:6006)
#       bash start.sh stop     # 停止服务
set -e

# AutoDL 非交互 shell 无 conda PATH，显式注入
export PATH=/root/miniconda3/bin:$PATH

MODEL_DIR=/root/autodl-tmp/models
LOG_DIR=/root/autodl-tmp/logs
SERVICE_DIR=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$MODEL_DIR/BAAI" "$LOG_DIR"

# 密钥：与业务侧 .env 的 EMBEDDING_API_KEY / RERANKER_API_KEY 保持一致（留空则不鉴权）
export EMBEDDING_API_KEY=${EMBEDDING_API_KEY:-}

stop() {
  pkill -f "combined_service:app" 2>/dev/null && echo "combined service stopped" || true
}

if [ "$1" = "stop" ]; then stop; exit 0; fi

# 1. 模型下载（已存在则跳过）
if [ ! -f "$MODEL_DIR/BAAI/bge-m3/config.json" ]; then
  echo "下载 bge-m3 ..."
  modelscope download --model BAAI/bge-m3 --local_dir "$MODEL_DIR/BAAI/bge-m3"
fi
if [ ! -f "$MODEL_DIR/BAAI/bge-reranker-large/config.json" ]; then
  echo "下载 bge-reranker-large ..."
  modelscope download --model BAAI/bge-reranker-large --local_dir "$MODEL_DIR/BAAI/bge-reranker-large"
fi

# 2. 启动服务（复用系统自带 conda/python 环境，缺依赖自动装）
cd "$SERVICE_DIR"
python -c "import fastapi, uvicorn, pymilvus, FlagEmbedding" 2>/dev/null || \
  pip install -q fastapi uvicorn "pymilvus[model]" FlagEmbedding modelscope

export BGE_M3_PATH="$MODEL_DIR/BAAI/bge-m3"
export BGE_RERANKER_LARGE="$MODEL_DIR/BAAI/bge-reranker-large"
export BGE_DEVICE=cuda:0
export BGE_RERANKER_DEVICE=cuda:0
export BGE_FP16=true
export BGE_RERANKER_FP16=true

nohup python -m uvicorn combined_service:app --host 0.0.0.0 --port 6006 > "$LOG_DIR/bge_combined.log" 2>&1 &
echo "合并服务启动中 pid=$! 日志 $LOG_DIR/bge_combined.log"

# 3. 等待就绪并预热（首次加载模型 40~90s，两个模型串行加载）
AUTH_HEADER=()
[ -n "$EMBEDDING_API_KEY" ] && AUTH_HEADER=(-H "Authorization: Bearer $EMBEDDING_API_KEY")
echo "等待服务就绪（首次加载模型较慢）..."
for i in $(seq 1 90); do
  sleep 2
  H=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:6006/health || true)
  if [ "$H" = "200" ]; then
    echo "服务已就绪。预热两个模型..."
    curl -s http://127.0.0.1:6006/v1/embeddings "${AUTH_HEADER[@]}" -H "Content-Type: application/json" -d '{"texts":["预热"]}' > /dev/null
    curl -s http://127.0.0.1:6006/v1/rerank "${AUTH_HEADER[@]}" -H "Content-Type: application/json" -d '{"query":"预热","documents":["预热"]}' > /dev/null
    echo "完成。对外地址请查看 AutoDL 控制台的 6006 端口映射（https://<实例ID>-6006.autodl.pro）。"
    echo "业务侧 .env 配置："
    echo "  EMBEDDING_API_URL=https://<实例ID>-6006.autodl.pro/v1/embeddings"
    echo "  RERANKER_API_URL=https://<实例ID>-6006.autodl.pro/v1/rerank"
    exit 0
  fi
done
echo "超时：请查看日志 tail -50 $LOG_DIR/bge_combined.log"
exit 1
