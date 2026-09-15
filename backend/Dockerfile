FROM python:3.12-slim

WORKDIR /app

# v2 引擎版：编码走远程 GPU 服务，镜像不含 torch/本地模型，
# 纯 Python 依赖，构建从 5~10 分钟降至 1~2 分钟
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
