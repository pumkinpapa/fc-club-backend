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
# ★ 신규: 시스템관리자 권한 + cascade 삭제 서비스
from app.services.match_service import delete_member_cascade

router = APIRouter(prefix="/api/members", tags=["회원관리"])


# 시스템관리자 전화번호 (matches.py와 동일하게 유지)
SYS_ADMIN_PHONE = "01000000001"


def get_system_admin_user(current_user: Member = Depends(get_current_user)) -> Member:
    """시스템관리자 권한 확인"""
    if current_user.phone != SYS_ADMIN_PHONE:
        raise HTTPException(status_code=403, detail="시스템관리자만 수행 가능합니다.")
    return current_user


# ──────────────────────────────────
# 회원 조회
# ──────────────────────────────────

@router.get("/", response_model=List[MemberResponse])
async def list_members(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
    status: str = Query("승인", description="회원 상태 필터"),
):
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
    members = db.query(Member).filter(Member.status == "대기").order_by(Member.join_date).all()
    return [MemberResponse.model_validate(m) for m in members]


@router.post("/{member_id}/approve")
async def approve_member(
    member_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")
    member.status = "승인"
    db.commit()
    db.refresh(member)
    return {"message": f"{member.name}님이 승인되었습니다."}


@router.post("/{member_id}/reject")
async def reject_member(
    member_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")
    member.status = "거절"
    db.commit()
    db.refresh(member)
    return {"message": f"{member.name}님이 거절되었습니다."}


@router.get("/{member_id}", response_model=MemberResponse)
async def get_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
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
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(member, key, value)
    db.commit()
    db.refresh(member)
    return MemberResponse.model_validate(member)


# ══════════════════════════════════════════════
# ★★★ 수정: 회원 삭제 - 시스템관리자 전용 + cascade ★★★
# ══════════════════════════════════════════════

@router.delete("/{member_id}")
async def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
    sys_admin: Member = Depends(get_system_admin_user),  # ★ 시스템관리자로 변경
):
    """
    회원 완전 삭제 (시스템관리자 전용)

    - 회원의 모든 MatchRecord(투표/팀/결과) 삭제
    - Member 레코드 삭제
    - 시스템관리자 자신은 삭제 불가
    - 삭제와 동시에 랭킹에서 제거됨 (실시간 집계)
    """
    try:
        name = delete_member_cascade(db, member_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": f"{name}님이 삭제되었습니다."}
