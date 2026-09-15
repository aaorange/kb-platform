# -*- coding: utf-8 -*-
"""四维权限鉴权引擎 — 项目最大亮点

输入：用户身份（部门名 + 角色名列表）+ 候选知识单元权限列表
输出：有权切片列表 + 被拦截切片列表

四维 OR 逻辑：满足任意一个 scope 即可访问
  global     → 所有人可见（scope_value 为 null）
  department → 用户部门名匹配 scope_value
  role       → 用户角色名列表包含 scope_value
  user       → 用户名匹配 scope_value
"""
from dataclasses import dataclass


@dataclass
class FilterResult:
    allowed: list  # 有权访问的切片
    blocked: list  # 被拦截的切片
    blocked_doc_ids: list[str]  # 被拦截的文档 ID（用于前端提示）


def check_permission(user_dept: str | None, user_roles: list[str], user_name: str,
                     permissions: list[dict]) -> bool:
    """检查单个知识单元的四维权限，任一满足即可"""
    if not permissions:
        return False  # 安全优先：无权限配置默认不可见

    for perm in permissions:
        scope_type = perm.get("scope_type")
        # 向量库（npz/Milvus）存的是 scope_name，DB 存的是 scope_value，两者都兼容
        scope_value = perm.get("scope_value") or perm.get("scope_name")

        if scope_type == "global":
            return True
        if scope_type == "department" and user_dept and scope_value == user_dept:
            return True
        if scope_type == "role" and scope_value in user_roles:
            return True
        if scope_type == "user" and scope_value == user_name:
            return True

    return False


def filter_chunks_by_permission(
    chunks: list[dict],
    user_dept: str | None,
    user_roles: list[str],
    user_name: str,
) -> FilterResult:
    """对检索召回的切片做权限过滤

    chunks: [{"chunk_id", "doc_id", "heading", "content", "permissions": [...]}]
    """
    allowed, blocked = [], []
    blocked_doc_ids = set()

    for chunk in chunks:
        perms = chunk.get("permissions", [])
        if check_permission(user_dept, user_roles, user_name, perms):
            allowed.append(chunk)
        else:
            blocked.append(chunk)
            blocked_doc_ids.add(chunk["doc_id"])

    return FilterResult(
        allowed=allowed,
        blocked=blocked,
        blocked_doc_ids=list(blocked_doc_ids),
    )
