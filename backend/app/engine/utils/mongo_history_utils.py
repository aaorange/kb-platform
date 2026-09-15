# -*- coding: utf-8 -*-
"""历史对话兼容层 — 替代原 MongoDB 版 mongo_history_utils

kb-platform 的会话历史保存在 SQLite（ChatSession/ChatLog），由 chat 端点统一落库。
引擎节点仍按原接口调用（get_recent_messages / save_chat_message / format_json），
本模块通过进程内上下文变量注入历史，实现「Mongo → SQLite」零改动切换：

- chat 服务在运行查询图前：set_recent_history([...]) 注入最近对话
- 引擎节点读历史：get_recent_history()
- save_chat_message / update_message_item_names：no-op（落库由 persist_log 负责）
"""
import json
import threading

from app.engine.tool.logger import logger

_tls = threading.local()


def set_recent_history(messages: list[dict] | None):
    """注入当前请求的历史对话（chat 服务调用）

    messages 元素结构：{"role": "user"|"assistant", "text": "..."}
    """
    _tls.history = messages or []


def get_recent_messages(session_id=None, limit: int = 10) -> list[dict]:
    """读取注入的历史对话（引擎节点调用）"""
    return getattr(_tls, "history", [])[-limit:]


def save_chat_message(session_id=None, role=None, text=None, **kwargs):
    """no-op：答案落库由 kb-platform 的 persist_log 统一处理"""
    return None


def update_message_item_names(message_ids=None, item_names=None):
    """no-op：实体名关联随 ChatLog 一起由 persist_log 落库"""
    return None


def format_json(obj, indent: int = 4) -> str:
    """调试输出格式化（与原实现一致）"""
    try:
        return json.dumps(obj, ensure_ascii=False, indent=indent, default=str)
    except Exception as e:  # noqa: BLE001
        logger.warning("format_json 失败：%s", e)
        return str(obj)
