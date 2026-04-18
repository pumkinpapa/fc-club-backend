"""
인증 API

- 가입 신청 (관리자 승인 대기)
- 전화번호 로그인 (승인된 회원만)
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, get_current_user
from app.models import Member
from app.schemas import (
    PhoneLoginRequest, RegisterRequest,
    TokenResponse, MemberResponse,
)

router = APIRouter(prefix="/api/auth", tags=["인증"])


@router.post("/register")
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """
    가입 신청

    관리자가 승인하기 전까지 로그인 불가.
    """
    phone_clean = req.phone.replace("-", "")

    existing = db.query(Member).filter(Member.phone == phone_clean).first()
    if existing:
        if existing.status == "대기":
            raise HTTPException(status_code=409, detail="이미 가입 신청 중입니다. 관리자 승인을 기다려주세요.")
        else:
            raise HTTPException(status_code=409, detail="이미 등록된 전화번호입니다.")

    member = Member(
        name=req.name,
        birth=req.birth,
        phone=phone_clean,
        role="회원",
        status="대기",
        join_date=datetime.now(timezone.utc),
    )
    db.add(member)
    db.commit()
    db.refresh(member)

    return {
        "message": f"{req.name}님의 가입 신청이 완료되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
        "member": MemberResponse.model_validate(member),
    }


@router.post("/login", response_model=TokenResponse)
async def login_by_phone(req: PhoneLoginRequest, db: Session = Depends(get_db)):
    """전화번호로 로그인 (승인된 회원만)"""
    phone_clean = req.phone.replace("-", "")
    member = db.query(Member).filter(Member.phone == phone_clean).first()

    if not member:
        raise HTTPException(status_code=404, detail="등록되지 않은 번호입니다. 먼저 가입 신청을 해주세요.")

    if member.status == "대기":
        raise HTTPException(status_code=403, detail="가입 승인 대기 중입니다. 관리자에게 문의해주세요.")

    if member.status == "거절":
        raise HTTPException(status_code=403, detail="가입이 거절되었습니다. 관리자에게 문의해주세요.")

    jwt_token = create_access_token({"sub": str(member.id)})
    return TokenResponse(
        access_token=jwt_token,
        member=MemberResponse.model_validate(member),
    )


@router.get("/me", response_model=MemberResponse)
async def get_me(current_user: Member = Depends(get_current_user)):
    """현재 로그인 사용자 정보"""
    return MemberResponse.model_validate(current_user)
