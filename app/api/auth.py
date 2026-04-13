"""
인증 API

- 카카오 로그인
- 전화번호 로그인 (SMS 인증)
- 회원가입
"""

import random
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, get_current_user
from app.models import Member
from app.schemas import (
    KakaoLoginRequest, PhoneLoginRequest, RegisterRequest,
    TokenResponse, MemberResponse,
)
from app.services.kakao_service import get_kakao_login_url, get_kakao_token, get_kakao_user_info

router = APIRouter(prefix="/api/auth", tags=["인증"])

# 인증번호 임시 저장 (프로덕션에서는 Redis 사용 권장)
_verify_codes: dict[str, str] = {}


@router.get("/kakao/login-url")
async def kakao_login_url():
    """카카오 로그인 URL 반환"""
    return {"login_url": get_kakao_login_url()}


@router.get("/kakao/callback")
async def kakao_callback(code: str, db: Session = Depends(get_db)):
    """카카오 로그인 콜백"""
    token_data = await get_kakao_token(code)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="카카오 토큰 발급 실패")

    user_info = await get_kakao_user_info(access_token)
    kakao_id = user_info.get("id")
    if not kakao_id:
        raise HTTPException(status_code=400, detail="카카오 사용자 정보 조회 실패")

    member = db.query(Member).filter(Member.kakao_id == kakao_id).first()

    if not member:
        phone = user_info.get("phone", "")
        if phone:
            member = db.query(Member).filter(Member.phone == phone).first()
            if member:
                member.kakao_id = kakao_id
                db.commit()

    if not member:
        member = Member(
            name=user_info.get("name", "새회원"),
            birth=user_info.get("birthday", ""),
            phone=user_info.get("phone", ""),
            kakao_id=kakao_id,
            role="회원",
            join_date=datetime.now(timezone.utc),
        )
        db.add(member)
        db.commit()
        db.refresh(member)

    jwt_token = create_access_token({"sub": str(member.id)})
    return TokenResponse(
        access_token=jwt_token,
        member=MemberResponse.model_validate(member),
    )


@router.post("/send-code")
async def send_verify_code(req: PhoneLoginRequest):
    """SMS 인증번호 발송"""
    # 고정 인증번호 사용 (솔라피 연동 후 아래 주석 해제)
    code = "1234"
    _verify_codes[req.phone.replace("-", "")] = code

    # ── 솔라피 연동 후 아래 주석 해제 ──
    # from app.services.solapi_service import send_sms
    # code = "".join(random.choices(string.digits, k=4))
    # _verify_codes[req.phone.replace("-", "")] = code
    # result = await send_sms(
    #     to=req.phone,
    #     text=f"[FC 동호회] 인증번호: {code} (3분 내 입력)",
    # )
    # return {"message": "인증번호가 발송되었습니다.", "result": result}

    return {"message": "인증번호는 1234 입니다.", "code": code}


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """회원가입"""
    phone_clean = req.phone.replace("-", "")

    stored_code = _verify_codes.get(phone_clean)
    if not stored_code or stored_code != req.verify_code:
        raise HTTPException(status_code=400, detail="인증번호가 올바르지 않습니다.")

    existing = db.query(Member).filter(Member.phone == phone_clean).first()
    if existing:
        raise HTTPException(status_code=409, detail="이미 등록된 전화번호입니다.")

    member = Member(
        name=req.name,
        birth=req.birth,
        phone=phone_clean,
        role="회원",
        join_date=datetime.now(timezone.utc),
    )
    db.add(member)
    db.commit()
    db.refresh(member)

    _verify_codes.pop(phone_clean, None)

    jwt_token = create_access_token({"sub": str(member.id)})
    return TokenResponse(
        access_token=jwt_token,
        member=MemberResponse.model_validate(member),
    )


@router.post("/login", response_model=TokenResponse)
async def login_by_phone(req: PhoneLoginRequest, db: Session = Depends(get_db)):
    """전화번호로 로그인 (기존 회원)"""
    phone_clean = req.phone.replace("-", "")
    member = db.query(Member).filter(Member.phone == phone_clean).first()
    if not member:
        raise HTTPException(status_code=404, detail="등록되지 않은 번호입니다.")

    jwt_token = create_access_token({"sub": str(member.id)})
    return TokenResponse(
        access_token=jwt_token,
        member=MemberResponse.model_validate(member),
    )


@router.get("/me", response_model=MemberResponse)
async def get_me(current_user: Member = Depends(get_current_user)):
    """현재 로그인 사용자 정보"""
    return MemberResponse.model_validate(current_user)