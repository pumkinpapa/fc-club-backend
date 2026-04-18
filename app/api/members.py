"""
회원 관리 API
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, get_admin_user
from app.models import Member
from app.schemas import MemberResponse, MemberUpdate

router = APIRouter(prefix="/api/members", tags=["회원관리"])


@router.get("/", response_model=List[MemberResponse])
async def list_members(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
    status: str = Query("승인", description="회원 상태 필터 (승인/대기/거절/전체)"),
):
    """회원 목록 조회 (상태별 필터 가능)"""
    query = db.query(Member).order_by(Member.join_date)
    if status != "전체":
        query = query.filter(Member.status == status)
    members = query.all()
    return [MemberResponse.model_validate(m) for m in members]


@router.get("/pending", response_model=List[MemberResponse])
async def list_pending_members(
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """승인 대기 중인 회원 목록 (관리자 전용)"""
    members = db.query(Member).filter(Member.status == "대기").order_by(Member.join_date).all()
    return [MemberResponse.model_validate(m) for m in members]


@router.post("/{member_id}/approve", response_model=MemberResponse)
async def approve_member(
    member_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """가입 승인 (관리자 전용)"""
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")
    if member.status == "승인":
        raise HTTPException(status_code=400, detail="이미 승인된 회원입니다.")

    member.status = "승인"
    db.commit()
    db.refresh(member)
    return MemberResponse.model_validate(member)


@router.post("/{member_id}/reject", response_model=MemberResponse)
async def reject_member(
    member_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """가입 거절 (관리자 전용)"""
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")

    member.status = "거절"
    db.commit()
    db.refresh(member)
    return MemberResponse.model_validate(member)


@router.get("/{member_id}", response_model=MemberResponse)
async def get_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """회원 상세 조회"""
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")
    return MemberResponse.model_validate(member)


@router.put("/{member_id}", response_model=MemberResponse)
async def update_member(
    member_id: int,
    update: MemberUpdate,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """회원 정보 수정 (관리자 전용)"""
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")

    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(member, key, value)

    db.commit()
    db.refresh(member)
    return MemberResponse.model_validate(member)


@router.delete("/{member_id}")
async def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """회원 삭제 (관리자 전용)"""
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")

    db.delete(member)
    db.commit()
    return {"message": f"{member.name}님이 삭제되었습니다."}
