# -*- coding: utf-8 -*-
"""API v1 路由聚合"""
from fastapi import APIRouter
from app.api.v1.endpoints import auth, org, knowledge, chat, ops

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(org.router)
api_router.include_router(knowledge.router)
api_router.include_router(chat.router)
api_router.include_router(ops.router)
