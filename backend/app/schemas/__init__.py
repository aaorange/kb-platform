# -*- coding: utf-8 -*-
"""Pydantic schemas"""
from datetime import datetime
from pydantic import BaseModel


# ===== Auth =====
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    dept_id: int | None = None
    dept_name: str | None = None
    roles: list[str] = []
    is_admin: bool = False


# ===== Department =====
class DepartmentCreate(BaseModel):
    name: str
    parent_id: int | None = None


class DepartmentOut(BaseModel):
    id: int
    name: str
    parent_id: int | None = None
    created_at: datetime


# ===== Role =====
class RoleCreate(BaseModel):
    name: str
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RoleOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    user_count: int = 0


# ===== User =====
class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str
    dept_id: int | None = None
    role_ids: list[int] = []


class UserUpdate(BaseModel):
    display_name: str | None = None
    dept_id: int | None = None
    role_ids: list[int] | None = None
    is_active: bool | None = None
    is_admin: bool | None = None


class PasswordReset(BaseModel):
    new_password: str


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    dept_id: int | None = None
    dept_name: str | None = None
    roles: list[str] = []
    is_active: bool = True
    is_admin: bool = False


# ===== Knowledge =====
class PermissionConfig(BaseModel):
    scope_type: str  # global|department|role|user
    scope_value: str | None = None


class KnowledgeUnitOut(BaseModel):
    id: int
    doc_id: str
    title: str
    file_name: str
    category: str
    char_count: int
    is_enabled: bool
    permissions: list[PermissionConfig] = []
    created_at: datetime


class PermissionUpdate(BaseModel):
    permissions: list[PermissionConfig]


# ===== Chat =====
class ChatRequest(BaseModel):
    question: str
    session_id: int | None = None


class ChunkRef(BaseModel):
    chunk_id: str
    doc_id: str
    heading: str
    content_preview: str


class ChatStreamMeta(BaseModel):
    cited_chunks: list[ChunkRef] = []
    blocked_count: int = 0
    faq_hit: bool = False


# ===== FAQ =====
class FAQOut(BaseModel):
    id: int
    question: str
    answer: str
    hit_count: int
    is_published: bool
    created_at: datetime


class FAQCreate(BaseModel):
    question: str
    answer: str
    doc_ids: list[str] = []  # 回答依据的文档（缓存命中时权限复核用）


class FAQAutoGen(BaseModel):
    count: int = 5  # 从高频问题中取前 N 条生成


class FAQQuestion(BaseModel):
    question: str


# ===== 反馈 =====
class FeedbackRequest(BaseModel):
    value: int  # 1=赞 -1=踩 0=取消


# ===== Knowledge Gap =====
class GapOut(BaseModel):
    id: int
    question: str
    frequency: int
    status: str
    created_at: datetime


# ===== Dashboard =====
class DashboardStats(BaseModel):
    pv: int = 0
    uv: int = 0
    total_units: int = 0
    total_chunks: int = 0
    total_faq: int = 0
    total_gaps: int = 0
    top_questions: list[dict] = []
    top_cited: list[dict] = []
    token_total: int = 0
    avg_response_ms: int = 0
    feedback_positive: int = 0
    feedback_negative: int = 0


TokenResponse.model_rebuild()
