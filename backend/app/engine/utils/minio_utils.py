# -*- coding: utf-8 -*-
"""MinIO 客户端 — 懒加载单例

修复原版两处问题：
1. 原版在模块 import 时即连接 MinIO，MinIO 未启动时直接崩（导入图首节点就挂）
2. set_bucket_policy 误写在 config 对象上（应为 client）

图片桶策略：公开只读（s3:GetObject），便于前端直接渲染 md 中的图片 URL。
"""
import json
import threading

from minio import Minio

from app.engine.config.config import minio_config
from app.engine.tool.logger import logger

_minio_client = None
_lock = threading.Lock()


def _init_client() -> Minio:
    if not minio_config.endpoint:
        raise ValueError("MINIO_ENDPOINT 未配置：图片存储功能不可用")
    # minio-py 默认超时 5 分钟，端点不可达时导入任务近似挂死；
    # 用 urllib3 http_client 收紧超时（兼容各 minio-py 7.x 版本）：10s 连接 / 60s 读
    import urllib3
    http_client = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=10.0, read=60.0),
        retries=urllib3.Retry(total=2, backoff_factor=0.5),
    )
    client = Minio(
        endpoint=minio_config.endpoint,
        access_key=minio_config.access_key,
        secret_key=minio_config.secret_key,
        secure=False,
        http_client=http_client,
    )
    if not client.bucket_exists(minio_config.bucket_name):
        client.make_bucket(minio_config.bucket_name)
        policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{minio_config.bucket_name}/*"],
            }],
        }
        client.set_bucket_policy(minio_config.bucket_name, json.dumps(policy))
        logger.info("MinIO bucket 已创建并设置只读策略：%s", minio_config.bucket_name)
    return client


def get_minio_client() -> Minio:
    """懒加载：首次调用时连接（导入含图片的文档时才需要）"""
    global _minio_client
    if _minio_client is None:
        with _lock:
            if _minio_client is None:
                _minio_client = _init_client()
                logger.info("MinIO 已连接：%s", minio_config.endpoint)
    return _minio_client
