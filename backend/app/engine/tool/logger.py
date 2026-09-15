# -*- coding: utf-8 -*-
"""引擎统一 logger — 替代原 atguigu/tool/logger.py（colorlog 版），
直接复用标准 logging，输出到 backend 容器 stdout，格式保持可读。
"""
import logging

logger = logging.getLogger("kb.engine")

# 兜底：uvicorn 未配置该 logger 时保证有 handler（本地脚本运行场景）
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
