# -*- coding: utf-8 -*-
"""组织架构 API：部门/角色/用户 CRUD"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.deps import get_current_user, require_admin
from app.core.security import hash_password
from app.models import Department, Role, User, UserRole
from app.schemas import (
    DepartmentCreate, DepartmentOut, RoleCreate, RoleUpdate, RoleOut,
    UserCreate, UserUpdate, PasswordReset, UserOut, UserInfo,
)

router = APIRouter(prefix="/org", tags=["组织架构"])


# ===== Department =====
@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    result = await db.execute(select(Department).order_by(Department.id))
    return result.scalars().all()


@router.post("/departments", response_model=DepartmentOut)
async def create_department(req: DepartmentCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    dept = Department(name=req.name, parent_id=req.parent_id)
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    return dept


# ===== Role =====
@router.get("/roles", response_model=list[RoleOut])
async def list_roles(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    result = await db.execute(
        select(Role, func.count(UserRole.user_id).label("user_count"))
        .outerjoin(UserRole, UserRole.role_id == Role.id)
        .group_by(Role.id)
        .order_by(Role.id)
    )
    return [RoleOut(id=r.id, name=r.name, description=r.description, user_count=uc)
            for r, uc in result.all()]


@router.post("/roles", response_model=RoleOut)
async def create_role(req: RoleCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    role = Role(name=req.name, description=req.description)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return RoleOut(id=role.id, name=role.name, description=role.description, user_count=0)


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: int,
    req: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """编辑角色：名称/描述"""
    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(404, "角色不存在")
    if req.name is not None:
        existing = await db.execute(select(Role).where(Role.name == req.name, Role.id != role_id))
        if existing.scalar_one_or_none():
            raise HTTPException(400, "角色名称已存在")
        role.name = req.name
    if req.description is not None:
        role.description = req.description
    await db.commit()
    await db.refresh(role)
    count_result = await db.execute(
        select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id))
    user_count = count_result.scalar()
    return RoleOut(id=role.id, name=role.name, description=role.description, user_count=user_count)


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """删除角色：先清除用户关联，再删除角色记录"""
    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(404, "角色不存在")
    count_result = await db.execute(
        select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id))
    user_count = count_result.scalar()
    if user_count > 0:
        raise HTTPException(400, f"该角色下有 {user_count} 个用户，请先解除关联后再删除")
    await db.execute(delete(UserRole).where(UserRole.role_id == role_id))
    await db.delete(role)
    await db.commit()
    return {"message": f"已删除角色 {role.name}"}


# ===== User =====
@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    result = await db.execute(
        select(User).options(selectinload(User.roles), selectinload(User.department)).order_by(User.id)
    )
    users = result.scalars().all()
    out = []
    for u in users:
        out.append(UserOut(
            id=u.id, username=u.username, display_name=u.display_name,
            dept_id=u.dept_id, dept_name=u.department.name if u.department else None,
            roles=[r.name for r in u.roles], is_active=u.is_active, is_admin=u.is_admin,
        ))
    return out


@router.post("/users", response_model=UserOut)
async def create_user(req: UserCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_admin)):
    user = User(
        username=req.username,
        hashed_password=hash_password(req.password),
        display_name=req.display_name,
        dept_id=req.dept_id,
    )
    db.add(user)
    await db.flush()
    for rid in req.role_ids:
        db.add(UserRole(user_id=user.id, role_id=rid))
    await db.commit()
    await db.refresh(user)
    await db.refresh(user, attribute_names=["roles", "department"])
    return UserOut(
        id=user.id, username=user.username, display_name=user.display_name,
        dept_id=user.dept_id, dept_name=user.department.name if user.department else None,
        roles=[r.name for r in user.roles], is_active=user.is_active, is_admin=user.is_admin,
    )


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    req: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """编辑用户：姓名/部门/角色/启用状态/管理员标识"""
    result = await db.execute(
        select(User).options(selectinload(User.roles), selectinload(User.department))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "用户不存在")
    if user_id == _.id and req.is_admin is False:
        raise HTTPException(400, "不能取消自己的管理员权限")

    if req.display_name is not None:
        user.display_name = req.display_name
    if req.dept_id is not None:
        user.dept_id = req.dept_id
    if req.is_active is not None:
        if user_id == _.id and req.is_active is False:
            raise HTTPException(400, "不能停用自己")
        user.is_active = req.is_active
    if req.is_admin is not None:
        user.is_admin = req.is_admin

    if req.role_ids is not None:
        await db.execute(delete(UserRole).where(UserRole.user_id == user_id))
        for rid in req.role_ids:
            db.add(UserRole(user_id=user_id, role_id=rid))

    await db.commit()
    await db.refresh(user)
    await db.refresh(user, attribute_names=["roles", "department"])
    return UserOut(
        id=user.id, username=user.username, display_name=user.display_name,
        dept_id=user.dept_id, dept_name=user.department.name if user.department else None,
        roles=[r.name for r in user.roles], is_active=user.is_active, is_admin=user.is_admin,
    )


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    req: PasswordReset,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """管理员重置用户密码"""
    if len(req.new_password) < 6:
        raise HTTPException(400, "密码长度至少 6 位")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "用户不存在")
    user.hashed_password = hash_password(req.new_password)
    await db.commit()
    return {"message": f"已重置 {user.display_name} 的密码"}
