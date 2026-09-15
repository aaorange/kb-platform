# -*- coding: utf-8 -*-
"""认证 API：登录"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.core.deps import get_current_user
from app.models import User, Department
from app.schemas import LoginRequest, TokenResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).options(selectinload(User.roles), selectinload(User.department))
        .where(User.username == req.username)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")

    token = create_access_token(str(user.id), {"username": user.username})
    roles = [r.name for r in user.roles]
    dept_name = user.department.name if user.department else None
    return TokenResponse(
        access_token=token,
        user=UserInfo(
            id=user.id, username=user.username, display_name=user.display_name,
            dept_id=user.dept_id, dept_name=dept_name, roles=roles, is_admin=user.is_admin,
        ),
    )


@router.get("/me", response_model=UserInfo)
async def get_me(user: User = Depends(get_current_user)):
    roles = [r.name for r in user.roles]
    dept_name = user.department.name if user.department else None
    return UserInfo(
        id=user.id, username=user.username, display_name=user.display_name,
        dept_id=user.dept_id, dept_name=dept_name, roles=roles, is_admin=user.is_admin,
    )
